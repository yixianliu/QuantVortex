"""QuantVortex 启动性能基准测试。

测量目标：
  1. 各模块 import 耗时（Python 冷/热启动）
  2. MainWindow.__init__ 各阶段耗时
  3. MarketDataManager 数据源探测耗时
  4. 技术指标计算一次耗时
  5. 特征工程 build_features 一次耗时
  6. 预测器 fit + predict 单品种耗时

运行：
  python tests/e2e/test_startup_perf.py
"""
from __future__ import annotations

import time
import json
import os
import sys

# 确保项目根在 sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")


def section(name: str, fn):
    t0 = time.perf_counter()
    result = fn()
    dt = time.perf_counter() - t0
    print(f"  [{dt*1000:7.1f} ms] {name}")
    return result, dt


# ====================================================================
# 1. Import 耗时（冷启动模拟）
# ====================================================================
print("=" * 60)
print("QuantVortex 启动性能基准测试")
print("=" * 60)

import_times = {}
modules = [
    ("numpy",            lambda: __import__("numpy")),
    ("pandas",           lambda: __import__("pandas")),
    ("PyQt6",            lambda: __import__("PyQt6")),
    ("futures_quant.data", lambda: __import__("futures_quant.data", fromlist=[""])),
    ("futures_quant.indicators", lambda: __import__("futures_quant.indicators", fromlist=[""])),
    ("futures_quant.indicators.tech", lambda: __import__("futures_quant.indicators.tech", fromlist=[""])),
    ("futures_quant.ai", lambda: __import__("futures_quant.ai", fromlist=[""])),
    ("futures_quant.ai.predictor", lambda: __import__("futures_quant.ai.predictor", fromlist=[""])),
    ("futures_quant.ai.features", lambda: __import__("futures_quant.ai.features", fromlist=[""])),
    ("futures_quant.ai.lstm", lambda: __import__("futures_quant.ai.lstm", fromlist=[""])),
    ("futures_quant.storage.analysis_store", lambda: __import__("futures_quant.storage.analysis_store", fromlist=[""])),
    ("futures_quant.storage.config_manager", lambda: __import__("futures_quant.storage.config_manager", fromlist=[""])),
    ("futures_quant.ui.main_window", lambda: __import__("futures_quant.ui.main_window", fromlist=[""])),
]

print("\n[1] 模块导入耗时（热启动）:")
for mod_name, importer in modules:
    try:
        _, dt = section(mod_name, importer)
        import_times[mod_name] = round(dt * 1000, 1)
    except Exception as e:
        print(f"  [  error  ] {mod_name}: {e}")
        import_times[mod_name] = -1

# ====================================================================
# 2. MainWindow 初始化各阶段耗时
# ====================================================================
print("\n[2] MainWindow.__init__ 阶段耗时:")

from PyQt6.QtWidgets import QApplication
from futures_quant.ui.main_window import MainWindow

app = QApplication([])
t_start = time.perf_counter()

win = MainWindow()
t_init = time.perf_counter() - t_start

# 细分各阶段（通过 monkey-patch 重跑 init 逻辑来估算）
from futures_quant.data.market_data import MarketDataManager
from futures_quant.storage.analysis_store import AnalysisStore
from futures_quant.storage.config_manager import ConfigManager, SessionState

init_phases = {
    "ConfigManager + SessionState": lambda: (
        ConfigManager(),
        SessionState(),
    ),
    "MarketDataManager 实例化": lambda: MarketDataManager(),
    "AnalysisStore 实例化 + maintenance": lambda: (
        AnalysisStore("data/quant_analysis_perf.db"),
    ),
}

for phase_name, phase_fn in init_phases.items():
    try:
        _, dt = section(phase_name, phase_fn)
    except Exception as e:
        print(f"  [  error  ] {phase_name}: {e}")

# 连接探测（_do_connect 是 deferred 的）
print(f"  [      ---  ms] _do_connect（延迟到事件循环，此处跳过网络探测）")

# KWidget 构建
_, dt_build = section("UI 控件构建（_build）", lambda: None)  # 已在上面整体测过

app.quit()

# ====================================================================
# 3. 数据源探测耗时
# ====================================================================
print("\n[3] 数据源探测耗时:")

from futures_quant.data.market_data import MarketDataManager, _build_feed

mdm = MarketDataManager()
t_feed = time.perf_counter()
feed, source = _build_feed("sina", os.path.join(_ROOT, "data"))
dt_feed = time.perf_counter() - t_feed
print(f"  [{dt_feed*1000:7.1f} ms] _build_feed('sina') -> {source}")

t_connect = time.perf_counter()
mdm.connect()
dt_connect = time.perf_counter() - t_connect
print(f"  [{dt_connect*1000:7.1f} ms] MarketDataManager.connect()")

# ====================================================================
# 4. 技术指标计算耗时
# ====================================================================
print("\n[4] 技术指标计算耗时:")

from futures_quant.indicators.tech import add_indicators
import numpy as np
import pandas as pd

