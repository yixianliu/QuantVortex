# -*- coding: utf-8 -*-
"""M1-07 弃用垫片：`futures_quant.ai.tuning` 已迁移到 `ai_tuning_optional`。

任何仍在使用 `from futures_quant.ai.tuning.X import Y` 的调用方，会在
首次访问子模块属性时通过 `__getattr__` 惰性重定向到 `ai_tuning_optional`，
并打印一次 DeprecationWarning。

M1-07 之后生产代码不应再引用本包；新代码请直接：
    from futures_quant.ai_tuning_optional.data_preprocessor import DataPreprocessor
"""

import importlib
import warnings
from typing import Any

_RELOCATED = (
    "futures_quant.ai.tuning 已在 M1-07 迁移到 futures_quant.ai_tuning_optional，"
    "请更新 import。见 docs/ORPHAN_MODULES.md。"
)

_submodules = {
    "data_preprocessor",
    "data_validator",
    "parameter_optimizer",
    "performance_evaluator",
    "visualizer",
}


def __getattr__(name: str) -> Any:
    """M1-07 弃用垫片：惰性重定向 + DeprecationWarning。"""
    if name in _submodules:
        warnings.warn(_RELOCATED, DeprecationWarning, stacklevel=2)
        return importlib.import_module(
            f"futures_quant.ai_tuning_optional.{name}")
    raise AttributeError(f"module 'futures_quant.ai.tuning' has no attribute {name!r}")


def __dir__() -> list:
    return sorted(list(_submodules))