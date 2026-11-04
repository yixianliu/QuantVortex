"""M3.3 移仓换月成本模拟验收"""
from __future__ import annotations
import sys, os
from datetime import datetime
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.backtest.roll_cost import RollParams, should_roll, roll_cost

def test_roll_logic():
    params = RollParams()
    expiry = datetime(2026,2,1)
    d1 = datetime(2026,1,25)  # 7天前
    d2 = datetime(2026,1,20)
    assert should_roll(d1, expiry, params) is True
    assert should_roll(d2, expiry, params) is False
    cost = roll_cost(4000, 4010, 1, params)
    # 价差 + 手续费
    assert cost == 10*10 + 6
    print("test_roll_cost.py 全绿")

if __name__=="__main__":
    test_roll_logic()
