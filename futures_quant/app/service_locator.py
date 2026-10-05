"""服务定位器（简单依赖注入容器）。

提供全局单实例的服务注册与获取，用于解耦 UI 与业务层。
服务应在程序启动时注册（如在 main_window 初始化时）。
"""
from __future__ import annotations

import threading
from typing import Dict, TypeVar, Optional

T = TypeVar('T')


class ServiceLocator:
    """线程安全的服务注册表。"""
    _instance: Optional['ServiceLocator'] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._services: Dict[str, object] = {}

    @classmethod
    def instance(cls) -> 'ServiceLocator':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, name: str, service: object) -> None:
        """注册服务实例。"""
        with self._lock:
            self._services[name] = service

    def get(self, name: str) -> object:
        """获取服务实例。"""
        with self._lock:
            service = self._services.get(name)
            if service is None:
                raise KeyError(f"Service '{name}' not registered")
            return service

    def has(self, name: str) -> bool:
        """检查服务是否已注册。"""
        with self._lock:
            return name in self._services

    def clear(self) -> None:
        """清除所有服务（主要用于测试）。"""
        with self._lock:
            self._services.clear()


# 全局快捷方式
def provide(name: str, service: object) -> None:
    """注册服务。"""
    ServiceLocator.instance().register(name, service)


def request(name: str) -> object:
    """获取服务。"""
    return ServiceLocator.instance().get(name)


__all__ = ["ServiceLocator", "provide", "request"]