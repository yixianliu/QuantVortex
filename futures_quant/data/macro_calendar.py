"""M8.4 宏观事件日历：CPI / PMI / 美联储议息 / 国内政策发布日历，事件前后 3 日波动率放大标记。

设计：
- 内置常见宏观事件（可按需扩展 ``events`` 列表）：
    - CPI（月度，通常为每月 9-15 日）
    - PMI（月度，月末或次月初）
    - 美联储议息（FOMC，季度 8 次，3/6/9/12 月末）
    - 国内重要政策窗口（两会、政治局会议、国常会等）
- ``MacroCalendar(year)`` 生成该年度事件日历 DataFrame。
- ``mark_vol_amplification(close, lookback_days=3)`` 标记事件日及前后 N 日
  的波动率放大（相对常态 σ 的倍数 >1 即放大）。
- 数据缺失时优雅降级（返回空 DataFrame），不阻塞主流程。

防未来函数：波动率放大标记只用事件日及之前数据。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

__all__ = ["MacroEvent", "MacroCalendar", "mark_vol_amplification", "DEFAULT_EVENTS"]

# 事件定义：(名称, 类别, 发生规律)
DEFAULT_EVENTS: List[MacroEvent] = []


@dataclass
class MacroEvent:
    """宏观事件。"""
    name: str
    category: str        # macro / policy / central_bank / release
    date: dt.date
    impact: int = 3      # 影响窗口（前后 N 日）


class MacroCalendar:
    """宏观事件日历。

    参数:
        year: 事件所在年份（int）。
        events: 自定义事件列表，None 用默认（内置常见事件生成器）。
    """

    def __init__(self, year: int, events: Optional[List[MacroEvent]] = None) -> None:
        self.year = year
        self.events = events if events is not None else _build_default_events(year)

    def to_frame(self) -> pd.DataFrame:
        """返回事件 DataFrame（date / name / category / impact）。"""
        rows = [
            {"date": e.date, "name": e.name, "category": e.category, "impact": e.impact}
            for e in sorted(self.events, key=lambda x: x.date)
        ]
        return pd.DataFrame(rows)

    def events_on(self, d: dt.date) -> List[MacroEvent]:
        """返回指定日期的事件列表。"""
        return [e for e in self.events if e.date == d]

    def is_event_day(self, d: dt.date) -> bool:
        return any(e.date == d for e in self.events)

    def within_impact_window(self, d: dt.date) -> bool:
        """d 是否在任一事件的影响窗口内（事件日 ± impact）。"""
        for e in self.events:
            delta = (d - e.date).days
            if -e.impact <= delta <= e.impact:
                return True
        return False


def _build_default_events(year: int) -> List[MacroEvent]:
    """生成一年度的常见宏观事件日历。

    说明：此处为示例占位，实际应来自 config/macro_calendar.json 或外部数据源。
    - CPI：每月 10 日（中国发布日近似）
    - PMI：每月 1 日（中国 50 强制造业 PMI 发布日）
    - FOMC：3/6/9/12 月最后一周的周三（近似用月末）
    - 两会：3 月 5 日
    - 政治局会议：7 月（年中经济分析会）
    """
    evts: List[MacroEvent] = []
    # CPI 每月 10 日
    for m in range(1, 13):
        evts.append(MacroEvent("CPI 中国", "release", dt.date(year, m, 10), impact=2))
    # PMI 每月 1 日
    for m in range(1, 13):
        evts.append(MacroEvent("PMI 中国 50 强", "release", dt.date(year, m, 1), impact=2))
    # FOMC 季度（3/6/9/12 月最后一日，安全处理 12 月）
    for m in (3, 6, 9, 12):
        if m < 12:
            last_day = dt.date(year, m + 1, 1) - dt.timedelta(days=1)
        else:
            last_day = dt.date(year, 12, 31)
        evts.append(MacroEvent("FOMC 美联储议息", "central_bank", last_day, impact=3))
    # 两会
    evts.append(MacroEvent("全国两会", "policy", dt.date(year, 3, 5), impact=5))
    # 政治局年中经济分析会
    evts.append(MacroEvent("政治局年中会议", "policy", dt.date(year, 7, 30), impact=5))
    return evts


def mark_vol_amplification(
    close: pd.Series,
    calendar: MacroCalendar,
    lookback: int = 3,
) -> pd.DataFrame:
    """标记事件日及前后 N 日的波动率放大。

    参数:
        close: 收盘价序列（DatetimeIndex）。
        calendar: 宏观事件日历。
        lookback: 影响窗口（前后 N 日，默认 3）。

    返回:
        DataFrame，含列：
        - close
        - ret（日收益率）
        - vol（滚动 20 日 std，年化 ×√252）
        - vol_amplified（bool，事件窗口内且 vol 高于 20 日均值 → True）
        - event_name（当日事件名，无则空）
    """
    if close is None or len(close) < lookback + 1:
        return pd.DataFrame()

    c = close.astype(float)
    ret = c.pct_change()
    vol = ret.rolling(20, min_periods=5).std() * np.sqrt(252.0)
    vol_mean = vol.rolling(60, min_periods=1).mean()

    out = pd.DataFrame({
        "close": c,
        "ret": ret,
        "vol": vol,
        "vol_amplified": (vol > vol_mean).astype(bool),
        "event_name": "",
    }, index=c.index)

    # 标记事件窗口
    evts_by_date: Dict[dt.date, List[str]] = {}
    for e in calendar.events:
        evts_by_date.setdefault(e.date, []).append(e.name)
    for i, ts in enumerate(out.index):
        d = ts.date() if hasattr(ts, "date") else ts
        names = evts_by_date.get(d, [])
        if names:
            out.loc[i, "event_name"] = ";".join(names)
        # 事件窗口内
        in_window = calendar.within_impact_window(d)
        if in_window:
            out.loc[i, "vol_amplified"] = True
    return out


def vol_amplification_ratio(close: pd.Series, calendar: MacroCalendar, lookback: int = 3) -> float:
    """事件窗口日均值 vol / 非窗口日均值 vol（放大倍数）。

    返回：
        放大倍数（>1 表示事件窗口波动放大）。无窗口或数据不足时返回 1.0。
    """
    df = mark_vol_amplification(close, calendar, lookback=lookback)
    if df.empty:
        return 1.0
    mask = df["vol_amplified"].to_numpy().astype(bool)
    in_win = df.index[mask]
    out_win = df.index[~mask]
    vol = df["vol"].dropna()
    in_vol = vol.loc[in_win.intersection(vol.index)]
    out_vol = vol.loc[out_win.intersection(vol.index)]
    if in_vol.empty or out_vol.empty:
        return 1.0
    ratio = float(in_vol.mean() / out_vol.mean()) if out_vol.mean() > 0 else 1.0
    return max(ratio, 0.0)
