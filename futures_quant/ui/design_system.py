"""M1.2 设计系统（Design Tokens）：统一主色板 + 主题切换「一键全量刷新」。

背景（UPGRADE_PLAN M1.2）：
- 既有的 ``widgets.PALETTE`` 使用较暗的 ``#0f1116`` 背景与 ``#ef4444/#22c55e``
  涨跌色；专业设计规范要求统一为：主背景 ``#1e1e2e``、文本 ``#dcdcdc``、
  上涨 ``#ff4757``、下跌 ``#2ed573``。
- 本模块作为「单一事实来源」（single source of truth）：
  - ``DESIGN`` 定义上述规范色板（dark + light 双主题）；
  - ``apply_design()`` 把 ``DESIGN`` 注入 ``widgets.PALETTE``，并刷新所有已挂
    页面 / 图表 / 自绘控件的主题（一次调用完成全量刷新，消除页面级 inline
    setStyleSheet 不随主题切换刷新的历史缺陷）；
  - 颜色常量对外只读暴露（``BG`` / ``TEXT`` / ``UP`` / ``DOWN`` / ``ACCENT``），
    供 QSS 生成、自绘控件、报告导出等复用，避免硬编码散落。

非破坏式：
- 既可直接 ``from .design_system import DESIGN, apply_design``；
- 也可通过 ``DESIGN_OVERRIDE`` 关闭覆盖（恢复 widgets 原 PALETTE），便于回归。
"""
from __future__ import annotations

from typing import Dict, Optional

__all__ = [
    "DESIGN",
    "BG", "TEXT", "UP", "DOWN", "ACCENT", "SUB", "BORDER", "CARD",
    "apply_design",
    "reset_design",
    "design_tokens",
]

# ---- 规范色板（UPGRADE_PLAN M1.2 指定值）----
# dark 主背景 #1e1e2e、文本 #dcdcdc、上涨 #ff4757、下跌 #2ed573
DESIGN: Dict[str, Dict[str, str]] = {
    "dark": dict(
        bg="#1e1e2e", panel="#181825", card="#27273a", border="#45455f",
        text="#dcdcdc", sub="#8b93a7", accent="#7aa2f7", accent2="#3b82f6",
        up="#ff4757", down="#2ed573", grid="#2a2a3a",
        row_alt="#23233a", row_sel="#33335a", badge_bg="#313148",
        chip_bg="#27273a", scroll="#45455f",
    ),
    "light": dict(
        bg="#f5f7fa", panel="#eef2f7", card="#ffffff", border="#d1d5db",
        text="#1f2937", sub="#6b7280", accent="#2563eb", accent2="#3b82f6",
        up="#ff4757", down="#2ed573", grid="#e5e7eb",
        row_alt="#f8fafc", row_sel="#dbeafe", badge_bg="#eef2f7",
        chip_bg="#ffffff", scroll="#cbd5e1",
    ),
}

# 常用 token（默认取 dark，供 QSS / 自绘 / 报告导出引用；主题化请走 design_tokens(theme)）
BG: str = DESIGN["dark"]["bg"]
TEXT: str = DESIGN["dark"]["text"]
UP: str = DESIGN["dark"]["up"]
DOWN: str = DESIGN["dark"]["down"]
ACCENT: str = DESIGN["dark"]["accent"]
SUB: str = DESIGN["dark"]["sub"]
BORDER: str = DESIGN["dark"]["border"]
CARD: str = DESIGN["dark"]["card"]

_DEFAULT_PALETTE_SNAPSHOT: Optional[Dict] = None


def design_tokens(theme: str = "dark") -> Dict[str, str]:
    """返回指定主题的规范色板拷贝（不修改原表）。

    参数:
        theme: "dark" / "light"（未知回退 dark）。

    返回:
        dict: 该主题的全部 token。"""
    return dict(DESIGN.get(theme, DESIGN["dark"]))


def apply_design(theme: str = "dark", refresh_widgets: bool = True) -> Dict[str, str]:
    """把 DESIGN 注入 widgets.PALETTE，并刷新所有挂接控件主题。

    参数:
        theme: 目标主题。
        refresh_widgets: 是否遍历所有 set_theme 控件刷新（True 时全量刷新）。

    返回:
        dict: 本次应用的 token（便于调用方继续用）。

    副作用:
        - 修改 ``widgets.PALETTE`` 与 ``widgets.THEME``；
        - 遍历顶层控件树调用 ``set_theme``（若 refresh_widgets）。
    """
    global _DEFAULT_PALETTE_SNAPSHOT
    from . import widgets as W

    if _DEFAULT_PALETTE_SNAPSHOT is None:
        _DEFAULT_PALETTE_SNAPSHOT = {
            k: dict(v) for k, v in W.PALETTE.items()
        }
    # 1) 注入规范色板（覆盖 widgets.PALETTE 对应主题；另一主题保留以支持切换）
    W.PALETTE[theme] = dict(DESIGN.get(theme, W.PALETTE.get(theme, {})))
    W.THEME = theme
    if refresh_widgets:
        _refresh_all_widgets(theme)
    return design_tokens(theme)


def reset_design() -> None:
    """恢复 widgets 原始 PALETTE（回归护栏用，避免设计覆盖影响旧 e2e）。"""
    global _DEFAULT_PALETTE_SNAPSHOT
    if _DEFAULT_PALETTE_SNAPSHOT is None:
        return
    from . import widgets as W
    W.PALETTE = _DEFAULT_PALETTE_SNAPSHOT
    _DEFAULT_PALETTE_SNAPSHOT = None


def _refresh_all_widgets(theme: str) -> None:
    """遍历 QApplication 所有顶层窗口与子控件，调用其 set_theme（若有）。"""
    try:
        from PyQt6.QtWidgets import QApplication, QWidget
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    for top in app.allWidgets():
        try:
            if isinstance(top, QWidget) and hasattr(top, "set_theme"):
                top.set_theme(theme)
        except Exception:
            continue


__all__.append("_refresh_all_widgets")
