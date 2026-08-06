"""采集真实期货日线到 data/real_samples/ 供回测离线回放（R4 样本落库）。

把 akshare 拉到的真实行情规范为 DataFeed 标准列后落盘，使 CsvFeed（离线兜底，
方案 C3）与回测引擎形成封闭、可复现的真实数据回放链路。

用法（需联网）：
    python futures_quant/data/collect_real_samples.py          # 默认采集主力品种
    python futures_quant/data/collect_real_samples.py rb.SHFE  # 指定品种

落盘位置：<get_data_dir()>/real_samples/{symbol 下划线}_{period}.csv
命名与 CsvFeed 默认 base_dir 对齐。
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from futures_quant.data.akshare_feed import AkshareFeed
from futures_quant.runtime import get_data_dir

DEFAULT_SYMS = ["rb.SHFE", "i.DCE", "au.SHFE", "IF.CFFEX"]


def main() -> None:
    syms = sys.argv[1:] or DEFAULT_SYMS
    base = os.path.join(get_data_dir(), "real_samples")
    os.makedirs(base, exist_ok=True)
    feed = AkshareFeed()
    for sym in syms:
        try:
            df = feed.get_history(sym, "2009-01-01", "2026-12-31", "D")
            if df is None or df.empty:
                print(f"SKIP {sym}: empty")
                continue
            path = os.path.join(base, f"{sym.replace('.', '_')}_D.csv")
            df.to_csv(path, index=False)
            print(f"OK   {sym}: rows={len(df)} -> {path}")
        except Exception as e:  # noqa: BLE001
            print(f"ERR  {sym}: {repr(e)[:200]}")


if __name__ == "__main__":
    main()
