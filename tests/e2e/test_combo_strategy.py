"""M4.5 策略组合验收"""
from __future__ import annotations
import sys, os
from unittest.mock import Mock
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.combo import ComboStrategy
from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset
import pandas as pd

class MockStrategy(StrategyBase):
    """一个用于测试的简单策略，返回预设的信号。"""
    def __init__(self, symbol: str, signal: float):
        # signal 期望在 [-1, 1] 范围内
        super().__init__(symbol)
        self.signal = signal
        # 为了满足 _window_size，我们设置一个最小值
        self._window = 5
    
    def _window_size(self) -> int:
        return self._window
    
    def get_signal(self, bar: Bar) -> float:
        return self.signal
    
    # 我们不需要在 on_bar 中发送订单，因为组合策略会自己发送。
    # 但为了完整实现基类，我们可以保持不发送订单的 on_bar。
    def on_bar(self, bar: Bar) -> None:
        self._push(bar)
        # 不发送订单

class MockEngine:
    def __init__(self):
        self.orders = []
    def send_order(self, symbol, direction, offset, quantity, order_type, limit_price=None):
        self.orders.append({
            'symbol': symbol,
            'direction': direction,
            'offset': offset,
            'quantity': quantity,
            'order_type': order_type,
            'limit_price': limit_price,
        })
    def get_position(self, symbol):
        return 0, 0

def test_combo_strategy():
    engine = MockEngine()
    # 创建两个子策略：一个总是做多（信号=1），一个总是做空（信号=-1）
    strategy_long = MockStrategy('TEST_LONG', 1.0)
    strategy_short = MockStrategy('TEST_SHORT', -1.0)
    # 权重：多头策略权重 2，空头策略权重 1 => 组合信号 = (2*1 + 1*(-1))/(2+1) = (2-1)/3 = 1/3 ≈ 0.333
    # 如果阈值设为 0.5，则信号不足以开多，应该不开仓。
    strategies_weights = [(strategy_long, 2.0), (strategy_short, 1.0)]
    combo = ComboStrategy('TEST_COMBO', strategies_weights, params={'threshold': 0.5})
    combo.engine = engine
    
    # 创建一个假的 K 线
    bar = Bar(
        symbol='TEST_COMBO',
        datetime=pd.Timestamp('2026-01-01 09:30'),
        open=10,
        high=10.5,
        low=9.5,
        close=10,
        volume=0,
        open_interest=0
    )
    combo.on_bar(bar)
    # 期望无订单，因为组合信号 0.333 < 0.5
    assert len(engine.orders) == 0, f"期望无订单，实际得到 {len(engine.orders)} 单"
    
    # 调整权重：让多头权重更大，使组合信号超过阈值
    # 例如，多头权重 3，空头权重 1 => (3*1 + 1*(-1))/4 = (3-1)/4 = 0.5
    # 正好等于阈值，我们设定开仓条件为 > 阈值（不包含等于），所以仍不开仓。
    # 我们设定多头权重 4，空头权重 1 => (4-1)/5 = 3/5 = 0.6 > 0.5
    strategies_weights2 = [(strategy_long, 4.0), (strategy_short, 1.0)]
    combo2 = ComboStrategy('TEST_COMBO2', strategies_weights2, params={'threshold': 0.5})
    combo2.engine = engine
    # 清空订单
    engine.orders.clear()
    combo2.on_bar(bar)
    assert len(engine.orders) == 1, f"期望做多订单，实际得到 {len(engine.orders)} 单"
    assert engine.orders[0]['direction'] == Direction.LONG
    assert engine.orders[0]['offset'] == Offset.OPEN
    
    # 测试做空方向
    # 两个做空策略：信号 -1 和 -1，权重相等
    strategy_s1 = MockStrategy('TEST_S1', -1.0)
    strategy_s2 = MockStrategy('TEST_S2', -1.0)
    strategies_weights3 = [(strategy_s1, 1.0), (strategy_s2, 1.0)]
    combo3 = ComboStrategy('TEST_COMBO3', strategies_weights3, params={'threshold': 0.5})
    combo3.engine = engine
    engine.orders.clear()
    combo3.on_bar(bar)
    assert len(engine.orders) == 1, f"期望做空订单，实际得到 {len(engine.orders)} 单"
    assert engine.orders[0]['direction'] == Direction.SHORT
    assert engine.orders[0]['offset'] == Offset.OPEN
    
    print("test_combo_strategy.py 全绿")

if __name__=="__main__":
    test_combo_strategy()