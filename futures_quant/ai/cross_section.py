"""横截面筛选（M6.1）：全市场同时算趋势分 / 波动分 / 动量分 / 反转分。

设计：
- 输入为「品种 → DataFrame(近 N 日)」字典，DataFrame 需含 ``close`` / ``volume`` 列。
- 每个品种先算 4 个原始指标（基于过去窗口，**不含当日未收盘**）：
    - 趋势：close 与 60 日均线乖离（close/MA60 - 1）
    - 波动：60 日历史波动率（std × sqrt(252) × 100）
    - 动量：近 20 日涨跌幅（close/close[-21] - 1）
    - 反转：近 5 日涨跌幅（close/close[-6] - 1），用于逆势捕捉
- 再对 4 列分别做横截面 z-score（39 品种之间做排名），输出 [N品种, 4] 分数矩阵。
- ``rank_symbols`` 按 4 列加权求综合分（默认权重趋势 0.35、动量 0.30、波动 0.15、反转 0.20），
  返回按综合分从高到低的品种列表。
- ``heatmap`` 返回可直接给 UI 的 ``(labels, values, normalized_01)``。

防未来函数：仅使用 t 时刻及之前数据。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "CrossSectionResult",
    "compute_scores",
    "rank_symbols",
    "heatmap",
]

DEFAULT_WEIGHTS: Dict[str, float] = {
    "trend": 0.35,
    "momentum": 0.30,
    "reversal": 0.20,
    "volatility": 0.15,
}


@dataclass
class CrossSectionResult:
    """横截面筛选结果。"""

    scores: np.ndarray  # [N品种, 4]
    symbol_order: List[str]  # scores 行顺序
    composite: np.ndarray  # [N品种] 综合分
    top: List[str]
    bottom: List[str]
    elapsed_ms: float
    weights: Dict[str, float] = field(default_factory=dict)

    def df(self) -> pd.DataFrame:
        """返回分数 DataFrame，行为品种，列为 4 个分项 + composite。"""
        cols = ["trend", "momentum", "reversal", "volatility"]
        df = pd.DataFrame(self.scores, index=list(self.symbol_order), columns=cols)
        df["composite"] = self.composite
        return df


def _trend_score(close: pd.Series, lookback: int = 60) -> float:
    """趋势分：close 偏离 MA(lookback) 的幅度。"""
    if len(close) < lookback:
        return 0.0
    ma = close.iloc[-lookback:].mean()
    if ma == 0:
        return 0.0
    return float(close.iloc[-1] / ma - 1.0)


def _volatility_score(close: pd.Series, lookback: int = 60) -> float:
    """波动分：lookback 日年化历史波动率（%）。"""
    if len(close) < 2:
        return 0.0
    ret = close.iloc[-(lookback + 1):].pct_change().dropna()
    if ret.empty:
        return 0.0
    return float(ret.std(ddof=0) * math.sqrt(252.0) * 100.0)


def _momentum_score(close: pd.Series, lookback: int = 20) -> float:
    """动量分：近 lookback 日涨跌幅。"""
    if len(close) <= lookback:
        return 0.0
    prev = close.iloc[-1 - lookback]
    if prev == 0:
        return 0.0
    return float(close.iloc[-1] / prev - 1.0)


def _reversal_score(close: pd.Series, lookback: int = 5) -> float:
    """反转分：近 lookback 日涨跌幅（捕捉短促急涨/急跌后的反转）。"""
    if len(close) <= lookback:
        return 0.0
    prev = close.iloc[-1 - lookback]
    if prev == 0:
        return 0.0
    return float(close.iloc[-1] / prev - 1.0)


def compute_scores(
    data: Dict[str, pd.DataFrame],
    weights: Optional[Dict[str, float]] = None,
) -> CrossSectionResult:
    """对全市场品种计算 4 个横截面分数并给出综合排名。

    参数:
        data: {品种代码: DataFrame}。DataFrame 至少含 ``close`` 列，
            可选含 ``volume``。列名大小写敏感。
        weights: 4 个分项的权重。None 用默认权重
            (趋势 0.35 / 动量 0.30 / 反转 0.20 / 波动 0.15)。

    返回:
        CrossSectionResult

    异常:
        ValueError: data 为空、或权重缺失键、或权值和 ≤0。
    """
    t0 = time.perf_counter()
    if not data:
        raise ValueError("data must be non-empty dict")
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    for key in DEFAULT_WEIGHTS:
        if key not in w:
            raise ValueError(f"missing weight key: {key}")
    total = sum(w.values())
    if total <= 0:
        raise ValueError("sum(weights) must be > 0")
    norm = {k: v / total for k, v in w.items()}

    order: List[str] = list(data.keys())
    n = len(order)
    raw = np.zeros((n, 4), dtype=float)
    valid_mask = np.ones(n, dtype=bool)
    for i, sym in enumerate(order):
        df = data[sym]
        if df is None or len(df) < 2 or "close" not in df.columns:
            valid_mask[i] = False
            continue
        close = df["close"].astype(float).dropna()
        if len(close) < 2:
            valid_mask[i] = False
            continue
        raw[i, 0] = _trend_score(close)
        raw[i, 1] = _volatility_score(close)
        raw[i, 2] = _momentum_score(close)
        raw[i, 3] = _reversal_score(close)

    # 横截面 z-score：只用有效品种
    idx = np.where(valid_mask)[0]
    if len(idx) >= 2:
        cols_mean = raw[idx].mean(axis=0)
        cols_std = raw[idx].std(axis=0, ddof=0)
        cols_std[cols_std == 0] = 1.0  # 防止除零
        z = (raw - cols_mean) / cols_std
    else:
        z = raw.copy()

    composite = (
        z * np.array(
            [
                norm["trend"],
                norm["volatility"],
                norm["momentum"],
                norm["reversal"],
            ],
            dtype=float,
        )
    ).sum(axis=1)

    ranked = np.argsort(-composite)
    top = [order[i] for i in ranked[:5]]
    bottom = [order[i] for i in ranked[-5:]]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return CrossSectionResult(
        scores=z,
        symbol_order=order,
        composite=composite,
        top=top,
        bottom=bottom,
        elapsed_ms=elapsed_ms,
        weights=norm,
    )


def rank_symbols(
    data: Dict[str, pd.DataFrame],
    weights: Optional[Dict[str, float]] = None,
) -> List[str]:
    """按综合分从高到低返回品种列表。"""
    res = compute_scores(data, weights=weights)
    ranked = np.argsort(-res.composite)
    return [res.symbol_order[i] for i in ranked]


def heatmap(
    data: Dict[str, pd.DataFrame],
    weights: Optional[Dict[str, float]] = None,
) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """返回热力图数据：(品种标签, 4 列 z 分数, [0,1] 归一分)。

    归一化方式：逐列 min-max → [0, 1]。
    """
    res = compute_scores(data, weights=weights)
    z = res.scores
    mn = z.min(axis=0)
    mx = z.max(axis=0)
    rng = mx - mn
    rng[rng == 0] = 1.0
    norm01 = (z - mn) / rng
    return list(res.symbol_order), z, norm01
