"""M2.5 绩效指标 Schema 验收"""
from __future__ import annotations
import math
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.core.metric_schema import compute_extended_metrics, build_monthly_heatmap, METRIC_KEYS

def test_compute_extended_metrics():
    equity_curve = [100000.0, 101000.0, 100500.0, 102000.0, 103000.0]
    trades = [{"pnl": 1000}, {"pnl": -500}, {"pnl": 1500}]
    out = compute_extended_metrics(equity_curve, trades, bars_per_year=252)
    # 检查关键指标存在且为数值
    for k in ["total_return_pct","annual_return_pct","volatility","sortino_ratio","max_drawdown_pct","calmar_ratio","win_rate","var_95_pct","cvar_95_pct","max_win_streak","max_loss_streak"]:
        assert k in out, f"缺失 {k}"
        assert isinstance(out[k], (float,int)), f"{k} 非数值"
    # 总收益率验证
    exp_ret = (103000/100000 - 1)*100
    assert abs(out["total_return_pct"] - exp_ret) < 1e-6
    # 月度热力图
    from datetime import datetime
    dates = [datetime(2026,1,i+1) for i in range(len(equity_curve))]
    hm = build_monthly_heatmap(equity_curve, dates)
    assert isinstance(hm, dict)
    print("compute_extended_metrics 通过")

def test_metric_keys_coverage():
    # 确保所有 key 可被 compute_extended_metrics 返回（空值允许）
    equity_curve = [1.0, 1.01]
    trades = [{"pnl": 0.01}]
    out = compute_extended_metrics(equity_curve, trades)
    for k in METRIC_KEYS:
        assert k in out, f"METRIC_KEYS 缺失输出 {k}"
    print("METRIC_KEYS 覆盖通过")

if __name__=="__main__":
    test_compute_extended_metrics()
    test_metric_keys_coverage()
    print("test_metric_schema.py 全绿")
