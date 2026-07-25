"""SQLite 存储后端（默认）。

特点：
    - 单文件、零配置、进程内，可直接随 exe 桌面程序分发；
    - 行情 K 线按 (symbol, datetime) 建索引，支持区间查询；
    - 适合仿真盘、回测落地、单机轻量实盘。

如需多账户并发 / 海量历史 K 线 / 跨机器访问，请在 config 中切换到 PostgresBackend。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable, List, Optional

from ..core.types import Bar, Order, Trade
from .base import StorageBackend
from ..runtime import normalize_data_path


class SQLiteBackend(StorageBackend):
    def __init__(self, path: str = "data/futures_quant.db") -> None:
        self.path = normalize_data_path(path, "futures_quant.db")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # check_same_thread=False：引擎在单线程事件循环内调用，允许回测/UI 线程读取
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL + 普通同步：本地单写者场景下大幅提升逐笔写入吞吐，且保证断电安全
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    # ---------- schema ----------
    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS params (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("""CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, offset TEXT,
            quantity INTEGER, order_type TEXT, limit_price REAL, status TEXT,
            filled_price REAL, filled_quantity INTEGER, reject_reason TEXT, datetime TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, symbol TEXT,
            direction TEXT, offset TEXT, quantity INTEGER, price REAL, commission REAL,
            pnl REAL, datetime TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT, message TEXT, ts TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS bars (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, datetime TEXT, open REAL,
            high REAL, low REAL, close REAL, volume REAL, open_interest REAL)""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_bars_sym_dt ON bars(symbol, datetime)")
        cur.execute("""CREATE TABLE IF NOT EXISTS equity (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dt TEXT, equity REAL, available REAL,
            drawdown REAL)""")
        self.conn.commit()

    # ---------- 参数 ----------
    def save_param(self, key: str, value: Any) -> None:
        self.conn.execute("INSERT OR REPLACE INTO params VALUES (?,?)", (key, str(value)))
        self.conn.commit()

    def load_param(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM params WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # ---------- 委托 ----------
    def insert_order(self, order: Order) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (order.order_id, order.symbol, order.direction.value, order.offset.value,
             order.quantity, order.order_type.value, order.limit_price, order.status.value,
             order.filled_price, order.filled_quantity, order.reject_reason, str(order.datetime)),
        )
        self.conn.commit()

    def query_orders(self, symbol: Optional[str] = None) -> List[dict]:
        if symbol:
            cur = self.conn.execute("SELECT * FROM orders WHERE symbol=?", (symbol,))
        else:
            cur = self.conn.execute("SELECT * FROM orders ORDER BY datetime")
        return [dict(r) for r in cur.fetchall()]

    # ---------- 成交 ----------
    def insert_trade(self, trade: Trade) -> None:
        self.conn.execute(
            "INSERT INTO trades (order_id,symbol,direction,offset,quantity,price,commission,pnl,datetime)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (trade.order_id, trade.symbol, trade.direction.value, trade.offset.value,
             trade.quantity, trade.price, trade.commission, trade.pnl, str(trade.datetime)),
        )
        self.conn.commit()

    def query_trades(self, symbol: Optional[str] = None) -> List[dict]:
        if symbol:
            cur = self.conn.execute("SELECT * FROM trades WHERE symbol=?", (symbol,))
        else:
            cur = self.conn.execute("SELECT * FROM trades ORDER BY datetime")
        return [dict(r) for r in cur.fetchall()]

    # ---------- 行情 ----------
    def insert_bars(self, bars: Iterable[Bar]) -> None:
        rows = [(b.symbol, str(b.datetime), b.open, b.high, b.low, b.close,
                 b.volume, b.open_interest) for b in bars]
        if not rows:
            return
        self.conn.executemany(
            "INSERT INTO bars (symbol,datetime,open,high,low,close,volume,open_interest)"
            " VALUES (?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def query_bars(self, symbol: str, start: Optional[str] = None,
                   end: Optional[str] = None, limit: Optional[int] = None) -> List[Bar]:
        sql = "SELECT * FROM bars WHERE symbol=?"
        args: list = [symbol]
        if start:
            sql += " AND datetime>=?"; args.append(start)
        if end:
            sql += " AND datetime<=?"; args.append(end)
        sql += " ORDER BY datetime"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur = self.conn.execute(sql, args)
        return [Bar(r["symbol"], r["datetime"], r["open"], r["high"], r["low"], r["close"],
                    r["volume"], r["open_interest"]) for r in cur.fetchall()]

    # ---------- 日志 ----------
    def insert_log(self, level: str, message: str, ts: Optional[str] = None) -> None:
        self.conn.execute("INSERT INTO logs (level,message,ts) VALUES (?,?,?)", (level, message, ts))
        self.conn.commit()

    def query_logs(self, limit: int = 200) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    # ---------- 资金曲线 ----------
    def save_equity_point(self, dt: Any, equity: float, available: float, drawdown: float = 0.0) -> None:
        self.conn.execute(
            "INSERT INTO equity (dt,equity,available,drawdown) VALUES (?,?,?,?)",
            (str(dt), float(equity), float(available), float(drawdown)),
        )
        self.conn.commit()

    def query_equity(self) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM equity ORDER BY dt")
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
