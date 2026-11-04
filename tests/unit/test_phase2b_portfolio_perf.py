"""第二轮性能优化（P0+P1）回归测试。

覆盖两类风险点：
    1) 同 bar 复用权益：``available(eq)`` / ``risk_degree(eq)`` 与自算版本逐位相等，
       且持仓/价格变化后重新取权益仍得到正确风险度；
    2) 缓存不失效：合约对象被替换、账户级默认值变更后 ``_spec`` 缓存必须重建，
       多品种各自命中自己的乘数/保证金率；``_trading_day_key`` 的 lru_cache
       结果与直接计算一致，且实例调用与类调用等价。
"""
from __future__ import annotations

import sys
import os
from datetime import date, datetime, timedelta

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.core.portfolio import Portfolio
from futures_quant.core.types import Direction, Offset, Trade
from futures_quant.data.contract_specs import build_contract


def _make_portfolio(contracts=None, **kw) -> Portfolio:
    """构造测试用组合（默认 100 万初始资金、账户级 10% 保证金、每手 3 元手续费）。"""
    return Portfolio(initial_capital=1_000_000.0, margin_rate=0.10,
                     commission_per_lot=3.0, multiplier=10.0,
                     close_today_ratio=0.5, contracts=contracts or {}, **kw)


def _open(pf: Portfolio, symbol: str, qty: int, price: float, mult: float = 10.0) -> None:
    """开多仓并标记到市价（mult 显式传入，避免 Trade 默认乘数干扰）。"""
    pf.process_trade(Trade(symbol=symbol, direction=Direction.LONG, offset=Offset.OPEN,
                           quantity=qty, price=price, datetime=None, multiplier=mult))
    pf.update_price(symbol, price)


def test_available_and_risk_degree_reuse_equity_bit_identical():
    """同 bar 传入的权益与自算权益必须得到完全相同的可用资金/风险度。"""
    contracts = {"RB": build_contract("RB"), "IF": build_contract("IF")}
    pf = _make_portfolio(contracts)
    _open(pf, "RB", 3, 4000.0)
    _open(pf, "IF", 1, 5000.0, mult=300.0)

    eq = pf.equity()
    # 逐位相等（同一组运算数，不存在舍入差异）
    assert pf.available(eq) == pf.available()
    assert pf.risk_degree(eq) == pf.risk_degree()
    # 显式传入的路径确实复用了外部权益：与用「错误权益」得到的结果可区分
    assert pf.risk_degree(eq + 1.0) != pf.risk_degree(eq)


def test_risk_degree_correct_after_position_and_price_change():
    """持仓/价格变化后，用当根重新计算的权益求风险度仍然正确（复用不会读旧值）。"""
    contracts = {"RB": build_contract("RB")}
    pf = _make_portfolio(contracts)
    _open(pf, "RB", 1, 4000.0)
    rd_first = pf.risk_degree(pf.equity())

    # 加仓 + 价格上移：占用保证金与权益同时变化
    _open(pf, "RB", 20, 4200.0)
    eq = pf.equity()
    used = pf.used_margin()
    rt = pf.risk_degree(eq)
    assert rt == used / eq
    assert rt > rd_first
    # 自算路径仍等价
    assert rt == pf.risk_degree()


def test_spec_cache_invalidates_when_contract_replaced():
    """替换合约对象后缓存必须重建，不能沿用旧乘数/保证金率。"""
    c1 = build_contract("RB")
    contracts = {"RB": c1}
    pf = _make_portfolio(contracts)
    _open(pf, "RB", 2, 4000.0)
    used1 = pf.used_margin()
    assert pf._spec("RB")[0] is c1           # 命中缓存
    assert pf._spec("RB") is pf._spec("RB") # 返回同一缓存元组

    # 换了一个乘数翻倍的合约（模拟换月/重注册）
    c2 = build_contract("RB", multiplier=float(c1.multiplier) * 2)
    contracts["RB"] = c2
    used2 = pf.used_margin()
    assert abs(used2 - used1 * 2) < 1e-6
    assert pf._spec("RB")[0] is c2
    assert abs(pf._multiplier("RB") - float(c1.multiplier) * 2) < 1e-9


def test_spec_cache_invalidates_when_account_default_changes():
    """账户级默认参数变更（未知合约回落路径）也必须让缓存重建。"""
    pf = _make_portfolio()
    _open(pf, "UNKNOWN", 1, 100.0, mult=10.0)
    used_before = pf.used_margin()           # 默认 10% 保证金
    # 账户级默认保证金率上调到 20%
    pf.margin_rate = 0.20
    used_after = pf.used_margin()
    assert abs(used_after - used_before * 2) < 1e-6

    # 手续费默认值变更同样生效（成交时取缓存之外的实时默认值）
    pf2 = _make_portfolio()
    _open(pf2, "UNKNOWN", 1, 100.0, mult=10.0)
    pf2.commission_per_lot = 6.0
    pf2.process_trade(Trade(symbol="UNKNOWN", direction=Direction.LONG, offset=Offset.OPEN,
                            quantity=1, price=100.0, datetime=None, multiplier=10.0))
    assert pf2.trade_history[-1].commission == 6.0


def test_multi_symbol_uses_own_multiplier_and_margin_rate():
    """多品种缓存互不串味：每个品种用自己的乘数/保证金率。"""
    rb, if_ = build_contract("RB"), build_contract("IF")
    contracts = {"RB": rb, "IF": if_}
    pf = _make_portfolio(contracts)
    _open(pf, "RB", 2, 4000.0)
    _open(pf, "IF", 1, 5000.0, mult=float(if_.multiplier))

    expected = (2 * 4000.0 * float(rb.multiplier) * float(rb.margin_rate)
                + 1 * 5000.0 * float(if_.multiplier) * float(if_.margin_rate))
    assert abs(pf.used_margin() - expected) < 1e-6
    assert pf._multiplier("RB") == float(rb.multiplier)
    assert pf._multiplier("IF") == float(if_.multiplier)
    # 未注册合约回落账户默认值
    assert pf._multiplier("CU") == 10.0


def _ref_trading_day_key(dt):
    """参考实现（与 Backtester._trading_day_key 改动前逻辑逐行一致）。"""
    if getattr(dt, "hour", 0) >= 18:
        return (dt + timedelta(days=1)).date()
    return dt.date() if hasattr(dt, "date") else dt


def test_trading_day_key_cache_matches_direct_and_instance_call():
    """lru_cache 结果与直接计算一致；类调用与实例调用都只接收一个时间参数。"""
    from futures_quant.backtest.backtester import Backtester

    samples = [
        datetime(2026, 1, 2, 9, 0),
        datetime(2026, 1, 2, 17, 59),
        datetime(2026, 1, 2, 18, 0),
        datetime(2026, 1, 2, 0, 0),
        datetime(2026, 1, 5, 20, 30),
        date(2026, 1, 2),
    ]
    for dt in samples:
        assert Backtester._trading_day_key(dt) == _ref_trading_day_key(dt)

    # 实例调用（staticmethod 包 lru_cache，不应把 self 当参数）
    inst = object.__new__(Backtester)
    for dt in samples:
        assert inst._trading_day_key(dt) == _ref_trading_day_key(dt)

    # 同一时间戳第二次调用应命中缓存
    hits_before = Backtester._trading_day_key.cache_info().hits
    Backtester._trading_day_key(samples[0])
    Backtester._trading_day_key(samples[0])
    assert Backtester._trading_day_key.cache_info().hits >= hits_before + 1
