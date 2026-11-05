"""第 3 期：回测规模化 / 参数维度 / 可追溯 的实测脚本（只读 + 临时产物）。

三个部分：
    A. 锚点等价：旧路径（直接 Backtester）与新路径（runner + BacktestConfig）
       必须指标逐位相同、逐笔成交摘要相同；
    B. 规模实测：N 品种 × M 组合 × K 根 bar 的耗时与峰值内存，
       「改造前」= 把所有完整结果留在内存（naive），
       「改造后」= 边算边汇总 + 摘要上限 + Top-K（streaming）；
    C. 可复现：同一配置落库后按 run_id 复跑，校验结果摘要一致。

运行：
    python scripts/research/phase9_backtest_scale.py
产物：
    outputs/phase9_backtest_scale.json
    outputs/phase9_sweep_spool.jsonl（超限摘要落盘示例）
"""
from __future__ import annotations

import gc
import json
import os
import sys
import time
import tracemalloc
from typing import Any, Callable, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import psutil  # noqa: E402

from futures_quant.backtest import runner  # noqa: E402
from futures_quant.backtest.backtester import Backtester  # noqa: E402
from futures_quant.backtest.run_config import BacktestConfig  # noqa: E402
from futures_quant.backtest.sweep import SweepLimits, run_sweep  # noqa: E402
from futures_quant.backtest.trace import trades_digest  # noqa: E402
from futures_quant.config.settings import Config  # noqa: E402
from futures_quant.data.contract_specs import build_contract  # noqa: E402
from futures_quant.strategy.trend_following import TrendFollowing  # noqa: E402

import perf_probe  # noqa: E402  (复用其离线日线 Feed 与锚点常量)

OUT_DIR = os.path.join(ROOT, "outputs")
FEED = perf_probe.LocalDailyFeed()
PROC = psutil.Process()


def _rss_mb() -> float:
    return PROC.memory_info().rss / (1024 * 1024)


def _anchor_cfg(symbol: str, end: str) -> BacktestConfig:
    """锚点配置：warmup=60 + 非交易时段不阻断 + 含移仓成本。"""
    cfg = Config()
    cfg.risk.non_trading_hours_block = perf_probe.ANCHOR_BLOCK
    cfg.backtest.enable_roll_cost = perf_probe.ANCHOR_ROLL
    return BacktestConfig.from_settings(
        cfg, symbol=symbol, start=perf_probe.START, end=end, period="D",
        warmup=perf_probe.ANCHOR_WARMUP, strategy_name="trend_following",
        strategy_params={}, notes="anchor-equivalence",
    )


def _direct_anchor(symbol: str, end: str) -> Dict[str, Any]:
    """旧路径：与 perf_probe/_run_anchor 完全一致的构造方式。"""
    cfg = Config()
    cfg.risk.non_trading_hours_block = perf_probe.ANCHOR_BLOCK
    cfg.backtest.enable_roll_cost = perf_probe.ANCHOR_ROLL
    bt = Backtester(cfg, FEED)
    bt.add_contract(build_contract(symbol))
    bt.add_strategy(TrendFollowing(symbol=symbol))
    return bt.run(symbol, perf_probe.START, end, "D", perf_probe.ANCHOR_WARMUP)


def part_a_anchor() -> Dict[str, Any]:
    rows = []
    all_ok = True
    for code in ("rb.SHFE", "i.DCE"):
        for label, end in (("full_window", perf_probe.END),
                           ("anchor_window", perf_probe.ANCHOR_END)):
            old = _direct_anchor(code, end)
            new = runner.execute(_anchor_cfg(code, end), FEED)
            metrics_equal = all(
                old["metrics"].get(k) == new["metrics"].get(k)
                for k in perf_probe._ANCHOR_KEYS)
            digest_equal = trades_digest(old["trades"]) == trades_digest(new["trades"])
            ok = metrics_equal and digest_equal
            all_ok = all_ok and ok
            rows.append({
                "symbol": code,
                "window": label,
                "num_fills": new["metrics"].get("num_fills"),
                "trades_digest": new.get("trades_digest"),
                "metrics_equal": metrics_equal,
                "trades_digest_equal": digest_equal,
                "ok": ok,
            })
    ref = perf_probe.ANCHOR_REF
    rb_anchor = [r for r in rows if r["symbol"] == "rb.SHFE"
                 and r["window"] == "anchor_window"][0]
    i_full = [r for r in rows if r["symbol"] == "i.DCE"
              and r["window"] == "full_window"][0]
    return {
        "rows": rows,
        "all_ok": all_ok,
        "reference": {
            "rb_anchor_expected": ref["rb.SHFE"]["num_fills"],
            "rb_anchor_actual": rb_anchor["num_fills"],
            "i_full_expected": ref["i.DCE"]["num_fills"],
            "i_full_actual": i_full["num_fills"],
            "rb_full_actual": [r for r in rows if r["symbol"] == "rb.SHFE"
                               and r["window"] == "full_window"][0]["num_fills"],
        },
    }


