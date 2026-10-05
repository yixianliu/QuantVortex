"""M2-11 修复超参搜索器 - E2E smoke 验收。

DoD:
1) `import futures_quant.ai_tuning_optional.parameter_optimizer` 在无 sklearn
   环境下不抛 ModuleNotFoundError（M1-07 lazy import 模式）。
2) 调用 grid_search / random_search / _get_score_func 时抛带 pip 命令的
   ImportError，提示明确而非静默崩。
3) M1-07 迁移后 `from ..ai.lstm import LSTM` 相对导入路径可解析（原 M2-11
   阶段 `..lstm` 是在 ai/tuning/ 下的正确写法，迁出 ai/ 后需重新校正）。
4) grid_search / random_search 使用 TimeSeriesSplit 而非 KFold（时序数据
   不可随机打散，避免未来函数）。
5) `_require_sklearn()` 返回的 5 元组被 `ParameterGrid` 变量绑定，
   `n_iterations` 字段可以正确计算（M2-11 补丁中的漏项）。

运行方式:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m2_11.py
"""
from __future__ import annotations

import importlib
import importlib.abc
import inspect
import logging
import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QT_QPA_PLATFORM_DEFAULT = os.environ.get("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_QPA_PLATFORM"] = QT_QPA_PLATFORM_DEFAULT


class _BlockFinder(importlib.abc.MetaPathFinder):
    """把 sklearn 相关模块从 sys.path 完全隐藏。"""

    def __init__(self, blocked: set[str]):
        self._blocked = blocked

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self._blocked:
            return None
        for b in self._blocked:
            if fullname.startswith(b + "."):
                raise ModuleNotFoundError(f"No module named {fullname!r} (blocked for smoke)")
        return None


def _install_blocker(blocked: set[str]) -> list[importlib.abc.MetaPathFinder]:
    removed = []
    keys_to_pop = [k for k in list(sys.modules) if k == "sklearn" or k.startswith("sklearn.")]
    for k in keys_to_pop:
        sys.modules.pop(k, None)
    finder = _BlockFinder(blocked)
    sys.meta_path.insert(0, finder)
    removed.append(finder)
    return removed


def _uninstall(finders: list[importlib.abc.MetaPathFinder]) -> None:
    for f in finders:
        try:
            sys.meta_path.remove(f)
        except ValueError:
            pass


def _import_fresh(mod_name: str):
    keys_to_pop = [k for k in list(sys.modules) if k == mod_name or k.startswith(mod_name + ".")]
    for k in keys_to_pop:
        sys.modules.pop(k, None)
    return importlib.import_module(mod_name)


# ============================================================
# 测试用例
# ============================================================

MODULE = "futures_quant.ai_tuning_optional.parameter_optimizer"
INSTALL_HINT_KEYWORDS = ("scikit-learn", "pip install")


def test_1_import_ok_without_sklearn() -> None:
    """无 sklearn 环境下顶层 import 不抛 ModuleNotFoundError。"""
    removed = _install_blocker({"sklearn"})
    try:
        mod = _import_fresh(MODULE)
        # 顶层常量/工具应可见
        assert hasattr(mod, "_SKLEARN_INSTALL_HINT")
        assert hasattr(mod, "_require_sklearn")
        assert hasattr(mod, "_time_series_cv")
        assert hasattr(mod, "ModelParameterOptimizer")
        assert hasattr(mod, "optimize_model_parameters")
        assert hasattr(mod, "COMMON_PARAM_GRIDS")
    finally:
        _uninstall(removed)
    print("[1/6] PASS module imports cleanly without sklearn")


def test_2_grid_search_raises_import_error_without_sklearn() -> None:
    """无 sklearn 环境下调用 grid_search 抛带 pip 命令的 ImportError。"""
    removed = _install_blocker({"sklearn"})
    try:
        mod = _import_fresh(MODULE)
        opt = mod.ModelParameterOptimizer()
        try:
            opt.grid_search(
                estimator=None, param_grid={"a": [1, 2]},
                X=None, y=None,
            )
        except ImportError as e:
            msg = str(e)
            assert "scikit-learn" in msg and "pip install" in msg, (
                f"ImportError 未包含 pip 安装提示: {msg!r}"
            )
        else:
            raise AssertionError("grid_search 未抛 ImportError")
    finally:
        _uninstall(removed)
    print("[2/6] PASS grid_search raises ImportError with pip hint")


