# -*- coding: utf-8 -*-
"""MySQL 备份/迁移闭环测试：本地→MySQL→清空本地→MySQL 迁移回→校验。"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from futures_quant.storage import data_transfer as dtf
from futures_quant.storage.analysis_store import AnalysisStore

HOST, PORT, DB, USER, PWD = "127.0.0.1", 3306, "qv_selftest_tmp", "root", "root"

tmp = tempfile.mkdtemp(prefix="qv_my_")
db_path = os.path.join(tmp, "roundtrip.db")
store = AnalysisStore(db_path)

# 造数据（覆盖多种类型：文本/浮点/整型/中文）
for i in range(120):
    store.add_log(f"2026-07-25 10:00:{i % 60:02d}", "INFO", f"日志消息 {i} · 中文√")
store.save_prediction({"ts": "2026-07-25", "symbol": "rb.SHFE", "period": "D",
                       "horizon": 12, "last_close": 3501.5,
                       "expected_return_pct": -0.88, "p_up": 0.42, "p_down": 0.58,
                       "risk_score": 66.6, "risk_label": "高", "model": "LSTM",
                       "regime": "震荡", "verdict": "观望", "score": 0,
                       "forecast": "[3500, 3495.5]"})
store.save_alert("2026-07-25", "cu.SHFE", "macd_cross", "WARN", "MACD 金叉", 1)
store.upsert_sample("rb.SHFE", "D", 100, 65, 1, note="备注·中文")

# 1. 备份到 MySQL
rep = dtf.backup_to_mysql(store.conn, HOST, PORT, DB, USER, PWD,
                          progress=lambda m: print("  ", m))
assert rep["logs"] == 120 and rep["predictions"] == 1, rep
print("[OK] backup_to_mysql:", rep)

# 2. 清空本地（模拟换新机器）
for t in ("logs", "predictions", "alerts", "screening_samples"):
    store.conn.execute(f"DELETE FROM {t}")
store.conn.commit()
assert store.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0] == 0

# 3. 从 MySQL 迁移/恢复回本地
rep2 = dtf.restore_from_mysql(store.conn, HOST, PORT, DB, USER, PWD, db_path,
                              progress=lambda m: print("  ", m))
assert all(v.get("verified") for v in rep2.values()), rep2
print("[OK] restore_from_mysql:", {k: v["rows"] for k, v in rep2.items()})

# 4. 数据一致性校验（含中文与浮点）
n = store.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
assert n == 120, n
row = store.conn.execute(
    "SELECT * FROM predictions ORDER BY id DESC LIMIT 1").fetchone()
assert abs(row["expected_return_pct"] - (-0.88)) < 1e-9
assert row["regime"] == "震荡" and row["verdict"] == "观望"
msg = store.conn.execute("SELECT message FROM logs LIMIT 1").fetchone()[0]
assert "中文√" in msg
samp = store.conn.execute("SELECT note FROM screening_samples").fetchone()[0]
assert samp == "备注·中文"
print("[OK] data integrity verified (rows / floats / Chinese text)")

# 清理：删掉测试库
import pymysql
c = pymysql.connect(host=HOST, port=PORT, user=USER, password=PWD)
with c.cursor() as cur:
    cur.execute(f"DROP DATABASE IF EXISTS `{DB}`")
c.close()
store.close()
shutil.rmtree(tmp, ignore_errors=True)
print("\nMYSQL ROUND-TRIP TEST PASSED")
