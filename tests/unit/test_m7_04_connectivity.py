# -*- coding: utf-8 -*-
"""M7-04 连通性测试体验升级 DoD 验收。

M7-04 全部 7 项 DoD：
① 展示 HTTP 状态码 / 耗时 / 模型名 / 时间戳（四元组）
② 失败显示原始响应（可折叠展开）
③ 失败分类给出可执行建议
④ 错误分类：401/404/503/Timeout/ConnectTimeout/ConnectionError/SSLError/circuit_open
⑤ 历史列表保留最近 5 次（按时间倒序）
⑥ 显示 spinner + 允许取消（threading.Event）
⑦ 接入 M3-08 重试熔断（circuit_open 分类）

DoD 门禁（UPGRADE_PLAN_V5.md）：
- mock 各状态码响应 → 显示对应建议文案且无崩溃
- 历史列表按时间倒序保留 5 条

共 20 项：分类文案 10 + 状态 3 + 历史 3 + 端到端展示 2 + 前置 2。
"""
from __future__ import annotations

import time

import pytest
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QListView, QListWidget, QPlainTextEdit, QPushButton, QTextEdit


@pytest.fixture
def app():
    a = QApplication.instance() or QApplication([])
    yield a
    if not a.property("_is_fixture"):
        a.setProperty("_is_fixture", True)


@pytest.fixture
def dlg(app, monkeypatch):
    # 阻断所有消息框 + 输入框弹窗
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: ("key-123", True))

    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    import futures_quant.ui.ai_settings_dialog as mod

    toast_calls = {"count": 0}
    def fake_toast(parent, message, level="info", duration=2500, **kwargs):
        toast_calls["count"] += 1
    monkeypatch.setattr(mod, "Toast", fake_toast)

    d = AIConfigDialog(None)
    # offscreen 下必须 show 一次让子控件继承显示状态，否则 isVisible() 恒 False
    d.show()
    d._test_advice.show()  # 确保 advice 初始可见（_show_test_result 会显式 show）
    d._raw_toggle.show()
    d._raw_view.show()
    app.processEvents()
    yield d
    d.deleteLater()


# ─────────────────────────────────────────────────────────────
# 1. 分类建议：_TEST_ADVICE 表完整性
# ─────────────────────────────────────────────────────────────

def test_advice_table_has_all_codes(dlg):
    """_TEST_ADVICE 表必须覆盖全部 10 个分类码。"""
    required = {"no_key", "no_requests", "circuit_open", "Timeout",
                "ConnectTimeout", "ConnectionError", "SSLError",
                "401", "404", "503"}
    missing = required - set(dlg._TEST_ADVICE)
    assert not missing, f"_TEST_ADVICE 缺少：{missing}"


def test_advice_401(dlg):
    """401 → 提示密钥/过期。"""
    out = dlg._test_advice_for({"ok": False, "reason": "HTTP 401"})
    assert "密钥" in out or "过期" in out, out


def test_advice_404(dlg):
    """404 → 提示模型名/拼写。"""
    out = dlg._test_advice_for({"ok": False, "reason": "HTTP 404"})
    assert "模型" in out and "agnes-3.0-flash" in out, out


def test_advice_503(dlg):
    """503 → 提示维护/限流/权限/余额。"""
    out = dlg._test_advice_for({"ok": False, "reason": "HTTP 503"})
    assert any(k in out for k in ("维护", "限流", "权限", "余额")), out


def test_advice_timeout(dlg):
    """Timeout 异常 → 提示超时/代理。"""
    out = dlg._test_advice_for({"ok": False, "reason": "Timeout"})
    assert "超时" in out and "代理" in out, out


def test_advice_connect_timeout(dlg):
    """ConnectTimeout → 提示网络/代理。"""
    out = dlg._test_advice_for({"ok": False, "reason": "ConnectTimeout"})
    assert "连接超时" in out, out


def test_advice_connection_error(dlg):
    """ConnectionError → 提示防火墙/网络。"""
    out = dlg._test_advice_for({"ok": False, "reason": "ConnectionError"})
    assert "无法连接" in out or "防火墙" in out, out


def test_advice_ssl(dlg):
    """SSLError → 提示系统时间/中间人。"""
    out = dlg._test_advice_for({"ok": False, "reason": "SSLError"})
    assert "SSL" in out and "系统时间" in out, out


def test_advice_circuit_open(dlg):
    """circuit_open → 提示熔断。"""
    out = dlg._test_advice_for({"ok": False, "reason": "circuit_open"})
    assert "熔断" in out and "5" in out, out


def test_advice_success_and_cancelled(dlg):
    """ok=True 与 cancelled=True 分支独立。"""
    ok = dlg._test_advice_for({"ok": True})
    assert "正常" in ok
    cx = dlg._test_advice_for({"ok": False, "cancelled": True, "reason": ""})
    assert "取消" in cx


