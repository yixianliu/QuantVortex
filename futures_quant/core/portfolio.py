"""投资组合 / 资金账户（期货保证金记账）。

核心会计规则：
    equity（权益）      = 初始资金 + 累计已实现盈亏 + 浮动盈亏
    used_margin（占用保证金）= Σ 持仓手数 × 当前标记价 × 保证金率
    available（可用资金）  = equity - used_margin
期货为保证金交易，开仓只冻结保证金而非全额；T+0 多空双向。
"""
from __future__ import annotations

from typing import Dict, List

from .types import Direction, Offset, Position, Trade


class Portfolio:
    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        margin_rate: float = 0.10,
        commission_per_lot: float = 3.0,
        logger=None,
    ) -> None:
        self.initial_capital = float(initial_capital)
        self.margin_rate = float(margin_rate)
        self.commission_per_lot = float(commission_per_lot)
        self.logger = logger

        self.cash = float(initial_capital)       # 可用资金（扣除保证金与手续费后）
        self.positions: Dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.total_commission: float = 0.0        # 累计手续费
        self._current_prices: Dict[str, float] = {}
        self.trade_history: List[Trade] = []

    # ---------- 持仓与价格 ----------
    def _get_position(self, symbol: str) -> Position:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def update_price(self, symbol: str, price: float) -> None:
        self._current_prices[symbol] = float(price)

    # ---------- 成交处理 ----------
    def process_trade(self, trade: Trade) -> None:
        """处理一笔成交，更新持仓、保证金占用、手续费与盈亏。"""
        pos = self._get_position(trade.symbol)
        realized = pos.update_on_trade(trade.direction, trade.offset, trade.quantity, trade.price)

        # 手续费：双边收取（开平都收）
        commission = abs(trade.quantity) * self.commission_per_lot
        trade.commission = commission
        trade.pnl = realized
        self.realized_pnl += realized
        self.total_commission += commission
        self.cash -= commission  # 手续费直接扣减可用资金

        self.trade_history.append(trade)
        if self.logger:
            self.logger.info(
                f"成交 {trade.symbol} {trade.direction.value} {trade.offset.value} "
                f"{trade.quantity}@{trade.price:.2f} 手续费{commission:.2f} 已实现{realized:.2f}"
            )

    # ---------- 指标计算 ----------
    def used_margin(self) -> float:
        margin = 0.0
        for sym, pos in self.positions.items():
            price = self._current_prices.get(sym, 0.0)
            if price <= 0:
                continue
            margin += (pos.long_qty + pos.short_qty) * price * self.margin_rate
        return margin

    def unrealized_pnl(self) -> float:
        upnl = 0.0
        for sym, pos in self.positions.items():
            price = self._current_prices.get(sym, 0.0)
            if price <= 0:
                continue
            upnl += (price - pos.long_avg_price) * pos.long_qty
            upnl += (pos.short_avg_price - price) * pos.short_qty
        return upnl

    def equity(self) -> float:
        """当前权益（标记到市价）。"""
        return self.initial_capital + self.realized_pnl + self.unrealized_pnl()

    def available(self) -> float:
        return self.equity() - self.used_margin()

    def summary(self) -> dict:
        return {
            "equity": round(self.equity(), 2),
            "available": round(self.available(), 2),
            "used_margin": round(self.used_margin(), 2),
            "realized_pnl": round(self.realized_pnl(), 2),
            "unrealized_pnl": round(self.unrealized_pnl(), 2),
            "position_count": sum(
                1 for p in self.positions.values() if p.long_qty or p.short_qty
            ),
        }
