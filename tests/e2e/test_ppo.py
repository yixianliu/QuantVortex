"""M5.6 PPO 强化学习验收测试（无 torch 走 numpy 降级路径）。

覆盖：
- PPO 可导入、可构造（无 torch 时 backend='numpy'）；
- act/predict 输出动作在 {-2,-1,0,+1,+2} 内；
- train 在确定性奖励环境下夏普 > 随机基线（验收 M5.6）；
- 训练 steps 计数正确。
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import numpy as np
from ai.ppo import PPO, ACTIONS


def _make_env(n_state: int, reward_rule: str = "plus"):
    """简单环境：state 为特征，动作仓位 av，奖励 = f(av, state)，10 步后 done。"""
    step_count = {"n": 0}

    def env_step(state, action_value):
        step_count["n"] += 1
        done = step_count["n"] % 10 == 0
        if reward_rule == "plus":
            # 鼓励多仓位：奖励 = 0.1 * av + 0.01 * sum(state)
            r = 0.1 * action_value + 0.01 * float(np.sum(state))
        else:
            r = 0.0
        next_state = state * 0.9 + np.array([0.1] * n_state)
        return next_state, r, done

    return env_step


def test_import_and_backend():
    ppo = PPO(n_state=6)
    assert ppo.backend in ("torch", "numpy")
    print("import OK, backend =", ppo.backend)


def test_actions_in_range():
    ppo = PPO(n_state=6)
    s = np.random.randn(6)
    for _ in range(20):
        av = ppo.action_value(s)
        assert av in ACTIONS, f"动作 {av} 越界"
    # 批量 predict
    states = np.random.randn(10, 6)
    pred = ppo.predict(states)
    assert pred.shape == (10,)
    assert all(p in ACTIONS for p in pred)
    print("动作范围 OK")


def test_sharpe_beats_random():
    """验收：10k steps 后夏普 > 随机基线。"""
    n_state = 8
    ppo = PPO(n_state=n_state, n_epochs=50, steps_per_epoch=200, seed=7)
    env = _make_env(n_state, reward_rule="plus")
    res = ppo.train(env)
    assert res["steps"] == 50 * 200
    assert res["improved"], f"夏普 {res['sharpe']} 未超过随机基线 {res['random_baseline_sharpe']}"
    print(f"夏普 OK: policy={res['sharpe']:.3f} random={res['random_baseline_sharpe']:.3f}")


def test_flat_reward_sharpe_near_zero():
    """无奖励环境夏普应接近 0（无套利机会）。"""
    n_state = 5
    ppo = PPO(n_state=n_state, n_epochs=10, steps_per_epoch=100, seed=1)
    env = _make_env(n_state, reward_rule="flat")
    res = ppo.train(env)
    assert abs(res["sharpe"]) < 0.5, f"平坦奖励夏普应接近 0，实际 {res['sharpe']}"
    print("平坦奖励夏普 OK")


if __name__ == "__main__":
    test_import_and_backend()
    test_actions_in_range()
    test_sharpe_beats_random()
    test_flat_reward_sharpe_near_zero()
    print("test_ppo.py 全绿")
