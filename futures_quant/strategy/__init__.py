"""策略注册表（M1-03）。

设计目标：
    - **消除白名单**：`BacktestService.run_backtest_with_params()` 不再用
      ``if/elif`` 手工列举策略；改为统一走本模块的 ``STRATEGY_REGISTRY``。
    - **可扩展**：新增策略只需在对应模块调用 ``@register_strategy("name")``，
      或在包加载时 ``register_strategy("name", Cls)`` 显式注册。
    - **Fail-Fast**：未知策略名抛 ``ValueError``（不静默回退到默认）。
    - **统一实例化**：``build_strategy(name, symbol, **params)`` 是唯一的
      「名字 → 策略实例」入口，进化引擎与手动回测共享同一策略构造路径。

M1-03（2026-10-01）：本模块建立后，`BacktestService.run_backtest_with_params`
改为查表；`EvolutionEngine` 的 ``GeneStrategy`` 也显式注册（"gene"），
使「基因→策略」的构造路径可通过注册表统一访问，消除平行路径。
"""
from __future__ import annotations

import importlib
import logging
from typing import Dict, Optional, Type

from .base import StrategyBase

__all__ = [
    "STRATEGY_REGISTRY",
    "register_strategy",
    "get_strategy_class",
    "list_strategies",
    "build_strategy",
    "StrategyBase",
]

logger = logging.getLogger(__name__)

# 策略注册表：name → StrategyBase 子类
STRATEGY_REGISTRY: Dict[str, Type[StrategyBase]] = {}


def register_strategy(name: str, cls: Optional[Type[StrategyBase]] = None) -> Type[StrategyBase]:
    """策略注册器：既可当函数用，也可当装饰器用。

    示例:
        @register_strategy("trend_following")
        class TrendFollowing(StrategyBase): ...

    或:
        register_strategy("trend_following", TrendFollowing)
    """
    def _register(c: Type[StrategyBase]) -> Type[StrategyBase]:
        if not (isinstance(c, type) and issubclass(c, StrategyBase)):
            raise TypeError(f"register_strategy 只接受 StrategyBase 子类，收到 {c!r}")
        STRATEGY_REGISTRY[name] = c
        return c

    if cls is not None:
        return _register(cls)
    return _register


def get_strategy_class(name: str) -> Type[StrategyBase]:
    """获取策略类；未注册时抛 ``ValueError``（不静默回退）。"""
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        known = ", ".join(sorted(STRATEGY_REGISTRY.keys())) or "(empty)"
        raise ValueError(f"Unknown strategy: {name!r}. Registered: {known}")
    return cls


def list_strategies() -> list:
    """已注册的策略名列表（字典序）。"""
    return sorted(STRATEGY_REGISTRY.keys())


def build_strategy(name: str, symbol: str, params: Optional[dict] = None) -> StrategyBase:
    """按名字构造策略实例。

    所有内置策略统一签名 ``__init__(self, symbol, params=None)``；``params`` 会与
    ``StrategyBase.default_params`` 深合并。

    参数:
        name: 已注册策略名（见 STRATEGY_REGISTRY）。
        symbol: 合约代码，如 "rb.SHFE"。
        params: 可选，用户参数 dict；默认空。

    返回:
        StrategyBase 实例。

    异常:
        ValueError: 未知策略名。
    """
    cls = get_strategy_class(name)
    return cls(symbol=symbol, params=params)


# ============================================================
# 预注册内置策略
# ------------------------------------------------------------
# 设计要点：
#   - 轻量策略（trend_following / mean_reversion / breakout / grid / martingale）
#     在包加载时立即注册；
#   - `gene` 策略放在 auto_evolve.py 内，但 auto_evolve 内部有 `from . import validate`
#     会反向触发本 __init__ → 循环导入。所以 gene 用**延迟加载**：首次查询才导入。
# ============================================================
_IMMEDIATE_SPECS = [
    ("trend_following", "futures_quant.strategy.trend_following", "TrendFollowing"),
    ("mean_reversion", "futures_quant.strategy.mean_reversion", "MeanReversion"),
    ("breakout", "futures_quant.strategy.breakout", "Breakout"),
    ("grid", "futures_quant.strategy.grid", "Grid"),
    ("martingale", "futures_quant.strategy.martingale", "Martingale"),
]

# 延迟策略：name → (module, attr)
_LAZY_SPECS = {
    "gene": ("futures_quant.strategy.auto_evolve", "GeneStrategy"),
}


def _preload_builtin_strategies() -> None:
    """预加载轻量内置策略；失败不影响其他策略的注册。"""
    for name, mod_path, cls_name in _IMMEDIATE_SPECS:
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            if isinstance(cls, type) and issubclass(cls, StrategyBase):
                STRATEGY_REGISTRY[name] = cls
            else:
                logger.warning("策略 %s 未成功注册：%s.%s 不是 StrategyBase 子类",
                               name, mod_path, cls_name)
        except Exception as e:  # noqa: BLE001
            logger.warning("策略 %s 加载失败：%s", name, e)


def _try_lazy_load(name: str) -> bool:
    """按需加载延迟策略（gene 等）。已注册或加载失败返回 False。"""
    spec = _LAZY_SPECS.get(name)
    if spec is None:
        return False
    mod_path, cls_name = spec
    try:
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        if isinstance(cls, type) and issubclass(cls, StrategyBase):
            STRATEGY_REGISTRY[name] = cls
            return True
    except Exception as e:  # noqa: BLE001
        logger.warning("延迟加载策略 %s 失败：%s", name, e)
    return False


# 用 list_strategies() 与 get_strategy_class() 包装支持延迟加载
def list_strategies() -> list:  # noqa: F811
    """已注册（含可延迟加载）的策略名列表（字典序）。"""
    return sorted(set(STRATEGY_REGISTRY.keys()) | set(_LAZY_SPECS.keys()))


def get_strategy_class(name: str) -> Type[StrategyBase]:  # noqa: F811
    """获取策略类；未注册时抛 ``ValueError``（不静默回退）。

    若名字在延迟加载清单里，先尝试加载一次。
    """
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None and name in _LAZY_SPECS:
        _try_lazy_load(name)
        cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        known = ", ".join(list_strategies()) or "(empty)"
        raise ValueError(f"Unknown strategy: {name!r}. Registered: {known}")
    return cls


_preload_builtin_strategies()
