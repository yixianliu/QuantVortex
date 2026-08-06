"""可复用美化组件 + 主题调色板（期货量化系统 UI）。

设计目标：
    - 与 main_window 的 QSS 共用一套配色（PALETTE），保证全局视觉一致；
    - 组件读取模块级全局 THEME（"dark"/"light"），主题切换时由 main_window
      统一设置 widgets.THEME，无需逐个持有引用；
    - 纯 PyQt6 / QPainter，零额外依赖，离线可跑。
"""
from __future__ import annotations

from typing import Optional, Sequence

from PyQt6.QtCore import Qt, QRectF, pyqtProperty, QPropertyAnimation
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QFont, QLinearGradient, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
)

_FONT = None  # 延迟初始化，使用 QFontDatabase 加载的系统字体


def _get_font() -> str:
    """返回优先使用的字体名称。"""
    global _FONT
    if _FONT is not None:
        return _FONT
    import sys
    if sys.platform == "win32":
        _FONT = "Microsoft YaHei"
    elif sys.platform == "darwin":
        _FONT = "PingFang SC"
    else:
        _FONT = "Noto Sans CJK SC"
    return _FONT

# 全局主题开关（main_window._apply_theme 写入）
THEME = "dark"

# 主题调色板：UI 美化组件与 QSS 共用
PALETTE = {
    "dark": dict(
        bg="#0f1116", panel="#11141c", card="#161a24", border="#2a2e3a",
        text="#e6e6e6", sub="#8b93a7", accent="#2563eb", accent2="#3b82f6",
        up="#ef4444", down="#22c55e", grid="#1a1d27", row_alt="#131722",
        row_sel="#1f2a44", badge_bg="#1c2230", chip_bg="#161a24",
        scroll="#2a2e3a",
    ),
    "light": dict(
        bg="#f5f7fa", panel="#eef2f7", card="#ffffff", border="#d1d5db",
        text="#1f2937", sub="#6b7280", accent="#2563eb", accent2="#3b82f6",
        up="#dc2626", down="#16a34a", grid="#e5e7eb", row_alt="#f8fafc",
        row_sel="#dbeafe", badge_bg="#eef2f7", chip_bg="#ffffff",
        scroll="#cbd5e1",
    ),
}


def pal() -> dict:
    return PALETTE[THEME]


# ============================================================================
# 页面标题
# ============================================================================
class PageHeader(QWidget):
    """页面顶部标题：左侧强调条 + 大标题 + 副标题。"""

    def __init__(self, title: str, subtitle: str = "", theme: Optional[str] = None) -> None:
        super().__init__()
        self.setFixedHeight(50)
        self._theme = THEME if theme is None else theme
        self._bar = QFrame()
        self._bar.setFixedSize(4, 26)
        self._t = QLabel(title)
        self._s = QLabel(subtitle)
        self._s.setObjectName("sub")
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 6, 6, 0)
        root.setSpacing(0)
        hb = QHBoxLayout()
        hb.setContentsMargins(6, 0, 6, 0)
        hb.setSpacing(0)
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)
        vbox.addWidget(self._t)
        vbox.addWidget(self._s)
        hb.addWidget(self._bar)
        hb.addSpacing(10)
        hb.addLayout(vbox)
        hb.addStretch(1)
        root.addLayout(hb)
        self._sep = QFrame()
        self._sep.setObjectName("hsep")
        self._sep.setFixedHeight(1)
        root.addWidget(self._sep)
        self._apply()

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        self._bar.setStyleSheet(f"background:{p['accent']};border-radius:2px;")
        self._t.setStyleSheet(f"color:{p['text']};font-size:18px;font-weight:bold;")
        self._s.setStyleSheet(f"color:{p['sub']};font-size:12px;")
        self._sep.setStyleSheet(f"background:{p['border']};")


