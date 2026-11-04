"""AnalysisStore 单例提供者（2026-10-05）。

背景
----
主窗口按 UX-67 把 ``AnalysisStore`` 放到**后台线程**初始化（SQLite 建连 + 建表
约 100–500ms），以避免阻塞首帧。但页面可能在 store 就绪之前就被构造，或在其
就绪之前触发业务回调（典型：预测完成 → ``save_prediction`` 落盘），此时拿到
``None``，导致 ``AttributeError`` 或（加了判空护栏后）**预测结果被静默丢弃**。

方案
----
本模块提供**线程安全的按需创建单例**：

- :func:`get_store` —— 已有实例直接返回；否则**同步创建**（仅首次有开销）。
- :func:`set_store` —— 后台初始化完成后登记，全进程共享同一连接。

这样后台初始化退化为「预热优化」：提前完成时直接采用其结果；未完成时，
首次使用方同步兜底创建，功能不受时序影响。

线程安全
--------
``AnalysisStore`` 内部以 ``check_same_thread=False`` 打开连接，可跨线程使用；
本模块再用一把锁保证「只创建一个实例」，避免多线程重复建连。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_store = None          # AnalysisStore 实例
_store_path: Optional[str] = None


def get_store(db_path: Optional[str] = None):
    """获取 AnalysisStore 单例；不存在则同步创建。

    参数:
        db_path: 数据库路径；已存在实例时该参数被忽略（保证单例）。

    返回:
        AnalysisStore 实例；若创建失败返回 ``None``（调用方需判空）。
    """
    global _store, _store_path
    with _lock:
        if _store is not None:
            return _store
        try:
            from ..storage.analysis_store import AnalysisStore

            _store = AnalysisStore(db_path or "data/quant_analysis.db")
            _store_path = getattr(_store, "path", None)
            logger.info("AnalysisStore 按需创建完成：%s", _store_path)
        except SystemExit as e:  # noqa: BLE001
            # 安全软件/沙箱可能把底层文件操作拦截成 SystemExit（BaseException，
            # 不是 Exception 子类）。它是"创建失败"，绝不能让它终止进程或穿透出去。
            logger.error("AnalysisStore 创建被系统级拦截（SystemExit）：%s", e)
            _store = None
        except Exception as e:  # noqa: BLE001
            logger.warning("AnalysisStore 创建失败：%s", e)
            _store = None
        return _store


def set_store(store) -> None:
    """登记后台初始化完成的 AnalysisStore（后续 get_store 直接返回它）。

    已有实例时**不覆盖**，避免把已分发给页面的连接替换掉造成双连接。
    """
    global _store, _store_path
    if store is None:
        return
    with _lock:
        if _store is None:
            _store = store
            _store_path = getattr(store, "path", None)
        elif _store is not store:
            # 后台实例与按需实例不是同一个 —— 保留先用的那个，关闭后来者
            logger.debug("AnalysisStore 已存在，忽略后台实例（避免双连接）")
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass


def current_path() -> Optional[str]:
    """返回当前单例使用的数据库路径（便于诊断/日志）。"""
    with _lock:
        return _store_path


def reset_for_test() -> None:
    """测试用：清空单例（生产代码不应调用）。"""
    global _store, _store_path
    with _lock:
        _store = None
        _store_path = None


__all__ = ["get_store", "set_store", "current_path", "reset_for_test"]
