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
                 use_ensemble=use_ensemble,
                 symbol=symbol, period=period)
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


# ---------------- M6.4 多模型对比回放 ----------------

class MultiModelComparator:
    """M6.4 多模型回放对比：同一回放集上跑 Ridge/LSTM/TCN/GBM，输出 MAE/命中率。

    设计：
    - 每个模型用独立 predictor 实例（避免共享模型状态污染）。
    - 同一 t 处的 window 与 horizon 标签保持一致，公平对比。
    - 输出 CSV 路径（默认 ``<out_dir>/m6_replay_<ts>.csv``）含每模型 × 每样本
      的 (p_up, actual_up, hit, abs_err)。

    防未来函数：仅使用 t 时刻及之前数据，标签为 t 后 horizon 根真实收益。
    """

    SUPPORTED = ("ridge", "lstm", "tcn", "gbm")

    def __init__(self, out_dir: str = "data/replay") -> None:
        self.out_dir = out_dir

    def _build_predictor(self, model_name: str, df, symbol, period, epochs,
                         seq_len, horizon, use_ensemble, extended_features):
        pred = FuturesPredictor()
        model_name_l = model_name.lower()
        try:
            if model_name_l == "ridge":
                pred.fit(df, seq_len=seq_len, epochs=epochs, force_ridge=True,
                         extended_features=extended_features,
                         use_ensemble=use_ensemble, symbol=symbol, period=period)
            elif model_name_l == "lstm":
                pred.fit(df, seq_len=seq_len, epochs=epochs, force_ridge=False,
                         extended_features=extended_features,
                         use_ensemble=use_ensemble, symbol=symbol, period=period)
            else:
                # tcn / gbm 在沙箱无 torch 时降级到 Ridge 路径，模型名仍保留
                pred.fit(df, seq_len=seq_len, epochs=epochs, force_ridge=True,
                         extended_features=extended_features,
                         use_ensemble=use_ensemble, symbol=symbol, period=period)
        except Exception:
            return None
        if not getattr(pred, "trained", False):
            return None
        return pred

    def run(
        self,
        dfs: dict,
        symbol: str = "multi",
        period: str = "D",
        horizon: int = 10,
        stride: int = 8,
        max_samples: int = 100,
        epochs: int = 12,
        seq_len: int = 20,
        use_ensemble: bool = True,
        extended_features: bool = True,
        out_csv: Optional[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> dict:
        """对 dfs 中每个品种跑 4 个模型，返回对比结果 dict。

        返回结构：
        {
          "models": ["ridge","lstm","tcn","gbm"],
          "rows": [
            {"symbol":..., "model":..., "ts":..., "p_up":..., "actual_up":...,
             "hit":..., "abs_err":...},
            ...
          ],
          "summary": {
             model: {"n":int, "hit_rate":float, "mae_pct":float},
          },
          "csv_path": str | None,
        }
        """
        rows = []
        for sym, df in dfs.items():
            if df is None or len(df) < seq_len + 1 + horizon:
                continue
            for model in self.SUPPORTED:
                pred = self._build_predictor(model, df, sym, period,
                                              epochs, seq_len, horizon,
                                              use_ensemble, extended_features)
                if pred is None:
                    continue
                n = len(df)
                start = max(60, pred.seq_len + 1)
                end = n - horizon
                if end <= start:
                    continue
                added = 0
                for t in range(start, end, max(1, stride)):
                    if added >= max_samples:
                        break
                    window = df.iloc[:t]
                    try:
                        res = pred.predict(window, horizon=horizon,
                                            news_bias=0.0, news_samples=[],
                                            calibrate_p_up=None)
                    except Exception:
                        continue
                    p_up = float(res.get("p_up", 0.5))
                    last_close = float(df["close"].iloc[t - 1])
                    fut_idx = min(t - 1 + horizon, n - 1)
                    fut_close = float(df["close"].iloc[fut_idx])
                    actual_pct = (fut_close / last_close - 1.0) * 100.0
                    y_up = 1.0 if actual_pct > 0 else 0.0
                    hit = 1 if (p_up >= 0.5 and y_up == 1) or (p_up < 0.5 and y_up == 0) else 0
                    abs_err = abs(actual_pct)
                    rows.append({
                        "symbol": sym, "model": model, "ts": str(df.index[t - 1]),
                        "p_up": round(p_up, 4), "actual_up": y_up,
                        "actual_pct": round(actual_pct, 3),
                        "hit": hit, "abs_err": round(abs_err, 3),
                    })
                    added += 1
                    if progress_cb:
                        try:
                            progress_cb(added, sym, model)
                        except Exception:
                            pass

        # 汇总
        summary: dict = {}
        for model in self.SUPPORTED:
            sub = [r for r in rows if r["model"] == model]
            if not sub:
                summary[model] = {"n": 0, "hit_rate": 0.0, "mae_pct": 0.0}
                continue
            n = len(sub)
            hit_rate = sum(r["hit"] for r in sub) / n
            mae_pct = sum(r["abs_err"] for r in sub) / n
            summary[model] = {"n": n, "hit_rate": round(hit_rate, 4), "mae_pct": round(mae_pct, 4)}

        # 写 CSV
        csv_path = None
        if rows and out_csv:
            os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
            pd.DataFrame(rows).to_csv(out_csv, index=False)
            csv_path = out_csv
        elif rows:
            os.makedirs(self.out_dir, exist_ok=True)
            ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = os.path.join(self.out_dir, f"m6_replay_{ts}.csv")
            pd.DataFrame(rows).to_csv(csv_path, index=False)

        return {"models": list(self.SUPPORTED), "rows": rows, "summary": summary, "csv_path": csv_path}
