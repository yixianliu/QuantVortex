"""UX-67: 首屏性能基准测试。

测量启动到首帧的时间，目标 ≤ 800ms。

用法:
    python -m futures_quant.tests.startup_bench
"""
from __future__ import annotations

import os
import sys
import time
import json
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QUANTVORTEX_NO_PERSIST"] = "1"


def measure_startup() -> dict:
    """测量单次启动耗时，返回各阶段耗时。"""
    timings = {}

    # 阶段 1: Python 解释器 + 模块导入
    t0 = time.perf_counter()
    import futures_quant
    t1 = time.perf_counter()
    timings["import_futures_quant"] = round((t1 - t0) * 1000, 1)

    # 阶段 2: QApplication 初始化
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    t2 = time.perf_counter()
    timings["qapplication_init"] = round((t2 - t1) * 1000, 1)

    # 阶段 3: MainWindow 构造（使用 main() 函数中的完整初始化流程）
    from futures_quant.ui.main_window import main as ui_main
    # 我们需要测量 main() 中 MainWindow 构造的时间
    # 但由于 main() 会调用 app.exec()，我们需要手动模拟
    from futures_quant.ui.main_window import MainWindow
    from futures_quant.ui.splash import Splash

    # 创建 splash
    splash = Splash(app)
    splash.step("加载字体...")

    # 加载字体
    from PyQt6.QtGui import QFont, QFontDatabase
    from futures_quant.ui.main_window import get_font_paths
    t3 = time.perf_counter()
    chosen_family = ""
    for fp in get_font_paths():
        fid = QFontDatabase.addApplicationFont(fp)
        if fid >= 0:
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                chosen_family = fams[0]
                break
    if chosen_family:
        from futures_quant.ui.responsive_layout import get_layout_manager
        mgr = get_layout_manager()
        base_size = mgr.font_size(10)
        app.setFont(QFont(chosen_family, base_size))
    else:
        base_size = 10
        app.setFont(QFont("", base_size))
    t4 = time.perf_counter()
    timings["font_loading"] = round((t4 - t3) * 1000, 1)

    splash.step("初始化主窗口...")
    t5 = time.perf_counter()
    win = MainWindow()
    t6 = time.perf_counter()
    timings["mainwindow_init"] = round((t6 - t5) * 1000, 1)

    # 阶段 4: 窗口显示
    if getattr(win, "_want_max", True):
        win.showMaximized()
    else:
        win.show()
    splash.finish(win)
    win.raise_()
    win.activateWindow()
    t7 = time.perf_counter()
    timings["window_show"] = round((t7 - t6) * 1000, 1)

    # 总计
    timings["total"] = round((t7 - t0) * 1000, 1)

    # 清理
    win.close()
    app.quit()

    return timings


def run_benchmark(n_runs: int = 3) -> dict:
    """运行多次基准测试，返回统计结果。"""
    results = []
    for i in range(n_runs):
        print(f"运行 {i + 1}/{n_runs}...")
        timings = measure_startup()
        results.append(timings)
        print(f"  总耗时: {timings['total']}ms")

    # 计算统计
    totals = [r["total"] for r in results]
    avg = round(sum(totals) / len(totals), 1)
    min_val = min(totals)
    max_val = max(totals)

    return {
        "runs": n_runs,
        "avg_ms": avg,
        "min_ms": min_val,
        "max_ms": max_val,
        "target_ms": 800,
        "passed": avg <= 800,
        "details": results,
    }


def main() -> None:
    """运行基准测试并输出结果。"""
    print("=" * 60)
    print("QuantVortex 首屏性能基准测试 (UX-67)")
    print("目标: 启动到首帧 ≤ 800ms")
    print("=" * 60)
    print()

    result = run_benchmark(n_runs=3)

    print()
    print("=" * 60)
    print("测试结果")
    print("=" * 60)
    print(f"  平均耗时: {result['avg_ms']}ms")
    print(f"  最小耗时: {result['min_ms']}ms")
    print(f"  最大耗时: {result['max_ms']}ms")
    print(f"  目标:     {result['target_ms']}ms")
    print(f"  状态:     {'✅ PASS' if result['passed'] else '❌ FAIL'}")
    print()

    if result["passed"]:
        print("🎉 首屏性能达标！")
    else:
        print("⚠️  首屏性能未达标，需要进一步优化。")

    # 输出详细结果
    print()
    print("各阶段耗时详情:")
    print("-" * 60)
    if result["details"]:
        last = result["details"][-1]
        for stage, ms in last.items():
            if stage != "total":
                print(f"  {stage:30s}: {ms:8.1f}ms")
        print(f"  {'total':30s}: {last['total']:8.1f}ms")

    # 保存基线
    baseline_path = Path(HERE) / "startup_baseline.json"
    baseline_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n基线已保存: {baseline_path}")


if __name__ == "__main__":
    main()