def _k_window(k: int) -> Dict[str, Any]:
    """按目标 K 根 bar 反推起始日期；返回 start 与真实行数。"""
    df = FEED.get_history("rb.SHFE", perf_probe.START, perf_probe.END, "D")
    total = len(df)
    if k >= total:
        return {"start": perf_probe.START, "k": total}
    start = str(df["datetime"].iloc[total - k].date())
    view = FEED.get_history("rb.SHFE", start, perf_probe.END, "D")
    return {"start": start, "k": int(len(view))}


GRID = {"fast": [5, 10, 20], "slow": [30, 60], "stop_mult": [1.5, 2.5]}
SYMBOLS = ["rb.SHFE", "i.DCE", "cu.SHFE"]


def _naive_sweep(base_cfg: BacktestConfig, grid: dict, symbols: List[str],
                 should_abort: Any = None) -> List[Dict[str, Any]]:
    """改造前：每个组合的完整结果全部留在内存。"""
    from futures_quant.backtest.sweep import expand_grid
    out = []
    for symbol in symbols:
        for combo in expand_grid(grid):
            cfg = base_cfg.with_overrides(symbol=symbol, strategy_params=combo)
            out.append(runner.execute(cfg, FEED, should_abort=should_abort))
    return out


def _measure_memory(fn: Callable[[], Any]) -> Dict[str, Any]:
    """tracemalloc 峰值 + RSS 前后差（先用 gc 收干净）。"""
    gc.collect()
    rss_before = _rss_mb()
    tracemalloc.start()
    t0 = time.perf_counter()
    out = fn()
    elapsed = (time.perf_counter() - t0) * 1000.0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()
    rss_after = _rss_mb()
    return {"elapsed_ms_with_trace": round(elapsed, 1),
            "peak_traced_mb": round(peak / (1024 * 1024), 3),
            "rss_delta_mb": round(rss_after - rss_before, 3),
            "out": out}


def _time_round(fn: Callable[[], Any]) -> Dict[str, Any]:
    """计时一轮（tracemalloc 关闭），返回墙钟毫秒与输出。

    开发机存在其他会话/IDE 的负载尖峰，单次计时会被长尾拖偏；
    part_b 用「改造前/改造后交替、各取 3 轮最小值」的方式压低噪声。
    """
    gc.collect()
    t0 = time.perf_counter()
    out = fn()
    dt = (time.perf_counter() - t0) * 1000.0
    return {"ms": dt, "out": out}


