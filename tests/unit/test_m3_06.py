"""M3-06 修复多模型对比名不副实 —— pytest 形态。

由散落脚本 ``tests/test_m3_06.py``（模块级 ``PASS/FAIL`` 列表 + ``check(name,cond,detail)``
辅助 + 结尾 ``if FAIL: sys.exit(1)``，0 个 ``def test_*``）机械改写：
每段 ``check(...)`` 收敛成 ``assert cond, f"{name} — {detail}"``，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 保留分支依赖：无 torch 时 ts_transformer / transformer 走「显式不可用」分支，
  有 torch 时走「fit 不抛错」分支（与脚本 ``if TORCH_AVAILABLE`` 完全一致）。
"""
from __future__ import annotations

import inspect
import os
import tempfile

import numpy as np
import pandas as pd


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


def test_tcn_convolution_not_zero():
    """① TCN 卷积不再恒为 0，且因果性（改后半段不影响前半段输出）。"""
    from futures_quant.ai.tcn import TemporalConvNet

    net = TemporalConvNet(num_inputs=5, num_channels=[8, 8], kernel_size=2, seed=7)
    x = np.random.default_rng(0).standard_normal((20, 5))
    h = net._hidden(x)
    assert float(np.abs(h).sum()) > 1e-9, \
        f"卷积隐状态非全零（旧实现恒 0） — sum|h|={float(np.abs(h).sum()):.4f}"
    assert h.shape == (20, 8), f"隐状态形状正确 (seq_len, last_channel) — {h.shape}"
    x2 = x.copy()
    x2[10:] = 999.0
    h2 = net._hidden(x2)
    assert np.allclose(h[:9], h2[:9], atol=1e-12), \
        f"因果性：改动 t>=10 不影响 t<10 的输出（无未来函数） — max|Δ|={float(np.max(np.abs(h[:9] - h2[:9]))):.3e}"


def test_tcn_fit_learns():
    """② TCN.fit() 真的训练：loss 下降 + 预测优于均值基线 + 非恒值。"""
    from futures_quant.ai.tcn import TemporalConvNet

    rng = np.random.default_rng(1)
    X = rng.standard_normal((300, 20, 5))
    y = 0.8 * X[:, -1, 0] - 0.3 * X[:, -1, 1] + rng.normal(0, 0.05, 300)
    net2 = TemporalConvNet(num_inputs=5, num_channels=[16, 16], kernel_size=2, seed=7)
    pred_before = net2.predict(X)
    net2.fit(X, y, epochs=10, lr=0.01, batch_size=32)
    pred_after = net2.predict(X)
    assert len(net2.loss_history_) >= 2, \
        f"fit 后 loss_history 已记录 — {[round(v, 5) for v in net2.loss_history_]}"
    assert net2.loss_history_[-1] < net2.loss_history_[0], \
        f"loss 末值 < 初值（训练发生） — {net2.loss_history_[0]:.5f} → {net2.loss_history_[-1]:.5f}"
    mae_after = float(np.mean(np.abs(pred_after - y)))
    mae_base = float(np.mean(np.abs(y - y.mean())))
    assert mae_after < mae_base, f"fit 后 MAE 优于「恒预测均值」基线 — mae={mae_after:.4f} vs base={mae_base:.4f}"
    assert float(np.std(pred_after)) > 1e-6, f"预测非常数（有区分度） — std={float(np.std(pred_after)):.4f}"
    assert float(np.std(pred_before)) < mae_base, \
        f"fit 前预测接近随机常数（对比用） — std_before={float(np.std(pred_before)):.4f}"


