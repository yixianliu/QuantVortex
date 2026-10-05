"""核心数据类型与枚举。

期货特有约定：
    - 双向交易：多头 LONG / 空头 SHORT
    - 保证金交易：开仓占用保证金，而非全额资金
    - T+0：当日可开可平
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    """持仓 / 下单方向。"""

    LONG = "LONG"      # 多头
    SHORT = "SHORT"    # 空头
    NET = "NET"        # 净持仓（不区分多空，部分品种用）


class Offset(str, Enum):
    """开平标志（期货特有）。"""

    OPEN = "OPEN"        # 开仓
    CLOSE = "CLOSE"      # 平今 / 平仓（简化：统一平仓）
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


class OrderType(str, Enum):
    """委托类型。"""

    MARKET = "MARKET"    # 市价（回测中以下一根 bar 开盘价撮合）
    LIMIT = "LIMIT"      # 限价


class OrderStatus(str, Enum):
    """处理订单状态。
    
        继承: str, Enum"""
    SUBMITTED = "SUBMITTED"   # 已提交，待撮合
    FILLED = "FILLED"         # 全部成交
    PARTIAL = "PARTIAL"       # 部分成交
    CANCELLED = "CANCELLED"   # 已撤单
    REJECTED = "REJECTED"     # 被风控 / 交易所拒绝


@dataclass
class Bar:
    """单根 K 线。

    Attributes:
        symbol:       合约代码，如 "rb2410.SHFE"
        datetime:     时间戳（pandas.Timestamp）
        open/high/low/close: OHLC 价格
        volume:       成交量（手）
        open_interest: 持仓量（手）
    """

    symbol: str
    datetime: object
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    open_interest: float = 0.0


@dataclass
class Order:
    """委托单。"""

    symbol: str
    direction: Direction
    offset: Offset
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    status: OrderStatus = OrderStatus.SUBMITTED
    datetime: Optional[object] = None
    filled_price: Optional[float] = None
    filled_quantity: int = 0
    reject_reason: str = ""
    order_id: str = ""


@dataclass
class Trade:
    """成交记录。"""

    symbol: str
    direction: Direction
    offset: Offset
    quantity: int
    price: float
    datetime: object
    commission: float = 0.0
    order_id: str = ""
    pnl: float = 0.0  # 平仓时计算的已实现盈亏
    multiplier: float = 10.0  # 合约乘数（每手对应标的单位数），盈亏与保证金计算用


@dataclass
class Position:
    """某合约的持仓（多空分别记录）。"""

    symbol: str
    long_qty: int = 0
    short_qty: int = 0
    long_avg_price: float = 0.0
    short_avg_price: float = 0.0

    @property
    def net_qty(self) -> int:
        """处理netqty。
        
            返回:
                int"""
        return self.long_qty - self.short_qty

    def update_on_trade(self, direction: Direction, offset: Offset, qty: int,
                         price: float, multiplier: float = 1.0) -> float:
        """根据成交更新持仓，返回该笔成交产生的已实现盈亏（仅平仓时非零）。

        multiplier：合约乘数（每手对应标的单位数）。期货盈亏 = 价差 × 乘数 × 手数，
        此处必须乘乘数，否则盈亏与真实资金规模严重不符。
        """
        realized = 0.0
        if direction == Direction.LONG:
            if offset == Offset.OPEN:
                new_qty = self.long_qty + qty
                self.long_avg_price = (
                    (self.long_avg_price * self.long_qty + price * qty) / new_qty
                    if new_qty else 0.0
                )
                self.long_qty = new_qty
            else:  # 平空
                close_qty = min(qty, self.short_qty)
                realized = (self.short_avg_price - price) * close_qty * multiplier
                self.short_qty -= close_qty
                if self.short_qty == 0:
                    self.short_avg_price = 0.0
        else:  # SHORT
            if offset == Offset.OPEN:
                new_qty = self.short_qty + qty
                self.short_avg_price = (
                    (self.short_avg_price * self.short_qty + price * qty) / new_qty
                    if new_qty else 0.0
                )
                self.short_qty = new_qty
            else:  # 平多
                close_qty = min(qty, self.long_qty)
                realized = (price - self.long_avg_price) * close_qty * multiplier
                self.long_qty -= close_qty
                if self.long_qty == 0:
                    self.long_avg_price = 0.0
        return realized
