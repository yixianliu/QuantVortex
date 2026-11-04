"""M3-13 验证：漂移检测接线 + 修复。

验收点（对应 UPGRADE_PLAN_V5 M3-13 / §5.2-C10）：
  ① `corr_penalty` 恢复为真实计算（删硬编码 0）；
  ② `rolling_hit_drift` 的 `min_days` 与 `window` 解耦；
  ③ 预测页新增「模型漂移」指示灯；
  ④ `scheduler` 定时（默认 1h）对已预测品种跑漂移检测，超阈值写 `alerts`
     表并冒泡托盘。

文档验收标准：
    构造命中率从 60% 跌到 30% 的样本 → 漂移分 >0.2 且 UI 亮红

验证手段：
  · 分量可观测：DriftResult 拆出 mean_shift / corr_penalty / consistency / magnitude；
  · 稳定序列 vs 持续单向偏离的对照，确认 corr_penalty 不再恒为 0 且有判别力；
  · 30 天样本（< window 60）在改造前恒为 no_data，改造后能出结论；
  · 真实 SQLite（D 盘临时文件，不碰用户数据）+ 真实 QLabel 验证指示灯配色；
  · DriftMonitor 用假时钟，验证落库、冒泡、幂等与默认间隔。
"""
import os
import sys
import tempfile

# 必须在 QApplication 之前设定；同时避免沙箱 E:\Temp 极慢的问题
_TMPDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pytest_tmp")
os.makedirs(_TMPDIR, exist_ok=True)
for _v in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_v] = _TMPDIR
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


import numpy as np  # noqa: E402

from futures_quant.ai import constants as C                    # noqa: E402
from futures_quant.ai.drift import (                           # noqa: E402
    detect_drift, rolling_hit_drift, detect_from_store, detect_for_symbol,
)
from futures_quant.storage.analysis_store import AnalysisStore  # noqa: E402


# =========================================================================
# ① corr_penalty 真实计算
# =========================================================================
print("\n=== ① corr_penalty 恢复真实计算（原为硬编码 0.0） ===")

rng = np.random.default_rng(7)

# 稳定：围绕基准小幅波动
stable = [0.6 + rng.normal(0, 0.01) for _ in range(60)]
# 持续单向低：每天都显著低于基准
persistent = [0.35] * 60
# 均值相同但方向随机（"一半高一半低"）→ 一致性应显著低于 persistent
mixed = ([0.85] * 30 + [0.35] * 30)

r_stable = detect_drift(stable, 0.6)
r_persist = detect_drift(persistent, 0.6)
r_mixed = detect_drift(mixed, 0.6)

check("①稳定序列 corr_penalty ≈0", r_stable.corr_penalty < 0.02,
      f"corr_penalty={r_stable.corr_penalty:.4f} consistency="
      f"{r_stable.detail.get('consistency')}")
check("①持续单向偏离 corr_penalty 显著 >0", r_persist.corr_penalty > 0.2,
      f"corr_penalty={r_persist.corr_penalty:.4f}")
check("①corr_penalty 具备判别力（持续 > 随机交替）",
      r_persist.corr_penalty > r_mixed.corr_penalty + 0.2,
      f"persist={r_persist.corr_penalty:.4f} mixed={r_mixed.corr_penalty:.4f}")
check("①分量可观测（mean_shift / corr_penalty / consistency / magnitude 均在）",
      all(hasattr(r_persist, k) for k in ("mean_shift", "corr_penalty"))
      and "consistency" in r_persist.detail and "magnitude" in r_persist.detail)
check("①drift_score = max(mean_shift, corr_penalty)",
      abs(r_persist.drift_score
          - max(r_persist.mean_shift, r_persist.corr_penalty)) < 1e-9,
      f"score={r_persist.drift_score} mean_shift={r_persist.mean_shift} "
      f"corr_penalty={r_persist.corr_penalty}")
# 源码层面：不再有硬编码
import inspect  # noqa: E402
_src = inspect.getsource(detect_drift)
check("①源码不再出现 `corr_penalty = 0.0` 硬编码",
      "corr_penalty = 0.0" not in _src)

# 阈值集中化：可通过 constants 覆盖
with C.override(C.DRIFT, noise_band=0.5):   # 噪声带放大到 0.5 → 全部偏离被判为噪声
    r_nb = detect_drift(persistent, 0.6)
check("①阈值集中化：调大 noise_band 后一致性惩罚归零（配置生效）",
      r_nb.corr_penalty == 0.0, f"corr_penalty={r_nb.corr_penalty}")
check("①DriftConfig 已注册到常量组（可用 settings.json 覆盖）",
      "drift" in C._GROUPS and hasattr(C, "DRIFT") and hasattr(C, "DEFAULT_DRIFT"))


# =========================================================================
# ② min_days 与 window 解耦
# =========================================================================
print("\n=== ② rolling_hit_drift 的 min_days 与 window 解耦 ===")

