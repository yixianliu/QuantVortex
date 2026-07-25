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
from .ensemble import MultiPeriodEnsemble


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


class FuturesPredictor:
    """期货价格序列预测器。"""

    FEATURES = ["ret", "vol", "RSI14", "MACD", "K", "boll_pct", "CCI14"]

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

    # ----------------------------- 特征 -----------------------------
    def _features(self, df: pd.DataFrame):
        ind, F, names = build_features(df, self.extended_features)
        self._feat_names = names
        return ind, F

    # ----------------------------- 训练 -----------------------------
    def fit(self, df: pd.DataFrame, seq_len: int = 20, epochs: int = 30,
            force_ridge: bool = False, extended_features: bool = False,
            use_ensemble: bool = False) -> dict:
        self.extended_features = extended_features
        self.use_ensemble = use_ensemble
        ind, F = self._features(df)
        self.seq_len = seq_len
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)
        Xs, Ys = [], []
        for t in range(seq_len, len(arr) - 1):
            Xs.append(arr[t - seq_len:t])
            Ys.append(y[t])
        if len(Xs) < 20:
            return {"trained": False, "reason": "数据不足"}
        Xs = np.array(Xs)
        Ys = np.nan_to_num(np.array(Ys), 0.0)
        mean = Xs.reshape(-1, Xs.shape[-1]).mean(0)
        std = Xs.reshape(-1, Xs.shape[-1]).std(0) + 1e-8
        self._feat_mean, self._feat_std = mean, std
        Xs = (Xs - mean) / std

        if force_ridge:
            self.use_lstm = False
            self._ridge = _Ridge()
            self._ridge.fit(Xs.reshape(len(Xs), -1), Ys)
        else:
            try:
                self.lstm = LSTM(input_size=arr.shape[1], hidden_size=16, output_size=1, seed=7)
                self.lstm.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=epochs, lr=0.01)
                probe = self.lstm.predict_last(Xs[-1])
                if not math.isfinite(probe):
                    raise ValueError("LSTM 输出非有限值")
                self.use_lstm = True
            except Exception:
                self.use_lstm = False
                self._ridge = _Ridge()
                self._ridge.fit(Xs.reshape(len(Xs), -1), Ys)

        # 训练集残差标准差（用于预测带）
        if self.use_lstm:
            preds = np.array([self.lstm.predict_last(Xs[i]) for i in range(len(Xs))])
        else:
            preds = np.array([self._ridge.predict(Xs[i].reshape(-1)) for i in range(len(Xs))])
        self.resid_std = float(np.std(Ys - preds)) + 1e-6

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
                "resid_std": round(self.resid_std, 6)}

    def _pred_one(self, Xseq: np.ndarray) -> float:
        if self.use_lstm and self.lstm is not None:
            return float(self.lstm.predict_last(Xseq))
        if self._ridge is not None:
            return self._ridge.predict(Xseq.reshape(-1))
        return 0.0

    def _assemble(self, rets, last_close, horizon, resid_std):
        """由每日收益序列构造价格路径与 ±1σ 区间。"""
        curve = [last_close]; upper = [last_close]; lower = [last_close]
        cum = 0.0
        for h, r in enumerate(rets, 1):
            cum += r
            price = last_close * math.exp(cum)
            sigma = resid_std * math.sqrt(h)
            curve.append(price)
            upper.append(last_close * math.exp(cum + sigma))
            lower.append(last_close * math.exp(cum - sigma))
        return np.array(curve), np.array(upper), np.array(lower)

    def _predict_next(self, df_upto: pd.DataFrame, seq_len: int | None = None) -> float:
        """滚动样本外评估用：截至 df_upto 的窗口，预测下一根对数收益。"""
        seq_len = seq_len or self.seq_len
        ind, F = self._features(df_upto)
        arr = F.values.astype(float)
        if self._feat_mean is None or len(arr) < seq_len + 1:
            return 0.0
        last = (arr[-seq_len:] - self._feat_mean) / self._feat_std
        return self._pred_one(last)

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
            self.fit(df)
        ind, F = self._features(df)
        arr = F.values.astype(float)
        last_close = float(ind["close"].iloc[-1])

        # 收益路径：集成模式直接用多周期集成的每日收益；否则原递归外推
        if self.use_ensemble and self.ensemble and self.ensemble.fitted:
            rets = list(self.ensemble.predict_daily_returns(df, horizon))
            resid_std = self.ensemble.ensemble_resid
        else:
            seq = (arr[-self.seq_len:] - self._feat_mean) / self._feat_std
            base_scaled = (arr[-1] - self._feat_mean) / self._feat_std
            rets = []
            for _ in range(1, horizon + 1):
                r = self._pred_one(seq)
                rets.append(r)
                new_row = base_scaled.copy()
                new_row[0] = r
                new_row[1] = 0.9 * seq[-1, 1] + 0.1 * abs(r)
                seq = np.vstack([seq[1:], new_row[None, :]])
            resid_std = self.resid_std

        curve, upper, lower = self._assemble(rets, last_close, horizon, resid_std)
        mean_cum = float(np.sum(rets))
        sigma_h = resid_std * math.sqrt(horizon)
        p_up = 0.5 * (1 + math.erf(mean_cum / (sigma_h * math.sqrt(2) + 1e-12))) if sigma_h > 0 else (1.0 if mean_cum > 0 else 0.0)

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
        }

    # ----------------------------- 辅助研判 -----------------------------
    def _risk_score(self, ind: pd.DataFrame) -> dict:
        last = ind.iloc[-1]
        close = float(last["close"])
        atr = float(ind["ATR"].iloc[-1]) if "ATR" in ind else 0.0
        atr_pct = (atr / close) if close else 0.0
        # 近期最大回撤
        roll_max = ind["close"].rolling(60, min_periods=1).max()
        dd = ((ind["close"] - roll_max) / roll_max).min()
        dd = abs(float(dd)) if math.isfinite(dd) else 0.0
        adx = float(last["ADX"]) if "ADX" in ind else 0.0
        # 距最近关键价位
        dist = 1.0
        if self.levels:
            prices = [abs(lv["price"] - close) / close for lv in self.levels]
            dist = min(prices) if prices else 1.0
        score = 100 * (0.4 * min(atr_pct / 0.03, 1) + 0.3 * min(dd / 0.1, 1)
                        + 0.15 * min(adx / 50, 1) + 0.15 * (1 - min(dist / 0.02, 1)))
        score = round(min(100.0, max(0.0, score)), 1)
        label = "低风险" if score < 33 else ("中等风险" if score < 66 else "高风险")
        return {"score": score, "label": label, "atr_pct": round(atr_pct * 100, 2)}

    def _long_short(self, forecast_price, last_close, res_score, risk_score) -> dict:
        exp = (forecast_price / last_close - 1)
        p_up_like = 1 / (1 + math.exp(-res_score / 20))
        long_score = 100 * p_up_like * (1 - risk_score / 100) * (0.5 + min(abs(exp) * 20, 0.5))
        short_score = 100 * (1 - p_up_like) * (1 - risk_score / 100) * (0.5 + min(abs(exp) * 20, 0.5))
        rec = "偏多" if long_score > short_score else "偏空"
        if abs(long_score - short_score) < 8:
            rec = "观望"
        return {"long": round(long_score, 1), "short": round(short_score, 1),
                "recommend": rec, "expected_return_pct": round(exp * 100, 3)}

    def _regime(self, ind: pd.DataFrame, tr: dict) -> str:
        last = ind.iloc[-1]
        adx = float(last["ADX"]) if "ADX" in ind else 0.0
        # 布林带宽
        if "BOLL_UP" in ind and "BOLL_LOW" in ind and "BOLL_MID" in ind:
            bw = float((ind["BOLL_UP"].iloc[-1] - ind["BOLL_LOW"].iloc[-1]) / ind["BOLL_MID"].iloc[-1])
        else:
            bw = 0.0
        if adx > 25 and tr["state"] in ("多头趋势", "空头趋势"):
            return "趋势行情"
        if bw < 0.01:
            return "震荡收敛(变盘窗口)"
        return "震荡行情"
