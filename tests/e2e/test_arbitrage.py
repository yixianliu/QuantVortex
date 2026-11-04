"""M4.2 统计套利验收：跨期 / 跨品种 / 期现 三类套利。"""
from __future__ import annotations
import sys, os
import pandas as pd
from unittest.mock import Mock
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.arbitrage.calendar_spread import CalendarSpread
from futures_quant.strategy.arbitrage.cross_instrument import (
    CrossInstrumentSpread,
    cointegration_score,
)
from futures_quant.strategy.arbitrage.spot_futures import SpotFuturesBasis
from futures_quant.core.types import Bar, Direction, Offset, OrderType


class MockEngine:
    def __init__(self):
        self.orders = []
        self.position_long = 0
        self.position_short = 0

    def send_order(self, symbol, direction, offset, quantity, order_type, limit_price):
        self.orders.append({
            'symbol': symbol,
            'direction': direction,
            'offset': offset,
            'quantity': quantity,
            'order_type': order_type,
            'limit_price': limit_price,
        })

    def get_position(self, symbol):
        return self.position_long, self.position_short


def _offset_val(v):
    """兼容枚举（Offset.OPEN.value='open'）与字符串 'open' 两种 offset 形态。"""
    return str(getattr(v, "value", v)).upper()


def _feed(strat, engine, closes, spot_prices=None):
    """喂入一组收盘价（可选现货价），返回订单列表。"""
    for i, c in enumerate(closes):
        spot = (spot_prices[i] if spot_prices is not None else None)
        bar = Bar(
            symbol=strat.symbol,
            datetime=pd.Timestamp('2026-01-01') + pd.Timedelta(minutes=i * 5),
            open=c, high=c, low=c, close=c, volume=0, open_interest=0,
        )
        if spot_prices is not None:
            strat._next_spot = lambda s=spot: s
        strat._push(bar)
        strat.on_bar(bar)
    return engine.orders


def test_calendar_spread():
    engine = MockEngine()
    strat = CalendarSpread(symbol='TEST', params={"window": 5, "entry_z": 1.5, "exit_z": 0.1})
    strat.engine = engine

    spreads = [0.0, 0.1, -0.1, 0.05, -0.05,  # 前5个填窗口，均值约0
               1.0,   # 第6个，Z≈12.5 > entry_z → 做空
               0.0,   # 第7个，回归
               -1.0]  # 第8个，Z≈-12.5 < -entry_z → 做多

    for i, spread in enumerate(spreads):
        bar = Bar(
            symbol='TEST',
            datetime=pd.Timestamp('2026-01-01') + pd.Timedelta(minutes=i * 5),
            open=spread, high=spread, low=spread, close=spread,
            volume=0, open_interest=0,
        )
        strat._push(bar)
        strat.on_bar(bar)

    assert len(engine.orders) >= 1, f"期望至少1个订单，实际{len(engine.orders)}"
    print(f"  [OK] calendar_spread 订单数={len(engine.orders)}")


def test_cross_instrument():
    """跨品种：价差极端 → 开仓；回归 → 平仓。"""
    engine = MockEngine()
    strat = CrossInstrumentSpread(symbol='rb', params={"pair_basis": 1.0, "lookback": 5,
                                  "entry_z": 1.5, "exit_z": 0.1})
    strat.engine = engine

    # 稳定 1.0 附近（std≈0），第6根跳到 2.0 → z 大 → 做空
    closes = [1.0, 1.05, 0.98, 1.02, 0.99,   # 窗口：mean≈1.008, std≈0.026
              2.0,                            # 2.0 → z≈38 → 做空
              1.0,                            # 回归
              1.5]                            # 仍偏高
    _feed(strat, engine, closes)

    opens = [o for o in engine.orders if _offset_val(o['offset']) == 'OPEN']
    closes_ord = [o for o in engine.orders if _offset_val(o['offset']) == 'CLOSE']
    print(f"  [OK] cross_instrument 开仓={len(opens)} 平仓={len(closes_ord)}")
    assert len(opens) >= 1, "跨品种应至少触发1次开仓"

    # cointegration_score 基本行为
    s = cointegration_score(
        [1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
        [2.0, 2.1, 2.2, 2.3, 2.4, 2.5],
    )
    print(f"  [OK] cointegration_score={s}")
    assert 0.0 <= s['coint_score'] <= 1.0
    assert isinstance(s['half_life'], float)


def test_spot_futures():
    """期现：期货升水极端 → 卖期货；贴水极端 → 买期货。"""
    engine = MockEngine()
    strat = SpotFuturesBasis(symbol='cu', params={"lookback": 5, "entry_z": 1.5, "exit_z": 0.1})
    strat.engine = engine

    # 现货固定 100；期货前5根≈[100,101,99,100,100]基差mean≈0 std≈0.7
    # 第6根期货=105 → 基差=5 → z≈(5-0.raw)/std 大 → 做空(卖期货)
    futures = [100, 101, 99, 100, 100, 105, 100, 95]
    spots = [100] * len(futures)
    _feed(strat, engine, futures, spots)

    opens = [o for o in engine.orders if _offset_val(o['offset']) == 'OPEN']
    print(f"  [OK] spot_futures 开仓={len(opens)}")
    assert len(opens) >= 1, "期现套利应至少触发1次开仓"


def test_all():
    test_calendar_spread()
    test_cross_instrument()
    test_spot_futures()
    print("test_arbitrage.py 全绿")


if __name__ == "__main__":
    test_all()