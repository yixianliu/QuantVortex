"""改良网格（动态间距 = ATR×k）日内短线策略。

M4.3 日内短线：改良网格（动态间距 = ATR×k）。
"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset
import pandas as pd

class Grid(StrategyBase):
    def __init__(self, symbol: str, params=None):
        super().__init__(symbol, params)
        self.atr_period = self.params.get("atr_period", 14) if self.params else 14
        self.grid_k = self.params.get("grid_k", 1.0) if self.params else 1.0
        self.max_grid = self.params.get("max_grid", 5) if self.params else 5
        self.reference_price = None  # 可以使用 VWAP 或 开盘价等作为参考价
        self._reference_price_set = False

    def _window_size(self) -> int:
        return self.atr_period + 5

    def on_bar(self, bar: Bar):
        self._push(bar)
        # 计算 ATR（仅使用历史数据）
        if len(self._closes) < self.atr_period:
            # 历史数据不足，先收集
            return
        highs = pd.Series(self._highs)
        lows = pd.Series(self._lows)
        closes = pd.Series(self._closes)
        tr1 = highs - lows
        tr2 = (highs - closes.shift(1)).abs()
        tr3 = (lows - closes.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(self.atr_period).mean().iloc[-1]
        if atr == 0:
            return
        grid_spacing = atr * self.grid_k

        # 设定参考价：如果尚未设定，使用当前 bar 的开盘价作为参考价（可改为 VWAP）
        if not self._reference_price_set:
            self.reference_price = bar.open
            self._reference_price_set = True

        # 计算当前价格相对于参考价的偏移（以网格间距为单位）
        deviation = (bar.close - self.reference_price) / grid_spacing
        # 我们采用简单的网格：当价格偏离参考价超过一定网格数时进行反向操作？
        # 这里我们实现一个简单的网格交易：当价格跌破参考价下方某个网格时做多，涨破上方某个网格时做空。
        # 为了避免频繁开仓，我们只在价格穿过整数网格时开仓，并在反向穿过时平仓。
        # 为了简化，我们只在价格跌破参考价 - grid_spacing 时做多，涨破参考价 + grid_spacing 时做空。
        # 实际网格策略更复杂，这里仅作演示。
        if bar.close < self.reference_price - grid_spacing:
            # 价格显著低于参考价，做多
            self.send_order(Direction.LONG, Offset.OPEN, 1)
        elif bar.close > self.reference_price + grid_spacing:
            # 价格显著高于参考价，做空
            self.send_order(Direction.SHORT, Offset.OPEN, 1)