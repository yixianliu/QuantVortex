"""M5.2 XGBoost/LightGBM 集成验收（使用玩具实现，因为可能未安装 XGBoost/LightGBM）"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import numpy as np
from futures_quant.ai.boosting import GradientBoostingModel

def test_boosting():
    # 创建一个简单的二分类数据集
    X = np.random.randn(100, 5)
    y = (X[:, 0] + X[:, 1] > 0).astype(int)  # 简单规则
    
    # 测试分类
    model_clf = GradientBoostingModel(task="classification", n_estimators=10, max_depth=3)
    model_clf.fit(X, y)
    preds = model_clf.predict(X)
    probs = model_clf.predict_proba(X)
    # 检查 preds 是一维且长度匹配
    assert preds.ndim == 1 and len(preds) == X.shape[0]
    # 检查 probs 形状为 (n_samples, 2)
    assert probs.ndim == 2 and probs.shape == (X.shape[0], 2)
    assert np.all((probs >= 0) & (probs <= 1))
    # 测试回归
    reg = GradientBoostingModel(task="regression", n_estimators=10, max_depth=3)
    reg.fit(X, y.astype(float))
    pred_reg = reg.predict(X)
    assert pred_reg.ndim == 1 and len(pred_reg) == X.shape[0]
    print("test_boosting.py 全绿")

if __name__ == "__main__":
    test_boosting()