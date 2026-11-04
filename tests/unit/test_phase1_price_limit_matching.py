"""第二轮 P0-7 / P1-5 回归测试：涨跌停基准、挂单过期、品种过滤。

覆盖问题：
  - P0-7 旧实现用「当根 (close-open)/open」判断当根开盘能否成交（未来函数）
  - P1-5 挂单不过期、跨品种串单成交
"""
from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from futures_quant.core.types import Direction, Offset, Order, OrderStatus, OrderType
from futures_quant.broker.backtest_broker import BacktestBroker
from futures_quant.backtest.backtester import Backtester


@dataclass
class BarStub:
    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    settle: float = None
    prev_settle: float = None


def _order(symbol="RB", direction=Direction.LONG, offset=Offset.OPEN, qty=1,
           order_type=OrderType.MARKET, limit_price=None):
    return Order(symbol=symbol, direction=direction, offset=offset,
                 quantity=qty, datetime=datetime(2026, 1, 5, 9, 0),
                 order_type=order_type, limit_price=limit_price)


def test_limit_uses_prev_settle_not_current_close():
    """昨结算 100、幅度 4% -> 涨停价 104。

    买 1：open=104, close=90（当日大跌）——旧实现因 (90-104)/104 < 4% 不拦截，
          但开盘确实封在涨停价，买入不能成交 => 必须拒单。
    买 2：open=100, close=104（当日 +4%）——旧实现会拒单（未来函数），
          但开盘并未封板，买入可以成交 => 必须成交。
    """
    broker = BacktestBroker(slippage=0.0, limit_up_pct=0.04, pending_expire_bars=5)
    broker.submit(_order())
    bar_open_at_limit = BarStub("RB", datetime(2026, 1, 6, 9, 0),
                                open=104.0, high=104.0, low=90.0, close=90.0,
                                prev_settle=100.0)
    assert broker.match(bar_open_at_limit) == [], "开盘封涨停时买入不应成交"

    broker2 = BacktestBroker(slippage=0.0, limit_up_pct=0.04, pending_expire_bars=5)
    broker2.submit(_order())
    bar_close_at_limit = BarStub("RB", datetime(2026, 1, 6, 9, 0),
                                 open=100.0, high=105.0, low=99.0, close=104.0,
                                 prev_settle=100.0)
    trades = broker2.match(bar_close_at_limit)
    assert len(trades) == 1, "开盘未封板时买入应成交（不得用当根 close 预判）"


def test_limit_down_sell_rejected():
    """跌停：卖出方向（开空/平多）不能成交，买入方向可成交。"""
    broker = BacktestBroker(slippage=0.0, limit_down_pct=0.04)
    bar = BarStub("RB", datetime(2026, 1, 6, 9, 0), open=96.0, high=97.0,
                  low=96.0, close=96.0, prev_settle=100.0)
    broker.submit(_order(direction=Direction.SHORT, offset=Offset.OPEN))
    broker.submit(_order(direction=Direction.LONG, offset=Offset.OPEN))
    trades = broker.match(bar)
    assert len(trades) == 1, "跌停时仅买入方向可成交"
    assert trades[0].direction == Direction.LONG


def test_symbol_filter_prevents_cross_symbol_fill():
    """A 的挂单不得被 B 的 K 线撮合。"""
    broker = BacktestBroker(slippage=0.0)
    broker.submit(_order(symbol="A"))
    bar_b = BarStub("B", datetime(2026, 1, 6, 9, 0), open=100, high=101, low=99, close=100)
    assert broker.match(bar_b) == [], "B 的行情不得撮合 A 的委托"
    assert len(broker.pending) == 1, "A 的委托应继续挂单"
    bar_a = BarStub("A", datetime(2026, 1, 6, 9, 0), open=100, high=101, low=99, close=100)
    assert len(broker.match(bar_a)) == 1, "A 的行情到达后才可成交"


def test_pending_order_expires():
    """限价单连续 N 根未触发即撤单。"""
    broker = BacktestBroker(slippage=0.0, pending_expire_bars=2)
    order = _order(order_type=OrderType.LIMIT, limit_price=90.0)
    broker.submit(order)
    for minute in (10, 11):
        bar = BarStub("RB", datetime(2026, 1, 6, 9, minute), open=100, high=101, low=99, close=100)
        broker.match(bar)
    assert len(broker.pending) == 0
    assert order.status == OrderStatus.CANCELLED
    assert "超" in order.reject_reason


def test_prev_settle_trading_day_grouping():
    """夜盘归属下一交易日，且上一交易日只认日盘结算价。"""
    records = [
        {"datetime": datetime(2026, 1, 5, 9, 0), "close": 100.0, "settle": 100.0},
        {"datetime": datetime(2026, 1, 5, 15, 0), "close": 101.0, "settle": 101.0},
        # 夜盘 21:00（日历日 1/5）属于 1/6 交易日，不能被当作 1/6 的昨结算
        {"datetime": datetime(2026, 1, 5, 21, 0), "close": 999.0, "settle": 999.0},
        {"datetime": datetime(2026, 1, 6, 9, 0), "close": 102.0, "settle": 102.0},
    ]
    prev = Backtester._prev_settle_by_index(records)
    assert prev[0] is None, "首个交易日没有昨结算"
    assert prev[1] is None, "同一交易日内的后续 bar 仍使用同一个昨结算（首日为 None）"
    assert prev[2] == 101.0, "1/6 夜盘的昨结算应为 1/5 日盘最后结算价，而非夜盘 999"
    assert prev[3] == 101.0
