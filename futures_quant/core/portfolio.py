"""投资组合 / 资金账户（期货保证金记账）。

核心会计规则：
    equity（权益）      = 初始资金 + 累计已实现盈亏 + 浮动盈亏
    used_margin（占用保证金）= Σ 持仓手数 × 当前标记价 × 合约乘数 × 合约保证金率
    available（可用资金）  = equity - used_margin
    risk_degree（风险度）  = used_margin / equity；>1.0 表示保证金不足，触发强平信号

期货为保证金交易，开仓只冻结保证金而非全额；T+0 多空双向。
M2.4：支持合约级 margin_rate 覆盖（逐合约差异化保证金），逐日盯市（每根 bar 标记到市价）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .types import Direction, Offset, Position, Trade


class Portfolio:
    """回测投资组合：维护保证金、持仓与可用资金，按账户级参数计算手续费与已实现/未实现盈亏。

    M2.4 扩展：
        - 合约级 margin_rate / multiplier / commission_per_lot 覆盖（contracts dict）
        - 逐日盯市：每根 bar 更新价格后实时计算权益 / 保证金 / 风险度
        - risk_degree()：占用保证金 / 权益，>1.0 为强平信号
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        margin_rate: float = 0.10,
        commission_per_lot: float = 3.0,
        logger=None,
        multiplier: float = 10.0,
        close_today_ratio: float = 1.0,
        contracts: Optional[Dict[str, object]] = None,
    ) -> None:
        """初始化投资组合。

        参数:
            initial_capital: 初始资金（元）
            margin_rate: 账户级默认保证金率
            commission_per_lot: 账户级默认每手手续费（元）
            logger: 日志器
            multiplier: 账户级默认合约乘数
            close_today_ratio: 平今仓手续费折扣（期货 T+0 平今优惠）
            contracts: {symbol: Contract} 合约级参数覆盖（margin_rate / multiplier /
                       commission_per_lot / close_today_commission_ratio）
        """
        self.initial_capital = float(initial_capital)
        self.margin_rate = float(margin_rate)
        self.commission_per_lot = float(commission_per_lot)
        self.logger = logger
        self.multiplier = float(multiplier)            # 合约乘数（每手标的单位数）
        self.close_today_ratio = float(close_today_ratio)  # 平今仓手续费折扣（T+0）
        self.contracts: Dict[str, object] = contracts or {}  # M2.4 合约级参数覆盖

        self.cash = float(initial_capital)       # 可用资金（扣除保证金与手续费后）
        self.positions: Dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.total_commission: float = 0.0        # 累计手续费
        self._current_prices: Dict[str, float] = {}
        self.trade_history: List[Trade] = []

    # ---------- 合约级参数 ----------
    def _margin_rate(self, symbol: str) -> float:
        """取合约级保证金率，未知合约回落账户默认。"""
        c = self.contracts.get(symbol)
        return float(c.margin_rate) if c and hasattr(c, "margin_rate") else self.margin_rate

    def _multiplier(self, symbol: str) -> float:
        """取合约级乘数，未知合约回落账户默认。"""
        c = self.contracts.get(symbol)
        return float(c.multiplier) if c and hasattr(c, "multiplier") else self.multiplier

    def _commission_rate(self, symbol: str) -> float:
        """取合约级每手手续费，未知合约回落账户默认。"""
        c = self.contracts.get(symbol)
        return float(c.commission_per_lot) if c and hasattr(c, "commission_per_lot") else self.commission_per_lot

    def _close_today_ratio(self, symbol: str) -> float:
        """取合约级平今仓折扣，未知合约回落账户默认。"""
        c = self.contracts.get(symbol)
        return float(c.close_today_commission_ratio) if c and hasattr(c, "close_today_commission_ratio") else self.close_today_ratio

    # ---------- 持仓与价格 ----------
    def _get_position(self, symbol: str) -> Position:
        """获取持仓对象（不存在则创建）。"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def update_price(self, symbol: str, price: float) -> None:
        """标记到市价（逐日盯市：每根 bar 调用一次）。"""
        self._current_prices[symbol] = float(price)

    # ---------- 成交处理 ----------
    def process_trade(self, trade: Trade) -> None:
        """处理一笔成交，更新持仓、保证金占用、手续费与盈亏。

        M2.4：手续费 / 乘数优先取合约级参数（contracts dict），未知合约回落账户默认。
        """
        pos = self._get_position(trade.symbol)
        # 成交自带合约乘数（经纪商按合约填），否则取合约级 / 账户级
        mult = float(getattr(trade, "multiplier", None) or self._multiplier(trade.symbol) or 1.0)
        realized = pos.update_on_trade(trade.direction, trade.offset,
                                       trade.quantity, trade.price, mult)

        # 手续费：双边收取（开平都收）；平今仓按合约级折扣（M2.4 合约级参数）
        base_fee = self._commission_rate(trade.symbol)
        if trade.offset == Offset.CLOSE_TODAY:
            ratio = self._close_today_ratio(trade.symbol)
        else:
            ratio = 1.0
        commission = abs(trade.quantity) * base_fee * ratio
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
        """占用保证金 = Σ (long_qty + short_qty) × 标记价 × 合约乘数 × 合约保证金率。

        M2.4：逐合约取 margin_rate，支持差异化保证金。
        """
        margin = 0.0
        for sym, pos in self.positions.items():
            price = self._current_prices.get(sym, 0.0)
            if price <= 0:
                continue
            # 期货保证金 = 手数 × 标记价 × 合约乘数 × 合约保证金率
            mult = self._multiplier(sym)
            rate = self._margin_rate(sym)
            margin += (pos.long_qty + pos.short_qty) * price * mult * rate
        return margin

    def unrealized_pnl(self) -> float:
        """浮动盈亏（逐日盯市：标记价 vs 开仓均价，乘以合约乘数）。"""
        upnl = 0.0
        for sym, pos in self.positions.items():
            price = self._current_prices.get(sym, 0.0)
            if price <= 0:
                continue
            mult = self._multiplier(sym)
            upnl += (price - pos.long_avg_price) * pos.long_qty * mult
            upnl += (pos.short_avg_price - price) * pos.short_qty * mult
        return upnl

    def equity(self) -> float:
        """当前权益（标记到市价）。"""
        return self.initial_capital + self.realized_pnl + self.unrealized_pnl()

    def available(self) -> float:
        """可用资金 = equity - used_margin。"""
        return self.equity() - self.used_margin()

    def risk_degree(self) -> float:
        """M2.4 风险度 = 占用保证金 / 权益。

        >1.0 表示保证金不足（强平信号）；0.8~1.0 为预警区间；<0.8 为安全区间。
        权益 ≤ 0 时返回 999.0（无法计算，视为已爆仓）。
        """
        eq = self.equity()
        if eq <= 0:
            return 999.0
        return self.used_margin() / eq

    def summary(self) -> dict:
        """账户摘要（含 M2.4 风险度）。"""
        eq = self.equity()
        used = self.used_margin()
        rd = used / eq if eq > 0 else 999.0
        return {
            "equity": round(eq, 2),
            "available": round(self.available(), 2),
            "used_margin": round(used, 2),
            "realized_pnl": round(self.realized_pnl(), 2),
            "unrealized_pnl": round(self.unrealized_pnl(), 2),
            "risk_degree": round(rd, 4),
            "position_count": sum(
                1 for p in self.positions.values() if p.long_qty or p.short_qty
            ),
        }
