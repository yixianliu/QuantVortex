"""合成行情生成器（分析/预测系统的默认数据源）。

⚠️ 重要说明（务必阅读）
----------------------
本沙箱环境无法连接期货公司前置机，也未安装 vnpy / ctpbee / akshare 等任何
实时行情包，因此**无法获取真实交易所行情**。为保证系统「可运行、可演示、逻辑可验证」，
本文件提供一个**统计特征贴近真实期货**的合成行情引擎：

    - 几何布朗运动 + 波动率聚集（GARCH 风格的波动率状态切换）；
    - 成交量与「绝对收益 / 波动」正相关（量价齐升齐降）；
    - 持仓量缓慢均值回复 + 趋势期增仓；
    - 可注入趋势 / 震荡 / 混合三种市场状态。

真实部署时，请用 `data/ctp_gateway.py` 中预留的 `CTPFeed` 接入点替换为实盘行情
（详见该文件），切勿把合成结果当作真实市场结论对外发布。

所有数据、算法、指标、KP预测均基于该行情工作，逻辑链路完全真实可复盘。
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from ..core.types import Bar
from .base import DataFeed


# 真实期货合约参数（仅用于显示、价位对齐、资金流代理，不做交易撮合）
FUTURES_UNIVERSE = [
    # symbol, name, category, exchange, multiplier, min_tick, typical_price
    ("rb",  "螺纹钢",   "黑色系",   "SHFE", 10, 1.0,   3500.0),
    ("hc",  "热卷",     "黑色系",   "SHFE", 10, 1.0,   3700.0),
    ("i",   "铁矿石",   "黑色系",   "DCE",  100, 0.5,   850.0),
    ("j",   "焦炭",     "黑色系",   "DCE",  100, 0.5,   2200.0),
    ("jm",  "焦煤",     "黑色系",   "DCE",  60,  0.5,   1700.0),
    ("SF",  "硅铁",     "黑色系",   "CZCE", 5,   2.0,   7000.0),
    ("SM",  "锰硅",     "黑色系",   "CZCE", 5,   2.0,   6800.0),
    ("ss",  "不锈钢",   "黑色系",   "SHFE", 5,   5.0,   14000.0),
    ("cu",  "沪铜",     "有色金属", "SHFE", 5,   10.0,  68000.0),
    ("al",  "沪铝",     "有色金属", "SHFE", 5,   5.0,   19000.0),
    ("zn",  "沪锌",     "有色金属", "SHFE", 5,   5.0,   21000.0),
    ("ni",  "沪镍",     "有色金属", "SHFE", 1,   10.0,  130000.0),
    ("sn",  "沪锡",     "有色金属", "SHFE", 1,   10.0,  210000.0),
    ("pb",  "沪铅",     "有色金属", "SHFE", 5,   5.0,   16000.0),
    ("au",  "沪金",     "贵金属",   "SHFE", 1000, 0.02, 460.0),
    ("ag",  "沪银",     "贵金属",   "SHFE", 15,  1.0,   5800.0),
    ("sc",  "原油",     "能源化工", "INE",  1000, 0.1,  600.0),
    ("fu",  "燃油",     "能源化工", "SHFE", 10,  1.0,   3200.0),
    ("bu",  "沥青",     "能源化工", "SHFE", 10,  2.0,   3600.0),
    ("ru",  "橡胶",     "能源化工", "SHFE", 10,  5.0,   13000.0),
    ("l",   "塑料",     "能源化工", "DCE",  5,   1.0,   8200.0),
    ("v",   "PVC",      "能源化工", "DCE",  5,   1.0,   6000.0),
    ("ta",  "PTA",      "能源化工", "CZCE", 5,   2.0,   5800.0),
    ("MA",  "甲醇",     "能源化工", "CZCE", 10,  1.0,   2500.0),
    ("eg",  "乙二醇",   "能源化工", "DCE",  10,  1.0,   4200.0),
    ("pp",  "聚丙烯",   "能源化工", "DCE",  5,   1.0,   7500.0),
    ("m",   "豆粕",     "农产品",   "DCE",  10,  1.0,   3200.0),
    ("rm",  "菜粕",     "农产品",   "CZCE", 10,  1.0,   2600.0),
    ("y",   "豆油",     "农产品",   "DCE",  10,  2.0,   7800.0),
    ("p",   "棕榈油",   "农产品",   "DCE",  10,  2.0,   7200.0),
    ("sr",  "白糖",     "农产品",   "CZCE", 10,  1.0,   6200.0),
    ("cf",  "棉花",     "农产品",   "CZCE", 5,   5.0,   15000.0),
    ("c",   "玉米",     "农产品",   "DCE",  10,  1.0,   2400.0),
    ("jd",  "鸡蛋",     "农产品",   "DCE",  10,  1.0,   3800.0),
    ("AP",  "苹果",     "农产品",   "CZCE", 10,  1.0,   8000.0),
    ("CJ",  "红枣",     "农产品",   "CZCE", 5,   5.0,   11000.0),
    ("IF",  "沪深300股指", "金融",  "CFFEX", 300, 0.2,   3600.0),
    ("IH",  "上证50股指",  "金融",  "CFFEX", 300, 0.2,   2500.0),
    ("T",   "十债",     "金融",     "CFFEX", 10000, 0.005, 102.0),
]

# 为行情生成挑选一个稳定的随机种子（按 symbol 哈希，保证可复现但各品种不同）
def _seed_for(symbol: str) -> int:
    """处理seedfor。
    
        参数:
            symbol: str
    
        返回:
            int"""
    h = 0
    for ch in symbol:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % (2**31)


def generate_bars(
    symbol: str = "TEST.SHFE",
    n: int = 5000,
    mode: str = "mixed",
    start_price: float | None = None,
    seed: int | None = None,
    freq: str = "1min",
    start_time: str = "2024-01-01 09:00:00",
) -> pd.DataFrame:
    """生成统计特征贴近真实期货的 OHLCV 合成行情。

    Args:
        symbol:       合约代码（含交易所后缀，如 rb.SHFE）；用于挑选种子与默认价。
        n:            K 线数量。
        mode:         trend / range / mixed——市场状态。
        start_price: 起始价；缺省按 symbol 在 FUTURES_UNIVERSE 中的典型价。
        seed:        随机种子（缺省按 symbol 哈希，保证可复现且各品种不同）。
        freq:        pandas offset 周期字符串。
        start_time:  起始时间。
    """
    if seed is None:
        seed = _seed_for(symbol)
    rng = np.random.default_rng(seed)

    # 起始价：优先参数，其次 Universe，再兜底
    if start_price is None:
        start_price = 3500.0
        for row in FUTURES_UNIVERSE:
            if symbol.startswith(row[0]):
                start_price = row[6]
                break

    idx = pd.date_range(start=start_time, periods=n, freq=freq)

    # ---- 波动率聚集：慢变波动率状态 + 突发放大 ----
    base_vol = 0.0012
    vol_state = base_vol
    vols = np.empty(n)
    rets = np.empty(n)
    # 趋势漂移
    drift = np.zeros(n)
    if mode == "trend":
        # 分段趋势
        seg = n // 3
        drift[:seg] = 0.00045
        drift[seg:2*seg] = -0.00055
        drift[2*seg:] = 0.00040
    elif mode == "range":
        drift[:] = 0.0
    else:  # mixed：regime 切换
        regime = rng.integers(0, 2, n)
        drift = np.where(regime == 0, 0.00050, -0.00050)
        switch = rng.random(n) < 0.0015
        drift = np.where(switch, -drift, drift)

    for t in range(n):
        # 波动率状态缓慢回复到 base，并受随机冲击
        vol_state = vol_state + 0.02 * (base_vol - vol_state) + rng.normal(0, base_vol * 0.15)
        vol_state = max(vol_state, base_vol * 0.4)
        # 偶发波动率爆发（消息面冲击）
        if rng.random() < 0.004:
            vol_state *= rng.uniform(1.8, 3.2)
        vols[t] = vol_state
        shock = rng.normal(0, 1)
        rets[t] = drift[t] + vol_state * shock
        # 轻微序列相关（惯性）
        if t > 0:
            rets[t] += 0.04 * rets[t - 1]

    log_price = np.log(start_price) + np.cumsum(rets)
    close = np.exp(log_price)

    # 由 close 构造 OHLC（含影线），影线幅度与波动正相关
    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1] * (1 + rng.normal(0, 0.0004, n - 1))
    intraday = vols * np.abs(rng.normal(1.0, 0.4, n))
    high = np.maximum(open_, close) * (1 + intraday)
    low = np.minimum(open_, close) * (1 - intraday)

    # 成交量：与绝对收益正相关（量价齐升）+ 基线 + 趋势期增仓放量
    absr = np.abs(rets)
    volume = rng.integers(800, 1500, n).astype(float) * (1 + 6 * absr / base_vol)
    volume *= (1 + 0.3 * np.clip(drift / 0.0005, -1, 1))
    volume = np.clip(volume, 200, None)

    # 持仓量：缓慢变化，趋势期增仓、反转期减仓
    oi = np.zeros(n)
    oi[0] = 100000.0
    for t in range(1, n):
        dchg = rng.normal(0, 400) + 4000 * drift[t] / 0.0005
        oi[t] = max(oi[t - 1] + dchg, 30000)
    # 把持仓量缩放到合理量级（按合约乘数概念）
    oi = np.round(oi)

    df = pd.DataFrame({
        "datetime": idx,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": oi,
    })
    return df


def resample_bars(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """将 1min 基准行情重采样到目标周期。

    支持 1m/5m/15m/30m/1h/4h/日线(D)/周线(W)。
    聚合规则：open=首, high=最大, low=最小, close=尾, volume/oi=求和。
    """
    if period in ("1m", "1min"):
        return df.reset_index(drop=True)
    rule_map = {
        "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1h", "4h": "4h", "D": "1D", "W": "1W",
    }
    rule = rule_map.get(period, period)
    agg = {
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "open_interest": "sum",
    }
    out = df.set_index("datetime").resample(rule).agg(agg).dropna()
    out = out.reset_index()
    return out


class SyntheticFeed(DataFeed):
    """基于 generate_bars 的本地数据源（分析/预测/验证用）。

    周期感知：
        - 日内周期（1m/5m/15m/30m/1h/4h）：以 1 分钟为基准序列，按需重采样；
        - 日线/周线（D/W）：直接以该周期生成（日线约 720 根、周线约 300 根），
          避免「从 1 分钟重采样日线只剩几根」的陷阱，保证指标与预测有足够样本。
    """

    # 周期内基础粒度
    _INTRADAY = {"1m", "5m", "15m", "30m", "1h", "4h"}
    _FREQ = {"D": "1D", "W": "1W"}

    def __init__(self, cache: dict | None = None) -> None:
        """初始化相关对象。
        
            参数:
                cache: dict | None"""
        self._cache: dict = cache or {}

    def _mode_for(self, symbol: str) -> str:
        """处理模式for。
        
            参数:
                symbol: str
        
            返回:
                str"""
        mode = "mixed"
        for row in FUTURES_UNIVERSE:
            if symbol.startswith(row[0]):
                if row[2] in ("贵金属", "金融"):
                    mode = "mixed"
                elif row[2] == "黑色系":
                    mode = "trend"
                break
        return mode

    def _base_1m(self, symbol: str) -> pd.DataFrame:
        """处理base1m。
        
            参数:
                symbol: str
        
            返回:
                pd.DataFrame"""
        key = (symbol, "1m")
        if key not in self._cache:
            self._cache[key] = generate_bars(symbol=symbol, mode=self._mode_for(symbol), n=12000)
        return self._cache[key]

    def _base_period(self, symbol: str, period: str) -> pd.DataFrame:
        """处理base周期。
        
            参数:
                symbol: str
                period: str
        
            返回:
                pd.DataFrame"""
        key = (symbol, period)
        if key in self._cache:
            return self._cache[key]
        if period in self._INTRADAY:
            base = self._base_1m(symbol)
            out = resample_bars(base, period) if period != "1m" else base
        else:
            freq = self._FREQ.get(period, period)
            # 日线生成 720 根、周线 320 根，足够指标与预测
            n = 720 if period == "D" else 320
            out = generate_bars(symbol=symbol, mode=self._mode_for(symbol),
                                n=n, freq=freq,
                                start_time="2020-01-01 00:00:00")
        self._cache[key] = out
        return out

    def get_history(
        self, symbol: str, start: str, end: str,
        period: str = "1m", limit: int = 0,
    ) -> pd.DataFrame:
        """获取history。
        
            参数:
                symbol: str
                start: str
                end: str
                period: str
                limit: int
        
            返回:
                pd.DataFrame"""
        base = self._base_period(symbol, period).copy()
        df = base[(base["datetime"] >= start) & (base["datetime"] <= end)]
        if limit:
            df = df.tail(limit)
        return df.reset_index(drop=True)

    # 便捷：直接取最近 limit 根（用于 UI 实时拉取 / 分析）
    def get_recent(self, symbol: str, period: str = "1m", limit: int = 600) -> pd.DataFrame:
        """获取recent。
        
            参数:
                symbol: str
                period: str
                limit: int
        
            返回:
                pd.DataFrame"""
        return self._base_period(symbol, period).tail(limit).reset_index(drop=True)
