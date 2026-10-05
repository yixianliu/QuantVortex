"""富文本 Tooltip 组件（期货量化系统 UI）。

设计目标：
    - 支持标题 / 正文 / 快捷键 / 状态点 4 种内容变体；
    - 延迟 450ms 显示，鼠标移出立即隐藏；
    - 随主题自动刷新（paintEvent 自绘，无 inline 样式残留）；
    - 零额外依赖，纯 PyQt6 + QPainter。

使用方式：
    tooltip = RichTooltip()
    tooltip.attach(widget, "标题", "正文内容", shortcut="Ctrl+Enter")
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QFrame, QApplication, QLabel

from .widgets import PALETTE, THEME, pal, _responsive_font, _responsive_size
from .states import paint_guard


class RichTooltip(QFrame):
    """富文本 Tooltip：延迟显示、4 种变体、主题感知。"""

    DELAY_MS = 450
    FONT_TITLE = 13
    FONT_BODY = 12
    FONT_SHORTCUT = 11
    PADDING_X = 12
    PADDING_Y = 8
    BORDER_RADIUS = 8
    MAX_WIDTH = 420

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = THEME
        self._title = ""
        self._body = ""
        self._shortcut = ""
        self._status_text = ""
        self._status_color = ""
        self._target: Optional[QWidget] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS)
        self._timer.timeout.connect(self._show)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

    def attach(
        self,
        widget: QWidget,
        title: str = "",
        body: str = "",
        shortcut: str = "",
        status: str = "",
        status_color: str = "",
    ) -> None:
        """绑定目标控件并配置 Tooltip 内容。"""
        self._target = widget
        self._title = title
        self._body = body
        self._shortcut = shortcut
        self._status_text = status
        self._status_color = status_color or pal().get("accent", "")
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        """处理鼠标进入/离开事件，延迟显示 Tooltip。"""
        if obj is self._target:
            et = event.type()
            if et == event.Type.MouseMove or et == event.Type.HoverMove:
                if self._hidden:
                    self._timer.start()
            elif et == event.Type.Leave:
                self._hide()
        return super().eventFilter(obj, event)

    def _show(self) -> None:
        """显示 Tooltip。"""
        if self._target is None:
            return
        self.adjustSize()
        pos = self._target.mapToGlobal(QPoint(0, self._target.height()))
        self.move(pos.x(), pos.y() + 4)
        self._apply()
        self.show()

    def _hide(self) -> None:
        """隐藏 Tooltip。"""
        self._timer.stop()
        self.hide()

    @property
    def _hidden(self) -> bool:
        return not self.isVisible()

    def set_theme(self, t: str) -> None:
        """切换主题。"""
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        """应用主题样式。"""
        p = PALETTE[self._theme]
        self.setStyleSheet(
            f"QFrame{{background:{p['panel']};border:1px solid {p['border']};"
            f"border-radius:{self.BORDER_RADIUS}px;}}")

    @paint_guard
    def paintEvent(self, event) -> None:  # noqa: N802
        """自绘 Tooltip 内容（标题/正文/快捷键/状态点）。"""
        p = PALETTE[self._theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(p["panel"])))
        painter.drawRoundedRect(self.rect(), self.BORDER_RADIUS, self.BORDER_RADIUS)

        pen = QPen(QColor(p["border"]))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), self.BORDER_RADIUS, self.BORDER_RADIUS)

        x = self.PADDING_X
        y = self.PADDING_Y
        line_h = _responsive_font(self.FONT_BODY) * 1.5

        # 状态点
        if self._status_text:
            dot_r = 5
            dot_y = y + dot_r
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(self._status_color or p["accent"])))
            painter.drawEllipse(QRectF(x, dot_y - dot_r, dot_r * 2, dot_r * 2))
            x += dot_r * 2 + 6

        # 标题
        if self._title:
            f = QFont()
            f.setPixelSize(_responsive_font(self.FONT_TITLE))
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QPen(QColor(p["text"])))
            painter.drawText(x, y + _responsive_font(self.FONT_TITLE) + 2, self._title)
            y += _responsive_font(self.FONT_TITLE) + 4

        # 正文
        if self._body:
            f = QFont()
            f.setPixelSize(_responsive_font(self.FONT_BODY))
            painter.setFont(f)
            painter.setPen(QPen(QColor(p["text"])))
            rect = QRectF(x, y, self.width() - x - self.PADDING_X, self.height() - y - self.PADDING_Y)
            painter.drawText(rect, Qt.TextFlag.TextWordWrap, self._body)
            y += _responsive_font(self.FONT_BODY) + 2

        # 快捷键
        if self._shortcut:
            f = QFont()
            f.setPixelSize(_responsive_font(self.FONT_SHORTCUT))
            painter.setFont(f)
            painter.setPen(QPen(QColor(p["sub"])))
            rect = QRectF(x, y, self.width() - x - self.PADDING_X, _responsive_font(self.FONT_SHORTCUT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._shortcut)

        painter.end()


class HoverTooltip:
    """鼠标悬停 Tooltip 管理器：延迟显示，自动跟随控件。"""

    def __init__(self, tooltip: RichTooltip) -> None:
        self._tooltip = tooltip
        self._target: Optional[QWidget] = None
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(RichTooltip.DELAY_MS)
        self._timer.timeout.connect(self._show)

    def attach(self, widget: QWidget, **kwargs) -> None:
        """绑定控件，配置 Tooltip 内容。"""
        self._target = widget
        self._tooltip.attach(widget, **kwargs)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._target:
            et = event.type()
            if et == event.Type.MouseMove or et == event.Type.HoverMove:
                if not self._tooltip.isVisible():
                    self._timer.start()
            elif et == event.Type.Leave:
                self._hide()
        return False

    def _show(self) -> None:
        self._tooltip._show()

    def _hide(self) -> None:
        self._timer.stop()
        self._tooltip._hide()
