"""M7-02 修复 requests NameError + 导入规范 · 单元测试。

覆盖 spec DoD：
    ① 顶层 ``import requests`` 兜底为 None（缺失时不 NameError）
    ② requests=None 时测试按钮禁用 + tooltip「未安装 requests」
    ③ 源码无残留 ``requests.exceptions.Timeout`` 裸引用（走 llm_client.probe）
    ④ 源码无函数内重复 ``from PyQt6.QtWidgets import QMessageBox``
    ⑤ probe 结果分类：Timeout → 「请求超时」；cancelled → 「测试已取消」；
       no_key / no_requests / circuit_open 均命中 _TEST_ADVICE 表
    ⑥ AIConfigDialog 在 requests=None 下可无异常构造（不抛 NameError）
"""
from __future__ import annotations

import ast
import textwrap

import pytest

from PyQt6.QtWidgets import QApplication


# ---------- QApplication fixture ----------
@pytest.fixture(scope="module")
def qapp():
    """返回离屏 QApplication 单例；已有则复用。"""
    app = QApplication.instance() or QApplication([])
    yield app
    # 不主动 quit —— pytest 生命周期结束会自动回收


def _import_dialog_module():
    """延迟 import 并缓存，避免模块顶层 requests 判断在 import 时定死。"""
    import importlib
    mod = importlib.import_module("futures_quant.ui.ai_settings_dialog")
    return mod


# ---------- Test 1: 顶层 requests 声明（可为 None 或真实模块） ----------
def test_1_top_level_requests_safe():
    """模块顶层 requests 变量必须存在；未安装时置 None 而非抛 ImportError。"""
    mod = _import_dialog_module()
    assert hasattr(mod, "requests")
    # 装或未装都合法：断言它是 None 或真实模块（含 post 属性）
    assert mod.requests is None or hasattr(mod.requests, "post")


# ---------- Test 2: 源码无 requests.exceptions 裸引用 ----------
def test_2_no_bare_requests_exceptions_ref():
    """spec M7-02②：源码禁止出现 requests.exceptions.Timeout / _req.exceptions.* 等硬编码。"""
    import pathlib
    src = pathlib.Path("futures_quant/ui/ai_settings_dialog.py").read_text(encoding="utf-8")
    forbidden_patterns = [
        "requests.exceptions.Timeout",
        "requests.exceptions.ConnectionError",
        "requests.exceptions.HTTPError",
        "_req.exceptions.Timeout",
    ]
    for pat in forbidden_patterns:
        assert pat not in src, f"源码残留禁引用 {pat}（应走 llm_client.probe 分类）"


# ---------- Test 3: 源码无函数内重复 QMessageBox 导入 ----------
def test_3_no_dup_qmessagebox_import():
    """spec M7-02③：函数内不得重复 from PyQt6.QtWidgets import QMessageBox。"""
    import pathlib
    src = pathlib.Path("futures_quant/ui/ai_settings_dialog.py").read_text(encoding="utf-8")
    tree = ast.parse(textwrap.dedent(src))
    # 收集所有 ImportFrom(模块=PyQt6.QtWidgets, names 含 QMessageBox) 出现次数
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "PyQt6.QtWidgets":
            if any(a.name == "QMessageBox" for a in node.names):
                count += 1
    assert count == 1, f"QMessageBox 应仅顶层导入一次，实际 {count} 次"


# ---------- Test 4: requests=None 时按钮禁用 + tooltip ----------
def test_4_requests_missing_disables_test_btn(monkeypatch, qapp):
    """spec M7-02② DoD：requests=None 时测试按钮禁用且 tooltip 含「未安装 requests」。"""
    mod = _import_dialog_module()
    monkeypatch.setattr(mod, "requests", None)
    dialog = mod.AIConfigDialog()
    try:
        btn = dialog._test_btn
        assert btn is not None
        assert btn.isEnabled() is False
        tooltip = btn.toolTip()
        assert "requests" in tooltip
        assert "pip install requests" in tooltip
    finally:
        dialog.deleteLater()


# ---------- Test 5: _test_advice_for 覆盖全部异常分类 ----------
def test_5_advice_classification(monkeypatch, qapp):
    """spec DoD：mock probe 返回 Timeout 等分类，advice 命中对应文案。"""
    mod = _import_dialog_module()
    monkeypatch.setattr(mod, "requests", None)  # 允许无 requests 构造 dialog
    dialog = mod.AIConfigDialog()
    try:
        # 每种异常分类应能查到 advice
        cases = {
            "Timeout": "请求超时",
            "ConnectTimeout": "连接超时",
            "ConnectionError": "无法连接",
            "SSLError": "SSL",
            "401": "未授权",
            "404": "模型不存在",
            "503": "服务不可用",
            "circuit_open": "熔断",
            "no_key": "未配置 API 密钥",
            "no_requests": "未安装 requests",
        }
        for reason, keyword in cases.items():
            res = {"ok": False, "reason": reason, "elapsed_ms": 0,
                   "status": 0, "body": "", "attempts": 0,
                   "cancelled": False, "breaker_open": False,
                   "model": "-", "time": ""}
            advice = dialog._test_advice_for(res)
            assert keyword in advice, \
                f"reason={reason!r} 未含关键词 {keyword!r}：{advice!r}"

        # cancelled 优先于 reason
        res_cancel = {"ok": False, "cancelled": True, "reason": "Timeout"}
        assert dialog._test_advice_for(res_cancel) == "测试已取消。"

        # ok 分支
        res_ok = {"ok": True}
        assert "连接正常" in dialog._test_advice_for(res_ok)
    finally:
        dialog.deleteLater()


# ---------- Test 6: requests=None 下可无异常构造 dialog ----------
def test_6_no_nameerror_on_construct(monkeypatch, qapp):
    """spec 核心 DoD：mock requests.post 抛 Timeout 时 UI 显示「请求超时」而非 NameError。

    这里模拟「无 requests 环境」——AIConfigDialog 构造函数必须能完整跑完
    （旧代码在构造时若访问 requests.xxx 会 NameError）。
    """
    mod = _import_dialog_module()
    monkeypatch.setattr(mod, "requests", None)
    # 直接构造不抛异常即为通过
    dialog = mod.AIConfigDialog()
    try:
        # 触发一次 _on_test 走 no_requests 分支（不启动线程）
        dialog._on_test()
        # _on_test 会显示 test_result —— 断言 _test_summary 或 _test_advice 有内容
        # （具体是「未安装 requests」的建议）
        summary_text = dialog._test_summary.text()
        advice_text = dialog._test_advice.text()
        combined = f"{summary_text} | {advice_text}"
        assert "requests" in combined.lower() or "未安装" in combined, \
            f"_on_test 未走 no_requests 分支：{combined[:200]!r}"
    finally:
        dialog.deleteLater()


# ---------- Test 7: requests 可用时按钮启用 ----------
def test_7_requests_present_enables_btn(monkeypatch, qapp):
    """requests 可用时（未 monkeypatch 为 None）测试按钮应启用。"""
    mod = _import_dialog_module()
    # 恢复真实 requests（如可导入）；不可用则跳过
    try:
        import requests as _req  # noqa: F401
    except ImportError:
        pytest.skip("本环境未安装 requests")
    monkeypatch.setattr(mod, "requests", _req)
    dialog = mod.AIConfigDialog()
    try:
        assert dialog._test_btn.isEnabled() is True
    finally:
        dialog.deleteLater()