def test_boosting_weighted_mean_and_split():
    """③ boosting：np.mean(weights=) 已换 np.average；_wmean 正确；_fit_tree 真实分裂；GBDT 学分段结构。"""
    from futures_quant.ai.boosting import (
        ToyGradientBoostingRegressor, ToyGradientBoostingClassifier,
        GradientBoostingModel, XGBOOST_AVAILABLE, LIGHTGBM_AVAILABLE,
    )

    src = inspect.getsource(ToyGradientBoostingRegressor) + inspect.getsource(ToyGradientBoostingClassifier)
    assert "np.mean(y, weights" not in src and "np.mean(y_binary, weights" not in src, \
        "源码中已无 np.mean(..., weights=)"

    w = np.array([1.0, 1.0, 1.0, 9.0])
    yv = np.array([0.0, 0.0, 0.0, 10.0])
    got = ToyGradientBoostingRegressor._wmean(yv, w)
    assert abs(got - 7.5) < 1e-12, f"_wmean 加权均值正确（期望 7.5） — {got}"
    assert abs(ToyGradientBoostingRegressor._wmean(yv, None) - 2.5) < 1e-12, \
        "_wmean 无权重时退化普通均值（期望 2.5）"

    Xs = np.column_stack([np.r_[np.zeros(50), np.ones(50) + 5.0],
                          np.random.default_rng(0).standard_normal(100)])
    ys = np.where(Xs[:, 0] < 2.0, -10.0, 10.0)
    toy = ToyGradientBoostingRegressor(n_estimators=3, learning_rate=0.5)
    tree = toy._fit_tree(Xs, ys, None)
    pv = tree(Xs)
    assert len(np.unique(np.round(pv, 9))) >= 2, \
        f"_fit_tree 产生两个不同的叶值（不再是常数） — unique={np.unique(np.round(pv, 9))}"

    gbm = ToyGradientBoostingRegressor(n_estimators=30, learning_rate=0.3)
    gbm.fit(Xs, ys)
    pg = gbm.predict(Xs)
    assert float(np.mean(np.abs(pg - ys))) < 0.5 * float(np.mean(np.abs(ys - ys.mean()))), \
        f"GBDT 拟合分段目标的 MAE 明显优于常数基线 — mae={float(np.mean(np.abs(pg - ys))):.3f}"

    gm = GradientBoostingModel(task="regression", n_estimators=20, max_depth=1,
                               learning_rate=0.3, random_state=7)
    gm.fit(Xs, ys)
    pgm = np.asarray(gm.predict(Xs), dtype=float).reshape(-1)
    assert len(pgm) == len(ys) and np.all(np.isfinite(pgm)), \
        "GradientBoostingModel(regression) 可训练且输出有限"
    gc = GradientBoostingModel(task="classification", n_estimators=10, max_depth=1,
                               learning_rate=0.3, random_state=7)
    yc = (ys > 0).astype(int)
    gc.fit(Xs, yc)
    assert len(np.asarray(gc.predict(Xs))) == len(yc), "GradientBoostingModel(classification) 可训练"


def test_ts_transformer_epochs_saved():
    """④ ts_transformer 补 self.epochs（装了 torch 不再 AttributeError），无 torch 明确不可用。"""
    from futures_quant.ai.ts_transformer import TSWrapper, TORCH_AVAILABLE

    w_ = TSWrapper(feature_size=5, seq_len=20, epochs=7, lr=0.002)
    assert getattr(w_, "epochs", None) == 7, "TSWrapper.epochs 已保存（旧实现漏赋值）"
    assert getattr(w_, "lr", None) is not None, "TSWrapper.lr 已保存"
    w_.fit(np.zeros((4, 20, 5)), np.zeros(4))
    if TORCH_AVAILABLE:
        assert True, "有 torch 时 fit 不抛错"
    else:
        assert getattr(w_, "available", None) is False, \
            "无 torch 时 fit 标记 available=False（不再静默恒 0）"
        assert np.all(np.asarray(w_.predict(np.zeros((3, 20, 5)))) == 0.0), \
            "无 torch 时 predict 仍返回 0 但已显式标注不可用"


