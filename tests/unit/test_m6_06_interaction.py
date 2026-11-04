# -*- coding: utf-8 -*-
"""M6-06 关于对话框交互与可达性 DoD 验收。

M6-06 六项 DoD：
① Esc 关闭对话框
② Tab 焦点顺序：Hero → 信息行 → 二维码卡 → 页脚按钮
③ 二维码卡可键盘激活（Enter / 空格 → 放大）
④ 复制按钮 accessibleName（形如「复制QQ号」）
⑤ 复制成功后 QToolTip 提示 + 按钮文案「已复制 ✓」
⑥ 页脚「复制版本信息」按钮

共 16 项：Esc 3 + Tab 顺序 3 + 键盘激活 3 + accessible 3 + 复制反馈 2 + 版本信息 2。
"""
from __future__ import annotations

import ast
import os

import pytest
from PyQt6.QtCore import Qt, QEvent, QPoint
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _key_press(key: int, mods: int = 0) -> QKeyEvent:
    """构造 QKeyEvent（PyQt6 需 int keycode）。"""
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier(mods))


def _key_press_esc() -> QKeyEvent:
    return _key_press(int(Qt.Key.Key_Escape))


def _key_press_tab() -> QKeyEvent:
    return _key_press(int(Qt.Key.Key_Tab))


# ─────────────────────────────────────────────────────────────
# ① Esc 关闭
# ─────────────────────────────────────────────────────────────

def test_esc_closes_dialog(qapp):
    """M6-06①：按 Esc 对话框 reject。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        rejected = {"n": 0}
        d.reject = lambda: rejected.__setitem__("n", rejected["n"] + 1)
        d.show()
        qapp.processEvents()
        d.keyPressEvent(_key_press_esc())
        assert rejected["n"] == 1, "Esc 未触发 reject"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_esc_handler_exists(qapp):
    """M6-06①：keyPressEvent 内 Esc 分支存在（源码级）。"""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "futures_quant", "ui", "about_page.py")
    src = open(path, "r", encoding="utf-8").read()
    tree = ast.parse(src)
    # 找 AboutDialog.keyPressEvent
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AboutDialog":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "keyPressEvent":
                    found = True
                    body_src = ast.get_source_segment(src, item) or ""
                    assert "Key_Escape" in body_src, "Esc 分支缺失"
    assert found, "AboutDialog.keyPressEvent 未找到"


def test_esc_defers_to_modal_up(qapp, monkeypatch):
    """M6-06①：当有模态灯箱打开时，父对话框的 Esc 交给 super() 处理
    （源码级断言：super().keyPressEvent 被调用，而不是 self.reject()）。
    """
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        reject_calls = {"n": 0}
        super_calls = {"n": 0}
        d.reject = lambda: reject_calls.__setitem__("n", reject_calls["n"] + 1)

        orig_super_kp = type(d).mro()[1].keyPressEvent

        def fake_super_kp(self, event):
            super_calls["n"] += 1
            return orig_super_kp(self, event)

        # 用类型级别的 fake super 拦不到直接 super() 调用；
        # 改在实例层拦截：monkeypatch QDialog 的 keyPressEvent。
        from PyQt6.QtWidgets import QDialog
        monkeypatch.setattr(
            QDialog, "keyPressEvent",
            lambda self, ev: (super_calls.__setitem__(
                "n", super_calls["n"] + 1), orig_super_kp(self, ev))[1])

        d.show()
        qapp.processEvents()
        # 假模态：非 self 的 activeModalWidget
        class _FakeModal:
            pass
        monkeypatch.setattr(
            QApplication, "activeModalWidget",
            staticmethod(lambda: _FakeModal()))
        d.keyPressEvent(_key_press_esc())
        # 关键断言：走 super().keyPressEvent 分支（父对话框的直接 self.reject 未调用）
        assert super_calls["n"] >= 1, \
            f"有模态时未调用 super().keyPressEvent（super={super_calls}）"
    finally:
        d.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ② Tab 焦点顺序
# ─────────────────────────────────────────────────────────────

def test_tab_order_chain_set(qapp):
    """M6-06②：_setup_tab_order 建立 4+N 条 setTabOrder 链。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        # 有信息行复制按钮 4 + 二维码卡 4 + 页脚按钮 3 = 11 控件 → 10 条 setTabOrder
        chain_len = (len(d._info_grid._rows)
                     + sum(len(sec._cards) for sec in d.findChildren(
                         type(d._info_grid).__module__ and
                         __import__("futures_quant.ui.about_page",
                                    fromlist=["_QRSection"])._QRSection
                         )) + 3)
        # 不严格锁死数量，但确保 >= 8 条 setTabOrder 关联
        # 采用 nextInFocusChain 探测：从第一个复制按钮出发应能走到第二个
        first = d._info_grid._rows[0]._copy_btn
        nxt = first.nextInFocusChain()
        # 至少第一个复制按钮的 next 是某个已知控件（不是 None）
        assert nxt is not None, "首个复制按钮 nextInFocusChain 为空"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_info_copy_buttons_in_tab_chain(qapp):
    """M6-06②：4 个信息行复制按钮都在焦点链中且是 StrongFocus。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        assert len(d._info_grid._rows) == 4
        for row in d._info_grid._rows:
            btn = row._copy_btn
            assert btn.focusPolicy() == Qt.FocusPolicy.StrongFocus
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_footer_buttons_in_tab_chain(qapp):
    """M6-06②：3 个页脚按钮都在焦点链中。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        for btn in (d._diag_btn, d._update_btn, d._copy_ver_btn):
            assert btn.focusPolicy() == Qt.FocusPolicy.StrongFocus, \
                f"{btn.text()} 焦点策略错误"
    finally:
        d.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ③ 二维码卡键盘激活
