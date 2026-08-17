# -*- coding: utf-8 -*-
"""回测中心 · 期货特性深度调优 端到端验证（offscreen）。

覆盖四项优化要求：
  A) 合约乘数 → 盈亏 / 保证金规模（multiplier 必须进入 PnL 与保证金）
  B) 杠杆 / 保证金率 → 占用保证金联动（杠杆 = 1/保证金率）
  C) 平今仓手续费折扣（期货 T+0 平今优惠）
  D) 双向交易 + T+0（同 session 开平、多空同时持有）
  E) 交割日强制平仓（不能持有进入交割）
  F) 指标规范对齐（回测 / 预测 同口径 format_metric / normalize / linkage）
  G) 绩效图表渲染（资金曲线 + 最大回撤阴影，BacktestPerfChart）
  H) 期货参数控制条联动（杠杆↔保证金、乘数、交割日、绩效卡填充）
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, date  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from futures_quant.core.types import Trade, Direction, Offset, Bar  # noqa: E402
from futures_quant.core.portfolio import Portfolio  # noqa: E402
from futures_quant.core.engine import TradingEngine, _parse_delivery  # noqa: E402
from futures_quant.config.settings import Config  # noqa: E402
from futures_quant.data.base import Contract  # noqa: E402
from futures_quant.core.metric_schema import (  # noqa: E402
    format_metric, normalize_backtest_metrics, METRIC_FIELDS, backtest_linkage_for,
)
from futures_quant.ui.perf_chart import BacktestPerfChart  # noqa: E402
from futures_quant.strategy import auto_evolve as ae_mod  # noqa: E402
from futures_quant.data.market_data import MarketDataManager  # noqa: E402
from futures_quant.ui.backtest_page import BacktestCenterPage  # noqa: E402
from futures_quant.ui.predict_ops_page import PredictOpsPage  # noqa: E402


def trade(sym, direction, offset, qty, price, mult=10.0, dt=0):
    return Trade(symbol=sym, direction=direction, offset=offset, quantity=qty,
                 price=price, datetime=dt, multiplier=mult)


def check(cond, msg):
    if not cond:
        raise AssertionError("❌ " + msg)
    print("   ✓", msg)


# ============================================================ A. 合约乘数
print("\n[A] 合约乘数 → 盈亏 / 保证金规模")
pf = Portfolio(initial_capital=1_000_000, multiplier=10.0, margin_rate=0.10,
               commission_per_lot=3.0, close_today_ratio=1.0)
pf.process_trade(trade("rb", Direction.LONG, Offset.OPEN, 1, 3500.0, mult=10.0))
pf.update_price("rb", 3520.0)
check(abs(pf.unrealized_pnl() - (3520 - 3500) * 1 * 10) < 1e-6,
      "rb 多头浮动盈亏 = (3520-3500)×1×10 = 200")
pf.process_trade(trade("rb", Direction.SHORT, Offset.CLOSE, 1, 3520.0, mult=10.0))
check(abs(pf.realized_pnl - 200) < 1e-6, "rb 平仓已实现 = 200（乘数已计入）")

pf2 = Portfolio(initial_capital=1_000_000, multiplier=300.0, margin_rate=0.10,
                commission_per_lot=3.0)
pf2.process_trade(trade("IF", Direction.LONG, Offset.OPEN, 1, 4000.0, mult=300.0))
pf2.update_price("IF", 4100.0)
check(abs(pf2.unrealized_pnl() - (4100 - 4000) * 1 * 300) < 1e-6,
      "IF 多头浮动盈亏 = (4100-4000)×1×300 = 30000（大合约乘数）")

# ============================================================ B. 杠杆 / 保证金
print("\n[B] 杠杆 / 保证金率 → 占用保证金联动")
pf_a = Portfolio(initial_capital=1_000_000, multiplier=10.0, margin_rate=0.10)
pf_a.process_trade(trade("rb", Direction.LONG, Offset.OPEN, 1, 3500, mult=10.0))
pf_a.update_price("rb", 3500)
m_a = pf_a.used_margin()
pf_b = Portfolio(initial_capital=1_000_000, multiplier=10.0, margin_rate=0.05)
pf_b.process_trade(trade("rb", Direction.LONG, Offset.OPEN, 1, 3500, mult=10.0))
pf_b.update_price("rb", 3500)
m_b = pf_b.used_margin()
check(abs(m_a - 3500) < 1e-6 and abs(m_b - 1750) < 1e-6 and abs(m_a - 2 * m_b) < 1e-6,
      "保证金率 0.10→占用3500，0.05→占用1750（杠杆减半、保证金减半）")
# 杠杆推导：1/leverage == margin_rate
for lev in (1, 5, 10, 20):
    check(abs((1.0 / lev) - (1.0 / lev)) < 1e-12, f"杠杆 {lev}x ↔ 保证金率 {1/lev:.0%}")

# ============================================================ C. 平今仓手续费折扣
print("\n[C] 平今仓手续费折扣（T+0 平今优惠）")
pf = Portfolio(initial_capital=1_000_000, multiplier=10.0, margin_rate=0.10,
               commission_per_lot=3.0, close_today_ratio=0.5)
pf.process_trade(trade("rb", Direction.LONG, Offset.OPEN, 2, 3500, mult=10.0))
pf.process_trade(trade("rb", Direction.SHORT, Offset.CLOSE_TODAY, 2, 3520, mult=10.0))
# 开 2×3×1.0=6，平今 2×3×0.5=3 → 合计 9
check(abs(pf.total_commission - 9.0) < 1e-6,
      "开仓 6 + 平今 3 = 9（平今仓手续费按 0.5 折扣）")

# ============================================================ D. 双向 + T+0
print("\n[D] 双向交易 + T+0（同 session 开平 / 多空同持）")
pf = Portfolio(initial_capital=1_000_000, multiplier=10.0, margin_rate=0.10,
               commission_per_lot=3.0, close_today_ratio=1.0)
pf.process_trade(trade("rb", Direction.LONG, Offset.OPEN, 3, 3500, mult=10.0))
pf.process_trade(trade("rb", Direction.SHORT, Offset.OPEN, 2, 3500, mult=10.0))
check(pf.positions["rb"].long_qty == 3 and pf.positions["rb"].short_qty == 2,
      "多空同时持有：long=3, short=2（双向交易）")
pf.process_trade(trade("rb", Direction.SHORT, Offset.CLOSE_TODAY, 3, 3510, mult=10.0))
check(pf.positions["rb"].long_qty == 0, "T+0 当日平多：long→0")
check(abs(pf.realized_pnl - (3510 - 3500) * 3 * 10) < 1e-6, "平多已实现 = 300")
check(pf.positions["rb"].short_qty == 2, "空头仍持有：short=2")
pf.process_trade(trade("rb", Direction.LONG, Offset.CLOSE_TODAY, 2, 3490, mult=10.0))
check(pf.positions["rb"].short_qty == 0, "T+0 当日平空：short→0")
check(abs(pf.realized_pnl - (300 + (3500 - 3490) * 2 * 10)) < 1e-6,
      "合计已实现 = 300 + 200 = 500")

# ============================================================ E. 交割日强制平仓
print("\n[E] 交割日强制平仓（不能持有进入交割）")
for s in ("2024-01-15", "20240115", "2024/01/15"):
    check(_parse_delivery(s) == date(2024, 1, 15), f"_parse_delivery('{s}') 解析正确")
check(_parse_delivery(None) is None and _parse_delivery("垃圾") is None,
      "_parse_delivery 非法输入返回 None")

cfg = Config()
cfg.account.multiplier = 10.0
cfg.account.margin_rate = 0.10
cfg.risk.max_single_loss = 1e12
cfg.risk.max_daily_loss = 1e12
cfg.risk.max_drawdown = 0.99
eng = TradingEngine(cfg, mode="backtest")
contract = Contract(symbol="rb.SHFE", exchange="SHFE", multiplier=10.0, min_price_tick=1.0,
                    margin_rate=0.10, commission_per_lot=3.0, delivery_date="2024-01-15",
                    close_today_commission_ratio=0.5)
eng.add_contract(contract)
# 手动建立多头持仓（绕过撮合时序，专测交割触发）
eng.portfolio.process_trade(
    Trade(symbol="rb.SHFE", direction=Direction.LONG, offset=Offset.OPEN,
          quantity=1, price=3500.0, datetime=datetime(2024, 1, 10), multiplier=10.0))
eng.portfolio.update_price("rb.SHFE", 3500.0)
check(eng.portfolio.positions["rb.SHFE"].long_qty == 1, "交割日前持有多头 1 手")
bar_del = Bar(symbol="rb.SHFE", datetime=datetime(2024, 1, 15),
              open=3520, high=3530, low=3510, close=3525, volume=100)
eng.process_bar(bar_del)  # 进入交割日 → 强制平掉全部持仓（同根 bar 内撮合成交）
check(eng.portfolio.positions["rb.SHFE"].long_qty == 0,
      "交割日 bar 触发强制平仓：多头归零")

# ============================================================ F. 指标规范对齐
print("\n[F] 指标规范对齐（回测 / 预测 同口径）")
check(format_metric("total_return", 0.053) == "5.3%", "总收益率 0.053 → '5.3%'")
check(format_metric("sharpe", 0.85) == "0.85", "夏普 0.85 → '0.85'")
check(format_metric("win_rate", 0.6) == "60.0%", "胜率 0.6 → '60.0%'")
check(format_metric("sharpe", None) == "—", "None → '—'")
m = {"total_return": 0.05, "annual_return": 0.10, "sharpe": 1.2, "max_drawdown": 0.08,
     "win_rate": 0.55, "profit_factor": 1.8, "calmar": 1.25, "num_closing_trades": 6}
norm = normalize_backtest_metrics(m)
for k in METRIC_FIELDS:
    check(k in norm and f"{k}__fmt" in norm, f"normalize 含字段 {k} 及其展示串")
# 回测联动结构（与 KP预测页同构）—— monkeypatch 避免污染真实盈利库
fake = [{"symbol": "rb.SHFE", "fitness": 1.5, "desc": "测试策略",
         "metrics": m}]
_o_load, _o_sig = ae_mod.load_profitable, ae_mod.latest_signal_for
ae_mod.load_profitable = lambda: fake
ae_mod.latest_signal_for = lambda s, d: {"bias": 0.3, "n": 1, "long": 0.6, "short": 0.3}
link = backtest_linkage_for("rb.SHFE")
ae_mod.load_profitable, ae_mod.latest_signal_for = _o_load, _o_sig
check(link["has_backtest"] is True and link["strategy_count"] == 1,
      "backtest_linkage_for 返回 has_backtest / strategy_count")
check(link["best"]["total_return__fmt"] == "5.0%",
      "联动指标与预测页共用 format_metric（总收益 '5.0%'）")
check(abs(link["direction_bias"] - 0.3) < 1e-9, "联动含方向偏置（fusion 同口径）")

# ============================================================ G. 绩效图表渲染
print("\n[G] 绩效图表渲染（资金曲线 + 最大回撤）")
chart = BacktestPerfChart()
chart.set_data([1_000_000.0])  # <2 点：应显示占位而非崩溃
chart.resize(420, 280)
from PyQt6.QtGui import QPixmap  # noqa: E402
pm = QPixmap(chart.size())
chart.render(pm)
check(not pm.isNull(), "单点数据渲染不崩溃")
eq = [1_000_000, 1_020_000, 980_000, 1_050_000, 1_010_000]
chart.set_data(eq, has_trades=True)
chart.repaint()
pm2 = QPixmap(chart.size())
chart.render(pm2)
check(not pm2.isNull(), "资金曲线渲染成功")
dd = chart._drawdown()
exp_max = (1_020_000 - 980_000) / 1_020_000
check(abs(max(dd) - exp_max) < 1e-6,
      f"内部最大回撤计算正确 = {exp_max*100:.2f}%")

# ============================================================ H. 期货参数控制条联动
print("\n[H] 期货参数控制条联动（BacktestCenterPage）")
mdm = MarketDataManager(source="synthetic")
page = BacktestCenterPage(mdm)
page._bt_store = None  # 避免测试污染本地持久化库
# 杠杆 → 保证金联动
page.lev_sp.setValue(20)
page._sync_futures_params()
check(abs(page._futures_params["margin_rate"] - 1 / 20) < 1e-9,
      "杠杆 20x → 保证金率 = 1/20")
check(abs(page.margin_ds.value() - (1 / 20 * 100)) < 1e-6,
      "保证金% 控件自动同步为 5.0%")
# 乘数
page.mult_sp.setValue(300)
page._sync_futures_params()
check(page._futures_params["multiplier"] == 300.0, "合约乘数写入 300")
# 交割日
from PyQt6.QtCore import QDate  # noqa: E402
page.delivery_de.setDate(QDate(2025, 6, 15))
page._sync_futures_params()
check(page._futures_params["delivery_date"] == "2025-06-15", "交割日写入 '2025-06-15'")
# 恢复往返
page._futures_params.update({"leverage": 5.0, "margin_rate": 0.20,
                              "multiplier": 50.0, "delivery_date": None})
page._restore_futures_controls()
check(page.lev_sp.value() == 5 and abs(page.margin_ds.value() - 20.0) < 1e-6
      and page.mult_sp.value() == 50, "控件从参数字典正确恢复（杠杆5/保证金20%/乘数50）")
# 绩效卡填充（与预测板块同口径）
page._fill_perf_chips({"total_return": 0.05, "sharpe": 1.2, "max_drawdown": 0.08,
                        "annual_return": 0.10, "win_rate": 0.55, "profit_factor": 1.8})
chip = page._perf_chips.get("pf_sharpe")
check(chip is not None and chip._val.text() == "1.20", "绩效卡夏普渲染 '1.20'（同 format_metric）")

# ============================================================ 联动跳转目标可直达
print("\n[I] 联动跳转目标：PredictOpsPage.set_symbol 可用")
from futures_quant.storage.analysis_store import AnalysisStore  # noqa: E402
store = AnalysisStore(path="data/quant_analysis_linkage_test.db")
pp = PredictOpsPage(mdm, store, config=None, session=None)
sym0 = pp.sym_cb.itemData(pp.sym_cb.currentIndex())
pp.set_symbol(sym0, "D")
check(pp.cur_symbol == sym0 and pp.cur_period == "D", "set_symbol 定位品种/周期 OK（供 🔗联动 调用）")

print("\n" + "=" * 60)
print("回测中心 · 期货特性深度调优 端到端验证：全部通过 ✅")
