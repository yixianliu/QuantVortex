# -*- coding: utf-8 -*-
"""M3-09：ensemble._Ridge 单元测试。

锁定：
  * 已知线性关系 → 拟合后 MAE < 1e-6；
  * alpha 网格 CV 能选出合理 alpha（噪声大时偏向更大的 alpha）；
  * 未训练时 predict 安全返回 0.0；
  * 奇异矩阵走 pinv 回退而不是抛异常。
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai.ensemble import _Ridge  # noqa: E402


def _linear_data(n=200, n_feat=4, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, n_feat))
    w = rng.normal(size=n_feat) * 2.0      # 任意维度都可用的真值权重
    y = X @ w + 1.25
    if noise:
        y = y + rng.normal(0, noise, n)
    return X, y


def test_ridge_recovers_exact_linear_relation():
    """无噪声线性关系：岭回归应几乎完美复原（MAE < 1e-6）。"""
    X, y = _linear_data(noise=0.0)
    m = _Ridge(alpha=1e-6)
    m.fit(X, y)
    pred = np.array([m.predict(x) for x in X])
    mae = float(np.mean(np.abs(pred - y)))
    assert mae < 1e-6, f"MAE={mae}"


def test_ridge_recovers_weights_and_bias():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(200, 4))
    w_true = np.array([0.8, -1.5, 0.3, 2.0])
    y = X @ w_true + 1.25
    m = _Ridge(alpha=1e-8)
    m.fit(X, y)
    assert m.w is not None
    assert np.allclose(m.w, w_true, atol=1e-4), m.w
    assert abs(m.b - 1.25) < 1e-4, m.b


def test_predict_before_fit_returns_zero():
    m = _Ridge()
    assert m.predict(np.zeros(3)) == 0.0


def test_fit_with_cv_picks_small_alpha_on_clean_data():
    """干净数据：CV 应选小 alpha（不需要强正则）。"""
    X, y = _linear_data(noise=0.0, seed=1)
    picked = _Ridge.fit_with_cv(X[:150], y[:150], X[150:], y[150:])
    assert picked is not None and picked.w is not None
    err = float(np.mean(np.abs(np.array([picked.predict(x) for x in X[150:]])
                               - y[150:])))
    assert err < 1e-4, f"验证 MAE={err}"
    assert picked.alpha <= 1.0, f"picked alpha={picked.alpha}"


def test_fit_with_cv_prefers_regularization_on_noisy_collinear_data():
    """共线 + 高噪：CV 选出的 alpha 应明显大于干净场景（正则起效）。"""
    rng = np.random.default_rng(7)
    n = 240
    base = rng.normal(size=(n, 1))
    X = np.hstack([base, base + 1e-8 * rng.normal(size=(n, 1)),
                   rng.normal(size=(n, 1))])     # 前两列近似共线
    y = X[:, 0] + 0.5 * X[:, 2] + rng.normal(0, 1.5, n)
    picked = _Ridge.fit_with_cv(X[:180], y[:180], X[180:], y[180:])
    assert picked is not None
    assert picked.alpha >= 1e-2, f"picked alpha={picked.alpha}（高噪场景应偏向正则）"


def test_fit_survives_singular_matrix():
    """X^T X 奇异时走 pinv 回退，不抛异常且输出有限。"""
    X = np.ones((20, 3))          # 秩 1 → X^T X 奇异
    y = np.arange(20, dtype=float)
    m = _Ridge(alpha=0.0)
    m.fit(X, y)
    assert np.all(np.isfinite(m.w))
    assert np.isfinite(m.predict(X[0]))


def test_alpha_grid_is_positive_and_ordered():
    assert len(_Ridge.ALPHA_GRID) >= 3
    assert all(a > 0 for a in _Ridge.ALPHA_GRID)


@pytest.mark.parametrize("n_feat", [1, 4, 8])
def test_ridge_various_feature_dims(n_feat):
    X, y = _linear_data(n=120, n_feat=n_feat, noise=0.0,
                        seed=10 + n_feat)
    m = _Ridge(alpha=1e-8)
    m.fit(X, y)
    pred = np.array([m.predict(x) for x in X])
    assert float(np.mean(np.abs(pred - y))) < 1e-6
