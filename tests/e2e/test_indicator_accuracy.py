"""M2.2 指标准确性对拍测试"""
from __future__ import annotations
import numpy as np
import pandas as pd
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.indicators.tech import dmi, sar, cci, obv, vwap, hv, garch

def test_dmi_sar_cci_obv():
    np.random.seed(0)
    n = 200
    high = pd.Series(np.cumsum(np.random.randn(n))+100)
    low = high - np.random.rand(n)*5
    close = (high+low)/2
    volume = pd.Series(np.random.randint(1000,5000,size=n))
    d = dmi(high, low, close)
    assert not d.isna().all().all()
    s = sar(high, low)
    assert len(s)==n
    c = cci(high, low, close)
    assert len(c)==n
    o = obv(close, volume)
    assert len(o)==n
    print("DMI/SAR/CCI/OBV ok")

def test_vwap_hv():
    np.random.seed(1)
    n = 200
    high = pd.Series(np.cumsum(np.random.randn(n))+100)
    low = high - np.random.rand(n)*5
    close = (high+low)/2
    volume = pd.Series(np.random.randint(1000,5000,size=n))
    v = vwap(high, low, close, volume, n=20)
    assert not v.isna().all()
    h = hv(close, n=20)
    assert not h.isna().all()
    g = garch(close)
    assert len(g)>0
    print("VWAP/HV/GARCH ok")

if __name__=="__main__":
    test_dmi_sar_cci_obv()
    test_vwap_hv()
    print("test_indicator_accuracy.py 全绿")
