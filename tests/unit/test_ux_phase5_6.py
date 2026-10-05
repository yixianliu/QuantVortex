"""UX Phase 5 & 6 单元测试。

覆盖任务：
- UX-60: 导航分组
- UX-61: 面包屑 + 页面副标题
- UX-62: 窄屏抽屉导航
- UX-64: 诊断面板联动日志目录
- UX-67: 首屏性能优化
- UX-70: 高 DPI 支持
- UX-71: Tab 顺序优化
- UX-72: setWhatsThis 覆盖
- UX-73: 屏幕变化订阅
- UX-74: 焦点环 QSS
- UX-75: QV_REDUCED_MOTION 门控

运行方式：
    QT_QPA_PLATFORM=offscreen pytest tests/unit/test_ux_phase5_6.py -v
"""
from __future__ import annotations

import os
import sys
import pytest

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ["QUANTVORTEX_NO_PERSIST"] = "1"


@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例（module scope 避免重复创建）。"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    _flush_pending_deletes(app)   # 所有挂起删除在这里一次性结算


# 待销毁的顶层 widget —— **延迟到模块收尾统一删一次**（v5.2.7）。
#
# 三版实现的坑：
#   ① 只 close() 不销毁 → widget 与 QApplication 的释放顺序交给 GC，
#      偶发 CRT fast-fail（0xC0000409）。
#   ② 每用例 deleteLater + processEvents()（v5.2.6 的写法）
#      → 更早、更频繁地触发同一个 fast-fail： ``test_top_tabs_widget_exists``
#      造的是一个**完整 MainWindow**，``deleteLater()`` 只是挂起删除事件，
#      而紧接着的 ``processEvents()`` 立刻把它结算掉 —— 主窗口在后续用例的
#      事件循环里被析构，Qt 直接 fast-fail。实测稳定卡在第 8/37 个用例。
#   ③ 延迟删除 + 对象身份集合（不用 ``id()``，地址可复用导致漏删）
#      → 37 个用例期间完全不动 Qt，所有 DeferredDelete 事件留到最后
#      一次性结算，崩溃消失。
_TO_DELETE: list = []


@pytest.fixture(autouse=True)
def _cleanup_widgets(app):
    """只登记新增的顶层 widget，真正销毁推迟到模块收尾。"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or app
    before = set(app.topLevelWidgets())     # 对象身份，避免 id() 地址复用
    yield
    for w in app.topLevelWidgets():
        if w not in before:
            _TO_DELETE.append(w)


def _flush_pending_deletes(app) -> None:
    """模块收尾：一次性结算所有挂起的删除（一次事件循环，而非 37 次）。"""
    pending, _TO_DELETE[:] = list(_TO_DELETE), []
    for w in pending:
        try:
            w.setParent(None)
            w.deleteLater()
        except Exception:
            pass
    for _ in range(2):
        try:
            app.processEvents()
        except Exception:
            break


# ============================================================================
# UX-60: 导航分组
# ============================================================================
class TestUX60NavGroups:
    """UX-60: 导航分组测试。"""

    def test_nav_groups_defined(self):
        """NAV_GROUPS 已定义且包含 3 个分组。"""
        from futures_quant.ui.main_window import NAV_GROUPS
        assert len(NAV_GROUPS) == 3

    def test_nav_groups_cover_all_pages(self):
        """NAV_GROUPS 覆盖所有 7 个页面。"""
        from futures_quant.ui.main_window import NAV_GROUPS, NAV
        covered = set()
        for _, start, end in NAV_GROUPS:
            covered.update(range(start, end))
        assert covered == set(range(len(NAV)))

    def test_nav_groups_indices_valid(self):
        """NAV_GROUPS 索引在有效范围内。"""
        from futures_quant.ui.main_window import NAV_GROUPS, NAV
        for _, start, end in NAV_GROUPS:
            assert 0 <= start < end <= len(NAV)


# ============================================================================
# UX-61: 面包屑 + 页面副标题
# ============================================================================
class TestUX61Breadcrumb:
    """UX-61: 面包屑和页面副标题测试。"""

    def test_page_subtitles_defined(self):
        """PAGE_SUBTITLES 已定义且覆盖所有页面。"""
        from futures_quant.ui.main_window import PAGE_SUBTITLES, NAV
        assert len(PAGE_SUBTITLES) == len(NAV)
        for idx in range(len(NAV)):
            assert idx in PAGE_SUBTITLES
            assert isinstance(PAGE_SUBTITLES[idx], str)
            assert len(PAGE_SUBTITLES[idx]) > 0

    def test_breadcrumb_method_exists(self, app):
        """_update_breadcrumb 方法存在。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        assert hasattr(w, "_update_breadcrumb")
        w.deleteLater()


