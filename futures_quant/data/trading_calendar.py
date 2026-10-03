"""期货时段识别与交易日历。

M3.6：夜盘 21:00-02:30 跨日归属当日交易日，节假日剔除。
"""
from __future__ import annotations
from datetime import datetime, time
from typing import Set

# 简化节假日表
HOLIDAYS: Set[datetime] = {
    datetime(2026,1,1).date(),
}

def is_trading_time(dt: datetime) -> bool:
    t = dt.time()
    # 日盘 09:00-11:30, 13:30-15:00
    day1 = time(9,0) <= t <= time(11,30)
    day2 = time(13,30) <= t <= time(15,0)
    # 夜盘 21:00-02:30（跨日）
    night = time(21,0) <= t or t <= time(2,30)
    return day1 or day2 or night

def trading_day_for(dt: datetime) -> datetime.date:
    """返回该时间点归属的交易日。
    
    夜盘 21:00-次日02:30 归属前一日交易日。
    """
    if dt.time() >= time(21,0):
        return dt.date()
    if dt.time() <= time(2,30):
        # 归属前一日
        from datetime import timedelta
        return (dt - timedelta(days=1)).date()
    return dt.date()

def is_trading_day(d: datetime) -> bool:
    if isinstance(d, datetime):
        dval = d.date()
    else:
        dval = d
    if dval.weekday() >= 5:
        return False
    if dval in HOLIDAYS:
        return False
    return True
