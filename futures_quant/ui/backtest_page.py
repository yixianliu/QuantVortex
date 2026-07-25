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

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QTabWidget,
    QCheckBox, QLineEdit,
)

from .pages import (
    BasePage, Worker, symbol_code, symbol_label, PERIODS, PERIOD_LABEL,
    ValidatePage,
)
from .widgets import PageHeader, ToolBar, prepare_table, color_pnl, PALETTE, THEME
from .icons import icon
from .chart_widget import PriceChart

from ..strategy.trend_following import TrendFollowing
from ..strategy.breakout import Breakout
from ..strategy.grid import Grid
from ..strategy.martingale import Martingale
from ..strategy.mean_reversion import MeanReversion

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

        self.run_btn = QPushButton("开始回测"); self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        self.export_btn = QPushButton("打开HTML报告"); self.export_btn.setObjectName("secondary")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._open_report)

        ctl.addWidget(QLabel("合约")); ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("策略")); ctl.addWidget(self.strat_cb)
        ctl.addWidget(QLabel("周期")); ctl.addWidget(self.per_cb)
        ctl.addWidget(QLabel("起")); ctl.addWidget(self.start_le)
        ctl.addWidget(QLabel("止")); ctl.addWidget(self.end_le)
        ctl.addWidget(QLabel("资金")); ctl.addWidget(self.cap_le)
        ctl.addWidget(self.risk_chk)
        ctl.addWidget(self.run_btn)
        ctl.addWidget(self.export_btn)
        ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        # ---- 提示行 ----
        self.info = QLabel("选择合约与策略后点击「开始回测」。回测区间以数据源实际可取行情为准。"
                           "合成行情仅用于方法验证，非真实市场结论。")
        self.info.setObjectName("sub")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        # ---- KPI 卡 ----
        self.kpi_bar = QHBoxLayout()
        self.kpi_bar.setSpacing(8)
        for key, title in [
            ("total_return", "总收益率"), ("annual_return", "年化"),
            ("sharpe", "夏普"), ("max_drawdown", "最大回撤"),
            ("win_rate", "胜率"), ("num_closing_trades", "平仓笔数"),
        ]:
            self.kpi_bar.addWidget(self._make_kpi(key, title))
        root.addLayout(self.kpi_bar)

        # ---- 主区：资金曲线 + 表格 ----
        self.chart = PriceChart()
        self.chart.setMinimumHeight(240)
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

        split = QVBoxLayout()
        split.setSpacing(8)
        split.addWidget(self.chart, 2)
        split.addWidget(self.tabs, 1)
        root.addLayout(split, 1)

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
        self.info.setText(f"正在回测 {sym} · {strat_name} · {PERIOD_LABEL.get(per, per)} "
                          f"· {start} ~ {end} …")

        def work():
            from futures_quant.config.settings import Config
            from futures_quant.backtest.backtester import Backtester
            from futures_quant.data.base import Contract

            cfg = Config()
            if not self.risk_chk.isChecked():
                # 放松风控，展示策略原始表现
                cfg.risk.max_single_loss = 1e12
                cfg.risk.max_daily_loss = 1e12
                cfg.risk.max_drawdown = 0.99
                cfg.risk.max_position_per_symbol = 100
                cfg.risk.max_total_position_ratio = 0.98
                cfg.risk.max_order_qty = 100
            cfg.backtest.start_cash = capital
            cfg.account.initial_capital = capital

            feed = self.mdm.feed
            row = next((r for r in self.mdm.universe if symbol_code(r) == sym), None)
            mult = float(row[4]) if row else 10.0
            tick = float(row[5]) if row else 1.0
            exch = row[3] if row else "SHFE"
            contract = Contract(symbol=sym, exchange=exch, multiplier=mult,
                                min_price_tick=tick, lot_size=1,
                                margin_rate=0.10, commission_per_lot=3.0)

            bt = Backtester(cfg, feed)
            bt.add_contract(contract)
            strat_cls = dict((n, c) for n, c in STRATEGIES)[strat_name]
            bt.add_strategy(strat_cls(sym, {}))

            res = bt.run(sym, start, end, per, warmup=60)
            outdir = os.path.join(ROOT, "data", "backtest_reports")
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
            f"夏普 {m.get('sharpe')}　平仓 {m.get('num_closing_trades')} 笔。")

    def _on_err(self, msg: str) -> None:
        self.run_btn.setEnabled(True); self.run_btn.setText("开始回测")
        self.export_btn.setEnabled(False)
        self.info.setStyleSheet("color:#ef4444;")
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


def _qcolor(key: str):
    from PyQt6.QtGui import QColor
    return QColor(PALETTE[THEME][key])


# ============================================================================
# 回测中心：合并「策略回测」与「预测验证」两个板块，一个入口两类回测
# ============================================================================
class BacktestCenterPage(BasePage):
    """回测中心：用标签页把「策略回测」与「预测验证」合并到同一入口。

    - 策略回测：选合约 / 策略 / 周期 / 区间 / 资金，跑历史回测，
      看资金曲线、成交明细、绩效指标（含 HTML 报告导出）。
    - 预测验证：滚动起点评估 AI 预测模型的方向胜率与偏差，验证其可用性。

    两个子页各自保留完整交互；外层仅一个「回测中心」入口，避免
    用户在两个独立板块间来回切换、概念混淆。
    """

    def __init__(self, mdm, store=None, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "backtest"
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "回测中心",
            "策略历史回测（绩效 / 回撤 / 胜率）· AI 预测模型验证（方向胜率 / 偏差）"
            "｜ 一个入口，两类回测"))

        self.tabs = QTabWidget()
        # 子页隐藏自身页头，避免与外层「回测中心」重复；标签即是其功能说明
        self._strat = BacktestPage(self.mdm, self.store, self.config,
                                    self.session, header=False)
        self._valid = ValidatePage(self.mdm, self.store, self.config,
                                     self.session, header=False)
        self.tabs.addTab(self._strat, "策略回测")
        self.tabs.addTab(self._valid, "预测验证")
        root.addWidget(self.tabs, 1)

    def set_theme(self, t: str) -> None:
        super().set_theme(t)
        self._strat.set_theme(t)
        self._valid.set_theme(t)
