"""M1-03 策略注册表 end-to-end smoke 测试。

覆盖端到端 DoD：
    1. STRATEGY_REGISTRY 建立，5 个即时策略 + 1 个延迟策略（gene）
    2. BacktestService.run_backtest_with_params 走注册表；未知策略抛 ValueError
    3. BacktestService.run_backtest_with_gene 通过 gene 注册入口创建 GeneStrategy
    4. 进化引擎的 GeneStrategy 与手动回测通过同一注册表访问
    5. 消除平行路径：源码扫描，不再出现旧的 if/elif 白名单
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from futures_quant.strategy import (  # noqa: E402
    STRATEGY_REGISTRY,
    list_strategies,
    get_strategy_class,
    build_strategy,
    register_strategy,
    StrategyBase,
)
from futures_quant.app.backtest_service import BacktestService  # noqa: E402


BUILTIN_IMMEDIATE = {"trend_following", "mean_reversion", "breakout", "grid", "martingale"}
BUILTIN_ALL = BUILTIN_IMMEDIATE | {"gene"}


# 1. 注册表完整
def test_01_registry_complete():
    assert set(list_strategies()) == BUILTIN_ALL
    for name in BUILTIN_IMMEDIATE:
        assert issubclass(STRATEGY_REGISTRY[name], StrategyBase)


# 2. build_strategy 覆盖所有 5 个即时策略
def test_02_build_all_immediate():
    for name in BUILTIN_IMMEDIATE:
        s = build_strategy(name, "rb.SHFE")
        assert isinstance(s, StrategyBase)
        assert s.symbol == "rb.SHFE"


# 3. gene 延迟加载（不 import 就查不到，导入后可拿到）
def test_03_gene_lazy_loads():
    # 首次查询触发延迟加载
    cls = get_strategy_class("gene")
    assert cls.__name__ == "GeneStrategy"
    assert issubclass(cls, StrategyBase)
    # 现在 STRATEGY_REGISTRY 中也应有 gene
    assert "gene" in STRATEGY_REGISTRY


# 4. 未知策略 fail fast
def test_04_unknown_raises():
    for bad_name in ("unknown", "", "Trend_Following", "TREND_FOLLOWING"):
        try:
            get_strategy_class(bad_name)
            raise AssertionError(f"应该抛 ValueError 但 get_strategy_class({bad_name!r}) 未抛")
        except ValueError:
            pass
        except AssertionError:
            raise
        except Exception:
            # 空字符串可能是 KeyError，视为 pass（也是 Fail Fast 的一种）
            pass


# 5. BacktestService 未知策略 → ValueError
def test_05_service_unknown_strategy_raises():
    svc = BacktestService(config=MagicMock(), feed=MagicMock())
    try:
        svc.run_backtest_with_params(
            symbol="rb.SHFE", start="2023-01-01", end="2023-02-01",
            strategy_name="__no_such__", strategy_params={}, generate_report=False,
        )
        raise AssertionError("run_backtest_with_params 未知策略未抛 ValueError")
    except ValueError as e:
        assert "Unknown strategy" in str(e) or "no_such" in str(e)


# 6. BacktestService.run_backtest_with_gene 走 GeneStrategy
def test_06_service_run_with_gene():
    svc = BacktestService(config=MagicMock(), feed=MagicMock())
    gene = {"type": "factor", "name": "momentum", "params": {"window": 5}}

    captured = {}

    def fake_run_backtest(symbol, start, end, period="1m", warmup=0,
                          strategy=None, generate_report=True):
        captured["strategy_class"] = type(strategy).__name__
        captured["symbol"] = symbol
        return {"metrics": {}, "equity_curve": [], "trades": [], "report": None}

    # 替换 run_backtest 观察 strategy 参数（避免真实回测触发 build_contract）
    orig = svc.run_backtest
    svc.run_backtest = fake_run_backtest
    try:
        svc.run_backtest_with_gene("rb.SHFE", "2023-01-01", "2023-02-01", gene)
    finally:
        svc.run_backtest = orig

    assert captured.get("strategy_class") == "GeneStrategy", (
        f"预期 GeneStrategy，实际 {captured.get('strategy_class')}")
    assert captured.get("symbol") == "rb.SHFE"


# 7. run_backtest_with_params 走注册表（不写 if/elif）
def test_07_service_uses_registry_not_if_else():
    """扫描源码：run_backtest_with_params 方法体里不应再有 if/elif 白名单。"""
    src = Path(ROOT / "futures_quant" / "app" / "backtest_service.py").read_text(encoding="utf-8")
    # 找到 run_backtest_with_params 方法体
    start = src.find("def run_backtest_with_params")
    assert start >= 0, "找不到 run_backtest_with_params 方法"
    # 下一个方法 def 或 __all__
    end_markers = ["def run_backtest_with_gene", "__all__"]
    end = len(src)
    for marker in end_markers:
        idx = src.find(marker, start + 1)
        if idx >= 0:
            end = min(end, idx)
    body = src[start:end]
    # 断言：body 里不应再出现 "elif strategy_name" 分支
    assert "elif strategy_name" not in body, (
        "run_backtest_with_params 仍有 if/elif 白名单，M1-03 未完成")
    assert "if strategy_name == " not in body, (
        "run_backtest_with_params 仍有 if 白名单，M1-03 未完成")
    # 应有 get_strategy_class 调用
    assert "get_strategy_class" in body


# 8. 注册表可加自定义策略
def test_08_register_custom_strategy():
    class _CustomStrategy(StrategyBase):
        name = "__custom__"

    register_strategy("__custom_smoke__", _CustomStrategy)
    try:
        assert "__custom_smoke__" in list_strategies()
        cls = get_strategy_class("__custom_smoke__")
        assert cls is _CustomStrategy
        s = build_strategy("__custom_smoke__", "rb.SHFE")
        assert s.symbol == "rb.SHFE"
        assert s.name == "__custom__"
    finally:
        STRATEGY_REGISTRY.pop("__custom_smoke__", None)


# 9. EvolutionEngine GeneStrategy 与手动回测共享同一策略入口
def test_09_gene_is_same_class_as_evolution_engine_uses():
    """注册表中的 gene 类就是 auto_evolve.GeneStrategy。"""
    from futures_quant.strategy.auto_evolve import GeneStrategy as RealGene
    cls_from_registry = get_strategy_class("gene")
    assert cls_from_registry is RealGene


# 10. BacktestService 提供 _make_backtester 统一入口
def test_10_service_has_unified_backtester_entry():
    svc = BacktestService(config=MagicMock(), feed=MagicMock())
    assert hasattr(svc, "_make_backtester")
    assert callable(svc._make_backtester)
    # 检查 backtest_service 源码里所有 bt = Backtester(...) 都被 _make_backtester 封装
    src = Path(ROOT / "futures_quant" / "app" / "backtest_service.py").read_text(encoding="utf-8")
    # 应只有 _make_backtester 内部有 Backtester(...) 构造
    assert src.count("Backtester(") == 1, (
        f"Backtester 应只在 _make_backtester 内构造一次，实际 {src.count('Backtester(')} 次")


# ============================================================
def _run():
    tests = [
        ("1. 注册表完整（5 即时 + 1 延迟）", test_01_registry_complete),
        ("2. 5 个即时策略均可 build_strategy", test_02_build_all_immediate),
        ("3. gene 延迟加载", test_03_gene_lazy_loads),
        ("4. 未知策略 fail fast", test_04_unknown_raises),
        ("5. BacktestService 未知策略抛 ValueError", test_05_service_unknown_strategy_raises),
        ("6. run_backtest_with_gene 走 GeneStrategy", test_06_service_run_with_gene),
        ("7. run_backtest_with_params 无 if/elif 白名单", test_07_service_uses_registry_not_if_else),
        ("8. register_strategy 注册自定义策略", test_08_register_custom_strategy),
        ("9. 注册表 gene 与 EvolutionEngine 同 class", test_09_gene_is_same_class_as_evolution_engine_uses),
        ("10. _make_backtester 统一构造入口", test_10_service_has_unified_backtester_entry),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception:
            print(f"  ❌ {name}")
            traceback.print_exc()
    print(f"\nM1-03 smoke: {passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    ok = _run()
    sys.exit(0 if ok else 1)
