"""M2.3 撮合差异化费率 / 滑点 / 涨跌停拦截验收"""
from __future__ import annotations
import sys, os
from dataclasses import dataclass
from datetime import datetime

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.core.types import Direction, Offset, Order, OrderType
from futures_quant.broker.backtest_broker import BacktestBroker

@dataclass
class SimpleContract:
    commission_per_lot: float = 3.0
    min_price_tick: float = 1.0
    multiplier: float = 10.0
    close_today_commission_ratio: float = 2.0

@dataclass
class SimpleBar:
    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float

def test_fee_close_today_vs_yesterday():
    broker = BacktestBroker(slippage=0.0, slip_mode="fixed")
    broker.contracts = {"A": SimpleContract(commission_per_lot=3.0, close_today_commission_ratio=2.0)}
    # 开仓 当日
    o_open = Order(symbol="A", direction=Direction.LONG, offset=Offset.OPEN, quantity=1, datetime=datetime(2026,1,2,9,0), order_id="o1")
    broker.submit(o_open)
    bar1 = SimpleBar(symbol="A", datetime=datetime(2026,1,2,10,0), open=100.0, high=101, low=99, close=100)
    broker.match(bar1)
    # 平仓 当日 => 平今
    o_close_today = Order(symbol="A", direction=Direction.SHORT, offset=Offset.CLOSE, quantity=1, datetime=datetime(2026,1,2,10,30), order_id="o2")
    broker.submit(o_close_today)
    bar2 = SimpleBar(symbol="A", datetime=datetime(2026,1,2,11,0), open=100.5, high=102, low=99, close=101)
    trades = broker.match(bar2)
    assert len(trades)==1
    t = trades[0]
    # 平今费 = 3 * 2 = 6
    assert abs(t.commission - 6.0) < 1e-6, f"平今费 {t.commission}"

    # 次日平仓 => 平昨
    o_close_yest = Order(symbol="A", direction=Direction.SHORT, offset=Offset.CLOSE, quantity=1, datetime=datetime(2026,1,3,9,30), order_id="o3")
    broker.submit(o_close_yest)
    bar3 = SimpleBar(symbol="A", datetime=datetime(2026,1,3,10,0), open=101.0, high=102, low=100, close=101)
    trades2 = broker.match(bar3)
    assert len(trades2)==1
    ty = trades2[0]
    assert abs(ty.commission - 3.0) < 1e-6, f"平昨费 {ty.commission}"
    print("费率差异化通过")

def test_slip_modes():
    broker = BacktestBroker(slippage=1.0, slip_mode="fixed", min_tick=0.5)
    bar = SimpleBar(symbol="B", datetime=datetime(2026,1,2,9,0), open=100, high=101, low=99, close=100)
    # 固定滑点：1 tick =0.5
    o = Order(symbol="B", direction=Direction.LONG, offset=Offset.OPEN, quantity=1, datetime=datetime(2026,1,2,8,59))
    broker.submit(o)
    trades = broker.match(bar)
    assert trades[0].price == 100.5
    # ratio
    broker2 = BacktestBroker(slip_mode="ratio", slip_ratio=0.001, min_tick=0.1)
    o2 = Order(symbol="B", direction=Direction.SHORT, offset=Offset.OPEN, quantity=1, datetime=datetime(2026,1,2,8,59))
    broker2.submit(o2)
    trades2 = broker2.match(bar)
    # slip_price=0.1, tick=0.1 => 1 tick
    assert abs(trades2[0].price - 99.9) < 1e-6
    print("滑点模式通过")

def test_limit_reject():
    broker = BacktestBroker(slippage=0.0, limit_up_pct=0.04)
    # 涨停：open100 close104 => +4%
    bar_up = SimpleBar(symbol="C", datetime=datetime(2026,1,2,9,0), open=100, high=105, low=99, close=104)
    # 开多应被拒
    o_up = Order(symbol="C", direction=Direction.LONG, offset=Offset.OPEN, quantity=1, datetime=datetime(2026,1,1,9,0))
    broker.submit(o_up)
    # 平多（方向SHORT，offset CLOSE）应被拒
    o_close_long = Order(symbol="C", direction=Direction.SHORT, offset=Offset.CLOSE, quantity=1, datetime=datetime(2026,1,1,9,0))
    broker.submit(o_close_long)
    trades = broker.match(bar_up)
    # 涨停日应拒开多和平多
    assert len(trades)==0
    # 检查订单状态
    # pending 清空后已拒
    print("涨跌停拦截通过")

if __name__=="__main__":
    test_fee_close_today_vs_yesterday()
    test_slip_modes()
    test_limit_reject()
    print("test_broker_rules.py 全绿")
