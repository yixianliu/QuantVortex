"""技术指标计算结果缓存（LRU）。

设计目标：
    1. 同一(symbol, period, indicator, params)组合在一定时间窗口内复用结果；
    2. 命中缓存时避免重复 rolling/ewm 运算，降低 UI 刷新与信号重算延迟；
    3. 线程安全：数据探测、K 线绘图、信号扫描并发访问不冲突。

实现约束：
    - 轻量纯 Python，不引入额外依赖；
    - pandas Series/DataFrame 不可哈希，转为 tuple-of-series 序列化开销大；
      因此采用「带大小限制的字典 + 最近访问链表」自实现 LRU。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

import pandas as pd

# 默认容量：避免长期运行内存膨胀；覆盖 39 品种 x 6 周期 x 30 指标绰绰有余
DEFAULT_CAPACITY = 4096


class IndicatorCache:
    """线程安全的 LRU 指标缓存。"""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._capacity = max(64, capacity)
        self._store: OrderedDict[str, tuple[pd.Series | pd.DataFrame, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    def _make_key(self, symbol: str, period: str, indicator: str,
                  params: tuple | None = None) -> str:
        """构造可读缓存键。params 仅取可 JSON 安全基础类型。"""
        params = params or ()
        return "|".join([
            str(symbol),
            str(period),
            str(indicator),
            "|".join(str(p) for p in params),
        ])

    # ------------------------------------------------------------------
    def get(self, symbol: str, period: str, indicator: str,
            params: tuple | None = None) -> pd.Series | pd.DataFrame | None:
        """取出缓存；命中则把节点移到尾部（最近访问）。"""
        key = self._make_key(symbol, period, indicator, params)
        with self._lock:
            if key not in self._store:
                self._misses += 1
                return None
            self._hits += 1
            value, _ = self._store.pop(key)
            self._store[key] = (value, self._now())
            return value

    # ------------------------------------------------------------------
    def put(self, symbol: str, period: str, indicator: str,
            value: pd.Series | pd.DataFrame,
            params: tuple | None = None) -> None:
        """写入缓存；容量满时淘汰头部（最久未使用）。"""
        key = self._make_key(symbol, period, indicator, params)
        with self._lock:
            if key in self._store:
                self._store.pop(key)
            self._store[key] = (value, self._now())
            while len(self._store) > self._capacity:
                self._store.popitem(last=False)

    # ------------------------------------------------------------------
    def invalidate(self, symbol: str, period: str | None = None) -> None:
        """清除指定品种（或品种+周期）缓存；新 K 线到达时调用。"""
        with self._lock:
            if period is None:
                keys = [k for k in self._store if k.startswith(f"{symbol}|")]
            else:
                keys = [k for k in self._store if k.startswith(f"{symbol}|{period}|")]
            for k in keys:
                del self._store[k]

    # ------------------------------------------------------------------
    def clear(self) -> None:
        """清空全部缓存。"""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """返回命中率统计。"""
        with self._lock:
            total = self._hits + self._misses
            return {
                "capacity": self._capacity,
                "size": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
            }

    # ------------------------------------------------------------------
    @staticmethod
    def _now() -> float:
        import time
        return time.monotonic()


# 全局单实例：多页面共享，避免重复计算
_instance = IndicatorCache()


def get_instance() -> IndicatorCache:
    return _instance


# ------------------------------------------------------------------
# 便捷装饰器：将指标函数包装为缓存版
# ------------------------------------------------------------------
def cached_indicator(func):
    """装饰器：自动按 (symbol, period, *args, **kwargs) 做 LRU 缓存。

    被装饰函数需遵循签名：func(df: pd.DataFrame, symbol: str, period: str, *args) -> Series/DataFrame
    """
    import functools

    @functools.wraps(func)
    def wrapper(df: pd.DataFrame, *args, **kwargs):
        # 约定：前两个位置参数为 symbol、period
        symbol = kwargs.get("symbol") or (args[0] if len(args) > 0 else "?")
        period = kwargs.get("period") or (args[1] if len(args) > 1 else "?")
        params = args[2:] if len(args) > 2 else ()

        cache = get_instance()
        cached = cache.get(symbol, period, func.__name__, params)
        if cached is not None:
            return cached

        result = func(df, *args, **kwargs)
        cache.put(symbol, period, func.__name__, result, params)
        return result

    return wrapper


# ------------------------------------------------------------------
# 预量化禁用：避免在未导入 heavy 模块时意外依赖
__all__ = [
    "IndicatorCache",
    "get_instance",
    "cached_indicator",
]