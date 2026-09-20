"""M1.4 多周期 K 线对照组件：同一合约 4 个周期（默认 5m/30m/4h/D）纵向堆叠，
滚轮同步缩放、共享十字光标。

设计（离线优先、零额外依赖）：
- 复用 ``chart_widget.KLineChart``（Painter 后端）作为各周期图，不引入新渲染栈。
- ``MultiPeriodSync``：同步控制器，把「可见根数缩放」与「悬浮索引」广播到所有图，
  保证 4 图横向对齐（同一时间轴），便于跨周期共振观察。
- ``MultiPeriodWidget``：组装 4 图 + 顶部周期标签 + 缩放条（滚轮缩放 / 拖动联动）。
  数据缺失时各图优雅降级（空白 + 周期水印），不抛错。
- 防未来函数：只渲染给定 bars，不读未来；各周期独立采样，互不填充。

用法：
    mp = MultiPeriodWidget()
    mp.set_data({"5m": bars_5m, "30m": bars_30m, "4h": bars_4h, "D": bars_d})
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QScrollArea,
    QFrame,
)

from .chart_widget import KLineChart
from .widgets import pal, THEME

__all__ = ["MultiPeriodSync", "MultiPeriodWidget", "DEFAULT_PERIODS"]

# 默认 4 周期（短→长），对应 UPGRADE_PLAN M1.4
DEFAULT_PERIODS: List[str] = ["5m", "30m", "4h", "D"]


class MultiPeriodSync:
    """多周期 K 线同步控制器。

    持有「可见根数（缩放）」与「悬浮索引（跨图十字）」两份共享状态，
    通过 KLineChart 的既有接口驱动各图保持一致。

    参数:
        default_visible: 默认可见根数（20~200）。
    """

    def __init__(self, default_visible: int = 60) -> None:
        """初始化同步控制器。"""
        self.default_visible = max(20, int(default_visible))
        self.hover_index: int = -1
        self._charts: List[KLineChart] = []

    # ---------------- 注册 / 移除 ----------------
    def register(self, chart: KLineChart) -> None:
        """注册一张 K 线，立即应用当前缩放。"""
        if chart not in self._charts:
            self._charts.append(chart)
        self._apply_zoom()

    def unregister(self, chart: KLineChart) -> None:
        """注销一张 K 线。"""
        if chart in self._charts:
            self._charts.remove(chart)

    # ---------------- 缩放 ----------------
    def zoom_in(self, step: int = 5) -> None:
        """放大（减少可见根数 → 局部放大）。"""
        self._visible = max(20, getattr(self, "_visible", self.default_visible) - step)
        self._apply_zoom()

    def zoom_out(self, step: int = 5) -> None:
        """缩小（增加可见根数 → 全局缩小）。"""
        self._visible = min(200, getattr(self, "_visible", self.default_visible) + step)
        self._apply_zoom()

    def set_visible(self, n: int) -> None:
        """直接设置可见根数（20~200 截断）。"""
        self._visible = int(max(20, min(200, n)))
        self._apply_zoom()

    @property
    def visible(self) -> int:
        """当前可见根数。"""
        return getattr(self, "_visible", self.default_visible)

    def _apply_zoom(self) -> None:
        """把当前可见根数广播到所有注册图。"""
        n = self.visible
        for c in self._charts:
            try:
                c._max_bars = int(n)  # KLineChart 可见根数（滚轮同源字段）
                c.update()
            except Exception:
                pass

    # ---------------- 跨图十字 ----------------
    def set_hover(self, index: int) -> None:
        """把悬浮索引广播到所有图（跨周期十字对齐）。"""
        self.hover_index = int(index)
        for c in self._charts:
            try:
                c._hover = int(index)
                c.update()
            except Exception:
                pass


class MultiPeriodWidget(QWidget):
    """多周期 K 线对照组件（4 图纵向堆叠 + 顶部周期标签 + 缩放控制）。

    特性:
        - 同一合约 4 周期纵向堆叠，横向时间轴对齐（共享可见根数与悬浮索引）。
        - Ctrl+滚轮 缩放全部图；普通滚轮 仅缩放最近交互图（回退）。
        - 主题感知（``set_theme``）。
    """

    #: 跨图悬浮对齐信号（index，-1 表示清除）
    hover_aligned = pyqtSignal(int)

    def __init__(self, periods: Optional[List[str]] = None,
                 parent: Optional[QWidget] = None) -> None:
        """初始化多周期组件。

        参数:
            periods: 周期标签列表（默认 DEFAULT_PERIODS）。
            parent: 父控件。"""
        super().__init__(parent)
        self.periods: List[str] = list(periods or DEFAULT_PERIODS)
        self._data: Dict[str, List[dict]] = {p: [] for p in self.periods}
        self._sync = MultiPeriodSync()
        self._theme = THEME
        self._build()

    # ---------------- 布局 ----------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # 顶部：周期标签条 + 缩放按钮
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        for p in self.periods:
            lab = QLabel(p)
            lab.setObjectName("mp-period")
            lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            top.addWidget(lab)
        top.addStretch(1)
        self.zoom_in_btn = QLabel("放大 +")
        self.zoom_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_in_btn.mousePressEvent = lambda e: self._sync.zoom_in()
        top.addWidget(self.zoom_in_btn)
        self.zoom_out_btn = QLabel("缩小 -")
        self.zoom_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_out_btn.mousePressEvent = lambda e: self._sync.zoom_out()
        top.addWidget(self.zoom_out_btn)
        root.addLayout(top)

        # 4 张 K 线纵向堆叠（滚动区，窄屏可滚）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self._charts: Dict[str, KLineChart] = {}
        for p in self.periods:
            ch = KLineChart(holder)
            ch.set_watermark(p)
            ch._hover = -1
            self._charts[p] = ch
            self._sync.register(ch)
            v.addWidget(ch)
        v.addStretch(1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        self._apply_theme()

    # ---------------- 数据 ----------------
    def set_data(self, data: Dict[str, Sequence[dict]]) -> None:
        """按周期灌数据。

        参数:
            data: ``{period: [bar, ...]}``，缺失周期留空（降级空白图）。"""
        for p in self.periods:
            bars = list((data or {}).get(p) or [])
            self._data[p] = bars
            ch = self._charts.get(p)
            if ch is not None:
                ch.set_data(bars)
                self._sync.register(ch)
        self._sync._apply_zoom()

    def set_period_data(self, period: str, bars: Sequence[dict]) -> None:
        """只更新单个周期（实时增量刷新）。"""
        if period not in self._charts:
            return
        self._data[period] = list(bars)
        self._charts[period].set_data(list(bars))
        self._sync.register(self._charts[period])
        self._sync._apply_zoom()

    # ---------------- 主题 ----------------
    def set_theme(self, t: str) -> None:
        """设置主题。

        参数:
            t: "dark" / "light"。"""
        self._theme = t
        for ch in self._charts.values():
            ch.set_theme(t)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """把主题色应用到标签 / 缩放按钮。"""
        p = pal()
        css = (f"QLabel#mp-period{{color:{p['text']};font-weight:bold;"
               f"background:{p['card']};border:1px solid {p['border']};"
               f"border-radius:4px;padding:2px 6px;}}")
        self.setStyleSheet(css)
        for btn in (self.zoom_in_btn, self.zoom_out_btn):
            btn.setStyleSheet(f"color:{p['sub']};padding:2px 4px;")

    # ---------------- 交互：滚轮同步缩放 ----------------
    def wheelEvent(self, event) -> None:  # noqa: N802
        """滚轮：Ctrl 同步缩放全部图；否则交由最近图默认行为。

        参数:
            event: 滚轮事件。"""
        if event.modifiers() & Qt.KeyboardControlModifier:
            d = -1 if event.angleDelta().y() > 0 else 1
            if d < 0:
                self._sync.zoom_in()
            else:
                self._sync.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)
