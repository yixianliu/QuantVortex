"""策略回测页（期货量化系统 UI）。

把项目自有的回测引擎（futures_quant.backtest.backtester.Backtester）接入桌面端：
    - 用户选择 合约 / 策略 / 周期 / 起止日期 / 初始资金；
    - 后台 Worker 线程驱动 Backtester 在 mdm.feed 的历史行情上回测；
    - 主区渲染：绩效 KPI 卡 + 资金曲线（PriceChart）+ 成交明细 / 绩效指标 双表；
    - 可一键导出引擎生成的 HTML 回测报告。

设计说明：
    - 行情直接复用 MarketDataManager 的底层 feed（mdm.feed.get_history）；
    - 默认放松风控阈值，展示策略原始表现；勾选「启用风控」则启用真实强平/限仓；
    - 合成行情（默认）仅用于方法验证，结论不可外推到真实市场。
仅依赖 PyQt6 / numpy / pandas，离线可跑。
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

from PyQt6.QtCore import QUrl, QDate
from PyQt6.QtGui import QDesktopServices, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QTabWidget,
    QCheckBox, QLineEdit, QSpinBox, QDateEdit, QDoubleSpinBox,
    QRadioButton, QGroupBox, QButtonGroup,
)

from .pages import (
    BasePage, Worker, symbol_code, symbol_label, PERIODS, PERIOD_LABEL,
)
from .widgets import (
    PageHeader, ToolBar, prepare_table, color_pnl, PALETTE, THEME, SectionHeader,
)
from .icons import icon
from .chart_widget import PriceChart
from ..runtime import get_data_dir

# 手动回测在历史记录表中的「代数」列用此哨兵值表示（区别于自动进化的正整数代数）
MANUAL_GEN = -1


class _BufLogger:
    """极简内存日志器：捕获引擎/经纪商的运行日志，便于测试断言（如交割强平告警）。"""

    def __init__(self) -> None:
        self.msgs: list = []

    def _a(self, lvl: str, msg: str) -> None:
        self.msgs.append((lvl, str(msg)))

    def warning(self, m) -> None:
        self._a("W", m)

    def info(self, m) -> None:
        self._a("I", m)

    def error(self, m) -> None:
        self._a("E", m)

    def debug(self, m) -> None:
        self._a("D", m)

from ..strategy.trend_following import TrendFollowing
from ..strategy.breakout import Breakout
from ..strategy.grid import Grid
from ..strategy.martingale import Martingale
from ..strategy.mean_reversion import MeanReversion
from ..core.metric_schema import format_metric, normalize_backtest_metrics
from .perf_chart import BacktestPerfChart
from .attribution_dialog import AttributionDialog

# 项目根目录（futures_quant/ui -> futures_quant -> root）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 可选策略注册表（展示名 -> 策略类）
STRATEGIES = [
    ("趋势跟踪", TrendFollowing),
    ("突破交易", Breakout),
    ("网格交易", Grid),
    ("马丁策略", Martingale),
    ("均值回归", MeanReversion),
]

# 各策略在对比图中的固定配色（与区块标题强调色一致，提升辨识度）
STRAT_COLORS = {
    "趋势跟踪": "#3b82f6",
    "突破交易": "#10b981",
    "网格交易": "#f59e0b",
    "马丁策略": "#ef4444",
    "均值回归": "#8b5cf6",
}

# 绩效指标中文标签
METRIC_LABELS = {
    "start_equity": "初始资金", "end_equity": "期末资金",
    "total_return": "总收益率", "annual_return": "年化收益",
    "sharpe": "夏普比率", "max_drawdown": "最大回撤",
    "win_rate": "胜率", "profit_factor": "盈亏比",
    "avg_win": "平均盈利", "avg_loss": "平均亏损",
    "num_fills": "成交笔数", "num_closing_trades": "平仓笔数",
    "long_opens": "多头开仓", "short_opens": "空头开仓",
}

# 参数敏感性扫描网格：初始资金档 × 周期档
SENS_CAPITALS = [250_000, 500_000, 1_000_000, 2_000_000]
SENS_PERIODS = ["5m", "15m", "30m", "1h", "D", "W"]
SENS_PERIOD_LABEL = {p: PERIOD_LABEL.get(p, p) for p in SENS_PERIODS}
SENS_CENTER_IDX = len(SENS_CAPITALS) // 2  # 居中资金档（代表性曲线用）
# 周期配色（用于敏感度代表性曲线叠加，区分时间粒度）
PERIOD_COLORS = {
    "5m": "#3b82f6", "15m": "#10b981", "30m": "#f59e0b",
    "1h": "#ef4444", "D": "#8b5cf6", "W": "#06b6d4",
}

# 参数优化（网格搜索）空间：每个策略挑选关键数值参数，给出候选档位。
# 候选数受控，组合数上限 MAX_OPT_COMBOS 防止回测过久。
MAX_OPT_COMBOS = 40
SEARCH_SCHEMA = {
    "趋势跟踪": {"fast": [5, 10, 15], "slow": [20, 30, 40], "atr_period": [10, 14, 20]},
    "突破交易": {"period": [10, 20, 30], "atr_period": [10, 14, 20]},
    "网格交易": {"grid_step": [10.0, 20.0, 40.0], "grid_count": [5, 10, 15]},
    "马丁策略": {"rsi_period": [10, 14, 20], "multiplier": [2.0, 2.5], "max_layers": [3, 4, 5]},
    "均值回归": {"period": [10, 20, 30], "num_std": [1.5, 2.0, 2.5]},
}
# 参数名 -> 紧凑中文/缩写（用于优化表内展示）
OPT_PARAM_SHORT = {
    "fast": "快线", "slow": "慢线", "atr_period": "ATR", "period": "周期",
    "grid_step": "步长", "grid_count": "层数", "rsi_period": "RSI",
    "multiplier": "乘数", "max_layers": "层数", "num_std": "标准差",
}


def _opt_combos(strat_name: str):
    """生成某策略的网格搜索参数组合（受 MAX_OPT_COMBOS 上限，超出则均匀抽样）。"""
    import itertools
    schema = SEARCH_SCHEMA.get(strat_name, {})
    if not schema:
        return [{}]
    keys = list(schema.keys())
    all_combos = [dict(zip(keys, vals))
                  for vals in itertools.product(*(schema[k] for k in keys))]
    if len(all_combos) > MAX_OPT_COMBOS:
        step = len(all_combos) / MAX_OPT_COMBOS
        all_combos = [all_combos[int(i * step)] for i in range(MAX_OPT_COMBOS)]
    return all_combos


def _pct(v: Optional[float]) -> str:
    if v is None:
        return "--"
    return f"{v * 100:,.2f}%"


class BacktestPage(BasePage):
    def __init__(self, mdm, store=None, config=None, session=None, header: bool = True):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "backtest"
        self._show_header = header
        dft = symbol_code(mdm.universe[0])
        if session is not None:
            self.cur_symbol, self.cur_period = session.get_page_selection("backtest", dft, "D")
        else:
            self.cur_symbol, self.cur_period = dft, "D"
        self._report_path: Optional[str] = None
        self._compare_results: dict = {}
        self._opt_best_params: Optional[dict] = None  # 最近一次优化的最优参数
        self._pending_params: Optional[dict] = None   # 待应用的最优参数（单模式覆盖）
        self._applied_params: Optional[dict] = None  # 用于信息栏标注
        self._kpi_frames: dict = {}
        self._kpi_labels: dict = {}
        self._kpi_titles: dict = {}
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        if self._show_header:
            root.addWidget(PageHeader("策略回测", "期货策略历史回测 · 绩效 / 回撤 / 胜率"))

        # ---- 控制条 ----
        ctl = QHBoxLayout()
        self.sym_cb = QComboBox(); self.sym_cb.setMinimumWidth(170)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        self.sym_cb.setCurrentIndex(max(0, self.sym_cb.findData(self.cur_symbol)))
        self.sym_cb.currentIndexChanged.connect(self._on_sel)

        self.strat_cb = QComboBox(); self.strat_cb.setMinimumWidth(120)
        for name, _ in STRATEGIES:
            self.strat_cb.addItem(name, name)
        if self.session is not None:
            last_strat = self.session.get("backtest_strategy")
            if last_strat:
                self.strat_cb.setCurrentIndex(max(0, self.strat_cb.findData(last_strat)))
        self.strat_cb.currentIndexChanged.connect(self._on_strat)

        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(self._on_sel)

        self.start_le = QLineEdit("2020-01-01")
        self.start_le.setFixedWidth(100)
        self.end_le = QLineEdit("2026-07-21")
        self.end_le.setFixedWidth(100)
        self.cap_le = QLineEdit("1000000")
        self.cap_le.setFixedWidth(90)

        self.risk_chk = QCheckBox("启用风控")
        self.risk_chk.setChecked(False)

        self.cmp_chk = QCheckBox("多策略对比")
        self.cmp_chk.setChecked(False)
        self.cmp_chk.setToolTip("勾选后一次回测全部策略，叠加资金曲线并生成策略对比表")

        self.sens_chk = QCheckBox("参数敏感度")
        self.sens_chk.setChecked(False)
        self.sens_chk.setToolTip("勾选后扫描 初始资金×周期 网格，生成敏感度矩阵评估策略稳定性")

        self.opt_chk = QCheckBox("参数优化")
        self.opt_chk.setChecked(False)
        self.opt_chk.setToolTip("勾选后对选中策略做参数网格搜索，按夏普排序找最优参数组合")

        # 三种分析模式互斥：任一勾选则取消其余，避免一次回测多类结果
        self._mode_chks = [self.cmp_chk, self.sens_chk, self.opt_chk]
        for a in self._mode_chks:
            for b in self._mode_chks:
                if a is not b:
                    a.toggled.connect(
                        lambda v, other=b: other.setChecked(False) if v else None)

        self.run_btn = QPushButton("开始回测"); self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        self.export_btn = QPushButton("打开HTML报告"); self.export_btn.setObjectName("secondary")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._open_report)
        self.apply_opt_btn = QPushButton("应用最优参数"); self.apply_opt_btn.setObjectName("secondary")
        self.apply_opt_btn.setEnabled(False)
        self.apply_opt_btn.setToolTip("参数优化完成后可用：以最优参数跑一遍单策略回测确认效果")
        self.apply_opt_btn.clicked.connect(self._apply_opt)

        ctl.addWidget(QLabel("合约")); ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("策略")); ctl.addWidget(self.strat_cb)
        ctl.addWidget(QLabel("周期")); ctl.addWidget(self.per_cb)
        ctl.addWidget(QLabel("起")); ctl.addWidget(self.start_le)
        ctl.addWidget(QLabel("止")); ctl.addWidget(self.end_le)
        ctl.addWidget(QLabel("资金")); ctl.addWidget(self.cap_le)
        ctl.addWidget(self.risk_chk)
        ctl.addWidget(self.cmp_chk)
        ctl.addWidget(self.sens_chk)
        ctl.addWidget(self.opt_chk)
        ctl.addWidget(self.run_btn)
        ctl.addWidget(self.export_btn)
        ctl.addWidget(self.apply_opt_btn)
        ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        # ---- 提示行 ----
        self.info = QLabel("选择合约与策略后点击「开始回测」。回测区间以数据源实际可取行情为准。"
                           "合成行情仅用于方法验证，非真实市场结论。")
        self.info.setObjectName("sub")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        # ---- 绩效概览 ----
        root.addWidget(SectionHeader("绩效概览", "#3b82f6"))
        self.kpi_bar = QHBoxLayout()
        self.kpi_bar.setSpacing(8)
        for key, title in [
            ("total_return", "总收益率"), ("annual_return", "年化"),
            ("sharpe", "夏普"), ("max_drawdown", "最大回撤"),
            ("win_rate", "胜率"), ("num_closing_trades", "平仓笔数"),
        ]:
            self.kpi_bar.addWidget(self._make_kpi(key, title))
        root.addLayout(self.kpi_bar)

        # ---- 资金曲线 ----
        default_strat = self.strat_cb.currentData() or STRATEGIES[0][0]
        self.sec_equity = SectionHeader("资金曲线", "#10b981", badge=default_strat)
        root.addWidget(self.sec_equity)
        self.chart = PriceChart()
        self.chart.setMinimumHeight(240)
        self.chart.set_title("资金曲线（运行回测后展示）")
        root.addWidget(self.chart, 3)

        # ---- 成交与指标 ----
        root.addWidget(SectionHeader("成交与指标", "#f59e0b"))
        self.tabs = QTabWidget()
        self.trade_tbl = QTableWidget(0, 8)
        self.trade_tbl.setHorizontalHeaderLabels(
            ["时间", "合约", "方向", "开平", "数量", "价格", "手续费", "盈亏"])
        self.trade_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metric_tbl = QTableWidget(0, 2)
        self.metric_tbl.setHorizontalHeaderLabels(["指标", "数值"])
        self.metric_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metric_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.trade_tbl, "成交明细")
        self.tabs.addTab(self.metric_tbl, "绩效指标")
        self.cmp_tbl = QTableWidget(0, 7)
        self.cmp_tbl.setHorizontalHeaderLabels(
            ["策略", "总收益率", "年化", "夏普", "最大回撤", "胜率", "平仓笔数"])
        self.cmp_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.cmp_tbl, "策略对比")
        # 参数敏感度矩阵：行=周期，列=资金档，单元格=总收益率（热力底色）
        self.sens_tbl = QTableWidget(0, len(SENS_CAPITALS) + 2)
        self.sens_tbl.setHorizontalHeaderLabels(
            ["周期＼资金"] + [f"{c // 10000}万" for c in SENS_CAPITALS] + ["平均收益"])
        self.sens_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.sens_tbl, "参数敏感度")
        # 参数优化：排名 / 参数组合 / 绩效
        self.opt_tbl = QTableWidget(0, 8)
        self.opt_tbl.setHorizontalHeaderLabels(
            ["排名", "参数组合", "总收益率", "年化", "夏普", "最大回撤", "胜率", "平仓笔数"])
        self.opt_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.opt_tbl, "参数优化")
        root.addWidget(self.tabs, 2)

        self._style_kpis()

    # ------------------------------------------------------------------
    def _make_kpi(self, key: str, title: str) -> QFrame:
        frame = QFrame(); frame.setObjectName("kpi"); frame.setFixedHeight(62)
        v = QVBoxLayout(frame); v.setContentsMargins(10, 6, 10, 6); v.setSpacing(2)
        lab = QLabel(title); lab.setObjectName("sub")
        val = QLabel("--"); val.setStyleSheet("font-size:18px;font-weight:bold;")
        v.addWidget(lab); v.addWidget(val)
        self._kpi_frames[key] = frame
        self._kpi_labels[key] = (lab, val)
        self._kpi_titles[key] = title
        return frame

    def _style_kpis(self) -> None:
        p = PALETTE[self._theme]
        for frame in self._kpi_frames.values():
            frame.setStyleSheet(
                f"background:{p['card']};border:1px solid {p['border']};border-radius:10px;")
        for lab, _ in self._kpi_labels.values():
            lab.setStyleSheet(f"color:{p['sub']};font-size:12px;")

    def set_theme(self, t: str) -> None:
        super().set_theme(t)
        self._style_kpis()

    # ------------------------------------------------------------------
    def _on_sel(self, *_):
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        self.selection_changed.emit(self.cur_symbol, self.cur_period)

    def _on_strat(self, *_):
        if self.session is not None:
            self.session.set("backtest_strategy", self.strat_cb.currentData())
        if getattr(self, "sec_equity", None) is not None:
            self.sec_equity.set_badge(self.strat_cb.currentData())
        # 对比模式下已缓存全部策略结果：切换下拉直接重绑明细，无需重跑
        if getattr(self, "_compare_results", None):
            name = self.strat_cb.currentData()
            res = self._compare_results.get(name)
            if res:
                self._update_kpis(res["metrics"])
                self._fill_trades(res["trades"])
                self._fill_metrics(res["metrics"])

    # ------------------------------------------------------------------
    def _run(self) -> None:
        sym = self.sym_cb.currentData()
        strat_name = self.strat_cb.currentData()
        per = self.per_cb.currentData()
        start = self.start_le.text().strip()
        end = self.end_le.text().strip()
        try:
            capital = float(self.cap_le.text().strip())
        except ValueError:
            capital = 1_000_000.0

        self.run_btn.setEnabled(False); self.run_btn.setText("回测中…")
        self.export_btn.setEnabled(False)
        self.apply_opt_btn.setEnabled(False)
        # 应用最优参数：单模式以覆盖参数运行（不来自优化模式）
        override = getattr(self, "_pending_params", None)
        self._applied_params = override
        self.info.setText(f"正在回测 {sym} · {strat_name} · {PERIOD_LABEL.get(per, per)} "
                          f"· {start} ~ {end} …"
                          + ("（应用优化最优参数确认）" if override else ""))

        def work():
            from futures_quant.config.settings import Config
            from futures_quant.backtest.backtester import Backtester
            from futures_quant.data.base import Contract
            from futures_quant.data.contract_specs import build_contract, get_contract_spec

            feed = self.mdm.feed
            row = next((r for r in self.mdm.universe if symbol_code(r) == sym), None)
            # R4.1：用真实品种规格构造合约（乘数/保证金/手续费/杠杆/交割日）
            contract = build_contract(sym)
            spec = get_contract_spec(sym)
            strat_cls = dict((n, c) for n, c in STRATEGIES)[strat_name]

            def make_cfg(cap):
                cfg = Config()
                if not self.risk_chk.isChecked():
                    # 放松风控，展示策略原始表现
                    cfg.risk.max_single_loss = 1e12
                    cfg.risk.max_daily_loss = 1e12
                    cfg.risk.max_drawdown = 0.99
                    cfg.risk.max_position_per_symbol = 100
                    cfg.risk.max_total_position_ratio = 0.98
                    cfg.risk.max_order_qty = 100
                # R4.1：接入真实品种规格（账户级保证金/手续费/乘数/杠杆生效）
                cfg.account.margin_rate = spec["margin_rate"]
                cfg.account.commission_per_lot = spec["commission_per_lot"]
                cfg.account.multiplier = spec["multiplier"]
                cfg.account.leverage = spec["leverage"]
                cfg.backtest.start_cash = cap
                cfg.account.initial_capital = cap
                return cfg

            outdir = os.path.join(ROOT, "data", "backtest_reports")

            if self.opt_chk.isChecked():
                # 参数优化：对选中策略做参数网格搜索，按夏普排序找最优
                base_params = strat_cls(sym, {}).params  # 默认参数（保底未搜索项）
                combos = _opt_combos(strat_name)
                scanned = []
                best_curve = None
                default_curve = None
                for combo in combos:
                    params = dict(base_params)
                    params.update(combo)
                    bt = Backtester(make_cfg(capital), feed)
                    bt.add_contract(contract)
                    bt.add_strategy(strat_cls(sym, params))
                    res = bt.run(sym, start, end, per, warmup=60)
                    m = res["metrics"]
                    scanned.append({"params": combo, "metrics": m,
                                    "equity_curve": res["equity_curve"]})
                    if combo == combos[0]:
                        default_curve = res["equity_curve"]
                # 按夏普降序排序（夏普缺失视为 -inf）
                ranked = sorted(
                    scanned,
                    key=lambda x: (x["metrics"].get("sharpe")
                                   if x["metrics"].get("sharpe") is not None else float("-inf")),
                    reverse=True)
                best = ranked[0] if ranked else None
                if best is not None:
                    best_curve = best["equity_curve"]
                return {
                    "opt": True, "ranked": ranked, "best": best,
                    "best_curve": best_curve, "default_curve": default_curve,
                    "n_scanned": len(scanned), "sym": sym, "per": per,
                    "strat": strat_name,
                }

            if self.sens_chk.isChecked():
                # 参数敏感度：扫描 初始资金 × 周期 网格，评估策略稳定性
                grid = {}
                center_cap = SENS_CAPITALS[SENS_CENTER_IDX]
                center_curves = []
                for cap in SENS_CAPITALS:
                    cfg = make_cfg(cap)
                    for pper in SENS_PERIODS:
                        bt = Backtester(cfg, feed)
                        bt.add_contract(contract)
                        bt.add_strategy(strat_cls(sym, {}))
                        res = bt.run(sym, start, end, pper, warmup=60)
                        grid[(pper, cap)] = res["metrics"]
                        if cap == center_cap:
                            center_curves.append((pper, res["equity_curve"]))
                return {
                    "sens": True, "grid": grid,
                    "center_curves": center_curves,
                    "caps": SENS_CAPITALS, "pers": SENS_PERIODS,
                    "center_cap": center_cap,
                    "sym": sym, "per": per, "strat": strat_name,
                }

            if self.cmp_chk.isChecked():
                # 多策略对比：逐一回测全部策略，叠加曲线并生成对比表
                results = []
                report = None
                for name, cls in STRATEGIES:
                    bt = Backtester(make_cfg(capital), feed)
                    bt.add_contract(contract)
                    bt.add_strategy(cls(sym, {}))
                    res = bt.run(sym, start, end, per, warmup=60)
                    results.append({
                        "strat": name,
                        "metrics": res["metrics"],
                        "equity_curve": res["equity_curve"],
                        "trades": res["trades"],
                    })
                    if name == strat_name:
                        paths = bt.export(
                            outdir, prefix=f"bt_{sym.replace('.', '_')}_{per}")
                        report = paths["html"]
                primary = dict((r["strat"], r) for r in results).get(
                    strat_name, results[0])
                return {
                    "compare": True, "results": results, "primary": primary,
                    "report": report, "sym": sym, "per": per, "strat": strat_name,
                }

            bt = Backtester(make_cfg(capital), feed)
            bt.add_contract(contract)
            bt.add_strategy(strat_cls(sym, override if override else {}))

            res = bt.run(sym, start, end, per, warmup=60)
            paths = bt.export(outdir, prefix=f"bt_{sym.replace('.', '_')}_{per}")
            return {
                "metrics": res["metrics"], "equity_curve": res["equity_curve"],
                "trades": res["trades"], "report": paths["html"],
                "sym": sym, "per": per, "strat": strat_name,
            }

        self._run_worker(work, self._on_done,
                         on_err=lambda e: self._on_err(str(e)))

    # ------------------------------------------------------------------
    def _on_done(self, r: dict) -> None:
        self.run_btn.setEnabled(True); self.run_btn.setText("开始回测")

        if r.get("opt"):
            # 参数优化：排名表 + 最优 vs 默认曲线叠加
            self._fill_opt(r["ranked"])
            self._update_chart_opt(r["best_curve"], r["default_curve"],
                                   r["sym"], r["per"])
            self.tabs.setCurrentWidget(self.opt_tbl)
            best = r["best"]
            if best is not None:
                self._update_kpis(best["metrics"])
            # 缓存最优参数，供「应用最优参数」使用
            self._opt_best_params = best["params"] if best else None
            self.apply_opt_btn.setEnabled(bool(best))
            self._report_path = None
            self.export_btn.setEnabled(False)
            self.info.setStyleSheet("")
            bparam = "，".join(f"{OPT_PARAM_SHORT.get(k, k)}={v}"
                               for k, v in (best["params"].items())) if best else "--"
            self.info.setText(
                f"参数优化完成：{r['sym']} · {r['strat']}　共扫描 {r['n_scanned']} 组参数"
                f"（按夏普排序）。最优：{bparam}　"
                f"夏普 {best['metrics'].get('sharpe') if best else '--'}　"
                f"总收益 {_pct(best['metrics'].get('total_return') if best else None)}。")
            return

        if r.get("sens"):
            # 参数敏感度矩阵 + 代表性曲线（居中资金档各周期叠加）
            self._fill_sens(r["grid"], r["caps"], r["pers"],
                            r["center_cap"], r["sym"], r["strat"])
            self._update_chart_sens(r["center_curves"], r["center_cap"], r["sym"])
            self.tabs.setCurrentWidget(self.sens_tbl)
            # KPI 卡展示居中资金档在「选中周期」（若网格含）的表现
            sel_per = self.cur_period if self.cur_period in r["pers"] \
                else r["pers"][len(r["pers"]) // 2]
            cell = r["grid"].get((sel_per, r["center_cap"])) or {}
            if cell:
                self._update_kpis(cell)
            self._report_path = None
            self.export_btn.setEnabled(False)
            self.info.setStyleSheet("")
            self.info.setText(
                f"参数敏感度扫描完成：{r['sym']} · {r['strat']}　"
                f"网格 {len(r['pers'])}周期 × {len(r['caps'])}资金档；"
                f"红=盈利 / 绿=亏损（底色强度示幅度），悬停单元格看夏普/回撤/胜率。")
            return

        if r.get("compare"):
            self._compare_results = {x["strat"]: x for x in r["results"]}
            # KPI 卡展示「选中策略」基准（下拉可切换，无需重跑）
            prim = self._compare_results.get(r["strat"], r["primary"])
            self._update_kpis(prim["metrics"])
            self._update_chart_compare(r["results"], r["sym"], r["per"])
            self._fill_trades(prim["trades"])
            self._fill_metrics(prim["metrics"])
            self._fill_compare(r["results"])
            self.sec_equity.set_badge(f"对比 {len(r['results'])} 策略")
            self.tabs.setCurrentWidget(self.cmp_tbl)
            self._report_path = r.get("report")
            self.export_btn.setEnabled(bool(self._report_path))
            self.info.setStyleSheet("")
            best = max(r["results"],
                       key=lambda x: (x["metrics"].get("total_return") or 0))
            self.info.setText(
                f"多策略对比完成：{r['sym']} · {PERIOD_LABEL.get(r['per'], r['per'])}　"
                f"共 {len(r['results'])} 个策略；最优「{best['strat']}」"
                f"总收益 {_pct(best['metrics'].get('total_return'))}。"
                f"切换上方「策略」下拉可查看各策略明细。")
            return

        m = r["metrics"]
        self._update_kpis(m)
        self._update_chart(r["equity_curve"], r["sym"], r["per"])
        self._fill_trades(r["trades"])
        self._fill_metrics(m)

        self._report_path = r["report"]
        self.export_btn.setEnabled(True)
        self.info.setStyleSheet("")  # 还原（交由 QSS 控制颜色）
        self.info.setText(
            f"完成：{r['sym']} · {r['strat']} · {PERIOD_LABEL.get(r['per'], r['per'])}　"
            f"总收益 {_pct(m.get('total_return'))}　最大回撤 {_pct(m.get('max_drawdown'))}　"
            f"夏普 {m.get('sharpe')}　平仓 {m.get('num_closing_trades')} 笔。"
            + ("（已应用优化最优参数确认）" if self._applied_params else ""))
        self._pending_params = None
        self._applied_params = None

    def _on_err(self, msg: str) -> None:
        self.run_btn.setEnabled(True); self.run_btn.setText("开始回测")
        self.export_btn.setEnabled(False)
        self.info.setStyleSheet(f"color:{p['down']};")
        self.info.setText(f"回测失败：{msg}（请检查合约/日期是否可取行情）")

    # ------------------------------------------------------------------
    def _update_kpis(self, m: dict) -> None:
        p = PALETTE[self._theme]
        mapping = {
            "total_return": m.get("total_return"),
            "annual_return": m.get("annual_return"),
            "sharpe": m.get("sharpe"),
            "max_drawdown": m.get("max_drawdown"),
            "win_rate": m.get("win_rate"),
            "num_closing_trades": m.get("num_closing_trades"),
        }
        for key, val in mapping.items():
            _, vlab = self._kpi_labels[key]
            if key in ("total_return", "annual_return", "max_drawdown", "win_rate"):
                vlab.setText(_pct(val))
                if val is None:
                    vlab.setStyleSheet(f"color:{p['text']};font-size:18px;font-weight:bold;")
                else:
                    col = p["down"] if val >= 0 else p["up"]  # 中国习惯：涨红跌绿
                    if key == "max_drawdown":
                        col = p["up"]  # 回撤为正值，用警示红
                    vlab.setStyleSheet(f"color:{col};font-size:18px;font-weight:bold;")
            else:
                txt = f"{val:,}" if isinstance(val, (int, float)) else "--"
                vlab.setText(txt)
                vlab.setStyleSheet(f"color:{p['text']};font-size:18px;font-weight:bold;")

    def _update_chart(self, curve: list, sym: str, per: str) -> None:
        if not curve:
            return
        n = len(curve)
        xs = list(range(n))
        ys = [float(e[1]) for e in curve]
        self.chart.set_data(
            series=[{"name": "资金曲线", "color": "#3b82f6", "x": xs, "y": ys}],
            title=f"{sym} 资金曲线（{PERIOD_LABEL.get(per, per)}）")

    def _update_chart_compare(self, results: list, sym: str, per: str) -> None:
        """多策略对比：把所有策略的资金曲线叠加到同一坐标系。"""
        series = []
        for r in results:
            curve = r.get("equity_curve") or []
            if not curve:
                continue
            ys = [float(e[1]) for e in curve]
            series.append({
                "name": r["strat"],
                "color": STRAT_COLORS.get(r["strat"], "#3b82f6"),
                "x": list(range(len(ys))), "y": ys,
            })
        if not series:
            return
        self.chart.set_data(
            series=series,
            title=f"{sym} 多策略资金曲线对比（{PERIOD_LABEL.get(per, per)}）")

    def _update_chart_sens(self, curves: list, cap: int, sym: str) -> None:
        """参数敏感度代表性曲线：居中资金档下，各周期资金曲线叠加，直观看时间粒度敏感性。"""
        series = []
        for per, curve in curves:
            if not curve:
                continue
            ys = [float(e[1]) for e in curve]
            series.append({
                "name": SENS_PERIOD_LABEL.get(per, per),
                "color": PERIOD_COLORS.get(per, "#3b82f6"),
                "x": list(range(len(ys))), "y": ys,
            })
        if not series:
            return
        self.chart.set_data(
            series=series,
            title=f"{sym} 敏感度代表性曲线（{cap // 10000}万 · 各周期叠加）")

    def _fill_sens(self, grid: dict, caps: list, pers: list,
                   center_cap: int, sym: str, strat: str) -> None:
        """参数敏感度矩阵：行=周期，列=资金档；单元格=总收益率，热力底色（涨红跌绿）。"""
        self.sens_tbl.setRowCount(0); self.sens_tbl.setColumnCount(0)
        prepare_table(self.sens_tbl, self._theme)
        ncols = len(caps) + 2  # 周期标签列 + 资金列 + 平均收益列
        nrows = len(pers) + 1   # 周期行 + 平均收益行
        self.sens_tbl.setColumnCount(ncols)
        self.sens_tbl.setRowCount(nrows)
        self.sens_tbl.setHorizontalHeaderLabels(
            ["周期＼资金"] + [f"{c // 10000}万" for c in caps] + ["平均收益"])
        p = PALETTE[self._theme]
        up, down = p["up"], p["down"]
        # 收集收益用于归一化配色（强度 ∝ 幅度）
        vals = []
        for per in pers:
            for cap in caps:
                tr = (grid.get((per, cap)) or {}).get("total_return")
                if isinstance(tr, (int, float)):
                    vals.append(tr)
        denom = max(abs(max(vals)) if vals else 1.0,
                    abs(min(vals)) if vals else 1.0, 1e-9)

        def bg(v):
            if v is None:
                return None
            scale = min(abs(v) / denom, 1.0)
            alpha = int(30 + 65 * scale)
            c = QColor(up if v >= 0 else down)
            c.setAlpha(alpha)
            return c

        # 第一列：周期标签
        for i, per in enumerate(pers):
            lab = QTableWidgetItem(SENS_PERIOD_LABEL.get(per, per))
            lab.setForeground(_qcolor("text"))
            self.sens_tbl.setItem(i, 0, lab)
        # 数据单元格 + 行平均
        for i, per in enumerate(pers):
            row_rets = []
            for j, cap in enumerate(caps):
                m = grid.get((per, cap)) or {}
                tr = m.get("total_return")
                item = QTableWidgetItem(_pct(tr))
                if isinstance(tr, (int, float)):
                    item.setForeground(_qcolor("up" if tr >= 0 else "down"))
                    b = bg(tr)
                    if b is not None:
                        item.setBackground(b)
                    row_rets.append(tr)
                    sh = m.get("sharpe"); dd = m.get("max_drawdown")
                    wr = m.get("win_rate"); nt = m.get("num_closing_trades")
                    item.setToolTip(
                        f"{SENS_PERIOD_LABEL.get(per, per)} · {cap // 10000}万\n"
                        f"总收益 {_pct(tr)}　年化 {_pct(m.get('annual_return'))}\n"
                        f"夏普 {sh}　回撤 {_pct(dd)}　胜率 {_pct(wr)}　平仓 {nt}笔")
                self.sens_tbl.setItem(i, j + 1, item)
            avg = sum(row_rets) / len(row_rets) if row_rets else None
            ai = QTableWidgetItem(_pct(avg))
            ai.setForeground(_qcolor("up" if (avg or 0) >= 0 else "down"))
            self.sens_tbl.setItem(i, ncols - 1, ai)
        # 平均收益行：各资金档跨周期均值 + 总平均
        avg_row = len(pers)
        alab = QTableWidgetItem("平均收益")
        alab.setForeground(_qcolor("text"))
        self.sens_tbl.setItem(avg_row, 0, alab)
        for j, cap in enumerate(caps):
            col_rets = [(grid.get((per, cap)) or {}).get("total_return")
                        for per in pers]
            col_rets = [x for x in col_rets if isinstance(x, (int, float))]
            avg = sum(col_rets) / len(col_rets) if col_rets else None
            ci = QTableWidgetItem(_pct(avg))
            ci.setForeground(_qcolor("up" if (avg or 0) >= 0 else "down"))
            self.sens_tbl.setItem(avg_row, j + 1, ci)
        grand = sum(vals) / len(vals) if vals else None
        gi = QTableWidgetItem(_pct(grand))
        gi.setForeground(_qcolor("up" if (grand or 0) >= 0 else "down"))
        self.sens_tbl.setItem(avg_row, ncols - 1, gi)

    def _fill_opt(self, ranked: list) -> None:
        """参数优化排名表：行=参数组合（按夏普降序），最优行高亮。"""
        self.opt_tbl.setRowCount(0)
        prepare_table(self.opt_tbl, self._theme)
        top = ranked[:15]  # 仅展示前 15，避免过长
        self.opt_tbl.setRowCount(len(top))
        p = PALETTE[self._theme]
        for i, item in enumerate(top):
            m = item["metrics"]
            params = item["params"]
            ptext = "，".join(f"{OPT_PARAM_SHORT.get(k, k)}={v}"
                             for k, v in params.items()) if params else "默认"
            self.opt_tbl.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.opt_tbl.setItem(i, 1, QTableWidgetItem(ptext))
            tr = m.get("total_return")
            tr_item = QTableWidgetItem(_pct(tr))
            tr_item.setForeground(_qcolor("up" if (tr or 0) >= 0 else "down"))
            self.opt_tbl.setItem(i, 2, tr_item)
            self.opt_tbl.setItem(i, 3, QTableWidgetItem(_pct(m.get("annual_return"))))
            sh = m.get("sharpe")
            self.opt_tbl.setItem(
                i, 4, QTableWidgetItem(f"{sh}" if sh is not None else "--"))
            dd_item = QTableWidgetItem(_pct(m.get("max_drawdown")))
            dd_item.setForeground(_qcolor("up"))
            self.opt_tbl.setItem(i, 5, dd_item)
            self.opt_tbl.setItem(i, 6, QTableWidgetItem(_pct(m.get("win_rate"))))
            self.opt_tbl.setItem(
                i, 7, QTableWidgetItem(str(m.get("num_closing_trades", "--"))))
            # 最优（第 1 名）整行高亮底色
            if i == 0:
                for c in range(self.opt_tbl.columnCount()):
                    it = self.opt_tbl.item(i, c)
                    if it is not None:
                        it.setBackground(_qcolor_bg("#10b981", alpha=40))
            # 悬停看完整参数
            self.opt_tbl.item(i, 1).setToolTip(
                "　".join(f"{k}={v}" for k, v in params.items()) if params
                else "默认参数")

    def _update_chart_opt(self, best_curve: list, default_curve: list,
                          sym: str, per: str) -> None:
        """参数优化曲线：最优参数（强调色）vs 默认参数（灰）叠加对比。"""
        series = []
        if default_curve:
            ys = [float(e[1]) for e in default_curve]
            series.append({"name": "默认参数", "color": "#94a3b8",
                           "x": list(range(len(ys))), "y": ys})
        if best_curve:
            ys = [float(e[1]) for e in best_curve]
            series.append({"name": "最优参数", "color": "#3b82f6",
                           "x": list(range(len(ys))), "y": ys})
        if not series:
            return
        self.chart.set_data(
            series=series,
            title=f"{sym} 参数优化曲线对比（{PERIOD_LABEL.get(per, per)}）")

    def _fill_compare(self, results: list) -> None:
        """策略对比表：行=策略，列=关键绩效指标；最优总收益高亮。"""
        self.cmp_tbl.setRowCount(0)
        prepare_table(self.cmp_tbl)
        self.cmp_tbl.setRowCount(len(results))
        best_idx = max(range(len(results)),
                       key=lambda i: (results[i]["metrics"].get("total_return") or 0))
        p = PALETTE[self._theme]
        up = p["up"]; down = p["down"]; warn = "#ef4444"
        for i, r in enumerate(results):
            m = r["metrics"]
            self.cmp_tbl.setItem(i, 0, QTableWidgetItem(r["strat"]))
            # 总收益率（涨红跌绿）
            tr = m.get("total_return")
            tr_item = QTableWidgetItem(_pct(tr))
            tr_item.setForeground(_qcolor("up" if (tr or 0) >= 0 else "down"))
            self.cmp_tbl.setItem(i, 1, tr_item)
            # 年化
            self.cmp_tbl.setItem(
                i, 2, QTableWidgetItem(_pct(m.get("annual_return"))))
            # 夏普
            sh = m.get("sharpe")
            self.cmp_tbl.setItem(
                i, 3, QTableWidgetItem(f"{sh}" if sh is not None else "--"))
            # 最大回撤（用警示红）
            dd_item = QTableWidgetItem(_pct(m.get("max_drawdown")))
            dd_item.setForeground(_qcolor("up"))  # 中国习惯：回撤为正值显红
            self.cmp_tbl.setItem(i, 4, dd_item)
            # 胜率
            self.cmp_tbl.setItem(
                i, 5, QTableWidgetItem(_pct(m.get("win_rate"))))
            # 平仓笔数
            self.cmp_tbl.setItem(
                i, 6, QTableWidgetItem(str(m.get("num_closing_trades", "--"))))
            # 最优策略整行高亮底色
            if i == best_idx:
                for c in range(self.cmp_tbl.columnCount()):
                    it = self.cmp_tbl.item(i, c)
                    if it is not None:
                        it.setBackground(_qcolor_bg("#10b981", alpha=40))

    def _fill_trades(self, trades: list) -> None:
        self.trade_tbl.setRowCount(0)
        prepare_table(self.trade_tbl)
        rows = trades[:500]
        self.trade_tbl.setRowCount(len(rows))
        for i, t in enumerate(rows):
            self.trade_tbl.setItem(i, 0, QTableWidgetItem(str(t.datetime)[:19]))
            self.trade_tbl.setItem(i, 1, QTableWidgetItem(str(t.symbol)))
            d_item = QTableWidgetItem(t.direction.value)
            if t.direction.value == "LONG":
                d_item.setForeground(_qcolor("up"))
            else:
                d_item.setForeground(_qcolor("down"))
            self.trade_tbl.setItem(i, 2, d_item)
            self.trade_tbl.setItem(i, 3, QTableWidgetItem(t.offset.value))
            self.trade_tbl.setItem(i, 4, QTableWidgetItem(str(t.quantity)))
            self.trade_tbl.setItem(i, 5, QTableWidgetItem(f"{t.price:.2f}"))
            self.trade_tbl.setItem(i, 6, QTableWidgetItem(f"{t.commission:.2f}"))
            pnl_item = QTableWidgetItem(f"{t.pnl:.2f}")
            color_pnl(pnl_item, t.pnl, self._theme)
            self.trade_tbl.setItem(i, 7, pnl_item)

    def _fill_metrics(self, m: dict) -> None:
        self.metric_tbl.setRowCount(0)
        prepare_table(self.metric_tbl)
        items = [(METRIC_LABELS.get(k, k), v) for k, v in m.items()]
        self.metric_tbl.setRowCount(len(items))
        for i, (lab, val) in enumerate(items):
            self.metric_tbl.setItem(i, 0, QTableWidgetItem(lab))
            if isinstance(val, float) and abs(val) < 1 and "权益" not in lab and "资金" not in lab:
                txt = _pct(val)
            elif isinstance(val, float):
                txt = f"{val:,.2f}"
            else:
                txt = str(val)
            self.metric_tbl.setItem(i, 1, QTableWidgetItem(txt))

    # ------------------------------------------------------------------
    def _open_report(self) -> None:
        if self._report_path and os.path.exists(self._report_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._report_path))

    def _apply_opt(self) -> None:
        """把最近一次参数优化的最优参数，作为单策略回测参数跑一遍确认。"""
        if not getattr(self, "_opt_best_params", None):
            return
        # 取消其他分析模式，回到单策略模式
        for chk in self._mode_chks:
            chk.setChecked(False)
        self._pending_params = dict(self._opt_best_params)
        self._run()


def _qcolor(key: str):
    from PyQt6.QtGui import QColor
    return QColor(PALETTE[THEME][key])


def _qcolor_bg(hex_color: str, alpha: int = 40):
    """由十六进制颜色构造带透明度的 QColor（用于对比表高亮行）。"""
    from PyQt6.QtGui import QColor
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


# ============================================================================
# 回测中心：全自动自我学习回测系统（零用户操作）
# ============================================================================

# 学习流水线五阶段（图标 + 名称）
PIPELINE_STAGES = [
    ("🧬", "因子生成"),
    ("⏱️", "历史回测"),
    ("🔁", "迭代优化"),
    ("⚖️", "盈利判定"),
    ("🚀", "同步AI预测"),
]

# 两次进化之间的间歇（毫秒）：页面可见时短间歇，不可见时长间歇省资源
GEN_INTERVAL_MS = 2200
GEN_INTERVAL_HIDDEN_MS = 12000
ERR_RETRY_MS = 6000


class BacktestCenterPage(BasePage):
    """回测中心 · 全自动自我学习回测系统。

    零用户操作闭环（页面打开即自动运行，无任何按钮/输入框）：
        ① 因子生成：AI 随机组合入场因子与风控参数，自主产生策略基因；
        ② 历史回测：每个基因经解释器策略送入回测引擎跑历史行情；
        ③ 迭代优化：遗传算法逐代进化（精英保留/锦标赛/交叉/变异），
           适应度综合夏普、收益、回撤、胜率与成交充分性；
        ④ 盈利判定：多阈值联合判定策略是否具备盈利能力；
        ⑤ 自动同步：盈利策略实时落盘策略库，「AI预测」模块直接读取
           并把策略方向信号融合进预测（无需任何人工确认）。
    品种自动轮换：每个品种进化若干代后自动切换下一品种，全市场循环学习。
    """

    def __init__(self, mdm, store=None, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "backtest"
        self._engine = None            # EvolutionEngine（懒创建）
        self._auto_started = False     # 只自动启动一次
        self._gen_running = False      # 当前是否有一代正在后台评估
        self._last_snapshot = None
        self._manual_mode = False       # 手动回测模式（与自动进化互斥）
        self._manual_running = False    # 当前是否在一次手动回测中
        self._manual_sym_cb = None
        self._manual_strat_cb = None
        self._manual_gene_override = None  # 预测页联动注入的精确基因
        self._lib_entries = []              # 盈利策略库当前行 → 原始条目
        self._manual_run_btn = None
        self._manual_group = None
        self._rb_auto = None
        self._rb_manual = None
        self._last_manual = None        # 最近一次手动回测结果（供测试/复用）
        self._last_manual_logger = None
        self._manual_config_restored = False  # R7-7.2：手动配置仅预填一次
        self._stage_tiles: list = []
        self._chips: dict = {}
        self._perf_chips: dict = {}   # 绩效指标卡（夏普/回撤/年化/卡玛/胜率/盈亏比）
        # 本地持久化库：引擎断点 / 历史回测记录 / 学习日志（自动保存+启动恢复）
        try:
            from ..storage.backtest_store import get_backtest_store
            self._bt_store = get_backtest_store()
        except Exception:  # noqa: BLE001
            self._bt_store = None
        # 期货特有参数（杠杆/保证金/乘数/交割日），由「期货参数」控制条配置
        r0 = self.mdm.universe[0] if self.mdm.universe else (None, None, None, "SHFE", 10, 1)
        self._futures_params: dict = {
            "leverage": 10.0,
            "margin_rate": 0.10,
            "multiplier": float(r0[4]) if len(r0) > 4 else 10.0,
            "commission_per_lot": 3.0,
            "close_today_ratio": 0.5,
            "delivery_date": None,
        }
        # 尝试从本地库恢复上次配置的期货参数
        if self._bt_store is not None:
            try:
                saved = self._bt_store.load_state("futures_params")
                if isinstance(saved, dict):
                    self._futures_params.update(saved)
            except Exception:  # noqa: BLE001
                pass
        self._restoring = False        # 恢复回放时不重复写日志库
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        from .widgets import StatusTile, MetricChip

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "回测中心 · 全自动自我学习",
            "AI自主生成策略因子 → 自动回测 → 迭代进化 → 盈利判定 → 自动同步AI预测"
            "｜ 全程零操作，打开即运行"))

        # ---- 运行状态行 ----
        self.info = QLabel("系统待命：进入本页后自动启动自我学习流程…")
        self.info.setObjectName("sub")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        # ---- 学习流水线五阶段状态灯 ----
        root.addWidget(SectionHeader("自我学习流水线", "#8b5cf6",
                                     badge="全自动"))
        stage_bar = QHBoxLayout()
        stage_bar.setSpacing(8)
        for ico, name in PIPELINE_STAGES:
            tile = StatusTile(f"{ico} {name}")
            tile.set_status("neutral", "待命", "等待系统启动")
            self._stage_tiles.append(tile)
            stage_bar.addWidget(tile)
        root.addLayout(stage_bar)

        # ---- 学习进度 KPI ----
        chip_bar = QHBoxLayout()
        chip_bar.setSpacing(8)
        for key, label in [
            ("symbol", "当前品种"), ("generation", "进化代数"),
            ("evaluated", "已评估策略"), ("profitable", "盈利策略库"),
            ("best_fit", "最佳适应度"), ("best_ret", "最佳总收益"),
        ]:
            chip = MetricChip(label)
            self._chips[key] = chip
            chip_bar.addWidget(chip)
        chip_bar.addStretch(1)
        root.addLayout(chip_bar)

        # ---- 期货特有参数控制条（杠杆/保证金/乘数/交割日，下代生效并持久化）----
        self._build_futures_params_bar()
        root.addWidget(self.futures_bar)

        # ---- 模式切换：自动进化（默认） / 手动回测（互斥）----
        self._build_mode_switch()
        root.addLayout(self._mode_row)

        # ---- 手动回测面板（默认隐藏，切到手动模式时展开）----
        self._build_manual_panel()
        root.addWidget(self._manual_group)
        self._manual_group.setVisible(False)

        # ---- 绩效指标卡（夏普/回撤/年化/卡玛/胜率/盈亏比，与预测板块同口径）----
        perf_bar = QHBoxLayout()
        perf_bar.setSpacing(8)
        for key, label in [
            ("pf_sharpe", "夏普比率"), ("pf_dd", "最大回撤"),
            ("pf_annual", "年化收益"), ("pf_calmar", "卡玛比率"),
            ("pf_wr", "胜率"), ("pf_pf", "盈亏比"),
        ]:
            chip = MetricChip(label)
            self._perf_chips[key] = chip
            perf_bar.addWidget(chip)
        perf_bar.addStretch(1)
        root.addLayout(perf_bar)

        # ---- 最优策略资金曲线 + 最大回撤（BacktestPerfChart）----
        self.sec_equity = SectionHeader("最优策略资金曲线 · 最大回撤", "#10b981",
                                        badge="自动更新")
        root.addWidget(self.sec_equity)
        self.chart = BacktestPerfChart()
        self.chart.setMinimumHeight(220)
        self.chart.set_title("资金曲线与最大回撤（系统自动回测后展示）")
        root.addWidget(self.chart, 3)

        # ---- 学习结果三视图 ----
        root.addWidget(SectionHeader("学习成果", "#f59e0b"))
        self.tabs = QTabWidget()

        # ① 当代种群排行
        self.pop_tbl = QTableWidget(0, 9)
        self.pop_tbl.setHorizontalHeaderLabels(
            ["排名", "策略因子（AI自动生成）", "总收益", "夏普", "最大回撤",
             "胜率", "交易数", "适应度", "盈利判定"])
        hh = self.pop_tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.pop_tbl, "🧬 当代种群排行")

        # ② 盈利策略库（已自动同步 AI 预测）
        self.lib_tbl = QTableWidget(0, 10)
        self.lib_tbl.setHorizontalHeaderLabels(
            ["品种", "策略因子", "总收益", "年化", "夏普", "回撤",
             "胜率", "发现时间", "状态", "操作"])
        self.lib_tbl.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.lib_tbl, "💰 盈利策略库")

        # ③ 历史回测记录（持久化，重启保留，供查看与对比）
        # R6：第 12 列「操作」挂📊详情按钮（打开绩效归因对话框）
        self.hist_tbl = QTableWidget(0, 12)
        self.hist_tbl.setHorizontalHeaderLabels(
            ["时间", "品种", "代数", "最优策略因子", "总收益", "夏普",
             "回撤", "胜率", "交易数", "适应度", "盈利入库", "操作"])
        hh2 = self.hist_tbl.horizontalHeader()
        hh2.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh2.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.hist_tbl, "🗂 历史回测记录")

        # ④ 学习日志
        from PyQt6.QtWidgets import QListWidget
        self.log_list = QListWidget()
        self.log_list.setWordWrap(True)
        self.tabs.addTab(self.log_list, "📜 学习日志")
        root.addWidget(self.tabs, 2)

    # ------------------------------------------------------------------
    # 期货特有参数控制条（杠杆 / 保证金 / 乘数 / 交割日）
    # ------------------------------------------------------------------
    def _build_futures_params_bar(self) -> None:
        from .widgets import ToolBar
        from PyQt6.QtCore import QDate

        self.futures_bar = ToolBar(QHBoxLayout())
        bar = self.futures_bar.layout()

        bar.addWidget(QLabel("杠杆"))
        self.lev_sp = QSpinBox()
        self.lev_sp.setRange(1, 20)
        self.lev_sp.setValue(int(round(self._futures_params["leverage"])))
        self.lev_sp.setToolTip("杠杆倍数（=1/保证金率）；影响保证金占用与潜在收益/风险")
        self.lev_sp.valueChanged.connect(self._sync_futures_params)
        bar.addWidget(self.lev_sp)

        bar.addWidget(QLabel("保证金%"))
        self.margin_ds = QDoubleSpinBox()
        self.margin_ds.setRange(1.0, 50.0)
        self.margin_ds.setSuffix("%")
        self.margin_ds.setDecimals(1)
        self.margin_ds.setValue(round(self._futures_params["margin_rate"] * 100, 1))
        self.margin_ds.setToolTip("保证金比例（与杠杆联动；改动其一另一方自动调整）")
        self.margin_ds.valueChanged.connect(self._sync_futures_params)
        bar.addWidget(self.margin_ds)

        bar.addWidget(QLabel("乘数"))
        self.mult_sp = QSpinBox()
        self.mult_sp.setRange(1, 1000)
        self.mult_sp.setValue(int(round(self._futures_params["multiplier"])))
        self.mult_sp.setToolTip("合约乘数（每手对应标的单位数，如 rb=10、IF=300）；"
                                "直接影响盈亏与保证金的资金规模")
        self.mult_sp.valueChanged.connect(self._sync_futures_params)
        bar.addWidget(self.mult_sp)

        bar.addWidget(QLabel("交割日"))
        self.delivery_de = QDateEdit()
        self.delivery_de.setCalendarPopup(True)
        self.delivery_de.setMinimumDate(QDate(2000, 1, 1))
        self.delivery_de.setMaximumDate(QDate(2100, 1, 1))
        self.delivery_de.setSpecialValueText("不限制")
        dd = self._futures_params.get("delivery_date")
        if dd:
            try:
                self.delivery_de.setDate(QDate.fromString(dd, "yyyy-MM-dd"))
            except Exception:  # noqa: BLE001
                self.delivery_de.setDate(self.delivery_de.minimumDate())
        else:
            self.delivery_de.setDate(self.delivery_de.minimumDate())
        self.delivery_de.dateChanged.connect(self._sync_futures_params)
        bar.addWidget(self.delivery_de)

        # 联动 AI 预测：携带当前品种跳转，进行板块联动分析
        self.link_btn = QPushButton("🔗 联动AI预测")
        self.link_btn.setObjectName("secondary")
        self.link_btn.setToolTip("携带当前学习品种跳转到「AI预测」板块，"
                                "查看与回测结果联动的研判")
        self.link_btn.clicked.connect(self._goto_predict)
        bar.addWidget(self.link_btn)
        bar.addStretch(1)

    def _sync_futures_params(self, *_):
        """期货参数变更 → 联动杠杆/保证金 → 持久化 → 实时下发引擎（下代生效）。"""
        lev = self.lev_sp.value()
        margin_rate = (1.0 / lev) if lev > 0 else 0.10
        # 保证金显示始终等于 1/杠杆（避免两控件互相打架）
        self.margin_ds.blockSignals(True)
        self.margin_ds.setValue(round(margin_rate * 100, 1))
        self.margin_ds.blockSignals(False)

        fp = self._futures_params
        fp["leverage"] = float(lev)
        fp["margin_rate"] = margin_rate
        fp["multiplier"] = float(self.mult_sp.value())
        dd = self.delivery_de.date()
        fp["delivery_date"] = (None if dd == self.delivery_de.minimumDate()
                               else dd.toString("yyyy-MM-dd"))

        # 持久化（自动保存，无需手动触发）
        if self._bt_store is not None:
            try:
                self._bt_store.save_state("futures_params", dict(fp))
            except Exception:  # noqa: BLE001
                pass
        # 实时下发引擎：下一代回测起即采用新参数
        if self._engine is not None:
            self._engine.futures_params = dict(fp)

        if not self._restoring:
            self._log(
                f"⚙️ 期货参数已更新：杠杆 {lev}x · 保证金 {margin_rate*100:.1f}% · "
                f"乘数 {fp['multiplier']:.0f}"
                + (f" · 交割 {fp['delivery_date']}" if fp["delivery_date"] else " · 交割不限制")
                + "，下代回测自动生效")

    def _goto_predict(self) -> None:
        """联动跳转：携带当前学习品种到「AI预测」板块并预选该品种。"""
        sym = (self._engine.symbol() if self._engine
               else (self.mdm.universe[0][0] if self.mdm.universe else None))
        if sym is None:
            return
        mw = self.window()
        if mw is None or not hasattr(mw, "_goto_page"):
            return
        mw._goto_page("predict")
        # 注意：page.PAGE_KEY 在 MainWindow 中被覆写为注册 key（"predict_ops"），
        # 故用导航后的当前页控件而非比对 PAGE_KEY。
        pg = mw.stack.currentWidget() if hasattr(mw, "stack") else None
        if pg is not None and hasattr(pg, "set_symbol"):
            try:
                pg.set_symbol(sym, "D")
            except Exception:  # noqa: BLE001
                pass

    def _lib_to_predict(self, idx: int) -> None:
        """盈利策略库行内「🔮 预测」：跳转到 AI预测 并预载该策略基因。"""
        if idx < 0 or idx >= len(self._lib_entries):
            return
        e = self._lib_entries[idx]
        sym = e.get("symbol")
        gene = e.get("gene")
        if not sym:
            return
        mw = self.window()
        if mw is None or not hasattr(mw, "_goto_page"):
            return
        mw._goto_page("predict")
        pg = mw.stack.currentWidget() if hasattr(mw, "stack") else None
        if pg is not None and hasattr(pg, "set_symbol"):
            try:
                pg.set_symbol(sym, "D", gene=gene)
            except Exception:  # noqa: BLE001
                pass

    def run_manual_for(self, symbol: str, gene: dict = None) -> None:
        """供「AI预测」页联动：切到手动回测模式并用指定策略基因跑回测。"""
        if self._closed:
            return
        # 切到手动模式（与自动进化互斥）
        if self._manual_mode is False:
            self._rb_manual.setChecked(True)  # 触发 _on_mode_toggle → 手动
        # 选择品种
        sidx = self._manual_sym_cb.findData(symbol) if self._manual_sym_cb else -1
        if sidx < 0 and self._manual_sym_cb is not None:
            self._populate_manual_symbols()
            sidx = self._manual_sym_cb.findData(symbol)
        if sidx >= 0:
            self._manual_sym_cb.setCurrentIndex(sidx)
        # 选「盈利库最优」并注入精确基因（避免与 lib 顺序不一致）
        if gene is not None:
            self._manual_gene_override = dict(gene)
            midx = self._manual_strat_cb.findData("__lib__") \
                if self._manual_strat_cb else -1
            if midx >= 0:
                self._manual_strat_cb.setCurrentIndex(midx)
        self._run_manual()

    def _fill_perf_chips(self, m: dict) -> None:
        """绩效指标卡：夏普/回撤/年化/卡玛/胜率/盈亏比（与预测板块同口径）。"""
        p = PALETTE[self._theme]

        def setk(key, val, color=""):
            c = self._perf_chips.get(key)
            if c:
                c.set_value(val, color)

        tr = m.get("total_return"); dd = m.get("max_drawdown")
        ann = m.get("annual_return"); sh = m.get("sharpe")
        wr = m.get("win_rate"); pf = m.get("profit_factor")
        setk("pf_sharpe", format_metric("sharpe", sh))
        setk("pf_dd", format_metric("max_drawdown", dd),
             p["up"] if dd else "")
        setk("pf_annual", format_metric("annual_return", ann),
             p["down"] if (ann or 0) >= 0 else p["up"])
        calmar = (ann / dd) if (ann is not None and dd and dd > 0) else None
        setk("pf_calmar", f"{calmar:.2f}" if calmar is not None else "--",
             p["down"] if (calmar or 0) >= 0 else p["up"])
        setk("pf_wr", format_metric("win_rate", wr))
        setk("pf_pf", format_metric("profit_factor", pf))

    # ------------------------------------------------------------------
    # 自动驱动：页面显示即启动，无任何用户操作
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._auto_started:
            self._auto_started = True
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(600, self._start_auto)

    def _start_auto(self) -> None:
        if self._closed:
            return
        try:
            from ..strategy.auto_evolve import EvolutionEngine, load_profitable
            self._engine = EvolutionEngine(
                self.mdm.feed, self.mdm.universe,
                futures_params=dict(self._futures_params))
            if self._bt_store is not None:
                try:  # 启动维护：限容 + 合并 WAL，保持长期高效
                    self._bt_store.prune()
                    self._bt_store.checkpoint()
                except Exception:  # noqa: BLE001
                    pass
            restored = self._restore_from_db()
            n_lib = len(load_profitable())
            if restored:
                self._log(f"♻️ 已从本地数据库恢复上次进度：第 "
                          f"{self._engine.generation} 代 · 累计评估 "
                          f"{self._engine.evaluated_total} 个策略 · 盈利库 "
                          f"{n_lib} 条，从「{self._engine.symbol_name()}」"
                          f"断点续跑")
            else:
                self._log(f"🟢 系统启动：自我学习引擎就绪（历史盈利策略库 "
                          f"{n_lib} 条），从「{self._engine.symbol_name()}」"
                          f"开始进化")
            self._fill_library(load_profitable())
            self._chips["profitable"].set_value(str(n_lib))
            self._next_generation()
        except Exception as e:  # noqa: BLE001
            self.info.setText(f"引擎启动失败：{e}（{ERR_RETRY_MS // 1000}s 后自动重试）")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(ERR_RETRY_MS, self._start_auto)

    # ------------------------------------------------------------------
    # 持久化：启动恢复（数据库 → 引擎断点 + UI 状态）
    # ------------------------------------------------------------------
    def _restore_from_db(self) -> bool:
        """从本地数据库恢复引擎断点、历史记录、日志与上次界面状态。"""
        if self._bt_store is None:
            return False
        restored = False
        self._restoring = True
        try:
            # ① 引擎断点（代数/种群/最优/品种进度）
            st = self._bt_store.load_state("engine")
            if st and self._engine is not None:
                restored = self._engine.restore_state(st)

            # ② 历史回测记录表（持久层为准，最近 300 条）
            hist = self._bt_store.recent_history(300)
            if hist:
                self._fill_history(hist)

            # ③ 学习日志回放（最近 100 条，倒序库 → 正序插回）
            logs = self._bt_store.recent_logs(100)
            for row in reversed(logs):
                ts = str(row.get("ts", ""))[11:19]
                from PyQt6.QtWidgets import QListWidgetItem
                self.log_list.insertItem(
                    0, QListWidgetItem(f"[{ts}] {row.get('text', '')}"))
            while self.log_list.count() > 200:
                self.log_list.takeItem(self.log_list.count() - 1)

            # ④ 上次快照 → KPI / 资金曲线 / 当代种群表
            snap = self._bt_store.load_state("last_snapshot")
            if snap:
                self._last_snapshot = snap
                self._render_snapshot_ui(snap)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._restoring = False
        return restored

    def _render_snapshot_ui(self, snap: dict) -> None:
        """把一份进化快照渲染到 KPI/曲线/种群表（恢复与实时共用）。"""
        p = PALETTE[self._theme]
        try:
            self._chips["symbol"].set_value(snap.get("symbol_name", "--"))
            self._chips["generation"].set_value(
                f"第 {snap.get('generation', 0)} 代")
            self._chips["evaluated"].set_value(
                f"{snap.get('evaluated_total', 0):,}")
            bo = snap.get("best_overall")
            if bo:
                self._chips["best_fit"].set_value(f"{bo['fitness']:.1f}")
                tr = (bo.get("metrics") or {}).get("total_return")
                self._chips["best_ret"].set_value(
                    _pct(tr), p["down"] if (tr or 0) >= 0 else p["up"])
            self._update_curves(snap)
            self._fill_population(snap.get("ranked") or [])
            # 期货参数控制条恢复到上次配置
            self._restore_futures_controls()
        except Exception:  # noqa: BLE001
            pass

    def _restore_futures_controls(self) -> None:
        """把已恢复/默认的期货参数同步到控制条显示（不触发持久化写库）。"""
        fp = self._futures_params
        try:
            self._restoring = True
            self.lev_sp.blockSignals(True)
            self.margin_ds.blockSignals(True)
            self.mult_sp.blockSignals(True)
            self.delivery_de.blockSignals(True)
            self.lev_sp.setValue(int(round(fp.get("leverage", 10))))
            self.margin_ds.setValue(round(fp.get("margin_rate", 0.10) * 100, 1))
            self.mult_sp.setValue(int(round(fp.get("multiplier", 10))))
            dd = fp.get("delivery_date")
            if dd:
                self.delivery_de.setDate(QDate.fromString(dd, "yyyy-MM-dd"))
            else:
                self.delivery_de.setDate(self.delivery_de.minimumDate())
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.lev_sp.blockSignals(False)
            self.margin_ds.blockSignals(False)
            self.mult_sp.blockSignals(False)
            self.delivery_de.blockSignals(False)
            self._restoring = False

    # ------------------------------------------------------------------
    # 模式切换：自动进化 / 手动回测（互斥）
    # ------------------------------------------------------------------
    def _build_mode_switch(self) -> None:
        self._mode_row = QHBoxLayout()
        self._mode_row.setSpacing(10)
        self._mode_row.addWidget(QLabel("运行模式"))
        self._rb_auto = QRadioButton("自动进化（AI 自我学习）")
        self._rb_manual = QRadioButton("手动回测（自定义期货策略）")
        self._rb_auto.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self._rb_auto)
        bg.addButton(self._rb_manual)
        self._rb_auto.toggled.connect(self._on_mode_toggle)
        self._rb_manual.toggled.connect(self._on_mode_toggle)
        self._mode_row.addWidget(self._rb_auto)
        self._mode_row.addWidget(self._rb_manual)
        self._mode_row.addStretch(1)

    def _build_manual_panel(self) -> None:
        self._manual_group = QGroupBox("🧪 手动回测 · 自定义期货策略")
        g = QVBoxLayout(self._manual_group)
        g.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("品种"))
        self._manual_sym_cb = QComboBox()
        self._manual_sym_cb.setMinimumWidth(180)
        row1.addWidget(self._manual_sym_cb, 1)
        row1.addWidget(QLabel("策略因子"))
        self._manual_strat_cb = QComboBox()
        self._manual_strat_cb.setMinimumWidth(200)
        row1.addWidget(self._manual_strat_cb, 1)
        g.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self._manual_run_btn = QPushButton("▶ 运行手动回测")
        self._manual_run_btn.setObjectName("primary")
        self._manual_run_btn.clicked.connect(self._run_manual)
        row2.addWidget(self._manual_run_btn)
        self._manual_hint = QLabel(
            "复用当前「期货参数」控制条的杠杆/保证金/乘数/交割日；"
            "交割日到达时引擎将强制平仓（与真实期货规则一致）。")
        self._manual_hint.setObjectName("sub")
        self._manual_hint.setWordWrap(True)
        row2.addWidget(self._manual_hint, 1)
        g.addLayout(row2)

    def _on_mode_toggle(self, *_args) -> None:
        auto = self._rb_auto.isChecked()
        # 互斥单选按钮切换会触发两次 toggled（自动取消 + 手动选中各一次），
        # 用 entering_manual 确保「品种下拉刷新 + 配置预填」只在真正切入手动模式
        # 那一次执行，避免第二次触发把预填结果又重置回首项。
        entering_manual = (not auto) and (not self._manual_mode)
        self._manual_mode = not auto
        if self._manual_group is not None:
            self._manual_group.setVisible(not auto)
        if auto:
            self.info.setText("🔄 已切回自动进化模式，系统将继续自我学习…")
            self._log("🔄 切回自动进化模式（手动回测暂停）")
            if self._engine is not None and not self._gen_running:
                self._next_generation()
        else:
            self.info.setText("🧪 手动回测模式：选择品种与策略后点击「运行手动回测」"
                              "（自动进化已暂停）。")
            self._log("🔧 切换至手动回测模式（自动进化暂停）")
            if entering_manual:
                self._populate_manual_symbols()
                self._populate_manual_strategies()
                # R7-7.2：首次进入手动模式时，用上次保存的手动配置预填面板
                self._maybe_restore_manual_config()

    def _populate_manual_symbols(self) -> None:
        cb = self._manual_sym_cb
        if cb is None:
            return
        # R5.3：扫描 data/real_samples/，给已有真实样本落盘的品种打标「📦真实」
        real_set: set[str] = set()
        try:
            sample_dir = os.path.join(get_data_dir(), "real_samples")
            if os.path.isdir(sample_dir):
                for fn in os.listdir(sample_dir):
                    # 文件名形如 rb_SHFE_D.csv → 还原为 rb.SHFE
                    if fn.endswith("_D.csv"):
                        stem = fn[:-len("_D.csv")]
                        real_set.add(stem.replace("_", ".", 1))
        except Exception:  # noqa: BLE001
            real_set = set()
        cb.blockSignals(True)
        cb.clear()
        for r in self.mdm.universe:
            sym = f"{r[0]}.{r[3]}"
            tag = " 📦真实" if sym in real_set else ""
            cb.addItem(f"{r[1]}（{sym}）{tag}", sym)
        cb.blockSignals(False)
        # 与品种联动刷新策略下拉（仅在未连接时连接一次）
        try:
            cb.currentIndexChanged.disconnect(self._populate_manual_strategies)
        except Exception:  # noqa: BLE001
            pass
        cb.currentIndexChanged.connect(self._populate_manual_strategies)

    def _populate_manual_strategies(self) -> None:
        cb = self._manual_strat_cb
        if cb is None:
            return
        sym = self._manual_sym_cb.currentData() if self._manual_sym_cb else None
        cb.blockSignals(True)
        cb.clear()
        presets = [
            ("ma_cross", "均线交叉（多空）"),
            ("donchian_break", "唐奇安突破（做多）"),
            ("rsi_reversal", "RSI 反转（多空）"),
            ("boll_break", "布林突破（做多）"),
            ("momentum", "动量（多空）"),
        ]
        for k, label in presets:
            cb.addItem(label, k)
        try:
            from ..strategy.auto_evolve import load_profitable
            lib = [e for e in load_profitable() if e.get("symbol") == sym]
            if lib:
                cb.addItem(f"盈利库最优（{sym} · {len(lib)} 条）", "__lib__")
        except Exception:  # noqa: BLE001
            pass
        cb.blockSignals(False)

    def _maybe_restore_manual_config(self) -> None:
        """R7-7.2：首次进入手动模式时，用本地库保存的上次手动配置预填面板。

        仅预填一次（_manual_config_restored 标志）；用户手动改动后不再覆盖，
        避免反复切模式时被旧配置打回。
        """
        if getattr(self, "_manual_config_restored", False):
            return
        if self._bt_store is None:
            return
        cfg = None
        try:
            cfg = self._bt_store.load_state("last_manual_config")
        except Exception:  # noqa: BLE001
            cfg = None
        if not isinstance(cfg, dict) or not cfg.get("symbol"):
            return
        cb = self._manual_sym_cb
        scb = self._manual_strat_cb
        if cb is None:
            return
        sidx = cb.findData(cfg["symbol"])
        if sidx < 0:
            return
        try:
            self._restoring = True
            cb.setCurrentIndex(sidx)   # 触发 _populate_manual_strategies 刷新策略下拉
            if scb is not None:
                lib = []
                try:
                    from ..strategy.auto_evolve import load_profitable
                    lib = [e for e in load_profitable() if e.get("symbol") == cfg["symbol"]]
                except Exception:  # noqa: BLE001
                    lib = []
                midx = scb.findData("__lib__") if lib else -1
                if midx >= 0:
                    scb.setCurrentIndex(midx)
            # 精确基因用 override 注入，保证「恢复该次完整配置」语义
            self._manual_gene_override = dict(cfg["gene"]) if cfg.get("gene") else None
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._restoring = False
        self._manual_config_restored = True
        self._log(f"♻️ 已预填上次手动回测配置：{cfg.get('symbol')}")

    @staticmethod
    def _manual_gene(preset: str) -> dict:
        """根据下拉选项构造一个合法的策略基因（供 GeneStrategy 回测）。"""
        presets = {
            "ma_cross": {"entry": "ma_cross", "params": {"fast": 5, "slow": 20},
                         "stop_mult": 2.0, "tp_mult": 0.0,
                         "allow_long": True, "allow_short": True, "lots": 1},
            "donchian_break": {"entry": "donchian_break", "params": {"period": 20},
                               "stop_mult": 2.0, "tp_mult": 0.0,
                               "allow_long": True, "allow_short": False, "lots": 1},
            "rsi_reversal": {"entry": "rsi_reversal",
                             "params": {"period": 14, "low": 30, "high": 70},
                             "stop_mult": 2.0, "tp_mult": 0.0,
                             "allow_long": True, "allow_short": True, "lots": 1},
            "boll_break": {"entry": "boll_break",
                           "params": {"period": 20, "num_std": 2.0},
                           "stop_mult": 2.0, "tp_mult": 0.0,
                           "allow_long": True, "allow_short": False, "lots": 1},
            "momentum": {"entry": "momentum", "params": {"period": 10, "th": 0.02},
                         "stop_mult": 2.0, "tp_mult": 0.0,
                         "allow_long": True, "allow_short": True, "lots": 1},
        }
        return dict(presets.get(preset, presets["ma_cross"]))

    def _run_manual(self) -> None:
        """在后台线程用 TradingEngine+BacktestBroker 跑一次用户自定义期货回测。"""
        if self._closed or self._manual_running:
            return
        sym = self._manual_sym_cb.currentData() if self._manual_sym_cb else None
        if not sym:
            return
        row = next((r for r in self.mdm.universe
                    if f"{r[0]}.{r[3]}" == sym), None)
        if row is None:
            self.info.setText(f"⚠️ 未找到品种 {sym} 的合约规格")
            return

        # 精确基因优先（AI预测联动注入 / 历史记录「复跑」注入），
        # 确保「恢复该次完整配置」时严格使用原基因而非预设默认值。
        gene_override = getattr(self, "_manual_gene_override", None)
        if gene_override is not None:
            gene = dict(gene_override)
            self._manual_gene_override = None
        else:
            preset = self._manual_strat_cb.currentData() if self._manual_strat_cb else "ma_cross"
            gene = self._manual_gene(preset)
            # 选「盈利库最优」且当前品种有入库策略，则直接复用其基因
            if preset == "__lib__":
                try:
                    from ..strategy.auto_evolve import load_profitable
                    lib = [e for e in load_profitable() if e.get("symbol") == sym]
                    if lib:
                        gene = dict(lib[0]["gene"])
                except Exception:  # noqa: BLE001
                    pass

        # R7-7.2：持久化最近一次手动配置（品种+策略+精确基因），
        # 下次进入手动模式时自动预填（重启不丢）。
        if self._bt_store is not None:
            try:
                preset = self._manual_strat_cb.currentData() if self._manual_strat_cb else "ma_cross"
                self._bt_store.save_state("last_manual_config",
                                          {"symbol": sym, "preset": preset, "gene": gene})
            except Exception:  # noqa: BLE001
                pass

        fp = dict(self._futures_params)
        lev = float(fp.get("leverage", 10.0))
        margin_rate = float(fp.get("margin_rate", 1.0 / lev))
        mult = float(fp.get("multiplier", row[4] if len(row) > 4 else 10.0))
        close_today_ratio = float(fp.get("close_today_ratio", 0.5))
        delivery_date = fp.get("delivery_date")
        start = self._engine.start if self._engine else "2000-01-01"
        end = self._engine.end if self._engine else "2100-01-01"
        period = self._engine.period if self._engine else "D"

        self._manual_running = True
        self._manual_run_btn.setEnabled(False)
        self.info.setText(f"🧪 手动回测中：{row[1]}（{sym}）· 杠杆 {lev}× · "
                          f"乘数 {mult} · 保证金 {margin_rate:.0%}"
                          f"{' · 交割日 ' + str(delivery_date) if delivery_date else ''} …")

        def work():
            from ..config.settings import Config
            from ..data.base import Contract
            from ..data.contract_specs import get_contract_spec
            from ..backtest.backtester import Backtester
            from ..strategy.auto_evolve import GeneStrategy
            cfg = Config()
            cfg.account.leverage = lev
            cfg.account.margin_rate = margin_rate
            cfg.account.multiplier = mult
            cfg.account.close_today_ratio = close_today_ratio
            spec = get_contract_spec(sym)
            # R4.1：手续费用真实品种规格（UI 未提供该字段）
            cfg.account.commission_per_lot = spec["commission_per_lot"]
            cfg.account.initial_capital = 1_000_000.0
            cfg.backtest.start_cash = 1_000_000.0
            # 放松风控以展示策略原始表现（与自动进化一致）
            cfg.risk.max_single_loss = 1e12
            cfg.risk.max_daily_loss = 1e12
            cfg.risk.max_drawdown = 0.99
            cfg.risk.max_position_per_symbol = 100
            cfg.risk.max_total_position_ratio = 0.98
            cfg.risk.max_order_qty = 100
            contract = Contract(
                symbol=sym, exchange=spec["exchange"], multiplier=mult,
                min_price_tick=spec["min_price_tick"],
                lot_size=1, margin_rate=margin_rate,
                commission_per_lot=spec["commission_per_lot"],
                trading_hours=None, delivery_date=delivery_date, leverage=lev,
                close_today_commission_ratio=close_today_ratio)
            logger = _BufLogger()
            bt = Backtester(cfg, self.mdm.feed, logger=logger)
            bt.add_contract(contract)
            bt.add_strategy(GeneStrategy(sym, gene))
            res = bt.run(sym, start, end, period, warmup=60)
            return {"gene": gene, "res": res, "sym": sym, "row": row,
                    "mult": mult, "logger": logger}

        self._run_worker(work, self._on_manual_done, on_err=self._on_manual_err)

    def _on_manual_done(self, result: dict) -> None:
        self._manual_running = False
        if self._manual_run_btn is not None:
            self._manual_run_btn.setEnabled(True)
        if self._closed:
            return
        from ..strategy.auto_evolve import (
            describe_gene, gene_signature, fitness, is_profitable, load_profitable)

        res = result["res"]
        gene = result["gene"]
        sym = result["sym"]
        row = result["row"]
        m = res["metrics"]
        fit = fitness(m)
        ok, reasons = is_profitable(m)
        desc = describe_gene(gene)
        sig = gene_signature(gene)
        period = self._engine.period if self._engine else "D"
        bo = {
            "symbol": sym, "symbol_name": row[1], "desc": desc,
            "fitness": fit, "profitable": ok, "reasons": reasons,
            "metrics": m, "equity_curve": res["equity_curve"],
            "gene": gene, "signature": sig,
        }
        snap = {
            "symbol": sym, "symbol_name": row[1], "period": period,
            "generation": MANUAL_GEN, "gen_in_symbol": 0,
            "best_overall": bo,
            "gen_best_curve": res["equity_curve"],
            "ranked": [{"desc": desc, "signature": sig, "gene": gene,
                        "metrics": m, "fitness": fit,
                        "profitable": ok, "reasons": reasons}],
            # R6：手动回测也透传成交记录（用于详情对话框）
            "gen_best_trades": res.get("trades", []),
            "library": load_profitable(),
            "new_profitable": [],
            "evaluated_total": 0,
            "profitable_total": len(load_profitable()),
            "symbol_done": False,
        }
        self._last_manual = result
        self._last_manual_logger = result.get("logger")
        # 复用与自动进化一致的渲染链路：资金曲线 + 绩效指标卡
        self._update_curves(snap)
        self._fill_library(snap.get("library") or [])
        if self._bt_store is not None:
            try:
                hid = self._bt_store.add_history(snap)
                snap["_history_id"] = hid
            except Exception:  # noqa: BLE001
                pass
        self._prepend_history_row(snap)
        self._log(f"🧪 手动回测完成：{row[1]} · 「{desc}」收益 "
                  f"{_pct(m.get('total_return'))} 夏普 {m.get('sharpe')} "
                  f"回撤 {_pct(m.get('max_drawdown'))} 适应度 {fit:.1f}")
        self.info.setText(
            f"✅ 手动回测完成：{row[1]} · 「{desc}」"
            f"总收益 {_pct(m.get('total_return'))} ｜ 夏普 {m.get('sharpe')} ｜ "
            f"最大回撤 {_pct(m.get('max_drawdown'))} ｜ 已写入历史记录。")
        self._toast(
            f"手动回测完成 · {row[1]} · 收益 {_pct(m.get('total_return'))} · "
            f"夏普 {m.get('sharpe')} · 回撤 {_pct(m.get('max_drawdown'))}",
            duration=4000)

    def _on_manual_err(self, msg: str) -> None:
        self._manual_running = False
        if self._manual_run_btn is not None:
            self._manual_run_btn.setEnabled(True)
        if self._closed:
            return
        self.info.setText(f"⚠️ 手动回测异常：{msg}")
        self._log(f"⚠️ 手动回测异常：{msg}")

    def _next_generation(self) -> None:
        """驱动一代进化（后台线程），完成后自动排程下一代。"""
        if self._closed or self._engine is None or self._gen_running:
            return
        if self._manual_mode:
            # 手动回测模式：暂停自动进化，避免覆盖手动结果
            return
        self._gen_running = True
        eng = self._engine
        sym_name, sym = eng.symbol_name(), eng.symbol()
        gen_no = eng.generation + 1
        self.info.setText(
            f"⚙️ 自动学习中：第 {gen_no} 代 · {sym_name}（{sym}）"
            f"· 种群 {eng.POP_SIZE} 个策略因子回测评估…（全程无需操作）")
        # 流水线状态灯：前三阶段亮起「进行中」
        self._set_stage(0, "good", "生成中",
                        f"第 {gen_no} 代：随机组合/交叉/变异产生 {eng.POP_SIZE} 个策略基因")
        self._set_stage(1, "good", "回测中", "逐一送入历史行情回测引擎")
        self._set_stage(2, "good", f"第{gen_no}代", "遗传算法逐代进化寻优")
        self._set_stage(3, "neutral", "等待", "回测完成后自动判定")
        self._set_stage(4, "neutral", "等待", "盈利策略将自动同步AI预测")

        bt_store = self._bt_store

        def work():
            snap = eng.step()
            # 自动持久化（在后台线程内完成，零 GUI 阻塞）：
            #   引擎断点 + 最新快照 + 本代历史记录
            if bt_store is not None:
                try:
                    bt_store.save_state("engine", eng.to_state())
                    slim = {k: v for k, v in snap.items() if k != "library"}
                    bt_store.save_state("last_snapshot", slim)
                    hid = bt_store.add_history(snap)
                    snap["_history_id"] = hid
                except Exception:  # noqa: BLE001
                    pass
            return snap

        self._run_worker(work, self._on_gen_done, on_err=self._on_gen_err)

    def _on_gen_done(self, snap: dict) -> None:
        self._gen_running = False
        if self._closed:
            return
        # 手动回测模式下：跳过 UI 刷新（不覆盖手动结果），仅保留已落库的快照
        if self._manual_mode:
            return
        self._last_snapshot = snap
        ranked = snap.get("ranked") or []
        best = ranked[0] if ranked else None
        new_prof = snap.get("new_profitable") or []

        # ---- 状态灯收尾 ----
        self._set_stage(0, "good", f"{len(ranked)} 因子", "本代已生成并评估的策略因子数")
        self._set_stage(1, "good", "完成", "全部基因历史回测完成")
        self._set_stage(2, "good", f"第{snap['generation']}代",
                        f"{snap['symbol_name']} 第 {snap['gen_in_symbol']}/"
                        f"{snap['gens_per_symbol']} 轮")
        if new_prof:
            self._set_stage(3, "good", f"+{len(new_prof)} 盈利",
                            "；".join(e["desc"][:26] for e in new_prof[:2]))
            self._set_stage(4, "good", f"库 {snap['profitable_total']} 条",
                            "已自动写入策略库，AI预测实时读取生效")
        else:
            self._set_stage(3, "bad", "未达标",
                            "本代无策略通过盈利判定（收益/夏普/回撤/胜率/交易数联合阈值）")
            self._set_stage(4,
                            "good" if snap["profitable_total"] else "neutral",
                            f"库 {snap['profitable_total']} 条",
                            "策略库现有盈利策略持续对AI预测生效")

        # ---- KPI ----
        p = PALETTE[self._theme]
        self._chips["symbol"].set_value(snap["symbol_name"])
        self._chips["generation"].set_value(f"第 {snap['generation']} 代")
        self._chips["evaluated"].set_value(f"{snap['evaluated_total']:,}")
        self._chips["profitable"].set_value(
            str(snap["profitable_total"]),
            p["down"] if snap["profitable_total"] else "")
        bo = snap.get("best_overall")
        if bo:
            self._chips["best_fit"].set_value(f"{bo['fitness']:.1f}")
            tr = (bo["metrics"] or {}).get("total_return")
            self._chips["best_ret"].set_value(
                _pct(tr), p["down"] if (tr or 0) >= 0 else p["up"])

        # ---- 资金曲线：当代最优 vs 历史最优 ----
        self._update_curves(snap)

        # ---- 表格 ----
        self._fill_population(ranked)
        self._fill_library(snap.get("library") or [])
        self._prepend_history_row(snap)

        # ---- 日志 ----
        if best:
            m = best["metrics"] or {}
            self._log(f"第 {snap['generation']} 代（{snap['symbol_name']}）完成："
                      f"最优「{best['desc']}」收益 {_pct(m.get('total_return'))} "
                      f"夏普 {m.get('sharpe')} 适应度 {best['fitness']}")
        for e in new_prof:
            self._log(f"💰 盈利策略入库并同步AI预测：{e['symbol_name']} · {e['desc']}"
                      f"（收益 {_pct(e['metrics'].get('total_return'))}，"
                      f"夏普 {e['metrics'].get('sharpe')}）")
        if snap.get("symbol_done"):
            self._log(f"🔄 品种轮换：{snap['symbol_name']} 学习完毕，"
                      f"自动切换至「{snap.get('next_symbol_name', '')}」")

        # ---- 状态行 + 排程下一代 ----
        self.info.setText(
            f"✅ 第 {snap['generation']} 代完成 · {snap['symbol_name']}　"
            f"累计评估 {snap['evaluated_total']} 个策略，盈利库 "
            f"{snap['profitable_total']} 条（已自动同步AI预测）。"
            f"系统持续自我进化中，无需任何操作…")
        self._schedule_next()

    def _on_gen_err(self, msg: str) -> None:
        self._gen_running = False
        if self._closed:
            return
        self._log(f"⚠️ 本代进化异常：{msg}（自动重试）")
        self.info.setText(f"⚠️ 学习过程出现异常：{msg}，{ERR_RETRY_MS // 1000}s 后自动重试…")
        self._schedule_next(ERR_RETRY_MS)

    def _schedule_next(self, delay: int | None = None) -> None:
        from PyQt6.QtCore import QTimer
        if delay is None:
            delay = GEN_INTERVAL_MS if self.isVisible() else GEN_INTERVAL_HIDDEN_MS
        QTimer.singleShot(delay, self._next_generation)

    # ------------------------------------------------------------------
    # 渲染辅助
    # ------------------------------------------------------------------
    def _set_stage(self, idx: int, level: str, value: str, tip: str = "") -> None:
        try:
            self._stage_tiles[idx].set_status(level, value, tip)
        except Exception:  # noqa: BLE001
            pass

    def _log(self, text: str) -> None:
        from PyQt6.QtWidgets import QListWidgetItem
        from datetime import datetime
        item = QListWidgetItem(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        self.log_list.insertItem(0, item)
        while self.log_list.count() > 200:
            self.log_list.takeItem(self.log_list.count() - 1)
        # 自动持久化日志（WAL 单条插入亚毫秒级；恢复回放期间不重复写）
        if self._bt_store is not None and not self._restoring:
            self._bt_store.add_log(text)

    def _update_curves(self, snap: dict) -> None:
        bo = snap.get("best_overall") or {}
        bo_curve = bo.get("equity_curve") or []
        gen_curve = snap.get("gen_best_curve") or []
        # 资金/收益率曲线 + 最大回撤阴影（BacktestPerfChart）
        eq = [float(e[1]) for e in (bo_curve or gen_curve)] if (bo_curve or gen_curve) else []
        metrics = bo.get("metrics") or {}
        if eq:
            self.chart.set_data(eq, has_trades=True)
            self.chart.set_metrics(metrics)
            self.sec_equity.set_badge((bo.get("desc") or "")[:30] or "自动更新")
        # 绩效指标卡（与预测板块同口径）
        self._fill_perf_chips(metrics)

    def _fill_population(self, ranked: list) -> None:
        self.pop_tbl.setRowCount(0)
        prepare_table(self.pop_tbl, self._theme)
        rows = ranked[:12]
        self.pop_tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            m = r["metrics"] or {}
            self.pop_tbl.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            d_item = QTableWidgetItem(r["desc"])
            d_item.setToolTip(r["desc"])
            self.pop_tbl.setItem(i, 1, d_item)
            tr = m.get("total_return")
            tr_item = QTableWidgetItem(_pct(tr))
            tr_item.setForeground(_qcolor("up" if (tr or 0) >= 0 else "down"))
            self.pop_tbl.setItem(i, 2, tr_item)
            sh = m.get("sharpe")
            self.pop_tbl.setItem(
                i, 3, QTableWidgetItem(f"{sh}" if sh is not None else "--"))
            dd_item = QTableWidgetItem(_pct(m.get("max_drawdown")))
            dd_item.setForeground(_qcolor("up"))
            self.pop_tbl.setItem(i, 4, dd_item)
            self.pop_tbl.setItem(i, 5, QTableWidgetItem(_pct(m.get("win_rate"))))
            self.pop_tbl.setItem(
                i, 6, QTableWidgetItem(str(m.get("num_closing_trades", "--"))))
            self.pop_tbl.setItem(i, 7, QTableWidgetItem(f"{r['fitness']:.1f}"))
            if r["profitable"]:
                v_item = QTableWidgetItem("✅ 可盈利")
                v_item.setForeground(_qcolor("up"))
            else:
                v_item = QTableWidgetItem("✕ 未达标")
                v_item.setToolTip("未达标原因：" + "；".join(r.get("reasons") or []))
                v_item.setForeground(_qcolor("down"))
            self.pop_tbl.setItem(i, 8, v_item)
            if r["profitable"]:
                for c in range(self.pop_tbl.columnCount()):
                    it = self.pop_tbl.item(i, c)
                    if it is not None:
                        it.setBackground(_qcolor_bg("#10b981", alpha=36))

    def _fill_library(self, lib: list) -> None:
        self.lib_tbl.setRowCount(0)
        prepare_table(self.lib_tbl, self._theme)
        rows = lib[:60]
        self._lib_entries = list(rows)
        self.lib_tbl.setRowCount(len(rows))
        for i, e in enumerate(rows):
            m = e.get("metrics") or {}
            self.lib_tbl.setItem(
                i, 0, QTableWidgetItem(f"{e.get('symbol_name', '')} "
                                       f"({e.get('symbol', '')})"))
            d_item = QTableWidgetItem(e.get("desc", ""))
            d_item.setToolTip(e.get("desc", ""))
            self.lib_tbl.setItem(i, 1, d_item)
            tr = m.get("total_return")
            tr_item = QTableWidgetItem(_pct(tr))
            tr_item.setForeground(_qcolor("up" if (tr or 0) >= 0 else "down"))
            self.lib_tbl.setItem(i, 2, tr_item)
            self.lib_tbl.setItem(i, 3, QTableWidgetItem(_pct(m.get("annual_return"))))
            sh = m.get("sharpe")
            self.lib_tbl.setItem(
                i, 4, QTableWidgetItem(f"{sh}" if sh is not None else "--"))
            dd_item = QTableWidgetItem(_pct(m.get("max_drawdown")))
            dd_item.setForeground(_qcolor("up"))
            self.lib_tbl.setItem(i, 5, dd_item)
            self.lib_tbl.setItem(i, 6, QTableWidgetItem(_pct(m.get("win_rate"))))
            self.lib_tbl.setItem(
                i, 7, QTableWidgetItem(str(e.get("found_at", ""))[:16].replace("T", " ")))
            s_item = QTableWidgetItem("✅ 已同步AI预测")
            s_item.setForeground(_qcolor("up"))
            s_item.setToolTip("该策略已写入盈利策略库，AI预测模块实时读取其方向信号并融合进预测")
            self.lib_tbl.setItem(i, 8, s_item)
            # 第 9 列：联动跳转「AI预测」并预载该策略基因
            btn = QPushButton("🔮 预测")
            btn.setObjectName("ghost")
            btn.setMinimumHeight(26)
            btn.clicked.connect(
                lambda _checked=False, idx=i: self._lib_to_predict(idx))
            self.lib_tbl.setCellWidget(i, 9, btn)

    # ------------------------------------------------------------------
    # 历史回测记录表（持久化数据渲染）
    # ------------------------------------------------------------------
    def _hist_row_values(self, rec: dict) -> list:
        """把一条历史记录（DB行或快照）转为表格 11 列的显示值。"""
        ts = str(rec.get("ts", ""))[:19].replace("T", " ")
        gen = rec.get("generation", "")
        gen_txt = "手动" if gen == MANUAL_GEN else f"第 {gen} 代"
        return [
            ts,
            f"{rec.get('symbol_name', '')}",
            gen_txt,
            rec.get("best_desc") or "--",
            _pct(rec.get("total_return")),
            f"{rec.get('sharpe')}" if rec.get("sharpe") is not None else "--",
            _pct(rec.get("max_drawdown")),
            _pct(rec.get("win_rate")),
            str(rec.get("trades") if rec.get("trades") is not None else "--"),
            f"{rec.get('fitness'):.1f}" if rec.get("fitness") is not None else "--",
            f"+{rec.get('new_profitable', 0)}" if rec.get("new_profitable") else "—",
        ]

    def _set_hist_row(self, i: int, rec: dict) -> None:
        vals = self._hist_row_values(rec)
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if c == 3:
                it.setToolTip(v)
            if c == 4:  # 总收益按涨跌着色
                tr = rec.get("total_return")
                it.setForeground(_qcolor("up" if (tr or 0) >= 0 else "down"))
            if c == 10 and rec.get("new_profitable"):
                it.setForeground(_qcolor("up"))
            self.hist_tbl.setItem(i, c, it)
        if rec.get("new_profitable"):
            for c in range(self.hist_tbl.columnCount()):
                it = self.hist_tbl.item(i, c)
                if it is not None:
                    it.setBackground(_qcolor_bg("#10b981", alpha=28))
        # 第 12 列：📊详情 + 🔁复跑 两个动作按钮
        self._set_hist_actions(i, rec)

    def _set_hist_actions(self, row: int, rec: dict) -> None:
        """在历史表第 12 列放「📊详情」「🔁复跑」两个按钮（共享一个容器）。"""
        from PyQt6.QtWidgets import QPushButton, QWidget, QHBoxLayout
        hid = rec.get("id")
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 1, 2, 1)
        h.setSpacing(4)

        b_detail = QPushButton("📊详情")
        b_detail.setFixedSize(60, 24)
        b_detail.setEnabled(bool(hid))
        b_detail.setToolTip("查看该次回测的分笔成交 / 月度收益 / 持仓时长归因"
                            if hid else "该记录未关联数据库，无法查看详情")
        b_detail.clicked.connect(lambda _=False, h=hid: self._show_history_detail(h))
        h.addWidget(b_detail)

        b_rerun = QPushButton("🔁复跑")
        b_rerun.setObjectName("secondary")
        b_rerun.setFixedSize(60, 24)
        b_rerun.setEnabled(bool(hid))
        b_rerun.setToolTip("用该次回测的精确基因+品种+期货参数重新跑一遍"
                           if hid else "该记录未关联数据库，无法复跑")
        b_rerun.clicked.connect(lambda _=False, h=hid: self._rerun_history(h))
        h.addWidget(b_rerun)

        self.hist_tbl.setCellWidget(row, 11, w)

    def _rerun_history(self, history_id) -> None:
        """R7-7.3：按 DB 行 id 取回该次完整配置（品种+精确基因）并重跑。

        复用 run_manual_for：切到手动回测模式 → 选中品种 → 注入精确基因 → 跑回测。
        期货参数取当前（持久化的）配置，与「恢复该次完整配置」意图一致。
        """
        if history_id is None or self._bt_store is None:
            return
        try:
            detail = self._bt_store.get_history_detail(int(history_id))
        except Exception:  # noqa: BLE001
            detail = None
        if not detail:
            self._log("⚠️ 未找到该历史记录，无法复跑")
            return
        gene = detail.get("gene")
        sym = detail.get("symbol")
        if not gene or not sym:
            self._log("⚠️ 该历史记录缺少基因/品种信息，无法复跑")
            return
        self._log(f"🔁 一键复跑：{detail.get('symbol_name', sym)} · "
                  f"「{(gene.get('entry') or '自定义')}」基因，切换手动模式重跑…")
        self.run_manual_for(sym, gene)

    def _show_history_detail(self, history_id) -> None:
        """按 DB 行 id 取回详情并弹出绩效归因对话框（R6）。"""
        if history_id is None or self._bt_store is None:
            return
        try:
            detail = self._bt_store.get_history_detail(int(history_id))
        except Exception:  # noqa: BLE001
            detail = None
        if not detail:
            return
        dlg = AttributionDialog(detail, self)
        dlg.exec()

    def _fill_history(self, hist: list) -> None:
        """整表刷新（启动恢复 / 主题切换用），hist 为 DB 倒序记录。"""
        self.hist_tbl.setRowCount(0)
        prepare_table(self.hist_tbl, self._theme)
        rows = hist[:300]
        self.hist_tbl.setRowCount(len(rows))
        for i, rec in enumerate(rows):
            self._set_hist_row(i, rec)

    def _prepend_history_row(self, snap: dict) -> None:
        """每代完成后把本代结果插到历史表最上方（与 DB 保持一致）。"""
        ranked = snap.get("ranked") or []
        best = ranked[0] if ranked else {}
        m = best.get("metrics") or {}
        import datetime as _dt
        rec = {
            "id": snap.get("_history_id"),
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "symbol_name": snap.get("symbol_name"),
            "generation": snap.get("generation"),
            "best_desc": best.get("desc"),
            "total_return": m.get("total_return"),
            "sharpe": m.get("sharpe"),
            "max_drawdown": m.get("max_drawdown"),
            "win_rate": m.get("win_rate"),
            "trades": m.get("num_closing_trades"),
            "fitness": best.get("fitness"),
            "new_profitable": len(snap.get("new_profitable") or []),
        }
        self.hist_tbl.insertRow(0)
        self._set_hist_row(0, rec)
        while self.hist_tbl.rowCount() > 300:
            self.hist_tbl.removeRow(self.hist_tbl.rowCount() - 1)

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        # 退出前合并 WAL，保证断点/历史完整落盘
        if self._bt_store is not None:
            try:
                self._bt_store.checkpoint()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)

    # ------------------------------------------------------------------
    def set_theme(self, t: str) -> None:
        super().set_theme(t)
        for tile in self._stage_tiles:
            tile.set_theme(t)
        for chip in self._chips.values():
            chip.set_theme(t)
        if self._last_snapshot:
            self._fill_population(self._last_snapshot.get("ranked") or [])
            self._fill_library(self._last_snapshot.get("library") or [])
        if self._bt_store is not None:
            self._fill_history(self._bt_store.recent_history(300))