# ============================================================================
# UX-62: 窄屏抽屉导航
# ============================================================================
class TestUX62NarrowScreen:
    """UX-62: 窄屏抽屉导航测试。"""

    def test_nav_thresholds_defined(self, app):
        """导航阈值常量已定义。"""
        from futures_quant.ui.main_window import MainWindow
        assert hasattr(MainWindow, "NAV_COLLAPSE_THRESHOLD")
        assert hasattr(MainWindow, "NAV_TAB_THRESHOLD")
        assert hasattr(MainWindow, "NAV_COLLAPSED_WIDTH")

    def test_nav_thresholds_values(self):
        """导航阈值常量值正确。"""
        from futures_quant.ui.main_window import MainWindow
        assert MainWindow.NAV_COLLAPSE_THRESHOLD == 1100
        assert MainWindow.NAV_TAB_THRESHOLD == 900
        assert MainWindow.NAV_COLLAPSED_WIDTH == 56

    def test_top_tabs_widget_exists(self, app):
        """_top_tabs 控件存在。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        assert hasattr(w, "_top_tabs")
        assert w._top_tabs is not None
        w.deleteLater()


# ============================================================================
# UX-64: 诊断面板联动日志目录
# ============================================================================
class TestUX64Diagnostics:
    """UX-64: 诊断面板联动日志目录测试。"""

    def test_open_log_dir_method_exists(self, app):
        """_open_log_dir 方法存在。"""
        from futures_quant.ui.diagnostics_dialog import DiagnosticsDialog
        d = DiagnosticsDialog()
        assert hasattr(d, "_open_log_dir")
        d.close()

    def test_btn_logs_exists(self, app):
        """_btn_logs 按钮存在。"""
        from futures_quant.ui.diagnostics_dialog import DiagnosticsDialog
        d = DiagnosticsDialog()
        assert hasattr(d, "_btn_logs")
        assert d._btn_logs is not None
        d.close()


# ============================================================================
# UX-67: 首屏性能优化
# ============================================================================
class TestUX67Startup:
    """UX-67: 首屏性能优化测试。"""

    def test_first_page_lazily_initialized(self, app):
        """首页延迟初始化标志存在。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        assert hasattr(w, "_first_page_initialized")
        assert w._first_page_initialized is False
        w.deleteLater()

    def test_loading_placeholder_exists(self, app):
        """加载占位符存在。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        assert hasattr(w, "_loading_placeholder")
        assert w._loading_placeholder is not None
        w.deleteLater()


# ============================================================================
# UX-70: 高 DPI 支持
# ============================================================================
class TestUX70HighDPI:
    """UX-70: 高 DPI 支持测试。"""

    def test_splash_logo_dpi_scaling(self):
        """Splash Logo 支持 DPI 超采样。"""
        from futures_quant.ui.splash import _logo_pixmap
        logo = _logo_pixmap()
        assert logo is not None
        assert logo.width() > 0
        assert logo.height() > 0

    def test_device_pixel_ratio_available(self, app):
        """devicePixelRatio 可用。"""
        dpr = app.devicePixelRatio()
        assert dpr > 0


# ============================================================================
# UX-71: Tab 顺序优化
# ============================================================================
class TestUX71TabOrder:
    """UX-71: Tab 顺序优化测试。"""

    def test_market_overview_has_tab_order_method(self):
        """MarketOverviewPage 类有 _setup_tab_order 方法。"""
        from futures_quant.ui.market_overview_page import MarketOverviewPage
        assert hasattr(MarketOverviewPage, "_setup_tab_order")

    def test_predict_ops_has_tab_order_method(self):
        """PredictOpsPage 类有 _setup_tab_order 方法。"""
        from futures_quant.ui.predict_ops_page import PredictOpsPage
        assert hasattr(PredictOpsPage, "_setup_tab_order")


# ============================================================================
# UX-72: setWhatsThis 覆盖
# ============================================================================
class TestUX72WhatsThis:
    """UX-72: setWhatsThis 覆盖测试。"""

    def test_nav_whats_this(self, app):
        """导航栏有 whatsThis 帮助文本。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        whats = w.nav.whatsThis()
        assert len(whats) > 50
        assert "Ctrl" in whats
        w.deleteLater()

    def test_status_conn_whats_this(self, app):
        """状态栏连接标签有 whatsThis。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        whats = w._status_conn.whatsThis()
        assert len(whats) > 20
        w.deleteLater()

    def test_conn_btn_whats_this(self, app):
        """重连按钮有 whatsThis。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        whats = w._conn_btn.whatsThis()
        assert len(whats) > 20
        w.deleteLater()

    def test_theme_btn_whats_this(self, app):
        """主题切换按钮有 whatsThis。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        whats = w._theme_btn.whatsThis()
        assert len(whats) > 10
        w.deleteLater()


# ============================================================================
# UX-73: 屏幕变化订阅
# ============================================================================
class TestUX73ScreenChange:
    """UX-73: 屏幕变化订阅测试。"""

    def test_connect_screen_changes_method_exists(self, app):
        """_connect_screen_changes 方法存在。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        assert hasattr(w, "_connect_screen_changes")
        w.deleteLater()

    def test_on_screen_changed_method_exists(self, app):
        """_on_screen_changed 方法存在。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        assert hasattr(w, "_on_screen_changed")
        w.deleteLater()


# ============================================================================
# UX-74: 焦点环 QSS
# ============================================================================
class TestUX74FocusRing:
    """UX-74: 焦点环 QSS 测试。"""

    def test_focus_visible_in_qss(self):
        """QSS 模板包含 focus-visible 样式。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "focus-visible" in qss

    def test_focus_visible_button(self):
        """QPushButton focus-visible 样式存在。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QPushButton:focus-visible" in qss

    def test_focus_visible_combobox(self):
        """QComboBox focus-visible 样式存在。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QComboBox:focus-visible" in qss

    def test_focus_visible_lineedit(self):
        """QLineEdit focus-visible 样式存在。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QLineEdit:focus-visible" in qss

    def test_focus_visible_table(self):
        """QTableWidget focus-visible 样式存在。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QTableWidget:focus-visible" in qss

    def test_focus_visible_checkbox(self):
        """QCheckBox focus-visible 样式存在。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QCheckBox:focus-visible" in qss

    def test_focus_visible_tabbar(self):
        """QTabBar focus-visible 样式存在。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QTabBar::tab:focus-visible" in qss


