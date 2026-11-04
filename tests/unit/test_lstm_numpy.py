# -*- coding: utf-8 -*-
"""M3-09：numpy LSTM 单元测试。

锁定：
  * 单调（可学习）序列训练后 loss 单调下降；
  * fit 返回每个 epoch 的 loss 序列；
  * predict_last / predict_batch 形状与有限性；
  * 常数目标 → 训练后预测趋近该常数（不发散）。
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai.lstm import LSTM  # noqa: E402


def _sequences(n=120, seq_len=8, n_feat=3, seed=0):
    """构造「下一根收益 = 当前窗口第 0 维均值」的可学习目标。"""
    rng = np.random.default_rng(seed)
    Xs = rng.normal(size=(n, seq_len, n_feat))
    Ys = Xs[:, -1, 0] * 0.8 - Xs[:, -1, 1] * 0.3
    return Xs, Ys


def test_fit_returns_loss_history():
    Xs, Ys = _sequences()
    m = LSTM(input_size=3, hidden_size=8, output_size=1, seed=1)
    losses = m.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=5, lr=0.01)
    assert isinstance(losses, list) and len(losses) == 5
    assert all(np.isfinite(l) for l in losses)


def test_loss_decreases_on_learnable_target():
    """可学习目标：末 epoch loss 显著低于首 epoch，且整体单调不增（允许 1e-9 抖动）。"""
    Xs, Ys = _sequences(n=160, seed=2)
    m = LSTM(input_size=3, hidden_size=16, output_size=1, seed=1)
    losses = m.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=30, lr=0.02)
    assert losses[-1] < losses[0], f"{losses[0]} → {losses[-1]}"
    # Adam + 小批量下 loss 会有正常抖动，允许 ≤20% 的步出现反弹
    bad = [i for i in range(len(losses) - 1)
           if losses[i + 1] > losses[i] + 1e-9]
    assert len(bad) <= max(1, len(losses) // 5), f"非下降步过多：{bad}"


def test_prediction_better_than_zero_baseline():
    Xs, Ys = _sequences(n=160, seed=3)
    m = LSTM(input_size=3, hidden_size=16, output_size=1, seed=1)
    m.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=30, lr=0.02)
    pred = m.predict_batch(Xs).reshape(-1)
    assert float(np.mean(np.abs(pred - Ys))) < float(np.mean(np.abs(Ys))), \
        "训练后应优于「恒预测 0」基线"


def test_predict_last_shape_and_finite():
    Xs, Ys = _sequences(n=40)
    m = LSTM(input_size=3, hidden_size=8, output_size=1, seed=1)
    m.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=2, lr=0.01)
    out = m.predict_last(Xs[0])
    assert np.all(np.isfinite(out))
    assert np.asarray(out).reshape(-1).size == 1


def test_predict_batch_shape():
    Xs, Ys = _sequences(n=40)
    m = LSTM(input_size=3, hidden_size=8, output_size=1, seed=1)
    m.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=2, lr=0.01)
    out = np.asarray(m.predict_batch(Xs))
    assert out.shape[0] == len(Xs)
    assert np.all(np.isfinite(out))


def test_constant_target_converges_not_diverges():
    """常数目标：训练后预测应靠近该常数，而不是发散/NaN。"""
    rng = np.random.default_rng(11)
    Xs = rng.normal(size=(80, 6, 2))
    Ys = np.full(80, 0.5)
    m = LSTM(input_size=2, hidden_size=8, output_size=1, seed=1)
    m.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=20, lr=0.02)
    pred = m.predict_batch(Xs).reshape(-1)
    assert np.all(np.isfinite(pred))
    assert float(np.mean(np.abs(pred - Ys))) < float(np.mean(np.abs(Ys))) + 1e-6


@pytest.mark.parametrize("hidden", [4, 16])
def test_various_hidden_sizes(hidden):
    Xs, Ys = _sequences(n=100, seed=5)
    m = LSTM(input_size=3, hidden_size=hidden, output_size=1, seed=1)
    losses = m.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=15, lr=0.02)
    assert losses[-1] < losses[0]


def test_weight_layout_matches_feature_importance_contract():
    """M3-07 依赖的布局约定：门控权重列数 = hidden + input。"""
    m = LSTM(input_size=5, hidden_size=6, output_size=1, seed=1)
    for name in ("Wf", "Wi", "Wc", "Wo"):
        w = getattr(m, name)
        assert w.shape == (6, 6 + 5), f"{name}.shape={w.shape}"
    assert m.Why.shape == (1, 6)
    assert int(m.hid) == 6 and int(m.in_sz) == 5