def part_b_scale() -> Dict[str, Any]:
    rows = []
    spool_path = os.path.join(OUT_DIR, "phase9_sweep_spool.jsonl")
    for target_k in (800, 1600):
        win = _k_window(target_k)
        base = BacktestConfig.from_settings(
            Config(), symbol=SYMBOLS[0], start=win["start"], end=perf_probe.END,
            period="D", warmup=60, strategy_name="trend_following",
            strategy_params={}, notes="scale-probe")
        combos = len(GRID["fast"]) * len(GRID["slow"]) * len(GRID["stop_mult"])
        n_runs = combos * len(SYMBOLS)

        # ---- 内存：tracemalloc 峰值（与计时分开测，避免互相干扰） ----
        mem_naive = _measure_memory(lambda b=base: _naive_sweep(b, GRID, SYMBOLS))
        kept = len(mem_naive["out"])
        naive_retained_mb = round(
            len(json.dumps([r["metrics"] for r in mem_naive["out"]],
                           default=str).encode()) / (1024 * 1024), 3)
        naive_peak = mem_naive["peak_traced_mb"]
        naive_rss = mem_naive["rss_delta_mb"]
        del mem_naive["out"]

        limits = SweepLimits(max_summaries_in_memory=50, memory_budget_mb=8.0,
                             top_k=5)
        mem_stream = _measure_memory(lambda b=base, l=limits: run_sweep(
            FEED, b, GRID, symbols=SYMBOLS, limits=l))
        stream_peak = mem_stream["peak_traced_mb"]
        stream_rss = mem_stream["rss_delta_mb"]
        rep = mem_stream["out"]  # 保留本次输出，供保留条数/Top-K 等元数据
        del mem_stream["out"]

        # ---- 改造后（紧预算）：摘要超限落盘，证明内存不随组合数线性增长 ----
        tight = SweepLimits(max_summaries_in_memory=10, memory_budget_mb=0.05,
                            top_k=2, summary_sink=spool_path)
        mem_tight = _measure_memory(lambda b=base, l=tight: run_sweep(
            FEED, b, GRID, symbols=SYMBOLS, limits=l))
        tight_peak = mem_tight["peak_traced_mb"]
        tight_rss = mem_tight["rss_delta_mb"]
        tight_out = mem_tight["out"]
        del mem_tight["out"]

        # ---- 耗时：改造前/改造后交替 3 轮，各取最小值，压低负载尖峰影响 ----
        best_naive = {"ms": None, "engine": None}
        best_stream = {"ms": None, "engine": None}
        for _ in range(3):
            r_naive = _time_round(lambda b=base: _naive_sweep(b, GRID, SYMBOLS))
            eng_naive = sum(float(x.get("duration_ms") or 0.0)
                            for x in r_naive["out"])
            if best_naive["ms"] is None or r_naive["ms"] < best_naive["ms"]:
                best_naive = {"ms": r_naive["ms"], "engine": eng_naive}
            del r_naive

            r_stream = _time_round(lambda b=base, l=limits: run_sweep(
                FEED, b, GRID, symbols=SYMBOLS, limits=l))
            eng_stream = float(r_stream["out"].get("engine_ms_total") or 0.0)
            if best_stream["ms"] is None or r_stream["ms"] < best_stream["ms"]:
                best_stream = {"ms": r_stream["ms"], "engine": eng_stream}
            del r_stream

        time_naive = round(best_naive["ms"], 1)
        naive_engine_ms = round(best_naive["engine"], 1)
        time_stream = round(best_stream["ms"], 1)
        stream_engine_ms = round(best_stream["engine"], 1)

        rows.append({
            "target_k": target_k,
            "actual_k": win["k"],
            "start": win["start"],
            "symbols": len(SYMBOLS),
            "combos": combos,
            "runs": n_runs,
            # 改造前
            "naive_elapsed_ms": time_naive,
            "naive_engine_ms_total": naive_engine_ms,
            "naive_peak_traced_mb": naive_peak,
            "naive_rss_delta_mb": naive_rss,
            "naive_full_results_kept": kept,
            "naive_metrics_json_mb": naive_retained_mb,
            # 改造后
            "stream_elapsed_ms": time_stream,
            "stream_engine_ms_total": stream_engine_ms,
            "stream_peak_traced_mb": stream_peak,
            "stream_rss_delta_mb": stream_rss,
            "stream_retained_summaries": rep["retained"],
            "stream_spooled": rep["spooled"],
            "stream_dropped": rep["dropped"],
            "stream_top_k": len(rep["top"]),
            "stream_summary_peak_bytes": rep["summary_bytes_peak"],
            # 紧预算
            "tight_peak_traced_mb": tight_peak,
            "tight_rss_delta_mb": tight_rss,
            "tight_retained": tight_out["retained"],
            "tight_spooled": tight_out["spooled"],
            "all_ok_sample": bool(rep["run_count"] == n_runs),
        })
        del rep
    return {"rows": rows, "spool_path": spool_path}


