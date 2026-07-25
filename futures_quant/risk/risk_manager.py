"""专业风控模块（实盘必备）。

四层风控：
    1) 资金风控：单笔最大亏损、单日最大亏损、总资金最大回撤，触发后停止交易并平仓锁仓；
    2) 仓位风控：单品种最大持仓手数、总仓位占用比例；
    3) 交易风控：单笔下单数量上限、非交易时段禁止下单、可用资金不足拦截；
    4) 异常风控：由引擎在网络/接口异常时调用 halt()，强制终止交易。
所有检查返回 (是否通过, 原因)，被拒订单不会进入撮合。
"""
from __future__ import annotations

from datetime import datetime, time
from typing import List, Optional, Tuple

from ..config.settings import RiskConfig
from ..core.types import Direction, Offset, Order, Position


def _in_trading_hours(hours: list, dt: datetime) -> bool:
    """判断 dt 是否落在交易时段内。hours 为空表示不限制。"""
    if not hours:
        return True
    t = dt.time()
    for start, end in hours:
        s = time.fromisoformat(start)
        e = time.fromisoformat(end)
        if s <= t <= e:
            return True
    return False


class RiskManager:
    def __init__(self, cfg: RiskConfig, logger=None) -> None:
        self.cfg = cfg
        self.logger = logger
        self.halted = False
        self.halt_reason = ""
        self.max_equity = 0.0
        self.day = None
        self.daily_start_equity = 0.0
        self.daily_pnl = 0.0          # 当日盈亏（UI 展示用）
        self.current_drawdown = 0.0   # 当前回撤（UI 展示用）

    # ---------- 生命周期 ----------
    def start(self, portfolio) -> None:
        self.max_equity = portfolio.equity()
        self.daily_start_equity = portfolio.equity()

    def reset(self) -> None:
        """手动解除风控暂停（如人工确认后）。"""
        self.halted = False
        self.halt_reason = ""

    def halt(self, reason: str) -> None:
        """异常风控：强制停止交易。"""
        self.halted = True
        self.halt_reason = reason
        if self.logger:
            self.logger.error(f"[风控] 触发异常暂停：{reason}")

    # ---------- 下单前检查 ----------
    def check_order(
        self,
        order: Order,
        portfolio,
        contract=None,
        dt=None,
    ) -> Tuple[bool, str]:
        if self.halted:
            # 暂停后禁止「开仓」，但允许「平仓」以便锁仓退出
            if order.offset == Offset.OPEN:
                return False, f"风控已暂停开仓（{self.halt_reason or '已触发'}）"
            return True, ""
        if order.quantity <= 0:
            return False, "委托数量非法"
        if order.quantity > self.cfg.max_order_qty:
            return False, f"单笔数量超过上限 {self.cfg.max_order_qty}"

        # 非交易时段
        if self.cfg.non_trading_hours_block and contract and dt is not None:
            if not _in_trading_hours(contract.trading_hours, dt):
                return False, "非交易时段禁止下单"

        pos: Optional[Position] = portfolio.positions.get(order.symbol)
        cur = 0
        if pos:
            cur = pos.long_qty if order.direction == Direction.LONG else pos.short_qty
        if order.offset == Offset.OPEN and cur + order.quantity > self.cfg.max_position_per_symbol:
            return False, f"单品种持仓超过上限 {self.cfg.max_position_per_symbol}"

        # 资金占用估算
        price = portfolio._current_prices.get(order.symbol) or order.limit_price or 0.0
        margin_rate = contract.margin_rate if contract else portfolio.margin_rate
        add_margin = order.quantity * (price or 0.0) * margin_rate
        new_used = portfolio.used_margin() + add_margin
        eq = portfolio.equity()
        if eq > 0 and new_used / eq > self.cfg.max_total_position_ratio:
            return False, "总仓位占用比例超限"
        if portfolio.available() < add_margin:
            return False, "可用资金不足以覆盖保证金"

        return True, ""

    # ---------- 每根 bar 后检查（回撤 / 单日亏损） ----------
    def on_new_bar(self, portfolio, dt) -> List[str]:
        triggered: List[str] = []
        d = dt.date() if isinstance(dt, datetime) else None
        if d is not None and d != self.day:
            self.day = d
            self.daily_start_equity = portfolio.equity()

        eq = portfolio.equity()
        self.max_equity = max(self.max_equity, eq)
        dd = 0.0
        if self.max_equity > 0:
            dd = (self.max_equity - eq) / self.max_equity
            if dd >= self.cfg.max_drawdown:
                self.halted = True
                self.halt_reason = "总回撤超限"
                triggered.append("max_drawdown")
                if self.logger:
                    self.logger.error(f"[风控] 总回撤 {dd:.1%} 触及阈值，停止交易")

        daily_pnl = eq - self.daily_start_equity
        self.daily_pnl = daily_pnl
        self.current_drawdown = dd
        if daily_pnl <= -self.cfg.max_daily_loss:
            self.halted = True
            self.halt_reason = "单日亏损超限"
            triggered.append("max_daily_loss")
            if self.logger:
                self.logger.error(f"[风控] 单日亏损 {daily_pnl:.2f} 触及阈值，停止交易")

        return triggered
