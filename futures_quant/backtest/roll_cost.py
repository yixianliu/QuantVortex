"""移仓换月成本模拟（第二轮 P1-1：已接入回测持仓成本链路）。

M3.3：按交割日 T-7 自动换月，价差 × 乘数 + 双边手续费计入回测。
第二轮：``Backtester`` 在换月日对持仓收取 ``roll_cost_commission``（下限成本），
由 ``config.backtest.enable_roll_cost`` 控制（默认开启，可关闭做对照）。
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


def roll_cost_commission(quantity: int, params: RollParams) -> float:
    """仅手续费部分的移仓成本（平旧 + 开新双边）。

    当缺少新旧合约价差数据（单合约连续序列回测）时，以本函数作为可核对的
    成本下限；价差成本需接入主力/连续映射后另行计入。
    """
    return 2.0 * float(params.commission_per_lot) * abs(int(quantity))


def build_roll_schedule(start, end) -> list:
    """为单合约连续序列生成近似换月日（每个自然月首个交易日）。

    说明：真实主力换月日由成交量/持仓量迁移决定（见 ``dominant.roll_transitions``）。
    本函数只在没有真实多合约数据时提供保守的月度换月成本下限，属近似实现。

    参数:
        start / end: 起止日期（str 或 date/datetime，可被 pandas 解析）
    返回:
        换月日列表（datetime.date），升序
    """
    import pandas as pd
    idx = pd.date_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="MS")
    return [d.date() for d in idx]
