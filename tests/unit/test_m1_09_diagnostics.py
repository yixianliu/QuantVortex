"""M1-09 系统诊断面板单元测试（覆盖 8 项检查 + 报告渲染 + 状态符号）。"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

from futures_quant.ui.diagnostics_dialog import (
    CHECK_NAMES,
    OK, WARN, FAIL,
    run_all_checks,
    render_report,
    check_python_version,
    check_deps,
    check_data_dir,
    check_disk,
    check_data_source,
    check_data_freshness,
    check_api_key,
    check_qr_gate,
)


def test_check_names_covers_8_items():
    """CHECK_NAMES 恰好 8 项，且与 spec 一致。"""
    assert len(CHECK_NAMES) == 8
    expected = {"python_version", "deps", "data_dir", "disk",
                "data_source", "data_freshness", "api_key", "qr_gate"}
    assert set(CHECK_NAMES) == expected


def test_run_all_checks_returns_8_rows():
    checks = run_all_checks()
    assert len(checks) == 8
    for c in checks:
        assert c["name"] in CHECK_NAMES
        assert c["status"] in {OK, WARN, FAIL}
        assert c["label"]
        assert c["desc"]


# ---------- 单项 ----------
def test_check_python_version_ok():
    status, desc, detail = check_python_version()
    # 当前 Python 3.13 应绿
    assert status == OK
    assert "3.13" in detail or "3.10" in detail or "3." in detail


def test_check_deps_missing_optional_gives_warn():
    status, desc, _ = check_deps(required=["PyQt6"], optional=["__no_such_module__"])
    assert status == WARN
    assert "__no_such_module__" in desc


def test_check_deps_missing_required_gives_fail():
    status, desc, _ = check_deps(required=["__no_such_module__"], optional=[])
    assert status == FAIL


def test_check_deps_all_present_ok():
    status, _, _ = check_deps(required=["PyQt6", "requests"], optional=[])
    assert status == OK


def test_check_data_dir_ok():
    with tempfile.TemporaryDirectory() as td:
        status, _, _ = check_data_dir(td)
        assert status == OK


def test_check_data_dir_nonexist_fails():
    status, desc, _ = check_data_dir("/nonexistent/path/xyz/123")
    assert status == FAIL
    assert "不存在" in desc


def test_check_disk_ok():
    status, _, _ = check_disk(disk_dir=".")
    assert status in {OK, WARN}  # 取决于磁盘剩余，但至少不红


def test_check_disk_bad_dir_fails():
    status, _, _ = check_disk(disk_dir="/nonexistent/path/xyz/123")
    assert status == FAIL


def test_check_data_source_none_warns():
    status, desc, _ = check_data_source(feed=None)
    assert status == WARN


def test_check_data_source_timeout_warns():
    class SlowFeed:
        def ping(self):
            import time
            time.sleep(10)
            return True

    status, desc, _ = check_data_source(feed=SlowFeed(), timeout_s=0.3)
    assert status == WARN
    assert "超时" in desc


def test_check_data_source_connectable_ok():
    class FastFeed:
        def ping(self):
            return True

    status, _, _ = check_data_source(feed=FastFeed(), timeout_s=2.0)
    assert status == OK


def test_check_data_freshness_none_warns():
    status, desc, _ = check_data_freshness(feed=None)
    assert status == WARN


def test_check_data_freshness_fresh():
    import time
    class FreshFeed:
        last_bar_ts = time.time() - 60  # 1 分钟前

    status, desc, _ = check_data_freshness(feed=FreshFeed())
    assert status == OK
    assert "24h" in desc or "新鲜" in desc


def test_check_data_freshness_stale():
    import time
    class StaleFeed:
        last_bar_ts = time.time() - 86400 * 10  # 10 天前

    status, desc, _ = check_data_freshness(feed=StaleFeed())
    assert status == FAIL
    assert "过期" in desc


def test_check_api_key_present():
    status, desc, _ = check_api_key("sk-abcdef1234")
    assert status == OK
    # 不显示全文
    assert "abcdef" not in desc


def test_check_api_key_missing_warns():
    # 清掉环境变量以保证 WARN
    os.environ.pop("QV_AGNES_API_KEY", None)
    status, desc, _ = check_api_key(None)
    assert status == WARN


def test_check_qr_gate_enabled():
    status, _, _ = check_qr_gate(enabled=True)
    assert status == OK


def test_check_qr_gate_disabled_warns():
    status, _, _ = check_qr_gate(enabled=False)
    assert status == WARN


# ---------- 报告 ----------
def test_render_report_contains_all_8_items():
    checks = run_all_checks()
    report = render_report(checks)
    for c in checks:
        assert c["label"] in report
        assert c["status"] in report
    assert "汇总" in report


def test_render_report_does_not_leak_full_key():
    checks = run_all_checks({"api_key_fingerprint": "sk-abc123XYZ-DEF456"})
    report = render_report(checks)
    assert "abc123XYZ-DEF456" not in report
    # 脱敏显示应保留首尾片段
    assert "sk-" in report or "…" in report


def test_render_report_empty_checks():
    report = render_report([])
    assert "汇总" in report
    assert "0 项正常" in report
