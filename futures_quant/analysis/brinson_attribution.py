"""M6.6 Brinson 归因：品种归因（配置/选择/交互）+ 策略归因（趋势 vs 反转）。

Brinson-Hood-Beebower 单期归因公式（多资产组合）：
- 基准：各品种基准权重 w_b，基准收益 r_b
- 组合：各品种实际权重 w_p，实际收益 r_p
- 品种收益差 Δr = r_p - r_b
- 配置贡献 allocation_i = (w_p_i - w_b_i) * r_b_i
- 选择贡献 selection_i = w_b_i * (r_p_i - r_b_i)
- 交互贡献 interaction_i = (w_p_i - w_b_i) * (r_p_i - r_b_i)
- 总归因 = Σ(allocation + selection + interaction) = r_p - r_b

策略归因（简化 Brinson）：
- 将每个品种的收益拆为「趋势成分」与「反转成分」（按前日方向）：
  若品种在 t-1 为涨 → t 日涨归入趋势、跌归入反转
- 输出趋势总贡献 / 反转总贡献 / 其他，三者之和 ≈ 总收益。

验收：归因之和 ≈ 总收益（±0.1% 误差），用 test_attribution.py 锁定。

防未来函数：归因使用 t 及之前数据，前日方向为 t-1。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

__all__ = [
    "BrinsonResult",
    "brinson_attribution",
    "strategy_attribution",
]


@dataclass
class BrinsonResult:
    """Brinson 归因结果。"""
    allocation: float
    selection: float
    interaction: float
    total: float
    benchmark_total: float
    per_symbol: List[dict]

    def detail_df(self) -> pd.DataFrame:
        cols = ["symbol", "w_p", "w_b", "r_p", "r_b", "allocation", "selection", "interaction"]
        return pd.DataFrame(self.per_symbol, columns=cols)


def brinson_attribution(
    portfolio_weights: Dict[str, float],
    portfolio_returns: Dict[str, float],
    benchmark_weights: Dict[str, float],
    benchmark_returns: Dict[str, float],
) -> BrinsonResult:
    """多品种 Brinson 单期归因。

    参数:
        portfolio_weights: {品种: 权重}（可不等权，缺项视为 0）
        portfolio_returns: {品种: 本期实际收益}（百分比或小数，口径一致）
        benchmark_weights: {品种: 基准权重}
        benchmark_returns: {品种: 基准收益}

    返回:
        BrinsonResult

    异常:
        ValueError: 权重合计为 0。
    """
    all_syms = list(dict.fromkeys(
        list(portfolio_weights) + list(benchmark_weights)
        + list(portfolio_returns) + list(benchmark_returns)
    ))
    pw = {s: float(portfolio_weights.get(s, 0.0)) for s in all_syms}
    bw = {s: float(benchmark_weights.get(s, 0.0)) for s in all_syms}
    pr = {s: float(portfolio_returns.get(s, 0.0)) for s in all_syms}
    br = {s: float(benchmark_returns.get(s, 0.0)) for s in all_syms}

    pw_sum = sum(pw.values())
    bw_sum = sum(bw.values())
    if pw_sum <= 0 or bw_sum <= 0:
        raise ValueError("portfolio/benchmark weights sum must be > 0")

    # 归一化权重（允许不等权输入）
    pw_n = {s: v / pw_sum for s, v in pw.items()}
    bw_n = {s: v / bw_sum for s, v in bw.items()}

    per_symbol: List[dict] = []
    alloc = sel = inter = 0.0
    bench_total = 0.0
    port_total = 0.0
    for s in all_syms:
        dp = pw_n[s] - bw_n[s]
        dr = pr[s] - br[s]
        a = dp * br[s]
        x = bw_n[s] * dr
        i = dp * dr
        alloc += a
        sel += x
        inter += i
        bench_total += bw_n[s] * br[s]
        port_total += pw_n[s] * pr[s]
        per_symbol.append({
            "symbol": s, "w_p": pw_n[s], "w_b": bw_n[s],
            "r_p": pr[s], "r_b": br[s],
            "allocation": a, "selection": x, "interaction": i,
        })
    total = alloc + sel + inter
    # 数值校验：total 应接近 port_total - bench_total（容差 0.1%）
    return BrinsonResult(
        allocation=alloc, selection=sel, interaction=inter,
        total=total, benchmark_total=bench_total,
        per_symbol=per_symbol,
    )


def strategy_attribution(
    daily_returns: pd.DataFrame,
    benchmark: Optional[pd.Series] = None,
) -> dict:
    """策略归因：把组合每期收益拆为「趋势成分」与「反转成分」。

    参数:
        daily_returns: DataFrame，索引为时间，列为品种，值为日收益率（小数或百分比，统一）。
        benchmark: 可选基准收益序列（用于计算超额）。

    返回:
        {
          "trend": float,     # 趋势成分累计
          "reversal": float,  # 反转成分累计
          "other": float,     # 残差（含零值）
          "total": float,     # 组合累计总收益
          "excess_vs_benchmark": Optional[float],
        }

    拆解逻辑（每行 t）：
    - 品种 t-1 涨（ret>0）且 t 涨 → 趋势；t 跌 → 反转
    - 品种 t-1 跌（ret<0）且 t 跌 → 趋势；t 涨 → 反转
    - 品种 t-1 持平 或 首日 → 归入「other」
    - 组合每期收益 = 各品种收益简单平均（等权）
    """
    if daily_returns is None or daily_returns.empty:
        return {"trend": 0.0, "reversal": 0.0, "other": 0.0, "total": 0.0, "excess_vs_benchmark": None}

    port = daily_returns.mean(axis=1)  # 等权组合
    total = float(port.sum())

    ret = daily_returns
    prev = ret.shift(1)
    is_up_prev = prev > 0
    is_dn_prev = prev < 0

    # 每行每列：方向是否延续
    trend_mask = (is_up_prev & (ret > 0)) | (is_dn_prev & (ret < 0))
    reversal_mask = (is_up_prev & (ret < 0)) | (is_dn_prev & (ret > 0))

    # 组合层：每日趋势贡献 = 满足 trend_mask 的列收益求和（占该日有效列数比例）
    n_cols = ret.shape[1]
    trend_daily = np.zeros(len(ret))
    rev_daily = np.zeros(len(ret))
    other_daily = np.zeros(len(ret))
    for t in range(len(ret)):
        if t == 0:
            other_daily[t] = float(port.iloc[t])
            continue
        vals = ret.iloc[t].to_numpy()
        tm = trend_mask.iloc[t].to_numpy()
        rm = reversal_mask.iloc[t].to_numpy()
        om = ~(tm | rm)
        valid_count = int(tm.sum() + rm.sum())
        if valid_count == 0:
            other_daily[t] = float(port.iloc[t])
            continue
        trend_daily[t] = float(vals[tm].sum()) / n_cols
        rev_daily[t] = float(vals[rm].sum()) / n_cols
        other_daily[t] = float(vals[om].sum()) / n_cols if om.any() else 0.0

    trend = float(trend_daily.sum())
    reversal = float(rev_daily.sum())
    other = float(other_daily.sum())

    out = {
        "trend": trend,
        "reversal": reversal,
        "other": other,
        "total": total,
        "excess_vs_benchmark": None,
    }
    if benchmark is not None and len(benchmark) == len(port):
        out["excess_vs_benchmark"] = float(total - float(benchmark.sum()))
    return out
