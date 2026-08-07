"""新浪期货公开行情接入（实盘数据 · 免密钥 · 无需期货公司柜台）。

⚠️ 数据来源与边界
------------------
- 数据源：新浪财经公开 HTTP 接口 `InnerFuturesNewService.getDailyKLine`（主力连续合约）。
  该接口**无需 API Key、无需期货公司授权**，只要有外网即可拉取全市场真实日线。
- 覆盖：本系统 39 个期货品种的主力连续合约（rb0/cu0/au0/IF0/...）已验证全部可用，
  真实历史从上市日延续至最近交易日（如螺纹钢 2009 年起、共 4000+ 根）。
- 周期：
    * **日线 D / 周线 W：真实数据**（W 由真实日线重采样得到）；
    * **日内周期（1m/5m/.../4h）：免费接口不提供历史分钟线**，本类返回 None，
      由上层 MarketDataManager 自动回退到 SyntheticFeed（明确为模拟，绝不冒充实盘）。
- 实时：免费接口无可靠实时推送；「最新价」取真实日线最后一根（即最近交易日收盘），
  交易时段内若新浪追加了当日棒，轮询会自然刷新——属真实数据，不随机伪造。
- 本文件不连接任何私有网络、不写入任何凭据，仅做公开行情的读取与缓存。
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request

import pandas as pd

from .base import DataFeed

_SINA_URL = "https://stock2.finance.sina.com.cn/futures/api/json.php/InnerFuturesNewService.getDailyKLine"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}

_COLS = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]


class SinaFeed(DataFeed):
    """新浪公开期货行情源（实盘日线）。"""

    source_label = "新浪实盘日线"

    def __init__(self, cache_dir: str = "data/sina_cache", timeout: float = 6.0,
                 max_age_hours: float = 6.0) -> None:
        """初始化相关对象。
        
            参数:
                cache_dir: str
                timeout: float
                max_age_hours: float"""
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.max_age_hours = max_age_hours
        self._mem: dict[str, pd.DataFrame] = {}
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 符号映射：rb.SHFE / IF.CFFEX / rb0 -> rb0
    # ------------------------------------------------------------------
    @staticmethod
    def _to_sina(symbol: str) -> str:
        """处理tosina。
        
            参数:
                symbol: str
        
            返回:
                str"""
        s = symbol.split(".")[0] if "." in symbol else symbol
        if len(s) >= 2 and s.endswith("0"):
            return s
        return s + "0"

    # ------------------------------------------------------------------
    # 网络与缓存
    # ------------------------------------------------------------------
    def _http(self, url: str) -> str:
        # ⚠️ SSL 验证已禁用以兼容部分内网/代理环境。
        # 生产环境若涉及敏感数据，建议启用 check_hostname=True 和 CERT_REQUIRED。
        """处理http。
        
            参数:
                url: str
        
            返回:
                str"""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络请求失败: {e.reason}") from e
        except OSError as e:
            raise RuntimeError(f"IO 错误: {e}") from e

    def _cache_path(self, sina_sym: str) -> str:
        """处理缓存路径。
        
            参数:
                sina_sym: str
        
            返回:
                str"""
        safe = sina_sym.replace("/", "_")
        return os.path.join(self.cache_dir, f"{safe}.csv")

    def _load_cache(self, sina_sym: str) -> pd.DataFrame | None:
        """加载缓存。
        
            参数:
                sina_sym: str
        
            返回:
                pd.DataFrame | None"""
        p = self._cache_path(sina_sym)
        try:
            if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < self.max_age_hours * 3600:
                return pd.read_csv(p)
        except Exception:
            pass
        return None

    def _save_cache(self, sina_sym: str, df: pd.DataFrame) -> None:
        """保存缓存。
        
            参数:
                sina_sym: str
                df: pd.DataFrame"""
        try:
            df.to_csv(self._cache_path(sina_sym), index=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 取真实日线（内存 -> 磁盘 -> 网络）
    # ------------------------------------------------------------------
    def _fetch_daily(self, symbol: str) -> pd.DataFrame:
        """获取daily。
        
            参数:
                symbol: str
        
            返回:
                pd.DataFrame"""
        sina = self._to_sina(symbol)
        if sina in self._mem:
            return self._mem[sina]
        cached = self._load_cache(sina)
        if cached is not None:
            self._mem[sina] = cached
            return cached
        try:
            raw = self._http(f"{_SINA_URL}?symbol={sina}")
            arr = json.loads(raw)
            rows = [{
                "datetime": r["d"],
                "open": float(r["o"]), "high": float(r["h"]),
                "low": float(r["l"]), "close": float(r["c"]),
                "volume": float(r.get("v", 0) or 0),
                "open_interest": float(r.get("p", 0) or 0),
            } for r in arr]
            df = pd.DataFrame(rows, columns=_COLS)
            if df.empty:
                raise ValueError("empty response")
            self._mem[sina] = df
            self._save_cache(sina, df)
            return df
        except Exception:
            # 网络失败：尝试陈旧缓存兜底
            p = self._cache_path(sina)
            if os.path.exists(p):
                try:
                    df = pd.read_csv(p)
                    self._mem[sina] = df
                    return df
                except Exception:
                    pass
            return pd.DataFrame(columns=_COLS)

    # ------------------------------------------------------------------
    # DataFeed 接口
    # ------------------------------------------------------------------
    def get_history(self, symbol: str, start: str, end: str,
                    period: str = "D", limit: int = 0) -> pd.DataFrame | None:
        """返回真实日线/周线；日内周期返回 None（交由上层回退合成）。"""
        if period not in ("D", "1D", "W", "1W"):
            return None
        df = self._fetch_daily(symbol)
        if df is None or df.empty:
            return pd.DataFrame(columns=_COLS)
        df = df.copy()
        df["datetime"] = pd.to_datetime(df["datetime"])
        if period in ("W", "1W"):
            from .synthetic import resample_bars
            df = resample_bars(df, "W")
        lo = pd.to_datetime(start)
        hi = pd.to_datetime(end)
        df = df[(df["datetime"] >= lo) & (df["datetime"] <= hi)]
        if limit:
            df = df.tail(limit)
        return df.reset_index(drop=True)

    def get_recent(self, symbol: str, period: str = "D", limit: int = 600) -> pd.DataFrame:
        """获取recent。
        
            参数:
                symbol: str
                period: str
                limit: int
        
            返回:
                pd.DataFrame"""
        df = self.get_history(symbol, "2000-01-01", "2100-01-01", period=period, limit=limit)
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return pd.DataFrame(columns=_COLS)
        return df
