#!/usr/bin/env python
"""测试 M2-09 可复现性：同 seed 重跑结果一致 + 断点续跑一致"""

import sys
import json
sys.path.insert(0, 'D:/PythonProject/QuantVortex')

from futures_quant.strategy.auto_evolve import EvolutionEngine

# 极简 mock feed（本测试只验证 RNG 可复现性，不跑真实回测，
# 因此通过直接构造引擎并比对 rng 序列 / 种群生成结果来验证）
class MockFeed:
    def get_history(self, symbol, start, end, period):
        return []

UNIVERSE = [['rb', '螺纹钢', 1, 'SHFE', 10, 1.0]]

# ---------- 测试 1：同 seed 生成的随机序列完全一致 ----------
print("测试 1: 同 seed 随机序列可复现")
e1 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
e2 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
seq1 = [e1.rng.random() for _ in range(200)]
seq2 = [e2.rng.random() for _ in range(200)]
assert seq1 == seq2, "同 seed 随机序列不一致"
assert e1.seed == 20240921 and e2.seed == 20240921, "seed 未记录到引擎"
print("✅ 同 seed 随机序列完全一致")

# ---------- 测试 2：不同 seed 应产生不同序列 ----------
print("\n测试 2: 不同 seed 序列应不同")
e3 = EvolutionEngine(MockFeed(), UNIVERSE, seed=12345)
seq3 = [e3.rng.random() for _ in range(200)]
assert seq1 != seq3, "不同 seed 却产生了相同序列"
print("✅ 不同 seed 序列不同")

# ---------- 测试 3：to_state 保存 seed + rng_state ----------
print("\n测试 3: to_state 保存 seed 与 rng 状态")
e1.rng.random()  # 推进 RNG，制造非零状态
state = e1.to_state()
assert "seed" in state, "to_state 缺少 seed"
assert "rng_state" in state, "to_state 缺少 rng_state"
assert state["seed"] == 20240921, "seed 值错误"
rng_state = state["rng_state"]
assert isinstance(rng_state, list) and len(rng_state) == 3, "rng_state 结构错误"
# 必须可 JSON 序列化（evolve_state 落库要求）
json.dumps(state)
print("✅ to_state 正确保存 seed + rng_state 且可 JSON 序列化")

# ---------- 测试 4：restore_state 恢复 rng 状态后序列继续一致 ----------
print("\n测试 4: restore_state 恢复 RNG 状态后可续跑一致")
# e1 当前已推进；记录 e1 后续序列作为期望值
expected_next = [e1.rng.random() for _ in range(50)]
# 新建引擎并恢复 e1 保存的状态
e4 = EvolutionEngine(MockFeed(), UNIVERSE, seed=1)  # 先用不同 seed 构造
ok = e4.restore_state(state)
assert ok, "restore_state 返回 False"
assert e4.seed == 20240921, "恢复后 seed 未还原"
actual_next = [e4.rng.random() for _ in range(50)]
assert expected_next == actual_next, "恢复后 RNG 后续序列不一致"
print("✅ 断点恢复后 RNG 续跑序列完全一致")

# ---------- 测试 5：profitable_total 恢复存档值而非当前库长度 ----------
print("\n测试 5: profitable_total 恢复存档值")
st5 = {
    "version": 1,
    "sym_idx": 0,
    "generation": 5,
    "profitable_total": 42,   # 存档值
    "seed": 20240921,
}
e5 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
cur_len = e5.profitable_total  # 当前库真实长度
e5.restore_state(st5)
assert e5.profitable_total == 42, (
    f"profitable_total 应为存档值 42，实际 {e5.profitable_total}")
print(f"✅ profitable_total 恢复为存档值 42（当前库长度 {cur_len}，未覆盖）")

# ---------- 测试 6：状态往返（save→restore→save）幂等 ----------
print("\n测试 6: 状态往返幂等")
e6 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
e6.rng.random()
s_a = e6.to_state()
e7 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
e7.restore_state(s_a)
s_b = e7.to_state()
assert s_a["rng_state"] == s_b["rng_state"], "往返后 rng_state 不一致"
assert s_a["seed"] == s_b["seed"], "往返后 seed 不一致"
print("✅ 状态往返幂等")

print("\n" + "="*50)
print("🎉 所有 M2-09 可复现性测试通过!")
print("="*50)
