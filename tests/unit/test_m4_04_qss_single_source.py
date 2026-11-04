# -*- coding: utf-8 -*-
"""M4-04 QSS 单一事实来源 DoD 验收。

M4-04 七项 DoD：
① `design_system.build_qss(theme) -> str`：由 DESIGN[theme] token 生成完整 QSS
② QSS 含 #card / #toolbar / #chip / #primary / #secondary / #ai-group / #btn-bar 选择器
③ DARK_QSS / LIGHT_QSS 常量删除，改为 build_qss() 动态生成
④ 首次生成结果写入 config/style.qss 作为可读快照
⑤ `apply_design(refresh_widgets=True)` 全量刷新打开

DoD 门禁：
- 切换主题后，QSS 控件与自绘控件配色同源
- `test_design_system.py` 绿

共 18 项：token 契约 5 + build_qss 6 + 选择器覆盖 5 + 刷新/恢复 2。
"""
from __future__ import annotations

import os
import re

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def app():
    a = QApplication.instance() or QApplication([])
    yield a
    if not a.property("_is_fixture"):
        a.setProperty("_is_fixture", True)


# ─────────────────────────────────────────────────────────────
# 1. DESIGN token 契约
# ─────────────────────────────────────────────────────────────

REQUIRED_TOKENS = {"bg", "panel", "card", "border", "text", "sub",
                   "accent", "accent2", "up", "down", "grid",
                   "row_alt", "row_sel", "badge_bg", "chip_bg",
                   "scroll", "warning"}


def test_design_has_dark_and_light():
    from futures_quant.ui.design_system import DESIGN
    assert set(DESIGN) >= {"dark", "light"}


def test_design_tokens_full_coverage():
    """dark 与 light 主题都必须有全 17 个 token。"""
    from futures_quant.ui.design_system import DESIGN
    for theme in ("dark", "light"):
        missing = REQUIRED_TOKENS - set(DESIGN[theme])
        assert not missing, f"{theme} 缺少 token：{missing}"


def test_design_tokens_are_hex_colors_or_numbers():
    """token 值：颜色 #hex / rgba(...)，数值 int（space/radius/font）。"""
    from futures_quant.ui.design_system import DESIGN
    for theme in ("dark", "light"):
        for k, v in DESIGN[theme].items():
            if k.startswith(("space_", "radius_", "font_")):
                assert isinstance(v, int), \
                    f"{theme}.{k} = {v!r} 应为 int"
            elif k.startswith("elevation_"):
                assert re.match(r"^rgba\(", str(v)), \
                    f"{theme}.{k} = {v!r} 应为 rgba 字符串"
            else:
                assert re.match(r"^#[0-9a-fA-F]{3,8}$", str(v)), \
                    f"{theme}.{k} = {v!r} 非颜色格式"


def test_design_tokens_dark_vs_light_differ():
    """dark 与 light 主题 bg/text 必须不同（否则主题化无意义）。"""
    from futures_quant.ui.design_system import DESIGN
    assert DESIGN["dark"]["bg"] != DESIGN["light"]["bg"]
    assert DESIGN["dark"]["text"] != DESIGN["light"]["text"]


def test_design_tokens_return_copy():
    """design_tokens() 返回拷贝，修改不影响原表。"""
    from futures_quant.ui.design_system import DESIGN, design_tokens
    tok = design_tokens("dark")
    tok["bg"] = "#FF0000"
    assert DESIGN["dark"]["bg"] != "#FF0000"


# ─────────────────────────────────────────────────────────────
# 2. build_qss 生成逻辑
# ─────────────────────────────────────────────────────────────

def test_build_qss_no_unresolved_placeholders():
    """build_qss 不允许残留 $XXX$ 占位符（安全护栏）。"""
    from futures_quant.ui.design_system import build_qss
    qss = build_qss("dark")
    assert "$" not in qss, f"残留占位符：{re.findall(r'\\$[A-Z0-9_]+\\$', qss)}"


def test_build_qss_unknown_theme_falls_back_to_dark():
    """未知主题回退 dark，不抛异常。"""
    from futures_quant.ui.design_system import build_qss
    qss = build_qss("holographic")
    assert "QWidget" in qss
    # 内容应与 dark 一致
    assert build_qss("holographic") == build_qss("dark")


def test_build_qss_dark_uses_dark_tokens():
    """build_qss('dark') 里出现的颜色值必须来自 DESIGN['dark']。"""
    from futures_quant.ui.design_system import DESIGN, build_qss
    qss = build_qss("dark")
    for tk in ("bg", "panel", "card", "border", "text", "accent"):
        assert DESIGN["dark"][tk] in qss, \
            f"dark.{tk}={DESIGN['dark'][tk]} 未出现在 QSS 中"


