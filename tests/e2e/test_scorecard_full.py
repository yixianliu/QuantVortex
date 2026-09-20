"""M8.5 e2e：综合信号面板（消息面/持仓/基差/事件 四子项汇入打分卡）。

验证点：
- M6.3 默认 4 项行为不变（include_full=False 时不出现 news/position/basis/event）。
- include_full=True 时 detail() 含全部 8 项。
- 各新子项缺失 → 0.5 中性，综合分可复现（与全 None 一致）。
- 偏多信号（消息面/基差/事件/持仓）抬升综合分。
- FULL_WEIGHTS 和=1。
"""
from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from futures_quant.analysis.scorecard import (
    DEFAULT_WEIGHTS,
    FULL_WEIGHTS,
    Scorecard,
    rank_scorecards,
)


def _make_df(seed: int = 7, n: int = 200, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.01, n)
    close = 100 * np.exp(np.cumsum(rets))
    vol = np.abs(rng.normal(1e5, 1e4, n)) + 1e3
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"close": close, "volume": vol, "high": close * 1.005, "low": close * 0.995},
        index=idx,
    )


class TestScorecardFull(unittest.TestCase):
    def test_default_m63_unchanged(self) -> None:
        df = _make_df()
        sc = Scorecard(df)  # include_full 默认 False
        keys = list(sc.sub_scores().keys())
        self.assertEqual(keys, ["technical", "volume", "ai_prob", "sector"])
        # 无 sector → 0.5 中性
        self.assertAlmostEqual(sc.sub_scores()["sector"].normalized, 0.5)

    def test_full_8_items(self) -> None:
        df = _make_df()
        sc = Scorecard(df, include_full=True)
        keys = set(sc.sub_scores().keys())
        self.assertEqual(keys, set(FULL_WEIGHTS.keys()))
        self.assertEqual(len(keys), 8)

    def test_full_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(FULL_WEIGHTS.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS.values()), 1.0, places=6)

    def test_all_missing_neutral_reproducible(self) -> None:
        df = _make_df()
        a = Scorecard(df, include_full=True)  # 全部新因子缺失
        b = Scorecard(df, include_full=True, news_sentiment=None,
                      position_long_short_ratio=None, basis_rank=None, event_impact=None)
        self.assertEqual(a.composite(), b.composite())
        # 缺失新子项各 normalized=0.5
        for k in ("news", "position", "basis", "event"):
            self.assertAlmostEqual(a.sub_scores()[k].normalized, 0.5)

    def test_bullish_raises_score(self) -> None:
        df = _make_df(drift=0.002)
        base = Scorecard(df, include_full=True).composite()
        bull = Scorecard(
            df, include_full=True,
            ai_prob=0.9,
            news_sentiment=0.85,
            position_long_short_ratio=3.0,
            basis_rank=0.9,
            event_impact=0.8,
        )
        self.assertGreater(bull.composite(), base)

    def test_bearish_lowers_score(self) -> None:
        df = _make_df()
        neutral = Scorecard(df, include_full=True).composite()
        bear = Scorecard(
            df, include_full=True,
            ai_prob=0.1,
            news_sentiment=0.15,
            position_long_short_ratio=0.3,
            basis_rank=0.1,
            event_impact=-0.8,
        )
        self.assertLess(bear.composite(), neutral)

    def test_position_tanh_symmetry(self) -> None:
        df = _make_df()
        # ratio=1 → 0.5；ratio=2 → >0.5；ratio=0.5 → <0.5
        s1 = Scorecard(df, include_full=True, position_long_short_ratio=1.0).sub_scores()["position"]
        s2 = Scorecard(df, include_full=True, position_long_short_ratio=2.0).sub_scores()["position"]
        s3 = Scorecard(df, include_full=True, position_long_short_ratio=0.5).sub_scores()["position"]
        self.assertAlmostEqual(s1.normalized, 0.5, places=6)
        self.assertGreater(s2.normalized, 0.5)
        self.assertLess(s3.normalized, 0.5)
        self.assertTrue(s1.available and s2.available and s3.available)

    def test_position_nonfinite_degrades_neutral(self) -> None:
        df = _make_df()
        for bad in (float("inf"), float("nan"), 0.0, -1.0):
            s = Scorecard(df, include_full=True, position_long_short_ratio=bad).sub_scores()["position"]
            self.assertFalse(s.available)
            self.assertAlmostEqual(s.normalized, 0.5)

    def test_event_clamped(self) -> None:
        df = _make_df()
        lo = Scorecard(df, include_full=True, event_impact=-5.0).sub_scores()["event"]
        hi = Scorecard(df, include_full=True, event_impact=5.0).sub_scores()["event"]
        self.assertAlmostEqual(lo.normalized, 0.0, places=6)
        self.assertAlmostEqual(hi.normalized, 1.0, places=6)
        zero = Scorecard(df, include_full=True, event_impact=0.0).sub_scores()["event"]
        self.assertAlmostEqual(zero.normalized, 0.5, places=6)

    def test_rank_scorecards_full(self) -> None:
        data = {f"S{i}": _make_df(seed=i, drift=0.001 * i) for i in range(5)}
        res = rank_scorecards(
            data,
            include_full=True,
            ai_probs={f"S{i}": 0.3 + 0.1 * i for i in range(5)},
            news_sentiments={f"S{i}": 0.4 + 0.08 * i for i in range(5)},
            position_ratios={f"S{i}": 1.0 + 0.4 * i for i in range(5)},
            basis_ranks={f"S{i}": 0.2 + 0.12 * i for i in range(5)},
            event_impacts={f"S{i}": -0.5 + 0.25 * i for i in range(5)},
        )
        self.assertEqual(len(res), 5)
        # 降序
        for i in range(len(res) - 1):
            self.assertGreaterEqual(res[i]["composite"], res[i + 1]["composite"])
        # 最强 S4（信号全多）应在前
        self.assertEqual(res[0]["symbol"], "S4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
