#!/usr/bin/env python3
"""UX Phase 5 & 6 冒烟测试：导航分组、窄屏抽屉、无障碍。

覆盖端到端 DoD：
    Phase 5:
    1. UX-60: 导航分组（NAV_GROUPS 3 组，覆盖 7 页）
    2. UX-61: 面包屑 + 页面副标题（PAGE_SUBTITLES）
    3. UX-62: 窄屏抽屉导航（三档宽度阈值）
    4. UX-64: 诊断面板联动日志目录（_open_log_dir）
    5. UX-67: 首屏性能优化（延迟首页构造）
    6. UX-68: 跨页导航（navigate_requested 信号）

    Phase 6:
    7. UX-70: 高 DPI 支持（devicePixelRatio）
    8. UX-71: Tab 顺序优化（setTabOrder）
    9. UX-72: setWhatsThis 覆盖（导航、状态栏）
    10. UX-73: 屏幕变化订阅（_connect_screen_changes）
    11. UX-74: 焦点环 QSS（focus-visible）
    12. UX-75: QV_REDUCED_MOTION 门控（MOTION 常量）

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_ux_phase5_6.py > tests/e2e/ux_phase5_6.log 2>&1; echo rc=$?
"""
from __future__ import annotations

import os
import sys
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 设置环境
os.environ["QUANTVORTEX_NO_PERSIST"] = "1"

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name: str, cond: bool, detail: str = "") -> None:
    """记录检查结果。"""
    results.append((name, bool(cond), detail))
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" | {detail}" if detail else ""))


def read_source(path: str) -> str:
    """读取源码文件。"""
    with open(path, encoding="utf-8") as f:
        return f.read()


# ============================================================================
# Phase 5: 页面级 UX
# ============================================================================

print("=" * 60)
print("Phase 5: 页面级 UX")
print("=" * 60)

# --- UX-60: 导航分组 ---
SRC_MAIN = os.path.join(ROOT, "futures_quant", "ui", "main_window.py")
src_main = read_source(SRC_MAIN)

# 检查 NAV_GROUPS 定义
if re.search(r"NAV_GROUPS\s*=", src_main):
    check("UX-60: NAV_GROUPS 已定义", True)
else:
    check("UX-60: NAV_GROUPS 已定义", False, "未找到 NAV_GROUPS")

# 检查 3 个分组
nav_groups_matches = re.findall(r'\("([^"]+)",\s*(\d+),\s*(\d+)\)', src_main)
if len(nav_groups_matches) >= 3:
    check("UX-60: 3 个导航分组", True, f"找到 {len(nav_groups_matches)} 组")
else:
    check("UX-60: 3 个导航分组", False, f"仅 {len(nav_groups_matches)} 组")

# 检查覆盖所有 7 页
covered_indices = set()
for _, start, end in nav_groups_matches:
    covered_indices.update(range(int(start), int(end)))
if covered_indices == set(range(7)):
    check("UX-60: 覆盖所有 7 页", True)
else:
    check("UX-60: 覆盖所有 7 页", False, f"覆盖 {sorted(covered_indices)}")

# --- UX-61: 面包屑 + 页面副标题 ---
# 检查 PAGE_SUBTITLES 定义
if re.search(r"PAGE_SUBTITLES\s*=", src_main):
    check("UX-61: PAGE_SUBTITLES 已定义", True)
else:
    check("UX-61: PAGE_SUBTITLES 已定义", False, "未找到 PAGE_SUBTITLES")

# 检查 _update_breadcrumb 方法
if "_update_breadcrumb" in src_main:
    check("UX-61: _update_breadcrumb 方法", True)
else:
    check("UX-61: _update_breadcrumb 方法", False, "未找到方法")

# --- UX-62: 窄屏抽屉导航 ---
# 检查阈值常量
if "NAV_COLLAPSE_THRESHOLD" in src_main:
    check("UX-62: NAV_COLLAPSE_THRESHOLD", True)
else:
    check("UX-62: NAV_COLLAPSE_THRESHOLD", False, "未找到常量")

if "NAV_TAB_THRESHOLD" in src_main:
    check("UX-62: NAV_TAB_THRESHOLD", True)
