"""轻量级独立回测页（R10 原型）。

复用现有 Backtester + BacktestPerfChart 架构，提供用户可配置的单策略回测：
    1. 选择合约 + 周期 + 策略类型
    2. 调整策略参数（动态生成参数控件）
    3. 设定起止日期 + 初始资金
    4. 后台运行回测
    5. 展示资金曲线 + 绩效指标 + 成交摘要

数据源：复用 mdm.feed（synthetic/sina/akshare/csv），支持离线回测。
仅依赖 PyQt6 / numpy / pandas，无第三方依赖。

M1-08（2026-10-01）：表单校验加固
    ① 起止日期 QLineEdit → QDateEdit(calendarPopup=True)，杜绝手输 2026-13-99；
    ② 起 < 止 校验 + inline 红色提示（QLabel，不弹 MessageBox）；
    ③ work() 的 bare `except Exception` → `logger.exception` + 分类提示（日期/数据/策略）；
    ④ set_theme 刷新 KPI 时保留原行为。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QGroupBox,
    QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox, QDateEdit,
)

logger = logging.getLogger(__name__)

from .pages import BasePage, Worker, symbol_code, symbol_label, PERIODS, PERIOD_LABEL
from .widgets import PageHeader, SectionHeader, StatCard, pal, prepare_table, ToolBar
from .states import DataGrid   # M4-08：统一表格能力（排序 / 右键菜单 / 列显隐 / 空态）
from ..backtest.backtester import Backtester
from ..app.service_locator import request
from ..app.backtest_service import BacktestService
from ..strategy.arbitrage import (
    CalendarSpread, CrossInstrumentSpread, SpotFuturesBasis,
)


# ---------------------------------------------------------------------------
# 策略注册表（与 backtest_page.py 保持一致）
# ---------------------------------------------------------------------------
STRATEGIES = [
    ("趋势跟踪", "TrendFollowing"),
    ("突破交易", "Breakout"),
    ("网格交易", "Grid"),
    ("马丁策略", "Martingale"),
    ("均值回归", "MeanReversion"),
    ("跨期套利", "CalendarSpread"),
    ("跨品种套利", "CrossInstrumentSpread"),
    ("期现套利", "SpotFuturesBasis"),
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


# 默认起止日期：2023-01-01 / 2024-12-31（与旧 QLineEdit 字面量一致）
DEFAULT_START_DATE = QDate(2023, 1, 1)
DEFAULT_END_DATE = QDate(2024, 12, 31)
# QDateEdit 允许的最小/最大年份：1990-01-01 至 2100-12-31（覆盖真实合约历史与展期）
DATE_MIN = QDate(1990, 1, 1)
DATE_MAX = QDate(2100, 12, 31)


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

        # ---- 日期 + 资金区（M1-08：QLineEdit → QDateEdit）----
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("起始日期:"))
        self.start_edit = QDateEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setMinimumDate(DATE_MIN)
        self.start_edit.setMaximumDate(DATE_MAX)
        self.start_edit.setDate(DEFAULT_START_DATE)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.start_edit)
        date_row.addWidget(QLabel("结束日期:"))
        self.end_edit = QDateEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setMinimumDate(DATE_MIN)
        self.end_edit.setMaximumDate(DATE_MAX)
        self.end_edit.setDate(DEFAULT_END_DATE)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.end_edit)
        date_row.addWidget(QLabel("初始资金:"))
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(10000, 10000000)
        self.capital_spin.setValue(1000000)
        self.capital_spin.setSuffix(" 元")
        date_row.addWidget(self.capital_spin)
        date_row.addStretch(1)
        root.addLayout(date_row)

        # M1-08: inline 校验提示（默认隐藏，仅在起>止时显示红色）
        self._validation_hint = QLabel("")
        self._validation_hint.setStyleSheet("color:#ef4444;font-size:12px;padding:2px 4px;")
        self._validation_hint.hide()
        root.addWidget(self._validation_hint)

        # 监听日期变化以更新校验状态
        self.start_edit.dateChanged.connect(self._on_date_change)
        self.end_edit.dateChanged.connect(self._on_date_change)

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
        self.kpis: dict[str, StatCard] = {}
        for label in ("总收益", "年化收益", "最大回撤", "夏普比率", "胜率", "盈亏比"):
            chip = StatCard(label, "--", theme=self._theme)
            self.kpis[label] = chip
            self.kpi_row.addWidget(chip, 1)
        root.addLayout(self.kpi_row)

        # ---- 图表区 ----
        from .perf_chart import BacktestPerfChart
        self.chart = BacktestPerfChart()
        self.chart.set_title("资金曲线与最大回撤")
        root.addWidget(self.chart, 2)

        # ---- 成交摘要表 ----
        self.trade_tbl = DataGrid(0, 4)
        self.trade_tbl.setHorizontalHeaderLabels(["日期", "方向", "手数", "盈亏(元)"])
        self.trade_tbl.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.trade_tbl, 1)

        self._on_strat_change(0)
        # 初始校验（构造完成后再跑一次，确保 UI 一致）
        self._on_date_change(DEFAULT_START_DATE)

    # ------------------------------------------------------------------
    # M1-08 表单校验
    # ------------------------------------------------------------------
    def _on_date_change(self, _d: QDate) -> None:
        """日期控件任一变化时刷新校验提示与运行按钮状态。"""
        err = self._validate_dates()
        if err:
            self._validation_hint.setText(f"⚠️ {err}")
            self._validation_hint.show()
            self._validation_hint.setStyleSheet("color:#ef4444;font-size:12px;padding:2px 4px;")
        else:
            self._validation_hint.hide()
        self._update_run_button()

    def _validate_dates(self) -> str:
        """返回错误描述；空字符串表示通过。"""
        start = self.start_edit.date()
        end = self.end_edit.date()
        if not start.isValid() or not end.isValid():
            return "起始或结束日期无效"
        if start == end:
            return "起始日期与结束日期不能相同"
        if start > end:
            return (f"起始日期 {start.toString('yyyy-MM-dd')} 必须早于结束日期 "
                    f"{end.toString('yyyy-MM-dd')}")
        return ""

    def _update_run_button(self) -> None:
        """根据当前状态启用/禁用运行按钮（校验失败禁用）。"""
        if self._running:
            self.run_btn.setEnabled(False)
            self.run_btn.setText("回测中…")
            return
        self.run_btn.setEnabled(not bool(self._validate_dates()))
        self.run_btn.setText("🚀 开始回测")

    # ------------------------------------------------------------------
    # 策略切换
    # ------------------------------------------------------------------
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

    def _dates_str(self) -> tuple[str, str]:
        """返回 (start, end) 的 `YYYY-MM-DD` 字符串（QDateEdit → str）。"""
        return (self.start_edit.date().toString("yyyy-MM-dd"),
                self.end_edit.date().toString("yyyy-MM-dd"))

    # ------------------------------------------------------------------
    # 回测执行
    # ------------------------------------------------------------------
    def _run_backtest(self) -> None:
        """运行回测 - 使用BacktestService。M1-08：入口加日期校验 + 分类错误提示。"""
        if self._running:
            return
        # M1-08：日期校验前置
        val_err = self._validate_dates()
        if val_err:
            self._validation_hint.setText(f"⚠️ {val_err}")
            self._validation_hint.show()
            self._validation_hint.setStyleSheet("color:#ef4444;font-size:12px;padding:2px 4px;")
            return

        sym = self.sym_cb.currentData()
        per = self.per_cb.currentData()
        strat_cls_name = self.strat_cb.currentData()
        start, end = self._dates_str()
        capital = self.capital_spin.value()

        if not sym:
            self._toast("请选择合约")
            return

        self._running = True
        self.run_btn.setEnabled(False)
        self.run_btn.setText("回测中…")

        def work():
            """处理work - 使用BacktestService。

            M1-08: 去掉裸 `except Exception: pass`；分类捕获（日期/数据/策略）并
            `logger.exception` 记录；向上抛出由 err() 走分类提示。
            """
            from ..strategy.trend_following import TrendFollowing
            from ..strategy.breakout import Breakout
            from ..strategy.grid import Grid
            from ..strategy.martingale import Martingale
            from ..strategy.mean_reversion import MeanReversion
            from ..strategy.arbitrage import (
                CalendarSpread, CrossInstrumentSpread, SpotFuturesBasis,
            )
            from ..config.settings import Config
            from ..data.base import Contract

            # 策略映射：常规策略签名 strat_cls(symbol, params={})，套利策略签名 strat_cls(symbol, params_dict)
            strat_map = {
                "TrendFollowing": TrendFollowing,
                "Breakout": Breakout,
                "Grid": Grid,
                "Martingale": Martingale,
                "MeanReversion": MeanReversion,
                "CalendarSpread": CalendarSpread,
                "CrossInstrumentSpread": CrossInstrumentSpread,
                "SpotFuturesBasis": SpotFuturesBasis,
            }
            strat_cls = strat_map.get(strat_cls_name)
            if strat_cls is None:
                raise ValueError(f"未知策略: {strat_cls_name}")

            params = self._collect_params()

            # 尝试使用BacktestService
            try:
                backtest_service = request("backtest_service")
                # 套利策略构造签名为 (symbol, params_dict)，常规策略为 (symbol, params={})
                if strat_cls_name in ("CalendarSpread", "CrossInstrumentSpread", "SpotFuturesBasis"):
                    strategy = strat_cls(symbol=sym, params=params)
                else:
                    strategy = strat_cls(symbol=sym, params={})
                result = backtest_service.run_backtest(sym, start, end, per, warmup=60, strategy=strategy)
                return result
            except KeyError as e:
                # 服务未注册：回退到原始实现（这是预期的降级路径，仅 warning）
                logger.warning("backtest_service 未注册（%s），回退到 Backtester 直连", e)
                cfg = Config()
                bt = Backtester(cfg, self.mdm.feed)
                bt.add_contract(Contract(symbol=sym, exchange="TEST"))
                bt.add_strategy(strat_cls(sym, params))
                res = bt.run(sym, start, end, per, warmup=60)
                # 兼容原有返回格式
                return {
                    "metrics": res["metrics"],
                    "equity_curve": res["equity_curve"],
                    "trades": res["trades"],
                }
            except (ValueError, TypeError) as e:
                # 参数/日期错误：直接上抛给 err() 走分类提示
                logger.exception("参数或日期错误：sym=%s start=%s end=%s period=%s",
                                 sym, start, end, per)
                raise ValueError(f"参数错误：{e}") from e
            except Exception as e:
                # 数据源/未预期异常：logger.exception 记录后重抛 RuntimeError
                logger.exception("回测失败：sym=%s start=%s end=%s period=%s",
                                 sym, start, end, per)
                raise RuntimeError(f"回测执行失败：{e}") from e

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
            """处理err（M1-08：分类提示）。"""
            self._running = False
            self.run_btn.setEnabled(True)
            self.run_btn.setText("🚀 开始回测")
            # 分类：数据源 / 参数 / 其他
            msg_lower = str(e).lower()
            if "数据" in e or "data" in msg_lower or "feed" in msg_lower:
                level = "warning"
                prefix = "⚠️ 数据"
            elif "参数" in e or "日期" in e or "value" in msg_lower or "unknown" in msg_lower:
                level = "error"
                prefix = "❌ 参数"
            else:
                level = "error"
                prefix = "❌ 回测"
            self._toast(f"{prefix}失败: {e}", level=level)

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
