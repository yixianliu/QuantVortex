"""M3-04 验证：特征缓存串味与线程竞争修复。

验收点（对应 UPGRADE_PLAN_V5 M3-04）：
  ① 缓存 key 含 close 尾部内容指纹：同长度 / 同末索引但内容不同 → 不串味；
  ② build_features 取用与入库均为深拷贝：调用方改写不污染缓存；
  ③ A 品种缓存不会污染 B 品种；
  ④ symbol / period 为 keyword-only 必填，缺省抛 TypeError；
  ⑤ 8 线程并发对不同品种调用 → 结果稳定且与单线程完全一致。
"""
import os
import sys
import threading

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from futures_quant.ai.features import (  # noqa: E402
    build_features,
    _IndicatorLRUCache,
)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


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


print("\n测试 ①: 缓存 key 含内容指纹（同长度 / 同末索引但中段价格不同）")
_IndicatorLRUCache.clear()
_a = _make_df(320, seed=1)
_b = _make_df(320, seed=1)
# 只改中段价格，保持长度与末索引一致 —— 旧 key 会误命中
_b.iloc[100:120, _b.columns.get_loc("close")] += 77.0
check("两份数据长度与末索引相同", len(_a) == len(_b) and str(_a.index[-1]) == str(_b.index[-1]))
ia, Fa, _ = build_features(_a, extended=True, symbol="RB", period="D")
ib, Fb, _ = build_features(_b, extended=True, symbol="RB", period="D")
diff = float(np.nanmax(np.abs(Fa.values - Fb.values)))
check("中段改动后特征矩阵确实不同（未被旧缓存串味）", diff > 1e-6, f"max|ΔF|={diff:.6f}")
check("缓存条目数为 2（两份数据各占一条）", _IndicatorLRUCache.stats()["size"] == 2,
      str(_IndicatorLRUCache.stats()))

print("\n测试 ②: 深拷贝隔离（调用方改写不污染缓存）")
_IndicatorLRUCache.clear()
_d = _make_df(300, seed=5)
i1, F1, _ = build_features(_d, extended=True, symbol="CU", period="D")
i1["close"] = -1.0            # 恶意改写返回值
i1["RSI14"] = 999.0
i2, F2, _ = build_features(_d, extended=True, symbol="CU", period="D")
check("返回的 ind 与缓存对象非同一引用", i1 is not i2)
check("改写返回值后再次取缓存不受污染",
      float(i2["close"].iloc[-1]) == float(_d["close"].iloc[-1]) and float(i2["RSI14"].iloc[-1]) != 999.0,
      f"close={float(i2['close'].iloc[-1]):.2f}, RSI14={float(i2['RSI14'].iloc[-1]):.3f}")

print("\n测试 ③: A 品种缓存不污染 B 品种")
_IndicatorLRUCache.clear()
_da = _make_df(300, seed=11, base=3500.0)
_db = _make_df(300, seed=11, base=72000.0)   # 同形状、同噪声、不同价位
iaa, Fa, _ = build_features(_da, extended=True, symbol="RB", period="D")
ibb, Fb, _ = build_features(_db, extended=True, symbol="AU", period="D")
check("两品种 close 量级差异巨大", float(_da["close"].mean()) * 10 < float(_db["close"].mean()))
check("RB 结果不含 AU 数据", abs(float(np.nanmean(Fa.values[:, 0])) - float(np.nanmean(Fb.values[:, 0]))) >= 0.0
      and float(iaa["close"].iloc[-1]) != float(ibb["close"].iloc[-1]))
check("缓存按品种分条存放", _IndicatorLRUCache.stats()["symbols"] == ["AU", "RB"],
      str(_IndicatorLRUCache.stats()["symbols"]))
# 反向回填：AU 取第二次须与第一次完全一致（稳定，非偶发）
ibb2, Fb2, _ = build_features(_db, extended=True, symbol="AU", period="D")
check("AU 二次取缓存结果一致", np.allclose(Fb.values, Fb2.values, equal_nan=True))

print("\n测试 ④: symbol / period 为 keyword-only 必填")
try:
    build_features(_make_df(200))
    check("缺 symbol/period 抛 TypeError", False, "未抛异常")
except TypeError as e:
    check("缺 symbol/period 抛 TypeError", True, str(e)[:80])
try:
    build_features(_make_df(200), True, "RB", "D")   # 位置传参应被拒绝
    check("位置传参被拒绝（keyword-only）", False, "未抛异常")
except TypeError:
    check("位置传参被拒绝（keyword-only）", True)

print("\n测试 ⑤: 8 线程并发（不同品种）结果与单线程一致")
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
check("并发无异常", not errs, "; ".join(errs)[:160])
check("并发覆盖全部 8 个品种", len(conc) == 8)
allclose = all(np.allclose(single[s], conc[s], equal_nan=True) for s in _syms if s in conc)
worst = max((float(np.nanmax(np.abs(single[s] - conc[s]))) for s in _syms if s in conc), default=-1.0)
check("并发结果与单线程逐元素一致", allclose, f"max|Δ|={worst:.3e}")

# 反复并发 3 轮，结果仍须完全一致（排除偶发竞争）
stable = True
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
    if e2 or not all(np.allclose(single[s], conc2[s], equal_nan=True) for s in _syms):
        stable = False
check("并发 3 轮结果保持稳定", stable)

print("\n测试 ⑥: ensemble 透传 symbol（不再落到 UNKNOWN 键）")
from futures_quant.ai.ensemble import MultiPeriodEnsemble, PeriodModel, _TreeModel  # noqa: E402

ens = MultiPeriodEnsemble(periods=("D",), hidden=8, seed=3, symbol="RB2601")
check("MultiPeriodEnsemble.symbol 已透传",
      all(getattr(m, "symbol", None) == "RB2601" for m in ens.models),
      str([getattr(m, "symbol", None) for m in ens.models]))
check("PeriodModel / _TreeModel 默认 symbol 为 UNKNOWN（仅兜底）",
      PeriodModel("D").symbol == "UNKNOWN" and _TreeModel("D").symbol == "UNKNOWN")

print("\n测试 ⑦: 缓存 key 结构含 5 段（symbol, period, len, last_index, fingerprint）")
_df = _make_df(200)
k = _IndicatorLRUCache._key("RB", "D", _df)
check("key 为 5 段", len(k) == 5, str(k))
check("fingerprint 为 8 位 hex", len(k[4]) == 8 and all(c in "0123456789abcdef" for c in k[4]), k[4])

print(f"\n{'=' * 60}")
print(f"M3-04 验证结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("test_m3_04.py 全绿")
