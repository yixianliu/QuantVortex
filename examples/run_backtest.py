"""回测示例：用合成行情验证 5 套策略 + 风控 + 引擎全链路。

运行：
    python examples/run_backtest.py

说明：合成行情仅用于验证程序逻辑，不代表真实市场表现。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from futures_quant.backtest.backtester import Backtester
from futures_quant.config.settings import Config
from futures_quant.data.base import Contract
from futures_quant.data.synthetic import SyntheticFeed, generate_bars
from futures_quant.strategy.breakout import Breakout
from futures_quant.strategy.grid import Grid
from futures_quant.strategy.martingale import Martingale
from futures_quant.strategy.mean_reversion import MeanReversion
from futures_quant.strategy.trend_following import TrendFollowing
from futures_quant.utils.logger import get_logger

PLANS = [
    ("趋势跟踪", "trend.SHFE", TrendFollowing, {}),
    ("突破交易", "trend.SHFE", Breakout, {}),
    ("网格交易", "range.SHFE", Grid, {}),
    ("均值回归", "range.SHFE", MeanReversion, {}),
    ("马丁策略", "mixed.SHFE", Martingale, {}),
]


def build_feed() -> SyntheticFeed:
    feed = SyntheticFeed()
    feed._cache[("trend.SHFE", "1m")] = generate_bars(symbol="trend.SHFE", mode="trend", n=20000, seed=7)
    feed._cache[("range.SHFE", "1m")] = generate_bars(symbol="range.SHFE", mode="range", n=20000, seed=11)
    feed._cache[("mixed.SHFE", "1m")] = generate_bars(symbol="mixed.SHFE", mode="mixed", n=20000, seed=23)
    return feed


def make_contract(sym: str) -> Contract:
    return Contract(
        symbol=sym, exchange="SHFE", multiplier=10, min_price_tick=1.0,
        margin_rate=0.10, commission_per_lot=3.0, trading_hours=[],
    )


def main() -> None:
    log = get_logger("backtest_example")
    cfg = Config.load(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.json"))
    feed = build_feed()
    out_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_root, exist_ok=True)

    print("=" * 72)
    print("期货策略回测示例（合成行情验证）")
    print("=" * 72)
    summary = []
    for name, sym, cls, params in PLANS:
        bt = Backtester(cfg, feed, logger=log)
        bt.add_contract(make_contract(sym))
        bt.add_strategy(cls(sym, params))
        out = bt.run(sym, "2024-01-01", "2024-12-31", period="1m", warmup=60)
        files = bt.export(outdir=out_root, prefix=name)
        m = out["metrics"]
        summary.append((name, m))
        print(f"\n--- {name} @ {sym} ---")
        for k, v in m.items():
            print(f"  {k:>18}: {v}")
        print(f"  导出: {files['summary']}")

    print("\n" + "=" * 72)
    print("汇总（总收益 / 夏普 / 最大回撤 / 胜率 / 成交数）")
    print("=" * 72)
    for name, m in summary:
        tr = m.get("total_return")
        sh = m.get("sharpe")
        dd = m.get("max_drawdown")
        wr = m.get("win_rate")
        nf = m.get("num_fills")
        print(f"  {name:<8} 收益 {tr if tr is None else f'{tr:.2%}'} | "
              f"夏普 {sh} | 回撤 {dd if dd is None else f'{dd:.2%}'} | "
              f"胜率 {wr if wr is None else f'{wr:.2%}'} | 成交 {nf}")


if __name__ == "__main__":
    main()
