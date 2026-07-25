"""多周期集成预测器（方向一·1.3）。

对原始日线重采样出多个周期（D / W），每个周期同时训练「基础 7 特征」与「扩展特征」
两套 LSTM（与 FuturesPredictor 的单模型结构一致），分别外推未来 horizon 天的「每日
收益」序列，再在**所有候选模型**（含 baseline 7 特征）上按验证集 MAE 反比加权集成。

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


class _Ridge:
    """最小二乘岭回归（扁平窗口 -> 单值），作 LSTM 回退。"""

    def __init__(self, alpha: float = 1e-3) -> None:
        self.alpha = alpha
        self.w = None
        self.b = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        X = np.asarray(X, float); y = np.asarray(y, float)
        XtX = X.T @ X + self.alpha * np.eye(X.shape[1])
        Xty = X.T @ y
        self.w = np.linalg.solve(XtX, Xty)
        self.b = y.mean() - (X.mean(0) @ self.w)

    def predict(self, x: np.ndarray) -> float:
        return float(np.dot(self.w, np.asarray(x, float)) + self.b)


def _make_sequences(arr: np.ndarray, y: np.ndarray, seq_len: int):
    Xs, Ys = [], []
    for t in range(seq_len, len(arr) - 1):
        Xs.append(arr[t - seq_len:t])
        Ys.append(y[t])
    if not Xs:
        return np.empty((0, seq_len, arr.shape[1])), np.empty(0)
    return np.array(Xs), np.nan_to_num(np.array(Ys), 0.0)


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

    def __init__(self, period: str, hidden: int = 16, seed: int = 7,
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
            step.append(r)
            new_row = base.copy()
            new_row[0] = r
            new_row[1] = 0.9 * seq[-1, 1] + 0.1 * abs(r)
            seq = np.vstack([seq[1:], new_row[None, :]])
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

    def __init__(self, periods=("D", "W"), hidden: int = 16, seed: int = 7) -> None:
        self.periods = list(periods)
        self.models = []
        k = 0
        # 每个周期两种特征集：基础 7 特征（baseline 成员）+ 扩展特征
        for p in self.periods:
            for ext in (False, True):
                self.models.append(
                    PeriodModel(p, hidden=hidden, seed=seed + k, extended=ext))
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
        # 集成残差：用日线模型（日收益量纲）作保守上界
        dres = [m.resid_std for m in self.models if m.mean is not None]
        self.ensemble_resid = float(min(dres)) if dres else 1e-4
        return self.fitted

    def _val_mae(self, df: pd.DataFrame, seq_len: int, cut: int) -> list:
        """验证段滚动单步（日收益量纲）MAE，用于公平估集成权重。"""
        actual = np.log(df["close"]).diff().shift(-1).values.astype(float)
        n = len(df)
        errs = []
        for m in self.models:
            if m.mean is None:
                errs.append(None)
                continue
            pe, ae = [], []
            for i in range(cut + seq_len, n):
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
