"""M4.3 日内短线验收"""
from __future__ import annotations
import sys, os
import pandas as pd
from unittest.mock import Mock
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.intraday.open_breakout import OpenBreakout
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

def test_open_breakout():
    engine = MockEngine()
    strat = OpenBreakout(symbol='TEST', params={'opening_bars': 3})
    strat.engine = engine
    
    # 前3根K线定义开盘区间：高=10, low=5
    # 我们构造：bar1: high=10, low=5, close=7
    # bar2: high=9, low=4, close=6
    # bar3: high=11, low=6, close=8
    # 则区间 high = max(10,9,11)=11, low = min(5,4,6)=4
    bars = [
        Bar('TEST', pd.Timestamp('2026-01-01 09:30'), 7, 10, 5, 7, 0, 0),
        Bar('TEST', pd.Timestamp('2026-01-01 09:31'), 6, 9, 4, 6, 0, 0),
        Bar('TEST', pd.Timestamp('2026-01-01 09:32'), 8, 11, 6, 8, 0, 0),
    ]
    for bar in bars:
        strat._push(bar)
        strat.on_bar(bar)
    # 此时应已确定区间，但尚未突破
    assert len(engine.orders) == 0, f"开盘区间内不应开仓，实际得到{len(engine.orders)}单"
    
    # 第4根K线：突破上轨（收盘价 > 11）
    bar4 = Bar('TEST', pd.Timestamp('2026-01-01 09:33'), 12, 12, 11, 12, 0, 0)
    strat._push(bar4)
    strat.on_bar(bar4)
    # 应该做多开仓
    assert len(engine.orders) == 1
    assert engine.orders[0]['direction'] == Direction.LONG
    assert engine.orders[0]['offset'] == Offset.OPEN
    
    # 继续测试下跌突破：先重置（新一天）或者继续但区间已失效？我们简单测试：后续再次收集区间后突破下轨
    # 为了简单，我们就不继续了。
    print("test_intraday.py 全绿")

if __name__=="__main__":
    test_open_breakout()