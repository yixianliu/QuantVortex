"""通用 UI 组件与状态（M4-07 · 组件补齐）。

本模块提供六个跨页面复用的基础组件，统一「主题可刷新 + 空态可占位 + 自绘优先」
三条约定，供 M4-08（表格能力铺开）等后续任务直接替换现有手写实现：

    1. :class:`Card`       —— 圆角容器 + 可选标题 + accent 左边条；
    2. :class:`EmptyState` —— 空状态占位（图标 + 主文案 + 次文案 + 可选行动按钮）；
    3. :class:`Skeleton`   —— 骨架屏（自绘 shimmer，受 ``MOTION`` 门控）；
    4. :class:`Toast`      —— 独立浮层提示（info/warn/error 三色 + 堆叠队列）；
    5. :class:`DataGrid`   —— 增强表格（排序 + 右键菜单 + 列显隐 + 空态占位）；
    6. :class:`Pagination` —— 分页控件（页码 / 每页条数 + 变更信号）。

设计约定（沿用 M4-05 结论）：
    - **主题色一律在 paintEvent / ``_style_static()`` 中读取**，不在构建期写死，
      否则切主题后样式不刷新；
    - 每个组件都实现 ``set_theme(t)``，由 ``BasePage.set_theme`` 递归下发；
    - 自绘一律走 :func:`paint_guard`，避免 ``paintEvent`` 抛异常触发 qFatal 直杀进程
      （表现：exit 127 无 traceback）。

运行期开关：
    ``QV_REDUCED_MOTION=1`` 关闭骨架屏 shimmer 等动效（无障碍 / 低性能场景）。
"""
from __future__ import annotations

import csv
import functools
import logging
import os
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTime, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMenu, QProgressBar, QPushButton, QSizePolicy,
    QScrollArea, QScrollBar, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from .paint_utils import paint_guard  # 从独立模块导入，解决循环引用

logger = logging.getLogger(__name__)


