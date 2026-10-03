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
    QRadioButton, QGroupBox, QButtonGroup, QProgressBar,
)

from .pages import (
    BasePage, Worker, symbol_code, symbol_label, PERIODS, PERIOD_LABEL,
)
from .widgets import (
    PageHeader, ToolBar, prepare_table, color_pnl, PALETTE, THEME, SectionHeader,
    StatCard,
)
from .icons import icon
from .chart_widget import PriceChart
from .states import DataGrid   # M4-08：统一表格能力（排序 / 右键菜单 / 列显隐 / 空态）
from ..runtime import get_data_dir
from ..strategy.arbitrage import (
    CalendarSpread, CrossInstrumentSpread, SpotFuturesBasis,
    cointegration_score,
)

# 手动回测在历史记录表中的「代数」列用此哨兵值表示（区别于自动进化的正整数代数）
MANUAL_GEN = -1


class _BufLogger:
    """极简内存日志器：捕获引擎/经纪商的运行日志，便于测试断言（如交割强平告警）。"""

    def __init__(self) -> None:
        """初始化相关对象。"""
        self.msgs: list = []

    def _a(self, lvl: str, msg: str) -> None:
        """处理a。
        
            参数:
                lvl: str
                msg: str"""
        self.msgs.append((lvl, str(msg)))

    def warning(self, m) -> None:
        """处理警告。
        
            参数:
                m"""
        self._a("W", m)

    def info(self, m) -> None:
        """处理信息。
        
            参数:
                m"""
        self._a("I", m)

    def error(self, m) -> None:
        """处理错误。
        
            参数:
                m"""
        self._a("E", m)

    def debug(self, m) -> None:
        """处理debug。
        
            参数:
                m"""
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
    ("跨期套利", CalendarSpread),
    ("跨品种套利", CrossInstrumentSpread),
    ("期现套利", SpotFuturesBasis),
]

# 各策略在对比图中的固定配色（与区块标题强调色一致，提升辨识度）
STRAT_COLORS = {
    "趋势跟踪": "#3b82f6",
    "突破交易": "#10b981",
    "网格交易": "#f59e0b",
    "马丁策略": "#ef4444",
    "均值回归": "#8b5cf6",
    "跨期套利": "#06b6d4",
    "跨品种套利": "#14b8a6",
    "期现套利": "#f59e0b",
}