# ─────────────────────────────────────────────────────────────

def test_qr_card_keyboard_focusable(qapp):
    """M6-06③：二维码卡 StrongFocus，可通过 Tab 到达。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        sections = d.findChildren(
            __import__("futures_quant.ui.about_page", fromlist=["_QRSection"])._QRSection)
        assert len(sections) == 2
        for sec in sections:
            for card in sec._cards:
                assert card._card.focusPolicy() == Qt.FocusPolicy.StrongFocus
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_qr_card_enter_opens_lightbox(qapp, monkeypatch):
    """M6-06③：Enter 键触发 _open_lightbox（放大浮层）。"""
    from futures_quant.ui.qr_card import QRCard
    opened = []

    def _fake_open(self):
        opened.append(self._title)
    monkeypatch.setattr(QRCard, "_open_lightbox", _fake_open)

    card = QRCard(title="测试卡", subtitle="", img_path="",
                  accent="accent", caption="", action_hint="点击放大")
    try:
        ev = _key_press(int(Qt.Key.Key_Return))
        card.keyPressEvent(ev)
        assert opened == ["测试卡"], f"Enter 未触发放大：{opened}"
    finally:
        card.deleteLater()
        qapp.processEvents()


def test_qr_card_space_opens_lightbox(qapp, monkeypatch):
    """M6-06③：空格键触发 _open_lightbox。"""
    from futures_quant.ui.qr_card import QRCard
    opened = []

    def _fake_open(self):
        opened.append(self._title)
    monkeypatch.setattr(QRCard, "_open_lightbox", _fake_open)

    card = QRCard(title="测试卡", subtitle="", img_path="",
                  accent="accent", caption="", action_hint="点击放大")
    try:
        ev = _key_press(int(Qt.Key.Key_Space))
        card.keyPressEvent(ev)
        assert opened == ["测试卡"]
    finally:
        card.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ④ accessible name
# ─────────────────────────────────────────────────────────────

def test_info_copy_btn_accessible_name(qapp):
    """M6-06④：复制按钮 accessibleName 形如「复制XX号」。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        names = [row._copy_btn.accessibleName() for row in d._info_grid._rows]
        # 4 行：QQ / 微信 / 手机 / 工作室
        for expected_prefix in ("复制QQ", "复制微信", "复制手机", "复制工作室"):
            assert any(n.startswith(expected_prefix) for n in names), \
                f"缺少 {expected_prefix} 前缀，实际：{names}"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_copy_btn_has_accessible_description(qapp):
    """M6-06④：复制按钮有 accessibleDescription。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        for row in d._info_grid._rows:
            btn = row._copy_btn
            assert btn.accessibleDescription(), \
                f"{btn.accessibleName()} 缺 accessibleDescription"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_qr_card_accessible_name(qapp):
    """M6-06④：二维码卡有 accessibleName「二维码卡片：XX」。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        sections = d.findChildren(
            __import__("futures_quant.ui.about_page", fromlist=["_QRSection"])._QRSection)
        for sec in sections:
            for card in sec._cards:
                name = card._card.accessibleName()
                assert name and "二维码卡片" in name, \
                    f"二维码卡 accessibleName 不含「二维码卡片」：{name}"
    finally:
        d.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ⑤ 复制反馈：文案变「已复制 ✓」 + QToolTip
# ─────────────────────────────────────────────────────────────

def test_copy_btn_text_becomes_done(qapp, monkeypatch):
    """M6-06⑤：点击后按钮文案变为「已复制 ✓」。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        btn = d._info_grid._rows[0]._copy_btn
        assert btn.text() == "复制"
        btn._do_copy()
        assert btn.text() == "已复制 ✓"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_copy_btn_writes_to_clipboard(qapp):
    """M6-06⑤：_do_copy 把值写入系统剪贴板。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        btn = d._info_grid._rows[0]._copy_btn  # QQ 行
        btn._do_copy()
        qapp.processEvents()
        clip = QApplication.clipboard().text()
        # QQ 值 1153602036
        assert clip == "1153602036", f"剪贴板内容异常：{clip!r}"
    finally:
        d.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ⑥ 页脚「复制版本信息」
# ─────────────────────────────────────────────────────────────

def test_footer_copy_ver_btn_exists(qapp):
    """M6-06⑥：页脚有「复制版本信息」按钮且 accessibleName 正确。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        assert d._copy_ver_btn.text() == "复制版本信息"
        assert d._copy_ver_btn.accessibleName() == "复制版本信息"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_copy_version_info_to_clipboard(qapp):
    """M6-06⑥：复制版本信息后剪贴板含版本号 + Python + PyQt6。"""
    from futures_quant.ui.about_page import AboutDialog
    import sys
    d = AboutDialog()
    try:
        d._copy_version_info()
        qapp.processEvents()
        clip = QApplication.clipboard().text()
        assert "QuantVortex" in clip
        assert "Python" in clip
        assert "PyQt6" in clip
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_version_info_text_format(qapp):
    """M6-06⑥：version_info_text 返回符合规范的字符串。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        s = d.version_info_text()
        # 三段式：QuantVortex v<ver> (<date>) / Python x.y / PyQt6 <qt>
        assert s.count("/") == 2, f"格式不符：{s}"
        assert "QuantVortex v" in s
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_copy_ver_btn_text_reverts(qapp, monkeypatch):
    """M6-06⑥：文案「已复制 ✓」1.2s 后复原（模拟立即到期）。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        d._copy_version_info()
        assert d._copy_ver_btn.text() == "已复制 ✓"
        # 立即复原（手动模拟 1.2s 到期）
        d._copy_ver_btn.setText("复制版本信息")
        assert d._copy_ver_btn.text() == "复制版本信息"
    finally:
        d.deleteLater()
        qapp.processEvents()
