"""M3-13 验证（pytest 改写版）：漂移检测接线 + 修复。

验收点（对应 UPGRADE_PLAN_V5 M3-13 / §5.2-C10）：
  ① ``corr_penalty`` 恢复为真实计算（删硬编码 0）；
  ② ``rolling_hit_drift`` 的 ``min_days`` 与 ``window`` 解耦；
  ③ 预测页新增「模型漂移」指示灯（真实 QLabel + 页面真实方法）；
  ④ ``scheduler`` 定时（默认 1h）对已预测品种跑漂移检测，超阈值写 ``alerts``
     表并冒泡托盘。

与散落脚本的差别（行为契约不变，仅改写形态）：
  · 原脚本用 ``SimpleNamespace`` 直接驱动 ``PredictOpsPage._refresh_drift_light``。
    生产代码已将样式拆到 ``_style_drift_light``，故 fake 必须补上该绑定（转发到
    真实方法），否则会 ``AttributeError``。本改写据实补上，避免「旧断言失实」。
  · 真实 SQLite（``.pytest_tmp`` 下临时库，不碰用户数据）+ 真实 ``QLabel`` 验证
    指示灯配色；``DriftMonitor`` 用假时钟验证落库、冒泡、幂等与默认间隔。

散落脚本原文：``tests/test_m3_13.py``（约 50 个 check）。
"""
import inspect
import os
import types
from pathlib import Path

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from futures_quant.ai import constants as C
from futures_quant.ai.drift import detect_drift, rolling_hit_drift, detect_from_store
from futures_quant.app.scheduler import DriftMonitor
from futures_quant.storage.analysis_store import AnalysisStore

# 避免沙箱 E:\Temp 极慢 + 强制 offscreen（与散落脚本一致）
_TMP = Path("D:/PythonProject/QuantVortex/.pytest_tmp")
_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for _v in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_v] = str(_TMP)


def _seed(store, symbol, hist_days, hist_rate, recent_days, recent_rate, per_day=10):
    """按天写入已结算预测：hist_days 训练期 + recent_days 近期。"""
    day = 0
    for _phase, days, rate in (("hist", hist_days, hist_rate),
                               ("recent", recent_days, recent_rate)):
        for _ in range(days):
            day += 1
            closed_ts = f"2026-{1 + day // 28:02d}-{1 + day % 28:02d} 15:00:00"
            n_hit = int(round(per_day * rate))
            for k in range(per_day):
                store.save_closed_prediction({
                    "ts": "2026-01-01", "symbol": symbol, "period": "D", "horizon": 10,
                    "last_close": 3500.0, "expected_return_pct": 0.1,
                    "p_up": 0.7, "p_down": 0.3, "risk_score": 30.0,
                    "risk_label": "中等风险", "model": "lstm_numpy",
                    "regime": "震荡行情", "verdict": "看多",
                    "score": 1.0 if k < n_hit else 0.0, "forecast": "[]",
                    "confidence": 0.6, "status": "closed", "config": "enhanced",
                    "actual_return_pct": 0.5 if k < n_hit else -0.5,
                    "closed_ts": closed_ts, "y_up": 1.0 if k < n_hit else 0.0,
                })


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def store():
    db = _TMP / "_m313_unit.db"
    if db.exists():
        db.unlink()
    s = AnalysisStore(str(db))
    _seed(s, "RB2601", hist_days=40, hist_rate=0.6, recent_days=30, recent_rate=0.3)
    _seed(s, "CU2601", hist_days=40, hist_rate=0.6, recent_days=30, recent_rate=0.58)
    yield s
    try:
        s.conn.close()
    except Exception:  # noqa: BLE001
        pass
    if db.exists():
        db.unlink()


@pytest.fixture(scope="module")
def palette():
    from futures_quant.ui.widgets import pal
    return pal()


