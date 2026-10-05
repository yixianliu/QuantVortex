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
