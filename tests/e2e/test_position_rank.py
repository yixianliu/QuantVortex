"""M8.2 持仓排名结构 e2e：Top20 多/空集中度 + 多空比。"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.data.position_rank import (  # noqa: E402
    PositionRankStats,
    compute_rank_stats,
    concentration_top_n,
)


def main() -> int:
    rng = np.random.default_rng(2026)

    # --- 模拟 Top20 持仓排名（20 席位 × long/short）---
    long_vol = rng.integers(10000, 80000, 20).astype(float)
    short_vol = rng.integers(8000, 70000, 20).astype(float)
    df = pd.DataFrame({
        "rank": range(1, 21),
        "long_vol": long_vol,
        "short_vol": short_vol,
    })

    stats = compute_rank_stats(df, top_n=5)
    assert isinstance(stats, PositionRankStats)

    # 多空比 = 总多/总空
    expected_ratio = long_vol.sum() / short_vol.sum()
    assert abs(stats.long_short_ratio - expected_ratio) < 1e-6, (
        f"ratio {stats.long_short_ratio} vs {expected_ratio}"
    )
    print(f"[OK] long_short_ratio={stats.long_short_ratio:.3f}")

    # 集中度：前 5 大占全部比例
    exp_long_conc = np.sort(long_vol)[::-1][:5].sum() / long_vol.sum()
    exp_short_conc = np.sort(short_vol)[::-1][:5].sum() / short_vol.sum()
    assert abs(stats.long_top5_conc - exp_long_conc) < 1e-6, f"long conc {stats.long_top5_conc} vs {exp_long_conc}"
    assert abs(stats.short_top5_conc - exp_short_conc) < 1e-6
    assert 0.0 <= stats.long_top5_conc <= 1.0
    print(f"[OK] long_top5_conc={stats.long_top5_conc:.3f} short_top5_conc={stats.short_top5_conc:.3f}")

    # 单调性：集中度随 top_n 增大而增大
    c1 = concentration_top_n(long_vol.tolist(), n=3)
    c2 = concentration_top_n(long_vol.tolist(), n=5)
    c3 = concentration_top_n(long_vol.tolist(), n=10)
    assert c1 <= c2 <= c3, f"集中度单调性失败: c1={c1} c2={c2} c3={c3}"
    print(f"[OK] 集中度单调性 c3={c3:.3f} >= c2={c2:.3f} >= c1={c1:.3f}")

    # 多空比 >1 偏多 / <1 偏空
    df_bullish = df.copy()
    df_bullish["short_vol"] = df_bullish["long_vol"] * 0.5
    s_bull = compute_rank_stats(df_bullish)
    assert s_bull.long_short_ratio > 1.0
    df_bearish = df.copy()
    df_bearish["long_vol"] = df_bearish["short_vol"] * 0.5
    s_bear = compute_rank_stats(df_bearish)
    assert s_bear.long_short_ratio < 1.0
    print(f"[OK] 偏多 ratio={s_bull.long_short_ratio:.2f} 偏空 ratio={s_bear.long_short_ratio:.2f}")

    # 空持仓 → 边界
    df_zero = pd.DataFrame({"long_vol": [0.0, 0.0], "short_vol": [0.0, 0.0]})
    s_zero = compute_rank_stats(df_zero)
    assert np.isnan(s_zero.long_short_ratio)
    print("[OK] 全零持仓 -> ratio=NaN")

    # 缺列
    try:
        compute_rank_stats(pd.DataFrame({"long_vol": [1.0]}))
        raise AssertionError("expected ValueError")
    except ValueError:
        print("[OK] 缺 short_vol 列 -> ValueError")

    print("ALL-OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
