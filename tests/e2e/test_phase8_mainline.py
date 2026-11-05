# -*- coding: utf-8 -*-
"""第 8 期主线压缩：真实点击路径计数（改造前后对照）。

主线定义：看行情 → 调策略 → 回测 → 看结果 → 预测。

做法：
    - 构建真实 MainWindow（offscreen），用真实控件 click() 驱动；
    - 用 QStackedWidget.currentChanged 统计“页面切换次数”；
    - 对耗时步骤（预测 / 手动回测）打桩，只统计“触发等待”的次数，
      不真正跑模型与回测（点击与跳转仍是真实控件事件）；
    - 分别走两条尾部路径：
        LEGACY：侧栏切回预测 → 手动选品种 → 点开始预测（改造前形态）
        NEW   ：点「🔮 去预测」（带上下文 + auto_run，改造后形态）

运行：
    python -m pytest tests/e2e/test_phase8_mainline.py -s -q
"""
from __future__ import annotations

import json
import os

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication


def _stop_timers(widget) -> None:
    """停掉窗口定时器，避免后台刷新干扰计数。"""
    for t in widget.findChildren(QTimer):
        try:
            if t.isActive():
                t.stop()
        except Exception:  # noqa: BLE001
            pass


class _Counter:
    """点击 / 页面切换 / 等待点计数。"""

    def __init__(self):
        self.clicks = 0
        self.switches = 0
        self.waits = 0
        self.notes = []

    def click(self) -> None:
        self.clicks += 1

    def to_dict(self) -> dict:
        return {"clicks": self.clicks, "page_switches": self.switches,
                "waits": self.waits, "notes": self.notes}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _build_window(qapp):
    from futures_quant.ui.main_window import MainWindow
    win = MainWindow()
    _stop_timers(win)
    win.resize(1600, 960)
    win.show()
    qapp.processEvents()
    # 首页是 showEvent 里 100ms 延迟构造的：测试里显式提前完成，
    # 避免延迟定时器在后续 processEvents 时插入一次页面切换，污染计数。
    win._init_first_page()
    qapp.processEvents()
    return win


def test_mainline_click_budget(qapp, monkeypatch):
    """统计主线两条尾部路径的点击/切页/等待次数并打印对照 JSON。"""
    from futures_quant.ui.backtest_page import BacktestCenterPage
    from futures_quant.ui.predict_ops_page import PredictOpsPage

    win = _build_window(qapp)
    # 起点：默认落在「行情全景」（启动定位不算用户动作，不计入统计）
    assert win._show_page(0)
    qapp.processEvents()
    counter = _Counter()

    def _on_stack_changed(i: int) -> None:
        """记录页面切换次数与被切到的页面（用于解释统计口径）。"""
        w = win.stack.widget(i)
        counter.switches += 1
        counter.notes.append(f"switch→{type(w).__name__}")

    win.stack.currentChanged.connect(_on_stack_changed)

    # 对耗时动作打桩：点击照样发生，只记一次“等待”
    monkeypatch.setattr(PredictOpsPage, "_run_prediction",
                        lambda self: setattr(counter, "waits", counter.waits + 1))
    monkeypatch.setattr(BacktestCenterPage, "_run_manual",
                        lambda self, *a, **k: setattr(counter, "waits", counter.waits + 1))

    try:
        # ---- 0) 看行情：已在行情全景页 ----
        mo = win.stack.currentWidget()

        # ---- 1) 双击行情行 → 预测页（真实点击路径）----
        counter.click()
        if getattr(mo, "watch", None) is not None and mo.watch.rowCount() > 0:
            mo._on_pick(0)
        else:
            # 离屏无数据时退化为同一条跨页信号（仍是一次用户动作）
            counter.notes.append("行情表为空，使用同一跨页信号代替双击")
            mo.navigate_requested.emit("predict_ops", {
                "symbol": mo.sym_cb.currentData(), "period": "D"})
        qapp.processEvents()
        predict = win.stack.currentWidget()

        # ---- 2) 调策略 / 预测：点开始预测 ----
        assert isinstance(predict, PredictOpsPage)
        counter.click()
        predict.start_btn.click()
        qapp.processEvents()

        # 模拟“预测已完成”（真实链路里由后台回调置位）
        predict._last_res = {"symbol": predict.cur_symbol, "period": predict.cur_period}
        predict._set_ai_ind_enabled(True)
        predict.backtest_link_btn.setEnabled(True)

        # ---- 3) 回测：点“回测此策略”（真实 click，自动切页 + 自动运行）----
        counter.click()
        predict.backtest_link_btn.click()
        qapp.processEvents()
        backtest = win.stack.currentWidget()
        assert isinstance(backtest, BacktestCenterPage)

        # ---- 4) 看结果：KPI 自动刷新，无点击 ----
        # 记录“回测已完成、准备去预测”这一刻的基数
        base = counter.to_dict()

        # ---- 5a) NEW：一键去预测（带上下文 + auto_run）----
        assert hasattr(backtest, "_manual_predict_btn"), "缺少一键去预测按钮"
        counter.click()
        backtest._manual_predict_btn.click()
        qapp.processEvents()
        assert isinstance(win.stack.currentWidget(), PredictOpsPage)
        assert counter.waits == base["waits"] + 1, "auto_run 未触发自动预测"
        new_total = counter.to_dict()
        new_delta = {
            "clicks": new_total["clicks"] - base["clicks"],
            "page_switches": new_total["page_switches"] - base["page_switches"],
            "waits": new_total["waits"] - base["waits"],
        }

        # ---- 5b) LEGACY：切回预测 → 手选品种 → 点开始（改造前形态）----
        # 先回到回测页，保证起点相同；这次“复位”不算用户操作，重新取基数
        win._goto_page("backtest")
        qapp.processEvents()
        base_legacy = counter.to_dict()
        # 侧栏切回预测（1 次点击 + 1 次切页）
        counter.click()
        win._goto_page("predict_ops")
        qapp.processEvents()
        p2 = win.stack.currentWidget()
        # 手动选品种（1 次点击）
        counter.click()
        idx = p2.sym_cb.findData(p2.cur_symbol)
        if idx >= 0:
            p2.sym_cb.setCurrentIndex(idx)
        # 点开始预测（1 次点击 + 1 次等待）
        counter.click()
        p2.start_btn.click()
        qapp.processEvents()
        legacy_total = counter.to_dict()
        legacy_delta = {
            "clicks": legacy_total["clicks"] - base_legacy["clicks"],
            "page_switches": legacy_total["page_switches"] - base_legacy["page_switches"],
            "waits": legacy_total["waits"] - base_legacy["waits"],
        }

        payload = {
            "legacy_tail": legacy_delta,
            "new_tail": new_delta,
            "reduction": {
                "clicks": legacy_delta["clicks"] - new_delta["clicks"],
                "page_switches": legacy_delta["page_switches"] - new_delta["page_switches"],
                "waits": legacy_delta["waits"] - new_delta["waits"],
            },
            "mainline_before_tail": base,
        }
        print("\nMAINLINE_CLICK_JSON " + json.dumps(payload, ensure_ascii=False))
        # 硬断言：新路径必须比旧路径少点击
        assert new_delta["clicks"] < legacy_delta["clicks"]
    finally:
        try:
            win.close()
        except Exception:  # noqa: BLE001
            pass
        qapp.processEvents()
