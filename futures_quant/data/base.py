"""数据层基类：合约定义、历史行情源、实时网关接口。

- Contract：期货合约参数（乘数、最小变动价位、保证金率等），用于订单合法性校验。
- DataFeed：历史 K 线数据源（回测用）。
- Gateway ：实时行情 / 交易网关（仿真 / CTP 实盘用）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Dict, Optional

import pandas as pd

from ..core.types import Bar


# ---------------------------------------------------------------------------
# 数据来源可信化（阶段 0）
#
# 约定：所有对外返回的行情 DataFrame 必须携带以下元数据（pandas DataFrame.attrs）：
#   - data_source：实际产出数据的源（sina / akshare / csv / ctp / synthetic）
#   - is_synthetic：是否合成/演示数据（True 时界面必须常驻水印）
#   - is_stale：是否为过期缓存（网络失败后回退旧缓存时为 True）
#   - as_of：数据最后更新时间（datetime / Timestamp / str 均可）
#   - note：降级或异常原因（供 UI 与回测报告展示，空串表示无异常）
#
# 兼容性：只写 DataFrame.attrs，不改变列结构与返回类型，旧调用方零改动。
# ---------------------------------------------------------------------------
PROVENANCE_KEYS = ("data_source", "is_synthetic", "is_stale", "as_of", "note")


def attach_provenance(
    df: pd.DataFrame,
    source: str,
    is_synthetic: bool = False,
    is_stale: bool = False,
    as_of=None,
    note: str = "",
) -> pd.DataFrame:
    """给行情表写入来源元数据（原地写 attrs，返回同一对象便于链式调用）。"""
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    try:
        df.attrs["data_source"] = str(source)
        df.attrs["is_synthetic"] = bool(is_synthetic)
        df.attrs["is_stale"] = bool(is_stale)
        df.attrs["as_of"] = as_of if as_of is not None else datetime.now()
        df.attrs["note"] = str(note or "")
    except Exception:  # noqa: BLE001 - 元数据写入失败不应影响行情主流程
        pass
    return df


def get_provenance(df: Optional[pd.DataFrame]) -> dict:
    """读取来源元数据；缺失时返回保守默认值（未知来源、非合成、非陈旧）。"""
    base = {"data_source": "unknown", "is_synthetic": False,
            "is_stale": False, "as_of": None, "note": ""}
    if df is None or not isinstance(df, pd.DataFrame):
        return base
    for k in PROVENANCE_KEYS:
        if k in df.attrs:
            base[k] = df.attrs[k]
    return base


def provenance_text(source: str, is_synthetic: bool = False, is_stale: bool = False,
                    as_of=None, note: str = "") -> str:
    """按元数据字段生成界面可读的来源文本（UI 可绕过 DataFrame 直接调用）。"""
    name = {
        "sina": "新浪日线",
        "akshare": "AKShare",
        "csv": "本地CSV",
        "ctp": "CTP",
        "ctp-fallback": "CTP历史回退",
        "synthetic": "合成行情(模拟)",
        "unknown": "来源未知",
    }.get(str(source), str(source))
    flags = []
    if is_synthetic:
        flags.append("模拟数据")
    if is_stale:
        flags.append("过期缓存")
    if note:
        flags.append(str(note))
    ts = ""
    if as_of is not None:
        try:
            ts = str(as_of)[:19]
        except Exception:  # noqa: BLE001
            ts = ""
    return name + (f" · {' / '.join(flags)}" if flags else "") + (f" · {ts}" if ts else "")


def provenance_label(df: Optional[pd.DataFrame]) -> str:
    """生成界面可读的数据来源标签（含合成/陈旧警示）。"""
    p = get_provenance(df)
    return provenance_text(p["data_source"], p["is_synthetic"], p["is_stale"],
                           p["as_of"], p["note"])


# ---------------------------------------------------------------------------
# 数据新鲜度阈值（第三轮 A · P1）
#
# 约定（在取数层 get_bars 生效）：
#   - 日线：当前日期与最后一根日线之间 **超过 1 个交易日** 即 stale
#     （周五数据在周一仍算新鲜；周二起算过期）；
#   - 分钟线：超过 **5 分钟**（且不小于 5 个周期长度）即 stale；
#   - 小时线：超过 5 个周期长度即 stale；
#   - 周线：超过 7 个自然日即 stale；
#   - 未知周期：不做判断（返回 False，避免误报）。
# ---------------------------------------------------------------------------
def _business_days_between(d1, d2) -> int:
    """两个日期之间的交易日数（按工作日近似，不含节假日）。"""
    if d2 <= d1:
        return 0
    try:
        return max(0, len(pd.bdate_range(d1, d2)) - 1)
    except Exception:  # noqa: BLE001
        return (d2 - d1).days


def evaluate_staleness(as_of, period: str = "D", now=None) -> tuple[bool, str]:
    """按周期阈值判定数据是否过期，返回 `(is_stale, 原因)`。

    参数:
        as_of: 数据最后更新时间（最后一根 K 线时间 / 数据源更新时间）。
        period: 周期字符串（D/1D/W/1W/M 或 1m/5m/15m/30m/1h/4h）。
        now: 当前时间（默认取系统当前时间，便于测试注入）。
    """
    if as_of is None:
        return False, ""
    try:
        ts = pd.to_datetime(as_of)
        cur = pd.to_datetime(now) if now is not None else pd.Timestamp.now()
    except Exception:  # noqa: BLE001
        return False, ""
    p = str(period or "D").upper()
    raw = str(period or "D").strip()
    try:
        if p in ("D", "1D"):
            n = _business_days_between(ts.date(), cur.date())
            if n > 1:
                return True, f"日线已过期 {n} 个交易日"
            return False, ""
        if p in ("W", "1W"):
            days = (cur.date() - ts.date()).days
            if days > 7:
                return True, f"周线已过期 {days} 天"
            return False, ""
        # 月线仅接受 "M"（"1m" 是 1 分钟线，不能因 upper() 被误判为月线）
        if p == "M" and raw.upper() == "M" and not raw[:-1].isdigit():
            if (cur.date() - ts.date()).days > 31:
                return True, "月线已过期超过 31 天"
            return False, ""
        # 分钟 / 小时（按原始大小写判断，避免 "1m" 与 "1M" 混淆）
        low = raw.lower()
        if low.endswith("min") and low[:-3].isdigit():
            sec = int(low[:-3]) * 60
        elif low.endswith("m") and low[:-1].isdigit():
            sec = int(low[:-1]) * 60
        elif low.endswith("h") and low[:-1].isdigit():
            sec = int(low[:-1]) * 3600
        else:
            return False, ""
        limit = max(300, 5 * sec)          # 分钟线最少 5 分钟
        gap = (cur - ts).total_seconds()
        if gap > limit:
            return True, f"分钟线已过期 {int(gap)} 秒（阈值 {limit} 秒）"
        return False, ""
    except Exception:  # noqa: BLE001
        return False, ""



# ---------------------------------------------------------------------------
# 可插拔数据源注册表（为未来 TqSdk / CTP 真实前置留槽，本阶段不实现新源）
#
# 用法（未来）：
#   from futures_quant.data.base import register_feed
#   register_feed("tqsdk", lambda **kw: TqSdkFeed(**kw))
# 之后 Config 中 source="tqsdk" 即可被 MarketDataManager 识别。
# ---------------------------------------------------------------------------
_FEED_FACTORIES: Dict[str, Callable[..., "DataFeed"]] = {}


def register_feed(name: str, factory: Callable[..., "DataFeed"]) -> None:
    """注册一个数据源工厂（name 不区分大小写，重复注册后写覆盖）。"""
    _FEED_FACTORIES[str(name).lower()] = factory


def get_feed_factory(name: str) -> Optional[Callable[..., "DataFeed"]]:
    """按名称取数据源工厂；未注册返回 None。"""
    return _FEED_FACTORIES.get(str(name).lower())


def registered_feeds() -> list:
    """已注册的可插拔数据源名称（不含内置 sina/akshare/csv/ctp/synthetic）。"""
    return sorted(_FEED_FACTORIES.keys())


class Contract:
    """期货合约基础参数。"""

    def __init__(
        self,
        symbol: str,
        exchange: str,
        multiplier: float = 10.0,
        min_price_tick: float = 1.0,
        lot_size: int = 1,
        margin_rate: float = 0.10,
        commission_per_lot: float = 3.0,
        trading_hours: Optional[list] = None,
        delivery_date: Optional[str] = None,
        leverage: Optional[float] = None,
        close_today_commission_ratio: float = 0.5,
    ) -> None:
        """初始化相关对象。
        
            参数:
                symbol: str
                exchange: str
                multiplier: float
                min_price_tick: float
                lot_size: int
                margin_rate: float
                commission_per_lot: float
                trading_hours: Optional[list]
                delivery_date: Optional[str]
                leverage: Optional[float]
                close_today_commission_ratio: float"""
        self.symbol = symbol
        self.exchange = exchange
        self.multiplier = multiplier
        self.min_price_tick = min_price_tick
        self.lot_size = lot_size
        self.margin_rate = margin_rate
        self.commission_per_lot = commission_per_lot
        # 交易时段，如 [("09:00","10:15"),("10:30","11:30"),("13:30","15:00"),("21:00","23:00")]
        self.trading_hours = trading_hours or []
        # 交割日（最后交易日，ISO "YYYY-MM-DD"）；非空时引擎在临近交割时强制平仓
        self.delivery_date = delivery_date
        # 该合约杠杆（覆盖账户默认杠杆）
        self.leverage = leverage
        # 平今仓手续费折扣（期货 T+0 平今优惠，如 0.5 / 0.0）
        self.close_today_commission_ratio = close_today_commission_ratio

    def round_price(self, price: float) -> float:
        """将价格对齐到最小变动价位。"""
        tick = self.min_price_tick
        return round(price / tick) * tick


class DataFeed(ABC):
    """历史行情源（回测）。"""

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        start: str,
        end: str,
        period: str = "1m",
        limit: int = 0,
    ) -> pd.DataFrame:
        """返回列：[datetime, open, high, low, close, volume, open_interest]。"""


class Gateway(ABC):
    """实时行情 / 交易网关（仿真或 CTP）。"""

    def __init__(self) -> None:
        """初始化相关对象。"""
        self.on_bar: Optional[Callable[[Bar], None]] = None
        self.on_trade: Optional[Callable] = None
        self.on_log: Optional[Callable[[str], None]] = None

    @abstractmethod
    def connect(self) -> bool:
        """连接相关对象。
        
            返回:
                bool"""
        ...

    @abstractmethod
    def subscribe(self, symbol: str) -> None:
        """处理subscribe。
        
            参数:
                symbol: str"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接相关对象。"""
        ...
