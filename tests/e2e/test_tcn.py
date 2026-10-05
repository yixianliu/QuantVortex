"""M5.3 TCN 基本功能测试"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import numpy as np
from futures_quant.ai.tcn import TemporalConvNet

def test_tcn_forward():
    # 创建一个小的 TCN
    num_inputs = 4
    num_channels = [3, 3, 3]
    tcn = TemporalConvNet(num_inputs=num_inputs, num_channels=num_channels, kernel_size=2, seed=42)
    # 生成随机输入
    seq_len = 10
    X = np.random.randn(1, seq_len, num_inputs)  # 单样本
    out = tcn.predict(X)  # shape: (1,)
    assert out.shape == (1,)
    # 多样本
    X2 = np.random.randn(5, seq_len, num_inputs)
    out2 = tcn.predict(X2)
    assert out2.shape == (5,)
    print("test_tcn.py 全绿")

if __name__ == "__main__":
    test_tcn_forward()