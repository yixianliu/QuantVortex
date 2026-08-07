"""关键价位计算（压力位 / 支撑位）。

方法（均基于历史 K 线，非未来函数）：
    1. 经典枢轴点(Pivot)：由最近一根已完成 K 线的 H/L/C 推导 R1~R3 / S1~S3；
    2. 摆动高低点：局部极值识别，越近、幅度越大权重越高；
    3. 量能密集区：按价格分箱，成交量加权寻找密集成交价，作为隐性支撑/压力。
输出统一为 [(price, kind, strength, label)]，供预测模块与图表叠加使用。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _pivots(high: float, low: float, close: float) -> list[dict]:
    """处理pivots。
    
        参数:
            high: float
            low: float
            close: float
    
        返回:
            list[dict]"""
    pp = (high + low + close) / 3
    r1 = 2 * pp - low
    s1 = 2 * pp - high
    r2 = pp + (high - low)
    s2 = pp - (high - low)
    r3 = high + 2 * (pp - low)
    s3 = low - 2 * (high - pp)
    return [
        {"price": r3, "kind": "resistance", "strength": 0.6, "label": "R3"},
        {"price": r2, "kind": "resistance", "strength": 0.8, "label": "R2"},
        {"price": r1, "kind": "resistance", "strength": 1.0, "label": "R1"},
        {"price": pp, "kind": "pivot", "strength": 1.0, "label": "PIVOT"},
        {"price": s1, "kind": "support", "strength": 1.0, "label": "S1"},
        {"price": s2, "kind": "support", "strength": 0.8, "label": "S2"},
        {"price": s3, "kind": "support", "strength": 0.6, "label": "S3"},
    ]


def _swing_levels(df: pd.DataFrame, window: int = 5, lookback: int = 120) -> list[dict]:
    """处理swing价位。
    
        参数:
            df: pd.DataFrame
            window: int
            lookback: int
    
        返回:
            list[dict]"""
    sub = df.tail(lookback)
    highs = sub["high"].values
    lows = sub["low"].values
    n = len(sub)
    levels = []
    for i in range(window, n - window):
        seg_h = highs[i - window:i + window + 1]
        seg_l = lows[i - window:i + window + 1]
        if highs[i] == seg_h.max():
            recency = (n - i) / n
            strength = 0.5 + 0.5 * recency
            levels.append({"price": float(highs[i]), "kind": "resistance",
                           "strength": strength, "label": "SwingH"})
        if lows[i] == seg_l.min():
            recency = (n - i) / n
            strength = 0.5 + 0.5 * recency
            levels.append({"price": float(lows[i]), "kind": "support",
                           "strength": strength, "label": "SwingL"})
    return levels


def _volume_clusters(df: pd.DataFrame, bins: int = 30, lookback: int = 240) -> list[dict]:
    """处理成交量clusters。
    
        参数:
            df: pd.DataFrame
            bins: int
            lookback: int
    
        返回:
            list[dict]"""
    sub = df.tail(lookback)
    if len(sub) < bins:
        return []
    price = sub["close"].values
    vol = sub["volume"].values
    try:
        counts, edges = np.histogram(price, bins=bins, weights=vol)
    except Exception:
        return []
    total = counts.sum()
    if total <= 0:
        return []
    centers = 0.5 * (edges[:-1] + edges[1:])
    # 取成交量占比最高的若干区间作为隐性价位
    order = np.argsort(counts)[::-1][:5]
    out = []
    for idx in order:
        ratio = counts[idx] / total
        if ratio < 0.05:
            continue
        kind = "support" if centers[idx] < price[-1] else "resistance"
        out.append({"price": float(centers[idx]), "kind": kind,
                    "strength": float(min(1.0, 0.4 + ratio * 4)),
                    "label": "VOL"})
    return out


def compute_levels(df: pd.DataFrame) -> list[dict]:
    """汇总所有方法的关键价位，按价格排序、去重接近值。"""
    if df is None or len(df) < 30:
        return []
    last = df.iloc[-1]
    levels = _pivots(float(last["high"]), float(last["low"]), float(last["close"]))
    levels += _swing_levels(df)
    levels += _volume_clusters(df)
    # 合并 ±0.15% 内的相近价位，强度取最大
    levels.sort(key=lambda x: x["price"])
    merged = []
    for lv in levels:
        if merged and abs(lv["price"] - merged[-1]["price"]) / max(merged[-1]["price"], 1e-9) < 0.0015:
            if lv["strength"] > merged[-1]["strength"]:
                merged[-1] = lv
        else:
            merged.append(lv)
    return merged
