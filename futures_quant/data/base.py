"""数据层基类：合约定义、历史行情源、实时网关接口。

- Contract：期货合约参数（乘数、最小变动价位、保证金率等），用于订单合法性校验。
- DataFeed：历史 K 线数据源（回测用）。
- Gateway ：实时行情 / 交易网关（仿真 / CTP 实盘用）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

import pandas as pd

from ..core.types import Bar


class Contract:
    """期货合约基础参数。"""

    def __init__(
        self,
        symbol: str,
        exchange: str,
        multiplier: float = 10.0,
        min_price_tick: float = 1.0,
        lot_size: int = 1,
        margin_rate: float = 0.10,
        commission_per_lot: float = 3.0,
        trading_hours: Optional[list] = None,
    ) -> None:
        self.symbol = symbol
        self.exchange = exchange
        self.multiplier = multiplier
        self.min_price_tick = min_price_tick
        self.lot_size = lot_size
        self.margin_rate = margin_rate
        self.commission_per_lot = commission_per_lot
        # 交易时段，如 [("09:00","10:15"),("10:30","11:30"),("13:30","15:00"),("21:00","23:00")]
        self.trading_hours = trading_hours or []

    def round_price(self, price: float) -> float:
        """将价格对齐到最小变动价位。"""
        tick = self.min_price_tick
        return round(price / tick) * tick


class DataFeed(ABC):
    """历史行情源（回测）。"""

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        start: str,
        end: str,
        period: str = "1m",
        limit: int = 0,
    ) -> pd.DataFrame:
        """返回列：[datetime, open, high, low, close, volume, open_interest]。"""


class Gateway(ABC):
    """实时行情 / 交易网关（仿真或 CTP）。"""

    def __init__(self) -> None:
        self.on_bar: Optional[Callable[[Bar], None]] = None
        self.on_trade: Optional[Callable] = None
        self.on_log: Optional[Callable[[str], None]] = None

    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def subscribe(self, symbol: str) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...
