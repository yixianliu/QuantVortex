"""M3-04 特征缓存串味与线程竞争修复 —— pytest 形态。

由散落脚本 ``tests/test_m3_04.py``（模块级 ``PASS/FAIL`` 列表 + ``check(name,cond,detail)``
辅助 + 结尾 ``if FAIL: sys.exit(1)``，0 个 ``def test_*``）机械改写：
每段 ``check(...)`` 收敛成 ``assert cond, f"{name} — {detail}"``，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 原脚本 ④ 的两处 ``try/except``-expects-``TypeError`` 改 ``pytest.raises(TypeError)``。
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd
import pytest

from futures_quant.ai.features import build_features, _IndicatorLRUCache


def _make_df(n=320, seed=1, base=3500.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.008, n)
    close = base * np.exp(np.cumsum(r))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    op = np.concatenate([[close[0]], close[:-1]])
    vol = rng.integers(1000, 9000, n).astype(float)
    return pd.DataFrame(
        {"open": op, "high": high, "low": low, "close": close, "volume": vol},
        index=pd.date_range("2023-01-02", periods=n, freq="D"),
    )


def test_cache_key_includes_content_fingerprint():
    """① 缓存 key 含 close 尾部内容指纹：同长度/同末索引但中段价格不同 → 不串味。"""
    _IndicatorLRUCache.clear()
    _a = _make_df(320, seed=1)
    _b = _make_df(320, seed=1)
    _b.iloc[100:120, _b.columns.get_loc("close")] += 77.0  # 只改中段，保持长度与末索引
    assert len(_a) == len(_b) and str(_a.index[-1]) == str(_b.index[-1]), "两份数据长度与末索引相同"

    ia, Fa, _ = build_features(_a, extended=True, symbol="RB", period="D")
    ib, Fb, _ = build_features(_b, extended=True, symbol="RB", period="D")
    diff = float(np.nanmax(np.abs(Fa.values - Fb.values)))
    assert diff > 1e-6, f"中段改动后特征矩阵确实不同（未被旧缓存串味） — max|ΔF|={diff:.6f}"
    assert _IndicatorLRUCache.stats()["size"] == 2, \
        f"缓存条目数为 2（两份数据各占一条） — {dict(_IndicatorLRUCache.stats())}"


def test_deepcopy_isolation():
    """② build_features 取用与入库均为深拷贝：调用方改写返回值不污染缓存。"""
    _IndicatorLRUCache.clear()
    _d = _make_df(300, seed=5)
    i1, F1, _ = build_features(_d, extended=True, symbol="CU", period="D")
    i1["close"] = -1.0  # 恶意改写返回值
    i1["RSI14"] = 999.0
    i2, F2, _ = build_features(_d, extended=True, symbol="CU", period="D")
    assert i1 is not i2, "返回的 ind 与缓存对象非同一引用"
    assert float(i2["close"].iloc[-1]) == float(_d["close"].iloc[-1]) \
        and float(i2["RSI14"].iloc[-1]) != 999.0, \
        "改写返回值后再次取缓存不受污染"


def test_a_symbol_cache_does_not_pollute_b():
    """③ A 品种缓存不污染 B 品种；反向回填二次取缓存结果一致。"""
    _IndicatorLRUCache.clear()
    _da = _make_df(300, seed=11, base=3500.0)
    _db = _make_df(300, seed=11, base=72000.0)  # 同形状、同噪声、不同价位
    iaa, Fa, _ = build_features(_da, extended=True, symbol="RB", period="D")
    ibb, Fb, _ = build_features(_db, extended=True, symbol="AU", period="D")
    assert float(_da["close"].mean()) * 10 < float(_db["close"].mean()), "两品种 close 量级差异巨大"
    assert abs(float(np.nanmean(Fa.values[:, 0])) - float(np.nanmean(Fb.values[:, 0]))) >= 0.0 \
        and float(iaa["close"].iloc[-1]) != float(ibb["close"].iloc[-1]), "RB 结果不含 AU 数据"
    assert _IndicatorLRUCache.stats()["symbols"] == ["AU", "RB"], \
        f"缓存按品种分条存放 — {dict(_IndicatorLRUCache.stats())['symbols']}"
    ibb2, Fb2, _ = build_features(_db, extended=True, symbol="AU", period="D")
    assert np.allclose(Fb.values, Fb2.values, equal_nan=True), "AU 二次取缓存结果一致"


def test_symbol_period_keyword_only():
    """④ symbol / period 为 keyword-only 必填，缺省或位置传参均抛 TypeError。"""
    with pytest.raises(TypeError, match=""):
        build_features(_make_df(200))
    with pytest.raises(TypeError):
        build_features(_make_df(200), True, "RB", "D")  # 位置传参应被拒绝


def test_concurrent_threads_stable():
    """⑤ 8 线程并发对不同品种调用 → 结果稳定且与单线程完全一致（含 3 轮）。"""
    _IndicatorLRUCache.clear()
    _syms = [f"S{i}" for i in range(8)]
    _dfs = {s: _make_df(260, seed=100 + i, base=1000.0 * (i + 1)) for i, s in enumerate(_syms)}

    single = {}
    for s in _syms:
        _i, _F, _ = build_features(_dfs[s], extended=True, symbol=s, period="D")
        single[s] = _F.values.copy()

    conc, errs = {}, []

    def _worker(sym):
        try:
            _i, _F, _ = build_features(_dfs[sym], extended=True, symbol=sym, period="D")
            conc[sym] = _F.values.copy()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{sym}: {e}")

    ths = [threading.Thread(target=_worker, args=(s,)) for s in _syms]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert not errs, f"并发无异常 — {'; '.join(errs)[:160]}"
    assert len(conc) == 8, "并发覆盖全部 8 个品种"
    assert all(np.allclose(single[s], conc[s], equal_nan=True) for s in _syms if s in conc), \
        "并发结果与单线程逐元素一致"

    # 反复并发 3 轮，结果仍须完全一致（排除偶发竞争）
    for _ in range(3):
        _IndicatorLRUCache.clear()
        conc2, e2 = {}, []

        def _w2(sym):
            try:
                _i, _F, _ = build_features(_dfs[sym], extended=True, symbol=sym, period="D")
                conc2[sym] = _F.values.copy()
            except Exception as e:  # noqa: BLE001
                e2.append(str(e))

        ts = [threading.Thread(target=_w2, args=(s,)) for s in _syms]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert not e2 and all(np.allclose(single[s], conc2[s], equal_nan=True) for s in _syms), \
            "并发 3 轮结果保持稳定"


def test_ensemble_passthrough_symbol():
    """⑥ ensemble 透传 symbol（不再落到 UNKNOWN 键）。"""
    from futures_quant.ai.ensemble import MultiPeriodEnsemble, PeriodModel, _TreeModel

    ens = MultiPeriodEnsemble(periods=("D",), hidden=8, seed=3, symbol="RB2601")
    assert all(getattr(m, "symbol", None) == "RB2601" for m in ens.models), \
        f"MultiPeriodEnsemble.symbol 已透传 — {[getattr(m, 'symbol', None) for m in ens.models]}"
    assert PeriodModel("D").symbol == "UNKNOWN" and _TreeModel("D").symbol == "UNKNOWN", \
        "PeriodModel / _TreeModel 默认 symbol 为 UNKNOWN（仅兜底）"


def test_cache_key_five_segments():
    """⑦ 缓存 key 结构含 5 段（symbol, period, len, last_index, fingerprint）。"""
    _df = _make_df(200)
    k = _IndicatorLRUCache._key("RB", "D", _df)
    assert len(k) == 5, f"key 为 5 段 — {k}"
    assert len(k[4]) == 8 and all(c in "0123456789abcdef" for c in k[4]), \
        f"fingerprint 为 8 位 hex — {k[4]}"
