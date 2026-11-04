"""UX Phase 7 契约测试：4 组契约验证。

覆盖 UX-82 要求：
1. Token 完整性：DESIGN 双主题所有 token 键值完整
2. QSS 无残留占位：build_qss 输出无 $ 占位符
3. 主题切换 N 次无残留样式：apply_design 多次切换无残留
4. 键盘可达：焦点环、Tab 顺序、快捷键

运行方式：
    QT_QPA_PLATFORM=offscreen pytest tests/unit/contracts/test_ux_contracts.py -v
"""
from __future__ import annotations

import os
import sys
import pytest
import re

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

os.environ["QUANTVORTEX_NO_PERSIST"] = "1"


# ============================================================================
# 契约 1: Token 完整性
# ============================================================================
class TestTokenCompleteness:
    """契约 1: DESIGN Token 完整性。

    DoD: 双主题所有 token 键值完整，无缺失。
    """

    # 必须存在的核心 token 键
    REQUIRED_KEYS = {
        "bg", "panel", "card", "border", "grid",
        "text", "sub", "accent", "accent2",
        "up", "down", "warning",
        "row_alt", "row_sel", "badge_bg", "chip_bg", "scroll",
        # Token v2 (UX-05)
        "radius_sm", "radius_md", "radius_lg", "radius_pill",
        "space_xs", "space_sm", "space_md", "space_lg", "space_xl",
        "space_1", "space_2", "space_3", "space_5", "space_6",
        "space_7", "space_9", "space_10", "space_14", "space_18",
        "space_20", "space_26", "space_32",
        "font_caption", "font_body", "font_h3", "font_h2", "font_h1",
        "elevation_e1", "elevation_e2", "elevation_e3",
        "chart_series_1", "chart_series_2", "chart_series_3",
        "chart_series_4", "chart_series_5", "chart_series_6",
    }

    def test_dark_theme_has_all_required_keys(self):
        """dark 主题包含所有必需 token。"""
        from futures_quant.ui.design_system import DESIGN
        dark = DESIGN["dark"]
        missing = self.REQUIRED_KEYS - set(dark.keys())
        assert len(missing) == 0, f"Missing keys in dark theme: {missing}"

    def test_light_theme_has_all_required_keys(self):
        """light 主题包含所有必需 token。"""
        from futures_quant.ui.design_system import DESIGN
        light = DESIGN["light"]
        missing = self.REQUIRED_KEYS - set(light.keys())
        assert len(missing) == 0, f"Missing keys in light theme: {missing}"

    def test_dark_light_same_keys(self):
        """dark 和 light 主题键集合一致。"""
        from futures_quant.ui.design_system import DESIGN
        dark_keys = set(DESIGN["dark"].keys())
        light_keys = set(DESIGN["light"].keys())
        assert dark_keys == light_keys, \
            f"Key mismatch: dark-only={dark_keys - light_keys}, light-only={light_keys - dark_keys}"

    def test_color_tokens_are_hex(self):
        """颜色 token 是有效的 hex 格式。"""
        from futures_quant.ui.design_system import DESIGN
        color_keys = {"bg", "panel", "card", "border", "grid",
                       "text", "sub", "accent", "accent2",
                       "up", "down", "warning",
                       "row_alt", "row_sel", "badge_bg", "chip_bg", "scroll",
                       "chart_series_1", "chart_series_2", "chart_series_3",
                       "chart_series_4", "chart_series_5", "chart_series_6"}
        hex_pattern = re.compile(r"^#[0-9a-fA-F]{6}$")
        for theme in ("dark", "light"):
            for key in color_keys:
                val = DESIGN[theme].get(key, "")
                assert hex_pattern.match(val), \
                    f"{theme}.{key}={val} is not valid hex color"

    def test_numeric_tokens_are_positive(self):
        """数值 token 是正数。"""
        from futures_quant.ui.design_system import DESIGN
        numeric_keys = {"radius_sm", "radius_md", "radius_lg", "radius_pill",
                        "space_xs", "space_sm", "space_md", "space_lg", "space_xl",
                        "space_1", "space_2", "space_3", "space_5", "space_6",
                        "space_7", "space_9", "space_10", "space_14", "space_18",
                        "space_20", "space_26", "space_32",
                        "font_caption", "font_body", "font_h3", "font_h2", "font_h1"}
        for theme in ("dark", "light"):
            for key in numeric_keys:
                val = DESIGN[theme].get(key, 0)
                assert isinstance(val, int) and val > 0, \
                    f"{theme}.{key}={val} is not positive int"

    def test_elevation_tokens_are_rgba(self):
        """elevation token 是 rgba 格式。"""
        from futures_quant.ui.design_system import DESIGN
        rgba_pattern = re.compile(r"^rgba\([^)]+\)$")
        for theme in ("dark", "light"):
            for key in ("elevation_e1", "elevation_e2", "elevation_e3"):
                val = DESIGN[theme].get(key, "")
                assert rgba_pattern.match(val), \
                    f"{theme}.{key}={val} is not valid rgba"

    def test_design_tokens_function_returns_copy(self):
        """design_tokens 函数返回拷贝而非引用。"""
        from futures_quant.ui.design_system import design_tokens, DESIGN
        tokens = design_tokens("dark")
        tokens["bg"] = "#000000"  # 修改拷贝
        assert DESIGN["dark"]["bg"] != "#000000", "design_tokens should return copy"


