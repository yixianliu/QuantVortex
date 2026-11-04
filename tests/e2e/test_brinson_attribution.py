"""M6.6 Brinson 归因 e2e：品种归因（配置/选择/交互）+ 策略归因（趋势 vs 反转）。"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.analysis.brinson_attribution import (  # noqa: E402
    brinson_attribution,
    strategy_attribution,
)


def main() -> int:
    rng = np.random.default_rng(2026)
    syms = ["rb", "au", "i", "IF", "SR"]

    # --- Brinson 品种归因 ---
    # 组合 / 基准权重与收益
    pw = {"rb": 0.4, "au": 0.3, "i": 0.2, "IF": 0.05, "SR": 0.05}
    bw = {"rb": 0.25, "au": 0.25, "i": 0.25, "IF": 0.15, "SR": 0.10}
    pr = {s: float(rng.normal(0.001, 0.01)) for s in syms}
    br = {s: float(rng.normal(0.0005, 0.008)) for s in syms}

    res = brinson_attribution(pw, pr, bw, br)
    # 验收：归因之和 ≈ 组合收益 - 基准收益（±0.1%）
    port_total = sum(pw[s] * pr[s] for s in syms) / sum(pw.values())
    bench_total = sum(bw[s] * br[s] for s in syms) / sum(bw.values())
    diff = abs(res.total - (port_total - bench_total))
    assert diff < 0.001 + 1e-6, f"归因和 {res.total} 与 组合-基准 {port_total - bench_total} 偏差 {diff}"
    print(f"[OK] Brinson 归因和={res.total:.6f} vs 组合-基准={port_total - bench_total:.6f} 偏差={diff:.6f}")

    # 各分项
    assert res.allocation + res.selection + res.interaction == res.total
    df = res.detail_df()
    assert len(df) == len(syms)
    assert {"symbol", "allocation", "selection", "interaction"}.issubset(df.columns)
    print(f"[OK] 分项 allocation={res.allocation:.5f} selection={res.selection:.5f} interaction={res.interaction:.5f}")

    # 边界：权重为 0
    try:
        brinson_attribution({}, {"rb": 0.01}, {"rb": 1.0}, {"rb": 0.0})
        raise AssertionError("expected ValueError")
    except ValueError:
        print("[OK] 零权重 -> ValueError")

    # --- 策略归因 ---
    # 构造 4 品种 50 日随机收益
    ret_df = pd.DataFrame(
        {s: rng.normal(0.0, 0.01, 50) for s in syms},
        index=pd.date_range("2026-01-01", periods=50, freq="D"),
    )
    strat = strategy_attribution(ret_df)
    assert set(strat) >= {"trend", "reversal", "other", "total"}
    # 归因之和 ≈ 总收益
    assert abs(strat["trend"] + strat["reversal"] + strat["other"] - strat["total"]) < 0.01, (
        f"策略归因偏差: {strat['trend'] + strat['reversal'] + strat['other']} vs {strat['total']}"
    )
    print(f"[OK] 策略归因 trend={strat['trend']:.4f} reversal={strat['reversal']:.4f} "
          f"other={strat['other']:.4f} total={strat['total']:.4f}")

    # 含基准
    bench = pd.Series(rng.normal(0.0, 0.005, 50), index=ret_df.index)
    strat2 = strategy_attribution(ret_df, benchmark=bench)
    assert strat2["excess_vs_benchmark"] is not None
    print(f"[OK] 超额 vs 基准={strat2['excess_vs_benchmark']:.4f}")

    # 空 DataFrame
    empty = strategy_attribution(pd.DataFrame())
    assert empty["total"] == 0.0
    print("[OK] 空 DataFrame -> total=0")

    print("ALL-OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
