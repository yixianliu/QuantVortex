"""经纪商接口基类。

经纪商负责把引擎发出的委托撮合成交，返回 Trade 列表。
- BacktestBroker：回测用，委托在下一根 bar 开盘撮合（防未来函数）；
- PaperBroker   ：仿真 / 实盘用，按当前价格即时撮合（含滑点）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.types import Order, Trade


class BrokerBase(ABC):
    @abstractmethod
    def submit(self, order: Order) -> None:
        """接收委托（回测中入队，实盘中发往接口）。"""

    @abstractmethod
    def match(self, bar) -> list[Trade]:
        """撮合并返回成交（回测按 bar 调用；实盘无需）。"""
