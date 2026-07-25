"""策略4：均值回归（布林带反转）。

    - 价格触及下轨 -> 认为超卖，开多；
    - 价格触及上轨 -> 认为超买，开空；
    - 价格回归中轨 -> 平仓离场。
适合震荡（range）行情；趋势行情中效果不佳，需配合风控与品种筛选。
"""
from __future__ import annotations

from ..core.indicators import bollinger_last
from ..core.types import Bar, Direction, Offset
from .base import StrategyBase


class MeanReversion(StrategyBase):
    name = "均值回归"
    default_params = {
        "period": 20,
        "num_std": 2.0,
        "lots": 1,
    }

    def _window_size(self) -> int:
        return int(self.params["period"] + 5)

    def on_bar(self, bar: Bar) -> None:
        self._push(bar)
        p = self.params
        if len(self._closes) < p["period"] + 1:
            return

        m, u, l = bollinger_last(self._closes, p["period"], p["num_std"])
        long_qty, short_qty = self.position()

        if long_qty > 0:
            if bar.close > m:
                self.send_order(Direction.SHORT, Offset.CLOSE, long_qty)
            return
        if short_qty > 0:
            if bar.close < m:
                self.send_order(Direction.LONG, Offset.CLOSE, short_qty)
            return

        if bar.close < l:
            self.send_order(Direction.LONG, Offset.OPEN, p["lots"])
        elif bar.close > u:
            self.send_order(Direction.SHORT, Offset.OPEN, p["lots"])
