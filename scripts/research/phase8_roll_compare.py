"""第 2 期 P0-3 对照实验：自然月近似换月 vs 真实主力换月。

用法（每次只跑一个品种，单次联网 ≤ 3 分钟）：
    python scripts/research/phase8_roll_compare.py --product rb --start 2024-01-01 --end 2026-09-30

说明：
- 价格序列两路完全相同（本地日线缓存，离线、确定、可复现）；
- A 路：roll_schedule=None，走内核既有「每自然月首个交易日」近似换月；
- B 路：由 data/dominant_chain.build_roll_schedule 生成真实主力换月日与手数；
- 主力连续价格已含换月跳空，故默认 roll_spread_mode=auto → 价差只报告不计权益，
  避免与连续价格跳空重复扣费；需要强制计费时传 --spread-mode charge。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_probe():
    """按路径载入 scripts/perf_probe.py，复用其离线日线 feed（与锚点同一口径）。"""
    path = ROOT / "scripts" / "perf_probe.py"
    spec = importlib.util.spec_from_file_location("perf_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _one_run(price_feed, symbol: str, start: str, end: str, schedule,
             spread_mode: str) -> dict:
    from futures_quant.backtest.backtester import Backtester
    from futures_quant.config.settings import Config
    from futures_quant.data.contract_specs import build_contract
    from futures_quant.strategy.trend_following import TrendFollowing

    cfg = Config()
    cfg.risk.non_trading_hours_block = False      # 与锚点口径一致
    cfg.backtest.enable_roll_cost = True
    cfg.backtest.roll_spread_mode = spread_mode
    bt = Backtester(cfg, price_feed)
    bt.add_contract(build_contract(symbol))
    bt.add_strategy(TrendFollowing(symbol=symbol))
    res = bt.run(symbol, start, end, "D", 60, roll_schedule=schedule)
    m = dict(res.get("metrics") or {})
    events = res.get("roll_events") or []
    return {
        "num_fills": m.get("num_fills"),
        "total_return": m.get("total_return"),
        "annual_return": m.get("annual_return"),
        "max_drawdown": m.get("max_drawdown"),
        "sharpe": m.get("sharpe"),
        "num_rolls": len(events),
        "roll_cost": res.get("total_roll_cost"),
        "roll_spread_reported": res.get("roll_spread_reported"),
        "basis": res.get("roll_cost_basis"),
        "roll_dates": [e["date"] for e in events],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True, help="品种字母段，如 rb / i")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--deadline", type=float, default=175.0, help="单次链抓取联网预算（秒）")
    ap.add_argument("--spread-mode", default="auto", choices=["auto", "charge", "report", "off"])
    ap.add_argument("--save", default="", help="可选：结果 JSON 保存路径")
    args = ap.parse_args()

    probe = _load_probe()
    price_feed = probe.LocalDailyFeed()

    from futures_quant.data.dominant_chain import build_roll_schedule
    from futures_quant.data.sina_feed import SinaFeed

    symbol = f"{args.product}.{probe.EXCHANGE_BY_CODE[args.product.upper()]}"
    t0 = time.time()
    schedule, stats = build_roll_schedule(
        SinaFeed(), args.product, args.start, args.end, deadline_s=args.deadline)
    build_s = round(time.time() - t0, 1)

    monthly = _one_run(price_feed, symbol, args.start, args.end, None, args.spread_mode)
    dominant = _one_run(price_feed, symbol, args.start, args.end, schedule, args.spread_mode)

    payload = {
        "product": args.product, "symbol": symbol,
        "window": [args.start, args.end],
        "roll_spread_mode": args.spread_mode,
        "chain": stats, "chain_elapsed_s": build_s,
        "monthly_approx": monthly, "real_dominant": dominant,
        "schedule": {str(k): v for k, v in schedule.items()},
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                                   encoding="utf-8")
        print(f"saved -> {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
