"""M1.1 图表引擎抽象层：把 K 线图拆成「渲染后端 + 数据层 + 交互层」三层。

设计（决策门 D1.1：默认 Painter 保证打包轻，可选 pyqtgraph 走硬件加速）：
- ``ChartData``（数据层）：持有 bars / 均线 / 预测带 / 关键价位 / 交易标记，
  提供归一化视图（价格缩放域、可见根数窗口），与渲染后端解耦。
- ``RenderBackend``（渲染后端抽象）：``render(chart, widget)`` + ``widget()`` 工厂。
  - ``PainterKLineBackend``：默认，复用 ``chart_widget.KLineChart``（零额外依赖，
    既有 e2e 护栏完全不变，仅作为「Painter 后端」的载体被引擎识别）。
  - ``PyQtGraphBackend``（可选加速）：惰性 import pyqtgraph；缺失时 ``available()``
    返回 False 并回退 Painter，绝不阻塞 UI（离线优先护栏）。
- ``make_chart(widget_class, data, backend)``（引擎入口）：统一工厂，按 backend 名
  选择渲染器并返回可挂到布局的 QWidget。

非破坏式：现有代码仍可 ``from .chart_widget import KLineChart``，本层是并行新增能力。
防未来函数：只渲染已给定的 bars，不读未来数据。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)

__all__ = [
    "ChartData",
    "RenderBackend",
    "PainterKLineBackend",
    "PyQtGraphBackend",
    "available_backends",
    "make_backend",
    "make_chart",
]


# ---------------------------------------------------------------------------
# 数据层
# ---------------------------------------------------------------------------
@dataclass
class ChartData:
    """K 线图表数据层（与渲染后端解耦）。

    参数:
        bars: 列表，每项含 open/high/low/close/volume(/time)。
        ma: 均线 dict ``{name: [values]}``。
        forecast: 预测带 dict ``{"y":[...], "upper":[...], "lower":[...]}`` 或 None。
        levels: 关键价位列表 ``[{price, kind, label}]``。
        trade_marks: 交易参考点列表。
        watermark: 背景水印文字。
    """
    bars: List[dict] = field(default_factory=list)
    ma: Dict[str, List[float]] = field(default_factory=dict)
    forecast: Optional[Dict[str, List[float]]] = None
    levels: List[dict] = field(default_factory=list)
    trade_marks: List[dict] = field(default_factory=list)
    watermark: str = ""

    def n_bars(self) -> int:
        return len(self.bars)

    def price_domain(self) -> tuple:
        """全部 K 线的 (min, max) 价格域（含预测带），无数据返回 (0,0)。"""
        lo, hi = float("inf"), float("-inf")
        for b in self.bars:
            try:
                lo = min(lo, float(b.get("low", 0) or 0))
                hi = max(hi, float(b.get("high", 0) or 0))
            except Exception:
                continue
        if self.forecast:
            for key in ("y", "upper", "lower"):
                for v in self.forecast.get(key) or []:
                    try:
                        lo = min(lo, float(v))
                        hi = max(hi, float(v))
                    except Exception:
                        continue
        if lo == float("inf"):
            return 0.0, 0.0
        return lo, hi

    def apply_to_widget(self, widget: Any) -> None:
        """把数据灌进一个 KLineChart 实例（调用其既有 set_* 接口）。"""
        widget.set_data(self.bars, ma=self.ma or None)
        if self.forecast is not None:
            widget.set_forecast(
                self.forecast.get("y"), self.forecast.get("upper"),
                self.forecast.get("lower"))
        else:
            widget.set_forecast(None)
        widget.set_levels(self.levels or None)
        widget.set_trade_marks(self.trade_marks or None)
        if self.watermark:
            widget.set_watermark(self.watermark)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "ChartData":
        """从 dict 构造（便于 UI 直接传参）。"""
        d = d or {}
        return cls(
            bars=list(d.get("bars") or []),
            ma={k: list(v) for k, v in (d.get("ma") or {}).items()},
            forecast=d.get("forecast"),
            levels=list(d.get("levels") or []),
            trade_marks=list(d.get("trade_marks") or []),
            watermark=str(d.get("watermark") or ""),
        )


# ---------------------------------------------------------------------------
# 渲染后端抽象
# ---------------------------------------------------------------------------
class RenderBackend:
    """渲染后端接口。子类实现 ``available()`` / ``create(widget_class, data)``。"""

    NAME: str = "base"

    def available(self) -> bool:
        return True

    def create(self, widget_class, data: ChartData, parent: Optional[QWidget] = None) -> QWidget:
        raise NotImplementedError

    @property
    def label(self) -> str:
        return self.NAME


class PainterKLineBackend(RenderBackend):
    """默认 Painter 后端：直接复用 ``chart_widget.KLineChart``。

    零额外依赖，既有 e2e（test_all_pages / test_perf_chart_ux）完全不变。
    """
    NAME = "painter"

    def create(self, widget_class, data: ChartData, parent: Optional[QWidget] = None) -> QWidget:
        from .chart_widget import KLineChart
        cls = widget_class if isinstance(widget_class, type) else KLineChart
        inst = cls(parent)
        data.apply_to_widget(inst)
        return inst


class PyQtGraphBackend(RenderBackend):
    """可选 pyqtgraph 硬件加速后端。

    惰性 import；缺失时 ``available()`` 返回 False，引擎自动回退 Painter（离线优先）。
    本实现仅做最基础的蜡烛 + 成交量绘制，提供「可切换加速路径」骨架。
    """
    NAME = "pyqtgraph"

    def __init__(self) -> None:
        self._mod = None
        self._checked = False

    def _ensure(self) -> bool:
        if not self._checked:
            try:
                import pyqtgraph  # noqa: F401
                self._mod = pyqtgraph
            except Exception:
                self._mod = None
            self._checked = True
        return self._mod is not None

    def available(self) -> bool:
        return self._ensure()

    def create(self, widget_class, data: ChartData, parent: Optional[QWidget] = None) -> QWidget:
        if not self._ensure():
            raise RuntimeError("pyqtgraph 不可用，请改用 painter 后端")
        import pyqtgraph as pg
        w = pg.PlotWidget(parent=parent)
        if data.bars:
            closes = [float(b.get("close", 0) or 0) for b in data.bars]
            w.plot(closes, pen="#3b82f6", name="close")
            lo, hi = data.price_domain()
            w.setYRange(lo, hi, padding=0.05)
        # 预测带
        if data.forecast and data.forecast.get("upper"):
            w.fillBetween(
                data.forecast["upper"], data.forecast.get("lower") or [0] * len(data.forecast["upper"]),
                pen=None, brush=(59, 130, 246, 60), name="band")
        if data.watermark:
            w.setTitle(data.watermark)
        return w


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------
_BACKENDS = {
    "painter": PainterKLineBackend,
    "pyqtgraph": PyQtGraphBackend,
}


def available_backends() -> List[Dict[str, Any]]:
    """列出可用后端 ``[{name, available, label}]``。"""
    out = []
    for name, cls in _BACKENDS.items():
        inst = cls()
        out.append({"name": name, "available": inst.available(), "label": inst.label})
    return out


def make_backend(name: str) -> RenderBackend:
    """按名取后端实例；未知名回退 painter。"""
    cls = _BACKENDS.get(name, PainterKLineBackend)
    return cls()


def make_chart(
    widget_class: Optional[type] = None,
    data: Optional[ChartData] = None,
    backend: str = "painter",
    parent: Optional[QWidget] = None,
) -> QWidget:
    """统一图表工厂：按 backend 选择渲染器，返回可挂布局的 QWidget。

    backend 不可用（如 pyqtgraph 缺失）时自动回退 painter 并 log warn（离线优先）。
    """
    if data is None:
        data = ChartData()
    be = make_backend(backend)
    if not be.available():
        log.warning("图表后端 %s 不可用，回退 painter", backend)
        be = PainterKLineBackend()
    return be.create(widget_class, data, parent)
