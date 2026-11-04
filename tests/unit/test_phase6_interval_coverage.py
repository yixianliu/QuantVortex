"""第六轮回归测试：预测区间真实覆盖率 + predictions 表向前兼容迁移。

覆盖点：
1. 真实覆盖率按「实际价格是否落在落库 [lower, upper]」计算，能判定过度覆盖/覆盖不足；
2. 样本 <30 一律 coverage=None 且给出原因，不返回伪精确数字；
3. 老数据 lower/upper 为 NULL 时必须剔除，不能用残差 σ 现算补洞；
4. 按品种 / horizon / 波动分层输出分组覆盖率；
5. σ 乘数 k' 只用训练段拟合、测试段验证，测试段不得参与定参；
6. 旧版 predictions 表迁移只新增列、保留原记录，新老记录可共存查询。
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from futures_quant.ai.evaluation import (
    MIN_INTERVAL_SAMPLES, evaluate_interval_coverage, interval_coverage,
    recommend_band_multiplier,
)
from futures_quant.storage.analysis_store import AnalysisStore


def _row(last=100.0, lower=98.0, upper=102.0, act_pct=0.0,
         symbol="RB.SHFE", horizon=10, band_sigma=0.0064, ts="2026-01-01T00:00:00"):
    """构造一条区间样本；默认实际价 100 落在 [98,102] 内。"""
    return {
        "last_close": last, "lower": lower, "upper": upper,
        "actual_return_pct": act_pct, "symbol": symbol, "horizon": horizon,
        "band_sigma": band_sigma, "closed_ts": ts,
    }


def _rows(n, hit=True, symbol="RB.SHFE", horizon=10, band_sigma=0.0064):
    act = 0.0 if hit else 10.0   # 0% → 命中；+10% → 必然落在区间外
    return [_row(act_pct=act, symbol=symbol, horizon=horizon,
                 band_sigma=band_sigma,
                 ts=f"2026-01-{(i % 28) + 1:02d}T00:00:00") for i in range(n)]


def test_over_coverage_is_detected():
    # 60 个样本全部命中 → 100% 覆盖，远高于名义 68.27%，判为过度覆盖
    r = interval_coverage(_rows(60, hit=True), nominal=0.6827)
    assert r["available"] is True
    assert r["n"] == 60 and r["n_hit"] == 60
    assert r["coverage"] == pytest.approx(1.0)
    assert r["verdict"] == "over"
    assert r["verdict_text"] == "过度覆盖"
    assert r["ci_low"] > 0.6827
    # 训练/测试足够时，校准建议应给出 k'（但不得用测试段定参）
    assert r["calibration"]["available"] is True
    assert r["calibration"]["k_prime"] > 0


def test_under_coverage_is_detected():
    # 60 个样本全部落在区间外 → 0% 覆盖，判为覆盖不足
    r = interval_coverage(_rows(60, hit=False), nominal=0.6827)
    assert r["available"] is True
    assert r["coverage"] == pytest.approx(0.0)
    assert r["verdict"] == "under"
    assert r["verdict_text"] == "覆盖不足"
    assert r["ci_high"] < 0.6827


def test_insufficient_samples_returns_none_with_reason():
    r = interval_coverage(_rows(10), nominal=0.6827)
    assert r["available"] is False
    assert r["coverage"] is None
    assert r["verdict"] == "insufficient"
    assert "样本数 10" in r["reason"]
    assert r["observed_rate"] == pytest.approx(1.0)


def test_legacy_null_band_rows_are_excluded():
    # 40 条新数据 + 20 条老数据（lower/upper 为 None）
    rows = _rows(40) + [{
        "last_close": 100.0, "lower": None, "upper": None,
        "actual_return_pct": 1.0, "symbol": "RB.SHFE", "horizon": 10,
        "band_sigma": None, "closed_ts": "2025-01-01T00:00:00",
    } for _ in range(20)]
    r = evaluate_interval_coverage(rows=rows, nominal=0.6827)
    assert r["total_rows"] == 60
    assert r["usable_rows"] == 40
    assert r["coverage"] == pytest.approx(1.0)
    assert r["n"] == 40


def test_no_usable_rows_returns_none_and_reason():
    r = evaluate_interval_coverage(rows=[], nominal=0.6827)
    assert r["coverage"] is None
    assert "lower/upper 为空" in r["reason"]
    assert r["calibration"]["available"] is False


def test_grouped_by_symbol_horizon_and_volatility():
    rows = (_rows(40, symbol="RB.SHFE", horizon=5, band_sigma=0.004)
            + _rows(40, symbol="I.DCE", horizon=10, band_sigma=0.012)
            + _rows(20, symbol="CU.SHFE", horizon=10, band_sigma=0.008))
    r = interval_coverage(rows, nominal=0.6827)
    assert r["n"] == 100
    assert set(r["by_symbol"]) == {"RB.SHFE", "I.DCE", "CU.SHFE"}
    assert r["by_symbol"]["RB.SHFE"]["n"] == 40
    # CU 只有 20 条 → 分组必须返回 None + 原因
    assert r["by_symbol"]["CU.SHFE"]["coverage"] is None
    assert "样本数 20" in r["by_symbol"]["CU.SHFE"]["reason"]
    assert set(r["by_horizon"]) == {"5", "10"}
    assert {"low", "mid", "high"}.issubset(set(r["by_volatility"]))


def test_interval_z_is_relative_to_start_price():
    """回归：z 必须按「相对起点价的 log 收益」标准化，不能把 ln(价格) 当漂移。

    价格量级 3000 时，若误用绝对价格 log，k' 会被抬到数百；正确口径下 k' 应 <2。
    """
    rows = []
    for i in range(70):
        rows.append(_row(last=3000.0, lower=2940.0, upper=3060.0,
                         act_pct=-0.4 + 0.012 * i,
                         ts=f"2026-02-{i + 1:02d}T00:00:00"))
    r = interval_coverage(rows, nominal=0.6827)
    assert r["calibration"]["available"] is True
    assert r["calibration"]["k_prime"] < 2.0
    assert r["coverage"] == pytest.approx(1.0)


def test_calibration_uses_train_segment_only():
    # 训练段 z≈0.5~1.0，测试段 z≈3~6：k' 必须由训练段给出（≈1），
    # 若误用全样本分位数 k' 会被测试段拉到 ≈3 以上。
    train = [{"z": 0.5 + i / 100.0, "half_log": 0.02, "sigma_h": 0.02,
              "hit": True, "horizon": 10, "symbol": "RB.SHFE",
              "ts": f"2025-01-{i + 1:02d}T00:00:00"} for i in range(70)]
    test = [{"z": 3.0 + i / 10.0, "half_log": 0.02, "sigma_h": 0.02,
             "hit": False, "horizon": 10, "symbol": "RB.SHFE",
             "ts": f"2025-03-{i + 1:02d}T00:00:00"} for i in range(30)]
    r = recommend_band_multiplier(train + test, target=0.6827,
                                  min_train=30, min_test=30, train_ratio=0.7)
    assert r["available"] is True
    assert r["train_n"] == 70 and r["test_n"] == 30
    assert r["k_prime"] < 1.5          # 未被测试段污染
    assert r["test_coverage_at_k_prime"] == pytest.approx(0.0)
    assert r["verdict"] == "rejected"
    assert "训练段" in r["rule"]


def test_migration_adds_columns_and_keeps_legacy_rows():
    fd, path = tempfile.mkstemp(prefix="qv_phase6_", suffix=".db")
    os.close(fd)
    try:
        # 构造迁移前的 predictions 表（第六轮新增列不存在）
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT, symbol TEXT, period TEXT, horizon INTEGER,"
            " last_close REAL, expected_return_pct REAL, p_up REAL, p_down REAL,"
            " risk_score REAL, risk_label TEXT, model TEXT, regime TEXT,"
            " verdict TEXT, score REAL, forecast TEXT, confidence REAL,"
            " status TEXT DEFAULT 'open', config TEXT DEFAULT 'enhanced',"
            " actual_return_pct REAL, closed_ts TEXT, y_up REAL DEFAULT 0)")
        conn.execute(
            "INSERT INTO predictions (ts,symbol,period,horizon,last_close,"
            "actual_return_pct,status,closed_ts) VALUES (?,?,?,?,?,?,?,?)",
            ("2025-01-01", "RB.SHFE", "D", 10, 100.0, 1.0, "closed",
             "2025-01-11"))
        conn.commit()
        conn.close()

        store = AnalysisStore(path)
        cols = {r[1] for r in store.conn.execute("PRAGMA table_info(predictions)")}
        assert {"lower", "upper", "band_sigma", "model_version",
                "data_fingerprint"}.issubset(cols)

        # 老记录保留，新增列为 NULL
        legacy = store.conn.execute(
            "SELECT id, lower, upper, band_sigma FROM predictions").fetchone()
        assert legacy["id"] == 1
        assert legacy["lower"] is None and legacy["upper"] is None

        # 新记录可写入区间元信息
        new_id = store.save_closed_prediction({
            "ts": "2026-01-01", "symbol": "RB.SHFE", "period": "D", "horizon": 10,
            "last_close": 100.0, "actual_return_pct": 1.0, "status": "closed",
            "closed_ts": "2026-01-11", "lower": 98.0, "upper": 102.0,
            "band_sigma": 0.0064, "model_version": "test:v",
            "data_fingerprint": "fp001",
        })
        assert new_id > 1
        got = store.conn.execute(
            "SELECT lower, upper, band_sigma, model_version, data_fingerprint "
            "FROM predictions WHERE id=?", (new_id,)).fetchone()
        assert got["lower"] == pytest.approx(98.0)
        assert got["upper"] == pytest.approx(102.0)
        assert got["band_sigma"] == pytest.approx(0.0064)
        assert got["model_version"] == "test:v"
        assert got["data_fingerprint"] == "fp001"

        # 老数据 NULL + 仅 1 条新数据 → 覆盖率必须 None + 原因
        result = evaluate_interval_coverage(store=store)
        assert result["coverage"] is None
        assert "样本数 1" in result["reason"] or "样本" in result["reason"]

        store.close()

        # 迁移幂等：再次打开不报错，列不重复
        store2 = AnalysisStore(path)
        cols2 = {r[1] for r in store2.conn.execute("PRAGMA table_info(predictions)")}
        assert "lower" in cols2
        store2.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


def test_store_query_handles_legacy_only_database():
    fd, path = tempfile.mkstemp(prefix="qv_phase6_legacy_", suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT, symbol TEXT, period TEXT, horizon INTEGER,"
            " last_close REAL, expected_return_pct REAL, p_up REAL, p_down REAL,"
            " risk_score REAL, risk_label TEXT, model TEXT, regime TEXT,"
            " verdict TEXT, score REAL, forecast TEXT, confidence REAL,"
            " status TEXT DEFAULT 'open', config TEXT DEFAULT 'enhanced',"
            " actual_return_pct REAL, closed_ts TEXT, y_up REAL DEFAULT 0)")
        conn.execute(
            "INSERT INTO predictions (ts,symbol,horizon,last_close,"
            "actual_return_pct,status) VALUES (?,?,?,?,?,?)",
            ("2025-01-01", "RB.SHFE", 10, 100.0, 2.0, "closed"))
        conn.commit()
        conn.close()
        store = AnalysisStore(path)
        rows = store.query_closed_with_bands()
        assert len(rows) == 1 and rows[0]["lower"] is None
        result = evaluate_interval_coverage(store=store)
        assert result["total_rows"] == 1
        assert result["usable_rows"] == 0
        assert result["coverage"] is None
        assert "lower/upper 为空" in result["reason"]
        store.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


def test_min_samples_constant_is_30():
    assert MIN_INTERVAL_SAMPLES == 30
