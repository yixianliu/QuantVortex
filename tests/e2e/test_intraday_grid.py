"""M4.3 改良网格策略验收"""
from __future__ import annotations
import sys, os
import pandas as pd
from unittest.mock import Mock
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.intraday.grid import Grid
from futures_quant.core.types import Bar, Direction, Offset

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

def test_grid():
    engine = MockEngine()
    strat = Grid(symbol='TEST', params={'atr_period': 5, 'grid_k': 1.0, 'max_grid': 5})
    strat.engine = engine
    
    # 我们需要先提供足够的数据来计算 ATR。
    # 设定一系列 bar，使得 ATR 为已知值。
    # 为了简单，我们设定 high-low-close 的波动使得 ATR ≈ 1.0。
    # 例如，让每根 bar 的 high = close + 0.5, low = close - 0.5, 则 TR ≈ 1.0 (假设收盘价变化不大)。
    # 我们还需要确保收盘价的变化不影响 TR 太大。
    # 我们设定一系列收盘价固定为 10，high=10.5, low=9.5。
    # 那么 TR = max(high-low, |high-close_prev|, |low-close_prev|).
    # 如果收盘价保持不变，则 high-low = 1.0, |high-close_prev| = |10.5-10|=0.5, |low-close_prev| = 0.5，所以 TR=1.0.
    # 因此 ATR 约为 1.0。
    # 我们先提供 5 根这样的 bar 来填满 ATR 窗口。
    base_price = 10.0
    for i in range(5):
        bar = Bar(
            symbol='TEST',
            datetime=pd.Timestamp('2026-01-01 09:30') + pd.Timedelta(minutes=i),
            open=base_price,
            high=base_price + 0.5,
            low=base_price - 0.5,
            close=base_price,
            volume=0,
            open_interest=0
        )
        strat.on_bar(bar)
    # 此时 ATR 应该约为 1.0（实际可能略有差异，但足够演示）。
    # 参考价 reference_price 被设定为第一根 bar 的 open？实际上在第一根 bar 时，_reference_price_set 为 False，
    # 所以会在第一根 bar 的 on_bar 中将 reference_price 设定为 bar.open (=10.0)。
    # 因此 reference_price = 10.0.
    # grid_spacing = ATR * grid_k ≈ 1.0 * 1.0 = 1.0.
    # 因此做多条件：close < reference_price - grid_spacing => close < 9.0
    # 做空条件：close > reference_price + grid_spacing => close > 11.0
    
    # 清空订单以便观察新订单
    engine.orders.clear()
    
    # 第6根：收盘价跌至 8.5 (<9.0) 应该做多
    bar6 = Bar(
        symbol='TEST',
        datetime=pd.Timestamp('2026-01-01 09:35'),
        open=base_price,
        high=base_price + 0.5,
        low=base_price - 0.5,
        close=8.5,   # 低于做多阈值
        volume=0,
        open_interest=0
    )
    strat.on_bar(bar6)
    # 应该做多开仓
    assert len(engine.orders) == 1
    assert engine.orders[0]['direction'] == Direction.LONG
    assert engine.orders[0]['offset'] == Offset.OPEN
    
    # 清空订单
    engine.orders.clear()
    # 第7根：收盘价升至 11.5 (>11.0) 应该做空
    bar7 = Bar(
        symbol='TEST',
        datetime=pd.Timestamp('2026-01-01 09:36'),
        open=base_price,
        high=base_price + 0.5,
        low=base_price - 0.5,
        close=11.5,   # 高于做空阈值
        volume=0,
        open_interest=0
    )
    strat.on_bar(bar7)
    assert len(engine.orders) == 1
    assert engine.orders[0]['direction'] == Direction.SHORT
    assert engine.orders[0]['offset'] == Offset.OPEN
    
    print("test_intraday_grid.py 全绿")

if __name__=="__main__":
    test_grid()