# ============================================================================
# 区块标题（强调色竖条 + 粗体标题 + 可选徽标）
# ============================================================================
class SectionHeader(QWidget):
    """区块标题：强调色竖条 + 粗体标题 + 右侧可选徽标。

    视觉风格与「行情全景」页面的区块标题栏完全一致，作为可复用组件供
    各功能页（回测中心、实盘监控等）复用，保证全应用视觉一致。
    主题切换由 BasePage.set_theme 递归下发到本组件，无需逐实例持有引用。
    """

    def __init__(self, title: str, accent: str = "#3b82f6",
                 badge: Optional[str] = None, theme: Optional[str] = None) -> None:
        super().__init__()
        self._title = title
        self._accent = accent
        self._theme = THEME if theme is None else theme

        root = QHBoxLayout(self)
        root.setContentsMargins(2, 4, 6, 4)
        root.setSpacing(6)

        self._bar = QFrame()
        self._bar.setFixedSize(4, 16)
        self._bar.setStyleSheet(f"QFrame{{background:{self._accent};border-radius:2px;}}")
        root.addWidget(self._bar)

        self._t = QLabel(title)
        root.addWidget(self._t, 1)

        self._badge: Optional["Badge"] = None
        if badge:
            self._badge = Badge(badge, bg=self._accent, fg="#ffffff", theme=self._theme)
            root.addWidget(self._badge)

        self._apply()

    # ------------------------------------------------------------------
    def set_title(self, title: str) -> None:
        self._title = title
        self._t.setText(title)

    def set_badge(self, text: str) -> None:
        """动态更新右侧徽标文本；传空字符串则隐藏。"""
        if not text:
            if self._badge is not None:
                self._badge.hide()
            return
        if self._badge is None:
            self._badge = Badge(text, bg=self._accent, fg="#ffffff", theme=self._theme)
            self.layout().addWidget(self._badge)
        else:
            self._badge.setText(text)
            self._badge.show()

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()
        if self._badge is not None:
            self._badge.set_theme(t)

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        self._t.setStyleSheet(
            f"font-size:14px;font-weight:bold;color:{p['text']};")


# ============================================================================
# 圆角 Badge
# ============================================================================
class Badge(QLabel):
    """圆角小标签（方向研判、状态等）。"""

    def __init__(self, text: str = "", bg: str = "", fg: str = "", theme: Optional[str] = None) -> None:
        super().__init__(text)
        self.setFixedHeight(24)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bg = bg
        self._fg = fg
        self._theme = THEME if theme is None else theme
        self._apply()

    def set_color(self, bg: str, fg: str) -> None:
        self._bg = bg
        self._fg = fg
        self._apply()

    def set_text(self, text: str) -> None:
        self.setText(text)

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        bg = self._bg or p["badge_bg"]
        fg = self._fg or p["text"]
        self.setStyleSheet(
            f"background:{bg};color:{fg};border-radius:11px;"
            f"padding:3px 12px;font-size:12px;font-weight:bold;")


# ============================================================================
# 指标卡 MetricChip
# ============================================================================
class MetricChip(QFrame):
    """指标卡：上方小标题 + 下方大数值，可设数值颜色。"""

    def __init__(self, label: str, value: str = "--", value_color: str = "",
                 theme: Optional[str] = None) -> None:
        super().__init__()
        self.setObjectName("chip")
        self.setMinimumWidth(120)
        self._theme = THEME if theme is None else theme
        self._val_color = value_color
        self._lab = QLabel(label)
        self._val = QLabel(value)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(3)
        lay.addWidget(self._lab)
        lay.addWidget(self._val)
        self._apply()

    def set_value(self, text: str, color: str = "") -> None:
        self._val.setText(text)
        c = color or self._val_color or pal()["text"]
        self._val.setStyleSheet(f"color:{c};font-size:16px;font-weight:bold;")

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        self.setStyleSheet(
            f"#chip{{background:{p['chip_bg']};border:1px solid {p['border']};"
            f"border-radius:10px;}}")
        self._lab.setStyleSheet(f"color:{p['sub']};font-size:11px;")
        self._val.setStyleSheet(
            f"color:{self._val_color or p['text']};font-size:16px;font-weight:bold;")


