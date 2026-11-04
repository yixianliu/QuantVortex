# -*- coding: utf-8 -*-
"""阶段 0（风控账务）回归测试。

覆盖：
1. equity() 必须计入手续费（旧实现只扣 cash，权益高估）；
2. cash / equity / unrealized 三个口径自洽：equity == cash + unrealized；
3. summary() 不再因把 float 当函数调用而 TypeError；
4. RiskManager.check_order 的保证金估算必须乘合约乘数。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from futures_quant.config.settings import RiskConfig
from futures_quant.core.portfolio import Portfolio
from futures_quant.core.types import Direction, Offset, Order, OrderType, Trade
from futures_quant.data.contract_specs import build_contract
from futures_quant.risk.risk_manager import RiskManager


def _portfolio(initial: float = 1_000_000.0) -> Portfolio:
    rb = build_contract("RB")
    return Portfolio(initial_capital=initial, margin_rate=0.10,
                     contracts={"RB": rb})


def test_equity_includes_commission_on_open():
    """开仓后权益应立即反映手续费，而不是只在 cash 里扣。"""
    pf = _portfolio()
    pf.update_price("RB", 4000.0)
    t = Trade(symbol="RB", direction=Direction.LONG, offset=Offset.OPEN,
              quantity=1, price=4000.0, datetime=None, order_id="p0-open",
              multiplier=10.0)
    pf.process_trade(t)

    fee = pf.total_commission
    assert fee > 0, "开仓必须产生手续费"
    # 无浮盈时：权益 = 初始资金 - 手续费
    assert abs(pf.equity() - (1_000_000.0 - fee)) < 1e-6
    # 三个口径自洽
    assert abs(pf.equity() - (pf.cash + pf.unrealized_pnl())) < 1e-6
    assert abs(pf.cash - (1_000_000.0 - fee)) < 1e-6


def test_equity_after_close_matches_realized_minus_fees():
    """平仓后权益 = 初始 + 已实现盈亏 - 双边手续费。"""
    pf = _portfolio()
    pf.update_price("RB", 4000.0)
    t1 = Trade(symbol="RB", direction=Direction.LONG, offset=Offset.OPEN,
               quantity=1, price=4000.0, datetime=None, order_id="p0-open2",
               multiplier=10.0)
    pf.process_trade(t1)
    pf.update_price("RB", 4100.0)
    t2 = Trade(symbol="RB", direction=Direction.SHORT, offset=Offset.CLOSE,
               quantity=1, price=4100.0, datetime=None, order_id="p0-close2",
               multiplier=10.0)
    pf.process_trade(t2)

    realized = pf.realized_pnl
    assert abs(realized - 1000.0) < 1e-6, "RB 乘数 10、涨 100 点应实现 1000 元"
    expected = 1_000_000.0 + realized - pf.total_commission
    assert abs(pf.equity() - expected) < 1e-6
    assert abs(pf.unrealized_pnl()) < 1e-9
    assert abs(pf.equity() - pf.cash) < 1e-6


def test_summary_has_consistent_figures():
    """summary() 必须可正常返回，且 cash/commission 字段与权益口径一致。"""
    pf = _portfolio()
    pf.update_price("RB", 4000.0)
    pf.process_trade(Trade(symbol="RB", direction=Direction.LONG, offset=Offset.OPEN,
                           quantity=1, price=4000.0, datetime=None,
                           order_id="p0-sum", multiplier=10.0))
    s = pf.summary()
    assert s["cash"] == round(pf.cash, 2)
    assert s["total_commission"] == round(pf.total_commission, 2)
    assert s["equity"] == round(pf.equity(), 2)
    assert s["realized_pnl"] == round(pf.realized_pnl, 2)


def test_risk_manager_margin_multiplies_contract_multiplier():
    """可用资金检查必须按「手数×价格×乘数×保证金率」估算保证金。

    旧实现漏乘乘数：5 手 RB 只算 5×4000×10% = 2000 元，
    新实现为 5×4000×10×10% = 20000 元；初始 1 万时应被拒绝。
    """
    pf = _portfolio(initial=10_000.0)
    pf.update_price("RB", 4000.0)
    rb = build_contract("RB")
    cfg = RiskConfig(max_total_position_ratio=2.0)  # 放大仓位比例，隔离可用资金检查
    rm = RiskManager(cfg)
    order = Order(symbol="RB", direction=Direction.LONG, offset=Offset.OPEN,
                  quantity=5, order_type=OrderType.MARKET, datetime=None,
                  order_id="p0-risk")
    ok, reason = rm.check_order(order, pf, contract=rb, dt=None)
    assert ok is False, "保证金 20000 > 可用 10000，必须拒单"
    assert "可用资金" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
