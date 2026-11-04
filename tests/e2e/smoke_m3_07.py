"""M3-07 修复特征重要性与风险评分 —— 端到端 smoke 验收。

DoD（spec + UPGRADE_PLAN_V5.md 第 337 行）：
  ① _feature_importance 只取 [:, F:]（跳过隐状态）再 mean(axis=0)
  ② 维度不符时 logger.warning 并返回空
  ③ _risk_score ATR=0 时用 ret.std()*sqrt(252) 兜底（此处实现为 ret.std * 1.6）

DoD 硬指标：注入已知权重 → Top1 特征与预期一致；ATR 缺失时风险分仍 >0。

运行：QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_07.py
"""
from __future__ import annotations

import os
import sys
import math

# ---- 沙箱 sys.path 注入 ----
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from types import SimpleNamespace


PASSED = 0
FAILED = 0
FAILURES: list[str] = []


# ============================================================
# Test 1: _feature_importance LSTM 分支 —— 跳过隐状态列，Top1 特征与预期一致
# ============================================================
def test_1_lstm_skip_hidden_columns() -> None:
    """M3-07 ①：LSTM 权重矩阵 (hid, hid+input) 的前 hid 列属于**隐状态**，
    应被跳过后取 [:, hid:]。注入 f1 显著大权重 → Top1 应为 f1。"""
    from futures_quant.ai.predictor import FuturesPredictor

    pred = FuturesPredictor()
    pred._feat_names = ["f0", "f1", "f2"]
    pred.use_lstm = True
    pred.external_model = None
    pred._ridge = None

    # 构造一个真实 LSTM（input=3, hid=4）
    from futures_quant.ai.lstm import LSTM
    lstm = LSTM(input_size=3, hidden_size=4, output_size=1, seed=42)
    hid, in_sz = lstm.hid, lstm.in_sz
    assert lstm.Wi.shape == (hid, hid + in_sz), f"LSTM Wi shape={lstm.Wi.shape}"

    # 覆盖 4 个门控权重：所有位置零，只让"输入特征 f1"（列 hid+1）显著大
    zero = np.zeros_like(lstm.Wi)
    for name in ("Wi", "Wf", "Wc", "Wo"):
        W = zero.copy()
        W[:, hid + 1] = 1.0  # f1 位置 = 1.0（其余 = 0）
        setattr(lstm, name, W)
    # Why: (1, hid)，全 1.0 使得每个隐单元贡献相同
    lstm.Why = np.ones((1, hid))

    pred.lstm = lstm
    fi = pred._feature_importance()

    assert fi, f"特征重要性返回空: {fi}"
    top1 = fi[0]
    assert top1["name"] == "f1", (
        f"Top1 特征错误：{top1} —— 期望 f1（f1 列权重 1.0，其他列 0）"
        f"；若 Top1 不是 f1，说明 [:, hid:] 切片错误"
    )
    # 归一化后 f1 重要性 = 1.0（其他 = 0）
    assert abs(top1["importance"] - 1.0) < 1e-6, (
        f"Top1 importance={top1['importance']}，期望 ≈ 1.0"
    )
    print(f"[1/6] PASS LSTM [:, hid:] 切片正确（Top1={top1['name']}@{top1['importance']}）")


# ============================================================
# Test 2: _feature_importance Ridge 分支 —— 按时间步平均，Top1 与预期一致
# ============================================================
def test_2_ridge_mean_over_timesteps() -> None:
    """M3-07 ①（续）：Ridge 权重长度 = seq_len * n_feat，应 reshape 后 mean(axis=0)。"""
    from futures_quant.ai.predictor import FuturesPredictor

    pred = FuturesPredictor()
    pred._feat_names = ["f0", "f1", "f2"]
    pred.seq_len = 5
    pred.use_lstm = False
    pred.lstm = None
    pred.external_model = None

    # 构造 fake Ridge：w 长度 = 5 * 3 = 15
    # 权重：每个 timestep 中 f0=1.0, f1=0.1, f2=0.05（f0 始终最强）
    w = np.array([1.0, 0.1, 0.05] * 5)
    pred._ridge = SimpleNamespace(w=w)

    fi = pred._feature_importance()

    assert fi, f"Ridge 特征重要性返回空: {fi}"
    top1 = fi[0]
    assert top1["name"] == "f0", (
        f"Top1 特征错误：{top1} —— 期望 f0（每个 timestep 权重均 1.0，其他 0.1/0.05）"
    )
    # 归一化：f0 占 1.0/(1.0+0.1+0.05) = 0.8696
    expected_f0 = 1.0 / (1.0 + 0.1 + 0.05)
    assert abs(top1["importance"] - expected_f0) < 1e-4, (
        f"Top1 importance={top1['importance']}，期望 ≈ {expected_f0:.4f}"
    )
    print(f"[2/6] PASS Ridge 按时间步平均（Top1={top1['name']}@{top1['importance']:.4f}, "
          f"expected={expected_f0:.4f}）")


# ============================================================
# Test 3: 维度不符时返回空 + logger.warning
# ============================================================
def test_3_dim_mismatch_returns_empty() -> None:
    """M3-07 ②：Ridge 权重长度既不等于 n 也不等于 seq_len * n → 返回 []。"""
    from futures_quant.ai.predictor import FuturesPredictor

    pred = FuturesPredictor()
    pred._feat_names = ["f0", "f1", "f2"]
    pred.seq_len = 5
    pred.use_lstm = False
    pred.lstm = None
    pred.external_model = None

    # 错误长度：既不是 3 也不是 15
    w = np.arange(7.0)
    pred._ridge = SimpleNamespace(w=w)

    fi = pred._feature_importance()

    assert fi == [], f"维度不符时应返回空列表，实际 {fi}"
    print(f"[3/6] PASS 维度不符返回空（w.size=7, n=3, seq_len=5）")


