"""M6.3 多因子打分卡 e2e：技术面 + 量能 + AI概率 + 板块因子 → 0-100。"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.analysis.scorecard import (  # noqa: E402
    DEFAULT_WEIGHTS,
    Scorecard,
    rank_scorecards,
)


def _df(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    out = pd.DataFrame({"close": close})
    if volume is not None:
        out["volume"] = volume
    return out


def main() -> int:
    rng = np.random.default_rng(2026)

    # --- Case 1: 全量输入（4 子项都可用）---
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 100))
    vol = np.full(100, 1000.0)
    vol[-5:] = 3000.0  # 近 5 日放量
    df = _df(close, vol)
    sc = Scorecard(df, ai_prob=0.7, sector_rank=1, sector_size=5)
    c1 = sc.composite()
    assert 0 <= c1 <= 100, c1
    d = sc.detail()
    assert all(0 <= d[k] <= 1 for k in ["technical_norm", "volume_norm", "ai_prob_norm", "sector_norm"])
    assert d["composite"] == c1
    assert 0.0 <= d["technical_norm"] <= 1.0
    # 量能：量比 = 3000/1000 = 3 → norm 应饱和 1.0
    assert d["volume_norm"] == 1.0
    # AI 概率：0.7 直接
    assert abs(d["ai_prob_norm"] - 0.7) < 1e-9
    # 板块：rank 1 of 5 → norm 1.0
    assert d["sector_norm"] == 1.0
    print(f"[OK] full inputs composite={c1} detail={d}")

    # --- Case 2: 缺失 AI + 板块 → 中性 0.5 占位 ---
    sc2 = Scorecard(df)
    c2 = sc2.composite()
    d2 = sc2.detail()
    assert d2["ai_prob_norm"] == 0.5
    assert d2["sector_norm"] == 0.5
    assert 0 <= c2 <= 100
    print(f"[OK] missing-items composite={c2}")

    # --- Case 3: 数据不足 → 技术面缺失 ---
    short_df = _df(close[:30])
    sc3 = Scorecard(short_df, ai_prob=0.5)
    c3 = sc3.composite()
    assert 0 <= c3 <= 100
    assert sc3.detail()["technical_norm"] == 0.5
    print(f"[OK] short-data composite={c3}")

    # --- 批量排序：3 品种按综合分降序 ---
    data = {
        "A": _df(100 * np.cumprod(1 + rng.normal(0.001, 0.01, 100)), np.full(100, 1000.0)),
        "B": _df(100 * np.cumprod(1 + rng.normal(-0.001, 0.01, 100)), np.full(100, 1000.0)),
        "C": _df(100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 100)), np.full(100, 500.0)),
    }
    ranked = rank_scorecards(data, ai_probs={"A": 0.8, "B": 0.3}, sector_ranks={"A": 1, "B": 2, "C": 3},
                             sector_sizes={"A": 3, "B": 3, "C": 3})
    comps = [r["composite"] for r in ranked]
    assert comps == sorted(comps, reverse=True), f"not sorted desc: {comps}"
    print(f"[OK] rank_scorecards order={[r['symbol'] for r in ranked]} comps={comps}")

    # --- 权重默认值 ---
    assert set(DEFAULT_WEIGHTS) == {"technical", "volume", "ai_prob", "sector"}
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9
    print("[OK] DEFAULT_WEIGHTS sum=1")

    print("ALL-OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
