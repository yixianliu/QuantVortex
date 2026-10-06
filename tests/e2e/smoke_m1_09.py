"""M1-09 系统诊断面板 end-to-end smoke 测试。

覆盖:
    1. run_all_checks 无 Qt 环境可用，返回 8 项
    2. render_report 含 8 项检查 + 汇总
    3. DiagnosticsDialog 可无头构造（QT_QPA_PLATFORM=offscreen）
    4. DiagnosticsDialog.run_all_checks_sync 返回 8 项且渲染到 _last_checks
    5. MainWindow._show_diagnostics 方法存在且菜单项「系统诊断…」可点击
    6. 8 项检查中，Python 版本 / 数据目录 / 磁盘 / 密钥 四项在合理 ctx 下为绿
    7. 报告不含密钥全文（脱敏）
    8. DiagnosticsDialog.closeEvent 可安全关闭（不挂起）
"""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from futures_quant.ui.diagnostics_dialog import (  # noqa: E402
    CHECK_NAMES, OK, WARN, FAIL,
    DiagnosticsDialog,
    run_all_checks,
    render_report,
)


_ctx = {
    "data_dir": os.path.join(ROOT, "data"),
    "disk_dir": ROOT,
    "data_feed": None,
    "api_key_fingerprint": "sk-abc12345",
    "qr_gate_enabled": False,
}


def _setup_qt():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


_app = None


# 1. 无 Qt 环境的核心函数
def test_01_core_functions():
    checks = run_all_checks(_ctx)
    assert len(checks) == 8
    assert {c["name"] for c in checks} == set(CHECK_NAMES)
    for c in checks:
        assert c["status"] in {OK, WARN, FAIL}


# 2. 报告结构
def test_02_report_structure():
    checks = run_all_checks(_ctx)
    report = render_report(checks)
    assert "系统诊断报告" in report
    assert "汇总" in report
    for c in checks:
        assert c["label"] in report
        assert c["status"] in report


# 3. Dialog 可无头构造
def test_03_dialog_constructs_offscreen():
    _setup_qt()
    dlg = DiagnosticsDialog(context=_ctx, auto_check=False)
    try:
        assert dlg.windowTitle() == "系统诊断"
        assert len(dlg._row_widgets) == 8
    finally:
        dlg.close()


# 4. run_all_checks_sync 渲染并保存
def test_04_sync_run_and_render():
    _app.processEvents()
    dlg = DiagnosticsDialog(context=_ctx, auto_check=False)
    try:
        checks = dlg.run_all_checks_sync()
        assert len(checks) == 8
        assert len(dlg._last_checks) == 8
        # 渲染后 report 有内容
        txt = dlg._report.toPlainText()
        assert "系统诊断报告" in txt
        assert "汇总" in txt
        # 各行都应有状态符号（同步渲染后）
        for name in CHECK_NAMES:
            icon_lbl, name_lbl, desc_lbl = dlg._row_widgets[name]
            assert icon_lbl.text() in {OK, WARN, FAIL}, (
                f"{name} 状态符号未渲染: {icon_lbl.text()!r}")
            assert name_lbl.text(), f"{name} 标签为空"
    finally:
        dlg.close()


# 5. MainWindow 接入菜单（不实际启动整个 MainWindow，只检查属性/方法存在）
def test_05_main_window_has_diagnostics_entry():
    import inspect
    from futures_quant.ui import main_window as mw_mod
    src = inspect.getsource(mw_mod.MainWindow)
    assert "_show_diagnostics" in src, "MainWindow 缺少 _show_diagnostics 方法"
    assert "系统诊断" in src, "MainWindow 菜单缺少「系统诊断」"
    assert "Ctrl+Shift+D" in src, "MainWindow 缺少快捷键 Ctrl+Shift+D"
    # 检查方法签名
    assert hasattr(mw_mod.MainWindow, "_show_diagnostics")


# 6. 核心 4 项在合理 ctx 下为绿（Python / 数据目录 / 磁盘 / 密钥）
def test_06_core_4_items_green():
    checks = run_all_checks(_ctx)
    by_name = {c["name"]: c for c in checks}
    assert by_name["python_version"]["status"] == OK
    assert by_name["data_dir"]["status"] == OK
    assert by_name["disk"]["status"] in {OK, WARN}  # 磁盘可能黄但通常绿
    assert by_name["api_key"]["status"] == OK


# 7. 报告不含密钥全文
def test_07_no_full_key_leak():
    checks = run_all_checks(_ctx)
    report = render_report(checks)
    full_key = "sk-abc12345"
    assert full_key not in report
    # 应显示脱敏
    assert "sk-" in report and "…" in report


# 8. 安全关闭（不挂起）
def test_08_safe_close():
    _app.processEvents()
    dlg = DiagnosticsDialog(context=_ctx, auto_check=False)
    dlg.run_all_checks_sync()
    dlg.close()
    # 再关一次也不报错
    dlg.close()


# 9. 断网/离线场景：feed=None 时数据源和新鲜度两项为 WARN 而非 FAIL
def test_09_offline_fallback():
    checks = run_all_checks({"data_feed": None})
    by_name = {c["name"]: c for c in checks}
    assert by_name["data_source"]["status"] == WARN
    assert by_name["data_freshness"]["status"] == WARN


# 10. 缺必需依赖为 FAIL（模拟缺 requests）
def test_10_missing_required_dep_fails():
    checks = run_all_checks({"required_deps": ["__missing_required_mod_xyz__"]})
    by_name = {c["name"]: c for c in checks}
    assert by_name["deps"]["status"] == FAIL
    assert "__missing_required_mod_xyz__" in by_name["deps"]["desc"]


def _run():
    tests = [
        ("1. 核心函数无 Qt 环境可用", test_01_core_functions),
        ("2. 报告结构含 8 项 + 汇总", test_02_report_structure),
        ("3. Dialog 可无头构造", test_03_dialog_constructs_offscreen),
        ("4. run_all_checks_sync 渲染", test_04_sync_run_and_render),
        ("5. MainWindow 有系统诊断菜单项", test_05_main_window_has_diagnostics_entry),
        ("6. 4 项核心检查为绿", test_06_core_4_items_green),
        ("7. 报告不含密钥全文", test_07_no_full_key_leak),
        ("8. 安全关闭不挂起", test_08_safe_close),
        ("9. 断网场景优雅降级", test_09_offline_fallback),
        ("10. 缺必需依赖为 FAIL", test_10_missing_required_dep_fails),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception:
            print(f"  ❌ {name}")
            traceback.print_exc()
    print(f"\nM1-09 smoke: {passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    ok = _run()
    sys.exit(0 if ok else 1)
