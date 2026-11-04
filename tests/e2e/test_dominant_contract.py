"""M3.1 主力合约动态识别验收"""
from __future__ import annotations
import sys, os
import pandas as pd
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)
from futures_quant.data.dominant import identify_dominant

def test_identify_dominant():
    data = {
        "date": ["2026-01-01","2026-01-01","2026-01-01","2026-01-02","2026-01-02","2026-01-02"],
        "contract": ["rb2401","rb2405","rb2409","rb2401","rb2405","rb2409"],
        "volume": [1000,2000,1500,500,800,1200],
        "open_interest": [3000,4000,2000,1500,2500,3500],
    }
    df = pd.DataFrame(data)
    mapping = identify_dominant(df, "rb")
    assert mapping[pd.Timestamp("2026-01-01")] == "rb2405"
    assert mapping[pd.Timestamp("2026-01-02")] == "rb2409"
    print("test_dominant_contract.py 全绿")

if __name__=="__main__":
    test_identify_dominant()
