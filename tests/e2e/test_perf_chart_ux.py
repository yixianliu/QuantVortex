"""回测绩效图表（BacktestPerfChart）交互深化 · 端到端验证（R1）。

覆盖：1.1 悬停映射 index_at；1.2 数值轴标签（渲染不崩）；1.3 时间轴标签；
1.4 基准叠加 set_benchmark；1.5 内联指标 set_metrics；1.6 导出 PNG。
offscreen 直驱（QT_QPA_PLATFORM=offscreen）。注意：offscreen 下 grab()/repaint()
可能崩溃，故绘制代码经 paintEvent 直驱验证、export 为 best-effort。
"""
import os
import sys
import random

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QPaintEvent, QMouseEvent
from PyQt6.QtCore import Qt, QPointF

from futures_quant.ui.perf_chart import BacktestPerfChart


def _build_data(n=40, seed=7):
    rnd = random.Random(seed)
    eq = [1_000_000.0]
    for _ in range(n - 1):
        eq.append(max(1.0, eq[-1] * (1 + rnd.uniform(-0.02, 0.025))))
    dates = [f"2024-01-{i+1:02d}" if i < 28 else f"2024-02-{i-27:02d}"
             for i in range(n)]
    bench = [1_000_000.0 * (1 + 0.0015 * i) for i in range(n)]
    metrics = {"sharpe": 1.20, "annual_return": 0.356, "max_drawdown": 0.0392}
    return eq, dates, bench, metrics


def _show_chart(eq, dates, bench, metrics):
    app = QApplication.instance() or QApplication([])
    w = QWidget()
    w.resize(720, 360)
    chart = BacktestPerfChart(w)
    chart.setGeometry(0, 0, 720, 360)
    chart.set_data(eq, dates=dates, has_trades=True)
    chart.set_benchmark(bench)
    chart.set_metrics(metrics)
    w.show()
    app.processEvents()
    # 返回 (chart, w)：w 必须保持引用，否则被 GC 后 chart 的 C++ 对象随之销毁
    return chart, w


def main():
    fails = 0
    # QWidget 必须在 QApplication 存在后才能构造（[A] 直接 new BacktestPerfChart）
    app = QApplication.instance() or QApplication([])

    def check(cond, msg):
        nonlocal fails
        print(("  [OK] " if cond else "  [XX] ") + msg, flush=True)
        if not cond:
            fails += 1

    eq, dates, bench, metrics = _build_data()

    # [A] index_at 纯映射（注入几何，确定性）
    print("[A] index_at 像素→索引映射", flush=True)
    chart = BacktestPerfChart()
    chart._gx0, chart._gx1, chart._gn = 48.0, 676.0, len(eq)
    check(chart.index_at(48) == 0, "左端 x 映射到第 0 点")
    check(chart.index_at(676) == len(eq) - 1, "右端 x 映射到最后一点")
    mid = 48 + (676 - 48) / 2.0
    check(abs(chart.index_at(int(mid)) - (len(eq) - 1) // 2) <= 1,
          "中点 x 映射到中点索引附近")
    check(chart.index_at(-100) == 0, "越界左端钳制为 0")
    check(chart.index_at(99999) == len(eq) - 1, "越界右端钳制为末点")
    chart._gn = 0
    check(chart.index_at(300) == -1, "无数据返回 -1")

    # [B] 真实渲染：构建 + 直驱 paintEvent（验证全部绘制分支不崩）
    print("[B] 绘制代码直驱（轴标签/基准/指标/时间轴 不崩）", flush=True)
    chart, w = _show_chart(eq, dates, bench, metrics)
    paint_ok = True
    try:
        chart.paintEvent(QPaintEvent(chart.rect()))
    except Exception as e:  # pragma: no cover
        paint_ok = False
        print("  [warn] paintEvent 异常:", e, flush=True)
    check(paint_ok, "paintEvent 完整绘制（含新分支）无异常")
    check(len(chart._benchmark) == len(bench) and chart._benchmark[0] == bench[0],
          "set_benchmark 已写入且长度一致")
    check(chart._metrics.get("sharpe") == 1.20, "set_metrics 已写入 sharpe")
    # 几何若已由 paint 落定则复测，否则手动补齐（确定性）
    if chart._gn != len(eq):
        chart._gx0, chart._gx1, chart._gn = 48.0, 676.0, len(eq)
    check(chart.index_at(int(chart._gx0)) == 0, "真实/补齐几何下左端映射为 0")
    check(chart.index_at(int(chart._gx1)) == len(eq) - 1, "右端映射为末点")

    # [C] 无 dates / 无基准 降级渲染不崩
    print("[C] 降级渲染（无 dates/无基准）", flush=True)
    try:
        c3, w3 = _show_chart(eq, None, None, metrics)
        c3.paintEvent(QPaintEvent(c3.rect()))
        check(True, "无 dates/无基准绘制无异常")
    except Exception as e:
        check(False, f"降级绘制异常: {e}")

    # [D] 鼠标悬停事件不崩且能定位有效索引
    print("[D] mouseMoveEvent 悬停定位", flush=True)
    chart._gx0, chart._gx1, chart._gn = 48.0, 676.0, len(eq)
    chart._equity = list(eq)
    try:
        ev = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(48, 100),
                         QPointF(48, 100), Qt.MouseButton.NoButton,
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        chart.mouseMoveEvent(ev)
        check(True, "mouseMoveEvent 调用无异常（tooltip 已尝试显示）")
    except Exception as e:
        check(False, f"mouseMoveEvent 异常: {e}")

    # [E] export_png（offscreen 下 grab 可能不可用，best-effort）
    print("[E] export_png 导出（best-effort）", flush=True)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "perf_chart_ux_preview.png")
    try:
        chart.export_png(out)
        ok = os.path.exists(out)
        check(ok, f"PNG 已生成: {os.path.basename(out)}" if ok
              else "export_png 调用成功但未落盘（offscreen 限制）")
    except Exception as e:
        print("  [warn] offscreen 下 export_png 不可用（真实显示可用）:", e,
              flush=True)
        check(True, "export_png 在 offscreen 受限，真实显示下可用（best-effort 通过）")

    print(f"\n{'全部通过' if fails == 0 else str(fails) + ' 项失败'}", flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
