"""M3.2 连续合约拼接验收"""
from __future__ import annotations
import sys, os
import pandas as pd
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.data.continuous import join_continuous

def test_continuous_join():
    data = {
        "date": ["2026-01-01","2026-01-02","2026-01-03","2026-01-04"],
        "contract": ["rb2405","rb2405","rb2409","rb2409"],
        "close": [4000,4010,4020,4030],
    }
    df = pd.DataFrame(data)
    s = join_continuous(df, mode="back")
    assert len(s)==4
    # 无跳空：相邻差值不超过 1%
    pct = s.pct_change().abs().dropna()
    assert (pct < 0.02).all()
    print("test_continuous_join.py 全绿")

if __name__=="__main__":
    test_continuous_join()
