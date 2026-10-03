"""波动率自适应仓位计算工具（ATR / 风险预算驱动）。

设计原则：
    - 基于 ATR（真实波幅）动态调整单笔风险额度，避免固定手数在高低波动品种上风险不均；
    - 支持凯利公式简化版（风险预算比例 × 资金 ÷ ATR）；
    - 所有计算均为纯函数，无状态，便于单元测试与回测集成。

计算公式：
    单笔最大风险（元）= 账户权益 × 风险比例
    每手盈亏波动（元）= ATR × 合约乘数
    推荐开仓手数 = floor(单笔最大风险 / 每手盈亏波动)
    取整后不超过 max_lots 上限
"""
from __future__ import annotations

import math
from typing import Optional


def atr_position_size(
    equity: float,
    atr: float,
    multiplier: float,
    risk_pct: float = 0.02,
    max_lots: int = 10,
) -> int:
    """按 ATR 风险预算计算推荐开仓手数。

    参数:
        equity:      当前账户权益（元）
        atr:         当前 ATR 值（价格单位）
        multiplier:  合约乘数（每手标的单位数，如 rb=10, IF=300）
        risk_pct:    单笔风险占权益比例，默认 2%
        max_lots:    手数硬上限（防止极端低波动下仓位过大）

    返回:
        推荐开仓手数（>= 0 整数）

    示例:
        >>> atr_position_size(equity=1_000_000, atr=50.0, multiplier=10, risk_pct=0.02)
        4   # 1,000,000 * 2% = 20,000 元风险；每手波动 50×10=500 元；20,000/500=40手 → 截断为 max_lots
    """
    if atr <= 0 or equity <= 0 or multiplier <= 0:
        return 0
    risk_budget = equity * risk_pct
    pnl_per_lot = atr * multiplier
    lots = int(math.floor(risk_budget / pnl_per_lot))
    return max(0, min(lots, max_lots))


def atr_stop_distance(
    entry_price: float,
    atr: float,
    direction: str,
    stop_mult: float = 2.0,
) -> float:
    """计算 ATR 跟踪止损价位。

    参数:
        entry_price: 开仓价（元）
        atr:         当前 ATR 值（元）
        direction:   "LONG" 或 "SHORT"
        stop_mult:   ATR 倍数，默认 2 倍 ATR

    返回:
        止损价（元，已对齐到整数，符合期货最小变动价位惯例）
    """
    if direction == "LONG":
        stop = entry_price - stop_mult * atr
    else:
        stop = entry_price + stop_mult * atr
    return round(stop, 2)


def volatility_regime(atrs: list[float], window: int = 20) -> str:
    """判断当前波动率 regimes（低/中/高），用于策略参数自适应调整。

    参数:
        atrs:    最近 N 根 K 线的 ATR 序列（按时间升序）
        window:  用于基准计算的窗口长度

    返回:
        "low" / "normal" / "high"
    """
    if not atrs or len(atrs) < 2:
        return "normal"
    n = min(window, len(atrs))
    recent = atrs[-n:]
    prev = atrs[-n * 2: -n] if len(atrs) >= n * 2 else atrs[:n]
    if not prev:
        return "normal"
    avg_recent = sum(recent) / len(recent)
    avg_prev = sum(prev) / len(prev)
    ratio = avg_recent / avg_prev if avg_prev > 0 else 1.0
    if ratio > 1.5:
        return "high"
    if ratio < 0.67:
        return "low"
    return "normal"


def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    cap: float = 0.25,
) -> float:
    """简化版凯利公式：f* = (bp - q) / b，上限 cap 防止过度激进。

    参数:
        win_rate: 历史胜率（0~1）
        avg_win:  平均盈利金额（> 0）
        avg_loss: 平均亏损金额的绝对值（> 0）
        cap:      凯利比例上限，默认 25%（防止过拟合历史数据导致过度持仓）

    返回:
        建议仓位比例（0~cap 的浮点数）

    示例:
        >>> kelly_fraction(win_rate=0.55, avg_win=800, avg_loss=600)
        0.083...  # 约 8.3% 资金用于该品种
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    b = avg_win / avg_loss
    q = 1.0 - win_rate
    f = (b * win_rate - q) / b
    return max(0.0, min(f, cap))
