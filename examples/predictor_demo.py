"""市场预测模块演示与自校验。

用法：
    python examples/predictor_demo.py

演示 Predictor 在三种行情模式下的趋势分析与预测输出，并对关键不变量做断言：
    - 预测长度 == horizon
    - 置信带下沿 <= 中枢 <= 上沿
    - 方向为 看涨/看跌/震荡 之一
    - 无 NaN / 无负值
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from futures_quant.data.synthetic import generate_bars
from futures_quant.analytics import Predictor


def _check(name: str, res) -> None:
    assert res.forecast, f"[{name}] 预测为空"
    assert len(res.forecast) == len(res.upper) == len(res.lower), f"[{name}] 长度不一致"
    for lo, fc, hi in zip(res.lower, res.forecast, res.upper):
        assert lo <= fc + 1e-6 <= hi + 1e-6, f"[{name}] 置信带顺序错误"
        assert lo > 0 and fc > 0 and hi > 0, f"[{name}] 出现非正价格"
    assert res.direction in ("看涨", "看跌", "震荡"), f"[{name}] 方向非法: {res.direction}"
    assert 0.0 <= res.confidence <= 1.0, f"[{name}] 置信度越界: {res.confidence}"
    assert all(v == v for v in res.metrics.values()), f"[{name}] 指标含 NaN"
    print(f"  [OK] {name}: 方向={res.direction} 目标={res.target_price:,.2f} "
          f"置信度={res.confidence:.0%} 趋势强度={res.trend_strength:+.2f} "
          f"R²={res.metrics['r_squared']}")


def main() -> None:
    print("=== 市场预测模块演示 ===")
    pred = Predictor()
    for mode in ("trend", "range", "mixed"):
        df = generate_bars(symbol="PRED.SHFE", mode=mode, n=300, seed=7)
        res = pred.predict(
            df["close"].tolist(), df["high"].tolist(), df["low"].tolist(),
            df["datetime"].tolist(), horizon=20, lookback=120, freq="1min")
        print(f"\n--- 模式: {mode} ---")
        print(res.summary)
        _check(mode, res)
    print("\n全部自校验通过 ✅")


if __name__ == "__main__":
    main()
