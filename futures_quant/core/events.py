"""事件总线。

M3.5：替代 linkage_bus，实现 publish/subscribe 机制。
"""
from __future__ import annotations
from typing import Callable, Dict, List

class EventBus:
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event: str, handler: Callable):
        self._listeners.setdefault(event, []).append(handler)

    def publish(self, event: str, payload: dict):
        for handler in self._listeners.get(event, []):
            handler(payload)

bus = EventBus()
