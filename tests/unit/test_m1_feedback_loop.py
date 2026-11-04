# -*- coding: utf-8 -*-
"""M1-01 验收：交易反馈闭环死链修复。

验证：
  1. AnalysisStore 新增 feedback_samples 表 + append_feedback_sample/feedback_sample_count；
  2. 写入 20 条样本后计数 == 20；
  3. FeedbackScheduler.run_once 在达到阈值时触发 retrain_fn 一次；
  4. record_trade_feedback 写回样本后计数随之增长。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.storage.analysis_store import AnalysisStore
from futures_quant.app.scheduler import FeedbackScheduler
from futures_quant.ai import feedback as fb


def _new_store():
    tmp = tempfile.mkdtemp(prefix="qv_m1_")
    db = os.path.join(tmp, "quant_analysis.db")
    return AnalysisStore(db)


def test_append_and_count():
    store = _new_store()
    for i in range(20):
        rid = store.append_feedback_sample(
            {"symbol": "rb.SHFE", "pnl": float(i), "source": "backtest"})
        assert isinstance(rid, int) and rid > 0
    assert store.feedback_sample_count() == 20
    assert store.feedback_sample_count("rb.SHFE") == 20
    assert store.feedback_sample_count("cu.SHFE") == 0


def test_scheduler_triggers_retrain():
    store = _new_store()
    for _ in range(20):
        store.append_feedback_sample({"symbol": "rb.SHFE", "pnl": 1.0})
    calls = []

    def retrain_fn(symbol, st):
        calls.append(symbol)
        return {"ok": True}

    sched = FeedbackScheduler(store, retrain_fn, min_samples=20)
    ev = sched.run_once("rb.SHFE")
    assert ev.triggered is True
    assert ev.n_samples == 20
    assert calls == ["rb.SHFE"]

    # 不足阈值时不触发
    sched2 = FeedbackScheduler(store, retrain_fn, min_samples=99)
    ev2 = sched2.run_once("rb.SHFE")
    assert ev2.triggered is False


def test_record_trade_feedback_writes():
    store = _new_store()
    trades = [{"pnl": 1.0}, {"pnl": -0.5}, {"pnl": 2.0}]
    res = fb.record_trade_feedback(store, trades, symbol="cu.SHFE", source="backtest")
    assert res["count"] == 3
    assert store.feedback_sample_count("cu.SHFE") == 3


if __name__ == "__main__":
    test_append_and_count()
    test_scheduler_triggers_retrain()
    test_record_trade_feedback_writes()
    print("[OK] M1-01 feedback loop verification passed")
