"""基础层自检脚本（无 UI）：验证 data/indicators/ai/analysis/storage 真实可用。"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd

from futures_quant.data.synthetic import generate_bars, SyntheticFeed, resample_bars
from futures_quant.data.market_data import MarketDataManager
from futures_quant.indicators.tech import add_indicators
from futures_quant.ai.predictor import FuturesPredictor
from futures_quant.analysis.signals import resonance, trend_score, divergence
from futures_quant.analysis.support_resistance import compute_levels
from futures_quant.storage.analysis_store import AnalysisStore

print("== 1. 合成行情 ==")
df = generate_bars("rb.SHFE", n=1500, mode="mixed")
print("  bars:", len(df), "cols:", list(df.columns))
print("  close range:", round(df.close.min(),1), "~", round(df.close.max(),1))

print("== 2. 多周期重采样 ==")
for p in ["5m","1h","D","W"]:
    r = resample_bars(df, p)
    print(f"  {p}: {len(r)} rows")

print("== 3. 指标 ==")
ind = add_indicators(df)
print("  indicator cols:", [c for c in ind.columns if c not in df.columns][:14], "...")
print("  last RSI14:", round(float(ind.RSI14.iloc[-1]),2), "ADX:", round(float(ind.ADX.iloc[-1]),2))

print("== 4. AI 预测（LSTM 训练+多步预测）==")
t0 = time.time()
pred = FuturesPredictor()
fit_info = pred.fit(df, seq_len=20, epochs=30)
print("  fit:", fit_info, " 训练耗时 %.2fs" % (time.time()-t0))
res = pred.predict(df, horizon=12)
print("  模型:", res["model"], " 预期收益%:", res["expected_return_pct"],
      " p_up:", res["p_up"], " 风险:", res["risk"]["label"], res["risk"]["score"])
print("  行情状态:", res["regime"], " 共振:", res["resonance"]["verdict"], res["resonance"]["score"])
print("  关键价位数:", len(res["levels"]), "| 示例:", [(round(l['price'],1), l['label']) for l in res['levels'][:3]])

print("== 5. 研判 ==")
print("  resonance:", resonance(ind)["verdict"])
print("  trend:", trend_score(ind)["state"], trend_score(ind)["strength"])
print("  divergence:", divergence(ind)["type"])
print("  levels:", len(compute_levels(df)), "个")

print("== 6. 市场全景 ==")
mgr = MarketDataManager()
pan = mgr.compute_panorama(period="D")
print("  品种数:", len(pan))
print(pan.head(5).to_string(index=False))

print("== 7. 盘口快照 ==")
q = mgr.get_quote("rb.SHFE", "1m")
print("  last:", round(q["last"],1), "chg%:", round(q["chg_pct"],2), "fund_flow(亿):", round(q["fund_flow"],3))

print("== 8. 存储层 ==")
store = AnalysisStore("data/_selftest.db")
store.cache_bars("rb.SHFE","1m", df.tail(100))
import datetime as dt
store.save_prediction({"ts": str(dt.datetime.now()), "symbol":"rb.SHFE","period":"1m","horizon":12,
    "last_close":res["last_close"],"expected_return_pct":res["expected_return_pct"],
    "p_up":res["p_up"],"p_down":res["p_down"],"risk_score":res["risk"]["score"],
    "risk_label":res["risk"]["label"],"model":res["model"],"regime":res["regime"],
    "verdict":res["resonance"]["verdict"],"score":res["resonance"]["score"],
    "forecast":str(res["forecast"])})
print("  predictions saved:", len(store.query_predictions()))
ok = store.export_csv("predictions", "data/_pred_export.csv")
print("  export csv:", ok)

print("\nALL CORE LAYERS OK")
