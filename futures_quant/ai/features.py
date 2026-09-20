"""特征工程模块，包含技术指标计算和特征构建。

提供完整的期货技术指标体系，涵盖：
- 趋势类指标：MA、EMA、MACD、ADX、DMI、BOLL等
- 震荡类指标：RSI、KDJ、CCI、ROC、BIAS等
- 量仓类指标：OBV、成交量变化率等
- 波动率类指标：ATR、历史波动率、vol_of_vol等
- 滞后与形态特征：ret_lag、close_open_ratio、high_low_ratio等

所有指标严格遵循标准计算公式，支持日线/分钟线/Tick多周期。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from collections import OrderedDict
import threading
from typing import Any, Tuple, List

from ..indicators.tech import add_indicators

# 共享指标缓存（基线修复）：原代码自引用本模块不存在的 _IndicatorLRUCache 致 ImportError。
# 此处实现与 features.py 原始意图一致的轻量 LRU：按 (symbol, period, 数据长度, 最新索引) 缓存
# 整份 add_indicators 输出，防未来函数（追加数据后 key 必变 → 自动失效重算）。
class _IndicatorLRUCache:
    _MAX = 128
    _lock = threading.Lock()

    @classmethod
    def _key(cls, symbol: str, period: str, df: pd.DataFrame) -> tuple:
        return (symbol, period, len(df),
                str(df.index[-1]) if len(df) else "")

    @classmethod
    def get(cls, symbol: str, period: str, df: pd.DataFrame):
        k = cls._key(symbol, period, df)
        with cls._lock:
            if k in _CACHE_ORD:
                _CACHE_ORD.move_to_end(k)
                return _CACHE_ORD[k]
            return None

    @classmethod
    def put(cls, symbol: str, period: str, df: pd.DataFrame, value) -> None:
        k = cls._key(symbol, period, df)
        with cls._lock:
            _CACHE_ORD[k] = value
            _CACHE_ORD.move_to_end(k)
            while len(_CACHE_ORD) > cls._MAX:
                _CACHE_ORD.popitem(last=False)


_CACHE_ORD: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()

# 特征名称与旧版完全保持一致，防止序列化兼容性问题
# 与 FuturesPredictor.FEATURES 保持同步
BASE_FEATURES = ["ret", "vol", "RSI14", "MACD", "K", "boll_pct", "CCI14"]

# 完整扩展特征列表，包含30+个高级因子
EXTENDED_FEATURES = [
    # —— 基础（保留）——
    "ret", "vol", "RSI14", "MACD", "K", "boll_pct", "CCI14",
    # —— 动量因子——
    "MOM10", "ROC12", "BIAS6",
    # —— 趋势强度与方向——
    "ADX", "dir_di",
    # —— 均线差异——
    "ma20_gap", "ma60_gap",
    # —— 成交量——
    "vol5", "vol_ratio", "obv_chg",
    # —— 波动率代理——
    "fund_proxy", "atr_pct",
    # —— 模型层深化·新增高阶因子（2026-08-27 补强，专门针对趋势行情准确率不足）——
    # ADXR 斜率：ADX 双指数平滑后的方向变化率，比 ADX 滞后但更稳定，捕捉趋势强度的持续性
    "adxr_slope5",
    # MA 多时间尺度斜率：MA20/MA60 斜率之比，区分"趋势启动"与"趋势延续"阶段
    "ma_slope_ratio",
    # DIF 斜率：MACD DIF 的一阶差分，领先于 MACD 柱，捕捉趋势拐点
    "dif_slope5",
    # 唐奇安通道突破强度：当前价相对 20 日高低的分位，大于 0.8 表示强势突破，小于 0.2 表示破位
    "donchian_rank",
    # 均线发散比：(MA5-MA20)/MA20 ÷ (MA20-MA60)/MA60，>1 短强长弱（趋势加速），<1 短弱长强（趋势衰竭）
    "ma_divergence_ratio",
    # —— 其量价新增特征——
    "volume_chg", "volume_ma_ratio", "volume_std_ratio",
    # —— 新增波动率特征——
    "vol_of_vol", "vol_change",
    # —— 新增滞后特征——
    "ret_lag1", "ret_lag2", "ret_lag5",
    # —— 新增价格形态特征——
    "close_open_ratio", "high_low_ratio",
]

def _add_lag_features(ind: pd.DataFrame, feature_names: List[str]) -> None:
    """为选定特征添加滞后（ lag）特征，捕捉时序依赖信息。
    
    参数:
        ind: 指标DataFrame
        feature_names: 要添加滞后特征的列名列表
    """
    for lag in [1, 2, 5]:
        lag_col_prefix = f"_lag{lag}"
        for f in feature_names:
            if f in ind.columns:
                col_name = f"{f}{lag_col_prefix}"
                ind[col_name] = ind[f].shift(lag)


def _add_volatility_features(ind: pd.DataFrame) -> None:
    """添加波动率相关特征：vol_of_vol (波动率的波动性) 和 vol_change (波动率变化率)。
    
    参数:
        ind: 指标DataFrame
    """
    # vol_of_vol：10周期波动率的标准差，衡量波动率自身的变化率
    if "vol" in ind.columns:
        ind["vol_of_vol"] = ind["vol"].rolling(10, min_periods=1).std()
    # vol_change：波动率变化率
    if "vol" in ind.columns:
        ind["vol_change"] = ind["vol"].pct_change()


def _add_price_pattern_features(ind: pd.DataFrame) -> None:
    """添加价格形态特征：close_open_ratio (收盘开盘比率) 和 high_low_ratio (最高最低比率)。
    
    参数:
        ind: 指标DataFrame
    """
    # close_open_ratio：收盘价/开盘价，>1 表示收于开盘价上方（看多），<1 表示收于开盘价下方（看空）
    if "close" in ind.columns and "open" in ind.columns:
        ind["close_open_ratio"] = ind["close"] / ind["open"].replace(0, np.nan)
    # high_low_ratio：最高价/最低价，反映K线体量大小，数值越大表示单日波动越大
    if "high" in ind.columns and "low" in ind.columns:
        ind["high_low_ratio"] = ind["high"] / ind["low"].replace(0, np.nan).replace([np.inf, -np.inf], np.nan)


def _add_volume_features(ind: pd.DataFrame) -> None:
    """添加成交量相关特征：volume_chg (成交量变化率), volume_ma_ratio (成交量均线比), volume_std_ratio (成交量标准差比)。
    
    参数:
        ind: 指标DataFrame
    """
    if "volume" in ind.columns:
        # volume_chg：成交量变化率
        ind["volume_chg"] = ind["volume"].pct_change()
    if "volume" in ind.columns:
        # volume_ma_ratio：成交量/20日均量，>1 表示成交放大，<1 表示成交萎缩
        ind["volume_ma_ratio"] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).mean()
    if "volume" in ind.columns:
        # volume_std_ratio：成交量/20日标准差比，反映成交量异常程度
        ind["volume_std_ratio"] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).std()


def build_features(
    df: pd.DataFrame,
    extended: bool = True,
    symbol: str = "UNKNOWN",
    period: str = "1m"
) -> tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """返回 (ind, F, feature_names)。

    参数:
        df: K 线 DataFrame（含 open/high/low/close/volume 列）。
        extended: 是否使用扩展特征集。
        symbol / period: 用于 LRU 缓存键。

    返回:
        ind: 计算完全部技术指标与衍生列的 DataFrame（含 ret / vol / close 等）。
        F: 已按 EXTENDED_FEATURES / BASE_FEATURES 列序对齐 + 滚动 z-score 的特征矩阵（DataFrame）。
        feature_names: F 的列顺序（训练 / 推理须保持一致）。
    """
    # 尝试从共享 LRU 缓存获取指标计算结果（键：symbol+period+数据量+最新索引）
    # —— 修复基线损坏：原代码自引用本模块不存在的 _IndicatorLRUCache
    cached_ind = _IndicatorLRUCache.get(symbol, period, df)
    if cached_ind is not None:
        ind = cached_ind
    else:
        # 缓存未命中，计算指标 - 启用所有指标类型（tech.add_indicators 不接收 use_atr，ATR 系列恒开启）
        ind = add_indicators(df,
            ma_list=(5, 10, 20, 30, 60),
            use_boll=True,
            use_macd=True,
            use_kdj=True,
            use_rsi=True,
            use_dmi=True,
        )
        # 存入缓存
        _IndicatorLRUCache.put(symbol, period, df, ind)
    
    # 确保必要的列存在（兼容性处理）
    if "change" not in ind.columns:
        ind["change"] = ind["close"].diff()
    
    # 收益率
    ind["ret"] = ind["close"].pct_change()
    # 波动率
    ind["vol"] = ind["ret"].rolling(10, min_periods=1).std()
    
    # 选择特征名称
    if extended:
        feature_names = EXTENDED_FEATURES.copy()
    else:
        feature_names = BASE_FEATURES.copy()
    
    # ── 新增：批量计算滞后特征 ──
    _add_lag_features(ind, feature_names)
    
    # ── 新增：批量计算波动率特征 ──
    _add_volatility_features(ind)
    
    # ── 新增：批量计算价格形态特征 ──
    _add_price_pattern_features(ind)
    
    # ── 新增：批量计算成交量特征 ──
    _add_volume_features(ind)
    
    # ── 统一的趋势因子计算（循环外，避免局部变量作用域问题）——
    # ADXR 斜率：ADX 双指数平滑后的方向变化率，捕捉趋势强度持续性
    if "ADXR" in ind.columns:
        ind["adxr_slope5"] = ind["ADXR"].diff(5)
    else:
        ind["adxr_slope5"] = 0.0
    # DIF 斜率：MACD DIF 的一阶差分，领先于 MACD 柱，捕捉趋势拐点
    if "DIF" in ind.columns:
        ind["dif_slope5"] = ind["DIF"].diff(5)
    else:
        ind["dif_slope5"] = 0.0
    # 唐奇安通道分位排名：价格相对 20 日高低区间的位置
    hi20 = ind["high"].rolling(20, min_periods=1).max()
    lo20 = ind["low"].rolling(20, min_periods=1).min()
    donchian_span = hi20 - lo20
    ind["donchian_rank"] = ((ind["close"] - lo20) / donchian_span.replace(0, np.nan)) \
                         .clip(0, 1).fillna(0.5)
    # MA 斜率比 & 均线发散比（依赖 MA20 / MA60 / MA5 列，由 add_indicators 统一生成）
    ma20_col = "MA20" if "MA20" in ind.columns else None
    ma60_col = "MA60" if "MA60" in ind.columns else None
    ma5_col  = "MA5"  if "MA5"  in ind.columns else None
    if ma20_col and ma60_col:
        s20 = ind[ma20_col].pct_change(5).fillna(0)
        s60 = ind[ma60_col].pct_change(5).fillna(0)
        ind["ma_slope_ratio"] = (
            (s20 / ind[ma20_col].replace(0, np.nan)).fillna(0) /
            (s60 / ind[ma60_col].replace(0, np.nan)).replace(0, np.nan)
        ).fillna(0)
        if ma5_col:
            s_short = (ind[ma5_col] - ind[ma20_col]) / ind[ma20_col].replace(0, np.nan)
            s_long  = (ind[ma20_col] - ind[ma60_col]) / ind[ma60_col].replace(0, np.nan)
            ind["ma_divergence_ratio"] = (s_short / s_long.replace(0, np.nan)).fillna(0)
        else:
            ind["ma_divergence_ratio"] = 0.0
    else:
        ind["ma_slope_ratio"] = 0.0
        ind["ma_divergence_ratio"] = 0.0
    
    # ── 填充缺失的特征列（确保所有EXTENDED_FEATURES均出现在ind中）——
    for f in feature_names:
        if f not in ind.columns:
            # 根据特征名称动态生成默认值
            if f == "volume_chg":
                ind[f] = ind["volume"].pct_change() if "volume" in ind.columns else 0.0
            elif f == "volume_ma_ratio":
                ind[f] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).mean() if "volume" in ind.columns else 1.0
            elif f == "volume_std_ratio":
                ind[f] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).std() if "volume" in ind.columns else 1.0
            elif f == "vol_of_vol":
                ind[f] = ind["vol"].rolling(10, min_periods=1).std() if "vol" in ind.columns else 0.0
            elif f == "vol_change":
                ind[f] = ind["vol"].pct_change() if "vol" in ind.columns else 0.0
            elif f == "ret_lag1":
                ind[f] = ind["ret"].shift(1)
            elif f == "ret_lag2":
                ind[f] = ind["ret"].shift(2)
            elif f == "ret_lag5":
                ind[f] = ind["ret"].shift(5)
            elif f == "close_open_ratio":
                ind[f] = ind["close"] / ind["open"].replace(0, np.nan) if "open" in ind.columns else 1.0
            elif f == "high_low_ratio":
                ind[f] = ind["high"] / ind["low"].replace(0, np.nan).replace([np.inf, -np.inf], np.nan) if "high" in ind.columns and "low" in ind.columns else 1.0
            else:
                ind[f] = 0.0
    
    # 特征矩阵——只保留已选特征列
    F = ind[feature_names].copy()
    # 替换NaN为0，确保数值稳定（在计算z-score前填充，避免传播NaN）
    F = F.fillna(0.0)
    
    # 滚动z-score（window=120，仅用当前及之前）
    # 我们对每个特征列分别计算滚动均值和标准差，窗口大小为120，最小观测数为120（即不足120时不产生值，随后填0）
    F_zscore = F.copy()
    for col in F.columns:
        # 计算滚动均值和标准差，窗口=120，最小观测数=120
        rolling_mean = F[col].rolling(window=120, min_periods=120).mean()
        rolling_std  = F[col].rolling(window=120, min_periods=120).std()
        # 避免除以0：当std为0时，设置z-score为0（因为此时所有值均等于均值）
        # 将std中的0替换为np.nan以产生NaN，随后填充为0
        z = (F[col] - rolling_mean) / rolling_std.replace(0, np.nan)
        # 将 NaN（包括std为0的情况和窗口不足120的情况）填充为 0
        z = z.fillna(0)
        F_zscore[col] = z
    
    # 转换为numpy数组
    F_numpy = F_zscore.to_numpy()
    
    return ind, F_zscore, feature_names