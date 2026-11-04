#!/usr/bin/env python
"""测试 M2-08 终止条件与实验记录功能"""

import sys
sys.path.insert(0, 'D:/PythonProject/QuantVortex')

from futures_quant.strategy.auto_evolve import EvolutionEngine

# 创建一个模拟的 feed
class MockFeed:
    def get_history(self, symbol, start, end, period):
        # 返回模拟数据
        return [
            {'datetime': '20240101', 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 1000},
            {'datetime': '20240102', 'open': 100.5, 'high': 101.5, 'low': 99.5, 'close': 101, 'volume': 1100},
        ]

# 测试 1: 验证构造函数参数
print("测试 1: 构造函数参数")
engine = EvolutionEngine(
    feed=MockFeed(),
    universe=[['rb', '螺纹钢', 1, 'SHFE', 10, 1.0]],
    start='2024-01-01',
    end='2024-01-02',
    seed=42,
    max_generations=3,
    patience=2,
    target_fitness=100.0
)
assert engine.max_generations == 3, "max_generations 参数错误"
assert engine.patience == 2, "patience 参数错误"
assert engine.target_fitness == 100.0, "target_fitness 参数错误"
assert engine._experiment['seed'] == 42, "experiment seed 错误"
assert engine._experiment['data_start'] == '2024-01-01', "experiment data_start 错误"
assert engine._experiment['data_end'] == '2024-01-02', "experiment data_end 错误"
print("✅ 构造函数参数测试通过")

# 测试 2: 验证 to_state/restore_state 包含实验数据
print("\n测试 2: 状态序列化")
state = engine.to_state()
assert 'experiment' in state, "to_state 缺少 experiment"
assert 'max_generations' in state, "to_state 缺少 max_generations"
assert 'patience' in state, "to_state 缺少 patience"
assert 'best_fitness' in state, "to_state 缺少 best_fitness"
assert 'stagnation_count' in state, "to_state 缺少 stagnation_count"

# 测试恢复
engine2 = EvolutionEngine(
    feed=MockFeed(),
    universe=[['rb', '螺纹钢', 1, 'SHFE', 10, 1.0]],
    seed=42
)
success = engine2.restore_state(state)
assert success, "restore_state 失败"
assert engine2.max_generations == 3, "恢复后的 max_generations 错误"
assert engine2.patience == 2, "恢复后的 patience 错误"
assert engine2._experiment['seed'] == 42, "恢复后的 experiment 错误"
print("✅ 状态序列化测试通过")

# 测试 3: 验证终止条件检查
print("\n测试 3: 终止条件检查")
engine3 = EvolutionEngine(
    feed=MockFeed(),
    universe=[['rb', '螺纹钢', 1, 'SHFE', 10, 1.0]],
    seed=42,
    max_generations=1
)
# 模拟已经完成1代
engine3.generation = 1
engine3._best_fitness = 50.0
engine3._stagnation_count = 0

# 下一次 step 应该直接返回终止信息
result = engine3.step()
assert result.get('evolution_done') == True, "应该检测到进化完成"
assert '已达最大代数上限' in result.get('termination_reason', ''), "终止原因错误"
print("✅ 终止条件检查测试通过")

# 测试 4: 验证实验记录内容
print("\n测试 4: 实验记录内容验证")
exp = engine._experiment
required_fields = ['seed', 'data_start', 'data_end', 'params', 'git_rev', 'started_at']
for field in required_fields:
    assert field in exp, f"experiment 缺少字段: {field}"
assert 'period' in exp['params'], "params 缺少 period"
assert 'max_generations' in exp['params'], "params 缺少 max_generations"
assert 'patience' in exp['params'], "params 缺少 patience"
print("✅ 实验记录内容测试通过")

print("\n" + "="*50)
print("🎉 所有 M2-08 测试通过!")
print("="*50)
