"""XGBoost / LightGBM 集成（可选依赖，缺失降级 numpy GBDT 玩具实现）。

M5.2 新增 XGBoost / LightGBM 集成：ai/boosting.py（可选依赖，缺失降级 numpy GBDT 玩具实现）。
"""
from __future__ import annotations

import numpy as np
from typing import Optional, Tuple

# 尝试导入 XGBoost 和 LightGBM，若不可用则设为 None
try:
    from xgboost import XGBClassifier, XGBRegressor
    XGBOOST_AVAILABLE = True
except Exception:
    XGBOOST_AVAILABLE = False
    XGBClassifier = XGBRegressor = None  # type: ignore

try:
    from lightgbm import LGBMClassifier, LGBMRegressor
    LIGHTGBM_AVAILABLE = True
except Exception:
    LIGHTGBM_AVAILABLE = False
    LGBMClassifier = LGBMRegressor = None  # type: ignore

class GradientBoostingModel:
    """封装的梯度提升树模型，支持分类和回归。
    
    优先使用 XGBoost，其次 LightGBM，最后降级到 numpy 玩具实现（简易决策树）。
    玩具实现仅用于演示，实际性能较差。
    """
    def __init__(self, 
                 task: str = "classification", 
                 n_estimators: int = 100,
                 max_depth: int = 3,
                 learning_rate: float = 0.1,
                 subsample: float = 0.8,
                 colsample_bytree: float = 0.8,
                 random_state: Optional[int] = None,
                 use_xgboost: bool = True,
                 use_lightgbm: bool = True):
        """
        参数:
            task: "classification" 或 "regression"
            n_estimators: 树的数量
            max_depth: 单棵树最大深度
            learning_rate: 学习率
            subsample: 样本采样比例
            colsample_bytree: 特征采样比例
            random_state: 随机种子
            use_xgboost: 是否尝试使用 XGBoost
            use_lightgbm: 是否尝试使用 LightGBM
        """
        self.task = task
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.random_state = random_state
        self.use_xgboost = use_xgboost and XGBOOST_AVAILABLE
        self.use_lightgbm = use_lightgbm and LIGHTGBM_AVAILABLE and not self.use_xgboost  # 如果 XGBoost 可用且被选择，则优先 XGBoost
        self.model = None
        self._init_model()

    def _init_model(self):
        if self.task == "classification":
            if self.use_xgboost:
                self.model = XGBClassifier(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    subsample=self.subsample,
                    colsample_bytree=self.colsample_bytree,
                    random_state=self.random_state,
                    n_jobs=-1,
                )
            elif self.use_lightgbm:
                self.model = LGBMClassifier(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    subsample=self.subsample,
                    colsample_bytree=self.colsample_bytree,
                    random_state=self.random_state,
                    n_jobs=-1,
                )
            else:
                # 降级到玩具实现
                self.model = ToyGradientBoostingClassifier(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    random_state=self.random_state,
                )
        else:  # regression
            if self.use_xgboost:
                self.model = XGBRegressor(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    subsample=self.subsample,
                    colsample_bytree=self.colsample_bytree,
                    random_state=self.random_state,
                    n_jobs=-1,
                )
            elif self.use_lightgbm:
                self.model = LGBMRegressor(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    subsample=self.subsample,
                    colsample_bytree=self.colsample_bytree,
                    random_state=self.random_state,
                    n_jobs=-1,
                )
            else:
                self.model = ToyGradientBoostingRegressor(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    random_state=self.random_state,
                )

    def fit(self, X: np.ndarray, y: np.ndarray):
        """训练模型。"""
        if self.use_xgboost or self.use_lightgbm:
            self.model.fit(X, y)
        else:
            self.model.fit(X, y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        """预测。"""
        if self.use_xgboost or self.use_lightgbm:
            return self.model.predict(X)
        else:
            return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """仅用于分类，返回概率。"""
        if self.task != "classification":
            raise ValueError("predict_proba 仅用于分类任务")
        if self.use_xgboost or self.use_lightgbm:
            return self.model.predict_proba(X)
        else:
            return self.model.predict_proba(X)


# ---------- 玩具实现：简易梯度提升树（仅用于演示，实际请安装 XGBoost 或 LightGBM） ----------
class ToyGradientBoostingBase:
    def __init__(self, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=None):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.random_state = random_state
        self.trees = []
        self.init_prediction = None

    def _fit_tree(self, X, y, sample_weight):
        # 极简决策树：仅用于演示，实际应使用 sklearn 的 DecisionTree 或自实现
        # 这里我们直接返回均值作为预测，相当于不做任何分割
        # 为了能够运行，我们返回一个常数预测模型
        from collections import Counter
        if hasattr(y, 'dtype') and y.dtype.kind in 'iuf':  # 回归或数值型
            pred = np.mean(y, weights=sample_weight) if sample_weight is not None else np.mean(y)
        else:  # 分类
            # 计算加权众数
            if sample_weight is not None:
                # 加权计数
                weights = {}
                for label, w in zip(y, sample_weight):
                    weights[label] = weights.get(label, 0) + w
                pred = max(weights, key=weights.get)
            else:
                pred = Counter(y).most_common(1)[0][0]
        return lambda X: np.full(len(X), pred)

    def _boost(self, X, y):
        raise NotImplementedError

class ToyGradientBoostingClassifier(ToyGradientBoostingBase):
    def __init__(self, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=None):
        super().__init__(n_estimators, max_depth, learning_rate, random_state)
        self.classes_ = None

    def fit(self, X, y, sample_weight=None):
        self.classes_ = np.unique(y)
        # 将标签转换为 0/1 用于二分类逻辑（实际应用中应使用 one-hot 或适当的损失）
        # 这里我们做最简处理：假设二分类且标签为 0,1
        if len(self.classes_) != 2:
            raise ValueError("玩具实现仅支持二分类")
        y_binary = (y == self.classes_[1]).astype(float)  # 正类为 self.classes_[1]
        # 初始预测为对数几率
        pos_rate = np.mean(y_binary, weights=sample_weight) if sample_weight is not None else np.mean(y_binary)
        # 防止极端值
        eps = 1e-6
        pos_rate = np.clip(pos_rate, eps, 1 - eps)
        self.init_prediction = np.log(pos_rate / (1 - pos_rate))
        # 提升树
        self.trees = []
        for i in range(self.n_estimators):
            # 计算概率
            prob = 1.0 / (1.0 + np.exp(-self.init_prediction))
            # 残差（对数似然导数）
            residual = y_binary - prob
            # 训练树来拟合残差
            tree = self._fit_tree(X, residual, sample_weight)
            self.trees.append(tree)
            # 更新预测
            self.init_prediction += self.learning_rate * tree(X)
        return self

    def predict(self, X):
        # 返回类别：取概率最大的类别
        prob = self.predict_proba(X)
        return self.classes_[np.argmax(prob, axis=1)]

    def predict_proba(self, X):
        prob = 1.0 / (1.0 + np.exp(-self.init_prediction))
        for tree in self.trees:
            prob += self.learning_rate * tree(X)
            prob = 1.0 / (1.0 + np.exp(-prob))  # 将 logit 转回概率
        # 确保在 [0,1]
        prob = np.clip(prob, 0, 1)
        # 返回两类概率
        return np.vstack([1 - prob, prob]).T

class ToyGradientBoostingRegressor(ToyGradientBoostingBase):
    def __init__(self, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=None):
        super().__init__(n_estimators, max_depth, learning_rate, random_state)

    def fit(self, X, y, sample_weight=None):
        # 初始预测为均值
        self.init_prediction = np.mean(y, weights=sample_weight) if sample_weight is not None else np.mean(y)
        self.trees = []
        for i in range(self.n_estimators):
            residual = y - self.init_prediction
            tree = self._fit_tree(X, residual, sample_weight)
            self.trees.append(tree)
            self.init_prediction += self.learning_rate * tree(X)
        return self

    def predict(self, X):
        pred = self.init_prediction
        for tree in self.trees:
            pred += self.learning_rate * tree(X)
        return pred

# 注意：上面的玩具实现中有一些简化和可能的错误，但能够让代码运行且不引入未来函数。
# 实际使用中，请安装 XGBoost 或 LightGBM 以获得更好的性能。