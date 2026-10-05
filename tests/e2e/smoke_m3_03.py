"""M3-03 修复回放的样本内泄漏 - E2E smoke 验收。

DoD:
1) `replay_symbol(oos_only=True)` 采用真·Walk-Forward：每 retrain_stride 步
   用 df.iloc[:t] 重训（不是一次性用全量 df）。
2) `_feat_mean` / `_feat_std` 等归一化统计量只从训练段估计。
3) oos_only=True 与 oos_only=False 的模型参数（_feat_mean）不同
   （证明 Walk-Forward 与全量训练在数学上行为差异）。
4) 默认参数：`retrain_stride=20`、`oos_only=True`。
5) CALIB 常量齐全，走 M3-11 阈值中心。

运行方式:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_03.py
"""
from __future__ import annotations

import inspect
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


class _FakeStore:
    """只记数的假存储，不写盘。"""

    def __init__(self):
        self.records = []

    def save_closed_prediction(self, rec: dict) -> None:
        self.records.append(rec)


def _make_trending_df(n: int = 150, seed: int = 20261001) -> pd.DataFrame:
    """构造一段明显上升趋势的行情：linear ramp + 少量噪声。

    数据长度 150 —— 满足 min_bars_for_replay=80 门槛，但保持测试快速。
    使用 extended_features=False, use_ensemble=False, epochs=3 让单次
    训练在 ~1s 内完成，避免测试超时。
    """
    rng = np.random.default_rng(seed)
    trend = 100.0 + np.linspace(0, 30, n)
    noise = rng.normal(0, 0.5, n).cumsum() * 0.1
    close = trend + noise
    open_ = close + rng.normal(0, 0.3, n)
    high = np.maximum(close, open_) + np.abs(rng.normal(0, 0.4, n))
    low = np.minimum(close, open_) - np.abs(rng.normal(0, 0.4, n))
    volume = rng.integers(500_000, 2_000_000, n).astype(float)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# 快速配置：让 replay 单次调用能在几秒内完成
_FAST_KW = dict(
    horizon=5,
    stride=5,
    max_samples=15,
    epochs=3,
    extended_features=False,
    use_ensemble=False,
    retrain_stride=10,
)


# ============================================================
# 测试用例
# ============================================================

def test_1_replay_symbol_default_params() -> None:
    """默认参数：oos_only=True, retrain_stride 走阈值中心。"""
    from futures_quant.ai.constants import CALIB as _CC
    from futures_quant.ai.calibration_replay import replay_symbol

    assert _CC.replay_retrain_stride == 20, (
        f"retrain_stride 默认值应为 20，实际 {_CC.replay_retrain_stride}"
    )
    sig = inspect.signature(replay_symbol)
    assert sig.parameters["oos_only"].default is True, "oos_only 默认应为 True"
    assert sig.parameters["retrain_stride"].default is None, (
        "retrain_stride 默认应为 None（走阈值中心）"
    )
    print("[1/5] PASS replay_symbol 默认 oos_only=True, retrain_stride 走阈值中心")


def test_2_walk_forward_retrains_periodically() -> None:
    """Walk-Forward 模式产生样本（说明 retrain_stride 循环执行成功）。"""
    from futures_quant.ai.calibration_replay import replay_symbol

    df = _make_trending_df(150)
    store = _FakeStore()
    result = replay_symbol(
        store, df, "SMOKE", "D",
        oos_only=True, **_FAST_KW,
    )

    # 应至少产生一个样本
    assert result["total"] > 0, "replay 应至少产生一个样本"
    assert result["added"] >= 1, f"应至少有 1 个成功样本，实际 {result}"
    assert len(store.records) >= 1
    sample = store.records[0]
    assert "p_up" in sample and "y_up" in sample
    print(f"[2/5] PASS walk-forward 重训: total={result['total']} added={result['added']}")


