"""M7-05 诊断页（第四分段）· 单元测试。

覆盖 spec DoD：
    ① SDK 版本 / 端点 / 生效参数 / 密钥来源与指纹 / requests 可用性 /
       环境变量注入 / 降级状态
    ② 复制诊断信息 → 剪贴板（不含密钥明文）
    ③ 打开日志目录
    ④ 与 M1-09 系统诊断联动跳转
    ⑤ 复制内容中**不含密钥明文**（grep 断言）
    ⑥ 无密钥时显示「未配置 → AI 功能将降级为本地规则」
"""
from __future__ import annotations

import os
import re

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_dialog():
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    return AIConfigDialog()


# ---------- Test 1: _key_fingerprint 空密钥 → 「未配置」 ----------
def test_1_fingerprint_empty():
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    assert AIConfigDialog._key_fingerprint(None) == "未配置"
    assert AIConfigDialog._key_fingerprint("") == "未配置"


# ---------- Test 2: _key_fingerprint 只含末 4 位（不含全文） ----------
def test_2_fingerprint_truncated():
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    result = AIConfigDialog._key_fingerprint("sk-abcdefg1234567890")
    # 只保留末 4 位
    assert "1234567890" not in result  # 不含正文
    assert "7890" in result  # 末 4 位保留
    assert result.startswith("…")


# ---------- Test 3: _key_fingerprint 短密钥也安全 ----------
def test_3_fingerprint_short_key():
    """短密钥（<4 位）不应泄露原文。"""
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    result = AIConfigDialog._key_fingerprint("abc")
    # abc 只有 3 位，切片 [-4:] 得完整 "abc"——但至少要加 … 前缀
    assert "…" in result or result == "未配置"


# ---------- Test 4: _diag_data 返回 8 个字段 ----------
def test_4_diag_data_has_8_fields(qapp):
    d = _make_dialog()
    try:
        data = d._diag_data()
        assert isinstance(data, dict)
        expected_keys = {
            "SDK 版本", "requests 可用性", "端点", "生效参数",
            "密钥来源", "密钥指纹", "环境变量注入", "降级状态",
        }
        assert set(data.keys()) == expected_keys
        # 每项都非空
        for k, v in data.items():
            assert isinstance(v, str)
            assert v, f"{k} 值不应为空"
    finally:
        d.deleteLater()


# ---------- Test 5: 无密钥时降级状态明确 ----------
def test_5_diag_data_no_key_downgrade(qapp, monkeypatch):
    """无密钥场景：密钥指纹=未配置 + 降级状态显示「未配置 → 本地规则」。"""
    d = _make_dialog()
    try:
        # 确保密钥清空
        from futures_quant.ai.config import get_ai_config
        ai_cfg = get_ai_config(d._config)
        ai_cfg.set_api_key(None)
        data = d._diag_data()
        assert data["密钥指纹"] == "未配置"
        assert "未配置" in data["密钥来源"]
        assert "降级为本地规则" in data["降级状态"]
    finally:
        d.deleteLater()


# ---------- Test 6: 环境变量未设置时诊断正确显示 ----------
def test_6_diag_data_env_not_set(qapp, monkeypatch):
    d = _make_dialog()
    try:
        monkeypatch.delenv("QV_AGNES_API_KEY", raising=False)
        data = d._diag_data()
        assert "未设置" in data["环境变量注入"]
        assert "QV_AGNES_API_KEY" in data["环境变量注入"]
    finally:
        d.deleteLater()


# ---------- Test 7: 环境变量已设置时诊断正确显示 ----------
def test_7_diag_data_env_set(qapp, monkeypatch):
    d = _make_dialog()
    try:
        monkeypatch.setenv("QV_AGNES_API_KEY", "sk-test-env-key-1234567890")
        data = d._diag_data()
        assert "已设置" in data["环境变量注入"]
        assert "QV_AGNES_API_KEY" in data["环境变量注入"]
    finally:
        d.deleteLater()


# ---------- Test 8: 端点固定显示 AGNES_API_BASE ----------
def test_8_diag_data_endpoint(qapp):
    from futures_quant.ui.ai_settings_dialog import AGNES_API_BASE
    d = _make_dialog()
    try:
        data = d._diag_data()
        assert data["端点"] == AGNES_API_BASE
    finally:
        d.deleteLater()


# ---------- Test 9: 生效参数包含 4 项 ----------
def test_9_diag_data_params(qapp):
    d = _make_dialog()
    try:
        data = d._diag_data()
        params = data["生效参数"]
        # 4 段用 " / " 分隔：model / tokens / 温度 / 超时
        assert "tokens" in params
        assert "温度" in params
        assert "超时" in params
    finally:
        d.deleteLater()


# ---------- Test 10: _refresh_diag_info 更新所有 diag_labels ----------
def test_10_refresh_diag_info_updates_labels(qapp):
    d = _make_dialog()
    try:
        d._refresh_diag_info()
        # 8 个标签都应存在且有文本
        for name in ["SDK 版本", "端点", "密钥指纹", "降级状态"]:
            lbl = d._diag_labels.get(name)
            assert lbl is not None, f"标签 {name} 不存在"
            assert lbl.text(), f"标签 {name} 文本为空"
    finally:
        d.deleteLater()


