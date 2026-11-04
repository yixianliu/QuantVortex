"""M8.6 e2e：预警规则引擎 + 政策/宏观事件「事件 → 阈值 → 通知」链路。

验证点（全部离线，无网络、无真实 store 落盘）：
- 原有 K 线规则（price_pct / rsi / fund_flow）行为不变。
- 新增 ``event`` 规则：基于 M8.4 MacroCalendar，处于事件影响窗口 → 触发；
  事件日当天 level="重要"，窗口内 level="注意"。
- 事件名过滤生效（不匹配 → 不触发）。
- 冷却去重：last_fired 在窗口内 → 跳过；窗外 → 可再次推送。
- scan_events 与通用 scan 对 event 规则行为一致，且不阻塞（store 抛异常仍返回触发）。
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from futures_quant.alerts.engine import (
    RULE_KINDS,
    evaluate_rule,
    scan,
    scan_events,
)
from futures_quant.data.macro_calendar import MacroCalendar, MacroEvent


class _FakeStore:
    """内存 store：记录 save_alert / touch_rule_fired 调用，验证写库链路。"""

    def __init__(self) -> None:
        self.alerts = []
        self.touched = []

    def save_alert(self, ts, symbol, rule, level, message):
        self.alerts.append(dict(ts=ts, symbol=symbol, rule=rule, level=level, message=message))

    def touch_rule_fired(self, rid, ts):
        self.touched.append((rid, ts))


class _BoomStore:
    """抛异常的 store：验证事件链路不阻塞（仍返回触发结果）。"""

    def save_alert(self, *a, **k):
        raise RuntimeError("db offline")

    def touch_rule_fired(self, *a, **k):
        raise RuntimeError("db offline")


def _kline(seed: int = 1, n: int = 130, last_chg: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.005, n)
    if n >= 1:
        rets[-1] = last_chg / 100.0
    close = 100 * np.exp(np.cumsum(rets))
    vol = np.abs(rng.normal(1e5, 1e4, n)) + 1e3
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": vol},
        index=idx,
    )


class TestEventRule(unittest.TestCase):
    def test_rule_kind_registered(self) -> None:
        self.assertIn("event", RULE_KINDS)
        self.assertEqual(RULE_KINDS["event"]["label"], "宏观/政策事件")

    def test_event_day_triggers_important(self) -> None:
        cal = MacroCalendar(2025)
        # 取一个具体事件日
        ev = cal.events[0]
        now = dt.datetime(ev.date.year, ev.date.month, ev.date.day, 10, 0)
        rule = {"id": 1, "kind": "event", "symbol": "MACRO",
                "param": ev.impact, "events": cal.events, "event_name": ev.name}
        res = evaluate_rule(rule, pd.DataFrame(), mdm=None, now=now)
        self.assertIsNotNone(res)
        level, msg = res
        self.assertEqual(level, "重要")
        self.assertIn(ev.name, msg)

    def test_window_day_triggers_attention(self) -> None:
        cal = MacroCalendar(2025)
        ev = cal.events[0]
        # 事件日 +1（仍在 impact=2 窗口内，但非事件日）
        day = ev.date + dt.timedelta(days=1)
        now = dt.datetime(day.year, day.month, day.day, 10, 0)
        rule = {"id": 2, "kind": "event", "param": 5,
                "events": [MacroEvent(ev.name, ev.category, ev.date, impact=5)]}
        res = evaluate_rule(rule, pd.DataFrame(), mdm=None, now=now)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "注意")

    def test_out_of_window_no_trigger(self) -> None:
        ev = MacroEvent("测试事件", "policy", dt.date(2025, 3, 5), impact=2)
        # 远在窗口外
        now = dt.datetime(2025, 6, 1)
        rule = {"id": 3, "kind": "event", "param": 2, "events": [ev]}
        self.assertIsNone(evaluate_rule(rule, pd.DataFrame(), mdm=None, now=now))

    def test_event_name_filter(self) -> None:
        ev = MacroEvent("CPI 中国", "release", dt.date(2025, 3, 10), impact=2)
        now = dt.datetime(2025, 3, 10)
        rule_hit = {"id": 4, "kind": "event", "param": 2, "events": [ev], "event_name": "CPI"}
        rule_miss = {"id": 5, "kind": "event", "param": 2, "events": [ev], "event_name": "PMI"}
        self.assertIsNotNone(evaluate_rule(rule_hit, pd.DataFrame(), mdm=None, now=now))
        self.assertIsNone(evaluate_rule(rule_miss, pd.DataFrame(), mdm=None, now=now))

    def test_default_calendar_used_when_no_events(self) -> None:
        # 不传 events → 走 M8.4 默认日历；选一个默认事件日应触发
        cal = MacroCalendar(2025)
        ev = next(e for e in cal.events if e.name == "FOMC 美联储议息")
        now = dt.datetime(ev.date.year, ev.date.month, ev.date.day, 10)
        rule = {"id": 6, "kind": "event", "param": ev.impact, "event_name": "FOMC"}
        res = evaluate_rule(rule, pd.DataFrame(), mdm=None, now=now)
        self.assertIsNotNone(res)


class TestEventScan(unittest.TestCase):
    def test_scan_events_fires_once_and_writes_db(self) -> None:
        store = _FakeStore()
        ev = MacroEvent("两会", "policy", dt.date(2025, 3, 5), impact=5)
        now = dt.datetime(2025, 3, 5)
        rule = {"id": 10, "kind": "event", "symbol": "MACRO", "param": 5,
                "events": [ev], "event_name": "两会"}
        fired = scan_events(None, store, [rule], now=now)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["level"], "重要")
        self.assertEqual(len(store.alerts), 1)
        self.assertEqual(store.alerts[0]["symbol"], "MACRO")
        self.assertEqual(store.touched, [(10, now.isoformat(timespec="seconds"))])

    def test_cooldown_dedup(self) -> None:
        store = _FakeStore()
        ev = MacroEvent("政治局年中会议", "policy", dt.date(2025, 7, 30), impact=5)
        now = dt.datetime(2025, 7, 30)
        rule = {"id": 20, "kind": "event", "param": 5, "events": [ev]}
        first = scan_events(None, store, [rule], now=now)
        self.assertEqual(len(first), 1)
        # 模拟已推送：last_fired 在冷却窗口内（1 天前）→ 应跳过
        rule["last_fired"] = (now - dt.timedelta(hours=12)).isoformat(timespec="seconds")
        second = scan_events(None, store, [rule], now=now)
        self.assertEqual(len(second), 0)
        self.assertEqual(len(store.alerts), 1)  # 未再写库

    def test_store_boom_not_blocking(self) -> None:
        ev = MacroEvent("两会", "policy", dt.date(2025, 3, 5), impact=5)
        rule = {"id": 30, "kind": "event", "param": 5, "events": [ev]}
        fired = scan_events(None, _BoomStore(), [rule], now=dt.datetime(2025, 3, 5))
        self.assertEqual(len(fired), 1)  # store 抛异常仍返回触发

    def test_scan_generic_handles_event_kind(self) -> None:
        """通用 scan 也正确处理 event 规则（不读 K 线，不抛错）。"""
        store = _FakeStore()
        ev = MacroEvent("两会", "policy", dt.date(2025, 3, 5), impact=5)
        rule = {"id": 40, "kind": "event", "symbol": "MACRO", "param": 5, "events": [ev]}
        fired = scan(None, store, [rule], now=dt.datetime(2025, 3, 5))
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["rule"], "宏观/政策事件")


class TestKLIneRulesUnchanged(unittest.TestCase):
    """回归：原有 K 线规则行为不变。"""

    def test_price_pct_trigger(self) -> None:
        df = _kline(last_chg=0.0)
        # 强制 close[-1] = close[-2]*1.07 → chg_pct = 7% >= 2*3%=6% → 重要
        df.loc[df.index[-1], "close"] = df["close"].iloc[-2] * 1.07
        res = evaluate_rule({"kind": "price_pct", "param": 3.0, "symbol": "rb"}, df, mdm=None)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "重要")  # 7% >= 2*3%

    def test_price_pct_attention(self) -> None:
        df = _kline(last_chg=0.0)
        df.loc[df.index[-1], "close"] = df["close"].iloc[-2] * 1.04  # 4% >= 3% 但 < 6%
        res = evaluate_rule({"kind": "price_pct", "param": 3.0, "symbol": "rb"}, df, mdm=None)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "注意")

    def test_price_pct_no_trigger(self) -> None:
        df = _kline(last_chg=0.0)
        df.loc[df.index[-1], "close"] = df["close"].iloc[-2] * 1.01
        self.assertIsNone(evaluate_rule({"kind": "price_pct", "param": 3.0, "symbol": "rb"}, df, mdm=None))

    def test_short_df_returns_none(self) -> None:
        self.assertIsNone(evaluate_rule(
            {"kind": "price_pct", "param": 3.0, "symbol": "rb"},
            pd.DataFrame({"close": [1.0, 2.0]}), mdm=None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
