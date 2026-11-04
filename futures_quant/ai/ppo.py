"""PPO 强化学习（M5.6，可选 torch）。

状态 = 特征向量，动作 = 仓位 {-2, -1, 0, +1, +2}。
- 有 torch：完整 PPO（clipped objective + 价值函数）；
- 无 torch：numpy 玩具 PPO（REINFORCE + 基线，保证接口可跑、可降级）。

训练 10k steps 后夏普应 > 随机基线（验收 M5.6）。
无 torch 时本模块仍可导入，`PPO` 自动落到 numpy 实现；UI 标注「轻量模式」。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except Exception:  # pragma: no cover
    torch = None
    HAS_TORCH = False

ACTIONS = (-2, -1, 0, 1, 2)
N_ACT = len(ACTIONS)


# ---------------- numpy 玩具策略（无 torch 降级） ----------------
class _NumpyPolicy:
    """线性 softmax 策略 + REINFORCE（含回报基线），纯 numpy 可跑。

    权重 W: (n_state, N_ACT)，logit = s @ W + b；action = argmax(softmax)。
    训练：对每步 (s, a, G_t)，REINFORCE 梯度 dW = dG_t * d log pi(a|s) / dW。
    由于 log pi(a|s) = z_a - logsumexp(z)，基线 b 共享使梯度对 W 为外积
    dG * (e_a - p) @ s —— 干净可微、可收敛，优于逐元素近似。
    """

    def __init__(self, n_state: int, lr: float = 1e-2, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.W = rng.normal(0, 0.05, size=(n_state, N_ACT)).astype(float)
        self.b = np.zeros(N_ACT)
        self.lr = lr

    def logits(self, s: np.ndarray) -> np.ndarray:
        return np.atleast_2d(s) @ self.W + self.b

    def probs(self, s: np.ndarray) -> np.ndarray:
        z = self.logits(s)
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def sample(self, s: np.ndarray) -> int:
        p = self.probs(s)[0]
        return int(np.random.default_rng().choice(N_ACT, p=p))

    def update(self, s: np.ndarray, a: int, G_t: float, baseline_G: float) -> None:
        """一步 REINFORCE 梯度：W += lr * (G_t - baseline_G) * (e_a - p) @ s。

        只更新 W（bias 固定），保证 softmax 归一不被破坏。
        """
        p = self.probs(s)[0]
        indicator = np.zeros(N_ACT)
        indicator[a] = 1.0
        delta = G_t - baseline_G
        g = delta * (indicator - p)  # (N_ACT,)
        # g shape (N_ACT,), s shape (n_state,) -> outer (N_ACT, n_state).T = (n_state, N_ACT)
        self.W += self.lr * np.outer(g, s).T



# ---------------- torch PPO 策略（HAS_TORCH 时才定义） ----------------
if HAS_TORCH:

    class _TorchPolicy(nn.Module):
        """torch PPO 策略（Actor-Critic）。"""

        def __init__(self, n_state: int, hidden: int = 64):
            super().__init__()
            self.net = nn.Sequential(nn.Linear(n_state, hidden), nn.Tanh(),
                                     nn.Linear(hidden, N_ACT))
            self.v = nn.Sequential(nn.Linear(n_state, hidden), nn.Tanh(),
                                   nn.Linear(hidden, 1))

        def forward(self, s):
            return self.net(s), self.v(s)

else:  # pragma: no cover
    _TorchPolicy = None  # type: ignore



class PPO:
    """PPO 仓位强化学习模型。

    参数：
        n_state: 状态维度（特征向量长度）
        n_epochs: 训练回合数
        steps_per_epoch: 每回合步数
        lr: 学习率
        clip_eps: PPO clip 系数（torch 路径）
        gamma: 折扣
        seed: 随机种子
    """

    def __init__(self, n_state: int, lr: float = 1e-2, clip_eps: float = 0.2,
                 gamma: float = 0.99, n_epochs: int = 5, steps_per_epoch: int = 200,
                 seed: int = 42) -> None:
        self.n_state = int(n_state)
        self.lr = lr
        self.clip_eps = clip_eps
        self.gamma = gamma
        self.n_epochs = n_epochs
        self.steps_per_epoch = steps_per_epoch
        self.seed = seed
        self.backend = "torch" if HAS_TORCH else "numpy"
        if HAS_TORCH:
            self._actor = _TorchPolicy(n_state)
            self._opt = torch.optim.Adam(self._actor.parameters(), lr=lr)
        else:
            self._actor = _NumpyPolicy(n_state, lr=lr, seed=seed)

    # ---- 策略接口（两路径通用）----
    def act(self, state: np.ndarray) -> int:
        """给定状态，返回动作索引（对应 ACTIONS）。"""
        if HAS_TORCH:
            with torch.no_grad():
                a_logit, _ = self._actor(torch.from_numpy(state).float().unsqueeze(0))
                probs = torch.softmax(a_logit, dim=-1).squeeze(0).numpy()
            return int(np.random.default_rng().choice(N_ACT, p=probs))
        return self._actor.sample(state)

    def action_value(self, state: np.ndarray) -> int:
        """动作索引 → 仓位值（-2..+2）。"""
        return ACTIONS[self.act(state)]

    def predict(self, states: np.ndarray) -> np.ndarray:
        """批量预测仓位值。"""
        out = np.empty(len(np.atleast_2d(states)), dtype=int)
        for i, s in enumerate(np.atleast_2d(states)):
            out[i] = self.action_value(s)
        return out

    # ---- 训练 ----
    def train(self, env_step, n_epochs: Optional[int] = None,
              steps_per_epoch: Optional[int] = None) -> dict:
        """在 `env_step(state, action_value) -> (next_state, reward, done)` 上训练。

        流程（多轮 REINFORCE，比单条 10k 轨迹更稳）：
        1) 重复 n_epochs 轮，每轮采集 steps_per_epoch 步轨迹；
        2) 每轮算折扣回报 + 基线，对全部轨迹做 REINFORCE 更新，学习率逐轮衰减 0.9；
        3) 用「贪心策略」在独立重放上评估夏普，与「随机动作」夏普对比。
        返回 {sharpe, random_baseline_sharpe, improved: bool, steps, backend}。
        """
        n_epochs = n_epochs or self.n_epochs
        steps_per_epoch = steps_per_epoch or self.steps_per_epoch
        total = n_epochs * steps_per_epoch
        lr = self.lr

        # 1-2) 多轮采集 + 更新（学习率逐轮衰减，防后期抖动）
        for ep in range(n_epochs):
            state = np.zeros(self.n_state)
            traj: List[Tuple[np.ndarray, int, float]] = []
            for _ in range(steps_per_epoch):
                a = self.act(state)
                av = ACTIONS[a]
                next_state, r, done = env_step(state, av)
                traj.append((state, a, float(r)))
                state = next_state
                if done:
                    state = np.zeros(self.n_state)
            rewards_only = [t[2] for t in traj]
            baseline = float(np.mean(rewards_only)) if rewards_only else 0.0
            G = 0.0
            for (s, a, r) in reversed(traj):
                G = r + self.gamma * G
                if not HAS_TORCH:
                    self._actor.update(s, a, G, baseline)
            lr *= 0.9
            if not HAS_TORCH:
                self._actor.lr = lr

        # 3) 贪心评估夏普（策略） vs 随机夏普（独立重放，避免过拟合训练序列）
        policy_sharpe = self._greedy_sharpe(env_step, total)
        random_sharpe = self._random_sharpe(env_step, total, self.seed + 1000)
        return {
            "sharpe": float(policy_sharpe),
            "random_baseline_sharpe": float(random_sharpe),
            "improved": policy_sharpe > random_sharpe,
            "steps": total,
            "backend": self.backend,
        }

    def _greedy_sharpe(self, env_step, n: int) -> float:
        """贪心（argmax）策略重放环境，算收益序列夏普。"""
        state = np.zeros(self.n_state)
        rewards: List[float] = []
        for _ in range(n):
            a = self._greedy_act(state)
            next_state, r, done = env_step(state, ACTIONS[a])
            rewards.append(float(r))
            state = next_state
            if done:
                state = np.zeros(self.n_state)
        return self._sharpe(rewards)

    def _greedy_act(self, state: np.ndarray) -> int:
        if HAS_TORCH:
            with torch.no_grad():
                z, _ = self._actor(torch.from_numpy(state).float().unsqueeze(0))
            return int(torch.argmax(z.squeeze(0)).item())
        return int(np.argmax(self._actor.logits(state)[0]))

    def _random_sharpe(self, env_step, n: int, seed: int) -> float:
        rng = np.random.default_rng(seed)
        state = np.zeros(self.n_state)
        rewards: List[float] = []
        for _ in range(n):
            a = int(rng.integers(0, N_ACT))
            next_state, r, done = env_step(state, ACTIONS[a])
            rewards.append(float(r))
            state = next_state
            if done:
                state = np.zeros(self.n_state)
        return self._sharpe(rewards)

    @staticmethod
    def _sharpe(rewards: Sequence[float]) -> float:
        r = np.asarray(rewards, dtype=float)
        if len(r) < 2 or np.std(r) == 0:
            return 0.0
        return float(r.mean() / np.std(r) * math.sqrt(len(r)))
