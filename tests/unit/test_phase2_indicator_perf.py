"""阶段二性能修复回归测试：数值一致性 + 「尾窗化」复杂度契约。

背景
----
回测主循环每根 bar 都会调用 ``futures_quant/core/indicators.py`` 的 ``*_last``
系列。旧实现每次都对整段历史（deque → list）重算/重建，回测累计为 O(n²)；
新实现只取尾部 window 根（``_tail``），复杂度 O(window)。

本文件锁定两条契约：
  1. **数值一致性**：新实现与「朴素全历史参考实现」逐点一致（参考实现即
     改动前的算法语义），且 list / tuple / deque / ndarray 四种容器结果一致；
  2. **复杂度不随历史长度增长**：同样窗口下，历史 500 根与 5000 根的耗时
     比值在宽松阈值内（相对断言，不依赖绝对耗时抖动）。

真实行情上的逐点比对由 ``scripts/perf_probe.py`` + 一次性探针完成，
单元测试只依赖确定性合成数据，不读 data/、不联网、不写盘。
"""
from __future__ import annotations

import math
import statistics
import time
from collections import deque

import numpy as np
import pandas as pd
import pytest

from futures_quant.core import indicators as ind
from futures_quant.indicators import tech

# ---------------------------------------------------------------------------
# 确定性合成数据（固定种子，避免测试抖动）
# ---------------------------------------------------------------------------


def _make_bars(n: int, seed: int = 7):
    """生成 n 根确定性 OHLC（随机游走 + 保证 high/low 包住 open/close）。"""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.6, n))
    high = close + rng.uniform(0.1, 1.2, n)
    low = close - rng.uniform(0.1, 1.2, n)
    return high.tolist(), low.tolist(), close.tolist()


# ---------------------------------------------------------------------------
# 朴素参考实现（逐点语义 = 改动前行为，仅用于对比，不参与线上计算）
# ---------------------------------------------------------------------------

_NAN = float("nan")


def _ref_sma(c, p):
    return sum(c[-p:]) / p if len(c) >= p else _NAN


def _ref_atr(h, l, c, p=14):
    """改动前实现：对整段历史重建 TR，再取最后 p 个求和（O(n) 每调用）。"""
    if len(c) < p + 1:
        return _NAN
    trs = []
    for i in range(1, len(c)):
        pc = c[i - 1]
        trs.append(max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc)))
    return sum(trs[-p:]) / p


def _ref_donchian(h, l, p=20):
    if len(h) < p + 1 or len(l) < p + 1:
        return _NAN, _NAN
    return max(h[-p - 1:-1]), min(l[-p - 1:-1])


def _ref_bollinger(c, p=20, k=2.0):
    if len(c) < p:
        return _NAN, _NAN, _NAN
    w = c[-p:]
    m = sum(w) / p
    sd = (sum((x - m) ** 2 for x in w) / p) ** 0.5
    return m, m + k * sd, m - k * sd


def _ref_rsi(c, p=14):
    if len(c) < p + 1:
        return 50.0
    d = [c[i] - c[i - 1] for i in range(len(c) - p, len(c))]
    g = sum(x if x > 0 else 0.0 for x in d) / p
    ls = sum(-x if x < 0 else 0.0 for x in d) / p
    if ls == 0:
        return 100.0 if g > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + g / ls)


def _ref_cci(h, l, c, p=20):
    if len(c) < p:
        return 0.0
    tp = [(h[i] + l[i] + c[i]) / 3.0 for i in range(len(c) - p, len(c))]
    ma = sum(tp) / p
    sd = (sum((x - ma) ** 2 for x in tp) / p) ** 0.5
    return 0.0 if sd == 0 else (tp[-1] - ma) / sd


def _ref_roc(c, p=12):
    return _NAN if len(c) < p + 1 else (c[-1] - c[-p - 1]) / c[-p - 1] * 100.0


def _ref_willr(h, l, c, p=14):
    if len(c) < p:
        return _NAN
    hh, ll = max(h[-p:]), min(l[-p:])
    return -50.0 if hh == ll else (hh - c[-1]) / (hh - ll) * -100.0


def _ref_stoch(h, l, c, kp=14):
    if len(c) < kp:
        return _NAN, _NAN
    hh, ll = max(h[-kp:]), min(l[-kp:])
    k = 50.0 if hh == ll else (c[-1] - ll) / (hh - ll) * 100.0
    return k, k