else:
    check("UX-62: NAV_TAB_THRESHOLD", False, "未找到常量")

# 检查 _top_tabs 控件
if "_top_tabs" in src_main:
    check("UX-62: _top_tabs 控件", True)
else:
    check("UX-62: _top_tabs 控件", False, "未找到控件")

# 检查 _update_nav_mode 方法
if "_update_nav_mode" in src_main:
    check("UX-62: _update_nav_mode 方法", True)
else:
    check("UX-62: _update_nav_mode 方法", False, "未找到方法")

# --- UX-64: 诊断面板联动 ---
SRC_DIAG = os.path.join(ROOT, "futures_quant", "ui", "diagnostics_dialog.py")
src_diag = read_source(SRC_DIAG)

# 检查 _btn_logs 按钮
if "_btn_logs" in src_diag:
    check("UX-64: _btn_logs 按钮", True)
else:
    check("UX-64: _btn_logs 按钮", False, "未找到按钮")

# 检查 _open_log_dir 方法
if "_open_log_dir" in src_diag:
    check("UX-64: _open_log_dir 方法", True)
else:
    check("UX-64: _open_log_dir 方法", False, "未找到方法")

# --- UX-67: 首屏性能优化 ---
# 检查 _first_page_initialized 标志
if "_first_page_initialized" in src_main:
    check("UX-67: _first_page_initialized 标志", True)
else:
    check("UX-67: _first_page_initialized 标志", False, "未找到标志")

# 检查 _loading_placeholder 占位符
if "_loading_placeholder" in src_main:
    check("UX-67: _loading_placeholder 占位符", True)
else:
    check("UX-67: _loading_placeholder 占位符", False, "未找到占位符")

# 检查 showEvent 延迟构造
if "QTimer.singleShot(100, self._init_first_page)" in src_main:
    check("UX-67: 延迟 100ms 构造首页", True)
else:
    check("UX-67: 延迟 100ms 构造首页", False, "未找到延迟构造")

# --- UX-68: 跨页导航 ---
# 检查 navigate_requested 信号
if "navigate_requested" in src_main:
    check("UX-68: navigate_requested 信号", True)
else:
    check("UX-68: navigate_requested 信号", False, "未找到信号")

# 检查 _on_navigate_requested 处理
if "_on_navigate_requested" in src_main:
    check("UX-68: _on_navigate_requested 处理", True)
else:
    check("UX-68: _on_navigate_requested 处理", False, "未找到处理")


# ============================================================================
# Phase 6: 无障碍 / DPI / 响应式
# ============================================================================

print("\n" + "=" * 60)
print("Phase 6: 无障碍 / DPI / 响应式")
print("=" * 60)

# --- UX-70: 高 DPI 支持 ---
SRC_SPLASH = os.path.join(ROOT, "futures_quant", "ui", "splash.py")
src_splash = read_source(SRC_SPLASH)

# 检查 devicePixelRatio 使用
if "devicePixelRatio" in src_splash:
    check("UX-70: devicePixelRatio 超采样", True)
else:
    check("UX-70: devicePixelRatio 超采样", False, "未找到超采样")

# 检查 _logo_pixmap 方法
if "_logo_pixmap" in src_splash:
    check("UX-70: _logo_pixmap 方法", True)
else:
    check("UX-70: _logo_pixmap 方法", False, "未找到方法")

# 检查 devicePixelRatio 属性设置
if "setDevicePixelRatio" in src_splash:
    check("UX-70: setDevicePixelRatio 属性", True)
else:
    check("UX-70: setDevicePixelRatio 属性", False, "未找到属性设置")

# --- UX-71: Tab 顺序优化 ---
SRC_MARKET = os.path.join(ROOT, "futures_quant", "ui", "market_overview_page.py")
src_market = read_source(SRC_MARKET)

# 检查 MarketOverviewPage 的 _setup_tab_order
if "_setup_tab_order" in src_market:
    check("UX-71: MarketOverviewPage _setup_tab_order", True)
else:
    check("UX-71: MarketOverviewPage _setup_tab_order", False, "未找到方法")

SRC_PREDICT = os.path.join(ROOT, "futures_quant", "ui", "predict_ops_page.py")
src_predict = read_source(SRC_PREDICT)