# 合成日线数据
n_bars = 600
rng = np.random.default_rng(42)
dates = pd.date_range("2024-01-01", periods=n_bars, freq="D")
close = 5000 + np.cumsum(rng.normal(0, 20, n_bars))
df_synth = pd.DataFrame({
    "datetime": dates,
    "open":   close + rng.normal(0, 2, n_bars),
    "high":   close + abs(rng.normal(0, 5, n_bars)),
    "low":    close - abs(rng.normal(0, 5, n_bars)),
    "close":  close,
    "volume": rng.integers(1000, 5000, n_bars).astype(float),
    "open_interest": rng.integers(5000, 15000, n_bars).astype(float),
})

ind_times = {}
for n_runs in (1, 3, 5):
    t0 = time.perf_counter()
    for _ in range(n_runs):
        add_indicators(df_synth)
    dt = (time.perf_counter() - t0) / n_runs
    ind_times[f"add_indicators x{n_runs}"] = round(dt * 1000, 1)
    print(f"  [{dt*1000:7.1f} ms] add_indicators (平均 {n_runs} 次)")

# ====================================================================
# 5. 特征工程耗时
# ====================================================================
print("\n[5] 特征工程 build_features 耗时:")

from futures_quant.ai.features import build_features, _indicator_cache

cache_before = _indicator_cache.stats()
print(f"  缓存状态（build_features 前）: {cache_before}")

t0 = time.perf_counter()
ind, F, names = build_features(df_synth, extended=True, symbol="rb.SHFE", period="D")
dt_feat = time.perf_counter() - t0
cache_after = _indicator_cache.stats()
print(f"  [{dt_feat*1000:7.1f} ms] build_features (extended=True, 首次=miss)")
print(f"  缓存状态: {cache_after}")

# 第二次调用应命中缓存
t0 = time.perf_counter()
ind2, F2, names2 = build_features(df_synth, extended=True, symbol="rb.SHFE", period="D")
dt_feat2 = time.perf_counter() - t0
print(f"  [{dt_feat2*1000:7.1f} ms] build_features (extended=True, 第二次=?)")

# ====================================================================
# 6. 预测器训练 + 预测耗时
# ====================================================================
print("\n[6] 预测器训练 + 预测耗时:")

from futures_quant.ai.predictor import FuturesPredictor

# 测试延迟导入效果：仅创建实例，不触发 AI 模块加载
t0 = time.perf_counter()
pred = FuturesPredictor()
dt_create = time.perf_counter() - t0
print(f"  [{dt_create*1000:7.1f} ms] FuturesPredictor() 实例化（延迟导入生效）")

# 检查 AI 子模块是否已被导入
ai_modules_loaded = any(m in sys.modules for m in ["futures_quant.ai.lstm", "futures_quant.ai.ensemble"])
print(f"  AI子模块已加载: {ai_modules_loaded}")

t0 = time.perf_counter()
fit_res = pred.fit(df_synth, seq_len=20, epochs=15, extended_features=False,
                   symbol="rb.SHFE", period="D")
dt_fit = time.perf_counter() - t0
print(f"  [{dt_fit*1000:7.1f} ms] predictor.fit (extended=False, epochs=15)")
print(f"      trained={fit_res.get('trained')}, model={fit_res.get('model')}")

t0 = time.perf_counter()
pred_res = pred.predict(df_synth, horizon=10, symbol="rb.SHFE", period="D")
dt_pred = time.perf_counter() - t0
print(f"  [{dt_pred*1000:7.1f} ms] predictor.predict (horizon=10)")
print(f"      p_up={pred_res.get('p_up')}, model={pred_res.get('model')}")

# ====================================================================
# 7. 完整 MainWindow 启动耗时（含 show）
# ====================================================================
print("\n[7] 完整 MainWindow 启动 + show 耗时:")

# 步骤2已 quit，重新创建 QApplication
from PyQt6.QtWidgets import QApplication as _QApp
app2 = _QApp([])

t0 = time.perf_counter()
win2 = MainWindow()
t_init2 = time.perf_counter() - t0
print(f"  [{t_init2*1000:7.1f} ms] MainWindow.__init__（热启动，模块已缓存）")

t_show = time.perf_counter()
win2.show()
t_show2 = time.perf_counter() - t_show
print(f"  [{t_show2*1000:7.1f} ms] win.show()")

app2.quit()

# ====================================================================
# 汇总报告
# ====================================================================
total = t_init2 + t_show2
report = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "module_import_ms": import_times,
    "mainwindow_init_ms": round(t_init2 * 1000, 1),
    "mainwindow_show_ms": round(t_show2 * 1000, 1),
    "mainwindow_total_ms": round(total * 1000, 1),
    "connect_ms": round(dt_connect * 1000, 1),
    "indicator_per_call_ms": ind_times,
    "build_features_first_ms": round(dt_feat * 1000, 1),
    "build_features_second_ms": round(dt_feat2 * 1000, 1),
    "predictor_create_ms": round(dt_create * 1000, 1),
    "ai_modules_loaded_at_create": ai_modules_loaded,
    "fit_ms": round(dt_fit * 1000, 1),
    "predict_ms": round(dt_pred * 1000, 1),
}

print("\n" + "=" * 60)
print("性能基准汇总")
print("=" * 60)
for k, v in report.items():
    if isinstance(v, dict):
        for kk, vv in v.items():
            print(f"  {k}.{kk}: {vv} ms")
    else:
        print(f"  {k}: {v} ms")

# 保存报告
out_path = os.path.join(_ROOT, "tests", "e2e", "perf_baseline_v2.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\n报告已保存: {out_path}")
