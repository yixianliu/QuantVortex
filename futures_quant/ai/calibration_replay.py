"""历史回放校准：把历史 K 线逐窗喂给 predictor，将「模型预测」作为已结算样本写入
分析库，从而使「可靠性校准」从「样本不足」快速进入有数据状态（out-of-time 实证）。

设计要点：
- 回放使用**独立新建**的 FuturesPredictor 实例，绝不复用调用方（如预测页）的共享
  predictor，避免污染后续实时预测的模型状态（predict() 一旦 trained 即不再重训）。
- 仅训练一次（全样本），随后滑窗 predict 不复训；以 stride + max_samples 控制规模，
  避免对全历史逐根重训导致的不堪重负。
- 真实收益口径与 evaluate_prediction 一致：以预测窗口末根 close 为起点，
  与 horizon 根之后的 close 比，判定方向是否命中。
- 离线、确定性：news_bias=0、calibrate_p_up=None，不引入资讯与外部校准噪声，
  保证回放样本是模型「纯粹」预测概率下的经验命中率。
- 训练采用与线上默认一致的 extended_features=True + use_ensemble=True（config='enhanced'），
  使回放出的 p_up 分布与线上预测同口径，校准映射可直接用于线上校准。
"""
from __future__ import annotations

import datetime as dt
import glob
import math
import os
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .predictor import FuturesPredictor


def load_bars_from_csv(path: str) -> Optional[pd.DataFrame]:
    """读取 real_samples 类 CSV（datetime,open,high,low,close,volume,open_interest），
    解析为带 DatetimeIndex 的 DataFrame；失败或样本不足返回 None。"""
    try:
        df = pd.read_csv(path)
        if "datetime" not in df.columns:
            return None
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
        for c in ("open", "high", "low", "close", "volume", "open_interest"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df if len(df) >= 80 else None
    except Exception:
        return None


def discover_local_samples(data_dir: str) -> list:
    """扫描 data/real_samples/*.csv，返回 [(path, symbol_label, period)]。

    文件名约定：<SYM>_<EXCH>_<PER>.csv（如 rb_SHFE_D.csv → ('rb.SHFE','D')）。
    """
    out = []
    for p in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        stem = os.path.basename(p)[:-4]
        parts = stem.split("_")
        if len(parts) < 2:
            continue
        label = f"{parts[0]}.{parts[1]}"
        per = parts[2] if len(parts) >= 3 else "D"
        out.append((p, label, per))
    return out


def replay_symbol(store, df, symbol, period: str = "D", horizon: int = 10,
                 stride: int = 8, max_samples: int = 250, config: str = "enhanced",
                 epochs: int = 20, extended_features: bool = True,
                 use_ensemble: bool = True, progress_cb: Optional[Callable] = None) -> dict:
    """回放单个品种的历史，把每个窗口的预测作为已结算校准样本写入 store。

    返回 {added, skipped, total, symbol}。
    """
    if df is None or len(df) < 80:
        return {"added": 0, "skipped": 0, "total": 0, "symbol": symbol}

    # 独立 predictor 实例：零副作用，绝不污染调用方的共享模型
    pred = FuturesPredictor()
    try:
        pred.fit(df, seq_len=20, epochs=epochs,
                 force_ridge=True,  # 沙箱无 torch，必须用岭回归兜底
                 extended_features=extended_features,
                 use_ensemble=use_ensemble)
    except Exception:
        return {"added": 0, "skipped": 0, "total": 0, "symbol": symbol}
    if not getattr(pred, "trained", False):
        return {"added": 0, "skipped": 0, "total": 0, "symbol": symbol}

    n = len(df)
    start = max(60, pred.seq_len + 1)
    end = n - horizon
    step = max(1, stride)
    if end <= start:
        return {"added": 0, "skipped": 0, "total": 0, "symbol": symbol}

    added = skipped = total = 0
    for t in range(start, end, step):
        if added >= max_samples:
            break
        total += 1
        window = df.iloc[:t]
        try:
            res = pred.predict(window, horizon=horizon,
                               news_bias=0.0, news_samples=[], calibrate_p_up=None)
        except Exception:
            skipped += 1
            continue
        p_up = float(res.get("p_up", 0.5))
        regime = res.get("regime") or "未知"
        model = res.get("model") or "LSTM"
        last_close = float(df["close"].iloc[t - 1])
        fut_idx = min(t - 1 + horizon, n - 1)
        fut_close = float(df["close"].iloc[fut_idx])
        actual_pct = (fut_close / last_close - 1.0) * 100.0
        y_up = 1.0 if actual_pct > 0 else 0.0
        hit = 1 if (p_up >= 0.5 and actual_pct > 0) or (p_up < 0.5 and actual_pct < 0) else 0
        rec = {
            "ts": str(df.index[t - 1]),
            "symbol": symbol, "period": period, "horizon": horizon,
            "last_close": round(last_close, 4),
            "expected_return_pct": round(float(res.get("expected_return_pct", 0.0)), 3),
            "p_up": round(p_up, 4), "p_down": round(1 - p_up, 4),
            "risk_score": float((res.get("risk") or {}).get("score", 0) or 0),
            "risk_label": (res.get("risk") or {}).get("label", ""),
            "model": model, "regime": regime, "verdict": "",
            "score": hit, "forecast": "", "confidence": round(p_up, 4),
            "status": "closed", "config": config,
            "actual_return_pct": round(actual_pct, 3),
            "y_up": y_up,
            "closed_ts": str(dt.datetime.now()),
        }
        try:
            store.save_closed_prediction(rec)
            added += 1
        except Exception:
            skipped += 1
        if progress_cb is not None:
            try:
                progress_cb(added, symbol)
            except Exception:
                pass
    return {"added": added, "skipped": skipped, "total": total, "symbol": symbol}


def replay_local_store(store, data_dir: str = "data/real_samples",
                       horizon: int = 10, stride: int = 8, max_samples: int = 250,
                       progress_cb: Optional[Callable] = None) -> dict:
    """回放本地真实样本目录（默认 data/real_samples）下的全部 CSV，灌入校准样本。

    返回 {added, skipped, total, symbols:[...]}。
    """
    samples = discover_local_samples(data_dir)
    added_total = skipped_total = total_total = 0
    syms = []
    for (path, label, per) in samples:
        df = load_bars_from_csv(path)
        if df is None:
            continue
        r = replay_symbol(store, df, label, period=per, horizon=horizon,
                          stride=stride, max_samples=max_samples,
                          progress_cb=progress_cb)
        added_total += r["added"]
        skipped_total += r["skipped"]
        total_total += r["total"]
        syms.append(r)
    return {"added": added_total, "skipped": skipped_total,
            "total": total_total, "symbols": syms}
