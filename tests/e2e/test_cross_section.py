"""M6.1 横截面筛选 e2e：39 品种 4 分计算 + 排序 + 热力图。"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai.cross_section import (  # noqa: E402
    CrossSectionResult,
    compute_scores,
    heatmap,
    rank_symbols,
)

N_SYMBOLS = 39
N_DAYS = 120
SEED = 2026


def _make_universe(seed: int = SEED, n: int = N_SYMBOLS) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    base = rng.uniform(3000, 80000, n)
    for i in range(n):
        rets = rng.normal(loc=0.0002 * (i % 5), scale=0.015 + 0.002 * (i % 7), size=N_DAYS)
        close = base[i] * np.cumprod(1 + rets)
        volume = rng.integers(1000, 20000, N_DAYS).astype(float)
        idx = pd.date_range("2026-01-01", periods=N_DAYS, freq="D")
        out[f"SYM{i:02d}"] = pd.DataFrame(
            {"open": close * 0.999, "close": close, "volume": volume}, index=idx
        )
    return out


def main() -> int:
    data = _make_universe()
    assert len(data) == N_SYMBOLS, "universe size mismatch"

    t0 = time.perf_counter()
    res = compute_scores(data)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert isinstance(res, CrossSectionResult)
    assert res.scores.shape == (N_SYMBOLS, 4), res.scores.shape
    assert res.composite.shape == (N_SYMBOLS,)
    assert len(res.top) == 5 and len(res.bottom) == 5
    assert res.elapsed_ms < 2000.0, f"too slow: {res.elapsed_ms:.1f}ms"
    print(f"[OK] compute_scores {elapsed_ms:.1f}ms top={res.top}")

    # 排序：综合分从高到低
    ranked = rank_symbols(data)
    assert len(ranked) == N_SYMBOLS
    sym_to_idx = {s: i for i, s in enumerate(res.symbol_order)}
    cs = res.composite
    for i in range(len(ranked) - 1):
        a = cs[sym_to_idx[ranked[i]]]
        b = cs[sym_to_idx[ranked[i + 1]]]
        assert a >= b - 1e-12, f"not sorted desc at {i}: {a} < {b}"
    print(f"[OK] rank_symbols head={ranked[:3]}")

    # 热力图：z + [0,1] 归一
    labels, z, norm01 = heatmap(data)
    assert labels == res.symbol_order
    assert z.shape == norm01.shape == (N_SYMBOLS, 4)
    assert norm01.min() >= -1e-9 and norm01.max() <= 1 + 1e-9
    print(f"[OK] heatmap labels={len(labels)} norm01∈[{norm01.min():.2f},{norm01.max():.2f}]")

    # df 输出
    df = res.df()
    assert list(df.columns) == ["trend", "momentum", "reversal", "volatility", "composite"]
    assert len(df) == N_SYMBOLS
    print(f"[OK] df head:")
    print(df.head())

    # 边界：数据不足
    data_short = {k: v.head(10) for k, v in data.items()}
    res2 = compute_scores(data_short)
    assert res2.scores.shape == (N_SYMBOLS, 4)
    print("[OK] short-data fallback")

    # 权重缺键
    try:
        compute_scores(data, weights={"trend": 1.0})
        raise AssertionError("expected ValueError")
    except ValueError:
        print("[OK] missing weight key -> ValueError")

    # 空 data
    try:
        compute_scores({})
        raise AssertionError("expected ValueError")
    except ValueError:
        print("[OK] empty data -> ValueError")

    print(f"ALL-OK total={time.perf_counter()-t0:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