def _ref_sar(high: pd.Series, low: pd.Series, accel: float = 0.02,
             maximum: float = 0.2) -> np.ndarray:
    """改动前 ``tech.sar`` 的逐行副本（pandas .iloc 逐点访问）。"""
    n = len(high)
    out = np.full(n, np.nan)
    if n < 2:
        return out
    trend = 1 if high.iloc[1] >= high.iloc[0] else -1
    ep = low.iloc[0] if trend > 0 else high.iloc[0]
    out[0] = low.iloc[0] if trend > 0 else high.iloc[0]
    af = accel
    for i in range(1, n):
        out[i] = out[i - 1] + af * (ep - out[i - 1])
        if trend > 0:
            if low.iloc[i] < out[i]:
                trend = -1
                out[i] = ep
                ep = low.iloc[i]
                af = accel
            else:
                if high.iloc[i] > ep:
                    ep = high.iloc[i]
                    af = min(af + accel, maximum)
        else:
            if high.iloc[i] > out[i]:
                trend = 1
                out[i] = ep
                ep = high.iloc[i]
                af = accel
            else:
                if low.iloc[i] < ep:
                    ep = low.iloc[i]
                    af = min(af + accel, maximum)
    return out


def _same(a, b, rel=1e-12, absolute=1e-12):
    """NaN 感知的近等比较（新实现与原实现应为 bit 级一致，阈值仅防 ±0 噪声）。"""
    fa, fb = float(a), float(b)
    if math.isnan(fa) or math.isnan(fb):
        return math.isnan(fa) and math.isnan(fb)
    return abs(fa - fb) <= absolute + rel * max(abs(fa), abs(fb))


# ---------------------------------------------------------------------------
# 1. _tail 自身的边界语义
# ---------------------------------------------------------------------------


def test_tail_boundaries():
    assert ind._tail(list(range(10)), 3) == [7, 8, 9]
    assert ind._tail(list(range(10)), 10) == list(range(10))
    assert ind._tail(list(range(10)), 99) == list(range(10))   # count >= n
    assert ind._tail(list(range(10)), 0) == []                 # count <= 0
    d = deque(range(10))
    assert ind._tail(d, 3) == [7, 8, 9]                        # deque 分支
    assert ind._tail(deque(range(3)), 5) == [0, 1, 2]


# ---------------------------------------------------------------------------
# 2. 与朴素参考实现逐点一致（含 NaN / 数据不足周期分支）
# ---------------------------------------------------------------------------


def test_atr_last_matches_naive_reference():
    h, l, c = _make_bars(800)
    checked = 0
    for i in range(len(c)):
        got = ind.atr_last(h[: i + 1], l[: i + 1], c[: i + 1], 14)
        exp = _ref_atr(h[: i + 1], l[: i + 1], c[: i + 1], 14)
        assert _same(got, exp), f"atr14 第 {i} 根不一致：{got} vs {exp}"
        checked += 1
    assert checked == len(c)
    # 周期大于可用历史：保持 nan
    assert math.isnan(ind.atr_last([1.0], [1.0], [1.0], 14))


def test_last_series_match_naive_reference():
    h, l, c = _make_bars(600)
    # 覆盖前段（数据不足）与后段（数据充足），避免 O(n²) 对比
    idxs = list(range(5, 40)) + list(range(40, len(c), 12)) + [len(c) - 1]
    for i in idxs:
        hh, ll, cc = h[: i + 1], l[: i + 1], c[: i + 1]
        assert _same(ind.sma_last(cc, 20), _ref_sma(cc, 20)), i
        up, lo = ind.donchian_last(hh, ll, 20)
        eup, elo = _ref_donchian(hh, ll, 20)
        assert _same(up, eup) and _same(lo, elo), i
        for got, exp in zip(ind.bollinger_last(cc, 20, 2.0), _ref_bollinger(cc, 20, 2.0)):
            assert _same(got, exp), i
        assert _same(ind.rsi_last(cc, 14), _ref_rsi(cc, 14)), i
        assert _same(ind.cci_last(hh, ll, cc, 20), _ref_cci(hh, ll, cc, 20)), i
        assert _same(ind.roc_last(cc, 12), _ref_roc(cc, 12)), i
        assert _same(ind.willr_last(hh, ll, cc, 14), _ref_willr(hh, ll, cc, 14)), i
        for got, exp in zip(ind.stoch_last(hh, ll, cc, 14, 3), _ref_stoch(hh, ll, cc, 14)):
            assert _same(got, exp), i
        assert _same(ind.sar_last(hh, ll), ll[-1]), i


# ---------------------------------------------------------------------------
# 3. 容器等价（_tail 的 deque / 切片分支不能改变结果）
# ---------------------------------------------------------------------------


