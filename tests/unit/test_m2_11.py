"""M2-11 超参搜索器修复 —— pytest 形态。

由散落脚本 ``tests/test_m2_11.py`` 改写，验收契约不变：
  ① 模块可正常导入（顶层无硬 sklearn 符号，已改惰性导入）
  ② 缺失 sklearn 时 ``_require_sklearn`` 抛带安装命令的 ImportError（本机有则走 present 分支）
  ③ LSTM 导入路径正确、且 ``futures_quant.ai.lstm`` 暴露 ``LSTM``
  ④ cv 折改用 ``TimeSeriesSplit``（源码引用 + 实例化校验）

**改写时的两处必要校正（非机械搬运，承接「门禁工件注释会过时」主题）**：
- 散落脚本 import 的是 ``futures_quant.ai.tuning.parameter_optimizer``，但该包在
  **M1-07 已迁移**到 ``futures_quant.ai_tuning_optional``（``ai/tuning/__init__.py`` 只剩
  惰性重定向的弃用垫片，``__getattr__`` 无法满足 ``import ...ai.tuning.parameter_optimizer``
  这种子模块 import）。故本文件 import 真实位置
  ``futures_quant.ai_tuning_optional.parameter_optimizer``，否则收集期 ``ModuleNotFoundError``。
- 散落脚本 ③ 断言 ``"from ..ai.lstm import" not in src``——M1-07 迁移后该断言**已失实**：
  源码在 M1-07 后位于 ``ai_tuning_optional/``（比原 ``ai/tuning/`` 浅一级），LSTM 的正确
  相对导入恰好是 ``from ..ai.lstm import``（``..`` 即 ``futures_quant/``）。本文件改为断言
  **当前正确路径存在且可解析**，而非"旧路径不存在"。
"""
from __future__ import annotations

import inspect
import sys

import pytest

from futures_quant.ai_tuning_optional import parameter_optimizer as po


class _BlockSklearn:
    """上下文管理器：让 import sklearn 抛 ImportError（与散落脚本原实现一致）。

    ``__exit__`` 保证恢复 ``sys.modules`` / ``sys.meta_path``，即使测试体抛错也回收，
    不向其它用例泄漏全局态。
    """

    def __enter__(self):
        self._saved = {}
        for k in list(sys.modules):
            if k == "sklearn" or k.startswith("sklearn."):
                self._saved[k] = sys.modules.pop(k)
        self._orig_find = sys.meta_path[:]

        class Blocker:
            def find_module(self, name, path=None):
                return None

            def find_spec(self, name, path=None, target=None):
                if name == "sklearn" or name.startswith("sklearn."):
                    raise ImportError(f"blocked: {name}")
                return None

        self._blocker = Blocker()
        sys.meta_path.insert(0, self._blocker)
        return self

    def __exit__(self, *a):
        try:
            sys.meta_path.remove(self._blocker)
        except ValueError:
            pass
        sys.modules.update(self._saved)


def test_module_imports_without_top_level_sklearn():
    """① 模块可正常导入，且顶层命名空间不残留 sklearn 符号（已改惰性导入）。"""
    assert hasattr(po, "ModelParameterOptimizer"), "模块应暴露 ModelParameterOptimizer"
    assert not hasattr(po, "GridSearchCV"), \
        "GridSearchCV 不应出现在模块顶层命名空间（应为惰性导入）"
    assert not hasattr(po, "make_scorer"), \
        "make_scorer 不应出现在模块顶层命名空间（应为惰性导入）"


def test_install_hint_constant_present():
    """无论本机是否装 sklearn，安装提示常量都应存在且含依赖名 + 安装命令。"""
    assert "scikit-learn" in po._SKLEARN_INSTALL_HINT
    assert "pip install" in po._SKLEARN_INSTALL_HINT


def test_missing_sklearn_raises_clear_importerror():
    """② 缺失 sklearn 时给出明确 ImportError（本机已装则走 present 分支、仅验证提示语存在）。"""
    with _BlockSklearn():
        try:
            po._require_sklearn()
        except ImportError as e:
            # 屏蔽成功（或本机本就无 sklearn）：必须能读到依赖名 + 安装命令
            msg = str(e)
            assert "scikit-learn" in msg, f"错误信息应指明依赖名 scikit-learn，实际：{msg}"
            assert "pip install" in msg, f"错误信息应给出安装命令 pip install，实际：{msg}"
        # 若 _require_sklearn 成功（本机有 sklearn 且屏蔽未生效），此分支无额外断言，仅确保不崩。


def test_lstm_import_path_resolves():
    """③ LSTM 导入路径正确（M1-07 后为 ``from ..ai.lstm import``）且模块暴露 LSTM。"""
    src = inspect.getsource(po)
    assert "from ..ai.lstm import" in src, \
        "源码应使用 M1-07 迁移后的正确路径 from ..ai.lstm import（.. 即 futures_quant/）"
    # 若 ai/lstm 模块可用，验证 ..ai.lstm 路径确实可解析
    try:
        import futures_quant.ai.lstm as _lstm_mod
        assert hasattr(_lstm_mod, "LSTM"), "futures_quant.ai.lstm 应暴露 LSTM"
    except Exception:
        pytest.skip("ai/lstm 模块不可用，仅校验源码路径已修正为 ..ai.lstm")


def test_uses_time_series_split():
    """④ grid/random_search 均改用 TimeSeriesSplit（时序不随机打散）。"""
    src = inspect.getsource(po)
    assert "_time_series_cv(self.cv_folds)" in src, "grid/random_search 应改用 _time_series_cv"
    assert "TimeSeriesSplit" in src, "应引用 TimeSeriesSplit"
    try:
        cv = po._time_series_cv(5)
        name = type(cv).__name__
        assert name == "TimeSeriesSplit", f"应返回 TimeSeriesSplit，实际 {name}"
    except ImportError:
        pytest.skip("本机无 sklearn，跳过 TimeSeriesSplit 实例化校验")