# =========================================================================
# ① corr_penalty 真实计算
# =========================================================================
def test_detect_drift_corr_penalty_real():
    """corr_penalty 不再恒 0：稳定≈0、持续单向偏离显著>0，且有判别力。"""
    rng = np.random.default_rng(7)
    stable = [0.6 + rng.normal(0, 0.01) for _ in range(60)]
    persistent = [0.35] * 60
    mixed = [0.85] * 30 + [0.35] * 30

    r_stable = detect_drift(stable, 0.6)
    r_persist = detect_drift(persistent, 0.6)
    r_mixed = detect_drift(mixed, 0.6)

    assert r_stable.corr_penalty < 0.02, f"稳定序列 corr_penalty={r_stable.corr_penalty}"
    assert r_persist.corr_penalty > 0.2, f"持续偏离 corr_penalty={r_persist.corr_penalty}"
    assert r_persist.corr_penalty > r_mixed.corr_penalty + 0.2, \
        f"persist={r_persist.corr_penalty} mixed={r_mixed.corr_penalty}"
    assert all(hasattr(r_persist, k) for k in ("mean_shift", "corr_penalty"))
    assert "consistency" in r_persist.detail and "magnitude" in r_persist.detail
    assert abs(r_persist.drift_score
               - max(r_persist.mean_shift, r_persist.corr_penalty)) < 1e-9


def test_detect_drift_no_hardcoded_corr_penalty():
    """源码层面：不再有 `corr_penalty = 0.0` 硬编码。"""
    src = inspect.getsource(detect_drift)
    assert "corr_penalty = 0.0" not in src


def test_drift_threshold_override_and_config():
    """阈值可通过 constants 覆盖；DriftConfig 已注册到常量组。"""
    persistent = [0.35] * 60
    with C.override(C.DRIFT, noise_band=0.5):  # 噪声带放大 → 全部偏离被判为噪声
        r_nb = detect_drift(persistent, 0.6)
    assert r_nb.corr_penalty == 0.0, f"corr_penalty={r_nb.corr_penalty}"
    assert "drift" in C._GROUPS and hasattr(C, "DRIFT") and hasattr(C, "DEFAULT_DRIFT")


# =========================================================================
# ② min_days 与 window 解耦
# =========================================================================
def test_rolling_min_days_window_decoupled():
    """30 天（<window 60）不再恒 no_data；min_days 与 window 可独立设置。"""
    r30 = rolling_hit_drift([0.3] * 30, 0.6)
    assert r30.status != "no_data", f"status={r30.status}"
    assert r30.status == "drift" and r30.drift_score > 0.2, f"score={r30.drift_score}"

    r_strict = rolling_hit_drift([0.3] * 30, 0.6, min_days=40)
    assert r_strict.status == "no_data", f"status={r_strict.status}"

    assert abs(rolling_hit_drift([0.6] * 20 + [0.3] * 10, 0.6,
                                window=10).window_mean - 0.3) < 1e-9
    assert C.DRIFT.min_days != C.DRIFT.window, \
        f"min_days={C.DRIFT.min_days} window={C.DRIFT.window}"


# =========================================================================
# ③ 构造真实反馈库 + 页面指示灯
# =========================================================================
def test_daily_hit_rates_aggregation(store):
    """按日命中率序列已生成且按样本数正确聚合。"""
    rates = store.daily_hit_rates("RB2601")
    assert len(rates) == 70, f"{len(rates)} 天"
    assert abs(rates[0][1] - 0.6) < 1e-9 and abs(rates[-1][1] - 0.3) < 1e-9, \
        f"首日={rates[0][1]} 末日={rates[-1][1]}"


def test_doc_drift_60_to_30(store):
    """文档验收：命中率 60%→30% 时漂移分 >0.2 且判定为 drift，基准=训练期 0.6。"""
    d = detect_from_store(store, "RB2601")
    assert d["drift_score"] > 0.2, f"score={d['drift_score']}"
    assert d["level"] == "drift", d["message"]
    assert abs(d["baseline_mean"] - 0.6) < 1e-9, f"baseline={d['baseline_mean']}"


def test_control_stable_no_alarm(store):
    """反向对照：命中率稳定（60%→58%）不告警。"""
    d_ok = detect_from_store(store, "CU2601")
    assert d_ok["level"] == "ok" and d_ok["drift_score"] < 0.2, \
        f"score={d_ok['drift_score']} level={d_ok['level']}"


def test_page_drift_light_widgets_and_method():
    """预测页新增 drift_light / drift_text / drift_btn 与 _refresh_drift_light。"""
    from futures_quant.ui.predict_ops_page import PredictOpsPage
    src = inspect.getsource(PredictOpsPage)
    assert all(k in src for k in ("drift_light", "drift_text", "drift_btn"))
    assert "_refresh_drift_light" in src