def test_comparator_calls_real_models():
    """⑤ MultiModelComparator 的 tcn / gbm 分支真正调用对应模型（force_ridge 仅对 ridge 生效）。"""
    from futures_quant.ai.calibration_replay import MultiModelComparator, build_external_estimator
    from futures_quant.ai.predictor import FuturesPredictor

    est_tcn = build_external_estimator("tcn", epochs=10)
    est_gbm = build_external_estimator("gbm")
    est_tr = build_external_estimator("transformer")
    est_zzz = build_external_estimator("no_such_model")
    from futures_quant.ai.ts_transformer import TORCH_AVAILABLE

    assert est_tcn is not None and type(est_tcn).__name__ == "_TCNEstimator", \
        "build_external_estimator('tcn') 返回 TCN 适配器"
    assert est_gbm is not None and type(est_gbm).__name__ == "_GBMEstimator", \
        "build_external_estimator('gbm') 返回 GBM 适配器"
    if TORCH_AVAILABLE:
        assert est_tr is not None, "有 torch 时 transformer 适配器可用"
    else:
        assert est_tr is None, f"无 torch 时 transformer 判不可用（返回 None） — torch={TORCH_AVAILABLE}"
    assert est_zzz is None, "未知模型名返回 None"

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
            assert p.external_model is not None, \
                f"{name}: 生效的是外部模型而非 Ridge 回退 — external={type(p.external_model).__name__ if p.external_model else None}"

    from futures_quant.ai.features import build_features

    ind, F, names = build_features(df, extended=False, symbol="M6_CMP", period="D")
    arr = F.values.astype(float)
    y = ind["ret"].shift(-1).values.astype(float)
    seq_len = 20
    Xs3 = np.array([arr[t - seq_len + 1:t + 1] for t in range(seq_len - 1, len(arr) - 1)])
    Ys3 = np.nan_to_num(np.array([y[t] for t in range(seq_len - 1, len(arr) - 1)]))
    cut = int(len(Xs3) * 0.8)
    maes = {}
    for name, p in preds.items():
        m, s = p._feat_mean, p._feat_std
        if m is None:
            maes[name] = float("nan")
            continue
        pv = np.asarray(p._batch_pred((Xs3[cut:] - m) / s), dtype=float).reshape(-1)
        maes[name] = float(np.mean(np.abs(pv - Ys3[cut:])))
    uniq = {round(v, 9) for v in maes.values() if np.isfinite(v)}
    assert len(uniq) >= 2, f"4 个模型的 MAE 不全相等 — unique={sorted(uniq)}"
    assert abs(maes["tcn"] - maes["ridge"]) > 1e-9, \
        f"tcn 的 MAE 与 ridge 不同（证明不再是同一模型） — tcn={maes['tcn']:.6f}, ridge={maes['ridge']:.6f}"
    assert abs(maes["gbm"] - maes["ridge"]) > 1e-9, \
        f"gbm 的 MAE 与 ridge 不同（证明不再是同一模型） — gbm={maes['gbm']:.6f}, ridge={maes['ridge']:.6f}"


def test_comparator_csv_varies(tmp_path):
    """⑥ 对比 CSV 中 4 列数值有差异（模型相关）。"""
    import pandas as _pd

    from futures_quant.ai.calibration_replay import MultiModelComparator

    csv_path = str(tmp_path / "cmp.csv")
    comp = MultiModelComparator(out_dir=str(tmp_path))
    df = _make_df(420, seed=3)
    res = comp.run({"RB": df}, horizon=5, stride=60, max_samples=6,
                   epochs=4, seq_len=20, use_ensemble=False,
                   extended_features=False, out_csv=csv_path)
    assert os.path.exists(csv_path), f"CSV 已生成 — {res.get('csv_path')}"
    cdf = _pd.read_csv(csv_path)
    models = sorted(cdf["model"].unique().tolist())
    assert len(models) >= 2, f"CSV 含多个模型行 — {models}"
    if len(models) >= 2:
        pivot = cdf.pivot_table(index="ts", columns="model", values="p_up")
        vary = pivot.std(axis=1).max()
        assert float(vary) > 1e-6, f"同一时间点各模型 p_up 有差异 — max std={float(vary):.4f}"
        mae_by_model = cdf.groupby("model")["abs_err"].mean()
        assert len({round(v, 6) for v in mae_by_model.values}) >= 2, \
            "abs_err 不再恒等于行情自身波幅（与模型相关）"
        assert "pred_pct" in cdf.columns, "CSV 含 pred_pct 列（新增，便于核对预测误差）"