# ============================================================================
# UX-75: QV_REDUCED_MOTION 门控
# ============================================================================
class TestUX75ReducedMotion:
    """UX-75: QV_REDUCED_MOTION 门控测试。"""

    def test_motion_constant_exists(self):
        """MOTION 常量存在。"""
        from futures_quant.ui.states import MOTION
        assert isinstance(MOTION, bool)

    def test_motion_enabled_function_exists(self):
        """motion_enabled 函数存在。"""
        from futures_quant.ui.states import motion_enabled
        assert callable(motion_enabled)

    def test_motion_default_true(self):
        """默认情况下 MOTION 为 True。"""
        from futures_quant.ui.states import MOTION, motion_enabled
        assert MOTION is True
        assert motion_enabled() is True

    def test_motion_disabled_with_env(self):
        """QV_REDUCED_MOTION=1 时 MOTION 为 False。"""
        os.environ["QV_REDUCED_MOTION"] = "1"
        try:
            import importlib
            import futures_quant.ui.states as states_mod
            importlib.reload(states_mod)
            assert states_mod.MOTION is False
            assert states_mod.motion_enabled() is False
        finally:
            os.environ.pop("QV_REDUCED_MOTION", None)
            import importlib
            import futures_quant.ui.states as states_mod
            importlib.reload(states_mod)


# ============================================================================
# 契约测试：QSS 无残留占位符
# ============================================================================
class TestQSSContract:
    """QSS 契约测试。"""

    def test_no_unresolved_placeholders(self):
        """QSS 模板无未解析的占位符。"""
        import re
        from futures_quant.ui.design_system import _QSS_TEMPLATE
        # 查找 $...$ 格式的占位符
        placeholders = re.findall(r"\$[A-Z_]+\$", _QSS_TEMPLATE)
        unresolved = [p for p in placeholders if p not in (
            "$ACCENT$", "$ACCENT2$", "$BG$", "$BORDER$", "$CARD$",
            "$DOWN$", "$GRID$", "$PANEL$", "$SUB$", "$TEXT$", "$UP$",
            "$radius_lg$", "$radius_md$", "$radius_pill$", "$radius_sm$",
            "$space_1$", "$space_2$", "$space_3$", "$space_5$",
            "$space_6$", "$space_7$", "$space_9$", "$space_10$",
            "$space_14$", "$space_18$", "$space_20$", "$space_26$",
            "$space_32$", "$space_lg$", "$space_md$", "$space_sm$",
            "$space_xl$", "$space_xs$",
            "$font_caption$", "$font_body$", "$font_h3$", "$font_h2$",
            "$font_h1$", "$font_h4$",
            "$elevation_e1$", "$elevation_e2$", "$elevation_e3$",
            "$chart_series_1$", "$chart_series_2$", "$chart_series_3$",
            "$chart_series_4$", "$chart_series_5$", "$chart_series_6$",
        )]
        assert len(unresolved) == 0, f"Unresolved placeholders: {unresolved}"

    def test_build_qss_no_residual_dollar(self):
        """build_qss 输出无残留 $ 占位符。"""
        from futures_quant.ui.design_system import build_qss
        for theme in ("dark", "light"):
            qss = build_qss(theme)
            assert "$" not in qss, f"Residual $ in {theme} theme"


# ============================================================================
# 契约测试：主题切换
# ============================================================================
class TestThemeContract:
    """主题切换契约测试。"""

    def test_build_qss_dark_light(self):
        """dark 和 light 主题都能生成 QSS。"""
        from futures_quant.ui.design_system import build_qss
        dark_qss = build_qss("dark")
        light_qss = build_qss("light")
        assert len(dark_qss) > 1000
        assert len(light_qss) > 1000

    def test_theme_colors_different(self):
        """dark 和 light 主题颜色不同。"""
        from futures_quant.ui.design_system import DESIGN
        dark = DESIGN["dark"]
        light = DESIGN["light"]
        assert dark["bg"] != light["bg"]
        assert dark["text"] != light["text"]