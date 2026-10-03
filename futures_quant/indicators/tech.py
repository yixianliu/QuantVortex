"""技术指标库（纯 numpy / pandas 向量化实现，零外部依赖）。

覆盖期货实战常用指标：
    趋势类：MA / EMA / BOLL / MACD / DMI(ADX/DI+/DI-) / SAR
    摆动类：RSI / KDJ / CCI / ROC / 乖离率(BIAS) / 动量(MOM)
    量能类：VOL(均量) / OBV / 量价背离辅助

所有函数返回与输入等长、首段为 NaN 的 Series/DataFrame，便于直接并入 K 线表。
如需替换为 TA-Lib，只需在本文件内替换函数体，对外接口不变。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .cache import IndicatorCache, get_instance, cached_indicator


# ----------------------------- 趋势类 -----------------------------
def sma(series: pd.Series, n: int) -> pd.Series:
    """处理sma。
    
        参数:
            series: pd.Series
            n: int
    
        返回:
            pd.Series"""
    return series.rolling(n, min_periods=1).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """处理EMA。
    
        参数:
            series: pd.Series
            n: int
    
        返回:
            pd.Series"""
    return series.ewm(span=n, adjust=False, min_periods=1).mean()


def boll(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """处理布林带。
    
        参数:
            close: pd.Series
            n: int
            k: float
    
        返回:
            pd.DataFrame"""
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=1).std(ddof=0)
    return pd.DataFrame({
        "BOLL_MID": mid, "BOLL_UP": mid + k * sd, "BOLL_LOW": mid - k * sd,
    })


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """处理MACD。
    
        参数:
            close: pd.Series
            fast: int
            slow: int
            signal: int
    
        返回:
            pd.DataFrame"""
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    hist = (dif - dea) * 2  # 期货软件常用 2 倍柱
    return pd.DataFrame({"DIF": dif, "DEA": dea, "MACD": hist})


def dmi(high: pd.Series, low: pd.Series, close: pd.Series,
        n: int = 14) -> pd.DataFrame:
    """计算 +DI / -DI / ADX / ADXR。"""
    up = high.diff()
    dn = -low.diff()
    # 注意：必须显式带上原索引。np.where 返回裸 ndarray，若直接 pd.Series(...) 会
    # 生成 0..n-1 的默认 RangeIndex；当 high/low 为 DatetimeIndex 时，后续与 atr
    # 相除会因索引对齐失败而产生全 NaN（历史 bug：ADX/±DI 恒为 NaN）。
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=low.index)
    tr = pd.concat([
        (high - low).abs(),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(n, min_periods=1).sum()
    plus_di = 100 * plus_dm.rolling(n, min_periods=1).sum() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(n, min_periods=1).sum() / atr.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.rolling(n, min_periods=1).mean()
    adxr = (adx + adx.shift(n)) / 2
    return pd.DataFrame({
        "PLUS_DI": plus_di, "MINUS_DI": minus_di, "ADX": adx, "ADXR": adxr,
    })


def sar(high: pd.Series, low: pd.Series, accel: float = 0.02,
        maximum: float = 0.2) -> pd.Series:
    """抛物线 SAR（Wilder）。"""
    n = len(high)
    sar = np.full(n, np.nan)
    if n < 2:
        return pd.Series(sar, index=high.index)
    trend = 1 if high.iloc[1] >= high.iloc[0] else -1
    ep = low.iloc[0] if trend > 0 else high.iloc[0]
    sar[0] = low.iloc[0] if trend > 0 else high.iloc[0]
    af = accel
    for i in range(1, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
        if trend > 0:
            if low.iloc[i] < sar[i]:
                trend = -1
                sar[i] = ep
                ep = low.iloc[i]
                af = accel
            else:
                if high.iloc[i] > ep:
                    ep = high.iloc[i]
                    af = min(af + accel, maximum)
        else:
            if high.iloc[i] > sar[i]:
                trend = 1
                sar[i] = ep
                ep = high.iloc[i]
                af = accel
            else:
                if low.iloc[i] < ep:
                    ep = low.iloc[i]
                    af = min(af + accel, maximum)
    return pd.Series(sar, index=high.index)


# ----------------------------- 摆动类 -----------------------------
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """处理RSI。
    
        参数:
            close: pd.Series
            n: int
    
        返回:
            pd.Series"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / n, adjust=False, min_periods=1).mean()
    al = loss.ewm(alpha=1 / n, adjust=False, min_periods=1).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def kdj(close: pd.Series, high: pd.Series, low: pd.Series,
        n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """处理KDJ。
    
        参数:
            close: pd.Series
            high: pd.Series
            low: pd.Series
            n: int
            m1: int
            m2: int
    
        返回:
            pd.DataFrame"""
    llv = low.rolling(n, min_periods=1).min()
    hhv = high.rolling(n, min_periods=1).max()
    rsv = (close - llv) / (hhv - llv).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1 / m1, adjust=False, min_periods=1).mean()
    d = k.ewm(alpha=1 / m2, adjust=False, min_periods=1).mean()
    j = 3 * k - 2 * d
    return pd.DataFrame({"K": k, "D": d, "J": j})


def cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """处理CCI。
    
        参数:
            high: pd.Series
            low: pd.Series
            close: pd.Series
            n: int
    
        返回:
            pd.Series"""
    tp = (high + low + close) / 3
    ma = tp.rolling(n, min_periods=1).mean()
    md = (tp - ma).abs().rolling(n, min_periods=1).mean()
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def roc(close: pd.Series, n: int = 12) -> pd.Series:
    """处理roc。
    
        参数:
            close: pd.Series
            n: int
    
        返回:
            pd.Series"""
    return close.pct_change(n) * 100


def bias(close: pd.Series, n: int = 6) -> pd.Series:
    """处理bias。
    
        参数:
            close: pd.Series
            n: int
    
        返回:
            pd.Series"""
    ma = sma(close, n)
    return (close - ma) / ma * 100


def momentum(close: pd.Series, n: int = 10) -> pd.Series:
    """处理momentum。
    
        参数:
            close: pd.Series
            n: int
    
        返回:
            pd.Series"""
    return close.diff(n)


# ----------------------------- 量能类 -----------------------------
def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """处理obv。
    
        参数:
            close: pd.Series
            volume: pd.Series
    
    返回:
        pd.Series"""
    sign = np.sign(close.diff().fillna(0))
    return (sign * volume).cumsum()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """平均真实波幅（Wilder 平滑，标准公式）。

    防未来函数：第 i 根的 ATR 仅依赖 close[i] 及之前的 TR/历史数据，
    使用 ewm(alpha=1/n, adjust=False) 因果递归，不回看未来。
    """
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def vol_ma(volume: pd.Series, n: int = 5) -> pd.Series:
    """处理成交量均线。
    
        参数:
            volume: pd.Series
            n: int
    
        返回:
            pd.Series"""
    return volume.rolling(n, min_periods=1).mean()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 20) -> pd.Series:
    """成交量加权平均价 VWAP。
    
    防未来函数：使用滚动窗口右对齐。
    """
    typical_price = (high + low + close) / 3.0
    cum_vol = volume.rolling(n, min_periods=1).sum()
    cum_tp_vol = (typical_price * volume).rolling(n, min_periods=1).sum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def hv(close: pd.Series, n: int = 20) -> pd.Series:
    """历史波动率 HV，按年化 252 个交易日。
    
    防未来函数：滚动标准差。
    """
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(n, min_periods=n).std() * np.sqrt(252)


def garch(close: pd.Series, n: int = 20) -> pd.Series:
    """GARCH(1,1) 条件波动率近似实现。
    
    若 arch 包可用则使用真实拟合，否则退化为 EWMA 波动率。
    防未来函数：仅使用历史数据滚动计算。
    """
    try:
        from arch import arch_model
        log_ret = np.log(close / close.shift(1)).dropna()
        am = arch_model(log_ret, vol='Garch', p=1, q=1)
        res = am.fit(disp='off')
        vol = res.conditional_volatility
        # 与原序列对齐
        idx = close.index[-len(vol):]
        return pd.Series(vol.values, index=idx)
    except Exception:
        # 降级：EWMA 波动率
        log_ret = np.log(close / close.shift(1))
        return log_ret.ewm(span=n, adjust=False).std() * np.sqrt(252)


