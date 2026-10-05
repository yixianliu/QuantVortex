"""M4.1 CTA 策略验收"""
from __future__ import annotations
import sys, os
import pandas as pd
import numpy as np
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy.cta.dual_thrust import DualThrust

def test_dual_thrust():
    n = 30
    df = pd.DataFrame({
        "high": np.cumsum(np.random.randn(n)) + 100,
        "low": np.cumsum(np.random.randn(n)) + 99,
        "close": np.cumsum(np.random.randn(n)) + 99.5,
    })
    strat = DualThrust(n=10)
    sig = strat.generate_signals(df)
    assert len(sig) == n
    print("test_strategies_cta.py 全绿")

if __name__=="__main__":
    test_dual_thrust()
