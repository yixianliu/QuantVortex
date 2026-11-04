"""M5.1 特征工程无未来函数验收"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import numpy as np
import pandas as pd
from futures_quant.ai.features import build_features

def test_features_no_lookahead():
    # 创建一个简单的价格序列，便于计算
    n = 150  # 足够长，以便测试窗口不足和足够的情况
    # 让价格线性增长，使得收益率恒定
    close = np.linspace(10, 20, n)  # 从10到20线性增长
    df = pd.DataFrame({
        'open': close,
        'high': close + 0.5,
        'low': close - 0.5,
        'close': close,
        'volume': np.ones(n) * 1000,
    }, index=pd.date_range(start='2026-01-01', periods=n, freq='1min'))
    
    # 计算全数据特征
    ind_full, F_full, feature_names = build_features(df, extended=True, symbol='TEST', period='1m')
    # 找到'ret'特征的索引
    ret_idx = feature_names.index('ret')
    
    # 选择两个时间点进行测试：一个在窗口不足时（t=50），一个在窗口足够时(t=130)
    for t in [50, 130]:
        # 使用仅截至t的数据（包括t）计算特征
        df_hist = df.iloc[:t+1]  # 注意：iloc的结束索引是 exclusive，所以我们要 t+1 来包括 t
        ind_hist, F_hist, _ = build_features(df_hist, extended=True, symbol='TEST', period='1m')
        # 特征矩阵的最后一行对应时间点 t（F 为 DataFrame）
        hist_value = F_hist.iloc[-1, ret_idx]
        # 全数据特征中对应时间点 t 的值（注意：全数据特征的行号与 df 的行号对应）
        full_value = F_full.iloc[t, ret_idx]
        # 两者应相等（因为我们只用了历史数据）
        assert np.isclose(hist_value, full_value, rtol=1e-6), \
            f"Lookahead detected at t={t}: hist={hist_value}, full={full_value}"
    
    print("test_features_no_lookahead.py 全绿")

if __name__ == "__main__":
    test_features_no_lookahead()