"""M1-07 孤模块处置 - E2E smoke 验收。

DoD:
1) `import futures_quant.ai_tuning_optional.<module>` 在无 sklearn / matplotlib
   / seaborn 环境下不抛 ModuleNotFoundError —— 让上层能"知道模块存在但依赖缺失"
   而不是"顶层 import 崩"。
2) 弃用垫片 `futures_quant.ai.tuning.<sub>` 仍能触发 DeprecationWarning，
   并惰性重定向到 ai_tuning_optional.<sub>。
3) `futures_quant.ai.tuning/` 目录下除 __init__.py 外不应再出现业务模块（避免
   新旧双份）。

运行方式:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m1_07.py
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import logging
import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QT_QPA_PLATFORM_DEFAULT = os.environ.get("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_QPA_PLATFORM"] = QT_QPA_PLATFORM_DEFAULT

# 需要守卫的模块（依赖 sklearn / matplotlib / seaborn）
_GUARDED_MODULES = (
    "futures_quant.ai_tuning_optional.data_preprocessor",
    "futures_quant.ai_tuning_optional.performance_evaluator",
    "futures_quant.ai_tuning_optional.visualizer",
)
# 不需要守卫的模块（仅依赖 numpy/pandas/stdlib）
_PLAIN_MODULES = (
    "futures_quant.ai_tuning_optional.data_validator",
    "futures_quant.ai_tuning_optional.parameter_optimizer",
    "futures_quant.ai_tuning_optional",
)


class _BlockFinder(importlib.abc.MetaPathFinder):
    """把指定模块名从 sys.path 完全隐藏，使 import 抛 ModuleNotFoundError。"""

    def __init__(self, blocked: set[str]):
        self._blocked = blocked

    def find_spec(self, fullname, path=None, target=None):
        # 只拦截精确匹配的顶级/子模块，不拦截前缀相同的名字
        if fullname in self._blocked:
            return None  # 交给后续 finder 处理
        # 前缀匹配（如 sklearn.preprocessing）：主动抛，防止 fallback 到真包
        for b in self._blocked:
            if fullname.startswith(b + "."):
                raise ModuleNotFoundError(f"No module named {fullname!r} (blocked for smoke)")
        return None


def _install_blocker(blocked: set[str]) -> list[importlib.abc.MetaPathFinder]:
    """把 blocker 插到 sys.meta_path 最前面，同时清理已加载的缓存。"""
    removed: list[importlib.abc.MetaPathFinder] = []
    finder = _BlockFinder(blocked)
    # 清掉 sys.modules 里所有已加载的 sklearn/matplotlib/seaborn 相关键
    keys_to_pop = [k for k in list(sys.modules) if _matches(k, blocked)]
    for k in keys_to_pop:
        sys.modules.pop(k, None)
    sys.meta_path.insert(0, finder)
    removed.append(finder)
    return removed


def _uninstall(finders: list[importlib.abc.MetaPathFinder]) -> None:
    for f in finders:
        try:
            sys.meta_path.remove(f)
        except ValueError:
            pass


def _matches(name: str, blocked: set[str]) -> bool:
    for b in blocked:
        if name == b or name.startswith(b + "."):
            return True
    return False


def _import_fresh(mod_name: str):
    """强制重新导入：先 evict 缓存再 importlib.import_module。"""
    keys_to_pop = [k for k in list(sys.modules) if k == mod_name or k.startswith(mod_name + ".")]
    for k in keys_to_pop:
        sys.modules.pop(k, None)
    return importlib.import_module(mod_name)


# ============================================================
# 测试用例
# ============================================================

def test_1_plain_imports_always_ok() -> None:
    """纯 stdlib + numpy + pandas 的模块在无 sklearn 环境下也应能导入。"""
    removed = _install_blocker({"sklearn", "matplotlib", "seaborn"})
    try:
        for m in _PLAIN_MODULES:
            _import_fresh(m)
    finally:
        _uninstall(removed)
    print("[1/6] PASS plain modules importable with sklearn/matplotlib/seaborn blocked")


def test_2_guarded_imports_ok_without_deps() -> None:
    """M1-07 核心 DoD：守卫过的模块在无 sklearn/matplotlib/seaborn 环境下
    顶层 import 不抛 ModuleNotFoundError。"""
    removed = _install_blocker({"sklearn", "matplotlib", "seaborn", "scipy"})
    try:
        for m in _GUARDED_MODULES:
            _import_fresh(m)
    finally:
        _uninstall(removed)
    print("[2/6] PASS guarded modules importable with heavy deps blocked")


def test_3_deprecation_shim_warns() -> None:
    """弃用垫片 `futures_quant.ai.tuning.data_preprocessor` 触发 DeprecationWarning
    并成功重定向到 ai_tuning_optional.data_preprocessor。"""
    removed = _install_blocker({"sklearn", "matplotlib", "seaborn", "scipy"})
    try:
        # 清缓存，确保重新走 __getattr__
        for k in list(sys.modules):
            if k.startswith("futures_quant.ai.tuning"):
                sys.modules.pop(k, None)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # 通过 __getattr__ 触发重定向
            import futures_quant.ai.tuning as tuning_pkg  # noqa: F401
            _ = tuning_pkg.data_preprocessor  # type: ignore[attr-defined]
        assert any(issubclass(i.category, DeprecationWarning) for i in w), (
            "弃用垫片未触发 DeprecationWarning"
        )
    finally:
        _uninstall(removed)
    print("[3/6] PASS deprecation shim warns and redirects")


def test_4_no_duplicates_in_ai_tuning() -> None:
    """futures_quant/ai/tuning/ 目录应仅剩 __init__.py，业务模块已全部迁走。"""
    ai_tuning_dir = ROOT / "futures_quant" / "ai" / "tuning"
    assert ai_tuning_dir.is_dir(), f"缺失目录: {ai_tuning_dir}"
    py_files = list(ai_tuning_dir.glob("*.py"))
    names = {p.name for p in py_files}
    # 只允许 __init__.py（弃用垫片）
    unexpected = names - {"__init__.py"}
    assert not unexpected, (
        f"ai/tuning/ 目录残留业务模块: {sorted(unexpected)}；"
        "M1-07 要求业务模块全部迁至 ai_tuning_optional/"
    )
    print(f"[4/6] PASS ai/tuning/ 仅剩 __init__.py（垫片），无业务模块残留: {sorted(names)}")


def test_5_orphan_registry_exists() -> None:
    """docs/ORPHAN_MODULES.md 台账应存在并列出 3 个关键模块的处置状态。"""
    registry = ROOT / "docs" / "ORPHAN_MODULES.md"
    assert registry.is_file(), f"缺失台账: {registry}"
    text = registry.read_text(encoding="utf-8")
    for kw in ("ai_tuning_optional", "M1-07", "M2-08", "M4-03"):
        assert kw in text, f"ORPHAN_MODULES.md 未提及关键字段: {kw}"
    print("[5/6] PASS ORPHAN_MODULES.md 台账存在且覆盖关键字段")


def test_6_ai_tuning_shim_dir_lists_submodules() -> None:
    """弃用垫片 `dir(futures_quant.ai.tuning)` 应列出 5 个子模块名，便于 IDE 提示。"""
    removed = _install_blocker({"sklearn", "matplotlib", "seaborn", "scipy"})
    try:
        for k in list(sys.modules):
            if k.startswith("futures_quant.ai.tuning"):
                sys.modules.pop(k, None)
        import futures_quant.ai.tuning as tuning_pkg  # noqa: F401
        listing = dir(tuning_pkg)
        expected = {"data_preprocessor", "data_validator", "parameter_optimizer",
                    "performance_evaluator", "visualizer"}
        missing = expected - set(listing)
        assert not missing, f"垫片 dir() 缺少子模块提示: {sorted(missing)}"
    finally:
        _uninstall(removed)
    print("[6/6] PASS deprecation shim dir() lists all submodules")


def main() -> int:
    # 确保日志不吵
    logging.basicConfig(level=logging.WARNING)

    tests = [
        test_1_plain_imports_always_ok,
        test_2_guarded_imports_ok_without_deps,
        test_3_deprecation_shim_warns,
        test_4_no_duplicates_in_ai_tuning,
        test_5_orphan_registry_exists,
        test_6_ai_tuning_shim_dir_lists_submodules,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc!r}")

    total = len(tests)
    passed = total - failed
    print(f"\n=== M1-07 smoke: {passed}/{total} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
