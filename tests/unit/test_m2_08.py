"""M2-08 终止条件与实验记录功能 —— pytest 形态。

由散落脚本 ``tests/test_m2_08.py``（模块级 ``print``+``assert``，0 个 ``def test_*``）
机械改写而来：把 4 段顶层断言收敛成 4 个 pytest 函数，行为契约保持不变。

改写要点（非简单移动）：
- 去掉脚本里的 ``sys.path.insert(0, 'D:/.../QuantVortex')`` 硬编码——``tests/conftest.py``
  已把项目根注入 ``sys.path``，pytest 收集期无需再手动插路径。
- 原脚本顶层无模块级 ``sys.exit``（属 7 个 ``print``+``assert`` 脚本之一），
  故本文件是"纯改写、无新增语义"的最安全试点。
- 顶层断言 → 每段一个 ``def test_*``，``assert`` 直接保留（pytest 原生）。

运行：
    QT_QPA_PLATFORM=offscreen pytest tests/unit/test_m2_08.py -q
"""
from __future__ import annotations

import pytest

from futures_quant.strategy.auto_evolve import EvolutionEngine


class MockFeed:
    """与原始脚本完全一致的模拟行情源（不依赖真实网络/数据）。"""

    def get_history(self, symbol, start, end, period):
        return [
            {"datetime": "20240101", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
            {"datetime": "20240102", "open": 100.5, "high": 101.5, "low": 99.5, "close": 101, "volume": 1100},
        ]


def _make_engine(seed: int = 42, max_generations: int = 3, patience: int = 2, target_fitness: float = 100.0):
    """构造与原始脚本"测试 1"段一致引擎（含实验记录字段）。"""
    return EvolutionEngine(
        feed=MockFeed(),
        universe=[["rb", "螺纹钢", 1, "SHFE", 10, 1.0]],
        start="2024-01-01",
        end="2024-01-02",
        seed=seed,
        max_generations=max_generations,
        patience=patience,
        target_fitness=target_fitness,
    )


def test_constructor_params():
    """原"测试 1：构造函数参数"。"""
    engine = _make_engine()
    assert engine.max_generations == 3, "max_generations 参数错误"
    assert engine.patience == 2, "patience 参数错误"
    assert engine.target_fitness == 100.0, "target_fitness 参数错误"
    assert engine._experiment["seed"] == 42, "experiment seed 错误"
    assert engine._experiment["data_start"] == "2024-01-01", "experiment data_start 错误"
    assert engine._experiment["data_end"] == "2024-01-02", "experiment data_end 错误"


def test_state_serialization():
    """原"测试 2：状态序列化"——to_state 含实验数据、restore_state 可还原。"""
    engine = _make_engine()
    state = engine.to_state()
    for key in ("experiment", "max_generations", "patience", "best_fitness", "stagnation_count"):
        assert key in state, f"to_state 缺少 {key}"

    engine2 = EvolutionEngine(feed=MockFeed(), universe=[["rb", "螺纹钢", 1, "SHFE", 10, 1.0]], seed=42)
    success = engine2.restore_state(state)
    assert success, "restore_state 失败"
    assert engine2.max_generations == 3, "恢复后的 max_generations 错误"
    assert engine2.patience == 2, "恢复后的 patience 错误"
    assert engine2._experiment["seed"] == 42, "恢复后的 experiment 错误"


def test_termination_condition():
    """原"测试 3：终止条件检查"——max_generations=1 且已跑 1 代时下次 step 即终止。"""
    engine = _make_engine(max_generations=1)
    engine.generation = 1
    engine._best_fitness = 50.0
    engine._stagnation_count = 0

    result = engine.step()
    assert result.get("evolution_done") is True, "应该检测到进化完成"
    assert "已达最大代数上限" in result.get("termination_reason", ""), "终止原因错误"


def test_experiment_record_fields():
    """原"测试 4：实验记录内容验证"——experiment 必含的字段与 params 子字段。"""
    engine = _make_engine()
    exp = engine._experiment
    for field in ("seed", "data_start", "data_end", "params", "git_rev", "started_at"):
        assert field in exp, f"experiment 缺少字段: {field}"
    for sub in ("period", "max_generations", "patience"):
        assert sub in exp["params"], f"params 缺少 {sub}"
