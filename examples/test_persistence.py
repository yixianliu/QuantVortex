import tempfile, os, json
from futures_quant.storage.json_store import AtomicJSON
from futures_quant.storage.config_manager import ConfigManager, SessionState
from futures_quant.storage.analysis_store import AnalysisStore

d = tempfile.mkdtemp()
p = os.path.join(d, "s.json")
aj = AtomicJSON(p, default={"a": {"b": 1}, "x": 5}, version=1)
aj.set("a.b", 99); aj.set("x", 7); aj.save()
print("save ok, data:", aj.data)

with open(p, "w") as f:
    f.write("{bad json")
rec = AtomicJSON(p, default={"a": {"b": 1}, "x": 5}, version=1)
print("corrupt recovered a.b =", rec.get("a.b"), "(expect 99 from .bak)")

aj2 = AtomicJSON(p, default={"a": {"b": 1}, "newkey": "def"}, version=2)
print("migrated newkey =", aj2.get("newkey"))

cm = ConfigManager(defaults_path="config/settings.json")
print("config theme default =", cm.get("ui.theme"), "| source =", cm.get("data.source"))
cm.set("ui.theme", "light"); assert cm.save()
cm2 = ConfigManager(defaults_path="config/settings.json")
print("persisted theme =", cm2.get("ui.theme"))
cm2.set("ui.theme", "dark"); cm2.save()

ss = SessionState(path=os.path.join(d, "session.json"))
ss.set("window", {"x": 10, "y": 20, "w": 1300, "h": 800, "maximized": False})
ss.set_page_selection("market", "au.SHFE", "D")
assert ss.flush()
ss2 = SessionState(path=os.path.join(d, "session.json"))
print("session window =", ss2.get("window"),
      "| page market =", ss2.get_page_selection("market"))

# ---- SessionState 边界用例 ----
# 1) 缺失键回落默认值
assert ss2.get("nonexistent.deep", "fallback") == "fallback"
# 2) 损坏的 session 文件应回退默认而非崩溃
bad = os.path.join(d, "bad_session.json")
with open(bad, "w") as f:
    f.write("{not json")
ss_bad = SessionState(path=bad)
assert ss_bad.get("window") == SessionState._DEFAULTS["window"], "corrupt session must fall back to defaults"
# 3) maximized 标志可持久化
ss3 = SessionState(path=os.path.join(d, "session_max.json"))
ss3.set("window", {"x": 0, "y": 0, "w": 1366, "h": 768, "maximized": True})
assert ss3.flush()
ss3b = SessionState(path=os.path.join(d, "session_max.json"))
assert ss3b.get("window")["maximized"] is True, "maximized flag must survive reload"
print("session edge cases OK")

# ---- AnalysisStore：WAL / 写入 / 查询 / integrity_check / prune / checkpoint ----
db = os.path.join(d, "test_analysis.db")
store = AnalysisStore(path=db)
# 日志写入（触发 WAL）
for i in range(50):
    store.add_log(ts=f"2026-07-21 10:{i:02d}:00", level="INFO", message=f"msg {i}")
# 预测 + 研判 + 预警
store.save_prediction({"ts": "2026-07-21 10:00:00", "symbol": "rb.SHFE", "period": "D",
                       "horizon": 5, "last_close": 3700.0, "expected_return_pct": 1.2,
                       "p_up": 0.6, "p_down": 0.4, "risk_score": 0.3, "risk_label": "低",
                       "model": "lstm", "regime": "trend", "verdict": "偏多", "score": 0.7,
                       "forecast": "[3705,3710,3712]"})
store.save_analysis("2026-07-21 10:00:00", "rb.SHFE", "resonance", "均线多头", "详情")
store.save_alert("2026-07-21 10:00:00", "rb.SHFE", "price_cross", "info", "上穿", 1)
# WAL 机制验证：checkpoint 后 -wal 文件应清空/合并
store.checkpoint()
wal_path = db + "-wal"
wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
print("wal after checkpoint size =", wal_size)
# 完整性校验
assert store.integrity_check() is True, "integrity_check must pass on fresh db"
print("integrity_check OK")
# 查询落库正确
preds = store.query_predictions(symbol="rb.SHFE", limit=10)
assert len(preds) == 1 and preds[0]["symbol"] == "rb.SHFE", "prediction must be queryable"
logs = store.query_logs(limit=10)
assert len(logs) == 10, "log query must return requested limit"
print("query OK (preds=%d, logs=%d)" % (len(preds), len(logs)))
# prune：日志容量上限（测试用极小上限验证逻辑）
store.prune(keep={"logs": 10, "predictions": 2000, "analysis": 2000, "alerts": 2000})
assert store.query_logs(limit=1000)[-1]["message"] == "msg 40", "prune must keep newest 10 logs"
print("prune OK (kept newest 10 of 50 logs)")
store.close()

print("PERSISTENCE_OK")
