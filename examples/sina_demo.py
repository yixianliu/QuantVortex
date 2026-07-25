"""实盘数据接入演示（新浪公开期货接口，免密钥）。

验证「接入实盘数据」是否真正打通：拉取真实日线 -> 指标 -> AI 预测 -> 保存真实图表。

运行：
    python examples/sina_demo.py
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from futures_quant.data.sina_feed import SinaFeed
from futures_quant.data.market_data import MarketDataManager
from futures_quant.indicators.tech import add_indicators
from futures_quant.ai.predictor import FuturesPredictor


def main() -> None:
    mgr = MarketDataManager(source="sina")
    mgr.connect()
    feed = mgr.feed  # 即 SinaFeed 实例
    print("数据源状态:", mgr.status, "| label:", mgr.source_label)

    targets = ["rb.SHFE", "cu.SHFE", "au.SHFE", "IF.CFFEX", "m.DCE", "T.CFFEX"]
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)

    pred = FuturesPredictor()
    for sym in targets:
        t0 = time.time()
        df = feed.get_recent(sym, "D", limit=600)
        if df is None or df.empty:
            print(f"[跳过] {sym}: 无真实数据")
            continue
        ind = add_indicators(df)
        info = pred.fit(df, seq_len=20, epochs=25)
        res = pred.predict(df, horizon=12)
        last_date = str(df["datetime"].iloc[-1].date())
        print(f"\n=== {sym} | 真实日线最后交易日 {last_date} | {len(df)} 根 ===")
        print(f"  最新价: {res['last_close']}  预期收益%: {res['expected_return_pct']}  "
              f"p_up: {res['p_up']}  风险: {res['risk']['label']}({res['risk']['score']})")
        print(f"  行情状态: {res['regime']}  共振: {res['resonance']['verdict']}({res['resonance']['score']})  "
              f"模型: {res['model']}  训练{time.time()-t0:.1f}s")
        print(f"  关键价位(前3): {[(round(l['price'],1), l['label']) for l in res['levels'][:3]]}")

        # 真实日线 + 预测曲线图
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(ind["datetime"], ind["close"], color="#2563eb", lw=1.2, label="Real close")
        fc = pd.to_datetime(df["datetime"].iloc[-1]) + pd.to_timedelta(np.arange(1, 13), "D")
        ax.plot(list(df["datetime"].iloc[-1:]) + list(fc),
                res["forecast"], color="#ef4444", lw=1.6, ls="--", label="AI forecast")
        ax.fill_between(list(df["datetime"].iloc[-1:]) + list(fc),
                        res["lower"], res["upper"], color="#ef4444", alpha=0.12)
        ax.set_title(f"{sym} real daily + AI forecast (source: Sina live)", fontsize=12)
        ax.legend(); ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"sina_{sym.split('.')[0]}_forecast.png"), dpi=110)
        plt.close(fig)
        print(f"  图表已保存: output/sina_{sym.split('.')[0]}_forecast.png")

    print("\n实盘数据接入验证完成。")


if __name__ == "__main__":
    main()
