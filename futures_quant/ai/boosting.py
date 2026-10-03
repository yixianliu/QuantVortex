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
        # M3-06：回归基线值 / 分类基线 logit（保持标量，避免与 trees 重复累加）
        self.base_value = 0.0
        self.base_logit = 0.0

    # ---- M3-06：加权均值修正 ----
    # `np.mean(y, weights=...)` 是**不存在的**关键字（np.mean 只有 a/axis/dtype/out/
    # keepdims/where），一旦 sample_weight 非 None 就直接 TypeError；而 np.average
    # 原生支持 weights。三处调用统一改为 _wmean。
    @staticmethod
    def _wmean(y, sample_weight=None) -> float:
        """加权均值（sample_weight 为 None 时退化为普通均值）。"""
        y = np.asarray(y, dtype=float)
        if sample_weight is None:
            return float(np.mean(y)) if len(y) else 0.0
        w = np.asarray(sample_weight, dtype=float)
        if len(y) == 0 or float(w.sum()) <= 0:
            return float(np.mean(y)) if len(y) else 0.0
        return float(np.average(y, weights=w))

    def _leaf_value(self, y, sample_weight=None):
        """叶节点预测值：回归=加权均值；分类=加权众数。"""
        y = np.asarray(y)
        if y.dtype.kind in "iuf":
            return self._wmean(y, sample_weight)
        from collections import Counter
        if sample_weight is not None:
            weights = {}
            for label, w in zip(y, sample_weight):
                weights[label] = weights.get(label, 0.0) + float(w)
            return max(weights, key=weights.get) if weights else 0
        return Counter(y).most_common(1)[0][0] if len(y) else 0

    def _best_split(self, X, y, sample_weight):
        """在 (特征, 阈值) 上搜索使加权不纯度下降最大的切分（1 层决策树）。

        切分准则：回归用**加权方差下降**，分类用**加权 Gini 下降**。
        候选阈值取每个特征的分位数（最多 16 个），保证 O(n_feat × 16 × n)。
        找不到有效切分（如所有取值相同）时返回 None → 退化为常数叶。
        """
        X = np.asarray(X, dtype=float)
        y = np.asarray(y)
        n, n_feat = X.shape
        if sample_weight is None:
            sample_weight = np.ones(n, dtype=float)
        else:
            sample_weight = np.asarray(sample_weight, dtype=float)
        is_reg = y.dtype.kind in "iuf"
        if is_reg:
            base = float(np.average((y - np.average(y, weights=sample_weight)) ** 2,
                                    weights=sample_weight))
        else:
            base = _gini(y, sample_weight)
        if n < 4:
            return None
        best = None
        for j in range(n_feat):
            col = X[:, j]
            qs = np.unique(np.quantile(col, np.linspace(0.05, 0.95, 16)))
            for thr in qs:
                left = col <= thr
                nl, nr = int(left.sum()), int((~left).sum())
                if nl < 2 or nr < 2:
                    continue
                yl, yr = y[left], y[~left]
                wl, wr = sample_weight[left], sample_weight[~left]
                if is_reg:
                    ml, mr = self._wmean(yl, wl), self._wmean(yr, wr)
                    imp = (float(np.average((yl - ml) ** 2, weights=wl)) * wl.sum()
                           + float(np.average((yr - mr) ** 2, weights=wr)) * wr.sum())
                else:
                    imp = (_gini(yl, wl) * wl.sum() + _gini(yr, wr) * wr.sum())
                imp = imp / max(sample_weight.sum(), 1e-12)
                gain = base - float(imp)
                if best is None or gain > best[0]:
                    best = (float(gain), int(j), float(thr))
        # 增益必须为正且显著，否则退化为常数叶（避免在无信息特征上过拟合噪声）
        if best is None or best[0] <= 1e-12:
            return None
        return best[1], best[2]

    def _fit_tree(self, X, y, sample_weight):
        """拟合一棵**真实做阈值分裂**的树（至少 1 层）。

        旧实现无论输入什么都返回常数（"直接返回均值作为预测，相当于不做任何分割"），
        导致整个 GBDT 的每一轮都只是给常数加一个常数 —— 等价于"预测训练集均值"，
        在模型对比里与 Ridge 的 MAE 差异只来自常数基线不同，毫无学习可言。
        """
        X = np.asarray(X, dtype=float)
        y = np.asarray(y)
        split = self._best_split(X, y, sample_weight)
        if split is None:
            const = self._leaf_value(y, sample_weight)
            return lambda Z: np.full(len(np.asarray(Z)), const)
        j, thr = split
        left_mask = X[:, j] <= thr
        lv = self._leaf_value(y[left_mask],
                              None if sample_weight is None else np.asarray(sample_weight)[left_mask])
        rv = self._leaf_value(y[~left_mask],
                              None if sample_weight is None else np.asarray(sample_weight)[~left_mask])

        def _predict(Z):
            """处理predict。

                参数:
                    Z"""
            Z = np.asarray(Z, dtype=float)
            m = Z[:, j] <= thr
            out = np.empty(len(Z), dtype=float)
            out[m] = lv
            out[~m] = rv
            return out

        return _predict

    def _boost(self, X, y):
        raise NotImplementedError


