"""M3-05 真·Walk-Forward 接入生产 —— pytest 形态。

由散落脚本 ``tests/test_m3_05.py``（模块级 ``PASS/FAIL`` 列表 + ``check(name,cond,detail)``
辅助 + 结尾 ``if FAIL: sys.exit(1)``，0 个 ``def test_*``）机械改写：
每段 ``check(...)`` 收敛成 ``assert cond, f"{name} — {detail}"``，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 原脚本 ② 的 ``try/except``-expects-``ValueError`` 改 ``pytest.raises(ValueError)``。
- 保持 RNG 消耗顺序与原脚本一致（``default_rng(0)`` → X → y → y_big → y_bin），
  否则 ④ 的阈值断言不再确定性成立。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from futures_quant.ai.validation import WalkForward, WalkForwardResult


def _make_df(n=300, seed=7, base=3500.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.009, n)
    close = base * np.exp(np.cumsum(r))
    return pd.DataFrame(
        {
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close * (1 + np.abs(rng.normal(0, 0.004, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.004, n))),
            "close": close,
            "volume": rng.integers(1000, 9000, n).astype(float),
        },
        index=pd.date_range("2023-01-02", periods=n, freq="D"),
    )


def _linear_trainer(X, y):
    import numpy as _np
    return {"w": _np.linalg.lstsq(X, y, rcond=None)[0]}


def _linear_predictor(model, X):
    return X @ model["w"]


@pytest.fixture(scope="module")
def shared_data():
    """保持 RNG 消耗顺序与原脚本一致：X, y, y_big, y_bin 一次生成，供 ③④ 复用。"""
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 3))
    y = X @ np.array([0.5, -0.3, 0.1]) + rng.normal(0, 0.05, 400)
    y_big = 100.0 + rng.normal(0, 1.0, 400)
    y_bin = (rng.normal(size=400) > 0).astype(float)
    return {"rng": rng, "X": X, "y": y, "y_big": y_big, "y_bin": y_bin}


def test_folds_plan_causality():
    """① 折叠方案因果性：train/test 严格不重叠、各折 test 两两不相交。"""
    wf = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
    plan = wf.folds_plan(400)
    assert len(plan) >= 3, f"折数 >= 3 — n_folds={len(plan)}"
    ok_order = all(p["train_start"] < p["train_end"] <= p["test_start"] < p["test_end"] for p in plan)
    assert ok_order, f"每折 train 严格早于 test — {plan[:2]}"
    disjoint = all(plan[i]["test_end"] <= plan[i + 1]["test_start"] for i in range(len(plan) - 1))
    assert disjoint, "各折 test 区间两两不相交"


def test_validate_plan_rejects_leakage():
    """② validate_plan 能拦截有泄漏的折叠方案（step<test_len 重叠 / 因果倒置）。"""
    with pytest.raises(ValueError):
        WalkForward.validate_plan([
            {"fold": 0, "train_start": 0, "train_end": 100, "test_start": 100, "test_end": 140},
            {"fold": 1, "train_start": 0, "train_end": 110, "test_start": 110, "test_end": 150},
        ])
    with pytest.raises(ValueError):
        WalkForward.validate_plan([
            {"fold": 0, "train_start": 0, "train_end": 120, "test_start": 100, "test_end": 140},
        ])


def test_trainer_calls_equal_fold_count(shared_data):
    """③ OOS 汇总复用 fold 内已训模型：trainer 调用次数 == 折数（不再翻倍）。"""
    calls = {"n": 0}

    def _trainer(X, y):
        calls["n"] += 1
        return _linear_trainer(X, y)

    X, y = shared_data["X"], shared_data["y"]
    wf = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
    wf.add_model("lin", _trainer, _linear_predictor)
    res: WalkForwardResult = wf.run(X, y)
    n_folds = len(res.models["lin"])
    assert calls["n"] == n_folds, f"trainer 调用次数 == 折数 — calls={calls['n']}, folds={n_folds}"
    assert res.oos["lin"]["n"] == sum(f.n_test for f in res.models["lin"]), \
        f"OOS 样本数 == 各折 test 长度之和 — {res.oos['lin']['n']}"


def test_hit_threshold_is_train_median(shared_data):
    """④ 命中率阈值 = median(train_returns)（回归目标不再用 0.5）；二分类仍用 0.5。"""
    X = shared_data["X"]
    y_big = shared_data["y_big"]
    y_bin = shared_data["y_bin"]

    wf3 = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
    wf3.add_model("lin", _linear_trainer, _linear_predictor)
    res3 = wf3.run(X, y_big)
    thrs = [f.hit_threshold for f in res3.models["lin"]]
    assert all(t is not None for t in thrs), f"Fold.hit_threshold 已记录 — {[round(t, 3) for t in thrs]}"
    assert all(abs(t - 100.0) < 1.0 for t in thrs), \
        f"阈值取训练段中位数（≈100，非 0.5） — thr={[round(t, 3) for t in thrs]}"
    hits = [f.hit_rate for f in res3.models["lin"]]
    assert not all(abs(h - 1.0) < 1e-12 for h in hits), \
        f"命中率不再退化为常数 1.0 — hit={[round(h, 3) for h in hits]}"

    wf4 = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
    wf4.add_model("lin", _linear_trainer, _linear_predictor)
    res4 = wf4.run(X, y_bin)
    assert all(abs(f.hit_threshold - 0.5) < 1e-12 for f in res4.models["lin"]), \
        "二分类目标阈值仍为 0.5"


def test_summary_renderable(shared_data):
    """⑤ summary() 可渲染且含 MAE。"""
    X, y = shared_data["X"], shared_data["y"]
    wf = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
    wf.add_model("lin", _linear_trainer, _linear_predictor)
    res = wf.run(X, y)
    s = res.summary()
    assert "MAE=" in s, f"summary 非空且含 MAE — {s.replace(chr(10), ' | ')[:80]}"


def test_predictor_walk_forward_true():
    """⑥ predictor.evaluate(use_walk_forward=True) 真滚动；_walk_forward_plan 边界正确。"""
    from futures_quant.ai.predictor import FuturesPredictor, _walk_forward_plan

    plan2 = _walk_forward_plan(600)
    assert plan2 is not None and len(plan2) >= 3, f"_walk_forward_plan(600) 产出 >= 3 折 — n={len(plan2) if plan2 else 0}"
    assert _walk_forward_plan(50) is None, "_walk_forward_plan(50) 返回 None（样本不足，回退 80/20）"

    df = _make_df(300, seed=7)
    P = FuturesPredictor()
    r = P.evaluate(df, horizon=1, seq_len=20, epochs=2, extended_features=False,
                  use_ensemble=False, symbol="WF", period="D", use_walk_forward=True)
    assert "error" not in r, f"evaluate 未返回 error — {r.get('error', '')}"
    assert r.get("walk_forward") is True, "walk_forward=True（真的滚起来了）"
    assert r.get("n_folds", 0) >= 3, f"n_folds >= 3 — n_folds={r.get('n_folds')}"
    folds = r.get("folds", [])
    assert len(folds) == r.get("n_folds"), "folds 明细已返回"
    assert all(f["train"][1] <= f["test"][0] for f in folds), \
        f"每折 train/test 不重叠 — {[(f['train'], f['test']) for f in folds]}"
    assert all(folds[i]["test"][1] <= folds[i + 1]["test"][0] for i in range(len(folds) - 1)), \
        "各折 test 两两不相交"
    assert r.get("val_samples") == sum(f["n_test"] for f in folds), \
        f"val_samples == 各折 n_test 之和 — {r.get('val_samples')}"
    assert all(np.isfinite(r.get(k, np.nan)) for k in
               ("direction_acc", "mae", "rmse", "r_squared", "sharpe_ratio", "max_drawdown")), \
        "指标均为有限值"


def test_walk_forward_false_unchanged():
    """⑦ use_walk_forward=False 仍走原 80/20 路径（行为不变）。"""
    from futures_quant.ai.predictor import FuturesPredictor

    df = _make_df(300, seed=7)
    P = FuturesPredictor()
    r2 = P.evaluate(df, horizon=1, seq_len=20, epochs=2, extended_features=False,
                   use_ensemble=False, symbol="WF2", period="D", use_walk_forward=False)
    assert r2.get("walk_forward") is False, "walk_forward=False"
    assert r2.get("n_folds") == 0, "n_folds=0"
    assert np.isfinite(r2.get("mae", np.nan)), f"旧路径指标有限 — mae={r2.get('mae'):.5f}"
    ratio = r2["val_samples"] / (r2["val_samples"] + r2["train_samples"])
    assert 0.15 <= ratio <= 0.25, f"旧路径 val_samples 约占 20% — ratio={ratio:.3f}"
