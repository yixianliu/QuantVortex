"""M7.5 e2e：模型漂移检测（近 60 天命中率 vs 训练期基准，超阈值触发重训警告）。

验证点：
- 命中率稳定在基准附近 → 不触发（status=ok，drift_score 低）。
- 命中率持续高于基准 → 触发（status=drift）。
- 窗口样本不足 → no_data 降级（不误报）。
- 边界：drift_score∈[0,1]；threshold 可调。
- rolling_hit_drift 取最后 window 天。
"""
from __future__ import annotations

import unittest

import numpy as np

from futures_quant.ai.drift import detect_drift, rolling_hit_drift, DEFAULT_THRESHOLD


class TestDetectDrift(unittest.TestCase):
    def test_stable_no_trigger(self) -> None:
        rng = np.random.default_rng(1)
        window = [0.5 + float(rng.normal(0, 0.01)) for _ in range(60)]
        res = detect_drift(window, 0.5)
        self.assertEqual(res.status, "ok")
        self.assertFalse(res.triggered)
        self.assertLess(res.drift_score, DEFAULT_THRESHOLD)

    def test_sustained_high_triggers(self) -> None:
        window = [0.80] * 60
        res = detect_drift(window, 0.5)
        self.assertEqual(res.status, "drift")
        self.assertTrue(res.triggered)
        # |0.8-0.5|/0.5 = 0.6
        self.assertAlmostEqual(res.drift_score, 0.6, places=6)

    def test_sustained_low_triggers(self) -> None:
        res = detect_drift([0.10] * 60, 0.5)
        self.assertTrue(res.triggered)
        self.assertAlmostEqual(res.drift_score, 0.8, places=6)

    def test_no_data_degrades(self) -> None:
        res = detect_drift([0.5, 0.5, 0.5], 0.5, min_days=10)
        self.assertEqual(res.status, "no_data")
        self.assertFalse(res.triggered)
        self.assertIsNone(res.correlation)

    def test_score_bounds(self) -> None:
        rng = np.random.default_rng(2)
        window = [float(np.clip(0.5 + rng.normal(0, 0.1), 0, 1)) for _ in range(60)]
        res = detect_drift(window, 0.5)
        self.assertGreaterEqual(res.drift_score, 0.0)
        self.assertLessEqual(res.drift_score, 1.0)

    def test_threshold_tunable(self) -> None:
        res = detect_drift([0.6] * 60, 0.5, threshold=0.3)
        # |0.6-0.5|/0.5=0.2 ≤0.3 → 不触发
        self.assertFalse(res.triggered)
        res2 = detect_drift([0.6] * 60, 0.5, threshold=0.15)
        self.assertTrue(res2.triggered)

    def test_to_dict(self) -> None:
        res = detect_drift([0.5] * 60, 0.5)
        d = res.to_dict()
        for k in ("drift_score", "window_mean", "baseline_mean", "correlation", "triggered", "status"):
            self.assertIn(k, d)


class TestRolling(unittest.TestCase):
    def test_rolling_takes_last_window(self) -> None:
        # 前 100 天稳定 0.5，最后 60 天全部 0.9 → 取最后 60 天应触发
        series = [0.5] * 100 + [0.9] * 60
        res = rolling_hit_drift(series, 0.5, window=60)
        self.assertTrue(res.triggered)
        self.assertAlmostEqual(res.window_mean, 0.9, places=6)

    def test_rolling_insufficient_series(self) -> None:
        res = rolling_hit_drift([0.5, 0.6], 0.5, window=60)
        self.assertEqual(res.status, "no_data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