# 检查 PredictOpsPage 的 _setup_tab_order
if "_setup_tab_order" in src_predict:
    check("UX-71: PredictOpsPage _setup_tab_order", True)
else:
    check("UX-71: PredictOpsPage _setup_tab_order", False, "未找到方法")

# 检查 showEvent 调用 _setup_tab_order
if "QTimer.singleShot(0, self._setup_tab_order)" in src_market:
    check("UX-71: MarketOverview showEvent 调用", True)
else:
    check("UX-71: MarketOverview showEvent 调用", False, "未找到调用")

if "QTimer.singleShot(0, self._setup_tab_order)" in src_predict:
    check("UX-71: PredictOps showEvent 调用", True)
else:
    check("UX-71: PredictOps showEvent 调用", False, "未找到调用")

# --- UX-72: setWhatsThis 覆盖 ---
# 检查 nav whatsThis
if 'self.nav.setWhatsThis' in src_main:
    check("UX-72: 导航栏 whatsThis", True)
else:
    check("UX-72: 导航栏 whatsThis", False, "未找到 setWhatsThis")

# 检查状态栏 whatsThis
if 'self._status_conn.setWhatsThis' in src_main:
    check("UX-72: 状态栏连接 whatsThis", True)
else:
    check("UX-72: 状态栏连接 whatsThis", False, "未找到 setWhatsThis")

# 检查重连按钮 whatsThis
if 'self._conn_btn.setWhatsThis' in src_main:
    check("UX-72: 重连按钮 whatsThis", True)
else:
    check("UX-72: 重连按钮 whatsThis", False, "未找到 setWhatsThis")

# 检查主题按钮 whatsThis
if 'self._theme_btn.setWhatsThis' in src_main:
    check("UX-72: 主题按钮 whatsThis", True)
else:
    check("UX-72: 主题按钮 whatsThis", False, "未找到 setWhatsThis")

# --- UX-73: 屏幕变化订阅 ---
# 检查 _connect_screen_changes 方法
if "_connect_screen_changes" in src_main:
    check("UX-73: _connect_screen_changes 方法", True)
else:
    check("UX-73: _connect_screen_changes 方法", False, "未找到方法")

# 检查 _on_screen_changed 方法
if "_on_screen_changed" in src_main:
    check("UX-73: _on_screen_changed 方法", True)
else:
    check("UX-73: _on_screen_changed 方法", False, "未找到方法")

# 检查 geometryChanged 信号连接
if "geometryChanged.connect" in src_main:
    check("UX-73: geometryChanged 信号", True)
else:
    check("UX-73: geometryChanged 信号", False, "未找到信号连接")

# 检查 virtualGeometryChanged 信号连接
if "virtualGeometryChanged.connect" in src_main:
    check("UX-73: virtualGeometryChanged 信号", True)
else:
    check("UX-73: virtualGeometryChanged 信号", False, "未找到信号连接")

# --- UX-74: 焦点环 QSS ---
SRC_QSS = os.path.join(ROOT, "futures_quant", "ui", "design_system.py")
src_qss = read_source(SRC_QSS)

# 检查 focus-visible 样式
focus_visible_count = len(re.findall(r":focus-visible", src_qss))
if focus_visible_count >= 10:
    check("UX-74: focus-visible 样式", True, f"找到 {focus_visible_count} 处")
else:
    check("UX-74: focus-visible 样式", False, f"仅 {focus_visible_count} 处")

# 检查特定控件 focus-visible
if "QPushButton:focus-visible" in src_qss:
    check("UX-74: QPushButton focus-visible", True)
else:
    check("UX-74: QPushButton focus-visible", False, "未找到样式")

if "QLineEdit:focus-visible" in src_qss:
    check("UX-74: QLineEdit focus-visible", True)
else:
    check("UX-74: QLineEdit focus-visible", False, "未找到样式")

if "QComboBox:focus-visible" in src_qss:
    check("UX-74: QComboBox focus-visible", True)
else:
    check("UX-74: QComboBox focus-visible", False, "未找到样式")

# --- UX-75: QV_REDUCED_MOTION 门控 ---
SRC_STATES = os.path.join(ROOT, "futures_quant", "ui", "states.py")
src_states = read_source(SRC_STATES)

