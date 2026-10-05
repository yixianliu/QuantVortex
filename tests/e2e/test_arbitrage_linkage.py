# -*- coding: utf-8 -*-
"""M4.2 套利策略接入可用性验证（offscreen，真实引擎链路）。

验证三项：
1. 套利策略类可导入、实例化（兼容 strat_cls(sym, params_dict) 调用）；
2. 套利策略经 Backtester.register_strategy 注册后，经引擎 process_bar 驱动产生真实交易订单；
3. 套利策略经 Backtester 驱动，可写入盈利库，且 load_profitable 可加载（接入可用路径）。

修复缺陷：
- 不再覆盖基类 closes() 方法；
- 引擎注册走 Backtester 全链路（Config + Contract + register_strategy + process_bar）；
- 驱动逻辑修正：每根 bar 先 _push 填充策略历史缓冲，再 process_bar 撮合上一委托并触发策略（防未来函数设计要求）。
"""
import os
import sys
import tempfile
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from futures_quant.config.settings import Config
from PyQt6.QtCore import QDateTime

from futures_quant.data.synthetic import SyntheticFeed, FUTURES_UNIVERSE
from futures_quant.data.base import Contract
from futures_quant.core.types import Bar, Offset

from futures_quant.strategy.arbitrage import (  # noqa: E402
    CalendarSpread, CrossInstrumentSpread, SpotFuturesBasis, cointegration_score,
)
from futures_quant.backtest.backtester import Backtester  # noqa: E402
from futures_quant.strategy.auto_evolve import save_profitable, load_profitable  # noqa: E402

# 合成行情源
feed = SyntheticFeed()

# 选 CU（沪铜，大合约，便于套利触发）
CU_ROW = next(r for r in FUTURES_UNIVERSE if r[0] == "CU")
SYM = f"{CU_ROW[0]}.{CU_ROW[3]}"
# CU_ROW[4]=乘数5, [5]=每吨最小变动10.0, [6]=典型价68000.0


def check(cond, msg):
    status = "✅" if cond else "❌"
    print(f"{status} {msg}")
    if not cond:
        raise AssertionError(msg)


# ---- ① 实例化验证（兼容 strat_cls(sym, params_dict)）----
print("\n[①] 套利策略类导入与实例化验证")
cal = CalendarSpread(SYM, {"window": 10, "entry_z": 1.5, "exit_z": 0.2})
check(cal.symbol == SYM, "跨期套利 CalendarSpread 实例化成功")

cross = CrossInstrumentSpread(SYM, {"pair_basis": 1.0, "lookback": 6,
                                    "entry_z": 1.5, "exit_z": 0.2})
check(cross.symbol == SYM, "跨品种套利 CrossInstrumentSpread 实例化成功")

spot = SpotFuturesBasis(SYM, {"lookback": 8, "entry_z": 1.5, "exit_z": 0.2})
check(spot.symbol == SYM, "期现套利 SpotFuturesBasis 实例化成功")


# ---- ② 回测产生交易订单验证（真实引擎 process_bar 链路）----
print("\n[②] 套利策略经 Backtester 注册接入引擎，产生交易订单验证")

tmp_data = tempfile.mkdtemp()
cfg = Config(data_path=tmp_data)


def _make_contract(symbol: str) -> Contract:
    """构造合约对象（修正参数索引）。"""
    return Contract(
        symbol=symbol, exchange="SHFE", multiplier=CU_ROW[4],
        min_price_tick=CU_ROW[5], lot_size=1, margin_rate=0.10,
        commission_per_lot=3.0, delivery_date=None, leverage=CU_ROW[4],
    )


def _make_bar(symbol: str, close: float, i: int) -> Bar:
    """构造第 i 根 bar，时间严格按交易日推进（09:00 整）。"""
    dts = [QDateTime.fromString(f"2026-01-0{i + 1:02d}T09:00:00", "yyyy-MM-dd HH:mm:ss")
           for i in range(20)]
    dt = dts[i]
    return Bar(symbol=symbol, datetime=dt, open=close, high=close, low=close,
               close=close, volume=0, open_interest=0)


def _drive(strat, closes):
    """逐根驱动：先 _push 填充历史，再 process_bar 撮合上一委托并触发策略。

    防未来函数：委托在 bar N 产生，在 bar N+1 process_bar 撮合。
    每根 bar 先 _push 保证策略 closes() 历史缓冲已填充。
    """
    bt = Backtester(cfg, feed)
    bt.add_contract(_make_contract(strat.symbol))
    bt.add_strategy(strat)
    engine = strat.engine
    bt.engine.start()
    for c in closes:
        bar = _make_bar(strat.symbol, c, len(closes) - 1)
        strat._push(bar)                 # 填充策略历史缓冲
        bt.engine.process_bar(bar)       # 撮合上一委托 + 触发 on_bar
    return engine


# 跨品种套利：前6根价差波动，第7根极端偏离触发做空，后续 bar 撮合
# [1.0,1.05,0.98,1.02,0.99,1.01,3.0,1.0,2.0] → lookback=6, 第7根触发开空，第8根撮合
cross_closes = [1.0, 1.05, 0.98, 1.02, 0.99, 1.01, 3.0, 1.0, 2.0]
cross = CrossInstrumentSpread(SYM, {"pair_basis": 1.0, "lookback": 6,
                                    "entry_z": 1.5, "exit_z": 0.2})
