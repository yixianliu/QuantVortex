"""统计套利策略子包（M4.2）。

- CalendarSpread        跨期套利（近月/远月价差 Z-score）
- CrossInstrumentSpread 跨品种套利（配对价差均值回归，RB-I 风格）
- SpotFuturesBasis      期现套利（基差均值回归）
"""
from .calendar_spread import CalendarSpread
from .cross_instrument import CrossInstrumentSpread, cointegration_score
from .spot_futures import SpotFuturesBasis

__all__ = [
    "CalendarSpread",
    "CrossInstrumentSpread",
    "SpotFuturesBasis",
    "cointegration_score",
]