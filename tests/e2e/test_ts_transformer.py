"""M5.4 TS-Transformer 基本功能测试"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import numpy as np

try:
    import torch
    TORCH_AVAILABLE = True
except Exception:
    TORCH_AVAILABLE = False

from futures_quant.ai.ts_transformer import TSWrapper

def test_ts_transformer():
    # 创建一个小的数据集
    seq_len = 10
    feature_size = 4
    n_samples = 20
    X = np.random.randn(n_samples, seq_len, feature_size).astype(np.float32)
    y = (X[:, :, 0].sum(axis=1) > 0).astype(np.float32)  # 简单规则

    model = TSWrapper(feature_size=feature_size, seq_len=seq_len, epochs=2)
    model.fit(X, y)
    preds = model.predict(X)
    assert preds.shape == (n_samples,)
    # 检查预测值在合理范围内（对于回归，这里我们只是检查形状）
    # 对于分类，我们可能想检查是否是0或1，但这里我们使用了MSE loss，所以输出是连续的
    # 我们只确保没有NaN
    assert not np.isnan(preds).any()
    print("test_ts_transformer.py 全绿")

if __name__ == "__main__":
    test_ts_transformer()