"""M5.7 Walk-Forward 滚动验证验收测试。

覆盖：
- 折叠计划因果性（训练区间严格在测试区间之前，无未来函数）；
- 折叠数量与步长；
- 模型注册 + 运行；
- OOS 汇总指标一致性（拼接 OOS 段的 MAE/命中率）；
- min_folds 不足时抛错；
- 回归目标（非二分类）hit_rate 为 None。
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import numpy as np
from ai.validation import WalkForward


def _mean_model(train: np.ndarray, target: np.ndarray):
    """玩具模型：用训练集均值作为预测（无状态），验证框架正确性。"""
    val = float(np.mean(target))
    return {"mean": val}


def _mean_predict(model, x_test: np.ndarray) -> np.ndarray:
    return np.full(x_test.shape[0], model["mean"])


def test_folds_plan_causal():
    wf = WalkForward(train_len=252, test_len=63, step=63, min_folds=3)
    n = 252 + 63 * 5  # 5 折
    plan = wf.folds_plan(n)
    assert len(plan) == 5
    for p in plan:
        # 因果：训练区间结束 == 测试区间开始
        assert p["train_end"] == p["test_start"]
        assert p["train_start"] >= 0
        assert p["test_end"] <= n
    # 步长正确：相邻折 test_start 相差 step
    for a, b in zip(plan, plan[1:]):
        assert b["test_start"] - a["test_start"] == 63
    print("folds_plan 因果性 OK")


def test_run_with_binary():
    np.random.seed(0)
    n = 252 + 63 * 4
    X = np.random.randn(n, 8)
    y = (X[:, 0] + 0.5 > 0).astype(int)  # 二分类方向标签
    wf = WalkForward(train_len=252, test_len=63, step=63, min_folds=3)
    wf.add_model("mean", _mean_model, _mean_predict)
    res = wf.run(X, y)
    # 各模型至少 min_folds 折
    assert len(res.models["mean"]) >= 3
    # OOS 汇总存在且 n 合理
    assert "mean" in res.oos
    assert res.oos["mean"]["n"] > 0
    assert 0.0 <= res.oos["mean"]["hit_rate"] <= 1.0
    assert res.oos["mean"]["mae"] >= 0.0
    print("binary run OK:", res.summary())


def test_regression_hit_none():
    np.random.seed(1)
    n = 252 + 63 * 3
    X = np.random.randn(n, 4)
    y = np.random.randn(n)  # 回归目标
    wf = WalkForward(train_len=252, test_len=63, step=63, min_folds=2)
    wf.add_model("mean", _mean_model, _mean_predict)
    res = wf.run(X, y)
    assert res.oos["mean"]["hit_rate"] is None
    print("regression hit_rate None OK")


def test_min_folds_error():
    wf = WalkForward(train_len=252, test_len=63, step=63, min_folds=10)
    try:
        wf.folds_plan(252 + 63 * 2)  # 仅 2 折，低于 min_folds=10
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        print("min_folds 不足正确抛错 OK")


def test_invalid_params():
    for bad in [dict(train_len=0), dict(test_len=-1), dict(step=0)]:
        try:
            WalkForward(**bad)
            raise AssertionError(f"非法参数 {bad} 应抛 ValueError")
        except ValueError:
            pass
    print("非法参数正确抛错 OK")


if __name__ == "__main__":
    test_folds_plan_causal()
    test_run_with_binary()
    test_regression_hit_none()
    test_min_folds_error()
    test_invalid_params()
    print("test_walk_forward.py 全绿")
