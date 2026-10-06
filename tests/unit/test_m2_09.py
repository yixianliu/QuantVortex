"""M2-09 可复现性 —— pytest 形态。

由散落脚本 ``tests/test_m2_09.py``（模块级 ``print``+``assert``，0 个 ``def test_*``）
机械改写：6 段顶层断言收敛成 6 个 pytest 函数，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 本测试只验证 RNG 可复现性，不跑真实回测——MockFeed 返回空列表即可。
"""
from __future__ import annotations

import json

from futures_quant.strategy.auto_evolve import EvolutionEngine


class MockFeed:
    """本测试只验证 RNG 可复现性，不跑真实回测。"""

    def get_history(self, symbol, start, end, period):
        return []


UNIVERSE = [["rb", "螺纹钢", 1, "SHFE", 10, 1.0]]


def test_same_seed_same_sequence():
    """同 seed 生成的随机序列完全一致。"""
    e1 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    e2 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    seq1 = [e1.rng.random() for _ in range(200)]
    seq2 = [e2.rng.random() for _ in range(200)]
    assert seq1 == seq2, "同 seed 随机序列不一致"
    assert e1.seed == 20240921 and e2.seed == 20240921, "seed 未记录到引擎"


def test_diff_seed_diff_sequence():
    """不同 seed 应产生不同序列。"""
    e1 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    seq1 = [e1.rng.random() for _ in range(200)]
    e3 = EvolutionEngine(MockFeed(), UNIVERSE, seed=12345)
    seq3 = [e3.rng.random() for _ in range(200)]
    assert seq1 != seq3, "不同 seed 却产生了相同序列"


def test_to_state_saves_seed_and_rng_state():
    """to_state 保存 seed + rng_state，且可 JSON 序列化（evolve_state 落库要求）。"""
    e1 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    e1.rng.random()  # 推进 RNG，制造非零状态
    state = e1.to_state()
    assert "seed" in state, "to_state 缺少 seed"
    assert "rng_state" in state, "to_state 缺少 rng_state"
    assert state["seed"] == 20240921, "seed 值错误"
    rng_state = state["rng_state"]
    assert isinstance(rng_state, list) and len(rng_state) == 3, "rng_state 结构错误"
    json.dumps(state)


def test_restore_state_continues_rng():
    """restore_state 恢复 RNG 状态后，续跑序列与源引擎完全一致。"""
    e1 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    e1.rng.random()
    state = e1.to_state()
    expected_next = [e1.rng.random() for _ in range(50)]

    e4 = EvolutionEngine(MockFeed(), UNIVERSE, seed=1)  # 先用不同 seed 构造
    ok = e4.restore_state(state)
    assert ok, "restore_state 返回 False"
    assert e4.seed == 20240921, "恢复后 seed 未还原"
    actual_next = [e4.rng.random() for _ in range(50)]
    assert expected_next == actual_next, "恢复后 RNG 后续序列不一致"


def test_profitable_total_restores_archived_value():
    """profitable_total 恢复存档值，而非当前库长度。"""
    st5 = {
        "version": 1,
        "sym_idx": 0,
        "generation": 5,
        "profitable_total": 42,  # 存档值
        "seed": 20240921,
    }
    e5 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    _cur_len = e5.profitable_total  # 当前库真实长度（仅作说明，不覆盖）
    e5.restore_state(st5)
    assert e5.profitable_total == 42, (
        f"profitable_total 应为存档值 42，实际 {e5.profitable_total}")


def test_state_roundtrip_idempotent():
    """状态往返（save→restore→save）幂等。"""
    e6 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    e6.rng.random()
    s_a = e6.to_state()
    e7 = EvolutionEngine(MockFeed(), UNIVERSE, seed=20240921)
    e7.restore_state(s_a)
    s_b = e7.to_state()
    assert s_a["rng_state"] == s_b["rng_state"], "往返后 rng_state 不一致"
    assert s_a["seed"] == s_b["seed"], "往返后 seed 不一致"
