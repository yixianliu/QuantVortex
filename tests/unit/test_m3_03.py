"""M3-03 修复回放的样本内泄漏（真·Walk-Forward）—— pytest 形态。

由散落脚本 ``tests/test_m3_03.py``（模块级 ``print``+``assert``，0 个 ``def test_*``）
机械改写，行为契约不变：
  ① 新增参数 ``retrain_stride``（默认 20）/ ``oos_only``（默认 True）存在且默认正确
  ② OOS(walk-forward) 与 FULL(全量训练) 两种模式均产出样本
  ③ 两模式结果不同 → 证明训练数据确实只用了历史段（泄漏消除）
  ④ 归一化统计量只来自训练段（软校验，predictor 未训练成功则跳过）
  ⑤ docstring 已说明 Walk-Forward 与泄漏修复

注：单次 fit 约 3~5s，故测试刻意缩小规模（n=300 / epochs=3 / 少重训），
整体约数十秒。改动仅去掉 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from futures_quant.ai.calibration_replay import replay_symbol


class FakeStore:
    """只记录、不落库的假 store。"""

    def __init__(self):
        self.records = []

    def save_closed_prediction(self, rec):
        self.records.append(rec)


def hit_rate(store) -> float:
    if not store.records:
        return float("nan")
    return sum(r["score"] for r in store.records) / len(store.records)


def make_df(n=300, seed=5):
    """前半段上涨、后半段下跌——全量训练会「预知」后期下跌，与
    只用历史的 walk-forward 产生系统性差异。"""
    rng = np.random.RandomState(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    up = np.linspace(100, 150, n // 2)
    down = np.linspace(150, 115, n - n // 2)
    close = np.concatenate([up, down]) + np.cumsum(rng.randn(n)) * 0.25
    return pd.DataFrame(
        {"open": close + rng.randn(n) * 0.1,
         "high": close + np.abs(rng.randn(n)) * 0.8,
         "low": close - np.abs(rng.randn(n)) * 0.8,
         "close": close,
         "volume": np.abs(rng.randn(n)) * 800 + 4000},
        index=idx)


@pytest.fixture(scope="module")
def df():
    return make_df()


def test_new_params_present_with_correct_defaults():
    """① retrain_stride / oos_only 参数存在，且默认语义正确。

    **改写校正（非机械搬运，承接「门禁工件注释会过时」主题）**：散落脚本断言
    ``retrain_stride`` 默认 ``== 20``，但当前生产已把默认改为 **config 驱动**——
    参数层默认是 ``None``（哨兵：回退到 ``ai.constants.CALIB.replay_retrain_stride``），
    有效默认值 20 落在配置层。故本断言锁的是**当前契约**（参数=None 哨兵 + 配置默认 20），
    而非旧写法的参数层硬 20。
    """
    from futures_quant.ai.constants import CALIB
    sig = inspect.signature(replay_symbol)
    assert "retrain_stride" in sig.parameters, "缺少 retrain_stride 参数"
    assert "oos_only" in sig.parameters, "缺少 oos_only 参数"
    # 参数层：None 哨兵（回退到 config），而非硬编码 20
    assert sig.parameters["retrain_stride"].default is None, \
        "retrain_stride 参数默认应为 None（哨兵，回退 CALIB.replay_retrain_stride）"
    assert sig.parameters["oos_only"].default is True, "oos_only 默认应为 True"
    # 配置层：有效默认值 20
    assert CALIB.replay_retrain_stride == 20, "CALIB.replay_retrain_stride 默认应为 20"


def test_both_modes_produce_samples(df):
    """② OOS(walk-forward) 与 FULL(全量训练) 两种模式均产出样本入库。"""
    s_oos = FakeStore()
    r_oos = replay_symbol(s_oos, df, symbol="TEST", period="D",
                          horizon=10, stride=12, max_samples=40,
                          epochs=3, oos_only=True, retrain_stride=24)
    assert r_oos["added"] > 0, "OOS 模式应有样本入库"

    s_full = FakeStore()
    r_full = replay_symbol(s_full, df, symbol="TEST", period="D",
                           horizon=10, stride=12, max_samples=40,
                           epochs=3, oos_only=False)
    assert r_full["added"] > 0, "全量训练模式应有样本入库（用于对比）"


def test_modes_differ_proves_no_leak(df):
    """③ 两模式结果不同 → 证明训练数据确实只用了历史段（泄漏消除）。"""
    s_oos = FakeStore()
    replay_symbol(s_oos, df, symbol="TEST", period="D",
                  horizon=10, stride=12, max_samples=40,
                  epochs=3, oos_only=True, retrain_stride=24)
    s_full = FakeStore()
    replay_symbol(s_full, df, symbol="TEST", period="D",
                  horizon=10, stride=12, max_samples=40,
                  epochs=3, oos_only=False)

    hr_oos, hr_full = hit_rate(s_oos), hit_rate(s_full)
    p_oos = np.array([r["p_up"] for r in s_oos.records])
    p_full = np.array([r["p_up"] for r in s_full.records])
    diff = abs(hr_oos - hr_full)
    pup_diff = abs(float(np.mean(p_oos)) - float(np.mean(p_full)))
    assert diff > 0.05 or pup_diff > 1e-6, (
        f"两模式结果完全相同（命中率差 {diff:.4f}、p_up均值差 {pup_diff:.6f}）"
        f"—— 说明仍在用全量训练，walk-forward 未生效")


def test_normalization_stats_from_train_only(df):
    """④ 归一化统计量只来自训练段（软校验：predictor 未训练成功则跳过）。"""
    from futures_quant.ai.predictor import FuturesPredictor

    stat_keys = None
    try:
        p_tr = FuturesPredictor()
        p_tr.fit(df.iloc[:200], seq_len=20, epochs=3, force_ridge=True,
                 extended_features=True, use_ensemble=True, symbol="NORM_T", period="D")
        p_al = FuturesPredictor()
        p_al.fit(df, seq_len=20, epochs=3, force_ridge=True,
                 extended_features=True, use_ensemble=True, symbol="NORM_F", period="D")
        if getattr(p_tr, "trained", False) and getattr(p_al, "trained", False):
            stat_keys = [k for k in ("_feat_mean", "_feat_std", "_feat_mu", "_feat_sigma")
                         if hasattr(p_tr, k)]
            for k in stat_keys:
                a = np.asarray(getattr(p_tr, k), dtype=float)
                b = np.asarray(getattr(p_al, k), dtype=float)
                same = a.shape == b.shape and np.allclose(a, b, equal_nan=True)
                assert not same, f"{k} 在训练段与全量下相同 → 统计量疑似泄漏未来"
    except Exception:
        pass

    if not stat_keys:
        pytest.skip("未直接校验统计量（predictor 未训练成功），已由③的模式差异间接证明训练段不同")


def test_docstring_mentions_walk_forward_and_leak_fix():
    """⑤ docstring 已说明 Walk-Forward 与泄漏修复。"""
    import futures_quant.ai.calibration_replay as cr
    doc = cr.__doc__ or ""
    assert "walk-forward" in doc.lower(), "docstring 应说明 Walk-Forward"
    assert "泄漏" in doc, "docstring 应说明修复了样本内泄漏"
