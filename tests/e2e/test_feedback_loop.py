"""M7.4 e2e：用户反馈闭环（交易结果写回 + 触发再训练 + 调度器），全部离线。

验证点：
- record_trade_feedback：正确统计 pnl / 胜率 / 总数，写回 store（缺接口降级不抛错）。
- trigger_retrain：样本 ≥ 阈值触发（调 retrain_fn），< 阈值不触发；自定义谓词覆盖。
- FeedbackScheduler.run_once：达到阈值触发再训练，历史事件记录；未达阈值不触发。
- FeedbackScheduler 可选定时 start/stop：不阻塞调用方，stop 后不再排程。
- 参数校验（retrain_fn 必填、interval>0）。
"""
from __future__ import annotations

import time
import unittest

from futures_quant.ai import feedback as fb
from futures_quant.app.scheduler import FeedbackScheduler, SchedulerEvent


class _MemoryStore:
    """具备反馈接口的内存 store。"""

    def __init__(self, counts: dict | None = None, with_api: bool = True) -> None:
        self.samples = []
        self.counts = counts or {}
        self.with_api = with_api

    def append_feedback_sample(self, s: dict) -> None:
        self.samples.append(s)

    def feedback_sample_count(self, symbol: str) -> int:
        return self.counts.get(symbol, 0)


class TestRecordTradeFeedback(unittest.TestCase):
    def test_stats(self) -> None:
        store = _MemoryStore()
        trades = [
            {"pnl": 100.0, "close": 1.0},
            {"pnl": -50.0, "close": 2.0},
            {"pnl": 30.0, "close": 3.0},
        ]
        res = fb.record_trade_feedback(store, trades, "rb", "D", "backtest")
        self.assertEqual(res["count"], 3)
        self.assertEqual(len(store.samples), 3)
        self.assertAlmostEqual(res["total_pnl"], 80.0, places=3)
        self.assertAlmostEqual(res["avg_pnl"], 80.0 / 3, places=3)
        self.assertAlmostEqual(res["win_rate"], 2 / 3, places=6)
        self.assertEqual(res["source"], "backtest")
        self.assertEqual(res["symbol"], "rb")

    def test_empty_trades(self) -> None:
        store = _MemoryStore()
        res = fb.record_trade_feedback(store, [], "rb")
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["win_rate"], 0.0)

    def test_missing_api_degrades(self) -> None:
        class NoAPI:
            pass
        res = fb.record_trade_feedback(NoAPI(), [{"pnl": 5.0}], "rb")
        self.assertEqual(res["count"], 0)  # 不抛错，降级


class TestTriggerRetrain(unittest.TestCase):
    def test_below_threshold_not_triggered(self) -> None:
        store = _MemoryStore(counts={"rb": 5})
        calls = []
        def retrain(sym, st):
            calls.append(sym)
            return {"ok": True}
        res = fb.trigger_retrain(retrain, store, "rb", min_samples=20)
        self.assertFalse(res["triggered"])
        self.assertEqual(calls, [])
        self.assertIn("未触发", res["reason"])

    def test_at_threshold_triggered(self) -> None:
        store = _MemoryStore(counts={"rb": 20})
        calls = []
        def retrain(sym, st):
            calls.append(sym)
            return {"ok": True, "sym": sym}
        res = fb.trigger_retrain(retrain, store, "rb", min_samples=20)
        self.assertTrue(res["triggered"])
        self.assertEqual(calls, ["rb"])
        self.assertEqual(res["result"], {"ok": True, "sym": "rb"})

    def test_custom_predicate_overrides(self) -> None:
        store = _MemoryStore(counts={"rb": 1})  # 低于默认阈值
        res = fb.trigger_retrain(lambda s, st: {"ok": 1}, store, "rb", min_samples=20,
                                 should_retrain=lambda n, sym: n >= 1)
        self.assertTrue(res["triggered"])


class TestScheduler(unittest.TestCase):
    def test_run_once_triggered(self) -> None:
        store = _MemoryStore(counts={"au": 30})
        sched = FeedbackScheduler(store, lambda s, st: {"retrained": True}, min_samples=20)
        ev = sched.run_once("au")
        self.assertTrue(ev.triggered)
        self.assertEqual(ev.n_samples, 30)
        self.assertEqual(sched.history[-1], ev)

    def test_run_once_not_triggered(self) -> None:
        store = _MemoryStore(counts={"au": 3})
        sched = FeedbackScheduler(store, lambda s, st: {"retrained": True})
        ev = sched.run_once("au")
        self.assertFalse(ev.triggered)

    def test_retrain_error_captured(self) -> None:
        store = _MemoryStore(counts={"i": 99})
        def boom(s, st):
            raise RuntimeError("x")
        sched = FeedbackScheduler(store, boom)
        ev = sched.run_once("i")
        self.assertTrue(ev.triggered)
        self.assertIn("失败", ev.message)

    def test_invalid_retrain_fn(self) -> None:
        store = _MemoryStore()
        with self.assertRaises(ValueError):
            FeedbackScheduler(store, None)

    def test_summary(self) -> None:
        store = _MemoryStore(counts={"au": 30, "rb": 2})
        sched = FeedbackScheduler(store, lambda s, st: {}, min_samples=20)
        sched.run_once("au")
        sched.run_once("rb")
        s = sched.summary()
        self.assertEqual(s["total_events"], 2)
        self.assertEqual(s["triggered"], 1)
        self.assertFalse(s["running"])

    def test_optional_interval_does_not_block(self) -> None:
        store = _MemoryStore(counts={"x": 50})
        sched = FeedbackScheduler(store, lambda s, st: {"ok": 1}, min_samples=10)
        sched.start(["x"], interval_seconds=0.05)
        self.assertTrue(sched._running)
        t0 = time.time()
        time.sleep(0.12)  # 应触发至少 1 次 interval run_once
        self.assertLess(time.time() - t0, 1.0)  # 未被阻塞
        sched.stop()
        self.assertFalse(sched._running)
        # 至少记录了一次 interval 事件
        self.assertTrue(any(e.trigger == "interval" for e in sched.history))

    def test_start_invalid_interval(self) -> None:
        store = _MemoryStore()
        sched = FeedbackScheduler(store, lambda s, st: {})
        with self.assertRaises(ValueError):
            sched.start(["x"], interval_seconds=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