def part_c_replay(tmp_db: str) -> Dict[str, Any]:
    """同一配置落库 + 按 run_id 复跑校验（临时库，不碰生产库）。"""
    from futures_quant.storage.backtest_store import BacktestStore

    cfg = _anchor_cfg("rb.SHFE", perf_probe.END)
    result = runner.execute(cfg, FEED)
    store = BacktestStore(tmp_db)
    store.save_run(runner.record_from_result(result))
    replay = runner.replay_run(store, result["run_id"], FEED)
    attempts = (store.get_run(result["run_id"]) or {}).get("attempts")
    store.close()
    return {
        "run_id": result["run_id"],
        "params_hash": result["params_hash"],
        "data_fingerprint": result["data_fingerprint_short"],
        "result_hash": result["result_hash"],
        "trades_digest": result["trades_digest"],
        "replay_ok": replay["ok"],
        "checks": replay["checks"],
        "attempts_after_replay": attempts,
        "db": tmp_db,
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="第 3 期规模化/可追溯实测")
    ap.add_argument("--db", default="",
                    help="落库复跑使用的库路径；默认用 outputs 下的临时库。"
                         "传 data/quant_backtest.db 可在生产库建表（会自动备份）")
    ap.add_argument("--only-replay", action="store_true",
                    help="只执行 C 段（落库 + 复跑校验），跳过耗时的规模实测")
    args = ap.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    tmp_db = args.db or os.path.join(OUT_DIR, "_phase9_replay.db")
    if not args.db:
        for p in (tmp_db, tmp_db + "-wal", tmp_db + "-shm"):
            if os.path.exists(p):
                os.remove(p)

    a: Dict[str, Any] = {"rows": [], "all_ok": True}
    b: Dict[str, Any] = {"rows": [], "spool_path": ""}
    if not args.only_replay:
        print("=" * 70)
        print("A. 锚点等价（旧路径 vs 新路径）")
        a = part_a_anchor()
        for r in a["rows"]:
            print(f"  {r['symbol']:<8} {r['window']:<14} fills={r['num_fills']:<4} "
                  f"metrics_equal={r['metrics_equal']} digest_equal={r['trades_digest_equal']}")
        print(f"  reference: {a['reference']}")
        print(f"  all_ok: {a['all_ok']}")

        print("=" * 70)
        _m = len(GRID["fast"]) * len(GRID["slow"]) * len(GRID["stop_mult"])
        print(f"B. 规模实测（N={len(SYMBOLS)} 品种, M={_m} 组合, K=800/1600）")
        b = part_b_scale()
        for r in b["rows"]:
            print(f"  K={r['actual_k']:<5} runs={r['runs']:<3} "
                  f"naive: {r['naive_elapsed_ms']:>8.1f}ms engine={r['naive_engine_ms_total']:.1f}ms "
                  f"peak={r['naive_peak_traced_mb']:.3f}MB rssΔ={r['naive_rss_delta_mb']:+.3f}MB | "
                  f"stream: {r['stream_elapsed_ms']:>8.1f}ms engine={r['stream_engine_ms_total']:.1f}ms "
                  f"peak={r['stream_peak_traced_mb']:.3f}MB rssΔ={r['stream_rss_delta_mb']:+.3f}MB "
                  f"spooled={r['stream_spooled']} | tight peak={r['tight_peak_traced_mb']:.3f}MB "
                  f"spooled={r['tight_spooled']}")

    print("=" * 70)
    print("C. 落库 + 按 run_id 复跑校验")
    c = part_c_replay(tmp_db)
    print(f"  run_id={c['run_id']} params_hash={c['params_hash']} "
          f"data_fp={c['data_fingerprint']} result_hash={c['result_hash']}")
    print(f"  replay_ok={c['replay_ok']} attempts={c['attempts_after_replay']}")
    for chk in c["checks"]:
        print(f"    - {chk['name']:<18} ok={chk['ok']}")

    payload = {"anchor": a, "scale": b, "replay": c,
               "conditions": {
                   "feed": "LocalDailyFeed（本地 akshare 日线缓存，离线）",
                   "memory": "tracemalloc 峰值 + psutil RSS 前后差；numpy 缓冲区不计入 tracemalloc",
                   "timing": "tracemalloc 关闭后单独计时，取 3 次运行的最小值（开发机有并行会话负载尖峰）",
               }}
    out_path = os.path.join(OUT_DIR, "phase9_backtest_scale.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已写入 {out_path}")
    ok = a["all_ok"] and c["replay_ok"] and all(r["all_ok_sample"] for r in b["rows"])
    print(f"总判定: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
