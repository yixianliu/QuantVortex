"""M6.2 板块联动 e2e：6 板块因子 + 板块内 rank + 相关性验收。"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.analysis.sector import DEFAULT_SECTOR_MAP, SectorFactor  # noqa: E402


def _make_universe(seed: int = 2026, n_days: int = 250) -> dict:
    """按 DEFAULT_SECTOR_MAP 取 6 个板块各 2-3 个品种造数据。"""
    rng = np.random.default_rng(seed)
    picked: dict = {}
    for sec in ["黑色", "有色", "贵金属", "能化", "农产品", "金融"]:
        members = [s for s, m in DEFAULT_SECTOR_MAP.items() if m == sec]
        for sym in members[:3]:
            base = rng.uniform(2000, 60000)
            rets = rng.normal(0.0003, 0.018, n_days)
            close = base * np.cumprod(1 + rets)
            picked[sym] = pd.DataFrame(
                {"close": close}, index=pd.date_range("2025-09-01", periods=n_days, freq="D")
            )
    return picked


def main() -> int:
    data = _make_universe()
    sf = SectorFactor(data)

    sectors = sf.sectors()
    assert len(sectors) == 6, f"expected 6 sectors, got {sectors}"
    print(f"[OK] sectors={sectors}")

    fr = sf.factor_returns(window=20)
    for sec in sectors:
        assert sec in fr, f"missing sector factor {sec}"
        assert np.isfinite(fr[sec]), f"factor {sec} not finite: {fr[sec]}"
    print(f"[OK] factor_returns window=20:")
    for sec, v in fr.items():
        print(f"      {sec:6s} {v:+.4f}")

    rank = sf.rank_in_sector(window=20)
    assert len(rank) == len(data), "rank should cover all symbols"
    for sym, (sec, r, c) in rank.items():
        assert sec in sectors
        assert 1 <= r <= c, f"rank out of range: {sym} r={r} c={c}"
    print(f"[OK] rank_in_sector {len(rank)} symbols, sample={list(rank.items())[:3]}")

    corr = sf.correlation_with_members(window=20)
    for sec in sectors:
        assert corr.get(sec, 0.0) > 0.6, f"corr too low for {sec}: {corr.get(sec)}"
    print(f"[OK] correlation_with_members >0.6: {corr}")

    fs = sf.factor_series(window=20)
    for sec in sectors:
        assert sec in fs and len(fs[sec]) > 0
    print(f"[OK] factor_series lengths={ {k: len(v) for k, v in fs.items()} }")

    print("ALL-OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
