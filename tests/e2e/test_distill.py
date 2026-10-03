"""M7.6 e2e：知识蒸馏（最强策略基因 → 可读规则集 → rules.json，保真度评估）。

验证点：
- select_top 按 fitness 降序取前 k。
- distill 扁平基因 → 可读规则（factor_label / entry_desc / exit_desc / risk）。
- distill 树结构基因（type=op + left/right）→ 组合因子标签。
- export_rules 写 rules.json（写入成功 + 结构），路径只读时降级（written=False 不抛错）。
- fidelity 夏普下降比例：下降 ≤10% 合格，>10% 不合格；原始夏普 0 → 0.0。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from futures_quant.strategy.distill import (
    FIDELITY_TOLERANCE,
    distill,
    export_rules,
    fidelity,
    select_top,
)


def _entries() -> list:
    return [
        {"gene": {"factor": "ma_cross", "ma_fast": 5, "ma_slow": 30,
                  "stop_mult": 2.0, "tp_mult": 0, "lots": 1, "allow_long": True, "allow_short": True},
         "fitness": 10.0},
        {"gene": {"factor": "donchian_break", "stop_mult": 1.5, "tp_mult": 2.0, "lots": 2},
         "fitness": 25.0},
        {"gene": {"factor": "rsi_reversal", "stop_mult": 3.0, "tp_mult": 0, "lots": 1},
         "fitness": 15.0},
    ]


class TestSelectTop(unittest.TestCase):
    def test_ranking(self) -> None:
        top = select_top(_entries(), 2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]["fitness"], 25.0)
        self.assertEqual(top[1]["fitness"], 15.0)

    def test_missing_fitness_last(self) -> None:
        e = _entries() + [{"gene": {"factor": "x"}, "fitness": None}]
        top = select_top(e, 4)
        self.assertEqual(top[-1], e[3])  # fitness=None 排最后


class TestDistill(unittest.TestCase):
    def test_flat_gene(self) -> None:
        r = distill(_entries()[0]["gene"])
        self.assertEqual(r["factor"], "ma_cross")
        self.assertEqual(r["factor_label"], "双均线交叉")
        self.assertIn("入场", r["entry_desc"])
        self.assertIn("ATR 跟踪止损", r["exit_desc"])
        self.assertEqual(r["risk"]["stop_mult"], 2.0)
        self.assertEqual(r["params"]["ma_fast"], 5)

    def test_tree_gene(self) -> None:
        tree = {
            "type": "op", "op": "AND",
            "left": {"factor": "ma_cross", "stop_mult": 1.0},
            "right": {"factor": "momentum", "stop_mult": 2.0},
        }
        r = distill(tree)
        self.assertIn("ma_cross", r["factor"])
        self.assertIn("momentum", r["factor"])
        self.assertIn("AND", r["entry_desc"])

    def test_unknown_factor_fallback_label(self) -> None:
        r = distill({"factor": "totally_new_factor", "stop_mult": 1.0})
        self.assertEqual(r["factor_label"], "totally_new_factor")  # 无标签回退原名


class TestExport(unittest.TestCase):
    def test_export_writes_file(self) -> None:
        tmp = tempfile.mkdtemp(prefix="distill_")
        path = os.path.join(tmp, "sub", "rules.json")
        res = export_rules(_entries(), k=3, path=path)
        self.assertTrue(res["written"])
        self.assertEqual(res["n_rules"], 3)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["n_rules"], 3)
        self.assertEqual(data["best_fitness"], 25.0)
        self.assertEqual(len(data["rules"]), 3)

    def test_export_readonly_degrades(self) -> None:
        # 父目录为已存在的文件 → makedirs 失败，写入降级（written=False，规则仍返回）
        tmp = tempfile.mkdtemp(prefix="distill_")
        blocker = os.path.join(tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        bad_path = os.path.join(blocker, "nested", "rules.json")  # blocker 是文件不是目录
        res = export_rules(_entries(), k=2, path=bad_path)
        self.assertFalse(res["written"])
        self.assertEqual(res["n_rules"], 2)  # 规则仍计算
        self.assertTrue(res["top"])

    def test_empty_entries(self) -> None:
        tmp = tempfile.mkdtemp(prefix="distill_")
        res = export_rules([], k=3, path=os.path.join(tmp, "r.json"))
        self.assertEqual(res["n_rules"], 0)
        self.assertIsNone(res["best_fitness"])


class TestFidelity(unittest.TestCase):
    def test_within_tolerance_passes(self) -> None:
        drop = fidelity({"sharpe": 1.0}, {"sharpe": 0.95})
        self.assertLessEqual(drop, FIDELITY_TOLERANCE)  # 0.05 ≤ 0.10

    def test_exceeds_tolerance(self) -> None:
        drop = fidelity({"sharpe": 1.0}, {"sharpe": 0.5})
        self.assertGreater(drop, FIDELITY_TOLERANCE)  # 0.5 > 0.10

    def test_zero_original(self) -> None:
        self.assertEqual(fidelity({"sharpe": 0.0}, {"sharpe": 0.4}), 0.0)

    def test_missing_original(self) -> None:
        self.assertEqual(fidelity({}, {"sharpe": 0.4}), 0.0)

    def test_distilled_better_no_negative(self) -> None:
        # 蒸馏后夏普更高 → 下降 0（不罚）
        self.assertEqual(fidelity({"sharpe": 1.0}, {"sharpe": 1.5}), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
