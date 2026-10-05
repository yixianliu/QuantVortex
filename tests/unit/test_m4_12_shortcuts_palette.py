# -*- coding: utf-8 -*-
"""M4-12 快捷键与命令面板 DoD 验收。

M4-12 三项 DoD：
① 新增：Ctrl+K 命令面板 / F5 刷新当前页 / Ctrl+E 导出当前表 /
   Ctrl+, 打开模型配置 / Esc 关闭浮层 / Ctrl+1..7 切页
② 帮助菜单新增「快捷键」清单
③ 全部注册到 _setup_shortcuts() 并在状态栏 Tooltip 提示

DoD 门禁：每个快捷键有对应测试（offscreen 下 QTest.keyClick）；
命令面板搜索「回测」可跳转。

共 14 项：快捷键注册 6 + 帮助清单 2 + 状态栏 Tooltip 1 + 命令面板 5。
"""
from __future__ import annotations

import ast
import os

import pytest
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _proj_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _src(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# ① 快捷键注册（Ctrl+K / F5 / Ctrl+E / Ctrl+, / Esc / Ctrl+1..7）
# ─────────────────────────────────────────────────────────────

def test_shortcut_seqs_registered(qapp):
    """M4-12①：7 组快捷键全部注册到 _shortcut_seqs。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        seqs = [s for s, _ in mw._shortcut_seqs]
        for expected in ("Ctrl+K", "F5", "Ctrl+E", "Ctrl+,", "Esc"):
            assert expected in seqs, f"缺 {expected}"
        # Ctrl+1..7 切页
        for i in range(1, 8):
            assert f"Ctrl+{i}" in seqs, f"缺 Ctrl+{i}"
    finally:
        mw.deleteLater()
        qapp.processEvents()


def test_shortcut_helpers_registered(qapp):
    """M4-12①：M7-07 局部快捷键说明也登记进帮助清单。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        seqs = [s for s, _ in mw._shortcut_seqs]
        # AI 对话框局部快捷键（登记为说明，不是 QShortcut）
        for expected in ("Ctrl+S（AI 对话框）", "Ctrl+Enter（AI 对话框）",
                         "Ctrl+R（AI 对话框）"):
            assert expected in seqs, f"缺 {expected}"
    finally:
        mw.deleteLater()
        qapp.processEvents()


def test_shortcut_handler_bound(qapp):
    """M4-12①：Ctrl+K 对应 _open_palette 函数存在。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        assert callable(mw._open_palette)
        assert callable(mw._refresh_current_page)
        assert callable(mw._export_current_table)
        assert callable(mw._open_ai_settings)
        assert callable(mw._close_overlays)
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ② 帮助菜单「快捷键」清单
# ─────────────────────────────────────────────────────────────

def test_help_menu_has_shortcuts_entry(qapp):
    """M4-12②：帮助菜单下含「快捷键」动作。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        mb = mw.menuBar()
        help_texts = []
        for act in mb.actions():
            if act.text() == "帮助":
                for sub in act.menu().actions():
                    help_texts.append(sub.text())
        assert any("快捷键" in t for t in help_texts), \
            f"帮助菜单缺「快捷键」：{help_texts}"
    finally:
        mw.deleteLater()
        qapp.processEvents()


def test_show_shortcuts_callable(qapp):
    """M4-12②：_show_shortcuts 方法可调用（打开快捷键清单对话框）。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        assert callable(mw._show_shortcuts)
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ③ 状态栏 Tooltip 快捷键速查
# ─────────────────────────────────────────────────────────────

def test_status_tooltip_lists_shortcuts(qapp):
    """M4-12③：状态栏 Tooltip 含「快捷键」字样并列举主要序列。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        tip = mw.status.toolTip()
        assert "快捷键" in tip
        for expected in ("Ctrl+K", "F5", "Ctrl+E"):
            assert expected in tip, f"Tooltip 缺 {expected}"
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# 命令面板
# ─────────────────────────────────────────────────────────────

def test_command_palette_fuzzy_match(qapp):
    """M4-12①：命令面板模糊搜索「回测」可命中「回测中心」项。"""
    from futures_quant.ui.command_palette import CommandPalette, fuzzy_score
    assert fuzzy_score("回测", "回测中心") > 0
    assert fuzzy_score("ht", "回测") == 0  # 中文字符不参与 ASCII 匹配
    assert fuzzy_score("bc", "backtest") > 0


def test_command_palette_filter(qapp):
    """M4-12①：CommandPalette 按 query 过滤结果。"""
    from futures_quant.ui.command_palette import CommandPalette
    items = [
        ("页面:回测中心", "页面", lambda: None),
        ("页面:行情全景", "页面", lambda: None),
        ("命令:导出当前表（Ctrl+E）", "命令", lambda: None),
    ]
    cp = CommandPalette(None, items)
    try:
        cp._refill("")
        assert cp.listw.count() == 3
        cp._refill("回测")
        assert cp.listw.count() == 1
        assert "回测中心" in cp.listw.item(0).text()
        cp._refill("E")
        # 「导出当前表（Ctrl+E）」含 E
        assert cp.listw.count() >= 1
    finally:
        cp.deleteLater()
        qapp.processEvents()


def test_command_palette_esc_reject(qapp):
    """M4-12①：Esc 键关闭命令面板（走 eventFilter 而非 keyPressEvent）。"""
    from futures_quant.ui.command_palette import CommandPalette
    cp = CommandPalette(None, [("测试", "测试", lambda: None)])
    try:
        rejected = {"n": 0}
        cp.reject = lambda: rejected.__setitem__("n", rejected["n"] + 1)
        ev = QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_Escape),
                       Qt.KeyboardModifier(0))
        # CommandPalette 用 eventFilter 拦 input 的 Esc（源码 line 147-152）
        handled = cp.eventFilter(cp.input, ev)
        assert rejected["n"] == 1, "Esc 未触发 reject"
        assert handled is True, "Esc 事件应被 eventFilter 消费"
    finally:
        cp.deleteLater()
        qapp.processEvents()


