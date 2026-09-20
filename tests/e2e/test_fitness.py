"""M7.2 e2e：升级适应度函数（0.4*sharpe+0.3*calmar-0.2*max_dd-0.1*dd_dur + 跨品种稳定性惩罚）。

验证点：
- 方案公式逐项可加（sharpe/calmar 正向、max_dd/dd_dur 负向）。
- max_dd 百分制与小数制兼容。
- 跨品种夏普一致（cv≈0）不罚；离散大罚。
- 空/全零指标返回 -100。
- 全 0 夏普且 calmar=0、mdd=0 → 0.0（中性）。
"""
from __future__ import annotations

import unittest

from futures_quant.strategy.evolver import compute_fitness


class TestFitnessFormula(unittest.TestCase):
    def test_zero_all_is_zero(self) -> None:
        self.assertAlmostEqual(compute_fitness({"sharpe": 0.0, "calmar": 0.0, "max_drawdown": 0.0}), 0.0)

    def test_sharpe_contribution(self) -> None:
        f = compute_fitness({"sharpe": 1.0})
        self.assertAlmostEqual(f, 0.4, places=6)

    def test_calmar_contribution(self) -> None:
        self.assertAlmostEqual(compute_fitness({"calmar": 1.0}), 0.3, places=6)

    def test_max_dd_penalty_decimal(self) -> None:
        # -0.2 * 0.20 = -0.04
        self.assertAlmostEqual(compute_fitness({"max_drawdown": 0.20}), -0.04, places=6)

    def test_max_dd_penalty_percent_scale(self) -> None:
        # 百分制 20.0 → 0.20 → -0.04（与小数制一致）
        self.assertAlmostEqual(compute_fitness({"max_drawdown": 20.0}), -0.04, places=6)

    def test_dd_duration_penalty(self) -> None:
        # -0.1 * 0.5 = -0.05
        self.assertAlmostEqual(compute_fitness({"drawdown_duration": 0.5}), -0.05, places=6)

    def test_combined_formula(self) -> None:
        f = compute_fitness({"sharpe": 2.0, "calmar": 3.0, "max_drawdown": 0.10, "drawdown_duration": 0.2})
        # 0.4*2 + 0.3*3 - 0.2*0.1 - 0.1*0.2 = 0.8 + 0.9 - 0.02 - 0.02 = 1.66
        self.assertAlmostEqual(f, 1.66, places=6)

    def test_empty_returns_minus_100(self) -> None:
        self.assertEqual(compute_fitness({}), -100.0)
        self.assertEqual(compute_fitness(None), -100.0)


class TestStabilityPenalty(unittest.TestCase):
    def test_consistent_sharpes_no_penalty(self) -> None:
        base = compute_fitness({"sharpe": 1.0}, cross_symbol_sharpes=[1.0, 1.0, 1.0])
        self.assertAlmostEqual(base, 0.4, places=6)

    def test_diverse_sharpes_penalized(self) -> None:
        base = compute_fitness({"sharpe": 1.0})
        penalized = compute_fitness({"sharpe": 1.0}, cross_symbol_sharpes=[10.0, -10.0, 0.0])
        # cv of [10,-10,0] = std/|mean| = std(=7.45)/0 → fallback to std 7.45 → penalty capped 0.5
        self.assertLess(penalized, base - 0.3)

    def test_penalty_capped_at_half(self) -> None:
        base = compute_fitness({"sharpe": 1.0})
        f = compute_fitness({"sharpe": 1.0}, cross_symbol_sharpes=[100.0, -100.0, 0.0])
        self.assertGreaterEqual(f, base - 0.5 - 1e-9)
        self.assertLess(f, base)

    def test_single_symbol_no_penalty(self) -> None:
        self.assertAlmostEqual(
            compute_fitness({"sharpe": 1.0}, cross_symbol_sharpes=[3.0]),
            compute_fitness({"sharpe": 1.0}),
            places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
