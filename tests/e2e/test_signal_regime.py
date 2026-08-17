"""策略信号 · 行情状态感知回归测试（锁定 regime-aware 加权，⑦ 的下一层）。

验证：
  1. regime_of 对趋势行情估值 > 对震荡行情估值；
  2. 类型匹配单调性：趋势型在趋势行情权重更高、反转型在震荡行情权重更高；
  3. 集成融合：强趋势行情下，趋势型策略(+1)的权重应压过反转型(-1)，净 bias 偏正。
纯函数级 + 一次 latest_signal_for 集成校验，不触碰回测引擎。
"""
from __future__ import annotations

import os
import sys
import math

_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

import pandas as pd
from futures_quant.strategy import auto_evolve as ae


def _df(vals):
    return pd.DataFrame({"close": vals, "high": [v + 1 for v in vals],
                         "low": [v - 1 for v in vals]})


def main() -> None:
    trend = [100 + i * 0.5 for i in range(60)] + [100 + 30 + 5]
    rng = [100 + 4 * math.sin(i / 3) for i in range(61)]
    rt, rr = ae.regime_of(trend), ae.regime_of(rng)
    assert rt > rr, f"regime 趋势({rt}) 应 > 震荡({rr})"

    # 类型匹配单调性
    assert ae._gene_regime_match("donchian_break", 1.0) > \
        ae._gene_regime_match("donchian_break", 0.0)
    assert ae._gene_regime_match("rsi_reversal", 0.0) > \
        ae._gene_regime_match("rsi_reversal", 1.0)

    gene_d = {"entry": "donchian_break", "params": {"period": 20}}
    gene_r = {"entry": "rsi_reversal", "params": {"period": 14, "low": 30, "high": 70}}
    orig = ae.load_profitable
    ae.load_profitable = lambda: [
        {"symbol": "X", "gene": gene_d, "fitness": 1.0,
         "metrics": {"sharpe": 0.4, "win_rate": 0.5}},
        {"symbol": "X", "gene": gene_r, "fitness": 1.0,
         "metrics": {"sharpe": 0.4, "win_rate": 0.5}},
    ]
    try:
        res = ae.latest_signal_for("X", _df(trend))
    finally:
        ae.load_profitable = orig

    assert res["bias"] > 0, f"趋势行情 bias 应偏正，实际 {res['bias']}"
    print("PASS: 行情状态感知加权（regime 估计 + 类型匹配 + 集成融合）")
    print(f"      regime 趋势={rt:.2f} 震荡={rr:.2f} | bias@趋势={res['bias']:.3f}")


if __name__ == "__main__":
    main()
