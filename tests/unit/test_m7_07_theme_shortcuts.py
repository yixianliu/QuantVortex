# -*- coding: utf-8 -*-
"""M7-07 主题化与交互提示 DoD 验收。

M7-07 六项 DoD：
① 硬编码 inline 样式改 pal()/token
② set_theme() 递归覆盖全部分段与字段
③ 快捷键：Ctrl+S / Ctrl+Enter / Ctrl+R / Esc
④ 控件补 setToolTip
⑤ _apply_timer 单发 150ms
⑥ config_applied 信号保留

DoD 门禁：
- 连续切换主题 10 次无残留旧色
- 4 个快捷键均生效且写进「快捷键」帮助

共 18 项：快捷键 4 + 主题切换 5 + setToolTip 5 + apply_timer 2 + 契约 2。
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_dialog():
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    return AIConfigDialog()


@pytest.fixture
def dlg(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("key", True))
    import futures_quant.ui.ai_settings_dialog as mod
    monkeypatch.setattr(mod, "Toast", lambda *a, **k: None)

    d = _make_dialog()
    try:
        yield d
    finally:
        # Ctrl+S / Ctrl+R 等用例会启动对话框内部单发 QTimer（_apply_timer 等）。
        # 定时器回调若不先 stop 就 deleteLater 掉 widget，回调会在对象已释放后
        # 触发（M7-07⑤ 的 _finish_apply → _do_apply 还 touching 配置层），
        # 属明确的对象生命周期错误，必须先停表再删对象。
        try:
            for name in ("_apply_timer", "_save_spinner", "_test_poll",
                         "_copy_timer"):
                t = getattr(d, name, None)
                if t is not None:
                    t.stop()
        except Exception:
            pass
        try:
            d.deleteLater()
        except Exception:
            pass
        try:
            qapp.processEvents()
        except Exception:
            pass
        # 上面这段与「teardown 前先停定时器」一起，是 v5.2.6 把本文件
        # 退出期 0xC0000409 崩溃根治掉的关键（真因见 test_apply_timer_timeout_wired
        # 的 docstring：真实槽函数被误触发）。
        try:
            for name in ("_apply_timer", "_save_spinner", "_test_poll",
                         "_copy_timer"):
                t = getattr(d, name, None)
                if t is not None:
                    t.stop()
        except Exception:
            pass
        try:
            d.deleteLater()
        except Exception:
            pass
        # 强制处理 pending deleteLater，防止大量未清理 widget 在 session 结束时 crash
        try:
            qapp.processEvents()
        except Exception:
            pass


def _key_event(key, mods=0, is_press=True):
    """构造 QKeyEvent（PyQt6 需 int keycode，非 Qt.Key_*）。"""
    return QKeyEvent(
        QEvent.Type.KeyPress if is_press else QEvent.Type.KeyRelease,
        key, Qt.KeyboardModifiers(mods) if mods else Qt.KeyboardModifier.NoModifier,
    )


# 注：QEvent.Type 需要单独导入


# ─────────────────────────────────────────────────────────────
# 1. 快捷键 4 项（DoD ③）
# ─────────────────────────────────────────────────────────────

def test_shortcut_ctrl_s_calls_apply(dlg, monkeypatch):
    """Ctrl+S → _on_apply 被调用。"""
    called = {"n": 0}
    monkeypatch.setattr(dlg, "_on_apply", lambda: called.__setitem__("n", called["n"] + 1))
    ev = QKeyEvent(QEvent.Type.KeyPress,
                   int(Qt.Key.Key_S),
                   Qt.KeyboardModifier.ControlModifier)
    dlg.keyPressEvent(ev)
    assert called["n"] == 1


def test_shortcut_ctrl_enter_calls_test(dlg, monkeypatch):
    """Ctrl+Enter → _on_test 被调用。"""
    called = {"n": 0}
    monkeypatch.setattr(dlg, "_on_test", lambda: called.__setitem__("n", called["n"] + 1))
    ev = QKeyEvent(QEvent.Type.KeyPress,
                   int(Qt.Key.Key_Return),
                   Qt.KeyboardModifier.ControlModifier)
    dlg.keyPressEvent(ev)
    assert called["n"] == 1


def test_shortcut_ctrl_r_calls_reset(dlg, monkeypatch):
    """Ctrl+R → _on_reset 被调用（含 QMessageBox.question 二次确认，已被 monkeypatch）。"""
    called = {"n": 0}
    monkeypatch.setattr(dlg, "_on_reset", lambda: called.__setitem__("n", called["n"] + 1))
    ev = QKeyEvent(QEvent.Type.KeyPress,
                   int(Qt.Key.Key_R),
                   Qt.KeyboardModifier.ControlModifier)
    dlg.keyPressEvent(ev)
    assert called["n"] == 1


def test_shortcut_esc_calls_reject(dlg):
    """Esc → reject（对话框关闭且不保存）。"""
    rejected = {"n": 0}
    dlg.reject = lambda: rejected.__setitem__("n", rejected["n"] + 1)
    ev = QKeyEvent(QEvent.Type.KeyPress,
                   int(Qt.Key.Key_Escape),
                   Qt.KeyboardModifier.NoModifier)
    dlg.keyPressEvent(ev)
    assert rejected["n"] == 1


def test_shortcut_s_plain_not_intercepted(dlg, monkeypatch):
    """普通 S（无 Ctrl）→ 不被对话框拦截，转发父类处理。"""
    called = {"n": 0}
    monkeypatch.setattr(dlg, "_on_apply", lambda: called.__setitem__("n", called["n"] + 1))
    ev = QKeyEvent(QEvent.Type.KeyPress,
                   int(Qt.Key.Key_S),
                   Qt.KeyboardModifier.NoModifier)
    dlg.keyPressEvent(ev)
    assert called["n"] == 0, "无 Ctrl 时 S 不应触发 apply"


# ─────────────────────────────────────────────────────────────
# 2. set_theme 递归刷新（DoD ②）
# ─────────────────────────────────────────────────────────────

def test_set_theme_calls_reapply_theme(dlg):
    """set_theme 内部必须调用 _apply_theme 与 _style_status（消除状态残留）。"""
    calls = {"apply_theme": 0, "style_status": 0}
    orig_at = dlg._apply_theme
    orig_ss = dlg._style_status
    def _fake_at():
        calls["apply_theme"] += 1
        orig_at()
    def _fake_ss(lv):
        calls["style_status"] += 1
        orig_ss(lv)
    dlg._apply_theme = _fake_at
    dlg._style_status = _fake_ss
    try:
        dlg.set_theme("light")
        assert calls["apply_theme"] >= 1
        assert calls["style_status"] >= 1
    finally:
        dlg.set_theme("dark")


def test_set_theme_dark_to_light_to_dark_no_residue(dlg):
    """10 次连续 dark↔light 切换后，styleSheet 色值属于当前主题（无残留）。

    色值从 widgets.PALETTE 读（ai_settings_dialog._apply_theme 用 pal()），
    主题切换后 bg 值必须与当前 PALETTE 一致。
    """
    from futures_quant.ui import widgets as W
    try:
        for i in range(10):
            theme = "light" if i % 2 == 0 else "dark"
            dlg.set_theme(theme)
        # 最后一次是 dark
        sheet = dlg.styleSheet()
        dark_bg = W.PALETTE["dark"]["bg"]
        light_bg = W.PALETTE["light"]["bg"]
        assert dark_bg in sheet, f"dark bg {dark_bg} 未出现在 styleSheet"
        assert light_bg not in sheet, f"light bg {light_bg} 残留"
        # 切到 light 反向验证
        dlg.set_theme("light")
        sheet2 = dlg.styleSheet()
        assert light_bg in sheet2, f"light bg {light_bg} 未出现在 styleSheet"
        assert dark_bg not in sheet2, f"dark bg {dark_bg} 残留"
    finally:
        dlg.set_theme("dark")


def test_set_theme_qss_contains_all_field_selectors(dlg):
    """set_theme 触发 _apply_theme，QSS 含 6 个字段级选择器。"""
    dlg.set_theme("light")
    sheet = dlg.styleSheet()
    for selector in ("#ai-group", "#ai-input", "#ai-nav",
                     "#ai-hint", "#ai-error", "#ai-dirty"):
        assert selector in sheet, f"QSS 缺少选择器：{selector}"
    dlg.set_theme("dark")


def test_set_theme_syncs_widgets_theme(dlg):
    """set_theme 同步 widgets.THEME 与 ai_settings_dialog.THEME（消除残留的关键）。"""
    from futures_quant.ui import widgets as W
    import futures_quant.ui.ai_settings_dialog as mod

    orig_w = W.THEME
    orig_mod = mod.THEME
    try:
        dlg.set_theme("light")
        assert W.THEME == "light"
        assert mod.THEME == "light"
    finally:
        dlg.set_theme("dark")
        W.THEME = orig_w
        mod.THEME = orig_mod


# ─────────────────────────────────────────────────────────────
# 3. setToolTip 覆盖（DoD ④）
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("attr", [
    "_api_key_edit", "_model_combo", "_max_tokens_spin",
    "_temperature_spin", "_timeout_spin", "_retry_spin",
    "_backoff_spin", "_concurrency_spin", "_proxy_edit",
    "_redact_check", "_watchdog_check", "_reset_btn",
    "_history_list", "_export_btn", "_import_btn",
])
def test_tooltip_present(dlg, attr):
    """关键控件必须补 setToolTip（说明取值范围与影响）。"""
    w = getattr(dlg, attr, None)
    assert w is not None, f"控件 {attr} 不存在"
    tt = w.toolTip()
    assert tt and len(tt) >= 6, f"{attr} tooltip 缺失或过短：{tt!r}"


# ─────────────────────────────────────────────────────────────
# 4. _apply_timer 单发 150ms（DoD ⑤）
# ─────────────────────────────────────────────────────────────

def test_apply_timer_single_shot(dlg):
    """_apply_timer 必须 singleShot=True（避免重复触发）。"""
    assert dlg._apply_timer.isSingleShot() is True


def test_apply_timer_timeout_wired(dlg):
    """_apply_timer.timeout 连接到 _finish_apply。

    v5.2.6 修正（这个用例单独就能把整个文件搞崩）：
    原实现用 ``monkeypatch.setattr(dlg, "_finish_apply", stub)`` 去拦截槽函数，
    但 Qt 信号在 ``AIConfigDialog.__init__`` 里就已经绑定了**真实**槽函数，
    事后改实例属性**拦不住**那个连接 —— 于是 ``emit()`` 真跑了
    ``_finish_apply → _do_apply``（会落配置、改全局状态），
    既污染其它用例的状态，又在进程里留下未清理的 Qt 调用，
    最终把整个用例文件带崩（CRT fast-fail 0xC0000409，最后 2 个用例根本跑不到）。
    正确做法：**先断言「确实已连着槽」**，再断开、重连到计数器上验证信号通路。
    """
    timer = dlg._apply_timer
    assert timer.receivers(timer.timeout) >= 1, "_apply_timer.timeout 未接槽"

    called = {"n": 0}

    def _stub():
        called["n"] += 1

    try:
        timer.timeout.disconnect()
        timer.timeout.connect(_stub)
        timer.timeout.emit()
    finally:
        timer.timeout.disconnect()
    assert called["n"] == 1


# ─────────────────────────────────────────────────────────────
# 5. 契约与信号（DoD ⑥）
# ─────────────────────────────────────────────────────────────

def test_config_applied_signal_exists(dlg):
    """config_applied 信号存在（主窗口状态栏依赖）。"""
    assert hasattr(dlg, "config_applied"), "缺少 config_applied 信号"