# 只有 30 天（< window 60）：改造前 min_days=window=60 → 恒 no_data
r30 = rolling_hit_drift([0.3] * 30, 0.6)
check("②30 天样本不再是 no_data（改造前恒为 no_data）",
      r30.status != "no_data", f"status={r30.status} score={r30.drift_score}")
check("②30 天样本能正确判定为漂移", r30.status == "drift" and r30.drift_score > 0.2,
      f"score={r30.drift_score}")

# min_days 可独立收紧：30 天但要求 40 天 → 应回到 no_data
r_strict = rolling_hit_drift([0.3] * 30, 0.6, min_days=40)
check("②min_days 可独立设置（40 天门槛 → 30 天样本降级 no_data）",
      r_strict.status == "no_data", f"status={r_strict.status}")
check("②window 仍可独立设置（window=10 → 只看最近 10 天）",
      abs(rolling_hit_drift([0.6] * 20 + [0.3] * 10, 0.6,
                            window=10).window_mean - 0.3) < 1e-9)
check("②默认值：min_days=10 与 window=60 不相等（已解耦）",
      C.DRIFT.min_days != C.DRIFT.window,
      f"min_days={C.DRIFT.min_days} window={C.DRIFT.window}")


# =========================================================================
# 构造真实反馈库：命中率 60% → 30%
# =========================================================================
print("\n=== ③ 构造 60%→30% 样本（文档验收场景） ===")

_db = os.path.join(_TMPDIR, "_m313_test.db")
if os.path.exists(_db):
    os.remove(_db)
store = AnalysisStore(_db)


def _seed(symbol: str, hist_days: int, hist_rate: float,
          recent_days: int, recent_rate: float, per_day: int = 10):
    """按天写入已结算预测：`hist_days` 天训练期 + `recent_days` 天近期。"""
    day = 0
    for phase, days, rate in (("hist", hist_days, hist_rate),
                              ("recent", recent_days, recent_rate)):
        for _ in range(days):
            day += 1
            ts = f"2026-01-01"
            closed_ts = f"2026-{1 + day // 28:02d}-{1 + day % 28:02d} 15:00:00"
            n_hit = int(round(per_day * rate))
            for k in range(per_day):
                store.save_closed_prediction({
                    "ts": ts, "symbol": symbol, "period": "D", "horizon": 10,
                    "last_close": 3500.0, "expected_return_pct": 0.1,
                    "p_up": 0.7, "p_down": 0.3, "risk_score": 30.0,
                    "risk_label": "中等风险", "model": "lstm_numpy",
                    "regime": "震荡行情", "verdict": "看多",
                    "score": 1.0 if k < n_hit else 0.0, "forecast": "[]",
                    "confidence": 0.6, "status": "closed", "config": "enhanced",
                    "actual_return_pct": 0.5 if k < n_hit else -0.5,
                    "closed_ts": closed_ts, "y_up": 1.0 if k < n_hit else 0.0,
                })


_seed("RB2601", hist_days=40, hist_rate=0.6, recent_days=30, recent_rate=0.3)
rates = store.daily_hit_rates("RB2601")
check("③按日命中率序列已生成", len(rates) == 70, f"{len(rates)} 天")
check("③每日命中率按样本数正确聚合",
      abs(rates[0][1] - 0.6) < 1e-9 and abs(rates[-1][1] - 0.3) < 1e-9,
      f"首日={rates[0][1]} 末日={rates[-1][1]}")

d = detect_from_store(store, "RB2601")
check("③文档验收：命中率 60%→30% 时漂移分 >0.2", d["drift_score"] > 0.2,
      f"score={d['drift_score']} level={d['level']}")
check("③文档验收：状态判定为 drift", d["level"] == "drift", d["message"])
check("③基准取「窗口前」的训练期命中率 0.6", abs(d["baseline_mean"] - 0.6) < 1e-9,
      f"baseline={d['baseline_mean']}")

# 反向对照：一直稳定的品种不应告警
_seed("CU2601", hist_days=40, hist_rate=0.6, recent_days=30, recent_rate=0.58)
d_ok = detect_from_store(store, "CU2601")
check("③对照组：命中率稳定（60%→58%）不告警",
      d_ok["level"] == "ok" and d_ok["drift_score"] < 0.2,
      f"score={d_ok['drift_score']} level={d_ok['level']}")


# =========================================================================
# ③ UI 指示灯（真实 QLabel + 页面真实方法）
# =========================================================================
print("\n=== ③ 预测页「模型漂移」指示灯 ===")

from types import SimpleNamespace  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication.instance() or QApplication([])

try:
    from futures_quant.ui.predict_ops_page import PredictOpsPage
    src_page = __import__("inspect").getsource(PredictOpsPage)
except Exception as e:  # noqa: BLE001
    src_page = ""
    print(f"  [!!] 预测页不可用：{e}")

check("③页面新增 drift_light / drift_text / drift_btn",
      all(k in (src_page or "") for k in
          ("drift_light", "drift_text", "drift_btn")))
check("③页面新增 _refresh_drift_light 方法并接在刷新按钮上",
      "_refresh_drift_light" in (src_page or ""))