# ============================================================================
# 市场状态指示灯 StatusTile
# ============================================================================
class StatusTile(QFrame):
    """市场状态指示灯：左侧色条 + 图标 + 标签 + 数值 + 状态文案。

    根据 good / bad / neutral 动态着色并切换图标；每次刷新调用 pulse()
    做一次短暂的透明度脉冲（动画），让用户对行情好坏「一目了然」。
    主题切换由调用方下发 set_theme 刷新配色。
    """

    def __init__(self, label: str, theme: Optional[str] = None) -> None:
        super().__init__()
        self.setObjectName("status-tile")
        self._theme = THEME if theme is None else theme
        self._glow = 0.0
        self._level = "neutral"

        self._ico = QLabel("●")
        self._ico.setObjectName("st-ico")
        self._lab = QLabel(label)
        self._lab.setObjectName("st-lab")
        self._val = QLabel("--")
        self._val.setObjectName("st-val")
        self._tip = QLabel("")
        self._tip.setObjectName("st-tip")
        self._tip.setWordWrap(True)

        vb = QVBoxLayout()
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(2)
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)
        row1.addWidget(self._ico)
        row1.addWidget(self._lab)
        row1.addStretch(1)
        row1.addWidget(self._val)
        vb.addLayout(row1)
        vb.addWidget(self._tip)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addLayout(vb, 1)
        self._apply()

    # ---- 动画属性：脉冲高亮（0~1）----
    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, v: float) -> None:
        self._glow = v
        self._apply_glow()

    glow = pyqtProperty(float, _get_glow, _set_glow)

    def set_status(self, level: str, value_text: str, tip: str = "") -> None:
        """level: 'good' | 'bad' | 'neutral'。"""
        self._level = level
        self._val.setText(value_text)
        self._tip.setText(tip)
        self._apply()
        self.pulse()

    def pulse(self) -> None:
        """刷新时做一次透明度脉冲（动画反馈）。"""
        try:
            a = QPropertyAnimation(self, b"glow")
            a.setDuration(650)
            a.setStartValue(1.0)
            a.setEndValue(0.0)
            a.start()
        except Exception:  # noqa: BLE001
            pass

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _level_color(self) -> str:
        p = PALETTE[self._theme]
        return {"good": p["up"], "bad": p["down"],
                "neutral": p["accent"]}.get(self._level, p["accent"])

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        col = self._level_color()
        self._lab.setStyleSheet(f"color:{p['text']};font-size:12px;font-weight:bold;")
        self._val.setStyleSheet(f"color:{col};font-size:15px;font-weight:bold;")
        self._tip.setStyleSheet(f"color:{p['sub']};font-size:11px;")
        self._ico.setStyleSheet(f"color:{col};font-size:14px;")
        self._apply_glow()

    def _apply_glow(self) -> None:
        p = PALETTE[self._theme]
        col = self._level_color()
        bg = QColor(col)
        bg.setAlpha(int(16 + self._glow * 70))
        self.setStyleSheet(
            f"QFrame#status-tile{{background:{bg.name(QColor.NameFormat.HexArgb)};"
            f"border:1px solid {col};border-left:4px solid {col};"
            f"border-radius:10px;}}")


