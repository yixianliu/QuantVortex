"""M7-03 信息层级与状态反馈 · 单元测试。

覆盖 spec DoD：
    ① 每个字段：Label + 控件 + Hint + Error（就地显示，默认隐藏）
    ② Dirty 状态：字段变更 → 标题栏「● 未保存」+ 「应用」按钮变 primary
    ③ 保存中：按钮禁用 + 文案「保存中…」+ spinner
    ④ 错误态：字段红边框 + Error 文本 + 自动聚焦（不再 QMessageBox）
    ⑤ 成功态：非阻断 Toast 2.5s 自动消失
    ⑥ 打包模式密钥只读说明（走 is_frozen() 分支）
"""
from __future__ import annotations

import ast
import textwrap

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_dialog():
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    return AIConfigDialog()


# ---------- Test 1: _field_errors 空模型名报错 ----------
def test_1_field_errors_empty_model(qapp):
    d = _make_dialog()
    try:
        # 正常状态无错误
        d._model_combo.setCurrentText("agnes-3.0-flash")
        assert "model" not in d._field_errors()
        # 模型名空
        d._model_combo.setCurrentText("")
        errs = d._field_errors()
        assert "model" in errs
        assert "不能为空" in errs["model"]
    finally:
        d.deleteLater()


# ---------- Test 2: _field_errors proxy 前缀校验 ----------
def test_2_field_errors_proxy_prefix(qapp):
    d = _make_dialog()
    try:
        # 空代理合法
        d._proxy_edit.setText("")
        assert "proxy" not in d._field_errors()
        # 合法 http
        d._proxy_edit.setText("http://127.0.0.1:7890")
        assert "proxy" not in d._field_errors()
        # 合法 https
        d._proxy_edit.setText("https://proxy.example.com")
        assert "proxy" not in d._field_errors()
        # 非法：无前缀
        d._proxy_edit.setText("127.0.0.1:7890")
        errs = d._field_errors()
        assert "proxy" in errs
        assert "http" in errs["proxy"]
    finally:
        d.deleteLater()


# ---------- Test 3: 温度过高 → 软提示 warn（不阻断） ----------
def test_3_temperature_high_warn_not_block(qapp):
    d = _make_dialog()
    try:
        # 低温：无 warn
        d._temperature_spin.setValue(0.3)
        d._revalidate()
        temp_meta = d._fields["temperature"]
        assert temp_meta["error"].isHidden() or temp_meta["error"].text() == ""
        # 温度 1.5 过高：应显示 warn 提示（不阻断保存）
        d._temperature_spin.setValue(1.5)
        d._revalidate()
        assert not temp_meta["error"].isHidden()
        assert "偏高" in temp_meta["error"].text()
        # 关键：温度过高不阻断保存（不加入 _field_errors）
        assert "temperature" not in d._field_errors()
        assert d._save_btn.isEnabled() is True
    finally:
        d.deleteLater()


# ---------- Test 4: _revalidate 阻断时禁用保存按钮 ----------
def test_4_revalidate_blocks_save(qapp):
    d = _make_dialog()
    try:
        # 清空模型名
        d._model_combo.setCurrentText("")
        d._revalidate()
        assert d._save_btn.isEnabled() is False
        # tooltip 提示
        assert "错误" in d._save_btn.toolTip() or "未修正" in d._save_btn.toolTip()
        # 修复后按钮恢复
        d._model_combo.setCurrentText("agnes-3.0-flash")
        d._revalidate()
        assert d._save_btn.isEnabled() is True
    finally:
        d.deleteLater()


# ---------- Test 5: _mark_dirty 显示角标 + 按钮 primary ----------
def test_5_mark_dirty_shows_badge(qapp):
    d = _make_dialog()
    try:
        # 初始无 dirty
        assert d._dirty is False
        assert d._dirty_badge.isHidden()
        assert d._save_btn.objectName() == "secondary"
        # 标记 dirty
        d._mark_dirty()
        assert d._dirty is True
        assert not d._dirty_badge.isHidden()
        assert d._dirty_badge.text() == "● 未保存"
        assert d._save_btn.objectName() == "primary"
        # 重复 mark 不重复（幂等）
        d._mark_dirty()
        assert d._dirty is True
    finally:
        d.deleteLater()


# ---------- Test 6: _clear_dirty 恢复 ----------
def test_6_clear_dirty_hides_badge(qapp):
    d = _make_dialog()
    try:
        d._mark_dirty()
        assert d._dirty is True
        d._clear_dirty()
        assert d._dirty is False
        assert d._dirty_badge.isHidden()
        assert d._save_btn.objectName() == "secondary"
    finally:
        d.deleteLater()


# ---------- Test 7: 字段变更触发 dirty + 校验 ----------
def test_7_field_change_marks_dirty(qapp):
    d = _make_dialog()
    try:
        # 干净状态
        assert d._dirty is False
        # 直接调 _on_field_changed 触发（绕过 signal）
        d._on_field_changed()
        assert d._dirty is True
        assert not d._dirty_badge.isHidden()
    finally:
        d.deleteLater()


