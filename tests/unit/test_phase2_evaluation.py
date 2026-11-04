"""第三轮 A · P0 回归测试：统一命中率口径 + 预测信号净值 + GA 适应度/缓存键。

覆盖点：
1. 命中率必须与基准率、样本量、Wilson 置信区间一起报告；
2. 中性带样本不计入命中率；
3. 预测信号 → 真实下一根收益 − 手续费/滑点，夏普不得直接用预测值；
4. Walk-Forward 折必须严格样本外，且 folds 标注真实训练/测试时间；
5. GA 适应度不得奖励负夏普（移除 abs(sharpe)）；
6. GA 缓存键必须含品种 / IS 区间 / 周期 / 数据版本 / 基因参数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from futures_quant.ai.evaluation import (
    directional_hit_rate, estimate_cost_rate, net_performance,
    probability_hit_rate, probability_is_hit, wilson_interval,
)


def test_hit_rate_reports_base_rate_and_ci():
    # 10 个样本：8 涨 2 跌（基准率 0.8），预测全做多 → 命中 8/10
    actual = np.array([1, 2, 3, 4, 5, 6, 7, 8, -1, -2], dtype=float) / 100.0
    pred = np.full(10, 0.01)
    r = directional_hit_rate(pred, actual)
    assert r["n"] == 10
    assert r["n_hit"] == 8
    assert r["hit_rate"] == pytest.approx(0.8)
    assert r["base_rate"] == pytest.approx(0.8)
    assert r["edge"] == pytest.approx(0.0)
    assert r["ci_low"] < 0.8 < r["ci_high"]
    # 与基准率持平 → 不显著（不能宣称有技能）
    assert r["significant"] is False


def test_hit_rate_neutral_band_excluded():
    actual = np.array([0.01, -0.02, 0.03, -0.01], dtype=float)
    pred = np.array([0.0, 0.001, 0.02, -0.005], dtype=float)
    r = directional_hit_rate(pred, actual, neutral_band=0.002)
    # |pred| <= 0.002 的 3 个样本（0.0/0.001/-0.005? 最后 |-0.005|>0.002 保留）
    assert r["n"] == 2
    assert r["n_neutral"] == 2
    assert r["n"] + r["n_neutral"] == 4


def test_hit_rate_empty_is_safe():
    r = directional_hit_rate([], [])
    assert r["n"] == 0
    assert r["hit_rate"] == 0.0
    assert r["significant"] is False


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(60, 100)
    assert 0.5 < lo < 0.6
    assert 0.6 < hi < 0.7
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_probability_hit_rate_matches_manual():
    p_up = [0.7, 0.6, 0.4, 0.3, 0.55]
    actual_up = [1, 0, 0, 1, 1]
    r = probability_hit_rate(p_up, actual_up, threshold=0.5)
    # 预测 [多,多,空,空,多]，实际 [涨,跌,跌,涨,涨] → 命中 1,3,5 = 3/5
    assert r["n_hit"] == 3
    assert r["hit_rate"] == pytest.approx(0.6)
    assert r["base_rate"] == pytest.approx(0.6)   # 3 涨 2 跌 → 基准 0.6
    assert r["significant"] is False
    assert probability_is_hit(0.7, 1) == 1
    assert probability_is_hit(0.4, 1) == 0


def test_net_performance_charges_costs_and_uses_real_returns():
    actual = np.array([0.010, -0.004, 0.012, 0.006, 0.003])
    pred = np.full(5, 0.01)          # 永远做多
    cost = estimate_cost_rate(4000.0, multiplier=10, commission_per_lot=3,
                              slippage_ticks=1, min_price_tick=1)
    gross = net_performance(pred, actual, cost_rate=0.0)
    net = net_performance(pred, actual, cost_rate=cost)
    assert net["total_return"] < gross["total_return"]
    assert net["total_cost"] > 0
    # 净值应为逐样本复利，且毛净差主要来自单次建仓成本
    assert abs(net["total_return"] - float(net["equity_curve"][-1] - 1)) < 1e-6
    assert gross["total_return"] - net["total_return"] > 0.9 * float(cost)
    # 毛口径夏普 > 净口径（成本压低均值、抬高波动）
    assert gross["sharpe"] > net["sharpe"] > 0


def test_net_performance_short_direction_and_turnover():
    actual = np.array([-0.01, 0.01, -0.02, 0.02])
    pred = np.array([-0.1, 0.1, -0.1, 0.1])   # 方向全对
    r = net_performance(pred, actual, cost_rate=0.0003)
    # 仓位 [-1,+1,-1,+1]：首次建仓 1 + 三次反手各 2 = 7 次换手
    assert r["turnover"] == pytest.approx(7.0)
    assert r["total_return_gross"] == pytest.approx(
        np.prod(1 + np.abs(actual)) - 1, rel=1e-6)


def _make_df(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 4000 + np.cumsum(rng.normal(0, 8, n))
    return pd.DataFrame({
        "datetime": idx,
        "open": close + rng.normal(0, 3, n),
        "high": close + np.abs(rng.normal(0, 6, n)),
        "low": close - np.abs(rng.normal(0, 6, n)),
        "close": close,
        "volume": rng.integers(1000, 5000, n).astype(float),
        "open_interest": rng.integers(10000, 50000, n).astype(float),
    })


def test_walk_forward_is_true_oos_and_metrics_use_net_equity():
    from futures_quant.ai.predictor import FuturesPredictor
    df = _make_df(500)
    p = FuturesPredictor()
    core = p._evaluate_core(df, epochs=4, seq_len=10, symbol="rb.SHFE",
                            period="D", use_walk_forward=True)
    assert "error" not in core
    m = core["metrics"]
    assert m["walk_forward"] is True
    assert m["n_folds"] >= 3
    folds = m["folds"]
    for f in folds:
        # train_end 为开区间，test_start 可取 train_end；时间轴上必须严格不重叠
        assert f["test"][0] >= f["train"][1]
        assert f["train_time"][0] != "" and f["test_time"][0] != ""
        assert (pd.to_datetime(f["test_time"][0])
                > pd.to_datetime(f["train_time"][1]))
    # folds 的测试段互不重叠
    segs = sorted([tuple(f["test"]) for f in folds])
    for a, b in zip(segs, segs[1:]):
        assert a[1] <= b[0]

    # 新口径：夏普来自扣费净值，不等于旧口径「val_preds 当收益」
    val = np.asarray(core["val_preds"], dtype=float)
    old_sharpe = (np.mean(val - 0.02 / 252) / np.std(val) * np.sqrt(252)
                  if np.std(val) > 1e-12 else 0.0)
    assert m["sharpe_ratio"] != pytest.approx(old_sharpe, rel=1e-3)
    assert "sharpe_gross" in m and "total_cost" in m
    assert m["direction_base_rate"] > 0
    assert 0 <= m["direction_acc"] <= 1
    assert m["direction_acc_ci_low"] <= m["direction_acc"] <= m["direction_acc_ci_high"]


def test_features_are_causal_no_future_bars():
    """未来 bar 的扰动不得改变过去任何一行的特征（防未来函数）。"""
    from futures_quant.ai.predictor import FuturesPredictor
    df = _make_df(320)
    p1 = FuturesPredictor()
    _ind1, f1 = p1._features(df, symbol="rb.TEST", period="D")

    cut = 200
    df2 = df.copy()
    for col in ("open", "high", "low", "close", "volume", "open_interest"):
        df2.loc[cut + 1:, col] = df2.loc[cut + 1:, col] * 1.5
    p2 = FuturesPredictor()
    _ind2, f2 = p2._features(df2, symbol="rb.TEST2", period="D")

    a = f1.iloc[:cut + 1].to_numpy(dtype=float)
    b = f2.iloc[:cut + 1].to_numpy(dtype=float)
    assert np.allclose(a, b, equal_nan=True, rtol=1e-9, atol=1e-9)


def test_fitness_does_not_reward_negative_sharpe():
    from futures_quant.strategy.auto_evolve import fitness
    base = {"total_return": 0.2, "max_drawdown": 0.1, "win_rate": 0.5,
            "num_closing_trades": 30, "avg_win": 0.02, "avg_loss": -0.01,
            "profit_factor": 1.5, "max_consecutive_loss": 2}
    f_pos = fitness({**base, "sharpe": 2.0})
    f_neg = fitness({**base, "sharpe": -2.0})
    assert f_pos > f_neg
    assert f_neg <= fitness({**base, "sharpe": 0.0})


class _DummyFeed:
    """最小行情源：返回固定日线，供 GA 缓存键测试。"""

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def get_history(self, symbol, start, end, period="D", limit=0):
        from futures_quant.data.base import attach_provenance
        return attach_provenance(self._df.copy(), "csv", as_of=self._df["datetime"].iloc[-1])


def test_ga_cache_key_includes_symbol_range_and_data_version():
    from futures_quant.strategy.auto_evolve import EvolutionEngine
    df = _make_df(300)
    eng = EvolutionEngine(_DummyFeed(df), ["rb.SHFE"], "2020-01-01", "2021-12-31", "D")
    k1 = eng._cache_key("sigA", "rb.SHFE")
    k2 = eng._cache_key("sigA", "i.DCE")
    k3 = eng._cache_key("sigB", "rb.SHFE")
    assert "rb.SHFE" in k1 and "rb.SHFE" in k3
    assert k1 != k2                      # 品种不同
    assert k1 != k3                      # 参数不同
    # IS 区间必须早于 end（不含 OOS）
    fs, fe = eng._fit_range("rb.SHFE")
    assert fe < "2021-12-31"
    assert k1.split("|")[1] == fs and k1.split("|")[2] == fe
