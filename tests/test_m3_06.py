"""M3-06 验证：修复多模型对比名不副实。

验收点（对应 UPGRADE_PLAN_V5 M3-06）：
  ① tcn.fit() 实装：卷积输出不再恒 0，训练后 loss 下降；
  ② ts_transformer 补 self.epochs（装了 torch 不再 AttributeError），无 torch 明确不可用；
  ③ boosting：np.mean(weights=) → np.average；_fit_tree 做真实阈值分裂；
  ④ MultiModelComparator 的 tcn / gbm 分支真正调用对应模型（force_ridge 仅对 ridge 生效）；
  ⑤ 4 个模型在同一 df 上的 MAE 不全相等；对比 CSV 中数值有差异。
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


def _make_df(n=420, seed=3, base=3500.0):
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
        index=pd.date_range("2022-01-03", periods=n, freq="D"),
    )


print("\n测试 ①: TCN 卷积不再恒为 0")
from futures_quant.ai.tcn import TemporalConvNet  # noqa: E402

net = TemporalConvNet(num_inputs=5, num_channels=[8, 8], kernel_size=2, seed=7)
x = np.random.default_rng(0).standard_normal((20, 5))
h = net._hidden(x)
check("卷积隐状态非全零（旧实现恒 0）", float(np.abs(h).sum()) > 1e-9,
      f"sum|h|={float(np.abs(h).sum()):.4f}")
check("隐状态形状正确 (seq_len, last_channel)", h.shape == (20, 8), str(h.shape))
# 因果性：把序列后半段改成完全不同的值，前半段输出不应改变
x2 = x.copy()
x2[10:] = 999.0
h2 = net._hidden(x2)
check("因果性：改动 t>=10 不影响 t<10 的输出（无未来函数）",
      np.allclose(h[:9], h2[:9], atol=1e-12),
      f"max|Δ|={float(np.max(np.abs(h[:9] - h2[:9]))):.3e}")

print("\n测试 ②: TCN.fit() 真的训练（loss 下降 + 预测非恒值）")
rng = np.random.default_rng(1)
X = rng.standard_normal((300, 20, 5))
# 让目标与「最后一个时间步的第 0 维」强相关，验证模型确实学到了东西
y = 0.8 * X[:, -1, 0] - 0.3 * X[:, -1, 1] + rng.normal(0, 0.05, 300)
net2 = TemporalConvNet(num_inputs=5, num_channels=[16, 16], kernel_size=2, seed=7)
pred_before = net2.predict(X)
net2.fit(X, y, epochs=10, lr=0.01, batch_size=32)
pred_after = net2.predict(X)
check("fit 后 loss_history 已记录", len(net2.loss_history_) >= 2,
      f"{[round(v, 5) for v in net2.loss_history_]}")
check("loss 末值 < 初值（训练发生）",
      net2.loss_history_[-1] < net2.loss_history_[0],
      f"{net2.loss_history_[0]:.5f} → {net2.loss_history_[-1]:.5f}")
mae_after = float(np.mean(np.abs(pred_after - y)))
mae_base = float(np.mean(np.abs(y - y.mean())))
check("fit 后 MAE 优于「恒预测均值」基线", mae_after < mae_base,
      f"mae={mae_after:.4f} vs base={mae_base:.4f}")
check("预测非常数（有区分度）", float(np.std(pred_after)) > 1e-6,
      f"std={float(np.std(pred_after)):.4f}")
check("fit 前预测接近随机常数（对比用）", float(np.std(pred_before)) < mae_base,
      f"std_before={float(np.std(pred_before)):.4f}")

print("\n测试 ③: boosting —— 加权均值与真实阈值分裂")
from futures_quant.ai.boosting import (  # noqa: E402
    ToyGradientBoostingRegressor, ToyGradientBoostingClassifier,
    GradientBoostingModel, XGBOOST_AVAILABLE, LIGHTGBM_AVAILABLE,
)

# ③-a np.mean(weights=) 已不存在
import inspect  # noqa: E402
src = inspect.getsource(ToyGradientBoostingRegressor) + inspect.getsource(ToyGradientBoostingClassifier)
check("源码中已无 np.mean(..., weights=)", "np.mean(y, weights" not in src
      and "np.mean(y_binary, weights" not in src)
# ③-b 加权均值正确
w = np.array([1.0, 1.0, 1.0, 9.0])
yv = np.array([0.0, 0.0, 0.0, 10.0])
got = ToyGradientBoostingRegressor._wmean(yv, w)
check("_wmean 加权均值正确（期望 7.5）", abs(got - 7.5) < 1e-12, f"{got}")
check("_wmean 无权重时退化普通均值（期望 2.5）",
      abs(ToyGradientBoostingRegressor._wmean(yv, None) - 2.5) < 1e-12)

# ③-c _fit_tree 做真实分裂（左/右叶值不同）
Xs = np.column_stack([np.r_[np.zeros(50), np.ones(50) + 5.0],
                      np.random.default_rng(0).standard_normal(100)])
ys = np.where(Xs[:, 0] < 2.0, -10.0, 10.0)
toy = ToyGradientBoostingRegressor(n_estimators=3, learning_rate=0.5)
tree = toy._fit_tree(Xs, ys, None)
pv = tree(Xs)
check("_fit_tree 产生两个不同的叶值（不再是常数）", len(np.unique(np.round(pv, 9))) >= 2,
      f"unique={np.unique(np.round(pv, 9))}")

# ③-d GBDT 整体能学到分段结构
gbm = ToyGradientBoostingRegressor(n_estimators=30, learning_rate=0.3)
gbm.fit(Xs, ys)
pg = gbm.predict(Xs)
check("GBDT 拟合分段目标的 MAE 明显优于常数基线",
      float(np.mean(np.abs(pg - ys))) < 0.5 * float(np.mean(np.abs(ys - ys.mean()))),
      f"mae={float(np.mean(np.abs(pg - ys))):.3f} vs base={float(np.mean(np.abs(ys - ys.mean()))):.3f}")

# ③-e 封装类（无 xgboost/lightgbm → 走玩具实现）可训练
gm = GradientBoostingModel(task="regression", n_estimators=20, max_depth=1,
                           learning_rate=0.3, random_state=7)
gm.fit(Xs, ys)
pgm = np.asarray(gm.predict(Xs), dtype=float).reshape(-1)
check("GradientBoostingModel(regression) 可训练且输出有限",
      len(pgm) == len(ys) and np.all(np.isfinite(pgm)))
gc = GradientBoostingModel(task="classification", n_estimators=10, max_depth=1,
                           learning_rate=0.3, random_state=7)
yc = (ys > 0).astype(int)
gc.fit(Xs, yc)
check("GradientBoostingModel(classification) 可训练",
      len(np.asarray(gc.predict(Xs))) == len(yc))
print(f"     （xgboost={XGBOOST_AVAILABLE}, lightgbm={LIGHTGBM_AVAILABLE} → "
      f"{'第三方库' if (XGBOOST_AVAILABLE or LIGHTGBM_AVAILABLE) else '玩具实现'}）")

print("\n测试 ④: ts_transformer 补 self.epochs + 无 torch 明确不可用")
from futures_quant.ai.ts_transformer import TSWrapper, TORCH_AVAILABLE  # noqa: E402

w_ = TSWrapper(feature_size=5, seq_len=20, epochs=7, lr=0.002)
check("TSWrapper.epochs 已保存（旧实现漏赋值）", getattr(w_, "epochs", None) == 7)
check("TSWrapper.lr 已保存", getattr(w_, "lr", None) is not None)
w_.fit(np.zeros((4, 20, 5)), np.zeros(4))
if TORCH_AVAILABLE:
    check("有 torch 时 fit 不抛错", True)
else:
    check("无 torch 时 fit 标记 available=False（不再静默恒 0）",
          getattr(w_, "available", None) is False)
    check("无 torch 时 predict 仍返回 0 但已显式标注不可用",
          np.all(np.asarray(w_.predict(np.zeros((3, 20, 5)))) == 0.0))

print("\n测试 ⑤: MultiModelComparator 的 tcn / gbm 分支真调用")
from futures_quant.ai.calibration_replay import (  # noqa: E402
    MultiModelComparator, build_external_estimator,
)

est_tcn = build_external_estimator("tcn", epochs=10)
est_gbm = build_external_estimator("gbm")
est_tr = build_external_estimator("transformer")
est_zzz = build_external_estimator("no_such_model")
check("build_external_estimator('tcn') 返回 TCN 适配器",
      est_tcn is not None and type(est_tcn).__name__ == "_TCNEstimator")
check("build_external_estimator('gbm') 返回 GBM 适配器",
      est_gbm is not None and type(est_gbm).__name__ == "_GBMEstimator")
check("无 torch 时 transformer 判不可用（返回 None）",
      (est_tr is None) if not TORCH_AVAILABLE else (est_tr is not None),
      f"torch={TORCH_AVAILABLE}")
check("未知模型名返回 None", est_zzz is None)

from futures_quant.ai.predictor import FuturesPredictor  # noqa: E402

df = _make_df(420, seed=3)
preds = {}
for name in ("ridge", "lstm", "tcn", "gbm"):
    p = FuturesPredictor()
    if name == "ridge":
        p.fit(df, seq_len=20, epochs=6, force_ridge=True, extended_features=False,
              use_ensemble=False, symbol=f"M_{name}", period="D")
    elif name == "lstm":
        p.fit(df, seq_len=20, epochs=6, force_ridge=False, extended_features=False,
              use_ensemble=False, symbol=f"M_{name}", period="D")
    else:
        est = build_external_estimator(name, epochs=8)
        p.fit(df, seq_len=20, epochs=6, force_ridge=False, extended_features=False,
              use_ensemble=False, symbol=f"M_{name}", period="D", external_model=est)
    preds[name] = p
    if name in ("tcn", "gbm"):
        check(f"{name}: 生效的是外部模型而非 Ridge 回退", p.external_model is not None,
              f"external={type(p.external_model).__name__ if p.external_model else None}")

# 在同一 hold-out 序列上算 MAE
from futures_quant.ai.features import build_features  # noqa: E402

ind, F, names = build_features(df, extended=False, symbol="M6_CMP", period="D")
arr = F.values.astype(float)
y = ind["ret"].shift(-1).values.astype(float)
seq_len = 20
Xs3 = np.array([arr[t - seq_len + 1:t + 1] for t in range(seq_len - 1, len(arr) - 1)])
Ys3 = np.nan_to_num(np.array([y[t] for t in range(seq_len - 1, len(arr) - 1)]))
cut = int(len(Xs3) * 0.8)
maes = {}
for name, p in preds.items():
    m = p._feat_mean
    s = p._feat_std
    if m is None:
        maes[name] = float("nan")
        continue
    pv = np.asarray(p._batch_pred((Xs3[cut:] - m) / s), dtype=float).reshape(-1)
    maes[name] = float(np.mean(np.abs(pv - Ys3[cut:])))
print("     各模型 hold-out MAE：" +
      "，".join(f"{k}={v:.6f}" for k, v in maes.items()))
uniq = {round(v, 9) for v in maes.values() if np.isfinite(v)}
check("4 个模型的 MAE 不全相等", len(uniq) >= 2, f"unique={sorted(uniq)}")
check("tcn 的 MAE 与 ridge 不同（证明不再是同一模型）",
      abs(maes["tcn"] - maes["ridge"]) > 1e-9,
      f"tcn={maes['tcn']:.6f}, ridge={maes['ridge']:.6f}")
check("gbm 的 MAE 与 ridge 不同（证明不再是同一模型）",
      abs(maes["gbm"] - maes["ridge"]) > 1e-9,
      f"gbm={maes['gbm']:.6f}, ridge={maes['ridge']:.6f}")

print("\n测试 ⑥: 对比 CSV 中 4 列数值有差异")
import tempfile  # noqa: E402

cmp_dir = tempfile.mkdtemp(prefix="m3_06_")
csv_path = os.path.join(cmp_dir, "cmp.csv")
comp = MultiModelComparator(out_dir=cmp_dir)
res = comp.run({"RB": df}, horizon=5, stride=60, max_samples=6,
               epochs=4, seq_len=20, use_ensemble=False,
               extended_features=False, out_csv=csv_path)
check("CSV 已生成", os.path.exists(csv_path), str(res.get("csv_path")))
if os.path.exists(csv_path):
    cdf = pd.read_csv(csv_path)
    models = sorted(cdf["model"].unique().tolist())
    check("CSV 含多个模型行", len(models) >= 2, str(models))
    if len(models) >= 2:
        # 同一时间点上不同模型的 p_up 应有差异
        pivot = cdf.pivot_table(index="ts", columns="model", values="p_up")
        vary = pivot.std(axis=1).max()
        check("同一时间点各模型 p_up 有差异", float(vary) > 1e-6, f"max std={float(vary):.4f}")
        mae_by_model = cdf.groupby("model")["abs_err"].mean()
        print("     各模型 abs_err 均值：" +
              "，".join(f"{k}={v:.4f}" for k, v in mae_by_model.items()))
        check("abs_err 不再恒等于行情自身波幅（与模型相关）",
              len({round(v, 6) for v in mae_by_model.values}) >= 2)
        check("CSV 含 pred_pct 列（新增，便于核对预测误差）",
              "pred_pct" in cdf.columns)

print(f"\n{'=' * 60}")
print(f"M3-06 验证结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("test_m3_06.py 全绿")