# ============================================================================
# 动效门控
# ============================================================================
def _env_flag(name: str, default: bool = False) -> bool:
    """读取布尔型环境变量（1/true/yes/on 视为真）。"""
    raw = os.environ.get(name, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


#: 全局动效开关：``QV_REDUCED_MOTION=1`` 时关闭 shimmer / 脉动等自绘动画。
#: M4-14 会把该常量推广到 StatusTile.pulse / _FadeCover / 数字滚动，此处先落地。
#: UX-75: 已铺开至全部动画入口（widgets.pulse / Skeleton / _SaveSpinner / qr_card hover）
MOTION = not _env_flag("QV_REDUCED_MOTION")


def motion_enabled() -> bool:
    """返回当前动效开关状态（便捷函数，避免导入常量）。

    UX-75: QV_REDUCED_MOTION 门控辅助函数。
    """
    return MOTION


# ============================================================================
# 从 widgets 导入依赖
# ============================================================================
from .widgets import PALETTE, THEME, _responsive_font, _responsive_size, pal


# ============================================================================
# ① Card：圆角容器 + 可选标题 + accent 左边条
# ============================================================================
class Card(QFrame):
    """圆角卡片容器：可选标题行 + 内容区 + 左侧 accent 边条。

    与 ``QFrame`` 手写卡片的区别：
        - accent 边条用 **paintEvent 自绘**（而非 border-left 颜色），切主题自动生效，
          不需要在 ``set_theme`` 里重设样式表（M4-05 教训）；
        - 提供 :meth:`content_layout` 供调用方直接往里塞控件。
    """

    def __init__(self, title: str = "", subtitle: str = "",
                 accent: str = "", theme: Optional[str] = None) -> None:
        """初始化卡片。

        参数:
            title: 标题文本（空则不显示标题行）。
            subtitle: 标题右侧的次级说明（空则不显示）。
            accent: 左侧边条颜色（十六进制）；空则用主题 accent 色。
            theme: 主题名，默认取全局 ``THEME``。
        """
        super().__init__()
        self.setObjectName("card")
        self._theme = THEME if theme is None else theme
        self._accent = accent
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(_responsive_size(12), _responsive_size(10),
                                _responsive_size(12), _responsive_size(10))
        root.setSpacing(_responsive_size(6))

        self._title_lab = QLabel(title)
        self._title_lab.setObjectName("card-title")
        self._sub_lab = QLabel(subtitle)
        self._sub_lab.setObjectName("sub")

        if title:
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(_responsive_size(8))
            head.addWidget(self._title_lab)
            if subtitle:
                head.addWidget(self._sub_lab)
            head.addStretch(1)
            root.addLayout(head)

        self._content = QVBoxLayout()
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(_responsive_size(6))
        root.addLayout(self._content)

        self._apply()

    def content_layout(self) -> QVBoxLayout:
        """返回内容区布局，供调用方直接 addWidget。"""
        return self._content

    def set_title(self, title: str, subtitle: str = "") -> None:
        """设置/更新标题与副标题（空标题会隐藏标题行）。"""
        self._title_lab.setText(title)
        self._sub_lab.setText(subtitle)
        self._title_lab.setVisible(bool(title))
        self._sub_lab.setVisible(bool(subtitle))

    def set_accent(self, color: str) -> None:
        """设置左侧 accent 边条颜色（空串回落主题 accent）。"""
        self._accent = color
        self.update()

    def set_theme(self, t: str) -> None:
        """切换主题（背景/边框/文字色随之刷新）。"""
        self._theme = t
        self._apply()
        self.update()

    def _apply(self) -> None:
        """应用主题样式（圆角 + 背景 + 边框 + 标题色）。"""
        p = PALETTE[self._theme]
        radius = _responsive_size(10)
        self.setStyleSheet(
            f"QFrame#card{{background:{p['card']};border:1px solid {p['border']};"
            f"border-radius:{radius}px;}}"
            f"QLabel#card-title{{color:{p['text']};font-size:{_responsive_font(12)}px;"
            f"font-weight:bold;}}"
            f"QLabel#sub{{color:{p['sub']};font-size:{_responsive_font(10)}px;}}")

    @paint_guard
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制左侧 accent 边条（自绘，随主题自动刷新）。"""
        super().paintEvent(event)
        p = PALETTE[self._theme]
        col = QColor(self._accent or p["accent"])
        pp = QPainter(self)
        pp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = _responsive_size(3, min_size=2)
        r = self.rect()
        pp.fillRect(QRect(r.x(), r.y(), w, r.height()), col)


# ============================================================================
# ④ EmptyState：空状态占位
# ============================================================================
class EmptyState(QWidget):
    """空状态占位：大图标 + 主文案 + 次文案 + 可选行动按钮。

    用途：表格无数据、请求失败、功能未配置等场景，避免出现「一片空白」的歧义界面。
    """

    #: 点击行动按钮时发出
    action_clicked = pyqtSignal()

    #: UX-66：空态文案模板（分级文案）
    TEMPLATES = {
        "no_data": {
            "icon": "📭", "title": "暂无数据",
            "subtitle": "点击刷新或导入数据", "action": "",
        },
        "filtered": {
            "icon": "🔍", "title": "无匹配结果",
            "subtitle": "请尝试调整筛选条件", "action": "清除筛选",
        },
        "load_failed": {
            "icon": "⚠️", "title": "加载失败",
            "subtitle": "请检查网络或数据源后重试", "action": "重试",
        },
        "loading": {
            "icon": "⏳", "title": "加载中…",
            "subtitle": "请稍候", "action": "",
        },
        "no_permission": {
            "icon": "🔒", "title": "无权限访问",
            "subtitle": "请联系管理员开通权限", "action": "",
        },
    }

    def __init__(self, icon: str = "📭", title: str = "暂无数据",
                 subtitle: str = "", action_text: str = "",
                 theme: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        """初始化空状态。

        参数:
            icon: 图标（emoji 或单字），绘制在文案上方。
            title: 主文案。
            subtitle: 次级说明。
            action_text: 行动按钮文案（空则不显示按钮）。
            theme: 主题名。
            parent: 父控件（DataGrid 空态覆盖层需显式指定，见 :class:`DataGrid`）。
        """
        super().__init__(parent)
        self._theme = THEME if theme is None else theme
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._icon = QLabel(icon)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setObjectName("empty-icon")
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setObjectName("empty-title")
        self._title.setWordWrap(True)
        self._sub = QLabel(subtitle)
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setObjectName("sub")
        self._sub.setWordWrap(True)
        self._sub.setVisible(bool(subtitle))

        self._btn = QPushButton(action_text)
        self._btn.setObjectName("secondary")
        self._btn.setVisible(bool(action_text))
        self._btn.clicked.connect(self.action_clicked.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(_responsive_size(16), _responsive_size(16),
                                _responsive_size(16), _responsive_size(16))
        root.setSpacing(_responsive_size(6))
        root.addStretch(1)
        root.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._title)
        root.addWidget(self._sub)
        if action_text:
            root.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignCenter)
        root.addStretch(1)
        self._apply()

    def set_template(self, name: str) -> None:
        """UX-66：按模板名称设置空态文案。

        参数:
            name: 模板键（no_data/filtered/load_failed/loading/no_permission）。
        """
        tpl = self.TEMPLATES.get(name, self.TEMPLATES["no_data"])
        self._icon.setText(tpl["icon"])
        self.set_text(tpl["title"], tpl["subtitle"])
        self._btn.setText(tpl["action"])
        self._btn.setVisible(bool(tpl["action"]))

    def set_retry(self, text: str = "重试") -> None:
        """UX-66：设置重试按钮。

        参数:
            text: 按钮文案。
        """
        self._btn.setText(text)
        self._btn.setVisible(True)

    def set_text(self, title: str, subtitle: str = "") -> None:
        """更新主/次文案。"""
        self._title.setText(title)
        self._sub.setText(subtitle)
        self._sub.setVisible(bool(subtitle))

    def set_theme(self, t: str) -> None:
        """切换主题。"""
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        """应用主题样式（图标弱化、主文案强调、次文案弱化）。"""
        p = PALETTE[self._theme]
        self._icon.setStyleSheet(f"font-size:{_responsive_font(28)}px;")
        self._title.setStyleSheet(
            f"color:{p['sub']};font-size:{_responsive_font(13)}px;font-weight:bold;")
        self._sub.setStyleSheet(f"color:{p['sub']};font-size:{_responsive_font(11)}px;")


# ============================================================================
# ⑤ Skeleton：骨架屏（自绘 shimmer）
# ============================================================================
class Skeleton(QWidget):
    """骨架屏：加载期占位，自绘若干「灰块 + 扫光」，避免布局跳动。

    动效受 :data:`MOTION` 门控：``QV_REDUCED_MOTION=1`` 时退化为静态灰块（不启动定时器）。
    """

    _FRAME_MS = 60          # 约 16fps，足够柔和且开销低
    _SWEEP_WIDTH = 0.35     # 扫光宽度占组件宽度比例

    def __init__(self, rows: int = 3, row_height: int = 14,
                 gap: int = 10, theme: Optional[str] = None) -> None:
        """初始化骨架屏。

        参数:
            rows: 灰块行数。
            row_height: 每行高度（px）。
            gap: 行间距（px）。
            theme: 主题名。
        """
        super().__init__()
        self._theme = THEME if theme is None else theme
        self._rows = max(1, int(rows))
        self._row_h = max(4, int(row_height))
        self._gap = max(0, int(gap))
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self._FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.setMinimumHeight(self._rows * (self._row_h + self._gap))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_animation_enabled(MOTION)

    def set_animation_enabled(self, enabled: bool) -> None:
        """开/关 shimmer 动效（关闭后为静态灰块）。"""
        self._anim = bool(enabled) and MOTION
        if self._anim and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def stop_animation(self) -> None:
        """停止动画（用于销毁前清理定时器）。"""
        self._timer.stop()
        self._anim = False

    def set_theme(self, t: str) -> None:
        """切换主题（灰块与扫光色随之刷新）。"""
        self._theme = t
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        """可见时启动动效。"""
        super().showEvent(event)
        if self._anim:
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        """隐藏时停止动效（避免后台定时器空转）。"""
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        """推进扫光相位并重绘。"""
        self._phase = (self._phase + 0.06) % 1.4
        self.update()

    @paint_guard
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制灰块与扫光渐变。"""
        p = PALETTE[self._theme]
        base = QColor(p["row_alt"])
        sweep = QColor(p["accent"])
        sweep.setAlpha(38)          # 极淡扫光，不喧宾夺主

        pp = QPainter(self)
        pp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        y = r.y()
        for i in range(self._rows):
            # 首行占满，其余行右侧留白，模拟「标题 + 正文」层级
            w = r.width() if i == 0 else int(r.width() * 0.72)
            block = QRect(r.x(), y, max(4, w), self._row_h)
            pp.setPen(Qt.PenStyle.NoPen)
            pp.setBrush(base)
            pp.drawRoundedRect(QRectF(block), 4, 4)
            if self._anim:
                cx = r.x() + (self._phase - self._SWEEP_WIDTH) * r.width()
                gw = max(8, int(r.width() * self._SWEEP_WIDTH))
                grad_rect = QRect(int(cx), y, gw, self._row_h)
                pp.setBrush(sweep)
                pp.drawRoundedRect(QRectF(grad_rect), 4, 4)
            y += self._row_h + self._gap


# ============================================================================
# ③ Toast：独立浮层提示（三色 + 堆叠队列）
# ============================================================================
class Toast(QFrame):
    """轻量浮层提示：附着于父窗口顶部居中，自动消失，多条纵向堆叠。

    与 ``BasePage._toast`` 的区别：本组件是**独立浮层**（不占用页面布局空间、
    不挤压内容），支持 info/warn/error 三色与队列堆叠，可作为后者的替代实现。
    """

    _LEVEL_COLOR = {"info": "accent", "warn": "warning", "error": "down"}
    _MARGIN = 12
    _GAP = 8

    #: 每个父窗口的当前堆叠（parent id -> Toast 列表），用于纵向排布
    _stacks: dict[int, list["Toast"]] = {}

    def __init__(self, parent: QWidget, message: str, level: str = "info",
                 duration: int = 2500) -> None:
        """初始化提示。

        参数:
            parent: 附着的目标窗口/页面。
            message: 提示文本。
            level: ``info`` / ``warn`` / ``error``。
            duration: 自动关闭毫秒数（0 = 不自动关闭，需手动 :meth:`dismiss`）。
        """
        super().__init__(parent)
        self.setObjectName("toast")
        self._theme = THEME
        self._level = level if level in self._LEVEL_COLOR else "info"
        self._duration = int(duration)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._lab = QLabel(message)
        self._lab.setObjectName("toast-text")
        self._lab.setWordWrap(True)
        self._lab.setMaximumWidth(420)
        box = QHBoxLayout(self)
        box.setContentsMargins(_responsive_size(12), _responsive_size(8),
                               _responsive_size(12), _responsive_size(8))
        box.addWidget(self._lab)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        self._apply()
        self.adjustSize()

    # ---- 生命周期 ----
    def present(self) -> "Toast":
        """加入父窗口堆叠并显示（返回自身便于链式调用）。"""
        pid = id(self.parent())
        stack = Toast._stacks.setdefault(pid, [])
        stack.append(self)
        try:
            self.parent().installEventFilter(self)
        except Exception:  # noqa: BLE001 - 父对象可能已销毁
            pass
        self._layout_stack()
        self.show()
        self.raise_()
        if self._duration > 0:
            self._timer.start(self._duration)
        return self

    def dismiss(self) -> None:
        """关闭并从堆叠移除（安全重复调用）。"""
        try:
            self._timer.stop()
        except Exception:  # noqa: BLE001
            pass
        pid = id(self.parent()) if self.parent() is not None else 0
        stack = Toast._stacks.get(pid)
        if stack and self in stack:
            stack.remove(self)
        try:
            if self.parent() is not None:
                self.parent().removeEventFilter(self)
        except Exception:  # noqa: BLE001
            pass
        self.close()
        self.deleteLater()
        if stack is not None:
            Toast._relayout(pid)

    def set_theme(self, t: str) -> None:
        """切换主题。"""
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        """应用主题样式（底色 + 左侧色条 + 圆角 + 阴影替代边框）。"""
        p = PALETTE[self._theme]
        col = p[self._LEVEL_COLOR[self._level]]
        radius = _responsive_size(8)
        self.setStyleSheet(
            f"QFrame#toast{{background:{p['panel']};border:1px solid {col};"
            f"border-radius:{radius}px;}}"
            f"QLabel#toast-text{{color:{p['text']};font-size:{_responsive_font(11)}px;}}")

    def _layout_stack(self) -> None:
        """按当前堆叠顺序纵向排布（顶部居中，自上而下）。"""
        pid = id(self.parent())
        Toast._relayout(pid)

    @classmethod
    def _relayout(cls, pid: int) -> None:
        """重新排布某父窗口下的全部 Toast。"""
        stack = cls._stacks.get(pid)
        if not stack:
            cls._stacks.pop(pid, None)
            return
        parent = stack[0].parent()
        if parent is None:
            return
        y = cls._MARGIN
        for t in stack:
            t.adjustSize()
            x = max(cls._MARGIN, (parent.width() - t.width()) // 2)
            t.move(QPoint(x, y))
            y += t.height() + cls._GAP

    def eventFilter(self, obj, event) -> bool:  # noqa: N802, ANN001
        """父窗口尺寸变化时重排，避免 Toast 悬在错误位置。"""
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self._layout_stack()
        return False

    @paint_guard
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制左侧等级色条（自绘，随主题刷新）。"""
        super().paintEvent(event)
        p = PALETTE[self._theme]
        col = QColor(p[self._LEVEL_COLOR[self._level]])
        pp = QPainter(self)
        pp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        pp.fillRect(QRect(r.x(), r.y(), _responsive_size(3, min_size=2), r.height()), col)


def toast(parent: QWidget, message: str, level: str = "info",
          duration: int = 2500) -> Toast:
    """在 ``parent`` 上弹出一条浮层提示（便捷工厂）。

    参数:
        parent: 目标窗口/页面。
        message: 提示文本。
        level: ``info`` / ``warn`` / ``error``。
        duration: 自动关闭毫秒数。

    返回:
        Toast：已显示，可再调 ``dismiss()`` 提前关闭。
    """
    return Toast(parent, message, level=level, duration=duration).present()


# ============================================================================
# ② DataGrid：增强表格
# ============================================================================
class DataGrid(QTableWidget):
    """增强表格：默认排序 + 右键菜单 + 列显隐 + 空态占位。

    相对裸 ``QTableWidget`` 补齐的能力（对应 M4-08 铺开的统一能力）：
        - 点击表头排序（``sortingEnabled`` 默认开，用 ``setCellWidget`` 的表应传
          ``sortable=False``）；
        - 右键菜单：复制行 / 复制单元格 / 导出 CSV / 列显隐；
        - 行数为 0 时自动叠加 :class:`EmptyState` 占位；
        - 双击行联动：默认「复制整行 + Toast 提示」，可用 :meth:`set_row_action`
          换成页面自定义语义；
        - ``set_theme`` 统一隔行底色与选中色。
    """

    #: 双击某一行时发出（参数为行号，从 0 开始）
    row_double_clicked = pyqtSignal(int)

    def __init__(self, rows: int = 0, cols: int = 0, parent: Optional[QWidget] = None,
                 empty_title: str = "暂无数据", empty_subtitle: str = "",
                 sortable: bool = True) -> None:
        """初始化表格。

        参数:
            rows: 初始行数。
            cols: 初始列数。
            parent: 父控件。
            empty_title: 空态主文案。
            empty_subtitle: 空态次文案。
            sortable: 是否允许点击表头排序。**使用 ``setCellWidget`` 的表应传 False**——
                排序会重排数据行，而单元格控件不跟随（表现为控件错位/消失）。
        """
        super().__init__(rows, cols, parent)
        self._theme = THEME
        self._sortable = bool(sortable)
        # 关键：**不要**打开 Qt 的 setSortingEnabled(True)。
        # Qt 会在每次 setItem 后自动重排，而业务代码是按“插入顺序 + 行下标”批量填充的，
        # 行位置在填充过程中被反复打乱 → 单元格互相覆盖/丢失（实测 26 格只剩 14 格有值）。
        # 改为：内部始终关闭自动排序，由表头点击时手动 sortItems 一次性排序。
        self.setSortingEnabled(False)
        self._sort_col = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        if self._sortable:
            hdr = self.horizontalHeader()
            hdr.setSortIndicatorShown(True)
            hdr.sectionClicked.connect(self._on_header_clicked)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.cellDoubleClicked.connect(self._on_double_click)
        self._row_action: Optional[Callable[[int], None]] = None
        # M4-14②：无障碍名称/描述（读屏器可辨识；子类/实例可再覆盖）
        self.setAccessibleName("数据表格")
        self.setAccessibleDescription(
            "支持表头排序、右键复制/导出 CSV、列显隐")

        # 空态覆盖层挂在本表格上（**不要**挂到 viewport()）：viewport 是 Qt 内部
        # 子控件，把 Python 持有的 QWidget 塞进去会在销毁期出现析构顺序错乱，
        # 表现为进程被硬杀（exit 127，无 traceback）。改为挂 self + 按视口几何定位。
        self._empty = EmptyState("📭", empty_title, empty_subtitle,
                                 theme=self._theme, parent=self)
        self._empty.hide()
        self._sync_empty()

        # 注意：**不要**连接 model 的 rowsInserted/rowsRemoved/modelReset。
        # 表格销毁（或清空行）时这些信号仍会触发，回调会触摸已半销毁的 C++ 对象，
        # 进程被硬杀（exit 127，无 traceback）。改用 setRowCount / clear 覆写兜底。

    # ---- 空态 ----
    def set_empty_text(self, title: str, subtitle: str = "") -> None:
        """设置空态文案。"""
        self._empty.set_text(title, subtitle)

    def _sync_empty(self) -> None:
        """按当前行数显示/隐藏空态占位，并铺满视口。"""
        empty = self.rowCount() == 0
        self._empty.setVisible(empty)
        if empty:
            vp = self.viewport()
            # 视口几何是相对本表格的，直接用即可让覆盖层正好盖住数据区
            self._empty.setGeometry(QRect(vp.x(), vp.y(),
                                          max(0, vp.width()), max(0, vp.height())))
            self._empty.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """视口尺寸变化时同步空态占位尺寸。"""
        super().resizeEvent(event)
        if self._empty.isVisible():
            vp = self.viewport()
            self._empty.setGeometry(QRect(vp.x(), vp.y(), vp.width(), vp.height()))

    def setRowCount(self, rows: int) -> None:  # noqa: N802
        """覆写：行数变化后同步空态（不依赖 model 信号，见构造中的说明）。"""
        super().setRowCount(rows)
        self._sync_empty()

    def clear(self) -> None:
        """覆写：清空表格后同步空态（保留表头）。"""
        super().clear()
        self._sync_empty()

    # ---- 排序（手动模式，见构造注释） ----
    def is_sortable(self) -> bool:
        """是否允许点击表头排序（区别于 Qt 的 ``isSortingEnabled`` 自动排序）。"""
        return self._sortable

    def _on_header_clicked(self, index: int) -> None:
        """表头点击：同列切换升/降序，异列重置为升序，然后一次性排序。"""
        if index < 0:
            return
        if self._sort_col == index:
            self._sort_order = (Qt.SortOrder.DescendingOrder
                                if self._sort_order == Qt.SortOrder.AscendingOrder
                                else Qt.SortOrder.AscendingOrder)
        else:
            self._sort_col = index
            self._sort_order = Qt.SortOrder.AscendingOrder
        self.horizontalHeader().setSortIndicator(index, self._sort_order)
        # sortItems 直接对 item 排序，不依赖 Qt 自动排序机制
        self.sortItems(index, self._sort_order)
        self._sort_col = index      # sortItems 不会改动列，保持记录
        self._sync_empty()

    # ---- 双击行联动 ----
    def set_row_action(self, handler: Optional[Callable[[int], None]]) -> None:
        """设置双击行的页面自定义动作（``None`` 恢复默认「复制整行 + Toast」）。

        参数:
            handler: 接收行号的可调用对象；设置后不再执行默认复制行为。
        """
        self._row_action = handler

    def _on_double_click(self, row: int, col: int) -> None:
        """双击行：优先走页面自定义动作，否则复制整行并提示。"""
        if row < 0:
            return
        if self._row_action is not None:
            self._row_action(row)
            self.row_double_clicked.emit(row)
            return
        self.setCurrentCell(row, max(0, col))
        self.copy_row()
        try:
            toast(self, f"已复制第 {row + 1} 行", level="info", duration=1400)
        except Exception:  # noqa: BLE001 - 提示失败不应影响主流程
            pass
        self.row_double_clicked.emit(row)

    # ---- 右键菜单（UX-57 语义分级） ----
    def _menu(self, pos: QPoint) -> None:
        """UX-57：语义分级右键菜单（行操作 / 复制 / 导出 / 列）。"""
        menu = QMenu(self)
        # 行操作区
        if self._row_action is not None:
            act_row = menu.addAction("📋 打开详情…")
            act_row.triggered.connect(lambda: self._row_action(self.currentRow()))
        act_copy_row = menu.addAction("复制整行 (TSV)")
        act_copy_cell = menu.addAction("复制单元格")
        menu.addSeparator()
        # 复制多格式区
        copy_menu = menu.addMenu("复制为…")
        act_tsv = copy_menu.addAction("TSV (制表符)")
        act_csv = copy_menu.addAction("CSV")
        act_md = copy_menu.addAction("Markdown")
        act_json = copy_menu.addAction("JSON")
        menu.addSeparator()
        # 导出区
        act_csv_export = menu.addAction("导出 CSV…")
        act_excel_export = menu.addAction("导出 Excel…")
        menu.addSeparator()
        # 列设置区
        col_menu = menu.addMenu("列显隐")
        for c in range(self.columnCount()):
            header = self.horizontalHeaderItem(c)
            name = header.text() if header is not None else f"列 {c + 1}"
            act = col_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(not self.isColumnHidden(c))
            act.triggered.connect(
                lambda _v, cc=c: self.setColumnHidden(cc, not self.isColumnHidden(cc)))
        act_col_settings = menu.addAction("💾 保存列设置…")
        act_load_settings = menu.addAction("📂 加载列设置…")

        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen == act_copy_row:
            self.copy_tsv()
        elif chosen == act_copy_cell:
            self.copy_cell()
        elif chosen == act_tsv:
            self.copy_tsv()
        elif chosen == act_csv:
            self.copy_csv()
        elif chosen == act_md:
            self.copy_markdown()
        elif chosen == act_json:
            self.copy_json()
        elif chosen == act_csv_export:
            self.export_csv()
        elif chosen == act_excel_export:
            self.export_excel()
        elif chosen == act_col_settings:
            path, _ = QFileDialog.getSaveFileName(
                self, "保存列设置", "grid_state.json", "JSON (*.json)")
            if path:
                self.save_state(path)
        elif chosen == act_load_settings:
            path, _ = QFileDialog.getOpenFileName(
                self, "加载列设置", "grid_state.json", "JSON (*.json)")
            if path:
                self.load_state(path)

    def _current_row_text(self) -> str:
        """当前行文本（制表符分隔）。"""
        r = self.currentRow()
        if r < 0:
            return ""
        return "\t".join(self._cell_text(r, c) for c in range(self.columnCount()))

    def _cell_text(self, r: int, c: int) -> str:
        """取单元格显示文本（无 item 时读模型数据）。"""
        it = self.item(r, c)
        if it is not None:
            return it.text()
        idx = self.model().index(r, c) if self.model() is not None else None
        return str(idx.data()) if idx is not None else ""

    def copy_row(self) -> None:
        """复制当前行到剪贴板（Tab 分隔，可直接粘贴进 Excel）。"""
        text = self._current_row_text()
        if text and QApplication.instance() is not None:
            QApplication.clipboard().setText(text)

    def copy_cell(self) -> None:
        """复制当前单元格到剪贴板。"""
        r, c = self.currentRow(), self.currentColumn()
        if r >= 0 and c >= 0 and QApplication.instance() is not None:
            QApplication.clipboard().setText(self._cell_text(r, c))

    def export_csv(self, path: Optional[str] = None) -> Optional[str]:
        """导出全表为 CSV（``utf-8-sig``，Excel 直接打开不乱码）。

        参数:
            path: 目标路径；为空则弹保存对话框。

        返回:
            写入成功的路径；用户取消或失败返回 None。
        """
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "table.csv", "CSV (*.csv)")
        if not path:
            return None
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow([
                    (self.horizontalHeaderItem(c).text()
                     if self.horizontalHeaderItem(c) is not None else f"列 {c + 1}")
                    for c in range(self.columnCount())
                ])
                for r in range(self.rowCount()):
                    if self.isRowHidden(r):
                        continue
                    writer.writerow([self._cell_text(r, c) for c in range(self.columnCount())])
            return path
        except OSError as exc:
            logger.warning("导出 CSV 失败：%s", exc)
            return None

    # ---- 主题 ----
    def set_theme(self, t: str) -> None:
        """切换主题（隔行底色 + 选中色 + 空态同步）。"""
        self._theme = t
        p = PALETTE[t]
        self.setStyleSheet(
            f"QTableWidget{{background:{p['card']};alternate-background-color:{p['row_alt']};"
            f"color:{p['text']};gridline-color:{p['grid']};}}"
            f"QHeaderView::section{{background:{p['panel']};color:{p['sub']};"
            f"border:0;border-right:1px solid {p['border']};padding:4px;}}")
        self._empty.set_theme(t)

    def stretch_columns(self) -> None:
        """所有列等宽铺满（常用收尾调用）。"""
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    # ---- UX-50：批量填充（setUpdatesEnabled + blockSignals） ----
    def fill_bulk(self, rows: int, cols: int, data: list[list]) -> None:
        """UX-50：批量填充表格数据（10k 行 ≤ 300ms）。

        参数:
            rows: 数据行数。
            cols: 数据列数。
            data: 二维列表 [[r0c0, r0c1, ...], [r1c0, ...], ...]。
        """
        self.setUpdatesEnabled(False)
        self.blockSignals(True)
        try:
            self.setRowCount(rows)
            self.setColumnCount(cols)
            for r, row_data in enumerate(data):
                for c, val in enumerate(row_data):
                    if val is not None:
                        item = QTableWidgetItem(str(val))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                                              Qt.AlignmentFlag.AlignLeft)
                        self.setItem(r, c, item)
        finally:
            self.blockSignals(False)
            self.setUpdatesEnabled(True)
        self._sync_empty()

    # ---- UX-54：多格式复制（TSV/CSV/Markdown/JSON） ----
    def _grid_to_rows(self) -> list[list[str]]:
        """导出全表为二维字符串列表（含表头）。"""
        rows = []
        rows.append([
            (self.horizontalHeaderItem(c).text()
             if self.horizontalHeaderItem(c) is not None else f"列 {c + 1}")
            for c in range(self.columnCount())
        ])
        for r in range(self.rowCount()):
            if self.isRowHidden(r):
                continue
            rows.append([self._cell_text(r, c) for c in range(self.columnCount())])
        return rows

    def copy_as(self, fmt: str = "tsv") -> str:
        """UX-54：多格式复制。返回复制文本，同时写入剪贴板。

        参数:
            fmt: "tsv" | "csv" | "markdown" | "json"

        返回:
            复制的文本内容。
        """
        rows = self._grid_to_rows()
        if not rows:
            return ""
        if fmt == "csv":
            import io
            buf = io.StringIO()
            csv.writer(buf, lineterminator="\n").writerows(rows)
            text = buf.getvalue()
        elif fmt == "markdown":
            lines = ["| " + " | ".join(rows[0]) + " |"]
            lines.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
            for row in rows[1:]:
                lines.append("| " + " | ".join(row) + " |")
            text = "\n".join(lines)
        elif fmt == "json":
            import json
            headers = rows[0]
            items = [dict(zip(headers, row)) for row in rows[1:]]
            text = json.dumps(items, ensure_ascii=False, indent=2)
        else:  # tsv (default)
            text = "\n".join("\t".join(row) for row in rows)
        if QApplication.instance() is not None:
            QApplication.clipboard().setText(text)
        return text

    def copy_tsv(self) -> None:
        """UX-54：复制 TSV 格式（默认）。"""
        self.copy_as("tsv")

    def copy_csv(self) -> None:
        """UX-54：复制 CSV 格式。"""
        self.copy_as("csv")

    def copy_markdown(self) -> None:
        """UX-54：复制 Markdown 表格格式。"""
        self.copy_as("markdown")

    def copy_json(self) -> None:
        """UX-54：复制 JSON 格式。"""
        self.copy_as("json")

    # ---- UX-53：列设置持久化 ----
    def save_state(self, path: str) -> None:
        """UX-53：保存列设置到 JSON（列显隐、列宽、排序态）。"""
        import json
        state = {
            "columns": {
                str(c): {
                    "hidden": self.isColumnHidden(c),
                    "width": self.columnWidth(c),
                }
                for c in range(self.columnCount())
            },
            "sort_col": self._sort_col,
            "sort_order": "asc" if self._sort_order == Qt.SortOrder.AscendingOrder else "desc",
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_state(self, path: str) -> bool:
        """UX-53：从 JSON 恢复列设置。返回是否成功。"""
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            for c_str, cfg in state.get("columns", {}).items():
                c = int(c_str)
                if c < self.columnCount():
                    self.setColumnHidden(c, cfg.get("hidden", False))
                    self.setColumnWidth(c, cfg.get("width", 100))
            if "sort_col" in state:
                self._sort_col = state["sort_col"]
                self._sort_order = (Qt.SortOrder.AscendingOrder
                                    if state.get("sort_order") == "asc"
                                    else Qt.SortOrder.DescendingOrder)
                if self._sort_col >= 0:
                    self.horizontalHeader().setSortIndicator(self._sort_col, self._sort_order)
            return True
        except Exception:
            return False

    # ---- UX-56：Excel 导出（openpyxl 软依赖） ----
    def export_excel(self, path: Optional[str] = None) -> Optional[str]:
        """UX-56：导出 Excel（openpyxl 软依赖，缺失降级 CSV）。

        参数:
            path: 目标路径；为空则弹保存对话框。

        返回:
            写入成功的路径；用户取消或失败返回 None。
        """
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "table.xlsx",
                                                   "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return None
        try:
            from openpyxl import Workbook
        except ImportError:
            # openpyxl 不可用，降级为 CSV
            return self.export_csv(path)
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Data"
            rows = self._grid_to_rows()
            for row in rows:
                ws.append(row)
            wb.save(path)
            return path
        except Exception as exc:
            logger.warning("导出 Excel 失败：%s", exc)
            return None

    # ---- UX-52：条件格式（色阶/涨跌箭头/阈值着色） ----
    def apply_color_scale(self, col: int, lo: float, hi: float,
                          low_color: str = "#22c55e", mid_color: str = "#fbbf24",
                          high_color: str = "#ef4444") -> None:
        """UX-52：数值色阶着色（红绿渐变）。

        参数:
            col: 列索引。
            lo: 最小值。
            hi: 最大值。
            low_color: 低值颜色。
            mid_color: 中值颜色。
            high_color: 高值颜色。
        """
        if lo == hi:
            return
        for r in range(self.rowCount()):
            item = self.item(r, col)
            if item is None:
                continue
            try:
                val = float(item.text())
            except (ValueError, TypeError):
                continue
            t = max(0.0, min(1.0, (val - lo) / (hi - lo)))
            color = self._lerp_color(low_color, mid_color, high_color, t)
            item.setBackground(QColor(color))

    def apply_arrow(self, col: int, threshold: float = 0.0) -> None:
        """UX-52：涨跌箭头着色（>阈值绿色↑，<阈值红色↓，=阈值灰色）。

        参数:
            col: 列索引。
            threshold: 零线阈值。
        """
        pal = pal(self._theme)
        up_color = QColor(pal.get("up", "#ef4444"))
        down_color = QColor(pal.get("down", "#22c55e"))
        sub_color = QColor(pal.get("sub", "#64748b"))
        for r in range(self.rowCount()):
            item = self.item(r, col)
            if item is None:
                continue
            text = item.text()
            try:
                val = float(text.replace("+", "").replace("%", "").replace(",", ""))
            except (ValueError, TypeError):
                continue
            if val > threshold:
                item.setText(f"↑ {text}")
                item.setForeground(up_color)
            elif val < threshold:
                item.setText(f"↓ {text}")
                item.setForeground(down_color)
            else:
                item.setForeground(sub_color)

    def apply_threshold(self, col: int, warn_at: float, crit_at: float,
                        warn_color: str = "#fbbf24", crit_color: str = "#ef4444") -> None:
        """UX-52：阈值着色（超过 warn 黄色，超过 crit 红色）。

        参数:
            col: 列索引。
            warn_at: 警告阈值。
            crit_at: 严重阈值。
            warn_color: 警告色。
            crit_color: 严重色。
        """
        for r in range(self.rowCount()):
            item = self.item(r, col)
            if item is None:
                continue
            try:
                val = float(item.text().replace(",", "").replace("%", ""))
            except (ValueError, TypeError):
                continue
            if val >= crit_at:
                item.setBackground(QColor(crit_color))
            elif val >= warn_at:
                item.setBackground(QColor(warn_color))

    @staticmethod
    def _lerp_color(c1: str, c2: str, c3: str, t: float) -> str:
        """三色调色板线性插值（t=0→c1, t=0.5→c2, t=1→c3）。"""
        def parse(c: str) -> tuple[int, int, int]:
            c = c.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        if t <= 0.5:
            r1, g1, b1 = parse(c1)
            r2, g2, b2 = parse(c2)
            tt = t * 2
        else:
            r1, g1, b1 = parse(c2)
            r2, g2, b2 = parse(c3)
            tt = (t - 0.5) * 2
        r = int(r1 + (r2 - r1) * tt)
        g = int(g1 + (g2 - g1) * tt)
        b = int(b1 + (b2 - b1) * tt)
        return f"#{r:02x}{g:02x}{b:02x}"

    # ---- UX-55：搜索/筛选（文本匹配隐藏行） ----
    def search_filter(self, keyword: str) -> int:
        """UX-55：按关键字筛选行（隐藏不匹配行）。

        参数:
            keyword: 搜索关键字；空字符串清除筛选。

        返回:
            匹配的行数。
        """
        keyword_lower = keyword.strip().lower()
        matched = 0
        for r in range(self.rowCount()):
            if not keyword_lower:
                self.setRowHidden(r, False)
                matched += 1
                continue
            row_text = " ".join(self._cell_text(r, c) for c in range(self.columnCount()))
            if keyword_lower in row_text.lower():
                self.setRowHidden(r, False)
                matched += 1
            else:
                self.setRowHidden(r, True)
        self._sync_empty()
        return matched

    def clear_filter(self) -> None:
        """UX-55：清除筛选（显示所有行）。"""
        for r in range(self.rowCount()):
            self.setRowHidden(r, False)
        self._sync_empty()


# ============================================================================
# ⑥ Pagination：分页控件
# ============================================================================
class Pagination(QWidget):
    """分页控件：上页 / 页码信息 / 下页 + 每页条数。

    仅负责「页码状态与信号」，不绑定任何数据源——由调用方在 :attr:`page_changed`
    里按 ``(page, page_size)`` 切片取数。
    """

    #: 页码变化（从 1 开始）
    page_changed = pyqtSignal(int)
    #: 每页条数变化
    page_size_changed = pyqtSignal(int)

    _PAGE_SIZES = (20, 50, 100, 200)

    def __init__(self, total: int = 0, page_size: int = 50,
                 theme: Optional[str] = None) -> None:
        """初始化分页控件。

        参数:
            total: 总条数。
            page_size: 每页条数（须在 :attr:`_PAGE_SIZES` 中之一）。
            theme: 主题名。
        """
        super().__init__()
        self._theme = THEME if theme is None else theme
        self._total = max(0, int(total))
        self._page_size = int(page_size)
        self._page = 1

        self._prev = QPushButton("上一页")
        self._prev.setObjectName("secondary")
        self._next = QPushButton("下一页")
        self._next.setObjectName("secondary")
        self._info = QLabel()
        self._info.setObjectName("sub")
        self._size_cb = QComboBox()
        self._size_cb.addItems([str(s) for s in self._PAGE_SIZES])
        if self._page_size in self._PAGE_SIZES:
            self._size_cb.setCurrentText(str(self._page_size))
        else:
            self._page_size = int(self._size_cb.currentText())

        self._prev.clicked.connect(lambda: self.set_page(self._page - 1))
        self._next.clicked.connect(lambda: self.set_page(self._page + 1))
        self._size_cb.currentTextChanged.connect(self._on_size_changed)

        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(_responsive_size(6))
        box.addWidget(self._prev)
        box.addWidget(self._info)
        box.addWidget(self._next)
        box.addStretch(1)
        box.addWidget(QLabel("每页"))
        box.addWidget(self._size_cb)
        self._apply()
        self._refresh()

    # ---- 状态 ----
    @property
    def page(self) -> int:
        """当前页码（从 1 开始）。"""
        return self._page

    @property
    def page_size(self) -> int:
        """每页条数。"""
        return self._page_size

    @property
    def page_count(self) -> int:
        """总页数（至少 1）。"""
        return max(1, -(-self._total // self._page_size))

    def set_total(self, total: int, keep_page: bool = True) -> None:
        """设置总条数并刷新显示。

        参数:
            total: 新的总条数。
            keep_page: 是否保留当前页码（False 则回到第 1 页）。
        """
        self._total = max(0, int(total))
        if not keep_page:
            self._page = 1
        self._page = min(self._page, self.page_count)
        self._refresh()

    def set_page(self, page: int) -> None:
        """切换页码（越界自动夹紧），变化后发 :attr:`page_changed`。"""
        new_page = max(1, min(int(page), self.page_count))
        if new_page == self._page:
            return
        self._page = new_page
        self._refresh()
        self.page_changed.emit(self._page)

    def slice_range(self) -> tuple[int, int]:
        """当前页对应的数据切片 ``[start, end)``。"""
        start = (self._page - 1) * self._page_size
        return start, min(start + self._page_size, self._total)

    def set_theme(self, t: str) -> None:
        """切换主题。"""
        self._theme = t
        self._apply()

    def _on_size_changed(self, text: str) -> None:
        """每页条数变化：回到第 1 页并发信号。"""
        try:
            self._page_size = int(text)
        except ValueError:
            return
        self._page = 1
        self._refresh()
        self.page_size_changed.emit(self._page_size)

    def _refresh(self) -> None:
        """刷新按钮可用态与页码文案。"""
        self._prev.setEnabled(self._page > 1)
        self._next.setEnabled(self._page < self.page_count)
        start, end = self.slice_range()
        self._info.setText(f"第 {self._page} / {self.page_count} 页　{start}-{end} / {self._total}")

    def _apply(self) -> None:
        """应用主题样式。"""
        p = PALETTE[self._theme]
        self._info.setStyleSheet(f"color:{p['sub']};font-size:{_responsive_font(11)}px;")


# ============================================================================
# UX-26：六件套补全 —— StatTile / FieldRow / SegmentedControl
# ============================================================================
class StatTile(QFrame):
    """紧凑统计方块：标签 + 数值 + 可选涨跌色，适合横排 KPI 卡片组。"""

    def __init__(self, label: str = "", value: str = "--",
                 delta: float = 0.0, theme: Optional[str] = None) -> None:
        super().__init__()
        self._theme = THEME if theme is None else theme
        self._label = label
        self._value = value
        self._delta = delta
        self._lbl = QLabel(label)
        self._val = QLabel(value)
        self._delta_lbl = QLabel("")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_responsive_size(8), _responsive_size(6), _responsive_size(8), _responsive_size(6))
        lay.setSpacing(_responsive_size(2))
        lay.addWidget(self._lbl)
        lay.addWidget(self._val)
        lay.addWidget(self._delta_lbl)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._apply()

    def set_value(self, value: str, delta: Optional[float] = None) -> None:
        """更新数值与涨跌。"""
        self._value = value
        self._val.setText(value)
        if delta is not None:
            self._delta = delta
        self._apply()

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        token = design_tokens(self._theme)
        self.setStyleSheet(
            f"QFrame{{background:{p['card']};border:1px solid {p['border']};"
            f"border-radius:{token['radius_md']}px;}}")
        self._lbl.setStyleSheet(f"color:{p['sub']};font-size:{_responsive_font(11)}px;")
        color = p['up'] if self._delta >= 0 else p['down'] if self._delta < 0 else p['text']
        self._val.setStyleSheet(f"color:{p['text']};font-size:{_responsive_font(16)}px;font-weight:bold;")
        if self._delta != 0:
            arrow = "▲" if self._delta >= 0 else "▼"
            self._delta_lbl.setText(f"{arrow} {abs(self._delta)*100:.1f}%")
            self._delta_lbl.setStyleSheet(f"color:{color};font-size:{_responsive_font(11)}px;")
        else:
            self._delta_lbl.setText("")


class FieldRow(QWidget):
    """标签-输入行：左侧固定宽度标签 + 右侧输入控件，适合表单。"""

    def __init__(self, label: str = "", widget: Optional[QWidget] = None,
                 theme: Optional[str] = None) -> None:
        super().__init__()
        self._theme = THEME if theme is None else theme
        self._lbl = QLabel(label)
        self._widget = widget
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(_responsive_size(8))
        lay.addWidget(self._lbl, 0)
        if widget is not None:
            lay.addWidget(widget, 1)
        else:
            lay.addStretch(1)
        self._apply()

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        self._lbl.setStyleSheet(f"color:{p['sub']};font-size:{_responsive_font(12)}px;")
        self._lbl.setMinimumWidth(72)


class SegmentedControl(QWidget):
    """分段控制器：水平排列的互斥选择按钮（类似 iOS Segmented Control）。"""

    def __init__(self, options: list[str] = None,
                 theme: Optional[str] = None) -> None:
        super().__init__()
        self._theme = THEME if theme is None else theme
        self._options = options or []
        self._buttons: list[QPushButton] = []
        self._selected = 0
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(_responsive_size(2))
        for opt in self._options:
            btn = QPushButton(opt)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, i=len(self._buttons): self._select(i))
            self._buttons.append(btn)
            self._layout.addWidget(btn)
        if self._buttons:
            self._buttons[0].setChecked(True)
        self._apply()

    def _select(self, idx: int) -> None:
        if idx == self._selected:
            return
        self._selected = idx
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == idx)
        self._apply()

    def current_index(self) -> int:
        return self._selected

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        for i, btn in enumerate(self._buttons):
            if i == self._selected:
                btn.setStyleSheet(
                    f"QPushButton{{background:{p['card']};color:{p['text']};"
                    f"border:1px solid {p['border']};font-weight:600;"
                    f"padding:{_responsive_size(4)}px {_responsive_size(10)}px;"
                    f"border-radius:{design_tokens()['radius_md']}px;}}")
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{p['sub']};"
                    f"border:none;font-weight:400;"
                    f"padding:{_responsive_size(4)}px {_responsive_size(10)}px;"
                    f"border-radius:{design_tokens()['radius_md']}px;}}")


# ============================================================================
# UX-20：PageShell —— 统一页面外壳（标题 + 工具条 + 内容 + 状态条）
# ============================================================================
class PageShell(QWidget):
    """统一页面外壳：封装标题 / 子标题 / 工具条 / 内容区 / 底部状态条。

    与 BasePage._build() 中手写布局的区别：
        - 消除 9 页重复的 PageHeader + ToolBar 构造代码（行数下降 ≥60%）；
        - 提供 ``content_layout`` 供子类直接填充内容；
        - 提供 ``set_status`` 更新底部状态条。
    """

    def __init__(self, title: str = "", subtitle: str = "",
                 theme: Optional[str] = None) -> None:
        super().__init__()
        self._theme = THEME if theme is None else theme
        self._title = title
        self._subtitle = subtitle
        self._status_text = ""
        self._build()
        self._apply()

    def _build(self) -> None:
        from .widgets import PageHeader, ToolBar  # 延迟导入避免循环依赖

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # 标题区
        if self._title:
            self._header = PageHeader(self._title, self._subtitle)
            root.addWidget(self._header)

        # 工具条区
        self._toolbar_lay = QHBoxLayout()
        self._toolbar_lay.setContentsMargins(0, 0, 0, 0)
        self._toolbar = ToolBar(self._toolbar_lay)
        root.addWidget(self._toolbar)

        # 内容区
        self._content_lay = QVBoxLayout()
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self._content_lay, 1)

        # 状态条
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("status-bar")
        root.addWidget(self._status_lbl)

    def content_layout(self) -> QVBoxLayout:
        return self._content_lay

    def toolbar_layout(self) -> QHBoxLayout:
        return self._toolbar_lay

    def set_status(self, text: str = "") -> None:
        self._status_text = text
        self._status_lbl.setText(text)
        self._apply()

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()
        fn = getattr(self, "_header", None)
        if fn is not None and hasattr(fn, "set_theme"):
            fn.set_theme(t)

    def _apply(self) -> None:
        p = PALETTE[self._theme]
        self._status_lbl.setStyleSheet(
            f"color:{p['sub']};font-size:{_responsive_font(11)}px;"
            f"padding:{_responsive_size(2)}px {_responsive_size(4)}px;")


# ============================================================================
# UX-59：StatusPill 行内状态点
# ============================================================================
class StatusPill(QWidget):
    """UX-59：行内状态指示点（连接态/预警态/正常态）。

    用法:
        pill = StatusPill(text="已连接", state="ok", theme="dark")
        layout.addWidget(pill)
    """

    _STATE_COLORS = {
        "ok": "up",        # 正常/连接
        "warn": "warning", # 预警
        "error": "down",   # 错误/断开
        "info": "accent",  # 信息
        "off": "sub",      # 离线/关闭
    }

    def __init__(self, text: str = "", state: str = "ok",
                 theme: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        """初始化状态点。

        参数:
            text: 状态文本。
            state: 状态键（ok/warn/error/info/off）。
            theme: 主题名。
            parent: 父控件。
        """
        super().__init__(parent)
        self._theme = THEME if theme is None else theme
        self._state = state
        self._text = text
        self._dot_color = self._resolve_color()
        self.setFixedHeight(20)
        self.setMouseTracking(True)

    def _resolve_color(self) -> str:
        """根据状态键解析 token 颜色键。"""
        key = self._STATE_COLORS.get(self._state, "sub")
        p = pal(self._theme)
        return p.get(key, p.get("sub", "#64748b"))

    def set_state(self, state: str, text: Optional[str] = None) -> None:
        """更新状态。

        参数:
            state: 状态键。
            text: 可选的文本更新。
        """
        self._state = state
        if text is not None:
            self._text = text
        self._dot_color = self._resolve_color()
        self.update()

    def set_text(self, text: str) -> None:
        """更新文本。"""
        self._text = text
        self.update()

    def set_theme(self, t: str) -> None:
        """切换主题。"""
        self._theme = t
        self._dot_color = self._resolve_color()
        self.update()

    @paint_guard
    def paintEvent(self, event) -> None:
        """绘制状态点 + 文本。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pad = 8
        dot_r = 5
        dot_x = pad + dot_r
        dot_y = self.height() // 2
        # 圆点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._dot_color))
        p.drawEllipse(int(dot_x - dot_r), int(dot_y - dot_r), dot_r * 2, dot_r * 2)
        # 文本
        if self._text:
            pal = PALETTE[self._theme]
            p.setPen(QColor(pal["text"]))
            p.setFont(QFont(_responsive_font(9)))
            p.drawText(int(dot_x + dot_r + 6), dot_y + 4, self._text)

    def sizeHint(self):
        """最小尺寸提示。"""
        from PyQt6.QtCore import QSize
        w = 20 + (len(self._text) * 7 if self._text else 0)
        return QSize(w, 20)


# ============================================================================
# 长任务进度面板（UX-63：进度条 + 阶段文案 + ETA + 可取消 + 日志滚动）
# ============================================================================

class LongTaskPanel(QWidget):
    """长任务进度面板（UX-63）。

    组件功能：
        - 进度条（0~100%）+ 阶段文案
        - ETA 预估（基于进度速率推算剩余时间）
        - 阶段指示器（圆点列，显示已完成/进行中/待执行）
        - 可取消按钮（发 ``cancel_requested`` 信号）
        - 可折叠实时日志滚动区

    用法::

        panel = LongTaskPanel(task_name="策略进化")
        panel.set_phases(["初始化", "评估", "交叉", "变异", "选择"])
        panel.set_worker(worker)          # 自动连接 progress/log/interrupted
        panel.layout().addWidget(panel)   # 加入页面布局

    信号:
        cancel_requested: 用户点击取消时发出
    """

    cancel_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None, task_name: str = "任务") -> None:
        super().__init__(parent)
        self._theme: str = THEME
        self._task_name = task_name
        self._worker = None
        self._phases: list[str] = []
        self._current_phase: int = -1
        self._elapsed_start: Optional[QTime] = None
        self._log_visible: bool = False
        self._cancel_btn: Optional[QPushButton] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # 第一行：任务名称 + ETA
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._name_lbl = QLabel(task_name)
        self._name_lbl.setFont(QFont(_responsive_font(9)))
        self._eta_lbl = QLabel("")
        self._eta_lbl.setFont(QFont(_responsive_font(9)))
        row1.addWidget(self._name_lbl)
        row1.addStretch()
        row1.addWidget(self._eta_lbl)
        root.addLayout(row1)

        # 第二行：进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%p%")
        self._progress.setFixedHeight(18)
        root.addWidget(self._progress)

        # 第三行：阶段文案
        self._stage_lbl = QLabel("准备中…")
        self._stage_lbl.setFont(QFont(_responsive_font(9)))
        root.addWidget(self._stage_lbl)

        # 第四行：阶段指示器（动态生成）
        self._phase_row = QHBoxLayout()
        self._phase_row.setSpacing(4)
        self._phase_dots: list[QLabel] = []
        root.addLayout(self._phase_row)

        # 第五行：日志滚动区（默认隐藏）
        log_toggle_btn = QPushButton("📋 日志")
        log_toggle_btn.setObjectName("ux-tmp-log-toggle")
        log_toggle_btn.setFixedHeight(22)
        log_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        log_toggle_btn.clicked.connect(self._toggle_log)
        root.addWidget(log_toggle_btn)

        self._log_area = QScrollArea()
        self._log_area.setWidgetResizable(True)
        self._log_area.setFixedHeight(120)
        self._log_area.hide()

        log_text = QTextEdit()
        log_text.setObjectName("ux-tmp-log-text")
        log_text.setReadOnly(True)
        log_text.setFont(QFont("Consolas", 8))
        log_text.setAcceptRichText(False)
        self._log_text = log_text
        self._log_area.setWidget(log_text)
        root.addWidget(self._log_area)

        # 第六行：取消按钮
        self._cancel_btn = QPushButton("取消任务")
        self._cancel_btn.setObjectName("ux-tmp-cancel")
        self._cancel_btn.setFixedHeight(24)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.hide()
        root.addWidget(self._cancel_btn)

        self._apply()

    def _apply(self) -> None:
        """应用当前主题样式。"""
        pal = PALETTE.get(self._theme, PALETTE.get("dark", {}))
        text_c = pal.get("text", "#e2e8f0")
        sub_c = pal.get("sub", "#94a3b8")
        bg_c = pal.get("bg", "#0f172a")
        panel_c = pal.get("panel", "#1e293b")
        border_c = pal.get("border", "#334155")
        accent_c = pal.get("accent", "#3b82f6")

        self._name_lbl.setStyleSheet(
            f"color:{text_c}; font-weight:bold;"
        )
        self._eta_lbl.setStyleSheet(
            f"color:{sub_c};"
        )
        self._stage_lbl.setStyleSheet(
            f"color:{sub_c};"
        )
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background:{bg_c};
                border:1px solid {border_c};
                border-radius:4px;
            }}
            QProgressBar::chunk {{
                background:{accent_c};
                border-radius:3px;
            }}
        """)
        self._log_area.setStyleSheet(f"""
            QScrollArea {{
                background:{panel_c};
                border:1px solid {border_c};
                border-radius:4px;
            }}
        """)
        self._log_text.setStyleSheet(f"""
            QTextEdit {{
                background:{panel_c};
                color:{text_c};
                border:none;
                padding:4px 6px;
            }}
        """)
        self._cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background:{bg_c};
                color:{text_c};
                border:1px solid {accent_c};
                border-radius:4px;
                padding:2px 12px;
            }}
            QPushButton:hover {{
                background:{accent_c};
                color:#fff;
            }}
        """)

    def set_worker(self, worker) -> None:
        """绑定 Worker 并自动连接信号。

        参数:
            worker: 具有 progress(int,str)/log(str)/interrupted() 信号的 Worker 对象。
        """
        if self._worker is not None:
            try:
                self._worker.progress.disconnect()
                self._worker.interrupted.disconnect()
            except (TypeError, RuntimeError):
                pass

        self._worker = worker
        self._elapsed_start = QTime.currentTime()
        self._progress.setValue(0)
        self._stage_lbl.setText("任务开始…")
        self._log_text.clear()
        self._cancel_btn.show()
        self._log_area.hide()

        if worker is not None:
            worker.progress.connect(self._on_progress)
            if hasattr(worker, "log"):
                worker.log.connect(self._on_log)
            worker.interrupted.connect(self._on_interrupted)

    def clear(self) -> None:
        """重置面板到初始状态。"""
        self._progress.setValue(0)
        self._stage_lbl.setText("准备中…")
        self._eta_lbl.setText("")
        self._log_text.clear()
        self._cancel_btn.hide()
        self._log_area.hide()
        self._elapsed_start = None
        self._current_phase = -1

    def set_phases(self, names: list[str]) -> None:
        """设置阶段名称列表并渲染圆点指示器。

        参数:
            names: 阶段名称列表（如 ["评估", "交叉", "变异"]）。
        """
        self._phases = list(names)
        self._current_phase = -1
        while self._phase_row.count():
            item = self._phase_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._phase_dots.clear()
        for i, name in enumerate(self._phases):
            lbl = QLabel(f"① {name}" if i == 0 else f"{'②③④⑤⑥⑦⑧⑨⑩'[i-1] if i < 10 else i} {name}")
            lbl.setFont(QFont(_responsive_font(8)))
            lbl.setStyleSheet(f"color:{PALETTE.get(self._theme, {}).get('sub', '#94a3b8')};")
            self._phase_dots.append(lbl)
            self._phase_row.addWidget(lbl)
            if i < len(self._phases) - 1:
                arrow = QLabel("→")
                arrow.setFont(QFont(_responsive_font(8)))
                arrow.setStyleSheet(f"color:{PALETTE.get(self._theme, {}).get('border', '#334155')};")
                self._phase_row.addWidget(arrow)
        self._phase_row.addStretch()
        self._update_phase_colors()

    def set_current_phase(self, idx: int) -> None:
        """更新当前阶段索引。

        参数:
            idx: 0-based 阶段索引。
        """
        self._current_phase = idx
        self._update_phase_colors()

    def _update_phase_colors(self) -> None:
        """刷新阶段指示器颜色（已完成=accent，当前=accent加粗，待执行=sub）。"""
        pal = PALETTE.get(self._theme, PALETTE.get("dark", {}))
        text_c = pal.get("text", "#e2e8f0")
        sub_c = pal.get("sub", "#94a3b8")
        border_c = pal.get("border", "#334155")
        accent_c = pal.get("accent", "#3b82f6")
        for i, dot in enumerate(self._phase_dots):
            if i < self._current_phase:
                dot.setStyleSheet(f"color:{accent_c}; font-weight:bold;")
            elif i == self._current_phase:
                dot.setStyleSheet(f"color:{accent_c}; font-weight:bold; background:{bg_c}; padding:0 4px; border-radius:3px;")
            else:
                dot.setStyleSheet(f"color:{sub_c};")

    def _on_progress(self, pct: int, text: str) -> None:
        """进度回调：更新进度条、阶段文案、ETA。"""
        self._progress.setValue(pct)
        if text:
            self._stage_lbl.setText(text)
        self._update_eta(pct)

    def _on_log(self, msg: str) -> None:
        """日志回调：追加日志行。"""
        ts = QTime.currentTime().toString("HH:mm:ss")
        self._log_text.append(f"[{ts}] {msg}")
        sb = self._log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_interrupted(self) -> None:
        """任务被中断回调：更新 UI 状态。"""
        self._stage_lbl.setText("任务已取消")
        self._cancel_btn.hide()
        self._log_area.show()

    def _update_eta(self, pct: int) -> None:
        """根据进度速率估算剩余时间。"""
        if self._elapsed_start is None or pct <= 0:
            return
        elapsed = QTime(self._elapsed_start).msecsTo(QTime.currentTime())
        if elapsed <= 0:
            return
        eta_ms = int(elapsed / max(pct, 1) * (100 - pct))
        mins, sec = divmod(eta_ms // 1000, 60)
        if mins >= 60:
            hrs, mins = divmod(mins, 60)
            self._eta_lbl.setText(f"预计剩余: {hrs}时{mins}分")
        elif mins > 0:
            self._eta_lbl.setText(f"预计剩余: {mins}分{sec}秒")
        else:
            self._eta_lbl.setText(f"预计剩余: {sec}秒")

    def _toggle_log(self) -> None:
        """切换日志区可见性。"""
        self._log_area.setVisible(not self._log_area.isVisible())

    def _on_cancel(self) -> None:
        """取消按钮点击：发出 cancel_requested 信号。"""
        self.cancel_requested.emit()

    def set_theme(self, t: str) -> None:
        """切换主题。"""
        self._theme = t
        self._apply()
        if hasattr(self, "_phase_dots"):
            self._update_phase_colors()


__all__ = [
    "MOTION", "paint_guard", "Card", "EmptyState", "Skeleton", "Toast",
    "toast", "DataGrid", "Pagination",
    "StatTile", "FieldRow", "SegmentedControl", "PageShell",
    "StatusPill", "LongTaskPanel",
]
