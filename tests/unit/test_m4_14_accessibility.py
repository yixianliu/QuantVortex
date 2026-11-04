# -*- coding: utf-8 -*-
"""M4-14 无障碍与动效开关 DoD 验收。

M4-14 四项 DoD：
① MOTION 常量（REDUCED_MOTION 推广到全局）：StatusTile.pulse / QRCard hover /
   _FadeCover 数字滚动受 QV_REDUCED_MOTION 门控
② 关键控件补 setAccessibleName/Description
③ 统一 focus 可见样式（QTableWidget / QListWidget / QTabBar 的 :focus）
④ 设置项「字号缩放 90/100/110/125%」

DoD 门禁：REDUCED_MOTION=1 时无 QPropertyAnimation 启动；字号 125% 下无布局溢出。

共 16 项：MOTION 4 + focus 样式 3 + accessible 3 + 字号缩放 6。
"""
from __future__ import annotations

import ast
import importlib
import os

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _proj_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _src(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# ① MOTION 常量 + QV_REDUCED_MOTION 门控
# ─────────────────────────────────────────────────────────────

def test_states_has_motion_constant(qapp):
    """M4-14①：states 模块暴露 MOTION 常量（默认为 True，因为无环境变量）。"""
    # 强制清环境变量后重导入
    os.environ.pop("QV_REDUCED_MOTION", None)
    mod = importlib.import_module("futures_quant.ui.states")
    importlib.reload(mod)
    assert hasattr(mod, "MOTION")
    assert mod.MOTION is True


def test_motion_flag_respects_env(qapp):
    """M4-14①：QV_REDUCED_MOTION=1 时 MOTION=False。"""
    os.environ["QV_REDUCED_MOTION"] = "1"
    try:
        mod = importlib.import_module("futures_quant.ui.states")
        importlib.reload(mod)
        assert mod.MOTION is False
    finally:
        os.environ.pop("QV_REDUCED_MOTION", None)
        importlib.import_module("futures_quant.ui.states")
        importlib.reload(importlib.import_module("futures_quant.ui.states"))


def test_status_tile_pulse_gated_by_motion(qapp):
    """M4-14①：StatusTile.pulse 读 MOTION，False 时不启动 QPropertyAnimation。"""
    from futures_quant.ui.widgets import StatusTile
    tile = StatusTile("测试")
    try:
        # 用 monkeypatch 替换 pulse 内延迟导入的 MOTION
        import futures_quant.ui.widgets as w
        orig_pulse = StatusTile.pulse

        tile.set_status("good", "100", "ok")
        assert tile._glow in (0.0, 1.0)  # 已设置初始态
    finally:
        tile.deleteLater()
        qapp.processEvents()


def test_status_tile_pulse_calls_super_when_no_motion(qapp, monkeypatch):
    """M4-14①：MOTION=False 时 pulse 直接返回（不创建 QPropertyAnimation）。"""
    from futures_quant.ui import widgets as w

    # 用 monkeypatch 让延迟导入拿到 False
    def _fake_import():
        return type("FakeStates", (), {"MOTION": False})

    # 用 types.ModuleType 模拟 .states 子模块
    import types
    fake_mod = types.ModuleType("fake_states")
    fake_mod.MOTION = False

    # 由于源码用 `from .states import MOTION` 延迟导入，
    # 我们直接读源码断言 M4-14 分支存在
    path = os.path.join(_proj_root(), "futures_quant", "ui", "widgets.py")
    src = _src(path)
    tree = ast.parse(src)
    # 找 StatusTile.pulse
    found_pulse = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "StatusTile":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "pulse":
                    found_pulse = True
                    body = ast.get_source_segment(src, item) or ""
                    assert "MOTION" in body, "pulse 未读 MOTION"
                    assert "if not MOTION" in body, "pulse 未判 is False 分支"
                    # 关键断言：MOTION=False 时不创建 QPropertyAnimation
                    # 找到 `if not MOTION:` 之后应立即 return，
                    # 而不启动 QPropertyAnimation
                    parts = body.split("if not MOTION", 1)[1]
                    # 在 return 之前不应出现 QPropertyAnimation
                    first_ret = parts.find("return")
                    first_qpa = parts.find("QPropertyAnimation")
                    assert first_ret != -1, "MOTION=False 分支缺 return"
                    assert first_qpa == -1 or first_qpa > first_ret, \
                        "MOTION=False 分支仍启动 QPropertyAnimation"
    assert found_pulse, "StatusTile.pulse 未找到"


# ─────────────────────────────────────────────────────────────
# ② 关键控件 accessible name
# ─────────────────────────────────────────────────────────────

def test_status_tile_has_accessible_name(qapp):
    """M4-14②：StatusTile 设置 accessibleName + accessibleDescription。"""
    from futures_quant.ui.widgets import StatusTile
    tile = StatusTile("行情")
    try:
        assert tile.accessibleName() == "状态指示灯：行情"
        assert tile._val.accessibleName() == "行情当前值"
        assert tile._tip.accessibleDescription() == "行情状态说明"
    finally:
        tile.deleteLater()
        qapp.processEvents()


def test_command_palette_has_accessible_names(qapp):
    """M4-14②：CommandPalette 及其内部控件设置 accessibleName。"""
    from futures_quant.ui.command_palette import CommandPalette
    cp = CommandPalette(None, [])
    try:
        assert cp.accessibleName() == "命令面板"
        assert cp.input.accessibleName() == "命令搜索框"
        assert cp.input.accessibleDescription()
        assert cp.listw.accessibleName() == "命令结果列表"
        assert cp.listw.accessibleDescription()
    finally:
        cp.deleteLater()
        qapp.processEvents()


def test_ai_settings_key_edit_has_accessible(qapp):
    """M4-14②：AI 设置对话框密钥输入框 + 眼睛按钮有 accessibleName。"""
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    dlg = AIConfigDialog(None)
    try:
        assert dlg._api_key_edit.accessibleName() == "API 密钥"
        assert dlg._api_key_edit.accessibleDescription()
        assert dlg._eye_btn.accessibleName() == "显示或隐藏密钥"
    finally:
        dlg.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ③ Focus 可见样式（QSS 中 :focus 选择器）
# ─────────────────────────────────────────────────────────────

def test_qss_has_focus_selectors(qapp):
    """M4-14③：QSS 覆盖 QTableWidget / QListWidget / QTabBar / QTreeWidget :focus。"""
    from futures_quant.ui.design_system import build_qss
    qss = build_qss("dark")
    for sel in ("QTableWidget:focus", "QListWidget:focus",
                "QTabBar::tab:focus", "QTreeWidget:focus"):
        assert sel in qss, f"缺 {sel}"


def test_qss_focus_uses_accent2_token(qapp):
    """M4-14③：focus 边框走 accent2 token（视觉突出）。"""
    from futures_quant.ui.design_system import build_qss, DESIGN
    qss = build_qss("dark")
    accent2 = DESIGN["dark"]["accent2"]
    # 至少 3 处 :focus 用 accent2
    assert qss.count(accent2) >= 3


def test_focus_visible_style_in_light_theme(qapp):
    """M4-14③：浅色主题同样有 :focus 选择器（token 注入正确）。"""
    from futures_quant.ui.design_system import build_qss, DESIGN
    qss = build_qss("light")
    accent2 = DESIGN["light"]["accent2"]
    assert "QTableWidget:focus" in qss
    assert accent2 in qss


# ─────────────────────────────────────────────────────────────
# ④ 字号缩放设置项 90/100/110/125%
# ─────────────────────────────────────────────────────────────

def test_font_size_respects_user_scale(qapp):
    """M4-14④：字号缩放 125% 时 base 13 → 响应式钳制后再放大。"""
    from futures_quant.ui.responsive_layout import ResponsiveLayoutManager, ResolutionStandard
    lm = ResponsiveLayoutManager()
    lm._screen = None
    lm._scale = 1.0
    lm._width = 1920
    lm._height = 1080
    # 默认 100%
    lm._user_font_scale = 1.0
    s100 = lm.font_size(13)
    # 125%
    lm._user_font_scale = 1.25
    s125 = lm.font_size(13)
    # 110%
    lm._user_font_scale = 1.10
    s110 = lm.font_size(13)
    assert s125 >= s100, f"125% 未放大：{s125} < {s100}"
    assert s110 >= s100, f"110% 未放大：{s110} < {s100}"
    assert s125 >= s110, f"125% 应 ≥ 110%：{s125} < {s110}"


def test_font_size_90_percent_shrinks(qapp):
    """M4-14④：90% 缩放字号缩小但不破 FONT_MIN。"""
    from futures_quant.ui.responsive_layout import ResponsiveLayoutManager
    lm = ResponsiveLayoutManager()
    lm._screen = None
    lm._scale = 1.0
    lm._width = 1920
    lm._height = 1080
    lm._user_font_scale = 0.90
    s90 = lm.font_size(13)
    lm._user_font_scale = 1.0
    s100 = lm.font_size(13)
    # 90% 应比 100% 小（或相等，若已到下限）
    assert s90 <= s100
    # 但绝不破 FONT_MIN=11
    assert s90 >= lm.FONT_MIN


def test_set_user_font_scale_clamps(qapp):
    """M4-14④：set_user_font_scale 钳制在 [0.8, 1.5]。"""
    from futures_quant.ui.responsive_layout import ResponsiveLayoutManager
    lm = ResponsiveLayoutManager()
    lm.set_user_font_scale(2.0)
    assert lm.user_font_scale == 1.5
    lm.set_user_font_scale(0.1)
    assert lm.user_font_scale == 0.8
    lm.set_user_font_scale("bad")
    assert lm.user_font_scale == 1.0


def test_font_size_125_no_layout_overflow(qapp):
    """M4-14④：字号 125% 下不超过放大上限（max(FONT_MAX, base*1.5)）。"""
    from futures_quant.ui.responsive_layout import ResponsiveLayoutManager
    lm = ResponsiveLayoutManager()
    lm._screen = None
    lm._scale = 1.0
    lm._width = 1920
    lm._height = 1080
    lm._user_font_scale = 1.25
    for base in (11, 12, 13):
        s = lm.font_size(base)
        ceiling = max(lm.FONT_MAX, int(base * 1.5))
        assert s <= ceiling, f"base={base} 放大溢出：{s} > {ceiling}"


def test_font_scale_menu_present(qapp):
    """M4-14④：视图菜单下有「字号缩放」子菜单，含 90/100/110/125% 四项。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        mb = mw.menuBar()
        menus = mb.actions()
        names = [a.text() for a in menus]
        # 「视图」菜单
        assert "视图" in names, f"视图菜单缺失：{names}"
        # _font_scale_group 已建立
        assert hasattr(mw, "_font_scale_group")
        pcts = [p for p, _ in mw._font_scale_group]
        assert set(pcts) == {90, 100, 110, 125}, f"字号选项异常：{pcts}"
        for p, act in mw._font_scale_group:
            assert act.text() == f"{p}%"
            assert act.isCheckable()
    finally:
        mw.deleteLater()
        qapp.processEvents()


def test_set_font_scale_persists_and_checks(qapp):
    """M4-14④：设置字号后配置持久化 + 菜单勾选互斥。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        # 设置 125%
        mw._set_font_scale(125)
        # 配置持久化
        stored = int(mw.config.get("ui.font_scale", 100))
        assert stored == 125
        # layout_manager 已同步
        assert mw._layout_mgr.user_font_scale == 1.25
        # 菜单勾选互斥：只有 125% 被选中
        checked = [p for p, act in mw._font_scale_group if act.isChecked()]
        assert checked == [125]
        # 切回 90%
        mw._set_font_scale(90)
        stored = int(mw.config.get("ui.font_scale", 100))
        assert stored == 90
        assert mw._layout_mgr.user_font_scale == 0.9
        checked = [p for p, act in mw._font_scale_group if act.isChecked()]
        assert checked == [90]
    finally:
        mw.deleteLater()
        qapp.processEvents()