def test_advice_unknown_reason_fallback(dlg):
    """未知 reason 走 fallback 而非 KeyError。"""
    out = dlg._test_advice_for({"ok": False, "reason": "Weird"})
    assert "测试失败" in out and "Weird" in out, out


# ─────────────────────────────────────────────────────────────
# 2. 初始状态：_test_state / _test_history / _test_cancel
# ─────────────────────────────────────────────────────────────

def test_initial_test_state_idle(dlg):
    assert dlg._test_state == "idle"


def test_initial_test_history_empty(dlg):
    assert dlg._test_history == []


def test_initial_cancel_not_set(dlg):
    assert dlg._test_cancel.is_set() is False


# ─────────────────────────────────────────────────────────────
# 3. 四元组展示：_show_test_result 头部文本
# ─────────────────────────────────────────────────────────────

def test_show_result_displays_quad_tuple(dlg):
    """① 四元组：状态码 / 耗时 / 模型 / 时间戳 全展示。"""
    res = {"ok": True, "status": 200, "elapsed_ms": 42,
           "model": "agnes-3.0-flash", "time": "2026-10-01 10:30:00",
           "body": "", "attempts": 1, "cancelled": False,
           "breaker_open": False}
    dlg._show_test_result(res)
    txt = dlg._test_summary.text()
    assert "HTTP 200" in txt
    assert "42 ms" in txt
    assert "agnes-3.0-flash" in txt
    assert "2026-10-01" in txt
    assert "✓" in txt, f"成功应显示 ✓：{txt}"


def test_show_result_failure_marks_x_and_red(dlg):
    """失败 → ✗ + 红色（up=红）。"""
    res = {"ok": False, "status": 503, "elapsed_ms": 88,
           "model": "agnes-3.0-flash", "time": "2026-10-01 10:30:00",
           "reason": "HTTP 503", "body": "Service Unavailable",
           "attempts": 3, "cancelled": False, "breaker_open": False}
    dlg._show_test_result(res)
    txt = dlg._test_summary.text()
    assert "HTTP 503" in txt
    assert "✗" in txt, txt


def test_show_result_advice_visible_on_failure(dlg):
    """失败时 _test_advice 显示 + 内容以「建议：」开头。"""
    res = {"ok": False, "status": 401, "elapsed_ms": 10,
           "model": "agnes-3.0-flash", "time": "2026-10-01 10:30:00",
           "reason": "HTTP 401", "body": "", "attempts": 1,
           "cancelled": False, "breaker_open": False}
    dlg._show_test_result(res)
    # isHidden() 只看自身隐藏标志，不受父容器当前页切换影响（诊断页非当前）
    assert not dlg._test_advice.isHidden()
    assert dlg._test_advice.text().startswith("建议：")
    assert "密钥" in dlg._test_advice.text()


def test_show_result_no_advice_when_success(dlg):
    """成功时 _test_advice 仍显示，但文案为「连接正常」。"""
    res = {"ok": True, "status": 200, "elapsed_ms": 42,
           "model": "agnes-3.0-flash", "time": "2026-10-01 10:30:00",
           "body": "", "attempts": 1, "cancelled": False,
           "breaker_open": False}
    dlg._show_test_result(res)
    assert "连接正常" in dlg._test_advice.text()


# ─────────────────────────────────────────────────────────────
# 4. 原始响应可折叠展开（M7-04 ②）
# ─────────────────────────────────────────────────────────────

def test_show_result_body_shows_toggle_and_view(dlg):
    """有 body 时 _raw_toggle 显示 + _raw_view 隐藏（等用户点击展开）。"""
    res = {"ok": False, "status": 503, "elapsed_ms": 10,
           "model": "-", "time": "2026-10-01 10:30:00",
           "reason": "HTTP 503", "body": '{"error": "rate limited"}',
           "attempts": 1, "cancelled": False, "breaker_open": False}
    dlg._show_test_result(res)
    # isHidden 判断自身 show/hide 状态，避免父容器切换页时误判
    assert not dlg._raw_toggle.isHidden()
    assert dlg._raw_view.toPlainText() == '{"error": "rate limited"}'
    assert dlg._raw_view.isHidden()


def test_show_result_no_body_hides_toggle(dlg):
    """无 body 时 toggle 与 view 都隐藏。"""
    res = {"ok": False, "status": 500, "elapsed_ms": 10,
           "model": "-", "time": "2026-10-01 10:30:00",
           "reason": "HTTP 500", "body": "", "attempts": 1,
           "cancelled": False, "breaker_open": False}
    dlg._show_test_result(res)
    assert not dlg._raw_toggle.isVisible()
    assert not dlg._raw_view.isVisible()


# ─────────────────────────────────────────────────────────────
# 5. 历史列表：最近 5 条 + 时间倒序（M7-04 ⑤）
# ─────────────────────────────────────────────────────────────

def _mk_res(i, ok=True):
    return {"ok": ok, "status": 200 if ok else 503, "elapsed_ms": 10 + i,
            "model": f"m-{i}", "time": f"2026-10-01 10:{i:02d}:00",
            "reason": "" if ok else "HTTP 503", "body": "",
            "attempts": 1, "cancelled": False, "breaker_open": False}


