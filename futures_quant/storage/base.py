"""存储后端抽象接口。

定义统一的存储契约，使上层（引擎 / 回测 / UI）不依赖具体数据库实现。
当前提供：
    - SQLiteBackend   ：默认，零配置单文件，适合桌面 exe / 仿真 / 回测落地
    - PostgresBackend ：生产 / 多账户 / 时序，基于 PostgreSQL + TimescaleDB 超表

所有方法均为同步接口；切换后端只需改 config.storage.backend，上层代码无需改动。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, List, Optional

from ..core.types import Bar, Order, Trade


class StorageBackend(ABC):
    # ---------------- 参数 (KV) ----------------
    @abstractmethod
    def save_param(self, key: str, value: Any) -> None:
        """保存一个策略 / 系统参数（覆盖写）。"""

    @abstractmethod
    def load_param(self, key: str, default: Any = None) -> Any:
        """读取参数，不存在时返回 default。"""

    # ---------------- 委托 ----------------
    @abstractmethod
    def insert_order(self, order: Order) -> None:
        """写入 / 更新一笔委托（按 order_id 幂等）。"""

    @abstractmethod
    def query_orders(self, symbol: Optional[str] = None) -> List[dict]:
        """查询委托；symbol 为空则返回全部。"""

    # ---------------- 成交 ----------------
    @abstractmethod
    def insert_trade(self, trade: Trade) -> None:
        """写入一笔成交记录。"""

    @abstractmethod
    def query_trades(self, symbol: Optional[str] = None) -> List[dict]:
        """查询成交；symbol 为空则返回全部。"""

    # ---------------- 行情（时间序列） ----------------
    @abstractmethod
    def insert_bars(self, bars: Iterable[Bar]) -> None:
        """批量写入 K 线（可接受 list / generator of Bar）。"""

    @abstractmethod
    def query_bars(
        self, symbol: str, start: Optional[str] = None,
        end: Optional[str] = None, limit: Optional[int] = None,
    ) -> List[Bar]:
        """按合约 + 时间区间查询 K 线，按时间升序返回 Bar 对象列表。"""

    # ---------------- 日志 ----------------
    @abstractmethod
    def insert_log(self, level: str, message: str, ts: Optional[str] = None) -> None:
        """写入一条分级日志。"""

    @abstractmethod
    def query_logs(self, limit: int = 200) -> List[dict]:
        """查询最近 limit 条日志（倒序）。"""

    # ---------------- 资金曲线 ----------------
    @abstractmethod
    def save_equity_point(self, dt: Any, equity: float, available: float, drawdown: float = 0.0) -> None:
        """写入一个资金曲线采样点（回测 / 实盘复盘用）。"""

    @abstractmethod
    def query_equity(self) -> List[dict]:
        """查询完整资金曲线（按时间升序）。"""

    @abstractmethod
    def close(self) -> None:
        """关闭连接 / 释放资源。"""
