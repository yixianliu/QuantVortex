"""轻量统计外推预测器（API 参考实现的本地降级路径）。

本文件原为核心包 `futures_quant.analytics`，在项目瘦身时迁出：主程序统一使用
`futures_quant.ai.predictor.FuturesPredictor`（LSTM / 岭回归），此处保留一份
零依赖（仅 numpy）的轻量实现，供 `futures_ai_predict.py` 在**云端 AI 不可用**
时降级出图，同时作为对接方理解输入 / 输出契约的最小样例。

与主线预测器的差异：
    - 主线 FuturesPredictor：接收 DataFrame，走特征工程 + 神经网络，重、准；
    - 本文件 Predictor：接收裸列表，走对数线性回归外推，轻、快、结果可解释。

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
    """一次预测的完整输出。所有字段均为模型计算结果，非投资建议。"""

    direction: str                       # 方向研判：看涨 / 看跌 / 震荡
    confidence: float                    # 置信度（0~1，由 R² 与趋势强度启发式合成）
    trend_strength: float                # 趋势强度（-1~1，负为空头、正为多头）
    last_price: float                    # 最后一根已知 K 线的收盘价
    target_price: float                  # 预测期末的价格中枢
    support: float                       # 回看窗口内的最低价（近期支撑）
    resistance: float                    # 回看窗口内的最高价（近期阻力）
    forecast: List[float]                # 逐期预测中枢，长度 == horizon
    upper: List[float]                   # 情景区间上沿，与 forecast 等长
    lower: List[float]                   # 情景区间下沿，与 forecast 等长
    dates: List[str]                     # 预测期时间标签，与 forecast 等长
    metrics: dict = field(default_factory=dict)  # 指标快照（均线/RSI/ATR/R² 等）
    summary: str = ""                    # 可直接展示给用户的中文摘要


class Predictor:
    """趋势分析 + 统计外推预测器。

    算法流程：
        1. 取回看窗口内的收盘价，对其**对数序列**做一元线性回归，斜率即每根
           K 线的平均漂移率（几何收益率），R² 衡量趋势的「干净程度」；
        2. 叠加均线排列（快线 - 慢线，用 ATR 归一化）得到趋势强度 ts ∈ [-1, 1]；
        3. 按漂移率做几何外推得到预测中枢，置信带宽度随步数 √i 放大
           （随机游走假设下的标准差累积规律）。
    """

    def __init__(self, fast: int = 10, slow: int = 30,
                 rsi_period: int = 14, atr_period: int = 14,
                 band_mult: float = 1.96) -> None:
        """初始化预测器参数。

        参数：
            fast:       快速均线周期，用于判断短期方向。
            slow:       慢速均线周期，与快线之差反映趋势排列。
            rsi_period: RSI 计算周期，衡量超买超卖。
            atr_period: ATR 计算周期，用于归一化均线差值。
            band_mult:  置信带倍数，1.96 对应正态分布约 95% 覆盖率。
        """
        self.fast = fast
        self.slow = slow
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.band_mult = band_mult

    # ---------- 内部指标工具（均只取最后一个值，避免整段计算的开销）----------
    @staticmethod
    def _sma(seq: Sequence[float], period: int) -> float:
        """简单移动平均的最后值；样本不足返回 NaN。"""
        s = list(seq)
        if len(s) < period:
            return float("nan")
        return sum(s[-period:]) / period

    @staticmethod
    def _rsi(closes: Sequence[float], period: int) -> float:
        """相对强弱指标 RSI 的最后值；样本不足返回中性值 50。"""
        if len(closes) < period + 1:
            return 50.0
        # 逐根差分后拆成涨幅序列与跌幅序列，各自取周期均值
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]
        g = sum(gains[-period:]) / period
        ls = sum(losses[-period:]) / period
        if ls == 0:  # 无下跌：单边上涨记 100，全平记中性 50
            return 100.0 if g > 0 else 50.0
        rs = g / ls
        return 100.0 - 100.0 / (1.0 + rs)

    @staticmethod
    def _atr(highs: Sequence[float], lows: Sequence[float],
             closes: Sequence[float], period: int) -> float:
        """真实波幅 ATR 的最后值；样本不足返回 NaN。

        真实波幅 TR = max(当根振幅, |最高价 - 昨收|, |最低价 - 昨收|)，
        后两项用于捕捉跳空缺口带来的实际波动。
        """
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
        """基于历史 K 线做趋势研判与多步外推。

        参数：
            closes:    收盘价序列（按时间升序），至少 3 个元素。
            highs:     最高价序列，长度需与 closes 一致。
            lows:      最低价序列，长度需与 closes 一致。
            datetimes: 时间戳序列，仅用于生成预测期标签；为 None 时退化为 T+1…T+N。
            horizon:   向前预测的 K 线根数。
            lookback:  回看窗口长度，超过实际长度时自动截断。
            freq:      生成时间标签所用的 pandas 频率别名（如 "1min" / "D"）。

        返回：
            PredictionResult，包含方向、置信度、预测路径与情景区间。

        异常：
            ValueError: 历史数据少于 3 根 K 线时抛出。
        """
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

        # 步骤 1：对数收盘价线性回归。取对数是为了让斜率含义变成「每根的复合
        # 收益率」，从而可以用 exp(slope * i) 做几何外推而非线性外推。
        x = np.arange(len(win), dtype=float)
        y = np.log(win)
        slope, intercept = np.polyfit(x, y, 1)
        yhat = intercept + slope * x
        ss_res = float(np.sum((y - yhat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

        # 步骤 2：指标快照
        ma_fast = self._sma(win, self.fast)
        ma_slow = self._sma(win, self.slow)
        rsi = self._rsi(win, self.rsi_period)
        atr = self._atr(wh, wl, win, self.atr_period)
        rets = np.diff(np.log(win))
        sigma = float(np.std(rets)) if len(rets) > 1 else 0.0

        # 步骤 3：趋势强度 = 漂移项 + 均线排列项，各占一半，tanh 压缩到 ±1。
        # 均线差用 ATR 归一化，使不同价格量级的品种可横向比较。
        eps = 1e-9
        ts = 0.5 * float(np.tanh(slope * 500.0))
        if atr and atr == atr:  # atr == atr 用于排除 NaN
            ts += 0.5 * float(np.tanh((ma_fast - ma_slow) / (atr + eps)))
        ts = max(-1.0, min(1.0, ts))

        # ±0.15 为方向判定的死区，避免在无趋势行情里频繁翻多翻空
        if ts > 0.15:
            direction = "看涨"
        elif ts < -0.15:
            direction = "看跌"
        else:
            direction = "震荡"

        # 步骤 4：几何漂移外推 + √i 放大的置信带
        base = float(win[-1])
        drift = slope
        forecast: List[float] = []
        upper: List[float] = []
        lower: List[float] = []
        for i in range(1, horizon + 1):
            fc = base * float(np.exp(drift * i))
            # 随机游走下，i 步后的对数价格标准差为 sigma * √i
            k = self.band_mult * sigma * (i ** 0.5)
            forecast.append(fc)
            upper.append(fc * float(np.exp(k)))
            lower.append(max(fc * float(np.exp(-k)), 1e-6))

        # 步骤 5：生成预测期的时间标签；pandas 不可用或时间列异常时退化为 T+i
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
        # 置信度构成：0.35 基线 + 拟合优度贡献 0.4 + 趋势强度贡献 0.25
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
        """把研判结果拼成多行中文摘要，末行固定附风险提示。"""
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
