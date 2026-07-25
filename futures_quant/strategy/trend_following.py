"""策略1：趋势跟踪（双均线 + ATR 跟踪止损）。

适配期货 T+0、双向、保证金：
    - 快线上穿慢线开多，下穿开空；
    - 持仓期间用 ATR 倍数做跟踪止损；
    - 反向信号也平仓反手。
信号仅在当前 bar 收盘后产生，下一根 bar 开盘撮合（无未来函数）。
"""
from __future__ import annotations

from ..core.indicators import atr_last, sma_last
from ..core.types import Bar, Direction, Offset
from .base import StrategyBase


class TrendFollowing(StrategyBase):
    name = "趋势跟踪"
    default_params = {
        "fast": 10,
        "slow": 30,
        "atr_period": 14,
        "stop_mult": 2.0,
        "lots": 1,
    }

    def __init__(self, symbol, params=None):
        super().__init__(symbol, params)
        self._stop = None
        self._side = 0  # 1 多 / -1 空 / 0 空仓

    def _window_size(self) -> int:
        p = self.params
        return int(max(p["fast"], p["slow"], p["atr_period"]) + 5)

    def on_bar(self, bar: Bar) -> None:
        self._push(bar)
        p = self.params
        if len(self._closes) < p["slow"] + 1:
            return

        # 直接计算当前 bar 指标值（基于有限窗口的纯列表计算，O(window)）
        fast = sma_last(self._closes, p["fast"])
        slow = sma_last(self._closes, p["slow"])
        a = atr_last(self._highs, self._lows, self._closes, p["atr_period"])
        long_qty, short_qty = self.position()

        if long_qty > 0:
            self._stop = max(self._stop, bar.close - p["stop_mult"] * a)
            if bar.close < self._stop or fast < slow:
                self.send_order(Direction.SHORT, Offset.CLOSE, long_qty)
                self._side = 0
            return
        if short_qty > 0:
            self._stop = min(self._stop, bar.close + p["stop_mult"] * a)
            if bar.close > self._stop or fast > slow:
                self.send_order(Direction.LONG, Offset.CLOSE, short_qty)
                self._side = 0
            return

        if fast > slow:
            self._stop = bar.close - p["stop_mult"] * a
            self._side = 1
            self.send_order(Direction.LONG, Offset.OPEN, p["lots"])
        elif fast < slow:
            self._stop = bar.close + p["stop_mult"] * a
            self._side = -1
            self.send_order(Direction.SHORT, Offset.OPEN, p["lots"])
