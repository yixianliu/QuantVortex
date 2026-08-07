"""回测经纪商：委托在下一根 bar 开盘价撮合（杜绝未来函数）。

滑点：开多/平空在开盘价 + slippage*min_tick；开空/平多在开盘价 - slippage*min_tick。
限价单：若本根 bar 开盘价不满足限价，则该 bar 不成交（简化处理）。
"""
from __future__ import annotations

from ..core.types import Direction, Order, OrderStatus, OrderType, Trade
from .base import BrokerBase


class BacktestBroker(BrokerBase):
    """回测broker。
    
        继承: BrokerBase"""
    def __init__(self, slippage: float = 1.0, min_tick: float = 1.0,
                 contracts: dict | None = None, multiplier: float = 10.0) -> None:
        """初始化相关对象。
        
            参数:
                slippage: float
                min_tick: float
                contracts: dict | None
                multiplier: float"""
        self.slippage = slippage
        self.min_tick = min_tick
        self.contracts = contracts or {}
        self.multiplier = multiplier   # 合约未知时的默认乘数
        self.pending: list[Order] = []

    def _tick(self, symbol: str) -> float:
        """处理Tick 数据。
        
            参数:
                symbol: str
        
            返回:
                float"""
        c = self.contracts.get(symbol)
        return c.min_price_tick if c else self.min_tick

    def submit(self, order: Order) -> None:
        """处理submit。
        
            参数:
                order: Order"""
        order.status = OrderStatus.SUBMITTED
        self.pending.append(order)

    def match(self, bar) -> list[Trade]:
        """撮合当前 bar 的委托并返回成交列表（回测专用）。

        防未来函数：策略在 bar N 产生的信号委托不会在 bar N 内成交，
        而是在下一根 bar（即调用本方法时传入的 bar）的开盘价撮合，
        因此回测绩效不会被未来信息污染。

            参数:
                bar: 当前用于撮合的 K 线（实为信号产生后的下一根 bar）

            返回:
                list[Trade]: 本根 bar 内成交的 Trade 列表"""
        trades: list[Trade] = []
        still_pending: list[Order] = []
        for order in self.pending:
            c = self.contracts.get(order.symbol)
            tick = self._tick(order.symbol)
            fill = bar.open  # 以「下一根 bar 开盘价」撮合，规避未来函数
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
                multiplier=c.multiplier if c else self.multiplier,
            )
            order.status = OrderStatus.FILLED
            order.filled_price = fill
            order.filled_quantity = order.quantity
            trades.append(trade)
        self.pending = still_pending
        return trades
