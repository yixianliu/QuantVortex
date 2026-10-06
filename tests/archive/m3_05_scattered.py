"""M3-05 验证：真·Walk-Forward 接入生产。

验收点（对应 UPGRADE_PLAN_V5 M3-05）：
  ① evaluate(use_walk_forward=True) 走 WalkForward.folds_plan() 真滚动，不再退化为 85/15；
  ② OOS 汇总复用 fold 内已训模型（trainer 调用次数 == fold 数，不再翻倍）；
  ③ 命中率阈值改为 median(train_returns)（回归目标）；
  ④ 折叠因果性自检：train/test 严格不重叠、各折 test 两两不相交。
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from futures_quant.ai.validation import WalkForward, WalkForwardResult  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


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


print("\n测试 ①: 折叠方案因果性（train/test 严格不重叠、test 两两不相交）")
wf = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
plan = wf.folds_plan(400)
check("折数 >= 3", len(plan) >= 3, f"n_folds={len(plan)}")
ok_order = all(p["train_start"] < p["train_end"] <= p["test_start"] < p["test_end"] for p in plan)
check("每折 train 严格早于 test", ok_order, str(plan[:2]))
disjoint = all(plan[i]["test_end"] <= plan[i + 1]["test_start"] for i in range(len(plan) - 1))
check("各折 test 区间两两不相交", disjoint)

print("\n测试 ②: validate_plan 能拦截有泄漏的折叠方案")
try:
    WalkForward.validate_plan([
        {"fold": 0, "train_start": 0, "train_end": 100, "test_start": 100, "test_end": 140},
        {"fold": 1, "train_start": 0, "train_end": 110, "test_start": 110, "test_end": 150},
    ])
    check("step < test_len（测试段重叠）被拦截", False, "未抛异常")
except ValueError as e:
    check("step < test_len（测试段重叠）被拦截", True, str(e)[:70])
try:
    WalkForward.validate_plan([
        {"fold": 0, "train_start": 0, "train_end": 120, "test_start": 100, "test_end": 140},
    ])
    check("train_end > test_start（因果倒置）被拦截", False, "未抛异常")
except ValueError:
    check("train_end > test_start（因果倒置）被拦截", True)

print("\n测试 ③: OOS 汇总复用 fold 内已训模型（训练次数 == 折数，不再翻倍）")
calls = {"n": 0}


def _trainer(X, y):
    calls["n"] += 1
    w = np.linalg.lstsq(X, y, rcond=None)[0]
    return {"w": w}


def _predictor(model, X):
    return X @ model["w"]


rng = np.random.default_rng(0)
X = rng.normal(size=(400, 3))
y = X @ np.array([0.5, -0.3, 0.1]) + rng.normal(0, 0.05, 400)
wf2 = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
wf2.add_model("lin", _trainer, _predictor)
res: WalkForwardResult = wf2.run(X, y)
n_folds = len(res.models["lin"])
check("trainer 调用次数 == 折数（旧的重复训练已删除）", calls["n"] == n_folds,
      f"calls={calls['n']}, folds={n_folds}")
check("OOS 样本数 == 各折 test 长度之和",
      res.oos["lin"]["n"] == sum(f.n_test for f in res.models["lin"]),
      f"{res.oos['lin']['n']} vs {sum(f.n_test for f in res.models['lin'])}")

print("\n测试 ④: 命中率阈值 = median(train_returns)（回归目标不再用 0.5）")
# 构造量级远离 0.5 的回归目标：旧阈值 0.5 会把所有样本判为「看多」，命中率恒为 1.0
y_big = 100.0 + rng.normal(0, 1.0, 400)
wf3 = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
wf3.add_model("lin", _trainer, _predictor)
res3 = wf3.run(X, y_big)
thrs = [f.hit_threshold for f in res3.models["lin"]]
check("Fold.hit_threshold 已记录", all(t is not None for t in thrs), str([round(t, 3) for t in thrs]))
check("阈值取训练段中位数（≈100，非 0.5）", all(abs(t - 100.0) < 1.0 for t in thrs),
      f"thr={[round(t, 3) for t in thrs]}")
hits = [f.hit_rate for f in res3.models["lin"]]
check("命中率不再退化为常数 1.0", not all(abs(h - 1.0) < 1e-12 for h in hits),
      f"hit={[round(h, 3) for h in hits]}")

# 二分类目标仍用 0.5
y_bin = (rng.normal(size=400) > 0).astype(float)
wf4 = WalkForward(train_len=120, test_len=40, step=40, min_folds=3)
wf4.add_model("lin", _trainer, _predictor)
res4 = wf4.run(X, y_bin)
check("二分类目标阈值仍为 0.5", all(abs(f.hit_threshold - 0.5) < 1e-12 for f in res4.models["lin"]))

print("\n测试 ⑤: summary() 可渲染")
s = res.summary()
check("summary 非空且含 MAE", "MAE=" in s, s.replace("\n", " | ")[:80])

print("\n测试 ⑥: predictor.evaluate(use_walk_forward=True) 真滚动")
from futures_quant.ai.predictor import FuturesPredictor, _walk_forward_plan  # noqa: E402

plan2 = _walk_forward_plan(600)
check("_walk_forward_plan(600) 产出 >= 3 折", plan2 is not None and len(plan2) >= 3,
      f"n={len(plan2) if plan2 else 0}")
check("_walk_forward_plan(50) 返回 None（样本不足，回退 80/20）", _walk_forward_plan(50) is None)

df = _make_df(300, seed=7)
P = FuturesPredictor()
r = P.evaluate(df, horizon=1, seq_len=20, epochs=2, extended_features=False,
               use_ensemble=False, symbol="WF", period="D", use_walk_forward=True)
check("evaluate 未返回 error", "error" not in r, str(r.get("error", "")))
check("walk_forward=True（真的滚起来了）", r.get("walk_forward") is True)
check("n_folds >= 3", r.get("n_folds", 0) >= 3, f"n_folds={r.get('n_folds')}")
folds = r.get("folds", [])
check("folds 明细已返回", len(folds) == r.get("n_folds"))
check("每折 train/test 不重叠", all(f["train"][1] <= f["test"][0] for f in folds),
      str([(f["train"], f["test"]) for f in folds]))
check("各折 test 两两不相交",
      all(folds[i]["test"][1] <= folds[i + 1]["test"][0] for i in range(len(folds) - 1)))
check("val_samples == 各折 n_test 之和",
      r.get("val_samples") == sum(f["n_test"] for f in folds),
      f"{r.get('val_samples')} vs {sum(f['n_test'] for f in folds)}")
check("指标均为有限值",
      all(np.isfinite(r.get(k, np.nan)) for k in
          ("direction_acc", "mae", "rmse", "r_squared", "sharpe_ratio", "max_drawdown")),
      f"acc={r.get('direction_acc'):.3f}, mae={r.get('mae'):.5f}")

print("\n测试 ⑦: use_walk_forward=False 仍走原 80/20 路径（行为不变）")
r2 = P.evaluate(df, horizon=1, seq_len=20, epochs=2, extended_features=False,
                use_ensemble=False, symbol="WF2", period="D", use_walk_forward=False)
check("walk_forward=False", r2.get("walk_forward") is False)
check("n_folds=0", r2.get("n_folds") == 0)
check("旧路径指标有限", np.isfinite(r2.get("mae", np.nan)), f"mae={r2.get('mae'):.5f}")
check("旧路径 val_samples 约占 20%", 0.15 <= r2["val_samples"] / (r2["val_samples"] + r2["train_samples"]) <= 0.25)

print(f"\n{'=' * 60}")
print(f"M3-05 验证结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("test_m3_05.py 全绿")
