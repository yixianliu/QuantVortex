"""第二轮 P0-2 回归测试：速览/资金流统一为「当日口径」。

旧实现问题：
  - 涨跌幅基准 = 窗口首根（get_quote 用上一根，panorama 用首根）
  - OI 变化 = 半窗口
  - 资金流 = 半窗口 / 30 根累计
本测试用「窗口首根远低于当日」的数据，证明新口径只认上一交易日收盘。
"""
from __future__ import annotations

import sys
import os
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from futures_quant.data.market_data import daily_snapshot, trading_day_key


def _frame(rows):
    return pd.DataFrame([
        {"datetime": pd.Timestamp(t), "open": o, "high": max(o, c), "low": min(o, c),
         "close": c, "volume": v, "open_interest": oi}
        for t, o, c, v, oi in rows
    ])


def test_daily_change_uses_prev_trading_day_not_window_first():
    # 窗口首根 90，上一交易日收盘 105，当日收盘 108
    df = _frame([
        ("2026-01-05 09:00", 90, 90.5, 10, 1000),
        ("2026-01-06 09:00", 104, 105, 20, 1300),
        ("2026-01-07 09:00", 106, 108, 30, 1500),
    ])
    snap = daily_snapshot(df, mult=10)
    assert snap["last"] == 108.0
    assert snap["prev_close"] == 105.0, "基准必须是上一交易日收盘，不是窗口首根 90"
    assert abs(snap["chg_pct"] - (108 / 105 - 1) * 100) < 1e-9
    assert snap["has_prev_day"] is True


def test_oi_and_fund_flow_are_daily_only():
    df = _frame([
        ("2026-01-05 09:00", 90, 91, 10, 1000),
        ("2026-01-06 09:00", 104, 105, 20, 1300),
        ("2026-01-07 09:00", 106, 107, 30, 1500),
        ("2026-01-07 14:00", 107, 108, 40, 1600),
    ])
    snap = daily_snapshot(df, mult=10)
    # OI：当日最后 1600 vs 上一交易日最后 1300（不是半窗口 OI）
    assert snap["oi_now"] == 1600.0
    assert snap["oi_prev"] == 1300.0
    assert abs(snap["oi_chg_pct"] - (1600 / 1300 - 1) * 100) < 1e-9
    # 资金流只累计最后一个交易日：(107-106)*30*10 + (108-107)*40*10 = 300+400=700 元
    assert abs(snap["fund_flow"] - 700 / 1e8) < 1e-12
    assert snap["volume_day"] == 70.0, "当日成交量应只累计当日，不是 30 根累计"


def test_night_session_belongs_to_next_trading_day():
    assert trading_day_key(pd.Timestamp("2026-01-05 21:00")) == pd.Timestamp("2026-01-06").date()
    assert trading_day_key(pd.Timestamp("2026-01-06 01:30")) == pd.Timestamp("2026-01-06").date()
    assert trading_day_key(pd.Timestamp("2026-01-06 15:00")) == pd.Timestamp("2026-01-06").date()


def test_night_session_no_fake_change():
    # 1/6 日盘收 105；1/6 夜盘（属 1/7 交易日）开 200 是不同交易时段，
    # 当日涨跌幅应对比 1/6 日盘收盘 105，而不是夜盘内部上一根。
    df = _frame([
        ("2026-01-06 09:00", 104, 105, 20, 1300),
        ("2026-01-06 21:00", 200, 201, 5, 1350),
    ])
    snap = daily_snapshot(df, mult=10)
    assert snap["prev_close"] == 105.0
    assert abs(snap["chg_pct"] - (201 / 105 - 1) * 100) < 1e-9


def test_holiday_gap_uses_last_available_trading_day():
    # 1/9 之后直接跳到 1/12（周末/休市），基准仍是 1/9，不产生跨日假涨跌
    df = _frame([
        ("2026-01-08 15:00", 104, 105, 20, 1300),
        ("2026-01-09 15:00", 105, 107, 25, 1350),
        ("2026-01-12 09:00", 107, 108, 30, 1400),
    ])
    snap = daily_snapshot(df, mult=10)
    assert snap["prev_close"] == 107.0
    assert abs(snap["chg_pct"] - (108 / 107 - 1) * 100) < 1e-9


def test_single_day_has_no_prev():
    df = _frame([("2026-01-07 09:00", 106, 108, 30, 1500)])
    snap = daily_snapshot(df, mult=10)
    assert snap["has_prev_day"] is False
    assert snap["chg_pct"] == 0.0
    assert snap["prev_close"] is None
