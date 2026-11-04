"""M7.1 e2e：三轨进化控制器（策略 / 模型超参 / 风控），独立 + 联合进化，离线可测。

验证点：
- random_genome 生成指定轨基因（缺失轨为 None）。
- active_tracks 反映非空轨。
- mutate / crossover 结构保持（key 不丢、类型正确）。
- evaluate 委托 fitness_fn；异常降级 -1e9。
- run(generations) 返回 best_genome + 收敛曲线长度=generations，best/mean 有限。
- 单轨独立进化（只变异 model 轨，strategy 不变）。
- 参数校验（pop_size<2、generations<0）。
- 可复现（同 seed 两次 run 收敛一致）。
"""
from __future__ import annotations

import unittest

import numpy as np

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from futures_quant.strategy.evolver import (
    DEFAULT_MODEL_SPACE,
    DEFAULT_RISK_SPACE,
    Genome,
    TRACKS,
    EvolutionController,
)


def _sq_sum_fitness(g: Genome) -> float:
    """假适应度：所有轨数值基因的平方和（越大越『好』），用于离线验证 GA 是否单调不劣化趋势。"""
    s = 0.0
    for t in TRACKS:
        gene = getattr(g, t)
        if not gene:
            continue
        for v in gene.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                s += float(v) ** 2
    return s


def _count_genes(g: Genome) -> int:
    n = 0
    for t in TRACKS:
        gene = getattr(g, t)
        if gene:
            n += 1
    return n


class TestGenome(unittest.TestCase):
    def test_random_tracks_partial(self) -> None:
        ctl = EvolutionController(_sq_sum_fitness, seed=1)
        g = ctl.random_genome(["model"])
        self.assertIsNotNone(g.model)
        self.assertIsNone(g.strategy)
        self.assertEqual(g.active_tracks(), ["model"])

    def test_clone_independent(self) -> None:
        g = Genome(model={"lr": 0.01})
        c = g.clone()
        c.model["lr"] = 0.05
        self.assertEqual(g.model["lr"], 0.01)


class TestMutation(unittest.TestCase):
    def setUp(self) -> None:
        self.ctl = EvolutionController(_sq_sum_fitness, seed=7)

    def test_mutation_preserves_structure(self) -> None:
        import json
        g = self.ctl.random_genome(TRACKS)
        # model / risk 轨：变异只替换取值，key 集不变
        model_keys = set((g.model or {}).keys())
        risk_keys = set((g.risk or {}).keys())
        for _ in range(5):
            g = self.ctl.mutate(g, TRACKS)
            self.assertIsInstance(g.strategy, dict, "strategy 轨必须是 dict")
            json.dumps(g.strategy)  # 可序列化（基因要落盘）
            self.assertSetEqual(set((g.model or {}).keys()), model_keys, "model 轨 key 不变")
            self.assertSetEqual(set((g.risk or {}).keys()), risk_keys, "risk 轨 key 不变")

    def test_single_track_mutation_isolated(self) -> None:
        g = self.ctl.random_genome(["model", "strategy"])
        strat_snapshot = dict(g.strategy)
        m2 = self.ctl.mutate(g, ["model"])
        self.assertEqual(m2.strategy, strat_snapshot)  # 未触碰轨不变
        self.assertIsNotNone(m2.model)

    def test_crossover_structure(self) -> None:
        a = self.ctl.random_genome(TRACKS)
        b = self.ctl.random_genome(TRACKS)
        c = self.ctl.crossover(a, b, ["risk"])
        self.assertIsInstance(c.risk, dict)
        # risk 轨 key 为 a/b 的并集
        self.assertTrue(set(c.risk.keys()) & set(DEFAULT_RISK_SPACE.keys()))

    def test_evaluate_delegates(self) -> None:
        g = Genome(model={"lr": 2.0})
        self.assertEqual(self.ctl.evaluate(g), 4.0)  # 2.0^2

    def test_evaluate_exception_degrades(self) -> None:
        def boom(_: Genome) -> float:
            raise RuntimeError("x")
        ctl = EvolutionController(boom, seed=0)
        self.assertLess(ctl.evaluate(Genome(model={"lr": 1.0})), -1e8)


class TestRun(unittest.TestCase):
    def test_run_returns_convergence(self) -> None:
        ctl = EvolutionController(_sq_sum_fitness, pop_size=6, elites=2, seed=3)
        res = ctl.run(generations=5, tracks=["model"])
        self.assertEqual(len(res["convergence"]), 5)
        for row in res["convergence"]:
            self.assertTrue(np.isfinite(row["best"]))
            self.assertTrue(np.isfinite(row["mean"]))
        self.assertIsNotNone(res["best_genome"].model)

    def test_run_improves_or_equal_best(self) -> None:
        """GA 收敛末代 best 不应劣于首代 best（精英保留保证单调不降）。"""
        ctl = EvolutionController(_sq_sum_fitness, pop_size=8, elites=2, seed=11)
        res = ctl.run(generations=8, tracks=["model", "risk"])
        conv = res["convergence"]
        self.assertGreaterEqual(conv[-1]["best"], conv[0]["best"] - 1e-6)

    def test_reproducible_with_seed(self) -> None:
        a = EvolutionController(_sq_sum_fitness, pop_size=6, seed=42).run(generations=4, tracks=["model"])
        b = EvolutionController(_sq_sum_fitness, pop_size=6, seed=42).run(generations=4, tracks=["model"])
        self.assertEqual([r["best"] for r in a["convergence"]], [r["best"] for r in b["convergence"]])

    def test_invalid_params(self) -> None:
        with self.assertRaises(ValueError):
            EvolutionController(_sq_sum_fitness, pop_size=1)
        ctl = EvolutionController(_sq_sum_fitness, seed=0)
        with self.assertRaises(ValueError):
            ctl.run(generations=-1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