def _gini(y, sample_weight=None) -> float:
    """加权 Gini 不纯度（越小越纯）。"""
    y = np.asarray(y)
    n = len(y)
    if n == 0:
        return 0.0
    if sample_weight is None:
        _, cnt = np.unique(y, return_counts=True)
        p = cnt / n
    else:
        w = np.asarray(sample_weight, dtype=float)
        tot = w.sum()
        if tot <= 0:
            _, cnt = np.unique(y, return_counts=True)
            p = cnt / n
        else:
            labels = np.unique(y)
            p = np.array([w[y == lb].sum() for lb in labels]) / tot
    return float(1.0 - np.sum(p ** 2))

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
        # 初始预测为对数几率（**标量基线**）
        pos_rate = self._wmean(y_binary, sample_weight)
        # 防止极端值
        eps = 1e-6
        pos_rate = np.clip(pos_rate, eps, 1 - eps)
        self.base_logit = float(np.log(pos_rate / (1 - pos_rate)))
        self.init_prediction = self.base_logit
        # M3-06：旧实现把累积结果写回 `init_prediction`，而 predict 又从
        # `init_prediction` 起把 trees 再加一遍 → **每棵树都被算了两遍**，
        # 预测值系统性翻倍。改为基线保持标量、显式维护 logits 轨迹。
        logits = np.full(len(y), self.base_logit, dtype=float)
        self.trees = []
        for _ in range(self.n_estimators):
            prob = 1.0 / (1.0 + np.exp(-logits))
            residual = y_binary - prob          # 对数似然的一阶梯度
            tree = self._fit_tree(X, residual, sample_weight)
            self.trees.append(tree)
            logits = logits + self.learning_rate * tree(X)
        return self

    def _logit(self, X) -> np.ndarray:
        """基线 logit + 各树加权贡献（每棵树只算一次）。"""
        X = np.asarray(X, dtype=float)
        z = np.full(len(X), float(self.base_logit), dtype=float)
        for tree in self.trees:
            z = z + self.learning_rate * tree(X)
        return z

    def predict(self, X):
        # 返回类别：取概率最大的类别
        prob = self.predict_proba(X)
        return self.classes_[np.argmax(prob, axis=1)]

    def predict_proba(self, X):
        prob = 1.0 / (1.0 + np.exp(-self._logit(X)))
        prob = np.clip(prob, 0.0, 1.0)
        return np.vstack([1 - prob, prob]).T

class ToyGradientBoostingRegressor(ToyGradientBoostingBase):
    def __init__(self, n_estimators=100, max_depth=3, learning_rate=0.1, random_state=None):
        super().__init__(n_estimators, max_depth, learning_rate, random_state)

    def fit(self, X, y, sample_weight=None):
        # 初始预测为均值（**标量基线**，训练期单独维护 preds 轨迹）
        y = np.asarray(y, dtype=float)
        self.base_value = self._wmean(y, sample_weight)
        self.init_prediction = self.base_value
        preds = np.full(len(y), float(self.base_value), dtype=float)
        self.trees = []
        for _ in range(self.n_estimators):
            residual = y - preds
            tree = self._fit_tree(X, residual, sample_weight)
            self.trees.append(tree)
            preds = preds + self.learning_rate * tree(X)
        return self

    def predict(self, X):
        # M3-06：基线 + 各树加权贡献，每棵树只算一次（旧实现重复累加）
        X = np.asarray(X, dtype=float)
        pred = np.full(len(X), float(self.base_value), dtype=float)
        for tree in self.trees:
            pred = pred + self.learning_rate * tree(X)
        return pred

# M3-06 后记：玩具实现已能「真学习」（真实阈值分裂 + 正确的累加语义），但仍只支持
# 1 层分裂、无正则与早停，仅作无第三方库时的降级路径。
# 实际使用中，请安装 XGBoost 或 LightGBM 以获得更好的性能。