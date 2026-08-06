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

    def __init__(self, cache_dir: str | None = None) -> None:
        self.cache_dir = cache_dir or os.path.join(get_data_dir(), "akshare_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._mem: dict = {}

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
        return os.path.join(self.cache_dir, f"{symbol.replace('.', '_')}_D.csv")

    def _load(self, symbol: str) -> pd.DataFrame:
        key = (symbol, "D")
        if key not in self._mem:
            df = self._fetch_daily(symbol)
            try:
                df.to_csv(self._cache_path(symbol), index=False)
            except Exception:  # noqa: BLE001
                pass
            self._mem[key] = df
        return self._mem[key]

    # ------------------------------------------------------------------
    def get_history(
        self, symbol: str, start: str, end: str,
        period: str = "1m", limit: int = 0,
    ) -> pd.DataFrame:
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
        if period not in ("D", "1D", "W", "1W"):
            from .synthetic import SyntheticFeed
            logger.warning("akshare 不支持周期 %s，回退合成行情", period)
            return SyntheticFeed().get_recent(symbol, period, limit)
        df = self._load(symbol)
        return df.tail(limit).reset_index(drop=True)