def test_3_random_search_raises_import_error_without_sklearn() -> None:
    """random_search 同样在无 sklearn 环境下抛带 pip 命令的 ImportError。"""
    removed = _install_blocker({"sklearn"})
    try:
        mod = _import_fresh(MODULE)
        opt = mod.ModelParameterOptimizer()
        try:
            opt.random_search(
                estimator=None, param_distributions={"a": [1, 2]},
                X=None, y=None,
            )
        except ImportError as e:
            msg = str(e)
            assert "scikit-learn" in msg and "pip install" in msg
        else:
            raise AssertionError("random_search 未抛 ImportError")
    finally:
        _uninstall(removed)
    print("[3/6] PASS random_search raises ImportError with pip hint")


def test_4_get_score_func_raises_without_sklearn() -> None:
    """`_get_score_func` 无 sklearn 时也应抛带 pip 提示的 ImportError。"""
    removed = _install_blocker({"sklearn"})
    try:
        mod = _import_fresh(MODULE)
        opt = mod.ModelParameterOptimizer(scoring_metric="neg_mean_squared_error")
        try:
            opt._get_score_func()
        except ImportError as e:
            msg = str(e)
            assert "scikit-learn" in msg and "pip install" in msg
        else:
            raise AssertionError("_get_score_func 未抛 ImportError")
    finally:
        _uninstall(removed)
    print("[4/6] PASS _get_score_func raises ImportError with pip hint")


def test_5_lstm_import_path_resolvable() -> None:
    """M1-07 迁移后 `from ..ai.lstm import LSTM` 相对路径仍可解析。

    源码扫描断言：不再残留 `from ..lstm` 写法（那是 ai/tuning/ 时期的
    正确写法，M1-07 迁到 ai_tuning_optional/ 后会解析成
    futures_quant.lstm，必 ModuleNotFoundError）。
    """
    src = (ROOT / "futures_quant" / "ai_tuning_optional" / "parameter_optimizer.py").read_text(
        encoding="utf-8"
    )
    # 应有 ..ai.lstm
    assert "from ..ai.lstm import LSTM" in src, (
        "LSTM 相对导入未校正到 ..ai.lstm；M1-07 迁移后 ..lstm 会解析成 futures_quant.lstm"
    )
    # 不应有裸 ..lstm（避免误导）
    assert "from ..lstm import LSTM" not in src, (
        "残留 `from ..lstm import LSTM`；M1-07 迁出 ai/ 后必 ModuleNotFoundError"
    )
    print("[5/6] PASS LSTM import path fixed to ..ai.lstm")


def test_6_grid_search_binds_parametergrid() -> None:
    """grid_search 中 ParameterGrid 变量已正确绑定（M2-11 补丁漏项修复）。"""
    src = (ROOT / "futures_quant" / "ai_tuning_optional" / "parameter_optimizer.py").read_text(
        encoding="utf-8"
    )
    # 网格搜索解构应包含 ParameterGrid（不是下划线丢弃）
    match = re.search(
        r"ParameterGrid,\s*_,\s*GridSearchCV,\s*make_scorer,\s*_tss\s*=\s*_require_sklearn\(\)",
        src,
    )
    assert match, (
        "grid_search 未把 _require_sklearn() 返回的 ParameterGrid 绑定到局部变量；"
        "n_iterations 计算会 NameError"
    )
    print("[6/6] PASS grid_search binds ParameterGrid local variable")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)

    tests = [
        test_1_import_ok_without_sklearn,
        test_2_grid_search_raises_import_error_without_sklearn,
        test_3_random_search_raises_import_error_without_sklearn,
        test_4_get_score_func_raises_without_sklearn,
        test_5_lstm_import_path_resolvable,
        test_6_grid_search_binds_parametergrid,
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
    print(f"\n=== M2-11 smoke: {passed}/{total} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