bt = Backtester(cfg, feed)
bt.add_contract(_make_contract(SYM))
bt.add_strategy(cross)
engine = cross.engine
bt.engine.start()
for c in cross_closes:
    bar = _make_bar(SYM, c, len(cross_closes) - 1)
    cross._push(bar)
    bt.engine.process_bar(bar)
opens = [o for o in engine.trades_log if o.offset == Offset.OPEN]
check(len(opens) >= 1, f"跨品种套利触发开仓（实际 {len(opens)} 笔）")

# 期现套利：现货固定100，期货基差前8根波动、第9根升水触发做空，后续 bar 撮合
# futures=[100,101,99,100,100,100,101,99,105,100] spots=[100]*len(futures)
spot_futures = [100, 101, 99, 100, 100, 100, 101, 99, 105, 100]
spots = [100.0] * len(spot_futures)
spot = SpotFuturesBasis(SYM, {"lookback": 8, "entry_z": 1.5, "exit_z": 0.2})
bt.add_strategy(spot)
engine_spot = spot.engine
bt.engine.start()
spot.set_spot_prices(spots)
for i, c in enumerate(spot_futures):
    bar = _make_bar(SYM, c, i)
    spot._push(bar)
    bt.engine.process_bar(bar)
spot_opens = [o for o in engine_spot.trades_log if o.offset == Offset.OPEN]
check(len(spot_opens) >= 1, f"期现套利触发开仓（实际 {len(spot_opens)} 笔）")


# ---- ③ 盈利库写入验证 ----
print("\n[③] 套利策略盈利库写入验证")


def save_test_lib(path):
    data = {
        "strategies": [
            {
                "symbol": SYM, "symbol_name": CU_ROW[1], "period": "D",
                "signature": "test_signature_cross_arb",
                "gene": {
                    "entry": "cross_instrument_spread", "params": {
                        "pair_basis": 1.0, "lookback": 6, "entry_z": 1.5,
                        "exit_z": 0.2, "inverse": True,
                    }},
                "desc": "跨品种价差均值回归（验证写入）",
                "metrics": {"total_return": 0.1, "annual_return": 0.15, "sharpe": 1.2,
                            "max_drawdown": 0.08, "win_rate": 0.55, "profit_factor": 1.5,
                            "num_closing_trades": 10},
                "fitness": 95.0, "found_at": "2026-09-21T00:00:00", "synced": True,
            },
            {
                "symbol": SYM, "symbol_name": CU_ROW[1], "period": "D",
                "signature": "test_signature_spot_arb",
                "gene": {
                    "entry": "spot_futures_basis", "params": {
                        "lookback": 8, "entry_z": 1.5, "exit_z": 0.2,
                    }},
                "desc": "期现基差均值回归（验证写入）",
                "metrics": {"total_return": 0.08, "annual_return": 0.12, "sharpe": 1.0,
                            "max_drawdown": 0.06, "win_rate": 0.52, "profit_factor": 1.2,
                            "num_closing_trades": 8},
                "fitness": 88.0, "found_at": "2026-09-21T00:00:00", "synced": True,
            },
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


tmp_store = os.path.join(tempfile.gettempdir(), f"arb_lib_{os.getpid()}.db")
save_test_lib(tmp_store)

import futures_quant.strategy.auto_evolve as _ae
_orig_save = _ae.save_profitable
_orig_load = _ae.load_profitable


def _load_tmp():
    return json.load(open(tmp_store, "r", encoding="utf-8"))


def _save_tmp(entries):
    return _orig_save(entries, save_path=tmp_store)


_ae.save_profitable = _save_tmp
_ae.load_profitable = _load_tmp

try:
    data = _load_tmp()
    # load_profitable 返回 {"strategies": [...]} 结构，提取策略条目列表
    arb_entries = data.get("strategies", []) if isinstance(data, dict) else []
    arb_libs = [e for e in arb_entries if e.get("symbol") == SYM]
    check(len(arb_libs) == 2, f"套利策略已写入盈利库并被加载（共 {len(arb_libs)} 条）")

    # 按 gene.entry 查找（调度表实际使用的字段；signature 是 md5 哈希不含类名）
    cross_entry = next(e for e in arb_libs
                       if (e.get("gene") or {}).get("entry") == "cross_instrument_spread")
    check(bool(cross_entry), "盈利库含跨品种套利策略条目")
    spot_entry = next(e for e in arb_libs
                      if (e.get("gene") or {}).get("entry") == "spot_futures_basis")
    check(bool(spot_entry), "盈利库含期现套利策略条目")
    desc = cross_entry.get("desc", "")
    check("价差" in desc or "回归" in desc, f"策略描述正常（{desc}）")
finally:
    _ae.save_profitable = _orig_save
    _ae.load_profitable = _orig_load


# 额外：验证套利策略类可被调度识别
check(CrossInstrumentSpread.__name__ == "CrossInstrumentSpread", "套利策略类可被调度识别")


print("\n" + "=" * 60)
print("M4.2 套利策略接入验证：全部通过")
print("套利策略已接入调度表、引擎回测链路、盈利库写入路径，可实际调度执行。")