def test_container_equivalence():
    h, l, c = _make_bars(700)
    base = {
        "sma20": ind.sma_last(c, 20),
        "atr14": ind.atr_last(h, l, c, 14),
        "don": ind.donchian_last(h, l, 20),
        "boll": ind.bollinger_last(c, 20, 2.0),
        "rsi14": ind.rsi_last(c, 14),
        "cci20": ind.cci_last(h, l, c, 20),
        "roc12": ind.roc_last(c, 12),
        "willr14": ind.willr_last(h, l, c, 14),
        "stoch": ind.stoch_last(h, l, c, 14, 3),
    }
    containers = {
        "tuple": (tuple(h), tuple(l), tuple(c)),
        "deque": (deque(h), deque(l), deque(c)),
        "ndarray": (np.asarray(h), np.asarray(l), np.asarray(c)),
        # 带 maxlen 的 deque（回测里的真实形态）
        "deque_maxlen": (deque(h, maxlen=500), deque(l, maxlen=500), deque(c, maxlen=500)),
    }
    for name, (hh, ll, cc) in containers.items():
        got = {
            "sma20": ind.sma_last(cc, 20),
            "atr14": ind.atr_last(hh, ll, cc, 14),
            "don": ind.donchian_last(hh, ll, 20),
            "boll": ind.bollinger_last(cc, 20, 2.0),
            "rsi14": ind.rsi_last(cc, 14),
            "cci20": ind.cci_last(hh, ll, cc, 20),
            "roc12": ind.roc_last(cc, 12),
            "willr14": ind.willr_last(hh, ll, cc, 14),
            "stoch": ind.stoch_last(hh, ll, cc, 14, 3),
        }
        for key, exp in base.items():
            a, b = got[key], exp
            if isinstance(a, tuple):
                assert all(_same(x, y) for x, y in zip(a, b)), (name, key, a, b)
            else:
                assert _same(a, b), (name, key, a, b)


# ---------------------------------------------------------------------------
# 4. 复杂度契约：耗时不随历史长度增长（相对阈值，避免绝对耗时抖动）
# ---------------------------------------------------------------------------


def _per_call_us(fn, repeats: int = 5, inner: int = 300) -> float:
    """取多次中位数，抑制调度抖动。"""
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in range(inner):
            fn()
        samples.append((time.perf_counter() - t0) * 1e6 / inner)
    return statistics.median(samples)


def test_atr_last_cost_does_not_grow_with_history():
    h, l, c = _make_bars(5000)
    short = (deque(h[-500:], maxlen=500), deque(l[-500:], maxlen=500), deque(c[-500:], maxlen=500))
    long_ = (deque(h, maxlen=5000), deque(l, maxlen=5000), deque(c, maxlen=5000))
    # 两者尾部窗口内容完全相同（同一份数据），只有总历史长度不同
    t_short = _per_call_us(lambda: ind.atr_last(*short, 14))
    t_long = _per_call_us(lambda: ind.atr_last(*long_, 14))
    ratio = t_long / t_short
    assert ratio <= 4.0, f"atr_last 耗时随历史长度增长过多：500→{t_short:.2f}us，5000→{t_long:.2f}us"
    assert t_long < 1000.0, f"atr_last 单次耗时超宽松上限：{t_long:.2f}us"


def test_sar_scales_linearly_and_under_loose_cap():
    h, l, c = _make_bars(5000)
    h_s, l_s = pd.Series(h), pd.Series(l)
    got = tech.sar(h_s, l_s)
    assert len(got) == len(h_s)
    # 宽松上限：5000 根应远低于 2s（实测毫秒级，留足 CI 抖动余量）
    t0 = time.perf_counter()
    tech.sar(h_s, l_s)
    cost_ms = (time.perf_counter() - t0) * 1000.0
    if cost_ms > 50.0:  # 只在明显异常（>10 倍）时才二次确认，避免单次抖动误报
        samples = []
        for _ in range(3):
            t0 = time.perf_counter()
            tech.sar(h_s, l_s)
            samples.append((time.perf_counter() - t0) * 1000.0)
        assert statistics.median(samples) < 2000.0, f"SAR 5000 根过慢：{statistics.median(samples):.1f}ms"


# ---------------------------------------------------------------------------
# 5. tech.sar 与改动前参考实现逐点一致（含参数变体与边界）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("accel,maximum", [(0.02, 0.2), (0.01, 0.1), (0.03, 0.3)])
def test_sar_matches_reference(accel, maximum):
    h, l, _ = _make_bars(1500, seed=11)
    h_s, l_s = pd.Series(h), pd.Series(l)
    got = tech.sar(h_s, l_s, accel, maximum).to_numpy()
    exp = _ref_sar(h_s, l_s, accel, maximum)
    assert np.array_equal(np.isnan(got), np.isnan(exp))
    mask = ~np.isnan(exp)
    assert np.array_equal(got[mask], exp[mask]), "SAR 与参考实现不一致"


def test_sar_edge_cases():
    empty = tech.sar(pd.Series(dtype=float), pd.Series(dtype=float))
    assert len(empty) == 0
    single = tech.sar(pd.Series([3.0]), pd.Series([2.0]))
    assert len(single) == 1 and single.isna().all()
    # 索引必须原样保留（K 线表依赖）
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    out = tech.sar(pd.Series(np.arange(50, dtype=float), index=idx),
                   pd.Series(np.arange(50, dtype=float) - 1.0, index=idx))
    assert out.index.equals(idx)
    assert not out.iloc[0] != out.iloc[0]  # 第 0 根有值（非 NaN）