# 绩效指标中文标签
METRIC_LABELS = {
    "start_equity": "初始资金", "end_equity": "期末资金",
    "total_return": "总收益率", "annual_return": "年化收益",
    "sharpe": "夏普比率", "max_drawdown": "最大回撤",
    "win_rate": "胜率", "profit_factor": "盈亏比",
    "avg_win": "平均盈利", "avg_loss": "平均亏损",
    "max_consecutive_loss": "最大连亏", "var_95": "95% VaR",
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
# 优化 schema：扩充参数空间，覆盖更广的策略配置
SEARCH_SCHEMA = {
    # 趋势跟踪：多档位均线 + ATR 周期
    "趋势跟踪": {
        "fast": [3, 5, 8, 10, 15, 20],
        "slow": [10, 15, 20, 30, 40, 50, 60],
        "atr_period": [10, 14, 20, 25, 30]
    },
    # 突破交易：唐奇安通道不同周期 + ATR 止损
    "突破交易": {
        "period": [10, 15, 20, 25, 30, 40],
        "atr_period": [10, 14, 20, 25, 30]
    },
    # 网格交易：网格步长与层数组合
    "网格交易": {
        "grid_step": [10.0, 15.0, 20.0, 30.0, 40.0],
        "grid_count": [5, 8, 10, 12, 15]
    },
    # 马丁策略：RSI 周期 + 加仓倍数 + 最大层数
    "马丁策略": {
        "rsi_period": [7, 10, 14, 20, 21, 28],
        "multiplier": [1.5, 2.0, 2.5, 3.0],
        "max_layers": [2, 3, 4, 5, 6]
    },
    # 均值回归：布林带周期与区间宽度
    "均值回归": {
        "period": [10, 15, 20, 25, 30, 40],
        "num_std": [1.5, 2.0, 2.5, 3.0, 3.5]
    },
    # 跨期套利：价差窗口 + 开仓/平仓 z-score
    "跨期套利": {
        "window": [10, 15, 20, 25, 30, 40],
        "entry_z": [1.5, 2.0, 2.5, 3.0],
        "exit_z": [0.1, 0.2, 0.3, 0.5]
    },
    # 跨品种套利：回归窗口 + z-score 阈值
    "跨品种套利": {
        "lookback": [10, 15, 20, 25, 30],
        "entry_z": [1.5, 2.0, 2.5, 3.0],
        "exit_z": [0.1, 0.2, 0.3, 0.5],
        "pair_basis": [1.0, 1.5, 2.0, 2.5]
    },
    # 期现套利：基差窗口 + z-score 阈值
    "期现套利": {
        "lookback": [10, 15, 20, 25, 30],
        "entry_z": [1.5, 2.0, 2.5, 3.0],
        "exit_z": [0.1, 0.2, 0.3, 0.5]
    },
}
# 参数名 -> 紧凑中文/缩写（用于优化表内展示）
OPT_PARAM_SHORT = {
    "fast": "快线", "slow": "慢线", "atr_period": "ATR", "period": "周期",
    "grid_step": "步长", "grid_count": "层数", "rsi_period": "RSI",
    "multiplier": "乘数", "max_layers": "层数", "num_std": "标准差",
    "window": "窗口", "entry_z": "开仓阈值", "exit_z": "平仓阈值",
    "lookback": "窗口", "pair_basis": "换算基准",
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
    """处理pct。
    
        参数:
            v: Optional[float]
    
        返回:
            str"""
    if v is None:
        return "--"
    return f"{v * 100:,.2f}%"


class BacktestPage(BasePage):
    """回测页面。
    
        继承: BasePage"""
    def __init__(self, mdm, store=None, config=None, session=None, header: bool = True):
        """初始化相关对象。
        
            参数:
                mdm
                store
                config
                session
                header: bool"""
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
        # M3.5：订阅全局事件总线，预测产出时即时消费待验证信号（预测→回测闭环）
        try:
            from ..core.events import bus as _EBUS
            _EBUS.subscribe("prediction.created", lambda *_a: self._sync_from_prediction_bus())
        except Exception:  # noqa: BLE001
            pass
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        """构建相关对象。"""
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
        # M4-06⑤：长任务「停止」按钮——回测/优化/敏感度扫描期间可协作式中止
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("secondary")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("请求中止当前回测（在下一个检查点生效，不会留下半截结果）")
        self.stop_btn.clicked.connect(self._stop_run)

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
        ctl.addWidget(self.stop_btn)
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
        self.trade_tbl = DataGrid(0, 8)
        self.trade_tbl.setHorizontalHeaderLabels(
            ["时间", "合约", "方向", "开平", "数量", "价格", "手续费", "盈亏"])
        self.trade_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metric_tbl = DataGrid(0, 2)
        self.metric_tbl.setHorizontalHeaderLabels(["指标", "数值"])
        self.metric_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metric_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.trade_tbl, "成交明细")
        self.tabs.addTab(self.metric_tbl, "绩效指标")
        self.cmp_tbl = DataGrid(0, 7)
        self.cmp_tbl.setHorizontalHeaderLabels(
            ["策略", "总收益率", "年化", "夏普", "最大回撤", "胜率", "平仓笔数"])
        self.cmp_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.cmp_tbl, "策略对比")
        # 参数敏感度矩阵：行=周期，列=资金档，单元格=总收益率（热力底色）
        self.sens_tbl = DataGrid(0, len(SENS_CAPITALS) + 2)
        self.sens_tbl.setHorizontalHeaderLabels(
            ["周期＼资金"] + [f"{c // 10000}万" for c in SENS_CAPITALS] + ["平均收益"])
        self.sens_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.sens_tbl, "参数敏感度")
        # 参数优化：排名 / 参数组合 / 绩效 / 因子贡献
        self.opt_tbl = DataGrid(0, 9)
        self.opt_tbl.setHorizontalHeaderLabels(
            ["排名", "参数组合", "总收益率", "年化", "夏普", "最大回撤", "胜率", "平仓笔数", "因子贡献度"])
        self.opt_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.opt_tbl, "参数优化")
        root.addWidget(self.tabs, 2)

        self._style_kpis()

    # ------------------------------------------------------------------
    def _make_kpi(self, key: str, title: str) -> QFrame:
        """生成kpi。
        
            参数:
                key: str
                title: str
        
            返回:
                QFrame"""
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
        """处理stylekpis（M4-05：含按最近 KPI 值重新着色，随主题调色板刷新）。"""
        p = PALETTE[self._theme]
        for frame in self._kpi_frames.values():
            frame.setStyleSheet(
                f"background:{p['card']};border:1px solid {p['border']};border-radius:10px;")
        for lab, _ in self._kpi_labels.values():
            lab.setStyleSheet(f"color:{p['sub']};font-size:12px;")
        # M4-05：KPI 数值着色（涨/跌/回撤）依赖调色板，切主题时按缓存值重算一次
        if getattr(self, "_last_kpis", None):
            for key, val in self._last_kpis.items():
                vlab = self._kpi_labels[key][1]
                if key in ("total_return", "annual_return", "max_drawdown", "win_rate"):
                    if val is None:
                        vlab.setStyleSheet(
                            f"color:{p['text']};font-size:18px;font-weight:bold;")
                    else:
                        col = p["down"] if val >= 0 else p["up"]
                        if key == "max_drawdown":
                            col = p["up"]
                        vlab.setStyleSheet(f"color:{col};font-size:18px;font-weight:bold;")
                else:
                    vlab.setStyleSheet(
                        f"color:{p['text']};font-size:18px;font-weight:bold;")

    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        super().set_theme(t)
        self._style_kpis()

    # ------------------------------------------------------------------
    def _on_sel(self, *_):
        """处理onsel。
        
            参数:
                *_: 可变位置参数"""
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        self.selection_changed.emit(self.cur_symbol, self.cur_period)

    def _on_strat(self, *_):
        """处理onstrat。
        
            参数:
                *_: 可变位置参数"""
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
        """运行相关对象。"""
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
        self.stop_btn.setEnabled(True)   # M4-06⑤：长任务期间开放「停止」
        self.export_btn.setEnabled(False)
        self.apply_opt_btn.setEnabled(False)
        # 应用最优参数：单模式以覆盖参数运行（不来自优化模式）
        override = getattr(self, "_pending_params", None)
        self._applied_params = override
        self.info.setText(f"正在回测 {sym} · {strat_name} · {PERIOD_LABEL.get(per, per)} "
                          f"· {start} ~ {end} …"
                          + ("（应用优化最优参数确认）" if override else ""))

        def work():
            """处理work。"""
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
                """生成cfg。
                
                    参数:
                        cap"""
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
                # 参数优化：使用BacktestService
                try:
                    from futures_quant.app.service_locator import request
                    backtest_service = request("backtest_service")
                    
                    base_params = strat_cls(sym, {}).params  # 默认参数（保底未搜索项）
                    combos = _opt_combos(strat_name)
                    scanned = []
                    best_curve = None
                    default_curve = None
                    
                    for combo in combos:
                        params = dict(base_params)
                        params.update(combo)

                        # 创建策略实例（套利策略签名: strat_cls(symbol, params_dict)，其余为 **params）
                        if strat_name in ("跨期套利", "跨品种套利", "期现套利"):
                            strat_cls = dict((n, c) for n, c in STRATEGIES)[strat_name]
                            strategy = strat_cls(sym, params)
                        else:
                            if strat_name == "趋势跟踪":
                                from futures_quant.strategy.trend_following import TrendFollowing
                                strategy = TrendFollowing(symbol=sym, **params)
                            elif strat_name == "突破交易":
                                from futures_quant.strategy.breakout import Breakout
                                strategy = Breakout(symbol=sym, **params)
                            elif strat_name == "网格交易":
                                from futures_quant.strategy.grid import Grid
                                strategy = Grid(symbol=sym, **params)
                            elif strat_name == "马丁策略":
                                from futures_quant.strategy.martingale import Martingale
                                strategy = Martingale(symbol=sym, **params)
                            elif strat_name == "均值回归":
                                from futures_quant.strategy.mean_reversion import MeanReversion
                                strategy = MeanReversion(symbol=sym, **params)
                            else:
                                # 默认使用趋势跟踪
                                from futures_quant.strategy.trend_following import TrendFollowing
                                strategy = TrendFollowing(symbol=sym, **params)
                        
                        # 运行回测
                        result = backtest_service.run_backtest(sym, start, end, period, warmup=60, strategy=strategy)
                        
                        m = result["metrics"]
                        scanned.append({"params": combo, "metrics": m,
                                        "equity_curve": result["equity_curve"]})
                        if combo == combos[0]:
                            default_curve = result["equity_curve"]
                    
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
                except Exception as e:
                    # 如果服务不可用，回退到原有实现
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
                        res = bt.run(sym, start, end, per, warmup=60,
                             should_abort=self._abort_predicate())
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
                # 参数敏感度：使用BacktestService
                try:
                    from futures_quant.app.service_locator import request
                    backtest_service = request("backtest_service")
                    
                    grid = {}
                    center_cap = SENS_CAPITALS[SENS_CENTER_IDX]
                    center_curves = []
                    
                    # 创建默认策略实例（用于敏感度测试）
                    if strat_name in ("跨期套利", "跨品种套利", "期现套利"):
                        strat_cls = dict((n, c) for n, c in STRATEGIES)[strat_name]
                    elif strat_name == "趋势跟踪":
                        from futures_quant.strategy.trend_following import TrendFollowing
                        strat_cls = TrendFollowing
                    elif strat_name == "突破交易":
                        from futures_quant.strategy.breakout import Breakout
                        strat_cls = Breakout
                    elif strat_name == "网格交易":
                        from futures_quant.strategy.grid import Grid
                        strat_cls = Grid
                    elif strat_name == "马丁策略":
                        from futures_quant.strategy.martingale import Martingale
                        strat_cls = Martingale
                    elif strat_name == "均值回归":
                        from futures_quant.strategy.mean_reversion import MeanReversion
                        strat_cls = MeanReversion
                    else:
                        from futures_quant.strategy.trend_following import TrendFollowing
                        strat_cls = TrendFollowing

                    for cap in SENS_CAPITALS:
                        for pper in SENS_PERIODS:
                            # 套利策略签名: strat_cls(symbol, params_dict)；其余为 strat_cls(symbol, params={})
                            if strat_name in ("跨期套利", "跨品种套利", "期现套利"):
                                strategy = strat_cls(sym, params={})
                            else:
                                strategy = strat_cls(symbol=sym, params={})
                            result = backtest_service.run_backtest(sym, start, end, pper, warmup=60, strategy=strategy)
                            grid[(pper, cap)] = result["metrics"]
                            if cap == center_cap:
                                center_curves.append((pper, result["equity_curve"]))
                    
                    return {
                        "sens": True, "grid": grid,
                        "center_curves": center_curves,
                        "caps": SENS_CAPITALS, "pers": SENS_PERIODS,
                        "center_cap": center_cap,
                        "sym": sym, "per": per, "strat": strat_name,
                    }
                except Exception as e:
                    # 如果服务不可用，回退到原有实现
                    grid = {}
                    center_cap = SENS_CAPITALS[SENS_CENTER_IDX]
                    center_curves = []
                    for cap in SENS_CAPITALS:
                        cfg = make_cfg(cap)
                        for pper in SENS_PERIODS:
                            bt = Backtester(cfg, feed)
                            bt.add_contract(contract)
                            bt.add_strategy(strat_cls(sym, {}))
                            res = bt.run(sym, start, end, pper, warmup=60,
                                          should_abort=self._abort_predicate())
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
                # 多策略对比：使用BacktestService
                try:
                    from futures_quant.app.service_locator import request
                    backtest_service = request("backtest_service")
                    
                    results = []
                    report = None
                    for name, cls in STRATEGIES:
                        strategy = cls(symbol=sym, params={})
                        result = backtest_service.run_backtest(sym, start, end, per, warmup=60, strategy=strategy)
                        results.append({
                            "strat": name,
                            "metrics": result["metrics"],
                            "equity_curve": result["equity_curve"],
                            "trades": result["trades"],
                        })
                        if name == strat_name:
                            report = result["report"]
                    
                    primary = dict((r["strat"], r) for r in results).get(
                        strat_name, results[0])
                    return {
                        "compare": True, "results": results, "primary": primary,
                        "report": report, "sym": sym, "per": per, "strat": strat_name,
                    }
                except Exception as e:
                    # 如果服务不可用，回退到原有实现
                    results = []
                    report = None
                    for name, cls in STRATEGIES:
                        bt = Backtester(make_cfg(capital), feed)
                        bt.add_contract(contract)
                        bt.add_strategy(cls(sym, {}))
                        res = bt.run(sym, start, end, per, warmup=60,
                             should_abort=self._abort_predicate())
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

            # 简单回测情况 - 使用BacktestService
            try:
                from futures_quant.app.service_locator import request
                backtest_service = request("backtest_service")
                
                # 创建策略实例
                strategy_params = override if override else {}
                if strat_name == "趋势跟踪":
                    from futures_quant.strategy.trend_following import TrendFollowing
                    strategy = TrendFollowing(symbol=sym, **strategy_params)
                elif strat_name == "突破交易":
                    from futures_quant.strategy.breakout import Breakout
                    strategy = Breakout(symbol=sym, **strategy_params)
                elif strat_name == "网格交易":
                    from futures_quant.strategy.grid import Grid
                    strategy = Grid(symbol=sym, **strategy_params)
                elif strat_name == "马丁策略":
                    from futures_quant.strategy.martingale import Martingale
                    strategy = Martingale(symbol=sym, **strategy_params)
                elif strat_name == "均值回归":
                    from futures_quant.strategy.mean_reversion import MeanReversion
                    strategy = MeanReversion(symbol=sym, **strategy_params)
                else:
                    # 默认使用趋势跟踪
                    from futures_quant.strategy.trend_following import TrendFollowing
                    strategy = TrendFollowing(symbol=sym, **strategy_params)
                
                # 运行回测
                result = backtest_service.run_backtest(sym, start, end, period, warmup=60, strategy=strategy)
                return {
                    "metrics": result["metrics"], "equity_curve": result["equity_curve"],
                    "trades": result["trades"], "report": result["report"],
                    "sym": sym, "per": per, "strat": strat_name,
                }
            except Exception as e:
                # 如果服务不可用，回退到原有实现
                bt = Backtester(make_cfg(capital), feed)
                bt.add_contract(contract)
                bt.add_strategy(strat_cls(sym, override if override else {}))
                
                res = bt.run(sym, start, end, per, warmup=60,
                             should_abort=self._abort_predicate())
                paths = bt.export(outdir, prefix=f"bt_{sym.replace('.', '_')}_{per}")
                return {
                    "metrics": res["metrics"], "equity_curve": res["equity_curve"],
                    "trades": res["trades"], "report": paths["html"],
                    "sym": sym, "per": per, "strat": strat_name,
                }

        self._run_worker(work, self._on_done,
                         on_err=lambda e: self._on_err(str(e)),
                         on_interrupted=self._on_interrupted)

    # ------------------------------------------------------------------
    # M4-06⑤：长任务中断生命周期
    # ------------------------------------------------------------------
    def _end_run(self) -> None:
        """恢复工具栏可交互态（成功 / 失败 / 中断三条路径共用）。"""
        self.run_btn.setEnabled(True)
        self.run_btn.setText("开始回测")
        self.stop_btn.setEnabled(False)

    def _stop_run(self) -> None:
        """请求中止当前回测（协作式：在引擎下一个检查点生效）。"""
        if not getattr(self, "_workers", None):
            self._end_run()
            return
        self._workers[-1].requestInterruption()
        self.stop_btn.setEnabled(False)
        self.info.setStyleSheet("")  # 还原（交由 QSS 控制颜色）
        self.info.setText("已请求停止回测，正在等待当前批次结束…")

    def _on_interrupted(self) -> None:
        """回测被用户中止：不发结果，仅恢复界面并给出中性提示（不算失败）。"""
        self._end_run()
        self.export_btn.setEnabled(False)
        self.info.setStyleSheet("")
        self.info.setText("回测已停止（未产生结果）。")

    # ------------------------------------------------------------------
    def _on_done(self, r: dict) -> None:
        """处理ondone。
        
            参数:
                r: dict"""
        self._end_run()

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
        """处理onerr。
        
            参数:
                msg: str"""
        self._end_run()
        self.export_btn.setEnabled(False)
        self.info.setStyleSheet(f"color:{p['down']};")
        self.info.setText(f"回测失败：{msg}（请检查合约/日期是否可取行情）")

    # ------------------------------------------------------------------
    def _update_kpis(self, m: dict) -> None:
        """更新kpis。
        
            参数:
                m: dict"""
        p = PALETTE[self._theme]
        mapping = {
            "total_return": m.get("total_return"),
            "annual_return": m.get("annual_return"),
            "sharpe": m.get("sharpe"),
            "max_drawdown": m.get("max_drawdown"),
            "win_rate": m.get("win_rate"),
            "num_closing_trades": m.get("num_closing_trades"),
        }
        self._last_kpis = mapping   # M4-05：缓存最近 KPI 值，供切主题时按新调色板重着色
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
        """更新图表。
        
            参数:
                curve: list
                sym: str
                per: str"""
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
            """处理bg。
            
                参数:
                    v"""
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
            # 因子贡献度：基于参数敏感度简易计算（显示关键参数对收益的影响）
            factor_contrib = self._compute_factor_contribution(params, m, ranked)
            fc_item = QTableWidgetItem(factor_contrib)
            fc_item.setToolTip("显示关键参数对策略绩效的边际贡献度\n基于同策略不同参数组合的收益差异估算")
            self.opt_tbl.setItem(i, 8, fc_item)
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

    def _compute_factor_contribution(self, params: dict, metrics: dict, ranked: list) -> str:
        """基于参数敏感度简易估算关键因子贡献度（用于参数优化表展示）。"""
        if not params or len(ranked) < 3:
            return "数据不足"
        try:
            # 找出同策略下其他参数组合，计算各参数的边际效应
            base_return = metrics.get("total_return", 0)
            contributions = {}
            for key, val in params.items():
                # 寻找仅该参数不同的组合
                diffs = []
                for other in ranked:
                    other_params = other["params"]
                    other_return = other["metrics"].get("total_return", 0)
                    # 仅当前参数不同，其他相同
                    if all(other_params.get(k) == v for k, v in params.items() if k != key):
                        if other_params.get(key) != val:
                            diffs.append(abs(other_return - base_return))
                if diffs:
                    contributions[key] = sum(diffs) / len(diffs)
            if not contributions:
                return "单因子"
            # 归一化显示
            total = sum(contributions.values())
            if total == 0:
                return "均衡"
            sorted_contrib = sorted(contributions.items(), key=lambda x: -x[1])
            top2 = sorted_contrib[:2]
            return "、".join(f"{OPT_PARAM_SHORT.get(k, k)}:{v/total*100:.0f}%" for k, v in top2)
        except Exception:
            return "计算异常"

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
        """处理fill交易记录。
        
            参数:
                trades: list"""
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
        """处理fillmetrics。
        
            参数:
                m: dict"""
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
        """打开report。"""
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
    """处理qcolor。
    
        参数:
            key: str"""
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
    ("🚀", "同步KP预测"),
]

