"""M3-06 修复多模型对比名不副实 —— 端到端 smoke 验收。

DoD（spec + UPGRADE_PLAN_V5.md 第 336 行）：
  ① tcn.fit() 实装（因果膨胀卷积 + 岭回归/GD）
  ② ts_transformer 补 self.epochs
  ③ boosting: np.mean(weights=...) → np.average + _fit_tree 真实阈值分裂
  ④ MultiModelComparator 的 tcn/gbm 真调对应模型
  ⑤ 无 torch 时 ts_transformer 明确标不可用

DoD 硬指标：4 个模型在同一 df 上的 MAE **不全相等**（spec 原文）。

运行：QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_06.py
"""
from __future__ import annotations

import os
import sys
import math
import tempfile

# ---- 沙箱 sys.path 注入 ----
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd


# ---- 合成 df（与 smoke_m3_03 同风格） ----
def _make_df(n: int = 500, seed: int = 20261001) -> pd.DataFrame:
    """构造随机游走 K 线（close 从 100 起步），覆盖 add_indicators 全部输入列。"""
    rng = np.random.default_rng(seed)
    ret = rng.standard_normal(n) * 0.01
    close = 100.0 * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(rng.standard_normal(n)) * 0.005)
    low = close * (1 - np.abs(rng.standard_normal(n)) * 0.005)
    volume = 1000 + np.abs(rng.standard_normal(n)) * 500
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": np.r_[close[0], close[:-1]],
        "high": high, "low": low, "close": close,
        "volume": volume.astype(int),
        "settlement": close,
    }, index=idx)


PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def _report(ok: bool, msg: str) -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"PASS  {msg}")
    else:
        FAILED += 1
        FAILURES.append(msg)
        print(f"FAIL  {msg}")


# ============================================================
# Test 1: _causal_conv 修好 —— TCN 隐状态非全零
# ============================================================
def test_1_causal_conv_nonzero() -> None:
    """M3-06 ①：`_causal_conv` 切片修复后 TCN 卷积输出非零。"""
    from futures_quant.ai.tcn import TemporalConvNet

    tc = TemporalConvNet(num_inputs=3, num_channels=(8, 8), kernel_size=2, seed=42)
    # 随机输入（seq_len=30, in_ch=3）
    x = np.random.default_rng(0).standard_normal((30, 3))
    h = tc._hidden(x)
    assert h.shape == (30, 8), f"hidden shape 错误: {h.shape}"
    # ReLU + 小权重(0.01) 会正常产生 40~60% 非零，旧 bug（切片错）会让全部输出 0。
    # 判据改为「非零比例显著高于 ReLU 随机期望（>10%）」，而不是硬编码 50%。
    n_nonzero = int((np.abs(h) > 1e-8).sum())
    ratio = n_nonzero / h.size
    assert ratio > 0.10, (
        f"卷积输出非零比例过低（{n_nonzero}/{h.size}={ratio:.1%}）—— _causal_conv 未修好"
    )
    # 同时幅值应大于零权重初始化产生的极小值（0.01 * 卷积）
    h_abs_max = float(np.abs(h).max())
    assert h_abs_max > 1e-4, f"卷积输出幅值过小：max={h_abs_max}"
    print(f"[1/7] PASS _causal_conv 修好（非零比例 {ratio:.1%}, max|out|={h_abs_max:.4f}）")


