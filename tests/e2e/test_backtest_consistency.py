"""M2.6 向量化与事件驱动回测一致性验收"""
from __future__ import annotations
import sys, os
from datetime import datetime
import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.config.settings import Config
from futures_quant.backtest.backtester import Backtester

class SimpleFeed:
    def get_history(self, symbol, start, end, period):
        n = 200
        dates = pd.date_range(start="2026-01-01", periods=n, freq="D")
        price = 100 + np.cumsum(np.random.randn(n) * 0.5)
        df = pd.DataFrame({
            "datetime": dates,
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price + np.random.randn(n) * 0.1,
            "volume": 1000,
            "open_interest": 500
        })
        # 生成一个简单的信号列便于向量化路径
        df["signal"] = np.where(df["close"].diff() > 0, 1, -1)
        df["signal"].fillna(0, inplace=True)
        return df

def test_consistency():
    np.random.seed(0)
    cfg = Config()
    feed = SimpleFeed()
    bt_event = Backtester(cfg, feed, mode="event")
    bt_vec = Backtester(cfg, feed, mode="vectorized")
    # 事件驱动
    res_event = bt_event.run(symbol="RB", start="2026-01-01", end="2026-06-30", period="D", warmup=5)
    # 向量化
    res_vec = bt_vec.run(symbol="RB", start="2026-01-01", end="2026-06-30", period="D", warmup=5)
    m_e = res_event["metrics"]
    m_v = res_vec["metrics"]
    # 指标差异 <0.5%
    for k in ["total_return","sharpe","max_drawdown","win_rate"]:
        v_e = m_e.get(k)
        v_v = m_v.get(k)
        if v_e is None or v_v is None:
            continue
        diff = abs(v_e - v_v) / (abs(v_e)+1e-9)
        assert diff < 0.005, f"{k} 差异 {diff}"
    print("向量化与事件驱动一致性通过")

if __name__=="__main__":
    test_consistency()
    print("test_backtest_consistency.py 全绿")
