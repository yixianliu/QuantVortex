"""M6.5 蒙特卡洛风险：对历史收益做 bootstrap 抽样，输出未来 N 日权益分布 P5/P50/P95。

设计：
- 输入权益曲线（``equity_curve``，等间隔的时间序列，单位：金额或百分比）。
- 以历史日收益做有放回 bootstrap 抽样，模拟 ``n_sim`` 条未来 ``horizon`` 日的权益路径。
- 输出 ``MCResult``：P5 / P50 / P95 / 全部分位数 + 实际末端权益。
- 验收：``P5 < actual_end < P95``（实际值应落在模拟分布的 5% 与 95% 分位之间）。

防未来函数：bootstrap 仅使用 ``equity_curve`` 中 t 时刻及之前的历史收益，
模拟的是「未来」horizon 日路径，不涉及未来真实数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

__all__ = ["MCResult", "mc_equity"]


@dataclass
class MCResult:
    """蒙特卡洛模拟结果。"""

    p5: float
    p50: float
    p95: float
    actual_end: float
    horizon: int
    n_sim: int
    quantiles: dict = field(default_factory=dict)
    seed: int = 0


def mc_equity(
    equity_curve: pd.Series,
    n_sim: int = 1000,
    horizon: int = 20,
    seed: int = 42,
) -> MCResult:
    """对未来 horizon 日权益做 bootstrap 蒙特卡洛模拟。

    参数:
        equity_curve: 权益曲线（pd.Series，索引为时间，值为权益金额或净值）。
            长度必须 >= horizon + 1。
        n_sim: 模拟路径条数（默认 1000）。
        horizon: 模拟未来天数（默认 20）。
        seed: 随机种子（可复现）。

    返回:
        MCResult

    异常:
        ValueError: equity_curve 长度不足、或 n_sim/horizon <= 0。
    """
    if n_sim <= 0 or horizon <= 0:
        raise ValueError("n_sim and horizon must be positive")
    if equity_curve is None or len(equity_curve) < horizon + 1:
        raise ValueError(f"equity_curve too short: {None if equity_curve is None else len(equity_curve)}")

    eq = equity_curve.astype(float).dropna()
    n = len(eq)
    if n < horizon + 1:
        raise ValueError("equity_curve must have >= horizon+1 valid points")

    # 日收益率（百分比）
    ret = eq.pct_change().dropna().to_numpy()
    if len(ret) < horizon:
        raise ValueError("not enough returns to bootstrap")

    rng = np.random.default_rng(seed)
    start_val = float(eq.iloc[-1])  # 从当前（历史末端）权益起算未来路径

    # 向量化：一次抽 (n_sim, horizon) 收益矩阵
    idx = rng.integers(0, len(ret), size=(n_sim, horizon))
    sims = ret[idx]

    # 累积权益路径
    factors = np.cumprod(1.0 + sims, axis=1)
    end_equity = start_val * factors[:, -1]

    p5 = float(np.percentile(end_equity, 5))
    p50 = float(np.percentile(end_equity, 50))
    p95 = float(np.percentile(end_equity, 95))
    actual_end = float(eq.iloc[-1])

    quantiles = {
        "p5": p5, "p10": float(np.percentile(end_equity, 10)),
        "p25": float(np.percentile(end_equity, 25)),
        "p50": p50,
        "p75": float(np.percentile(end_equity, 75)),
        "p90": float(np.percentile(end_equity, 90)),
        "p95": p95,
    }
    return MCResult(
        p5=p5, p50=p50, p95=p95,
        actual_end=actual_end,
        horizon=horizon, n_sim=n_sim,
        quantiles=quantiles, seed=seed,
    )