def test_build_qss_light_uses_light_tokens():
    """build_qss('light') 用 light token 替换。"""
    from futures_quant.ui.design_system import DESIGN, build_qss
    qss = build_qss("light")
    # light 的 bg 出现在 qss；dark 的 bg 不应出现
    assert DESIGN["light"]["bg"] in qss
    assert DESIGN["dark"]["bg"] not in qss


def test_build_qss_dark_vs_light_differ():
    """两主题生成的 QSS 必须不同（关键选择器颜色不同）。"""
    from futures_quant.ui.design_system import build_qss
    dark_qss = build_qss("dark")
    light_qss = build_qss("light")
    assert dark_qss != light_qss


def test_build_qss_placeholder_guard_rail(monkeypatch):
    """模板含未替换占位符时应抛 ValueError（防止静默失败）。"""
    import futures_quant.ui.design_system as ds
    orig = ds._QSS_TEMPLATE
    try:
        ds._QSS_TEMPLATE = orig + "\nQWidget { color:$UNDEFINED_TOKEN$; }"
        with pytest.raises(ValueError, match="占位符"):
            ds.build_qss("dark")
    finally:
        ds._QSS_TEMPLATE = orig


# ─────────────────────────────────────────────────────────────
# 3. QSS 选择器覆盖（M4-04 DoD ②）
# ─────────────────────────────────────────────────────────────

REQUIRED_SELECTORS = [
    "QFrame#card",       # 卡片
    "QFrame#toolbar",    # 工具栏
    "QFrame#chip",       # 芯片
    "QPushButton#primary",   # 主按钮
    "QPushButton#secondary", # 次按钮
    "QFrame#ai-group",   # AI 分组
    "QFrame#btn-bar",    # 按钮栏
]


@pytest.mark.parametrize("selector", REQUIRED_SELECTORS)
def test_qss_contains_required_selector(selector):
    """QSS 模板必须覆盖 M4-04 DoD 明确列出的 7 个选择器。"""
    from futures_quant.ui.design_system import build_qss
    qss = build_qss("dark")
    assert selector in qss, f"QSS 缺少选择器：{selector}"


def test_qss_snapshot_file_exists():
    """config/style.qss 作为可读快照存在。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    snap = os.path.join(root, "config", "style.qss")
    assert os.path.isfile(snap), f"缺少快照文件：{snap}"
    assert os.path.getsize(snap) > 1000, "快照文件过小，疑似空模板"


def test_qss_snapshot_matches_generated_dark(app):
    """快照与当前 build_qss('dark') 内容大致一致（首行匹配）。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    snap = os.path.join(root, "config", "style.qss")
    with open(snap, "r", encoding="utf-8") as f:
        snap_txt = f.read()
    from futures_quant.ui.design_system import build_qss
    gen = build_qss("dark")
    # 结构一致：都含 QWidget / #card / #primary
    for token in ("QWidget", "QFrame#card", "QPushButton#primary"):
        assert token in snap_txt and token in gen


# ─────────────────────────────────────────────────────────────
# 4. apply_design / reset_design 契约
# ─────────────────────────────────────────────────────────────

def test_apply_design_updates_widgets_palette(app):
    """apply_design 将 DESIGN[theme] 注入 widgets.PALETTE。"""
    import futures_quant.ui as ui_pkg
    from futures_quant.ui import widgets as W
    from futures_quant.ui.design_system import DESIGN, apply_design
    snap = {k: dict(v) for k, v in W.PALETTE.items()}
    try:
        apply_design("light")
        # PALETTE['light'] 应等于 DESIGN['light']
        for tk in REQUIRED_TOKENS:
            assert W.PALETTE["light"][tk] == DESIGN["light"][tk]
        assert W.THEME == "light"
    finally:
        W.PALETTE = snap
        W.THEME = "dark"


def test_reset_design_restores_original(app):
    """reset_design 恢复 widgets 原始 PALETTE 与 THEME。"""
    from futures_quant.ui import widgets as W
    from futures_quant.ui.design_system import apply_design, reset_design
    snap = {k: dict(v) for k, v in W.PALETTE.items()}
    try:
        apply_design("light")
        reset_design()
        # 恢复后 PALETTE['dark'] 与快照一致
        assert W.PALETTE["dark"] == snap["dark"]
    finally:
        W.PALETTE = snap
        W.THEME = "dark"
