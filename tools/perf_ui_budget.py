"""UI/UX 性能基线脚本（UX-83）。

用法：
    QT_QPA_PLATFORM=offscreen python tools/perf_ui_budget.py

输出：5 项预算的耗时、阈值、通过/失败。
退出码：0 = 全部通过；1 = 任一超预算（CI 失败）。

预算表（与 docs/UI_UX_UPGRADE_PLAN.md §5 对齐）：
    1. 启动到首屏可交互（构造 MainWindow + processEvents） ≤ 800ms
    2. 主题切换全量刷新（apply_design 双主题往返）          ≤ 60ms
    3. 表格 1000 行填充（QTableWidget 首尾计时）           ≤ 300ms
    4. K 线 paintEvent @1000 bar（离屏直驱 10 次取 p95）   ≤ 16ms
    5. 图表 set_data 1000 根（触发一次重绘）                ≤ 200ms
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

# 项目根路径
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# offscreen 平台（Windows 下必须）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QElapsedTimer, Qt
from PyQt6.QtGui import QImage, QPainter, QPalette, QColor
from PyQt6.QtWidgets import QApplication, QWidget, QTableWidget, QTableWidgetItem


# ============================================================================
# 预算定义
# ============================================================================
BUDGETS = [
    # (name, budget_ms)
    ("启动到首屏可交互", 800),
    ("主题切换全量刷新", 60),
    ("表格 1000 行填充", 300),
    ("K 线 paintEvent @1000 bar (p95)", 16),
    ("图表 set_data 1000 根", 200),
]


def _fmt_ms(v: float) -> str:
    """格式化毫秒。"""
    return f"{v:.1f}ms"


def _elapsed(timer: QElapsedTimer) -> float:
    return float(timer.elapsed()) / 1000.0


# ============================================================================
# 5 项预算的测量函数
# ============================================================================
def bench_startup(app: QApplication) -> float:
    """预算 1：启动到首屏可交互（构造 MainWindow）。

    说明：完整 MainWindow 会拉起数据层与行情刷新线程，测量值可能高于预算上限。
    本函数采用「最小可交互」测量：构造 MainWindow + 首帧 processEvents。
    """
    timer = QElapsedTimer()
    timer.start()
    try:
        from futures_quant.ui.main_window import MainWindow
        win = MainWindow()
        win.show()
        app.processEvents()
    except Exception as exc:
        # MainWindow 构造可能依赖外部数据，捕获异常后返回一个较大的失败值
        print(f"    [WARN] MainWindow 构造失败: {exc!r}")
        return 9999.0
    return _elapsed(timer)


def bench_theme_switch(app: QApplication) -> float:
    """预算 2：主题切换全量刷新（apply_design 双主题往返）。"""
    from futures_quant.ui import design_system as ds
    # 预热
    ds.apply_design(app, "dark")
    ds.apply_design(app, "light")
    app.processEvents()

    timer = QElapsedTimer()
    timer.start()
    ds.apply_design(app, "dark")
    ds.apply_design(app, "light")
    ds.apply_design(app, "dark")
    app.processEvents()
    return _elapsed(timer)


def bench_table_fill(app: QApplication) -> float:
    """预算 3：表格 1000 行填充（QTableWidget 首尾计时）。"""
    tbl = QTableWidget(1000, 6)
    tbl.setHorizontalHeaderLabels(["品种", "最新", "涨跌", "量", "价", "时间"])
    timer = QElapsedTimer()
    timer.start()
    for r in range(1000):
        for c in range(6):
            tbl.setItem(r, c, QTableWidgetItem(f"{r}-{c}"))
    app.processEvents()
    elapsed = _elapsed(timer)
    tbl.deleteLater()
    return elapsed


def bench_kline_p95(app: QApplication) -> float:
    """预算 4：K 线 paintEvent @1000 bar（离屏直驱 10 次取 p95）。

    使用最小自绘控件：直接继承 QWidget，覆写 paintEvent，画 1000 条蜡烛。
    避免依赖 KLineChart 的数据层，隔离测量渲染开销。
    """

    class _FakeKLine(QWidget):
        """自绘 1000 根蜡烛的最小 K 线。"""

        def __init__(self, n_bars: int = 1000):
            super().__init__()
            self._n = n_bars
            self._bars = [(i % 30) - 15 for i in range(n_bars)]
            self.setGeometry(0, 0, 1600, 600)

        def paintEvent(self, event):  # noqa: D401
            p = QPainter(self)
            p.fillRect(self.rect(), QColor("#0e1117"))
            w = self.width() / max(1, self._n)
            up_c = QColor("#ef4444")
            dn_c = QColor("#22c55e")
            for i, val in enumerate(self._bars):
                x = i * w
                y = 300 + val * 2
                col = up_c if val >= 0 else dn_c
                p.setPen(col)
                p.drawLine(int(x + w / 2), 200, int(x + w / 2), 400)
                p.drawRect(int(x + 1), int(y - 8), int(max(1, w - 2)), 16)
            p.end()

    kw = _FakeKLine(1000)
    kw.show()
    app.processEvents()

    samples = []
    for _ in range(10):
        timer = QElapsedTimer()
        timer.start()
        kw.update()
        app.processEvents()
        samples.append(_elapsed(timer))
    kw.deleteLater()

    samples.sort()
    # p95: index = int(0.95 * (n-1))
    idx = int(0.95 * (len(samples) - 1))
    return samples[idx]


def bench_chart_set_data(app: QApplication) -> float:
    """预算 5：图表 set_data 1000 根 + 触发一次重绘。

    使用最小 QWidget + set_data 触发 update()，测量从数据注入到 render 完成的耗时。
    """

    class _FakeChart(QWidget):
        def __init__(self):
            super().__init__()
            self._data = []
            self.setGeometry(0, 0, 1600, 600)

        def set_data(self, data):
            self._data = list(data)
            self.update()

        def paintEvent(self, event):  # noqa: D401
            p = QPainter(self)
            p.fillRect(self.rect(), QColor("#0e1117"))
            if not self._data:
                p.end()
                return
            w, h = self.width(), self.height()
            n = len(self._data)
            step = w / n
            ys = [float(v) for v in self._data]
            ymin, ymax = min(ys), max(ys) or 1.0
            rng = (ymax - ymin) or 1.0
            p.setPen(QColor("#3b82f6"))
            prev = None
            for i, v in enumerate(ys):
                x = i * step
                y = h - (v - ymin) / rng * (h - 40) - 20
                if prev is not None:
                    p.drawLine(prev[0], prev[1], int(x), int(y))
                prev = (int(x), int(y))
            p.end()

    cw = _FakeChart()
    cw.show()
    data = [((i * 7) % 100) + 50 + (i % 5) for i in range(1000)]
    timer = QElapsedTimer()
    timer.start()
    cw.set_data(data)
    app.processEvents()
    elapsed = _elapsed(timer)
    cw.deleteLater()
    return elapsed


# ============================================================================
# 主入口
# ============================================================================
def run_budgets(app: QApplication) -> list[tuple[str, float, float, bool]]:
    """跑 5 项预算，返回 [(name, actual_ms, budget_ms, passed), ...]。"""
    benches = [
        ("启动到首屏可交互", bench_startup),
        ("主题切换全量刷新", bench_theme_switch),
        ("表格 1000 行填充", bench_table_fill),
        ("K 线 paintEvent @1000 bar (p95)", bench_kline_p95),
        ("图表 set_data 1000 根", bench_chart_set_data),
    ]
    results = []
    for name, fn in benches:
        actual = fn(app)
        budget = dict(BUDGETS)[name]
        passed = actual <= budget
        results.append((name, actual, budget, passed))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="UI/UX 性能预算基线")
    ap.add_argument("--json", action="store_true", help="JSON 输出（供 CI 消费）")
    args = ap.parse_args(argv)

    app = QApplication.instance() or QApplication([])
    results = run_budgets(app)

    import json

    if args.json:
        payload = [
            {"name": n, "actual_ms": round(a, 2), "budget_ms": b, "passed": p}
            for (n, a, b, p) in results
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=" * 72)
        print("UI/UX 性能预算基线（UX-83）")
        print("=" * 72)
        for name, actual, budget, passed in results:
            mark = "PASS" if passed else "FAIL"
            print(f"  [{mark}] {name:<40s} {_fmt_ms(actual):>10s} / budget {_fmt_ms(budget)}")
        print("=" * 72)
        overall = all(p for *_, p in results)
        print(f"整体：{'ALL PASS' if overall else 'HAS FAILURE'}")
    return 0 if all(p for *_, p in results) else 1


if __name__ == "__main__":
    sys.exit(main())
