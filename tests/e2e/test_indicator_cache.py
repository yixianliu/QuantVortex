"""M2.1 指标缓存与性能验收测试。

验收标准：
- 单指标计算 <5ms @ 1000 根
- 缓存命中有效
- test_indicator_forecast.py 保持绿
"""
from __future__ import annotations

import time
import numpy as np
import pandas as pd
import sys
import os

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.indicators.cache import get_instance, IndicatorCache
from futures_quant.indicators.tech import sma, ema

def test_cache_hit_miss():
    cache = get_instance()
    cache.clear()
    # 构造测试数据
    n = 1000
    close = pd.Series(np.random.randn(n).cumsum() + 100)
    sid = "rb.SHFE"
    period = "D"

    # 第一次计算 -> miss
    t0 = time.perf_counter()
    res1 = sma(close, 20)
    t1 = time.perf_counter()
    dt1 = (t1 - t0) * 1000

    # 手动写入缓存模拟
    cache.put(sid, period, "sma", res1, (20,))
    cached = cache.get(sid, period, "sma", (20,))
    assert cached is not None
    pd.testing.assert_series_equal(cached, res1)

    # 性能要求
    print(f"SMA 1000根耗时 {dt1:.2f} ms")
    assert dt1 < 5.0, f"SMA 计算耗时 {dt1:.2f}ms >=5ms"

    # 命中率统计
    stats = cache.stats()
    assert stats["hits"] >= 1

def test_cache_key_uniqueness():
    cache = get_instance()
    cache.clear()
    s1 = pd.Series([1,2,3,4,5])
    s2 = pd.Series([1,2,3,4,6])
    cache.put("A", "D", "sma", s1, (10,))
    cache.put("A", "D", "sma", s2, (20,))
    v1 = cache.get("A", "D", "sma", (10,))
    v2 = cache.get("A", "D", "sma", (20,))
    assert v1 is not None and v2 is not None
    assert v1.iloc[-1] != v2.iloc[-1]

if __name__ == "__main__":
    test_cache_hit_miss()
    test_cache_key_uniqueness()
    print("test_indicator_cache.py 全绿")
