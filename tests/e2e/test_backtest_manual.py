# -*- coding: utf-8 -*-
"""回测中心「手动回测」模式端到端验证（offscreen）。

验证 R2：手动/交割交易路径接入主流程
  1. 模式互斥：切到「手动回测」后自动进化暂停、面板展开；
  2. 手动回测：用 TradingEngine+BacktestBroker 跑用户自定义期货策略；
  3. 渲染复用：资金曲线(perf_chart) + 绩效指标卡(与预测同口径) 被填充；
  4. 持久化：结果写入 backtest_store.add_history（generation=MANUAL_GEN 哨兵）；
  5. 交割日强平：设置交割日后，引擎在到达交割日时强制平仓（日志出现「交割」）。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from futures_quant.data.market_data import MarketDataManager  # noqa: E402
from futures_quant.ui.backtest_page import BacktestCenterPage, MANUAL_GEN  # noqa: E402
from futures_quant.core.types import Offset  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    status = "✅" if cond else "❌"
    print(f"{status} {msg}")
    if not cond:
        fails += 1


# ---- 构造页面并等待自动启动（自动进化先就绪，手动模式复用同一引擎/行情）----
mdm = MarketDataManager(source="synthetic")
page = BacktestCenterPage(mdm)
page.show()
app.processEvents()

t0 = time.time()
while page._engine is None and (time.time() - t0) * 1000 < 8000:
    app.processEvents()
    time.sleep(0.02)
check(page._engine is not None, "[0] 引擎自动就绪（手动模式复用同一引擎/行情）")

# ---- [1] 模式互斥：切到手动 ----
page._rb_manual.setChecked(True)
app.processEvents()
check(page._manual_mode is True, "[1] 切到「手动回测」模式：_manual_mode=True")
check(page._manual_group.isVisible(), "[1] 手动回测面板已展开")
check(not page._rb_auto.isChecked(), "[1] 自动进化单选已取消")

# ---- [2] 选择品种与策略，运行手动回测 ----
idx = page._manual_sym_cb.findData("rb.SHFE")
check(idx >= 0, "[2] 品种下拉含 rb.SHFE")
page._manual_sym_cb.setCurrentIndex(idx if idx >= 0 else 0)
page._manual_strat_cb.setCurrentIndex(0)  # ma_cross（多空）
app.processEvents()

# 等待可能仍在运行的自动代际结束（手动模式下其 _on_gen_done 会早退，不会覆盖手动结果）
t0 = time.time()
while page._gen_running and (time.time() - t0) * 1000 < 15000:
    app.processEvents()
    time.sleep(0.02)

page._run_manual()
t0 = time.time()
while page._manual_running and (time.time() - t0) * 1000 < 30000:
    app.processEvents()
    time.sleep(0.02)
check(not page._manual_running, "[2] 手动回测后台任务完成")
check(page._last_manual is not None, "[2] 手动回测结果已回传（_last_manual）")

# ---- [3] 渲染复用：资金曲线 + 绩效指标卡 ----
eq = getattr(page.chart, "_equity", [])
check(len(eq) > 0, f"[3] 绩效图资金曲线已填充（{len(eq)} 个采样点）")
dd_txt = page._perf_chips["pf_dd"]._val.text()
check(dd_txt not in ("", "—", "--"), f"[3] 绩效指标卡已填充（最大回撤={dd_txt}）")
sh_txt = page._perf_chips["pf_sharpe"]._val.text()
print(f"    夏普={sh_txt} 年化={page._perf_chips['pf_annual']._val.text()} "
      f"卡玛={page._perf_chips['pf_calmar']._val.text()} "
      f"胜率={page._perf_chips['pf_wr']._val.text()} "
      f"盈亏比={page._perf_chips['pf_pf']._val.text()}")

# ---- [4] 持久化：写入历史记录表（MANUAL_GEN 哨兵）----
hist = page._bt_store.recent_history(50)
manual_rows = [r for r in hist
               if r.get("generation") == MANUAL_GEN and r.get("symbol") == "rb.SHFE"]
check(len(manual_rows) >= 1,
      f"[4] 手动回测已写入历史记录（generation={MANUAL_GEN} 哨兵，"
      f"命中 {len(manual_rows)} 条）")

# 自动进化应已暂停：等待一个自动代际间隔，确认无新快照覆盖手动结果
gen_before = page._engine.generation
time.sleep(0.1)
app.processEvents()
time.sleep(0.6)
app.processEvents()
check(page._last_snapshot is None or page._engine.generation == gen_before,
      "[4] 手动模式下自动进化已暂停（代数未推进）")

# ---- [5] 交割日强平：设置交割日，重跑并验证强制平仓 ----
page._futures_params["delivery_date"] = "2020-01-10"  # 远早于行情中段
mi = page._manual_strat_cb.findData("momentum")
page._manual_strat_cb.setCurrentIndex(mi if mi >= 0 else 0)
app.processEvents()

t0 = time.time()
while page._gen_running and (time.time() - t0) * 1000 < 15000:
    app.processEvents()
    time.sleep(0.02)

page._run_manual()
t0 = time.time()
while page._manual_running and (time.time() - t0) * 1000 < 30000:
    app.processEvents()
    time.sleep(0.02)
check(not page._manual_running, "[5] 交割日手动回测完成")

logger = page._last_manual_logger
check(logger is not None, "[5] 引擎日志器已挂载")
delivery_logged = any("交割" in m for _, m in (logger.msgs if logger else []))
check(delivery_logged, "[5] 到达交割日触发强制平仓（日志含「交割」告警）")

trades = page._last_manual["res"]["trades"]
close_trades = [t for t in trades if t.offset == Offset.CLOSE]
check(len(close_trades) > 0, f"[5] 回测产生平仓成交（{len(close_trades)} 笔平仓）")

# 还原：切回自动进化模式，确认可恢复
page._rb_auto.setChecked(True)
app.processEvents()
check(page._manual_mode is False, "[6] 切回自动进化：_manual_mode=False")
check(not page._manual_group.isVisible(), "[6] 手动面板已收起")

page.close()
print("=" * 60)
if fails == 0:
    print("回测中心「手动回测」模式端到端验证：全部通过")
else:
    print(f"回测中心「手动回测」模式端到端验证：{fails} 项失败")
    sys.exit(1)
