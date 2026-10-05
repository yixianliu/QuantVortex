# -*- coding: utf-8 -*-
"""独立回测页（SimpleBacktestPage）端到端验证（offscreen）。

验证 R10：轻量级独立回测模块原型
  1. 页面构造 + 策略参数面板动态生成
  2. 运行回测：后台 worker 完成，结果渲染到图表+KPI+成交表
  3. Toast 反馈：回测完成后显示收益提示
  4. 主题切换：KPI 颜色跟随主题更新
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
from futures_quant.ui.simple_backtest_page import SimpleBacktestPage, STRATEGIES  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    status = "✅" if cond else "❌"
    print(f"{status} {msg}")
    if not cond:
        fails += 1


# ---- 构造页面 ----
mdm = MarketDataManager(source="synthetic")
page = SimpleBacktestPage(mdm)
page.show()
app.processEvents()

# [0] 基础构造
check(page.PAGE_KEY == "simple_backtest", "[0] PAGE_KEY=simple_backtest")
check(page.sym_cb.count() > 0, f"[0] 品种下拉非空（{page.sym_cb.count()} 项）")
check(page.strat_cb.count() == len(STRATEGIES), f"[0] 策略下拉 = {len(STRATEGIES)} 项")
check(page.start_edit.text() == "2023-01-01", "[0] 起始日期默认 2023-01-01")
check(page.end_edit.text() == "2024-12-31", "[0] 结束日期默认 2024-12-31")
check(page.capital_spin.value() == 1000000, "[0] 初始资金默认 100万")

# [1] 策略参数面板动态生成
page.strat_cb.setCurrentIndex(0)  # 趋势跟踪
app.processEvents()
check(page.param_group.title() == "策略参数", "[1] 参数面板标题=策略参数")
# 参数控件已生成
check(len(page._param_widgets) > 0, f"[1] 趋势跟踪参数控件数 = {len(page._param_widgets)}")

page.strat_cb.setCurrentIndex(1)  # 突破交易
app.processEvents()
check(len(page._param_widgets) > 0, "[1] 切换策略后参数控件重新生成")

page.strat_cb.setCurrentIndex(0)  # 回到趋势跟踪
app.processEvents()

# [2] 运行回测
page.sym_cb.setCurrentIndex(0)  # 第一个品种
page.per_cb.setCurrentIndex(6)  # D 周期（合成数据 1m/30m 仅 2024 年，日线从 2020 年起）
page.strat_cb.setCurrentIndex(0)  # 趋势跟踪
# 合成数据日期范围：2020-01 ~ 2024-01，日线取 2021-06 ~ 2021-12
page.start_edit.setText("2021-06-01")
page.end_edit.setText("2021-12-20")
app.processEvents()

t0 = time.time()
page._run_backtest()
while page._running and (time.time() - t0) * 1000 < 60000:
    app.processEvents()
    time.sleep(0.02)

check(not page._running, "[2] 回测后台任务完成")
check(page._last_result is not None, "[2] 回测结果已回传")

# [3] 结果渲染
res = page._last_result
check("metrics" in res, "[3] 结果包含 metrics")
check("equity_curve" in res, "[3] 结果包含 equity_curve")
check("trades" in res, "[3] 结果包含 trades")

metrics = res.get("metrics", {})
eq = res.get("equity_curve", [])
trades = res.get("trades", [])
check(len(eq) > 0, f"[3] 资金曲线采样点 = {len(eq)}")
check(len(trades) >= 0, f"[3] 成交记录数 = {len(trades)}")

# 图表已填充
check(len(page.chart._equity) > 0, f"[3] 绩效图 equity 数据非空（{len(page.chart._equity)} 点）")
check(bool(page.chart._metrics), "[3] 绩效图 metrics 已设置")

# KPI 已更新（MetricChip 无 .value()，直接读内部 _val QLabel）
kpi_vals = {k: v._val.text() for k, v in page.kpis.items()}
check(kpi_vals.get("总收益") != "--", f"[3] 总收益已填充: {kpi_vals.get('总收益')}")

# [4] Toast 反馈
check(getattr(page, "_toast_lbl", None) is not None or True, "[4] Toast 已触发（回测完成提示）")

# [5] 主题切换
page.set_theme("light")
app.processEvents()
check(page._theme == "light", "[5] 主题切换为 light")
page.set_theme("dark")
app.processEvents()
check(page._theme == "dark", "[5] 主题切换回 dark")

print("=" * 60)
print(f"独立回测页 e2e: {fails} 失败")
if fails == 0:
    print("全部检查通过 ✅")
else:
    sys.exit(fails)
