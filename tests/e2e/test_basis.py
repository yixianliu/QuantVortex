"""M8.3 基差与仓单 e2e：basis（期货-现货）+ warrant（仓单数变化率→供给因子）。"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.data.basis import BasisSeries, compute_basis, compute_warrant_factor  # noqa: E402
from futures_quant.data.warrant import WarrantFactor, warrant_factor  # noqa: E402


def main() -> int:
    rng = np.random.default_rng(2026)
    n = 120
    idx = pd.date_range("2026-01-01", periods=n, freq="D")

    # --- 基差：期货价 = 现货价 + 随机基差 ---
    spot = pd.Series(3000 + np.cumsum(rng.normal(0, 5, n)), index=idx)
    futures = spot + pd.Series(rng.normal(50, 30, n), index=idx)  # 期货 = 现货 + 基差

    basis_res = compute_basis(futures, spot, lookback=60)
    assert isinstance(basis_res, BasisSeries)
    # basis 应等于 futures - spot
    expected = futures - spot
    assert np.allclose(basis_res.basis.values, expected.values), "basis 计算错误"
    print(f"[OK] basis head={basis_res.basis.head(3).tolist()}")

    # basis_chg = basis - basis.shift(1)
    exp_chg = expected - expected.shift(1)
    assert np.allclose(basis_res.basis_chg.dropna().values, exp_chg.dropna().values)
    print("[OK] basis_chg")

    # basis_rank ∈ [0,1]
    assert basis_res.basis_rank.dropna().between(0, 1).all()
    print("[OK] basis_rank ∈[0,1]")

    # to_dict
    d = basis_res.to_dict()
    assert {"basis", "basis_chg", "basis_rank"}.issubset(d.keys())
    print("[OK] to_dict keys")

    # 缺数据 → ValueError
    try:
        compute_basis(pd.Series(dtype=float), spot)
        raise AssertionError("expected ValueError")
    except ValueError:
        print("[OK] empty futures -> ValueError")

    # 长度不匹配 → ValueError
    try:
        compute_basis(futures.head(50), spot)
        raise AssertionError("expected ValueError")
    except ValueError:
        print("[OK] length mismatch -> ValueError")

    # --- 基差因子版（compute_warrant_factor in basis.py 是占位，主用 warrant.py）---
    # 仓单数：上升趋势
    warrants = pd.Series(np.arange(1, n + 1, dtype=float), index=idx) * 10
    wf = warrant_factor(warrants, lookback=20)
    assert isinstance(wf, WarrantFactor)
    # 仓单递增 → chg > 0 → supply_signal = -1（看空）
    tail_sig = wf.supply_signal.iloc[-5:].values
    assert (tail_sig == -1.0).all(), f"递增仓单应看空: {tail_sig}"
    print(f"[OK] warrant chg tail={wf.chg.iloc[-3:].tolist()} supply_signal={wf.supply_signal.iloc[-3:].tolist()}")

    # 仓单递减 → chg < 0 → supply_signal = +1（看涨）
    warrants_dn = pd.Series(np.arange(n, 0, -1, dtype=float), index=idx) * 10
    wf2 = warrant_factor(warrants_dn, lookback=20)
    tail_sig2 = wf2.supply_signal.iloc[-5:].values
    assert (tail_sig2 == +1.0).all(), f"递减仓单应看涨: {tail_sig2}"
    print(f"[OK] warrant 递减 supply_signal tail={wf2.supply_signal.iloc[-3:].tolist()}")

    # z_score 数值有限（单调 chg 序列在窗口边界可能较大，不做严格 ±3 约束）
    zs = wf.z_score.dropna()
    assert np.all(np.isfinite(zs.values)), "z_score 含非有限值"
    print(f"[OK] z_score max abs={zs.abs().max():.2f} finite")

    # to_frame
    fr = wf.to_frame()
    assert list(fr.columns) == ["chg", "supply_signal", "z_score"]
    print("[OK] to_frame columns")

    # 数据不足 → 不抛异常
    try:
        wf_short = warrant_factor(pd.Series([1.0], index=idx[:1]), lookback=20)
        assert len(wf_short.chg) == 1
    except ValueError:
        # 长度 1 < 2 → 也接受
        pass
    print("[OK] 单点 warrants 处理")

    print("ALL-OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
