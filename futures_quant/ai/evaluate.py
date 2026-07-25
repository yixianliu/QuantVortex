"""测试集 MAE 评估（方向一·1.3）。

walk-forward：用前 (1 - test_frac) 训练，对测试段每根用「截至该根」的窗口
（无未来函数）预测下一步对数收益，与实际下一步收益比较，得到样本外单步 MAE。

用于量化验证：增强模型（扩展特征 + 多周期集成）相对 baseline（原 7 特征单日线
模型）的测试集 MAE 改善（roadmap 目标 10%~15%）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .predictor import FuturesPredictor
from .ensemble import MultiPeriodEnsemble


def rolling_mae(df: pd.DataFrame, *, use_ensemble: bool = False,
               extended_features: bool = False, test_frac: float = 0.25,
               seq_len: int = 20, epochs: int = 20) -> float | None:
    """返回测试集单步收益 MAE；数据不足返回 None。"""
    n = len(df)
    cut = int(n * (1 - test_frac))
    if cut < seq_len + 5 or n - cut < seq_len:
        return None

    train = df.iloc[:cut]
    if use_ensemble:
        ens = MultiPeriodEnsemble()
        if not ens.fit(train, seq_len, epochs):
            return None
        pred_fn = lambda d: ens.predict_next(d, seq_len)
    else:
        p = FuturesPredictor()
        p.fit(train, seq_len, epochs, extended_features=extended_features)
        pred_fn = lambda d: p._predict_next(d, seq_len)

    # 实际下一步对数收益：actual[j] = log(close[j+1] / close[j])
    actual = np.log(df["close"]).diff().shift(-1).values.astype(float)

    preds, acts = [], []
    for i in range(cut + seq_len, n):
        d = df.iloc[:i]                 # 截至 i-1，无未来函数
        pr = pred_fn(d)
        ac = actual[i - 1]              # 窗口结束于 i-1 的下一步真实收益
        if np.isfinite(ac) and np.isfinite(pr):
            preds.append(pr)
            acts.append(ac)
    if not preds:
        return None
    return float(np.mean(np.abs(np.array(preds) - np.array(acts))))


def compare(df: pd.DataFrame, **kw) -> dict | None:
    """对比 baseline vs 增强，返回 MAE 与改善百分比。"""
    base = rolling_mae(df, use_ensemble=False, extended_features=False, **kw)
    enh = rolling_mae(df, use_ensemble=True, extended_features=True, **kw)
    if base is None or enh is None or base <= 0:
        return None
    improvement = (base - enh) / base * 100.0
    return {
        "baseline_mae": round(base, 6),
        "enhanced_mae": round(enh, 6),
        "improvement_pct": round(improvement, 2),
    }