# ============================================================
# Test 4: 外部模型返回空
# ============================================================
def test_4_external_model_returns_empty() -> None:
    """M3-07：外部模型（TCN/GBM）没有可解释的输入权重 → 返回空。"""
    from futures_quant.ai.predictor import FuturesPredictor

    pred = FuturesPredictor()
    pred._feat_names = ["f0", "f1", "f2"]
    # 假外部模型
    class FakeEst:
        pass
    pred.external_model = FakeEst()
    pred.use_lstm = False
    pred.lstm = None
    pred._ridge = None

    fi = pred._feature_importance()

    assert fi == [], f"外部模型应返回空列表，实际 {fi}"
    print(f"[4/6] PASS 外部模型返回空（TCN/GBM 无权重解释）")


# ============================================================
# Test 5: _risk_score ATR=0 时用 ret.std 兜底，风险分仍 > 0
# ============================================================
def test_5_risk_score_atr_fallback() -> None:
    """M3-07 ③：ATR14 全为 0 时，应改用 ret.std * 1.6 兜底，风险分仍 > 0。"""
    from futures_quant.ai.predictor import FuturesPredictor

    n = 100
    rng = np.random.default_rng(7)
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.01))
    # ret = log return
    ret = np.concatenate([[0.0], np.diff(np.log(close))])
    # ATR14 全为 0（模拟 ATR 列异常）
    ind = pd.DataFrame({
        "close": close,
        "ret": ret,
        "ATR14": np.zeros(n),
        "ADX": np.full(n, 25.0),
    })

    pred = FuturesPredictor()
    r = pred._risk_score(ind)

    assert r.get("atr_source") == "ret_std_fallback", (
        f"ATR=0 时 atr_source 应为 'ret_std_fallback'，实际 {r.get('atr_source')}"
    )
    # 风险分应 > 0（因为兜底后 atr_pct > 0）
    assert r["score"] > 0, (
        f"ATR=0 兜底后风险分应 > 0，实际 {r['score']}"
    )
    # atr_pct 应有值（不是 0）
    assert r["atr_pct"] > 0, (
        f"ATR=0 兜底后 atr_pct 应 > 0，实际 {r['atr_pct']}"
    )
    # 兜底值 ≈ 1.6 * ret.std()
    expected_atr_pct = 1.6 * float(pd.Series(ret[1:]).std()) * 100  # 转成百分比
    assert abs(r["atr_pct"] - expected_atr_pct) < 1.0, (
        f"兜底 atr_pct={r['atr_pct']}，期望 ≈ {expected_atr_pct:.2f}（1.6 × ret.std）"
    )
    print(f"[5/6] PASS ATR=0 兜底（score={r['score']}, atr_pct={r['atr_pct']}%, "
          f"atr_source={r['atr_source']}）")


# ============================================================
# Test 6: _risk_score 正常 ATR 路径 —— atr_source="ATR14"，风险分与兜底值不同
# ============================================================
def test_6_risk_score_normal_atr() -> None:
    """M3-07 ③：ATR14 正常时走 ATR 路径（atr_source='ATR14'），不触发兜底。"""
    from futures_quant.ai.predictor import FuturesPredictor

    n = 100
    rng = np.random.default_rng(7)
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.01))
    ret = np.concatenate([[0.0], np.diff(np.log(close))])
    # ATR14 正常值（约 1.0，即 close 的 ~1%）
    atr14 = close * 0.01
    ind = pd.DataFrame({
        "close": close,
        "ret": ret,
        "ATR14": atr14,
        "ADX": np.full(n, 25.0),
    })

    pred = FuturesPredictor()
    r = pred._risk_score(ind)

    assert r.get("atr_source") == "ATR14", (
        f"ATR 正常时 atr_source 应为 'ATR14'，实际 {r.get('atr_source')}"
    )
    # atr_pct = ATR14[-1] / close[-1] * 100 ≈ 1.0%
    assert abs(r["atr_pct"] - 1.0) < 0.5, (
        f"ATR 路径 atr_pct={r['atr_pct']}，期望 ≈ 1.0（ATR/close=1%）"
    )
    print(f"[6/6] PASS 正常 ATR 路径（score={r['score']}, atr_pct={r['atr_pct']}%, "
          f"atr_source={r['atr_source']}）")


# ============================================================
def main() -> int:
    global PASSED, FAILED
    tests = [
        test_1_lstm_skip_hidden_columns,
        test_2_ridge_mean_over_timesteps,
        test_3_dim_mismatch_returns_empty,
        test_4_external_model_returns_empty,
        test_5_risk_score_atr_fallback,
        test_6_risk_score_normal_atr,
    ]
    total = len(tests)
    for t in tests:
        try:
            t()
            PASSED += 1
        except Exception as e:
            FAILED += 1
            FAILURES.append(f"{t.__name__}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")

    print(f"\n=== M3-07 smoke: {PASSED}/{total} passed ===")
    if FAILED:
        print(f"Failures ({FAILED}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
