"""本地 CSV/Parquet 真实行情回放源（R4 离线兜底，方案 C3）。

用于：把 akshare 拉到的真实行情（或手工整理的 CSV）落盘后，在封闭、可复现的
环境下回放，喂给回测引擎。与 SyntheticFeed / AkshareFeed 同契约。

文件命名约定：{base_dir}/{symbol 下划线}_{period}.csv
    例：data/real_samples/rb_SHFE_D.csv
    列必须含：datetime, open, high, low, close, volume, open_interest
    （与 DataFeed.get_history 约定一致）

base_dir 缺省为 <data_dir>/real_samples。若某 (symbol, period) 文件不存在，
回退 synthetic，保证上层不崩。
"""
from __future__ import annotations

import os

import pandas as pd

from .base import DataFeed
from ..runtime import get_data_dir


class CsvFeed(DataFeed):
    """从本地 CSV 读取真实行情回放（封闭、可复现）。"""

    def __init__(self, base_dir: str | None = None) -> None:
        """初始化相关对象。
        
            参数:
                base_dir: str | None"""
        self.base_dir = base_dir or os.path.join(get_data_dir(), "real_samples")
        self._mem: dict = {}

    def _path_for(self, symbol: str, period: str) -> str:
        """处理路径for。
        
            参数:
                symbol: str
                period: str
        
            返回:
                str"""
        return os.path.join(self.base_dir, f"{symbol.replace('.', '_')}_{period}.csv")

    def _load(self, symbol: str, period: str) -> pd.DataFrame | None:
        """加载相关对象。
        
            参数:
                symbol: str
                period: str
        
            返回:
                pd.DataFrame | None"""
        key = (symbol, period)
        if key in self._mem:
            return self._mem[key]
        path = self._path_for(symbol, period)
        if not os.path.exists(path):
            return None
        df = pd.read_csv(path)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        self._mem[key] = df
        return df

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
        df = self._load(symbol, period)
        if df is None:
            from .synthetic import SyntheticFeed
            return SyntheticFeed().get_history(symbol, start, end, period, limit)
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
        df = self._load(symbol, period)
        if df is None:
            from .synthetic import SyntheticFeed
            return SyntheticFeed().get_recent(symbol, period, limit)
        return df.tail(limit).reset_index(drop=True)