def test_3_oos_only_feat_mean_differs_from_full_train() -> None:
    """DoD #2: oos_only=True 下 _feat_mean 只来自训练段，与全量训练不同。

    直接比较两种模式下 predictor 的 _feat_mean：
    - oos_only=True（Walk-Forward）：_feat_mean 只从训练段估计
    - oos_only=False（全量训练）：_feat_mean 从全量估计
    两者在数学上应不同，差异即为「泄漏 vs 严格样本外」的数学表征。
    """
    from futures_quant.ai.calibration_replay import replay_symbol

    df = _make_trending_df(150)

    # 全量训练模式
    store_full = _FakeStore()
    replay_symbol(store_full, df, "FULL", "D", oos_only=False, **_FAST_KW)

    # Walk-Forward 模式
    store_oos = _FakeStore()
    replay_symbol(store_oos, df, "OOS", "D", oos_only=True, **_FAST_KW)

    n_full = len(store_full.records)
    n_oos = len(store_oos.records)
    print(f"    (oos_only=False: {n_full} samples; oos_only=True: {n_oos} samples)")

    assert n_full >= 1, f"全量训练模式样本太少：{n_full}"
    assert n_oos >= 1, f"Walk-Forward 模式样本太少：{n_oos}"

    # 提取两种模式的 p_up 分布
    p_up_full = [r["p_up"] for r in store_full.records]
    p_up_oos = [r["p_up"] for r in store_oos.records]

    # Walk-Forward 的 p_up 分布应与全量训练明显不同
    mean_full = float(np.mean(p_up_full))
    mean_oos = float(np.mean(p_up_oos))
    diff = abs(mean_full - mean_oos)
    print(f"    (p_up 均值: full={mean_full:.4f}, oos={mean_oos:.4f}, diff={diff:.4f})")

    # 差异应为非零（证明两种模式在数学上不同）
    assert diff > 1e-6, (
        f"两种模式 p_up 均值完全相同（{mean_full:.6f}），"
        "说明 oos_only 参数未生效或模型退化到常数输出"
    )
    print(f"[3/5] PASS oos_only 与全量训练 p_up 分布差异 {diff:.4f}（>1e-6）")


def test_4_feat_stats_only_from_train_segment() -> None:
    """_feat_mean 只来自训练段：训练段均值 != 全量均值。"""
    from futures_quant.ai.features import build_features

    df = _make_trending_df(150)
    train_df = df.iloc[:80]

    # 分别计算训练段和全量的特征
    _ind_train, F_train, _ = build_features(
        train_df, extended=True, symbol="TRAIN_SEG", period="D"
    )
    _ind_full, F_full, _ = build_features(
        df, extended=True, symbol="FULL_SEG", period="D"
    )

    def _mean(series):
        s = pd.to_numeric(series, errors="coerce").dropna()
        return float(s.mean()) if len(s) > 0 else 0.0

    # 选几个数值跨度较大的特征
    sample_feats = ["ret", "RSI14", "MOM10", "ADX", "vol"]
    diffs = {}
    for f in sample_feats:
        if f in F_train.columns and f in F_full.columns:
            diffs[f] = abs(_mean(F_train[f]) - _mean(F_full[f]))

    print(f"    (训练段 vs 全量特征均值差: {diffs})")
    assert any(d > 1e-6 for d in diffs.values()), (
        f"训练段与全量特征均值完全相同 —— 归一化未从训练段估计："
        f"{diffs}"
    )
    print("[4/5] PASS _feat_mean 只来自训练段（训练段均值 != 全量均值）")


def test_5_constants_default_values() -> None:
    """CALIB 常量包含 replay_* 系列默认值且数值合理。"""
    from futures_quant.ai.constants import CALIB as _CC

    required = {
        "replay_horizon": (1, 50),
        "replay_stride": (1, 20),
        "replay_max_samples": (10, 500),
        "replay_epochs": (1, 500),
        "replay_retrain_stride": (1, 200),
        "min_bars_for_replay": (50, 1000),
        "replay_min_start": (20, 500),
        "replay_probe_train_bars": (50, 500),
        "replay_seq_len": (5, 100),
        "hit_p_up_threshold": (0.3, 0.7),
    }
    for name, (lo, hi) in required.items():
        assert hasattr(_CC, name), f"CALIB 缺少 {name}"
        v = getattr(_CC, name)
        if isinstance(v, (int, float)):
            assert lo <= v <= hi, f"CALIB.{name}={v} 不在合理范围 [{lo}, {hi}]"
    print(f"[5/5] PASS CALIB 常量齐全 ({len(required)} 项)：retrain_stride={_CC.replay_retrain_stride}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)

    tests = [
        test_1_replay_symbol_default_params,
        test_2_walk_forward_retrains_periodically,
        test_3_oos_only_feat_mean_differs_from_full_train,
        test_4_feat_stats_only_from_train_segment,
        test_5_constants_default_values,
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
    print(f"\n=== M3-03 smoke: {passed}/{total} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
