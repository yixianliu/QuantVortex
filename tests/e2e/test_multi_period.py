"""M1.4 e2e：多周期 K 线对照组件（同步缩放 + 跨图十字 + 主题），离线验证。

验证点：
- 构造 4 周期纵向堆叠，注册 4 张 KLineChart。
- set_data 灌数据（缺失周期降级空图，不抛错）。
- MultiPeriodSync：zoom_in/zoom_out/set_visible 截断 20~200，广播 _max_bars。
- set_hover 跨图广播 _hover（4 图同一索引）。
- set_theme 刷新主题色（不崩）。
"""
from __future__ import annotations

import random
import unittest

from PyQt6.QtWidgets import QApplication

from futures_quant.ui.multi_period_widget import (
    MultiPeriodWidget,
    MultiPeriodSync,
    DEFAULT_PERIODS,
)


def _bars(n: int, base: float) -> list[dict]:
    """生成 n 根合成 K 线。"""
    random.seed(n + int(base))
    out = []
    c = base
    for i in range(n):
        o = c
        h = c + 2.0
        l = c - 2.0
        c = c + random.uniform(-1.0, 1.0)
        out.append({"time": i, "open": o, "high": h, "low": l,
                    "close": c, "volume": 100 + i})
    return out


class TestMultiPeriodSync(unittest.TestCase):
    def test_zoom_bounds(self) -> None:
        s = MultiPeriodSync()
        for _ in range(100):
            s.zoom_in()
        self.assertEqual(s.visible, 20)
        for _ in range(200):
            s.zoom_out()
        self.assertEqual(s.visible, 200)

    def test_set_visible_clamps(self) -> None:
        s = MultiPeriodSync()
        s.set_visible(5)
        self.assertEqual(s.visible, 20)
        s.set_visible(9999)
        self.assertEqual(s.visible, 200)

    def test_hover_broadcast(self) -> None:
        app = QApplication.instance() or QApplication([])
        s = MultiPeriodSync()
        from futures_quant.ui.chart_widget import KLineChart
        a, b = KLineChart(), KLineChart()
        s.register(a)
        s.register(b)
        s.set_hover(7)
        self.assertEqual(a._hover, 7)
        self.assertEqual(b._hover, 7)
        a.deleteLater()
        b.deleteLater()
        app.processEvents()


class TestMultiPeriodWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_default_periods(self) -> None:
        self.assertEqual(len(DEFAULT_PERIODS), 4)

    def test_construction_registers_all(self) -> None:
        mp = MultiPeriodWidget()
        self.assertEqual(len(mp._charts), 4)
        self.assertEqual(len(mp._sync._charts), 4)
        mp.deleteLater()
        self.app.processEvents()

    def test_set_data_missing_period_degrades(self) -> None:
        mp = MultiPeriodWidget()
        mp.set_data({"5m": _bars(50, 100)})  # 其余 3 周期缺失
        self.assertEqual(len(mp._charts["5m"]._bars), 50)
        self.assertEqual(len(mp._charts["30m"]._bars), 0)  # 降级空图
        mp.deleteLater()
        self.app.processEvents()

    def test_set_period_data_incremental(self) -> None:
        mp = MultiPeriodWidget()
        mp.set_period_data("D", _bars(30, 88))
        self.assertEqual(len(mp._charts["D"]._bars), 30)
        mp.deleteLater()
        self.app.processEvents()

    def test_zoom_updates_all_charts(self) -> None:
        mp = MultiPeriodWidget()
        mp._sync.set_visible(40)
        for ch in mp._charts.values():
            self.assertEqual(ch._max_bars, 40)
        mp.deleteLater()
        self.app.processEvents()

    def test_theme_switch_no_crash(self) -> None:
        mp = MultiPeriodWidget()
        mp.set_theme("light")
        mp.set_theme("dark")
        self.app.processEvents()
        mp.deleteLater()
        self.app.processEvents()


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
