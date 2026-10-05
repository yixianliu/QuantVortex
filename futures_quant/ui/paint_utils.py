"""画刷保护工具：paint_guard 装饰器。

本模块提供 paint_guard 装饰器，用于捕获 paintEvent 中的异常，
避免未处理异常触发 qFatal 直接杀进程（表现：exit 127 无 traceback）。

本模块不依赖 widgets 或 states，可安全被任何 UI 模块导入，解决循环引用问题。
"""
from __future__ import annotations

import functools
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def paint_guard(fn: Callable) -> Callable:
    """装饰 ``paintEvent``：捕获异常，避免未处理异常触发 qFatal 直接杀进程。

    PyQt 在虚函数（paintEvent 等）里抛出未捕获异常会走 qFatal，**没有 traceback**、
    faulthandler 也抓不到，表现为进程 exit 127 静默闪退。这里统一兜底并只告警一次，
    保证「画错」最多退化为「不画」，而不是「程序消失」。

    参数:
        fn: 被装饰的 paintEvent 方法

    返回:
        包装后的方法，异常会被捕获并记录日志
    """
    warned: set[str] = set()

    @functools.wraps(fn)
    def _inner(self, event):  # noqa: ANN001 - Qt 回调签名固定
        try:
            return fn(self, event)
        except Exception as exc:  # noqa: BLE001 - 必须兜住全部异常
            key = f"{type(self).__name__}.{fn.__name__}"
            if key not in warned:
                warned.add(key)
                logger.warning("paintEvent 异常已忽略（%s）：%s", key, exc)
            return None
    return _inner
