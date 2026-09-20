"""Bollinger Bands 波动率交易策略。

M4.4 波动率交易：Bollinger 带内做空/带外做多。
"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset
import pandas as pd

class BollingerBands(StrategyBase):
    def __init__(self, symbol: str, params=None):
        super().__init__(symbol, params)
        self.window = self.params.get("window", 20) if self.params else 20
        self.window_dev = self.params.get("window_dev", 2.0) if self.params else 2.0

    def _window_size(self) -> int:
        return self.window + 5

    def on_bar(self, bar: Bar):
        self._push(bar)
        closes = pd.Series(self._closes)
        if len(closes) < self.window:
            return
        ma = closes.rolling(self.window).mean().iloc[-1]
        # 布林带标准定义用总体标准差（ddof=0）；pandas 默认样本标准差(ddof=1)会使轨道偏宽
        std = closes.rolling(self.window).std(ddof=0).iloc[-1]
        if std == 0:
            return
        upper = ma + self.window_dev * std
        lower = ma - self.window_dev * std
        price = bar.close
        # 策略逻辑：
        #   价格跌破下轨（做多）：price < lower
        #   价格突破上轨（做空）：price > upper
        #   带内持有或观望（这里我们只做开仓信号，实际可加平仓逻辑）
        if price < lower:
            self.send_order(Direction.LONG, Offset.OPEN, 1)
        elif price > upper:
            self.send_order(Direction.SHORT, Offset.OPEN, 1)