# ============================================================
# Test 2: fit() 真训练 —— loss 单调不增且 final_weight 有变化
# ============================================================
def test_2_tcn_fit_learns() -> None:
    """M3-06 ①：`fit()` 真的跑训练；训练后 loss ≤ 初始，final_weight 与初始不同。"""
    from futures_quant.ai.tcn import TemporalConvNet

    # 构造线性可分数据：y = 2 * x[:, 0] + noise
    rng = np.random.default_rng(20260106)
    n, seq, k = 120, 15, 3
    X = rng.standard_normal((n, seq, k))
    y = 2.0 * X[:, -1, 0] + rng.standard_normal(n) * 0.05

    tc = TemporalConvNet(num_inputs=k, num_channels=(16, 16), kernel_size=2, seed=7)
    w_before = tc.final_weight.copy()

    tc.fit(X, y, epochs=8, lr=0.01, batch_size=32)

    assert tc.fitted is True, "fit 未标记 fitted=True"
    assert len(tc.loss_history_) >= 3, f"loss_history_ 太短: {len(tc.loss_history_)}"
    # loss 单调不增（允许相等 —— LS 收尾时可能不再下降）
    lh = tc.loss_history_
    for i in range(1, len(lh)):
        assert lh[i] <= lh[i - 1] + 1e-12, (
            f"loss 第 {i} 步反弹: {lh[i-1]:.6f} → {lh[i]:.6f}"
        )
    # final_weight 训练后与初始不同（若初始 w * 0.01，训练后应明显变）
    diff = float(np.linalg.norm(tc.final_weight - w_before))
    assert diff > 1e-3, f"final_weight 几乎没变（diff={diff}）—— fit 空转"
    # 训练后对训练集 MAE 应显著优于随机 w（初始 random w * 0.01 时基线 MAE 通常很大）
    pred = tc.predict(X)
    mae = float(np.mean(np.abs(pred - y)))
    # 期望 MAE 显著小于 y 的标准差（否则训练毫无效果）
    y_std = float(np.std(y))
    assert mae < y_std * 0.8, (
        f"训练后 MAE={mae:.4f} ≥ 0.8*y_std={y_std*0.8:.4f} —— fit 未真学习"
    )
    print(f"[2/7] PASS tcn.fit 真训练（loss {lh[0]:.4f} → {lh[-1]:.4f}, MAE={mae:.4f}, y_std={y_std:.4f}）")


# ============================================================
# Test 3: TSWrapper.epochs 属性存在
# ============================================================
def test_3_ts_wrapper_has_epochs() -> None:
    """M3-06 ②：TSWrapper 构造即持有 self.epochs / self.lr。"""
    from futures_quant.ai.ts_transformer import TSWrapper, TORCH_AVAILABLE

    sw = TSWrapper(feature_size=5, epochs=15, lr=0.005)
    assert hasattr(sw, "epochs"), "TSWrapper 缺 self.epochs（M3-06 ② 未修）"
    assert sw.epochs == 15, f"epochs={sw.epochs}，期望 15"
    assert hasattr(sw, "lr"), "TSWrapper 缺 self.lr"
    assert sw.lr == 0.005
    # 无 torch 时 available=False 且 fit 后仍为 False（明确标不可用）
    if not TORCH_AVAILABLE:
        sw.fit(np.zeros((10, 5, 5)), np.zeros(10))
        assert getattr(sw, "available", True) is False, (
            "无 torch 时 fit 后 available 应为 False（M3-06 ⑤ 未修）"
        )
        # predict 恒返回 0（占位）
        p = sw.predict(np.zeros((3, 5, 5)))
        assert np.allclose(p, 0.0), "无 torch 时 predict 应恒返回 0"
    print(f"[3/7] PASS TSWrapper 有 epochs/lr 属性（epochs={sw.epochs}, torch={TORCH_AVAILABLE}）")


