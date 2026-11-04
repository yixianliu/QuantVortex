"""M1.5 持仓模拟组合层：模拟账户资金 / 保证金占用 / 风险度仪表盘（纯逻辑，可离线）。

设计（离线、零依赖、无未来函数）：
- ``PaperPortfolio`` 持有模拟账户：初始资金、当前持仓（方向/手数/开仓均价）、
  每手保证金率与合约乘数。
- 关键指标：
  - 占用保证金 ``margin_used = Σ 手数 × price × multiplier × margin_rate``
  - 权益 ``equity = cash + Σ(浮动盈亏)``（浮动盈亏随最新价盯市）
  - 风险度 ``risk_degree = margin_used / equity``（>0.8 红色告警，>1.0 强平）
- 操作：
  - ``open_long / open_short``：开仓（占用保证金、扣可用资金，含手续费）
  - ``close_long / close_short``：平仓（释放保证金、结算盈亏、加回可用资金）
  - ``mark_to_market(price)``：最新价盯市，刷新浮动盈亏与风险度
- 数据缺失 / 参数非法时优雅降级（不抛错，返回 0 / 拒绝），离线优先。

风控红线（护栏 7）：本层不承诺收益；风险度仅供模拟警示，非投资建议。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = [
    "PaperPortfolio",
    "Position",
    "ALERT_THRESHOLD",
    "LIQUIDATE_THRESHOLD",
]

# 风险度告警 / 强平阈值
ALERT_THRESHOLD: float = 0.80
LIQUIDATE_THRESHOLD: float = 1.00


@dataclass
class Position:
    """单方向持仓。"""
    direction: str = ""          # "long" / "short"
    lots: int = 0
    avg_price: float = 0.0
    symbol: str = ""


class PaperPortfolio:
    """模拟持仓组合（资金 + 保证金 + 风险度）。

    参数:
        cash: 初始资金（>0）。
        multiplier: 合约乘数（每手）。
        margin_rate: 保证金率（0~1）。
        commission: 每手手续费（可选）。
    """

    def __init__(self, cash: float = 1_000_000.0, multiplier: float = 10.0,
                 margin_rate: float = 0.10, commission: float = 0.0) -> None:
        if cash <= 0:
            raise ValueError("初始资金必须 > 0")
        self.initial_cash = float(cash)
        self.cash = float(cash)
        self.multiplier = float(multiplier)
        self.margin_rate = float(margin_rate)
        self.commission = float(commission)
        self.long_pos: Position = Position("long", 0, 0.0, "")
        self.short_pos: Position = Position("short", 0, 0.0, "")
        self._mark_price: Optional[float] = None

    # ---------------- 保证金 / 风险度 ----------------
    def margin_used(self, price: float) -> float:
        """按给定价计算的总占用保证金。"""
        if price is None or price <= 0:
            return 0.0
        p = float(price)
        return ((self.long_pos.lots + self.short_pos.lots) * p * self.multiplier
                * self.margin_rate)

    def unrealized_pnl(self, price: float) -> float:
        """按给定价的浮动盈亏（多头 + / 空头 -）。"""
        if price is None or price <= 0:
            return 0.0
        p = float(price)
        pnl = 0.0
        if self.long_pos.lots:
            pnl += (p - self.long_pos.avg_price) * self.long_pos.lots * self.multiplier
        if self.short_pos.lots:
            pnl += (self.short_pos.avg_price - p) * self.short_pos.lots * self.multiplier
        return pnl

    def equity(self, price: float) -> float:
        """权益 = 可用资金 + 浮动盈亏。"""
        p = float(price) if (price and price > 0) else 0.0
        return self.cash + self.unrealized_pnl(p)

    def risk_degree(self, price: float) -> float:
        """风险度 = 占用保证金 / 权益（0~∞）。无持仓返回 0。"""
        if price is None or price <= 0:
            return 0.0
        p = float(price)
        eq = self.equity(p)
        if eq <= 0:
            return float("inf") if self.margin_used(p) > 0 else 0.0
        return self.margin_used(p) / eq

    def risk_status(self, price: float) -> Dict[str, object]:
        """风险度仪表盘数据（等级 + 是否告警/强平）。"""
        rd = self.risk_degree(price)
        if rd >= LIQUIDATE_THRESHOLD:
            level, alert, liquidate = "danger", True, True
        elif rd >= ALERT_THRESHOLD:
            level, alert, liquidate = "warn", True, False
        else:
            level, alert, liquidate = "safe", False, False
        return {
            "risk_degree": round(rd, 4),
            "margin_used": round(self.margin_used(price), 2),
            "equity": round(self.equity(price), 2),
            "level": level,
            "alert": alert,
            "liquidate": liquidate,
            "available_cash": round(self.cash, 2),
        }

    def mark_to_market(self, price: float) -> Dict[str, object]:
        """最新价盯市，更新 _mark_price 并返回仪表盘数据。"""
        if price and price > 0:
            self._mark_price = float(price)
        return self.risk_status(self._mark_price if self._mark_price else 0.0)

    # ---------------- 开 / 平仓 ----------------
    def open_long(self, symbol: str, price: float, lots: int = 1,
                   commission: Optional[float] = None) -> Dict[str, object]:
        """开多仓。资金不足保证金时拒绝（部分成交取可承受手数）。"""
        return self._open("long", symbol, price, lots, commission, sign=+1)

    def open_short(self, symbol: str, price: float, lots: int = 1,
                   commission: Optional[float] = None) -> Dict[str, object]:
        """开空仓。"""
        return self._open("short", symbol, price, lots, commission, sign=-1)

    def _open(self, side: str, symbol: str, price: float, lots: int,
              commission: Optional[float], sign: int) -> Dict[str, object]:
        cm = self.commission if commission is None else float(commission)
        if not price or price <= 0:
            return {"ok": False, "filled_lots": 0, "reason": "无有效价格"}
        if lots <= 0:
            return {"ok": False, "filled_lots": 0, "reason": "手数须 > 0"}
        p = float(price)
        pos = self.long_pos if side == "long" else self.short_pos
        # 每手所需保证金 + 手续费
        per_margin = p * self.multiplier * self.margin_rate
        per_cost = per_margin + cm
        # 可承受手数（不超过可用资金）
        affordable = int(self.cash // per_cost) if per_cost > 0 else 0
        filled = min(lots, affordable)
        if filled <= 0:
            return {"ok": False, "filled_lots": 0, "reason": "资金不足"}
        # 更新均价与手数（加仓摊薄）
        new_lots = pos.lots + filled
        pos.avg_price = ((pos.avg_price * pos.lots + p * filled) / new_lots) if new_lots else p
        pos.lots = new_lots
        pos.symbol = symbol
        self.cash -= (filled * per_cost)
        return {"ok": True, "filled_lots": filled,
                "risk": self.risk_status(p),
                "margin_used": self.margin_used(p), "equity": self.equity(p)}

    def close_long(self, symbol: str, price: float, lots: int = 0,
                   commission: Optional[float] = None) -> Dict[str, object]:
        """平多仓。lots=0 全平。"""
        return self._close("long", symbol, price, lots, commission, sign=+1)

    def close_short(self, symbol: str, price: float, lots: int = 0,
                    commission: Optional[float] = None) -> Dict[str, object]:
        """平空仓。"""
        return self._close("short", symbol, price, lots, commission, sign=-1)

    def _close(self, side: str, symbol: str, price: float, lots: int,
               commission: Optional[float], sign: int) -> Dict[str, object]:
        cm = self.commission if commission is None else float(commission)
        if not price or price <= 0:
            return {"ok": False, "closed_lots": 0, "reason": "无有效价格"}
        pos = self.long_pos if side == "long" else self.short_pos
        if pos.lots <= 0:
            return {"ok": False, "closed_lots": 0, "reason": "无持仓"}
        closed = min(lots, pos.lots) if lots > 0 else pos.lots
        if closed <= 0:
            return {"ok": False, "closed_lots": 0, "reason": "手数须 > 0"}
        p = float(price)
        # 结算盈亏：方向 × (平 - 开) × 手数 × 乘数
        pnl = sign * (p - pos.avg_price) * closed * self.multiplier
        # 释放保证金 + 盈亏 - 手续费 → 现金
        release_margin = closed * p * self.multiplier * self.margin_rate
        self.cash += (release_margin + pnl - closed * cm)
        pos.lots -= closed
        if pos.lots <= 0:
            pos.lots = 0
            pos.avg_price = 0.0
        return {"ok": True, "closed_lots": closed, "realized_pnl": round(pnl, 2),
                "equity": self.equity(p), "cash": round(self.cash, 2)}

    # ---------------- 汇总 ----------------
    def summary(self, price: float = 0.0) -> Dict[str, object]:
        """组合汇总（资金 / 持仓 / 风险度），price 为 0 时取最新盯市价。"""
        p = float(price) if price and price > 0 else (self._mark_price or 0.0)
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 2),
            "equity": round(self.equity(p), 2),
            "margin_used": round(self.margin_used(p), 2),
            "risk_degree": round(self.risk_degree(p), 4),
            "long_lots": self.long_pos.lots,
            "short_lots": self.short_pos.lots,
            "mark_price": self._mark_price,
            "alert": self.risk_degree(p) >= ALERT_THRESHOLD,
        }

    def total_lots(self) -> int:
        return self.long_pos.lots + self.short_pos.lots
