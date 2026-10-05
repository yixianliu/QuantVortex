# -*- coding: utf-8 -*-
"""回测中心「全自动自我学习」端到端验证（offscreen）。

1. 构造 BacktestCenterPage，模拟 showEvent 自动启动；
2. 同步驱动一代进化（不等 QTimer，直接调内部方法）；
3. 断言 KPI/状态灯/表格/日志已更新；
4. 验证盈利策略库 → latest_signal_for 供 KP预测融合。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from futures_quant.data.market_data import MarketDataManager  # noqa: E402
from futures_quant.ui.backtest_page import BacktestCenterPage  # noqa: E402
from futures_quant.strategy import auto_evolve as ae  # noqa: E402

mdm = MarketDataManager(source="synthetic")
page = BacktestCenterPage(mdm)
print("[1] 页面构造 OK, PAGE_KEY =", page.PAGE_KEY)

# —— 走真实路径：show() 触发 showEvent → 600ms 后自动启动 ——
import time

page.show()
app.processEvents()
assert page._auto_started, "showEvent 未置位自动启动标志"

deadline = 30_000
t0 = time.time()
while page._engine is None and (time.time() - t0) * 1000 < 8000:
    app.processEvents()
    time.sleep(0.02)
assert page._engine is not None, "引擎未自动创建（零操作启动失败）"
print("[2] 零操作自动启动 OK（showEvent → 定时器 → 引擎已创建）")

# 引擎创建后第一代已异步开跑；等第一份快照产出
t0 = time.time()
while page._last_snapshot is None and (time.time() - t0) * 1000 < deadline:
    app.processEvents()
    time.sleep(0.02)
assert page._last_snapshot is not None, "一代进化超时未完成（无快照）"
snap = page._last_snapshot
print(f"[3] 第一代进化完成 OK: symbol={snap['symbol']} "
      f"gen={snap['generation']} ranked={len(snap['ranked'])} "
      f"profitable_new={len(snap.get('new_profitable', []))}")

# —— 等排程的第二代自动跑完（验证自我迭代与排程链）——
gen0 = page._last_snapshot["generation"]
sym0 = page._last_snapshot["symbol"]
t0 = time.time()
while (time.time() - t0) * 1000 < deadline:
    app.processEvents()
    time.sleep(0.02)
    s = page._last_snapshot
    if s and (s["generation"] > gen0 or s["symbol"] != sym0):
        break
s = page._last_snapshot
assert s["generation"] > gen0 or s["symbol"] != sym0, "第二代未自动排程执行"
print(f"[4] 第二代自动进化 OK: 已评估 {page._engine.evaluated_total} 个策略")

# —— UI 断言 ——
assert page.pop_tbl.rowCount() > 0, "当代种群表为空"
assert page.log_list.count() > 0, "学习日志为空"
chip_gen = page._chips["generation"]._val.text()
assert chip_gen not in ("", "—"), "进化代数 KPI 未更新"
print(f"[5] UI 展示 OK: 种群表 {page.pop_tbl.rowCount()} 行, "
      f"日志 {page.log_list.count()} 条, 代数chip={chip_gen}, "
      f"盈利库表 {page.lib_tbl.rowCount()} 行")

# —— 盈利策略 → KP预测同步链路 ——
lib = ae.load_profitable()
print(f"[6] 盈利策略库落盘: {len(lib)} 条 @ {ae.STORE_PATH}")
if lib:
    sym = lib[0]["symbol"]
    df = mdm.get_bars(sym, "D", 300)
    sig = ae.latest_signal_for(sym, df)
    assert sig["n"] > 0, "latest_signal_for 未读到策略"
    assert -1.0 <= sig["bias"] <= 1.0
    print(f"[7] KP预测同步信号 OK: {sym} n={sig['n']} bias={sig['bias']:+.3f} "
          f"long={sig['long']} short={sig['short']}")
else:
    # 合成数据下可能暂无盈利策略，验证接口容错即可
    sig = ae.latest_signal_for("rb.SHFE", mdm.get_bars("rb.SHFE", "D", 300))
    assert sig["n"] == 0 and sig["bias"] == 0.0
    print("[7] 盈利库暂空，latest_signal_for 容错 OK（继续进化会自动补充）")

# —— 主题切换与关闭保护 ——
page.set_theme("light")
page.set_theme("dark")
page.close()
print("[8] 主题切换 / 关闭保护 OK")

print("=" * 60)
print("回测中心全自动自学习流程端到端验证：全部通过")
