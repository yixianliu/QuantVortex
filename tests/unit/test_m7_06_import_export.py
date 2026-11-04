"""M7-06 配置导入 / 导出 / 重置 · 单元测试。

覆盖 spec DoD：
    ① 导出：JSON 含 schema + version + exported_at + config（不含密钥）
    ② 导入：schema 版本校验 + 字段类型/范围校验 + 明确错误
    ③ 重置：二次确认对话框 + 密钥清空 + 参数回默认
    ④ 恢复默认不弹阻断式错误对话框（Toast 非阻断）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_dialog():
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    return AIConfigDialog()


# ---------- Test 1: EXPORT_SCHEMA / EXPORT_VERSION 常量契约 ----------
def test_1_export_constants_contract():
    from futures_quant.ui.ai_settings_dialog import (
        EXPORT_SCHEMA, EXPORT_VERSION, _IMPORT_SPEC,
    )
    assert EXPORT_SCHEMA == "quantvortex.ai-config"
    assert EXPORT_VERSION == 1
    # _IMPORT_SPEC 覆盖 10 个字段
    expected_keys = {"model", "timeout", "max_tokens", "temperature",
                     "retry", "backoff_base", "concurrency",
                     "proxy", "redact_log", "watchdog"}
    assert set(_IMPORT_SPEC.keys()) == expected_keys
    # 每个 spec 是 (type, range) 元组
    for k, spec in _IMPORT_SPEC.items():
        assert isinstance(spec, tuple) and len(spec) == 2, f"{k} spec 格式错误"
        typ, rng = spec
        assert isinstance(typ, type)
        assert rng is None or (isinstance(rng, tuple) and len(rng) == 2)


# ---------- Test 2: _current_config_dict 不含 api_key（DoD 硬约束） ----------
def test_2_current_config_dict_excludes_api_key(qapp):
    """安全契约：导出字典不得包含 api_key 字段。"""
    d = _make_dialog()
    try:
        cfg = d._current_config_dict()
        assert isinstance(cfg, dict)
        assert "api_key" not in cfg
        assert "endpoint" not in cfg  # 端点固定，不导出
        # 10 个字段全部存在
        expected = {"model", "timeout", "max_tokens", "temperature",
                    "retry", "backoff_base", "concurrency",
                    "proxy", "redact_log", "watchdog"}
        assert set(cfg.keys()) == expected
    finally:
        d.deleteLater()


# ---------- Test 3: _validate_import 根节点非 dict ----------
def test_3_validate_import_non_dict(qapp):
    d = _make_dialog()
    try:
        assert d._validate_import(None) is not None
        assert d._validate_import([]) is not None
        assert d._validate_import("string") is not None
        assert "对象" in d._validate_import(None)
    finally:
        d.deleteLater()


# ---------- Test 4: _validate_import schema 不匹配 ----------
def test_4_validate_import_schema_mismatch(qapp):
    d = _make_dialog()
    try:
        err = d._validate_import({"schema": "wrong.schema", "version": 1,
                                  "config": {}})
        assert err is not None
        assert "schema" in err.lower()
    finally:
        d.deleteLater()


# ---------- Test 5: _validate_import version 过大 ----------
def test_5_validate_import_version_too_high(qapp):
    d = _make_dialog()
    try:
        err = d._validate_import({"schema": "quantvortex.ai-config",
                                  "version": 999, "config": {}})
        assert err is not None
        assert "版本" in err or "version" in err.lower()
    finally:
        d.deleteLater()


# ---------- Test 6: _validate_import 缺 config ----------
def test_6_validate_import_missing_config(qapp):
    d = _make_dialog()
    try:
        err = d._validate_import({"schema": "quantvortex.ai-config",
                                  "version": 1})
        assert err is not None
        assert "config" in err
    finally:
        d.deleteLater()


# ---------- Test 7: _validate_import 字段类型错误 ----------
def test_7_validate_import_type_error(qapp):
    d = _make_dialog()
    try:
        # timeout 应为 int 给 float
        err = d._validate_import({"schema": "quantvortex.ai-config",
                                  "version": 1,
                                  "config": {"timeout": 30.5}})
        assert err is not None
        assert "timeout" in err and "类型" in err
    finally:
        d.deleteLater()


# ---------- Test 8: _validate_import 字段超范围 ----------
def test_8_validate_import_range_error(qapp):
    d = _make_dialog()
    try:
        # timeout 越上界
        err = d._validate_import({"schema": "quantvortex.ai-config",
                                  "version": 1,
                                  "config": {"timeout": 500}})
        assert err is not None
        assert "timeout" in err and "范围" in err
        # max_tokens 越下界
        err = d._validate_import({"schema": "quantvortex.ai-config",
                                  "version": 1,
                                  "config": {"max_tokens": 100}})
        assert err is not None
        assert "max_tokens" in err
    finally:
        d.deleteLater()


# ---------- Test 9: _validate_import bool 判定（bool 是 int 子类陷阱） ----------
def test_9_validate_import_bool_not_int(qapp):
    """bool 是 int 子类：如果 spec 声明 int 传入 True/False 应报错。"""
    d = _make_dialog()
    try:
        # redact_log 是 bool 声明，传 True 合法
        assert d._validate_import({"schema": "quantvortex.ai-config",
                                   "version": 1,
                                   "config": {"redact_log": True}}) is None
        # timeout 是 int 声明，传 True（bool 会被误判为 int）应报错
        err = d._validate_import({"schema": "quantvortex.ai-config",
                                  "version": 1,
                                  "config": {"timeout": True}})
        assert err is not None, "bool 传入 int 字段应被识别为类型错误"
    finally:
        d.deleteLater()


# ---------- Test 10: _validate_import 空 model 报错 ----------
def test_10_validate_import_empty_model(qapp):
    d = _make_dialog()
    try:
        err = d._validate_import({"schema": "quantvortex.ai-config",
                                  "version": 1,
                                  "config": {"model": "   "}})
        assert err is not None
        assert "model" in err and "空" in err
    finally:
        d.deleteLater()


# ---------- Test 11: _validate_import 合法数据返回 None ----------
def test_11_validate_import_valid_data(qapp):
    d = _make_dialog()
    try:
        data = {
            "schema": "quantvortex.ai-config",
            "version": 1,
            "config": {
                "model": "agnes-3.0-flash",
                "timeout": 30,
                "max_tokens": 2048,
                "temperature": 0.3,
                "retry": 2,
                "backoff_base": 1.0,
                "concurrency": 2,
                "proxy": "",
                "redact_log": True,
                "watchdog": True,
            },
        }
        assert d._validate_import(data) is None
    finally:
        d.deleteLater()


# ---------- Test 12: _validate_import 未知键忽略（向前兼容） ----------
def test_12_validate_import_unknown_key_ignored(qapp):
    """spec：未知键忽略，保证向前兼容。"""
    d = _make_dialog()
    try:
        data = {
            "schema": "quantvortex.ai-config",
            "version": 1,
            "config": {
                "model": "agnes-3.0-flash",
                "future_field": "unknown value",  # 前向兼容
                "totally_unknown": 12345,
            },
        }
        assert d._validate_import(data) is None
    finally:
        d.deleteLater()


# ---------- Test 13: _apply_imported 应用合法配置 ----------
def test_13_apply_imported_updates_widgets(qapp):
    d = _make_dialog()
    try:
        cfg = {
            "model": "custom-model",
            "timeout": 45,
            "max_tokens": 4096,
            "temperature": 0.7,
            "retry": 3,
            "backoff_base": 2.0,
            "concurrency": 4,
            "proxy": "http://localhost:7890",
            "redact_log": False,
            "watchdog": False,
        }
        d._apply_imported(cfg)
        # 断言各控件被更新
        assert d._model_combo.currentText() == "custom-model"
        assert d._timeout_spin.value() == 45
        assert d._max_tokens_spin.value() == 4096
        assert abs(d._temperature_spin.value() - 0.7) < 1e-6
        assert d._retry_spin.value() == 3
        assert abs(d._backoff_spin.value() - 2.0) < 1e-6
        assert d._concurrency_spin.value() == 4
        assert d._proxy_edit.text() == "http://localhost:7890"
        assert d._redact_check.isChecked() is False
        assert d._watchdog_check.isChecked() is False
    finally:
        d.deleteLater()


# ---------- Test 14: _on_reset 拒绝（No）不修改配置 ----------
def test_14_on_reset_cancel_no_change(qapp, monkeypatch):
    """M7-06③：QMessageBox.question 返回 No 时不修改任何状态。"""
    d = _make_dialog()
    try:
        # 先记录当前模型
        original_model = d._model_combo.currentText()
        original_timeout = d._timeout_spin.value()

        # 让 QMessageBox.question 返回 No
        from futures_quant.ui import ai_settings_dialog as mod
        from PyQt6.QtWidgets import QMessageBox
        def fake_question(*args, **kwargs):
            return QMessageBox.StandardButton.No
        monkeypatch.setattr(mod.QMessageBox, "question", staticmethod(fake_question))
        d._on_reset()
        # 状态未变
        assert d._model_combo.currentText() == original_model
        assert d._timeout_spin.value() == original_timeout
    finally:
        d.deleteLater()


# ---------- Test 15: _on_reset 确认（Yes）执行重置 ----------
def test_15_on_reset_confirm_executes_reset(qapp, monkeypatch):
    """M7-06③：QMessageBox.question 返回 Yes 时走重置分支。"""
    d = _make_dialog()
    try:
        # 记录 dirty 标记会被清除
        d._mark_dirty()
        assert d._dirty is True

        # 让 QMessageBox.question 返回 Yes
        from futures_quant.ui import ai_settings_dialog as mod
        from PyQt6.QtWidgets import QMessageBox
        def fake_question(*args, **kwargs):
            return QMessageBox.StandardButton.Yes
        monkeypatch.setattr(mod.QMessageBox, "question", staticmethod(fake_question))

        # 拦截 Toast 避免弹窗副作用（present 可能启动动画定时器）
        called_toasts = []
        def fake_toast(parent, message, level="info", duration=2500, **kwargs):
            called_toasts.append({"message": message, "level": level,
                                  "duration": duration})
            class _Noop:
                def present(self):
                    pass
            return _Noop()
        monkeypatch.setattr(mod, "Toast", fake_toast)

        d._on_reset()
        # 重置后 dirty 应被清除
        assert d._dirty is False
        # 应有 Toast 提示
        assert len(called_toasts) >= 1
        toast = called_toasts[0]
        assert toast.get("level") == "info"
        assert "恢复默认" in toast.get("message", "")
    finally:
        d.deleteLater()


# ---------- Test 16: 导出文件不含 api_key（端到端） ----------
def test_16_export_no_api_key_e2e(qapp, monkeypatch, tmp_path):
    """端到端：模拟用户点导出 → 生成的 JSON 文件不含 api_key。"""
    d = _make_dialog()
    try:
        from futures_quant.ui import ai_settings_dialog as mod
        from PyQt6.QtWidgets import QMessageBox

        out_file = tmp_path / "exported.json"
        def fake_save(*args, **kwargs):
            return (str(out_file), "*.json")
        def fake_info(*args, **kwargs):
            return QMessageBox.StandardButton.Ok
        monkeypatch.setattr(mod.QFileDialog, "getSaveFileName",
                            staticmethod(fake_save))
        monkeypatch.setattr(mod.QMessageBox, "information",
                            staticmethod(fake_info))

        d._on_export_config()

        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        # 关键契约：不含 api_key
        assert "api_key" not in data
        assert "api_key" not in data.get("config", {})
        # 结构完整
        assert data["schema"] == "quantvortex.ai-config"
        assert data["version"] == 1
        assert "exported_at" in data
        assert "config" in data
    finally:
        d.deleteLater()


# ---------- Test 17: 导入非法文件走 Toast 错误分支（不 crash） ----------
def test_17_import_bad_file_no_crash(qapp, monkeypatch, tmp_path):
    """非法 JSON 文件 → Toast 错误提示，不抛异常。"""
    d = _make_dialog()
    try:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not a json {{{", encoding="utf-8")

        from futures_quant.ui import ai_settings_dialog as mod
        def fake_open(*args, **kwargs):
            return (str(bad_file), "*.json")
        monkeypatch.setattr(mod.QFileDialog, "getOpenFileName",
                            staticmethod(fake_open))

        called_toasts = []
        def fake_toast(parent, message, level="info", duration=2500, **kwargs):
            called_toasts.append({"message": message, "level": level,
                                  "duration": duration})
            class _Noop:
                def present(self):
                    pass
            return _Noop()
        monkeypatch.setattr(mod, "Toast", fake_toast)

        d._on_import_config()

        assert len(called_toasts) >= 1
        assert called_toasts[0].get("level") == "error"
        assert "导入失败" in called_toasts[0].get("message", "")
    finally:
        d.deleteLater()


# ---------- Test 18: 导入合法 JSON → 应用 + Toast 提示 ----------
def test_18_import_valid_json_applies(qapp, monkeypatch, tmp_path):
    """合法 JSON → 字段被应用 + 跳到高级页 + info Toast。"""
    d = _make_dialog()
    try:
        from futures_quant.ui import ai_settings_dialog as mod
        import futures_quant.ui.ai_settings_dialog as ad

        # 构造合法导出文件
        valid_data = {
            "schema": "quantvortex.ai-config",
            "version": 1,
            "exported_at": "2026-01-01T00:00:00",
            "config": {
                "model": "imported-model",
                "timeout": 60,
                "max_tokens": 4096,
                "temperature": 0.5,
                "retry": 3,
                "backoff_base": 1.5,
                "concurrency": 3,
                "proxy": "",
                "redact_log": False,
                "watchdog": True,
            },
        }
        valid_file = tmp_path / "valid.json"
        valid_file.write_text(json.dumps(valid_data, ensure_ascii=False),
                              encoding="utf-8")

        def fake_open(*args, **kwargs):
            return (str(valid_file), "*.json")
        monkeypatch.setattr(mod.QFileDialog, "getOpenFileName",
                            staticmethod(fake_open))

        called_toasts = []
        def fake_toast(parent, message, level="info", duration=2500, **kwargs):
            called_toasts.append({"message": message, "level": level,
                                  "duration": duration})
            class _Noop:
                def present(self):
                    pass
            return _Noop()
        monkeypatch.setattr(mod, "Toast", fake_toast)

        d._set_compact(False)  # 确保 wide 模式（stack.currentIndex 有效）
        d._on_import_config()

        # 控件被应用
        assert d._model_combo.currentText() == "imported-model"
        assert d._timeout_spin.value() == 60
        assert d._max_tokens_spin.value() == 4096
        assert abs(d._temperature_spin.value() - 0.5) < 1e-6
        # 跳到高级页（index=2）
        assert d._stack.currentIndex() == 2
        # info Toast 出现
        assert any(t.get("level") == "info" for t in called_toasts)
    finally:
        d.deleteLater()
