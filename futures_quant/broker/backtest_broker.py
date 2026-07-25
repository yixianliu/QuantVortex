"""回测经纪商：委托在下一根 bar 开盘价撮合（杜绝未来函数）。

滑点：开多/平空在开盘价 + slippage*min_tick；开空/平多在开盘价 - slippage*min_tick。
限价单：若本根 bar 开盘价不满足限价，则该 bar 不成交（简化处理）。
"""
from __future__ import annotations

from ..core.types import Direction, Order, OrderStatus, OrderType, Trade
from .base import BrokerBase


class BacktestBroker(BrokerBase):
    def __init__(self, slippage: float = 1.0, min_tick: float = 1.0, contracts: dict | None = None) -> None:
        self.slippage = slippage
        self.min_tick = min_tick
        self.contracts = contracts or {}
        self.pending: list[Order] = []

    def _tick(self, symbol: str) -> float:
        c = self.contracts.get(symbol)
        return c.min_price_tick if c else self.min_tick

    def submit(self, order: Order) -> None:
        order.status = OrderStatus.SUBMITTED
        self.pending.append(order)

    def match(self, bar) -> list[Trade]:
        trades: list[Trade] = []
        still_pending: list[Order] = []
        for order in self.pending:
            tick = self._tick(order.symbol)
            fill = bar.open
            if order.direction == Direction.LONG:
                fill = bar.open + self.slippage * tick
            else:
                fill = bar.open - self.slippage * tick

            if order.order_type == OrderType.LIMIT and order.limit_price is not None:
                if order.direction == Direction.LONG and fill > order.limit_price:
                    still_pending.append(order)  # 未触发，留待后续
                    continue
                if order.direction == Direction.SHORT and fill < order.limit_price:
                    still_pending.append(order)
                    continue

            trade = Trade(
                symbol=order.symbol,
                direction=order.direction,
                offset=order.offset,
                quantity=order.quantity,
                price=round(fill, 4),
                datetime=bar.datetime,
                order_id=order.order_id,
            )
            order.status = OrderStatus.FILLED
            order.filled_price = fill
            order.filled_quantity = order.quantity
            trades.append(trade)
        self.pending = still_pending
        return trades
