"""按 run_id 复跑回测并校验结果一致性。

用法:
    python scripts/replay_run.py --run-id bt_xxxxxxxxxxxx
    python scripts/replay_run.py --run-id bt_xxxxxxxxxxxx --db data/quant_backtest.db
    python scripts/replay_run.py --run-id bt_xxxxxxxxxxxx --export-dir outputs/replay

校验逻辑（任一项不一致即退出码 1）：
    - 参数快照哈希、数据指纹、run_id、result_hash、逐笔成交摘要、
      资金曲线摘要、KPI 全量比对。

说明：
    - 默认使用离线本地日线 Feed（与 perf_probe 相同），保证不联网；
    - 复跑不会写库，仅在指定 --export-dir 时导出 JSON/CSV。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from futures_quant.backtest import export as export_mod  # noqa: E402
from futures_quant.backtest import runner  # noqa: E402
from futures_quant.storage.backtest_store import BacktestStore  # noqa: E402


def _feed(kind: str):
    if kind == "local":
        import perf_probe
        return perf_probe.LocalDailyFeed()
    if kind == "synthetic":
        from futures_quant.data.synthetic import SyntheticFeed
        return SyntheticFeed()
    if kind == "market":
        from futures_quant.data.market_data import MarketDataManager
        return MarketDataManager().feed
    raise ValueError(f"未知 feed 类型：{kind}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按 run_id 复跑并校验回测结果")
    ap.add_argument("--run-id", required=True, help="回测运行 id（backtest_runs.run_id）")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "quant_backtest.db"),
                    help="回测库路径（默认生产库，只读）")
    ap.add_argument("--feed", default="local", choices=("local", "synthetic", "market"),
                    help="复跑使用的行情源（默认离线本地日线）")
    ap.add_argument("--export-dir", default="", help="可选：导出复跑结果到该目录")
    ap.add_argument("--json-out", default="", help="可选：把校验报告写入 JSON 文件")
    args = ap.parse_args(argv)
    # 统一转为绝对路径：BacktestStore 会把相对路径解析到 data/ 目录下
    db_path = os.path.abspath(args.db)

    store = BacktestStore(db_path)
    try:
        rec = store.get_run(args.run_id)
        if rec is None:
            print(f"[FAIL] 库中不存在 run_id={args.run_id}（db={args.db}）")
            return 1
        try:
            report = runner.replay_run(store, args.run_id, _feed(args.feed))
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] 复跑失败：{type(e).__name__}: {e}")
            return 2

        result = report["result"]
        print(f"run_id={args.run_id}")
        print(f"symbol={rec.get('symbol')} window={rec.get('start')}~{rec.get('end')} "
              f"period={rec.get('period')} strategy={rec.get('strategy_name')}")
        print(f"params_hash={rec.get('params_hash')} data_fp={rec.get('data_fingerprint')}")
        print("-" * 64)
        for chk in report["checks"]:
            mark = "OK " if chk["ok"] else "FAIL"
            print(f"[{mark}] {chk['name']}")
            if not chk["ok"]:
                print(f"       expected={chk['expected']}")
                print(f"       actual  ={chk['actual']}")
        print("-" * 64)
        print(f"复跑结论：{'一致' if report['ok'] else '不一致'}")

        if args.export_dir:
            paths = export_mod.export_result(result, args.export_dir,
                                             prefix=args.run_id)
            print("导出：")
            for k, v in paths.items():
                print(f"  {k}: {v}")
        if args.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
            print(f"校验报告：{args.json_out}")
        return 0 if report["ok"] else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