# ============================================================================
# 契约 2: QSS 无残留占位
# ============================================================================
class TestQSSNoResidualPlaceholders:
    """契约 2: build_qss 输出无残留 $ 占位符。

    DoD: 主题切换后 QSS 无任何 $...$ 未替换占位。
    """

    def test_build_qss_dark_no_residual(self):
        """dark 主题 QSS 无残留占位符。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "$" not in qss, f"Residual $ in dark QSS: {qss[:200]}"

    def test_build_qss_light_no_residual(self):
        """light 主题 QSS 无残留占位符。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("light")
        assert "$" not in qss, f"Residual $ in light QSS: {qss[:200]}"

    def test_qss_template_has_expected_placeholders(self):
        """QSS 模板包含预期的占位符。"""
        from futures_quant.ui.design_system import _QSS_TEMPLATE
        expected = ["$BG$", "$TEXT$", "$PANEL$", "$BORDER$", "$CARD$",
                    "$ACCENT$", "$ACCENT2$", "$UP$", "$GRID$", "$SUB$"]
        for ph in expected:
            assert ph in _QSS_TEMPLATE, f"{ph} not found in template"

    def test_all_template_placeholders_mapped(self):
        """模板中所有占位符都被 build_qss 的 mapping 覆盖（无未映射残留）。"""
        # 通过 build_qss 输出验证：所有 $ 都应被替换掉
        from futures_quant.ui.design_system import build_qss
        for theme_name in ("dark", "light"):
            qss = build_qss(theme_name)
            # 提取残留的 $word$ 形式
            residual = re.findall(r"\$[A-Za-z0-9_]+\$", qss)
            assert not residual, \
                f"[{theme_name}] Residual placeholders after build_qss: {residual}"

    def test_qss_contains_focus_visible(self):
        """QSS 包含 focus-visible 样式（UX-74）。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert ":focus-visible" in qss, "focus-visible not found in QSS"

    def test_qss_contains_top_tabs(self):
        """QSS 包含 top-tabs 样式（UX-62）。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "top-tabs" in qss, "top-tabs not found in QSS"

    def test_qss_contains_page_header(self):
        """QSS 包含 page-header 样式（UX-61）。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "page-header" in qss, "page-header not found in QSS"

    def test_qss_length_reasonable(self):
        """QSS 长度合理（>1000 字符）。"""
        from futures_quant.ui.design_system import build_qss
        for theme in ("dark", "light"):
            qss = build_qss(theme)
            assert len(qss) > 1000, f"{theme} QSS too short: {len(qss)} chars"


# ============================================================================
# 契约 3: 主题切换无残留样式
# ============================================================================
class TestThemeSwitchNoResidual:
    """契约 3: 主题切换 N 次无残留样式。

    DoD: apply_design 多次切换后 PALETTE 一致，无残留。
    """

    def test_apply_design_dark_then_light(self):
        """dark → light 切换后 PALETTE 一致。"""
        from futures_quant.ui.design_system import apply_design, DESIGN
        from futures_quant.ui import widgets as W
        # 记录初始状态
        initial_palette = {k: dict(v) for k, v in W.PALETTE.items()}
        # 切换到 dark
        apply_design("dark")
        assert W.PALETTE["dark"] == DESIGN["dark"]
        # 切换到 light
        apply_design("light")
        assert W.PALETTE["light"] == DESIGN["light"]
        # 恢复
        apply_design("dark")
        assert W.PALETTE["dark"] == DESIGN["dark"]

    def test_apply_design_multiple_times(self):
        """多次切换后 PALETTE 仍与 DESIGN 一致。"""
        from futures_quant.ui.design_system import apply_design, DESIGN
        from futures_quant.ui import widgets as W
        for _ in range(10):
            apply_design("dark")
            apply_design("light")
        assert W.PALETTE["dark"] == DESIGN["dark"]
        assert W.PALETTE["light"] == DESIGN["light"]

    def test_apply_design_returns_tokens(self):
        """apply_design 返回 token 字典。"""
        from futures_quant.ui.design_system import apply_design
        tokens = apply_design("dark")
        assert isinstance(tokens, dict)
        assert "bg" in tokens
        assert "text" in tokens

    def test_apply_design_refreshes_widgets(self):
        """apply_design 刷新 widgets.PALETTE。"""
        from futures_quant.ui.design_system import apply_design, DESIGN
        from futures_quant.ui import widgets as W
        # 先修改 widgets.PALETTE
        W.PALETTE["dark"]["bg"] = "#000000"
        # 应用设计应恢复
        apply_design("dark")
        assert W.PALETTE["dark"]["bg"] == DESIGN["dark"]["bg"]

    def test_reset_design_restores_original(self):
        """reset_design 恢复原始 PALETTE。"""
        from futures_quant.ui.design_system import apply_design, reset_design
        from futures_quant.ui import widgets as W
        # 记录原始
        original = {k: dict(v) for k, v in W.PALETTE.items()}
        # 应用设计
        apply_design("light")
        # 重置
        reset_design()
        # 验证恢复
        for theme in original:
            assert W.PALETTE[theme] == original[theme], \
                f"Theme {theme} not restored after reset"


# ============================================================================
# 契约 4: 键盘可达
# ============================================================================
class TestKeyboardAccessible:
    """契约 4: 键盘可达性。

    DoD: 焦点环、Tab 顺序、快捷键均正确配置。
    """

    @pytest.fixture(scope="class")
    def app(self):
        """创建 QApplication 实例。"""
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        yield app
        app.processEvents()

    def test_focus_visible_in_qss(self):
        """QSS 包含 focus-visible 样式。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        focus_count = qss.count(":focus-visible")
        assert focus_count >= 10, f"Expected >=10 focus-visible, got {focus_count}"

    def test_focus_visible_button(self):
        """QPushButton 有 focus-visible 样式。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QPushButton:focus-visible" in qss

    def test_focus_visible_lineedit(self):
        """QLineEdit 有 focus-visible 样式。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QLineEdit:focus-visible" in qss

    def test_focus_visible_combobox(self):
        """QComboBox 有 focus-visible 样式。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QComboBox:focus-visible" in qss

    def test_focus_visible_checkbox(self):
        """QCheckBox 有 focus-visible 样式。"""
        from futures_quant.ui.design_system import build_qss
        qss = build_qss("dark")
        assert "QCheckBox:focus-visible" in qss

    def test_nav_has_accessible_name(self, app):
        """导航栏有 accessibleName。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        w.show()
        app.processEvents()
        assert w.nav.accessibleName() == "主导航"
        w.deleteLater()
        app.processEvents()

    def test_nav_has_whats_this(self, app):
        """导航栏有 whatsThis 帮助文本。"""
        from futures_quant.ui.main_window import MainWindow
        w = MainWindow()
        w.show()
        app.processEvents()
        whats = w.nav.whatsThis()
        assert len(whats) > 50, f"whatsThis too short: {len(whats)}"
        w.deleteLater()
        app.processEvents()

    def test_market_overview_has_tab_order(self):
        """MarketOverviewPage 有 _setup_tab_order 方法。"""
        from futures_quant.ui.market_overview_page import MarketOverviewPage
        assert hasattr(MarketOverviewPage, "_setup_tab_order")

    def test_predict_ops_has_tab_order(self):
        """PredictOpsPage 有 _setup_tab_order 方法。"""
        from futures_quant.ui.predict_ops_page import PredictOpsPage
        assert hasattr(PredictOpsPage, "_setup_tab_order")

    def test_motion_gate_exists(self):
        """MOTION 门控存在。"""
        from futures_quant.ui.states import MOTION, motion_enabled
        assert isinstance(MOTION, bool)
        assert callable(motion_enabled)

    def test_motion_gate_function_works(self):
        """motion_enabled 函数工作正常。"""
        from futures_quant.ui.states import MOTION, motion_enabled
        assert motion_enabled() == MOTION


# ============================================================================
# 汇总
# ============================================================================
if __name__ == "__main__":
    # 直接运行时显示汇总
    import pytest
    pytest.main([__file__, "-v"])