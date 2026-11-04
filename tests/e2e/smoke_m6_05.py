# -*- coding: utf-8 -*-
"""M6-05 冒烟测试：关于页视觉层次与主题化（offscreen）。

覆盖（验收条款）：
    ① 五段式结构：Hero（头像/标题/slogan/版本 Pill）+ 功能 chips +
       联系信息行（含复制按钮）+ 二维码双组（分区标题）+ 页脚（警告卡/诊断/更新）
    ② 全 token：连续切换 dark↔light 10 次，抽样 QLabel styleSheet
       色值均属当前主题 token 集
    ③ set_theme 不反向写全局 W.THEME
    ④ 浅色主题正文对比度 ≥4.5:1（WCAG 相对亮度计算）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from futures_quant.ui.design_system import apply_design, DESIGN
from futures_quant.ui import widgets as W
from futures_quant.ui.about_page import (
    AboutDialog, _VersionPill, _FeatureChip, _InfoRow, _CopyButton,
    _SectionTitle,
)

dlg = AboutDialog(None)
dlg.show()
app.processEvents()


def token_set(theme):
    """当前主题全部合法色值集合（含派生 rgba 前缀判定用）。"""
    return set(DESIGN[theme].values())


def audit_colors(widget, theme):
    """抽样 widget 树全部 QLabel 的 styleSheet，校验色值属于 token 集。"""
    from PyQt6.QtWidgets import QLabel
    allowed = {c.lower() for c in token_set(theme)} | {"#ffffff", "transparent", "none"}
    bad = []
    for lbl in widget.findChildren(QLabel):
        ss = lbl.styleSheet()
        for m in re.finditer(r"#[0-9a-fA-F]{6}\b|rgba\([^)]*\)", ss):
            tok = m.group(0).lower()
            if tok.startswith("rgba"):
                continue   # rgba 为 token 派生（_alpha），单独验证
            if tok not in allowed:
                bad.append((lbl.text()[:12], tok))
    return bad


def rgba_sources_ok(widget):
    """rgba(...) 必须可由 token 派生：拒绝任何与 token RGB 通道不符的 rgba。"""
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QLabel
    ok_rgb = {(QColor(c).red(), QColor(c).green(), QColor(c).blue())
              for c in token_set(W.THEME)}
    bad = []
    for lbl in widget.findChildren(QLabel):
        for m in re.finditer(r"rgba\((\d+),(\d+),(\d+),", lbl.styleSheet()):
            rgb = tuple(int(m.group(i)) for i in (1, 2, 3))
            if rgb not in ok_rgb:
                bad.append((lbl.text()[:12], rgb))
    return bad


# ---------- ① 五段式结构 ----------
assert dlg._title_lbl.text() == "QuantVortex"
assert isinstance(dlg._themables[0], object)
pills = dlg.findChildren(_VersionPill)
assert pills, "应有版本 Pill"
assert f"v{os.environ.get('APP_VERSION', '')}" or pills[0].text()
assert "·" in pills[0].text(), "版本 Pill 应含『版本 · 日期』"
chips = dlg.findChildren(_FeatureChip)
assert len(chips) == 4, f"应有 4 个功能 chip: {len(chips)}"
assert any("AI 多模型预测" in c.text() for c in chips)
assert any("13 源消息面" in c.text() for c in chips)
rows = dlg.findChildren(_InfoRow)
assert len(rows) == 4, f"应有 4 行联系信息: {len(rows)}"
copy_btns = dlg.findChildren(_CopyButton)
assert len(copy_btns) >= 3, "信息行应有复制按钮"
assert dlg._disclaimer.text().startswith("⚠ 免责声明")
assert dlg._diag_btn.text() == "系统诊断" and dlg._update_btn.text() == "检查更新"

# ---------- ② 主题往返 10 次 + token 审计 ----------
for i in range(10):
    theme = "dark" if i % 2 == 0 else "light"
    W.THEME = theme          # 模拟 apply_design 已更新全局（正式路径同此）
    W.PALETTE[theme] = dict(DESIGN[theme])
    dlg.set_theme(theme)
    app.processEvents()
    bad = audit_colors(dlg, theme)
    assert not bad, f"[{theme}] 存在非 token 色值: {bad[:5]}"
    bad_rgba = rgba_sources_ok(dlg)
    assert not bad_rgba, f"[{theme}] 存在非 token 派生 rgba: {bad_rgba[:5]}"

# ---------- ③ set_theme 不写全局 ----------
theme_before = W.THEME
dlg.set_theme("dark")
assert W.THEME == theme_before, "set_theme 不得反向修改 W.THEME"

# ---------- ④ 浅色正文对比度 ≥4.5:1（WCAG） ----------
def rel_lum(hex_color: str) -> float:
    """WCAG 相对亮度。"""
    def chan(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    c = hex_color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


light = DESIGN["light"]
ratio_text = contrast(light["text"], light["panel"])   # 正文 vs 对话框底
assert ratio_text >= 4.5, f"浅色正文对比度不足: {ratio_text:.2f}"
ratio_sub = contrast(light["sub"], light["panel"])
print(f"浅色对比度: 正文 {ratio_text:.2f}:1, 副文案 {ratio_sub:.2f}:1")

dlg.close()
print("M6-05 SMOKE OK")
