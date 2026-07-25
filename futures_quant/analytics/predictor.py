"""市场预测分析模块（analytics）。

包含：
    - predictor.Predictor：基于历史 K 线的趋势分析与统计外推预测。

重要声明：
    本模块所有「预测」均为**统计模型外推**，使用历史价格的特征（趋势斜率、
    波动率、均线排列等）给出情景区间与方向概率，绝非确定性预测，更不构成
    任何投资建议。实盘决策须结合自身判断与风险管理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass
class PredictionResult:
    """预测结果。所有字段均为模型输出，非投资建议。"""

    direction: str                       # 看涨 / 看跌 / 震荡
    confidence: float                    # 模型置信度（0~1，启发式）
    trend_strength: float                # 趋势强度（-1~1）
    last_price: float
    target_price: float                  # 期末预测价
    support: float                       # 近期支撑
    resistance: float                    # 近期阻力
    forecast: List[float]               # 逐期预测中枢
    upper: List[float]                   # 上沿（情景区间）
    lower: List[float]                   # 下沿（情景区间）
    dates: List[str]                     # 预测期标签
    metrics: dict = field(default_factory=dict)
    summary: str = ""


class Predictor:
    """趋势分析 + 统计外推预测器。

    方法：对回看窗口内的对数收盘价做线性回归得到每期漂移率（slope），
    结合均线排列、RSI、ATR、波动率给出趋势强度与方向；预测路径按漂移率外推，
    置信带随步数 √i 放大（随机游走式情景区间）。
    """

    def __init__(self, fast: int = 10, slow: int = 30,
                 rsi_period: int = 14, atr_period: int = 14,
                 band_mult: float = 1.96) -> None:
        self.fast = fast
        self.slow = slow
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.band_mult = band_mult

    # ---------- 工具 ----------
    @staticmethod
    def _sma(seq: Sequence[float], period: int) -> float:
        s = list(seq)
        if len(s) < period:
            return float("nan")
        return sum(s[-period:]) / period

    @staticmethod
    def _rsi(closes: Sequence[float], period: int) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]
        g = sum(gains[-period:]) / period
        ls = sum(losses[-period:]) / period
        if ls == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / ls
        return 100.0 - 100.0 / (1.0 + rs)

    @staticmethod
    def _atr(highs: Sequence[float], lows: Sequence[float],
             closes: Sequence[float], period: int) -> float:
        h, l, c = list(highs), list(lows), list(closes)
        if len(c) < period + 1:
            return float("nan")
        trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
               for i in range(1, len(c))]
        if len(trs) < period:
            return float("nan")
        return sum(trs[-period:]) / period

    # ---------- 主入口 ----------
    def predict(self, closes: Sequence[float], highs: Sequence[float],
                lows: Sequence[float], datetimes: Optional[Sequence] = None,
                horizon: int = 20, lookback: int = 120,
                freq: str = "1min") -> PredictionResult:
        import numpy as np

        closes = list(map(float, closes))
        highs = list(map(float, highs))
        lows = list(map(float, lows))
        n = len(closes)
        if n < 3:
            raise ValueError("历史数据不足，无法进行预测（至少需要 3 根 K 线）")

        lb = min(lookback, n)
        win = np.array(closes[-lb:])
        wh = highs[-lb:]
        wl = lows[-lb:]

        # 对数收盘线性回归
        x = np.arange(len(win), dtype=float)
        y = np.log(win)
        slope, intercept = np.polyfit(x, y, 1)
        yhat = intercept + slope * x
        ss_res = float(np.sum((y - yhat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

        # 指标
        ma_fast = self._sma(win, self.fast)
        ma_slow = self._sma(win, self.slow)
        rsi = self._rsi(win, self.rsi_period)
        atr = self._atr(wh, wl, win, self.atr_period)
        rets = np.diff(np.log(win))
        sigma = float(np.std(rets)) if len(rets) > 1 else 0.0

        # 趋势强度：漂移 + 均线排列（归一化到 -1~1）
        eps = 1e-9
        ts = 0.5 * float(np.tanh(slope * 500.0))
        if atr and atr == atr:  # not nan
            ts += 0.5 * float(np.tanh((ma_fast - ma_slow) / (atr + eps)))
        ts = max(-1.0, min(1.0, ts))

        if ts > 0.15:
            direction = "看涨"
        elif ts < -0.15:
            direction = "看跌"
        else:
            direction = "震荡"

        # 预测路径（漂移外推）
        base = float(win[-1])
        drift = slope
        forecast: List[float] = []
        upper: List[float] = []
        lower: List[float] = []
        for i in range(1, horizon + 1):
            fc = base * float(np.exp(drift * i))
            k = self.band_mult * sigma * (i ** 0.5)
            forecast.append(fc)
            upper.append(fc * float(np.exp(k)))
            lower.append(max(fc * float(np.exp(-k)), 1e-6))

        # 日期标签
        dates: List[str] = []
        if datetimes is not None and len(datetimes) >= 1:
            try:
                import pandas as pd
                last = pd.Timestamp(datetimes[-1])
                idx = pd.date_range(last, periods=horizon + 1, freq=freq)[1:]
                dates = [str(d) for d in idx]
            except Exception:
                dates = [f"T+{i}" for i in range(1, horizon + 1)]
        else:
            dates = [f"T+{i}" for i in range(1, horizon + 1)]

        support = float(min(wl))
        resistance = float(max(wh))
        target = forecast[-1] if forecast else base
        confidence = max(0.0, min(1.0, 0.35 + 0.4 * max(r2, 0.0) + 0.25 * abs(ts)))

        metrics = {
            "ma_fast": round(ma_fast, 2),
            "ma_slow": round(ma_slow, 2),
            "ma_alignment": "多头排列" if ma_fast > ma_slow else ("空头排列" if ma_fast < ma_slow else "缠绕"),
            "rsi": round(rsi, 1),
            "atr": round(atr, 2) if atr == atr else None,
            "volatility_pct": round(sigma * 100, 3),
            "slope_pct_per_bar": round(drift * 100, 4),
            "r_squared": round(r2, 3),
        }

        summary = self._build_summary(direction, ts, target, base, support, resistance, metrics)
        return PredictionResult(
            direction=direction, confidence=confidence, trend_strength=ts,
            last_price=base, target_price=target, support=support, resistance=resistance,
            forecast=forecast, upper=upper, lower=lower, dates=dates,
            metrics=metrics, summary=summary,
        )

    @staticmethod
    def _build_summary(direction, ts, target, base, support, resistance, m) -> str:
        chg = (target / base - 1) * 100 if base else 0.0
        lines = [
            f"方向研判：{direction}（趋势强度 {ts:+.2f}）",
            f"期末预测价：{target:,.2f}（较当前 {chg:+.2f}%）",
            f"近期支撑：{support:,.2f}　近期阻力：{resistance:,.2f}",
            f"均线：{m['ma_alignment']}（快 {m['ma_fast']} / 慢 {m['ma_slow']}）",
            f"RSI：{m['rsi']}　ATR：{m['atr']}　波动率：{m['volatility_pct']}%",
            f"回归拟合优度 R²：{m['r_squared']}",
            "⚠️ 以上为统计模型外推的情景区间，非确定性预测，不构成投资建议。",
        ]
        return "\n".join(lines)
