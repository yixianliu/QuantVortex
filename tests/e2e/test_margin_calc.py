"""M2.4 保证金动态 + 风险度验收"""
from __future__ import annotations
import sys, os
from dataclasses import dataclass

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.core.types import Direction, Offset, Trade
from futures_quant.core.portfolio import Portfolio
from futures_quant.data.contract_specs import build_contract

@dataclass
class SimplePosition:
    symbol: str
    long_avg_price: float = 0.0
    short_avg_price: float = 0.0
    long_qty: int = 0
    short_qty: int = 0

def test_margin_risk_degree():
    contracts = {}
    c = build_contract("RB")
    contracts["RB"] = c
    pf = Portfolio(initial_capital=1_000_000.0, margin_rate=0.10, contracts=contracts)
    # 模拟一笔开多成交
    t = Trade(symbol="RB", direction=Direction.LONG, offset=Offset.OPEN, quantity=1, price=4000.0, datetime=None, order_id="t1")
    pf.process_trade(t)
    pf.update_price("RB", 4000.0)
    used = pf.used_margin()
    mr = c.margin_rate
    mult = c.multiplier
    expected_used = 1 * 4000.0 * mult * mr
    assert abs(used - expected_used) < 1e-6, f"used {used} != {expected_used}"
    rd = pf.risk_degree()
    eq = pf.equity()
    assert abs(rd - used/eq) < 1e-6
    # 风险度 > 1 触发
    # 增大持仓
    for _ in range(50):
        t2 = Trade(symbol="RB", direction=Direction.LONG, offset=Offset.OPEN, quantity=10, price=4000.0, datetime=None, order_id="t2")
        pf.process_trade(t2)
    pf.update_price("RB", 4000.0)
    assert pf.risk_degree() > 0.5
    print("margin/risk_degree 通过")

def test_contract_override():
    contracts = {}
    c = build_contract("IF")
    # 金融期货保证金率更高
    assert c.margin_rate >= 0.12
    contracts["IF"] = c
    pf = Portfolio(initial_capital=1_000_000.0, margin_rate=0.10, contracts=contracts)
    t = Trade(symbol="IF", direction=Direction.LONG, offset=Offset.OPEN, quantity=1, price=5000.0, datetime=None, order_id="t3")
    pf.process_trade(t)
    pf.update_price("IF", 5000.0)
    used = pf.used_margin()
    # 用合约级参数计算
    expected = 1 * 5000.0 * c.multiplier * c.margin_rate
    assert abs(used - expected) < 1e-6
    print("合约级覆盖通过")

if __name__=="__main__":
    test_margin_risk_degree()
    test_contract_override()
    print("test_margin_calc.py 全绿")