# ============================================================
# Test 4: build_external_estimator('transformer') 无 torch 时返回 None
# ============================================================
def test_4_transformer_unavailable_without_torch() -> None:
    """M3-06 ⑤：无 torch 时 build_external_estimator('transformer') 明确返回 None。"""
    from futures_quant.ai.calibration_replay import build_external_estimator
    from futures_quant.ai.ts_transformer import TORCH_AVAILABLE

    if not TORCH_AVAILABLE:
        est = build_external_estimator("transformer")
        assert est is None, (
            f"无 torch 时 transformer 应返回 None，实际 {type(est).__name__}"
        )
        est2 = build_external_estimator("ts_transformer")
        assert est2 is None
    else:
        # torch 存在时应能构造（不断言具体类型，只不断言返回 None）
        est = build_external_estimator("transformer")
        assert est is not None
    # tcn / gbm 应总能构造（numpy 实现）
    est_tcn = build_external_estimator("tcn")
    est_gbm = build_external_estimator("gbm")
    assert est_tcn is not None
    assert est_gbm is not None
    print(f"[4/7] PASS build_external_estimator: tcn/gbm 可构造, "
          f"transformer={'None (无 torch)' if not TORCH_AVAILABLE else 'ok'}")


# ============================================================
# Test 5: boosting._wmean 支持 sample_weight（无 TypeError）
# ============================================================
def test_5_boosting_wmean_accepts_weights() -> None:
    """M3-06 ③：`_wmean` 用 np.average 而非 np.mean(weights=...)。"""
    from futures_quant.ai.boosting import ToyGradientBoostingRegressor

    # 静态方法，构造实例即可
    gb = ToyGradientBoostingRegressor(n_estimators=1)
    y = np.array([1.0, 2.0, 3.0, 4.0])
    w = np.array([1.0, 1.0, 2.0, 2.0])

    # 关键：sample_weight 非 None 不能抛 TypeError
    # 旧 bug: np.mean(y, weights=w) → TypeError: mean() got unexpected kwarg
    val = gb._wmean(y, sample_weight=w)
    expected = float(np.average(y, weights=w))  # = (1+2+2*3+2*4)/6 = 3.1667
    assert abs(val - expected) < 1e-9, f"_wmean 加权均值错误: {val} ≠ {expected}"

    # sample_weight=None 退化普通均值
    val_none = gb._wmean(y, sample_weight=None)
    assert abs(val_none - float(np.mean(y))) < 1e-9

    # 空数组兜底
    assert gb._wmean(np.array([]), sample_weight=None) == 0.0
    print(f"[5/7] PASS _wmean 支持 sample_weight（加权={val:.4f}, 均={val_none}）")


# ============================================================
# Test 6: _fit_tree 真实阈值分裂（非退化常数）
# ============================================================
def test_6_fit_tree_real_split() -> None:
    """M3-06 ③：`_fit_tree` 对线性可分数据做真实分裂，不同 X 得到不同预测。"""
    from futures_quant.ai.boosting import ToyGradientBoostingRegressor

    # 构造可分数据：x < 0 → y=0, x ≥ 0 → y=1
    rng = np.random.default_rng(42)
    n = 200
    x1 = rng.standard_normal(n) * 0.5
    y = (x1 >= 0).astype(float)
    X = np.column_stack([x1, rng.standard_normal(n) * 0.01])  # 第 2 列噪声

    # 单棵树 × learning_rate=0.1 只贡献 ~0.1 幅度，用 20 棵树积累到可观差异
    gb = ToyGradientBoostingRegressor(n_estimators=20, learning_rate=0.3,
                                       random_state=42)
    gb.fit(X, y)

    # 若树退化常数，对 x=-0.5 与 x=+0.5 应返回同一个值；修好后返回不同值
    pred_neg = gb.predict(np.array([[-0.5, 0.0]]))[0]
    pred_pos = gb.predict(np.array([[+0.5, 0.0]]))[0]
    diff = abs(pred_pos - pred_neg)
    assert diff > 0.3, (
        f"树退化常数：predict(-0.5)={pred_neg:.4f}, predict(+0.5)={pred_pos:.4f}, "
        f"diff={diff} —— 阈值分裂未生效"
    )
    print(f"[6/7] PASS _fit_tree 真实分裂（pred(-0.5)={pred_neg:.3f}, "
          f"pred(+0.5)={pred_pos:.3f}, diff={diff:.3f}）")


