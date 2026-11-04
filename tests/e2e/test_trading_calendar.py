"""M3.6 期货时段识别验收"""
from __future__ import annotations
import sys, os
from datetime import datetime
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.data.trading_calendar import trading_day_for, is_trading_time, is_trading_day

def test_trading_calendar():
    dt_night = datetime(2026,1,2,22,30)
    assert trading_day_for(dt_night) == datetime(2026,1,2).date()
    dt_early = datetime(2026,1,3,1,30)
    assert trading_day_for(dt_early) == datetime(2026,1,2).date()
    assert is_trading_time(datetime(2026,1,2,10,0)) is True
    assert is_trading_time(datetime(2026,1,2,12,0)) is False
    assert is_trading_day(datetime(2026,1,1)) is False  # 节假日
    print("test_trading_calendar.py 全绿")

if __name__=="__main__":
    test_trading_calendar()
