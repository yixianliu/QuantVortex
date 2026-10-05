"""Performance Baseline

对比项：
1. Indicator cache hit vs cold run
2. LSTM predict_batch vs loop predict_last

Output: tests/e2e/perf_baseline.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def make_df(n: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    base = np.cumsum(rng.normal(0, 1, n)) + 10000
    return pd.DataFrame({
        "open": base + rng.normal(0, 0.5, n),
        "high": base + rng.normal(0.5, 0.5, n),
        "low": base - rng.normal(0.5, 0.5, n),
        "close": base + rng.normal(0, 0.5, n),
        "volume": np.abs(rng.normal(1000, 200, n)).astype(int),
        "open_interest": np.abs(rng.normal(5000, 100, n)).astype(int),
    })


def bench_indicator(n: int = 6) -> dict[str, Any]:
    from futures_quant.indicators.tech import add_indicators
    from futures_quant.indicators.cache import IndicatorCache, get_instance

    df = make_df(5000)
    cache: IndicatorCache = get_instance()
    cache.clear()

    t0 = time.perf_counter()
    for _ in range(n):
        add_indicators(df.copy())
    cold_s = (time.perf_counter() - t0) / n

    # seed cache
    first = add_indicators(df.copy())
    cache.put("rb.SHFE", "D", "add_indicators", first)

    t0 = time.perf_counter()
    for _ in range(n):
        add_indicators(df.copy())
    warm_s = (time.perf_counter() - t0) / n

    stats = cache.stats()
    return {
        "cold_ms": round(cold_s * 1000, 2),
        "warm_ms": round(warm_s * 1000, 2),
        "speedup": round(cold_s / max(warm_s, 1e-6), 2),
        "cache_size": stats["size"],
    }


def bench_lstm(n: int = 5) -> dict[str, Any]:
    from futures_quant.ai.lstm import LSTM

    rng = np.random.default_rng(7)
    B, T, F = 512, 20, 7
    X = rng.normal(0, 1, (B, T, F)).astype(np.float32)
    model = LSTM(input_size=F, hidden_size=32, output_size=1, seed=7)
    model.predict_last(X[0])
    model.predict_batch(X[:8])

    t0 = time.perf_counter()
    for _ in range(n):
        _ = [model.predict_last(X[i]) for i in range(B)]
    loop_s = (time.perf_counter() - t0) / n

    t0 = time.perf_counter()
    for _ in range(n):
        _ = model.predict_batch(X)
    batch_s = (time.perf_counter() - t0) / n

    return {
        "samples": B,
        "loop_sec": round(loop_s, 4),
        "batch_sec": round(batch_s, 4),
        "speedup": round(loop_s / max(batch_s, 1e-6), 2),
    }


def bench_backtest(n: int = 1) -> dict[str, Any]:
    from futures_quant.data.synthetic import SyntheticFeed
    from futures_quant.core.engine import TradingEngine
    from futures_quant.config.settings import Config
    from futures_quant.strategy.trend_following import TrendFollowing
    from futures_quant.data.contract_specs import build_contract

    cfg = Config()
    feed = SyntheticFeed()
    df = feed.get_history("rb.SHFE", "2015-01-01", "2025-01-01", "D")
    if df is None or df.empty:
        return {"error": "no_synthetic_data"}

    contract = build_contract("rb.SHFE")

    engine = TradingEngine(cfg, mode="backtest")
    engine.add_contract(contract)
    engine.register_strategy(TrendFollowing(symbol="rb.SHFE"))

    t0 = time.perf_counter()
    for _ in range(n):
        engine.start()
        for _, r in df.iterrows():
            from futures_quant.core.types import Bar
            bar = Bar(
                symbol="rb.SHFE",
                datetime=pd.Timestamp(r["datetime"]),
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
                volume=float(r["volume"]), open_interest=float(r["open_interest"]),
            )
            engine.process_bar(bar)
    elapsed = (time.perf_counter() - t0) / n

    return {
        "bars": int(len(df)),
        "trades": int(len(engine.trades_log)),
        "elapsed_sec": round(elapsed, 3),
        "bars_per_sec": round(len(df) / max(elapsed, 1e-6), 1),
    }


def main() -> int:
    print("=" * 60)
    print("Performance Baseline")
    print("=" * 60)

    print("\n[1/3] Indicator cache ...")
    ind = bench_indicator()
    print(f"  cold={ind['cold_ms']}ms  warm={ind['warm_ms']}ms  "
          f"speedup={ind['speedup']}x")

    print("\n[2/3] LSTM batch predict ...")
    lstm = bench_lstm()
    print(f"  {lstm['samples']} samples  loop={lstm['loop_sec']}s  "
          f"batch={lstm['batch_sec']}s  speedup={lstm['speedup']}x")

    print("\n[3/3] Backtest throughput ...")
    bt = bench_backtest()
    if "error" in bt:
        print(f"  skip: {bt['error']}")
        bt = {"bars": 0, "trades": 0, "bars_per_sec": 0}
    else:
        print(f"  {bt['bars']} bars  {bt['trades']} trades  "
              f"{bt['bars_per_sec']} bars/s")

    result = {
        "timestamp": pd.Timestamp.now().isoformat(timespec="seconds"),
        "indicator": ind,
        "lstm": lstm,
        "backtest": bt,
    }
    out = os.path.join(HERE, "perf_baseline.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[done] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())