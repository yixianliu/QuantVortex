"""GARCH(1,1) 波动率择时策略（M4.4 第三子项）。

核心思想：条件波动率（用 EWMA/GARCH 递推估计，离线可算、无外部依赖）高于
阈值分位 → 市场处于高波动期，应**降低杠杆/保守**（做空波动率）；低于分位
→ 低波动期，正常持仓（做多波动率）。与 HV 分位策略方向一致（高波动→保守）。

实现说明（离线优先护栏）：
- 条件方差递推：sigma2_t = omega + alpha * r_t^2 + beta * sigma2_{t-1}
  取 (alpha, beta) = (0.05, 0.95) 接近 EWMA，无 torch/arch 也能算。
- 用「过去 vol_window 根条件波动率的分位」判断当前波动率高低。
- 信号：高波动分位 → SHORT（保守）；低波动分位 → LONG（正常）。

防未来函数：所有计算只用 bar.close 及之前数据（StrategyBase._push 缓冲）。
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset


class GARCHTiming(StrategyBase):
    """GARCH(1,1) 波动率择时：高条件波动率保守（做空），低波动率正常（做多）。"""

    name = "garch_timing"
    default_params: dict = {
        "omega": 1e-6,      # GARCH 常数项
        "alpha": 0.05,     # ARCH 项（接近 EWMA）
        "beta": 0.95,      # GARCH 项
        "vol_window": 20,  # 条件波动率历史窗口（分位基准）
        "percentile_window": 100,  # 分位统计窗口
        "high_threshold": 80.0,    # 高于此分位 → 高波动 → 保守（SHORT）
        "low_threshold": 20.0,     # 低于此分位 → 低波动 → 正常（LONG）
    }

    def __init__(self, symbol: str, params: Optional[dict] = None) -> None:
        super().__init__(symbol, params)
        self.omega = self.params.get("omega", 1e-6)
        self.alpha = self.params.get("alpha", 0.05)
        self.beta = self.params.get("beta", 0.95)
        self.vol_window = int(self.params.get("vol_window", 20))
        self.percentile_window = int(self.params.get("percentile_window", 100))
        self.high_threshold = float(self.params.get("high_threshold", 80.0))
        self.low_threshold = float(self.params.get("low_threshold", 20.0))
        # 条件方差递推状态 + 滚动波动率序列
        self._sigma2: float = 0.0
        self._cond_vol_series: List[float] = []

    def _window_size(self) -> int:
        # 需要 vol_window 根算条件波动率 + percentile_window 根算分位
        return self.vol_window + self.percentile_window + 5

    def _update_cond_vol(self, ret: float) -> float:
        """EWMA/GARCH 条件方差递推，返回当前条件波动率。"""
        self._sigma2 = self.omega + self.alpha * (ret ** 2) + self.beta * self._sigma2
        return float(np.sqrt(self._sigma2))

    def on_bar(self, bar: Bar) -> None:
        self._push(bar)
        closes = pd.Series(self._closes)
        if len(closes) < self.vol_window + 1:
            return
        log_ret = float(np.log(closes.iloc[-1] / closes.iloc[-1 - 1]))
        cv = self._update_cond_vol(log_ret)
        self._cond_vol_series.append(cv)
        if len(self._cond_vol_series) > self.percentile_window:
            self._cond_vol_series.pop(0)
        if len(self._cond_vol_series) < self.percentile_window:
            return
        s = pd.Series(self._cond_vol_series)
        percentile = float((s <= cv).mean() * 100.0)
        # 高波动 → 保守（做空波动率）；低波动 → 正常（做多波动率）
        if percentile > self.high_threshold:
            self.send_order(Direction.SHORT, Offset.OPEN, 1)
        elif percentile < self.low_threshold:
            self.send_order(Direction.LONG, Offset.OPEN, 1)