def test_drift_light_colors(qapp, store, palette):
    """真实 QLabel 驱动真实方法：漂移红 / 正常绿 / 无数据灰。"""
    from futures_quant.ui.predict_ops_page import PredictOpsPage

    def _mk(sym):
        f = types.SimpleNamespace(store=store, cur_symbol=sym,
                                  drift_light=QLabel(), drift_text=QLabel())
        # 生产代码已将样式拆到 _style_drift_light，fake 须补此绑定（转发真实方法）
        f._style_drift_light = lambda: PredictOpsPage._style_drift_light(f)
        return f

    f = _mk("RB2601")
    PredictOpsPage._refresh_drift_light(f)
    css = f.drift_light.styleSheet().lower()
    assert palette["up"].lower() in css, f"css={css}"
    assert "建议重训" in f.drift_text.text() and "0.60" in f.drift_text.text(), \
        f"text={f.drift_text.text()[:80]}"

    f_ok = _mk("CU2601")
    PredictOpsPage._refresh_drift_light(f_ok)
    assert palette["down"].lower() in f_ok.drift_light.styleSheet().lower()

    f_na = _mk("NODATA")
    PredictOpsPage._refresh_drift_light(f_na)
    assert palette["sub"].lower() in f_na.drift_light.styleSheet().lower()


# =========================================================================
# ④ scheduler 定时漂移检测
# =========================================================================
def test_drift_config_default_interval():
    assert C.DRIFT.scheduler_interval_min == 60, f"{C.DRIFT.scheduler_interval_min}"


def test_drift_monitor_scan_and_persist(store):
    """扫描全部品种、超阈值写 alerts 表、冒泡托盘、幂等去噪。"""
    notified = []
    scheduled = []

    def _notify(msg, level):
        notified.append((msg, level))

    def _fake_schedule(interval, fn):
        scheduled.append((interval, fn))
        return types.SimpleNamespace(cancel=lambda: None)

    mon = DriftMonitor(store, notify_fn=_notify, schedule_fn=_fake_schedule)
    syms = store.predicted_symbols()
    assert "RB2601" in syms and "CU2601" in syms, str(syms)

    evs = mon.check_all()
    by_sym = {e.symbol: e for e in evs}
    assert len(evs) == len(syms), f"{len(evs)} 个"
    assert by_sym["RB2601"].level == "drift", by_sym["RB2601"].message
    assert by_sym["CU2601"].level == "ok"

    alerts = store.query_alerts(limit=500)
    new_alerts = [a for a in alerts if a.get("rule") == "model_drift"]
    assert len(new_alerts) >= 1, f"新增 {len(new_alerts)} 条"
    assert any("RB2601" in (a.get("message") or "") for a in new_alerts)

    assert len(notified) == 1 and notified[0][1] == "drift", f"{len(notified)} 次"

    mon.check_all()  # 幂等：同一状态不重复告警/冒泡
    assert len(notified) == 1
    assert len([a for a in store.query_alerts(limit=500)
                if a.get("rule") == "model_drift"]) == len(new_alerts)


def test_drift_monitor_schedule_start_stop(store):
    """定时：默认间隔 1h（3600s）、回调可手动触发、stop 可停、summary 可用。"""
    scheduled = []

    def _fake_schedule(interval, fn):
        scheduled.append((interval, fn))
        return types.SimpleNamespace(cancel=lambda: None)

    mon = DriftMonitor(store, notify_fn=lambda m, l: None, schedule_fn=_fake_schedule)
    mon.start()
    assert scheduled and abs(scheduled[-1][0] - 3600.0) < 1e-6, \
        f"interval={scheduled[-1][0] if scheduled else None}s"
    assert bool(scheduled) and callable(scheduled[-1][1])

    hb = len(mon.history)
    scheduled[-1][1]()  # 手动触发一轮
    assert len(mon.history) > hb, f"{hb} → {len(mon.history)}"

    mon.stop()
    assert mon.summary()["running"] is False
    assert isinstance(mon.summary(), dict) and mon.summary()["drifted"] >= 1, \
        str(mon.summary())
