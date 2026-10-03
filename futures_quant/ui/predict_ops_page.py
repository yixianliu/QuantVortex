"""预测操作板块：统一"KP预测"与"选品机会"两大功能。

核心交互流程：
1. 用户选择目标品种 + 点击"开始预测"按钮触发KP预测
2. 展示基本面分析、K线图分析及K线图预测路线
3. K线图上明确标注建议买入价格与卖出价格位置
4. 保留选品机会的评分排行功能作为子面板

设计原则：
- 用户选择品种 → 点击"开始预测" → 一次性完成全部预测流程
- K线图结合趋势分析，标注交易参考点
- 品种排行作为辅助面板，提供"可考虑入手"的品种参考
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import time
from bisect import bisect_right
from typing import Optional

import numpy as np
import pandas as pd

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTextEdit, QTableWidgetItem, QHeaderView, QFrame,
    QSplitter, QSizePolicy, QAbstractItemView, QTabWidget, QSpinBox,
    QProgressBar, QCheckBox, QDialog,
)

from .widgets import (
    PageHeader, Badge, StatCard, ConfidenceBar, SectionHeader,
    color_pnl, pal, THEME, ToolBar, PALETTE,
)
from .states import DataGrid   # M4-08：统一表格能力（排序 / 右键菜单 / 列显隐 / 空态）
from .icons import icon
from .chart_widget import KLineChart, PriceChart, ReliabilityChart
from .pages import BasePage, Worker, df_to_bars, symbol_code, symbol_label, PERIODS, PERIOD_LABEL

logger = logging.getLogger(__name__)
from ..data.market_data import MarketDataManager
from ..indicators.tech import add_indicators, cached_add_indicators
# 以下重型模块延迟导入：仅在使用时才加载，避免启动时阻塞
# from ..ai.predictor import FuturesPredictor          → 延迟
# from ..ai.feedback import ...                        → 延迟
# from ..ai.calibration_replay import ...               → 延迟
# from ..ai import news_feed                            → 延迟
# from ..strategy.auto_evolve import ...                → 延迟
# from ..ai.linkage_bus import BUS                      → 延迟
# from ..analysis.signals import resonance, trend_score → 延迟
from ..core.metric_schema import format_metric, backtest_linkage_for, METRIC_LABEL
from ..storage.analysis_store import AnalysisStore
from ..ai.feedback import calibration_band_at
from ..strategy.auto_evolve import describe_gene


# ============================================================================
# 选品评分引擎（移植自 screening_page，因子从原始 df 计算，AI方向用廉价岭回归）
# ============================================================================
def _screen(mdm, store=None):
    """对全合约做「入手机会」评分，返回 (品种列表, 板块聚合列表)。

    评分 = 100 × (0.70·五因子分位 + 0.12·波动适中 + 0.18·AI方向概率分位)。
    五因子（均为正向贡献，按全样本分位归一化，避免量纲差异）：
        ret20  近20日涨幅（动量，留上行空间，>22% 做折让避免追高）
        ma_gap 均线乖离（MA5/MA20-1，多头排列越好越高）
        fund   近20日资金流强度
        vr     量比（近半 vs 前半）
        oi     持仓变化
    AI 方向概率使用 FuturesPredictor 的 force_ridge 快速岭回归（进程内廉价，
    秒级），失败回退中性 0.5，不阻塞主流程。
    """
    REQUIRED = 65          # 因子计算所需最少日线根数
    LOOKBACK = 130         # 取数窗口（含 MA60 余量）
    rows = mdm.universe
    raw = []

    def _empty(sym, name, cat, reason):
        """处理empty。
        
            参数:
                sym
                name
                cat
                reason"""
        raw.append({"sym": sym, "name": name, "cat": cat,
                    "score": 0.0, "tier": "样本不足", "ret": 0.0,
                    "pu": 0.5, "reason": reason})

    for r in rows:
        sym = symbol_code(r)
        name, cat = r[1], r[2]
        try:
            df = mdm.get_bars(sym, "D", LOOKBACK)
        except Exception:
            _empty(sym, name, cat, "取数异常")
            continue
        if df is None or len(df) < REQUIRED:
            _empty(sym, name, cat, "数据不足")
            continue
        try:
            close = df["close"].astype(float)
            if float(close.iloc[-1]) <= 0 or len(close) < 22:
                _empty(sym, name, cat, "数据异常")
                continue
            # 近 20 日涨幅（动量）
            ret_20 = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1.0) * 100.0
            # 均线乖离（多头排列强度）
            ma5 = float(close.tail(5).mean())
            ma20 = float(close.tail(20).mean())
            ma_gap = (ma5 / ma20 - 1.0) * 100.0 if ma20 else 0.0
            # 量比（近半 vs 前半）
            half = max(1, len(df) // 2)
            vol_recent = float(df["volume"].tail(half).mean())
            vol_prior = float(df["volume"].head(half).mean())
            vr = vol_recent / vol_prior if vol_prior else 1.0
            # 持仓变化
            if "open_interest" in df.columns:
                oi_now = float(df["open_interest"].iloc[-1])
                oi_prev = float(df["open_interest"].iloc[half])
                oi = (oi_now - oi_prev) / oi_prev * 100.0 if oi_prev else 0.0
            else:
                oi = 0.0
            # 资金流（(收-开)×量×收×乘数 近20日累计，单位亿）
            mult = float(r[4]) if len(r) > 4 and r[4] else 1.0
            fund = float(((df["close"] - df["open"]) * df["volume"]
                          * df["close"] * mult).tail(20).sum() / 1e8)
            # 年化波动
            pct = close.pct_change().dropna()
            vol_20 = (float(pct.tail(20).std()) * math.sqrt(252) * 100.0
                      if len(pct) >= 20 else 0.0)
            # AI 方向概率（廉价岭回归；任何异常回退 0.5）
            try:
                from ..ai.predictor import FuturesPredictor as _FP
                pr = _FP()
                pr.fit(df, seq_len=20, epochs=15, force_ridge=True)
                pp = pr.predict(df, horizon=5)
                pu = float(pp["p_up"])
            except Exception:
                pu = 0.5
            raw.append({"sym": sym, "name": name, "cat": cat,
                        "ret_20": ret_20, "ma_gap": ma_gap, "vr": vr,
                        "oi": oi, "fund": fund, "vol_20": vol_20, "pu": pu})
        except Exception:
            _empty(sym, name, cat, "计算异常")
            continue

    if not raw:
        return [], []

    # ---- 数据驱动分位加权：用全样本分位替代拍脑袋权重，直接反映各因子强度 ----
    def _rank(vals):
        """处理rank。
        
            参数:
                vals"""
        s = sorted(vals)
        n = len(s) or 1
        return [bisect_right(s, v) / n for v in vals]

    rt = _rank([r.get("ret_20", 0.0) for r in raw])
    rm = _rank([r.get("ma_gap", 0.0) for r in raw])
    rf = _rank([r.get("fund", 0.0) for r in raw])
    rv = _rank([r.get("vr", 1.0) for r in raw])
    ro = _rank([r.get("oi", 0.0) for r in raw])
    rpu = _rank([r.get("pu", 0.5) for r in raw])

    for i, r in enumerate(raw):
        vol_score = max(0.0, 1.0 - abs(r.get("vol_20", 0.0) - 28.0) / 35.0)
        f = (0.30 * rt[i] + 0.20 * rm[i] + 0.20 * rf[i]
             + 0.15 * rv[i] + 0.15 * ro[i])
        score = 100.0 * (0.70 * f + 0.12 * vol_score + 0.18 * rpu[i])
        # 追高折让：近 20 日已大幅上涨（透支上行空间）则下调入手吸引力
        if r.get("ret_20", 0.0) > 22:
            score *= 0.8
        r["score"] = round(max(0.0, min(100.0, score)), 1)
        r["ret"] = round(r.get("ret_20", 0.0), 1)
        r["pu"] = round(r.get("pu", 0.5), 3)
        s = r["score"]
        r["tier"] = ("优先入手" if s >= 68 else
                     "可留意" if s >= 55 else "暂观望")
        r["reason"] = ""

    raw.sort(key=lambda x: -x["score"])

    # ---- 板块聚合 ----
    cat_map = {}
    for r in raw:
        cat_map.setdefault(r["cat"], []).append(r)
    cats = []
    for c, items in cat_map.items():
        avg = np.mean([it["score"] for it in items])
        rec = sum(1 for it in items if it["score"] >= 68)
        cats.append({"cat": c, "avg": round(avg, 1), "n": len(items),
                     "rec": rec, "items": items})
    cats.sort(key=lambda x: -x["avg"])
    return raw, cats


# 校准区间宽度阈值（Wilson 95%）：本次预测落点处区间宽于此值视为「校准不可信」，
# 触发实时研判徽章降级为「⚠低置信」。区间越宽 = 该档概率的校准样本越稀疏。
LOW_CONF_BAND_WIDTH = 0.25


# ============================================================================
# 预测操作页面
# ============================================================================
class PredictOpsPage(BasePage):
    """统一预测操作板块：KP预测 + 选品机会评分。

    交互流程：
    1. 顶部：选择品种 + 周期 + 点击"开始预测"按钮
    2. 预测执行后展示：K线图（含买卖点位标注）+ 基本面分析 + 解读
    3. 右侧面板：品种入手机会排行，辅助决策
    """

    def __init__(self, mdm, store, config=None, session=None):
        """初始化相关对象。
        
            参数:
                mdm
                store
                config
                session"""
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "predict_ops"
        dft = symbol_code(mdm.universe[0])
        if session is not None:
            self.cur_symbol, self.cur_period = session.get_page_selection(
                self.PAGE_KEY, dft, "D")
        else:
            self.cur_symbol, self.cur_period = dft, "D"
        self._predictor = None   # 延迟初始化，避免启动时加载 AI 模块
        self._results = []       # 选品评分结果
        self._cats = []          # 板块聚合结果
        self._linkage_accent = False   # 联动标签当前是否高亮（accent），供 _style_static 重绘
        self._preloaded_gene = None    # 回测中心联动预载的策略基因
        self._preloaded_symbol = None
        self._news_cache = None
        self._news_cache_ts = 0
        self._news_cache_interval = 30.0  # seconds
        # 筛选结果缓存
        self._screen_cache = None          # (results, cats)
        self._screen_cache_ts = 0
        self._screen_cache_ttl = 300.0     # 5 minutes
        # 缓存：预测器拟合结果（避免重复训练）
        self._fit_cache = None          # (fit_result, symbol, period, extended_features, use_ensemble, cache_ts)
        self._fit_cache_ttl = 10.0      # seconds
        # ---- 指标预测 / AI 辅助 控制状态 ----
        self.ind_forecast_on = True    # 是否在 MACD/KDJ/RSI 图上叠加预测曲线
        self.ind_horizon = 10          # 指标预测步数
        self._last_ind = None          # 最近一次渲染的指标 DataFrame（供 AI 研判）
        self._last_res = None          # 最近一次预测结果（供 AI 研判）
        self._ai_running = False       # AI 指标研判进行中标记
        # ---- 双向联动：订阅全局事件总线（M3.5 core.events），回测中心产出经总线广播 ----
        try:
            from ..core.events import bus as _EBUS
            _EBUS.subscribe("backtest.completed", self._on_backtest_updated)
        except Exception:  # noqa: BLE001
            pass
        self._build()
        self._screen_lazy = True   # 首次 showEvent 时延迟加载选品排行
        # M4-13④：图表高度按窗口动态分配（min(260, avail/4)）
        self._apply_chart_heights()

    # ---- M4-13④：图表高度随窗口动态分配 ----
    def resizeEvent(self, event) -> None:  # noqa: N802
        """窗口尺寸变化：重算副图最小高度（768p 下无纵向滚动条）。"""
        super().resizeEvent(event)
        self._apply_chart_heights()

    def _apply_chart_heights(self) -> None:
        """副图 minHeight = min(260, avail/4)（下限 150）；主图 = min(360, avail/3)。

        avail 取**屏幕高度**（responsive_layout 单例，与响应式三档同源），
        而非 self.height() —— 后者被子图 minHeight 硬约束钳高（布局最小值
        反向撑大页面），公式会死锁在 260，768p 下永远缩不下去（滚动条病根）。
        768p 屏：副图 192px、主图 256px，四图 + 页头/控制栏 ≤ 视口高。
        """
        try:
            from .responsive_layout import get_layout_manager
            avail = max(480, int(get_layout_manager().height))
            sub_h = min(260, max(150, avail // 4))
            self.macd.setMinimumHeight(sub_h)
            self.kdj.setMinimumHeight(sub_h)
            self.rsi.setMinimumHeight(sub_h)
            self.chart.setMinimumHeight(min(360, max(240, avail // 3)))
        except AttributeError:
            pass   # _build 未完成时不做任何事
        except Exception:  # noqa: BLE001
            pass

    # ---- 构建界面 ----
    def _build(self):
        """构建相关对象。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # 页头
        root.addWidget(PageHeader(
            "预测操作中心",
            "选品种 · 开始预测 · 看K线(含买卖点位) · 参考基本面 · 品种排行"))

        # ---- 顶部控制栏 ----
        ctl = QHBoxLayout()
        self.sym_cb = QComboBox()
        self.sym_cb.setMinimumWidth(180)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        self.sym_cb.setCurrentIndex(max(0, self.sym_cb.findData(self.cur_symbol)))
        self.sym_cb.currentIndexChanged.connect(self._on_sel)

        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(self._on_sel)

        self.hor_spin = QSpinBox()
        self.hor_spin.setRange(3, 30)
        self.hor_spin.setValue(12)

        self.start_btn = QPushButton("🚀 开始预测")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(36)
        # M4-05：移除硬编码配色，改由 QSS #primary（token 同源）统一着色，切主题自动刷新
        self.start_btn.clicked.connect(self._run_prediction)

        ctl.addWidget(QLabel("目标品种"))
        ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("周期"))
        ctl.addWidget(self.per_cb)
        ctl.addWidget(QLabel("预测步数"))
        ctl.addWidget(self.hor_spin)
        ctl.addSpacing(12)
        ctl.addWidget(self.start_btn)
        # M4-06⑤：预测长任务的「停止」按钮（协作式，在下一个检查点生效）
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("ghost")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("请求中止当前预测流程（结算/选参/校准等子步骤间生效）")
        self.stop_btn.clicked.connect(self._stop_prediction)
        ctl.addWidget(self.stop_btn)
        # 联动：用该品种已沉淀的最优回测策略反向跑回测
        self.backtest_link_btn = QPushButton("🧪 回测此策略")
        self.backtest_link_btn.setObjectName("ghost")
        self.backtest_link_btn.setMinimumHeight(36)
        self.backtest_link_btn.setEnabled(False)
        self.backtest_link_btn.setToolTip("跳转到「回测中心」并用该品种已验证的最优策略跑一次手动回测")
        self.backtest_link_btn.clicked.connect(self._goto_backtest_with_strategy)
        ctl.addWidget(self.backtest_link_btn)
        # 双向联动实时状态：显示回测中心反哺的调参画像
        self.linkage_lbl = QLabel("🔗 联动：回测库空")
        self.linkage_lbl.setObjectName("sub")
        self.linkage_lbl.setStyleSheet(f"font-size:11px;color:{pal()['sub']};")
        ctl.addWidget(self.linkage_lbl)
        ctl.addStretch(1)

        self.status_lbl = QLabel("就绪，选择品种后点击「开始预测」")
        self.status_lbl.setObjectName("sub")
        p = pal()
        self.status_lbl.setStyleSheet(f"font-size:12px;color:{p['sub']};")
        ctl.addWidget(self.status_lbl)
        root.addWidget(ToolBar(ctl))

        # ---- 结果卡片行 ----
        self.chips = {
            "exp": StatCard("预期收益", "--", theme=self._theme),
            "pup": StatCard("上涨概率", "--", theme=self._theme),
            "risk": StatCard("风险度", "--", theme=self._theme),
            "regime": StatCard("行情状态", "--", theme=self._theme),
            "model": StatCard("模型", "--", theme=self._theme),
            "conf": StatCard("校准置信度", "--", theme=self._theme),
            "news": StatCard("资讯偏置", "--", theme=self._theme),
        }
        cstrip = QHBoxLayout()
        cstrip.setSpacing(6)
        for c in self.chips.values():
            cstrip.addWidget(c, 1)
        root.addLayout(cstrip)

        # ---- 指标共振研判条 ----
        self.verdict_badge = Badge("--", pal()["accent"], "#fff")
        self.score_bar = ConfidenceBar(0.5)
        self.trend_badge = Badge("--")
        ind_row = QHBoxLayout()
        ind_row.addWidget(QLabel("指标共振:"))
        ind_row.addWidget(self.verdict_badge)
        ind_row.addSpacing(16)
        ind_row.addWidget(QLabel("多空分:"))
        ind_row.addWidget(self.score_bar, 1)
        self.score_val = QLabel("--")
        self.score_val.setObjectName("sub")
        self.score_val.setStyleSheet(f"font-size:11px;color:{p['sub']};min-width:34px;")
        ind_row.addWidget(self.score_val)
        ind_row.addSpacing(16)
        ind_row.addWidget(QLabel("趋势:"))
        ind_row.addWidget(self.trend_badge)
        ind_row.addStretch(1)
        root.addLayout(ind_row)

        # ---- 主区域：K线图 + 选品排行 ----
        main_split = QSplitter(Qt.Orientation.Horizontal)

        # ===== 左侧：K线图 + 副图 =====
        left_tab = QTabWidget()
        left_tab.setObjectName("predict-chart-tab")

        # Tab 1: K线分析
        chart_tab = QWidget()
        chart_layout = QVBoxLayout(chart_tab)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(4)

        # 指标图工具条：预测曲线开关 + 指标预测步数 + AI 指标研判
        ind_tool = QHBoxLayout()
        ind_tool.setSpacing(8)
        self.ind_fc_chk = QCheckBox("显示指标预测曲线")
        self.ind_fc_chk.setChecked(True)
        self.ind_fc_chk.setToolTip("基于历史指标自回归外推未来走势预测曲线（虚线）")
        self.ind_fc_chk.stateChanged.connect(self._on_toggle_ind_fc)
        ind_tool.addWidget(self.ind_fc_chk)
        ind_tool.addWidget(QLabel("指标预测步数"))
        self.ind_hor_spin = QSpinBox()
        self.ind_hor_spin.setRange(3, 30)
        self.ind_hor_spin.setValue(10)
        self.ind_hor_spin.setToolTip("MACD/KDJ/RSI 预测曲线外推步数")
        self.ind_hor_spin.valueChanged.connect(self._on_ind_hor_changed)
        ind_tool.addWidget(self.ind_hor_spin)
        ind_tool.addStretch(1)
        self.ai_ind_btn = QPushButton("🤖 AI 指标研判")
        self.ai_ind_btn.setObjectName("ghost")
        self.ai_ind_btn.setMinimumHeight(30)
        self.ai_ind_btn.setToolTip("调用 AI 模型，基于 MACD/KDJ/RSI 预测曲线"
                                   "辅助趋势研判与买卖信号分析")
        self.ai_ind_btn.clicked.connect(self._run_ai_indicator)
        ind_tool.addWidget(self.ai_ind_btn)
        chart_layout.addLayout(ind_tool)

        self.chart = KLineChart()
        self.chart.setMinimumHeight(320)
        chart_layout.addWidget(self.chart, 3)

        # 副图：MACD / KDJ / RSI —— 每个图表独占一行垂直堆叠，
        # 各占独立高度（min 260），大幅增加图表高度提升可读性。
        self.macd = PriceChart()
        self.macd.setMinimumHeight(260)
        self.kdj = PriceChart()
        self.kdj.setMinimumHeight(260)
        self.rsi = PriceChart()
        self.rsi.setMinimumHeight(260)
        chart_layout.addWidget(self.macd, 1)
        chart_layout.addWidget(self.kdj, 1)
        chart_layout.addWidget(self.rsi, 1)

        # M4-13②：图表间 hover 联动（双向）——任一副图 hover 时主图十字线同步，
        # 主图 hover 时副图十字回显。set_hover_fraction 不回发信号，无反馈环。
        for sub in (self.macd, self.kdj, self.rsi):
            sub.hover_fraction.connect(self.chart.set_hover_fraction)
            self.chart.hover_fraction.connect(sub.set_hover_fraction)

        # 图例说明：买卖点位标注
        self.legend = QLabel(
            "<span style='color:#22c55e;font-weight:600;'>◆</span> 建议买入　"
            "<span style='color:#ef4444;font-weight:600;'>◆</span> 建议卖出　"
            "<span style='color:#f59e0b;font-weight:600;'>◆</span> 止损位　"
            "<span style='color:#3b82f6;font-weight:600;'>━</span> 支撑/压力线　"
            "<span style='color:#ef4444;font-weight:600;'>┅</span> KP预测路径(红涨绿跌)"
        )
        self.legend.setObjectName("sub")
        self.legend.setStyleSheet(f"font-size:11px;color:{p['sub']};padding:2px 0;")
        chart_layout.addWidget(self.legend)

        left_tab.addTab(chart_tab, "📈 K线分析")

        # Tab 2: 基本面分析
        self.fundamental_text = QTextEdit()
        self.fundamental_text.setReadOnly(True)
        self.fundamental_text.setHtml(
            "<p style='color:#94a3b8'>点击「开始预测」后，这里将展示基本面分析结果，"
            "包括资金面、持仓变化、板块表现等数据。</p>")
        left_tab.addTab(self.fundamental_text, "📊 基本面分析")

        # Tab 3: 概率校准（校准可靠度图 + 预测概率带）
        calib_tab = QWidget()
        calib_layout = QVBoxLayout(calib_tab)
        calib_layout.setContentsMargins(8, 8, 8, 8)
        calib_layout.setSpacing(6)

        self.calib_intro = QLabel(
            "本页把模型的「自信度」摊开给你看：上图为<b>校准可靠度图</b>"
            "（模型说涨 X% vs 历史上真实涨了多少，落点越贴近对角线越诚实）；"
            "下图为<b>预测价格概率带</b>（中枢价 ±1σ 置信区间）。")
        self.calib_intro.setWordWrap(True)
        self.calib_intro.setObjectName("sub")
        self.calib_intro.setStyleSheet(f"font-size:12px;color:{p['sub']};padding:2px 0;")
        calib_layout.addWidget(self.calib_intro)

        # 历史回放校准工具条：把本地真实样本逐窗回放，批量灌入已结算校准样本，
        # 使「校准可靠度图」从「样本不足」快速进入有数据状态（离线、无需联网）。
        replay_bar = QHBoxLayout()
        replay_bar.setSpacing(8)
        self.replay_btn = QPushButton("📥 历史回放校准")
        self.replay_btn.setObjectName("ghost")
        self.replay_btn.setMinimumHeight(32)
        self.replay_btn.setToolTip("回放 data/real_samples 下的真实期货日线，"
                                   "把模型逐窗预测作为已结算样本写入校准库")
        self.replay_btn.clicked.connect(self._run_replay)
        # 回放步长（与实时预测口径一致）
        self.replay_hor = QSpinBox()
        self.replay_hor.setRange(5, 30)
        self.replay_hor.setValue(10)
        self.replay_hor.setToolTip("回放预测步长（horizon），与实时预测口径一致")
        # 仅当前品种开关
        self.replay_cur = QCheckBox("仅当前品种")
        self.replay_cur.setChecked(False)
        self.replay_cur.setToolTip("勾选则只回放当前选中品种，否则回放本地全部真实样本")
        self.replay_prog = QProgressBar()
        self.replay_prog.setRange(0, 100)  # M4-09：真实百分比（按样本数推进）
        self.replay_prog.setValue(0)
        self.replay_prog.setVisible(False)
        self.replay_prog.setMaximumHeight(14)
        self.replay_status = QLabel("")
        self.replay_status.setObjectName("sub")
        self.replay_status.setStyleSheet(f"font-size:11px;color:{p['sub']};")
        replay_bar.addWidget(self.replay_btn)
        # M4-06⑤：回放是批量长任务（逐品种逐窗），提供协作式停止入口
        self.replay_stop_btn = QPushButton("停止")
        self.replay_stop_btn.setObjectName("ghost")
        self.replay_stop_btn.setMinimumHeight(32)
        self.replay_stop_btn.setEnabled(False)
        self.replay_stop_btn.setToolTip("请求中止当前历史回放（在当前品种回放结束后生效）")
        self.replay_stop_btn.clicked.connect(self._stop_replay)
        replay_bar.addWidget(self.replay_stop_btn)
        replay_bar.addWidget(QLabel("步长"))
        replay_bar.addWidget(self.replay_hor)
        replay_bar.addWidget(self.replay_cur)
        replay_bar.addWidget(self.replay_prog, 1)
        replay_bar.addWidget(self.replay_status)
        calib_layout.addLayout(replay_bar)

        # M3-05 ④：Walk-Forward 滚动验证入口。
        # 上面的「历史回放校准」只灌校准样本；这里直接给出**因果滚动**的样本外
        # 性能指标（逐折只用历史段训练再预测未来段），用来判断模型是否真有技能。
        wf_bar = QHBoxLayout()
        wf_bar.setSpacing(8)
        self.wf_btn = QPushButton("🔁 Walk-Forward 验证")
        self.wf_btn.setObjectName("ghost")
        self.wf_btn.setMinimumHeight(32)
        self.wf_btn.setToolTip("对当前品种做因果滚动验证：逐折只用历史段训练、再预测未来段，"
                               "输出折数 / 样本外方向准确率 / MAE（成本约为单次评估的折数倍）")
        self.wf_btn.clicked.connect(self._run_walk_forward)
        self.wf_prog = QProgressBar()
        self.wf_prog.setRange(0, 0)          # 未知总量 → 忙碌指示
        self.wf_prog.setVisible(False)
        self.wf_prog.setMaximumHeight(14)
        wf_bar.addWidget(self.wf_btn)
        wf_bar.addWidget(self.wf_prog, 1)
        calib_layout.addLayout(wf_bar)

        self.wf_status = QLabel("")
        self.wf_status.setWordWrap(True)
        self.wf_status.setObjectName("sub")
        self.wf_status.setStyleSheet(f"font-size:11px;color:{p['sub']};padding:2px 0;")
        calib_layout.addWidget(self.wf_status)

        # 校准状态速览卡片：样本数 / 平均偏差 / 评级 / 校准区间±（不确定性）
        self.calib_stats = {
            "n": StatCard("校准样本", "--", theme=self._theme),
            "err": StatCard("平均偏差", "--", theme=self._theme),
            "grade": StatCard("校准评级", "--", theme=self._theme),
            "band": StatCard("校准区间±", "--", theme=self._theme),
        }
        calib_stat_strip = QHBoxLayout()
        calib_stat_strip.setSpacing(6)
        for c in self.calib_stats.values():
            calib_stat_strip.addWidget(c, 1)
        calib_layout.addLayout(calib_stat_strip)

        self.calib_hint = QLabel(
            "提示：点击上方「📥 历史回放校准」灌入本地真实样本，"
            "即可看到样本外校准曲线与评级。")
        self.calib_hint.setWordWrap(True)
        self.calib_hint.setObjectName("sub")
        self.calib_hint.setStyleSheet(f"font-size:11px;color:{p['sub']};padding:2px 0;")
        calib_layout.addWidget(self.calib_hint)

        self.reliability_chart = ReliabilityChart()
        self.reliability_chart.setMinimumHeight(240)
        calib_layout.addWidget(self.reliability_chart, 1)

        self.prob_band = PriceChart()
        self.prob_band.setMinimumHeight(240)
        calib_layout.addWidget(self.prob_band, 1)

        left_tab.addTab(calib_tab, "🎯 概率校准")

        # ===== M3-10：模型状态面板（Model Card）=====
        # 让用户明确知道「当前到底在跑哪个模型、是否降级、是不是占位实现」。
        mc_tab = QWidget()
        mc_layout = QVBoxLayout(mc_tab)
        mc_layout.setContentsMargins(8, 8, 8, 8)
        mc_layout.setSpacing(6)

        self.mc_intro = QLabel(
            "这里列出全部候选模型与其<b>真实状态</b>："
            "<b>占位实现</b>指接口齐全但并非端到端训练（或依赖缺失时恒值输出）的模型，"
            "标灰显示且注明局限 —— 不要把它的输出当完整模型用。")
        self.mc_intro.setWordWrap(True)
        self.mc_intro.setObjectName("sub")
        self.mc_intro.setStyleSheet(f"font-size:12px;color:{p['sub']};padding:2px 0;")
        mc_layout.addWidget(self.mc_intro)

        # ===== M3-13 ③：模型漂移指示灯 =====
        # 一眼看出「当前品种的模型是不是已经跑偏了」：
        #   绿 ok / 红 drift（超阈值，建议重训）/ 灰 no_data（样本不足）
        drift_row = QHBoxLayout()
        drift_row.setSpacing(6)
        self.drift_light = QLabel("●")
        self.drift_light.setFixedWidth(14)
        self.drift_light.setObjectName("drift_light")
        self.drift_light.setToolTip("模型漂移指示灯：绿=正常，红=命中率相对训练期显著漂移（建议重训），"
                                    "灰=已结算样本不足，暂不判定")
        self.drift_text = QLabel("模型漂移：未检测")
        self.drift_text.setObjectName("sub")
        self.drift_text.setWordWrap(True)
        self.drift_btn = QPushButton("📉 检测漂移")
        self.drift_btn.setObjectName("ghost")
        self.drift_btn.setMinimumHeight(28)
        self.drift_btn.setToolTip("对当前品种跑一次漂移检测：比较近 60 天的方向命中率"
                                  "与训练期基准，超过阈值即提示重训")
        self.drift_btn.clicked.connect(self._refresh_drift_light)
        drift_row.addWidget(self.drift_light)
        drift_row.addWidget(self.drift_text, 1)
        drift_row.addWidget(self.drift_btn)
        mc_layout.addLayout(drift_row)

        mc_bar = QHBoxLayout()
        mc_bar.setSpacing(8)
        self.mc_refresh_btn = QPushButton("🔄 刷新模型状态")
        self.mc_refresh_btn.setObjectName("ghost")
        self.mc_refresh_btn.setMinimumHeight(32)
        self.mc_refresh_btn.setToolTip("重新探测 torch / sklearn / arch 等可选依赖，"
                                       "并读取当前预测器的训练状态")
        self.mc_refresh_btn.clicked.connect(self._refresh_model_cards)
        self.mc_summary = QLabel("")
        self.mc_summary.setObjectName("sub")
        self.mc_summary.setStyleSheet(f"font-size:11px;color:{p['sub']};")
        mc_bar.addWidget(self.mc_refresh_btn)
        mc_bar.addWidget(self.mc_summary, 1)
        mc_layout.addLayout(mc_bar)

        from ..ai.model_card import COLUMNS as _MC_COLUMNS  # 延迟导入避免启动阻塞

        # M4-08：模型状态表改用 DataGrid（排序 / 右键复制·导出 / 列显隐 / 空态 / 主题刷新）
        self.mc_tbl = DataGrid(0, len(_MC_COLUMNS),
                               empty_title="暂无模型卡片",
                               empty_subtitle="点击「刷新」探测本机可用模型")
        self.mc_tbl.setHorizontalHeaderLabels(list(_MC_COLUMNS))
        self.mc_tbl.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.mc_tbl.horizontalHeader().setStretchLastSection(True)
        mc_layout.addWidget(self.mc_tbl, 1)
        self._mc_tab_index = left_tab.addTab(mc_tab, "🧩 模型状态")
        # 惰性刷新：首次切到该页时才探测依赖，避免启动期白跑一次 importlib
        left_tab.currentChanged.connect(self._on_left_tab_changed)

        main_split.addWidget(left_tab)

        # ===== 右侧：选品排行 + 预测解读 =====
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # 做多/做空性价比（附数值标签，便于直接读数）
        self.long_bar = ConfidenceBar(0.5)
        self.short_bar = ConfidenceBar(0.5)
        self.long_val = QLabel("--")
        self.long_val.setObjectName("sub")
        self.long_val.setStyleSheet(f"font-size:11px;color:{p['sub']};min-width:34px;")
        self.short_val = QLabel("--")
        self.short_val.setObjectName("sub")
        self.short_val.setStyleSheet(f"font-size:11px;color:{p['sub']};min-width:34px;")
        rl = QHBoxLayout()
        rl.addWidget(QLabel("做多性价比"))
        rl.addWidget(self.long_bar, 1)
        rl.addWidget(self.long_val)
        rs = QHBoxLayout()
        rs.addWidget(QLabel("做空性价比"))
        rs.addWidget(self.short_bar, 1)
        rs.addWidget(self.short_val)
        right_layout.addLayout(rl)
        right_layout.addLayout(rs)
        self.rec_badge = Badge("--")
        rh = QHBoxLayout()
        rh.addWidget(QLabel("综合建议:"))
        rh.addWidget(self.rec_badge)
        rh.addStretch(1)
        right_layout.addLayout(rh)

        # 选品排行（带伸缩比例，随窗口调整）
        right_layout.addWidget(SectionHeader("品种入手机会排行", accent="#3b82f6"))
        # 移除「板块」列：品种字段完整展示（ResizeToContents），其余字段平均分配列宽
        # M4-08：选品排行改用 DataGrid；末列含「分析」按钮单元格控件 → 排序关闭
        # （原 setSortingEnabled(True) 的 Qt 自动排序会打乱 setCellWidget，一并移除）
        self.screen_tbl = DataGrid(0, 5, sortable=False,
                                   empty_title="暂无选品结果",
                                   empty_subtitle="点击「开始预测」生成排行")
        self.screen_tbl.setHorizontalHeaderLabels(
            ["品种", "评分", "20日%", "AI方向", "操作"])
        _hdr = self.screen_tbl.horizontalHeader()
        # 品种列：按内容自适应，保证名称+代码完整可见
        _hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        # 其余字段（评分/20日%/AI方向/操作）平均分配剩余宽度，布局均衡
        for _c in range(1, 5):
            _hdr.setSectionResizeMode(_c, QHeaderView.ResizeMode.Stretch)
        self.screen_tbl.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.screen_tbl.itemSelectionChanged.connect(self._on_screen_select)
        # 选品排行（带伸缩比例，不再硬性限制最大高度）
        right_layout.addWidget(self.screen_tbl, 2)  # stretch=2，随窗口伸缩

        # 评分档位图例
        self.legend2 = QLabel(
            "<span style='color:#ef4444;font-weight:600;'>■</span> 优先入手(≥68)　"
            "<span style='color:#3b82f6;font-weight:600;'>■</span> 可留意(≥55)　"
            "<span style='color:#64748b;font-weight:600;'>■</span> 暂观望"
        )
        self.legend2.setObjectName("sub")
        self.legend2.setStyleSheet(f"font-size:11px;color:{p['sub']};")
        right_layout.addWidget(self.legend2, 1)  # stretch=1

        # 板块机会地图
        right_layout.addWidget(SectionHeader("板块机会", accent="#22c55e"))
        self.heat_lbl = QLabel("—")
        self.heat_lbl.setWordWrap(True)
        # 去掉 setMaximumHeight，改用 stretch 控制高度比例
        right_layout.addWidget(self.heat_lbl, 1)  # stretch=1

        # 预测解读
        right_layout.addWidget(SectionHeader("预测解读", accent="#a855f7"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setHtml(
            "<p style='color:#94a3b8'>点击「开始预测」后，这里将给出专业、详细的白话版解读："
            "能不能入手、什么时候入手、为什么不能入手，以及技术面 / 模型面 / "
            "资讯面 / 基本面 / 历史表现 的全面分析与操作建议。</p>")
        right_layout.addWidget(self.detail, 2)  # stretch=2，底部预留更多阅读空间

        main_split.addWidget(right_panel)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 2)
        root.addWidget(main_split, 1)

        # 初始加载K线图（主线程，轻量）
        self._base_refresh()
        # M4-05：构建期主题色 inline 样式集中重绘（保证切主题后被覆盖刷新）
        self._style_static()

    # ------------------------------------------------------------------
    # M4-05：构建期主题色 inline 样式集中管理（消除「inline setStyleSheet 不随
    # 全局 QSS 刷新」缺陷）。本方法在 _build 末尾与 set_theme 中重跑。
    # ------------------------------------------------------------------
    def _style_static(self) -> None:
        """重绘所有构建期主题色 inline 样式。"""
        p = pal()
        self.linkage_lbl.setStyleSheet(
            f"font-size:11px;color:{p['accent'] if self._linkage_accent else p['sub']};")
        self.status_lbl.setStyleSheet(f"font-size:12px;color:{p['sub']};")
        self.score_val.setStyleSheet(f"font-size:11px;color:{p['sub']};min-width:34px;")
        self.legend.setStyleSheet(f"font-size:11px;color:{p['sub']};padding:2px 0;")
        self.calib_intro.setStyleSheet(f"font-size:12px;color:{p['sub']};padding:2px 0;")
        self.replay_status.setStyleSheet(f"font-size:11px;color:{p['sub']};")
        self.wf_status.setStyleSheet(f"font-size:11px;color:{p['sub']};padding:2px 0;")
        self.calib_hint.setStyleSheet(f"font-size:11px;color:{p['sub']};padding:2px 0;")
        self.mc_intro.setStyleSheet(f"font-size:12px;color:{p['sub']};padding:2px 0;")
        self.mc_summary.setStyleSheet(f"font-size:11px;color:{p['sub']};")
        self.long_val.setStyleSheet(f"font-size:11px;color:{p['sub']};min-width:34px;")
        self.short_val.setStyleSheet(f"font-size:11px;color:{p['sub']};min-width:34px;")
        self.legend2.setStyleSheet(f"font-size:11px;color:{p['sub']};")

    # ---- 懒加载：首次可见时启动选品排行后台任务 ----
    def showEvent(self, event):
        """显示事件。
        
            参数:
                event"""
        super().showEvent(event)
        # 页面可见时刷新回测中心反哺的实时联动状态
        try:
            self._refresh_linkage_label()
        except Exception:  # noqa: BLE001
            pass
        if getattr(self, "_screen_lazy", False):
            self._screen_lazy = False
            QTimer.singleShot(100, self._run_screen)

    # ---- 事件处理 ----
    def _on_sel(self, *_):
        """处理onsel。
        
            参数:
                *_: 可变位置参数"""
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        # 联动按钮：当前品种有回测沉淀时才可点
        try:
            has_bt = bool(backtest_linkage_for(self.cur_symbol).get("has_backtest"))
        except Exception:  # noqa: BLE001
            has_bt = False
        if hasattr(self, "backtest_link_btn"):
            self.backtest_link_btn.setEnabled(has_bt)
        self._base_refresh()

    def _goto_backtest_with_strategy(self) -> None:
        """联动跳转：携带当前品种的最优回测策略基因，反向驱动「回测中心」手动回测。"""
        sym = self.cur_symbol
        if not sym:
            return
        gene = None
        try:
            gene = backtest_linkage_for(sym).get("best_gene")
        except Exception:  # noqa: BLE001
            gene = None
        mw = self.window()
        if mw is None or not hasattr(mw, "_goto_page"):
            return
        mw._goto_page("backtest")
        pg = mw.stack.currentWidget() if hasattr(mw, "stack") else None
        if pg is not None and hasattr(pg, "run_manual_for"):
            try:
                pg.run_manual_for(sym, gene)
            except Exception:  # noqa: BLE001
                pass

    def set_symbol(self, symbol: str, period: str = "D", gene=None) -> None:
        """供「回测中心」联动跳转：定位到指定品种/周期并刷新基础图。

        gene: 若由回测中心某条盈利策略带入，则预载该策略基因，
              使本次预测融合该策略方向（双向联动的「基因透传」）。
        """
        idx = self.sym_cb.findData(symbol)
        if idx >= 0:
            self.sym_cb.setCurrentIndex(idx)
        pidx = self.per_cb.findData(period)
        if pidx >= 0:
            self.per_cb.setCurrentIndex(pidx)
        # 记录预载基因（供 _run_prediction 融合）
        self._preloaded_gene = dict(gene) if gene else None
        self._preloaded_symbol = symbol if gene else None
        self._on_sel()
        if gene:
            try:
                desc = describe_gene(gene)
            except Exception:  # noqa: BLE001
                desc = str(gene)
            self.status_lbl.setText(
                f"🧬 已载入回测策略基因：{desc} — 点击「开始预测」将其方向融合进研判")
        else:
            self.status_lbl.setText(
                f"已选中品种：{symbol}，点击「开始预测」进行分析")

    def _base_refresh(self):
        """加载基础K线图（无预测数据）。"""
        df = self.mdm.get_bars(self.cur_symbol, self.cur_period, 600)
        if df.empty:
            return
        ind = cached_add_indicators(self.cur_symbol, self.cur_period, df)
        bars = df_to_bars(df)
        self.chart.set_data(bars, ma={"MA10": ind["MA10"].tolist(),
                                      "MA20": ind["MA20"].tolist()})
        self.chart.set_watermark(f"{self.cur_symbol} · {self.cur_period}")
        self.chart.set_forecast(None)
        self.chart.set_levels([])
        self.chart.set_trade_marks([])
        # 副图指标 + 未来走势预测曲线
        self._render_indicators(ind)

    # ---- 指标预测曲线 + AI 辅助研判 ----
    _AI_INDICATOR_SYSTEM = (
        "你是资深期货量化分析师，擅长基于 MACD / KDJ / RSI 等技术指标"
        "与模型研判给出简洁、可执行的中文趋势研判。只基于给定数据客观分析，"
        "不编造未提供的信息，明确提示风险。")

    def _render_indicators(self, ind) -> None:
        """渲染 MACD / KDJ / RSI 副图，并叠加基于历史数据的未来走势预测曲线。

        - 每个指标取「主序列」（DIF / K / RSI6）做自回归外推预测（虚线 + 置信带）；
        - 次序列（DEA / D / J / RSI14）保留历史对照；
        - 预测曲线随「显示指标预测曲线」开关与「指标预测步数」实时刷新。
        """
        self._last_ind = ind
        if ind is None or len(ind) == 0:
            return
        H = self.ind_horizon
        show = self.ind_forecast_on

        # MACD：主序列 DIF（预测），对照 DEA
        dif = self._safe_list(ind, "DIF")
        dea = self._safe_list(ind, "DEA")
        macd_series, macd_band = self._build_ind_chart(
            "DIF", "#3b82f6", dif,
            [{"name": "DEA", "color": "#f59e0b", "hist": dea}],
            H, show)
        self.macd.set_data(series=macd_series, bands=macd_band, title="MACD")

        # KDJ：主序列 K（预测），对照 D / J
        k = self._safe_list(ind, "K")
        d = self._safe_list(ind, "D")
        j = self._safe_list(ind, "J")
        kdj_series, kdj_band = self._build_ind_chart(
            "K", "#3b82f6", k,
            [{"name": "D", "color": "#22c55e", "hist": d},
             {"name": "J", "color": "#ef4444", "hist": j}],
            H, show)
        self.kdj.set_data(series=kdj_series, bands=kdj_band, title="KDJ")

        # RSI：主序列 RSI6（预测，含 0~100 边界回归），对照 RSI14
        r6 = self._safe_list(ind, "RSI6")
        r14 = self._safe_list(ind, "RSI14")
        rsi_series, rsi_band = self._build_ind_chart(
            "RSI6", "#a855f7", r6,
            [{"name": "RSI14", "color": "#06b6d4", "hist": r14}],
            H, show, bounds=(0.0, 100.0))
        self.rsi.set_data(series=rsi_series, bands=rsi_band, title="RSI")

    @staticmethod
    def _safe_list(ind, col) -> list:
        """从指标 DataFrame 取列并过滤非有限值（NaN/±inf → 丢弃）。"""
        try:
            s = ind[col]
        except KeyError:
            return []
        out = []
        for v in s.tolist():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv):
                out.append(fv)
        return out

    def _build_ind_chart(self, pname, pcolor, phist, extras, H, show,
                         bounds=None):
        """构造单个指标图的 series / bands。

        PriceChart 按数组下标定位（忽略 series 的 x 字段），因此预测曲线通过
        **历史段以 None 占位** 实现对齐：仅前景段（末点 + 外推）为有限值，
        落在绘图区右侧，与历史线末端自然衔接。置信带全程有限（历史段零宽、
        前景段真实带），与下标一致，避免错位。
        """
        N = len(phist)
        series = [{"name": pname, "color": pcolor, "y": phist}]
        bands = []
        if show and N >= 5:
            fc, lo, hi = self._indicator_forecast(phist, H,
                                                  bounds[0] if bounds else None,
                                                  bounds[1] if bounds else None)
            if fc is not None:
                # 前景段：历史段 None 占位跳过，仅末点 + 外推为有限值（落右侧）
                fc_y = [None] * (N - 1) + [phist[-1]] + list(fc)
                series.append({"name": pname + "预测", "color": pcolor,
                               "y": fc_y, "dashed": True})
                # 全程有限置信带：历史段零宽，前景段真实带
                full_lo = phist[:-1] + [phist[-1]] + list(lo)
                full_hi = phist[:-1] + [phist[-1]] + list(hi)
                bands.append({"lower": full_lo, "upper": full_hi,
                               "color": pcolor, "alpha": 28})
        for ex in extras:
            eh = ex.get("hist") or []
            series.append({"name": ex["name"], "color": ex["color"], "y": eh})
        return series, bands

    def _indicator_forecast(self, y, horizon, lo=None, hi=None):
        """基于历史指标序列自回归外推未来走势（含 ±1σ 置信带）。

        方法：对尾部窗口做最小二乘趋势线，外推时趋势随时间指数衰减（避免盲目延展），
        有界指标（如 RSI/KDJ 0~100）叠加向中值回归项并夹紧边界；
        置信带宽度随步数 √i 扩张，体现不确定性累积。
        """
        ys = [float(v) for v in y if math.isfinite(v)]
        if len(ys) < 5:
            return None, None, None
        arr = np.array(ys[-40:], dtype=float)
        n = len(arr)
        t = np.arange(n, dtype=float)
        slope = 0.0
        if n >= 3:
            A = np.vstack([t, np.ones(n)]).T
            try:
                coef, *_ = np.linalg.lstsq(A, arr, rcond=None)
                slope = float(coef[0])
            except Exception:  # noqa: BLE001
                slope = 0.0
        last = float(arr[-1])
        diffs = np.diff(arr)
        resid_std = float(np.std(diffs)) if len(diffs) else (abs(slope) + 1e-6)
        resid_std = max(resid_std, 1e-6)
        fc, lower, upper = [], [], []
        for i in range(1, horizon + 1):
            damp = math.exp(-0.06 * i)
            v = last + slope * damp * i
            if lo is not None and hi is not None:
                mid = 0.5 * (lo + hi)
                v = v + (mid - v) * (1.0 - math.exp(-0.04 * i))
                v = max(lo, min(hi, v))
            fc.append(float(v))
            b = float(resid_std * math.sqrt(i))
            lower.append(float(v) - b)
            upper.append(float(v) + b)
        return fc, lower, upper

    def _on_toggle_ind_fc(self, state) -> None:
        """切换「显示指标预测曲线」开关，重渲染当前指标图。"""
        self.ind_forecast_on = bool(state)
        if getattr(self, "_last_ind", None) is not None:
            self._render_indicators(self._last_ind)

    def _on_ind_hor_changed(self, val) -> None:
        """调整指标预测步数，重渲染当前指标图。"""
        self.ind_horizon = int(val)
        if getattr(self, "_last_ind", None) is not None:
            self._render_indicators(self._last_ind)

    # ---- 双向联动：回测中心 → 预测 ----
    def _on_backtest_updated(self, payload: dict) -> None:
        """回测中心实时推送盈利策略时，刷新本页联动状态（画像已在总线内重建）。"""
        try:
            self._refresh_linkage_label()
        except Exception:  # noqa: BLE001
            pass

    def _refresh_linkage_label(self) -> None:
        """刷新控制栏的联动状态标签：展示回测库反哺的调参画像（命中率 + 权重）。"""
        try:
            from ..ai.linkage_bus import BUS as _BUS
            t = _BUS.get_tuning(self.cur_symbol)
            g = (t.get("global") or {})
            n = int(g.get("n", 0) or 0)
            if n == 0:
                self.linkage_lbl.setText("🔗 联动：回测库空（预测未反哺）")
                self._linkage_accent = False
                self.linkage_lbl.setStyleSheet(
                    f"font-size:11px;color:{pal()['sub']};")
                return
            cons = float(g.get("consensus", 0.0) or 0.0)
            base = float(g.get("strat_weight_base", 0.30) or 0.30)
            sym = t.get("symbol")
            extra = (f" · 本品种权重 {sym.get('weight', base):.2f}"
                     if sym else "")
            hit_rate = float(g.get("hit_rate", 0.5) or 0.5)
            hit_txt = f" · 命中率 {hit_rate*100:.0f}%" if n >= 2 else ""
            self.linkage_lbl.setText(
                f"🔗 联动：回测库 {n} 条 · 方向一致 {cons*100:.0f}% · "
                f"权重 {base:.2f}{extra}{hit_txt}")
            self._linkage_accent = True
            self.linkage_lbl.setStyleSheet(
                f"font-size:11px;color:{pal()['accent']};")
        except Exception:  # noqa: BLE001
            pass

    # ---- AI 指标研判 ----
    def _run_ai_indicator(self) -> None:
        """调用 AI 模型，基于 MACD/KDJ/RSI 现状与预测曲线辅助趋势研判与信号分析。"""
        if getattr(self, "_ai_running", False):
            return
        self._ai_running = True
        self.ai_ind_btn.setEnabled(False)
        self.ai_ind_btn.setText("🤖 AI 研判中…")
        sym = self.cur_symbol
        ind = getattr(self, "_last_ind", None)
        res = getattr(self, "_last_res", None)

        def work():
            """构造指标研判提示词并调用 AI 模型。"""
            try:
                # 1. 确保最新配置（含 API 密钥）已应用到 LLM 客户端
                from ..ai.config import get_ai_config
                ai_cfg = get_ai_config(self.config)
                ai_cfg.apply()
                
                # 2. 诊断：检查 API 密钥是否真正已加载到客户端
                from ..ai.llm_client import get_client, api_status
                client = get_client()
                status = api_status()
                
                # 调试日志：打印关键状态
                print(f"[AI指标研判] 配置状态: configured={status.get('configured')}, "
                      f"usable={status.get('usable')}, client.api_key={'已设置' if client.api_key else '未设置'}")
                
                if not status.get("usable"):
                    # 给出更具体的错误提示
                    if not status.get("configured"):
                        return "⚠️ AI 模型不可用：未检测到 API 密钥。\n" \
                               "请在顶部「AI」菜单 →「模型配置」中填入 Agnes AI API 密钥并点击「应用」，" \
                               "或设置环境变量 QV_AGNES_API_KEY。"
                    elif not status.get("requests_available"):
                        return "⚠️ AI 模型不可用：缺少 requests 库。\n" \
                               "请运行 `pip install requests` 安装依赖。"
                    else:
                        return "⚠️ AI 模型不可用：已配置密钥但连接失败。\n" \
                               "请检查网络连通性，或在「AI」菜单 →「模型配置」中点击「测试连接」验证。"
                
                # 3. 调用 AI
                from ..ai.llm_client import chat
                prompt = self._build_indicator_ai_prompt(sym, ind, res)
                result = chat(self._AI_INDICATOR_SYSTEM, prompt)
                
                if result is None:
                    return "⚠️ AI 调用返回空结果（可能网络超时或 API 限流）。\n" \
                           "请稍后重试，或在「AI」菜单中检查 API 状态。"
                return result
                
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                return f"AI 调用异常：{type(e).__name__}: {e}"

        def done(text):
            """处理done。
            
            参数:
                text"""
            self._ai_running = False
            self.ai_ind_btn.setEnabled(True)
            self.ai_ind_btn.setText("🤖 AI 指标研判")
            self._show_ai_indicator_dialog(text)

        def err(e):
            """处理err。
            
            参数:
                e"""
            self._ai_running = False
            self.ai_ind_btn.setEnabled(True)
            self.ai_ind_btn.setText("🤖 AI 指标研判")
            self._show_ai_indicator_dialog(f"AI 调用出错：{e}")

        self._run_worker(work, done, on_err=err)

    def _build_indicator_ai_prompt(self, sym, ind, res) -> str:
        """构造发给 AI 的指标研判提示词（现状 + 预测曲线结论 + 主模型研判）。"""
        parts = [f"请基于以下期货品种 {sym} 的技术指标现状与未来走势预测，"
                 f"给出趋势研判、买卖信号（做多/做空/观望）与关键风险提示。"]
        if ind is not None and len(ind):
            try:
                def _last(col):
                    s = ind[col].dropna()
                    return float(s.iloc[-1]) if len(s) else None

                dif, dea = _last("DIF"), _last("DEA")
                kk, dd, jj = _last("K"), _last("D"), _last("J")
                r6, r14 = _last("RSI6"), _last("RSI14")
                H = self.ind_horizon
                if None not in (dif, dea):
                    parts.append(
                        f"MACD：DIF={dif:.3f}，DEA={dea:.3f}，柱={dif - dea:.3f}"
                        f"（{'多头' if dif > dea else '空头'}），"
                        f"未来 {H} 步 DIF 已外推预测曲线。")
                if None not in (kk, dd, jj):
                    parts.append(
                        f"KDJ：K={kk:.1f}，D={dd:.1f}，J={jj:.1f}"
                        f"（{'超买' if kk > 80 else '超卖' if kk < 20 else '中性'}）。")
                if None not in (r6, r14):
                    parts.append(
                        f"RSI：RSI6={r6:.1f}，RSI14={r14:.1f}"
                        f"（{'超买' if r14 > 70 else '超卖' if r14 < 30 else '中性'}）。")
            except Exception:  # noqa: BLE001
                pass
        if res is not None:
            try:
                parts.append(
                    f"主模型研判：上涨概率 {float(res.get('p_up', 0.5)) * 100:.0f}%，"
                    f"预期收益 {float(res.get('expected_return_pct', 0)):+.2f}%，"
                    f"行情状态 {res.get('regime', '')}，"
                    f"风险 {res.get('risk', {}).get('label', '')}。")
                fc = res.get("forecast") or []
                if len(fc) > 1:
                    parts.append(f"主图 KP 预测目标 {float(fc[-1]):,.2f}。")
            except Exception:  # noqa: BLE001
                pass
        parts.append("请以「结论：做多/做空/观望；理由：…；风险：…」三段式作答，"
                     "中文，不超过 200 字。")
        return "\n".join(parts)

    def _show_ai_indicator_dialog(self, text: str) -> None:
        """弹出 AI 指标研判结果对话框。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("🤖 AI 指标趋势研判")
        dlg.setMinimumSize(480, 340)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(QLabel(f"品种：{self.cur_symbol} · 指标：MACD / KDJ / RSI"))
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(text)
        v.addWidget(te, 1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(close_btn)
        v.addLayout(h)
        dlg.exec()

    # ---- 选品评分 ----
    def _run_screen(self):
        """后台运行选品评分。失败时在状态栏提示，便于排查而非静默空白。"""
        now = time.time()
        if self._screen_cache is not None and (now - self._screen_cache_ts) < self._screen_cache_ttl:
            # 使用缓存结果
            self._results, self._cats = self._screen_cache
            self._refresh_screen_table()
            return
        def work():
            """处理work。"""
            return _screen(self.mdm, self.store)

        def done(payload):
            """处理done。
            
            参数:
                payload"""
            self._results, self._cats = payload
            self._screen_cache = payload
            self._screen_cache_ts = now
            self._refresh_screen_table()

        def err(e):
            """处理err。
            
            参数:
                e"""
            self.status_lbl.setText(f"选品评分加载失败: {e}")

        self._run_worker(work, done, on_err=err)

    def _refresh_screen_table(self):
        """刷新选品排行表格。"""
        tbl = self.screen_tbl
        tbl.setRowCount(0)
        for r in self._results[:20]:
            row = tbl.rowCount()
            tbl.insertRow(row)
            # 品种（完整展示名称 + 代码）
            sym_item = QTableWidgetItem(f"{r['name']} {r['sym']}")
            tbl.setItem(row, 0, sym_item)
            # 评分
            score_item = QTableWidgetItem(f"{r['score']:.1f}")
            if r["score"] >= 68:
                score_item.setForeground(QColor("#22c55e"))
            elif r["score"] >= 55:
                score_item.setForeground(QColor("#3b82f6"))
            else:
                score_item.setForeground(QColor("#64748b"))
            tbl.setItem(row, 1, score_item)
            # 20日%（C5 中国惯例：涨=红、跌=绿；原代码反向，已纠正）
            _p = pal()
            ret_item = QTableWidgetItem(f"{r['ret']:+.1f}%")
            ret_item.setForeground(QColor(_p["up"] if r["ret"] >= 0
                                          else _p["down"]))
            tbl.setItem(row, 2, ret_item)
            # AI方向（多=红、空=绿；中性用琥珀提示色）
            pu = r.get("pu", 0.5)
            ai_dir = "偏多" if pu >= 0.55 else ("偏空" if pu <= 0.45 else "中性")
            ai_col = _p["up"] if pu >= 0.55 else (
                _p["down"] if pu <= 0.45 else "#f59e0b")
            ai_item = QTableWidgetItem(ai_dir)
            ai_item.setForeground(QColor(ai_col))
            tbl.setItem(row, 3, ai_item)
            # 操作按钮
            btn = QPushButton("分析")
            btn.setObjectName("secondary")
            # M4-05⑤：移除硬编码浅色配色，改由 QSS #secondary（token 同源）统一着色
            sym = r["sym"]
            btn.clicked.connect(lambda checked, s=sym: self._select_and_predict(s))
            tbl.setCellWidget(row, 4, btn)

        # 板块机会热力图（可视化条形图）
        if not self._cats:
            self.heat_lbl.setText("—")
            return
        
        # 构建HTML条形图：每个板块一行，颜色根据得分区间，长度代表平均分
        html_parts = []
        for c in self._cats[:8]:
            cat_name = c["cat"]
            avg = c["avg"]
            # 确定颜色：≥68红，55-67蓝，<58灰
            if avg >= 68:
                bar_color = "#ef4444"   # 优先入手
            elif avg >= 55:
                bar_color = "#3b82f6"   # 可留意
            else:
                bar_color = "#64748b"   # 暂观望
            
            # 计算进度条宽度百分比（max 100）
            width_pct = min(100, max(0, avg))
            
            html_parts.append(
                f'<div style="margin:4px 0;font-size:12px;">'
                f'<span style="color:#fff;font-weight:500;min-width:60px;display:inline-block;">{cat_name}</span>'
                f'<div style="background:#e2e8f0;border-radius:4px;height:14px;overflow:hidden;margin:0 8px;">'
                f'<div style="background:{bar_color};height:100%;width:{width_pct}%;transition:width 0.3s;"></div>'
                f'</div>'
                f'<span style="color:#64748b;font-size:11px;">{avg:.0f}分</span>'
                f'</div>')
        
        self.heat_lbl.setText("<p style='margin:4px 0;font-size:11px;color:#64748b;'>各板块入手机会评分：</p>" + "".join(html_parts))

    def _on_screen_select(self):
        """选中排行品种时，自动在品种选择器中定位。"""
        rows = self.screen_tbl.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if row < len(self._results):
                sym = self._results[row]["sym"]
                idx = self.sym_cb.findData(sym)
                if idx >= 0:
                    self.sym_cb.setCurrentIndex(idx)
                    self.status_lbl.setText(f"已选中品种：{sym}，点击「开始预测」进行分析")

    def _select_and_predict(self, symbol: str):
        """从排行表格选中品种并自动开始预测。"""
        idx = self.sym_cb.findData(symbol)
        if idx >= 0:
            self.sym_cb.setCurrentIndex(idx)
            self.cur_symbol = symbol
            self._run_prediction()

    # ---- 校准置信带 → 实时研判降级信号 ----
    @staticmethod
    def _calib_conf_flag(calib_info, p_up: float):
        """判定本次预测落点的校准区间是否过宽（不可信）。

        返回 (low_conf, lo, hi, width)：
          low_conf=True 当且仅当：
            ① 落点处 Wilson 区间宽 > 阈值；
            ② 或该分箱历史样本 < 50（样本稀疏 → 区间天然宽）。
        """
        bins = []
        if isinstance(calib_info, dict):
            bins = calib_info.get("bins") or []
        lo, hi = calibration_band_at(bins, float(p_up))
        if lo is None or hi is None:
            return (False, lo, hi, None)
        width = float(hi) - float(lo)
        # 用最近中心值匹配该落点所在分箱（避免 Wilson 区间边界截断导致误匹配）
        n_at_bin = min(bins, key=lambda b: abs(b[0] - float(p_up)))[2] if bins else None
        if n_at_bin is not None and n_at_bin < 50:
            return (True, lo, hi, width)
        return (width > LOW_CONF_BAND_WIDTH, lo, hi, width)

    def _render_verdict_badge(self, reso: dict, low_conf: bool) -> None:
        """渲染指标共振研判徽章；low_conf=True 时追加「⚠低置信」降级标记并转琥珀色。"""
        verdict = reso.get("verdict", "信号不明")
        score = float(reso.get("score", 0) or 0)
        if low_conf:
            self.verdict_badge.setText(f"{verdict}·⚠低置信")
            self.verdict_badge.set_color("#f59e0b", "#1a1d27")
        else:
            self.verdict_badge.setText(verdict)
            vcol = (pal()["up"] if score > 20 else
                    pal()["down"] if score < -20 else pal()["sub"])
            self.verdict_badge.set_color(vcol, "#fff")

    # ---- KP预测 ----
    def _run_prediction(self):
        """执行完整预测流程。"""
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        horizon = self.hor_spin.value()
        self.start_btn.setEnabled(False)
        self.start_btn.setText("预测中…")
        self.stop_btn.setEnabled(True)
        self.status_lbl.setText("正在执行预测流程：结算历史 → 获取资讯 → 自适应选参 → KP预测 → 校准…")
        sym, per = self.cur_symbol, self.cur_period

        store, mdm = self.store, self.mdm
        name = category = ""
        for r in mdm.universe:
            if symbol_code(r) == sym:
                name, category = r[1], r[2]
                break

        def work(worker):
            # ① 学习结算
            """处理work（M5-07③：注入 worker —— 资讯抓取支持协作式取消）。"""
            # 延迟导入：仅在实际预测时才加载 AI 模块，避免启动阻塞
            from ..ai.feedback import (
                evaluate_all_open, quick_regime, adaptive_config,
                calibrated_confidence, reliability_calibration,
            )
            from ..ai import news_feed
            from ..core.exceptions import InterruptionError
            try:
                settle = evaluate_all_open(store, mdm, max_n=40)
            except Exception:
                settle = {"evaluated": 0, "hits": 0, "rate": None}
            df = mdm.get_bars(sym, per, 600)
            # M3-10：留存训练数据引用，供「🧩 模型状态」面板显示训练区间与样本量
            self._last_train_df = df
            # ② 自适应选参
            regime0 = quick_regime(df)
            try:
                cfg = adaptive_config(store, regime0)
            except Exception:
                cfg = {"extended_features": True, "use_ensemble": True,
                       "source": "default", "rate": None}
            # ③ 多源资讯 (with caching)
            try:
                now = time.time()
                if self._news_cache is not None and (now - self._news_cache_ts) < self._news_cache_interval:
                    all_news = self._news_cache
                else:
                    # M5-07③：改用 fetch_all_news（带 should_abort/on_progress）——
                    # 点「停止预测」后不再等待剩余源；进度经 progress 信号上报
                    all_news = news_feed.fetch_all_news(
                        limit=60, force=False, per_source_timeout=8,
                        on_progress=lambda d, t, txt: worker.emit_progress(
                            int(d / t * 100), f"资讯 {txt}"),
                        should_abort=worker.isInterruptionRequested)
                    self._news_cache = all_news
                    self._news_cache_ts = now
                bias_info = news_feed.news_bias_for_symbol(
                    sym, name, category, all_news)
            except InterruptionError:
                raise
            except Exception:
                bias_info = {"bias": 0.0, "matched": 0, "samples": []}
                all_news = {"items": [], "sources": {}, "by_source": {},
                            "by_category": {}}
            # M5-07③：资讯阶段结束的中断检查点（取消后不进入训练）
            if worker.isInterruptionRequested():
                raise InterruptionError("预测已被用户中断")
            # ③.5 盈利策略库信号（回测中心自动进化的可盈利策略，自动应用）
            try:
                strat_sig = evolved_signal_for(sym, df)
            except Exception:
                strat_sig = {"n": 0, "bias": 0.0, "long": 0, "short": 0,
                             "detail": []}
            # ③.6 回测中心联动预载基因：显式把该策略方向融合进研判
            if self._preloaded_gene and self._preloaded_symbol == sym:
                strat_sig = self._merge_preloaded_strategy(sym, df, strat_sig)
            # 融合：资讯偏置 + 自适应权重×策略方向偏置（截断到 ±1）
            # 自适应权重：策略样本越充分、信号越强，融合权重越高（0.3~0.75），
            # 让回测沉淀的高质量策略在研判中占据合理主导，弱信号时不喧宾夺主。
            # —— 回测中心反哺：读取全市场盈利回测调参画像，自我调整融合权重 ——
            from ..ai.linkage_bus import BUS as _BUS
            tuning = _BUS.get_tuning(sym)
            g_tune = (tuning.get("global") or {})
            s_tune = (tuning.get("symbol") or {})
            consensus = float(g_tune.get("consensus", 0.0))
            base_w = float(s_tune.get("weight",
                          g_tune.get("strat_weight_base", 0.30)))
            strat_bias = float(strat_sig.get("bias", 0.0))
            strat_n = int(strat_sig.get("n", 0) or 0)
            strat_conf = min(1.0, strat_n / 5.0) * min(1.0, abs(strat_bias))
            # 基础权重来自回测库容量×方向一致性；单品种有沉淀时进一步上探，
            # 回测信号越强、全市场方向越一致 → 权重越高（自我调整、贴合实际行情）
            w_strat = base_w + 0.45 * strat_conf * (0.5 + 0.5 * consensus)
            w_strat = min(0.85, w_strat)
            fused_bias = bias_info["bias"] + w_strat * strat_bias
            fused_bias = max(-1.0, min(1.0, fused_bias))
            # ④ 完整预测（回测画像偏好：库充足时自动开启扩展特征 / 集成模型）
            ext = bool(cfg["extended_features"]) or bool(
                g_tune.get("prefer_extended", False))
            ens = bool(cfg["use_ensemble"]) or bool(
                g_tune.get("prefer_ensemble", False))
            cfg["extended_features"] = ext
            cfg["use_ensemble"] = ens
            # 延迟初始化 predictor
            if self._predictor is None:
                from ..ai.predictor import FuturesPredictor
                self._predictor = FuturesPredictor()
            # 使用缓存的拟合结果（如果可用且未过期）
            cache_key = (sym, per, ext, ens)
            now = time.time()
            if self._fit_cache is not None and \
               self._fit_cache[0] == cache_key and \
               (now - self._fit_cache[1]) < self._fit_cache_ttl:
                fit = self._fit_cache[2]
            else:
                fit = self._predictor.fit(df, seq_len=20, epochs=25,
                                         extended_features=ext,
                                         use_ensemble=ens,
                                         symbol=sym, period=per)
                self._fit_cache = (cache_key, now, fit)
            res = self._predictor.predict(df, horizon=horizon,
                                         news_bias=fused_bias,
                                         news_samples=bias_info["samples"],
                                         symbol=sym, period=per)
            # ⑤ 置信度校准：优先样本外「可靠性校准」（按模型概率分箱的实际命中率），
            #    样本不足时回退到扁平 regime 命中率（旧行为）。
            cfg_key = "enhanced" if cfg["extended_features"] else "baseline"
            try:
                calib_fn, calib_info = reliability_calibration(
                    store, regime=res["regime"], min_samples=20)
                if calib_fn is not None:
                    conf = float(calib_fn(res["p_up"]))
                else:
                    conf = calibrated_confidence(store, res["regime"], cfg_key,
                                                 res["p_up"])
            except Exception:
                calib_fn, calib_info = None, None
                conf = res["p_up"]
            # M3-12 ①：过去这里会带着 calibrate_p_up 再跑一次完整 predict()，
            # 但重跑唯一生效的副作用只有 p_up 融合（其余字段不依赖 p_up），
            # 却要重做特征工程 + 递归/集成外推 + 全套指标研判 → 单次预测耗时翻倍。
            # 改为就地应用校准函数，语义等价、耗时归零。
            if abs(conf - res["p_up"]) > 1e-9:
                self._predictor.apply_p_up_calibration(res, conf)
            res["symbol"] = sym
            res["period"] = per
            res["strategy_signal"] = strat_sig
            # ⑥ AI多维研判
            try:
                ai_report = news_feed.ai_analyze_news(all_news, res, name,
                                                      category, self.mdm)
            except Exception:
                ai_report = {"model": "heuristic", "trend": "", "risk": "",
                             "suggestion": "", "by_category": {}}
            return res, fit, cfg, bias_info, conf, settle, all_news, ai_report, calib_info

        def done(payload):
            """处理done。
            
                参数:
                    payload"""
            self._on_predict_done(payload)

        def err(e):
            """处理err。
            
                参数:
                    e"""
            self.start_btn.setEnabled(True)
            self.start_btn.setText("🚀 开始预测")
            self.status_lbl.setText(f"预测出错: {e}")
            print("预测错误:", e)

        self._run_worker(work, done, on_err=err, on_interrupted=self._on_pred_interrupted)

    # ------------------------------------------------------------------
    # M4-06⑤：预测长任务中断生命周期
    # ------------------------------------------------------------------
    def _end_prediction(self) -> None:
        """恢复预测按钮可交互态（成功 / 失败 / 中断共用）。"""
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始预测")
        self.stop_btn.setEnabled(False)

    def _stop_prediction(self) -> None:
        """请求中止当前预测流程（协作式：在下一个检查点生效）。"""
        if not getattr(self, "_workers", None):
            self._end_prediction()
            return
        self._workers[-1].requestInterruption()
        self.stop_btn.setEnabled(False)
        self.status_lbl.setText("已请求停止预测，正在等待当前子步骤结束…")

    def _on_pred_interrupted(self) -> None:
        """预测被用户中止：不写结果、不算失败，仅恢复界面。"""
        self._end_prediction()
        self.status_lbl.setText("⏹ 预测已停止（未产生结果）。")

    def _end_replay(self) -> None:
        """恢复回放按钮可交互态（成功 / 失败 / 中断共用）。"""
        self._replaying = False
        self.replay_btn.setEnabled(True)
        self.replay_stop_btn.setEnabled(False)

    def _stop_replay(self) -> None:
        """请求中止当前历史回放（协作式：在下一个品种/窗口边界生效）。"""
        if not getattr(self, "_workers", None):
            self._end_replay()
            return
        self._workers[-1].requestInterruption()
        self.replay_stop_btn.setEnabled(False)
        self.replay_status.setText("已请求停止回放，正在等待当前品种结束…")

    def _on_replay_interrupted(self) -> None:
        """回放被用户中止：不落库、不算失败，仅恢复界面。"""
        self._end_replay()
        self.replay_prog.setVisible(False)
        self.replay_status.setText("⏹ 回放已停止（未写入新样本）。")

    def _on_replay_progress(self, pct: int, text: str) -> None:
        """回放进度回调（M4-09）：真实百分比 + 「回放 x/y」。

        参数:
            pct: int — 0~100 真实百分比
            text: str — 引擎上报的「回放 x/y」文本
        """
        if getattr(self, "_closed", False):
            return
        try:
            self.replay_prog.setValue(pct)
            self.replay_status.setText(
                f"正在回放历史以积累校准样本…（{text}）")
        except Exception:  # noqa: BLE001
            pass

    # ---- 历史回放校准（批量灌入样本外校准样本） ----
    def _run_replay(self):
        """回放本地真实样本，把模型逐窗预测作为已结算样本写入校准库。

        回放在独立 worker 线程中执行（LRU 训练较重），完成后重算可靠性校准并刷新图表。
        回放使用 calibration_replay 内部新建的 predictor，绝不影响本页共享的
        self.predictor（避免污染后续实时预测）。
        """
        if getattr(self, "_replaying", False):
            return
        self._replaying = True
        self.replay_btn.setEnabled(False)
        self.replay_stop_btn.setEnabled(True)
        self.replay_prog.setVisible(True)
        self.replay_prog.setValue(0)
        self.replay_status.setText("正在回放历史以积累校准样本…")

        store = self.store
        only_cur = self.replay_cur.isChecked()
        horizon = self.replay_hor.value()
        if only_cur:
            samples = [(None, self.cur_symbol, self.cur_period)]
        else:
            from ..ai.calibration_replay import discover_local_samples as _discover
            samples = _discover("data/real_samples")
            if not samples:
                samples = [(None, self.cur_symbol, self.cur_period)]

        total = len(samples)

        def work():
            """处理work。"""
            from ..ai.calibration_replay import load_bars_from_csv, replay_symbol
            # M4-09：修复既有遗漏——reliability_calibration 此前仅在预测 work 内导入，
            # 回放 work 引用会抛 NameError；此处显式导入以保障回放完整闭环。
            from ..ai.feedback import reliability_calibration
            added_total = 0
            for idx, (path, sym, per) in enumerate(samples):
                # M4-06：逐品种边界检查中断（协作式停止，在下一品种开始前生效）
                self._workers[-1].check_interruption()
                df = load_bars_from_csv(path) if path else None
                if df is None:
                    try:
                        df = self.mdm.get_bars(self.cur_symbol, self.cur_period, 600)
                    except Exception:
                        df = None
                if df is not None:
                    # 单个品种回放（逐文件调用 replay_symbol，避免一次性载入全部大 CSV）
                    rr = replay_symbol(store, df, sym, period=per, horizon=horizon,
                                       stride=8, max_samples=250,
                                       progress_cb=lambda a, s: None)
                    added_total += rr["added"]
                # M4-09：真实百分比进度（含跳过样本也计入分母）
                if total:
                    self._workers[-1].emit_progress(
                        int((idx + 1) / total * 100), f"回放 {idx + 1}/{total}")
            try:
                fn, info = reliability_calibration(store, regime=None, min_samples=20)
            except Exception:
                fn, info = None, {"status": "error"}
            return {"added": added_total, "info": info,
                    "syms": len(samples), "horizon": horizon,
                    "only_cur": only_cur}

        def done(payload):
            """处理done。
            
                参数:
                    payload"""
            self._end_replay()
            self.replay_prog.setValue(100)
            self.replay_prog.setVisible(False)
            info = payload.get("info", {})
            if info.get("status") == "ok":
                self.replay_status.setText(
                    f"回放完成：写入 {payload['added']} 条已结算样本，"
                    f"校准已启用（{info.get('coverage')} 条）")
                try:
                    self._refresh_reliability()
                except Exception:
                    pass
            else:
                self.replay_status.setText(
                    f"回放完成：写入 {payload['added']} 条，但样本仍不足（需 ≥20 条已结算）")
                try:
                    self._refresh_reliability()
                except Exception:
                    pass

        def err(e):
            """处理err。
            
                参数:
                    e"""
            self._end_replay()
            self.replay_prog.setValue(100)
            self.replay_prog.setVisible(False)
            self.replay_status.setText(f"回放出错: {e}")
            print("回放出错:", e)

        self._run_worker(work, done, on_err=err,
                        on_progress=self._on_replay_progress,
                        on_interrupted=self._on_replay_interrupted)

    def _run_walk_forward(self):
        """M3-05 ④：对当前品种跑真·Walk-Forward 滚动验证。

        逐折重训成本较高（约为单次评估的 fold 数倍），故放在 worker 线程；
        使用**独立**的 FuturesPredictor，绝不污染本页共享的 self.predictor。
        结果展示折数、样本外方向准确率与 MAE，并写入页面日志。
        """
        if getattr(self, "_wf_running", False):
            return
        self._wf_running = True
        self.wf_btn.setEnabled(False)
        self.wf_prog.setVisible(True)
        self.wf_status.setText("正在做 Walk-Forward 滚动验证（逐折重训，请稍候）…")

        sym, per = self.cur_symbol, self.cur_period

        def work():
            """处理work。"""
            from ..ai.predictor import FuturesPredictor
            df = self.mdm.get_bars(sym, per, 600)
            if df is None or len(df) < 80:
                return {"error": "数据不足（需 ≥80 根 K 线）"}
            # 独立实例：避免覆盖本页共享模型的归一化统计量
            p = FuturesPredictor()
            return p.evaluate(df, horizon=1, seq_len=20, epochs=10,
                              extended_features=False, use_ensemble=False,
                              symbol=sym, period=per, use_walk_forward=True)

        def done(r):
            """处理done。

                参数:
                    r"""
            self._wf_running = False
            self.wf_btn.setEnabled(True)
            self.wf_prog.setVisible(False)
            if not r or r.get("error"):
                self.wf_status.setText(f"Walk-Forward 验证失败：{r.get('error') if r else '无结果'}")
                return
            n_folds = int(r.get("n_folds", 0))
            acc = float(r.get("direction_acc", 0.0))
            mae = float(r.get("mae", 0.0))
            wf_on = bool(r.get("walk_forward"))
            fold_txt = "、".join(f"#{f['fold']}[{f['train'][1]}→{f['test'][1]}]"
                                 for f in (r.get("folds") or []))
            self.wf_status.setText(
                f"{'✅ 真·滚动' if wf_on else '⚠️ 已回退固定切分'}：{n_folds} 折 · "
                f"样本外方向准确率 {acc:.1%} · MAE {mae:.5f} · "
                f"OOS 样本 {r.get('val_samples', 0)}"
                + (f"\n折叠（train_end→test_end）：{fold_txt}" if fold_txt else ""))
            logger.info("Walk-Forward 验证 [%s]：%d 折，方向准确率 %.3f，MAE %.6f",
                        sym, n_folds, acc, mae)

        def err(e):
            """处理err。

                参数:
                    e"""
            self._wf_running = False
            self.wf_btn.setEnabled(True)
            self.wf_prog.setVisible(False)
            self.wf_status.setText(f"Walk-Forward 验证出错: {e}")

        self._run_worker(work, done, on_err=err)

    def _refresh_reliability(self):
        """重算全局可靠性校准并刷新可靠度图（无当前预测落点时 mark=None）。"""
        try:
            fn, info = reliability_calibration(self.store, regime=None, min_samples=20)
        except Exception:
            fn, info = None, {"status": "error", "bins": [], "coverage": 0}
        bins = info.get("bins") or []
        self._update_calib_stats(bins, info.get("status", ""), info.get("coverage", 0))
        self.reliability_chart.set_data(
            bins=bins, status=info.get("status", ""),
            coverage=info.get("coverage", 0), mark=None)
        self.reliability_chart.repaint()

    def _update_calib_stats(self, bins, status: str, coverage: int) -> None:
        """刷新「校准状态速览」卡片（样本数 / 平均偏差 / 评级 / 校准区间±）
        与空状态提示。

        bins: reliability_calibration 返回的
              [(center, smoothed, n, lo, hi), ...]；
        coverage: 已结算样本总数。样本不足（<20）时显示提示并标「样本不足」。
        """
        from ..ai.feedback import mean_band_width
        valid = [(c, s, n) for (c, s, n, *_ ) in (bins or [])
                 if n > 0 and 0.0 <= s <= 1.0 and 0.0 <= c <= 1.0]
        if not valid or int(coverage or 0) < 20:
            self.calib_stats["n"].set_value(f"{int(coverage or 0)}")
            self.calib_stats["err"].set_value("--")
            self.calib_stats["grade"].set_value("样本不足", pal()["sub"])
            self.calib_stats["band"].set_value("--")
            self.calib_hint.setVisible(True)
            return
        self.calib_hint.setVisible(False)
        # 加权平均绝对偏差（校准误差）与方向性偏差（负=过度自信）
        tot = float(sum(n for _, _, n in valid))
        werr = sum(abs(s - c) * n for c, s, n in valid) / tot
        bias = sum((s - c) * n for c, s, n in valid) / tot
        # 校准整体不确定性：各分箱 Wilson 区间宽度的均值（绝对值）
        mbw = mean_band_width(bins)
        if mbw is not None:
            self.calib_stats["band"].set_value(f"{mbw * 100:.1f}pp")
        else:
            self.calib_stats["band"].set_value("--")
        # 评级：先按点估计误差/方向定档，区间过宽时追加「宽区间」警示
        if werr < 0.06:
            grade, gcol = "良好", pal()["up"]
        elif bias < 0:
            grade, gcol = "偏自信", pal()["down"]
        else:
            grade, gcol = "偏保守", "#f59e0b"
        if mbw is not None and mbw > 0.20:
            grade = grade + "·宽区间"
            gcol = "#f59e0b"
        self.calib_stats["n"].set_value(f"{int(coverage)}")
        self.calib_stats["err"].set_value(f"{werr * 100:.1f}pp")
        self.calib_stats["grade"].set_value(grade, gcol)

    def _merge_preloaded_strategy(self, sym: str, df, strat_sig: dict) -> dict:
        """把回测中心联动预载的策略基因融合进策略信号（双向联动的「基因透传」）。

        在策略明细首位插入该策略，并相应累计 n/多空计数，供研判页显式展示。
        """
        if not (self._preloaded_gene and self._preloaded_symbol == sym):
            return strat_sig
        try:
            from ..strategy.auto_evolve import (
                ensemble_strategy_signal as _ensemble_sig,
                describe_gene as _describe_gene,
            )
            closes = df["close"].tolist()
            highs = df["high"].tolist() if "high" in df else closes
            lows = df["low"].tolist() if "low" in df else closes
            d = int(round(_ensemble_sig(self._preloaded_gene, closes, highs, lows) or 0))
            pdesc = _describe_gene(self._preloaded_gene)
            pre = {"desc": pdesc, "direction": d,
                   "preloaded": True, "source": "回测中心联动载入"}
            strat_sig.setdefault("detail", []).insert(0, pre)
            strat_sig["n"] = int(strat_sig.get("n", 0) or 0) + 1
            if d > 0:
                strat_sig["long"] = int(strat_sig.get("long", 0) or 0) + 1
            elif d < 0:
                strat_sig["short"] = int(strat_sig.get("short", 0) or 0) + 1
            strat_sig["preloaded_desc"] = pdesc
            strat_sig["preloaded_dir"] = d
        except Exception:  # noqa: BLE001
            pass
        return strat_sig

    def _compute_trade_marks(self, res: dict, df=None) -> list:
        """计算K线图交易参考点标注（增强版）。
        
        基于趋势分析 + 压力支撑位 + KP预测，在图上标注：
        - 建议买入价格（绿色菱形）：支撑位附近、模型看多信号确认
        - 建议卖出价格（红色菱形）：压力位附近、目标止盈位
        - 多档参考区间 + 止损位
        """
        try:
            levels = res.get("levels", [])
            forecast = res.get("forecast", [])
            last = float(res.get("last_close", 0))
            p_up = float(res.get("p_up", 0.5))
            exp_ret = float(res.get("expected_return_pct", 0.0))

            # 分离压力位和支撑位
            supports = [lv for lv in levels
                        if float(lv.get("price", 0)) < last]
            resistances = [lv for lv in levels
                           if float(lv.get("price", 0)) > last]
            supports.sort(key=lambda lv: float(lv.get("price", 0)),
                          reverse=True)
            resistances.sort(key=lambda lv: float(lv.get("price", 0)))

            marks = []

            # 1. 建议买入位（基于支撑位 + 模型看多信号）
            if supports and last > 0:
                nearest_support = float(supports[0]["price"])
                # 支撑位上方 0.3%~0.8% 作为入场区间
                enter_low = nearest_support * 1.003
                enter_high = nearest_support * 1.008
                if p_up >= 0.55:
                    enter_y = enter_low
                elif p_up >= 0.45:
                    enter_y = (enter_low + enter_high) / 2
                else:
                    enter_y = enter_high
                marks.append({
                    "x_idx": -1,
                    "y_enter": enter_y,
                    "label_enter": "建议买入",
                    "price_display": f"{nearest_support:,.1f}",
                    "color_enter": "#22c55e",
                })
                # 第二支撑位（加仓区间）
                if len(supports) > 1:
                    second_support = float(supports[1]["price"])
                    marks.append({
                        "x_idx": -1,
                        "y_enter": second_support * 1.005,
                        "label_enter": "加仓区间",
                        "price_display": f"{second_support:,.1f}",
                        "color_enter": "#10b981",
                    })

            # 2. 建议卖出位（基于压力位 + 预测目标价）
            exit_targets = []
            if resistances and last > 0:
                nearest_resistance = float(resistances[0]["price"])
                exit_y = nearest_resistance * 0.997
                exit_targets.append((exit_y, nearest_resistance, "建议卖出"))
            if len(forecast) > 1:
                forecast_target = float(forecast[-1])
                if forecast_target > last:
                    exit_targets.append(
                        (forecast_target * 0.997, forecast_target, "AI目标"))
            seen_prices = set()
            unique_targets = []
            for y, price, label in exit_targets:
                price_key = round(price, 0)
                if price_key not in seen_prices:
                    seen_prices.add(price_key)
                    unique_targets.append((y, price, label))
            unique_targets.sort(key=lambda x: x[1])
            for i, (y, price, label) in enumerate(unique_targets[:2]):
                marks.append({
                    "x_idx": -1,
                    "y_enter": y,
                    "label_enter": label if i == 0 else "第二目标",
                    "price_display": f"{price:,.1f}",
                    "color_enter": "#ef4444",
                })

            # 3. 止损位
            risk_score = float(res.get("risk", {}).get("score", 50))
            if supports and last > 0:
                far_support = (float(supports[-1]["price"])
                               if len(supports) > 1
                               else float(supports[0]["price"]))
                stop_loss = far_support * 0.99
                marks.append({
                    "x_idx": -1,
                    "y_enter": stop_loss,
                    "label_enter": "止损位",
                    "price_display": f"{far_support:,.1f}",
                    "color_enter": "#f59e0b",
                })
            return marks
        except Exception:
            return []

    def _on_predict_done(self, payload):
        """预测完成后的UI更新。"""
        (res, fit, cfg, bias_info, conf, settle, all_news,
         ai_report, calib_info) = payload
        self._end_prediction()
        self.status_lbl.setText(f"✅ 预测完成 — {res['symbol']} / {res['period']}")
        self._last_res = res

        # ---- 更新K线图 ----
        df = self.mdm.get_bars(res["symbol"], res["period"], 300)
        ind = cached_add_indicators(res["symbol"], res["period"], df)
        bars = df_to_bars(df)
        self.chart.set_data(bars, ma={"MA10": ind["MA10"].tolist(),
                                      "MA20": ind["MA20"].tolist()})
        self.chart.set_watermark(f"{res['symbol']} · {res['period']} · KP预测")
        self.chart.set_forecast(res["forecast"], res["upper"], res["lower"])
        self.chart.set_levels(res["levels"])
        # 标注买卖点位
        self.chart.set_trade_marks(self._compute_trade_marks(res, df))

        # ---- 更新副图指标 + 预测曲线 ----
        self._render_indicators(ind)

        # ---- 概率校准可视化（校准可靠度图 + 预测概率带） ----
        self._update_calibration_tab(res, conf, calib_info)

        # 指标共振研判
        try:
            from ..analysis.signals import resonance as _resonance, trend_score as _trend_score
            reso = _resonance(ind)
            tr = _trend_score(ind)
        except Exception:
            reso = {"verdict": "信号不明", "score": 0}
            tr = {"state": "未知"}
        # ---- 校准置信带 → 实时研判降级信号 ----
        # 若本次预测落点落在「校准区间过宽」区域（该档概率校准样本稀疏），
        # 研判徽章追加「⚠低置信」并转琥珀色，提示模型自信度不可尽信。
        low_conf, band_lo, band_hi, band_w = self._calib_conf_flag(calib_info, res["p_up"])
        self._render_verdict_badge(reso, low_conf)
        self.score_bar.set_pct((reso["score"] + 100) / 200)
        self.score_val.setText(f"{reso['score']:+.0f}")
        self.trend_badge.setText(tr["state"])
        self.trend_badge.set_color(pal()["accent"], "#fff")
        ind_info = {"verdict": reso["verdict"], "score": reso["score"],
                    "state": tr["state"]}

        # ---- 更新结果卡片 ----
        col = pal()["up"] if res["expected_return_pct"] >= 0 else pal()["down"]
        self.chips["exp"].set_value(f"{res['expected_return_pct']:+,.2f}%", col)
        self.chips["exp"].set_sub("年化")
        self.chips["pup"].set_value(f"{res['p_up']*100:,.1f}%")
        self.chips["pup"].set_sub("涨幔概率")
        self.chips["risk"].set_value(
            f"{res['risk']['label']} {res['risk']['score']:.0f}")
        self.chips["regime"].set_value(res["regime"])
        self.chips["model"].set_value(res["model"])
        self.chips["conf"].set_value(f"{conf*100:,.0f}%")
        nb = res.get("news_bias", 0.0)
        nb_txt = ("中性" if abs(nb) < 0.05 else
                  f"偏多 {nb:+.2f}" if nb > 0 else f"偏空 {nb:+.2f}")
        self.chips["news"].set_value(
            nb_txt,
            pal()["up"] if nb > 0.05 else
            pal()["down"] if nb < -0.05 else "")

        # 做多/做空性价比
        self.long_bar.set_pct(res["long_short"]["long"] / 100)
        self.short_bar.set_pct(res["long_short"]["short"] / 100)
        self.long_val.setText(f"{res['long_short']['long']:.0f}%")
        self.short_val.setText(f"{res['long_short']['short']:.0f}%")
        # 校准不确定度 → 建议徽章一致性降级：区间过宽时，模型「偏多」建议降为
        # 「观望（置信偏低）」，与下方合成结论「谨慎观望（置信偏低）」保持一致。
        rec_txt = PredictOpsPage._soft_degrade_recommend(
            res["long_short"]["recommend"], low_conf)
        self.rec_badge.setText("建议:" + rec_txt)
        self.rec_badge.set_color(
            "#f59e0b" if rec_txt.startswith("观望（置信偏低）") else pal()["accent"],
            "#1a1d27" if rec_txt.startswith("观望（置信偏低）") else "#fff")

        # ---- 资讯深度解读 ----
        sym = res["symbol"]
        name = category = ""
        for r in self.mdm.universe:
            if symbol_code(r) == sym:
                name, category = r[1], r[2]
                break
        try:
            from ..ai import news_feed as _nf
            news_an = _nf.analyze_symbol_news(sym, name, category,
                                                    all_news)
        except Exception:
            news_an = {"bias": bias_info.get("bias", 0.0),
                       "matched": bias_info.get("matched", 0),
                       "bull": 0, "bear": 0, "items": []}

        # ---- 基本面/资金面 ----
        fund_info = {"sym_flow": None, "sym_oi": None, "sym_vr": None,
                     "sym_chg": None, "cat_avg": None, "cat_rank": None,
                     "cat_n": 0, "cat_flow": None}
        try:
            pan = self.mdm.compute_panorama(res["period"])
            if not pan.empty:
                srow = pan[pan["symbol"] == sym]
                if not srow.empty:
                    sr = srow.iloc[0]
                    fund_info.update(
                        sym_flow=float(sr["fund_flow"]),
                        sym_oi=float(sr["oi_chg"]),
                        sym_vr=float(sr["vol_ratio"]),
                        sym_chg=float(sr["chg_pct"]))
                cat = pan[pan["category"] == category]
                if not cat.empty:
                    fund_info["cat_avg"] = float(cat["chg_pct"].mean())
                    fund_info["cat_n"] = int(len(cat))
                    fund_info["cat_flow"] = float(cat["fund_flow"].sum())
                    rank = int((cat["chg_pct"] < fund_info["sym_chg"]).sum() + 1)
                    fund_info["cat_rank"] = rank
        except Exception:
            pass

        try:
            stats = self.store.prediction_stats()
        except Exception:
            stats = {"total": 0, "rate": None, "by_config": {},
                     "by_regime": {}, "by_model": {}}
        try:
            closed = self.store.query_closed_predictions(limit=6)
        except Exception:
            closed = []

        # ---- 更新预测解读 ----
        self.detail.setHtml(self._detail_html(
            res, cfg, bias_info, conf, news_an, name, category,
            ind_info, fund_info, stats, closed, settle,
            ai_report=ai_report, all_news=all_news,
            calib_band=(band_lo, band_hi, band_w, low_conf)))

        # ---- 更新基本面分析Tab ----
        self.fundamental_text.setHtml(self._fundamental_html(
            res, fund_info, name, category, news_an))

        # ---- 存库 ----
        cfg_key = "enhanced" if cfg["extended_features"] else "baseline"
        self.store.save_prediction({
            "ts": str(dt.datetime.now()),
            "symbol": res["symbol"],
            "period": res["period"],
            "horizon": res["horizon"],
            "last_close": res["last_close"],
            "expected_return_pct": res["expected_return_pct"],
            "p_up": res["p_up"],
            "p_down": res["p_down"],
            "risk_score": res["risk"]["score"],
            "risk_label": res["risk"]["label"],
            "model": res["model"],
            "regime": res["regime"],
            "verdict": res["resonance"]["verdict"],
            "score": res["resonance"]["score"],
            "forecast": str([round(x, 2) for x in res["forecast"]]),
            "confidence": round(float(conf), 4),
            "status": "open",
            "config": cfg_key,
        })

        # ---- 双向联动：把本次研判信号推送到回测中心，待其验证（自我训练闭环） ----
        try:
            from ..ai.linkage_bus import BUS as _BUS
            strat = res.get("strategy_signal") or {}
            _BUS.push_prediction(res["symbol"], {
                "p_up": float(res.get("p_up", 0.5)),
                "p_down": float(res.get("p_down", 0.5)),
                "expected_return_pct": float(res.get("expected_return_pct", 0.0)),
                "horizon": int(res.get("horizon", 0)),
                "forecast_target": (float(res["forecast"][-1])
                                    if res.get("forecast") else None),
                "direction_bias": float(strat.get("bias", 0.0) or 0.0),
                "news_bias": float(res.get("news_bias", 0.0)),
                "regime": res.get("regime", ""),
                "ts": str(dt.datetime.now()),
            })
        except Exception:  # noqa: BLE001
            pass
        self._refresh_linkage_label()

        # M3-10：本次预测刚训练完 predictor，模型状态面板同步刷新
        # （训练区间 / 样本量 / 是否降级到此才有真实值）
        try:
            self._refresh_model_cards()
        except Exception:  # noqa: BLE001
            pass

        # 若选品排行/板块机会此前加载失败（空白），预测完成后自愈刷新一次
        if not self._results:
            self._run_screen()

    # ---- 概率校准可视化 ----
    def _update_calibration_tab(self, res: dict, conf, calib_info) -> None:
        """刷新「概率校准」页：校准可靠度图 + 预测价格概率带。

        calib_info: reliability_calibration 返回的 info 字典（含 bins/status/
                    coverage）；可能为 None（异常回退）或空 bins（样本不足）。
        两个图表均做了防御：数据缺失时显示提示而非崩溃，保证任何状态下
        「概率校准」页都可安全打开。
        """
        # ① 校准可靠度图：用样本外校准分箱（含本次预测落点）
        bins, status, coverage = [], "", 0
        if isinstance(calib_info, dict):
            bins = calib_info.get("bins", []) or []
            status = calib_info.get("status", "") or ""
            coverage = int(calib_info.get("coverage", 0) or 0)
        self._update_calib_stats(bins, status, coverage)
        # 本次预测落点的校准区间（Wilson）：把可靠度图的「区间带」直接挂到落点
        pu = float(res.get("p_up", 0.5))
        conf = float(conf)
        band = calibration_band_at(bins, pu)
        mark = (pu, conf, band[0], band[1]) if (band[0] is not None
                                                 and band[1] is not None) else (pu, conf)
        try:
            self.reliability_chart.set_data(
                bins, status=status, coverage=coverage, mark=mark)
        except Exception:  # noqa: BLE001
            self.reliability_chart.set_data([], mark=mark)

        # ② 预测价格概率带：中枢价 + ±1σ 置信区间（PriceChart 复用）
        def _ok(v):
            """处理ok。
            
                参数:
                    v"""
            return v is not None and math.isfinite(float(v))
        try:
            fc = res.get("forecast") or []
            up = res.get("upper") or []
            lo = res.get("lower") or []
            if (len(fc) > 1 and len(up) == len(fc) and len(lo) == len(fc)
                    and all(_ok(v) for v in fc)
                    and all(_ok(v) for v in up)
                    and all(_ok(v) for v in lo)):
                x = list(range(len(fc)))
                self.prob_band.set_data(
                    series=[{"name": "预测中枢", "color": "#f59e0b",
                             "x": x, "y": [float(v) for v in fc]}],
                    bands=[{"lower": [float(v) for v in lo],
                            "upper": [float(v) for v in up],
                            "color": "#f59e0b", "alpha": 45}],
                    x_ticks=[(0.0, "今"),
                             (1.0, f"+{int(res.get('horizon', 1))}步")],
                    title="预测价格概率带（±1σ 置信区间）")
            else:
                self.prob_band.clear()
        except Exception:  # noqa: BLE001
            self.prob_band.clear()

    # ---- 校准不确定度 → 结论软降级 ----
    @staticmethod
    def _soft_degrade_enter(enter: str, enter_col: str, low_conf: bool):
        """校准区间过宽时，把激进「可以入手」软降级为「谨慎观望（置信偏低）」。

        只有真正激进的建仓建议才降级；偏空 / 观望结论本身已保守，不改。
        返回 (enter, enter_col)，low_conf 为 False 时原样返回（零副作用）。
        """
        if low_conf and enter.startswith("可以入手"):
            return "谨慎观望（置信偏低）", "#f59e0b"
        return enter, enter_col

    @staticmethod
    def _soft_degrade_recommend(rec: str, low_conf: bool):
        """校准区间过宽时，把模型「偏多」建议降级为「观望（置信偏低）」。

        与 _soft_degrade_enter 保持结论一致，避免「建议:偏多」与「谨慎观望」矛盾。
        「偏空 / 观望」本身已保守，不改。low_conf 为 False 时原样返回。
        """
        if low_conf and rec == "偏多":
            return "观望（置信偏低）"
        return rec

    # ---- 预测解读HTML ----
    @staticmethod
    def _detail_html(res, cfg, bias_info, conf, news_an, name, category,
                     ind_info=None, fund_info=None, stats=None,
                     closed=None, settle=None, ai_report=None,
                     all_news=None, calib_band=None) -> str:
        """处理detailhtml。
        
            参数:
                res
                cfg
                bias_info
                conf
                news_an
                name
                category
                ind_info
                fund_info
                stats
                closed
                settle
                ai_report
                all_news
                calib_band
        
            返回:
                str"""
        p = pal()
        up_c, dn_c, tx_c, mut_c = p["up"], p["down"], p["text"], "#94a3b8"
        p_up = float(res["p_up"])
        p_dn = float(res["p_down"])
        last = float(res["last_close"])
        target = float(res["forecast"][-1])
        exp = float(res["expected_return_pct"])
        horizon = int(res["horizon"])
        risk_score = float(res["risk"]["score"])
        risk_label = res["risk"]["label"]
        reso = (ind_info or {}).get("verdict", "—")
        ind_score = float((ind_info or {}).get("score", 0) or 0)

        # 校准不确定度（落点 Wilson 区间）说明：把「区间置信带」直接挂到研判文本，
        # 让用户在看结论时同步感知「本次预测的校准可信度」，而非只看一个点估计。
        calib_note = ""
        clow = False  # 落点是否落在「校准区间过宽」档（由 calib_band 第4元素透传）
        if calib_band is not None:
            clo, chi, cw, clow = calib_band
            if clo is not None and chi is not None and cw is not None:
                wpp = cw * 100
                if clow:
                    calib_note = (f"（⚠ 落点校准区间 ±{wpp:.1f}pp 过宽，"
                                  f"该档概率校准样本稀疏，研判可信度下降，"
                                  f"建议仅作参考）")
                else:
                    calib_note = f"（落点校准区间 ±{wpp:.1f}pp，校准较可信）"

        # 资讯偏置文案（本函数内独立计算，避免依赖外部局部变量）
        nb = float(res.get("news_bias", 0.0))
        nb_txt = ("中性" if abs(nb) < 0.05 else
                  f"偏多 {nb:+.2f}" if nb > 0 else f"偏空 {nb:+.2f}")

        if p_up >= 0.55:
            dir_word, ccol = "上涨", up_c
        elif p_up <= 0.45:
            dir_word, ccol = "下跌", dn_c
        else:
            dir_word, ccol = "震荡", mut_c

        if p_up >= 0.55 and ind_score > 0 and risk_score < 60:
            enter, enter_col = "可以入手（偏多）", up_c
        elif p_up <= 0.45 or ind_score < 0:
            enter, enter_col = "暂不建议入手（偏空）", dn_c
        else:
            enter, enter_col = "谨慎观望（方向不明）", "#f59e0b"

        # 校准不确定度 → 结论软降级：区间过宽时，激进「可以入手」降为「谨慎观望（置信偏低）」，
        # 避免在高不确定档位误导用户激进建仓。偏空 / 观望结论本身已保守，不改。
        enter, enter_col = PredictOpsPage._soft_degrade_enter(enter, enter_col, clow)

        def row(k, v, color=""):
            """处理行。
            
                参数:
                    k
                    v
                    color"""
            c = f" style='color:{color}'" if color else ""
            return (f"<tr><td style='color:{mut_c};padding:3px 12px 3px 0;"
                    f"white-space:nowrap'>{k}</td>"
                    f"<td{c}>{v}</td></tr>")

        # 资讯深度
        news_items = (news_an or {}).get("items", [])
        news_html = ""
        for it in news_items[:5]:
            s = float(it.get("sentiment", 0))
            tone = "📈" if s > 0 else "📉" if s < 0 else "➖"
            news_html += (
                f"<div style='padding:4px 0;border-bottom:1px solid #1a1d27;'>"
                f"{tone} <span style='color:{tx_c}'>{it.get('title','')[:60]}</span>"
                f" <span style='color:{mut_c};font-size:11px;'>{it.get('source','')}</span>"
                f"</div>")

        # AI研判
        ai_trend = (ai_report or {}).get("trend", "")
        ai_risk = (ai_report or {}).get("risk", "")
        ai_sugg = (ai_report or {}).get("suggestion", "")
        ai_html = ""
        if ai_trend:
            ai_html += f"<p><b>趋势研判：</b>{ai_trend}</p>"
        if ai_risk:
            ai_html += f"<p><b>风险提示：</b>{ai_risk}</p>"
        if ai_sugg:
            ai_html += f"<p><b>操作建议：</b>{ai_sugg}</p>"

        # 盈利策略库信号（回测中心自动进化并同步）
        ss = res.get("strategy_signal") or {}
        strat_html = ""
        if int(ss.get("n", 0) or 0) > 0:
            sb = float(ss.get("bias", 0.0) or 0.0)
            if sb > 0.15:
                sb_txt, sb_col = f"偏多 {sb:+.2f}", up_c
            elif sb < -0.15:
                sb_txt, sb_col = f"偏空 {sb:+.2f}", dn_c
            else:
                sb_txt, sb_col = f"中性 {sb:+.2f}", mut_c
            rows = ""
            for d in (ss.get("detail") or [])[:4]:
                sig = int(d.get("signal", 0) or 0)
                tone = ("📈 看多" if sig > 0 else
                        "📉 看空" if sig < 0 else "➖ 观望")
                tr = d.get("total_return")
                sh = d.get("sharpe")
                tr_s = format_metric("total_return", tr)
                sh_s = format_metric("sharpe", sh)
                rows += (
                    f"<div style='padding:2px 0;color:{mut_c};font-size:12px;'>"
                    f"{tone} <span style='color:{tx_c}'>{d.get('desc','')[:52]}</span>"
                    f"（回测收益 {tr_s}，夏普 {sh_s}）</div>")
            strat_html = (
                f"<p><b>🧬 盈利策略库：</b>已自动应用 "
                f"<b>{ss.get('n', 0)}</b> 个经回测验证的盈利策略"
                f"（看多 {ss.get('long', 0)} / 看空 {ss.get('short', 0)}），"
                f"加权方向 <b style='color:{sb_col}'>{sb_txt}</b>，"
                f"已融合进本次预测。</p>{rows}")

        # 回测联动（与「回测中心」指标口径完全一致，确保两板块无缝对接）
        link = backtest_linkage_for(res.get("symbol", ""))
        link_html = ""
        if link.get("has_backtest"):
            best = link.get("best", {})
            db = float(link.get("direction_bias", 0.0) or 0.0)
            if db > 0.15:
                db_txt, db_col = f"偏多 {db:+.2f}", up_c
            elif db < -0.15:
                db_txt, db_col = f"偏空 {db:+.2f}", dn_c
            else:
                db_txt, db_col = f"中性 {db:+.2f}", mut_c
            def lr(k, v):
                """处理lr。
                
                    参数:
                        k
                        v"""
                return (f"<tr><td style='color:{mut_c};padding:3px 12px 3px 0;"
                        f"white-space:nowrap'>{METRIC_LABEL[k]}</td>"
                        f"<td>{v}</td></tr>")
            rows = "".join(lr(k, best.get(f"{k}__fmt", "—"))
                           for k in ("total_return", "annual_return", "sharpe",
                                     "max_drawdown", "win_rate", "profit_factor")
                           if k in best)
            link_html = (
                f"<p><b>🔗 回测联动：</b>该品种已沉淀 "
                f"<b>{link['strategy_count']}</b> 个经回测验证的盈利策略，"
                f"加权方向 <b style='color:{db_col}'>{db_txt}</b>。"
                f"最优策略：<span style='color:{tx_c}'>{link.get('best_desc','')}</span></p>"
                f"<table style='border-collapse:collapse;margin-top:4px;'>"
                f"<tr><td colspan='2' style='color:{mut_c};font-size:11px;'>"
                f"最优策略指标（与回测中心同源）</td></tr>{rows}</table>")

        # 历史表现
        stats_html = ""
        if stats:
            total = stats.get("total", 0)
            rate = stats.get("rate")
            if total > 0:
                rate_str = f"{rate*100:.1f}%" if rate is not None else "—"
                stats_html = (
                    f"<p><b>历史预测回测：</b>累计 {total} 次，"
                    f"方向命中率 {rate_str}，"
                    f"已结算 {settle.get('evaluated', 0)} 次"
                    f"（命中 {settle.get('hits', 0)} 次）</p>")

        html = f"""
        <div style='font-size:13px;line-height:1.6;'>
            <p style='font-size:15px;font-weight:bold;color:{enter_col};'>
                ● 结论：{enter}
            </p>
            <p><b>模型面：</b>
            方向「{dir_word}」概率 {p_up*100:.0f}% / {p_dn*100:.0f}%，
            预期收益 {exp:+.2f}% / {horizon} 根K线，
            风险度「{risk_label}」（{risk_score:.0f} 分），
            模型 {res.get('model','—')} / 行情状态 {res.get('regime','—')}，
            校准置信度 {conf*100:.0f}%。{calib_note}
            </p>
            <p><b>技术面：</b>
            指标共振「{reso}」（多空分 {ind_score:+.0f}），
            趋势「{(ind_info or {}).get('state','—')}」。
            K线图已标注<b style='color:#22c55e;'>建议买入</b>与
            <b style='color:#ef4444;'>建议卖出</b>价位，供参考。
            </p>
            {strat_html}
            {ai_html}
            {stats_html}
            <table>
                {row('合约', f'{name} ({res.get("symbol","")})')}
                {row('周期', PERIOD_LABEL.get(res.get("period",""), res.get("period","")))}
                {row('最新价', f'{last:,.2f}')}
                {row('KP预测目标', f'{target:,.2f}（{((target/last-1)*100):+.2f}%）')}
                {row('资讯偏置', f'{nb_txt}（匹配 {bias_info.get("matched",0)} 条）')}
            </table>
            {'<div style="margin-top:8px;border-top:1px solid #2a2e3a;padding-top:8px;">' + news_html + '</div>' if news_html else ''}
        </div>
        """
        return html

    @staticmethod
    def _fundamental_html(res, fund_info, name, category, news_an) -> str:
        """生成基本面分析HTML。"""
        p = pal()
        tx_c, mut_c = p["text"], "#94a3b8"
        fi = fund_info or {}

        def row(k, v, color=""):
            """处理行。
            
                参数:
                    k
                    v
                    color"""
            c = f" style='color:{color}'" if color else ""
            return (f"<tr><td style='color:{mut_c};padding:3px 12px 3px 0;"
                    f"white-space:nowrap'>{k}</td>"
                    f"<td{c}>{v}</td></tr>")

        flow_color = ("#22c55e" if fi.get("sym_flow", 0) > 0
                      else "#ef4444" if fi.get("sym_flow", 0) < 0
                      else tx_c)
        oi_color = ("#22c55e" if fi.get("sym_oi", 0) > 0
                    else "#ef4444" if fi.get("sym_oi", 0) < 0
                    else tx_c)

        news_items = (news_an or {}).get("items", [])
        news_html = ""
        for it in news_items[:8]:
            s = float(it.get("sentiment", 0))
            tone = "📈" if s > 0 else "📉" if s < 0 else "➖"
            news_html += (
                f"<div style='padding:4px 0;border-bottom:1px solid #1a1d27;'>"
                f"{tone} {it.get('title','')[:60]}"
                f" <span style='color:{mut_c};font-size:11px;'>"
                f"{it.get('source','')} | {it.get('category','')}</span>"
                f"</div>")

        html = f"""
        <div style='font-size:13px;line-height:1.6;'>
            <p style='font-size:15px;font-weight:bold;color:{tx_c};'>
                📊 {name}（{category}）— 基本面分析
            </p>
            <table>
                {row('品种', f'{name}（{res.get("symbol","")}）')}
                {row('板块', category)}
                {row('最新价', f'{float(res.get("last_close",0)):,.2f}')}
                {row('资金流向', f"{fi.get('sym_flow', '—')} 亿" if fi.get('sym_flow') is not None else '—', flow_color)}
                {row('持仓变化', f"{fi.get('sym_oi', '—'):+.2f}%" if fi.get('sym_oi') is not None else '—', oi_color)}
                {row('量比', f"{fi.get('sym_vr', '—'):.2f}" if fi.get('sym_vr') is not None else '—')}
                {row('板块平均涨跌', f"{fi.get('cat_avg', '—'):+.2f}%" if fi.get('cat_avg') is not None else '—')}
                {row('板块内排名', f"{fi.get('cat_rank', '—')}/{fi.get('cat_n', '—')}" if fi.get('cat_rank') is not None else '—')}
                {row('板块资金流', f"{fi.get('cat_flow', '—'):+.2f} 亿" if fi.get('cat_flow') is not None else '—')}
                {row('资讯偏置', f"{res.get('news_bias', 0):+.3f}（匹配 {news_an.get('matched', 0)} 条，偏多 {news_an.get('bull', 0)} / 偏空 {news_an.get('bear', 0)}）")}
            </table>
            {'<div style="margin-top:10px;border-top:1px solid #2a2e3a;padding-top:8px;"><b>相关资讯：</b></div>' + news_html if news_html else ''}
        </div>
        """
        return html

    # ---- 主题切换 ----
    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        super().set_theme(t)
        # M4-05：重绘构建期主题色 inline 样式（消除切主题后停留在旧配色）
        self._style_static()
        for attr in ("chart", "macd", "kdj", "rsi", "reliability_chart", "prob_band"):
            c = getattr(self, attr, None)
            if c is not None and hasattr(c, "set_theme"):
                c.set_theme(t)
        # M3-10：占位行的标灰色随主题走，切换主题后须重刷一次
        try:
            self._refresh_model_cards()
        except Exception:  # noqa: BLE001
            pass
        # M3-13：指示灯的红/绿/灰取自当前主题调色板，切换主题后必须重刷
        try:
            self._refresh_drift_light()
        except Exception:  # noqa: BLE001
            pass
        # M4-05：选品排行表（评分/涨跌/AI方向着色）随主题重渲染（用缓存结果）
        if self._results:
            try:
                self._refresh_screen_table()
            except Exception:  # noqa: BLE001
                pass

    # ----------------------------- M3-10 模型状态 -----------------------------
    def _on_left_tab_changed(self, idx: int) -> None:
        """切到「🧩 模型状态」页时惰性刷新一次。"""
        if idx != getattr(self, "_mc_tab_index", -1):
            return
        if getattr(self, "_mc_cards", None):
            return          # 已刷新过，等用户手动点「刷新」或下次预测
        try:
            self._refresh_model_cards()
        except Exception:  # noqa: BLE001
            pass

    def _refresh_model_cards(self) -> None:
        """刷新「🧩 模型状态」面板。

        每次都**实时探测**可选依赖（torch / sklearn / arch），因此装上或卸载依赖后
        无需重启即可看到状态变化。占位实现（is_stub）整行标灰。
        """
        try:
            from ..ai.model_card import (collect_model_cards, cards_to_rows,
                                         format_cards_text)
        except Exception as e:  # noqa: BLE001
            logger.warning("模型卡片模块不可用：%s", e)
            return
        # 注意：本页共享的 predictor 是 `self._predictor`（延迟初始化），
        # 不是 `self.predictor`（后者只是文档注释里的旧称）。
        pred = getattr(self, "_predictor", None)
        df = getattr(self, "_last_train_df", None)
        ext = getattr(pred, "external_model", None)
        try:
            cards = collect_model_cards(predictor=pred, df=df, external_model=ext)
        except Exception as e:  # noqa: BLE001
            logger.warning("采集模型卡片失败：%s", e)
            return
        self._mc_cards = cards
        rows = cards_to_rows(cards)
        tbl = getattr(self, "mc_tbl", None)
        if tbl is None:
            return
        tbl.setRowCount(len(rows))
        muted = QColor(pal()["sub"])
        normal = QColor(pal()["text"])
        for i, (card, row) in enumerate(zip(cards, rows)):
            for j, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                # 占位实现 → 整行标灰（随主题色刷新，不用 inline stylesheet）
                item.setForeground(muted if card.is_stub else normal)
                tbl.setItem(i, j, item)
        n_stub = sum(1 for c in cards if c.is_stub)
        n_on = sum(1 for c in cards if c.enabled)
        self.mc_summary.setText(
            f"共 {len(cards)} 个候选模型：{n_on} 个启用，{n_stub} 个占位实现（灰字）"
            + ("　·　训练区间 " + cards[0].train_range
               if cards and cards[0].train_range else ""))
        logger.info("模型状态面板已刷新：\n%s", format_cards_text(cards))
        # 模型状态刷新时顺带更新漂移指示灯（同属「模型健康度」）
        self._refresh_drift_light()

    # ----------------------------- M3-13 模型漂移指示灯 -----------------------------
    def _refresh_drift_light(self) -> None:
        """刷新「模型漂移」指示灯（绿 ok / 红 drift / 灰 no_data）。

        数据来源：`store.daily_hit_rates` 的按日命中率序列 vs 训练期（窗口前）基准。
        任何异常都降级为灰色「未检测」，绝不因漂移检测失败影响主流程。
        """
        light = getattr(self, "drift_light", None)
        text = getattr(self, "drift_text", None)
        if light is None or text is None:
            return
        p = pal()
        sym = getattr(self, "cur_symbol", "") or ""
        # 颜色语义：红=告警（建议重训）、绿=正常、灰=样本不足/未检测
        c_drift, c_ok, c_na = p["up"], p["down"], p["sub"]
        try:
            from ..ai.drift import detect_from_store
            res = detect_from_store(self.store, sym)
        except Exception as e:  # noqa: BLE001
            logger.warning("漂移指示灯刷新失败（%s）：%s", sym, e)
            light.setStyleSheet(f"color:{c_na};font-size:16px;")
            text.setText(f"模型漂移：{sym} 未检测（{e}）")
            return
        level = str(res.get("level") or "no_data")
        score = float(res.get("drift_score") or 0.0)
        if level == "drift":
            light.setStyleSheet(f"color:{c_drift};font-size:16px;")
            text.setText(
                f"<b style='color:{c_drift}'>模型漂移 {score:.2f}</b>　"
                f"近期命中率 {float(res.get('window_mean') or 0):.2f} "
                f"vs 训练期 {float(res.get('baseline_mean') or 0):.2f}　"
                f"→ 建议重训")
        elif level == "ok":
            light.setStyleSheet(f"color:{c_ok};font-size:16px;")
            text.setText(
                f"模型漂移 {score:.2f}（正常）　近 {int(res.get('n_days') or 0)} 天"
                f"命中率 {float(res.get('window_mean') or 0):.2f} "
                f"vs 训练期 {float(res.get('baseline_mean') or 0):.2f}")
        else:
            light.setStyleSheet(f"color:{c_na};font-size:16px;")
            text.setText(f"模型漂移：{sym} {res.get('message') or '样本不足，暂不判定'}")