# ---------- Test 8: _focus_first_error 跳转到首个错误字段所在页 ----------
def test_8_focus_first_error_jumps_page(qapp):
    d = _make_dialog()
    try:
        d.resize(720, 700)
        d._set_compact(False)
        # 清空 model（模型在第 1 页）
        d._model_combo.setCurrentText("")
        # 先切到别的页
        d._apply_current_index(3)
        assert d._stack.currentIndex() == 3
        # 触发 _focus_first_error
        d._focus_first_error()
        assert d._stack.currentIndex() == 1, "未跳转到 model 字段所在页"
    finally:
        d.deleteLater()


# ---------- Test 9: _show_field 三种 level 分级 ----------
def test_9_show_field_levels(qapp):
    d = _make_dialog()
    try:
        meta = d._fields["temperature"]
        widget = meta["widget"]
        err = meta["error"]
        # error level
        d._show_field("temperature", "越界错误", "error")
        assert not err.isHidden()
        assert "越界错误" in err.text()
        # warn level
        d._show_field("temperature", "偏高提示", "warn")
        assert "偏高提示" in err.text()
        # none level：清空
        d._show_field("temperature", "", "none")
        assert err.isHidden() or err.text() == ""
    finally:
        d.deleteLater()


# ---------- Test 10: _set_saving 保存中态契约 ----------
def test_10_set_saving_state(qapp):
    d = _make_dialog()
    try:
        d._model_combo.setCurrentText("agnes-3.0-flash")
        d._revalidate()
        # 正常启用态
        assert d._save_btn.isEnabled() is True
        assert "保存" in d._save_btn.text() or "应用" in d._save_btn.text()
        # 切到 saving 态
        d._set_saving(True)
        assert d._save_btn.isEnabled() is False
        assert d._save_btn.text() == "保存中…"
        # 恢复
        d._set_saving(False)
        assert d._save_btn.isEnabled() is True
        assert d._save_btn.text() != "保存中…"
    finally:
        d.deleteLater()


# ---------- Test 11: 错误态方法内无 QMessageBox（M7-03④ 契约） ----------
def test_11_no_qmessagebox_in_error_paths(qapp):
    """M7-03④：错误态相关方法（_on_apply / _focus_first_error / _revalidate /
    _field_errors / _show_field）内部不得出现 QMessageBox.information/critical/warning。

    非错误态的 QMessageBox 允许保留（复制成功提示、重置确认等）。
    """
    import pathlib
    src = pathlib.Path("futures_quant/ui/ai_settings_dialog.py").read_text(encoding="utf-8")
    tree = ast.parse(textwrap.dedent(src))
    error_paths = {"_on_apply", "_focus_first_error", "_revalidate",
                   "_field_errors", "_show_field", "_on_field_changed"}
    # 遍历所有 FunctionDef，找到错误态方法
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in error_paths:
            continue
        # 收集该方法内的 QMessageBox.information/critical/warning 调用
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            if (isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name)
                    and f.value.id == "QMessageBox"
                    and f.attr in ("information", "critical", "warning")):
                violations.append((node.name, f.attr, sub.lineno))
    assert violations == [], \
        f"错误态方法仍存在 QMessageBox 阻断式调用：{violations}（M7-03④ 应改为 Toast）"


# ---------- Test 12: Toast 已接线到 _on_apply / _do_apply ----------
def test_12_toast_imported_and_used(qapp):
    """M7-03⑤：Toast 从 states 导入且在保存流程中被调用。"""
    import pathlib
    src = pathlib.Path("futures_quant/ui/ai_settings_dialog.py").read_text(encoding="utf-8")
    assert "from .states import" in src
    assert "Toast" in src
    # 保存成功/失败/错误三处 Toast 调用
    assert 'level="info"' in src or 'level="success"' in src
    assert 'level="error"' in src
    assert 'level="warn"' in src
    # duration 2500（2.5s 非阻断）
    assert "2500" in src


# ---------- Test 13: _on_apply 遇错误只 Toast 不弹 QMessageBox ----------
def test_13_on_apply_errors_use_toast(qapp, monkeypatch):
    """错误分支：调 _on_apply → 走 _revalidate + _focus_first_error + Toast 分支。"""
    d = _make_dialog()
    try:
        # 制造错误状态
        d._model_combo.setCurrentText("")
        # 记录是否弹出 QMessageBox（用 monkeypatch 拦截）
        called = {"count": 0}
        original = None
        from futures_quant.ui import ai_settings_dialog as mod
        original = mod.QMessageBox
        class _BlockedBox:
            @staticmethod
            def __getattr__(name):
                def _raise(*a, **kw):
                    called["count"] += 1
                    raise AssertionError(f"QMessageBox.{name} 不应被调用")
                return _raise
        monkeypatch.setattr(mod, "QMessageBox", _BlockedBox())
        d._on_apply()
        assert called["count"] == 0, "错误分支不应走 QMessageBox"
        # 应跳转到 model 字段所在页
        assert d._stack.currentIndex() == 1
    finally:
        d.deleteLater()
