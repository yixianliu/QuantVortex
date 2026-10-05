"""AkShare 真实期货行情数据源（R4 真实源，方案 C2）。

通过 akshare 拉取真实期货历史 K 线，实现 DataFeed 接口，与 SyntheticFeed
同契约，可由 MarketDataManager 工厂注入（source="akshare"）。

契约（DataFeed.get_history 约定返回列）：
    [datetime, open, high, low, close, volume, open_interest]

akshare 说明：
- 免费接口主力连续代码为「品种+0」（如 rb0、i0、IF0）；新浪源日线接口
  futures_zh_daily_sina 返回列 [date, open, high, low, close, volume, hold, settle]，
  需映射 date->datetime、hold->open_interest，并丢弃 settle。
- 免费接口仅提供日线/周线级别的「主力连续」历史，无分钟线；非日线周期回退合成。
- 主力连续无单月交割日（delivery_date=None），回测仍是真实行情。
- 拉取结果按 (symbol, period) 缓存到 data/akshare_cache/，避免重复联网。

网络不可用/接口异常时，本 feed 的方法会抛出异常，由上层（MarketDataManager
_build_feed / connect）捕获并回退 synthetic，绝不冒充实盘。
"""
from __future__ import annotations

import logging
import os
import time

import pandas as pd

from .base import DataFeed
from ..runtime import get_data_dir

logger = logging.getLogger(__name__)


def _to_ak_symbol(symbol: str) -> str:
    """rb.SHFE / RB / rb0 -> 新浪/akshare 主力连续代码（rb0）。"""
    code = symbol.split(".")[0]
    if code and code[-1].isdigit():
        # 已是 rb0 形式
        return code
    return code + "0"


