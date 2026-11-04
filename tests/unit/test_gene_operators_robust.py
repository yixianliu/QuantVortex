# -*- coding: utf-8 -*-
"""M1-02/M2-01 回归：遗传算子对任意基因（树形+旧版扁平库基因）零异常。

验收（来自 UPGRADE_PLAN_V5 M2-01）：
  对 60 个库基因 × 100 次 mutate + 2000 次 crossover 零异常；
  模拟 step() 繁育循环不抛错。
"""
import os
import random
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import futures_quant.strategy.auto_evolve as ae


def _library_genes():
    return ae.load_profitable()


def test_mutate_no_exception():
    rng = random.Random(12345)
    genes = _library_genes() or [ae.random_gene(rng) for _ in range(20)]
    for base in genes:
        for _ in range(100):
            try:
                g = ae.mutate(base, rng)
                assert g["type"] in ("factor", "op")
            except Exception:
                raise AssertionError("mutate 抛异常于基因: " + repr(base))


def test_crossover_no_exception():
    rng = random.Random(999)
    genes = _library_genes() or [ae.random_gene(rng) for _ in range(20)]
    n = 0
    for i in range(min(2000, 40 * len(genes))):
        a = genes[i % len(genes)]
        b = genes[(i * 7 + 3) % len(genes)]
        try:
            g = ae.crossover(a, b, rng)
            assert g["type"] in ("factor", "op")
            n += 1
        except Exception:
            raise AssertionError("crossover 抛异常于基因对")
    assert n > 0


def test_step_breeding_robust():
    """模拟 step() 的繁育循环，验证扁平库基因不再导致整代作废。"""
    rng = random.Random(7)
    pop = _library_genes()[:6] or [ae.random_gene(rng) for _ in range(6)]
    try:
        next_pop = []
        while len(next_pop) < 10:
            a = pop[rng.randrange(len(pop))]
            b = pop[rng.randrange(len(pop))]
            child = ae.crossover(a, b, rng) if rng.random() < 0.6 else dict(a)
            if rng.random() < 0.5:
                child = ae.mutate(child, rng)
            next_pop.append(child)
    except Exception:
        traceback.print_exc()
        raise AssertionError("繁育循环异常")


if __name__ == "__main__":
    test_mutate_no_exception()
    test_crossover_no_exception()
    test_step_breeding_robust()
    print("[OK] gene operator robustness passed")
