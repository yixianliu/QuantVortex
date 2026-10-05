"""QuantVortex 冷启动性能测试 - 模拟首次启动场景。"""
from __future__ import annotations

import time
import os
import sys
import subprocess
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def measure_cold_startup():
    """测量冷启动时间（模拟真实用户首次启动）。"""
    print("=" * 60)
    print("QuantVortex 冷启动性能测试")
    print("=" * 60)

    probe_lines = [
        "import time, sys, os, json",
        "",
        'sys.path.insert(0, r"{}")'.format(ROOT.replace("\\", "/")),
        'os.environ["QUANTVORTEX_NO_PERSIST"] = "1"',
        "",
        "t0 = time.perf_counter()",
        "results = {}",
        "",
        "# Phase 1: import 耗时",
        "t1 = time.perf_counter()",
        "import numpy",
        'results["import_numpy"] = round((time.perf_counter()-t1)*1000, 1)',
        "",
        "t1 = time.perf_counter()",
        "import pandas",
        'results["import_pandas"] = round((time.perf_counter()-t1)*1000, 1)',
        "",
        "t1 = time.perf_counter()",
        "from PyQt6.QtWidgets import QApplication",
        'results["import_pyqt6"] = round((time.perf_counter()-t1)*1000, 1)',
        "",
        "t1 = time.perf_counter()",
        "from futures_quant.ui.main_window import MainWindow",
        'results["import_main_window"] = round((time.perf_counter()-t1)*1000, 1)',
        "",
        "app = QApplication([])",
        "",
        "t1 = time.perf_counter()",
        "win = MainWindow()",
        'results["init_mainwindow"] = round((time.perf_counter()-t1)*1000, 1)',
        "",
        "t1 = time.perf_counter()",
        "win.show()",
        'results["show_window"] = round((time.perf_counter()-t1)*1000, 1)',
        "",
        "app.quit()",
        "",
        'results["total"] = round((time.perf_counter()-t0)*1000, 1)',
        "",
        "print(json.dumps(results, indent=2))",
    ]
    probe_code = "\n".join(probe_lines)

    tmp_script = os.path.join(os.path.dirname(__file__), "_cold_probe_tmp.py")
    with open(tmp_script, "w", encoding="utf-8") as f:
        f.write(probe_code)

    try:
        result = subprocess.run(
            [sys.executable, tmp_script],
            capture_output=True, text=True, timeout=120,
            cwd=ROOT
        )
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr[:800])
    finally:
        if os.path.exists(tmp_script):
            os.remove(tmp_script)


if __name__ == "__main__":
    measure_cold_startup()