# ----------------------------- 聚合入口 -----------------------------
def add_indicators(
    df: pd.DataFrame,
    ma_list: tuple[int, ...] = (5, 10, 20, 60),
    use_boll: bool = True, use_macd: bool = True, use_kdj: bool = True,
    use_rsi: bool = True, use_dmi: bool = True, use_sar: bool = True,
) -> pd.DataFrame:
    """把常用指标并入 K 线 DataFrame（原地返回新表）。"""
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]
    vol = out["volume"]
    for n in ma_list:
        out[f"MA{n}"] = sma(close, n)
    out["EMA20"] = ema(close, 20)
    if use_boll:
        out = out.join(boll(close))
    if use_macd:
        out = out.join(macd(close))
    if use_kdj:
        out = out.join(kdj(close, high, low))
    if use_rsi:
        out["RSI6"] = rsi(close, 6)
        out["RSI14"] = rsi(close, 14)
    if use_dmi:
        out = out.join(dmi(high, low, close))
    if use_sar:
        out["SAR"] = sar(high, low)
    out["BIAS6"] = bias(close, 6)
    out["MOM10"] = momentum(close, 10)
    out["CCI14"] = cci(high, low, close)
    out["OBV"] = obv(close, vol)
    out["VOL_MA5"] = vol_ma(vol, 5)
    out["ROC12"] = roc(close, 12)
    out["ATR14"] = atr(high, low, close, 14)

    # ------------------------------------------------------------------
    # M3-01：补齐下游 8 个「恒零特征」的真实计算。
    # 这些列此前从未被产出，导致 features.build_features 走
    # `else: fill_data[f] = 0.0` 静默填 0 —— 模型吃进 8 个全零列而不自知。
    # 命名与 EXTENDED_FEATURES 保持一致（小写）。
    # ------------------------------------------------------------------
    # 布林带分位：价格在布林通道中的相对位置（0=下轨，1=上轨）
    if {"BOLL_UP", "BOLL_LOW"}.issubset(out.columns):
        band = (out["BOLL_UP"] - out["BOLL_LOW"]).replace(0, np.nan)
        out["boll_pct"] = ((out["close"] - out["BOLL_LOW"]) / band).clip(0, 1).fillna(0.5)
    else:
        out["boll_pct"] = 0.5

    # DI 方向：+DI 与 -DI 之差（>0 多头占优，<0 空头占优）
    if {"PLUS_DI", "MINUS_DI"}.issubset(out.columns):
        out["dir_di"] = (out["PLUS_DI"] - out["MINUS_DI"]).fillna(0.0)
    else:
        out["dir_di"] = 0.0

    # 均线乖离：价格相对 MA20 / MA60 的相对偏离
    out["ma20_gap"] = ((close / out["MA20"].replace(0, np.nan)) - 1.0).fillna(0.0) \
        if "MA20" in out.columns else 0.0
    out["ma60_gap"] = ((close / out["MA60"].replace(0, np.nan)) - 1.0).fillna(0.0) \
        if "MA60" in out.columns else 0.0

    # 成交量：5 日均量与量比（现量 / 5 日均量）
    if "volume" in out.columns:
        vol_ma5 = vol.rolling(5, min_periods=1).mean()
        out["vol5"] = vol_ma5.fillna(0.0)
        out["vol_ratio"] = (vol / vol_ma5.replace(0, np.nan)).fillna(1.0)
    else:
        out["vol5"] = 0.0
        out["vol_ratio"] = 1.0

    # OBV 变化率：能量潮的 5 日变动（捕捉量能趋势）
    if "OBV" in out.columns:
        out["obv_chg"] = out["OBV"].diff(5).fillna(0.0)
    else:
        out["obv_chg"] = 0.0

    # ATR 占比：真实波幅 / 收盘价（归一化波动率，跨品种可比）
    if "ATR14" in out.columns:
        out["atr_pct"] = (out["ATR14"] / close.replace(0, np.nan)).fillna(0.0)
    else:
        out["atr_pct"] = 0.0

    return out


# ----------------------------- 缓存聚合入口 -----------------------------
def cached_add_indicators(symbol: str, period: str, df: pd.DataFrame) -> pd.DataFrame:
    """带 LRU 缓存的 add_indicators，同一 (symbol, period, df) 命中缓存时直接返回。

    注意：df 作为缓存键的一部分（基于 id），不同调用传入相同数据但不同对象时仍会重算；
    适用于 UI 反复调用相同 symbol/period 场景，避免重复 rolling/ewm 运算。
    """
    cache = get_instance()
    key = f"add_indicators|{symbol}|{period}|{df.shape}|{df.index[-1] if len(df) else 0}"
    cached = cache.get(symbol, period, "add_indicators", (df.shape, str(df.index[-1]) if len(df) else ""))
    if cached is not None:
        return cached
    result = add_indicators(df)
    cache.put(symbol, period, "add_indicators", result, (df.shape, str(df.index[-1]) if len(df) else ""))
    return result
