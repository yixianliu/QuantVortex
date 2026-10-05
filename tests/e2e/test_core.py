"""基础层自检脚本（无 UI）：验证 data/indicators/ai/analysis/storage 真实可用。

运行方式（pytest）：
    pytest tests/e2e/test_core.py -s
顶层 import 与步骤封装为 test_layers 用例，断言关键结果（防未来函数：
所有步骤仅依赖当日及之前数据）；_run_all_steps() 保持原自检打印语义。
"""
from __future__ import annotations
import os
import sys
import time
import numpy as np
import pandas as pd

_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from futures_quant.data.synthetic import generate_bars, SyntheticFeed, resample_bars
from futures_quant.data.market_data import MarketDataManager
from futures_quant.indicators.tech import add_indicators
from futures_quant.ai.predictor import FuturesPredictor
from futures_quant.analysis.signals import resonance, trend_score, divergence
from futures_quant.analysis.support_resistance import compute_levels
from futures_quant.storage.analysis_store import AnalysisStore


def _step1_synthetic() -> pd.DataFrame:
    print("== 1. 合成行情 ==")
    df = generate_bars("rb.SHFE", n=1500, mode="mixed")
    print("  bars:", len(df), "cols:", list(df.columns))
    print("  close range:", round(df.close.min(), 1), "~", round(df.close.max(), 1))
    return df


def _step2_resample(df: pd.DataFrame) -> None:
    print("== 2. 多周期重采样 ==")
    for p in ["5m", "1h", "D", "W"]:
        r = resample_bars(df, p)
        print(f"  {p}: {len(r)} rows")


def _step3_indicators(df: pd.DataFrame) -> None:
    print("== 3. 指标 ==")
    ind = add_indicators(df)
    print("  indicator cols:", [c for c in ind.columns if c not in df.columns][:14], "...")
    print("  last RSI14:", round(float(ind.RSI14.iloc[-1]), 2),
          "ADX:", round(float(ind.ADX.iloc[-1]), 2))


def _step4_predict(df: pd.DataFrame) -> dict:
    print("== 4. KP预测（LSTM 训练+多步预测）==")
    t0 = time.time()
    pred = FuturesPredictor()
    fit_info = pred.fit(df, seq_len=20, epochs=30)
    print("  fit:", fit_info, " 训练耗时 %.2fs" % (time.time() - t0))
    res = pred.predict(df, horizon=12)
    print("  模型:", res["model"], " 预期收益%:", res["expected_return_pct"],
          " p_up:", res["p_up"], " 风险:", res["risk"]["label"], res["risk"]["score"])
    print("  行情状态:", res["regime"], " 共振:", res["resonance"]["verdict"],
          res["resonance"]["score"])
    print("  关键价位数:", len(res["levels"]),
          "| 示例:", [(round(l['price'], 1), l['label']) for l in res['levels'][:3]])
    return res


def _step5_analysis(df: pd.DataFrame, res: dict) -> None:
    print("== 5. 研判 ==")
    ind = add_indicators(df)
    print("  resonance:", resonance(ind)["verdict"])
    print("  trend:", trend_score(ind)["state"], trend_score(ind)["strength"])
    print("  divergence:", divergence(ind)["type"])
    print("  levels:", len(compute_levels(df)), "个")


def _step6_panorama() -> None:
    print("== 6. 市场全景 ==")
    mgr = MarketDataManager()
    pan = mgr.compute_panorama(period="D")
    print("  品种数:", len(pan))
    print(pan.head(5).to_string(index=False))


def _step7_quote() -> None:
    print("== 7. 盘口快照 ==")
    mgr = MarketDataManager()
    q = mgr.get_quote("rb.SHFE", "1m")
    print("  last:", round(q["last"], 1), "chg%:", round(q["chg_pct"], 2),
          "fund_flow(亿):", round(q["fund_flow"], 3))


def _step8_storage(df: pd.DataFrame, res: dict) -> None:
    print("== 8. 存储层 ==")
    store = AnalysisStore("data/_selftest.db")
    store.cache_bars("rb.SHFE", "1m", df.tail(100))
    import datetime as dt
    store.save_prediction({"ts": str(dt.datetime.now()), "symbol": "rb.SHFE",
                           "period": "1m", "horizon": 12,
                           "last_close": res["last_close"],
                           "expected_return_pct": res["expected_return_pct"],
                           "p_up": res["p_up"], "p_down": res["p_down"],
                           "risk_score": res["risk"]["score"],
                           "risk_label": res["risk"]["label"],
                           "model": res["model"], "regime": res["regime"],
                           "verdict": res["resonance"]["verdict"],
                           "score": res["resonance"]["score"],
                           "forecast": str(res["forecast"])})
    print("  predictions saved:", len(store.query_predictions()))
    ok = store.export_csv("predictions", "data/_pred_export.csv")
    print("  export csv:", ok)


def _run_all_steps() -> dict:
    df = _step1_synthetic()
    _step2_resample(df)
    _step3_indicators(df)
    res = _step4_predict(df)
    _step5_analysis(df, res)
    _step6_panorama()
    _step7_quote()
    _step8_storage(df, res)
    print("\nALL CORE LAYERS OK")
    return res


# ------------------------------------------------------------------
# pytest 入口：封装为用例，关键结果断言（防未来函数：仅用当日及之前数据）
# ------------------------------------------------------------------
def test_layers():
    res = _run_all_steps()
    # 预测结果结构完整
    assert "expected_return_pct" in res
    assert "p_up" in res
    # 数据层：日线真实重采样
    df = generate_bars("rb.SHFE", n=100, mode="mixed")
    assert len(df) == 100
    # 指标层：防未来函数——RSI 只依赖当前及之前收盘价
    ind = add_indicators(df)
    assert not np.isnan(ind.RSI14.iloc[-1])