# ---------- Test 11: _on_copy_diag 复制不含密钥明文（DoD 硬约束） ----------
def test_11_copy_diag_no_key_plaintext(qapp, monkeypatch):
    """**关键契约**：复制内容中不得出现密钥正文（连续 ≥20 字符主体）。"""
    d = _make_dialog()
    try:
        # 设置一个长密钥（20+ 字符主体，能触发扫描铁律）
        from futures_quant.ai.config import get_ai_config
        ai_cfg = get_ai_config(d._config)
        secret_key = "sk-TEST-FIXTURE-NOT-REAL-00000000000000"  # secret-scan: allow
        ai_cfg.set_api_key(secret_key)

        # 捕获剪贴板内容
        captured = {}
        class _FakeClipboard:
            def setText(self, text):
                captured["text"] = text
        from futures_quant.ui import ai_settings_dialog as mod
        monkeypatch.setattr(mod.QApplication, "clipboard",
                            staticmethod(lambda: _FakeClipboard()))

        # 拦截 Toast 避免动画定时器
        def fake_toast(parent, message, level="info", duration=2500, **kwargs):
            class _Noop:
                def present(self):
                    pass
            return _Noop()
        monkeypatch.setattr(mod, "Toast", fake_toast)

        d._on_copy_diag()

        text = captured.get("text", "")
        # 1) 复制内容存在
        assert "诊断信息" in text
        # 2) **不含密钥正文**（去除「sk-」前缀后的 20+ 字符主体不得出现）
        key_body = secret_key[3:]  # "THISISASECRETKEYFORTEST1234567890abcdef"
        assert key_body not in text, "复制内容泄露了密钥正文"
        # 3) 完整密钥原文不出现
        assert secret_key not in text
        # 4) 允许末 4 位（这是 spec 明确的脱敏格式）
        assert "…cdef" in text or secret_key[-4:] in text
    finally:
        d.deleteLater()


# ---------- Test 12: _on_open_log_dir 创建 logs/ 目录（不崩溃） ----------
def test_12_open_log_dir_creates_dir(qapp, monkeypatch, tmp_path):
    d = _make_dialog()
    try:
        from futures_quant.ui import ai_settings_dialog as mod
        # 拦截 QDesktopServices.openUrl 避免打开系统文件浏览器
        called = {"count": 0}
        def fake_open(*args, **kwargs):
            called["count"] += 1
        monkeypatch.setattr(mod.QDesktopServices, "openUrl",
                            staticmethod(fake_open))
        d._on_open_log_dir()
        # 目录被创建（在 cwd 下）
        import os
        log_dir = os.path.join(os.getcwd(), "logs")
        assert os.path.isdir(log_dir)
        # 系统浏览器被调用
        assert called["count"] >= 1
    finally:
        d.deleteLater()


# ---------- Test 13: system_diag_requested 信号存在且可发出 ----------
def test_13_system_diag_signal_emits(qapp):
    """M7-05④：信号可被发出（联动跳转基础）。"""
    d = _make_dialog()
    try:
        # 断言信号存在
        assert hasattr(d, "system_diag_requested")
        # 拦截 QMessageBox.information 避免弹窗
        from futures_quant.ui import ai_settings_dialog as mod
        from PyQt6.QtWidgets import QMessageBox
        def fake_info(*args, **kwargs):
            return QMessageBox.StandardButton.Ok
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(fake_info))
        try:
            # 触发信号（无 receiver 时走兜底分支）
            d.system_diag_requested.emit()
        finally:
            monkeypatch.undo()
    finally:
        d.deleteLater()


# ---------- Test 14: 熔断打开时降级状态显示「熔断打开中」 ----------
def test_14_diag_data_circuit_open(qapp, monkeypatch):
    """api_status 熔断打开 → 降级状态显示熔断提示。"""
    d = _make_dialog()
    try:
        from futures_quant.ui import ai_settings_dialog as mod
        # monkeypatch llm_client.api_status 返回熔断打开状态
        def fake_api_status():
            return {
                "usable": False,
                "configured": True,
                "circuit": {"open": True, "reason": "5 consecutive failures"},
            }
        monkeypatch.setattr("futures_quant.ai.llm_client.api_status", fake_api_status)
        data = d._diag_data()
        assert "熔断打开中" in data["降级状态"]
    finally:
        d.deleteLater()


# ---------- Test 15: 复制内容 grep 断言无 20+ 字符连续密钥主体 ----------
def test_15_copy_diag_regex_no_long_secret(qapp, monkeypatch):
    """**安全铁律**：连续主体 ≥20 字符必须视为密钥，不能出现在复制内容中。"""
    d = _make_dialog()
    try:
        from futures_quant.ai.config import get_ai_config
        ai_cfg = get_ai_config(d._config)
        secret_key = "sk-" + "A" * 60  # 极长密钥（60+ 字符主体）

        ai_cfg.set_api_key(secret_key)

        captured = {}
        class _FakeClipboard:
            def setText(self, text):
                captured["text"] = text
        from futures_quant.ui import ai_settings_dialog as mod
        monkeypatch.setattr(mod.QApplication, "clipboard",
                            staticmethod(lambda: _FakeClipboard()))
        def fake_toast(parent, message, level="info", duration=2500, **kwargs):
            class _Noop:
                def present(self):
                    pass
            return _Noop()
        monkeypatch.setattr(mod, "Toast", fake_toast)

        d._on_copy_diag()

        text = captured.get("text", "")
        # 连续 20 个相同字符不得出现（密钥主体 60 个 A 必须被脱敏）
        assert not re.search(r"A{20,}", text), \
            f"复制内容含连续 20+ 字符密钥主体：{text!r}"
    finally:
        d.deleteLater()
