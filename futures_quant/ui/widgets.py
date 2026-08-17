"""可复用美化组件 + 主题调色板（期货量化系统 UI）。

设计目标：
    - 与 main_window 的 QSS 共用一套配色（PALETTE），保证全局视觉一致；
    - 组件读取模块级全局 THEME（"dark"/"light"），主题切换时由 main_window
      统一设置 widgets.THEME，无需逐个持有引用；
    - 纯 PyQt6 / QPainter，零额外依赖，离线可跑。
"""
from __future__ import annotations

import csv as _csv
from typing import Optional, Sequence

from PyQt6 import sip
from PyQt6.QtCore import Qt, QRectF, QRect, QPoint, QSize, pyqtProperty, QPropertyAnimation
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QFont, QLinearGradient, QIcon, QPixmap, QAction
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QLayout, QWidgetItem, QGridLayout, QStyledItemDelegate,
    QAbstractItemView, QApplication, QMenu, QFileDialog,
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
    """处理pal。
    
        返回:
            dict"""
    return PALETTE[THEME]


# ============================================================================
# 页面标题
# ============================================================================
class PageHeader(QWidget):
    """页面顶部标题：左侧强调条 + 大标题 + 副标题。"""

    def __init__(self, title: str, subtitle: str = "", theme: Optional[str] = None) -> None:
        """初始化相关对象。
        
            参数:
                title: str
                subtitle: str
                theme: Optional[str]"""
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
        """设置主题。
        
            参数:
                t: str"""
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        """应用相关对象。"""
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
        """初始化相关对象。
        
            参数:
                title: str
                accent: str
                badge: Optional[str]
                theme: Optional[str]"""
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
        """设置title。
        
            参数:
                title: str"""
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
        """设置主题。
        
            参数:
                t: str"""
        self._theme = t
        self._apply()
        if self._badge is not None:
            self._badge.set_theme(t)

    def _apply(self) -> None:
        """应用相关对象。"""
        p = PALETTE[self._theme]
        self._t.setStyleSheet(
            f"font-size:14px;font-weight:bold;color:{p['text']};")


