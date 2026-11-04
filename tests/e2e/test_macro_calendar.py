"""M8.4 宏观事件日历 e2e：CPI/PMI/FOMC/政策日历 + 事件前后 3 日波动率放大标记。"""
from __future__ import annotations

import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.data.macro_calendar import (  # noqa: E402
    MacroCalendar,
    MacroEvent,
    mark_vol_amplification,
    vol_amplification_ratio,
)


def main() -> int:
    # --- 日历生成 ---
    cal = MacroCalendar(2026)
    df = cal.to_frame()
    assert {"date", "name", "category", "impact"}.issubset(df.columns)
    # 每年至少 24 个事件（CPI 12 + PMI 12 + FOMC 4 + 政策 2 = 30）
    assert len(df) >= 24, f"事件数过少: {len(df)}"
    print(f"[OK] 2026 日历事件数={len(df)}")

    # 事件去重排序
    dates = df["date"].tolist()
    assert dates == sorted(dates), "日历未排序"
    print("[OK] 日历排序")

    # is_event_day / events_on
    d_cpi = dt.date(2026, 1, 10)
    assert cal.is_event_day(d_cpi)
    evts = cal.events_on(d_cpi)
    assert any(e.name == "CPI 中国" for e in evts)
    print(f"[OK] events_on({d_cpi}) = {[e.name for e in evts]}")

    # within_impact_window
    assert cal.within_impact_window(d_cpi)
    assert cal.within_impact_window(d_cpi + dt.timedelta(days=2))  # CPI impact=2
    assert not cal.within_impact_window(d_cpi + dt.timedelta(days=5))
    print("[OK] impact_window")

    # --- 波动率放大标记 ---
    rng = np.random.default_rng(2026)
    n = 250
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    # 在事件日制造波动放大（模拟事件冲击）
    rets = rng.normal(0, 0.01, n)
    # CPI 日（1 月 10 日）附近放大波动
    for i, ts in enumerate(idx):
        if ts.date() in (dt.date(2026, 1, 10), dt.date(2026, 1, 13), dt.date(2026, 1, 14)):
            rets[i] += abs(rng.normal(0, 0.03))
    close = 100 * np.cumprod(1 + rets)
    close = pd.Series(close, index=idx)

    marked = mark_vol_amplification(close, cal, lookback=3)
    assert not marked.empty
    assert {"close", "ret", "vol", "vol_amplified", "event_name"}.issubset(marked.columns)
    # 事件日 event_name 非空
    event_days = marked[marked["event_name"] != ""]
    assert len(event_days) >= 1, "应有事件日标记"
    print(f"[OK] marked 列={list(marked.columns)} event_days={len(event_days)}")

    # vol_amplified 应有部分 True
    assert marked["vol_amplified"].any(), "应有波动放大标记"
    print(f"[OK] vol_amplified 触发数={int(marked['vol_amplified'].sum())}")

    # 放大倍数
    ratio = vol_amplification_ratio(close, cal, lookback=3)
    assert ratio > 0
    print(f"[OK] 事件窗口波动放大倍数={ratio:.2f}x")

    # 空数据 → 空 DataFrame
    empty = mark_vol_amplification(pd.Series(dtype=float), cal, lookback=3)
    assert empty.empty
    print("[OK] 空 close -> 空 DataFrame")

    # 自定义事件
    my_cal = MacroCalendar(2026, events=[
        MacroEvent("自定义事件", "policy", dt.date(2026, 5, 15), impact=3),
    ])
    assert my_cal.is_event_day(dt.date(2026, 5, 15))
    assert not my_cal.is_event_day(dt.date(2026, 1, 10))
    print("[OK] 自定义事件日历")

    print("ALL-OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
