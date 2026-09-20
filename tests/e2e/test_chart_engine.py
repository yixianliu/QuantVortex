"""M1.1 e2e：图表引擎抽象层（数据层 + 渲染后端 + 工厂），offscreen 验证。

验证点：
- ChartData：price_domain / n_bars / from_dict / apply_to_widget 灌数据到 KLineChart。
- make_chart(backend="painter") 返回 QWidget，且 KLineChart 已加载数据。
- available_backends：painter 恒可用；pyqtgraph 可用/不可用都不报错。
- make_chart(backend="pyqtgraph") 缺失时自动回退 painter（离线优先护栏）。
- make_chart(backend="unknown") 回退 painter。
- 渲染一次 paintEvent 不崩（offscreen 走直驱 paintEvent 契约）。
"""
from __future__ import annotations

import unittest

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication, QWidget

from futures_quant.ui.chart_engine import (
    ChartData,
    available_backends,
    make_backend,
    make_chart,
)


def _bars(n: int = 60, seed: int = 3) -> list:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    out = []
    for i in range(n):
        c = float(close[i])
        out.append({
            "time": f"2025-{i//30+1:02d}-{i%30+1:02d}",
            "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
            "volume": int(1e4 + rng.integers(0, 1e3)),
        })
    return out


class TestChartData(unittest.TestCase):
    def test_price_domain(self) -> None:
        d = ChartData(bars=_bars(50))
        lo, hi = d.price_domain()
        self.assertGreater(hi, lo)
        closes = [b["close"] for b in d.bars]
        self.assertGreaterEqual(lo, min(closes) * 0.985)
        self.assertLessEqual(hi, max(closes) * 1.015)

    def test_from_dict(self) -> None:
        bars = _bars(10)
        d = ChartData.from_dict({"bars": bars, "watermark": "rb.D"})
        self.assertEqual(d.n_bars(), 10)
        self.assertEqual(d.watermark, "rb.D")

    def test_apply_to_widget(self) -> None:
        app = QApplication.instance() or QApplication([])
        from futures_quant.ui.chart_widget import KLineChart
        c = KLineChart()
        data = ChartData(bars=_bars(30), watermark="au.D")
        data.apply_to_widget(c)
        self.assertEqual(len(c._bars), 30)  # 既有私有字段验证灌入成功
        self.assertEqual(c._watermark, "au.D")


class TestBackends(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])

    def test_painter_always_available(self) -> None:
        info = {b["name"]: b for b in available_backends()}
        self.assertTrue(info["painter"]["available"])
        self.assertIn("pyqtgraph", info)  # 列出但不强求可用

    def test_make_chart_painter(self) -> None:
        data = ChartData(bars=_bars(40))
        w = make_chart(data=data, backend="painter")
        self.assertIsInstance(w, QWidget)
        self.assertEqual(len(w._bars), 40)

    def test_unknown_backend_falls_back(self) -> None:
        data = ChartData(bars=_bars(20))
        w = make_chart(data=data, backend="does_not_exist")
        self.assertIsInstance(w, QWidget)
        self.assertEqual(len(w._bars), 20)

    def test_pyqtgraph_backend_or_fallback(self) -> None:
        """pyqtgraph 后端：可用时返回加速 widget；不可用时自动回退 painter。

        无论当前环境是否安装 pyqtgraph，本调用都不抛异常（离线优先护栏）。
        """
        data = ChartData(bars=_bars(20))
        w = make_chart(data=data, backend="pyqtgraph")
        self.assertIsInstance(w, QWidget)
        pg_info = next(b for b in available_backends() if b["name"] == "pyqtgraph")
        if pg_info["available"]:
            # 加速后端：非 KLineChart，无 _bars 字段（PlotWidget 体系）
            self.assertFalse(hasattr(w, "_bars"))
        else:
            # 回退 painter：KLineChart 体系，已灌入数据
            self.assertTrue(hasattr(w, "_bars"))
            self.assertEqual(len(w._bars), 20)

    def test_make_backend_painter(self) -> None:
        be = make_backend("painter")
        self.assertTrue(be.available())


class TestRenderSmoke(unittest.TestCase):
    """offscreen 渲染冒烟：构造 → show → 直驱 paintEvent，不崩。"""

    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])

    def _drive_paint(self, w: QWidget) -> None:
        w.show()
        self.app.processEvents()
        w.updateGeometry()
        ev = QPaintEvent(w.rect())
        w.paintEvent(ev)
        self.app.processEvents()

    def test_painter_chart_paint(self) -> None:
        data = ChartData(bars=_bars(80))
        data.ma = {"MA5": [None] * 4 + [float(np.mean([b["close"] for b in _bars(80)[i-4:i+1]])) for i in range(4, 80)]}
        w = make_chart(data=data, backend="painter")
        parent = QWidget()
        w.setParent(parent)
        parent.show()
        self.app.processEvents()
        self._drive_paint(w)  # 不抛异常即通过


if __name__ == "__main__":
    unittest.main(verbosity=2)
