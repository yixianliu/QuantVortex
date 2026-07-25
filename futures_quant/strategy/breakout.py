"""策略2：突破交易（唐奇安通道 + ATR 止损）。

    - 收盘价突破过去 N 根 K 线最高价 -> 开多；
    - 跌破过去 N 根 K 线最低价 -> 开空；
    - 持仓用 ATR 跟踪止损，反向通道突破也离场。
通道计算时排除当前 bar，避免用到「当前尚未收盘」的极值（防未来函数）。
"""
from __future__ import annotations

from ..core.indicators import atr_last, donchian_last
from ..core.types import Bar, Direction, Offset
from .base import StrategyBase


class Breakout(StrategyBase):
    name = "突破交易"
    default_params = {
        "period": 20,
        "atr_period": 14,
        "stop_mult": 2.0,
        "lots": 1,
    }

    def __init__(self, symbol, params=None):
        super().__init__(symbol, params)
        self._stop = None

    def _window_size(self) -> int:
        p = self.params
        return int(max(p["period"], p["atr_period"]) + 5)

    def on_bar(self, bar: Bar) -> None:
        self._push(bar)
        p = self.params
        if len(self._closes) < p["period"] + 1:
            return

        # 唐奇安通道自动排除当前 bar（防未来函数）
        u, l = donchian_last(self._highs, self._lows, p["period"])
        a = atr_last(self._highs, self._lows, self._closes, p["atr_period"])
        long_qty, short_qty = self.position()

        if long_qty > 0:
            self._stop = max(self._stop, bar.close - p["stop_mult"] * a)
            if bar.close < self._stop or bar.close < l:
                self.send_order(Direction.SHORT, Offset.CLOSE, long_qty)
            return
        if short_qty > 0:
            self._stop = min(self._stop, bar.close + p["stop_mult"] * a)
            if bar.close > self._stop or bar.close > u:
                self.send_order(Direction.LONG, Offset.CLOSE, short_qty)
            return

        if bar.close > u:
            self._stop = bar.close - p["stop_mult"] * a
            self.send_order(Direction.LONG, Offset.OPEN, p["lots"])
        elif bar.close < l:
            self._stop = bar.close + p["stop_mult"] * a
            self.send_order(Direction.SHORT, Offset.OPEN, p["lots"])