# ============================================================================
# 圆角 Badge
# ============================================================================
class Badge(QLabel):
    """圆角小标签（方向研判、状态等）。"""

    def __init__(self, text: str = "", bg: str = "", fg: str = "", theme: Optional[str] = None) -> None:
        """初始化相关对象。
        
            参数:
                text: str
                bg: str
                fg: str
                theme: Optional[str]"""
        super().__init__(text)
        self.setFixedHeight(24)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bg = bg
        self._fg = fg
        self._theme = THEME if theme is None else theme
        self._apply()

    def set_color(self, bg: str, fg: str) -> None:
        """设置颜色。
        
            参数:
                bg: str
                fg: str"""
        self._bg = bg
        self._fg = fg
        self._apply()

    def set_text(self, text: str) -> None:
        """设置文本。
        
            参数:
                text: str"""
        self.setText(text)

    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        """应用相关对象。"""
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
        """初始化相关对象。
        
            参数:
                label: str
                value: str
                value_color: str
                theme: Optional[str]"""
        super().__init__()
        self.setObjectName("chip")
        # 取消固定最小宽度，允许在窄栏内压缩换行（消除行情全景横向滚动）
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._theme = THEME if theme is None else theme
        self._val_color = value_color
        self._lab = QLabel(label)
        self._lab.setWordWrap(True)
        self._val = QLabel(value)
        self._val.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(3)
        lay.addWidget(self._lab)
        lay.addWidget(self._val)
        self._apply()

    def set_value(self, text: str, color: str = "") -> None:
        """设置数值。
        
            参数:
                text: str
                color: str"""
        self._val.setText(text)
        c = color or self._val_color or pal()["text"]
        self._val.setStyleSheet(f"color:{c};font-size:16px;font-weight:bold;")

    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        """应用相关对象。"""
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
        """初始化相关对象。
        
            参数:
                label: str
                theme: Optional[str]"""
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
        """获取glow。
        
            返回:
                float"""
        return self._glow

    def _set_glow(self, v: float) -> None:
        """设置glow。
        
            参数:
                v: float"""
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
        """设置主题。
        
            参数:
                t: str"""
        self._theme = t
        self._apply()

    def _level_color(self) -> str:
        """处理价位颜色。
        
            返回:
                str"""
        p = PALETTE[self._theme]
        return {"good": p["up"], "bad": p["down"],
                "neutral": p["accent"]}.get(self._level, p["accent"])

    def _apply(self) -> None:
        """应用相关对象。"""
        p = PALETTE[self._theme]
        col = self._level_color()
        self._lab.setStyleSheet(f"color:{p['text']};font-size:12px;font-weight:bold;")
        self._val.setStyleSheet(f"color:{col};font-size:15px;font-weight:bold;")
        self._tip.setStyleSheet(f"color:{p['sub']};font-size:11px;")
        self._ico.setStyleSheet(f"color:{col};font-size:14px;")
        self._apply_glow()

    def _apply_glow(self) -> None:
        """应用glow。"""
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
        """初始化相关对象。
        
            参数:
                pct: float
                theme: Optional[str]"""
        super().__init__()
        self._pct = max(0.0, min(1.0, pct))
        self._theme = THEME if theme is None else theme
        self.setFixedHeight(18)
        # 取消固定最小宽度，允许在窄栏内压缩（消除行情全景横向滚动）
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_pct(self, pct: float) -> None:
        """设置pct。
        
            参数:
                pct: float"""
        self._pct = max(0.0, min(1.0, pct))
        self.update()

    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        self._theme = t
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制事件。
        
            参数:
                event"""
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
        """初始化相关对象。
        
            参数:
                layout: 'QHBoxLayout'
                theme: Optional[str]"""
        super().__init__()
        self.setObjectName("toolbar")
        self._theme = THEME if theme is None else theme
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # 外观由 main_window 的全局 QSS（#toolbar 选择器）统一下发，主题切换时自动更新

    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
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


def _fmt_hands(v: float) -> tuple[str, str]:
    """格式化「手」数 -> (数值, 单位)。
    
    自动在 1 万手 以上使用「万手」作单位，避免数值过大。
    返回: (数值文本, 单位)
    """
    v = abs(v)
    if v >= 1e8:
        return f"{v / 1e8:,.2f}", "亿手"
    if v >= 1e4:
        return f"{v / 1e4:,.2f}", "万手"
    return f"{v:,.0f}", "手"


def _fmt_yi(v: float) -> tuple[str, str]:
    """格式化「亿」数 -> (数值, 单位)。
    
    返回: (数值文本, "亿")
    """
    return f"{v:+,.2f}", "亿"


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


# ============================================================================
# 响应式两列容器（行情全景：宽屏并排 / 窄屏自动堆叠为单列）
# ============================================================================
class ResponsiveRow(QWidget):
    """把两张卡片（a, b）放进一个网格容器：可用宽度 ≥ threshold 时并排，
    否则纵向堆叠。用于消除行情全景面板在窄栏下的横向溢出。"""

    def __init__(self, a: QWidget, b: QWidget, threshold: int = 720,
                 parent: Optional[QWidget] = None) -> None:
        """初始化响应式行。

        参数:
            a: 左/上卡片
            b: 右/下卡片
            threshold: 触发并排布局的最小宽度（px）
            parent: 父控件"""
        super().__init__(parent)
        self._a, self._b, self._threshold = a, b, threshold
        self._g = QGridLayout(self)
        self._g.setContentsMargins(0, 0, 0, 0)
        self._g.setSpacing(8)
        self._g.addWidget(a, 0, 0)
        self._g.addWidget(b, 0, 1)
        self._g.setColumnStretch(0, 1)
        self._g.setColumnStretch(1, 1)
        self._horiz = None
        self._apply(True)

    def _apply(self, force: bool = False) -> None:
        """按当前宽度重排：宽屏并排、窄屏堆叠。"""
        h = self.width() >= self._threshold
        if h == self._horiz and not force:
            return
        self._horiz = h
        self._g.removeWidget(self._a)
        self._g.removeWidget(self._b)
        if h:
            self._g.setColumnStretch(0, 1)
            self._g.setColumnStretch(1, 1)
            self._g.addWidget(self._a, 0, 0)
            self._g.addWidget(self._b, 0, 1)
        else:
            self._g.setColumnStretch(0, 1)
            self._g.setColumnStretch(1, 0)
            self._g.addWidget(self._a, 0, 0)
            self._g.addWidget(self._b, 1, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """处理窗口尺寸变化，触发重排。"""
        super().resizeEvent(event)
        self._apply()


# ============================================================================
# 流式布局 FlowLayout（板块强度条等需要按宽度自动换行收纳的场景）
# ============================================================================
class FlowLayout(QLayout):
    """轻量流式布局：子控件按宽度自动换行，避免横向溢出。

    适配 PyQt6：基于 sizeHint / heightForWidth / setGeometry 重排。
    """

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = -1) -> None:
        """初始化流式布局。

        参数:
            parent: 父控件
            spacing: 子项间距（<0 时使用默认）"""
        super().__init__(parent)
        if spacing >= 0:
            self.setSpacing(spacing)
        self._items: list = []

    def addItem(self, item) -> None:  # noqa: N802
        """添加布局项。"""
        self._items.append(item)

    def addWidget(self, w: QWidget) -> None:
        """添加控件。

        关键：显式把控件挂到布局的父控件上，避免控件仅被 QWidgetItem 的
        C++ 裸指针持有。否则 Python 包装器被 GC 回收时会一并删除 C++ 控件，
        导致后续布局时 item.widget() 拿到悬空指针而段错误（闪退）。
        这与 QHBoxLayout/VBoxLayout 等内置布局的自动 reparent 行为一致。
        """
        parent = self.parentWidget()
        if parent is not None and w.parent() is None:
            w.setParent(parent)
        self.addItem(QWidgetItem(w))

    def itemAt(self, index: int):  # noqa: N802
        """返回指定索引的布局项。"""
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        """移除并返回指定索引的布局项。"""
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def count(self) -> int:  # noqa: N802
        """返回布局项数量。"""
        return len(self._items)

    def expandingDirections(self):  # noqa: N802
        """声明不向任何方向扩展。"""
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        """启用按宽度计算高度。"""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        """给定宽度时的总高度。"""
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        """按当前宽度给出建议尺寸（含换行高度）。"""
        w = self.geometry().width() or 1
        return QSize(w, self.heightForWidth(w))

    def minimumSize(self) -> QSize:  # noqa: N802
        """最小尺寸：宽度至少 1，高度为当前宽度下的换行高度。"""
        w = self.geometry().width() or 1
        return QSize(1, self.heightForWidth(w))

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        """应用布局几何。"""
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        """核心排版：从左到右排布，超宽则换行；apply=True 时真正落位。"""
        x = rect.x()
        y = rect.y()
        line_height = 0
        space = self.spacing()
        for item in self._items:
            w = item.widget()
            # 防御：控件已被删除（悬空指针）时跳过，绝不访问其方法，
            # 否则会触发段错误导致整个程序闪退。
            if w is None or sip.isdeleted(w) or w.isHidden():
                continue
            sz = item.sizeHint()
            next_x = x + sz.width() + space
            if next_x - space > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + space
                next_x = x + sz.width() + space
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), sz))
            x = next_x
            line_height = max(line_height, sz.height())
        return y + line_height - rect.y()


# ============================================================================
# 指标卡 StatCard（行情全景盘口快照：标签 + 大数值 + 单位 + 副提示 + 比例条）
# ============================================================================
class StatCard(QFrame):
    """市场指标卡：上方标签 + 中部「箭头 + 大数值 + 单位」+ 底部副提示 + 可选比例条。

    较旧版新增：
    - 数值左侧方向箭头（↑ 红 / ↓ 绿 / — 中性），一眼识别方向；
    - 支持传入 trend 列表并在右侧绘制迷你 sparkline（最近 7 点折线），
      升级为「文字 + 方向 + 趋势」三位一体 KPI 卡。
    """

    # sparkline 最大保存点数
    _TREND_MAX = 12

    def __init__(self, label: str, value: str = "--", unit: str = "",
                 sub: str = "", value_size: int = 18, compact: bool = False,
                 theme: Optional[str] = None) -> None:
        """初始化指标卡。

        参数:
            label: 指标名称
            value: 数值文本
            unit: 单位后缀（如 万手 / 亿）
            sub: 副提示行
            value_size: 数值字号
            compact: 紧凑模式
            theme: 主题
            trend: 可选，最近 N 点历史值（用于 sparkline）"""
        super().__init__()
        self.setObjectName("stat")
        self._theme = THEME if theme is None else theme
        self._val_size = value_size
        self._compact = compact
        self._bar_frac = 0.0
        self._bar_color = pal()["accent"]
        # 方向箭头：空 = 中性
        self._arrow = ""
        self._trend: list[float] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._lab = QLabel(label)
        self._lab.setObjectName("st-lab")
        self._arrow_lbl = QLabel("")
        self._arrow_lbl.setObjectName("st-arrow")
        self._arrow_lbl.setFixedWidth(14)
        self._arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._val = QLabel(str(value))
        self._val.setObjectName("st-val")
        self._unit = QLabel(str(unit))
        self._unit.setObjectName("st-unit")
        self._sub = QLabel(str(sub))
        self._sub.setObjectName("st-sub")
        self._sub.setWordWrap(True)
        if not sub:
            self._sub.hide()

        vrow = QHBoxLayout()
        vrow.setContentsMargins(0, 0, 0, 0)
        vrow.setSpacing(2)
        vrow.addWidget(self._arrow_lbl)
        vrow.addWidget(self._val)
        vrow.addWidget(self._unit)
        vrow.addStretch(1)

        root = QVBoxLayout(self)
        if compact:
            root.setContentsMargins(8, 5, 8, 5)
            root.setSpacing(1)
        else:
            root.setContentsMargins(12, 8, 12, 8)
            root.setSpacing(2)
        root.addWidget(self._lab)
        root.addLayout(vrow)
        root.addWidget(self._sub)
        self._apply()

    def set_value_size(self, size: int) -> None:
        """设置数值字号。"""
        self._val_size = size
        self._apply()

    def set_value(self, text: str, color: str = "",
                  direction: str = "", trend: Optional[list] = None,
                  tooltip: str = "") -> None:
        """设置数值（沿用 MetricChip 接口，便于盘口刷新复用）。

        参数:
            text: 数值字符
            color: 颜色
            direction: 方向指示 "up" / "down" / "flat" / ""（中性）
            trend: 最近的数值列表，用于 sparkline 迷你趋势
            tooltip: tooltip 文本（涨跌说明 / 诊断信息）
        """
        self._val.setText(str(text))
        c = color or pal()["text"]
        self._val.setStyleSheet(
            f"color:{c};font-size:{self._val_size}px;font-weight:bold;")
        d = (direction or "").lower()
        if d == "up":
            self._arrow = "▲"
        elif d == "down":
            self._arrow = "▼"
        else:
            self._arrow = ("──" if d == "flat" else "")
        self._arrow_lbl.setText(self._arrow)
        p = PALETTE[self._theme]
        arrow_col = (p["up"] if d == "up"
                     else p["down"] if d == "down"
                     else p.get("sub", p["text"]))
        self._arrow_lbl.setStyleSheet(
            f"color:{arrow_col};font-size:12px;font-weight:bold;")
        if trend is not None:
            self._trend = list(trend)[-self._TREND_MAX:]
        else:
            self._trend = []
        if tooltip:
            self.setToolTip(tooltip)
        else:
            self.setToolTip("")
        self.update()

    def set_unit(self, u: str) -> None:
        """设置单位后缀（空则隐藏）。"""
        self._unit.setText(str(u))
        self._unit.setVisible(bool(u))

    def set_sub(self, s: str) -> None:
        """设置副提示行（空则隐藏）。"""
        self._sub.setText(str(s))
        self._sub.setVisible(bool(s))

    def set_bar(self, frac: float, color: str = "") -> None:
        """设置底部比例条（0~1）。"""
        self._bar_frac = max(0.0, min(1.0, frac))
        self._bar_color = color or pal()["accent"]
        self.update()

    def set_theme(self, t: str) -> None:
        """设置主题。"""
        self._theme = t
        self._apply()
        self.update()

    def _apply(self) -> None:
        """应用相关对象。"""
        p = PALETTE[self._theme]
        self.setStyleSheet(
            f"QFrame#stat{{background:{p['card']};border:1px solid {p['border']};"
            f"border-radius:10px;}}")
        lab_size = 10 if self._compact else 11
        unit_size = 10 if self._compact else 11
        self._lab.setStyleSheet(f"color:{p['sub']};font-size:{lab_size}px;")
        self._unit.setStyleSheet(f"color:{p['sub']};font-size:{unit_size}px;font-weight:bold;")
        self._sub.setStyleSheet(f"color:{p['sub']};font-size:10px;")
        if not self._arrow_lbl.styleSheet():
            self._arrow_lbl.setStyleSheet(
                f"color:{p['sub']};font-size:12px;font-weight:bold;")
        # 数值颜色在 set_value 中按数据着色，这里仅兜底字号
        if not self._val.styleSheet():
            self._val.setStyleSheet(
                f"color:{p['text']};font-size:{self._val_size}px;font-weight:bold;")

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制底部比例条 + 趋势 sparkline（叠加在样式表背景之上）。"""
        super().paintEvent(event)
        if self._bar_frac > 0:
            pp = QPainter(self)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self.rect()
            h = 3
            bar_w = int(r.width() * self._bar_frac)
            pp.fillRect(r.x(), r.bottom() - h, bar_w, h, QColor(self._bar_color))

        # 趋势 sparkline（仅紧凑 KPI 卡绘制，避免行高高耸）
        if not self._trend or not self._compact:
            return
        try:
            pp = QPainter(self)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self.rect()
            # sparkline 区域：底层就是卡片内部，靠左边留出箭头宽度，右侧不贴边
            pad_l = 18
            pad_r = 6
            pad_t = 2
            plot = QRectF(r.x() + pad_l, r.y() + pad_t,
                          r.width() - pad_l - pad_r, max(1, r.height() - pad_t - 10))
            if plot.width() <= 0 or plot.height() <= 0:
                return
            vals = list(self._trend)
            if len(vals) < 2:
                return
            vmin = min(vals)
            vmax = max(vals)
            if vmax - vmin < 1e-9:
                vmax = vmin + 1e-9
            pts: list = []
            for i, v in enumerate(vals):
                x = plot.x() + (i / (len(vals) - 1)) * plot.width()
                y = plot.y() + plot.height() - ((v - vmin) / (vmax - vmin)) * plot.height()
                pts.append(QPointF(x, y))
            p = PALETTE[self._theme]
            last_up = (vals[-1] >= vals[0]) if len(vals) >= 2 else True
            line_col = QColor(p["up"] if last_up else p["down"])
            line_col.setAlpha(180)
            pp.setPen(line_col)
            pp.setBrush(Qt.BrushStyle.NoBrush)
            pp.drawPolyline(*pts)
            # 末端圆点
            if pts:
                pp.setPen(Qt.PenStyle.NoPen)
                pp.setBrush(line_col)
                pp.drawEllipse(pts[-1], 2.5, 2.5)
        except Exception:  # noqa: BLE001
            pass


