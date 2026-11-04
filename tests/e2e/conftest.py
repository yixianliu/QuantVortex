"""tests/e2e 目录专用 pytest 配置。

历史背景：
    ``tests/e2e`` 目录里既有 pytest 风格（含 ``def test_*``）的正式测试，
    也有大量以 ``test_`` 前缀命名的**独立脚本**——它们在 module 顶层
    调用 ``_exit(0)`` / ``sys.exit(0)``，一旦被 pytest import 就崩。

策略：
    ``pytest_ignore_collect`` 钩子根据"文件里是否存在 ``def test_``"
    做轻量判定——没有 pytest 测试函数的一律跳过。这样既不会误伤真的
    有 test 的 e2e 脚本，也能一次性把所有独立脚本排除。

    判定规则：
        - 后缀必须是 ``.py``
        - 文件名以 ``test_`` 开头（与 pytest.ini 的 ``python_files`` 一致）
        - 全文不含 ``def test_`` 关键字 → 跳过

    不做更严格的 AST 分析（避免读文件时的编码/大文件开销）。
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Qt 应用生命周期（阶段 3 修复 0xC0000409 原生崩溃）
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def qapp():
    """整个 e2e 会话共享唯一 QApplication。

    历史问题：多个用例在函数内部执行
    ``app = QApplication.instance() or QApplication([])`` 后只保留**局部引用**；
    函数返回时 Python GC 释放唯一的包装对象，Qt 的 C++ 单例随之被销毁。
    后续用例若再构造 QWidget，Qt 会在“没有 QApplication”的状态下直接
    ``qFatal``，进程以 0xC0000409（fail-fast）退出——这正是 e2e 无法一次
    跑完的根因。

    该 session 级 fixture 持有引用，保证 QApplication 的 C++ 实例活到整个
    会话结束；用例内部再调用 ``QApplication.instance()`` 只会拿到同一实例。
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # 不在 fixture 内 quit()/析构：Qt 顶层对象由解释器退出时统一回收，
    # 主动 quit 可能唤醒残留事件循环，反而增加退出期的不确定性。


def pytest_ignore_collect(collection_path: Path, config) -> bool | None:
    """跳过 e2e 下没有 ``def test_`` 的 test_*.py 独立脚本。"""
    if collection_path.suffix != ".py":
        return None
    if not collection_path.name.startswith("test_"):
        return None
    try:
        text = collection_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if "def test_" not in text:
        return True
    return None
