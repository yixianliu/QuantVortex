"""成交量异动（放量 2σ）日内短线策略。

M4.3 日内短线：成交量异动（放量 2σ）。
"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset
import pandas as pd
from collections import deque

class VolumeAnomaly(StrategyBase):
    def __init__(self, symbol: str, params=None):
        super().__init__(symbol, params)
        self.window = self.params.get("window", 20) if self.params else 20
        self.entry_multiplier = self.params.get("entry_multiplier", 2.0) if self.params else 2.0
        # 维护成交量历史序列（仅使用已发生数据，杜绝未来函数）。
        self._volumes: deque = deque()

    def _window_size(self) -> int:
        return self.window + 5

    def on_bar(self, bar: Bar):
        self._push(bar)
        # 使用历史成交量（不包括当前 bar）计算均值和标准差
        if len(self._volumes) < self.window:
            # 历史数据不足，先收集数据
            self._volumes.append(bar.volume)
            return
        # 计算滚动均值和标准差（仅使用历史数据）
        vol_series = pd.Series(self._volumes)
        mean = vol_series.rolling(self.window).mean().iloc[-1]
        std = vol_series.rolling(self.window).std().iloc[-1]
        if std == 0:
            # 仍然无法计算，保存当前量以后继续
            self._volumes.append(bar.volume)
            return
        # 当前成交量
        vol = bar.volume
        # 判断是否放量
        if vol > mean + self.entry_multiplier * std:
            # 放量时，根据价格方向决定做多还是做空
            if bar.close > bar.open:
                # 收盘价 > 开盘价，视为放量上涨，做多
                self.send_order(Direction.LONG, Offset.OPEN, 1)
            elif bar.close < bar.open:
                # 收盘价 < 开盘价，视为放量下跌，做空
                self.send_order(Direction.SHORT, Offset.OPEN, 1)
        # 将当前成交量加入历史序列，供后续 bar 使用
        self._volumes.append(bar.volume)
        # 仅保留最近 _window_size() 根，超出则丢弃最旧，保证长度恒定
        cap = self._window_size()
        while len(self._volumes) > cap:
            self._volumes.popleft()