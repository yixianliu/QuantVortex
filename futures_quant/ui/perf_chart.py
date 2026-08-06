"""回测绩效图表（纯 QPainter，零第三方依赖，离线可跑）。

BacktestPerfChart：在单一控件内同时呈现
    - 上半区：资金 / 收益率曲线（渐变填充 + 起点基线 + 峰值/终点标注）
    - 下半区：最大回撤区域（红色阴影，从 0 向下展开），标注最大回撤值
主题配色与全应用共用 widgets.PALETTE，切换主题时由调用方下发 set_theme。
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QLinearGradient
from PyQt6.QtWidgets import QWidget, QToolTip

from .widgets import THEME, PALETTE

_FONT = None  # 延迟初始化，使用系统字体


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


class BacktestPerfChart(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(260)
        self._equity: List[float] = []
        self._dates: List[str] = []
        self._title = "回测绩效：资金曲线与最大回撤"
        self._theme = THEME
        self._has_trades = False
        self._benchmark: List[float] = []
        self._metrics: dict = {}
        self._gx0 = self._gx1 = 0.0
        self._gn = 0

    # ---------- 公开接口 ----------
    def set_theme(self, t: str) -> None:
        self._theme = t
        self.update()

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def set_data(self, equity: Sequence[float],
                 dates: Optional[Sequence[str]] = None,
                 has_trades: bool = False) -> None:
        self._equity = [float(x) for x in equity] if equity else []
        self._dates = [str(d) for d in (dates or [])]
        self._has_trades = has_trades or bool(self._equity)
        self.update()

    def clear(self) -> None:
        self._equity = []
        self._dates = []
        self._has_trades = False
        self.update()

    # ---------- 扩展接口（R1 交互深化） ----------
    def set_benchmark(self, series: Optional[Sequence[float]]) -> None:
        """叠加一条"买入持有"基准参考线（与资金曲线同起点归一化）。"""
        self._benchmark = [float(x) for x in series] if series else []
        self.update()

    def set_metrics(self, metrics: Optional[dict]) -> None:
        """右上角内联展示夏普/年化/最大回撤。"""
        self._metrics = dict(metrics or {})
        self.update()

    def index_at(self, x: int) -> int:
        """把像素 x 映射回数据索引（供悬停提示）。返回 -1 表示无效。"""
        if self._gn < 2 or self._gx1 <= self._gx0:
            return -1
        t = (x - self._gx0) / (self._gx1 - self._gx0)
        idx = int(round(t * (self._gn - 1)))
        return max(0, min(self._gn - 1, idx))

    def export_png(self, path: str) -> None:
        """导出当前绘制结果为 PNG。"""
        self.grab().save(path)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if len(self._equity) < 2:
            return
        idx = self.index_at(int(ev.position().x()))
        if idx < 0:
            return
        eq = self._equity
        dd = self._drawdown()
        start = eq[0] or 1.0
        ret = (eq[idx] - start) / start
        date = self._dates[idx] if idx < len(self._dates) else f"#{idx}"
        tip = (f"{date}\n资金 {eq[idx]:,.0f}\n"
               f"收益率 {ret * 100:+.1f}%\n回撤 {dd[idx] * 100:.1f}%")
        QToolTip.showText(ev.globalPosition().toPoint(), tip, self)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        QToolTip.hideText()

    # ---------- 内部计算 ----------
    def _drawdown(self) -> List[float]:
        if not self._equity:
            return []
        eq = self._equity
        peak = eq[0]
        dd = []
        for v in eq:
            if v > peak:
                peak = v
            dd.append((peak - v) / peak if peak > 0 else 0.0)
        return dd

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = PALETTE[self._theme]
        W, H = self.width(), self.height()
        pad_l, pad_r = 48, 44
        pad_t = 22 if self._title else 6
        pad_b = 16

        # 标题（基线落在顶部留白区内，避免贴边被裁切）
        if self._title:
            p.setPen(QColor(pal["text"]))
            p.setFont(QFont(_get_font(), 11, QFont.Weight.Bold))
            p.drawText(pad_l, pad_t - 6, self._title)

        if not self._equity or len(self._equity) < 2:
            p.setPen(QColor(pal["sub"]))
            p.setFont(QFont(_get_font(), 11))
            p.drawText(pad_l, (pad_t + H) // 2, "暂无回测数据")
            return

        eq = self._equity
        dd = self._drawdown()
        start = eq[0]
        lo, hi = min(eq), max(eq)
        eq_span = (hi - lo) or abs(hi) * 0.01 or 1.0
        # 回撤区间（0 ~ max_dd）
        max_dd = max(dd) if dd else 0.0
        dd_span = max_dd or 0.0001

        # 区域划分：上 64% 资金曲线，下 36% 回撤
        x0, x1 = pad_l, W - pad_r
        n = len(eq)
        self._gx0, self._gx1, self._gn = x0, x1, n
        plot_h = H - pad_t - pad_b
        split = pad_t + int(plot_h * 0.64)
        eq_top, eq_bot = pad_t, split - 6
        dd_top, dd_bot = split + 6, H - pad_b

        def ex(i: int) -> float:
            return x0 + (i / (n - 1)) * (x1 - x0) if n > 1 else (x0 + x1) / 2

        def ey(v: float) -> float:
            return eq_bot - (v - lo) / eq_span * (eq_bot - eq_top)

        def dy(d: float) -> float:
            return dd_top + d / dd_span * (dd_bot - dd_top)

        up = QColor(pal["up"])      # 期货惯例：涨红
        down = QColor(pal["down"])
        grid = QColor(pal["grid"])
        sub = QColor(pal["sub"])
        text = QColor(pal["text"])

        # ---- 上半区：资金曲线 ----
        # 网格
        p.setPen(QPen(grid, 1))
        for k in range(4):
            yy = eq_top + k * (eq_bot - eq_top) / 3
            p.drawLine(int(x0), int(yy), int(x1), int(yy))
        # 左轴：资金刻度
        p.setPen(QColor(pal["sub"]))
        p.setFont(QFont(_get_font(), 8))
        for k in range(4):
            yy = eq_top + k * (eq_bot - eq_top) / 3
            val = hi - (k / 3.0) * (hi - lo)
            p.drawText(2, int(yy) + 3, f"{val:,.0f}")
        # 起点基线
        base_y = ey(start)
        p.setPen(QPen(sub, 1, Qt.PenStyle.DashLine))
        p.drawLine(int(x0), int(base_y), int(x1), int(base_y))

        # 曲线 + 渐变填充
        pts = [QPointF(ex(i), ey(v)) for i, v in enumerate(eq)]
        if len(pts) > 1:
            grad = QLinearGradient(0, eq_top, 0, eq_bot)
            grad.setColorAt(0, QColor(up.red(), up.green(), up.blue(), 60))
            grad.setColorAt(1, QColor(up.red(), up.green(), up.blue(), 6))
            poly = [QPointF(x0, eq_bot)] + pts + [QPointF(x1, eq_bot)]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawPolygon(poly)
            p.setPen(QPen(up, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(pts)

        # 基准叠加（买入持有，归一化到起点）
        if self._benchmark and len(self._benchmark) == n and self._benchmark[0]:
            b0 = self._benchmark[0]
            bpts = [QPointF(ex(i), ey(self._benchmark[i] / b0 * start))
                    for i in range(n)]
            p.setPen(QPen(QColor(pal["text"]), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(bpts)

        # 峰值 / 终点标注
        peak_i = int(max(range(len(eq)), key=lambda i: eq[i]))
        p.setPen(text)
        p.setFont(QFont(_get_font(), 9))
        p.drawText(int(x1) - 120, int(eq_top) + 12,
                   f"起点 {start:,.0f}")
        p.drawText(int(x0) + 4, int(eq_top) + 12,
                   f"峰值 {hi:,.0f}")
        p.drawText(int(x1) - 120, int(eq_bot) - 4,
                   f"终点 {eq[-1]:,.0f}")

        # 内联指标注解（右上）
        if self._metrics:
            parts = []
            if "sharpe" in self._metrics:
                parts.append(f"夏普 {float(self._metrics['sharpe']):.2f}")
            if "annual_return" in self._metrics:
                ar = self._metrics["annual_return"]
                parts.append(f"年化 {ar * 100:.1f}%" if isinstance(ar, (int, float)) else f"年化 {ar}")
            if "max_drawdown" in self._metrics:
                md = self._metrics["max_drawdown"]
                parts.append(f"回撤 {md * 100:.1f}%" if isinstance(md, (int, float)) else f"回撤 {md}")
            if parts:
                p.setPen(QColor(pal["sub"]))
                p.setFont(QFont(_get_font(), 9))
                p.drawText(int(x1) - 172, int(eq_top) - 4, "   ".join(parts))

        # ---- 下半区：最大回撤阴影 ----
        # 0 基线（顶部）
        p.setPen(QPen(sub, 1))
        p.drawLine(int(x0), int(dd_top), int(x1), int(dd_top))
        # 右轴：回撤%刻度
        p.setPen(QColor(pal["sub"]))
        p.setFont(QFont(_get_font(), 8))
        for k in range(3):
            yy = dd_top + k * (dd_bot - dd_top) / 2
            val = (1 - k / 2.0) * max_dd * 100
            p.drawText(int(x1) + 3, int(yy) + 3, f"{val:.1f}%")
        # 回撤区域（红，向下）
        dd_pts = [QPointF(ex(i), dy(d)) for i, d in enumerate(dd)]
        if len(dd_pts) > 1:
            poly2 = [QPointF(x0, dd_top)] + dd_pts + [QPointF(x1, dd_top)]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(down.red(), down.green(), down.blue(), 55))
            p.drawPolygon(poly2)
            p.setPen(QPen(down, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(dd_pts)
        # 最大回撤标注
        p.setPen(down)
        p.setFont(QFont(_get_font(), 9, QFont.Weight.Bold))
        p.drawText(int(x0) + 4, int(dd_bot) - 2,
                   f"最大回撤 {max_dd*100:.1f}%")

        # 时间轴标签（底部）
        if self._dates and n > 1:
            p.setPen(QColor(pal["sub"]))
            p.setFont(QFont(_get_font(), 8))
            ticks = 5
            for t in range(ticks):
                i = int(round(t / (ticks - 1) * (n - 1)))
                xx = ex(i)
                p.drawText(int(xx) - 20, H - 3, str(self._dates[i])[:10])

        # 分隔标签
        p.setPen(sub)
        p.setFont(QFont(_get_font(), 9))
        p.drawText(int(x0) + 4, int(split) - 1, "资金曲线")
        p.drawText(int(x0) + 4, int(split) + 14, "回撤")