# 检查 MOTION 常量
if "MOTION = not _env_flag" in src_states:
    check("UX-75: MOTION 常量定义", True)
else:
    check("UX-75: MOTION 常量定义", False, "未找到定义")

# 检查 motion_enabled 函数
if "def motion_enabled" in src_states:
    check("UX-75: motion_enabled 函数", True)
else:
    check("UX-75: motion_enabled 函数", False, "未找到函数")

# 检查 widgets.py 的 MOTION 门控
SRC_WIDGETS = os.path.join(ROOT, "futures_quant", "ui", "widgets.py")
src_widgets = read_source(SRC_WIDGETS)

if "if not MOTION:" in src_widgets:
    check("UX-75: widgets.py MOTION 门控", True)
else:
    check("UX-75: widgets.py MOTION 门控", False, "未找到门控")

# 检查 ai_settings_dialog.py 的 MOTION 门控
SRC_AI = os.path.join(ROOT, "futures_quant", "ui", "ai_settings_dialog.py")
src_ai = read_source(SRC_AI)

if "if MOTION:" in src_ai:
    check("UX-75: ai_settings_dialog MOTION 门控", True)
else:
    check("UX-75: ai_settings_dialog MOTION 门控", False, "未找到门控")

# 检查 qr_card.py 的 MOTION 门控
SRC_QR = os.path.join(ROOT, "futures_quant", "ui", "qr_card.py")
src_qr = read_source(SRC_QR)

if "MOTION" in src_qr:
    check("UX-75: qr_card MOTION 门控", True)
else:
    check("UX-75: qr_card MOTION 门控", False, "未找到门控")


# ============================================================================
# 运行时验证（实际构造控件）
# ============================================================================

print("\n" + "=" * 60)
print("运行时验证")
print("=" * 60)

# 导入主窗口并验证
try:
    from futures_quant.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    app.processEvents()

    # 验证 NAV_GROUPS
    from futures_quant.ui.main_window import NAV_GROUPS
    check("运行时: NAV_GROUPS 可导入", True, f"{len(NAV_GROUPS)} 组")

    # 验证 PAGE_SUBTITLES
    from futures_quant.ui.main_window import PAGE_SUBTITLES
    check("运行时: PAGE_SUBTITLES 可导入", True, f"{len(PAGE_SUBTITLES)} 项")

    # 验证阈值常量
    check("运行时: NAV_COLLAPSE_THRESHOLD", True, str(MainWindow.NAV_COLLAPSE_THRESHOLD))
    check("运行时: NAV_TAB_THRESHOLD", True, str(MainWindow.NAV_TAB_THRESHOLD))
    check("运行时: NAV_COLLAPSED_WIDTH", True, str(MainWindow.NAV_COLLAPSED_WIDTH))

    # 验证 _top_tabs 控件
    check("运行时: _top_tabs 控件", hasattr(w, "_top_tabs"))

    # 验证 whatsThis
    whats = w.nav.whatsThis()
    check("运行时: 导航栏 whatsThis", len(whats) > 50, f"{len(whats)} chars")

    # 验证焦点环
    from futures_quant.ui.design_system import build_qss
    qss = build_qss("dark")
    check("运行时: focus-visible 在 QSS", "focus-visible" in qss)

    # 验证 MOTION
    from futures_quant.ui.states import MOTION, motion_enabled
    check("运行时: MOTION 常量", isinstance(MOTION, bool))
    check("运行时: motion_enabled 函数", callable(motion_enabled))

    w.deleteLater()
    app.processEvents()
except Exception as e:
    check("运行时验证", False, str(e))


# ============================================================================
# 汇总
# ============================================================================

print("\n" + "=" * 60)
print("测试汇总")
print("=" * 60)

total = len(results)
passed = sum(1 for _, cond, _ in results if cond)
failed = total - passed

print(f"总计: {total}")
print(f"通过: {passed}")
print(f"失败: {failed}")

if failed > 0:
    print("\n失败项:")
    for name, cond, detail in results:
        if not cond:
            print(f"  [FAIL] {name} | {detail}")
    sys.exit(1)
else:
    print("\n所有测试通过！")
    sys.exit(0)