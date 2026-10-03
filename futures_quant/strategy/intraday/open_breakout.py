"""开盘突破（30min）日内短线策略。

M4.3 日内短线：开盘突破（30min）。
"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset

class OpenBreakout(StrategyBase):
    def __init__(self, symbol: str, params=None):
        # params可包含 opening_bars: int = 30 (表示前30根K线定义开盘区间)
        super().__init__(symbol, params)
        self.opening_bars = self.params.get("opening_bars", 30) if self.params else 30
        self._high = None
        self._low = None
        self._established = False  # 是否已确定今日开盘区间
        self._session_bars_count = 0  # 今日已处理的K线数（假设数据连续且仅含交易时段）

    def _window_size(self) -> int:
        return self.opening_bars + 5

    def on_bar(self, bar: Bar):
        self._push(bar)
        # 简单判断是否仍在同一天：这里假设数据是连续的交易时段，且不跨日。
        # 实际应需要根据日期变化重置。为简化，我们每kbar累加，若超过一定阈值则重置。
        # 这里我们假设每日交易时段K线数量已知，若超过则重置。
        # 为演示，我们设定每日最大K线数为 240 (6小时*60分钟)。
        if self._session_bars_count >= 240:
            self._reset_session()
        self._session_bars_count += 1

        if not self._established:
            # 仍在收集开盘区间
            highs = self.highs()
            lows = self.lows()
            if len(highs) >= self.opening_bars:
                # 计算前 opening_bars 根的高低
                self._high = max(highs[-self.opening_bars:])
                self._low = min(lows[-self.opening_bars:])
                self._established = True
                # 可选：在确定区间后立即开仓？通常是后续突破才开仓。
        else:
            # 已确定开盘区间，检查突破
            close = bar.close
            if close > self._high:
                self.send_order(Direction.LONG, Offset.OPEN, 1)
                # 触发后可选择不再重复开仓，这里简单处理：开仓后将 _established 设为 False 以避免重复
                self._established = False
            elif close < self._low:
                self.send_order(Direction.SHORT, Offset.OPEN, 1)
                self._established = False

    def _reset_session(self):
        self._high = None
        self._low = None
        self._established = False
        self._session_bars_count = 0