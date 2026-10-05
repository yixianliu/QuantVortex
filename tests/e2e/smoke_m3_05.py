"""M3-05 真·Walk-Forward 验证接入生产 - E2E smoke 验收。

DoD:
1) `WalkForward.folds_plan(n)` 返回 fold 数 ≥3 且 train/test 区间严格不重叠
   （validate_plan 自检）。
2) `use_walk_forward=True` 下 `evaluate` 走真滚动（不再退化为 85/15）。
3) OOS 汇总**复用 fold 内已训模型**（不再重训）。
4) 命中率阈值 = 训练段收益中位数 `median(y_train)`（回归目标）。

运行方式:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_05.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QT_QPA_PLATFORM_DEFAULT = os.environ.get("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_QPA_PLATFORM"] = QT_QPA_PLATFORM_DEFAULT


def _make_df(n: int = 400, seed: int = 20261002) -> pd.DataFrame:
    """构造 400 根 K 线的合成行情。"""
    rng = np.random.default_rng(seed)
    trend = 100.0 + np.linspace(0, 20, n)
    close = trend + rng.normal(0, 0.5, n).cumsum() * 0.1
    open_ = close + rng.normal(0, 0.3, n)
    high = np.maximum(close, open_) + np.abs(rng.normal(0, 0.4, n))
    low = np.minimum(close, open_) - np.abs(rng.normal(0, 0.4, n))
    volume = rng.integers(500_000, 2_000_000, n).astype(float)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ============================================================
# 测试用例
# ============================================================

def test_1_folds_plan_causal_and_at_least_3() -> None:
    """folds_plan 返回 ≥3 折，且 train/test 区间严格不重叠（validate_plan 自检通过）。"""
    from futures_quant.ai.validation import WalkForward

    # 使用较小窗口，让 400 样本能跑出多折
    wf = WalkForward(train_len=100, test_len=25, step=25, min_folds=3)
    plan = wf.folds_plan(400)

    assert len(plan) >= 3, f"应至少 3 折，实际 {len(plan)}"

    # 检查因果性
    for p in plan:
        # train 区间严格早于 test 区间
        assert p["train_start"] < p["train_end"] <= p["test_start"] < p["test_end"], (
            f"折叠 {p['fold']} 区间不满足因果顺序：{p}"
        )
        # train 严格早于 test 起始（无重叠）
        assert p["train_end"] <= p["test_start"], (
            f"折叠 {p['fold']} train_end={p['train_end']} > test_start={p['test_start']}"
        )

    # 检查相邻折 test 区间不重叠（step >= test_len）
    for i in range(1, len(plan)):
        prev = plan[i - 1]
        cur = plan[i]
        assert cur["test_start"] >= prev["test_end"], (
            f"折叠 {i} test_start={cur['test_start']} 早于上一折 test_end={prev['test_end']}"
        )

    print(f"[1/5] PASS folds_plan 产出 {len(plan)} 折，因果性 + 无重叠自检通过")


def test_2_validate_plan_raises_on_overlap() -> None:
    """validate_plan 遇到重叠 fold 时抛 ValueError（不静默产出污染指标）。"""
    from futures_quant.ai.validation import WalkForward

    # 手动构造一个「test 重叠」的 plan
    bad_plan = [
        {"fold": 0, "train_start": 0, "train_end": 100, "test_start": 100, "test_end": 150},
        # 下一折 test_start=130 早于上一折 test_end=150，重叠！
        {"fold": 1, "train_start": 80, "train_end": 130, "test_start": 130, "test_end": 180},
    ]

    try:
        WalkForward.validate_plan(bad_plan)
    except ValueError as e:
        assert "重叠" in str(e) or "overlap" in str(e).lower(), (
            f"错误消息应提示重叠，实际：{e}"
        )
    else:
        raise AssertionError("重叠 fold 未抛 ValueError")

    # 因果顺序错乱的 plan 也应报错
    bad_causal = [
        {"fold": 0, "train_start": 0, "train_end": 100,
         "test_start": 90, "test_end": 150},  # test_start < train_end
    ]
    try:
        WalkForward.validate_plan(bad_causal)
    except ValueError:
        pass
    else:
        raise AssertionError("因果错乱未抛 ValueError")

    print("[2/5] PASS validate_plan 遇重叠 / 因果错乱均抛 ValueError")


def test_3_walk_forward_run_reuses_fold_models() -> None:
    """OOS 汇总复用 fold 内已训模型（trainer 只被调用 len(plan) 次，非 2×）。"""
    from futures_quant.ai.validation import WalkForward

    n_train_calls = 0

    def trainer(x_tr, y_tr):
        nonlocal n_train_calls
        n_train_calls += 1
        # 用简单线性模型：y_pred = mean(y_train)（占位，验证只调用次数）
        return {"mean": float(np.mean(y_tr))}

    def predictor(model, x_te):
        return np.full(x_te.shape[0], model["mean"])

    wf = WalkForward(train_len=50, test_len=25, step=25, min_folds=3)
    wf.add_model("linear", trainer, predictor)

    n = 200
    X = np.random.default_rng(0).standard_normal((n, 5))
    y = np.random.default_rng(1).standard_normal(n)

    result = wf.run(X, y)

    # trainer 应被调用 len(folds) 次（每折一次），而不是 2×len(folds)
    n_folds = len(result.models["linear"])
    assert n_train_calls == n_folds, (
        f"trainer 应被调用 {n_folds} 次（每折一次），实际 {n_train_calls} 次"
        f" —— 说明 OOS 汇总仍在重训"
    )
    print(f"[3/5] PASS OOS 汇总复用 fold 内模型（trainer 调用 {n_train_calls} 次 = fold 数）")


def test_4_hit_threshold_uses_train_median() -> None:
    """回归目标：hit_threshold = median(y_train)，不是 0.5。"""
    from futures_quant.ai.validation import WalkForward

    def trainer(x_tr, y_tr):
        return {"mean": float(np.mean(y_tr))}

    def predictor(model, x_te):
        return np.full(x_te.shape[0], model["mean"])

    wf = WalkForward(train_len=50, test_len=25, step=25, min_folds=3)
    wf.add_model("linear", trainer, predictor)

    # 构造非对称回归目标（如 y ~ N(2, 1)）
    rng = np.random.default_rng(2)
    n = 200
    X = rng.standard_normal((n, 5))
    y = rng.standard_normal(n) + 2.0  # 均值约 2.0，中位数应远离 0.5

    result = wf.run(X, y)
    folds = result.models["linear"]

    # 所有折的 hit_threshold 应接近 y 中位数（约 2.0），而非 0.5
    for f in folds:
        assert f.hit_threshold is not None
        # 中位数应在 1.5 ~ 2.5 之间（远大于 0.5）
        assert f.hit_threshold > 1.0, (
            f"fold {f.fold} 的 hit_threshold={f.hit_threshold}，"
            f"应接近 median(y_train)≈2.0，而非 0.5"
        )

    # 至少 1 折的阈值明显偏离 0.5
    assert any(f.hit_threshold != 0.5 for f in folds), (
        "所有折的 hit_threshold 都是 0.5 —— 说明未走训练段中位数逻辑"
    )

    sample_thr = folds[0].hit_threshold
    print(f"[4/5] PASS hit_threshold 用训练段中位数（fold0={sample_thr:.4f}，非 0.5）")


def test_5_predictor_evaluate_walk_forward_flag() -> None:
    """`FuturesPredictor.evaluate(use_walk_forward=True)` 返回 `walk_forward=True` 且 fold 数 ≥3。"""
    from futures_quant.ai.predictor import FuturesPredictor

    df = _make_df(400)
    pred = FuturesPredictor()

    # 用较短的 seq_len 让模型能跑起来
    result = pred.evaluate(
        df, horizon=1, seq_len=10, epochs=3,
        extended_features=False, use_ensemble=False,
        symbol="WF_SMOKE", period="D",
        use_walk_forward=True,
    )

    # 应走真·Walk-Forward
    assert result.get("walk_forward") is True, (
        f"use_walk_forward=True 但返回 walk_forward={result.get('walk_forward')}，"
        "说明回退到固定切分"
    )
    n_folds = result.get("n_folds", 0)
    assert n_folds >= 3, (
        f"walk-forward 应产出 ≥3 折，实际 n_folds={n_folds}"
    )
    print(f"[5/5] PASS evaluate 走真·Walk-Forward（walk_forward=True, n_folds={n_folds}）")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)

    tests = [
        test_1_folds_plan_causal_and_at_least_3,
        test_2_validate_plan_raises_on_overlap,
        test_3_walk_forward_run_reuses_fold_models,
        test_4_hit_threshold_uses_train_median,
        test_5_predictor_evaluate_walk_forward_flag,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {t.__name__}: {exc!r}")

    total = len(tests)
    passed = total - failed
    print(f"\n=== M3-05 smoke: {passed}/{total} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
