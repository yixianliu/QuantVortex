"""仿真经纪商：按当前价格即时撮合，用于无账号环境下的全链路验证。

与 BacktestBroker 的区别：委托立即成交（不等待下一根 bar），更贴近实时仿真。
实盘请替换为 data/ctp_gateway 中的真实 CTP 接口。
"""
from __future__ import annotations

from ..core.types import Direction, Order, OrderStatus, Trade
from .base import BrokerBase


class PaperBroker(BrokerBase):
    def __init__(self, slippage: float = 1.0, min_tick: float = 1.0, contracts: dict | None = None) -> None:
        self.slippage = slippage
        self.min_tick = min_tick
        self.contracts = contracts or {}

    def _tick(self, symbol: str) -> float:
        c = self.contracts.get(symbol)
        return c.min_price_tick if c else self.min_tick

    def submit(self, order: Order) -> None:
        # 实盘模式下 submit 通常直接发往接口；此处由引擎调用 fill_now 即时成交
        raise RuntimeError("PaperBroker 请使用 fill_now() 即时撮合。")

    def match(self, bar) -> list[Trade]:
        return []

    def fill_now(self, order: Order, price: float) -> list[Trade]:
        if price is None or price <= 0:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "无有效价格"
            return []
        tick = self._tick(order.symbol)
        fill = price + (self.slippage * tick if order.direction == Direction.LONG
                        else -self.slippage * tick)
        trade = Trade(
            symbol=order.symbol,
            direction=order.direction,
            offset=order.offset,
            quantity=order.quantity,
            price=round(fill, 4),
            datetime=order.datetime,
            order_id=order.order_id,
        )
        order.status = OrderStatus.FILLED
        order.filled_price = fill
        order.filled_quantity = order.quantity
        return [trade]
