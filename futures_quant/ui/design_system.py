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
  - 颜�色常量对外只读暴露（``BG`` / ``TEXT`` / ``UP`` / ``DOWN`` / ``ACCENT``），
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
    "build_qss",
    "_QSS_TEMPLATE",
]

# ---- 规范色板（UPGRADE_PLAN M1.2 指定值）----
# dark 主背景 #1e1e2e、文本 #dcdcdc、上涨 #ff4757、下跌 #2ed573
DESIGN: Dict[str, Dict[str, str]] = {
    "dark": dict(
        bg="#1e1e2e", panel="#181825", card="#27273a", border="#45455f",
        text="#dcdcdc", sub="#8b93a7", accent="#7aa2f7", accent2="#3b82f6",
        up="#ff4757", down="#2ed573", grid="#2a2a3a",
        row_alt="#23233a", row_sel="#33335a", badge_bg="#313148",
        chip_bg="#27273a", scroll="#45455f", warning="#f59e0b",
        # Token v2 新增（UX-05）
        radius_sm=6, radius_md=8, radius_lg=10, radius_pill=12,
        space_xs=4, space_sm=8, space_md=12, space_lg=16, space_xl=24,
        space_1=1, space_2=2, space_3=3, space_5=5, space_6=6, space_7=7, space_9=9, space_10=10, space_14=14, space_18=18, space_20=20, space_26=26, space_32=32,
        font_caption=11, font_body=12, font_h3=13, font_h2=16, font_h1=18,
        elevation_e1="rgba(0,0,0,.18)", elevation_e2="rgba(0,0,0,.28)", elevation_e3="rgba(0,0,0,.40)",
        chart_series_1="#7aa2f7", chart_series_2="#f59e0b", chart_series_3="#2ed573", chart_series_4="#ff4757", chart_series_5="#a78bfa", chart_series_6="#22d3ee",
    ),
    "light": dict(
        bg="#f5f7fa", panel="#eef2f7", card="#ffffff", border="#d1d5db",
        text="#1f2937", sub="#6b7280", accent="#2563eb", accent2="#3b82f6",
        up="#ff4757", down="#2ed573", grid="#e5e7eb",
        row_alt="#f8fafc", row_sel="#dbeafe", badge_bg="#eef2f7",
        chip_bg="#ffffff", scroll="#cbd5e1", warning="#d97706",
        # Token v2 新增（UX-05）
        radius_sm=6, radius_md=8, radius_lg=10, radius_pill=12,
        space_xs=4, space_sm=8, space_md=12, space_lg=16, space_xl=24,
        space_1=1, space_2=2, space_3=3, space_5=5, space_6=6, space_7=7, space_9=9, space_10=10, space_14=14, space_18=18, space_20=20, space_26=26, space_32=32,
        font_caption=11, font_body=12, font_h3=13, font_h2=16, font_h1=18,
        elevation_e1="rgba(15,23,42,.08)", elevation_e2="rgba(15,23,42,.12)", elevation_e3="rgba(15,23,42,.18)",
        chart_series_1="#7aa2f7", chart_series_2="#f59e0b", chart_series_3="#2ed573", chart_series_4="#ff4757", chart_series_5="#a78bfa", chart_series_6="#22d3ee",
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
    # 1) 注入规范色板（覆盖 widgets.PALETTE 两个主题以保持同步）
    W.PALETTE[theme] = dict(DESIGN.get(theme, {}))
    other_theme = "light" if theme == "dark" else "dark"
    W.PALETTE[other_theme] = dict(DESIGN.get(other_theme, {}))
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


# ============================================================================
# QSS 单一事实来源（M4-04）
# ----------------------------------------------------------------------------
# 模板中所有核心色均用 $TOKEN$ 占位，由 DESIGN[theme] 注入；交互态（hover/
# pressed/disabled）在模板内固定，不影响基础配色一致性。QSS 控件与自绘控件
# （经 apply_design 注入 widgets.PALETTE）因此同源。字号保留 11/12/13px 三档，
# 供 responsive_layout.scale_qss_fonts 做响应式钳制。
# ============================================================================
_QSS_TEMPLATE = """
/* ===== 基础 ===== */
QWidget { background:$BG$; color:$TEXT$; font-family:'SimHei','Noto Sans SC','Microsoft YaHei',sans-serif; }
QMainWindow { background:$BG$; }
QWidget#central { background:$BG$; }
QWidget#content-panel { background:$BG$; }
QFrame#toolbar { background:$PANEL$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; }
QFrame#hsep { background:$GRID$; border:none; }

/* ===== 侧边导航 ===== */
QListWidget#nav { background:$PANEL$; border:none; padding-top:$space_10$px; padding-bottom:$space_10$px; outline:0; }
QListWidget#nav::item { color:$SUB$; padding:$space_md$ $space_lg$; border-left:$space_3$px solid transparent; margin:$space_2$px $space_sm$px; border-radius:$radius_md$px; }
QListWidget#nav::item:hover { background:$CARD$; color:$TEXT$; }
QListWidget#nav::item:selected { background:$CARD$; color:$TEXT$; border-left:$space_3$px solid $ACCENT$; }

/* ===== 内容区 ===== */
QStackedWidget { background:$BG$; }

/* ===== UX-61: 页面头部 ===== */
QFrame#page-header { background:$PANEL$; border-bottom:$space_1$px solid $BORDER$; }
QLabel#breadcrumb { color:$TEXT$; font-weight:600; }
QLabel#breadcrumb-sep { color:$SUB$; }
QLabel#page-subtitle { color:$SUB$; }

/* ===== 文本 ===== */
QLabel { color:$TEXT$; background:transparent; }
QLabel#sub { color:$SUB$; }

/* ===== 按钮 ===== */
QPushButton { background:$ACCENT$; color:#fff; border:$space_1$px solid transparent; border-radius:$radius_md$px; padding:$space_sm$px $space_18$px; font-size:$font_h3$px; font-weight:bold; }
QPushButton:hover { background:$ACCENT2$; border-color:$ACCENT$; }
QPushButton:pressed { background:$ACCENT2$; padding-top:$space_9$px; padding-bottom:$space_7$px; }
QPushButton:focus { border:$space_1$px solid $ACCENT2$; outline:none; }
QPushButton:disabled { background:$PANEL$; color:$SUB$; border-color:transparent; }
QPushButton#secondary { background:$CARD$; color:$TEXT$; border:$space_1$px solid $BORDER$; font-weight:500; }
QPushButton#secondary:hover { background:$PANEL$; border-color:$BORDER$; color:$TEXT$; }
QPushButton#secondary:pressed { background:$PANEL$; }
QPushButton#secondary:focus { border-color:$ACCENT2$; }
QPushButton#primary { background:$ACCENT$; }
QPushButton#primary:hover { background:$ACCENT2$; }
QPushButton#danger { background:#dc2626; }
QPushButton#danger:hover { background:#b91c1c; }
QPushButton#danger:pressed { background:#991b1b; }

/* ===== 输入控件 ===== */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background:$CARD$; border:$space_1$px solid $BORDER$; border-radius:$radius_md$px; padding:$space_6$px $space_10$px; color:$TEXT$; font-size:$font_h3$px; selection-background-color:$ACCENT$; selection-color:#fff; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover { border-color:$BORDER$; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus { border:$space_1$px solid $ACCENT2$; background:$CARD$; }
QComboBox::drop-down { border:none; width:$space_20$px; }
QComboBox QAbstractItemView { background:$CARD$; color:$TEXT$; selection-background-color:$ACCENT$; selection-color:#fff; border:$space_1$px solid $BORDER$; border-radius:$radius_md$px; outline:0; padding:$space_xs$px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width:$space_lg$px; border:none; background:transparent; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover { background:$PANEL$; }

/* ===== 表格 ===== */
QTableWidget { background:$CARD$; gridline-color:$GRID$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; outline=0; font-size:$font_body$px; }
QTableWidget::item { padding:$space_6$px $space_sm$px; border:none; }
QTableWidget::item:selected { background:$ACCENT$; color:#fff; }
QHeaderView::section { background:$PANEL$; color:$SUB$; border:none; padding:$space_sm$px; font-weight:bold; font-size:$font_body$px; }
QHeaderView::section:hover { color:$TEXT$; }
QTableWidget::item:hover { background:$CARD$; }

/* ===== 标签页 ===== */
QTabWidget::pane { border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; top:-$space_1$px; }
QTabBar::tab { background:$PANEL$; color:$SUB$; padding:$space_9$px $space_lg$px; margin-right:$space_6$px; border-top-left-radius:$radius_md$px; border-top-right-radius:$radius_md$px; }
QTabBar::tab:selected { background:$CARD$; color:$TEXT$; }
QTabBar::tab:hover { color:$TEXT$; }

/* ===== UX-62: 顶部 Tab 导航 ===== */
QTabWidget#top-tabs { background:$PANEL$; border-bottom:$space_1$px solid $BORDER$; }
QTabWidget#top-tabs::pane { border:none; top:0; }
QTabWidget#top-tabs > QTabBar::tab { background:transparent; color:$SUB$; padding:$space_6$px $space_md$px; margin-right:$space_2$px; border-radius:$radius_md$px; }
QTabWidget#top-tabs > QTabBar::tab:selected { background:$ACCENT$; color:#fff; }
QTabWidget#top-tabs > QTabBar::tab:hover { background:$CARD$; color:$TEXT$; }

/* ===== 滚动条 ===== */
QScrollBar:vertical { background:$BG$; width:$space_md$px; border-radius:$radius_sm$px; margin=0; }
QScrollBar::handle:vertical { background:$BORDER$; border-radius:$radius_sm$px; min-height:$space_32$px; margin:$space_1$px; }
QScrollBar::handle:vertical:hover { background:$SUB$; }
QScrollBar::handle:vertical:pressed { background:$ACCENT$; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height=0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:$BG$; height:$space_md$px; border-radius:$radius_sm$px; margin=0; }
QScrollBar::handle:horizontal { background:$BORDER$; border-radius:$radius_sm$px; min-width:$space_32$px; margin:$space_1$px; }
QScrollBar::handle:horizontal:hover { background:$SUB$; }
QScrollBar::handle:horizontal:pressed { background:$ACCENT$; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width=0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }

/* ===== 复选框 ===== */
QCheckBox { color:$TEXT$; spacing:$space_sm$px; background:transparent; }
QCheckBox::indicator { width:$space_lg$px; height:$space_lg$px; border-radius:$space_xs$px; border:$space_1$px solid $BORDER$; background:$CARD$; }
QCheckBox::indicator:hover { border-color:$ACCENT$; }
QCheckBox::indicator:checked { background:$ACCENT$; border-color:$ACCENT$; }
QCheckBox::indicator:checked:hover { background:$ACCENT2$; }

/* ===== 菜单栏 / 菜单 ===== */
QMenuBar { background:$PANEL$; color:$TEXT$; padding:$space_3$px $space_6$px; border-bottom:$space_1$px solid $BORDER$; spacing:$space_2$px; }
QMenuBar::item { background=transparent; padding:$space_6$px $space_14$px; border-radius:$radius_sm$px; }
QMenuBar::item:selected { background:$ACCENT$; color:#fff; }
QMenuBar::item:pressed { background:$ACCENT2$; }
QMenu { background:$CARD$; color:$TEXT$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; padding:$space_6$px; }
QMenu::item { padding:$space_sm$px $space_26$px $space_sm$px $space_14$px; border-radius:$radius_sm$px; }
QMenu::item:selected { background:$ACCENT$; color:#fff; }
QMenu::separator { height:$space_1$px; background:$BORDER$; margin:$space_5$px $space_md$px; }

/* ===== 状态栏 ===== */
QStatusBar { background:$PANEL$; color:$SUB$; border-top:$space_1$px solid $BORDER$; padding:$space_5$px $space_md$px; }
QStatusBar::item { border:none; }
#status-dot { color:$UP$; font-weight:bold; font-size:$font_h3$px; }
#status-ver { color:$ACCENT2$; font-weight:bold; font-size:$font_h3$px; padding=0 $space_sm$px; }
QFrame#chip { border-radius:$radius_pill$px; }

/* ===== 设计系统选择器（M4-04 单一事实来源） ===== */
QFrame#card { background:$CARD$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; }
QFrame#ai-group { background:$PANEL$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; }
QWidget#btn-bar, QFrame#btn-bar { background:transparent; spacing:$space_sm$px; }
QGroupBox#primary { border:$space_1$px solid $ACCENT$; border-radius:$radius_lg$px; }
QWidget#secondary { background:$PANEL$; }

QToolTip { background:$PANEL$; color:$TEXT$; border:$space_1$px solid $BORDER$; border-radius:$radius_sm$px; padding:$space_5$px $space_sm$px; }

/* ===== 焦点可见样式（UX-74：键盘导航可辨识） ===== */
/* 通用焦点环：2px 圆角描边，仅键盘导航时显示 */
QPushButton:focus-visible { border:$space_2$px solid $ACCENT2$; outline:none; }
QComboBox:focus-visible, QSpinBox:focus-visible, QDoubleSpinBox:focus-visible, QLineEdit:focus-visible { border:$space_2$px solid $ACCENT2$; outline:none; }
QTableWidget:focus-visible { border:$space_2$px solid $ACCENT2$; }
QListWidget:focus-visible { border:$space_2$px solid $ACCENT2$; }
QTreeWidget:focus-visible, QTreeView:focus-visible, QListView:focus-visible { border:$space_2$px solid $ACCENT2$; }
QCheckBox:focus-visible, QRadioButton:focus-visible { outline:$space_2$px solid $ACCENT2$; border-radius:$radius_md$px; }
QSlider::handle:focus-visible { border:$space_2$px solid $ACCENT2$; }
QScrollBar::handle:focus-visible { background:$ACCENT2$; }
QMenu:focus-visible { border:$space_1$px solid $ACCENT2$; }
QDialog:focus-visible { border:$space_1$px solid $ACCENT2$; }
QLineEdit:focus-visible { border:$space_2$px solid $ACCENT2$; }
QTextEdit:focus-visible, QPlainTextEdit:focus-visible { border:$space_2$px solid $ACCENT2$; }
QListWidget#nav:focus { border:none; }
QListWidget#nav::item:focus { background:$CARD$; color:$TEXT$; border-left:$space_3$px solid $ACCENT2$; }
QTabBar::tab:focus { color:$TEXT$; border:$space_1$px solid $ACCENT2$; border-bottom:none; }
QTabBar::tab:focus-visible { color:$TEXT$; border:$space_2$px solid $ACCENT2$; border-bottom:none; }
"""
def build_qss(theme: str = "dark") -> str:
    """由 DESIGN[theme] token 生成完整 QSS（单一事实来源，M4-04）。

    所有核心色取自 DESIGN[theme]，与自绘控件（经 apply_design 注入的
    widgets.PALETTE）同源；交互态在模板内固定，不影响基础配色一致性。

    参数:
        theme: "dark" / "light"（未知回退 dark）。

    返回:
        str: 可直接 setStyleSheet 的 QSS（含 11/12/13px 三档字号占位）。
    """
    tk = DESIGN.get(theme, DESIGN["dark"])
    mapping = {
        "$BG$": str(tk["bg"]),
        "$TEXT$": str(tk["text"]),
        "$PANEL$": str(tk["panel"]),
        "$BORDER$": str(tk["border"]),
        "$GRID$": str(tk["grid"]),
        "$SUB$": str(tk["sub"]),
        "$CARD$": str(tk["card"]),
        "$ACCENT$": str(tk["accent"]),
        "$ACCENT2$": str(tk["accent2"]),
        "$DOWN$": str(tk["down"]),
        "$UP$": str(tk["up"]),
        # Token v2 新增（UX-05）
        "$radius_sm$": str(tk["radius_sm"]),
        "$radius_md$": str(tk["radius_md"]),
        "$radius_lg$": str(tk["radius_lg"]),
        "$radius_pill$": str(tk["radius_pill"]),
        "$space_xs$": str(tk["space_xs"]),
        "$space_sm$": str(tk["space_sm"]),
        "$space_md$": str(tk["space_md"]),
        "$space_lg$": str(tk["space_lg"]),
        "$space_xl$": str(tk["space_xl"]),
        "$space_1$": str(tk["space_1"]),
        "$space_2$": str(tk["space_2"]),
        "$space_3$": str(tk["space_3"]),
        "$space_5$": str(tk["space_5"]),
        "$space_6$": str(tk["space_6"]),
        "$space_7$": str(tk["space_7"]),
        "$space_9$": str(tk["space_9"]),
        "$space_10$": str(tk["space_10"]),
        "$space_14$": str(tk["space_14"]),
        "$space_18$": str(tk["space_18"]),
        "$space_20$": str(tk["space_20"]),
        "$space_26$": str(tk["space_26"]),
        "$space_32$": str(tk["space_32"]),
        "$font_caption$": str(tk["font_caption"]),
        "$font_body$": str(tk["font_body"]),
        "$font_h3$": str(tk["font_h3"]),
        "$font_h2$": str(tk["font_h2"]),
        "$font_h1$": str(tk["font_h1"]),
        "$elevation_e1$": str(tk["elevation_e1"]),
        "$elevation_e2$": str(tk["elevation_e2"]),
        "$elevation_e3$": str(tk["elevation_e3"]),
        "$chart_series_1$": str(tk["chart_series_1"]),
        "$chart_series_2$": str(tk["chart_series_2"]),
        "$chart_series_3$": str(tk["chart_series_3"]),
        "$chart_series_4$": str(tk["chart_series_4"]),
        "$chart_series_5$": str(tk["chart_series_5"]),
        "$chart_series_6$": str(tk["chart_series_6"]),
    }
    qss = _QSS_TEMPLATE
    for ph, val in mapping.items():
        qss = qss.replace(ph, val)
    if "$" in qss:
        # 安全护栏：若有占位未替换，抛出以便及时发现模板/映射不一致
        import re as _re
        _left = _re.findall(r"\$[A-Za-z0-9_]+\$", qss)
        raise ValueError(f"QSS 模板存在未替换占位符：{_left}")
    return qss


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