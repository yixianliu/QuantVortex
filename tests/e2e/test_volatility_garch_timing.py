"""M4.4 波动率交易：GARCH 波动率择时策略验收。

覆盖：
- GARCHTiming 可导入、可构造；
- 高波动段 → 出现保守信号（SHORT）；
- 低波动段 → 出现正常信号（LONG）；
- 方向与 HV 分位一致（高波动→保守）。
"""
from __future__ import annotations
import sys, os
import pandas as pd
import numpy as np
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.volatility.garch_timing import GARCHTiming
from futures_quant.core.types import Bar, Direction, Offset


class MockEngine:
    def __init__(self):
        self.orders = []

    def send_order(self, symbol, direction, offset, quantity, order_type, limit_price=None):
        self.orders.append({
            "symbol": symbol, "direction": direction, "offset": offset,
            "quantity": quantity, "order_type": order_type, "limit_price": limit_price,
        })

    def get_position(self, symbol):
        return 0, 0


def _mk_bar(symbol, i, close, base_ts="2026-01-01 09:30", vol=0.1):
    return Bar(
        symbol=symbol,
        datetime=pd.Timestamp(base_ts) + pd.Timedelta(minutes=i),
        open=close, high=close + vol, low=close - vol,
        close=close, volume=0, open_interest=0,
    )


def test_garch_timing_runs():
    engine = MockEngine()
    strat = GARCHTiming(symbol="TEST", params={
        "vol_window": 5, "percentile_window": 20,
        "high_threshold": 70.0, "low_threshold": 30.0,
    })
    strat.engine = engine

    rng = np.random.default_rng(0)
    base = 100.0
    # 前 40 根：低波动（小噪声）
    for i in range(40):
        close = base + rng.normal(0, 0.1)
        strat.on_bar(_mk_bar("TEST", i, close))
    engine.orders.clear()
    # 接下来 40 根：高波动（大噪声）→ 条件波动率抬升 → 应触发保守（SHORT）
    for i in range(40, 80):
        close = base + rng.normal(0, 3.0)
        strat.on_bar(_mk_bar("TEST", i, close, vol=3.0))
    short_orders = [o for o in engine.orders if o["direction"] == Direction.SHORT]
    print(f"high-vol segment: total orders={len(engine.orders)}, short={len(short_orders)}")
    assert len(short_orders) >= 1, "高波动段应产生至少一次保守（SHORT）信号"

    # 再 40 根：回到低波动 → 条件波动率回落 → 应触发正常（LONG）
    engine.orders.clear()
    for i in range(80, 120):
        close = base + rng.normal(0, 0.1)
        strat.on_bar(_mk_bar("TEST", i, close))
    long_orders = [o for o in engine.orders if o["direction"] == Direction.LONG]
    print(f"low-vol segment: total orders={len(engine.orders)}, long={len(long_orders)}")
    assert len(long_orders) >= 1, "低波动段应产生至少一次正常（LONG）信号"

    print("test_volatility_garch_timing.py 全绿")


if __name__ == "__main__":
    test_garch_timing_runs()
