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

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMenu, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .widgets import PALETTE, THEME, _responsive_font, _responsive_size, pal

logger = logging.getLogger(__name__)


# ============================================================================
# 动效门控 + 自绘保护
# ============================================================================
def _env_flag(name: str, default: bool = False) -> bool:
    """读取布尔型环境变量（1/true/yes/on 视为真）。"""
    raw = os.environ.get(name, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


#: 全局动效开关：``QV_REDUCED_MOTION=1`` 时关闭 shimmer / 脉动等自绘动画。
#: M4-14 会把该常量推广到 StatusTile.pulse / _FadeCover / 数字滚动，此处先落地。
MOTION = not _env_flag("QV_REDUCED_MOTION")


def paint_guard(fn: Callable) -> Callable:
    """装饰 ``paintEvent``：捕获异常，避免未处理异常触发 qFatal 直接杀进程。

    PyQt 在虚函数（paintEvent 等）里抛出未捕获异常会走 qFatal，**没有 traceback**、
    faulthandler 也抓不到，表现为进程 exit 127 静默闪退。这里统一兜底并只告警一次，
    保证「画错」最多退化为「不画」，而不是「程序消失」。
    """
    warned: set[str] = set()

    @functools.wraps(fn)
    def _inner(self, event):  # noqa: ANN001 - Qt 回调签名固定
        try:
            return fn(self, event)
        except Exception as exc:  # noqa: BLE001 - 必须兜住全部异常
            key = f"{type(self).__name__}.{fn.__name__}"
            if key not in warned:
                warned.add(key)
                logger.warning("paintEvent 异常已忽略（%s）：%s", key, exc)
            return None
    return _inner


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

    _LEVEL_COLOR = {"info": "accent", "warn": "accent2", "error": "down"}
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

    # ---- 右键菜单 ----
    def _menu(self, pos: QPoint) -> None:
        """在鼠标位置弹出上下文菜单。"""
        menu = QMenu(self)
        act_row = menu.addAction("复制整行")
        act_cell = menu.addAction("复制单元格")
        menu.addSeparator()
        act_csv = menu.addAction("导出 CSV…")
        menu.addSeparator()
        col_menu = menu.addMenu("列显隐")
        for c in range(self.columnCount()):
            header = self.horizontalHeaderItem(c)
            name = header.text() if header is not None else f"列 {c + 1}"
            act = col_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(not self.isColumnHidden(c))
            act.triggered.connect(lambda _v, cc=c: self.setColumnHidden(cc, not self.isColumnHidden(cc)))
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is act_row:
            self.copy_row()
        elif chosen is act_cell:
            self.copy_cell()
        elif chosen is act_csv:
            self.export_csv()

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


__all__ = [
    "MOTION", "paint_guard", "Card", "EmptyState", "Skeleton", "Toast",
    "toast", "DataGrid", "Pagination",
]