# 因子分析配置
FACTOR_ANALYSIS_CONFIG = {
    "min_samples": 5,           # 最小样本数
    "correlation_threshold": 0.7,  # 相关性阈值（用于冗余检测）
    "importance_method": "variance",  # 重要性计算方法：variance/shap/permutation
    "stability_window": 10,     # 稳定性计算窗口（代数）
    "top_factors_display": 15,  # 展示前N个重要因子
}

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
        ⑤ 自动同步：盈利策略实时落盘策略库，「KP预测」模块直接读取
           并把策略方向信号融合进预测（无需任何人工确认）。
    品种自动轮换：每个品种进化若干代后自动切换下一品种，全市场循环学习。
    """

    def __init__(self, mdm, store=None, config=None, session=None):
        """初始化相关对象。
        
            参数:
                mdm
                store
                config
                session"""
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
        # M4-09：自动进化长任务可视化状态
        self._evolution_stopped = False  # 用户主动停止（不再排程下一代）
        self._paused = False              # 暂停（点击继续后恢复）
        self._evolution_worker = None     # 当前代 evolution worker 句柄
        self._cur_gen_no = 0             # 当前代编号（进度标签用）
        self._evo_progress = None         # QProgressBar（真实百分比）
        self._evo_stage_label = None      # 「第 n 代 · 基因 i/10」状态标签
        self._evo_pause_btn = None        # 暂停/继续/重新开始 按钮
        self._evo_stop_btn = None         # 停止 按钮
        # 本地持久化库：引擎断点 / 历史回测记录 / 学习日志（自动保存+启动恢复）
        try:
            from ..storage.backtest_store import get_backtest_store
            self._bt_store = get_backtest_store()
        except Exception:  # noqa: BLE001
            self._bt_store = None
        # M2-10 ④：进化档案（孤岛 EvolutionStore 接入，逐代落盘供回看）
        self._evo_store = None
        self._evo_run_id = None      # 当前 run（None → save_run 自动生成）
        self._evo_run_gens = []      # 当前 run 的逐代记录
        try:
            from ..storage.evolution_store import EvolutionStore
            self._evo_store = EvolutionStore()
        except Exception:  # noqa: BLE001
            self._evo_store = None
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
        """构建相关对象。"""
        from .widgets import StatusTile, StatCard

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "回测中心 · 全自动自我学习",
            "AI自主生成策略因子 → 自动回测 → 迭代进化 → 盈利判定 → 自动同步KP预测"
            "｜ 全程零操作，打开即运行"))

        # ---- 运行状态行 ----
        self.info = QLabel("系统待命：进入本页后自动启动自我学习流程…")
        self.info.setObjectName("sub")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        # ---- M4-09：进化长任务可视化（实时百分比 + 第 n 代·基因 i/10 + 暂停/停止）----
        evo_ctrl = QHBoxLayout()
        evo_ctrl.setSpacing(8)
        self._evo_stage_label = QLabel("准备中…")
        self._evo_stage_label.setObjectName("sub")
        self._evo_stage_label.setWordWrap(True)
        evo_ctrl.addWidget(self._evo_stage_label, 1)
        self._evo_pause_btn = QPushButton("⏸ 暂停")
        self._evo_pause_btn.setObjectName("secondary")
        self._evo_pause_btn.setEnabled(False)
        self._evo_pause_btn.setToolTip("暂停/继续自动进化循环（也可重新开始）")
        self._evo_pause_btn.clicked.connect(self._toggle_pause)
        evo_ctrl.addWidget(self._evo_pause_btn)
        self._evo_stop_btn = QPushButton("⏹ 停止")
        self._evo_stop_btn.setObjectName("secondary")
        self._evo_stop_btn.setEnabled(False)
        self._evo_stop_btn.setToolTip("停止自动进化（不再排程下一代；可重新开始）")
        self._evo_stop_btn.clicked.connect(self._stop_evolution)
        evo_ctrl.addWidget(self._evo_stop_btn)
        root.addLayout(evo_ctrl)

        self._evo_progress = QProgressBar()
        self._evo_progress.setRange(0, 100)
        self._evo_progress.setValue(0)
        self._evo_progress.setTextVisible(True)
        self._evo_progress.setFormat("%p% · 第 0 代")
        root.addWidget(self._evo_progress)

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
            chip = StatCard(label, theme=self._theme)
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
            chip = StatCard(label, theme=self._theme)
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

        # ---- 学习结果四视图 ----
        root.addWidget(SectionHeader("学习成果", "#f59e0b"))
        self.tabs = QTabWidget()

        # ① 当代种群排行
        self.pop_tbl = DataGrid(0, 9)
        self.pop_tbl.setHorizontalHeaderLabels(
            ["排名", "策略因子（AI自动生成）", "总收益", "夏普", "最大回撤",
             "胜率", "交易数", "适应度", "盈利判定"])
        hh = self.pop_tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.pop_tbl, "🧬 当代种群排行")

        # ② 因子重要性分析（基于当代种群的参数敏感度）
        self.factor_tbl = DataGrid(0, 5)
        self.factor_tbl.setHorizontalHeaderLabels(
            ["因子名称", "重要性得分", "收益贡献度", "稳定性", "推荐区间"])
        self.factor_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.factor_tbl, "🔬 因子重要性")

        # ③ 因子相关性分析（热力图 + 冗余检测）
        self.factor_corr_tbl = DataGrid(0, 0)
        self.tabs.addTab(self.factor_corr_tbl, "🔗 因子相关性")

        # ④ 因子参数调优界面（自定义参数范围 + 网格搜索）
        self.factor_tune_tbl = DataGrid(0, 6)
        self.factor_tune_tbl.setHorizontalHeaderLabels(
            ["因子名称", "当前值", "调优范围", "步长", "最优值", "预期提升"])
        self.factor_tune_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.factor_tune_tbl, "⚙️ 因子参数调优")

        # ⑤ 因子绩效监控（历史表现追踪 + 预警）
        self.factor_monitor_tbl = DataGrid(0, 8)
        self.factor_monitor_tbl.setHorizontalHeaderLabels(
            ["因子名称", "历史平均收益", "历史夏普", "历史最大回撤", "胜率稳定性",
             "参数敏感度", "近期趋势", "预警状态"])
        self.factor_monitor_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.factor_monitor_tbl, "📊 因子绩效监控")

        # ⑥ 盈利策略库（已自动同步 KP预测）
        self.lib_tbl = DataGrid(0, 10, sortable=False)
        self.lib_tbl.setHorizontalHeaderLabels(
            ["品种", "策略因子", "总收益", "年化", "夏普", "回撤",
             "胜率", "发现时间", "状态", "操作"])
        self.lib_tbl.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.lib_tbl, "💰 盈利策略库")

        # ⑦ 历史回测记录（持久化，重启保留，供查看与对比）
        # R6：第 12 列「操作」挂📊详情按钮（打开绩效归因对话框）
        self.hist_tbl = DataGrid(0, 12, sortable=False)
        self.hist_tbl.setHorizontalHeaderLabels(
            ["时间", "品种", "代数", "最优策略因子", "总收益", "夏普",
             "回撤", "胜率", "交易数", "适应度", "盈利入库", "操作"])
        hh2 = self.hist_tbl.horizontalHeader()
        hh2.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh2.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.hist_tbl, "🗂 历史回测记录")

        # ⑧ 学习日志
        from PyQt6.QtWidgets import QListWidget
        self.log_list = QListWidget()
        self.log_list.setWordWrap(True)
        self.tabs.addTab(self.log_list, "📜 学习日志")

        # ⑨ 蒸馏规则（M2-10）：展示由盈利策略库蒸馏出的可读规则文本
        from PyQt6.QtWidgets import QPlainTextEdit
        self.rules_text = QPlainTextEdit()
        self.rules_text.setReadOnly(True)
        self.rules_text.setPlaceholderText(
            "点击工具栏「🧪 蒸馏规则」，从盈利策略库生成可读规则集…")
        self.tabs.addTab(self.rules_text, "📐 蒸馏规则")
        root.addWidget(self.tabs, 2)

    # ------------------------------------------------------------------
    # 期货特有参数控制条（杠杆 / 保证金 / 乘数 / 交割日）
    # ------------------------------------------------------------------
    def _build_futures_params_bar(self) -> None:
        """构建期货参数K线。"""
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

        # 联动 KP预测：携带当前品种跳转，进行板块联动分析
        self.link_btn = QPushButton("🔗 联动KP预测")
        self.link_btn.setObjectName("secondary")
        self.link_btn.setToolTip("携带当前学习品种跳转到「KP预测」板块，"
                                "查看与回测结果联动的研判")
        self.link_btn.clicked.connect(self._goto_predict)
        bar.addWidget(self.link_btn)

        # M2-10 ③：蒸馏规则按钮 → 生成 rules.json 并在「📐 蒸馏规则」页签展示
        self.distill_btn = QPushButton("🧪 蒸馏规则")
        self.distill_btn.setObjectName("secondary")
        self.distill_btn.setToolTip("把盈利策略库 top-K 蒸馏为人类可读规则集，"
                                    "写入 data/auto_strategies/rules.json")
        self.distill_btn.clicked.connect(self._on_distill_clicked)
        bar.addWidget(self.distill_btn)

        # M3-05 ④：Walk-Forward 滚动验证 —— 检验「回测发现的策略」在因果滚动
        # 切分下是否仍有样本外技能（逐折只用历史段训练再预测未来段）。
        self.wf_btn = QPushButton("🔁 Walk-Forward 验证")
        self.wf_btn.setObjectName("secondary")
        self.wf_btn.setToolTip("对当前品种做因果滚动验证：逐折只用历史段训练再预测未来段，"
                               "输出折数 / 样本外方向准确率 / MAE（结果写入「📐 蒸馏规则」页签）")
        self.wf_btn.clicked.connect(self._on_walk_forward_clicked)
        bar.addWidget(self.wf_btn)

        # M2-10 ④：进化档案下拉 → 回看历史 run
        self.archive_combo = QComboBox()
        self.archive_combo.setMinimumWidth(190)
        self.archive_combo.setToolTip("进化档案：选择历史 run 回看其收敛记录")
        self.archive_combo.currentIndexChanged.connect(self._on_archive_selected)
        bar.addWidget(QLabel("进化档案"))
        bar.addWidget(self.archive_combo)
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

    # ------------------------------------------------------------------
    # M2-10 ③ 蒸馏规则 / ④ 进化档案
    # ------------------------------------------------------------------
    def _on_distill_clicked(self) -> None:
        """点击「🧪 蒸馏规则」：从盈利策略库蒸馏规则 → 写 rules.json → 页签展示。"""
        try:
            from ..strategy.distill import export_rules, format_rules_text
            from ..strategy.auto_evolve import load_profitable
            entries = load_profitable() or []
            if not entries:
                self.rules_text.setPlainText(
                    "盈利策略库为空，暂无可蒸馏的规则。请先让系统进化出入库策略。")
                self._log("🧪 蒸馏规则：盈利策略库为空，未生成规则")
                return
            payload = export_rules(entries, k=3)
            text = format_rules_text(payload)
            self.rules_text.setPlainText(text)
            # 切到规则页签，让用户立刻看到结果
            idx = self.tabs.indexOf(self.rules_text)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
            self._log(f"🧪 蒸馏规则完成：{payload.get('n_rules', 0)} 条 → "
                      f"{payload.get('path')}")
        except Exception as e:  # noqa: BLE001
            self.rules_text.setPlainText(f"蒸馏失败：{e}")
            self._log(f"⚠️ 蒸馏规则失败：{e}")

    def _on_walk_forward_clicked(self) -> None:
        """点击「🔁 Walk-Forward 验证」：对当前品种做因果滚动验证并展示结果。

        逐折重训开销较大，故走 worker 线程；结果写到「📐 蒸馏规则」页签（该页签
        是只读文本区，用作通用输出面板）并同步写入运行日志。
        """
        sym = self.sym_cb.currentData() if hasattr(self, "sym_cb") else None
        per = self.per_cb.currentData() if hasattr(self, "per_cb") else "D"
        if not sym:
            self._log("⚠️ Walk-Forward 验证：未选择品种")
            return
        self.wf_btn.setEnabled(False)
        self._log(f"🔁 Walk-Forward 验证启动：{sym} {per} …")

        def work():
            """处理work。"""
            from ..ai.predictor import FuturesPredictor
            df = self.mdm.feed.get_history(sym, "2000-01-01", "2099-12-31", per or "D")
            if df is None or len(df) < 80:
                return {"error": "数据不足（需 ≥80 根 K 线）"}
            p = FuturesPredictor()
            return p.evaluate(df, horizon=1, seq_len=20, epochs=10,
                              extended_features=False, use_ensemble=False,
                              symbol=sym, period=per or "D", use_walk_forward=True)

        def done(r):
            """处理done。

                参数:
                    r"""
            self.wf_btn.setEnabled(True)
            if not r or r.get("error"):
                self._log(f"⚠️ Walk-Forward 验证失败：{r.get('error') if r else '无结果'}")
                if hasattr(self, "rules_text"):
                    self.rules_text.setPlainText(
                        f"Walk-Forward 验证失败：{r.get('error') if r else '无结果'}")
                return
            folds = r.get("folds") or []
            lines = [
                f"Walk-Forward 滚动验证 · {sym} {per}",
                f"折数：{r.get('n_folds', 0)}　OOS 样本：{r.get('val_samples', 0)}"
                f"　{'真·滚动' if r.get('walk_forward') else '⚠️ 已回退固定 80/20 切分'}",
                f"样本外方向准确率：{float(r.get('direction_acc', 0.0)):.2%}",
                f"MAE：{float(r.get('mae', 0.0)):.6f}　RMSE：{float(r.get('rmse', 0.0)):.6f}",
                f"R²：{float(r.get('r_squared', 0.0)):.4f}　夏普：{float(r.get('sharpe_ratio', 0.0)):.3f}",
                "",
                "各折区间（train_end → test_end，严格不重叠）：",
            ]
            lines += [f"  折#{f['fold']}：train[{f['train'][0]},{f['train'][1]}) → "
                      f"test[{f['test'][0]},{f['test'][1]})　n={f['n_test']}　阈值={f['threshold']:.6f}"
                      for f in folds]
            text = "\n".join(lines)
            if hasattr(self, "rules_text"):
                self.rules_text.setPlainText(text)
                idx = self.tabs.indexOf(self.rules_text)
                if idx >= 0:
                    self.tabs.setCurrentIndex(idx)
            self._log(f"✅ Walk-Forward 验证完成：{r.get('n_folds', 0)} 折，"
                      f"方向准确率 {float(r.get('direction_acc', 0.0)):.2%}")

        def err(e):
            """处理err。

                参数:
                    e"""
            self.wf_btn.setEnabled(True)
            self._log(f"⚠️ Walk-Forward 验证出错：{e}")

        self._run_worker(work, done, on_err=err)

    def _refresh_archive(self) -> None:
        """刷新「进化档案」下拉：列出 EvolutionStore 中的历史 run。"""
        try:
            store = self._evo_store
            if store is None:
                return
            runs = store.list_runs()
            self.archive_combo.blockSignals(True)
            self.archive_combo.clear()
            self.archive_combo.addItem("（无档案）", None)
            for r in runs[:50]:
                label = (f"{r.get('created_at', '')[:16]} · "
                         f"{r.get('n_generations', 0)}代 · "
                         f"fit {r.get('best_fitness')}")
                self.archive_combo.addItem(label, r.get("run_id"))
            self.archive_combo.blockSignals(False)
        except Exception:  # noqa: BLE001
            pass

    def _on_archive_selected(self, _idx: int = 0) -> None:
        """选中某个历史 run → 在规则页签展示其收敛曲线摘要。"""
        try:
            rid = self.archive_combo.currentData()
            if not rid:
                return
            conv = self._evo_store.convergence(rid)
            if not conv:
                self.rules_text.setPlainText(f"档案 {rid} 无收敛记录。")
                return
            lines = [f"进化档案 {rid} · 共 {len(conv)} 代收敛记录", ""]
            for c in conv:
                lines.append(f"  第 {c.get('generation')} 代：best = {c.get('best')}")
            best = conv[-1].get("best")
            first = conv[0].get("best")
            if best is not None and first is not None:
                lines.append("")
                lines.append(f"收敛提升：{first} → {best}")
            self.rules_text.setPlainText("\n".join(lines))
            idx = self.tabs.indexOf(self.rules_text)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        except Exception as e:  # noqa: BLE001
            self._log(f"⚠️ 读取进化档案失败：{e}")

    def _save_evo_run(self, snap: dict) -> None:
        """M2-10 ④：每代把本代记录追加到当前 run 并落盘（供档案回看）。"""
        try:
            if self._evo_store is None or self._engine is None:
                return
            if self._evo_run_id is None:
                self._evo_run_id = None  # save_run 自动生成
                self._evo_run_gens = []
            ranked = snap.get("ranked") or []
            best = ranked[0] if ranked else {}
            self._evo_run_gens.append({
                "generation": snap.get("generation"),
                "best_fitness": best.get("fitness"),
                "best_genome": best.get("gene"),
                "symbol": snap.get("symbol"),
            })
            eng = self._engine
            params = {
                "seed": getattr(eng, "seed", None),
                "period": eng.period,
                "pop_size": eng.POP_SIZE,
                "max_generations": getattr(eng, "max_generations", None),
                "symbol": snap.get("symbol"),
            }
            bo = snap.get("best_overall") or {}
            best_payload = {
                "genome": bo.get("gene") or best.get("gene"),
                "fitness": bo.get("fitness") or best.get("fitness"),
                "metrics": bo.get("metrics") or best.get("metrics"),
            }
            self._evo_run_id = self._evo_store.save_run(
                self._evo_run_id, params, self._evo_run_gens, best_payload)
            self._refresh_archive()
        except Exception as e:  # noqa: BLE001
            # 档案落盘失败不阻断进化主流程
            self._log(f"⚠️ 进化档案落盘失败：{e}")

    def _goto_predict(self) -> None:
        """联动跳转：携带当前学习品种到「KP预测」板块并预选该品种。"""
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
        """盈利策略库行内「🔮 预测」：跳转到 KP预测 并预载该策略基因。"""
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
        """供「KP预测」页联动：切到手动回测模式并用指定策略基因跑回测。"""
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

    def _sync_from_prediction_bus(self) -> None:
        """消费预测操作板块推送的待验证研判信号（预测 → 回测 闭环）。

        这些信号由预测页在每次研判完成时写入联动总线；回测中心在此读取并提示，
        引导用户用真实回测验证预测策略，形成「预测 → 回测验证 → 反哺预测」的自我训练。
        """
        try:
            from ..ai.linkage_bus import BUS
            pending = BUS.consume_pending_predictions()
            if pending:
                syms = ", ".join(sorted({str(p.get("symbol", "")) for p in pending}))
                self._log(f"📡 收到预测信号 {len(pending)} 条（{syms}），"
                          f"可在「手动回测」中验证其策略有效性。")
        except Exception:  # noqa: BLE001
            pass

    def _fill_perf_chips(self, m: dict) -> None:
        """绩效指标卡：夏普/回撤/年化/卡玛/胜率/盈亏比（与预测板块同口径）。"""
        p = PALETTE[self._theme]

        def setk(key, val, color=""):
            """处理setk。
            
                参数:
                    key
                    val
                    color"""
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
        """显示事件。
        
            参数:
                event"""
        super().showEvent(event)
        if not self._auto_started:
            self._auto_started = True
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(600, self._start_auto)

    def _start_auto(self) -> None:
        """启动auto。"""
        if self._closed:
            return
        try:
            from ..strategy.auto_evolve import EvolutionEngine, load_profitable
            # M2-08/M2-09：从 config 读取进化参数（seed 默认 20240921、终止条件）
            try:
                from ..config.settings import Config
                _ev = Config().evolution
                _seed = int(_ev.seed)
                _max_gen = int(_ev.max_generations)
                _patience = int(_ev.patience)
                _target = _ev.target_fitness
            except Exception:  # noqa: BLE001
                _seed, _max_gen, _patience, _target = 20240921, 200, 30, None
            self._engine = EvolutionEngine(
                self.mdm.feed, self.mdm.universe,
                seed=_seed,                       # M2-09 可复现性
                futures_params=dict(self._futures_params),
                max_generations=_max_gen,         # M2-08 终止条件
                patience=_patience,
                target_fitness=_target)
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
            # M2-10 ④：启动时刷新「进化档案」下拉
            self._refresh_archive()
            self._sync_from_prediction_bus()
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
        """构建模式switch。"""
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
        """构建manual面板。"""
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
        # M4-06⑤：手动回测的「停止」按钮（协作式，在引擎下一个检查点生效）
        self._manual_stop_btn = QPushButton("停止")
        self._manual_stop_btn.setObjectName("secondary")
        self._manual_stop_btn.setEnabled(False)
        self._manual_stop_btn.setToolTip("请求中止当前手动回测")
        self._manual_stop_btn.clicked.connect(self._stop_manual)
        row2.addWidget(self._manual_stop_btn)
        self._manual_hint = QLabel(
            "复用当前「期货参数」控制条的杠杆/保证金/乘数/交割日；"
            "交割日到达时引擎将强制平仓（与真实期货规则一致）。")
        self._manual_hint.setObjectName("sub")
        self._manual_hint.setWordWrap(True)
        row2.addWidget(self._manual_hint, 1)
        g.addLayout(row2)

    def _on_mode_toggle(self, *_args) -> None:
        """处理on模式toggle。
        
            参数:
                *_args: 可变位置参数"""
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
        """处理populatemanual合约代码。"""
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
        """处理populatemanual策略。"""
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

        # 精确基因优先（KP预测联动注入 / 历史记录「复跑」注入），
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
        self._manual_stop_btn.setEnabled(True)
        self.info.setText(f"🧪 手动回测中：{row[1]}（{sym}）· 杠杆 {lev}× · "
                          f"乘数 {mult} · 保证金 {margin_rate:.0%}"
                          f"{' · 交割日 ' + str(delivery_date) if delivery_date else ''} …")

        def work():
            """处理work。"""
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
            res = bt.run(sym, start, end, period, warmup=60,
                         should_abort=self._abort_predicate())
            return {"gene": gene, "res": res, "sym": sym, "row": row,
                    "mult": mult, "logger": logger}

        self._run_worker(work, self._on_manual_done, on_err=self._on_manual_err,
                         on_interrupted=self._on_manual_interrupted)

    # ------------------------------------------------------------------
    # M4-06⑤：手动回测中断生命周期
    # ------------------------------------------------------------------
    def _stop_manual(self) -> None:
        """请求中止当前手动回测（协作式：在引擎下一个检查点生效）。"""
        if not getattr(self, "_workers", None):
            self._end_manual_run()
            return
        self._workers[-1].requestInterruption()
        self._manual_stop_btn.setEnabled(False)
        self.info.setText("已请求停止手动回测，正在等待当前批次结束…")

    def _end_manual_run(self) -> None:
        """恢复手动回测按钮可交互态（成功 / 失败 / 中断共用）。"""
        self._manual_running = False
        if self._manual_run_btn is not None:
            self._manual_run_btn.setEnabled(True)
        self._manual_stop_btn.setEnabled(False)

    def _on_manual_interrupted(self) -> None:
        """手动回测被用户中止：不落库、不算失败，仅恢复界面。"""
        self._end_manual_run()
        if not self._closed:
            self.info.setText("手动回测已停止（未产生结果）。")

    def _on_manual_done(self, result: dict) -> None:
        """处理onmanualdone。
        
            参数:
                result: dict"""
        self._end_manual_run()
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
        # 命中回执：将本次回测结果作为后续预测调权的依据（盈利≈方向命中）
        try:
            from ..ai.linkage_bus import BUS
            hit = float(m.get("total_return", 0) or 0) > 0
            BUS.record_hit(sym, hit)
        except Exception:  # noqa: BLE001
            pass
        # ---- 双向联动：回测结果反哺预测（实时推送盈利策略画像） ----
        try:
            from ..ai.linkage_bus import BUS
            BUS.push_backtest_result(sym, gene, m)
        except Exception:  # noqa: BLE001
            pass
        # 消费预测操作板块推送的待验证信号（预测 → 回测 闭环）
        self._sync_from_prediction_bus()

    def _on_manual_err(self, msg: str) -> None:
        """处理onmanualerr。
        
            参数:
                msg: str"""
        self._end_manual_run()
        if self._closed:
            return
        self.info.setText(f"⚠️ 手动回测异常：{msg}")
        self._log(f"⚠️ 手动回测异常：{msg}")

    def _next_generation(self) -> None:
        """驱动一代进化（后台线程），完成后自动排程下一代。"""
        if self._closed or self._engine is None or self._gen_running:
            return
        if self._evolution_stopped:
            # 用户已主动停止：不再排程新一代，等待「重新开始」
            return
        if self._paused:
            # 暂停态：仅在用户点击「继续」时由 _toggle_pause 调用本方法，
            # 正常情况下不会进入（_toggle_pause 会先清 _paused 再调用）
            return
        if self._manual_mode:
            # 手动回测模式：暂停自动进化，避免覆盖手动结果
            return
        self._gen_running = True
        eng = self._engine
        sym_name, sym = eng.symbol_name(), eng.symbol()
        gen_no = eng.generation + 1
        self._cur_gen_no = gen_no
        self.info.setText(
            f"⚙️ 自动学习中：第 {gen_no} 代 · {sym_name}（{sym}）"
            f"· 种群 {eng.POP_SIZE} 个策略因子回测评估…（全程无需操作）")
        # 流水线状态灯：前三阶段亮起「进行中」
        self._set_stage(0, "good", "生成中",
                        f"第 {gen_no} 代：随机组合/交叉/变异产生 {eng.POP_SIZE} 个策略基因")
        self._set_stage(1, "good", "回测中", "逐一送入历史行情回测引擎")
        self._set_stage(2, "good", f"第{gen_no}代", "遗传算法逐代进化寻优")
        self._set_stage(3, "neutral", "等待", "回测完成后自动判定")
        self._set_stage(4, "neutral", "等待", "盈利策略将自动同步KP预测")
        # M4-09：进度可视化复位 + 按钮态（运行中可暂停/停止）
        self._evo_progress.setValue(0)
        self._evo_progress.setFormat(f"%p% · 第 {gen_no} 代")
        self._evo_stage_label.setText(
            f"⚙️ 第 {gen_no} 代 · 种群 {eng.POP_SIZE} 个策略因子回测评估中…")
        if self._evo_pause_btn is not None:
            self._evo_pause_btn.setEnabled(True)
            self._evo_pause_btn.setText("⏸ 暂停")
        if self._evo_stop_btn is not None:
            self._evo_stop_btn.setEnabled(True)

        bt_store = self._bt_store

        def work(worker):
            """后台处理一代进化，并实时上报进度（M4-09）。"""
            def _prog(done, total, text):
                worker.emit_progress(int(done / total * 100), text)
            snap = eng.step(
                should_abort=worker.isInterruptionRequested,
                on_progress=_prog,
            )
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

        self._evolution_worker = self._run_worker(
            work, self._on_gen_done, on_err=self._on_gen_err,
            on_progress=self._on_evolution_progress,
            on_interrupted=self._on_evolution_interrupted)

    def _on_gen_done(self, snap: dict) -> None:
        """处理ongendone。
        
            参数:
                snap: dict"""
        self._gen_running = False
        if self._closed:
            return
        # M4-09：进度条收尾 + 按钮态复位
        self._evo_progress.setValue(100)
        self._evo_progress.setFormat(
            f"%p% · 第 {snap.get('generation', self._cur_gen_no)} 代 完成")
        if self._evo_pause_btn is not None:
            self._evo_pause_btn.setEnabled(False)
        if self._evo_stop_btn is not None:
            self._evo_stop_btn.setEnabled(False)
        # M4-09：用户主动停止 → 不再排程下一代（验收核心：点停止后不再继续）
        if self._evolution_stopped:
            self.info.setText("🛑 进化已停止，不再排程下一代。（点击「重新开始」可恢复）")
            self._set_stage(2, "neutral", "已停止", "进化循环已停止")
            return
        # M4-09：暂停态 → 当前代已完成但不排程下一代，等待「继续」
        if self._paused:
            self.info.setText("⏸ 进化已暂停，点击「继续」恢复自我学习。")
            self._set_stage(2, "neutral", "已暂停", "等待用户继续")
            if self._evo_pause_btn is not None:
                self._evo_pause_btn.setEnabled(True)
                self._evo_pause_btn.setText("▶ 继续")
            return
        # M2-08: 进化已终止（达到终止条件），停止排程下一代并显示原因
        if snap.get("evolution_done"):
            reason = snap.get("termination_reason", "")
            gen = snap.get("generation", 0)
            max_gen = snap.get("max_generations")
            stag = snap.get("stagnation_count", 0)
            status = f"🛑 进化已终止：{reason}"
            if max_gen is not None:
                status += f"（第 {gen}/{max_gen} 代 · 已停滞 {stag} 代）"
            self.info.setText(status)
            self._log(f"🛑 {reason}")
            self._set_stage(3, "neutral", "已终止", reason)
            self._set_stage(4, "neutral", "已终止", "进化循环已停止，不再排程下一代")
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
                            "已自动写入策略库，KP预测实时读取生效")
        else:
            self._set_stage(3, "bad", "未达标",
                            "本代无策略通过盈利判定（收益/夏普/回撤/胜率/交易数联合阈值）")
            self._set_stage(4,
                            "good" if snap["profitable_total"] else "neutral",
                            f"库 {snap['profitable_total']} 条",
                            "策略库现有盈利策略持续对KP预测生效")

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
        # M2-10 ④：本代记录追加到进化档案（落盘 + 刷新下拉）
        self._save_evo_run(snap)
        if best:
            m = best["metrics"] or {}
            self._log(f"第 {snap['generation']} 代（{snap['symbol_name']}）完成："
                      f"最优「{best['desc']}」收益 {_pct(m.get('total_return'))} "
                      f"夏普 {m.get('sharpe')} 适应度 {best['fitness']}")
        for e in new_prof:
            self._log(f"💰 盈利策略入库并同步KP预测：{e['symbol_name']} · {e['desc']}"
                      f"（收益 {_pct(e['metrics'].get('total_return'))}，"
                      f"夏普 {e['metrics'].get('sharpe')}）")
        # M2-12：评估失败告警（失败率 >30% 时引擎侧已置 eval_fail_warn）
        if snap.get("eval_fail_warn"):
            self._log(f"⚠️ {snap['eval_fail_warn']}（详见日志）")
        elif snap.get("failed_count"):
            self._log(f"ℹ️ 本代 {snap['failed_count']} 个基因评估失败（已跳过）")
        if snap.get("symbol_done"):
            self._log(f"🔄 品种轮换：{snap['symbol_name']} 学习完毕，"
                      f"自动切换至「{snap.get('next_symbol_name', '')}」")

        # ---- 状态行 + 排程下一代 ----
        self.info.setText(
            f"✅ 第 {snap['generation']} 代完成 · {snap['symbol_name']}　"
            f"累计评估 {snap['evaluated_total']} 个策略，盈利库 "
            f"{snap['profitable_total']} 条（已自动同步KP预测）。"
            f"系统持续自我进化中，无需任何操作…")
        self._schedule_next()

    def _on_gen_err(self, msg: str) -> None:
        """处理ongenerr。
        
            参数:
                msg: str"""
        self._gen_running = False
        if self._closed:
            return
        if self._evolution_stopped or self._paused:
            # 停止/暂停态：不再自动重试排程
            self._evo_progress.setFormat(
                f"%p% · 第 {self._cur_gen_no} 代 异常")
            if self._evo_pause_btn is not None and self._paused:
                self._evo_pause_btn.setEnabled(True)
                self._evo_pause_btn.setText("▶ 继续")
            return
        self._log(f"⚠️ 本代进化异常：{msg}（自动重试）")
        self.info.setText(f"⚠️ 学习过程出现异常：{msg}，{ERR_RETRY_MS // 1000}s 后自动重试…")
        self._schedule_next(ERR_RETRY_MS)

    def _schedule_next(self, delay: int | None = None) -> None:
        """处理schedulenext。
        
            参数:
                delay: int | None"""
        from PyQt6.QtCore import QTimer
        # M4-09：停止/暂停态不排程下一代
        if self._evolution_stopped or self._paused:
            return
        if delay is None:
            delay = GEN_INTERVAL_MS if self.isVisible() else GEN_INTERVAL_HIDDEN_MS
        QTimer.singleShot(delay, self._next_generation)

    # ------------------------------------------------------------------
    # M4-09：长任务可视化（进度 + 取消 UI）
    # ------------------------------------------------------------------
    def _on_evolution_progress(self, pct: int, text: str) -> None:
        """进化进度回调（来自 M4-06 的 ``progress`` 信号）。

        参数:
            pct: int — 0~100 真实百分比
            text: str — 引擎上报的「基因 i/10」文本
        """
        if self._closed:
            return
        self._evo_progress.setValue(pct)
        self._evo_progress.setFormat(f"%p% · 第 {self._cur_gen_no} 代 · {text}")
        self._evo_stage_label.setText(f"⚙️ 第 {self._cur_gen_no} 代 · {text}")
        # 状态灯第 3 格同步基因进度
        self._set_stage(2, "good", text, "遗传算法逐代进化寻优（实时）")

    def _on_evolution_interrupted(self) -> None:
        """自动进化被用户中止（M4-06 ``interrupted``）：恢复界面，不排程下一代。"""
        self._gen_running = False
        self._evolution_worker = None
        if self._closed:
            return
        self._evo_progress.setFormat(
            f"%p% · 第 {self._cur_gen_no} 代 已中断")
        if self._evo_pause_btn is not None:
            self._evo_pause_btn.setEnabled(False)
        if self._evo_stop_btn is not None:
            self._evo_stop_btn.setEnabled(False)
        if self._evolution_stopped:
            # 停止语义：当前代已在基因粒度被中断
            self.info.setText(
                "🛑 进化已停止（当前代已中断）。点击「重新开始」可恢复自我学习。")
            self._set_stage(2, "neutral", "已停止", "进化循环已停止")
            if self._evo_pause_btn is not None:
                self._evo_pause_btn.setEnabled(True)
                self._evo_pause_btn.setText("🔄 重新开始")
        else:
            # 中断即暂停（未点停止）：等待继续
            self._paused = True
            self.info.setText("⏸ 进化已暂停，点击「继续」恢复自我学习。")
            self._set_stage(2, "neutral", "已暂停", "等待用户继续")
            if self._evo_pause_btn is not None:
                self._evo_pause_btn.setEnabled(True)
                self._evo_pause_btn.setText("▶ 继续")

    def _toggle_pause(self) -> None:
        """暂停/继续/重新开始 三态切换（M4-09）。"""
        if self._evolution_stopped:
            self._restart_evolution()
            return
        if self._gen_running and not self._paused:
            # 正在跑一代：置暂停标志，当前代结束后不再排程下一代
            self._paused = True
            self._evo_pause_btn.setText("▶ 继续")
            self.info.setText("⏸ 进化已暂停，当前代结束后不再排程（点击「继续」恢复）。")
        elif self._paused:
            # 恢复：清暂停标志并立即排程下一代
            self._paused = False
            self._evo_pause_btn.setText("⏸ 暂停")
            self.info.setText("▶ 恢复自我学习…")
            if not self._gen_running:
                self._next_generation()

    def _stop_evolution(self) -> None:
        """停止自动进化（M4-09）：请求中断当前代 + 标记不再排程下一代。"""
        if self._evolution_stopped and not self._gen_running:
            return
        self._evolution_stopped = True
        self._paused = False
        if self._evolution_worker is not None:
            try:
                self._evolution_worker.requestInterruption()
            except Exception:  # noqa: BLE001
                pass
        if self._evo_stop_btn is not None:
            self._evo_stop_btn.setEnabled(False)
        if self._evo_pause_btn is not None:
            self._evo_pause_btn.setText("🔄 重新开始")
            self._evo_pause_btn.setEnabled(True)
        self.info.setText(
            "🛑 进化已停止，不再排程下一代（点击「重新开始」可恢复）。")

    def _restart_evolution(self) -> None:
        """从停止态恢复自我学习（M4-09）。"""
        self._evolution_stopped = False
        self._paused = False
        if self._evo_pause_btn is not None:
            self._evo_pause_btn.setText("⏸ 暂停")
            self._evo_pause_btn.setEnabled(True)
        if self._evo_stop_btn is not None:
            self._evo_stop_btn.setEnabled(True)
        if self._engine is None:
            self._start_auto()
        elif not self._gen_running:
            self._next_generation()

    # ------------------------------------------------------------------
    # 渲染辅助
    # ------------------------------------------------------------------
    def _set_stage(self, idx: int, level: str, value: str, tip: str = "") -> None:
        """设置stage。
        
            参数:
                idx: int
                level: str
                value: str
                tip: str"""
        try:
            self._stage_tiles[idx].set_status(level, value, tip)
        except Exception:  # noqa: BLE001
            pass

    def _log(self, text: str) -> None:
        """记录日志相关对象。
        
            参数:
                text: str"""
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
        """更新curves。
        
            参数:
                snap: dict"""
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
        """处理fillpopulation。
        
            参数:
                ranked: list"""
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
        # 同时填充因子重要性表
        self._fill_factor_importance(ranked)
        # 填充新增的因子分析标签页
        self._fill_factor_correlation(ranked)
        self._fill_factor_tune(ranked)
        self._fill_factor_monitor(ranked)

    def _fill_factor_importance(self, ranked: list) -> None:
        """基于当代种群计算因子重要性（参数敏感度分析）。
        
        参数:
            ranked: 当代种群排行列表，每项包含 params、metrics、fitness 等"""
        self.factor_tbl.setRowCount(0)
        prepare_table(self.factor_tbl, self._theme)
        if len(ranked) < 5:
            self.factor_tbl.setRowCount(1)
            self.factor_tbl.setItem(0, 0, QTableWidgetItem("样本不足（需≥5个策略）"))
            self.factor_tbl.setItem(0, 1, QTableWidgetItem("--"))
            self.factor_tbl.setItem(0, 2, QTableWidgetItem("--"))
            self.factor_tbl.setItem(0, 3, QTableWidgetItem("--"))
            self.factor_tbl.setItem(0, 4, QTableWidgetItem("--"))
            return
        
        try:
            # 收集所有出现过的参数
            param_names = set()
            for r in ranked:
                params = r.get("params", {})
                for k in params.keys():
                    param_names.add(k)
            param_names = sorted(param_names)
            
            # 计算每个参数的重要性：基于该参数变化对收益/夏普的影响
            factor_scores = {}
            for pname in param_names:
                # 按该参数值分组，计算组内收益/夏普的方差作为敏感度
                groups = {}
                for r in ranked:
                    val = r.get("params", {}).get(pname)
                    if val is not None:
                        key = str(val)
                        if key not in groups:
                            groups[key] = {"returns": [], "sharpes": []}
                        m = r.get("metrics", {})
                        if m.get("total_return") is not None:
                            groups[key]["returns"].append(m["total_return"])
                        if m.get("sharpe") is not None:
                            groups[key]["sharpes"].append(m["sharpe"])
                
                # 计算组间方差（敏感度）
                if len(groups) >= 2:
                    all_returns = []
                    all_sharpes = []
                    for g in groups.values():
                        if g["returns"]:
                            all_returns.append(sum(g["returns"]) / len(g["returns"]))
                        if g["sharpes"]:
                            all_sharpes.append(sum(g["sharpes"]) / len(g["sharpes"]))
                    
                    if len(all_returns) >= 2:
                        import numpy as np
                        ret_var = np.var(all_returns) if len(all_returns) > 1 else 0
                        sharpe_var = np.var(all_sharpes) if len(all_sharpes) > 1 else 0
                        # 综合得分：收益敏感度 + 夏普敏感度
                        score = ret_var * 10000 + sharpe_var * 100
                        factor_scores[pname] = {
                            "score": score,
                            "groups": groups,
                            "ret_var": ret_var,
                            "sharpe_var": sharpe_var
                        }
            
            if not factor_scores:
                self.factor_tbl.setRowCount(1)
                self.factor_tbl.setItem(0, 0, QTableWidgetItem("无有效因子变异"))
                return
            
            # 按重要性排序
            sorted_factors = sorted(factor_scores.items(), key=lambda x: -x[1]["score"])
            
            self.factor_tbl.setRowCount(len(sorted_factors))
            p = PALETTE[self._theme]
            for i, (fname, fdata) in enumerate(sorted_factors):
                # 因子名称（使用中文缩写）
                name_item = QTableWidgetItem(OPT_PARAM_SHORT.get(fname, fname))
                name_item.setToolTip(f"原始参数名: {fname}")
                self.factor_tbl.setItem(i, 0, name_item)
                
                # 重要性得分（归一化 0-100）
                max_score = sorted_factors[0][1]["score"] if sorted_factors else 1
                norm_score = (fdata["score"] / max_score * 100) if max_score > 0 else 0
                score_item = QTableWidgetItem(f"{norm_score:.1f}")
                if norm_score >= 70:
                    score_item.setForeground(_qcolor("up"))
                elif norm_score >= 40:
                    score_item.setForeground(_qcolor("text"))
                else:
                    score_item.setForeground(_qcolor("down"))
                self.factor_tbl.setItem(i, 1, score_item)
                
                # 收益贡献度（基于收益方差占比）
                total_ret_var = sum(v["ret_var"] for v in factor_scores.values())
                contrib = (fdata["ret_var"] / total_ret_var * 100) if total_ret_var > 0 else 0
                contrib_item = QTableWidgetItem(f"{contrib:.1f}%")
                contrib_item.setToolTip(f"该参数取值变化解释的收益方差占比")
                self.factor_tbl.setItem(i, 2, contrib_item)
                
                # 稳定性（组内收益的一致性，CV越小越稳定）
                stabilities = []
                for g in fdata["groups"].values():
                    if len(g["returns"]) >= 2:
                        import numpy as np
                        mean_r = np.mean(g["returns"])
                        std_r = np.std(g["returns"])
                        cv = std_r / abs(mean_r) if mean_r != 0 else 10
                        stabilities.append(1 / (1 + cv))
                stability = (sum(stabilities) / len(stabilities) * 100) if stabilities else 50
                stab_item = QTableWidgetItem(f"{stability:.0f}%")
                stab_item.setToolTip("参数同值下不同策略收益的一致性（越高越稳定）")
                self.factor_tbl.setItem(i, 3, stab_item)
                
                # 推荐区间（表现最好的参数值范围）
                best_group = max(fdata["groups"].items(), 
                                key=lambda x: sum(x[1]["returns"])/len(x[1]["returns"]) if x[1]["returns"] else -1e9)
                best_val = best_group[0]
                # 找出表现前50%的参数值
                group_perfs = []
                for gval, gdata in fdata["groups"].items():
                    if gdata["returns"]:
                        avg_ret = sum(gdata["returns"]) / len(gdata["returns"])
                        group_perfs.append((gval, avg_ret))
                group_perfs.sort(key=lambda x: -x[1])
                top_half = group_perfs[:max(1, len(group_perfs)//2)]
                if len(top_half) == 1:
                    rec_range = top_half[0][0]
                else:
                    vals = [v[0] for v in top_half]
                    rec_range = f"{min(vals)} ~ {max(vals)}"
                range_item = QTableWidgetItem(rec_range)
                range_item.setToolTip(f"建议参数取值区间（基于当代种群表现前50%）")
                self.factor_tbl.setItem(i, 4, range_item)
                
        except Exception as e:
            self.factor_tbl.setRowCount(1)
            self.factor_tbl.setItem(0, 0, QTableWidgetItem(f"计算异常: {str(e)[:30]}"))

    # ============================================================================
    # 因子相关性分析（热力图 + 冗余检测）
    # ============================================================================
    def _fill_factor_correlation(self, ranked: list) -> None:
        """计算并展示因子间的相关性矩阵，识别冗余因子。
        
        参数:
            ranked: 当代种群排行列表
        """
        self.factor_corr_tbl.setRowCount(0)
        prepare_table(self.factor_corr_tbl, self._theme)
        
        if len(ranked) < FACTOR_ANALYSIS_CONFIG["min_samples"]:
            self.factor_corr_tbl.setRowCount(1)
            self.factor_corr_tbl.setColumnCount(1)
            self.factor_corr_tbl.setHorizontalHeaderLabels(["提示"])
            self.factor_corr_tbl.setItem(0, 0, QTableWidgetItem(
                f"样本不足（需≥{FACTOR_ANALYSIS_CONFIG['min_samples']}个策略），无法计算相关性"))
            return
        
        try:
            import numpy as np
            
            # 收集所有因子参数
            param_names = set()
            for r in ranked:
                params = r.get("params", {})
                for k in params.keys():
                    param_names.add(k)
            param_names = sorted(param_names)
            
            if len(param_names) < 2:
                self.factor_corr_tbl.setRowCount(1)
                self.factor_corr_tbl.setColumnCount(1)
                self.factor_corr_tbl.setHorizontalHeaderLabels(["提示"])
                self.factor_corr_tbl.setItem(0, 0, QTableWidgetItem("因子数量不足，无法计算相关性"))
                return
            
            # 构建因子矩阵：行=策略，列=因子参数值
            n_strategies = len(ranked)
            n_factors = len(param_names)
            factor_matrix = np.full((n_strategies, n_factors), np.nan)
            
            for i, r in enumerate(ranked):
                params = r.get("params", {})
                for j, pname in enumerate(param_names):
                    val = params.get(pname)
                    if val is not None:
                        factor_matrix[i, j] = float(val)
            
            # 计算相关性矩阵（优先使用 Spearman 秩相关，回退到 Pearson）
            corr_matrix = np.full((n_factors, n_factors), np.nan)
            for i in range(n_factors):
                for j in range(n_factors):
                    if i == j:
                        corr_matrix[i, j] = 1.0
                    else:
                        col_i = factor_matrix[:, i]
                        col_j = factor_matrix[:, j]
                        # 只使用两列都有值的行
                        mask = ~np.isnan(col_i) & ~np.isnan(col_j)
                        if mask.sum() >= 3:
                            x = col_i[mask]
                            y = col_j[mask]
                            # 尝试 Spearman（需要 scipy），回退到 Pearson
                            try:
                                from scipy.stats import spearmanr
                                corr, _ = spearmanr(x, y)
                                corr_matrix[i, j] = corr if not np.isnan(corr) else 0.0
                            except ImportError:
                                # 回退到 Pearson 相关系数
                                corr_matrix[i, j] = np.corrcoef(x, y)[0, 1]
                        else:
                            corr_matrix[i, j] = 0.0
            
            # 设置表格
            self.factor_corr_tbl.setRowCount(n_factors)
            self.factor_corr_tbl.setColumnCount(n_factors + 1)
            headers = ["因子\\因子"] + [OPT_PARAM_SHORT.get(p, p) for p in param_names]
            self.factor_corr_tbl.setHorizontalHeaderLabels(headers)
            
            p = PALETTE[self._theme]
            threshold = FACTOR_ANALYSIS_CONFIG["correlation_threshold"]
            
            for i in range(n_factors):
                # 第一列：因子名称
                name_item = QTableWidgetItem(OPT_PARAM_SHORT.get(param_names[i], param_names[i]))
                name_item.setToolTip(f"原始参数名: {param_names[i]}")
                self.factor_corr_tbl.setItem(i, 0, name_item)
                
                for j in range(n_factors):
                    corr = corr_matrix[i, j]
                    if np.isnan(corr):
                        item = QTableWidgetItem("--")
                    else:
                        item = QTableWidgetItem(f"{corr:.2f}")
                        # 颜色编码：红=高正相关，蓝=高负相关，白=无相关
                        if abs(corr) >= threshold:
                            if corr > 0:
                                item.setForeground(_qcolor("up"))  # 高正相关 = 红
                                item.setToolTip(f"⚠️ 高正相关 ({corr:.2f})：{param_names[i]} 与 {param_names[j]} 可能冗余")
                            else:
                                item.setForeground(QColor("#3b82f6"))  # 高负相关 = 蓝
                                item.setToolTip(f"高负相关 ({corr:.2f})：{param_names[i]} 与 {param_names[j]} 互补")
                        elif abs(corr) >= 0.4:
                            item.setForeground(_qcolor("text"))  # 中等相关 = 默认色
                            item.setToolTip(f"中等相关 ({corr:.2f})")
                        else:
                            item.setForeground(_qcolor("sub"))  # 低相关 = 灰
                            item.setToolTip(f"低相关 ({corr:.2f})：基本独立")
                        
                        # 对角线高亮
                        if i == j:
                            item.setBackground(_qcolor_bg("#10b981", alpha=30))
                            item.setForeground(_qcolor("up"))
                    
                    self.factor_corr_tbl.setItem(i, j + 1, item)
            
            # 检测冗余因子对
            redundant_pairs = []
            for i in range(n_factors):
                for j in range(i + 1, n_factors):
                    if abs(corr_matrix[i, j]) >= threshold:
                        redundant_pairs.append((param_names[i], param_names[j], corr_matrix[i, j]))
            
            if redundant_pairs:
                self._log(f"⚠️ 检测到 {len(redundant_pairs)} 对高相关因子（阈值≥{threshold}），建议参数调优时注意冗余")
            
        except Exception as e:
            self.factor_corr_tbl.setRowCount(1)
            self.factor_corr_tbl.setColumnCount(1)
            self.factor_corr_tbl.setHorizontalHeaderLabels(["错误"])
            self.factor_corr_tbl.setItem(0, 0, QTableWidgetItem(f"相关性计算异常: {str(e)[:50]}"))

    # ============================================================================
    # 因子参数调优界面（自定义参数范围 + 网格搜索预期收益估算）
    # ============================================================================
    def _fill_factor_tune(self, ranked: list) -> None:
        """基于当代种群表现，为每个因子推荐调优范围和最优值。
        
        参数:
            ranked: 当代种群排行列表
        """
        self.factor_tune_tbl.setRowCount(0)
        prepare_table(self.factor_tune_tbl, self._theme)
        
        if len(ranked) < FACTOR_ANALYSIS_CONFIG["min_samples"]:
            self.factor_tune_tbl.setRowCount(1)
            self.factor_tune_tbl.setItem(0, 0, QTableWidgetItem("样本不足，无法生成调优建议"))
            return
        
        try:
            # 收集所有因子参数
            param_names = set()
            for r in ranked:
                params = r.get("params", {})
                for k in params.keys():
                    param_names.add(k)
            param_names = sorted(param_names)
            
            if not param_names:
                self.factor_tune_tbl.setRowCount(1)
                self.factor_tune_tbl.setItem(0, 0, QTableWidgetItem("无可调优因子"))
                return
            
            # 获取当前最优策略的参数作为基准
            best_params = ranked[0].get("params", {}) if ranked else {}
            
            self.factor_tune_tbl.setRowCount(len(param_names))
            
            for i, pname in enumerate(param_names):
                # 因子名称
                name_item = QTableWidgetItem(OPT_PARAM_SHORT.get(pname, pname))
                name_item.setToolTip(f"原始参数名: {pname}")
                self.factor_tune_tbl.setItem(i, 0, name_item)
                
                # 当前值（最优策略的值）
                curr_val = best_params.get(pname, "—")
                curr_item = QTableWidgetItem(str(curr_val))
                curr_item.setToolTip(f"当前最优策略的参数值")
                self.factor_tune_tbl.setItem(i, 1, curr_item)
                
                # 收集该参数在所有策略中的取值
                values = []
                perf_map = {}  # 值 -> 平均收益
                for r in ranked:
                    val = r.get("params", {}).get(pname)
                    ret = r.get("metrics", {}).get("total_return")
                    if val is not None and ret is not None:
                        val_str = str(val)
                        values.append(val)
                        if val_str not in perf_map:
                            perf_map[val_str] = []
                        perf_map[val_str].append(ret)
                
                if not values:
                    self.factor_tune_tbl.setItem(i, 2, QTableWidgetItem("无数据"))
                    self.factor_tune_tbl.setItem(i, 3, QTableWidgetItem("—"))
                    self.factor_tune_tbl.setItem(i, 4, QTableWidgetItem("—"))
                    self.factor_tune_tbl.setItem(i, 5, QTableWidgetItem("—"))
                    continue
                
                # 计算各取值的平均表现
                val_perf = {}
                for v, rets in perf_map.items():
                    val_perf[v] = sum(rets) / len(rets)
                
                # 推荐调优范围：表现前50%的值的范围
                sorted_vals = sorted(val_perf.items(), key=lambda x: -x[1])
                top_half = sorted_vals[:max(1, len(sorted_vals) // 2)]
                top_vals = [float(v[0]) for v in top_half]
                
                min_val, max_val = min(top_vals), max(top_vals)
                if min_val == max_val:
                    range_text = str(min_val)
                else:
                    range_text = f"{min_val:.4g} ~ {max_val:.4g}"
                
                range_item = QTableWidgetItem(range_text)
                range_item.setToolTip(f"建议调优范围（基于表现前50%策略的参数值分布）")
                self.factor_tune_tbl.setItem(i, 2, range_item)
                
                # 步长建议（基于值的分布密度）
                if len(set(top_vals)) > 1:
                    sorted_unique = sorted(set(top_vals))
                    diffs = [sorted_unique[k+1] - sorted_unique[k] for k in range(len(sorted_unique)-1)]
                    step = min(diffs) if diffs else 1
                    step_text = f"{step:.4g}"
                else:
                    step_text = "1"
                step_item = QTableWidgetItem(step_text)
                step_item.setToolTip("建议网格搜索步长（基于当前值分布的最小间隔）")
                self.factor_tune_tbl.setItem(i, 3, step_item)
                
                # 最优值（表现最好的参数值）
                best_val = sorted_vals[0][0] if sorted_vals else "—"
                best_item = QTableWidgetItem(str(best_val))
                best_item.setForeground(_qcolor("up"))
                best_item.setToolTip(f"当前种群中表现最优的参数值（平均收益: {val_perf.get(str(best_val), 0):.4f}）")
                self.factor_tune_tbl.setItem(i, 4, best_item)
                
                # 预期提升（相对于当前值的边际收益）
                curr_val_str = str(curr_val)
                if curr_val_str in val_perf and best_val in val_perf:
                    curr_perf = val_perf[curr_val_str]
                    best_perf = val_perf[str(best_val)]
                    improvement = (best_perf - curr_perf) * 100  # 转为百分点
                    imp_item = QTableWidgetItem(f"{improvement:+.2f}%")
                    if improvement > 0:
                        imp_item.setForeground(_qcolor("up"))
                    elif improvement < 0:
                        imp_item.setForeground(_qcolor("down"))
                    imp_item.setToolTip(f"切换到最优值预期可提升的收益率（百分点）")
                    self.factor_tune_tbl.setItem(i, 5, imp_item)
                else:
                    self.factor_tune_tbl.setItem(i, 5, QTableWidgetItem("—"))
            
        except Exception as e:
            self.factor_tune_tbl.setRowCount(1)
            self.factor_tune_tbl.setItem(0, 0, QTableWidgetItem(f"调优建议生成异常: {str(e)[:50]}"))

    # ============================================================================
    # 因子绩效监控（历史表现追踪 + 预警）
    # ============================================================================
    def _fill_factor_monitor(self, ranked: list) -> None:
        """监控因子的历史绩效表现，提供预警机制。
        
        参数:
            ranked: 当代种群排行列表
        """
        self.factor_monitor_tbl.setRowCount(0)
        prepare_table(self.factor_monitor_tbl, self._theme)
        
        if len(ranked) < FACTOR_ANALYSIS_CONFIG["min_samples"]:
            self.factor_monitor_tbl.setRowCount(1)
            self.factor_monitor_tbl.setItem(0, 0, QTableWidgetItem("样本不足，无法生成监控指标"))
            return
        
        try:
            import numpy as np
            
            # 从历史数据库获取长期绩效数据
            history_data = []
            if self._bt_store is not None:
                try:
                    # 获取最近的历史记录用于长期监控
                    hist = self._bt_store.recent_history(200)
                    for rec in hist:
                        best_desc = rec.get("best_desc", "")
                        # 解析策略描述中的参数
                        # 这里简化处理：使用当前种群的参数分布作为代理
                        pass
                except Exception:
                    pass
            
            # 收集所有因子参数
            param_names = set()
            for r in ranked:
                params = r.get("params", {})
                for k in params.keys():
                    param_names.add(k)
            param_names = sorted(param_names)
            
            if not param_names:
                self.factor_monitor_tbl.setRowCount(1)
                self.factor_monitor_tbl.setItem(0, 0, QTableWidgetItem("无可监控因子"))
                return
            
            self.factor_monitor_tbl.setRowCount(len(param_names))
            
            # 计算每个因子的监控指标
            for i, pname in enumerate(param_names):
                # 因子名称
                name_item = QTableWidgetItem(OPT_PARAM_SHORT.get(pname, pname))
                name_item.setToolTip(f"原始参数名: {pname}")
                self.factor_monitor_tbl.setItem(i, 0, name_item)
                
                # 收集该因子在当代种群中的表现分布
                values = []
                returns = []
                sharpes = []
                drawdowns = []
                win_rates = []
                
                for r in ranked:
                    val = r.get("params", {}).get(pname)
                    m = r.get("metrics", {})
                    if val is not None:
                        values.append(float(val))
                        if m.get("total_return") is not None:
                            returns.append(m["total_return"])
                        if m.get("sharpe") is not None:
                            sharpes.append(m["sharpe"])
                        if m.get("max_drawdown") is not None:
                            drawdowns.append(m["max_drawdown"])
                        if m.get("win_rate") is not None:
                            win_rates.append(m["win_rate"])
                
                if not returns:
                    for c in range(1, 8):
                        self.factor_monitor_tbl.setItem(i, c, QTableWidgetItem("无数据"))
                    continue
                
                # 历史平均收益
                avg_ret = np.mean(returns)
                ret_item = QTableWidgetItem(f"{avg_ret*100:+.2f}%")
                ret_item.setForeground(_qcolor("up" if avg_ret >= 0 else "down"))
                self.factor_monitor_tbl.setItem(i, 1, ret_item)
                
                # 历史夏普
                avg_sharpe = np.mean(sharpes) if sharpes else 0
                sharpe_item = QTableWidgetItem(f"{avg_sharpe:.2f}")
                sharpe_item.setForeground(_qcolor("up" if avg_sharpe >= 1 else ("text" if avg_sharpe >= 0 else "down")))
                self.factor_monitor_tbl.setItem(i, 2, sharpe_item)
                
                # 历史最大回撤
                avg_dd = np.mean(drawdowns) if drawdowns else 0
                dd_item = QTableWidgetItem(f"{avg_dd*100:.2f}%")
                dd_item.setForeground(_qcolor("up"))  # 回撤显红（警示）
                self.factor_monitor_tbl.setItem(i, 3, dd_item)
                
                # 胜率稳定性（胜率的变异系数倒数）
                if len(win_rates) >= 2:
                    wr_mean = np.mean(win_rates)
                    wr_std = np.std(win_rates)
                    wr_cv = wr_std / wr_mean if wr_mean != 0 else 10
                    wr_stability = 1 / (1 + wr_cv) * 100
                else:
                    wr_stability = 50
                stab_item = QTableWidgetItem(f"{wr_stability:.0f}%")
                stab_item.setToolTip("胜率在不同参数取值下的稳定性（越高越稳定）")
                self.factor_monitor_tbl.setItem(i, 4, stab_item)
                
                # 参数敏感度（收益方差）
                ret_var = np.var(returns) if len(returns) >= 2 else 0
                sens_item = QTableWidgetItem(f"{ret_var*10000:.2f}")
                sens_item.setToolTip("参数取值变化导致的收益方差（越大越敏感，需谨慎调优）")
                self.factor_monitor_tbl.setItem(i, 5, sens_item)
                
                # 近期趋势（最近3代最优策略中该参数的变化趋势）
                trend_text = "→"
                trend_color = _qcolor("text")
                if len(ranked) >= 3:
                    recent_best_vals = [r.get("params", {}).get(pname) for r in ranked[:3]]
                    recent_best_vals = [v for v in recent_best_vals if v is not None]
                    if len(recent_best_vals) >= 2:
                        if recent_best_vals[0] > recent_best_vals[-1]:
                            trend_text = "▲ 上升"
                            trend_color = _qcolor("up")
                        elif recent_best_vals[0] < recent_best_vals[-1]:
                            trend_text = "▼ 下降"
                            trend_color = _qcolor("down")
                trend_item = QTableWidgetItem(trend_text)
                trend_item.setForeground(trend_color)
                trend_item.setToolTip("近期最优策略中该参数的演化趋势")
                self.factor_monitor_tbl.setItem(i, 6, trend_item)
                
                # 预警状态
                alerts = []
                if avg_sharpe < 0.5:
                    alerts.append("夏普偏低")
                if avg_dd > 0.2:
                    alerts.append("回撤过大")
                if wr_stability < 30:
                    alerts.append("胜率不稳")
                if ret_var * 10000 > 50:
                    alerts.append("高敏感")
                if avg_ret < 0:
                    alerts.append("均值为负")
                
                alert_text = "、".join(alerts) if alerts else "✅ 正常"
                alert_item = QTableWidgetItem(alert_text)
                if alerts:
                    alert_item.setForeground(_qcolor("up"))
                    alert_item.setToolTip("⚠️ 预警：" + "；".join(alerts))
                else:
                    alert_item.setForeground(_qcolor("down"))
                    alert_item.setToolTip("✅ 该因子各项指标均在正常范围内")
                self.factor_monitor_tbl.setItem(i, 7, alert_item)
                
        except Exception as e:
            self.factor_monitor_tbl.setRowCount(1)
            self.factor_monitor_tbl.setItem(0, 0, QTableWidgetItem(f"监控指标计算异常: {str(e)[:50]}"))

    def _fill_library(self, lib: list) -> None:
        """处理filllibrary。
        
            参数:
                lib: list"""
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
            s_item = QTableWidgetItem("✅ 已同步KP预测")
            s_item.setForeground(_qcolor("up"))
            s_item.setToolTip("该策略已写入盈利策略库，KP预测模块实时读取其方向信号并融合进预测")
            self.lib_tbl.setItem(i, 8, s_item)
            # 第 9 列：联动跳转「KP预测」并预载该策略基因
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
        """设置hist行。
        
            参数:
                i: int
                rec: dict"""
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
        """关闭事件。
        
            参数:
                event"""
        if self._bt_store is not None:
            try:
                self._bt_store.checkpoint()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)

    # ------------------------------------------------------------------
    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        super().set_theme(t)
        for tile in self._stage_tiles:
            tile.set_theme(t)
        for chip in self._chips.values():
            chip.set_theme(t)
        for chip in self._perf_chips.values():
            chip.set_theme(t)
        if self._last_snapshot:
            ranked = self._last_snapshot.get("ranked") or []
            self._fill_population(ranked)
            self._fill_library(self._last_snapshot.get("library") or [])
        if self._bt_store is not None:
            self._fill_history(self._bt_store.recent_history(300))
