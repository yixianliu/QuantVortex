"""极简事件总线。

用于解耦策略、风控、经纪商、UI 之间的消息传递。
事件类型见 EventType；事件体为任意对象（Bar / Order / Trade / dict）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List


class EventType(str, Enum):
    TICK = "TICK"
    BAR = "BAR"
    ORDER = "ORDER"
    TRADE = "TRADE"
    LOG = "LOG"
    RISK = "RISK"
    ACCOUNT = "ACCOUNT"


@dataclass
class Event:
    type: EventType
    data: object


class EventBus:
    """发布 / 订阅事件总线。"""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._subscribers.get(event.type.value, []):
            try:
                handler(event)
            except Exception as exc:  # 单订阅者异常不应中断整个引擎
                print(f"[EventBus] handler error for {event.type}: {exc}")

    def clear(self) -> None:
        self._subscribers.clear()
