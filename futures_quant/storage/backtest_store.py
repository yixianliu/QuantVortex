"""回测中心持久化存储层（SQLite，WAL 模式，线程安全）。

职责：
    - evolve_state   ：进化引擎断点状态 / 最新快照（KV，JSON 序列化）——
                       程序重启后无缝恢复到上次退出时的进度；
    - evolve_history ：历次回测（每一代进化）的完整结果——时间戳、品种、
                       代数、最优策略参数与全部指标，供历史查看与对比；
    - evolve_log     ：学习日志，重启后回放。

设计要点（高效可靠、不阻塞 GUI）：
    - WAL + synchronous=NORMAL：崩溃可恢复，写入亚毫秒级；
    - check_same_thread=False + threading.Lock：允许 Worker 后台线程直接
      落库（重量级写入全部发生在回测线程内，GUI 线程仅偶发小写入）；
    - 自动限容（history 1000 / log 500），防止无限膨胀拖慢读写。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
from typing import Any, Optional

from ..runtime import normalize_data_path


class BacktestStore:
    """回测中心专用持久化库（data/quant_backtest.db）。"""

    _PRUNE = {"evolve_history": 1000, "evolve_log": 500}

    def __init__(self, path: str = "data/quant_backtest.db") -> None:
        """初始化相关对象。
        
            参数:
                path: str"""
        self.path = normalize_data_path(path, "quant_backtest.db")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()
        self._migrate_schema()

    def _init_schema(self) -> None:
        """初始化表结构。"""
        with self._lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS evolve_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_ts TEXT);

            CREATE TABLE IF NOT EXISTS evolve_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                symbol TEXT, symbol_name TEXT, period TEXT,
                generation INTEGER, gen_in_symbol INTEGER,
                pop_size INTEGER,
                best_desc TEXT, best_signature TEXT,
                total_return REAL, annual_return REAL, sharpe REAL,
                max_drawdown REAL, win_rate REAL, trades INTEGER,
                fitness REAL,
                new_profitable INTEGER,
                profitable_total INTEGER,
                gene_json TEXT, metrics_json TEXT,
                trades_json TEXT, equity_curve_json TEXT);
            CREATE INDEX IF NOT EXISTS ix_hist_sym
                ON evolve_history(symbol, generation);

            CREATE TABLE IF NOT EXISTS evolve_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, text TEXT);
            """)
            self.conn.commit()

    def _migrate_schema(self) -> None:
        """增量迁移：为已存在的旧库补齐 R6 新增列（trades_json / equity_curve_json）。

        CREATE TABLE IF NOT EXISTS 不会修改既有表，老用户升级后数据目录里的
        quant_backtest.db 仍是 R5 时代 schema，会导致 R6 的 add_history 抛
        'no column named trades_json'。此处幂等补齐，避免升级后落库静默失败。
        """
        with self._lock:
            cols = {r[1] for r in self.conn.execute(
                "PRAGMA table_info(evolve_history)").fetchall()}
            for col, ddl in (("trades_json", "TEXT"),
                             ("equity_curve_json", "TEXT")):
                if col not in cols:
                    self.conn.execute(
                        f"ALTER TABLE evolve_history ADD COLUMN {col} {ddl}")
            self.conn.commit()

    # ------------------------------------------------------------------
    # KV 状态（引擎断点 / 最新快照）
    # ------------------------------------------------------------------
    def save_state(self, key: str, obj: Any) -> None:
        """保存状态。
        
            参数:
                key: str
                obj: Any"""
        try:
            payload = json.dumps(obj, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return
        with self._lock:
            self.conn.execute(
                "INSERT INTO evolve_state(key, value, updated_ts) "
                "VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_ts=excluded.updated_ts",
                (key, payload, dt.datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()

    def load_state(self, key: str) -> Optional[Any]:
        """加载状态。
        
            参数:
                key: str
        
            返回:
                Optional[Any]"""
        try:
            with self._lock:
                row = self.conn.execute(
                    "SELECT value FROM evolve_state WHERE key=?",
                    (key,)).fetchone()
            return json.loads(row["value"]) if row else None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 历史回测记录（每代一条）
    # ------------------------------------------------------------------
    def add_history(self, snap: dict) -> Optional[int]:
        """添加history。
        
            参数:
                snap: dict
        
            返回:
                Optional[int]"""
        ranked = snap.get("ranked") or []
        best = ranked[0] if ranked else {}
        m = best.get("metrics") or {}
        # R6：归因对话框需要分笔成交与资金曲线（轻量 JSON，单条历史 ~10~30KB）
        trades = snap.get("gen_best_trades") or []
        curve = snap.get("gen_best_curve") or []
        def _ser_trades(items) -> Optional[str]:
            """处理ser交易记录。
            
                参数:
                    items
            
                返回:
                    Optional[str]"""
            if not items:
                return None
            try:
                rows = [{
                    "datetime": str(t.datetime) if t.datetime else "",
                    "symbol": getattr(t, "symbol", ""),
                    "direction": t.direction.value if hasattr(t, "direction") else "",
                    "offset": t.offset.value if hasattr(t, "offset") else "",
                    "quantity": int(getattr(t, "quantity", 0)),
                    "price": float(getattr(t, "price", 0.0)),
                    "commission": float(getattr(t, "commission", 0.0)),
                    "pnl": float(getattr(t, "pnl", 0.0)),
                    "multiplier": float(getattr(t, "multiplier", 1.0)),
                } for t in items]
                return json.dumps(rows, ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                return None
        def _ser_curve(points) -> Optional[str]:
            """处理sercurve。
            
                参数:
                    points
            
                返回:
                    Optional[str]"""
            if not points:
                return None
            try:
                return json.dumps(
                    [(str(d), float(e), float(a)) for d, e, a in points],
                    ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                return None
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO evolve_history(ts, symbol, symbol_name, period, "
                "generation, gen_in_symbol, pop_size, best_desc, "
                "best_signature, total_return, annual_return, sharpe, "
                "max_drawdown, win_rate, trades, fitness, new_profitable, "
                "profitable_total, gene_json, metrics_json, "
                "trades_json, equity_curve_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (dt.datetime.now().isoformat(timespec="seconds"),
                 snap.get("symbol"), snap.get("symbol_name"),
                 snap.get("period"),
                 snap.get("generation"), snap.get("gen_in_symbol"),
                 len(ranked),
                 best.get("desc"), best.get("signature"),
                 m.get("total_return"), m.get("annual_return"),
                 m.get("sharpe"), m.get("max_drawdown"), m.get("win_rate"),
                 m.get("num_closing_trades"), best.get("fitness"),
                 len(snap.get("new_profitable") or []),
                 snap.get("profitable_total"),
                 json.dumps(best.get("gene") or {}, ensure_ascii=False)
                 if best.get("gene") else None,
                 json.dumps(m, ensure_ascii=False, default=str),
                 _ser_trades(trades),
                 _ser_curve(curve)))
            self.conn.commit()
            return cur.lastrowid

    def recent_history(self, limit: int = 300) -> list:
        """处理recenthistory。
        
            参数:
                limit: int
        
            返回:
                list"""
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT * FROM evolve_history ORDER BY id DESC LIMIT ?",
                    (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------
    # R6：归因详情（按 id 取回单条历史的成交 + 资金曲线）
    # ------------------------------------------------------------------
    def get_history_detail(self, history_id: int) -> Optional[dict]:
        """取回一条历史的完整细节：基础指标 + 分笔成交 + 资金曲线。"""
        try:
            with self._lock:
                row = self.conn.execute(
                    "SELECT * FROM evolve_history WHERE id=?",
                    (history_id,)).fetchone()
            if row is None:
                return None
            rec = dict(row)
            # 解析 trades_json / equity_curve_json（缺失则为空）
            for key in ("trades_json", "equity_curve_json"):
                if rec.get(key):
                    try:
                        rec[key.replace("_json", "")] = json.loads(rec[key])
                    except Exception:  # noqa: BLE001
                        rec[key.replace("_json", "")] = []
                else:
                    rec[key.replace("_json", "")] = []
            # gene_json / metrics_json 也顺手解析，便于 UI 重渲染
            for key, alias in (("gene_json", "gene"), ("metrics_json", "metrics")):
                if rec.get(key):
                    try:
                        rec[alias] = json.loads(rec[key])
                    except Exception:  # noqa: BLE001
                        rec[alias] = None
            return rec
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 学习日志
    # ------------------------------------------------------------------
    def add_log(self, text: str) -> None:
        """添加log。
        
            参数:
                text: str"""
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO evolve_log(ts, text) VALUES(?,?)",
                    (dt.datetime.now().isoformat(timespec="seconds"), text))
                self.conn.commit()
        except Exception:  # noqa: BLE001
            pass

    def recent_logs(self, limit: int = 200) -> list:
        """处理recentlogs。
        
            参数:
                limit: int
        
            返回:
                list"""
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT ts, text FROM evolve_log "
                    "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------
    def prune(self) -> None:
        """处理prune。"""
        with self._lock:
            for table, n in self._PRUNE.items():
                try:
                    self.conn.execute(
                        f"DELETE FROM {table} WHERE id IN ("
                        f"SELECT id FROM {table} "
                        f"ORDER BY id DESC LIMIT -1 OFFSET ?)", (n,))
                except Exception:  # noqa: BLE001
                    pass
            self.conn.commit()

    def checkpoint(self) -> None:
        """处理checkpoint。"""
        try:
            with self._lock:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self.conn.commit()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """关闭相关对象。"""
        try:
            self.checkpoint()
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass


# 模块级单例：整个进程共享一条连接，避免多页面重复打开
_STORE: Optional[BacktestStore] = None
_STORE_LOCK = threading.Lock()


def get_backtest_store() -> BacktestStore:
    """获取回测store。
    
        返回:
            BacktestStore"""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = BacktestStore()
        return _STORE
