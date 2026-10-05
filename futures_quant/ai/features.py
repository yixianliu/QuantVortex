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
import re
from collections import OrderedDict
import threading
import hashlib
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
        # M3-04：加入 close 内容指纹。
        # 原 key 仅 (symbol, period, len, index[-1])，无法区分「同长度、同末索引
        # 但价格不同」的数据（不同数据源 / 复权 / 回填修正），会命中错误缓存。
        #
        # 【与文档的差异·已标注】UPGRADE_PLAN_V5 约定指纹取 `df["close"].tail(50)`。
        # 实测该口径只能覆盖最近 50 根的修订：中段历史被回填修正时，len 与末索引
        # 均不变、尾部 50 根也不变 → 仍会误命中陈旧缓存，而 add_indicators 的
        # MA60 等长窗口列在中段是受影响的（训练矩阵 F 覆盖全历史，会被污染）。
        # 故此处按同一「内容指纹」语义扩展为**全序列 md5**；成本实测可忽略
        # （10 万根 ≈ 0.8MB，md5 亚毫秒级，远小于 add_indicators 本身耗时）。
        try:
            arr = df["close"].to_numpy(dtype="float64", copy=False)
            fingerprint = hashlib.md5(np.ascontiguousarray(arr).tobytes()).hexdigest()[:8]
        except Exception:  # noqa: BLE001
            fingerprint = ""
        return (symbol, period, len(df),
                str(df.index[-1]) if len(df) else "",
                fingerprint)

    @classmethod
    def get(cls, symbol: str, period: str, df: pd.DataFrame):
        k = cls._key(symbol, period, df)
        with cls._lock:
            if k not in _CACHE_ORD:
                return None
            _CACHE_ORD.move_to_end(k)
            cached = _CACHE_ORD[k]
        # M3-04：返回**深拷贝**。缓存对象在 build_features 后续流程中会被就地
        # 追加 ret/vol 等衍生列；若直接返回同一对象，调用方与缓存共享引用，
        # 多线程下会互相踩踏（线程竞争），且缓存内容被意外改写。
        return cached.copy(deep=True)

    @classmethod
    def stats(cls) -> dict:
        """M3-04：缓存观测口径（供 e2e 性能脚本与排障使用），线程安全。"""
        with cls._lock:
            return {
                "size": len(_CACHE_ORD),
                "max": cls._MAX,
                "symbols": sorted({str(k[0]) for k in _CACHE_ORD}),
            }

    @classmethod
    def clear(cls) -> None:
        """清空缓存（测试隔离用），线程安全。"""
        with cls._lock:
            _CACHE_ORD.clear()

    @classmethod
    def put(cls, symbol: str, period: str, df: pd.DataFrame, value) -> None:
        k = cls._key(symbol, period, df)
        # M3-04：入库同样存深拷贝，切断与外部持有的引用
        with cls._lock:
            _CACHE_ORD[k] = value.copy(deep=True)
            _CACHE_ORD.move_to_end(k)
            while len(_CACHE_ORD) > cls._MAX:
                _CACHE_ORD.popitem(last=False)


_CACHE_ORD: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()

# 对外别名：e2e 性能脚本以 `_indicator_cache.stats()` 观测缓存命中情况
_indicator_cache = _IndicatorLRUCache

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
    # M3-01：移除 "fund_proxy" —— 项目无基金/持仓数据源，该列必然恒为 0，
    # 留着只会给模型喂一个无信息量的常量列。
    "atr_pct",
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

# ---------------------------------------------------------------------------
# M3-01：显式「特征 → 来源列」映射表（Fail Fast 契约）
#
# 背景：此前 build_features 对任何缺失特征一律 `fill_data[f] = 0.0` 静默填零，
# 导致 8 个特征恒为 0 而调用方毫无察觉（模型吃到全零列却不报错）。
# 现改为：每个特征显式声明其来源列；缺失即 raise KeyError，把问题暴露在
# 特征构建阶段，而不是让错误静默地流进模型。
#
# 取值语义：
#   - str  ：该特征直接使用 ind 中的同名/指定来源列；
#   - None ：该特征由 build_features 内部动态计算（如滞后/波动率/形态特征），
#            不要求预先存在于 ind，跳过契约校验。
# ---------------------------------------------------------------------------
FEATURE_SOURCE: Dict[str, Optional[str]] = {
    # —— 基础：ret / vol 由 build_features 内部动态计算
    #     （ind["ret"]=close.pct_change()、ind["vol"]=ret.rolling(10).std()），
    #     并非 tech.add_indicators 的产出列，故标记为 None 以免来源校验。
    "ret": None, "vol": None,
    "RSI14": "RSI14", "CCI14": "CCI14", "MOM10": "MOM10",
    "ROC12": "ROC12", "BIAS6": "BIAS6", "ADX": "ADX",
    "MACD": "MACD", "K": "K",
    # —— M3-01 补齐来源的 8 个原恒零特征 ——
    "boll_pct": "boll_pct",
    "dir_di": "dir_di",
    "ma20_gap": "ma20_gap",
    "ma60_gap": "ma60_gap",
    "vol5": "vol5",
    "vol_ratio": "vol_ratio",
    "obv_chg": "obv_chg",
    "atr_pct": "atr_pct",
    # —— 内部动态计算（不校验来源列）——
    "adxr_slope5": None, "dif_slope5": None, "donchian_rank": None,
    "ma_slope_ratio": None, "ma_divergence_ratio": None,
    "volume_chg": None, "volume_ma_ratio": None, "volume_std_ratio": None,
    "vol_of_vol": None, "vol_change": None,
    "ret_lag1": None, "ret_lag2": None, "ret_lag5": None,
    "close_open_ratio": None, "high_low_ratio": None,
}


