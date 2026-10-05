"""M8.2 持仓结构：交易所每日持仓排名 Top20，计算多单集中度 / 空单集中度 / 多空比。

设计：
- 输入：持仓排名 DataFrame（含 ``long_vol`` / ``short_vol`` 列，按席位或品种组织）。
- 多单集中度 = 前 N 多头席位的多单持仓占全部多单持仓比例（默认 N=5）。
- 空单集中度 = 前 N 空头席位的空单持仓占全部空单持仓比例（默认 N=5）。
- 多空比 = 总多单持仓 / 总空单持仓（>1 偏多）。
- 离线可算：纯 pandas/numpy，无网络依赖。数据源失败时返回 NaN 占位而非抛异常。

防未来函数：使用 t 时刻已发布的持仓排名，不引用 t 之后数据。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

__all__ = ["PositionRankStats", "compute_rank_stats", "concentration_top_n"]


@dataclass
class PositionRankStats:
    """持仓排名统计结果。"""

    long_total: float
    short_total: float
    long_short_ratio: float          # >1 偏多，<1 偏空，=1 均衡
    long_top5_conc: float            # 前 5 多头席位占全部多单比例 [0,1]
    short_top5_conc: float          # 前 5 空头席位占全部空单比例 [0,1]
    top5_long_volumes: List[float]
    top5_short_volumes: List[float]
    n_symbols: int = 0

    def to_dict(self) -> Dict[str, float]:
        return {
            "long_total": self.long_total,
            "short_total": self.short_total,
            "long_short_ratio": self.long_short_ratio,
            "long_top5_conc": self.long_top5_conc,
            "short_top5_conc": self.short_top5_conc,
            "n_symbols": self.n_symbols,
        }


def concentration_top_n(volumes: List[float], n: int = 5) -> float:
    """前 N 席位占总体比例。volumes 为各席位持仓量（未排序）。"""
    vols = [v for v in volumes if np.isfinite(v) and v >= 0]
    total = sum(vols)
    if total <= 0:
        return np.nan
    top = sorted(vols, reverse=True)[:n]
    return float(sum(top) / total)


def compute_rank_stats(
    df: pd.DataFrame,
    top_n: int = 5,
) -> PositionRankStats:
    """从持仓排名 DataFrame 计算多/空集中度与多空比。

    参数:
        df: 持仓排名表。需含 ``long_vol`` / ``short_vol`` 列（席位级，
            每行一个席位或一个品种×席位）。
        top_n: 集中度计算的席位数（默认 5）。

    返回:
        PositionRankStats

    异常:
        ValueError: df 缺少 long_vol / short_vol 列或为空。
    """
    if df is None or df.empty:
        raise ValueError("df must be non-empty")
    for col in ("long_vol", "short_vol"):
        if col not in df.columns:
            raise ValueError(f"missing column {col}")

    long_vols = pd.to_numeric(df["long_vol"], errors="coerce").dropna()
    short_vols = pd.to_numeric(df["short_vol"], errors="coerce").dropna()

    long_total = float(long_vols.sum()) if len(long_vols) else 0.0
    short_total = float(short_vols.sum()) if len(short_vols) else 0.0

    if short_total > 0:
        ratio = long_total / short_total
    elif long_total > 0:
        ratio = np.inf
    else:
        ratio = np.nan

    long_list = [float(x) for x in long_vols.tolist()]
    short_list = [float(x) for x in short_vols.tolist()]
    long_top5 = sorted(long_list, reverse=True)[:top_n]
    short_top5 = sorted(short_list, reverse=True)[:top_n]

    return PositionRankStats(
        long_total=long_total,
        short_total=short_total,
        long_short_ratio=float(ratio),
        long_top5_conc=concentration_top_n(long_list, top_n),
        short_top5_conc=concentration_top_n(short_list, top_n),
        top5_long_volumes=long_top5,
        top5_short_volumes=short_top5,
        n_symbols=len(df),
    )