# 用真实 QLabel 驱动真实方法（不构造整页，避免无谓开销）
from futures_quant.ui.widgets import pal  # noqa: E402
P = pal()
fake = SimpleNamespace(store=store, cur_symbol="RB2601",
                       drift_light=QLabel(), drift_text=QLabel())
PredictOpsPage._refresh_drift_light(fake)
css = fake.drift_light.styleSheet()
check("③漂移时指示灯亮红（用主题调色板 up 色）",
      P["up"].lower() in css.lower(), f"css={css}")
check("③漂移时文案给出「建议重训」与两个命中率",
      "建议重训" in fake.drift_text.text() and "0.60" in fake.drift_text.text(),
      fake.drift_text.text()[:80])

# 正常品种 → 绿灯
fake2 = SimpleNamespace(store=store, cur_symbol="CU2601",
                        drift_light=QLabel(), drift_text=QLabel())
PredictOpsPage._refresh_drift_light(fake2)
check("③正常时指示灯为绿（down 色）",
      P["down"].lower() in fake2.drift_light.styleSheet().lower(),
      fake2.drift_light.styleSheet())

# 无数据品种 → 灰灯
fake3 = SimpleNamespace(store=store, cur_symbol="NODATA",
                        drift_light=QLabel(), drift_text=QLabel())
PredictOpsPage._refresh_drift_light(fake3)
check("③样本不足时指示灯为灰（sub 色）",
      P["sub"].lower() in fake3.drift_light.styleSheet().lower(),
      fake3.drift_text.text()[:60])


# =========================================================================
# ④ scheduler 定时漂移检测
# =========================================================================
print("\n=== ④ scheduler 定时漂移检测（默认 1h） + 落库 + 冒泡 ===")

from futures_quant.app.scheduler import DriftMonitor  # noqa: E402

check("④DriftConfig.scheduler_interval_min 默认 60（1 小时）",
      C.DRIFT.scheduler_interval_min == 60, f"{C.DRIFT.scheduler_interval_min}")

notified = []
scheduled = []


def _notify(msg, level):
    notified.append((msg, level))


def _fake_schedule(interval, fn):
    scheduled.append((interval, fn))
    return SimpleNamespace(cancel=lambda: None)


mon = DriftMonitor(store, notify_fn=_notify, schedule_fn=_fake_schedule)
syms = store.predicted_symbols()
check("④能枚举到已预测品种", "RB2601" in syms and "CU2601" in syms, str(syms))

alerts_before = len(store.query_alerts(limit=500))
evs = mon.check_all()
by_sym = {e.symbol: e for e in evs}
check("④扫描全部品种并产出事件", len(evs) == len(syms), f"{len(evs)} 个")
check("④RB2601 判定为 drift", by_sym["RB2601"].level == "drift",
      by_sym["RB2601"].message)
check("④CU2601 判定为 ok", by_sym["CU2601"].level == "ok")

alerts = store.query_alerts(limit=500)
new_alerts = [a for a in alerts if a.get("rule") == "model_drift"]
check("④超阈值写入 alerts 表（rule=model_drift）", len(new_alerts) >= 1,
      f"新增 {len(new_alerts)} 条（原 {alerts_before}）")
check("④告警内容含品种与漂移分",
      any("RB2601" in (a.get("message") or "") for a in new_alerts),
      (new_alerts[0].get("message") if new_alerts else "")[:60])
check("④触发托盘冒泡一次", len(notified) == 1 and notified[0][1] == "drift",
      f"{len(notified)} 次")

# 幂等：同一品种状态未变化 → 不重复告警/冒泡
mon.check_all()
check("④同一状态不重复告警（幂等去噪）",
      len(notified) == 1 and len(
          [a for a in store.query_alerts(limit=500)
           if a.get("rule") == "model_drift"]) == len(new_alerts),
      f"冒泡 {len(notified)} 次")

# 定时：假时钟，验证间隔与可手动触发
mon.start()
check("④start 使用默认间隔 1h（3600s）",
      scheduled and abs(scheduled[-1][0] - 3600.0) < 1e-6,
      f"interval={scheduled[-1][0] if scheduled else None}s")
check("④定时器已注册回调（不阻塞主线程）", bool(scheduled) and callable(scheduled[-1][1]))
_check_before = len(mon.history)
scheduled[-1][1]()      # 手动触发一轮
check("④定时器回调可执行一轮扫描", len(mon.history) > _check_before,
      f"{_check_before} → {len(mon.history)}")
mon.stop()
check("④stop 后可正常停止", mon.summary()["running"] is False)
check("④summary 汇总可用", isinstance(mon.summary(), dict)
      and mon.summary()["drifted"] >= 1, str(mon.summary()))


# =========================================================================
# 汇总
# =========================================================================
print("\n" + "=" * 60)
print(f"M3-13 验证结果：PASS={len(PASS)}  FAIL={len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print(f"  - {f}")
print("=" * 60)
try:
    store.conn.close()
    os.remove(_db)
except Exception:  # noqa: BLE001
    pass
sys.exit(1 if FAIL else 0)
