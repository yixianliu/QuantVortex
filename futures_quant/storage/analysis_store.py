"""分析系统存储层（SQLite，单文件、零配置、可随 EXE 分发）。

存储内容：
    - bars：历史 K 线缓存（按 symbol+period 索引，本地加速加载）；
    - predictions：每次 AI 预测记录（含预期收益、涨跌概率、风险度、模型类型）；
    - analysis：指标共振 / 背离等研判记录；
    - alerts：预警规则与触发日志；
    - logs：系统运行日志。

提供查询与 CSV 导出接口，供「日志 / 预警 / 报告」模块使用。
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import sqlite3
from typing import Any, Optional

from ..runtime import normalize_data_path


class AnalysisStore:
    def __init__(self, path: str = "data/quant_analysis.db") -> None:
        self.path = normalize_data_path(path, "quant_analysis.db")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # 使用归一化后的可写路径打开库，避免打包后从不可写目录启动时
        # 实际打开的库与 self.path 指向的不是同一个文件。
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # ---- 崩溃安全 + 读写效率的 PRAGMA ----
        self.conn.execute("PRAGMA journal_mode=WAL")          # 写前日志，崩溃可恢复
        self.conn.execute("PRAGMA synchronous=NORMAL")        # WAL 下兼顾安全与吞吐
        self.conn.execute("PRAGMA busy_timeout=5000")        # 并发写等待，避免 SQLITE_BUSY
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._healthy = self.integrity_check()

    # ----------------------------- 健壮性与恢复 -----------------------------
    @property
    def healthy(self) -> bool:
        return getattr(self, "_healthy", True)

    def integrity_check(self) -> bool:
        """返回数据库是否完好；用于启动时异常恢复判定。"""
        try:
            rows = self.conn.execute("PRAGMA integrity_check").fetchall()
            return bool(rows) and all((r[0] == "ok") for r in rows)
        except Exception:
            return False

    def checkpoint(self) -> None:
        """将 WAL 合并回主库，防止 WAL 无限增长；关闭/退出时调用。"""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()
        except Exception:
            pass

    _PRUNABLE = {"logs": 3000, "predictions": 2000, "analysis": 2000,
                 "alerts": 2000, "judgments": 2000}

    def prune(self, keep: Optional[dict] = None) -> None:
        """限制各表容量，避免历史记录无限膨胀影响读写效率。保留最近的 N 条。"""
        spec = keep or self._PRUNABLE
        for table, n in spec.items():
            try:
                # 删除「按 id 倒序后，跳过最近 n 条」的更旧记录
                self.conn.execute(
                    f"DELETE FROM {table} WHERE id IN ("
                    f"SELECT id FROM {table} ORDER BY id DESC LIMIT -1 OFFSET ?)", (n,))
            except Exception:
                pass
        self.conn.commit()

    def maintenance(self) -> None:
        """启动/定时维护：合并 WAL + 限容。"""
        self.checkpoint()
        self.prune()

    def _init_schema(self) -> None:
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS bars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, period TEXT, datetime TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, open_interest REAL);
        CREATE INDEX IF NOT EXISTS ix_bars ON bars(symbol, period, datetime);

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, period TEXT, horizon INTEGER,
            last_close REAL, expected_return_pct REAL,
            p_up REAL, p_down REAL, risk_score REAL, risk_label TEXT,
            model TEXT, regime TEXT, verdict TEXT, score REAL,
            forecast TEXT);

        CREATE TABLE IF NOT EXISTS analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, kind TEXT, summary TEXT, detail TEXT);

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, rule TEXT, level TEXT, message TEXT, fired INTEGER);

        CREATE TABLE IF NOT EXISTS alert_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, kind TEXT, param REAL, enabled INTEGER DEFAULT 1,
            note TEXT, created_ts TEXT, last_fired TEXT);
        CREATE INDEX IF NOT EXISTS ix_alert_rules ON alert_rules(symbol, kind);

        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, level TEXT, message TEXT);

        CREATE TABLE IF NOT EXISTS judgments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, category TEXT,
            decision TEXT, direction INTEGER, entry_price REAL,
            note TEXT, outcome TEXT, closed_ts TEXT);
        CREATE INDEX IF NOT EXISTS ix_judgments ON judgments(symbol, ts);

        CREATE TABLE IF NOT EXISTS screening_samples (
            symbol TEXT PRIMARY KEY,
            period TEXT DEFAULT 'D',
            available_bars INTEGER DEFAULT 0,
            required_bars INTEGER DEFAULT 65,
            sufficient INTEGER DEFAULT 0,
            last_collected_ts TEXT,
            status TEXT DEFAULT 'ok',
            note TEXT);
        """)
        # 预测历史表增量迁移（库文件可能已存在旧 schema，需兼容追加列）
        self._migrate_predictions()
        self.conn.commit()

    def _migrate_predictions(self) -> None:
        """为已存在的 predictions 表追加新列（SQLite 不支持 ADD COLUMN IF NOT EXISTS）。"""
        wanted = {
            "confidence": "REAL",
            "status": "TEXT DEFAULT 'open'",
            "config": "TEXT DEFAULT 'enhanced'",
            "actual_return_pct": "REAL",
            "closed_ts": "TEXT",
        }
        cur = self.conn.execute("PRAGMA table_info(predictions)")
        exist = {r[1] for r in cur.fetchall()}
        for col, typedef in wanted.items():
            if col not in exist:
                try:
                    self.conn.execute(
                        f"ALTER TABLE predictions ADD COLUMN {col} {typedef}")
                except Exception:
                    pass

    # ----------------------------- 行情缓存 -----------------------------
    def cache_bars(self, symbol: str, period: str, df) -> None:
        rows = [(symbol, period, str(r["datetime"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]), float(r["volume"]),
                 float(r.get("open_interest", 0) or 0)) for _, r in df.iterrows()]
        self.conn.executemany(
            "INSERT INTO bars (symbol,period,datetime,open,high,low,close,volume,open_interest)"
            " VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def load_cached_bars(self, symbol: str, period: str, limit: int = 600) -> list:
        cur = self.conn.execute(
            "SELECT * FROM bars WHERE symbol=? AND period=? ORDER BY datetime DESC LIMIT ?",
            (symbol, period, limit))
        return [dict(r) for r in cur.fetchall()][::-1]

    # ----------------------------- 预测记录 -----------------------------
    def save_prediction(self, rec: dict) -> int:
        """写入一条预测记录，返回自增 id（供后续回测/反馈闭环使用）。"""
        cur = self.conn.execute(
            "INSERT INTO predictions (ts,symbol,period,horizon,last_close,expected_return_pct,"
            "p_up,p_down,risk_score,risk_label,model,regime,verdict,score,forecast,"
            "confidence,status,config)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec.get("ts"), rec.get("symbol"), rec.get("period"), rec.get("horizon"),
             rec.get("last_close"), rec.get("expected_return_pct"),
             rec.get("p_up"), rec.get("p_down"), rec.get("risk_score"), rec.get("risk_label"),
             rec.get("model"), rec.get("regime"), rec.get("verdict"), rec.get("score"),
             rec.get("forecast"), rec.get("confidence"),
             rec.get("status", "open"), rec.get("config", "enhanced")))
        self.conn.commit()
        return cur.lastrowid

    def update_prediction_outcome(self, pred_id: int, actual_return_pct: float,
                                   hit: int, closed_ts: str) -> None:
        """预测到期结算：写入实际收益、方向是否命中、结算时间。"""
        self.conn.execute(
            "UPDATE predictions SET status='closed', actual_return_pct=?, "
            "score=?, closed_ts=? WHERE id=?",
            (actual_return_pct, hit, closed_ts, pred_id))
        self.conn.commit()

    def query_open_predictions(self, limit: int = 200) -> list:
        """返回尚未结算（status='open'）的预测记录。"""
        cur = self.conn.execute(
            "SELECT * FROM predictions WHERE status='open' ORDER BY id DESC LIMIT ?",
            (limit,))
        return [dict(r) for r in cur.fetchall()]

    def query_closed_predictions(self, limit: int = 6) -> list:
        """返回最近已结算（status='closed'）的预测记录，供学习看板展示。

        返回字段含：symbol, period, horizon, verdict, p_up,
        expected_return_pct(预测预期), actual_return_pct(真实), score(1命中/0未中),
        regime, model, config, closed_ts。
        """
        cur = self.conn.execute(
            "SELECT symbol, period, horizon, verdict, p_up, expected_return_pct, "
            "actual_return_pct, score, regime, model, config, closed_ts "
            "FROM predictions WHERE status='closed' ORDER BY id DESC LIMIT ?",
            (limit,))
        return [dict(r) for r in cur.fetchall()]

    def count_predictions(self, status: Optional[str] = None) -> int:
        """统计预测记录总数（可按 status 过滤），用于看板健康度提示。"""
        if status:
            return self.conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE status=?", (status,)
            ).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]

    def prediction_stats(self, symbol: Optional[str] = None) -> dict:
        """预测方向命中率统计（基于已结算记录）。

        命中定义：pred 时 p_up>0.5 且 实际收益>0，或 p_up<0.5 且 实际收益<0。
        按 总体 / 模型 / 行情状态 分组聚合，供「学习反馈」看板使用。
        """
        where = "WHERE status='closed'" + (" AND symbol=?" if symbol else "")
        args = (symbol,) if symbol else ()
        rows = self.conn.execute(
            f"SELECT * FROM predictions {where} ORDER BY id DESC", args).fetchall()
        rows = [dict(r) for r in rows]
        total = len(rows)
        hits = sum(1 for r in rows if int(r.get("score") or 0) == 1)
        by_model: dict = {}
        by_regime: dict = {}
        by_config: dict = {}
        for r in rows:
            m = r.get("model") or "未知"
            rg = r.get("regime") or "未知"
            cf = r.get("config") or "enhanced"
            for bucket, key in ((by_model, m), (by_regime, rg), (by_config, cf)):
                b = bucket.setdefault(key, {"total": 0, "hits": 0})
                b["total"] += 1
                b["hits"] += int(r.get("score") or 0)
        for bucket in (by_model, by_regime, by_config):
            for k, v in bucket.items():
                v["rate"] = (v["hits"] / v["total"]) if v["total"] else None
        return dict(total=total, hits=hits,
                    rate=(hits / total) if total else None,
                    by_model=by_model, by_regime=by_regime, by_config=by_config)

    # ----------------------------- 选品样本持久化 -----------------------------
    def upsert_sample(self, symbol: str, period: str, available: int,
                      required: int, sufficient: int, status: str = "ok",
                      note: str = "") -> None:
        """写入/更新某品种的样本状态。sufficient=0 表示样本不足、待补采。"""
        self.conn.execute(
            "INSERT INTO screening_samples (symbol,period,available_bars,required_bars,"
            "sufficient,last_collected_ts,status,note) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "period=excluded.period, available_bars=excluded.available_bars, "
            "required_bars=excluded.required_bars, sufficient=excluded.sufficient, "
            "last_collected_ts=excluded.last_collected_ts, status=excluded.status, "
            "note=excluded.note",
            (symbol, period, available, required, sufficient,
             str(dt.datetime.now()), status, note))
        self.conn.commit()

    def query_insufficient_samples(self) -> list:
        """返回所有样本不足（sufficient=0）的品种，供界面提示与补采。"""
        cur = self.conn.execute(
            "SELECT * FROM screening_samples WHERE sufficient=0 ORDER BY symbol")
        return [dict(r) for r in cur.fetchall()]

    def mark_sample_collected(self, symbol: str, available: int) -> None:
        self.conn.execute(
            "UPDATE screening_samples SET sufficient=1, available_bars=?, "
            "last_collected_ts=?, status='ok' WHERE symbol=?",
            (available, str(dt.datetime.now()), symbol))
        self.conn.commit()

    def query_predictions(self, symbol: Optional[str] = None, limit: int = 100) -> list:
        if symbol:
            cur = self.conn.execute(
                "SELECT * FROM predictions WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol, limit))
        else:
            cur = self.conn.execute("SELECT * FROM predictions ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    # ----------------------------- 研判记录 -----------------------------
    def save_analysis(self, ts: str, symbol: str, kind: str, summary: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO analysis (ts,symbol,kind,summary,detail) VALUES (?,?,?,?,?)",
            (ts, symbol, kind, summary, detail))
        self.conn.commit()

    def query_analysis(self, limit: int = 100) -> list:
        cur = self.conn.execute("SELECT * FROM analysis ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    # ----------------------------- 预警 -----------------------------
    def save_alert(self, ts: str, symbol: str, rule: str, level: str, message: str, fired: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO alerts (ts,symbol,rule,level,message,fired) VALUES (?,?,?,?,?,?)",
            (ts, symbol, rule, level, message, fired))
        self.conn.commit()

    def query_alerts(self, limit: int = 200) -> list:
        cur = self.conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    # ----------------------------- 预警规则 -----------------------------
    def add_alert_rule(self, rec: dict) -> int:
        """写入一条预警规则；返回自增 id。rec 字段：symbol/kind/param/enabled/note。"""
        cur = self.conn.execute(
            "INSERT INTO alert_rules (symbol,kind,param,enabled,note,created_ts,last_fired)"
            " VALUES (?,?,?,?,?,?,?)",
            (rec.get("symbol"), rec.get("kind"), rec.get("param"),
             int(bool(rec.get("enabled", True))), rec.get("note") or "",
             rec.get("created_ts"), None))
        self.conn.commit()
        return cur.lastrowid

    def list_alert_rules(self, enabled_only: bool = False) -> list:
        sql = "SELECT * FROM alert_rules"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id DESC"
        cur = self.conn.execute(sql)
        return [dict(r) for r in cur.fetchall()]

    def get_alert_rule(self, rid: int) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM alert_rules WHERE id=?", (rid,))
        r = cur.fetchone()
        return dict(r) if r else None

    def update_alert_rule(self, rid: int, **fields) -> None:
        allowed = {"symbol", "kind", "param", "enabled", "note"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        if "enabled" in sets:
            sets["enabled"] = int(bool(sets["enabled"]))
        cols = ", ".join(f"{k}=?" for k in sets)
        self.conn.execute(
            f"UPDATE alert_rules SET {cols} WHERE id=?",
            tuple(sets.values()) + (rid,))
        self.conn.commit()

    def set_alert_rule_enabled(self, rid: int, enabled: bool) -> None:
        self.update_alert_rule(rid, enabled=enabled)

    def touch_rule_fired(self, rid: int, ts: str) -> None:
        """记录规则最近一次触发时间，用于冷却去重。"""
        self.conn.execute(
            "UPDATE alert_rules SET last_fired=? WHERE id=?", (ts, rid))
        self.conn.commit()

    def remove_alert_rule(self, rid: int) -> None:
        self.conn.execute("DELETE FROM alert_rules WHERE id=?", (rid,))
        self.conn.commit()

    # ----------------------------- 选品判断记录 -----------------------------
    def save_judgment(self, rec: dict) -> int:
        """写入一条选品判断记录；返回自增 id。"""
        cur = self.conn.execute(
            "INSERT INTO judgments (ts,symbol,category,decision,direction,"
            "entry_price,note,outcome,closed_ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (rec.get("ts"), rec.get("symbol"), rec.get("category"),
             rec.get("decision"), rec.get("direction"), rec.get("entry_price"),
             rec.get("note"), rec.get("outcome"), rec.get("closed_ts")))
        self.conn.commit()
        return cur.lastrowid

    def query_judgments(self, symbol: Optional[str] = None, limit: int = 300) -> list:
        if symbol:
            cur = self.conn.execute(
                "SELECT * FROM judgments WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol, limit))
        else:
            cur = self.conn.execute(
                "SELECT * FROM judgments ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    def close_judgment(self, jid: int, outcome: str, closed_ts: str) -> None:
        """结算一条判断：写入 outcome(win/loss) 与结算时间。"""
        self.conn.execute(
            "UPDATE judgments SET outcome=?, closed_ts=? WHERE id=?",
            (outcome, closed_ts, jid))
        self.conn.commit()

    def judgment_stats(self, symbol: Optional[str] = None) -> dict:
        """统计已结算的方向性判断胜率。

        仅统计 direction != 0（做多/做空）且 outcome in (win,loss) 的记录。
        返回 {total, wins, losses, rate}；无样本时 rate=None。
        """
        rows = self.query_judgments(symbol, limit=2000)
        wins = losses = 0
        for r in rows:
            if r.get("direction") in (1, -1) and r.get("outcome") in ("win", "loss"):
                if r["outcome"] == "win":
                    wins += 1
                else:
                    losses += 1
        total = wins + losses
        return dict(total=total, wins=wins, losses=losses,
                    rate=(wins / total) if total else None)

    # ----------------------------- 日志 -----------------------------
    def add_log(self, ts: str, level: str, message: str) -> None:
        self.conn.execute("INSERT INTO logs (ts,level,message) VALUES (?,?,?)", (ts, level, message))
        self.conn.commit()

    def query_logs(self, limit: int = 300) -> list:
        cur = self.conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    # ----------------------------- 导出 -----------------------------
    def export_csv(self, table: str, path: str) -> bool:
        cols = {"predictions": ["ts","symbol","period","horizon","last_close","expected_return_pct",
                                "p_up","p_down","risk_score","risk_label","model","regime","verdict","score"],
                "alerts": ["ts","symbol","rule","level","message","fired"],
                "analysis": ["ts","symbol","kind","summary","detail"],
                "logs": ["ts","level","message"]}
        if table not in cols:
            return False
        cur = self.conn.execute(f"SELECT {','.join(cols[table])} FROM {table} ORDER BY id DESC")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols[table])
            w.writerows(cur.fetchall())
        return True

    def close(self) -> None:
        """落盘 WAL 后关闭，确保崩溃/退出前数据已持久化。"""
        try:
            self.checkpoint()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
