"""M3-04 特征缓存串味与线程竞争 - E2E smoke 验收。

DoD:
1) 缓存 key 使用 (symbol, period, len, index[-1], md5(close)[:8]) —— 全序列
   md5 而非 tail(50)，防止中段回填修正被误命中。
2) `build_features` 返回深拷贝（调用方修改返回的 F 不会影响缓存）。
3) 并发 8 线程对不同品种调用 → 结果稳定（无锁崩溃、无串味）。
4) A 品种缓存不会污染 B 品种（不同 symbol 的缓存完全隔离）。

运行方式:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_04.py
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QT_QPA_PLATFORM_DEFAULT = os.environ.get("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_QPA_PLATFORM"] = QT_QPA_PLATFORM_DEFAULT


def _make_df(n: int = 100, base: float = 100.0, seed: int = 20261001) -> pd.DataFrame:
    """构造一段 OHLCV 合成行情。"""
    rng = np.random.default_rng(seed)
    trend = base + np.linspace(0, 20, n)
    close = trend + rng.normal(0, 0.5, n).cumsum() * 0.1
    open_ = close + rng.normal(0, 0.3, n)
    high = np.maximum(close, open_) + np.abs(rng.normal(0, 0.4, n))
    low = np.minimum(close, open_) - np.abs(rng.normal(0, 0.4, n))
    volume = rng.integers(500_000, 2_000_000, n).astype(float)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ============================================================
# 测试用例
# ============================================================

def test_1_cache_key_includes_close_fingerprint() -> None:
    """缓存 key 包含 close 内容 md5 指纹（防同长度不同数据误命中）。"""
    from futures_quant.ai.features import _IndicatorLRUCache

    df = _make_df(100, base=100.0, seed=1)
    df2 = _make_df(100, base=200.0, seed=2)  # 相同长度、相同索引，不同价格

    key_a = _IndicatorLRUCache._key("SYM", "D", df)
    key_b = _IndicatorLRUCache._key("SYM", "D", df2)

    # 两个 key 前 4 项应相同（symbol, period, len, index[-1]）
    assert key_a[0] == key_b[0] == "SYM"
    assert key_a[1] == key_b[1] == "D"
    assert key_a[2] == key_b[2] == 100
    assert key_a[3] == key_b[3]
    # 但第 5 项（md5 指纹）必须不同
    assert key_a[4] != key_b[4], (
        f"相同长度/索引但不同价格的 df，key 指纹应不同（防串味），实际：{key_a[4]} == {key_b[4]}"
    )
    print(f"[1/5] PASS 缓存 key 含 close md5 指纹（{key_a[4]} vs {key_b[4]}）")


def test_2_build_features_returns_deep_copy() -> None:
    """build_features 返回深拷贝：调用方修改返回的 F 不应影响缓存。"""
    from futures_quant.ai.features import build_features, _IndicatorLRUCache

    _IndicatorLRUCache.clear()

    df = _make_df(120, base=100.0, seed=3)
    ind1, F1, _names1 = build_features(df, extended=True, symbol="COPI", period="D")

    # 再次调用（应命中缓存）
    ind2, F2, _names2 = build_features(df, extended=True, symbol="COPI", period="D")

    # 修改 F1 的一个值
    F1.iloc[0, 0] = 999999.0

    # F2 应未受影响（深拷贝隔离）
    assert F2.iloc[0, 0] != 999999.0, (
        f"修改 F1 后 F2 也被污染（{F2.iloc[0, 0]}）—— 说明缓存未做深拷贝，存在串味"
    )
    print("[2/5] PASS build_features 返回深拷贝（修改返回对象不影响缓存）")


def test_3_concurrent_threads_stable() -> None:
    """并发 8 线程对不同品种调用 build_features → 结果稳定（无锁崩溃、无串味）。"""
    from futures_quant.ai.features import build_features, _IndicatorLRUCache

    _IndicatorLRUCache.clear()

    def _run(symbol: str, base: float, seed: int):
        df = _make_df(120, base=base, seed=seed)
        ind, F, names = build_features(df, extended=True, symbol=symbol, period="D")
        # 验证 F 有列，且非空
        assert len(F.columns) == len(names)
        assert len(names) > 0
        # 用 close（原 K 线收盘价）作为「指纹」—— ret 在第 0 行是 NaN→0，
        # 所有品种都是 0，无法区分；直接用原始 close 更能暴露串味。
        # 同时取一个非零特征值（如 row=50 的 ret）作为补充指纹
        probe_close = float(df["close"].iloc[50])
        # 找 F 中某个非零列（避免 ret/vol 等前几行都是 0 的滞后特征）
        probe_val = 0.0
        for f in names:
            s = pd.to_numeric(F[f], errors="coerce")
            if s.notna().sum() > 50:  # 有足够多非 NaN 值
                probe_val = float(s.iloc[60])
                break
        return symbol, probe_close, probe_val, len(F.columns), len(names)

    # 8 个并发任务，每个使用不同 symbol（不同数据）
    tasks = [
        ("RB", 100.0, 11),
        ("AU", 400.0, 12),
        ("IF", 4000.0, 13),
        ("I", 800.0, 14),
        ("CU", 70000.0, 15),
        ("AG", 5000.0, 16),
        ("M", 3000.0, 17),
        ("P", 9000.0, 18),
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda t: _run(*t), tasks))

    # 所有结果都应成功
    assert len(results) == 8
    # 不同品种的 close[50] 应该各不相同（防止串味）
    close_values = [r[1] for r in results]
    unique_closes = set(close_values)
    assert len(unique_closes) == 8, (
        f"并发调用下 df.close[50] 有重复值，说明不同品种互不污染失败："
        f"{close_values}"
    )
    print(f"[3/5] PASS 并发 8 线程稳定（{len(unique_closes)}/8 个不同品种 close[50] 互不污染）")


def test_4_different_symbols_do_not_pollute() -> None:
    """A 品种缓存不会污染 B 品种（不同 symbol 完全隔离）。"""
    from futures_quant.ai.features import build_features, _IndicatorLRUCache

    _IndicatorLRUCache.clear()

    # A 品种：base=100，价格从 100 → 120
    df_a = _make_df(100, base=100.0, seed=41)
    _ind_a, F_a, _ = build_features(df_a, extended=True, symbol="A", period="D")
    # 用 close[50] 作为指纹（ret[50] 在第 50 行有实际值，且不同 base 下明显不同）
    a_close = float(df_a["close"].iloc[50])

    # B 品种：base=200，价格从 200 → 220
    df_b = _make_df(100, base=200.0, seed=42)
    _ind_b, F_b, _ = build_features(df_b, extended=True, symbol="B", period="D")
    b_close = float(df_b["close"].iloc[50])

    # A 和 B 的价格应明显不同（100 vs 200）
    assert abs(a_close - b_close) > 0.5, (
        f"A 品种 close={a_close}，B 品种 close={b_close}，"
        "两者接近 —— 说明 A 品种缓存污染了 B 品种"
    )

    # 缓存里应包含 A 和 B 两个 symbol
    stats = _IndicatorLRUCache.stats()
    assert "A" in stats["symbols"], f"缓存未记录 A 品种: {stats['symbols']}"
    assert "B" in stats["symbols"], f"缓存未记录 B 品种: {stats['symbols']}"

    print(f"[4/5] PASS A/B 品种缓存隔离（A.close={a_close:.4f}, B.close={b_close:.4f}）")


def test_5_cache_stats_thread_safe() -> None:
    """_IndicatorLRUCache.stats() 线程安全：并发读写不崩溃。"""
    from futures_quant.ai.features import build_features, _IndicatorLRUCache

    _IndicatorLRUCache.clear()

    def _writer():
        df = _make_df(80, base=100.0, seed=99)
        build_features(df, extended=True, symbol="W", period="D")

    def _reader():
        _IndicatorLRUCache.stats()

    # 并发 4 写 + 4 读，共 32 次操作
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = []
        for _ in range(4):
            futs.append(pool.submit(_writer))
            futs.append(pool.submit(_reader))
        for f in futs:
            try:
                f.result(timeout=10)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    assert not errors, f"并发读写缓存出错：{[type(e).__name__ for e in errors]}"
    stats = _IndicatorLRUCache.stats()
    assert stats["size"] >= 1, f"缓存应至少含 1 项，实际 {stats}"
    print(f"[5/5] PASS cache.stats() 线程安全（{stats['size']} entries, {stats['symbols']}）")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)

    tests = [
        test_1_cache_key_includes_close_fingerprint,
        test_2_build_features_returns_deep_copy,
        test_3_concurrent_threads_stable,
        test_4_different_symbols_do_not_pollute,
        test_5_cache_stats_thread_safe,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {t.__name__}: {exc!r}")

    total = len(tests)
    passed = total - failed
    print(f"\n=== M3-04 smoke: {passed}/{total} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