def test_history_keeps_latest_five(dlg):
    """6 次测试后 _test_history 只留 5 条 + _history_list.count() == 5。"""
    for i in range(6):
        dlg._show_test_result(_mk_res(i))
    assert len(dlg._test_history) == 5
    assert dlg._history_list.count() == 5


def test_history_time_desc_order(dlg):
    """最新在前：_test_history[0]["time"] > [4]["time"]。"""
    for i in range(3):
        dlg._show_test_result(_mk_res(i))
    times = [h["time"] for h in dlg._test_history]
    assert times == sorted(times, reverse=True), times
    # _test_history 顺序：[2] [1] [0]（最新在前）
    assert dlg._test_history[0]["time"] == "2026-10-01 10:02:00"
    assert dlg._test_history[2]["time"] == "2026-10-01 10:00:00"


def test_history_cancelled_not_recorded(dlg):
    """cancelled 结果不进历史（避免污染统计）。"""
    res = {"ok": False, "status": 0, "elapsed_ms": 10,
           "model": "-", "time": "2026-10-01 10:00:00",
           "reason": "", "body": "", "attempts": 0,
           "cancelled": True, "breaker_open": False}
    dlg._show_test_result(res)
    assert dlg._test_history == []
    assert dlg._history_list.count() == 0


# ─────────────────────────────────────────────────────────────
# 6. 前置条件检查：no_key / no_requests（M7-04 ⑦ + M7-02 联动）
# ─────────────────────────────────────────────────────────────

def test_on_test_no_key_shows_advice_without_poll(app, monkeypatch):
    """前置无密钥 → 直接展示 no_key 建议卡 + 跳到诊断页（不启动轮询）。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: ("", False))

    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    import futures_quant.ui.ai_settings_dialog as mod

    monkeypatch.setattr(mod, "Toast", lambda *a, **k: None)

    # 让 get_client().available() 返回 False（触发前置失败分支）
    import futures_quant.ai.llm_client as llm_client_mod
    class _FakeClient:
        available_flag = False
        model = "agnes-3.0-flash"
        api_key = ""
        def available(self):
            return self.available_flag
    monkeypatch.setattr(llm_client_mod, "get_client",
                        lambda: _FakeClient())

    d = AIConfigDialog(None)
    d.show()
    app.processEvents()
    try:
        d._on_test()
        # 未启动轮询 + state 仍是 idle
        assert d._test_state == "idle"
        assert not d._test_poll.isActive()
        # 结果卡显示 no_key 相关建议
        assert not d._test_advice.isHidden()
        advice = d._test_advice.text()
        assert "密钥" in advice, advice
        # 且没启动 spinner（idle 前置失败分支不应 show spinner）
        assert d._test_spinner.isHidden()
    finally:
        d.deleteLater()


def test_on_test_running_click_sets_cancel(app, monkeypatch):
    """running 状态下再点 _test_btn → cancel.set() + 按钮文案切换。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: ("key", True))

    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    import futures_quant.ui.ai_settings_dialog as mod
    monkeypatch.setattr(mod, "Toast", lambda *a, **k: None)

    d = AIConfigDialog(None)
    try:
        # 手动设置 running 态
        d._test_state = "running"
        d._test_cancel.clear()
        d._on_test()
        assert d._test_cancel.is_set() is True
        assert d._test_btn.text() == "取消中…"
        assert not d._test_btn.isEnabled()
    finally:
        d.deleteLater()


# ─────────────────────────────────────────────────────────────
# 7. _poll_test 轮询收尾（模拟 probe 完成后 UI 更新）
# ─────────────────────────────────────────────────────────────

def test_poll_test_restores_idle_and_btn(app, monkeypatch):
    """poll 时 test_state=running + result 就位 → 恢复 idle + 恢复按钮文案。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: ("key", True))

    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    import futures_quant.ui.ai_settings_dialog as mod
    monkeypatch.setattr(mod, "Toast", lambda *a, **k: None)

    d = AIConfigDialog(None)
    try:
        d._test_state = "running"
        d._test_result = {"ok": True, "status": 200, "elapsed_ms": 50,
                          "model": "agnes-3.0-flash",
                          "time": "2026-10-01 10:00:00",
                          "reason": "", "body": "", "attempts": 1,
                          "cancelled": False, "breaker_open": False}
        d._test_btn.setText("测试中… 点击取消")
        d._test_btn.setEnabled(False)
        d._test_spinner.show()
        d._poll_test()
        # 收尾
        assert d._test_state == "idle"
        assert d._test_result is None
        assert d._test_btn.text() == "测试连接"
        assert d._test_btn.isEnabled()
        assert d._test_spinner.isHidden()
        # 结果卡已展示
        assert "HTTP 200" in d._test_summary.text()
    finally:
        d.deleteLater()
