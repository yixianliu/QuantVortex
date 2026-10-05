"""PostgreSQL / TimescaleDB 存储后端（生产 / 多账户 / 时序）。

适用场景：
    - 实盘多账户并发写入（SQLite 单写者不满足时）；
    - 海量历史 K 线存储与回测复盘（TimescaleDB 超表按时间分块，区间查询极快）；
    - 跨机器访问（CTP 实盘机与策略研究机分离）。

依赖：psycopg（v3）或 psycopg2。未安装时**仅在实例化时报错**，不影响默认 SQLite 路径的导入与运行。
TimescaleDB 扩展若未安装，自动退回普通表（功能仍可用，仅失去时序分块优化）。
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

from ..core.types import Bar, Order, Trade
from .base import StorageBackend


class PostgresBackend(StorageBackend):
    """PostgreSQL + TimescaleDB 存储后端：面向生产 / 多账户 / 时序场景。
    
        继承: StorageBackend"""
    def __init__(self, host: str = "127.0.0.1", port: int = 5432, dbname: str = "futures",
                 user: str = "postgres", password: str = "", timescale: bool = True,
                 dsn: Optional[str] = None) -> None:
        """初始化相关对象。
        
            参数:
                host: str
                port: int
                dbname: str
                user: str
                password: str
                timescale: bool
                dsn: Optional[str]"""
        self._pg = self._load_driver()
        self._timescale = timescale
        self.conn = self._connect(dsn, host, port, dbname, user, password)
        self._init_schema()

    @staticmethod
    def _load_driver():
        """加载driver。"""
        try:
            import psycopg  # psycopg3
            return psycopg
        except ImportError:
            try:
                import psycopg2 as pg2  # psycopg2
                return pg2
            except ImportError as exc:
                raise ImportError(
                    "PostgresBackend 需要 psycopg 或 psycopg2，请先 `pip install psycopg`。"
                ) from exc

    def _connect(self, dsn, host, port, dbname, user, password):
        """连接相关对象。
        
            参数:
                dsn
                host
                port
                dbname
                user
                password"""
        if dsn:
            return self._pg.connect(dsn)
        return self._pg.connect(host=host, port=port, dbname=dbname, user=user, password=password)

    def _cursor(self):
        """处理cursor。"""
        return self.conn.cursor()

    # ---------- schema ----------
    def _init_schema(self) -> None:
        """初始化表结构。"""
        cur = self._cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS params (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("""CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, offset TEXT,
            quantity INTEGER, order_type TEXT, limit_price DOUBLE PRECISION, status TEXT,
            filled_price DOUBLE PRECISION, filled_quantity INTEGER, reject_reason TEXT, datetime TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trades (
            trade_id BIGSERIAL PRIMARY KEY, order_id TEXT, symbol TEXT, direction TEXT,
            offset TEXT, quantity INTEGER, price DOUBLE PRECISION, commission DOUBLE PRECISION,
            pnl DOUBLE PRECISION, datetime TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS logs (
            id BIGSERIAL PRIMARY KEY, level TEXT, message TEXT, ts TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS bars (
            symbol TEXT, datetime TIMESTAMPTZ, open DOUBLE PRECISION, high DOUBLE PRECISION,
            low DOUBLE PRECISION, close DOUBLE PRECISION, volume DOUBLE PRECISION,
            open_interest DOUBLE PRECISION)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS equity (
            id BIGSERIAL PRIMARY KEY, dt TIMESTAMPTZ, equity DOUBLE PRECISION,
            available DOUBLE PRECISION, drawdown DOUBLE PRECISION)""")
        if self._timescale:
            try:
                cur.execute("SELECT create_hypertable('bars','datetime', if_not_exists => TRUE)")
                cur.execute("SELECT create_hypertable('equity','dt', if_not_exists => TRUE)")
            except Exception:
                # TimescaleDB 未安装或已存在 -> 退回普通表
                pass
        self.conn.commit()

    # ---------- 参数 ----------
    def save_param(self, key: str, value: Any) -> None:
        """保存参数。
        
            参数:
                key: str
                value: Any"""
        cur = self._cursor()
        cur.execute(
            "INSERT INTO params (key,value) VALUES (%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, str(value)))
        self.conn.commit()

    def load_param(self, key: str, default: Any = None) -> Any:
        """加载参数。
        
            参数:
                key: str
                default: Any
        
            返回:
                Any"""
        cur = self._cursor()
        cur.execute("SELECT value FROM params WHERE key=%s", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    # ---------- 委托 ----------
    def insert_order(self, order: Order) -> None:
        """处理insert订单。
        
            参数:
                order: Order"""
        cur = self._cursor()
        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (order_id) DO UPDATE SET "
            "status=EXCLUDED.status, filled_price=EXCLUDED.filled_price, "
            "filled_quantity=EXCLUDED.filled_quantity, reject_reason=EXCLUDED.reject_reason",
            (order.order_id, order.symbol, order.direction.value, order.offset.value,
             order.quantity, order.order_type.value, order.limit_price, order.status.value,
             order.filled_price, order.filled_quantity, order.reject_reason, str(order.datetime)))
        self.conn.commit()

    def query_orders(self, symbol: Optional[str] = None) -> List[dict]:
        """处理query订单。
        
            参数:
                symbol: Optional[str]
        
            返回:
                List[dict]"""
        cur = self._cursor()
        if symbol:
            cur.execute("SELECT * FROM orders WHERE symbol=%s", (symbol,))
        else:
            cur.execute("SELECT * FROM orders ORDER BY datetime")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ---------- 成交 ----------
    def insert_trade(self, trade: Trade) -> None:
        """处理insert交易。
        
            参数:
                trade: Trade"""
        cur = self._cursor()
        cur.execute(
            "INSERT INTO trades (order_id,symbol,direction,offset,quantity,price,commission,pnl,datetime)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (trade.order_id, trade.symbol, trade.direction.value, trade.offset.value,
             trade.quantity, trade.price, trade.commission, trade.pnl, str(trade.datetime)))
        self.conn.commit()

    def query_trades(self, symbol: Optional[str] = None) -> List[dict]:
        """处理query交易记录。
        
            参数:
                symbol: Optional[str]
        
            返回:
                List[dict]"""
        cur = self._cursor()
        if symbol:
            cur.execute("SELECT * FROM trades WHERE symbol=%s", (symbol,))
        else:
            cur.execute("SELECT * FROM trades ORDER BY datetime")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ---------- 行情 ----------
    def insert_bars(self, bars: Iterable[Bar]) -> None:
        """处理insertK线。
        
            参数:
                bars: Iterable[Bar]"""
        rows = [(b.symbol, str(b.datetime), b.open, b.high, b.low, b.close,
                 b.volume, b.open_interest) for b in bars]
        if not rows:
            return
        cur = self._cursor()
        cur.executemany(
            "INSERT INTO bars (symbol,datetime,open,high,low,close,volume,open_interest)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        self.conn.commit()

    def query_bars(self, symbol: str, start: Optional[str] = None,
                   end: Optional[str] = None, limit: Optional[int] = None) -> List[Bar]:
        """处理queryK线。
        
            参数:
                symbol: str
                start: Optional[str]
                end: Optional[str]
                limit: Optional[int]
        
            返回:
                List[Bar]"""
        sql = "SELECT * FROM bars WHERE symbol=%s"
        args: list = [symbol]
        if start:
            sql += " AND datetime>=%s"; args.append(start)
        if end:
            sql += " AND datetime<=%s"; args.append(end)
        sql += " ORDER BY datetime"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur = self._cursor()
        cur.execute(sql, args)
        cols = [d[0] for d in cur.description]
        want = ["symbol", "datetime", "open", "high", "low", "close", "volume", "open_interest"]
        idx = [cols.index(c) for c in want]
        return [Bar(*(r[i] for i in idx)) for r in cur.fetchall()]

    # ---------- 日志 ----------
    def insert_log(self, level: str, message: str, ts: Optional[str] = None) -> None:
        """处理insertlog。
        
            参数:
                level: str
                message: str
                ts: Optional[str]"""
        cur = self._cursor()
        cur.execute("INSERT INTO logs (level,message,ts) VALUES (%s,%s,%s)", (level, message, ts))
        self.conn.commit()

    def query_logs(self, limit: int = 200) -> List[dict]:
        """处理querylogs。
        
            参数:
                limit: int
        
            返回:
                List[dict]"""
        cur = self._cursor()
        cur.execute("SELECT * FROM logs ORDER BY id DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ---------- 资金曲线 ----------
    def save_equity_point(self, dt: Any, equity: float, available: float, drawdown: float = 0.0) -> None:
        """保存权益point。
        
            参数:
                dt: Any
                equity: float
                available: float
                drawdown: float"""
        cur = self._cursor()
        cur.execute(
            "INSERT INTO equity (dt,equity,available,drawdown) VALUES (%s,%s,%s,%s)",
            (str(dt), float(equity), float(available), float(drawdown)))
        self.conn.commit()

    def query_equity(self) -> List[dict]:
        """处理query权益。
        
            返回:
                List[dict]"""
        cur = self._cursor()
        cur.execute("SELECT * FROM equity ORDER BY dt")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def close(self) -> None:
        """关闭相关对象。"""
        self.conn.close()
