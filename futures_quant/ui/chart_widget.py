"""可复用图表组件（PyQt6 / QPainter，零额外依赖）。

设计目标：
    - 主题感知（深色 / 浅色），配色与 main_window 的 QSS 一致；
    - 支持多序列折线、虚线序列、阴影置信带、网格、坐标轴、图例；
    - 行情实时图与预测图复用同一组件，保证视觉一致性；
    - 纯 QPainter 绘制，无 matplotlib / pyqtgraph 依赖，离线可跑。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence


def _finite(v) -> bool:
    """数值有限性守卫：int/float 且非 NaN/±inf。"""
    return isinstance(v, (int, float)) and math.isfinite(v)

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush, QLinearGradient, QPolygonF
from PyQt6.QtWidgets import QWidget, QApplication, QMenu, QFileDialog


_DEFAULT_SERIES_COLORS = [
    "#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#a855f7", "#06b6d4",
]


def _write_csv(path: str, rows) -> bool:
    """写 CSV（utf-8-sig，Excel 打开不乱码）；失败返回 False。"""
    import csv
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerows(rows)
        return True
    except OSError as exc:
        logger.warning("导出 CSV 失败：%s", exc)
        return False


import logging
logger = logging.getLogger(__name__)


class HoverCrosshairMixin(QWidget):
    """图表交互 mixin（M4-13）：十字光标 + Tooltip + 右键菜单 + hover 广播。

    复用自 KLineChart._draw_crosshair 的交互思路，抽成与布局无关的通用件：
        - ``hover_fraction`` 信号：鼠标在绘图区的横向占比（0~1，离开为 None），
          供跨图十字同步（副图 hover → 主图十字线，M4-13②）；
        - ``set_hover_fraction``：外部联动入口（接收方；不回发信号，无反馈环）；
        - 右键菜单：复制数据 / 导出 PNG / 导出 CSV（数据由子类 ``_export_rows`` 提供）；
        - ``_draw_cross`` / ``_draw_tooltip``：通用十字线与圆角信息框绘制。

    子类职责：
        - ``__init__`` 调 ``self._hover_init()``；
        - ``paintEvent`` 末尾调 ``self._draw_hover_layer(painter, pal)``；
        - 覆盖 ``_export_rows()`` 提供导出数据；
        - 绘图区几何写入 ``self._last_rect``（QRectF，供换算 hover 占比）。
    """

    #: hover 变化（float 0~1 或 None）——跨图十字同步用
    hover_fraction = pyqtSignal(object)

    # ---------- 初始化 ----------
    def _hover_init(self) -> None:
        """启用鼠标追踪 + 右键菜单（子类 __init__ 调用一次）。"""
        self.setMouseTracking(True)
        self._hover_x = -1.0
        self._hover_y = -1.0
        self._hovering = False
        self._ext_frac: Optional[float] = None
        self._last_rect: Optional[QRectF] = None
        self.attach_context_menu()

    def attach_context_menu(self) -> None:
        """挂接右键菜单（KLineChart 等自带鼠标处理者也可单独调用）。"""
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_menu)

    # ---------- 联动 ----------
    def set_hover_fraction(self, frac) -> None:
        """外部联动入口：副图 hover → 本图十字（None=清除）。不发信号，无环。"""
        self._ext_frac = None if frac is None else max(0.0, min(1.0, float(frac)))
        self.update()

    def _effective_fraction(self) -> Optional[float]:
        """生效的 hover 占比：本地鼠标优先，其次外部联动。"""
        if getattr(self, "_hovering", False):
            r = self._last_rect
            if r is not None and r.width() > 0:
                return max(0.0, min(1.0, (self._hover_x - r.left()) / r.width()))
            return None
        return getattr(self, "_ext_frac", None)

    # ---------- 事件 ----------
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """鼠标移动：记录位置并发 hover 占比（跨图同步）。"""
        self._hover_x = event.position().x()
        self._hover_y = event.position().y()
        self._hovering = True
        frac = self._effective_fraction()
        self.hover_fraction.emit(frac)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        """鼠标离开：清除本地 hover 并广播 None。"""
        self._hovering = False
        self.hover_fraction.emit(None)
        self.update()

    # ---------- 右键菜单（M4-13③） ----------
    def _show_ctx_menu(self, pos) -> None:
        """复制数据 / 导出 PNG / 导出 CSV。"""
        menu = QMenu(self)
        menu.addAction("复制数据", self._copy_data)
        menu.addAction("导出 PNG…", self._export_png)
        menu.addAction("导出 CSV…", self._export_csv)
        menu.exec(self.mapToGlobal(pos))

    def _copy_data(self) -> None:
        """导出数据 → 剪贴板（Tab 分隔）。"""
        text = "\n".join("\t".join(str(c) for c in row)
                         for row in self._export_rows())
        QApplication.clipboard().setText(text)

    def _export_png(self) -> None:
        """整图导出 PNG。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 PNG", "chart.png", "PNG (*.png)")
        if path:
            self.grab().save(path)

    def _export_csv(self) -> None:
        """导出数据 → CSV（utf-8-sig）。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", "chart.csv", "CSV (*.csv)")
        if path and not _write_csv(path, self._export_rows()):
            pass

    def _export_rows(self):
        """导出数据行（子类覆盖；首行为表头）。"""
        return []

    # ---------- 通用绘制 ----------
    def _draw_cross(self, painter, rect: QRectF, x: float, y: float,
                    color: QColor) -> None:
        """虚线十字（限制在绘图区内）。"""
        painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
        painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))

    def _draw_tooltip(self, painter, x: float, y: float, lines, pal) -> None:
        """圆角信息框（自动避让右/上边界）。"""
        painter.setFont(QFont(_get_font(), 9))
        fm = painter.fontMetrics()
        w = max((fm.horizontalAdvance(t) for t in lines), default=60) + 16
        h = len(lines) * 15 + 8
        bx = int(x) + 12
        if bx + w > self.width() - 4:
            bx = int(x) - 12 - w
        by = int(y) - h - 10
        if by < 4:
            by = int(y) + 10
        bg = (QColor(20, 24, 33, 242) if self._theme == "dark"
              else QColor(255, 255, 255, 245))
        sh = QColor(0, 0, 0, 60)
        painter.setBrush(QBrush(sh))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bx + 2, by + 2, w, h, 6, 6)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(pal["axis"], 1))
        painter.drawRoundedRect(bx, by, w, h, 6, 6)
        for k, t in enumerate(lines):
            painter.setPen(pal["text"])
            painter.drawText(bx + 8, by + 16 + k * 15, t)

    def _draw_hover_layer(self, painter, pal) -> None:
        """paintEvent 末尾调用：按生效 hover 画十字 + Tooltip（子类提供 _hover_info）。"""
        frac = self._effective_fraction()
        r = self._last_rect
        if frac is None or r is None or r.width() <= 0:
            return
        info = self._hover_info(frac)
        if info is None:
            return
        x, y, lines = info
        self._draw_cross(painter, r, x, y, pal["axis"])
        self._draw_tooltip(painter, x, y, lines, pal)

    def _hover_info(self, frac: float):
        """子类覆盖：返回 (x, y, lines) 或 None（该位置无数据）。"""
        return None


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


def _to_color(c) -> QColor:
    """处理to颜色。
    
        参数:
            c
    
        返回:
            QColor"""
    if isinstance(c, QColor):
        return c
    return QColor(c)


class PriceChart(HoverCrosshairMixin):
    """轻量折线 / 区域图组件。

    用法：
        chart.set_data(
            series=[{"name":"收盘","color":"#3b82f6","x":[...],"y":[...],"width":1.8},
                    {"name":"预测","color":"#f59e0b","x":[...],"y":[...],"dashed":True}],
            bands=[{"lower":[...], "upper":[...], "color":"#3b82f6", "alpha":40}],
            x_ticks=[(0.0,"起点"),(1.0,"终点")],
            title="行情与预测",
        )

    M4-13：十字光标 + Tooltip + 滚轮缩放（可视点窗口，最少 10 点）+
    hover 广播（副图 → 主图十字联动）+ 右键复制/导出。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化相关对象。

            参数:
                parent: Optional[QWidget]"""
        super().__init__(parent)
        self._hover_init()
        self.setMinimumHeight(240)
        self._series: List[dict] = []
        self._bands: List[dict] = []
        self._title = ""
        self._theme = "dark"
        self._x_ticks: Optional[List[tuple]] = None
        self._view: Optional[tuple] = None   # 可视窗口 (i0, i1)；None=全部

    # ---------- 公开接口 ----------
    def set_theme(self, theme: str) -> None:
        """设置主题。
        
            参数:
                theme: str"""
        self._theme = theme
        self.update()

    def set_title(self, title: str) -> None:
        """设置title。
        
            参数:
                title: str"""
        self._title = title
        self.update()

    def set_data(self, series: Optional[Sequence[dict]] = None,
                 bands: Optional[Sequence[dict]] = None,
                 x_ticks: Optional[List[tuple]] = None,
                 title: str = "") -> None:
        """设置数据。
        
            参数:
                series: Optional[Sequence[dict]]
                bands: Optional[Sequence[dict]]
                x_ticks: Optional[List[tuple]]
                title: str"""
        self._series = [dict(s) for s in (series or [])]
        self._bands = [dict(b) for b in (bands or [])]
        self._x_ticks = x_ticks
        self._title = title
        self._view = None    # 新数据重置缩放窗口
        self.update()

    def clear(self) -> None:
        """清空相关对象。"""
        self._series = []
        self._bands = []
        self._x_ticks = None
        self._view = None
        self.update()

    # ---------- 缩放（M4-13①：滚轮可视窗口） ----------
    def _n_points(self) -> int:
        """最长序列的点数（缩放窗口的索引域）。"""
        return max((len(s.get("y", [])) for s in self._series), default=0)

    def _view_window(self) -> tuple:
        """当前可视窗口 (i0, i1)（含端点，最少 10 点）。"""
        n = self._n_points()
        if n == 0:
            return (0, 0)
        if self._view is None:
            return (0, n - 1)
        i0, i1 = self._view
        i0 = max(0, min(int(i0), n - 2))
        i1 = max(i0 + 9, min(int(i1), n - 1))
        return (i0, i1)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """滚轮缩放：以光标为锚点调整可视窗口（上滚放大 / 下滚缩小）。"""
        n = self._n_points()
        if n < 12:
            return
        i0, i1 = self._view_window()
        r = self._last_rect
        anchor = 0.5
        if r is not None and r.width() > 0 and self._hovering:
            anchor = max(0.0, min(1.0, (self._hover_x - r.left()) / r.width()))
        cur = i0 + anchor * (i1 - i0)
        factor = 0.85 if event.angleDelta().y() > 0 else 1.18
        w = max(9.0, min(float(n - 1), (i1 - i0) * factor))
        i0n = cur - anchor * w
        if i0n < 0:
            i0n, _ = 0.0, 0.0
        if i0n + w > n - 1:
            i0n = (n - 1) - w
        self._view = (int(i0n), int(i0n + w))
        self.update()

    # ---------- 内部 ----------
    def _palette(self) -> dict:
        """处理palette。
        
            返回:
                dict"""
        if self._theme == "dark":
            return dict(grid=QColor(42, 46, 58), text=QColor(139, 147, 167),
                        axis=QColor(58, 63, 78))
        return dict(grid=QColor(229, 231, 235), text=QColor(107, 114, 128),
                    axis=QColor(209, 213, 219))

    def _y_range(self, i0: int = 0, i1: Optional[int] = None):
        """处理y区间（仅在可视窗口 [i0, i1] 内取值，滚轮缩放后自适应）。"""
        if i1 is None:
            i1 = 10 ** 9
        vals = []
        for s in self._series:
            y = s.get("y", [])
            for v in y[i0:i1 + 1]:
                if isinstance(v, (int, float)) and v == v:
                    vals.append(v)
        for b in self._bands:
            for key in ("lower", "upper"):
                seq = b.get(key, [])
                for v in seq[i0:i1 + 1]:
                    if isinstance(v, (int, float)) and v == v:
                        vals.append(v)
        if not vals:
            return 0.0, 1.0
        lo, hi = min(vals), max(vals)
        if hi == lo:
            pad = abs(hi) * 0.01 or 1.0
            return lo - pad, hi + pad
        pad = (hi - lo) * 0.08
        return lo - pad, hi + pad

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制事件。
        
            参数:
                event"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self._palette()
        W, H = self.width(), self.height()
        title_h = 24 if self._title else 4
        x0, y0 = 12, 10 + title_h
        x1, y1 = W - 14, H - 26
        if x1 <= x0 or y1 <= y0:
            return
        # M4-13：绘图区几何（供 hover 占比换算 / 缩放锚点）
        self._last_rect = QRectF(x0, y0, x1 - x0, y1 - y0)

        # 标题（增大字体，提升清晰度）
        if self._title:
            painter.setPen(pal["text"])
            painter.setFont(QFont(_get_font(), 12, QFont.Weight.Bold))
            painter.drawText(x0, 20 + title_h, self._title)

        # 无数据
        if not self._series:
            painter.setPen(pal["text"])
            painter.setFont(QFont(_get_font(), 11))
            painter.drawText(x0, (y0 + y1) // 2, "暂无数据")
            return

        # M4-13①：可视窗口映射（滚轮缩放）
        i0, i1 = self._view_window()
        view_n = i1 - i0 + 1
        ymin, ymax = self._y_range(i0, i1)
        span = ymax - ymin

        def mx(i: int) -> float:
            """处理mx。

                参数:
                    i: int

                返回:
                    float"""
            return (x0 + (i - i0) / (view_n - 1) * (x1 - x0)
                    if view_n > 1 else (x0 + x1) / 2)

        def my(v: float) -> float:
            """处理my。
            
                参数:
                    v: float
            
                返回:
                    float"""
            return y1 - (v - ymin) / span * (y1 - y0)

        # 横向网格 + Y 轴标签（增大字体）
        painter.setPen(QPen(pal["grid"], 1))
        painter.setFont(QFont(_get_font(), 10))
        for k in range(5):
            yy = y0 + k * (y1 - y0) / 4
            painter.drawLine(int(x0), int(yy), int(x1), int(yy))
            val = ymax - k * span / 4
            if isinstance(val, float) and val != val:
                continue
            painter.setPen(pal["text"])
            painter.drawText(4, int(yy) + 4, f"{val:,.1f}")
            painter.setPen(QPen(pal["grid"], 1))

        # X 轴刻度（调用方提供，增大字体）
        if self._x_ticks:
            painter.setPen(pal["text"])
            painter.setFont(QFont(_get_font(), 10))
            for frac, label in self._x_ticks:
                xx = x0 + frac * (x1 - x0)
                painter.drawLine(int(xx), int(y1), int(xx), int(y1) + 4)
                painter.drawText(int(xx) - 20, int(y1) + 18, str(label))

        # 置信带（在折线之下；仅绘可视窗口）
        for b in self._bands:
            lower, upper = b.get("lower", []), b.get("upper", [])
            if len(lower) < 2 or len(upper) < 2:
                continue
            color = _to_color(b.get("color", "#3b82f6"))
            alpha = int(b.get("alpha", 40))
            u_lo = max(i0, 0)
            u_hi = min(i1, len(upper) - 1)
            l_hi = min(i1, len(lower) - 1)
            if u_hi - u_lo < 1:
                continue
            poly = [QPointF(mx(i), my(upper[i])) for i in range(u_lo, u_hi + 1)]
            for i in range(l_hi, u_lo - 1, -1):
                poly.append(QPointF(mx(i), my(lower[i])))
            c = QColor(color)
            c.setAlpha(alpha)
            painter.setBrush(QBrush(c))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(poly)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # 折线序列（仅绘可视窗口）
        for idx, s in enumerate(self._series):
            y = s.get("y", [])
            if len(y) < 1:
                continue
            color = _to_color(s.get("color", _DEFAULT_SERIES_COLORS[idx % len(_DEFAULT_SERIES_COLORS)]))
            pen = QPen(color, float(s.get("width", 1.8)))
            if s.get("dashed"):
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            w_lo = max(i0, 0)
            w_hi = min(i1, len(y) - 1)
            pts = [QPointF(mx(i), my(y[i])) for i in range(w_lo, w_hi + 1)
                   if _finite(y[i])]
            for i in range(1, len(pts)):
                painter.drawLine(pts[i - 1], pts[i])
            # 端点小圆点（NaN 中心会触发 QPainterPath::arcTo NaN 警告，需守卫）
            if pts and _finite(pts[-1].x()) and _finite(pts[-1].y()):
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(pts[-1], 2.5, 2.5)
                painter.setPen(pen)

        # 图例（左上，增大字体和线条）
        if self._series:
            painter.setFont(QFont(_get_font(), 10))
            fm = painter.fontMetrics()
            lx = x0 + 8
            ly = y0 + 4
            for s in self._series:
                name = s.get("name", "")
                if not name:
                    continue
                color = _to_color(s.get("color", "#888"))
                painter.setPen(QPen(color, 2.5))
                painter.drawLine(int(lx), int(ly + 5), int(lx + 14), int(ly + 5))
                painter.setPen(pal["text"])
                painter.drawText(int(lx + 18), int(ly + 10), name)
                lx += 22 + fm.horizontalAdvance(name) + 14

        # M4-13：十字光标 + Tooltip（本地 hover 或外部联动）
        self._draw_hover_layer(painter, pal)

    # ---------- M4-13：hover 信息 / 导出 ----------
    def _hover_info(self, frac: float):
        """光标占比 → 最近样本点的十字位置与数值 Tooltip。"""
        if not self._series:
            return None
        i0, i1 = self._view_window()
        view_n = i1 - i0 + 1
        ni = max(i0, min(i1, i0 + int(round(frac * (view_n - 1)))))
        ymin, ymax = self._y_range(i0, i1)
        r = self._last_rect
        if r is None or r.height() <= 0:
            return None
        span = (ymax - ymin) or 1.0
        lines = [f"样本 {ni - i0 + 1}/{view_n}"]
        cy = None
        for s in self._series:
            y = s.get("y", [])
            if ni < len(y) and _finite(y[ni]):
                lines.append(f"{s.get('name', '')}: {y[ni]:,.2f}")
                if cy is None:
                    cy = r.bottom() - (y[ni] - ymin) / span * r.height()
        if cy is None:
            return None
        x = r.left() + (ni - i0) / (view_n - 1) * r.width() if view_n > 1 \
            else r.center().x()
        return float(x), float(cy), lines

    def _export_rows(self):
        """导出：样本序号 + 各序列数值（含非可视窗口全量）。"""
        n = self._n_points()
        names = [s.get("name", f"序列{k + 1}") for k, s in enumerate(self._series)]
        rows = [["样本"] + names]
        for i in range(n):
            rows.append([i + 1] + [s.get("y", [])[i]
                                   if i < len(s.get("y", [])) else ""
                                   for s in self._series])
        return rows


# ============================================================================
# 可靠性校准图（Reliability Diagram）：预测概率 vs 实际命中率
# ============================================================================

class ReliabilityChart(HoverCrosshairMixin):
    """可靠性校准图（Reliability Diagram）：预测概率 vs 实际命中率。

    把模型「自信度」摊开给用户看——理想情况下所有经验点应落在
    对角虚线（完美校准）上：模型说涨 70%，历史上就该 70% 真涨。
    点落在对角线下方 = 模型过度自信（需压缩）；上方 = 过度保守（需抬升）。
    点半径随样本量增大，颜色按偏离方向着色，便于一眼识别系统性偏差。
    另用红色高亮点标出「本次预测」在校准图上的落点（预测值→校准值）。

    M4-13：十字光标 + Tooltip（就近校准点读数）+ 右键复制/导出；
    不做滚轮缩放——横纵均为固定 [0,1] 概率域，缩放无意义（记录假设）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化相关对象。

            参数:
                parent: Optional[QWidget]"""
        super().__init__(parent)
        self._hover_init()
        self.setMinimumHeight(220)
        self._bins: list = []          # [(center, smoothed, n, lo, hi), ...]
        self._status = ""
        self._coverage = 0
        self._mark: Optional[tuple] = None   # (p_up, conf[, lo, hi]) 当前预测落点
        self._theme = "dark"

    def set_theme(self, theme: str) -> None:
        """设置主题。
        
            参数:
                theme: str"""
        self._theme = theme
        self.update()

    def set_data(self, bins=None, status: str = "", coverage: int = 0,
                 mark=None) -> None:
        # 归一化：兼容旧 3 元组 (center, smoothed, n) 与新 5 元组 (+lo, +hi)
        """设置数据。
        
            参数:
                bins
                status: str
                coverage: int
                mark"""
        norm = []
        for b in (bins or []):
            t = tuple(b)
            if len(t) >= 5:
                norm.append((t[0], t[1], t[2], t[3], t[4]))
            elif len(t) == 3:
                norm.append((t[0], t[1], t[2], None, None))
        self._bins = norm
        self._status = status
        self._coverage = coverage
        self._mark = mark
        self.update()

    def _palette(self) -> dict:
        """处理palette。
        
            返回:
                dict"""
        if self._theme == "dark":
            return dict(grid=QColor(42, 46, 58), text=QColor(139, 147, 167),
                        axis=QColor(58, 63, 78), bg=QColor(15, 17, 22))
        return dict(grid=QColor(229, 231, 235), text=QColor(107, 114, 128),
                    axis=QColor(203, 213, 225), bg=QColor(255, 255, 255))

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制事件。
        
            参数:
                event"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self._palette()
        W, H = self.width(), self.height()
        padL, padR, padT, padB = 42, 16, 16, 30
        plotW, plotH = W - padL - padR, H - padT - padB
        if plotW <= 10 or plotH <= 10:
            self._last_rect = None
            return
        # M4-13：绘图区几何（供 hover 占比换算）
        self._last_rect = QRectF(padL, padT, plotW, plotH)

        painter.fillRect(self.rect(), pal["bg"])

        def mx(v):
            """处理mx。
            
                参数:
                    v"""
            return padL + float(v) * plotW

        def my(v):
            """处理my。
            
                参数:
                    v"""
            return padT + (1.0 - float(v)) * plotH

        # 网格 + 刻度
        painter.setFont(QFont(_get_font(), 9))
        for k in range(5):
            frac = k / 4
            yy = my(frac)
            painter.setPen(QPen(pal["grid"], 1))
            painter.drawLine(int(padL), int(yy), int(padL + plotW), int(yy))
            painter.setPen(pal["text"])
            painter.drawText(6, int(yy) + 3, f"{frac*100:.0f}")
            xx = mx(frac)
            painter.setPen(QPen(pal["grid"], 1))
            painter.drawLine(int(xx), int(padT), int(xx), int(padT + plotH))
            painter.setPen(pal["text"])
            painter.drawText(int(xx) - 10, int(padT + plotH) + 16,
                             f"{frac*100:.0f}")

        # 轴标题
        painter.setPen(pal["text"])
        painter.setFont(QFont(_FONT, 10, QFont.Weight.Bold))
        painter.drawText(int(padL + plotW / 2 - 48), H - 2, "预测上涨概率 (%)")
        painter.save()
        painter.translate(12, int(padT + plotH / 2 + 30))
        painter.rotate(-90)
        painter.drawText(-50, 0, "实际命中率 (%)")
        painter.restore()

        # 完美校准对角线
        painter.setPen(QPen(pal["axis"], 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(int(mx(0)), int(my(0)), int(mx(1)), int(my(1)))

        # 区间置信带（Wilson 95%）：经验命中率上下界填充半透明带 + 误差须。
        # 用对角参考线之后的「数据层」绘制，确保压在网格之上、经验线之下。
        band_pts = [(c, s, n, lo, hi) for (c, s, n, lo, hi) in self._bins
                    if lo is not None and hi is not None and n > 0
                    and 0.0 <= s <= 1.0 and 0.0 <= c <= 1.0]
        if len(band_pts) >= 2:
            top = [QPointF(mx(c), my(hi)) for (c, s, n, lo, hi) in band_pts]
            bot = [QPointF(mx(c), my(lo)) for (c, s, n, lo, hi) in band_pts][::-1]
            band_col = QColor("#3b82f6")
            band_col.setAlpha(40)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(band_col))
            painter.drawPolygon(QPolygonF(top + bot))
            painter.setPen(QPen(QColor(59, 130, 246, 110), 1, Qt.PenStyle.DashLine))
            for seg in (top, bot):
                for j in range(1, len(seg)):
                    painter.drawLine(seg[j - 1], seg[j])
        # 误差须：每个经验点的 Wilson 区间竖向短线，给出单点可信度读数
        for (c, s, n, lo, hi) in band_pts:
            painter.setPen(QPen(QColor(148, 163, 184, 170), 1))
            painter.drawLine(int(mx(c)), int(my(hi)), int(mx(c)), int(my(lo)))

        valid = [(c, s, n) for (c, s, n, *_ ) in self._bins
                 if n > 0 and 0.0 <= s <= 1.0 and 0.0 <= c <= 1.0]

        if not valid:
            painter.setPen(pal["text"])
            painter.setFont(QFont(_get_font(), 11))
            msg = ("样本不足，暂无可绘制的校准点"
                   if not self._mark else "样本不足，仅显示本次预测落点")
            painter.drawText(int(padL + 8), int(padT + plotH / 2), msg)

        # 经验连线
        if len(valid) >= 2:
            painter.setPen(QPen(QColor("#3b82f6"), 2))
            pts = [QPointF(mx(c), my(s)) for (c, s, n) in valid]
            for j in range(1, len(pts)):
                painter.drawLine(pts[j - 1], pts[j])
        # 经验点（半径随样本量，颜色按偏离方向）
        for (c, s, n) in valid:
            r = max(3.0, min(9.0, 3.0 + math.sqrt(n)))
            over = s < c          # 实际 < 预测 = 过度自信
            col = QColor("#f59e0b") if over else QColor("#22c55e")
            painter.setBrush(QBrush(col))
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1))
            painter.drawEllipse(QPointF(mx(c), my(s)), r, r)
            if n >= 3:
                painter.setPen(pal["text"])
                painter.setFont(QFont(_get_font(), 8))
                painter.drawText(int(mx(c)) + int(r) + 2, int(my(s)) + 3,
                                 f"n={n}")

        # 本次预测落点（红点 + 水平校准区间误差棒 + 标注）
        if self._mark:
            try:
                pu, conf = float(self._mark[0]), float(self._mark[1])
            except Exception:
                pu, conf = 0.5, 0.5
            pxx, pyy = mx(pu), my(conf)
            # 校准区间水平误差棒（本次预测的校准不确定性）
            blo = bhi = None
            if len(self._mark) >= 4 and self._mark[2] is not None and self._mark[3] is not None:
                try:
                    blo, bhi = float(self._mark[2]), float(self._mark[3])
                    painter.setPen(QPen(QColor("#ef4444"), 1.5, Qt.PenStyle.DashLine))
                    painter.drawLine(int(mx(blo)), int(pyy), int(mx(bhi)), int(pyy))
                except Exception:
                    blo = bhi = None
            painter.setPen(QPen(QColor("#ef4444"), 2))
            painter.setBrush(QBrush(QColor("#ef4444")))
            painter.drawEllipse(QPointF(pxx, pyy), 5.5, 5.5)
            painter.setPen(QColor("#ef4444"))
            painter.setFont(QFont(_get_font(), 9, QFont.Weight.Bold))
            if blo is not None and bhi is not None:
                label = (f"本次: 预测{pu*100:.0f}% → 校准{conf*100:.0f}% "
                         f"[{blo*100:.0f}–{bhi*100:.0f}]")
            else:
                label = f"本次: 预测{pu*100:.0f}% → 校准{conf*100:.0f}%"
            lx = int(pxx - painter.fontMetrics().horizontalAdvance(label) - 10)
            if lx < padL:
                lx = int(pxx + 10)
            painter.drawText(lx, int(pyy - 8), label)

        # M4-13：十字光标 + Tooltip（本地 hover 或外部联动）
        self._draw_hover_layer(painter, pal)

    # ---------- M4-13：hover 信息 / 导出 ----------
    def _hover_info(self, frac: float):
        """光标占比 → 就近校准点的十字位置与读数 Tooltip。"""
        r = self._last_rect
        if r is None or r.width() <= 0:
            return None
        pv = max(0.0, min(1.0, frac))
        best, bd = None, 1e9
        for (c, s, n, lo, hi) in self._bins:
            if not (n > 0 and 0.0 <= s <= 1.0 and 0.0 <= c <= 1.0):
                continue
            d = abs(c - pv)
            if d < bd:
                bd, best = d, (c, s, n, lo, hi)
        if best is None:
            return None
        c, s, n, lo, hi = best
        x = r.left() + c * r.width()
        y = r.top() + (1.0 - s) * r.height()
        lines = [f"预测 {c * 100:.0f}%",
                 f"命中 {s * 100:.0f}%",
                 f"样本 n={n}"]
        if lo is not None and hi is not None:
            lines.append(f"Wilson [{lo * 100:.0f}–{hi * 100:.0f}]")
        return float(x), float(y), lines

    def _export_rows(self):
        """导出：预测概率 / 经验命中 / 样本 / Wilson 上下界。"""
        rows = [["预测概率", "经验命中", "样本", "下界", "上界"]]
        for (c, s, n, lo, hi) in self._bins:
            rows.append([c, s, n, lo if lo is not None else "",
                         hi if hi is not None else ""])
        return rows


# ============================================================================
# K 线（蜡烛）图组件：蜡烛 + 成交量 + 均线 + 十字光标 + 悬浮提示
# ============================================================================


def draw_trade_marks(painter, pal, marks: list, px_fn, py_fn, total_n: int,
                     padL: int, priceTop: int, plotW: int) -> None:
    """在 K 线图上绘制交易参考点标注（增强版）。

    每个 mark 包含: y_enter, label_enter, color_enter, price_display。
    渲染策略（提升可读性的关键）：
    - 先画贯穿全宽的半透明水平虚线（价位参考线），一眼看清所处价格区间；
    - 在左边缘画菱形锚点 + 圆角标签（标签含「名称 价格」），避免所有标注
      挤在最后一根 K 线处互相重叠；
    - 按 y 排序绘制，相邻标签过近时自动下移，杜绝文字堆叠。
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 按语义分组，保证视觉层次：止损(底) → 卖出 → 买入(顶) → 其它
    enter_marks = [m for m in marks if m.get("color_enter", "") in ("#22c55e", "#10b981")]
    exit_marks = [m for m in marks if m.get("color_enter", "") == "#ef4444"]
    stop_marks = [m for m in marks if m.get("color_enter", "") == "#f59e0b"]
    other_marks = [m for m in marks if m not in enter_marks + exit_marks + stop_marks]

    # 统一收集后按 y 升序绘制（价格由低到高），便于防重叠
    flat = []
    for grp in (stop_marks, exit_marks, enter_marks, other_marks):
        flat.extend(grp)
    flat.sort(key=lambda m: py_fn(m.get("y_enter", 0)) if _finite(py_fn(m.get("y_enter", 0))) else 1e18)

    last_label_y = None
    for m in flat:
        y_entry = py_fn(m.get("y_enter", 0))
        if not _finite(y_entry):
            continue
        color = QColor(m.get("color_enter", "#10b981"))
        label = m.get("label_enter", "")
        price_val = m.get("price_display", "")

        # 1) 贯穿全宽的水平参考虚线（半透明）
        lc = QColor(color)
        lc.setAlpha(55)
        painter.setPen(QPen(lc, 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(padL), int(y_entry), int(padL + plotW), int(y_entry))

        # 2) 左边缘菱形锚点（贴在参考线上）
        ax = int(padL + 10)
        pc = QColor(color)
        pc.setAlpha(235)
        s = 6
        painter.setBrush(QBrush(pc))
        painter.setPen(QPen(color, 1.5))
        painter.drawPolygon([
            QPointF(ax, y_entry - s), QPointF(ax + s * 0.6, y_entry),
            QPointF(ax, y_entry + s), QPointF(ax - s * 0.6, y_entry),
        ])

        # 3) 标签（菱形右侧）；与上一个标签过近则下移，避免重叠
        txt = f"{label} {price_val}"
        painter.setFont(QFont(_FONT, 9, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(txt)
        ty = int(y_entry)
        if last_label_y is not None and abs(ty - last_label_y) < 16:
            ty = last_label_y + 16
        last_label_y = ty

        bx = ax + s + 4
        # 标签背景（圆角，实色块保证对比度）
        bg = QColor(color)
        bg.setAlpha(205)
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bx - 2, ty - 9, tw + 6, 16, 3, 3)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(bx, ty + 4, txt)

    painter.restore()


class KLineChart(HoverCrosshairMixin):
    """期货 K 线图组件（纯 QPainter，零额外依赖，主题感知）。

    特性：
        - 蜡烛实体 + 影线，红涨绿跌（中国期货惯例，可切换）；
        - 蜡烛体宽随可视根数自适应（1~16px），大数据量自动进入「密集模式」
          以单根影线呈现，保证流畅渲染；
        - 底部成交量副图，颜色与涨跌一致；
        - 多均线叠加（MA5/MA10/MA20…），左上角图例 + 当前值；
        - 价格 / 成交量 / 时间三轴标注，右侧价格刻度（按量级自适应小数位）；
        - 最新价虚线 + 右侧圆角价签；
        - 鼠标悬浮十字光标 + 圆角信息框（开高低收 / 涨跌 / 量 / 均线），
          并在右轴与时间轴显示跟随光标的价签与日期；
        - 滚轮缩放可见根数（20~全部），提升信息密度与可读性。

    用法：
        chart = KLineChart()
        chart.set_data(bars, ma={"MA10": [...], "MA20": [...]})
        chart.set_theme("dark")
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化相关对象。
        
            参数:
                parent: Optional[QWidget]"""
        super().__init__(parent)
        self.setMinimumHeight(450)
        # M4-13：hover 广播（副图/主图十字联动）+ 右键复制/导出
        self.setMouseTracking(True)
        self.attach_context_menu()
        self._bars: List[dict] = []
        self._ma: dict = {}
        self._theme = "dark"
        self._show_volume = True
        self._hover = -1          # 悬浮命中的 bar 全局索引（-1 表示无）
        self._max_bars = 120      # 可见根数（滚轮缩放）
        self._up_color = "#ef4444"
        self._down_color = "#22c55e"
        self._forecast = None     # {"y":[...], "upper":[...], "lower":[...]}
        self._levels: list = []   # 压力/支撑线 [{price, kind, label}]
        self._trade_marks: list = []  # 交易参考点 [{x, y, type, label, price, anchor_y, color}]
        self._watermark = ""      # 背景水印文字（如合约代码 / 周期）
        self._vol_ma: list = []   # 成交量 MA5（与 _bars 等长，前 N 为 None）

    # ---------- 公开接口 ----------
    def set_theme(self, theme: str) -> None:
        """设置主题。
        
            参数:
                theme: str"""
        self._theme = theme
        self.update()

    def set_data(self, bars: Sequence[dict],
                 ma: Optional[dict] = None) -> None:
        """设置数据。
        
            参数:
                bars: Sequence[dict]
                ma: Optional[dict]"""
        self._bars = [dict(b) for b in bars]
        self._ma = {k: list(v) for k, v in (ma or {}).items()}
        self._max_bars = min(max(self._max_bars, 20), max(20, len(self._bars)))
        # 内部计算成交量 MA5（副图叠加，无需调用方提供）
        vols = [float(b.get("volume", 0) or 0) for b in self._bars]
        self._vol_ma = self._rolling_mean(vols, 5)
        self.update()

    def set_watermark(self, text: str = "") -> None:
        """设置绘图区背景水印文字（如合约代码 / 周期）。"""
        self._watermark = text or ""
        self.update()

    @staticmethod
    def _rolling_mean(seq: Sequence[float], n: int) -> list:
        """处理rollingmean。
        
            参数:
                seq: Sequence[float]
                n: int
        
            返回:
                list"""
        out = []
        for i in range(len(seq)):
            if i < n - 1:
                out.append(None)
                continue
            out.append(sum(seq[i - n + 1:i + 1]) / n)
        return out

    def set_ma(self, ma: dict) -> None:
        """设置均线。
        
            参数:
                ma: dict"""
        self._ma = {k: list(v) for k, v in (ma or {}).items()}
        self.update()

    def set_show_volume(self, show: bool) -> None:
        """设置show成交量。
        
            参数:
                show: bool"""
        self._show_volume = show
        self.update()

    def set_forecast(self, y: Optional[Sequence[float]] = None,
                     upper: Optional[Sequence[float]] = None,
                     lower: Optional[Sequence[float]] = None) -> None:
        """叠加 KP预测曲线（含 ±1σ 置信带）。y[0] 应与最后一根收盘价一致。"""
        if y is None:
            self._forecast = None
        else:
            has_upper = upper is not None and len(upper) > 0
            has_lower = lower is not None and len(lower) > 0
            self._forecast = {
                "y": list(y),
                "upper": list(upper) if has_upper else None,
                "lower": list(lower) if has_lower else None,
            }
        self.update()

    def set_levels(self, levels: Optional[Sequence[dict]] = None) -> None:
        """叠加关键价位（压力/支撑）水平虚线。"""
        self._levels = [dict(l) for l in (levels or [])]
        self.update()

    def set_trade_marks(self, marks: Optional[Sequence[dict]] = None) -> None:
        """叠加交易参考点：买入区间(绿)、卖出目标(红)。
        
        参数 marks: [{x_idx, y_enter, label_enter, color_enter, anchor_x, anchor_y}, ...]
        x_idx = 相对可见K线起始位置偏移量（整数），负数表示从尾部倒数。
        """
        self._trade_marks = [dict(m) for m in (marks or [])]
        self.update()

    def clear(self) -> None:
        """清空相关对象。"""
        self._bars = []
        self._ma = {}
        self._hover = -1
        self.update()

    # ---------- 调色板 ----------
    def _palette(self) -> dict:
        """处理palette。
        
            返回:
                dict"""
        from .widgets import pal
        p = pal()
        if self._theme == "dark":
            return dict(
                grid=QColor(p["grid"]), text=QColor(p["text"]),
                axis=QColor(54, 60, 74), cross=QColor(148, 160, 184),
                bg=QColor(p["bg"]), band=QColor(p["accent"]),
                plot=QColor(12, 14, 19), plot_top=QColor(20, 23, 30),
                plot_bot=QColor(9, 11, 15), sep=QColor(58, 64, 80),
                volma=QColor(p["accent2"]), hi=QColor(255, 255, 255, 14))
        return dict(
            grid=QColor(p["grid"]), text=QColor(p["text"]),
            axis=QColor(203, 213, 225), cross=QColor(120, 130, 150),
            bg=QColor(p["bg"]), band=QColor(p["accent"]),
            plot=QColor(p["card"]), plot_top=QColor(252, 253, 255),
            plot_bot=QColor(240, 244, 248), sep=QColor(203, 213, 225),
            volma=QColor(p["accent2"]), hi=QColor(15, 23, 42, 16))

    _MA_COLORS = ["#f59e0b", "#3b82f6", "#a855f7", "#06b6d4", "#eab308"]

    @staticmethod
    def _fmt_price(v: float) -> str:
        """处理fmt价格。
        
            参数:
                v: float
        
            返回:
                str"""
        if v is None:
            return ""
        a = abs(v)
        dec = 1 if a >= 1000 else 2 if a >= 100 else 3 if a >= 1 else 4
        return f"{v:,.{dec}f}"

    @staticmethod
    def _fmt_time(s: str) -> str:
        """处理fmt时间。
        
            参数:
                s: str
        
            返回:
                str"""
        s = str(s).strip()
        # 日线通常带 00:00:00，不显示无意义的时间
        if len(s) >= 19 and s[11:19] == "00:00:00":
            return s[:10]
        if "T" in s or (len(s) > 10 and ":" in s):
            return s[5:10] + " " + s[11:16]   # MM-DD HH:mm
        return s[:10]                          # YYYY-MM-DD

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制事件。
        
            参数:
                event"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self._palette()
        W, H = self.width(), self.height()
        padL, padR, padT, padB = 8, 64, 26, 24
        plotW = W - padL - padR
        plotH = H - padT - padB
        if plotW <= 10 or plotH <= 10:
            return

        bars = self._bars
        total = len(bars)
        if total == 0:
            painter.setPen(pal["text"]); painter.setFont(QFont(_get_font(), 11))
            painter.drawText(padL, padT + plotH // 2, "暂无数据")
            return

        view_n = min(self._max_bars, total)
        start = total - view_n
        fc = self._forecast
        horizon = (len(fc["y"]) - 1) if fc and len(fc["y"]) > 1 else 0
        total_n = view_n + horizon
        pitch = plotW / total_n
        body_w = max(1.0, min(pitch * 0.68, 16.0))
        dense = pitch < 3.0   # 大数据量：影线模式，保证流畅

        # 价格区间（可见蜡烛 + 可见均线）
        hi = -1e18
        lo = 1e18
        for gi in range(start, total):
            b = bars[gi]
            if b["high"] > hi:
                hi = b["high"]
            if b["low"] < lo:
                lo = b["low"]
        for series in self._ma.values():
            for gi in range(start, total):
                v = series[gi] if gi < len(series) else None
                if v is None:
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if fv == fv:
                    hi = max(hi, fv)
                    lo = min(lo, fv)
        if hi <= lo:
            hi = lo + 1
        padv = (hi - lo) * 0.06
        pmin, pmax = lo - padv, hi + padv

        volH = int(plotH * 0.22) if self._show_volume else 0
        priceTop = padT
        priceBot = padT + plotH - volH - (8 if volH else 0)
        priceH = max(10, priceBot - priceTop)
        volTop = priceBot + 8
        volBot = padT + plotH
        vmax = 1.0
        for gi in range(start, total):
            vmax = max(vmax, float(bars[gi]["volume"]) if bars[gi]["volume"] == bars[gi]["volume"] else 0.0)
        vmax = vmax * 1.1 or 1.0

        def px(gi: int) -> float:
            """处理px。
            
                参数:
                    gi: int
            
                返回:
                    float"""
            return padL + (gi - start + 0.5) / total_n * plotW

        def py(v: float) -> float:
            """处理py。
            
                参数:
                    v: float
            
                返回:
                    float"""
            return priceBot - (v - pmin) / (pmax - pmin) * priceH

        def vy(v: float) -> float:
            """处理vy。
            
                参数:
                    v: float
            
                返回:
                    float"""
            return volBot - (v / vmax) * (volBot - volTop)

        # ---- 绘图区底色（细腻竖向渐变）+ 细边框 ----
        grad = QLinearGradient(0, priceTop, 0, volBot)
        grad.setColorAt(0.0, pal["plot_top"])
        grad.setColorAt(1.0, pal["plot_bot"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawRect(padL, priceTop, plotW, volBot - priceTop)
        painter.setPen(QPen(pal["grid"], 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(padL, priceTop, plotW, volBot - priceTop)

        # ---- 背景水印（极淡，置于图层之下） ----
        if self._watermark:
            painter.save()
            wcol = QColor(255, 255, 255, 16) if self._theme == "dark" else QColor(15, 23, 42, 12)
            painter.setPen(wcol)
            painter.setFont(QFont(_get_font(), 30, QFont.Weight.Bold))
            fmw = painter.fontMetrics()
            wx = int(padL + plotW) - fmw.horizontalAdvance(self._watermark) - 14
            wy = int(volBot) - 14
            painter.drawText(wx, wy, self._watermark)
            painter.restore()

        # ---- 横向网格 + 右侧价格刻度（自适应小数位） ----
        painter.setFont(QFont(_get_font(), 9))
        for k in range(5):
            yy = priceTop + k * priceH / 4
            painter.setPen(QPen(pal["grid"], 1))
            painter.drawLine(int(padL), int(yy), int(padL + plotW), int(yy))
            val = pmax - k * (pmax - pmin) / 4
            painter.setPen(pal["text"])
            painter.drawText(int(padL + plotW + 5), int(yy) + 3, self._fmt_price(val))

        # ---- 纵向时间网格：以「月」为界（专业图表观感） ----
        seps = []  # (x, 'YYYY-MM')
        prev_m = None
        for gi in range(start, total):
            m = str(bars[gi].get("datetime", ""))[:7]
            if m and m != prev_m:
                if prev_m is not None:
                    seps.append((px(gi), m))
                prev_m = m
        last_label_x = -1e9
        for xx, m in seps:
            painter.setPen(QPen(pal["sep"], 1))
            painter.drawLine(int(xx), int(priceTop), int(xx), int(volBot))
            if xx - last_label_x > 44:
                painter.setPen(pal["text"]); painter.setFont(QFont(_get_font(), 8))
                # 放在绘图区上方空白处，避免与左上角 MA 图例重叠
                painter.drawText(int(xx) + 3, int(priceTop) - 4, m)
                last_label_x = xx
        # 末根日期常驻底部，确保最新时点可读
        painter.setPen(pal["text"]); painter.setFont(QFont(_get_font(), 8))
        _last_dt = self._fmt_time(str(bars[total - 1].get("datetime", "")))
        painter.drawText(int(padL + plotW) - 72, int(volBot) + 16, _last_dt)

        # ---- 蜡烛 ----
        for gi in range(start, total):
            b = bars[gi]
            x = px(gi)
            up = b["close"] >= b["open"]
            col = QColor(self._up_color if up else self._down_color)
            painter.setPen(QPen(col, 1))
            painter.setBrush(QBrush(col))
            if dense:
                painter.drawLine(int(x), int(py(b["high"])), int(x), int(py(b["low"])))
            else:
                # 影线
                painter.drawLine(int(x), int(py(b["high"])), int(x), int(py(b["low"])))
                # 实体（最小 1px 高度，圆角更精致）
                y_o, y_c = py(b["open"]), py(b["close"])
                top = min(y_o, y_c)
                hgt = max(1.0, abs(y_c - y_o))
                bw = max(1.0, body_w)
                r = min(2.0, bw / 2.0, hgt / 2.0)
                painter.drawRoundedRect(int(x - bw / 2), int(top), int(bw), int(hgt), r, r)

        # ---- 均线 ----
        for mi, (name, series) in enumerate(self._ma.items()):
            if len(series) < 2:
                continue
            color = QColor(self._MA_COLORS[mi % len(self._MA_COLORS)])
            painter.setPen(QPen(color, 1.5))
            pts = []
            for gi in range(start, total):
                v = series[gi] if gi < len(series) else None
                if v is None:
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if fv == fv:
                    pts.append(QPointF(px(gi), py(fv)))
            for j in range(1, len(pts)):
                painter.drawLine(pts[j - 1], pts[j])

        # ---- 最新价虚线 + 右侧圆角价签 ----
        last_bar = bars[total - 1]
        last = float(last_bar["close"])
        last_up = last_bar["close"] >= last_bar["open"]
        last_color = QColor(self._up_color if last_up else self._down_color)
        lp = py(last)
        painter.setPen(QPen(last_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(padL), int(lp), int(padL + plotW), int(lp))
        self._price_tag(painter, padL + plotW, lp, self._fmt_price(last), last_color)

        # ---- 关键价位（压力/支撑）水平虚线 ----
        # 按 y 排序后做简单防重叠：y 差 < 14px 的只画第一条
        levels_drawn: list[tuple[float, float, dict]] = []
        for lv in self._levels:
            try:
                pr = float(lv["price"])
            except Exception:
                continue
            if pr < pmin or pr > pmax:
                continue
            yy = py(pr)
            levels_drawn.append((yy, pr, lv))
        levels_drawn.sort(key=lambda x: x[0])
        last_y = -1e9
        for yy, pr, lv in levels_drawn:
            if abs(yy - last_y) < 14:
                continue
            last_y = yy
            is_sup = lv.get("kind") == "support"
            lc = QColor("#22c55e" if is_sup else "#ef4444")
            painter.setPen(QPen(lc, 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(padL), int(yy), int(padL + plotW), int(yy))
            painter.setFont(QFont(_get_font(), 8))
            painter.setPen(lc)
            painter.drawText(int(padL + 3), int(yy) - 2, f"{lv.get('label','')} {pr:,.0f}")

        # ---- 交易参考点标注（买入区间 / 卖出目标） ----
        if self._trade_marks:
            draw_trade_marks(painter, pal, self._trade_marks, px, py, total_n, padL, priceTop, plotW)

        # ---- KP预测曲线 + 置信带（增强：方向色 + 分隔线 + 终点价签） ----
        if fc and len(fc["y"]) > 1:
            base = total - 1  # 与最后一根蜡烛衔接
            # 历史 / 预测 分隔竖线（虚线，明确预测起点）
            sep_x = px(base)
            painter.setPen(QPen(pal["sep"], 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(sep_x), int(priceTop), int(sep_x), int(volBot))

            # 预测方向色（中国惯例：涨红 跌绿）
            y0 = float(fc["y"][0]); y1 = float(fc["y"][-1])
            up_dir = y1 >= y0
            fc_color = QColor(self._up_color if up_dir else self._down_color)

            pts = [QPointF(px(base + i), py(v)) for i, v in enumerate(fc["y"]) if _finite(v)]
            if len(pts) >= 2:
                # 置信带（方向色着色，淡透明）
                if fc.get("upper") and fc.get("lower"):
                    up, lo = fc["upper"], fc["lower"]
                    poly = [QPointF(px(base + i), py(up[i])) for i in range(len(up)) if _finite(up[i])]
                    for i in range(len(lo) - 1, -1, -1):
                        if _finite(lo[i]):
                            poly.append(QPointF(px(base + i), py(lo[i])))
                    if len(poly) >= 3:
                        bc = QColor(fc_color); bc.setAlpha(40)
                        painter.setBrush(QBrush(bc)); painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawPolygon(poly); painter.setBrush(Qt.BrushStyle.NoBrush)
                # 发光底线（宽、低透明度）提升趋势走向的视觉权重
                glow = QColor(fc_color); glow.setAlpha(45)
                painter.setPen(QPen(glow, 5))
                for j in range(1, len(pts)):
                    painter.drawLine(pts[j - 1], pts[j])
                # 主预测线（虚线，方向色，更醒目）
                painter.setPen(QPen(fc_color, 2.2, Qt.PenStyle.DashLine))
                for j in range(1, len(pts)):
                    painter.drawLine(pts[j - 1], pts[j])
                # 起点圆点
                painter.setBrush(QBrush(fc_color)); painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(pts[0], 3, 3)
                # 终点目标价签（方向色 + 涨跌幅度），清晰展示预测目标
                last_close = float(bars[total - 1]["close"])
                tgt = y1
                pct = (tgt / last_close - 1.0) * 100.0 if last_close else 0.0
                tag_txt = f"{self._fmt_price(tgt)} ({pct:+.1f}%)"
                self._forecast_tag(painter, pts[-1].x(), pts[-1].y(),
                                   tag_txt, fc_color, padL, plotW)
                # 顶部「预测 N 根」标注，紧贴分隔线
                painter.setFont(QFont(_get_font(), 9, QFont.Weight.Bold))
                painter.setPen(fc_color)
                painter.drawText(int(sep_x) + 4, int(priceTop) + 12,
                                 f"预测 {len(fc['y']) - 1} 根")

        # ---- 成交量副图 ----
        if self._show_volume:
            for gi in range(start, total):
                b = bars[gi]
                x = px(gi)
                up = b["close"] >= b["open"]
                col = QColor(self._up_color if up else self._down_color)
                col.setAlpha(150)
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QBrush(col))
                yv = vy(b["volume"])
                painter.drawRect(int(x - body_w / 2), int(yv), int(body_w), int(volBot - yv))
            # 成交量 MA5 叠加（细线，提供量能趋势参考）
            if len(self._vol_ma) == total:
                painter.setPen(QPen(pal["volma"], 1.2))
                vp = []
                for gi in range(start, total):
                    v = self._vol_ma[gi]
                    if v is None:
                        continue
                    vp.append(QPointF(px(gi), vy(v)))
                for j in range(1, len(vp)):
                    painter.drawLine(vp[j - 1], vp[j])
            painter.setPen(pal["text"]); painter.setFont(QFont(_get_font(), 8))
            painter.drawText(int(padL + plotW + 5), int(volTop) + 8, f"{vmax:,.0f}")

        # ---- 均线图例（左上） ----
        painter.setFont(QFont(_get_font(), 9)); fm = painter.fontMetrics()
        lx, ly = padL + 6, priceTop + 2
        for mi, (name, series) in enumerate(self._ma.items()):
            color = QColor(self._MA_COLORS[mi % len(self._MA_COLORS)])
            val = ""
            for gi in range(total - 1, start - 1, -1):
                v = series[gi] if gi < len(series) else None
                if v is not None:
                    try:
                        fv = float(v)
                    except Exception:
                        fv = float("nan")
                    if fv == fv:
                        val = f" {fv:,.1f}"
                        break
            label = f"{name}{val}"
            painter.setPen(QPen(color, 2))
            painter.drawLine(int(lx), int(ly + 4), int(lx + 12), int(ly + 4))
            painter.setPen(pal["text"])
            painter.drawText(int(lx + 16), int(ly + 9), label)
            lx += 16 + fm.horizontalAdvance(label) + 12

        # ---- 悬浮十字光标 + 信息框 ----
        if start <= self._hover < total:
            self._draw_crosshair(painter, pal, self._hover, px, py, vy,
                                 padL, priceTop, plotW, priceBot, volBot,
                                 pmin, pmax, priceH, total, start, total_n, body_w)

    def _price_tag(self, painter, right: int, y: float, text: str, color: QColor) -> None:
        """右侧轴上一个圆角价签（带柔和阴影）。"""
        if not _finite(y):
            return
        painter.setFont(QFont(_FONT, 9, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(text) + 10
        h = 16
        x = int(right + 3)
        yy = int(y - h / 2)
        # 阴影
        sh = QColor(0, 0, 0, 70)
        painter.setBrush(QBrush(sh)); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(x + 2, yy + 2, w, h, 3, 3)
        tag = QColor(color); tag.setAlpha(235)
        painter.setBrush(QBrush(tag)); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(x, yy, w, h, 3, 3)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(x + 5, yy + 12, text)

    def _forecast_tag(self, painter, x: float, y: float, text: str,
                      color: QColor, padL: int, plotW: int) -> None:
        """预测终点目标价签（含方向色与涨跌幅度），置于端点左侧避免越界。"""
        if not _finite(x) or not _finite(y):
            return
        painter.setFont(QFont(_FONT, 9, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(text) + 10
        h = 16
        xx = int(x - w - 6)                       # 默认放端点左侧
        if xx < padL + 2:
            xx = int(x + 6)                        # 左侧放不下则放右侧
        yy = int(y - h / 2)
        sh = QColor(0, 0, 0, 70)                  # 柔和阴影
        painter.setBrush(QBrush(sh)); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(xx + 2, yy + 2, w, h, 3, 3)
        tag = QColor(color); tag.setAlpha(240)
        painter.setBrush(QBrush(tag)); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(xx, yy, w, h, 3, 3)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(xx + 5, yy + 12, text)

    def _draw_crosshair(self, painter, pal, gi, px, py, vy,
                        padL, priceTop, plotW, priceBot, volBot,
                        pmin, pmax, priceH, total, start, total_n, body_w) -> None:
        """绘制crosshair。
        
            参数:
                painter
                pal
                gi
                px
                py
                vy
                padL
                priceTop
                plotW
                priceBot
                volBot
                pmin
                pmax
                priceH
                total
                start
                total_n
                body_w"""
        b = self._bars[gi]
        x = px(gi)
        # 高亮当前蜡烛（更柔和的竖向高亮带）
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(pal["hi"]))
        painter.drawRect(int(x - body_w / 2) - 1, priceTop, int(body_w) + 2, volBot - priceTop)
        # 十字线
        yc = py(b["close"])
        if _finite(yc):
            painter.setPen(QPen(pal["cross"], 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(x), int(priceTop), int(x), int(volBot))
            painter.drawLine(int(padL), int(yc), int(padL + plotW), int(yc))

        up = b["close"] >= b["open"]
        chg = (b["close"] / b["open"] - 1) * 100 if b["open"] else 0.0
        col = QColor(self._up_color if up else self._down_color)
        rows = [
            ("开", f"{b['open']:,.2f}"),
            ("高", f"{b['high']:,.2f}"),
            ("低", f"{b['low']:,.2f}"),
            ("收", f"{b['close']:,.2f}"),
            ("涨跌", f"{chg:+.2f}%"),
            ("量", f"{b['volume']:,.0f}"),
        ]
        for name, series in self._ma.items():
            v = series[gi] if gi < len(series) else None
            if v is not None:
                try:
                    fv = float(v)
                except Exception:
                    fv = float("nan")
                if fv == fv:
                    rows.append((name, f"{fv:,.2f}"))

        # 信息框（圆角 + 阴影 + 涨/跌色顶条 + 对齐双列）
        painter.setFont(QFont(_get_font(), 9)); fm = painter.fontMetrics()
        bw = max((fm.horizontalAdvance(f"{l}  {v}") for l, v in rows), default=80) + 26
        bw = max(bw, fm.horizontalAdvance(str(b.get('datetime', ''))[:19]) + 24)
        line_h = 16
        n_lines = 1 + len(rows)
        bh = n_lines * line_h + 10
        bx = int(x) + 14
        if bx + bw > padL + plotW:
            bx = int(x) - 14 - bw
        by = int(priceTop) + 6
        # 阴影
        sh = QColor(0, 0, 0, 60)
        painter.setBrush(QBrush(sh)); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bx + 3, by + 3, bw, bh, 8, 8)
        # 主体
        box = QColor(20, 24, 33) if self._theme == "dark" else QColor(255, 255, 255)
        box.setAlpha(245)
        painter.setPen(QPen(pal["axis"], 1))
        painter.setBrush(QBrush(box))
        painter.drawRoundedRect(bx, by, bw, bh, 8, 8)
        # 涨/跌色左侧条
        painter.setBrush(QBrush(col)); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bx, by, 4, bh, 2, 2)
        # 表头（时间，加粗着色）
        painter.setPen(col); painter.setFont(QFont(_get_font(), 10, QFont.Weight.Bold))
        painter.drawText(bx + 12, by + 18, str(b.get('datetime', ''))[:19])
        # 双列行
        val_bright = QColor(222, 228, 242) if self._theme == "dark" else QColor(30, 41, 59)
        painter.setFont(QFont(_get_font(), 9))
        for i, (l, v) in enumerate(rows):
            ry = by + 18 + (i + 1) * line_h
            painter.setPen(pal["text"]); painter.drawText(bx + 12, ry, l)
            is_chg = (l == "涨跌")
            painter.setPen(col if is_chg else val_bright)
            painter.drawText(bx + bw - 12 - fm.horizontalAdvance(v), ry, v)
        # 右轴价签（跟随光标）
        price_at = pmax - (yc - priceTop) / priceH * (pmax - pmin) if priceH else pmax
        self._price_tag(painter, padL + plotW, yc, self._fmt_price(price_at), col)

    # ---------- 交互 ----------
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """处理mousemove事件。
        
            参数:
                event"""
        if not self._bars:
            return
        padL, padR = 8, 64
        plotW = self.width() - padL - padR
        if plotW <= 0:
            return
        total = len(self._bars)
        view_n = min(self._max_bars, total)
        start = total - view_n
        x = event.position().x()
        frac = (x - padL) / plotW
        gi = start + int(frac * view_n)
        gi = max(start, min(total - 1, gi))
        # M4-13②：广播 hover 占比（供副图/外部图十字联动）
        self.hover_fraction.emit(max(0.0, min(1.0, frac)))
        if gi != self._hover:
            self._hover = gi
            self.update()

    def set_hover_fraction(self, frac) -> None:
        """M4-13②：外部联动入口——副图 hover → 主图十字线。

        占比映射到当前可视窗口的 bar 索引；None=清除。
        """
        if frac is None:
            if self._hover != -1:
                self._hover = -1
                self.update()
            return
        total = len(self._bars)
        if total == 0:
            return
        view_n = min(self._max_bars, total)
        start = total - view_n
        gi = start + int(max(0.0, min(1.0, float(frac))) * view_n)
        self._hover = max(start, min(total - 1, gi))
        self.update()

    def _export_rows(self):
        """M4-13③：导出全部 K 线 OHLCV。"""
        rows = [["时间", "开", "高", "低", "收", "量"]]
        for b in self._bars:
            rows.append([str(b.get("datetime", "")), b.get("open"),
                         b.get("high"), b.get("low"), b.get("close"),
                         b.get("volume")])
        return rows

    def leaveEvent(self, event) -> None:  # noqa: N802
        """处理leave事件。
        
            参数:
                event"""
        if self._hover != -1:
            self._hover = -1
            self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        """处理wheel事件。
        
            参数:
                event"""
        if not self._bars:
            return
        delta = event.angleDelta().y()
        factor = 0.9 if delta > 0 else 1.1
        new = int(self._max_bars * factor)
        self._max_bars = max(20, min(len(self._bars), new))
        self.update()
