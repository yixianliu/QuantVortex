"""增强特征工程（方向一·1.3）。

在原有 7 个基础特征之上，扩展「量价 / 资金 / 估值」类因子，为多周期集成模型
提供更丰富的预测信号：

    基础（与旧模型完全等价）：ret, vol, RSI14, MACD, K, boll_pct, CCI14
    扩展（新增）：
        动量/趋势 : MOM10, ROC12, BIAS6, ADX, dir_di=(PLUS_DI-MINUS_DI)/100
        均线乖离 : ma20_gap=close/MA20-1, ma60_gap=close/MA60-1
        短波动   : vol5=ret.rolling(5).std()
        量能     : vol_ratio=volume/VOL_MA5, obv_chg=OBV.pct_change(5)
        资金     : fund_proxy=日内资金流滚动占比（通用，无需外部列）
        价格风险 : atr_pct=(high-low)滚动均值/close

所有特征 ffill 后 fillna(0)，避免 NaN 进入 LSTM / 岭回归。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators.tech import add_indicators

# 与旧版 FuturesPredictor.FEATURES 完全一致，保证 extended=False 时行为不变
BASE_FEATURES = ["ret", "vol", "RSI14", "MACD", "K", "boll_pct", "CCI14"]

EXTENDED_FEATURES = [
    # —— 基础（保留）——
    "ret", "vol", "RSI14", "MACD", "K", "boll_pct", "CCI14",
    # —— 扩展 ——
    "MOM10", "ROC12", "BIAS6", "ADX", "dir_di",
    "ma20_gap", "ma60_gap", "vol5", "vol_ratio", "obv_chg",
    "fund_proxy", "atr_pct",
]


def build_features(df: pd.DataFrame, extended: bool = True):
    """返回 (ind, F, feature_names)。

    ind : 含全部指标的 DataFrame；F : 已对齐的特征矩阵 (len, n_feat)；
    feature_names : F 的列顺序（训练/推理须保持一致）。
    """
    ind = add_indicators(df)
    close = ind["close"]
    high = ind["high"]
    low = ind["low"]
    vol = ind["volume"]

    # —— 基础特征（与旧实现一致）——
    ind["ret"] = np.log(close).diff()
    ind["vol"] = ind["ret"].rolling(20, min_periods=1).std()
    denom = (ind["BOLL_UP"] - ind["BOLL_LOW"]).replace(0, np.nan)
    ind["boll_pct"] = ((close - ind["BOLL_LOW"]) / denom).fillna(0.5)

    if not extended:
        feats = BASE_FEATURES
        F = ind[feats].ffill().fillna(0.0)
        return ind, F, feats

    # —— 扩展特征 ——
    ind["MOM10"] = close.diff(10)
    ind["ROC12"] = close.pct_change(12) * 100.0
    ind["BIAS6"] = (close - ind["MA6"]) / ind["MA6"] if "MA6" in ind else (close - ind["MA5"]) / ind["MA5"]
    ind["ADX"] = ind["ADX"] if "ADX" in ind else 0.0
    if "PLUS_DI" in ind and "MINUS_DI" in ind:
        ind["dir_di"] = (ind["PLUS_DI"] - ind["MINUS_DI"]) / 100.0
    else:
        ind["dir_di"] = 0.0
    ind["ma20_gap"] = (close / ind["MA20"] - 1.0) if "MA20" in ind else 0.0
    ind["ma60_gap"] = (close / ind["MA60"] - 1.0) if "MA60" in ind else 0.0
    ind["vol5"] = ind["ret"].rolling(5, min_periods=1).std()
    vma5 = ind["VOL_MA5"] if "VOL_MA5" in ind else vol.rolling(5, min_periods=1).mean()
    ind["vol_ratio"] = (vol / vma5.replace(0, np.nan)).fillna(1.0)
    # 量能变化：成交量 5 日变化率（恒为正，避免 OBV 跨零产生 ±inf）
    ind["obv_chg"] = (vol.pct_change(5)
                      .replace([np.inf, -np.inf], 0.0)
                      .clip(-5.0, 5.0).fillna(0.0))

    # 资金代理：近 20 根日内资金流占比（正为净流入），滚动标准化，无外部列依赖
    fp = (close - ind["open"]) * vol * close if "open" in ind else ind["ret"] * vol * close
    num = fp.rolling(20, min_periods=1).sum()
    den = fp.abs().rolling(20, min_periods=1).sum().replace(0, np.nan)
    ind["fund_proxy"] = (num / den).fillna(0.0)

    # 价格风险：真实波幅占比（不依赖 ATR 列，自行计算）
    atr = (high - low).rolling(14, min_periods=1).mean()
    ind["atr_pct"] = (atr / close).fillna(0.0)

    feats = EXTENDED_FEATURES
    F = ind[feats].ffill().fillna(0.0)
    return ind, F, feats
