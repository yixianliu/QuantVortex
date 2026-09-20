"""M4.4 波动率交易：布林带策略验收。

用 window=3、close 序列 [10,12,14,8]（ddof=0）验证严格突破上/下轨：
- 第 3 根暴涨 close=14 → 破上轨 → 做空
- 第 4 根暴跌 close=8  → 破下轨 → 做多
window=3 时 std 由 3 点决定，close 才能严格（而非恰在边界）突破布林带。
"""
from __future__ import annotations
import sys, os
import pandas as pd
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.volatility.bollinger import BollingerBands
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


def test_bollinger_bands():
    engine = MockEngine()
    strat = BollingerBands(symbol="TEST", params={"window": 3, "window_dev": 1.0})
    strat.engine = engine

    closes_seq = [10, 12, 14, 8]
    for k, c in enumerate(closes_seq):
        b = Bar(
            symbol="TEST",
            datetime=pd.Timestamp("2026-01-01 09:30") + pd.Timedelta(minutes=k),
            open=c, high=c + 0.5, low=c - 0.5, close=c,
            volume=0, open_interest=0,
        )
        strat.on_bar(b)

    shorts = [o for o in engine.orders if o["direction"] == Direction.SHORT]
    longs = [o for o in engine.orders if o["direction"] == Direction.LONG]
    print(f"window=3 seq[10,12,14,8]: shorts={len(shorts)} longs={len(longs)}")
    assert len(shorts) >= 1, "暴涨应触发做空（破上轨）"
    assert len(longs) >= 1, "暴跌应触发做多（破下轨）"
    assert shorts[0]["offset"] == Offset.OPEN
    assert longs[0]["offset"] == Offset.OPEN
    print("test_volatility_bollinger.py 全绿")


if __name__ == "__main__":
    test_bollinger_bands()
