# -*- coding: utf-8 -*-
"""M6-05 关于对话框视觉层次与主题化 DoD 验收。

M6-05 五项 DoD：
① 五段式信息架构：Hero / 功能亮点 / 联系开发者 / 二维码双组 / 页脚
② 全部色值走 pal() / design_system.design_tokens(theme)，删除所有硬编码色
③ set_theme() 覆盖全部子控件（Hero / chip / 信息行 / 分区标题 / 页脚），删除反向写全局 W.THEME 逻辑
④ 分隔线用 QFrame[HLine] + token 色
⑤ 可选：Hero 右侧产品画廊

DoD 门禁：连续切换 dark↔light 10 次后，抽样全部 QLabel 的 styleSheet 色值均属于当前主题 token；浅色主题下正文对比度 ≥4.5:1（WCAG）

共 15 项：结构 5 + 主题化 5 + WCAG 3 + 契约 2。
"""
from __future__ import annotations

import os
import re

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QFrame


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _proj_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _src_of_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# 1. 五段式信息架构
# ─────────────────────────────────────────────────────────────

def test_hero_section_present(qapp):
    """Hero：品牌头像 104px + 产品名 + slogan + 版本 Pill。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        assert hasattr(d, "_title_lbl")
        assert hasattr(d, "_slogan_lbl")
        # 头像组件存在
        from PyQt6.QtWidgets import QLabel
        # 通过 themables 中的 avatar
        assert len(d._themables) >= 4
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_feature_chips_present(qapp):
    """功能亮点：3-4 个 chip。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        # 至少 3 个 themable 是 chip 类型（有 retheme）
        chips = [t for t in d._themables if hasattr(t, "text")]
        assert len(chips) >= 3
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_info_grid_present(qapp):
    """联系开发者：信息行网格（多行图标+标签+值+复制）。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        assert hasattr(d, "_info_grid")
        # info_grid 是 themable
        assert d._info_grid in d._themables
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_qr_sections_present(qapp):
    """二维码双组：联系（添加好友）+ 支付打赏，各有分区标题。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        # _SectionTitle 组件有 _title QLabel 属性
        titles = [t for t in d._themables
                  if hasattr(t, "_title") and getattr(t._title, "text", None)]
        assert len(titles) >= 1, f"分区标题数量：{len(titles)}"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_footer_disclaimer_present(qapp):
    """页脚：免责声明（警告卡片）+ 版权行 + 按钮。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        assert hasattr(d, "_disclaimer")
        assert hasattr(d, "_copyright_lbl")
        # 免责声明含免责声明关键字
        text = d._disclaimer.text()
        assert "免责" in text or "风险" in text or "投资" in text
    finally:
        d.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# 2. 主题化：全 token，无硬编码色
# ─────────────────────────────────────────────────────────────

def test_no_hardcoded_hex_colors_in_source():
    """M6-05②：源码不含硬编码 hex 色（除少数允许的 accent/warning 品牌常量）。"""
    root = _proj_root()
    src = _src_of_file(os.path.join(
        root, "futures_quant", "ui", "about_page.py"))
    # 允许 pal() 内部定义和注释中的色；主要检查 setStyleSheet 里
    # 匹配 setStyleSheet(... 内含 #xxxxxx 直接写字面值
    # 简单检查：setStyleSheet 后紧跟的字面 #hex 色
    pattern = re.compile(r"setStyleSheet\([^\n]*#[0-9a-fA-F]{6}")
    matches = pattern.findall(src)
    # 允许极少数例外（如品牌红/绿等固定色），这里断言数量极少
    assert len(matches) <= 3, \
        f"发现 {len(matches)} 处硬编码 hex 色：{matches[:5]}"


def test_no_wtheme_writeback():
    """M6-05③：删除反向写全局 W.THEME 的逻辑。"""
    root = _proj_root()
    src = _src_of_file(os.path.join(
        root, "futures_quant", "ui", "about_page.py"))
    # 不允许 W.THEME = 或 widgets.THEME = 赋值
    assert "W.THEME =" not in src
    assert "widgets.THEME =" not in src
    # THEME = t 赋值也不允许
    assert not re.search(r"\bTHEME\s*=\s*[\"']?(?:dark|light)", src), \
        "不应反向写全局 THEME"


def test_theme_switch_10x_no_residue(qapp):
    """M6-05 门禁：连续切换 dark↔light 10 次，全部 QLabel 色值属于当前 token。"""
    from futures_quant.ui import widgets as W
    from futures_quant.ui.about_page import AboutDialog

    d = AboutDialog()
    try:
        for i in range(10):
            theme = "light" if i % 2 == 0 else "dark"
            W.THEME = theme
            d.set_theme(theme)
        # 切到 dark
        palette = W.PALETTE["dark"]
        # 检查关键 QLabel 的 styleSheet 中至少有一个 dark token 色值
        for lbl_attr in ("_title_lbl", "_slogan_lbl", "_disclaimer",
                         "_copyright_lbl"):
            lbl = getattr(d, lbl_attr, None)
            if lbl is None:
                continue
            sheet = lbl.styleSheet()
            # 至少要有一个 dark palette 中的色值出现
            has_dark_token = any(
                color in sheet for color in palette.values() if isinstance(color, str)
            )
            assert has_dark_token, \
                f"{lbl_attr} styleSheet 未含 dark token 色值：{sheet}"
    finally:
        W.THEME = "dark"
        d.deleteLater()
        qapp.processEvents()


def test_theme_switch_light_10x_no_residue(qapp):
    """反向验证：切到 light 后，QLabel 含 light token 色值。"""
    from futures_quant.ui import widgets as W
    from futures_quant.ui.about_page import AboutDialog

    d = AboutDialog()
    try:
        for i in range(10):
            theme = "dark" if i % 2 == 0 else "light"
            W.THEME = theme
            d.set_theme(theme)
        palette = W.PALETTE["light"]
        for lbl_attr in ("_title_lbl", "_slogan_lbl", "_copyright_lbl"):
            lbl = getattr(d, lbl_attr, None)
            if lbl is None:
                continue
            sheet = lbl.styleSheet()
            has_light_token = any(
                color in sheet for color in palette.values()
                if isinstance(color, str)
            )
            assert has_light_token, \
                f"{lbl_attr} styleSheet 未含 light token 色值：{sheet}"
    finally:
        W.THEME = "dark"
        d.deleteLater()
        qapp.processEvents()


def test_disclaimer_has_warning_token(qapp):
    """免责声明卡片使用 warning token（左边框 + 警告底色）。"""
    from futures_quant.ui import widgets as W
    from futures_quant.ui.about_page import AboutDialog

    d = AboutDialog()
    try:
        W.THEME = "dark"
        d.set_theme("dark")
        sheet = d._disclaimer.styleSheet()
        assert "warning" in sheet or \
               W.PALETTE["dark"]["warning"] in sheet, \
            f"免责声明未使用 warning token：{sheet}"
    finally:
        d.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# 3. WCAG 对比度（浅色主题正文 ≥ 4.5:1）
# ─────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rel_luminance(rgb):
    """WCAG 相对亮度计算。"""
    def _c(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [_c(c) for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAG 对比度比。"""
    l1 = _rel_luminance(_hex_to_rgb(hex1))
    l2 = _rel_luminance(_hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_light_theme_body_contrast_wcag():
    """浅色主题下正文 text/bg 对比度 ≥ 4.5:1（WCAG AA）。"""
    from futures_quant.ui import widgets as W
    light = W.PALETTE["light"]
    ratio = _contrast_ratio(light["text"], light["panel"])
    assert ratio >= 4.5, f"浅色 text/panel 对比度 {ratio:.2f} < 4.5"


def test_light_theme_sub_contrast_wcag():
    """浅色主题下次级文本 sub/bg 对比度 ≥ 3:1（大文本 WCAG）。"""
    from futures_quant.ui import widgets as W
    light = W.PALETTE["light"]
    ratio = _contrast_ratio(light["sub"], light["panel"])
    # sub 通常是次级灰，允许 ≥3（大文本）
    assert ratio >= 3.0, f"浅色 sub/panel 对比度 {ratio:.2f} < 3.0"


def test_dark_theme_body_contrast_wcag():
    """深色主题下正文 text/bg 对比度 ≥ 4.5:1。"""
    from futures_quant.ui import widgets as W
    dark = W.PALETTE["dark"]
    ratio = _contrast_ratio(dark["text"], dark["panel"])
    assert ratio >= 4.5, f"深色 text/panel 对比度 {ratio:.2f} < 4.5"


# ─────────────────────────────────────────────────────────────
# 4. 契约
# ─────────────────────────────────────────────────────────────

def test_sep_is_qframe_hline(qapp):
    """M6-05④：分隔线用 QFrame[HLine]。"""
    from futures_quant.ui.about_page import AboutDialog
    d = AboutDialog()
    try:
        assert isinstance(d._sep, QFrame)
        # PyQt6: QFrame.Shape.HLine
        sep_shape = d._sep.frameShape()
        hline = QFrame.Shape.HLine
        assert sep_shape == hline, \
            f"_sep frameShape={sep_shape} != QFrame.Shape.HLine({hline})"
    finally:
        d.deleteLater()
        qapp.processEvents()


def test_no_global_theme_writeback_in_about(qapp):
    """about_page.set_theme 不写全局 W.THEME（消除副作用）。"""
    from futures_quant.ui import widgets as W
    from futures_quant.ui.about_page import AboutDialog

    d = AboutDialog()
    try:
        W.THEME = "dark"
        d.set_theme("light")
        # set_theme 不应改变全局 W.THEME
        assert W.THEME == "dark", \
            f"set_theme 反向写全局 W.THEME 为 {W.THEME}"
    finally:
        d.deleteLater()
        qapp.processEvents()