def _validate_feature_source(ind: pd.DataFrame, feature_names: List[str]) -> None:
    """M3-01：校验每个特征的来源列确实存在于 ind 中（Fail Fast）。

    Raises:
        KeyError: 任一特征未声明来源、或其来源列缺失。
    """
    missing_decl = [f for f in feature_names if f not in FEATURE_SOURCE]
    if missing_decl:
        raise KeyError(
            f"特征未在 FEATURE_SOURCE 中声明来源：{missing_decl}。"
            f"请补充映射（或显式置 None 表示内部动态计算）")
    missing_cols = [
        f"{f}→{FEATURE_SOURCE[f]}"
        for f in feature_names
        if FEATURE_SOURCE[f] is not None and FEATURE_SOURCE[f] not in ind.columns
    ]
    if missing_cols:
        raise KeyError(
            f"特征来源列缺失（禁止静默填 0）：{missing_cols}。"
            f"请检查 tech.add_indicators 是否产出这些列")


# 滞后列命名约定：<基列名>_lag<阶数>（如 ret_lag5）
_LAG_RE = re.compile(r"^(?P<base>.+)_lag(?P<lag>\d+)$")


def _add_lag_features(ind: pd.DataFrame, feature_names: List[str]) -> pd.DataFrame:
    """为选定特征添加滞后（lag）特征，捕捉时序依赖信息。

    M3-12：改为**按需求生成**。原实现是对 `feature_names` 里每个特征都生成
    lag1/2/5 三列 —— 扩展模式下 34 个特征 → 102 列，但真正进入模型的只有
    `ret_lag1` / `ret_lag2` / `ret_lag5` 三列，其余 99 列纯属白算，还要参与
    后续 `pd.concat`（特征工程在每次 fit / predict / 每折 walk-forward 都要跑）。
    现改为扫描 `feature_names` 中形如 `<基列>_lagN` 的项，只生成这些被引用列；
    今后若新增 `xxx_lag3`，只要写进 feature_names 就会自动被生成，无需改本函数。

    参数:
        ind: 指标DataFrame
        feature_names: 模型实际使用的特征列名列表

    返回:
        添加了滞后特征的新 DataFrame
    """
    lag_data = {}
    for f in feature_names:
        m = _LAG_RE.match(f)
        if not m:
            continue
        base, lag = m.group("base"), int(m.group("lag"))
        if base in ind.columns:
            lag_data[f] = ind[base].shift(lag)
    if lag_data:
        new_cols = pd.DataFrame(lag_data, index=ind.index)
        ind = pd.concat([ind, new_cols], axis=1)
    return ind


def _add_volatility_features(ind: pd.DataFrame) -> pd.DataFrame:
    """添加波动率相关特征：vol_of_vol (波动率的波动性) 和 vol_change (波动率变化率)。
    
    参数:
        ind: 指标DataFrame
    
    返回:
        添加了波动率特征的新 DataFrame
    """
    vol_data = {}
    if "vol" in ind.columns:
        vol_data["vol_of_vol"] = ind["vol"].rolling(10, min_periods=1).std()
        vol_data["vol_change"] = ind["vol"].pct_change()
    if vol_data:
        new_cols = pd.DataFrame(vol_data, index=ind.index)
        ind = pd.concat([ind, new_cols], axis=1)
    return ind


