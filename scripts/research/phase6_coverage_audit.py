"""第六轮审计：预测区间「真实覆盖率」样本外回放（rb / i / cu / IF）。

用途
----
`predictions` 表迁移前没有 lower/upper，无法用历史记录核算真实区间命中率；
本脚本用 ``replay_symbol`` 做严格 walk-forward（每 retrain_stride 根用截止到
t 的历史重训一次），把每次预测的区间与结算价写入**临时测试库**，再用
``evaluate_interval_coverage`` 统计真实覆盖率。

同时输出两种对照：
1. ``true``：实际价是否落在预测当时落库的 [lower, upper]（真实覆盖率）；
2. ``approx_per_sample``：用同一模型 band_sigma 以「预测起点价 ±σ√h」构造的
   近似区间（旧 UI 思路），不包含模型漂移；
3. ``ui_style_approx_global``：复刻预测页 `_band_coverage` 的全局近似——

     取最后 120 根 close，h=10，σ 取回放样本 band_sigma 的中位数，
     命中 = |close[i]/close[i-h]-1| <= σ*sqrt(h)

仅用于对照，**不得**作为真实覆盖率对外展示。

约束：只读 data/real_samples/*.csv；回放写入 tempfile 临时库，不碰生产数据库。
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from statistics import median

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.ai.calibration_replay import (
    discover_local_samples, load_bars_from_csv, replay_symbol,
)
from futures_quant.ai.evaluation import evaluate_interval_coverage
from futures_quant.storage.analysis_store import AnalysisStore

#: 固定随机种子，保证回放/分位数结果可复现
SEED = 20261104
#: 回放参数（每 768 根重训一次，兼顾样本量与运行时长；仍严格只用历史段训练）
HORIZON = 10
STRIDE = 40
MAX_SAMPLES = 100
RETRAIN_STRIDE = 768
#: 只取这 4 个有本地样本的品种，控制运行时长
TARGET_SYMBOLS = {"rb.SHFE", "i.DCE", "cu.SHFE", "IF.CFFEX"}
OUT_PATH = os.path.join("scripts", "research", "phase6_coverage_audit.json")


def _ui_style_approx(df: pd.DataFrame, sigma: float, horizon: int = HORIZON,
                     window: int = 120) -> dict:
    """复刻预测页近似覆盖率：|涨跌幅| <= σ*sqrt(h)。"""
    closes = pd.to_numeric(df["close"], errors="coerce").dropna().to_numpy()
    if closes.size <= horizon + 1 or not math.isfinite(sigma) or sigma <= 0:
        return {"available": False, "coverage": None, "n": 0,
                "reason": "样本或 σ 不足"}
    tail = closes[-min(window, closes.size):]
    rets = tail[:-horizon] / tail[horizon:] - 1.0
    limit = sigma * math.sqrt(horizon)
    hits = int(np.sum(np.abs(rets) <= limit))
    return {"available": True, "coverage": round(hits / len(rets), 6),
            "n": int(len(rets)), "limit": round(float(limit), 8),
            "sigma": round(float(sigma), 8)}


def _approx_per_sample(rows: list[dict], horizon: int = HORIZON) -> dict:
    """用同一 band_sigma 做「起点价 ±σ√h」近似区间，逐样本对照。"""
    hits = n = 0
    for r in rows:
        sigma = r.get("band_sigma")
        last = r.get("last_close")
        act = r.get("actual_return_pct")
        if sigma is None or last is None or act is None or float(sigma) <= 0:
            continue
        half = float(sigma) * math.sqrt(horizon)
        actual = float(last) * (1.0 + float(act) / 100.0)
        n += 1
        hits += int(abs(math.log(actual / float(last))) <= half)
    return {"available": n > 0, "coverage": (round(hits / n, 6) if n else None),
            "n": n, "n_hit": hits}


def main() -> dict:
    np.random.seed(SEED)
    samples = [(p, sym, per) for (p, sym, per)
               in discover_local_samples(os.path.join("data", "real_samples"))
               if sym in TARGET_SYMBOLS]
    results = []
    for path, symbol, period in samples:
        t0 = time.time()
        df = load_bars_from_csv(path)
        if df is None:
            results.append({"symbol": symbol, "period": period,
                            "error": "CSV 读取失败或样本不足"})
            continue
        with tempfile.TemporaryDirectory(prefix="qv_phase6_") as td:
            store = AnalysisStore(os.path.join(td, "audit.db"))
            try:
                rep = replay_symbol(
                    store, df, symbol, period=period, horizon=HORIZON,
                    stride=STRIDE, max_samples=MAX_SAMPLES,
                    retrain_stride=RETRAIN_STRIDE, config="enhanced",
                    extended_features=False, use_ensemble=False)
                rows = store.query_closed_with_bands(limit=10000)
                cov = evaluate_interval_coverage(rows=rows)
            finally:
                store.close()

        sigmas = [float(r["band_sigma"]) for r in rows
                  if r.get("band_sigma") is not None]
        sigma_med = float(median(sigmas)) if sigmas else 0.0
        approx_global = _ui_style_approx(df, sigma_med)
        approx_sample = _approx_per_sample(rows)
        results.append({
            "symbol": symbol,
            "period": period,
            "bars": int(len(df)),
            "rows": len(rows),
            "replay": rep,
            "true_coverage": {
                "available": cov.get("available"),
                "coverage": cov.get("coverage"),
                "n": cov.get("n"),
                "n_hit": cov.get("n_hit"),
                "nominal": cov.get("nominal"),
                "vc": {k: cov.get(k) for k in
                       ("ci_low", "ci_high", "deviation_pp", "verdict",
                        "verdict_text", "reason")},
                "by_horizon": cov.get("by_horizon"),
                "by_volatility": cov.get("by_volatility"),
                "calibration": cov.get("calibration"),
            },
            "approx_per_sample": approx_sample,
            "ui_style_approx_global": approx_global,
            "median_band_sigma": round(sigma_med, 8),
        })
        print(f"{symbol} rows={len(rows)} true={cov.get('coverage')} "
              f"approx_sample={approx_sample.get('coverage')} "
              f"approx_ui={approx_global.get('coverage')} "
              f"elapsed={round(time.time() - t0, 1)}s", flush=True)

    payload = {
        "seed": SEED,
        "horizon": HORIZON,
        "stride": STRIDE,
        "max_samples": MAX_SAMPLES,
        "retrain_stride": RETRAIN_STRIDE,
        "note": "真实覆盖率来自 walk-forward 临时库；ui_style_approx_global 仅对照，禁止对外冒充真实值",
        "symbols": results,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", os.path.abspath(OUT_PATH))
    return payload


if __name__ == "__main__":
    main()
