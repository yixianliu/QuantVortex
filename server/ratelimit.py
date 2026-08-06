"""按设备限流（令牌桶）。

代理服务把你的上游额度暴露给了公网，限流是防止额度被刷穿的第一道闸。
即便有人提取了客户端令牌，也只能以单设备速率消耗，且你可随时封禁。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last: float


class TokenBucket:
    """线程安全的令牌桶限流器。

    Args:
        rate_per_minute: 稳态速率（每分钟允许的请求数）。
        burst:           突发容量（瞬时可积攒的最大令牌数）。
        max_keys:        最多跟踪的键数量，超出时清理最久未活跃者，
                         防止被伪造设备号打爆内存。
    """

    def __init__(self, rate_per_minute: int, burst: int,
                 max_keys: int = 50_000) -> None:
        self.rate = max(rate_per_minute, 1) / 60.0   # 每秒补充的令牌
        self.burst = float(max(burst, 1))
        self.max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """尝试消耗一个令牌。

        Returns:
            (是否放行, 建议重试等待秒数)。放行时等待秒数为 0。
        """
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                if len(self._buckets) >= self.max_keys:
                    self._evict_locked(now)
                b = _Bucket(tokens=self.burst, last=now)
                self._buckets[key] = b

            # 按经过时间补充令牌，上限为 burst
            elapsed = now - b.last
            b.last = now
            b.tokens = min(self.burst, b.tokens + elapsed * self.rate)

            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0.0

            need = (1.0 - b.tokens) / self.rate
            return False, round(need, 2)

    def _evict_locked(self, now: float) -> None:
        """清理最久未活跃的 10% 键（调用方必须已持锁）。"""
        if not self._buckets:
            return
        victims = sorted(self._buckets.items(), key=lambda kv: kv[1].last)
        for k, _ in victims[: max(1, len(victims) // 10)]:
            self._buckets.pop(k, None)

    def stats(self) -> dict:
        with self._lock:
            return {"tracked_keys": len(self._buckets),
                    "rate_per_minute": round(self.rate * 60, 2),
                    "burst": self.burst}
