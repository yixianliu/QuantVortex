"""跨期价差 Z-score 套利策略。

M4.2 统计套利：近月/远月价差 Z-score。
"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Direction, Offset

class CalendarSpread(StrategyBase):
    def __init__(self, symbol: str, params: dict | None = None):
        self.symbol = symbol
        p = params or {}
        self.window = int(p.get("window", 20))
        self.entry_z = float(p.get("entry_z", 2.0))
        self.exit_z = float(p.get("exit_z", 0.5))
        super().__init__(symbol)

    def on_bar(self, bar):
        # 使用收盘价作为价差（近月 - 远月）
        spread = bar.close
        closes = self.closes()
        if len(closes) < self.window:
            return
        # 计算滚动均值和标准差（仅使用历史数据）
        mean = closes.rolling(self.window).mean().iloc[-1]
        std = closes.rolling(self.window).std().iloc[-1]
        if std == 0:
            return
        z = (spread - mean) / std
        # 简单的均值回归：价差过高做空（卖出近月买入远月），价差过低做多
        # 这里我们只做演示，实际需要根据价差方向确定交易方向
        if z > self.entry_z:
            # 做空价差：卖出近月，买入远月（简化为发出卖出指令）
            self.send_order(direction=Direction.SHORT, offset=Offset.OPEN, quantity=1)
        elif z < -self.entry_z:
            # 做多价差：买入近月，卖出远月
            self.send_order(direction=Direction.LONG, offset=Offset.OPEN, quantity=1)
        # 平仓条件：Z-score 回归至阈值内
        if abs(z) < self.exit_z:
            # 平仓逻辑：根据当前持仓方向进行平仓
            long_pos, short_pos = self.position()
            if long_pos > 0:
                self.send_order(direction=Direction.LONG, offset=Offset.CLOSE, quantity=long_pos)
            if short_pos > 0:
                self.send_order(direction=Direction.SHORT, offset=Offset.CLOSE, quantity=short_pos)