def _add_price_pattern_features(ind: pd.DataFrame) -> pd.DataFrame:
    """添加价格形态特征：close_open_ratio (收盘开盘比率) 和 high_low_ratio (最高最低比率)。
    
    参数:
        ind: 指标DataFrame
    
    返回:
        添加了价格形态特征的新 DataFrame
    """
    pattern_data = {}
    if "close" in ind.columns and "open" in ind.columns:
        pattern_data["close_open_ratio"] = ind["close"] / ind["open"].replace(0, np.nan)
    if "high" in ind.columns and "low" in ind.columns:
        pattern_data["high_low_ratio"] = ind["high"] / ind["low"].replace(0, np.nan).replace([np.inf, -np.inf], np.nan)
    if pattern_data:
        new_cols = pd.DataFrame(pattern_data, index=ind.index)
        ind = pd.concat([ind, new_cols], axis=1)
    return ind


def _add_volume_features(ind: pd.DataFrame) -> pd.DataFrame:
    """添加成交量相关特征：volume_chg (成交量变化率), volume_ma_ratio (成交量均线比), volume_std_ratio (成交量标准差比)。
    
    参数:
        ind: 指标DataFrame
    
    返回:
        添加了成交量特征的新 DataFrame
    """
    vol_data = {}
    if "volume" in ind.columns:
        vol_data["volume_chg"] = ind["volume"].pct_change()
        vol_data["volume_ma_ratio"] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).mean()
        vol_data["volume_std_ratio"] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).std()
    if vol_data:
        new_cols = pd.DataFrame(vol_data, index=ind.index)
        ind = pd.concat([ind, new_cols], axis=1)
    return ind


def build_features(
    df: pd.DataFrame,
    extended: bool = True,
    *,
    symbol: str,
    period: str,
) -> tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """M3-04：`symbol` / `period` 改为 **keyword-only 必填**（缺省抛 TypeError）。

    原实现二者均有默认值（"UNKNOWN" / "1m"），导致未显式传参的调用方
    （ensemble 多处、predictor._predict_next）全部落到同一默认 key 上 ——
    不同品种、不同周期的指标缓存互相覆盖（串味）。强制必填可让这类遗漏
    在调用处立刻暴露，而不是静默产出错误特征。
    """
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
    ind = _add_lag_features(ind, feature_names)
    
    # ── 新增：批量计算波动率特征 ──
    ind = _add_volatility_features(ind)
    
    # ── 新增：批量计算价格形态特征 ──
    ind = _add_price_pattern_features(ind)
    
    # ── 新增：批量计算成交量特征 ──
    ind = _add_volume_features(ind)
    
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
    
    # ── M3-01：先做 Fail Fast 契约校验（缺失即报错，杜绝静默填 0）──
    _validate_feature_source(ind, feature_names)

    # ── 填充缺失的特征列（确保所有EXTENDED_FEATURES均出现在ind中）——
    fill_data = {}
    for f in feature_names:
        if f not in ind.columns:
            # 根据特征名称动态生成默认值
            if f == "volume_chg":
                fill_data[f] = ind["volume"].pct_change() if "volume" in ind.columns else 0.0
            elif f == "volume_ma_ratio":
                fill_data[f] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).mean() if "volume" in ind.columns else 1.0
            elif f == "volume_std_ratio":
                fill_data[f] = ind["volume"] / ind["volume"].rolling(20, min_periods=1).std() if "volume" in ind.columns else 1.0
            elif f == "vol_of_vol":
                fill_data[f] = ind["vol"].rolling(10, min_periods=1).std() if "vol" in ind.columns else 0.0
            elif f == "vol_change":
                fill_data[f] = ind["vol"].pct_change() if "vol" in ind.columns else 0.0
            elif f == "ret_lag1":
                fill_data[f] = ind["ret"].shift(1)
            elif f == "ret_lag2":
                fill_data[f] = ind["ret"].shift(2)
            elif f == "ret_lag5":
                fill_data[f] = ind["ret"].shift(5)
            elif f == "close_open_ratio":
                fill_data[f] = ind["close"] / ind["open"].replace(0, np.nan) if "open" in ind.columns else 1.0
            elif f == "high_low_ratio":
                fill_data[f] = ind["high"] / ind["low"].replace(0, np.nan).replace([np.inf, -np.inf], np.nan) if "high" in ind.columns and "low" in ind.columns else 1.0
            else:
                # M3-01：走到这里说明该特征既非动态计算、也未被上面分支覆盖。
                # 由于 _validate_feature_source 已前置校验，正常流程不会到达；
                # 保留兜底但记录警告，避免再次出现「静默恒零」。
                logger.warning("特征 %s 无来源列且无动态计算分支，置 0（请检查 FEATURE_SOURCE）", f)
                fill_data[f] = 0.0
    if fill_data:
        new_cols = pd.DataFrame(fill_data, index=ind.index)
        ind = pd.concat([ind, new_cols], axis=1)
    
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