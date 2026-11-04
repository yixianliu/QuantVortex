"""UI 异步执行 helpers（M4-06⑥：历史 ``TaskRunner`` 已删除，改为兼容门面）。

背景：
    旧版本曾在此文件提供基于 ``QThreadPool`` 的 ``TaskRunner``。经全仓检索，除本文件
    的 ``__all__`` 与文档字符串外**无任何调用方**，属死代码。M4-06 统一异步框架后，
    全 UI 的后台任务均经由 ``futures_quant.ui.pages.Worker``（``QThread`` 子类，支持
    取消 / 进度 / 超时）与 ``BasePage._run_worker`` 执行。

本模块现在仅作为**兼容门面**，转发核心类型，供历史 import 路径继续可用，避免一次性
删除引发的 ``ImportError``（外部脚本/第三方扩展仍可能引用旧路径）。

用法（推荐直接使用 pages）::

    from futures_quant.ui.pages import Worker, InterruptionError

兼容用法::

    from futures_quant.ui.async_worker import Worker, InterruptionError
"""
from __future__ import annotations

from .pages import InterruptionError, Worker

__all__ = ["Worker", "InterruptionError"]
