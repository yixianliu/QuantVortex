"""M5.5 GARCH(1,1) 波动率模型基本功能测试"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import numpy as np
from futures_quant.ai.garch import GARCH

def test_garch():
    # 生成一些假设的收益率数据
    np.random.seed(42)
    returns = np.random.normal(0, 0.01, 1000)  # 均值为零，标准差为0.01的收益率
    
    model = GARCH(p=1, q=1)
    model.fit(returns)
    
    # 预测未来5天的波动率
    sigma2, sigma, ci = model.forecast(horizon=5)
    assert sigma2.shape == (5,)
    assert sigma.shape == (5,)
    assert ci.shape == (5, 2)
    # 检查方差和波动率为正
    assert np.all(sigma2 > 0)
    assert np.all(sigma > 0)
    # 检查置信区间下界 <= 0 <= 上界（因为均值为零）
    assert np.all(ci[:, 0] <= 0) and np.all(ci[:, 1] >= 0)
    
    # 测试更新
    model.update(0.02)
    # 再次预测以确保更新后仍能工作
    sigma2_up, sigma_up, ci_up = model.forecast(horizon=1)
    assert sigma2_up.shape == (1,)
    
    print("test_garch.py 全绿")

if __name__ == "__main__":
    test_garch()