"""指标共振 / 背离 / 趋势强弱打分。

这些函数消费 indicators.tech.add_indicators 产出的指标列，输出：
    - resonance():  多指标综合研判（多头 / 空头 / 震荡）+ 多空力量分(-100~100)；
    - divergence(): 价格与 RSI/MACD 的顶/底背离检测；
    - trend_score():趋势强弱打分(0~100) 与 ADX 辅助判定。

全部基于「已收盘」数据（末根指标值），不引用未来信息。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe(v) -> float:
    """处理safe。
    
        参数:
            v
    
        返回:
            float"""
    try:
        f = float(v)
        return f if np.isfinite(f) else 0.0
    except Exception:
        return 0.0


def resonance(df: pd.DataFrame) -> dict:
    """多指标共振研判。"""
    if df is None or len(df) < 35:
        return {"verdict": "数据不足", "score": 0.0, "signals": {}}
    last = df.iloc[-1]
    prev = df.iloc[-2]
    sig: dict[str, float] = {}

    # 均线排列：MA5>MA10>MA20>MA60 为多，反之为空
    ma_vals = [("MA5", _safe(last.get("MA5"))), ("MA10", _safe(last.get("MA10"))),
               ("MA20", _safe(last.get("MA20"))), ("MA60", _safe(last.get("MA60")))]
    if all(v for _, v in ma_vals):
        bull = ma_vals[0][1] > ma_vals[1][1] > ma_vals[2][1] > ma_vals[3][1]
        bear = ma_vals[0][1] < ma_vals[1][1] < ma_vals[2][1] < ma_vals[3][1]
        sig["均线排列"] = 100.0 if bull else (-100.0 if bear else 0.0)
    else:
        sig["均线排列"] = 0.0

    # MACD：DIF>DEA 且柱为正
    dif, dea, hist = _safe(last.get("DIF")), _safe(last.get("DEA")), _safe(last.get("MACD"))
    if dif or dea:
        sig["MACD"] = 100.0 if (dif > dea and hist > 0) else (-100.0 if (dif < dea and hist < 0) else 0.0)
    else:
        sig["MACD"] = 0.0

    # KDJ：K>D 且 J 未超买/超卖
    k, d = _safe(last.get("K")), _safe(last.get("D"))
    if k or d:
        if k > d and k < 80:
            sig["KDJ"] = 70.0
        elif k > d and k >= 80:
            sig["KDJ"] = 30.0  # 多头但超买，动能边际减弱
        elif k < d and k > 20:
            sig["KDJ"] = -70.0
        elif k < d and k <= 20:
            sig["KDJ"] = -30.0
        else:
            sig["KDJ"] = 0.0
    else:
        sig["KDJ"] = 0.0

    # RSI：>70 超买偏空回撤，<30 超卖偏多反弹，50 上方偏多
    rsi14 = _safe(last.get("RSI14"))
    if rsi14:
        if rsi14 > 70:
            sig["RSI"] = -40.0
        elif rsi14 < 30:
            sig["RSI"] = 40.0
        else:
            sig["RSI"] = 30.0 if rsi14 > 50 else -30.0
    else:
        sig["RSI"] = 0.0

    # BOLL：收盘价在上轨上方偏多、下轨下方偏空、中轨附近震荡
    close = _safe(last.get("close"))
    up, mid, low = _safe(last.get("BOLL_UP")), _safe(last.get("BOLL_MID")), _safe(last.get("BOLL_LOW"))
    if close and up and mid and low:
        if close > up:
            sig["BOLL"] = 60.0
        elif close < low:
            sig["BOLL"] = -60.0
        elif close > mid:
            sig["BOLL"] = 30.0
        else:
            sig["BOLL"] = -30.0
    else:
        sig["BOLL"] = 0.0

    # DMI：ADX>25 且 +DI>-DI 多头趋势
    adx = _safe(last.get("ADX"))
    pdi, mdi = _safe(last.get("PLUS_DI")), _safe(last.get("MINUS_DI"))
    if adx and pdi and mdi:
        if adx > 25:
            sig["DMI"] = 80.0 if pdi > mdi else -80.0
        else:
            sig["DMI"] = 10.0 if pdi > mdi else -10.0
    else:
        sig["DMI"] = 0.0

    score = float(np.mean(list(sig.values())))
    if score > 20:
        verdict = "多头共振"
    elif score < -20:
        verdict = "空头共振"
    else:
        verdict = "震荡"
    return {"verdict": verdict, "score": round(score, 1), "signals": {k: round(v, 1) for k, v in sig.items()}}


def divergence(df: pd.DataFrame, lookback: int = 60) -> dict:
    """价格与 RSI/MACD 的背离检测。"""
    if df is None or len(df) < lookback:
        return {"found": False, "type": "无", "detail": "数据不足"}
    sub = df.tail(lookback).reset_index(drop=True)
    price = sub["close"].values

    def _last_extreme(series, kind):
        # 返回最近一个局部极值索引与值
        """处理lastextreme。
        
            参数:
                series
                kind"""
        s = series.values
        n = len(s)
        for i in range(n - 3, 2, -1):
            if kind == "high" and s[i] >= s[i - 1] and s[i] >= s[i + 1]:
                return i, s[i]
            if kind == "low" and s[i] <= s[i - 1] and s[i] <= s[i + 1]:
                return i, s[i]
        return None, None

    # RSI 背离
    rsi = sub["RSI14"] if "RSI14" in sub else None
    result = {"found": False, "type": "无", "detail": ""}
    if rsi is not None:
        pi1, pv1 = _last_extreme(pd.Series(price), "high")
        pi2, pv2 = _last_extreme(pd.Series(price[:-3]), "high") if len(price) > 6 else (None, None)
        ri1, rv1 = _last_extreme(rsi, "high")
        if pi1 and pi2 and ri1 and pv1 > pv2:
            # 价格新高但 RSI 未新高 -> 顶背离
            if rv1 < rsi.iloc[:ri1].max():
                result = {"found": True, "type": "顶背离(RSI)", "detail": "价格创新高，RSI 动能走弱"}
        pl1, plv1 = _last_extreme(pd.Series(price), "low")
        rl1, rlv1 = _last_extreme(rsi, "low")
        if pl1 and rl1 and plv1 < price[len(price) - 6] if len(price) > 6 else False:
            if rlv1 > rsi.iloc[:rl1].min():
                result = {"found": True, "type": "底背离(RSI)", "detail": "价格创新低，RSI 动能回暖"}
    return result


def trend_score(df: pd.DataFrame) -> dict:
    """趋势强弱打分(0~100)。"""
    if df is None or len(df) < 35:
        return {"strength": 0, "state": "数据不足", "adx": 0.0}
    last = df.iloc[-1]
    adx = _safe(last.get("ADX"))
    close = _safe(last.get("close"))
    ma20 = _safe(last.get("MA20"))
    ma60 = _safe(last.get("MA60"))
    score = 50.0
    if adx:
        score = min(100.0, adx * 1.8)  # ADX 0~100 映射
    state = "趋势" if (adx and adx > 25) else "震荡"
    if close and ma20 and ma60:
        if close > ma20 > ma60:
            state = "多头趋势"
        elif close < ma20 < ma60:
            state = "空头趋势"
    return {"strength": round(score, 1), "state": state, "adx": round(adx, 1)}
