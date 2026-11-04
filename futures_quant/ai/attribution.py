"""特征贡献度 / 归因（M5.8）。

把「模型为什么这样预测」量化为**每个特征的重要性**，输出前 N 特征贡献度，
供预测页渲染 bar chart。

策略：
- 若安装了 `shap`，对 tree-based 模型（XGBoost/LightGBM）用 TreeSHAP 精确归因；
- 否则降级为**朴素重要性**：对每个特征做「置零扰动」，测预测值变化的幅度，
  作为该特征的贡献度（数值型，无需解释器，纯 numpy 可跑）。

接口：
    class FeatureAttribution(model, feature_names, shap_top_k=10)
        .importance(X_test, preds) -> np.ndarray  (shape = n_features)
        .top_k(k=10) -> List[(name, score)]        (按 |score| 降序)

model 须实现 `.predict(X)`（回归/分类值）；feature_names 与 X 列顺序一致。
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

# 可选 shap（tree-based 精确归因）
try:
    import shap as _shap
    HAS_SHAP = True
except Exception:  # pragma: no cover
    _shap = None
    HAS_SHAP = False

# 判断 model 是否为树模型（XGBoost/LightGBM），TreeSHAP 仅对其有效
_TREE_BASED = ("XGBClassifier", "XGBRegressor", "LGBMClassifier", "LGBMRegressor",
               "GradientBoostingClassifier", "GradientBoostingRegressor")


class FeatureAttribution:
    """特征贡献度计算（shap 可选，缺失降级朴素扰动重要性）。"""

    def __init__(self, model, feature_names: Sequence[str], shap_top_k: int = 10,
                 n_perturb: int = 32, seed: int = 42) -> None:
        self.model = model
        self.feature_names = list(feature_names)
        self.n_features = len(self.feature_names)
        self.shap_top_k = int(shap_top_k)
        self.n_perturb = int(n_perturb)
        self.seed = int(seed)
        self._importance: np.ndarray | None = None

    def _is_tree_based(self) -> bool:
        return type(self.model).__name__ in _TREE_BASED

    def importance(self, X_test: np.ndarray, preds: np.ndarray | None = None) -> np.ndarray:
        """返回每个特征的贡献度（shape = n_features）。"""
        X_test = np.atleast_2d(np.asarray(X_test, dtype=float))
        if preds is None:
            preds = np.asarray(self.model.predict(X_test), dtype=float)
        else:
            preds = np.asarray(preds, dtype=float)

        # 精确路径：shap TreeExplainer（仅树模型）
        if HAS_SHAP and self._is_tree_based():
            try:
                explainer = _shap.TreeExplainer(self.model)
                shap_values = explainer.shap_values(X_test)
                # shap_values 可能为 (n, m, k) 或 list，取均值方向
                sv = np.asarray(shap_values)
                if sv.ndim == 3:
                    sv = sv.mean(axis=1)
                self._importance = np.abs(sv).mean(axis=0)
                return self._importance
            except Exception:
                pass  # 降级到朴素重要性

        # 朴素路径：对每个特征 j，采样置零扰动，看 |Δpred| 均值
        rng = np.random.default_rng(self.seed)
        idx = rng.integers(0, X_test.shape[0], size=self.n_perturb)
        base = preds[idx]
        scores = np.zeros(self.n_features)
        for j in range(self.n_features):
            Xp = X_test[idx].copy()
            Xp[:, j] = 0.0  # 置零扰动
            pp = np.asarray(self.model.predict(Xp), dtype=float)
            scores[j] = float(np.mean(np.abs(pp - base)))
        self._importance = scores
        return scores

    def top_k(self, k: int | None = None) -> List[Tuple[str, float]]:
        """按 |贡献度| 降序取前 k 个 (特征名, 贡献度)。"""
        if self._importance is None:
            raise ValueError("请先调用 importance()")
        if k is None:
            k = self.shap_top_k
        order = np.argsort(-np.abs(self._importance))[:k]
        return [(self.feature_names[j], float(self._importance[j])) for j in order]

    def to_chart_data(self, k: int | None = None) -> Tuple[List[str], List[float]]:
        """输出 (labels, values) 供 UI 渲染 bar chart（前 k 特征）。"""
        pairs = self.top_k(k)
        return [p[0] for p in pairs], [round(p[1], 6) for p in pairs]