# ============================================================================
# 置信度条 ConfidenceBar
# ============================================================================
class ConfidenceBar(QWidget):
    """水平置信度条：轨道 + 渐变填充 + 百分比文字。"""

    def __init__(self, pct: float = 0.0, theme: Optional[str] = None) -> None:
        super().__init__()
        self._pct = max(0.0, min(1.0, pct))
        self._theme = THEME if theme is None else theme
        self.setFixedHeight(18)
        self.setMinimumWidth(120)

    def set_pct(self, pct: float) -> None:
        self._pct = max(0.0, min(1.0, pct))
        self.update()

    def set_theme(self, t: str) -> None:
        self._theme = t
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p_theme = PALETTE[self._theme]
        r = self.rect()
        h = 14
        y = (r.height() - h) // 2
        x0, x1 = r.x() + 1, r.x() + r.width() - 1
        track_w = x1 - x0
        # 轨道（宽度异常时跳过，避免圆角弧线计算 NaN）
        if track_w <= 0:
            return
        p.setBrush(QBrush(QColor(p_theme["card"])))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(x0, y, track_w, h, 7, 7)
        # 填充（裁剪到圆角内）
        fill_w = max(0, int(track_w * self._pct))
        if fill_w > 0:
            grad = QLinearGradient(0, y, 0, y + h)
            grad.setColorAt(0, QColor(p_theme["accent2"]))
            grad.setColorAt(1, QColor(p_theme["accent"]))
            p.setBrush(QBrush(grad))
            p.setClipRect(x0, y, fill_w, h)
            p.drawRoundedRect(x0, y, max(14, fill_w), h, 7, 7)
            p.setClipping(False)
        # 文字
        p.setPen(QColor(p_theme["text"]))
        p.setFont(QFont(_get_font(), 10, QFont.Weight.Bold))
        p.drawText(x0, y - 2, r.width(), h + 4,
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._pct:.0%}")


# ============================================================================
# 工具：导航圆点图标
# ============================================================================
class ToolBar(QFrame):
    """统一工具栏容器：圆角卡片 + 内边距，包裹页面控制条（合约/周期/按钮等）。

    用法：
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("合约")); ctl.addWidget(self.sym_cb)
        ...
        root.addWidget(ToolBar(ctl))
    主题切换由 main_window 统一下发 QSS（#toolbar 选择器），无需逐实例持有引用。
    """

    def __init__(self, layout: "QHBoxLayout", theme: Optional[str] = None) -> None:
        super().__init__()
        self.setObjectName("toolbar")
        self._theme = THEME if theme is None else theme
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # 外观由 main_window 的全局 QSS（#toolbar 选择器）统一下发，主题切换时自动更新

    def set_theme(self, t: str) -> None:
        self._theme = t


def make_dot_icon(color: str, size: int = 10) -> QIcon:
    """生成圆形彩色图标（避免字体图标在离屏渲染下的 tofu 问题）。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    pp = QPainter(pix)
    pp.setRenderHint(QPainter.RenderHint.Antialiasing)
    pp.setBrush(QBrush(QColor(color)))
    pp.setPen(Qt.PenStyle.NoPen)
    pp.drawEllipse(1, 1, size - 2, size - 2)
    pp.end()
    return QIcon(pix)


# ============================================================================
# 工具：表格隔行底色 + 盈亏配色
# ============================================================================
def stripe_table(table: QTableWidget, theme: Optional[str] = None) -> None:
    """为表格设置隔行底色（调用方在填充行之后调用）。"""
    t = THEME if theme is None else theme
    p = PALETTE[t]
    base = QColor(p["card"])
    alt = QColor(p["row_alt"])
    for i in range(table.rowCount()):
        c = alt if i % 2 else base
        for j in range(table.columnCount()):
            it = table.item(i, j)
            if it is not None:
                it.setBackground(c)


def prepare_table(table: QTableWidget, theme: Optional[str] = None) -> None:
    """表格统一预处理：隐藏左侧行号、设置默认行高、应用隔行底色。"""
    vh = table.verticalHeader()
    vh.setVisible(False)
    vh.setDefaultSectionSize(28)
    stripe_table(table, theme)


def color_pnl(item: QTableWidgetItem, value: float, theme: Optional[str] = None) -> None:
    """根据正负设置单元格前景色（红涨绿跌，中国期货惯例）。"""
    t = THEME if theme is None else theme
    p = PALETTE[t]
    if value > 0:
        item.setForeground(QColor(p["up"]))
    elif value < 0:
        item.setForeground(QColor(p["down"]))
    else:
        item.setForeground(QColor(p["text"]))