class AkshareFeed(DataFeed):
    """基于 akshare 的真实期货历史行情源（日线/周线）。"""

    source_label = "AkShare 实盘日线"

    #: M5-02①：缓存「新鲜」窗口（秒）。TTL 内命中本地缓存则直接用（不联网）；
    #: 超过 TTL 才尝试联网刷新，刷新失败时回退陈旧缓存并以 ``is_stale=True`` 标注。
    CACHE_TTL_SEC = 3600

    def __init__(self, cache_dir: str | None = None) -> None:
        """初始化相关对象。

        参数:
            cache_dir: str | None"""
        self.cache_dir = cache_dir or os.path.join(get_data_dir(), "akshare_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._mem: dict = {}
        # M5-02①：最近一次 _load 是否回退到陈旧缓存（UI 据此标注「行情陈旧」）
        self.is_stale: bool = False

    # ------------------------------------------------------------------
    def _fetch_daily(self, symbol: str) -> pd.DataFrame:
        """拉取主力连续日线并规范为 DataFeed 列。"""
        import akshare as ak

        ak_symbol = _to_ak_symbol(symbol)
        # 大小写兜底：先原样，再大写，再小写
        last_err: Exception | None = None
        for cand in (ak_symbol, ak_symbol.upper(), ak_symbol.lower()):
            try:
                df = ak.futures_zh_daily_sina(symbol=cand)
                if df is not None and not df.empty:
                    break
            except Exception as e:  # noqa: BLE001
                last_err = e
        else:
            raise RuntimeError(f"akshare 拉取 {ak_symbol} 失败: {last_err}") from last_err

        df = df.rename(columns={"date": "datetime", "hold": "open_interest"})
        keep = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]
        df = df[[c for c in keep if c in df.columns]]
        for c in keep:
            if c not in df.columns:
                df[c] = 0.0
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def _cache_path(self, symbol: str) -> str:
        """处理缓存路径。
        
            参数:
                symbol: str
        
            返回:
                str"""
        return os.path.join(self.cache_dir, f"{symbol.replace('.', '_')}_D.csv")

    def _read_cache(self, symbol: str) -> "pd.DataFrame | None":
        """读取本地磁盘缓存（M5-02①）。文件不存在/损坏返回 None。

        参数:
            symbol: str

        返回:
            pd.DataFrame | None — 规范化的缓存 DataFrame（含 datetime 列），无则 None。
        """
        path = self._cache_path(symbol)
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_csv(path)
            if df is None or df.empty:
                return None
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.sort_values("datetime").reset_index(drop=True)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("akshare 缓存读取失败 %s: %s", symbol, exc)
            return None

    @staticmethod
    def _cache_fresh(path: str, ttl_sec: float) -> bool:
        """缓存文件是否在新鲜窗口内（按 mtime 判定）。"""
        try:
            return time.time() - os.path.getmtime(path) <= ttl_sec
        except OSError:
            return False

    def _load(self, symbol: str) -> pd.DataFrame:
        """加载日线（M5-02①：缓存优先 → 过期联网 → 失败陈旧兜底）。

        降级链：
        ① 内存缓存命中 → 直接用（``is_stale=False``）；
        ② 内存缺失：读磁盘缓存，**未过期（≤ CACHE_TTL_SEC）→ 直接用**（不联网）；
        ③ 磁盘过期/缺失 → 联网 ``_fetch_daily`` 刷新并写回缓存；
        ④ 联网失败但存在**陈旧**磁盘缓存 → 回退该缓存并以 ``is_stale=True`` 标注；
        ⑤ 联网失败且无缓存 → 抛异常，由上层 MarketDataManager 回退 synthetic。

        参数:
            symbol: str

        返回:
            pd.DataFrame — 规范化日线；陈旧兜底时 ``self.is_stale`` 为 True。
        """
        key = (symbol, "D")
        self.is_stale = False
        if key in self._mem:
            return self._mem[key]

        path = self._cache_path(symbol)
        disk = self._read_cache(symbol)
        # ② 未过期磁盘缓存：直接复用，避免无谓联网
        if disk is not None and self._cache_fresh(path, self.CACHE_TTL_SEC):
            self._mem[key] = disk
            return disk

        # ③ 过期/缺失：尝试联网刷新并写回缓存
        try:
            df = self._fetch_daily(symbol)
            try:
                df.to_csv(path, index=False)
            except Exception:  # noqa: BLE001 - 写缓存失败不影响主流程
                pass
            self._mem[key] = df
            return df
        except Exception as exc:  # noqa: BLE001
            # ④ 联网失败 → 陈旧缓存兜底（标注 is_stale）
            if disk is not None:
                logger.warning(
                    "akshare 联网失败（%s），回退陈旧缓存 %s（is_stale）", exc, symbol)
                self.is_stale = True
                self._mem[key] = disk
                return disk
            # ⑤ 无缓存可退 → 上抛，由上层回退 synthetic
            raise

    # ------------------------------------------------------------------
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
        if period not in ("D", "1D", "W", "1W"):
            # 免费接口无分钟线，回退合成（标注非真实）
            from .synthetic import SyntheticFeed
            logger.warning("akshare 不支持周期 %s，回退合成行情", period)
            return SyntheticFeed().get_history(symbol, start, end, period, limit)
        df = self._load(symbol)
        mask = (df["datetime"] >= pd.to_datetime(start)) & (df["datetime"] <= pd.to_datetime(end))
        out = df[mask]
        if limit:
            out = out.tail(limit)
        return out.reset_index(drop=True)

    def get_recent(self, symbol: str, period: str = "D", limit: int = 600) -> pd.DataFrame:
        """获取recent。
        
            参数:
                symbol: str
                period: str
                limit: int
        
            返回:
                pd.DataFrame"""
        if period not in ("D", "1D", "W", "1W"):
            from .synthetic import SyntheticFeed
            logger.warning("akshare 不支持周期 %s，回退合成行情", period)
            return SyntheticFeed().get_recent(symbol, period, limit)
        df = self._load(symbol)
        return df.tail(limit).reset_index(drop=True)
