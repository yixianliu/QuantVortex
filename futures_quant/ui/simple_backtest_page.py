"""轻量级独立回测页（R10 原型）。

复用现有 Backtester + BacktestPerfChart 架构，提供用户可配置的单策略回测：
    1. 选择合约 + 周期 + 策略类型
    2. 调整策略参数（动态生成参数控件）
    3. 设定起止日期 + 初始资金
    4. 后台运行回测
    5. 展示资金曲线 + 绩效指标 + 成交摘要

数据源：复用 mdm.feed（synthetic/sina/akshare/csv），支持离线回测。
仅依赖 PyQt6 / numpy / pandas，无第三方依赖。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QGroupBox,
    QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox,
)

from .pages import BasePage, Worker, symbol_code, symbol_label, PERIODS, PERIOD_LABEL
from .widgets import PageHeader, SectionHeader, MetricChip, pal, prepare_table, ToolBar
from ..backtest.backtester import Backtester


# ---------------------------------------------------------------------------
# 策略注册表（与 backtest_page.py 保持一致）
# ---------------------------------------------------------------------------
STRATEGIES = [
    ("趋势跟踪", "TrendFollowing"),
    ("突破交易", "Breakout"),
    ("网格交易", "Grid"),
    ("马丁策略", "Martingale"),
    ("均值回归", "MeanReversion"),
]

# 参数控件定义：(key, label, default, spin_type)
# spin_type: "int" | "float" | "date"
PARAM_DEFS: Dict[str, list] = {
    "TrendFollowing": [
        ("fast", "快线周期", 10, "int"),
        ("slow", "慢线周期", 30, "int"),
        ("atr_period", "ATR周期", 14, "int"),
        ("stop_mult", "止损倍数", 2.0, "float"),
        ("lots", "手数", 1, "int"),
    ],
    "Breakout": [
        ("period", "突破周期", 20, "int"),
        ("atr_period", "ATR周期", 14, "int"),
        ("stop_mult", "止损倍数", 2.0, "float"),
        ("lots", "手数", 1, "int"),
    ],
    "Grid": [
        ("grid_step", "网格间距", 20.0, "float"),
        ("grid_count", "网格层数", 10, "int"),
        ("lots_per_grid", "每层手数", 1, "int"),
    ],
    "Martingale": [
        ("base_qty", "基础手数", 1, "int"),
        ("multiplier", "倍投倍数", 2, "int"),
        ("max_layers", "最大层数", 4, "int"),
        ("rsi_period", "RSI周期", 14, "int"),
        ("oversold", "超卖阈值", 30, "int"),
        ("overbought", "超买阈值", 55, "int"),
        ("take_profit", "止盈比例", 0.01, "float"),
        ("stop_loss", "止损比例", 0.02, "float"),
    ],
    "MeanReversion": [
        ("period", "周期", 20, "int"),
        ("num_std", "标准差倍数", 2.0, "float"),
        ("lots", "手数", 1, "int"),
    ],
}


class SimpleBacktestPage(BasePage):
    """轻量级独立回测页（R10 原型）。"""

    def __init__(self, mdm, store=None, config=None, session=None):
        """初始化相关对象。
        
            参数:
                mdm
                store
                config
                session"""
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "simple_backtest"
        self._running = False
        self._last_result = None
        self._param_widgets: dict = {}
        self._build()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """构建相关对象。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "独立回测",
            "选择合约 · 配置策略 · 运行回测 · 查看绩效"))

        # ---- 控制区 ----
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("合约:"))
        self.sym_cb = QComboBox()
        self.sym_cb.setMinimumWidth(140)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        ctl.addWidget(self.sym_cb)

        ctl.addWidget(QLabel("周期:"))
        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        ctl.addWidget(self.per_cb)

        ctl.addWidget(QLabel("策略:"))
        self.strat_cb = QComboBox()
        for name, cls_name in STRATEGIES:
            self.strat_cb.addItem(name, cls_name)
        self.strat_cb.currentIndexChanged.connect(self._on_strat_change)
        ctl.addWidget(self.strat_cb)

        ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        # ---- 参数区 ----
        self.param_group = QGroupBox("策略参数")
        self.param_form = QFormLayout(self.param_group)
        self.param_form.setSpacing(6)
        root.addWidget(self.param_group)

        # ---- 日期 + 资金区 ----
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("起始日期:"))
        self.start_edit = QLineEdit("2023-01-01")
        date_row.addWidget(self.start_edit)
        date_row.addWidget(QLabel("结束日期:"))
        self.end_edit = QLineEdit("2024-12-31")
        date_row.addWidget(self.end_edit)
        date_row.addWidget(QLabel("初始资金:"))
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(10000, 10000000)
        self.capital_spin.setValue(1000000)
        self.capital_spin.setSuffix(" 元")
        date_row.addWidget(self.capital_spin)
        date_row.addStretch(1)
        root.addLayout(date_row)

        # ---- 运行按钮 ----
        run_row = QHBoxLayout()
        self.run_btn = QPushButton("🚀 开始回测")
        self.run_btn.setObjectName("primary")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self._run_backtest)
        run_row.addWidget(self.run_btn)
        run_row.addStretch(1)
        root.addLayout(run_row)

        # ---- 绩效区 ----
        self.kpi_row = QHBoxLayout()
        self.kpis: dict[str, MetricChip] = {}
        for label in ("总收益", "年化收益", "最大回撤", "夏普比率", "胜率", "盈亏比"):
            chip = MetricChip(label, "--")
            self.kpis[label] = chip
            self.kpi_row.addWidget(chip, 1)
        root.addLayout(self.kpi_row)

        # ---- 图表区 ----
        from .perf_chart import BacktestPerfChart
        self.chart = BacktestPerfChart()
        self.chart.set_title("资金曲线与最大回撤")
        root.addWidget(self.chart, 2)

        # ---- 成交摘要表 ----
        self.trade_tbl = QTableWidget(0, 4)
        self.trade_tbl.setHorizontalHeaderLabels(["日期", "方向", "手数", "盈亏(元)"])
        self.trade_tbl.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.trade_tbl, 1)

        self._on_strat_change(0)

    def _on_strat_change(self, idx: int) -> None:
        """根据选中的策略动态生成参数控件。"""
        cls_name = self.strat_cb.currentData()
        # 清空旧控件
        for i in reversed(range(self.param_form.count())):
            w = self.param_form.itemAt(i).widget()
            if w is not None:
                w.deleteLater()
        self._param_widgets.clear()

        defs = PARAM_DEFS.get(cls_name, [])
        p = pal()
        for key, label, default, spin_type in defs:
            if spin_type == "int":
                spin = QSpinBox()
                spin.setRange(1, 1000)
                spin.setValue(int(default))
            elif spin_type == "float":
                spin = QDoubleSpinBox()
                spin.setDecimals(2)
                spin.setRange(0.01, 100.0)
                spin.setValue(float(default))
            else:
                spin = QLineEdit(str(default))
            self._param_widgets[key] = spin
            self.param_form.addRow(f"{label} ({key}):", spin)

    def _collect_params(self) -> dict:
        """收集当前参数值。"""
        params = {}
        for key, widget in self._param_widgets.items():
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                params[key] = widget.value()
            else:
                try:
                    params[key] = float(widget.text())
                except ValueError:
                    params[key] = widget.text()
        return params

    # ------------------------------------------------------------------
    # 回测执行
    # ------------------------------------------------------------------
    def _run_backtest(self) -> None:
        """运行回测。"""
        if self._running:
            return
        sym = self.sym_cb.currentData()
        per = self.per_cb.currentData()
        strat_cls_name = self.strat_cb.currentData()
        start = self.start_edit.text().strip()
        end = self.end_edit.text().strip()
        capital = self.capital_spin.value()

        if not sym or not start or not end:
            self._toast("请填写完整的合约、日期信息")
            return

        self._running = True
        self.run_btn.setEnabled(False)
        self.run_btn.setText("回测中…")

        def work():
            """处理work。"""
            from ..strategy.trend_following import TrendFollowing
            from ..strategy.breakout import Breakout
            from ..strategy.grid import Grid
            from ..strategy.martingale import Martingale
            from ..strategy.mean_reversion import MeanReversion
            from ..config.settings import Config
            from ..data.base import Contract
            strat_map = {
                "TrendFollowing": TrendFollowing,
                "Breakout": Breakout,
                "Grid": Grid,
                "Martingale": Martingale,
                "MeanReversion": MeanReversion,
            }
            strat_cls = strat_map.get(strat_cls_name)
            if strat_cls is None:
                raise ValueError(f"未知策略: {strat_cls_name}")

            params = self._collect_params()
            cfg = Config()
            bt = Backtester(cfg, self.mdm.feed)
            bt.add_contract(Contract(symbol=sym, exchange="TEST"))
            bt.add_strategy(strat_cls(sym, params))
            return bt.run(sym, start, end, per, warmup=60)

        def done(res: dict) -> None:
            """处理done。
            
                参数:
                    res: dict"""
            self._running = False
            self.run_btn.setEnabled(True)
            self.run_btn.setText("🚀 开始回测")
            self._last_result = res
            self._render_result(res)

        def err(e: str) -> None:
            """处理err。
            
                参数:
                    e: str"""
            self._running = False
            self.run_btn.setEnabled(True)
            self.run_btn.setText("🚀 开始回测")
            self._toast(f"❌ 回测失败: {e}", level="error")

        self._run_worker(work, done, on_err=err)

    def _render_result(self, res: dict) -> None:
        """渲染回测结果到图表 + KPI + 成交表。"""
        metrics = res.get("metrics", {})
        equity = res.get("equity_curve", [])
        trades = res.get("trades", [])

        # 资金曲线
        if equity:
            eq_vals = [float(e[1]) for e in equity]
            dates = [str(e[0])[:10] for e in equity]
            self.chart.set_data(eq_vals, dates=dates, has_trades=bool(trades))
            self.chart.set_metrics(metrics)
        else:
            self.chart.clear()

        # KPI 卡
        p = pal()
        total_ret = metrics.get("total_return", 0.0)
        ann_ret = metrics.get("annual_return", 0.0)
        max_dd = metrics.get("max_drawdown", 0.0)
        sharpe = metrics.get("sharpe", None)
        win_rate = metrics.get("win_rate", 0.0)
        profit_factor = metrics.get("profit_factor", 0.0)

        self.kpis["总收益"].set_value(f"{total_ret*100:+.2f}%", p["up"] if total_ret >= 0 else p["down"])
        self.kpis["年化收益"].set_value(f"{ann_ret*100:+.2f}%" if ann_ret is not None else "--")
        self.kpis["最大回撤"].set_value(f"{max_dd*100:.2f}%", p["down"])
        self.kpis["夏普比率"].set_value(f"{sharpe:.2f}" if sharpe is not None else "--")
        self.kpis["胜率"].set_value(f"{win_rate*100:.1f}%", p["text"])
        self.kpis["盈亏比"].set_value(f"{profit_factor:.2f}" if profit_factor is not None else "--")

        # 成交摘要（取最近 50 笔）
        self.trade_tbl.setRowCount(min(len(trades), 50))
        for i, t in enumerate(trades[-50:]):
            self.trade_tbl.setItem(i, 0, QTableWidgetItem(str(t.datetime)[:19]))
            self.trade_tbl.setItem(i, 1, QTableWidgetItem(t.direction.value))
            self.trade_tbl.setItem(i, 2, QTableWidgetItem(str(t.quantity)))
            pnl_item = QTableWidgetItem(f"{t.pnl:.2f}")
            pnl_color = p["up"] if t.pnl >= 0 else p["down"]
            pnl_item.setForeground(QColor(pnl_color))
            self.trade_tbl.setItem(i, 3, pnl_item)
        prepare_table(self.trade_tbl)

        # Toast 提示
        if total_ret > 0:
            self._toast(f"✅ 回测完成：总收益 {total_ret*100:+.2f}%，夏普 {sharpe or 0:.2f}")
        elif total_ret < 0:
            self._toast(f"⚠️ 回测完成：总收益 {total_ret*100:+.2f}%（亏损）")
        else:
            self._toast("⚠️ 回测完成：无成交记录")

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        super().set_theme(t)
        # 刷新 KPI 颜色
        p = pal()
        if self._last_result:
            self._render_result(self._last_result)
