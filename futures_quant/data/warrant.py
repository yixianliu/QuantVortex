"""M8.3 仓单（warrant）：仓单数时间序列 → 供给因子。

仓单（warehouse warrant）是期货交割仓库中已登记的未提取商品凭证，
其数量变化反映实物供给预期：
- 仓单数激增 → 现货库存充裕 → 期货价格承压（看空信号）；
- 仓单数持续减少 → 供给紧张 → 期货价格走强（看涨信号）。

设计：
- 输入 ``warrants`` 为仓单数时间序列（int 或 float，单位：张 / 吨）。
- ``warrant_factor(warrants, lookback=20)`` 输出：
    - ``chg``：``(w_t - w_{t-n}) / w_{t-n}`` 相对变化率（基准 0 时填 NaN 再填 0）
    - ``supply_signal``：``-sign(chg)``，取值 ∈ {-1, 0, +1}
      （+1 看涨 / -1 看空 / 0 中性）
    - ``z_score``：滚动 z-score（window=lookback，ddof=0，仅用历史）
- 数据不足（len < 2）时返回全 0 / NaN 占位 DataFrame，不抛异常。

防未来函数：chg / z_score 仅使用 t 时刻及之前数据。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

__all__ = ["WarrantFactor", "warrant_factor"]


@dataclass
class WarrantFactor:
    """仓单因子结果。"""

    chg: pd.Series            # 相对变化率
    supply_signal: pd.Series  # -1 / 0 / +1
    z_score: pd.Series        # 滚动 z-score
    lookback: int

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({
            "chg": self.chg,
            "supply_signal": self.supply_signal,
            "z_score": self.z_score,
        })


def warrant_factor(
    warrants: pd.Series,
    lookback: int = 20,
) -> WarrantFactor:
    """计算仓单数变化率与供给信号。

    参数:
        warrants: 仓单数时间序列（int / float，单位：张 或 吨）。
        lookback: 变化率 / z-score 的回看窗口（默认 20 日）。

    返回:
        WarrantFactor

    异常:
        ValueError: warrants 为 None 或长度为 0。
    """
    if warrants is None or len(warrants) == 0:
        raise ValueError("warrants must be a non-empty Series")

    w = warrants.astype(float)
    n = len(w)
    idx = w.index

    # 相对变化率
    base = w.shift(lookback)
    chg = (w - base) / base.replace(0, np.nan)
    chg = chg.fillna(0.0)

    # 供给信号：仓单减少（chg < 0）→ 看涨（+1）；仓单增加（chg > 0）→ 看空（-1）
    supply_signal = -np.sign(chg).astype(float)

    # 滚动 z-score（仅历史，window=lookback）
    rolling_mean = chg.rolling(lookback, min_periods=1).mean()
    rolling_std = chg.rolling(lookback, min_periods=1).std(ddof=0)
    z_score = (chg - rolling_mean) / rolling_std.replace(0, np.nan)
    z_score = z_score.fillna(0.0)

    return WarrantFactor(
        chg=chg,
        supply_signal=supply_signal,
        z_score=z_score,
        lookback=lookback,
    )
