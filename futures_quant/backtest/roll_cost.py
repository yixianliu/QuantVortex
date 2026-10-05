"""移仓换月成本模拟。

M3.3：按交割日 T-7 自动换月，价差 × 保证金 × 手续费计入回测。
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

@dataclass
class RollParams:
    roll_days_before_expiry: int = 7
    commission_per_lot: float = 3.0
    margin_rate: float = 0.1
    multiplier: int = 10

def should_roll(trade_date: datetime, expiry_date: datetime, params: RollParams) -> bool:
    days_left = (expiry_date.date() - trade_date.date()).days
    return days_left <= params.roll_days_before_expiry and days_left > 0

def roll_cost(price_current: float, price_next: float, quantity: int, params: RollParams) -> float:
    """计算移仓成本（价差 + 手续费）。
    
    价差成本：(price_next - price_current) * quantity * multiplier
    手续费：两次平开 × commission_per_lot * quantity
    """
    diff = price_next - price_current
    price_cost = diff * quantity * params.multiplier
    commission_cost = 2 * params.commission_per_lot * quantity
    return price_cost + commission_cost
