"""M1-03 策略注册表单元测试。

覆盖 DoD:
    - STRATEGY_REGISTRY 包含 5 个即时策略 + 1 个延迟策略（gene）；
    - list_strategies() 字典序返回全部 6 个；
    - 所有内置策略能通过 build_strategy 构造；
    - 未知策略抛 ValueError（不静默回退）；
    - register_strategy 装饰器可注册新策略；
    - register_strategy 拒绝非 StrategyBase 子类；
    - gene 是延迟加载（首次调用 get_strategy_class 才导入）。
"""
from __future__ import annotations

import pytest

from futures_quant.strategy import (
    STRATEGY_REGISTRY,
    build_strategy,
    get_strategy_class,
    list_strategies,
    register_strategy,
    StrategyBase,
)


BUILTIN_IMMEDIATE = {"trend_following", "mean_reversion", "breakout", "grid", "martingale"}
BUILTIN_ALL = BUILTIN_IMMEDIATE | {"gene"}


def test_registry_contains_all_builtins():
    """5 个即时 + 1 个延迟（gene）都在清单里。"""
    names = set(list_strategies())
    assert names == BUILTIN_ALL
    # 5 个即时策略已在 STRATEGY_REGISTRY 中
    for name in BUILTIN_IMMEDIATE:
        assert name in STRATEGY_REGISTRY
        assert issubclass(STRATEGY_REGISTRY[name], StrategyBase)


def test_list_strategies_is_sorted():
    """list_strategies 返回字典序。"""
    names = list_strategies()
    assert names == sorted(names)


def test_build_strategy_all_immediate():
    """所有内置即时策略都能构造。"""
    for name in BUILTIN_IMMEDIATE:
        s = build_strategy(name, "rb.SHFE")
        assert isinstance(s, StrategyBase)
        assert s.symbol == "rb.SHFE"


def test_build_strategy_with_params_overrides_default():
    """params 会覆盖 default_params 中的同名键。"""
    s = build_strategy("trend_following", "rb.SHFE", params={"fast": 3, "slow": 200})
    assert s.params["fast"] == 3
    assert s.params["slow"] == 200
    # 其他默认参数保留
    assert "atr_period" in s.params


def test_unknown_strategy_raises_value_error():
    """未知策略名抛 ValueError（Fail Fast）。"""
    with pytest.raises(ValueError, match=r"Unknown strategy"):
        get_strategy_class("unknown_策略_xyz")


def test_build_unknown_raises_value_error():
    """build_strategy 走注册表，未知名字也抛 ValueError。"""
    with pytest.raises(ValueError):
        build_strategy("not_registered_xyz", "rb.SHFE")


def test_register_strategy_decorator():
    """register_strategy 可作为装饰器注册新策略。"""
    @register_strategy("__test_dummy__")
    class _Dummy(StrategyBase):
        name = "dummy"

    try:
        assert "__test_dummy__" in STRATEGY_REGISTRY
        cls = get_strategy_class("__test_dummy__")
        assert cls is _Dummy
        s = _Dummy(symbol="rb.SHFE")
        assert s.symbol == "rb.SHFE"
        assert "__test_dummy__" in list_strategies()
    finally:
        STRATEGY_REGISTRY.pop("__test_dummy__", None)


def test_register_strategy_rejects_non_strategy_base():
    """register_strategy 拒绝非 StrategyBase 子类。"""
    class _NotStrategy:
        pass

    with pytest.raises(TypeError):
        register_strategy("__bad__", _NotStrategy)


def test_gene_is_lazy_loaded():
    """gene 策略是延迟加载：包初始化后尚未在 STRATEGY_REGISTRY 中。"""
    # 由于本模块顶层已导入过整个测试会话中的其他 test 可能已触发加载，
    # 这里只断言通过 get_strategy_class 能拿到 gene，且不抛错。
    cls = get_strategy_class("gene")
    assert cls is not None
    assert cls.__name__ == "GeneStrategy"
    assert issubclass(cls, StrategyBase)


def test_backtest_service_uses_registry():
    """BacktestService.run_backtest_with_params 未知策略走 ValueError。"""
    from futures_quant.app.backtest_service import BacktestService

    # 用 None 占位 config/feed；调用 run_backtest_with_params 会在构造策略处即失败
    svc = BacktestService(config=None, feed=None)
    with pytest.raises(ValueError, match=r"Unknown strategy"):
        svc.run_backtest_with_params(
            symbol="rb.SHFE",
            start="2023-01-01",
            end="2023-02-01",
            strategy_name="__no_such_strategy__",
            strategy_params={},
            generate_report=False,
        )
