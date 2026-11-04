"""M4.3 成交量异动策略验收"""
from __future__ import annotations
import sys, os
import pandas as pd
from unittest.mock import Mock
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.intraday.volume_anomaly import VolumeAnomaly
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

def test_volume_anomaly():
    engine = MockEngine()
    strat = VolumeAnomaly(symbol='TEST', params={'window': 5, 'entry_multiplier': 2.0})
    strat.engine = engine
    
    # 前5根K线用于计算均值和标准差
    # 我们设定成交量基本为 1000，然后放量到 3000 (均值+2*std)
    # 为了简单，我们让前5根成交量都为 1000，然后放量到 3000 (均值+2*std)
    # 但我们需要非零 std，所以设定前5根为: 1000, 1000, 1000, 1000, 1100
    bars = []
    # 前5根
    for i in range(5):
        vol = 1000 if i < 4 else 1100
        bar = Bar(
            symbol='TEST',
            datetime=pd.Timestamp('2026-01-01 09:30') + pd.Timedelta(minutes=i),
            open=10,
            high=10.5,
            low=9.5,
            close=10 if i%2==0 else 9.9,  # 随意
            volume=vol,
            open_interest=0
        )
        bars.append(bar)
    # 处理前5根
    for bar in bars:
        strat._push(bar)
        strat.on_bar(bar)
    # 此时应该还没有下单，因为还没到放量阈值
    print(f"After first 5 bars, orders: {len(engine.orders)}")
    # 清空订单记录，以便测试后续触发
    engine.orders.clear()
    
    # 第6根：放量且收盘价 > 开盘价
    bar6 = Bar(
        symbol='TEST',
        datetime=pd.Timestamp('2026-01-01 09:35'),
        open=10,
        high=12,
        low=9,
        close=11,   # 收盘价 > 开盘价
        volume=2000,
        open_interest=0
    )
    strat._push(bar6)
    strat.on_bar(bar6)
    print(f"After bar6, orders: {len(engine.orders)}")
    for i, o in enumerate(engine.orders):
        print(f"  Order {i}: {o}")
    # 应该做多开仓
    assert len(engine.orders) == 1, f"Expected 1 order after bar6, got {len(engine.orders)}"
    assert engine.orders[0]['direction'] == Direction.LONG
    assert engine.orders[0]['offset'] == Offset.OPEN
    
    # 清空订单，继续测试放量做空
    engine.orders.clear()
    # 第7根：放量且收盘价 < 开盘价
    bar7 = Bar(
        symbol='TEST',
        datetime=pd.Timestamp('2026-01-01 09:36'),
        open=11,
        high=12,
        low=9,
        close=10,   # 收盘价 < 开盘价
        volume=2500,
        open_interest=0
    )
    strat._push(bar7)
    strat.on_bar(bar7)
    print(f"After bar7, orders: {len(engine.orders)}")
    for i, o in enumerate(engine.orders):
        print(f"  Order {i}: {o}")
    assert len(engine.orders) == 1, f"Expected 1 order after bar7, got {len(engine.orders)}"
    assert engine.orders[0]['direction'] == Direction.SHORT
    assert engine.orders[0]['offset'] == Offset.OPEN
    
    print("test_volume_anomaly.py 全绿")

if __name__=="__main__":
    test_volume_anomaly()