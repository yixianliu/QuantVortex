"""M5.8 特征贡献度验收测试。

覆盖：
- 朴素扰动重要性对「真实重要特征」排序靠前（可解释性检查）；
- 未 fit 时调 top_k 抛错；
- importance 输出维度正确；
- to_chart_data 返回 (labels, values) 且长度 = k。
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import numpy as np
from ai.attribution import FeatureAttribution


class _LinearModel:
    """极简线性模型：pred = X @ w + b，仅实现 .predict。"""
    def __init__(self, w: np.ndarray, b: float = 0.0):
        self.w = np.asarray(w, dtype=float)
        self.b = float(b)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.atleast_2d(np.asarray(X, dtype=float)) @ self.w + self.b


def test_importance_ranking():
    """特征 0 权重最大 → 应排在 top1。"""
    np.random.seed(3)
    n, m = 200, 6
    X = np.random.randn(n, m)
    w = np.array([5.0, 1.0, 0.5, 0.1, 0.05, 0.01])  # 特征 0 最重
    model = _LinearModel(w, b=0.2)
    fa = FeatureAttribution(model, [f"f{i}" for i in range(m)], shap_top_k=3)
    scores = fa.importance(X, model.predict(X))
    assert scores.shape == (m,)
    top = fa.top_k(3)
    # 最重要特征 f0 应在 top3 且是第 1
    assert top[0][0] == "f0", f"top1 应为 f0，实际 {top[0]}"
    # 贡献度非负
    assert np.all(scores >= 0)
    print("重要性排序 OK", top)


def test_topk_requires_importance():
    fa = FeatureAttribution(_LinearModel(np.ones(3)), ["a", "b", "c"])
    try:
        fa.top_k()
        raise AssertionError("未调用 importance 时 top_k 应抛 ValueError")
    except ValueError:
        print("未 fit 时正确抛错 OK")


def test_chart_data_shape():
    np.random.seed(4)
    X = np.random.randn(80, 4)
    model = _LinearModel(np.array([3.0, 2.0, 1.0, 0.5]))
    fa = FeatureAttribution(model, ["a", "b", "c", "d"], shap_top_k=10)
    fa.importance(X, model.predict(X))
    labels, values = fa.to_chart_data(k=4)
    assert len(labels) == 4 and len(values) == 4
    assert all(isinstance(v, float) for v in values)
    print("chart_data OK", labels, values)


if __name__ == "__main__":
    test_importance_ranking()
    test_topk_requires_importance()
    test_chart_data_shape()
    print("test_attribution.py 全绿")
