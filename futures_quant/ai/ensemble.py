"""多周期集成预测器（方向一·1.3）。

对原始日线重采样出多个周期（D / W），每个周期同时训练「基础 7 特征」与「扩展特征」
两套 LSTM（与 FuturesPredictor 的单模型结构一致），并补充一个 **sklearn 梯度提升树**
基学习器（非线性视角），分别外推未来 horizon 天的「每日收益」序列，再在**所有候选模型**
（含 baseline 7 特征、扩展特征、树模型）上按验证集 MAE 反比加权集成。

这样设计的好处：当某个数据实现下扩展/低频特征是噪声时，baseline 成员靠验证权重
自动占主导，整体不会比 baseline 差；当扩展/低频特征有真实信息时又提供增益——
即一个稳健的 meta-ensemble，避免单纯叠加特征导致的退化。

本模块只负责「多周期 -> 集成每日收益」；涨跌概率 / 风险 / 多空 / 行情状态等研判
仍由 FuturesPredictor 复用既有权重完成。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .lstm import LSTM
from .features import build_features

try:
    from sklearn.ensemble import GradientBoostingRegressor
    _HAVE_GBM = True
except Exception:  # pragma: no cover - sklearn 缺失时优雅降级
    _HAVE_GBM = False


class _Ridge:
    """最小二乘岭回归（扁平窗口 -> 单值），作 LSTM 回退。"""

    ALPHA_GRID = (1e-3, 1e-2, 0.1, 1.0, 10.0, 100.0, 1000.0)

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self.w = None
        self.b = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        X = np.asarray(X, float); y = np.asarray(y, float)
        XtX = X.T @ X + self.alpha * np.eye(X.shape[1])
        Xty = X.T @ y
        try:
            self.w = np.linalg.solve(XtX, Xty)
        except np.linalg.LinAlgError:
            self.w = np.linalg.pinv(XtX) @ Xty
        self.b = y.mean() - (X.mean(0) @ self.w)

    def predict(self, x: np.ndarray) -> float:
        if self.w is None:
            return 0.0
        return float(np.dot(self.w, np.asarray(x, float)) + self.b)

    @classmethod
    def fit_with_cv(cls, Xtr: np.ndarray, ytr: np.ndarray,
                    Xva: np.ndarray, yva: np.ndarray) -> "_Ridge":
        """在验证集上按 MAE 选择最优 alpha，返回已训练模型。"""
        best, best_err = None, float("inf")
        for a in cls.ALPHA_GRID:
            m = cls(alpha=a)
            try:
                m.fit(Xtr, ytr)
                pv = np.array([m.predict(x) for x in Xva])
                err = float(np.mean(np.abs(yva - pv)))
            except Exception:
                continue
            if np.isfinite(err) and err < best_err:
                best, best_err = m, err
        return best if best is not None else cls(alpha=1.0)


class _TreeModel:
    """sklearn 梯度提升树基学习器（扁平窗口 -> 单值）。

    作为集成中的**非线性视角**：LSTM/Ridge 是序列模型，擅长时序依赖但易欠拟合
    特征间的复杂非线性交互；GBM 树对特征交互的捕获能力强，提供互补信号。
    仅作用于预测侧，不影响回测 fitness；通过现有反方差权重自动获得合理占比。
    """

    def __init__(self, period: str, seed: int = 7, extended: bool = True) -> None:
        self.period = period
        self.seed = seed
        self.extended = extended
        self.gbm = None
        self.mean = None          # 标记是否已训练（与 PeriodModel 接口一致）
        self.resid_std = 1e-4
        self.seq_len = 20

    def fit(self, df: pd.DataFrame, seq_len: int = 20, epochs: int = 25) -> bool:
        if not _HAVE_GBM:
            return False
        self.seq_len = seq_len
        rdf = _resample(df, self.period)
        if len(rdf) < seq_len + 5:
            return False
        ind, F, _ = build_features(rdf, extended=self.extended)
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)
        seqs, Ys = _make_sequences(arr, y, seq_len)   # 与 LSTM 成员同口径
        if len(seqs) < 20:
            return False
        Xs = seqs.reshape(len(seqs), -1)              # 扁平窗口
        try:
            self.gbm = GradientBoostingRegressor(
                n_estimators=100, max_depth=3, learning_rate=0.06,
                subsample=0.9, random_state=self.seed)
            # 时序切分：后 20% 留作样本外残差估计，避免样本内残差低估不确定性
            cut = int(len(Xs) * 0.8)
            if cut >= 20 and len(Xs) - cut >= 8:
                self.gbm.fit(Xs[:cut], Ys[:cut])
                oos = self.gbm.predict(Xs[cut:])
                self.resid_std = float(np.std(Ys[cut:] - oos)) + 1e-6
                self.gbm.fit(Xs, Ys)                  # 保留样本外 σ，全量重训
            else:
                self.gbm.fit(Xs, Ys)
                preds = self.gbm.predict(Xs)
                self.resid_std = float(np.std(Ys - preds)) * 1.5 + 1e-6
            self.mean = np.zeros(1)   # 标记已训练
            return True
        except Exception:
            self.gbm = None
            return False

    def _window(self, df_upto: pd.DataFrame, seq_len: int):
        rdf = _resample(df_upto, self.period)
        ind, F, _ = build_features(rdf, extended=self.extended)
        arr = F.values.astype(float)
        if len(arr) < seq_len + 1 or self.gbm is None:
            return None
        return arr[-seq_len:]   # (seq_len, n_feat)

    def predict_next(self, df_upto: pd.DataFrame, seq_len: int) -> float:
        x = self._window(df_upto, seq_len)
        if x is None:
            return 0.0
        r = float(self.gbm.predict(x.reshape(1, -1))[0])
        if self.period in ("W", "1W", "week"):
            r = r / 5.0
        return r

    def _daily_returns(self, df: pd.DataFrame, horizon: int) -> np.ndarray:
        x0 = self._window(df, self.seq_len)
        if x0 is None:
            return np.zeros(horizon)
        n_feat = x0.shape[1]
        base = x0[-1].copy()
        step = []
        for _ in range(1, horizon + 1):
            r = float(self.gbm.predict(x0.reshape(1, -1))[0])
            r = r if math.isfinite(r) else 0.0
            step.append(r)
            # 树模型工作在原始特征空间，直接写入（mean/std 传 None）
            x0 = _roll_step(x0, base, r, None, None)
        if self.period in ("W", "1W", "week"):
            daily = []
            for r in step:
                daily.extend([r / 5.0] * 5)
            step = daily[:horizon]
        out = np.array(step[:horizon], dtype=float)
        if len(out) < horizon:
            out = np.concatenate([out, np.zeros(horizon - len(out))])
        return out


def _make_sequences(arr: np.ndarray, y: np.ndarray, seq_len: int):
    """窗口含第 t 根，标签为 y[t]=ret[t+1]，与推理 arr[-seq_len:] 口径一致。

    （旧实现窗口为 arr[t-seq_len:t] 不含 t，训练 h=2 / 推理 h=1 错位一根。）
    """
    Xs, Ys = [], []
    for t in range(seq_len - 1, len(arr) - 1):
        Xs.append(arr[t - seq_len + 1:t + 1])
        Ys.append(y[t])
    if not Xs:
        return np.empty((0, seq_len, arr.shape[1])), np.empty(0)
    return np.array(Xs), np.nan_to_num(np.array(Ys), nan=0.0,
                                       posinf=0.0, neginf=0.0)


def _roll_step(seq: np.ndarray, base: np.ndarray, r: float,
               mean: np.ndarray | None, std: np.ndarray | None) -> np.ndarray:
    """递归外推推进一格。

    mean/std 非空表示 seq 处于 z-score 空间，需把原始收益 r 映射回 z 空间再写入；
    为 None 表示 seq 就是原始空间（树模型），直接写入。
    """
    new_row = base.copy()
    if mean is not None and std is not None:
        new_row[0] = (r - mean[0]) / std[0]
        if len(new_row) > 1:
            vol_prev = seq[-1, 1] * std[1] + mean[1]
            new_row[1] = (0.9 * vol_prev + 0.1 * abs(r) - mean[1]) / std[1]
    else:
        new_row[0] = r
        if len(new_row) > 1:
            new_row[1] = 0.9 * seq[-1, 1] + 0.1 * abs(r)
    return np.vstack([seq[1:], new_row[None, :]])


def _resample(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """把日线聚合到目标周期。D 原样返回；W 周线聚合（自动补日期索引）。"""
    if period in ("D", "1D", "day"):
        return df
    rule = {"W": "W", "1W": "W", "week": "W"}.get(period, period)
    rdf = df
    if not isinstance(df.index, pd.DatetimeIndex):
        rdf = df.copy()
        rdf.index = pd.date_range("2020-01-01", periods=len(df), freq="D")
    o = rdf["open"].resample(rule).first()
    h = rdf["high"].resample(rule).max()
    l = rdf["low"].resample(rule).min()
    c = rdf["close"].resample(rule).last()
    v = rdf["volume"].resample(rule).sum()
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()


class PeriodModel:
    """单周期模型（D 或 W），可训练基础 7 特征或扩展特征。"""

    def __init__(self, period: str, hidden: int = 32, seed: int = 7,
                 extended: bool = True) -> None:
        self.period = period
        self.hidden = hidden
        self.seed = seed
        self.extended = extended
        self.lstm = None
        self.ridge = None
        self.use_lstm = True
        self.mean = None
        self.std = None
        self.resid_std = 1e-4
        self.seq_len = 20

    def fit(self, df: pd.DataFrame, seq_len: int = 20, epochs: int = 25) -> bool:
        self.seq_len = seq_len
        rdf = _resample(df, self.period)
        if len(rdf) < seq_len + 5:
            return False
        ind, F, _ = build_features(rdf, extended=self.extended)
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)
        Xs, Ys = _make_sequences(arr, y, seq_len)
        if len(Xs) < 20:
            return False
        mean = Xs.reshape(-1, Xs.shape[-1]).mean(0)
        std = Xs.reshape(-1, Xs.shape[-1]).std(0) + 1e-8
        self.mean, self.std = mean, std
        Xs = (Xs - mean) / std
        try:
            self.lstm = LSTM(arr.shape[1], hidden_size=self.hidden, output_size=1, seed=self.seed)
            self.lstm.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=epochs, lr=0.01)
            probe = self.lstm.predict_last(Xs[-1])
            if not math.isfinite(probe):
                raise ValueError("LSTM 输出非有限值")
            self.use_lstm = True
        except Exception:
            self.use_lstm = False
            self.ridge = _Ridge()
            self.ridge.fit(Xs.reshape(len(Xs), -1), Ys)
        if self.use_lstm:
            preds = np.array([self.lstm.predict_last(Xs[i]) for i in range(len(Xs))])
        else:
            preds = np.array([self.ridge.predict(Xs[i].reshape(-1)) for i in range(len(Xs))])
        self.resid_std = float(np.std(Ys - preds)) + 1e-6
        return True

    def _pred(self, Xseq: np.ndarray) -> float:
        if self.use_lstm and self.lstm is not None:
            return float(self.lstm.predict_last(Xseq))
        if self.ridge is not None:
            return self.ridge.predict(Xseq.reshape(-1))
        return 0.0

    def _daily_returns(self, df: pd.DataFrame, horizon: int) -> np.ndarray:
        """该周期视角下未来 horizon 天的每日收益向量。"""
        rdf = _resample(df, self.period)
        ind, F, _ = build_features(rdf, extended=self.extended)
        arr = F.values.astype(float)
        if len(arr) < self.seq_len + 1:
            return np.zeros(horizon)
        last = (arr[-self.seq_len:] - self.mean) / self.std
        base = (arr[-1] - self.mean) / self.std
        seq = last.copy()
        step = []
        for _ in range(1, horizon + 1):
            r = self._pred(seq)
            r = float(r) if math.isfinite(r) else 0.0
            step.append(r)
            seq = _roll_step(seq, base, r, self.mean, self.std)
        # 周线：把每"周"收益均匀摊到 5 个交易日
        if self.period in ("W", "1W", "week"):
            daily = []
            for r in step:
                daily.extend([r / 5.0] * 5)
            step = daily[:horizon]
        out = np.array(step[:horizon], dtype=float)
        if len(out) < horizon:
            out = np.concatenate([out, np.zeros(horizon - len(out))])
        return out

    def predict_next(self, df_upto: pd.DataFrame, seq_len: int) -> float:
        """单步（下一根）收益预测，用于滚动样本外评估。"""
        rdf = _resample(df_upto, self.period)
        ind, F, _ = build_features(rdf, extended=self.extended)
        arr = F.values.astype(float)
        if len(arr) < seq_len + 1 or self.mean is None:
            return 0.0
        last = (arr[-seq_len:] - self.mean) / self.std
        r = self._pred(last)
        # 周线折算为单日收益
        if self.period in ("W", "1W", "week"):
            r = r / 5.0
        return float(r)


class MultiPeriodEnsemble:
    """稳健多周期集成：每个周期同时训练基础 7 特征与扩展特征两套模型。

    所有候选模型（含 baseline 7 特征）按验证集 MAE 反比加权集成，使得扩展/低频
    特征是噪声时 baseline 自动占主导，整体不会劣于 baseline。
    """

    def __init__(self, periods=("D", "W"), hidden: int = 32, seed: int = 7) -> None:
        self.periods = list(periods)
        self.models = []
        k = 0
        # 每个周期两种特征集：基础 7 特征（baseline 成员）+ 扩展特征
        for p in self.periods:
            for ext in (False, True):
                self.models.append(
                    PeriodModel(p, hidden=hidden, seed=seed + k, extended=ext))
                k += 1
        # 树模型基学习器（非线性视角）：每个周期各加一个扩展特征树成员
        if _HAVE_GBM:
            for p in self.periods:
                self.models.append(_TreeModel(p, seed=seed + 100 + k, extended=True))
                k += 1
        self.fitted = False
        self.ensemble_resid = 1e-4

    def fit(self, df: pd.DataFrame, seq_len: int = 20, epochs: int = 25) -> bool:
        n = len(df)
        cut = int(n * 0.8)
        # 数据充足时严格分离：前 80% 训练，后 20% 验证估权重（避免统计泄露）
        if cut < seq_len + 5:
            ok = [m.fit(df, seq_len, epochs) for m in self.models]
            self.fitted = any(m.mean is not None for m in self.models)
            k = max(1, sum(1 for m in self.models if m.mean is not None))
            self.weights = [1.0 / k] * len(self.models)
        else:
            train = df.iloc[:cut]
            ok = [m.fit(train, seq_len, epochs) for m in self.models]
            self.fitted = any(m.mean is not None for m in self.models)
            vmae = self._val_mae(df, seq_len, cut)
            w = []
            for e in vmae:
                w.append(0.0 if (e is None or not np.isfinite(e)) else 1.0 / (e + 1e-3))
            s = sum(w)
            self.weights = [x / s for x in w] if s > 0 else [1.0 / len(self.models)] * len(self.models)
        # 集成残差：按集成权重加权平均。
        # 旧实现取 min()（注释自称「保守上界」，实为**最乐观**估计），
        # 会系统性低估不确定性 -> 涨跌概率虚高。加权平均才与集成输出同口径。
        pairs = [(m.resid_std, w) for m, w in zip(self.models, self.weights)
                 if m.mean is not None and w > 0 and np.isfinite(m.resid_std)]
        if pairs:
            tw = sum(w for _, w in pairs)
            self.ensemble_resid = (float(sum(r * w for r, w in pairs) / tw)
                                   if tw > 0 else float(np.median([r for r, _ in pairs])))
        else:
            self.ensemble_resid = 1e-4
        return self.fitted

    def _val_mae(self, df: pd.DataFrame, seq_len: int, cut: int) -> list:
        """验证段滚动单步（日收益量纲）MAE，用于公平估集成权重。"""
        actual = np.log(df["close"]).diff().shift(-1).values.astype(float)
        n = len(df)
        # 抽样评估（最多 ~120 点），兼顾权重估计稳定性与 fit 速度
        span = max(1, n - (cut + seq_len))
        stride = max(1, span // 120)
        errs = []
        for m in self.models:
            if m.mean is None:
                errs.append(None)
                continue
            pe, ae = [], []
            for i in range(cut + seq_len, n, stride):
                pr = m.predict_next(df.iloc[:i], seq_len)
                ac = actual[i - 1]
                if np.isfinite(pr) and np.isfinite(ac):
                    pe.append(pr)
                    ae.append(ac)
            errs.append(float(np.mean(np.abs(np.array(pe) - np.array(ae)))) if pe else None)
        return errs

    def predict_daily_returns(self, df: pd.DataFrame, horizon: int) -> np.ndarray:
        rets, weights = [], []
        for m, w in zip(self.models, self.weights):
            if m.mean is None or w <= 0:
                continue
            try:
                dr = m._daily_returns(df, horizon)
                weights.append(w)
                rets.append(dr)
            except Exception:
                continue
        if not rets:
            return np.zeros(horizon)
        W = np.array(weights)
        W = W / W.sum()
        out = np.zeros(horizon)
        for dr, w in zip(rets, W):
            out += w * dr
        return out

    def predict_next(self, df_upto: pd.DataFrame, seq_len: int) -> float:
        rets, weights = [], []
        for m, w in zip(self.models, self.weights):
            if m.mean is None or w <= 0:
                continue
            try:
                r = m.predict_next(df_upto, seq_len)
                weights.append(w)
                rets.append(r)
            except Exception:
                continue
        if not rets:
            return 0.0
        W = np.array(weights)
        W = W / W.sum()
        return float(np.sum(W * np.array(rets)))
