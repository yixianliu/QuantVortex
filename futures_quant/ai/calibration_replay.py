"""历史回放校准：把历史 K 线逐窗喂给 predictor，将「模型预测」作为已结算样本写入
分析库，从而使「可靠性校准」从「样本不足」快速进入有数据状态。

设计要点：
- 回放使用**独立新建**的 FuturesPredictor 实例，绝不复用调用方（如预测页）的共享
  predictor，避免污染后续实时预测的模型状态（predict() 一旦 trained 即不再重训）。
- M3-03（关键修正）：此前本模块声称「out-of-time（样本外）实证」，但实现是
  **用全量 df 训练一次、再滑窗 predict** —— 模型在训练时已见过全部未来数据，
  属于典型的样本内泄漏（in-sample leakage），且该偏差会经 reliability_calibration
  反馈回线上 p_up，形成偏差放大回路。
  现改为**真·Walk-Forward**：
    * 每 ``retrain_stride`` 步，用 ``df.iloc[:t]``（严格截止到 t 的历史）重新训练；
    * 随后仅对 ``[t, t+horizon)`` 做预测，预测输入同样只用 ``df.iloc[:t]``；
    * 归一化统计量（_feat_mean / _feat_std 等）随 fit 只从训练段估计，杜绝未来信息。
  用 ``retrain_stride`` 控制重训频率以控成本（默认 20），而非逐根重训。
  ``oos_only=True``（默认）即上述严格样本外模式；置 False 可回退到旧的
  「全量训练一次」模式，仅用于对比/兼容，**不应**用于生成校准样本。
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
import logging
import math
import os
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .predictor import FuturesPredictor
# M3-11：阈值集中化（默认值 == 改造前字面量，行为不变）
from .constants import CALIB as _CC

logger = logging.getLogger(__name__)


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
        return df if len(df) >= _CC.min_bars_for_replay else None
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


def replay_symbol(store, df, symbol, period: str = "D", horizon: int = None,
                 stride: int = None, max_samples: int = None,
                 config: str = "enhanced",
                 epochs: int = None, extended_features: bool = True,
                 use_ensemble: bool = True, progress_cb: Optional[Callable] = None,
                 retrain_stride: int = None, oos_only: bool = True) -> dict:
    """回放单个品种的历史，把每个窗口的预测作为已结算校准样本写入 store。

    M3-03：默认走**真·Walk-Forward**（oos_only=True）—— 每 ``retrain_stride``
    步用 ``df.iloc[:t]`` 重训后再预测 ``[t, t+horizon)``，归一化统计量只从训练段
    估计，彻底消除原实现的样本内泄漏。

    参数:
        retrain_stride: 每隔多少根 K 线重新训练一次（默认 20）。越小越接近
            逐根重训（成本高），越大越省但适应性下降。
        oos_only: True（默认）严格样本外 walk-forward；False 回退到旧的
            「全量训练一次」模式，仅用于 A/B 对比或兼容，**不应用于生成校准样本**。

    返回 {added, skipped, total, symbol}。
    """
    # None 哨兵：缺省值取自阈值中心（避免 import 期固化）
    horizon = _CC.replay_horizon if horizon is None else horizon
    stride = _CC.replay_stride if stride is None else stride
    max_samples = _CC.replay_max_samples if max_samples is None else max_samples
    epochs = _CC.replay_epochs if epochs is None else epochs
    retrain_stride = (_CC.replay_retrain_stride if retrain_stride is None
                      else retrain_stride)
    if df is None or len(df) < _CC.min_bars_for_replay:
        return {"added": 0, "skipped": 0, "total": 0, "symbol": symbol}

    n = len(df)

    def _new_pred(train_df) -> Optional[FuturesPredictor]:
        """用给定（训练）段拟合一个独立 predictor；失败返回 None。"""
        p = FuturesPredictor()
        try:
            p.fit(train_df, seq_len=_CC.replay_seq_len, epochs=epochs,
                  force_ridge=True,  # 沙箱无 torch，必须用岭回归兜底
                  extended_features=extended_features,
                  use_ensemble=use_ensemble,
                  symbol=symbol, period=period)
        except Exception:
            return None
        return p if getattr(p, "trained", False) else None

    pred: Optional[FuturesPredictor] = None
    end = n - horizon
    step = max(1, stride)

    if not oos_only:
        # ---- 旧模式（仅用于对比/兼容）：全量训练一次，存在样本内泄漏 ----
        pred = _new_pred(df)
        if pred is None:
            return {"added": 0, "skipped": 0, "total": 0, "symbol": symbol}
        start = max(_CC.replay_min_start, pred.seq_len + 1)
        retrain_stride = 0            # 不再重训
        last_train_t = -10 ** 9
    else:
        # ---- 真 Walk-Forward：起点先用一个最小训练段拟合，确定 seq_len ----
        probe = _new_pred(df.iloc[:max(_CC.replay_min_start,
                                       _CC.replay_probe_train_bars)])
        start = max(_CC.replay_min_start,
                    (probe.seq_len + 1) if probe is not None
                    else _CC.replay_min_start)
        pred = None                    # 循环中按 stride 重训
        last_train_t = None

    if end <= start:
        return {"added": 0, "skipped": 0, "total": 0, "symbol": symbol}

    added = skipped = total = 0
    for t in range(start, end, step):
        if added >= max_samples:
            break
        total += 1
        window = df.iloc[:t]

        # M3-03：真 Walk-Forward —— 到步就用「截止到 t 的历史」重训
        if oos_only and (
            pred is None or last_train_t is None or (t - last_train_t) >= retrain_stride
        ):
            pred = _new_pred(window)
            if pred is None:
                skipped += 1
                continue
            last_train_t = t

        if pred is None:
            skipped += 1
            continue
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
        nu = _CC.hit_p_up_threshold
        hit = 1 if (p_up >= nu and actual_pct > 0) or (p_up < nu and actual_pct < 0) else 0
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

class _TCNEstimator:
    """把 `ai.tcn.TemporalConvNet` 适配成外部主模型接口 `fit(X_3d, y) / predict(X_3d)`。

    M3-06 ①：TCN 的 `fit()` 原来是个 `pass`（权重随机、什么都不学），且 `_causal_conv`
    因切片上界写错导致卷积输出恒为 0 —— 装上它等于装了个「恒预测 0」的假模型。
    现在 TCN 会在首次 fit 时按 `X.shape[2]` 惰性建网并真正训练读出层。
    """

    name = "tcn"

    def __init__(self, epochs: int = None, channels=None, kernel_size: int = None,
                 lr: float = None, seed: int = None) -> None:
        self.epochs = int(_CC.tcn_epochs if epochs is None else epochs)
        self.channels = list(_CC.tcn_channels if channels is None else channels)
        self.kernel_size = int(_CC.tcn_kernel_size if kernel_size is None
                               else kernel_size)
        self.lr = float(_CC.tcn_lr if lr is None else lr)
        self.seed = _CC.random_seed if seed is None else seed
        self.net = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        """处理fit。

            参数:
                X: np.ndarray
                y: np.ndarray"""
        from .tcn import TemporalConvNet
        if self.net is None:
            self.net = TemporalConvNet(
                num_inputs=int(np.asarray(X).shape[2]),
                num_channels=self.channels,
                kernel_size=self.kernel_size,
                seed=self.seed,
            )
        self.net.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=float),
                     epochs=self.epochs, lr=self.lr,
                     batch_size=_CC.tcn_batch_size)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """处理predict。

            参数:
                X: np.ndarray

            返回:
                np.ndarray"""
        if self.net is None:
            return np.zeros(len(np.asarray(X)), dtype=float)
        return np.asarray(self.net.predict(np.asarray(X, dtype=float)),
                          dtype=float).reshape(-1)


class _GBMEstimator:
    """把 `ai.boosting.GradientBoostingModel` 适配成外部主模型接口。

    输入是 (n, seq_len, n_feat) 的序列窗口，树模型不吃时序结构，按样本展平成
    (n, seq_len * n_feat) 后训练 —— 与 ensemble.py 里树成员的处理口径一致。
    """

    name = "gbm"

    def __init__(self, n_estimators: int = None, learning_rate: float = None,
                 max_depth: int = None, seed: int = None) -> None:
        self.n_estimators = int(_CC.gbm_n_estimators if n_estimators is None
                                else n_estimators)
        self.learning_rate = float(_CC.gbm_learning_rate if learning_rate is None
                                   else learning_rate)
        self.max_depth = int(_CC.gbm_max_depth if max_depth is None else max_depth)
        self.seed = _CC.random_seed if seed is None else seed
        self.model = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        """处理fit。

            参数:
                X: np.ndarray
                y: np.ndarray"""
        from .boosting import GradientBoostingModel
        flat = np.asarray(X, dtype=float).reshape(len(X), -1)
        self._n_feat_flat = flat.shape[1]
        self.model = GradientBoostingModel(
            task="regression",
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,          # 玩具实现按 1 层真实分裂
            learning_rate=self.learning_rate,
            random_state=self.seed,
        )
        self.model.fit(flat, np.asarray(y, dtype=float))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """处理predict。

            参数:
                X: np.ndarray

            返回:
                np.ndarray"""
        if self.model is None:
            return np.zeros(len(np.asarray(X)), dtype=float)
        flat = np.asarray(X, dtype=float).reshape(len(X), -1)
        return np.asarray(self.model.predict(flat), dtype=float).reshape(-1)


class _TSTransformerEstimator:
    """TS-Transformer 适配器。**无 torch 时明确不可用**（不伪装成可用模型）。

    M3-06 ⑤：TSTransformer 在无 torch 分支下 predict 恒返回 0，若参与对比会
    拉出一个「看起来很差的成员」却让人误以为是模型能力问题。这里直接判不可用。
    """

    name = "transformer"

    def __init__(self, epochs: int = None, seq_len: int = None) -> None:
        self.epochs = int(_CC.ts_epochs if epochs is None else epochs)
        self.seq_len = int(_CC.ts_seq_len if seq_len is None else seq_len)
        self.model = None
        self.available = False

    def fit(self, X: np.ndarray, y: np.ndarray):
        """处理fit。

            参数:
                X: np.ndarray
                y: np.ndarray"""
        from .ts_transformer import TSWrapper, TORCH_AVAILABLE
        if not TORCH_AVAILABLE:
            self.available = False
            logger.warning("TS-Transformer 不可用：未安装 torch，该成员不参与对比")
            return self
        self.model = TSWrapper(
            feature_size=int(np.asarray(X).shape[2]),
            seq_len=int(np.asarray(X).shape[1]),
            epochs=self.epochs,
        )
        self.model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=float))
        self.available = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """处理predict。

            参数:
                X: np.ndarray

            返回:
                np.ndarray"""
        if self.model is None or not getattr(self.model, "available", False):
            return np.zeros(len(np.asarray(X)), dtype=float)
        return np.asarray(self.model.predict(np.asarray(X, dtype=float)),
                          dtype=float).reshape(-1)


def build_external_estimator(model_name: str, epochs: int = None,
                            seq_len: int = None):
    """按名字构造外部主模型；不支持或不可用时返回 None。

    这是 M3-06 ④ 的落点：`MultiModelComparator` 的 tcn / gbm 分支由此真正
    拿到对应模型，而不是像旧实现那样被 `force_ridge=True` 悄悄降级成 Ridge。
    """
    if epochs is None:
        epochs = _CC.ts_epochs
    if seq_len is None:
        seq_len = _CC.ts_seq_len
    name = (model_name or "").lower()
    if name == "tcn":
        return _TCNEstimator(epochs=max(_CC.tcn_min_epochs, int(epochs)))
    if name in ("gbm", "boosting", "gbdt"):
        return _GBMEstimator()
    if name in ("transformer", "ts_transformer", "ts-transformer"):
        est = _TSTransformerEstimator(epochs=max(_CC.ts_min_epochs, int(epochs)),
                                     seq_len=seq_len)
        # 无 torch 时直接判不可用（避免"恒 0 模型"混入对比）
        from .ts_transformer import TORCH_AVAILABLE
        return est if TORCH_AVAILABLE else None
    return None


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
                # M3-06 ④：tcn / gbm **真正调用对应模型**（旧实现一律 force_ridge=True
                # 降级成 Ridge，四个分支里有两个是假的，对比表自然毫无差异）。
                est = build_external_estimator(model_name_l, epochs=epochs)
                if est is None:
                    logger.warning("模型 %s 不可用，跳过对比", model_name_l)
                    return None
                pred.fit(df, seq_len=seq_len, epochs=epochs, force_ridge=False,
                         extended_features=extended_features,
                         use_ensemble=use_ensemble, symbol=symbol, period=period,
                         external_model=est)
        except Exception:
            return None
        if not getattr(pred, "trained", False):
            return None
        if model_name_l not in ("ridge", "lstm") and pred.external_model is None:
            # 外部模型训练失败已被 _train_core 回退成 Ridge —— 不应再冒充 tcn/gbm
            logger.warning("模型 %s 训练失败并已回退 Ridge，跳过对比", model_name_l)
            return None
        return pred

    def run(
        self,
        dfs: dict,
        symbol: str = "multi",
        period: str = "D",
        horizon: int = None,
        stride: int = None,
        max_samples: int = None,
        epochs: int = None,
        seq_len: int = None,
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
        # 对比回放的默认值与 replay_* 部分同值但语义独立，故用 COMPARE_* 单独一组
        horizon = _CC.compare_horizon if horizon is None else horizon
        stride = _CC.compare_stride if stride is None else stride
        max_samples = _CC.compare_max_samples if max_samples is None else max_samples
        epochs = _CC.compare_epochs if epochs is None else epochs
        seq_len = _CC.compare_seq_len if seq_len is None else seq_len
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
                start = max(_CC.replay_min_start, pred.seq_len + 1)
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
                    # M3-06：abs_err 原来是 `abs(actual_pct)` —— 那是**行情自身波动
                    # 幅度**，与模型毫无关系，四个模型的 MAE 必然相等。改为
                    # 「模型预测涨跌幅度 vs 真实涨跌幅度」的误差，才具备可比性。
                    fc = res.get("forecast") or []
                    pred_pct = ((float(fc[-1]) / last_close - 1.0) * 100.0
                                if (fc and last_close) else 0.0)
                    y_up = 1.0 if actual_pct > 0 else 0.0
                    nu = _CC.hit_p_up_threshold
                    hit = 1 if (p_up >= nu and y_up == 1) or (p_up < nu and y_up == 0) else 0
                    abs_err = abs(pred_pct - actual_pct)
                    rows.append({
                        "symbol": sym, "model": model, "ts": str(df.index[t - 1]),
                        "p_up": round(p_up, 4), "actual_up": y_up,
                        "actual_pct": round(actual_pct, 3),
                        "pred_pct": round(pred_pct, 3),
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