# ============================================================================
# 表格比例条代理 BarDelegate
# ============================================================================
class BarDelegate(QStyledItemDelegate):
    """表格比例条代理：在单元格内绘制按比例填充的色条 + 文本。

    每格数据经 ItemDataRole 注入：
      UserRole    -> 数值（float，用于比例计算与正负着色）
      UserRole+1  -> 颜色（str，正红负绿）
      UserRole+2  -> 比例（0~1，已按列归一化）
    显示文本沿用 DisplayRole（已格式化好的字符串），保证数值精准、标签明确。
    """

    def __init__(self, theme: Optional[str] = None) -> None:
        """初始化代理。

        参数:
            theme: 主题"""
        super().__init__()
        self._theme = THEME if theme is None else theme

    def set_theme(self, t: str) -> None:
        """设置主题。"""
        self._theme = t

    def paint(self, painter: "QPainter", option, index) -> None:  # noqa: N802
        """绘制比例条 + 文本。"""
        p = PALETTE[self._theme]
        rect = option.rect
        val = index.data(Qt.ItemDataRole.UserRole)
        color = index.data(Qt.ItemDataRole.UserRole + 1)
        frac = index.data(Qt.ItemDataRole.UserRole + 2)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        # 背景（与隔行底色一致，避免 bar 列与其他列视觉割裂）
        bg = QColor(p["row_alt"]) if (index.row() % 2) else QColor(p["card"])
        painter.fillRect(rect, bg)
        # 比例条
        if isinstance(frac, (int, float)) and frac > 0 and color:
            bar_w = max(2, int(rect.width() * min(1.0, frac)))
            painter.save()
            painter.setClipRect(rect)
            painter.fillRect(rect.x(), rect.y(), bar_w, rect.height(), QColor(color))
            painter.restore()
        # 文本（数值色优先，否则默认文字色）
        tcol = QColor(color) if color else QColor(p["text"])
        painter.setPen(tcol)
        painter.setFont(QFont(_get_font(), 11, QFont.Weight.Bold))
        painter.drawText(rect.adjusted(6, 0, -4, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         str(text))


def _rank_sort_key(d: dict, key: str):
    """返回排序键（数值列按数值，文本列按字符串）。"""
    v = d.get(key, 0)
    return v if isinstance(v, (int, float)) else str(v)


# ============================================================================
# 榜单表格 RankTable（自动排名列 + 点击排序 + 比例条列）
# ============================================================================
class RankTable(QTableWidget):
    """榜单表格：自动排名列（前三奖牌色）+ 可点击表头排序 + 比例条列。

    列定义 cols: [(key, header, kind), ...]，kind ∈ {"text","num","bar"}。
      - text: 文本列，不参与排序；
      - num : 数字列，可点击表头排序（默认降序）；
      - bar : 比例条列（绘制色条 + 数值，可点击排序）。
    行数据：list[dict]，每 dict 的 key 对应列 key；bar 列用数值本身绘制比例，
    数值文本可由 key+"_txt" 字段覆盖（如 sd 表的「+10%」）。
    主题由 set_theme 递归下发（重绘比例条代理）。
    """

    MEDAL = {1: "#fbbf24", 2: "#cbd5e1", 3: "#d97706"}  # 金 / 银 / 铜

    def __init__(self, cols, theme: Optional[str] = None) -> None:
        """初始化榜单表格。

        参数:
            cols: 列定义 [(key, header, kind), ...]
            theme: 主题"""
        headers = ["#"] + [c[1] for c in cols]
        super().__init__(0, len(headers))
        self.setObjectName("rank")
        self._cols = cols
        self._theme = THEME if theme is None else theme
        self._data = []
        self._sort_key = None
        self._sort_asc = False
        self._hover_row = -1

        self.setHorizontalHeaderLabels(headers)
        p = PALETTE[self._theme]
        self.setStyleSheet(
            f"QTableWidget#rank{{border:1px solid {p['border']};"
            f"border-radius:8px;gridline-color:{p['grid']};background:{p['card']};}}")
        vh = self.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(26)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setHighlightSections(False)
        hh.setStyleSheet(
            f"QHeaderView::section{{background:{p['badge_bg']};color:{p['text']};"
            f"font-weight:bold;padding:4px;border:1px solid {p['border']};}}")
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        # 为 bar 列安装比例条代理
        self._bar_delegate = BarDelegate(self._theme)
        for ci, (key, h, kind) in enumerate(self._cols):
            if kind == "bar":
                self.setItemDelegateForColumn(ci + 1, self._bar_delegate)
        hh.sectionClicked.connect(self._on_header)
        self.cellDoubleClicked.connect(self._on_double_click)
        self.cellEntered.connect(self._on_cell_entered)
        # 右键菜单：复制选中行 / 导出 CSV
        self._view = []
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        # 双击回调（行情全景・榜单用）
        self._on_activate = None
        # tooltip 模板（"name / category / chg" 这种字符串，空则按数据）
        self._tooltip_template: str = ""

    def set_rows(self, rows) -> None:
        """设置行数据（list[dict]）并渲染。"""
        self._data = list(rows)
        self._render()

    def _render(self) -> None:
        """渲染：排序 -> 归一化比例 -> 填行。"""
        p = PALETTE[self._theme]
        data = self._data
        if self._sort_key is not None:
            data = sorted(data, key=lambda d: _rank_sort_key(d, self._sort_key),
                          reverse=not self._sort_asc)
        self._view = list(data)  # 记录当前（已排序）展示顺序，供导出/复制使用
        # 归一化 bar 列（同一列共用最大绝对值，保证比例可比）
        bar_max = {}
        for ci, (key, h, kind) in enumerate(self._cols):
            if kind == "bar":
                vals = [abs(float(d.get(key, 0) or 0)) for d in data]
                bar_max[key] = max(vals) if vals and max(vals) > 0 else 1.0
        n = len(data)
        self.setRowCount(n)
        if n:
            self.setColumnWidth(0, 32)  # 排名列固定窄宽
        for i, d in enumerate(data):
            rk = QTableWidgetItem(str(i + 1))
            rk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if i + 1 in self.MEDAL:
                rk.setForeground(QColor(self.MEDAL[i + 1]))
                rk.setFont(QFont(_get_font(), 11, QFont.Weight.Bold))
            self.setItem(i, 0, rk)
            for ci, (key, h, kind) in enumerate(self._cols):
                col = ci + 1
                val = d.get(key, "")
                if kind == "bar":
                    num = float(val) if isinstance(val, (int, float)) else 0.0
                    frac = (abs(num) / bar_max[key]) if bar_max.get(key) else 0.0
                    color = p["up"] if num >= 0 else p["down"]
                    # 前三名把 bar 列改成 medal 色
                    if 1 <= (i + 1) <= 3:
                        color = self.MEDAL.get(i + 1, color)
                    txt = d.get(key + "_txt", f"{num:+,.2f}")
                    item = QTableWidgetItem(str(txt))
                    item.setData(Qt.ItemDataRole.UserRole, num)
                    item.setData(Qt.ItemDataRole.UserRole + 1, color)
                    item.setData(Qt.ItemDataRole.UserRole + 2, frac)
                    item.setForeground(QColor(color))
                    self.setItem(i, col, item)
                else:
                    item = QTableWidgetItem(str(val))
                    item.setForeground(QColor(p["text"]))
                    self.setItem(i, col, item)
        if n:
            prepare_table(self)
        # tooltip 模板：自动逐行设置
        if self._tooltip_template:
            for i, d in enumerate(self._view):
                tip = self._tooltip_template.format(**d)
                for c in range(self.columnCount()):
                    it = self.item(i, c)
                    if it is not None:
                        it.setToolTip(tip)

    def set_on_activate(self, fn) -> None:
        """双击行触发回调：fn(row_dict)。"""
        self._on_activate = fn

    def set_tooltip_template(self, tpl: str) -> None:
        """tooltip 模板：用 str.format(**row) 展开（如 \"{name} · {category}\"）。"""
        self._tooltip_template = tpl
        if self._view:
            for i, d in enumerate(self._view):
                tip = self._tooltip_template.format(**d)
                for c in range(self.columnCount()):
                    it = self.item(i, c)
                    if it is not None:
                        it.setToolTip(tip)

    def _on_header(self, idx: int) -> None:
        """点击表头：切换排序键与方向。"""
        if idx == 0:
            return
        key = self._cols[idx - 1][0]
        kind = self._cols[idx - 1][2]
        if self._sort_key == key:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_key = key
            self._sort_asc = False if kind != "text" else True
        self._render()

    def _on_double_click(self, row: int, col: int) -> None:
        """双击行：如果注册了 on_activate 回调则传入该行元数据。"""
        if self._on_activate and 0 <= row < len(self._view):
            try:
                self._on_activate(self._view[row])
            except Exception:  # noqa: BLE001
                pass

    def _on_cell_entered(self, row: int, col: int) -> None:
        """鼠标进入单元格：高亮整行。"""
        if row == self._hover_row:
            return
        self._clear_row_highlight(self._hover_row)
        self._hover_row = row
        self._highlight_row(row)

    def leaveEvent(self, event) -> None:  # noqa: N802
        """鼠标离开表格：清掉高亮。"""
        self._clear_row_highlight(self._hover_row)
        self._hover_row = -1
        super().leaveEvent(event)

    def _highlight_row(self, row: int) -> None:
        """将指定行背景改为选中色（theme 感知）。"""
        if row < 0:
            return
        p = PALETTE[self._theme]
        sel = p.get("row_sel", "#1f2a44")
        for c in range(self.columnCount()):
            it = self.item(row, c)
            if it is not None:
                it.setBackground(QColor(sel))

    def _clear_row_highlight(self, row: int) -> None:
        """恢复指定行隔行底色。"""
        if row < 0:
            return
        p = PALETTE[self._theme]
        base = QColor(p["card"])
        alt = QColor(p["row_alt"])
        bg = alt if row % 2 else base
        for c in range(self.columnCount()):
            it = self.item(row, c)
            if it is not None:
                it.setBackground(QColor(bg.name()))

    def _on_context_menu(self, pos) -> None:
        """右键菜单：复制选中行 / 导出当前榜单 CSV。"""
        menu = QMenu(self)
        act_copy = QAction("复制选中行", self)
        act_copy.triggered.connect(self._copy_selected)
        menu.addAction(act_copy)
        act_csv = QAction("导出当前榜单为 CSV...", self)
        act_csv.triggered.connect(self._export_csv_dialog)
        menu.addAction(act_csv)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _export_csv_dialog(self) -> None:
        """弹出保存对话框并导出 CSV（utf-8-sig，Excel 友好）。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出榜单", "", "CSV 文件 (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        self._export_csv(path)

    def _export_csv(self, path: str) -> None:
        """导出当前（已排序）榜单为 CSV。

        参数:
            path: 目标文件路径（utf-8-sig 编码，Excel 直接打开中文不乱码）"""
        headers = ["排名"] + [c[1] for c in self._cols]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(headers)
            for i, d in enumerate(self._view):
                row = [i + 1]
                for (key, h, kind) in self._cols:
                    if kind == "bar":
                        row.append(str(d.get(key + "_txt", d.get(key, ""))))
                    else:
                        row.append(str(d.get(key, "")))
                w.writerow(row)

    def _copy_selected(self) -> None:
        """将选中行复制到剪贴板（TSV，首列含排名）。"""
        sel = self.selectedIndexes()
        rows = sorted({idx.row() for idx in sel})
        if not rows or not self._view:
            return
        lines = []
        for ri in rows:
            d = self._view[ri]
            cells = [str(ri + 1)]
            for (key, h, kind) in self._cols:
                if kind == "bar":
                    cells.append(str(d.get(key + "_txt", d.get(key, ""))))
                else:
                    cells.append(str(d.get(key, "")))
            lines.append("\t".join(cells))
        clip = QApplication.instance().clipboard()
        if clip is not None:
            clip.setText("\n".join(lines))

    def set_theme(self, t: str) -> None:
        """设置主题（同步比例条代理并重绘）。"""
        self._theme = t
        p = PALETTE[self._theme]
        self.setStyleSheet(
            f"QTableWidget#rank{{border:1px solid {p['border']};"
            f"border-radius:8px;gridline-color:{p['grid']};background:{p['card']};}}")
        self.horizontalHeader().setStyleSheet(
            f"QHeaderView::section{{background:{p['badge_bg']};color:{p['text']};"
            f"font-weight:bold;padding:4px;border:1px solid {p['border']};}}")
        self._bar_delegate.set_theme(t)
        self._render()
