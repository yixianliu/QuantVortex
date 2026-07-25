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

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush, QLinearGradient
from PyQt6.QtWidgets import QWidget


_DEFAULT_SERIES_COLORS = [
    "#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#a855f7", "#06b6d4",
]


_FONT = "SimHei"


def _to_color(c) -> QColor:
    if isinstance(c, QColor):
        return c
    return QColor(c)


class PriceChart(QWidget):
    """轻量折线 / 区域图组件。

    用法：
        chart.set_data(
            series=[{"name":"收盘","color":"#3b82f6","x":[...],"y":[...],"width":1.8},
                    {"name":"预测","color":"#f59e0b","x":[...],"y":[...],"dashed":True}],
            bands=[{"lower":[...], "upper":[...], "color":"#3b82f6", "alpha":40}],
            x_ticks=[(0.0,"起点"),(1.0,"终点")],
            title="行情与预测",
        )
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(240)
        self._series: List[dict] = []
        self._bands: List[dict] = []
        self._title = ""
        self._theme = "dark"
        self._x_ticks: Optional[List[tuple]] = None

    # ---------- 公开接口 ----------
    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def set_data(self, series: Optional[Sequence[dict]] = None,
                 bands: Optional[Sequence[dict]] = None,
                 x_ticks: Optional[List[tuple]] = None,
                 title: str = "") -> None:
        self._series = [dict(s) for s in (series or [])]
        self._bands = [dict(b) for b in (bands or [])]
        self._x_ticks = x_ticks
        self._title = title
        self.update()

    def clear(self) -> None:
        self._series = []
        self._bands = []
        self._x_ticks = None
        self.update()

    # ---------- 内部 ----------
    def _palette(self) -> dict:
        if self._theme == "dark":
            return dict(grid=QColor(42, 46, 58), text=QColor(139, 147, 167),
                        axis=QColor(58, 63, 78))
        return dict(grid=QColor(229, 231, 235), text=QColor(107, 114, 128),
                    axis=QColor(209, 213, 219))

    def _y_range(self):
        vals = []
        for s in self._series:
            for v in s.get("y", []):
                if isinstance(v, float) and v == v:  # 过滤 NaN
                    vals.append(v)
        for b in self._bands:
            for v in b.get("lower", []):
                if isinstance(v, float) and v == v:
                    vals.append(v)
            for v in b.get("upper", []):
                if isinstance(v, float) and v == v:
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self._palette()
        W, H = self.width(), self.height()
        title_h = 20 if self._title else 4
        x0, y0 = 10, 8 + title_h
        x1, y1 = W - 10, H - 22
        if x1 <= x0 or y1 <= y0:
            return

        # 标题
        if self._title:
            painter.setPen(pal["text"])
            painter.setFont(QFont(_FONT, 11, QFont.Weight.Bold))
            painter.drawText(x0, 6 + title_h - 6, self._title)

        # 无数据
        if not self._series:
            painter.setPen(pal["text"])
            painter.setFont(QFont(_FONT, 11))
            painter.drawText(x0, (y0 + y1) // 2, "暂无数据")
            return

        ymin, ymax = self._y_range()
        span = ymax - ymin
        n_max = max(len(s.get("y", [])) for s in self._series)

        def mx(i: int) -> float:
            return x0 + (i / (n_max - 1)) * (x1 - x0) if n_max > 1 else (x0 + x1) / 2

        def my(v: float) -> float:
            return y1 - (v - ymin) / span * (y1 - y0)

        # 横向网格 + Y 轴标签
        painter.setPen(QPen(pal["grid"], 1))
        painter.setFont(QFont(_FONT, 9))
        for k in range(5):
            yy = y0 + k * (y1 - y0) / 4
            painter.drawLine(int(x0), int(yy), int(x1), int(yy))
            val = ymax - k * span / 4
            if isinstance(val, float) and val != val:
                continue
            painter.setPen(pal["text"])
            painter.drawText(2, int(yy) + 3, f"{val:,.1f}")
            painter.setPen(QPen(pal["grid"], 1))

        # X 轴刻度（调用方提供）
        if self._x_ticks:
            painter.setPen(pal["text"])
            painter.setFont(QFont(_FONT, 9))
            for frac, label in self._x_ticks:
                xx = x0 + frac * (x1 - x0)
                painter.drawLine(int(xx), int(y1), int(xx), int(y1) + 3)
                painter.drawText(int(xx) - 18, int(y1) + 16, str(label))

        # 置信带（在折线之下）
        for b in self._bands:
            lower, upper = b.get("lower", []), b.get("upper", [])
            if len(lower) < 2 or len(upper) < 2:
                continue
            color = _to_color(b.get("color", "#3b82f6"))
            alpha = int(b.get("alpha", 40))
            poly = [QPointF(mx(i), my(upper[i])) for i in range(len(upper))]
            for i in range(len(lower) - 1, -1, -1):
                poly.append(QPointF(mx(i), my(lower[i])))
            c = QColor(color)
            c.setAlpha(alpha)
            painter.setBrush(QBrush(c))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(poly)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # 折线序列
        for idx, s in enumerate(self._series):
            y = s.get("y", [])
            if len(y) < 1:
                continue
            color = _to_color(s.get("color", _DEFAULT_SERIES_COLORS[idx % len(_DEFAULT_SERIES_COLORS)]))
            pen = QPen(color, float(s.get("width", 1.8)))
            if s.get("dashed"):
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            pts = [QPointF(mx(i), my(v)) for i, v in enumerate(y) if _finite(v)]
            for i in range(1, len(pts)):
                painter.drawLine(pts[i - 1], pts[i])
            # 端点小圆点（NaN 中心会触发 QPainterPath::arcTo NaN 警告，需守卫）
            if pts and _finite(pts[-1].x()) and _finite(pts[-1].y()):
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(pts[-1], 2.5, 2.5)
                painter.setPen(pen)

        # 图例（左上）
        if self._series:
            painter.setFont(QFont(_FONT, 9))
            fm = painter.fontMetrics()
            lx = x0 + 6
            ly = y0 + 2
            for s in self._series:
                name = s.get("name", "")
                if not name:
                    continue
                color = _to_color(s.get("color", "#888"))
                painter.setPen(QPen(color, 2))
                painter.drawLine(int(lx), int(ly + 4), int(lx + 12), int(ly + 4))
                painter.setPen(pal["text"])
                painter.drawText(int(lx + 16), int(ly + 9), name)
                lx += 16 + fm.horizontalAdvance(name) + 12


# ============================================================================
# K 线（蜡烛）图组件：蜡烛 + 成交量 + 均线 + 十字光标 + 悬浮提示
# ============================================================================
class KLineChart(QWidget):
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
        super().__init__(parent)
        self.setMinimumHeight(300)
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
        self._watermark = ""      # 背景水印文字（如合约代码 / 周期）
        self._vol_ma: list = []   # 成交量 MA5（与 _bars 等长，前 N 为 None）

    # ---------- 公开接口 ----------
    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def set_data(self, bars: Sequence[dict],
                 ma: Optional[dict] = None) -> None:
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
        out = []
        for i in range(len(seq)):
            if i < n - 1:
                out.append(None)
                continue
            out.append(sum(seq[i - n + 1:i + 1]) / n)
        return out

    def set_ma(self, ma: dict) -> None:
        self._ma = {k: list(v) for k, v in (ma or {}).items()}
        self.update()

    def set_show_volume(self, show: bool) -> None:
        self._show_volume = show
        self.update()

    def set_forecast(self, y: Optional[Sequence[float]] = None,
                     upper: Optional[Sequence[float]] = None,
                     lower: Optional[Sequence[float]] = None) -> None:
        """叠加 AI 预测曲线（含 ±1σ 置信带）。y[0] 应与最后一根收盘价一致。"""
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

    def clear(self) -> None:
        self._bars = []
        self._ma = {}
        self._hover = -1
        self.update()

    # ---------- 调色板 ----------
    def _palette(self) -> dict:
        if self._theme == "dark":
            return dict(
                grid=QColor(34, 39, 50), text=QColor(170, 178, 198),
                axis=QColor(54, 60, 74), cross=QColor(148, 160, 184),
                bg=QColor(15, 17, 22), band=QColor(37, 99, 235),
                plot=QColor(12, 14, 19), plot_top=QColor(20, 23, 30),
                plot_bot=QColor(9, 11, 15), sep=QColor(58, 64, 80),
                volma=QColor(245, 158, 11), hi=QColor(255, 255, 255, 14))
        return dict(
            grid=QColor(225, 229, 235), text=QColor(71, 85, 105),
            axis=QColor(203, 213, 225), cross=QColor(120, 130, 150),
            bg=QColor(255, 255, 255), band=QColor(37, 99, 235),
            plot=QColor(248, 250, 252), plot_top=QColor(252, 253, 255),
            plot_bot=QColor(240, 244, 248), sep=QColor(203, 213, 225),
            volma=QColor(217, 119, 6), hi=QColor(15, 23, 42, 16))

    _MA_COLORS = ["#f59e0b", "#3b82f6", "#a855f7", "#06b6d4", "#eab308"]

    @staticmethod
    def _fmt_price(v: float) -> str:
        if v is None:
            return ""
        a = abs(v)
        dec = 1 if a >= 1000 else 2 if a >= 100 else 3 if a >= 1 else 4
        return f"{v:,.{dec}f}"

    @staticmethod
    def _fmt_time(s: str) -> str:
        s = str(s).strip()
        # 日线通常带 00:00:00，不显示无意义的时间
        if len(s) >= 19 and s[11:19] == "00:00:00":
            return s[:10]
        if "T" in s or (len(s) > 10 and ":" in s):
            return s[5:10] + " " + s[11:16]   # MM-DD HH:mm
        return s[:10]                          # YYYY-MM-DD

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
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
            painter.setPen(pal["text"]); painter.setFont(QFont(_FONT, 11))
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
            return padL + (gi - start + 0.5) / total_n * plotW

        def py(v: float) -> float:
            return priceBot - (v - pmin) / (pmax - pmin) * priceH

        def vy(v: float) -> float:
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
            painter.setFont(QFont(_FONT, 30, QFont.Weight.Bold))
            fmw = painter.fontMetrics()
            wx = int(padL + plotW) - fmw.horizontalAdvance(self._watermark) - 14
            wy = int(volBot) - 14
            painter.drawText(wx, wy, self._watermark)
            painter.restore()

        # ---- 横向网格 + 右侧价格刻度（自适应小数位） ----
        painter.setFont(QFont(_FONT, 9))
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
                painter.setPen(pal["text"]); painter.setFont(QFont(_FONT, 8))
                # 放在绘图区上方空白处，避免与左上角 MA 图例重叠
                painter.drawText(int(xx) + 3, int(priceTop) - 4, m)
                last_label_x = xx
        # 末根日期常驻底部，确保最新时点可读
        painter.setPen(pal["text"]); painter.setFont(QFont(_FONT, 8))
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
            painter.setFont(QFont(_FONT, 8))
            painter.setPen(lc)
            painter.drawText(int(padL + 3), int(yy) - 2, f"{lv.get('label','')} {pr:,.0f}")

        # ---- AI 预测曲线 + 置信带 ----
        if fc and len(fc["y"]) > 1:
            base = total - 1  # 与最后一根蜡烛衔接
            if fc.get("upper") and fc.get("lower"):
                up, lo = fc["upper"], fc["lower"]
                poly = [QPointF(px(base + i), py(up[i])) for i in range(len(up)) if _finite(up[i])]
                for i in range(len(lo) - 1, -1, -1):
                    if _finite(lo[i]):
                        poly.append(QPointF(px(base + i), py(lo[i])))
                if len(poly) >= 3:
                    bc = QColor(self._MA_COLORS[1]); bc.setAlpha(45)
                    painter.setBrush(QBrush(bc)); painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPolygon(poly); painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor("#f59e0b"), 2.0, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            pts = [QPointF(px(base + i), py(v)) for i, v in enumerate(fc["y"]) if _finite(v)]
            for j in range(1, len(pts)):
                painter.drawLine(pts[j - 1], pts[j])
            if pts and _finite(pts[-1].x()) and _finite(pts[-1].y()):
                painter.setBrush(QBrush(QColor("#f59e0b"))); painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(pts[-1], 3, 3)

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
            painter.setPen(pal["text"]); painter.setFont(QFont(_FONT, 8))
            painter.drawText(int(padL + plotW + 5), int(volTop) + 8, f"{vmax:,.0f}")

        # ---- 均线图例（左上） ----
        painter.setFont(QFont(_FONT, 9)); fm = painter.fontMetrics()
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

    def _draw_crosshair(self, painter, pal, gi, px, py, vy,
                        padL, priceTop, plotW, priceBot, volBot,
                        pmin, pmax, priceH, total, start, total_n, body_w) -> None:
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
        painter.setFont(QFont(_FONT, 9)); fm = painter.fontMetrics()
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
        painter.setPen(col); painter.setFont(QFont(_FONT, 10, QFont.Weight.Bold))
        painter.drawText(bx + 12, by + 18, str(b.get('datetime', ''))[:19])
        # 双列行
        val_bright = QColor(222, 228, 242) if self._theme == "dark" else QColor(30, 41, 59)
        painter.setFont(QFont(_FONT, 9))
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
        if gi != self._hover:
            self._hover = gi
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover != -1:
            self._hover = -1
            self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self._bars:
            return
        delta = event.angleDelta().y()
        factor = 0.9 if delta > 0 else 1.1
        new = int(self._max_bars * factor)
        self._max_bars = max(20, min(len(self._bars), new))
        self.update()