# ============================================================
# Test 7: MultiModelComparator 4 模型 MAE 不全相等（DoD 硬指标）
# ============================================================
def _make_signal_df(n: int = 600, seed: int = 20261001) -> pd.DataFrame:
    """带**可学习信号**的 K 线（正弦波 + 上行趋势 + 噪声），避免纯随机游走
    让所有模型都预测 ≈0 导致 MAE 相等。"""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    trend = 0.0008 * t
    sine = 0.02 * np.sin(2 * np.pi * t / 30)          # 30 日周期
    noise = rng.standard_normal(n) * 0.005
    log_price = 4.6 + trend + sine + np.cumsum(noise)
    close = np.exp(log_price)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": np.r_[close[0], close[:-1]],
        "high": close * (1 + 0.003 + np.abs(rng.standard_normal(n)) * 0.002),
        "low": close * (1 - 0.003 - np.abs(rng.standard_normal(n)) * 0.002),
        "close": close,
        "volume": (1000 + np.abs(rng.standard_normal(n)) * 500).astype(int),
        "settlement": close,
    }, index=idx)


def test_7_multimodel_mae_not_all_equal() -> None:
    """M3-06 ④ DoD：ridge/lstm/tcn/gbm 在同一 df 上 MAE 不全相等。"""
    from futures_quant.ai.calibration_replay import MultiModelComparator

    # 关键：用带信号的数据（正弦波 + 趋势），否则纯随机游走下所有模型都预测 ~0，
    # 此时 MAE ≈ 市场自身波动，4 个模型的 MAE 自然相等（不代表分支未修）。
    df = _make_signal_df(600, seed=20261001)
    tmp_dir = tempfile.mkdtemp(prefix="m3_06_")
    comparator = MultiModelComparator(out_dir=tmp_dir)
    result = comparator.run(
        dfs={"TEST": df},
        symbol="TEST",
        period="D",
        horizon=5,
        stride=10,
        max_samples=30,
        epochs=8,
        seq_len=15,
        use_ensemble=False,
        extended_features=False,
        out_csv=None,
    )

    summary = result.get("summary", {})
    active = {m: summary[m] for m in summary if summary[m].get("n", 0) > 0}
    assert len(active) >= 3, (
        f"活跃模型不足 3 个：{list(active.keys())}（sandbox 无 torch，lstm 会降级为 numpy）"
    )
    maes = {m: s["mae_pct"] for m, s in active.items()}
    unique_maes = set(maes.values())
    print(f"[7/7] 详情: {maes}")
    print(f"        活跃模型: {sorted(active.keys())}")
    print(f"        样本数: " + ", ".join(f"{m}={summary[m]['n']}" for m in sorted(active)))

    # DoD 硬指标：4 列 MAE 不全相等（去重后 > 1 个值）
    assert len(unique_maes) > 1, (
        f"4 个模型 MAE 全相等：{maes} —— MultiModelComparator 分支仍在降级同一模型"
    )
    print(f"[7/7] PASS 4 模型 MAE 不全相等（unique={len(unique_maes)}：{sorted(unique_maes)}）")


# ============================================================
def main() -> int:
    global PASSED, FAILED
    tests = [
        test_1_causal_conv_nonzero,
        test_2_tcn_fit_learns,
        test_3_ts_wrapper_has_epochs,
        test_4_transformer_unavailable_without_torch,
        test_5_boosting_wmean_accepts_weights,
        test_6_fit_tree_real_split,
        test_7_multimodel_mae_not_all_equal,
    ]
    total = len(tests)
    for i, t in enumerate(tests, 1):
        try:
            t()
            PASSED += 1
        except Exception as e:
            FAILED += 1
            FAILURES.append(f"{t.__name__}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")

    print(f"\n=== M3-06 smoke: {PASSED}/{total} passed ===")
    if FAILED:
        print(f"Failures ({FAILED}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
