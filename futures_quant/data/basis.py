"""M8.3 基差与仓单因子：基差（期货价 - 现货价）与仓单数变化率 → 供给因子。

基差（basis）：
- 定义：``basis = futures_price - spot_price``（升水 >0 期货贵 / 贴水 <0 现货贵）。
- 基差变化率 ``basis_chg = basis - basis.shift(1)``。
- 基差分位 ``basis_rank``：在回看窗口内的 [0,1] 分位（>0.5 偏强势）。

仓单（warrant）：
- 仓单数变化率 ``warrant_chg = (w_t - w_{t-n}) / w_{t-n}``，作为供给因子。
- 仓单激增 → 供给充裕 → 看空信号；仓单减少 → 供给紧张 → 看涨信号。

离线可算：纯 pandas/numpy，无网络依赖。数据缺失时返回 NaN 而非抛异常。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

__all__ = [
    "BasisSeries",
    "compute_basis",
    "compute_warrant_factor",
]


@dataclass
class BasisSeries:
    """基差序列结果。"""

    basis: pd.Series
    basis_chg: pd.Series
    basis_rank: pd.Series
    lookback: int

    def to_dict(self) -> Dict[str, pd.Series]:
        return {"basis": self.basis, "basis_chg": self.basis_chg, "basis_rank": self.basis_rank}


def compute_basis(
    futures: pd.Series,
    spot: pd.Series,
    lookback: int = 60,
) -> BasisSeries:
    """计算基差序列及其分位。

    参数:
        futures: 期货价格序列（与 spot 同索引对齐）。
        spot: 现货价格序列。
        lookback: 分位计算的回看窗口（默认 60 日）。

    返回:
        BasisSeries

    异常:
        ValueError: futures/spot 为空或长度不匹配。
    """
    if futures is None or spot is None or len(futures) == 0:
        raise ValueError("futures/spot must be non-empty")
    if len(futures) != len(spot):
        raise ValueError("futures and spot must have same length")

    f = futures.astype(float)
    s = spot.astype(float)
    basis = f - s
    basis_chg = basis - basis.shift(1)
    basis_rank = basis.rolling(lookback, min_periods=1).rank(pct=True)
    return BasisSeries(basis=basis, basis_chg=basis_chg, basis_rank=basis_rank, lookback=lookback)


def compute_warrant_factor(
    warrants: pd.Series,
    lookback: int = 20,
) -> Dict[str, pd.Series]:
    """仓单数变化率 → 供给因子。

    参数:
        warrants: 仓单数时间序列（整数或浮点）。
        lookback: 变化率计算的回看窗口（默认 20 日）。

    返回:
        {
          "warrant_chg": 变化率（>0 供给增 / <0 供给减）,
          "supply_signal": -warrant_chg 符号（>0 看多 / <0 看空）,
        }

    说明：仓单激增 = 供给充裕 = 看空，故 supply_signal = -sign(warrant_chg)。
    """
    if warrants is None or len(warrants) < 2:
        return {"warrant_chg": pd.Series(dtype=float), "supply_signal": pd.Series(dtype=float)}

    w = warrants.astype(float)
    base = w.shift(lookback)
    warrant_chg = (w - base) / base.replace(0, np.nan)
    # 供给信号：仓单减少（chg<0）→ 供给紧张 → 看多（+1）；仓单增加（chg>0）→ 供给充裕 → 看空（-1）
    supply_signal = -np.sign(warrant_chg.fillna(0.0))
    return {"warrant_chg": warrant_chg, "supply_signal": supply_signal}
