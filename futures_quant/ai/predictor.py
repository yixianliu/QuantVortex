"""AI 智能预测核心（期货价格趋势 / 涨跌概率 / 压力支撑 / 风险度）。

流程：
    1. 特征工程：对数收益、滚动波动、RSI/MACD/KDJ/BOLL%/CCI 等；
    2. 训练：纯 numpy LSTM 预测「下一根对数收益」；若数值异常自动回退岭回归；
    3. 多步滚动：以最近窗口递归外推未来 N 根收盘价路径，并给出 ±1σ 预测带；
    4. 研判：涨跌概率（正态近似）、压力/支撑位、风险度、多空性价比、行情状态。

诚实声明：
    - 多步预测第 1 步为模型真实输出；第 2 步起的特征（指标类）采用「上一已知值
      外推 + 收益/波动滚动更新」的近似，属业界标准的点预测做法，非未来函数；
    - 模型在历史数据上拟合，预测为概率性研判，不构成任何交易建议。
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from ..analysis.support_resistance import compute_levels
from ..analysis.signals import resonance, trend_score
from .lstm import LSTM
from .features import build_features
from .ensemble import MultiPeriodEnsemble, _Ridge


def _mincer_zarnowitz(pred: np.ndarray, actual: np.ndarray) -> tuple[float, float]:
    """Mincer-Zarnowitz 预测校准回归：actual = a + b * pred。

    返回 (beta, resid_std)。beta 是「预测值应被缩放多少」的最优系数：
      * beta ≈ 1  预测幅度恰当；
      * beta ≈ 0  预测与真实值无关（纯噪声）——此时应把预测收缩到 0；
      * beta < 0  预测方向系统性相反。

    这是治理「随机游走上也给出极端置信度」的关键：无技能的模型 beta 自动趋近 0，
    预测被收缩、残差变大，概率自然回归 0.5，而非靠人工阈值硬压。

    额外做**显著性收缩**：校准段通常只有几十个点，beta 本身估计噪声很大，
    纯噪声序列上也可能偶然算出 0.6+。按 t 统计量收缩
    ``beta ← beta · t²/(1+t²)``，使统计上不显著的 beta 自动塌向 0，
    显著时才接近原值。这等价于以 N(0, se²) 为先验的贝叶斯后验均值。
    """
    pred = np.asarray(pred, float)
    actual = np.asarray(actual, float)
    ok = np.isfinite(pred) & np.isfinite(actual)
    pred, actual = pred[ok], actual[ok]
    n = len(pred)
    if n < 8:
        return 0.0, float(np.std(actual) if n else 1e-4) + 1e-6
    sd_p = float(np.std(pred))
    if sd_p < 1e-12:                     # 预测恒定 -> 无信息
        return 0.0, float(np.std(actual)) + 1e-6
    beta = float(np.cov(pred, actual, ddof=0)[0, 1] / (sd_p ** 2))
    resid = actual - beta * pred
    sd_r = float(np.std(resid))
    # beta 的标准误： se = σ_resid / (√n · σ_pred)
    se = sd_r / (math.sqrt(n) * sd_p + 1e-12)
    t = beta / (se + 1e-12)
    beta *= (t * t) / (1.0 + t * t)      # 显著性收缩
    beta = max(0.0, min(1.5, beta))      # 负相关一律视作无技能，不做反向下注
    return beta, float(np.std(actual - beta * pred)) + 1e-6


class FuturesPredictor:
    """期货价格序列预测器。"""

    FEATURES = ["ret", "vol", "RSI14", "MACD", "K", "boll_pct", "CCI14"]

    # 多步外推的每步阻尼：步数越远，模型信息衰减越快（避免递归发散）
    STEP_DAMPING = 0.92

    def __init__(self) -> None:
        self.lstm: LSTM | None = None
        self._ridge: _Ridge | None = None
        self.use_lstm = True
        self.trained = False
        self.seq_len = 20
        self._feat_mean: np.ndarray | None = None
        self._feat_std: np.ndarray | None = None
        self.resid_std = 1e-4
        self.levels: list[dict] = []
        self.extended_features = False
        self.use_ensemble = False
        self.ensemble: MultiPeriodEnsemble | None = None
        self._feat_names: list = []
        # 验证集导出的校准系数与技能度（predict 时用于收缩预测幅度）
        self.calib_beta = 1.0
        self.skill = 0.0                 # 相对「恒预测 0」基线的 MAE 改善率
        self.validated = False           # resid_std 是否来自样本外
        self.best_alpha = 1.0            # 验证集选出的岭回归正则强度

    # ----------------------------- 特征 -----------------------------
    def _features(self, df: pd.DataFrame):
        ind, F, names = build_features(df, self.extended_features)
        self._feat_names = names
        return ind, F

    # ------------------------------------------------------------------
    def _build_sequences(self, arr: np.ndarray, y: np.ndarray, seq_len: int):
        """构造 (窗口, 标签) 对。

        窗口取 arr[t-seq_len+1 : t+1]（**含第 t 根**），标签取 y[t]=ret[t+1]，
        即「用截至 t 的信息预测 t+1」，与推理时 arr[-seq_len:] -> ret[n] 完全同构。
        旧实现窗口为 arr[t-seq_len:t]（不含 t），训练实为 h=2 而推理 h=1，
        训练目标与实际用法错位一根，是模型精度的隐性损耗。
        """
        Xs, Ys = [], []
        for t in range(seq_len - 1, len(arr) - 1):
            Xs.append(arr[t - seq_len + 1:t + 1])
            Ys.append(y[t])
        if not Xs:
            return np.empty((0, seq_len, arr.shape[1])), np.empty(0)
        return np.array(Xs), np.nan_to_num(np.array(Ys), nan=0.0,
                                           posinf=0.0, neginf=0.0)

    def _train_core(self, Xs: np.ndarray, Ys: np.ndarray, n_feat: int,
                    epochs: int, force_ridge: bool) -> None:
        """在已归一化的 (Xs, Ys) 上训练主模型，LSTM 失败回退岭回归。"""
        if force_ridge:
            self.use_lstm = False
            self.lstm = None
            self._ridge = _Ridge(alpha=self.best_alpha)
            self._ridge.fit(Xs.reshape(len(Xs), -1), Ys)
            return
        try:
            self.lstm = LSTM(input_size=n_feat, hidden_size=32, output_size=1, seed=7)
            self.lstm.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=epochs, lr=0.005)
            probe = self.lstm.predict_last(Xs[-1])
            if not math.isfinite(probe):
                raise ValueError("LSTM 输出非有限值")
            self.use_lstm = True
        except Exception:
            self.use_lstm = False
            self._ridge = _Ridge(alpha=self.best_alpha)
            self._ridge.fit(Xs.reshape(len(Xs), -1), Ys)

    def _batch_pred(self, Xs: np.ndarray) -> np.ndarray:
        if self.use_lstm and self.lstm is not None:
            return np.array([self.lstm.predict_last(Xs[i]) for i in range(len(Xs))])
        if self._ridge is not None:
            return np.array([self._ridge.predict(Xs[i].reshape(-1)) for i in range(len(Xs))])
        return np.zeros(len(Xs))

    # ----------------------------- 训练 -----------------------------
    def fit(self, df: pd.DataFrame, seq_len: int = 20, epochs: int = 30,
            force_ridge: bool = False, extended_features: bool = False,
            use_ensemble: bool = False) -> dict:
        """训练。采用「时序切分 -> 验证集校准 -> 全量重训」三段式：

        1. 前 80% 训练、后 20% 验证（带 embargo 隔离带，杜绝窗口跨界泄漏）；
        2. 在验证集上做 Mincer-Zarnowitz 回归，得到预测缩放系数 beta 与
           **样本外**残差标准差——旧实现用样本内残差，σ 被系统性低估，
           是「概率虚高」的直接原因；
        3. 用全量数据重训主模型（时序场景下最新数据信息量最大），
           但保留第 2 步得到的 beta 与 σ 作为不确定性度量。
        """
        self.extended_features = extended_features
        self.use_ensemble = use_ensemble
        ind, F = self._features(df)
        self.seq_len = seq_len
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)
        Xs, Ys = self._build_sequences(arr, y, seq_len)
        if len(Xs) < 20:
            self.trained = False
            return {"trained": False, "reason": "数据不足"}

        mean = Xs.reshape(-1, Xs.shape[-1]).mean(0)
        std = Xs.reshape(-1, Xs.shape[-1]).std(0) + 1e-8
        self._feat_mean, self._feat_std = mean, std
        Xn = (Xs - mean) / std
        n_feat = arr.shape[1]

        # ---- 阶段 1/2：三段时序切分（训练 / 选参 / 校准）----
        # 三段互不重叠且各带 embargo 隔离带。之所以必须把「选超参」与「估校准系数」
        # 分在两段不同数据上：若共用一段，alpha 是在该段上挑出来的最优值，
        # 再在同一段做 MZ 回归会产生选择偏差——实测纯随机游走上 beta 被抬到 0.80，
        # 等于把「碰巧拟合上的噪声」误判成技能。
        m = len(Xn)
        embargo = seq_len
        c1, c2 = int(m * 0.6), int(m * 0.8)
        self.calib_beta, self.skill, self.validated = 1.0, 0.0, False
        self.best_alpha = 1.0

        has_3way = (c1 >= 20 and (c2 - c1 - embargo) >= 8 and (m - c2 - embargo) >= 8)
        has_2way = (c2 >= 20 and (m - c2 - embargo) >= 8)

        def _seg(a, b=None):
            X = Xn[a:b] if b is not None else Xn[a:]
            Y = Ys[a:b] if b is not None else Ys[a:]
            return X, Y

        if has_3way or has_2way:
            if has_3way:
                tr_X, tr_Y = _seg(0, c1)
                va_X, va_Y = _seg(c1 + embargo, c2)
                ca_X, ca_Y = _seg(c2 + embargo)
            else:
                # 样本不足以三分：只做 训练/校准 两段，alpha 用稳健默认值不搜索，
                # 宁可略欠拟合，也不引入选择偏差。
                tr_X, tr_Y = _seg(0, c2)
                va_X, va_Y = None, None
                ca_X, ca_Y = _seg(c2 + embargo)

            # 归一化统计量只用训练段，避免统计泄漏
            tm = tr_X.reshape(-1, n_feat).mean(0)
            ts = tr_X.reshape(-1, n_feat).std(0) + 1e-8
            tr_n = (tr_X - tm) / ts
            ca_n = (ca_X - tm) / ts

            if va_X is not None:
                va_n = (va_X - tm) / ts
                picked = _Ridge.fit_with_cv(tr_n.reshape(len(tr_n), -1), tr_Y,
                                            va_n.reshape(len(va_n), -1), va_Y)
                self.best_alpha = picked.alpha

            self._train_core(tr_n, tr_Y, n_feat, epochs, force_ridge)
            cp = self._batch_pred(ca_n)                # 完全未参与训练与选参
            beta, resid = _mincer_zarnowitz(cp, ca_Y)
            mae_model = float(np.mean(np.abs(ca_Y - beta * cp)))
            mae_base = float(np.mean(np.abs(ca_Y))) + 1e-12
            self.calib_beta = beta
            self.skill = max(0.0, 1.0 - mae_model / mae_base)
            self.resid_std = resid
            self.validated = True

        # ---- 阶段 3：全量重训（保留验证集导出的 beta / σ）----
        self._train_core(Xn, Ys, n_feat, epochs, force_ridge)
        if not self.validated:
            # 数据不足以切分：退回样本内残差，但按经验因子放大以免过度自信
            preds = self._batch_pred(Xn)
            self.resid_std = float(np.std(Ys - preds)) * 1.5 + 1e-6
            self.calib_beta = 0.5           # 未经验证的预测一律先收缩一半

        if use_ensemble and len(df) >= seq_len + 30:
            try:
                self.ensemble = MultiPeriodEnsemble()
                self.ensemble.fit(df, seq_len, epochs)
            except Exception:
                self.ensemble = None
        else:
            self.ensemble = None

        self.trained = True
        self.levels = compute_levels(df)
        return {"trained": True, "use_lstm": self.use_lstm,
                "use_ensemble": self.ensemble is not None and self.ensemble.fitted,
                "resid_std": round(self.resid_std, 6),
                "calib_beta": round(self.calib_beta, 4),
                "skill": round(self.skill, 4),
                "validated": self.validated}

    def _pred_one(self, Xseq: np.ndarray) -> float:
        if self.use_lstm and self.lstm is not None:
            return float(self.lstm.predict_last(Xseq))
        if self._ridge is not None:
            return self._ridge.predict(Xseq.reshape(-1))
        return 0.0

    # 单步累计对数收益的安全上下界（±60%），防止 math.exp 溢出
    _CUM_CLIP = 0.6

    def _assemble(self, rets, last_close, horizon, resid_std):
        """由每日收益序列构造价格路径与 ±1σ 区间。

        对累计对数收益做裁剪：模型发散时 math.exp 会抛 OverflowError，
        这里统一夹在 ±60%（对期货已属极端），保证 UI 永不因数值爆炸崩溃。
        """
        curve = [last_close]; upper = [last_close]; lower = [last_close]
        cum = 0.0
        for h, r in enumerate(rets, 1):
            cum += (r if math.isfinite(r) else 0.0)
            cum = max(-self._CUM_CLIP, min(self._CUM_CLIP, cum))
            sigma = min(resid_std * math.sqrt(h), self._CUM_CLIP)
            curve.append(last_close * math.exp(cum))
            upper.append(last_close * math.exp(min(cum + sigma, self._CUM_CLIP)))
            lower.append(last_close * math.exp(max(cum - sigma, -self._CUM_CLIP)))
        return np.array(curve), np.array(upper), np.array(lower)

    def _roll_forward(self, arr: np.ndarray, horizon: int) -> list[float]:
        """递归多步外推（已修正归一化口径）。

        关键修复：特征矩阵 seq 处于 **z-score 空间**，而模型输出 r 是**原始**对数收益。
        旧实现直接 `new_row[0] = r`，等于把 0.005 量级的原始收益塞进标准差为 1 的
        槽位——相当于每步都把收益特征强行置 0，递归迅速收敛到固定点并持续同向累加，
        这正是「随机游走上也能给出 ±10% 预期收益」的元凶。
        现改为先把 r 映射回 z 空间再写入，波动槽同理在原始空间更新后再归一化。
        """
        mean, std = self._feat_mean, self._feat_std
        seq = (arr[-self.seq_len:] - mean) / std
        base_scaled = (arr[-1] - mean) / std
        n_feat = arr.shape[1]
        rets: list[float] = []
        for step in range(horizon):
            r = self._pred_one(seq)
            if not math.isfinite(r):
                r = 0.0
            # 验证集校准 + 步长阻尼：越远的步预测越收缩
            r_eff = r * self.calib_beta * (self.STEP_DAMPING ** step)
            rets.append(float(r_eff))

            new_row = base_scaled.copy()
            # 槽位 0 = ret：原始 -> z 空间
            new_row[0] = (r_eff - mean[0]) / std[0]
            if n_feat > 1:
                # 槽位 1 = vol：先还原到原始空间做 EMA 更新，再归一化写回
                vol_prev = seq[-1, 1] * std[1] + mean[1]
                vol_next = 0.9 * vol_prev + 0.1 * abs(r_eff)
                new_row[1] = (vol_next - mean[1]) / std[1]
            seq = np.vstack([seq[1:], new_row[None, :]])
        return rets

    def _predict_next(self, df_upto: pd.DataFrame, seq_len: int | None = None) -> float:
        """滚动样本外评估用：截至 df_upto 的窗口，预测下一根对数收益。"""
        seq_len = seq_len or self.seq_len
        ind, F = self._features(df_upto)
        arr = F.values.astype(float)
        if self._feat_mean is None or len(arr) < seq_len + 1:
            return 0.0
        last = (arr[-seq_len:] - self._feat_mean) / self._feat_std
        return self._pred_one(last) * self.calib_beta

    # ----------------------------- 预测 -----------------------------
    def predict(self, df: pd.DataFrame, horizon: int = 10,
               news_bias: float = 0.0, news_samples: list | None = None,
               calibrate_p_up: float | None = None) -> dict:
        """执行预测。

        news_bias：外部资讯情感偏置，范围 [-1,1]，由 news_feed 计算得到；
            非零时作为「综合分析」的辅助维度，温和修正涨跌概率与预期收益方向，
            但不替代模型主体（限制幅度，避免单一资讯过度主导）。
        news_samples：命中的资讯标题列表，仅用于结果展示与落库。
        calibrate_p_up：若提供（来自历史命中率校准），其可信度高于纯模型 p_up，
            在两者间取加权融合，使「置信度」更贴合该行情状态的历史表现。
        """
        if not self.trained:
            res = self.fit(df)
            if not res.get("trained"):
                # 数据不足以训练：返回结构完整的「中性」结果，而非继续执行导致
                # `arr - None` 崩溃（旧实现在 25 根数据下必抛 TypeError）
                return self._neutral_result(df, horizon, res.get("reason", "数据不足"))
        ind, F = self._features(df)
        arr = F.values.astype(float)
        if len(ind) == 0 or self._feat_mean is None or len(arr) < self.seq_len:
            return self._neutral_result(df, horizon, "有效样本不足")
        last_close = float(ind["close"].iloc[-1])
        if not math.isfinite(last_close) or last_close <= 0:
            return self._neutral_result(df, horizon, "收盘价异常")

        # 收益路径：集成模式直接用多周期集成的每日收益；否则递归外推
        if self.use_ensemble and self.ensemble and self.ensemble.fitted:
            rets = list(self.ensemble.predict_daily_returns(df, horizon))
            resid_std = self.ensemble.ensemble_resid
        else:
            rets = self._roll_forward(arr, horizon)
            resid_std = self.resid_std

        resid_std = max(float(resid_std), 1e-6)
        curve, upper, lower = self._assemble(rets, last_close, horizon, resid_std)
        mean_cum = float(np.sum(rets))
        if not math.isfinite(mean_cum):
            mean_cum = 0.0
        mean_cum = max(-self._CUM_CLIP, min(self._CUM_CLIP, mean_cum))
        sigma_h = resid_std * math.sqrt(max(horizon, 1))
        p_up = 0.5 * (1 + math.erf(mean_cum / (sigma_h * math.sqrt(2) + 1e-12)))

        # 外部资讯情感偏置：把 news_bias 经 sigmoid 转成概率偏置并温和融合
        # （限制幅度，单条资讯最多撬动约 ±12% 的涨跌概率）
        if news_bias:
            bias_p = 1.0 / (1.0 + math.exp(-news_bias * 1.5))
            p_up = 0.85 * p_up + 0.15 * bias_p
            # 同向温和修正累计预期收益
            mean_cum = mean_cum + 0.15 * news_bias * abs(mean_cum if mean_cum else 0.01)
        # 历史校准：若提供校准概率，与模型 p_up 融合（校准更可信）
        if calibrate_p_up is not None:
            p_up = 0.6 * float(calibrate_p_up) + 0.4 * p_up
        p_up = max(0.01, min(0.99, p_up))

        # 指标研判
        res = resonance(ind)
        tr = trend_score(ind)
        risk = self._risk_score(ind)
        ls = self._long_short(curve[-1], last_close, res["score"], risk["score"])

        return {
            "symbol": None,
            "last_close": round(last_close, 4),
            "horizon": horizon,
            "forecast": curve.tolist(),
            "upper": upper,
            "lower": lower,
            "rets": rets,
            "p_up": round(p_up, 4),
            "p_down": round(1 - p_up, 4),
            "expected_return_pct": round(mean_cum * 100, 3),
            "resonance": res,
            "trend": tr,
            "risk": risk,
            "long_short": ls,
            "levels": self.levels,
            "news_bias": round(float(news_bias), 3) if news_bias else 0.0,
            "news_samples": list(news_samples or []),
            "model": ("LSTM+集成" if (self.use_ensemble and self.ensemble
                                       and self.ensemble.fitted)
                      else ("LSTM" if self.use_lstm else "Ridge(回退)")),
            "regime": self._regime(ind, tr),
            # —— 模型可信度元信息（供 UI 透明展示，不参与计算）——
            "calib_beta": round(self.calib_beta, 4),
            "skill": round(self.skill, 4),
            "validated": self.validated,
            "resid_std": round(resid_std, 6),
            "degraded": False,
            "feature_importance": self._feature_importance(),
        }

    # ------------------------------------------------------------------
    def _neutral_result(self, df: pd.DataFrame, horizon: int, reason: str) -> dict:
        """样本不足 / 数值异常时的安全兜底：结构与正常结果完全一致的中性研判。

        这样上层 UI、落库、校准链路都无需做 None 判断，也不会把「不知道」
        误呈现为「有把握的看多/看空」。
        """
        try:
            last_close = float(df["close"].iloc[-1])
            if not math.isfinite(last_close) or last_close <= 0:
                last_close = 0.0
        except Exception:
            last_close = 0.0
        flat = [last_close] * (horizon + 1)
        return {
            "symbol": None,
            "last_close": round(last_close, 4),
            "horizon": horizon,
            "forecast": list(flat),
            "upper": np.array(flat),
            "lower": np.array(flat),
            "rets": [0.0] * horizon,
            "p_up": 0.5, "p_down": 0.5,
            "expected_return_pct": 0.0,
            "resonance": {"score": 0.0, "label": "数据不足", "details": []},
            "trend": {"score": 0.0, "state": "未知"},
            "risk": {"score": 0.0, "label": "未知", "atr_pct": 0.0},
            "long_short": {"long": 0.0, "short": 0.0, "recommend": "观望",
                           "expected_return_pct": 0.0},
            "levels": [], "news_bias": 0.0, "news_samples": [],
            "model": "不可用", "regime": "未知",
            "calib_beta": 0.0, "skill": 0.0, "validated": False,
            "resid_std": 0.0, "feature_importance": [],
            "degraded": True, "degrade_reason": reason,
        }

    # ----------------------------- 辅助研判 -----------------------------
    @staticmethod
    def _safe(x, default: float = 0.0) -> float:
        """把可能为 NaN / inf / None 的标量安全转成有限 float。"""
        try:
            v = float(x)
        except (TypeError, ValueError):
            return default
        return v if math.isfinite(v) else default

    def _risk_score(self, ind: pd.DataFrame) -> dict:
        last = ind.iloc[-1]
        close = self._safe(last["close"])
        atr = self._safe(ind["ATR"].iloc[-1]) if "ATR" in ind else 0.0
        atr_pct = (atr / close) if close > 0 else 0.0
        # 近期最大回撤（roll_max 可能为 0/NaN，需整体防护）
        roll_max = ind["close"].rolling(60, min_periods=1).max().replace(0, np.nan)
        dd_series = (ind["close"] - roll_max) / roll_max
        dd = self._safe(dd_series.replace([np.inf, -np.inf], np.nan).min())
        dd = abs(dd)
        adx = self._safe(last["ADX"]) if "ADX" in ind else 0.0
        # 距最近关键价位
        dist = 1.0
        if self.levels and close > 0:
            prices = [abs(self._safe(lv.get("price")) - close) / close
                      for lv in self.levels if lv.get("price") is not None]
            dist = min(prices) if prices else 1.0
        score = 100 * (0.4 * min(atr_pct / 0.03, 1) + 0.3 * min(dd / 0.1, 1)
                        + 0.15 * min(adx / 50, 1) + 0.15 * (1 - min(dist / 0.02, 1)))
        score = round(min(100.0, max(0.0, score)), 1)
        label = "低风险" if score < 33 else ("中等风险" if score < 66 else "高风险")
        return {"score": score, "label": label, "atr_pct": round(atr_pct * 100, 2)}

    def _long_short(self, forecast_price, last_close, res_score, risk_score) -> dict:
        last_close = self._safe(last_close)
        forecast_price = self._safe(forecast_price)
        exp = (forecast_price / last_close - 1) if last_close > 0 else 0.0
        exp = max(-self._CUM_CLIP, min(self._CUM_CLIP, exp))
        res_score = max(-500.0, min(500.0, self._safe(res_score)))
        p_up_like = 1 / (1 + math.exp(-res_score / 20))
        long_score = 100 * p_up_like * (1 - risk_score / 100) * (0.5 + min(abs(exp) * 20, 0.5))
        short_score = 100 * (1 - p_up_like) * (1 - risk_score / 100) * (0.5 + min(abs(exp) * 20, 0.5))
        rec = "偏多" if long_score > short_score else "偏空"
        if abs(long_score - short_score) < 8:
            rec = "观望"
        return {"long": round(long_score, 1), "short": round(short_score, 1),
                "recommend": rec, "expected_return_pct": round(exp * 100, 3)}

    def _feature_importance(self) -> list[dict]:
        """计算特征重要性（基于模型权重绝对值排序）。

        对于 LSTM：取输出层权重 |W_hy| 与隐藏层到输出的间接贡献；
        对于 Ridge：直接取 |w|。
        返回 [(feature_name, importance_score), ...] 按重要性降序。
        """
        if not self._feat_names:
            return []
        importances = []

        if self.use_lstm and self.lstm is not None:
            # LSTM: 用输出层权重近似重要性
            try:
                wy = np.abs(self.lstm.Why).flatten()  # (hid,)
                # 每个输入特征的权重 = 输出层权重 × 输入→隐藏的加权平均
                w_input = self.lstm.Wi + self.lstm.Wf + self.lstm.Wc + self.lstm.Wo
                feat_weights = np.abs(w_input).mean(axis=0)  # (input_size,)
                feat_importance = feat_weights * wy.mean()
            except Exception:
                feat_importance = np.ones(len(self._feat_names))
        elif self._ridge is not None and self._ridge.w is not None:
            feat_importance = np.abs(self._ridge.w)
        else:
            return []

        # 确保长度匹配
        n = len(self._feat_names)
        if len(feat_importance) != n:
            feat_importance = feat_importance[:n] if len(feat_importance) > n else np.pad(
                feat_importance, (0, n - len(feat_importance)), constant_values=1.0)

        # 归一化并排序
        total = feat_importance.sum()
        if total > 0:
            feat_importance = feat_importance / total
        else:
            feat_importance = np.ones(n) / n

        indices = np.argsort(feat_importance)[::-1]
        importances = [
            {"name": self._feat_names[i], "importance": round(float(feat_importance[i]), 4)}
            for i in indices[:min(10, n)]  # 只返回 Top 10
        ]
        return importances

    def _regime(self, ind: pd.DataFrame, tr: dict) -> str:
        last = ind.iloc[-1]
        adx = self._safe(last["ADX"]) if "ADX" in ind else 0.0
        # 布林带宽（BOLL_MID 可能为 0，需防除零）
        bw = 0.0
        if "BOLL_UP" in ind and "BOLL_LOW" in ind and "BOLL_MID" in ind:
            mid = self._safe(ind["BOLL_MID"].iloc[-1])
            if mid:
                bw = self._safe((self._safe(ind["BOLL_UP"].iloc[-1])
                                 - self._safe(ind["BOLL_LOW"].iloc[-1])) / mid)
        if adx > 25 and tr["state"] in ("多头趋势", "空头趋势"):
            return "趋势行情"
        if bw < 0.01:
            return "震荡收敛(变盘窗口)"
        return "震荡行情"