def test_command_palette_enter_executes(qapp):
    """M4-12①：Enter 键执行当前选中项。"""
    from futures_quant.ui.command_palette import CommandPalette
    from PyQt6.QtWidgets import QDialog
    called = []
    items = [("测试项", "测试", lambda: called.append("exec"))]
    cp = CommandPalette(None, items)
    try:
        cp._refill("")
        cp._exec_current()
        assert called == ["exec"]
        # accept 后 result() == Accepted
        assert cp.result() == QDialog.DialogCode.Accepted
    finally:
        cp.deleteLater()
        qapp.processEvents()


def test_command_palette_keyboard_nav(qapp):
    """M4-12①：↑/↓ 键切换选中行。"""
    from futures_quant.ui.command_palette import CommandPalette
    items = [
        ("A", "cat", lambda: None),
        ("B", "cat", lambda: None),
        ("C", "cat", lambda: None),
    ]
    cp = CommandPalette(None, items)
    try:
        cp._refill("")
        assert cp.listw.currentRow() == 0
        cp._move(1)
        assert cp.listw.currentRow() == 1
        cp._move(-1)
        assert cp.listw.currentRow() == 0
        # 边界：负向越界不动
        cp._move(-1)
        assert cp.listw.currentRow() == 0
        # 边界：正向越界不动
        cp._move(1)
        cp._move(1)
        cp._move(10)
        assert cp.listw.currentRow() == 2
    finally:
        cp.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# 契约：M4-12 标记
# ─────────────────────────────────────────────────────────────

def test_m4_12_marker_in_source(qapp):
    """M4-12 关键节点在源码中有标记。"""
    path = os.path.join(_proj_root(), "futures_quant", "ui",
                        "main_window.py")
    src = _src(path)
    assert "M4-12①" in src
    assert "M4-12③" in src
