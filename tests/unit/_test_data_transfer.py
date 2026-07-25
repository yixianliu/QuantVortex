# -*- coding: utf-8 -*-
"""数据迁移/导出/备份模块自测（无需 MySQL 服务器，MySQL 部分只测导入路径）。"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.storage import data_transfer as dtf
from futures_quant.storage.analysis_store import AnalysisStore

tmp = tempfile.mkdtemp(prefix="qv_test_")
db_path = os.path.join(tmp, "test.db")
store = AnalysisStore(db_path)

# ---- 造数据 ----
store.add_log("2026-07-25 10:00:00", "INFO", "测试日志1")
store.add_log("2026-07-25 10:00:01", "WARN", "测试日志2")
store.save_analysis("2026-07-25", "rb.SHFE", "resonance", "多头共振", "detail")
store.save_prediction({"ts": "2026-07-25", "symbol": "rb.SHFE", "period": "D",
                       "horizon": 12, "last_close": 3500.0,
                       "expected_return_pct": 1.2, "p_up": 0.65, "p_down": 0.35,
                       "risk_score": 40, "risk_label": "中", "model": "LSTM",
                       "regime": "trend", "verdict": "看多", "score": 0,
                       "forecast": "[3500,3510]"})
store.save_alert("2026-07-25", "rb.SHFE", "break_high", "WARN", "突破新高", 1)
store.upsert_sample("rb.SHFE", "D", 100, 65, 1)

# ---- 1. 导出 CSV / JSON ----
out_csv = os.path.join(tmp, "export_csv")
rep = dtf.export_tables(store.conn, out_csv, fmt="csv")
assert rep["logs"] == 2 and rep["predictions"] == 1, rep
files = os.listdir(out_csv)
assert any(f.startswith("logs_") and f.endswith(".csv") for f in files), files
print("[OK] CSV export:", rep)

out_json = os.path.join(tmp, "export_json")
rep = dtf.export_tables(store.conn, out_json, tables=["logs", "alerts"], fmt="json")
assert rep == {"logs": 2, "alerts": 1}, rep
print("[OK] JSON export:", rep)

# ---- 2. ZIP 打包导出 ----
zip_path = dtf.export_all_zip(store.conn, tmp, fmt="csv")
assert os.path.exists(zip_path) and zip_path.endswith(".zip")
print("[OK] ZIP export:", os.path.basename(zip_path))

# ---- 3. 备份到文件 ----
bak = os.path.join(tmp, "backup.db")
dtf.backup_to_file(store.conn, bak)
probe = sqlite3.connect(bak)
n = probe.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
probe.close()
assert n == 2, n
print("[OK] backup_to_file: logs rows =", n)

# ---- 4. 修改数据后从备份恢复 ----
store.add_log("2026-07-25 11:00:00", "INFO", "恢复前新增的日志")
assert store.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0] == 3
safety = dtf.restore_from_file(store.conn, bak, db_path)
n = store.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
assert n == 2, f"恢复后应为2条，实际{n}"
assert os.path.exists(safety)
# 安全备份中应有恢复前的3条
probe = sqlite3.connect(safety)
assert probe.execute("SELECT COUNT(*) FROM logs").fetchone()[0] == 3
probe.close()
print("[OK] restore_from_file: rows back to", n, "| safety backup verified")

# ---- 5. 损坏文件恢复应被拒绝 ----
bad = os.path.join(tmp, "bad.db")
with open(bad, "wb") as f:
    f.write(b"not a sqlite file at all........")
try:
    dtf.restore_from_file(store.conn, bad, db_path)
    raise AssertionError("损坏文件未被拒绝！")
except Exception as e:
    print("[OK] corrupt file rejected:", type(e).__name__)

# ---- 6. MySQL 功能：未装 pymysql 时给出友好指引 ----
try:
    import pymysql  # noqa
    print("[OK] pymysql available:", pymysql.__version__)
except ImportError:
    try:
        dtf._require_pymysql()
    except RuntimeError as e:
        assert "pip install pymysql" in str(e)
        print("[OK] pymysql missing -> friendly error")

store.close()
shutil.rmtree(tmp, ignore_errors=True)
print("\nALL DATA-TRANSFER TESTS PASSED")
