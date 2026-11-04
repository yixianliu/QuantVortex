"""第二轮 P1-1 回归测试：换月映射与换月成本接入。

覆盖：
  - dominant.roll_transitions / continuous_symbol_map 输出主力切换事件
  - roll_cost.roll_cost_commission 双边手续费下限
  - Portfolio.apply_roll_cost 进入现金/权益
  - Backtester 换月日集合与 enable_roll_cost 开关
"""
from __future__ import annotations

import sys
import os
from datetime import date, datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from futures_quant.data.dominant import roll_transitions, continuous_symbol_map
from futures_quant.backtest.roll_cost import RollParams, roll_cost_commission
from futures_quant.core.portfolio import Portfolio
from futures_quant.backtest.backtester import Backtester


def test_roll_transitions():
    mapping = {
        date(2026, 1, 5): "RB2601",
        date(2026, 1, 6): "RB2601",
        date(2026, 1, 7): "RB2605",
        date(2026, 1, 8): "RB2610",
    }
    tr = roll_transitions(mapping)
    assert tr == [
        (date(2026, 1, 7), "RB2601", "RB2605"),
        (date(2026, 1, 8), "RB2605", "RB2610"),
    ]
    cmap = continuous_symbol_map(mapping)
    assert cmap[date(2026, 1, 7)] == "RB2605"


def test_roll_cost_commission():
    params = RollParams(commission_per_lot=3.0, multiplier=10)
    assert roll_cost_commission(2, params) == 12.0, "平旧+开新 = 2 × 3 × 2 手"
    assert roll_cost_commission(-2, params) == 12.0, "数量取绝对值"


def test_portfolio_applies_roll_cost():
    p = Portfolio(initial_capital=100_000)
    before = p.equity()
    p.apply_roll_cost(10.0)
    assert p.total_roll_cost == 10.0
    assert p.cash == 99_990.0
    assert p.equity() == before - 10.0


def _fake_bt(enabled: bool):
    bt = Backtester.__new__(Backtester)
    bt.enable_roll_cost = enabled
    return bt


def test_resolve_roll_dates_monthly_and_switch():
    records = [
        {"datetime": datetime(2026, 1, 2, 9, 0)},
        {"datetime": datetime(2026, 1, 20, 9, 0)},
        {"datetime": datetime(2026, 2, 2, 9, 0)},
    ]
    dates = Backtester._resolve_roll_dates(_fake_bt(True), records, None)
    assert dates == {date(2026, 1, 2), date(2026, 2, 2)}, "每月首个有行情交易日"
    assert Backtester._resolve_roll_dates(_fake_bt(False), records, None) == set(), \
        "enable_roll_cost=False 时应完全关闭"


def test_resolve_roll_dates_prefers_explicit_schedule():
    bt = _fake_bt(True)
    dates = Backtester._resolve_roll_dates(
        bt, [{"datetime": datetime(2026, 1, 5, 9, 0)}], {date(2026, 1, 5): ("RB2601", "RB2605")})
    assert dates == {date(2026, 1, 5)}
