"""行情全景 · 统一市场监控总览页。

将原「行情全景（实时行情）」与「市场全景（强弱/量能/资金流）」合并为
一站式的期货市场全景视图，并新增「财经资讯 + AI 智能解读」板块：

  - 实时行情：K 线图 + 盘口快照（最新价/涨跌/幅度/成交量/持仓量/资金流）+ 全市场速览表；
  - 市场全局：涨跌家数 / 市场广度 / 资金净流入 / 平均涨跌 / 领涨领跌板块 / 温度计 KPI，
             板块强度榜、涨跌分布与温度计；
  - 基本面关键指标：持仓异动（全市场持仓量变化）、供需 / 库存信号（由财经资讯 AI 研判得出）；
  - 榜单：领涨榜 / 领跌榜 / 资金流向榜 / 板块明细；
  - 财经资讯 + AI 解读：并发爬取 11 个财经资讯源（财联社 / 东方财富 / 和讯 / 同花顺 /
             华尔街见闻 / 金十 / 新浪财经 / 期货日报 / 中证网 / 证券时报 / 凤凰财经），
             经 AI 模型与规则引擎做情绪 / 供需 / 趋势研判，并基于【可信度加权偏置 +
             跨源一致性 + 信源覆盖度】输出综合置信度、趋势、风险、关注建议、
             关键事件、活跃品种与可操作洞察。

数据依赖：MarketDataManager（行情中枢）与 AnalysisStore（存储）；新闻来自 news_feed。
"""

from __future__ import annotations

import datetime as dt
import time
import os
import json
from typing import Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtProperty, QPropertyAnimation
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QScrollArea, QSplitter, QAbstractItemView, QListWidget, QListWidgetItem,
    QLineEdit, QTabWidget,
)

from .widgets import (
    PageHeader, MetricChip, ConfidenceBar, prepare_table,
    color_pnl, pal, ToolBar, THEME, SectionHeader, StatusTile,
)
from .chart_widget import PriceChart
from .pages import BasePage, symbol_code, symbol_label, PERIODS, PERIOD_LABEL, df_to_bars
from ..indicators.tech import add_indicators
from ..ai import news_feed


def _level_weight(level) -> float:
    """新闻重要度权重（与 news_feed 保持一致）。"""
    try:
        lv = str(level or "").upper()
    except Exception:
        lv = ""
    if lv in ("A", "3"):
        return 1.5
    if lv in ("B", "2"):
        return 1.0
    if lv in ("C", "1"):
        return 0.6
    return 0.8


def _fmt_yi(v: float) -> str:
    """把以「亿」为单位的数值格式化为易读形式（超万亿自动换算）。"""
    a = abs(v)
    if a >= 10000:
        return f"{v / 10000:+.2f}万亿"
    if a >= 100:
        return f"{v:+.0f}亿"
    return f"{v:+.1f}亿"


def _news_overall_bias(news: dict) -> float:
    """全市场资讯整体情绪偏置（时间衰减加权，∈[-1,1]）。"""
    items = (news or {}).get("items", [])
    if not items:
        return 0.0
    now = time.time()
    half_life = 24 * 3600.0
    wpos = wneg = 0.0
    for it in items:
        s = float(it.get("sentiment", 0))
        w = _level_weight(it.get("level"))
        ctime = it.get("ctime") or 0
        if ctime:
            age = max(0.0, now - float(ctime))
            w *= (0.3 + 0.7 * (0.5 ** (age / half_life)))
        if s > 0:
            wpos += w * s
        elif s < 0:
            wneg += -w * s
    return (wpos - wneg) / (wpos + wneg) if (wpos + wneg) else 0.0


class MarketOverviewPage(BasePage):
    """统一的期货市场全景视图。"""

    def __init__(self, mdm, store, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "market"
        dft = symbol_code(mdm.universe[0])
        if session is not None:
            self.cur_symbol, self.cur_period = session.get_page_selection(
                "market", dft, "D")
        else:
            self.cur_symbol, self.cur_period = dft, "D"
        self.cur_cat = "全部"
        self._live = False
        self._news = None          # 最近一次抓取的全市场资讯
        self._news_autoloaded = False  # 页面首次显示时自动拉取一次
        self._pano_lazy = False    # 首次 showEvent 时延迟加载全景
        self._ai_analysis = None   # 最近一次 AI 综合研判（市场级）
        self._tech = None          # 最近一次技术面研判（当前品种级）
        self._market_ctx = {}      # 市场全局上下文（强弱/涨跌家数/资金/情绪）
        self._news_sent = (0, 0, 0)  # 资讯情绪分布 (bull, bear, neutral)
        self._sd_rows = []         # 最近一次供需信号行（主题切换时重建列表用）
        self.status_tiles = []     # 实时行情四状态灯（强弱/涨跌家数/资金/情绪）
        # 自选预警：持久化到 data/watchlist.json（与 store 同目录）
        self._wl_file = (os.path.join(os.path.dirname(self.store.path), "watchlist.json")
                         if self.store else os.path.join("data", "watchlist.json"))
        self._watchlist = []
        self._wl_load()
        self._build()

    # ==================================================================
    # 构建
    # ==================================================================
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "行情全景",
            "全市场实时行情 · 板块强弱轮动 · 持仓 / 供需基本面 · 财经资讯 AI 智能解读 —— 一站式期货市场全景"))

        # ---- 控制条 ----
        ctl = QHBoxLayout()
        self.sym_cb = QComboBox(); self.sym_cb.setMinimumWidth(170)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        self.sym_cb.setCurrentIndex(max(0, self.sym_cb.findData(self.cur_symbol)))
        self.sym_cb.currentIndexChanged.connect(self._on_symbol)
        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(self._on_period)
        self.cat_cb = QComboBox()
        cats = ["全部"] + sorted({r[2] for r in self.mdm.universe})
        for c in cats:
            self.cat_cb.addItem(c)
        self.cat_cb.setCurrentIndex(max(0, self.cat_cb.findData(self.cur_cat)))
        self.cat_cb.currentIndexChanged.connect(self._on_cat)
        self.live_btn = QPushButton("启动实时")
        self.live_btn.setObjectName("secondary")
        self.live_btn.clicked.connect(self._toggle_live)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(lambda: self._refresh_all())
        self.news_btn = QPushButton("AI 资讯解读")
        self.news_btn.setObjectName("primary")
        self.news_btn.clicked.connect(self._run_news)
        ctl.addWidget(QLabel("合约")); ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("周期")); ctl.addWidget(self.per_cb)
        ctl.addWidget(QLabel("板块")); ctl.addWidget(self.cat_cb)
        ctl.addWidget(self.live_btn)
        ctl.addWidget(self.refresh_btn)
        ctl.addWidget(self.news_btn)
        ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        # ---- 双栏仪表盘：左=数据区，右=财经资讯 + AI 智能解读（常驻宽栏）----
        # 两栏各自独立滚动：浏览行情数据时，右侧 AI 研判始终可见。
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(6)

        # 左栏：实时行情 / 市场全局 / 基本面 / 榜单（独立滚动）
        left = QScrollArea()
        left.setWidgetResizable(True)
        lwid = QWidget()
        lcol = QVBoxLayout(lwid)
        lcol.setContentsMargins(2, 2, 2, 2)
        lcol.setSpacing(10)
        lcol.addWidget(self._build_realtime())
        lcol.addWidget(self._build_market_global())
        lcol.addWidget(self._build_fundamentals())
        lcol.addWidget(self._build_ranks())
        lcol.addWidget(self._build_watchlist())
        lcol.addStretch(1)
        left.setWidget(lwid)
        split.addWidget(left)

        # 右栏：财经资讯 + AI 智能解读（常驻醒目宽栏，独立滚动）
        right = QScrollArea()
        right.setWidgetResizable(True)
        rwid = QWidget()
        rcol = QVBoxLayout(rwid)
        rcol.setContentsMargins(2, 2, 2, 2)
        rcol.setSpacing(8)
        rcol.addWidget(self._build_news(), 1)  # 给 news 一个 stretch，让图表随窗口拉伸
        right.setWidget(rwid)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------
    # 区块标题栏（强调色 + 粗体）助手
    # ------------------------------------------------------------------
    def _section_header(self, title, accent="#3b82f6", badge=None):
        """带强调色竖条 + 粗体标题的区块标题栏，提升信息层级与扫描效率。

        现复用共享组件 widgets.SectionHeader（强调色竖条 + 粗体标题 + 可选
        徽标），与全应用视觉语言统一；主题色由 BasePage.set_theme 递归下发。
        """
        return SectionHeader(title, accent, badge, theme=self._theme)

    # ------------------------------------------------------------------
    # 区块一：实时行情（盘口快照 + 市场状态 + 全市场速览）
    # ------------------------------------------------------------------
    def _build_realtime(self) -> QFrame:
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 8, 10, 8); bl.setSpacing(10)
        bl.addWidget(self._section_header(
            "实时行情（盘口快照 · 市场状态）", "#3b82f6"))

        # 盘口快照（6 指标卡，按涨跌着色 + ▲▼ 箭头）
        self.chips = {
            "last": MetricChip("最新价", "--"),
            "chg": MetricChip("涨跌", "--"),
            "pct": MetricChip("涨跌幅", "--"),
            "vol": MetricChip("成交量", "--"),
            "oi": MetricChip("持仓量", "--"),
            "fund": MetricChip("资金流(亿)", "--"),
        }
        # 悬停提示：解释每个指标含义，增强交互信息量
        self.chips["last"].setToolTip("当前最新成交价（按涨跌着色）")
        self.chips["chg"].setToolTip("相对昨日收盘的涨跌点数（▲涨 / ▼跌）")
        self.chips["pct"].setToolTip("相对昨日收盘的涨跌幅百分比")
        self.chips["vol"].setToolTip("最新 K 线成交量（手）")
        self.chips["oi"].setToolTip("最新 K 线持仓量（未平仓合约数，反映资金关注度）")
        self.chips["fund"].setToolTip("近期 20 根 K 线资金流代理（亿元，正为净流入）")
        cstrip = QHBoxLayout()
        for c in self.chips.values():
            cstrip.addWidget(c, 1)
        bl.addLayout(cstrip)

        # 实时更新时间戳（脉冲式高亮，提示数据活跃度）
        self.quote_time = QLabel("行情更新：—")
        self.quote_time.setObjectName("quote-time")
        bl.addWidget(self.quote_time)

        # 市场状态总览：四个状态灯（强弱 / 涨跌家数 / 资金 / 情绪），
        # 以颜色 + 图标 + 脉冲动画直观反映行情好坏，无需看 K 线即可一目了然。
        bl.addWidget(self._section_header(
            "市场状态总览（强弱 · 涨跌家数 · 资金 · 情绪）", "#8b5cf6"))
        strip = QHBoxLayout(); strip.setSpacing(10)
        self.tile_strength = StatusTile("市场强弱", self._theme)
        self.tile_adv = StatusTile("涨跌家数", self._theme)
        self.tile_fund = StatusTile("资金流向", self._theme)
        self.tile_sent = StatusTile("市场情绪", self._theme)
        for t in (self.tile_strength, self.tile_adv, self.tile_fund, self.tile_sent):
            self.status_tiles.append(t)
            strip.addWidget(t, 1)
        bl.addLayout(strip)

        # —— 全市场速览：单独占据一整行（不再与 K 线并排）——
        bl.addWidget(self._section_header(
            "全市场速览（按涨跌幅排序 · 双击切换合约）", "#0ea5e9"))
        self.watch = QTableWidget(0, 6)
        self.watch.setHorizontalHeaderLabels(
            ["合约", "最新价", "涨跌幅%", "量比", "持仓变%", "资金流(亿)"])
        # 列宽策略：合约列给足最小宽度（避免名称被截断），其余列等宽拉伸填满整行
        whdr = self.watch.horizontalHeader()
        whdr.setMinimumSectionSize(96)
        whdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        whdr.setStretchLastSection(True)
        self.watch.setMinimumHeight(240)            # 固定高度 + 内部垂直滚动，保证整行完整呈现
        self.watch.setWordWrap(False)
        self.watch.setTextElideMode(Qt.TextElideMode.ElideNone)  # 不省略，字段完整展示
        self.watch.itemDoubleClicked.connect(self._on_pick)
        bl.addWidget(self.watch)
        return box

    # ------------------------------------------------------------------
    # 区块二：市场全局（KPI + 板块强度 + 涨跌分布 / 温度计）
    # ------------------------------------------------------------------
    def _mk_card(self, label):
        card = QFrame(); card.setObjectName("kpi-card")
        cv = QVBoxLayout(card); cv.setContentsMargins(10, 8, 10, 8); cv.setSpacing(2)
        v = QLabel("—"); v.setObjectName("kpi-val")
        l = QLabel(label); l.setObjectName("kpi-lbl")
        cv.addWidget(v); cv.addWidget(l)
        card._val = v
        return card

    def _set_card(self, key, text, color=""):
        c = self._kpi_cards.get(key)
        if not c:
            return
        c._val.setText(text)
        c._val.setStyleSheet("color:%s;font-size:17px;font-weight:bold;" %
                             (color or pal()["text"]))

    def _style_cards(self):
        p = pal()
        for c in self._kpi_cards.values():
            c.setStyleSheet(
                "QFrame#kpi-card{background:%s;border:1px solid %s;border-radius:10px;}"
                % (p["card"], p["border"]))

    def _build_market_global(self) -> QFrame:
        self._kpi_cards = {}  # 确保在首次构建时初始化
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 8, 10, 8); bl.setSpacing(10)
        bl.addWidget(self._section_header(
            "市场全局概览（涨跌家数 · 广度 · 资金 · 温度计）", "#0ea5e9"))

        # KPI 卡片：两行自动换行布局（第一行 6 个，第二行 3 个）
        self._kpi = QFrame(); self._kpi.setObjectName("kpi-panel")
        kpi_tips = {
            "up": "当前上涨的品种数量（基准：全市场全部品种）",
            "down": "当前下跌的品种数量",
            "flat": "涨跌幅为 0 的平盘品种数量",
            "breadth": "上涨家数占比 = 上涨 / 总数；>50% 偏多，<40% 偏空",
            "flow": "全市场主力资金净流入合计（亿元，正为净流入）",
            "avg": "全部品种涨跌幅的算术平均（反映整体强度）",
            "lead": "平均涨跌幅最高的板块（资金/情绪最强）",
            "lag": "平均涨跌幅最低的板块（资金/情绪最弱）",
            "temp": "市场温度计：由广度推导的热度（偏热 / 中性 / 偏冷）",
        }
        kpi_keys = [("up", "上涨家数"), ("down", "下跌家数"), ("flat", "平盘"),
                    ("breadth", "市场广度"), ("flow", "资金净流入"), ("avg", "平均涨跌"),
                    ("lead", "领涨板块"), ("lag", "领跌板块"), ("temp", "市场温度计")]
        kpi_wrap = QVBoxLayout(self._kpi); kpi_wrap.setContentsMargins(0, 0, 0, 0); kpi_wrap.setSpacing(6)
        # 第一行 6 个卡片
        row1 = QHBoxLayout(); row1.setSpacing(8)
        # 第二行 3 个卡片（居中）
        row2 = QHBoxLayout(); row2.setSpacing(8)
        for i, (key, label) in enumerate(kpi_keys):
            card = self._mk_card(label)
            card.setToolTip(kpi_tips.get(key, ""))
            self._kpi_cards[key] = card
            if i < 6:
                row1.addWidget(card)
            else:
                row2.addWidget(card)
        kpi_wrap.addLayout(row1)
        kpi_wrap.addLayout(row2)
        bl.addWidget(self._kpi)
        self._style_cards()

        charts = QHBoxLayout(); charts.setSpacing(10)
        lc = QWidget(); lcv = QVBoxLayout(lc); lcv.setContentsMargins(0, 0, 0, 0); lcv.setSpacing(4)
        lcv.addWidget(QLabel("板块强度榜（各板块成分品种平均涨跌幅，越长越强）"))
        self.bar = PriceChart(); self.bar.setMinimumHeight(200)
        lcv.addWidget(self.bar)
        rc = QWidget(); rcv = QVBoxLayout(rc); rcv.setContentsMargins(0, 0, 0, 0); rcv.setSpacing(6)
        rcv.addWidget(QLabel("全市场涨跌分布（红涨 / 绿跌 / 灰平，宽度=占比）"))
        # 占比式三段涨跌分布条（宽度按家数比例，悬停看明细）
        self.breadth_gauge = QWidget(); self.breadth_gauge.setMinimumHeight(22)
        self.breadth_gauge.setToolTip("红=上涨 / 灰=平盘 / 绿=下跌，各段宽度与家数占比一致")
        bg_lay = QHBoxLayout(self.breadth_gauge); bg_lay.setContentsMargins(0, 0, 0, 0); bg_lay.setSpacing(2)
        self._bg_up = QLabel(); self._bg_up.setObjectName("bg-up"); self._bg_up.setMinimumWidth(1)
        self._bg_flat = QLabel(); self._bg_flat.setObjectName("bg-flat"); self._bg_flat.setMinimumWidth(1)
        self._bg_down = QLabel(); self._bg_down.setObjectName("bg-down"); self._bg_down.setMinimumWidth(1)
        for w in (self._bg_up, self._bg_flat, self._bg_down):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter); w.setStyleSheet("color:#fff;font-size:11px;")
        bg_lay.addWidget(self._bg_up, 1); bg_lay.addWidget(self._bg_flat, 1); bg_lay.addWidget(self._bg_down, 1)
        rcv.addWidget(self.breadth_gauge)
        # 明细文字（家数 + 百分比）
        self.breadth_lbl = QLabel(); self.breadth_lbl.setWordWrap(True); self.breadth_lbl.setMinimumHeight(40)
        rcv.addWidget(self.breadth_lbl)
        rcv.addWidget(QLabel("市场温度计（广度越高越「热」）"))
        self.temp_bar = ConfidenceBar(0.5); self.temp_bar.setMinimumHeight(18)
        rcv.addWidget(self.temp_bar)
        self.temp_lbl = QLabel("—"); rcv.addWidget(self.temp_lbl)
        charts.addWidget(lc, 2); charts.addWidget(rc, 1)
        bl.addLayout(charts)
        return box

    # ------------------------------------------------------------------
    # 区块三：基本面关键指标（持仓异动 + 供需 / 库存信号）
    # ------------------------------------------------------------------
    def _build_fundamentals(self) -> QFrame:
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 8, 10, 8); bl.setSpacing(8)
        bl.addWidget(self._section_header(
            "基本面关键指标（持仓量变化 · 供需 / 库存信号）", "#f59e0b"))

        bot = QHBoxLayout(); bot.setSpacing(10)
        # 左：持仓异动
        b1 = QWidget(); b1l = QVBoxLayout(b1); b1l.setContentsMargins(0, 0, 0, 0); b1l.setSpacing(4)
        b1l.addWidget(QLabel("持仓异动（全市场持仓量变化 Top 10，%）"))
        self.oi_tbl = QTableWidget(0, 3)
        self.oi_tbl.setHorizontalHeaderLabels(["合约", "板块", "持仓变%"])
        self.oi_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        b1l.addWidget(self.oi_tbl)
        # 右：供需 / 库存信号
        b2 = QWidget(); b2l = QVBoxLayout(b2); b2l.setContentsMargins(0, 0, 0, 0); b2l.setSpacing(4)
        b2l.addWidget(QLabel("供需 / 库存信号（财经资讯 AI 研判，页面打开自动生成）"))
        self.sd_tbl = QTableWidget(0, 4)
        self.sd_tbl.setHorizontalHeaderLabels(["板块", "信号强度", "研判", "依据样本"])
        self.sd_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        b2l.addWidget(self.sd_tbl)
        bot.addWidget(b1, 1); bot.addWidget(b2, 1)
        bl.addLayout(bot)
        return box

    # ------------------------------------------------------------------
    # 区块四：榜单（领涨 / 领跌 / 资金流 / 板块明细）
    # ------------------------------------------------------------------
    def _build_ranks(self) -> QFrame:
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 8, 10, 8); bl.setSpacing(10)
        bl.addWidget(self._section_header(
            "榜单（领涨 · 领跌 · 资金流向 · 板块明细）", "#10b981"))

        gain = QHBoxLayout(); gain.setSpacing(10)
        g1 = QWidget(); g1l = QVBoxLayout(g1); g1l.setContentsMargins(0, 0, 0, 0); g1l.setSpacing(4)
        g1l.addWidget(QLabel("领涨榜（涨跌幅 Top 8）"))
        self.gain_tbl = QTableWidget(0, 3)
        self.gain_tbl.setHorizontalHeaderLabels(["合约", "板块", "涨跌幅%"])
        self.gain_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        g1l.addWidget(self.gain_tbl)
        g2 = QWidget(); g2l = QVBoxLayout(g2); g2l.setContentsMargins(0, 0, 0, 0); g2l.setSpacing(4)
        g2l.addWidget(QLabel("领跌榜（涨跌幅 Bottom 8）"))
        self.lag_tbl = QTableWidget(0, 3)
        self.lag_tbl.setHorizontalHeaderLabels(["合约", "板块", "涨跌幅%"])
        self.lag_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        g2l.addWidget(self.lag_tbl)
        gain.addWidget(g1, 1); gain.addWidget(g2, 1)
        bl.addLayout(gain)

        bot = QHBoxLayout(); bot.setSpacing(10)
        b1 = QWidget(); b1l = QVBoxLayout(b1); b1l.setContentsMargins(0, 0, 0, 0); b1l.setSpacing(4)
        b1l.addWidget(QLabel("资金流向榜（净流入 Top 8，亿）"))
        self.flow_tbl = QTableWidget(0, 3)
        self.flow_tbl.setHorizontalHeaderLabels(["合约", "板块", "资金流(亿)"])
        self.flow_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        b1l.addWidget(self.flow_tbl)
        b2 = QWidget(); b2l = QVBoxLayout(b2); b2l.setContentsMargins(0, 0, 0, 0); b2l.setSpacing(4)
        b2l.addWidget(QLabel("板块明细（强弱 / 资金 / 品种数）"))
        self.sec_tbl = QTableWidget(0, 4)
        self.sec_tbl.setHorizontalHeaderLabels(["板块", "平均涨跌%", "资金流(亿)", "品种数"])
        self.sec_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        b2l.addWidget(self.sec_tbl)
        bot.addWidget(b1, 1); bot.addWidget(b2, 1)
        bl.addLayout(bot)
        return box

    # ------------------------------------------------------------------
    # 区块四·五：自选预警（价格提醒）
    # ------------------------------------------------------------------
    def _build_watchlist(self) -> QFrame:
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 8, 10, 8); bl.setSpacing(8)
        self._wl_header = self._section_header("自选预警（价格提醒）", "#14b8a6", badge="0 自选")
        bl.addWidget(self._wl_header)

        add = QHBoxLayout(); add.setSpacing(6)
        self.wl_upper = QLineEdit(); self.wl_upper.setFixedWidth(78)
        self.wl_upper.setPlaceholderText("上限价")
        self.wl_lower = QLineEdit(); self.wl_lower.setFixedWidth(78)
        self.wl_lower.setPlaceholderText("下限价")
        self.wl_add = QPushButton("加自选(当前合约)"); self.wl_add.setObjectName("secondary")
        self.wl_add.clicked.connect(self._add_watch)
        self.wl_clr = QPushButton("清空触发"); self.wl_clr.setObjectName("secondary")
        self.wl_clr.clicked.connect(self._clear_alerts)
        add.addWidget(QLabel("上限")); add.addWidget(self.wl_upper)
        add.addWidget(QLabel("下限")); add.addWidget(self.wl_lower)
        add.addWidget(self.wl_add); add.addWidget(self.wl_clr)
        add.addStretch(1)
        bl.addLayout(add)

        bl.addWidget(QLabel("自选标的（双击行切换当前合约；涨/跌破阈值即触发预警高亮）"))
        self.wl_tbl = QTableWidget(0, 7)
        self.wl_tbl.setHorizontalHeaderLabels(
            ["合约", "最新价", "涨跌幅%", "上限", "下限", "状态", "移除"])
        self.wl_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.wl_tbl.itemDoubleClicked.connect(self._on_wl_pick)
        bl.addWidget(self.wl_tbl)
        return box

    def _wl_load(self):
        try:
            with open(self._wl_file, "r", encoding="utf-8") as f:
                self._watchlist = json.load(f) or []
        except Exception:
            self._watchlist = []

    def _wl_save(self):
        try:
            os.makedirs(os.path.dirname(self._wl_file), exist_ok=True)
            with open(self._wl_file, "w", encoding="utf-8") as f:
                json.dump(self._watchlist, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def _parse_price(s: str):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _add_watch(self):
        """把当前合约加入自选；未填阈值时默认按当前价 ±5% 生成上下限。"""
        sym = self.cur_symbol
        up = self._parse_price(self.wl_upper.text())
        lo = self._parse_price(self.wl_lower.text())
        if up is None and lo is None:
            q = self.mdm.get_quote(sym, self.cur_period)
            if q:
                last = float(q["last"])
                up = round(last * 1.05, 2)
                lo = round(last * 0.95, 2)
        for w in self._watchlist:
            if w["symbol"] == sym:
                w["upper"], w["lower"], w["triggered"], w["at"] = up, lo, None, None
                break
        else:
            self._watchlist.append(
                {"symbol": sym, "upper": up, "lower": lo,
                 "triggered": None, "at": None})
        self.wl_upper.clear(); self.wl_lower.clear()
        self._wl_save(); self._refresh_watchlist()

    def _remove_watch(self, row: int):
        if 0 <= row < len(self._watchlist):
            self._watchlist.pop(row)
            self._wl_save(); self._refresh_watchlist()

    def _clear_alerts(self):
        for w in self._watchlist:
            w["triggered"], w["at"] = None, None
        self._wl_save(); self._refresh_watchlist()

    def _refresh_watchlist(self):
        items = self._watchlist
        self.wl_tbl.setRowCount(len(items))
        alerts = 0
        p = pal()
        alert_bg = QColor(p["up"]); alert_bg.setAlpha(55)
        for i, w in enumerate(items):
            sym = w["symbol"]
            q = self.mdm.get_quote(sym, self.cur_period)
            last = float(q["last"]) if q else None
            chg = float(q["chg_pct"]) if q else None
            name = sym
            for r in self.mdm.universe:
                if symbol_code(r) == sym:
                    name = r[1]
                    break
            self.wl_tbl.setItem(i, 0, QTableWidgetItem(name))
            self.wl_tbl.setItem(
                i, 1, QTableWidgetItem(f"{last:,.1f}" if last is not None else "--"))
            cp = QTableWidgetItem(f"{chg:+,.2f}" if chg is not None else "--")
            if chg is not None:
                color_pnl(cp, chg)
            self.wl_tbl.setItem(i, 2, cp)
            self.wl_tbl.setItem(
                i, 3, QTableWidgetItem(f"{w['upper']:,.1f}" if w["upper"] is not None else "--"))
            self.wl_tbl.setItem(
                i, 4, QTableWidgetItem(f"{w['lower']:,.1f}" if w["lower"] is not None else "--"))
            status = "监控中"
            if last is not None:
                trig = None
                if w["upper"] is not None and last >= w["upper"]:
                    trig = "上破"
                elif w["lower"] is not None and last <= w["lower"]:
                    trig = "下破"
                if trig:
                    if w["triggered"] != trig:
                        w["triggered"] = trig
                        w["at"] = dt.datetime.now().strftime("%H:%M:%S")
                    status = f"{trig}预警 {w['at']}"
                    alerts += 1
                    for c in range(7):
                        it = self.wl_tbl.item(i, c)
                        if it is not None:
                            it.setBackground(alert_bg)
            else:
                status = "无行情"
            self.wl_tbl.setItem(i, 5, QTableWidgetItem(status))
            rm = QPushButton("移除"); rm.setObjectName("danger"); rm.setFixedSize(46, 22)
            rm.clicked.connect(lambda _, r=i: self._remove_watch(r))
            self.wl_tbl.setCellWidget(i, 6, rm)
        prepare_table(self.wl_tbl)
        self._wl_header.set_badge(f"{alerts} 预警" if alerts else f"{len(items)} 自选")

    def _on_wl_pick(self, item):
        row = item.row()
        if 0 <= row < len(self._watchlist):
            sym = self._watchlist[row]["symbol"]
            idx = self.sym_cb.findData(sym)
            if idx >= 0:
                self.sym_cb.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # 区块五：财经资讯 + AI 智能解读
    # ------------------------------------------------------------------
    def _build_news(self) -> QFrame:
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 8, 10, 8); bl.setSpacing(8)

        ctl = QHBoxLayout()
        ctl.addWidget(self._section_header("财经资讯 + AI智能解读", "#8b5cf6"))
        self.news_status = QLabel("页面打开自动生成 AI 研判；也可点击「AI 资讯解读」手动刷新")
        self.news_status.setObjectName("hint")
        ctl.addWidget(self.news_status, 1)
        bl.addLayout(ctl)

        # 资讯列表（上，限高，逐条展示核心含义）
        bl.addWidget(QLabel("最新市场动态（时间 · 来源 · 类别 · 核心含义 · 情绪）"))
        self.news_list = QListWidget()
        self.news_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.news_list.addItem(QListWidgetItem("资讯加载中…"))
        self.news_list.setMaximumHeight(280)
        bl.addWidget(self.news_list)

        # AI 研判：双 Tab 深度扩展（综合研判 + 技术面解读）
        self.ai_tabs = QTabWidget()
        self.ai_tabs.setObjectName("news-ai-tabs")
        self.ai_view = QTextEdit()        # Tab1：AI 综合研判（市场趋势 + 多空对比 + 预测）
        self.ai_view.setReadOnly(True)
        self.ai_view.setMinimumHeight(420)
        self.ai_view.setHtml(
            "<div style='font-size:13px;color:%s;line-height:1.5'>"
            "AI 综合研判将在页面打开后自动生成，请稍候…</div>" % pal()["sub"])
        self.tech_view = QTextEdit()      # Tab2：技术面解读（当前品种 均线/MACD/布林/支撑阻力）
        self.tech_view.setReadOnly(True)
        self.tech_view.setMinimumHeight(420)
        self.tech_view.setHtml(
            "<div style='font-size:13px;color:%s;line-height:1.5'>"
            "选择合约后将自动生成该品种的技术面解读，请稍候…</div>" % pal()["sub"])
        self.ai_tabs.addTab(self.ai_view, "🧠 AI 综合研判")
        self.ai_tabs.addTab(self.tech_view, "📐 技术面解读")
        bl.addWidget(self.ai_tabs, 1)
        return box

    # ==================================================================
    # 交互
    # ==================================================================
    def _on_symbol(self, i):
        self.cur_symbol = self.sym_cb.itemData(i)
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        self._refresh_quote()
        self._refresh_tech()

    def _on_period(self, i):
        self.cur_period = self.per_cb.itemData(i)
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        self._refresh_quote()
        self._refresh_pano()
        self._refresh_tech()

    def _on_cat(self, i):
        self.cur_cat = self.cat_cb.currentText()
        self._refresh_pano()

    def _toggle_live(self):
        if not self._live:
            self.mdm.start_live(self.cur_symbol, self.cur_period, 1000)
            self.mdm.bar_arrived.connect(self._on_live)
            self._live = True
            self.live_btn.setText("停止实时")
            self.live_btn.setObjectName("danger")
        else:
            self.mdm.stop_live(self.cur_symbol)
            try:
                self.mdm.bar_arrived.disconnect(self._on_live)
            except Exception:
                pass
            self._live = False
            self.live_btn.setText("启动实时")
            self.live_btn.setObjectName("secondary")
        self.live_btn.setStyleSheet("")

    def _on_live(self, bar):
        if bar.get("symbol") == self.cur_symbol:
            self._refresh_quote()

    def _refresh_all(self):
        self._refresh_quote()
        self._refresh_watch()
        self._refresh_pano()
        self._refresh_watchlist()

    # ------------------------------------------------------------------
    # 自动加载：页面首次显示（行情全景为默认首页，启动即触发）时，
    # 自动拉取一次多源财经资讯 + AI 研判 + 供需信号，无需手动点击。
    # ------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示：延迟加载全景（行情 + 速览 + 自选列表），避免构造期间阻塞主线程
        if not self._pano_lazy:
            self._pano_lazy = True
            QTimer.singleShot(100, self._refresh_all)
        if not self._news_autoloaded:
            self._news_autoloaded = True
            self.news_status.setText("正在自动获取全市场资讯与 AI 研判…")
            # 延迟 600ms，待布局稳定后再发起网络请求，避免首帧卡顿
            QTimer.singleShot(600, self._run_news)

    # ==================================================================
    # 数据加载
    # ==================================================================
    def _refresh_quote(self):
        """实时行情：盘口快照（按涨跌着色 + ▲▼ 箭头）。K 线图已移除，
        行情好坏改由上方四状态灯 + 盘口色彩直观呈现。"""
        q = self.mdm.get_quote(self.cur_symbol, self.cur_period)
        if not q:
            return
        upc = pal()["up"] if q["chg"] >= 0 else pal()["down"]
        arrow = "▲" if q["chg"] >= 0 else "▼"
        self.chips["last"].set_value(f"{q['last']:,.1f}", pal()["text"])
        self.chips["chg"].set_value(f"{arrow} {q['chg']:+,.1f}", upc)
        self.chips["pct"].set_value(f"{arrow} {q['chg_pct']:+,.2f}%", upc)
        self.chips["vol"].set_value(f"{q['volume']:,.0f}", pal()["sub"])
        self.chips["oi"].set_value(f"{q['open_interest']:,.0f}", pal()["sub"])
        self.chips["fund"].set_value(
            f"{q['fund_flow']:+,.2f}",
            pal()["up"] if q["fund_flow"] >= 0 else pal()["down"])
        # 更新时间戳（高亮提示数据已刷新）
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self.quote_time.setText(f"行情更新：{ts} · {self.cur_symbol}")
        self.quote_time.setStyleSheet(
            f"color:{pal()['accent']};font-size:11px;font-weight:bold;")

    def _refresh_watch(self):
        """全市场速览表（按涨跌幅排序）。"""
        pan = self.mdm.compute_panorama(self.cur_period)
        if pan is None or pan.empty:
            return
        # 受板块筛选影响
        pan = pan if self.cur_cat == "全部" else pan[pan["category"] == self.cur_cat]
        self.watch.setRowCount(len(pan))
        for i, (_, r) in enumerate(pan.iterrows()):
            self.watch.setItem(i, 0, QTableWidgetItem(r["name"]))
            self.watch.setItem(i, 1, QTableWidgetItem(f"{r['last']:,.1f}"))
            pct = QTableWidgetItem(f"{r['chg_pct']:+,.2f}")
            color_pnl(pct, r["chg_pct"])
            self.watch.setItem(i, 2, pct)
            self.watch.setItem(i, 3, QTableWidgetItem(f"{r['vol_ratio']:,.2f}"))
            oi = QTableWidgetItem(f"{r['oi_chg']:+,.2f}")
            color_pnl(oi, r["oi_chg"])
            self.watch.setItem(i, 4, oi)
            ff = QTableWidgetItem(f"{r['fund_flow']:+,.2f}")
            color_pnl(ff, r["fund_flow"])
            self.watch.setItem(i, 5, ff)
        prepare_table(self.watch)

    def _refresh_pano(self):
        """市场全局 + 持仓异动 + 榜单 + 板块明细。"""
        p = pal()
        pan_all = self.mdm.compute_panorama(self.cur_period)
        if pan_all is None or pan_all.empty:
            return
        pan = pan_all if self.cur_cat == "全部" else pan_all[pan_all["category"] == self.cur_cat]

        up = int((pan_all["chg_pct"] > 0).sum())
        down = int((pan_all["chg_pct"] < 0).sum())
        flat = int(len(pan_all) - up - down)
        total = len(pan_all)
        breadth = (up / total) if total else 0.0
        net_flow = float(pan_all["fund_flow"].sum())
        avg = float(pan_all["chg_pct"].mean())

        # KPI 英雄条
        self._set_card("up", str(up), pal()["up"])
        self._set_card("down", str(down), pal()["down"])
        self._set_card("flat", str(flat), pal()["sub"])
        self._set_card("breadth", f"{breadth*100:.0f}%",
                      f"{p['up']}" if breadth >= 0.5 else (f"{p['accent2']}" if breadth >= 0.4 else f"{p['down']}"))
        self._set_card("flow", f"{net_flow:+.1f}亿", f"{p['up']}" if net_flow >= 0 else f"{p['down']}")
        self._set_card("avg", f"{avg:+.2f}%", f"{p['up']}" if avg >= 0 else f"{p['down']}")
        grp = pan_all.groupby("category")["chg_pct"].mean().sort_values(ascending=False)
        lead = grp.index[0] if len(grp) else "—"
        lag = grp.index[-1] if len(grp) else "—"
        self._set_card("lead", lead, p["up"])
        self._set_card("lag", lag, p["down"])
        self.temp_bar.set_pct(breadth)
        temp = ("偏热" if breadth >= 0.55 else "中性偏暖" if breadth >= 0.45
                else "中性" if breadth >= 0.4 else "偏冷")
        self.temp_lbl.setText(f"广度 {breadth*100:.0f}% · {temp}")
        self.temp_lbl.setStyleSheet("color:%s;" % pal()["sub"])

        # 实时行情四状态灯（强弱 / 涨跌家数 / 资金）
        self._market_ctx = dict(up=up, down=down, flat=flat, total=total,
                                breadth=breadth, net_flow=net_flow, avg=avg,
                                lead=lead, lag=lag, temp=temp)
        if breadth >= 0.55:
            self.tile_strength.set_status("good", "普涨 ▲",
                                          f"上涨占比 {breadth*100:.0f}%，多头主导")
        elif breadth >= 0.45:
            self.tile_strength.set_status("neutral", "偏暖",
                                          f"上涨占比 {breadth*100:.0f}%，震荡偏强")
        elif breadth >= 0.4:
            self.tile_strength.set_status("neutral", "中性",
                                          f"上涨占比 {breadth*100:.0f}%，多空均衡")
        else:
            self.tile_strength.set_status("bad", "偏冷 ▼",
                                          f"上涨占比 {breadth*100:.0f}%，空头占优")
        a_level = "good" if up >= down else ("bad" if up < down else "neutral")
        self.tile_adv.set_status(a_level, f"{up}↑ / {down}↓",
                                 f"平盘 {flat} 家 · 共 {total} 个品种")
        f_level = "good" if net_flow >= 0 else "bad"
        self.tile_fund.set_status(
            f_level, _fmt_yi(net_flow),
            "全市场资金净流入" if net_flow >= 0 else "全市场资金净流出")

        # 涨跌分布（占比式三段条 + 明细）
        def pct(n):
            return (n / total * 100) if total else 0.0
        p = pal()
        # 三段条：按家数比例分配水平 stretch，段内显示百分比
        bg_lay = self.breadth_gauge.layout()
        bg_lay.setStretch(0, max(up, 1))
        bg_lay.setStretch(1, max(flat, 1))
        bg_lay.setStretch(2, max(down, 1))
        self._bg_up.setText(f"{pct(up):.0f}%")
        self._bg_flat.setText(f"{pct(flat):.0f}%")
        self._bg_down.setText(f"{pct(down):.0f}%")
        self._bg_up.setStyleSheet(f"background:{p['up']};color:{p['text']};font-size:11px;border-radius:3px;")
        self._bg_flat.setStyleSheet(f"background:{p['sub']};color:{p['bg']};font-size:11px;border-radius:3px;")
        self._bg_down.setStyleSheet(f"background:{p['down']};color:{p['text']};font-size:11px;border-radius:3px;")
        self.breadth_lbl.setText(
            f"<div style='font-size:12px;color:{p['sub']}'>"
            f"<span style='color:{p['up']}'>▲ 上涨 {up} 家</span> ｜ "
            f"<span style='color:{p['sub']}'>— 平盘 {flat} 家</span> ｜ "
            f"<span style='color:{p['down']}'>▼ 下跌 {down} 家</span> "
            f"（共 {total} 个品种，上涨占比 {pct(up):.0f}%）</div>")

        # 板块强度图
        agg = (pan_all.groupby("category")
                    .agg(mean_chg=("chg_pct", "mean"),
                         sum_flow=("fund_flow", "sum"),
                         count=("chg_pct", "count"))
                    .reset_index().sort_values("mean_chg", ascending=False))
        cats = agg["category"].tolist(); n = len(cats)
        xt = [(i / (n - 1) if n > 1 else 0.5, c) for i, c in enumerate(cats)]
        self.bar.set_data(
            series=[{"name": "平均涨跌幅%", "color": "#3b82f6",
                     "x": list(range(n)), "y": agg["mean_chg"].tolist()}],
            x_ticks=xt, title="板块强度（平均涨跌幅 %）")

        # 持仓异动（全市场，按 |oi_chg| 排序 Top 10）
        oi_sorted = pan_all.assign(abs_oi=pan_all["oi_chg"].abs()) \
            .sort_values("abs_oi", ascending=False).head(10)
        self.oi_tbl.setRowCount(len(oi_sorted))
        for i, (_, r) in enumerate(oi_sorted.iterrows()):
            self._set(self.oi_tbl, i, 0, r["name"])
            self._set(self.oi_tbl, i, 1, r["category"])
            v = self._set(self.oi_tbl, i, 2, f"{r['oi_chg']:+.2f}")
            color_pnl(v, r["oi_chg"])
        prepare_table(self.oi_tbl)

        # 板块明细
        self.sec_tbl.setRowCount(n)
        for i, (_, r) in enumerate(agg.iterrows()):
            self._set(self.sec_tbl, i, 0, r["category"])
            v = self._set(self.sec_tbl, i, 1, f"{r['mean_chg']:+.2f}")
            color_pnl(v, r["mean_chg"])
            f = self._set(self.sec_tbl, i, 2, f"{r['sum_flow']:+.2f}")
            color_pnl(f, r["sum_flow"])
            self._set(self.sec_tbl, i, 3, int(r["count"]))
        prepare_table(self.sec_tbl)

        # 领涨 / 领跌 / 资金流（受板块筛选影响）
        if pan.empty:
            return
        top = pan.sort_values("chg_pct", ascending=False).head(8)
        bot = pan.sort_values("chg_pct", ascending=True).head(8)
        fl = pan.sort_values("fund_flow", ascending=False).head(8)
        self.gain_tbl.setRowCount(len(top))
        for i, (_, r) in enumerate(top.iterrows()):
            self._set(self.gain_tbl, i, 0, r["name"])
            self._set(self.gain_tbl, i, 1, r["category"])
            v = self._set(self.gain_tbl, i, 2, f"{r['chg_pct']:+.2f}")
            color_pnl(v, r["chg_pct"])
        self.lag_tbl.setRowCount(len(bot))
        for i, (_, r) in enumerate(bot.iterrows()):
            self._set(self.lag_tbl, i, 0, r["name"])
            self._set(self.lag_tbl, i, 1, r["category"])
            v = self._set(self.lag_tbl, i, 2, f"{r['chg_pct']:+.2f}")
            color_pnl(v, r["chg_pct"])
        self.flow_tbl.setRowCount(len(fl))
        for i, (_, r) in enumerate(fl.iterrows()):
            self._set(self.flow_tbl, i, 0, r["name"])
            self._set(self.flow_tbl, i, 1, r["category"])
            v = self._set(self.flow_tbl, i, 2, f"{r['fund_flow']:+.2f}")
            color_pnl(v, r["fund_flow"])
        prepare_table(self.gain_tbl); prepare_table(self.lag_tbl); prepare_table(self.flow_tbl)

    # ---- 资讯 + AI 解读 ----
    def _run_news(self):
        if getattr(self, "_news_running", False):
            return
        self._news_running = True
        self.news_btn.setEnabled(False)
        self.news_btn.setText("解读中…")
        self.news_status.setText("正在并发爬取 11 个财经资讯源（财联社/东方财富/和讯/同花顺/"
                                  "华尔街见闻/金十/新浪财经/期货日报/中证网/证券时报/凤凰财经）…")

        def work():
            news = news_feed.fetch_all_news(limit=60)
            # 市场级 AI 研判
            bias = _news_overall_bias(news)
            p_up = max(0.05, min(0.95, 0.5 + 0.5 * bias))
            exp = round(bias * 3.0, 2)
            risk_label = "高" if abs(bias) > 0.4 else ("中" if abs(bias) > 0.15 else "低")
            res = {"p_up": p_up, "expected_return_pct": exp,
                   "risk": {"label": risk_label, "score": int(abs(bias) * 100)}}
            analysis = news_feed.ai_analyze_news(news, res, "期货市场", "全市场", mdm=self.mdm)
            # 当前品种技术面研判（与资讯偏置联动）
            tech = self._compute_technical(self.cur_symbol, self.cur_period, news_bias=bias)
            # 各板块供需 / 库存信号
            sd_rows = []
            for c in sorted({r[2] for r in self.mdm.universe}):
                b = news_feed.news_bias_for_symbol(c, c, c, news)
                sd_rows.append((c, b["bias"], b["matched"], b["samples"]))
            return news, analysis, sd_rows, tech

        def done(payload):
            news, analysis, sd_rows, tech = payload
            self._news = news
            self._fill_news(news, analysis, sd_rows, tech)
            # 资讯情绪分布 → 市场情绪状态灯
            bull = bear = neutral = 0
            for it in news.get("items", []):
                s = float(it.get("sentiment", 0))
                if s > 0.05:
                    bull += 1
                elif s < -0.05:
                    bear += 1
                else:
                    neutral += 1
            self._news_sent = (bull, bear, neutral)
            tot = bull + bear + neutral
            if tot:
                if bull >= bear:
                    lvl, val = "good", f"偏多 {bull}/{tot}"
                else:
                    lvl, val = "bad", f"偏空 {bear}/{tot}"
                tip = f"利好 {bull} · 利空 {bear} · 中性 {neutral}"
            else:
                lvl, val, tip = "neutral", "样本不足", ""
            self.tile_sent.set_status(lvl, val, tip)
            total = len(news.get("items", []))
            cov = news.get("source_coverage") or {}
            active = cov.get("active_sources", 0)
            tsrc = cov.get("total_sources", 0)
            conf = analysis.get("confidence")
            ts = dt.datetime.now().strftime("%H:%M:%S")
            conf_txt = f" · 综合置信度 {conf*100:.0f}%" if isinstance(conf, (int, float)) else ""
            self.news_status.setText(
                f"已更新 {ts} · 抓取 {total} 条 · 信源覆盖 {active}/{tsrc}{conf_txt} · AI 研判完成")
            self._restore_news_btn()

        def err(msg):
            self.news_status.setText(f"资讯获取失败：{msg}（将使用已有缓存或稍后重试）")
            self._restore_news_btn()

        self._run_worker(work, done, err)

    def _restore_news_btn(self):
        self._news_running = False
        self.news_btn.setEnabled(True)
        self.news_btn.setText("AI 资讯解读")

    def _fill_news(self, news, analysis, sd_rows, tech=None):
        self._sd_rows = sd_rows
        # 资讯列表（逐条自定义：时间 / 来源 / 类别 + 标题 + 核心含义 + 情绪标签）
        self.news_list.clear()
        items = news.get("items", [])
        p = pal()
        if not items:
            self.news_list.addItem(QListWidgetItem(
                "（暂无可读资讯；可再次点击「AI 资讯解读」）"))
        for it in items[:60]:
            self._add_news_row(it, p)

        # 保存并渲染（综合研判 + 技术面解读）
        self._ai_analysis = analysis
        self._tech = tech
        self._render_ai(analysis, tech)

        # 供需 / 库存信号表
        self.sd_tbl.setRowCount(len(sd_rows))
        for i, (c, bias, matched, samples) in enumerate(sd_rows):
            self._set(self.sd_tbl, i, 0, c)
            strength = self._set(self.sd_tbl, i, 1, f"{bias*100:+.0f}")
            color_pnl(strength, bias)
            if bias > 0.05:
                verdict = "供需偏紧 / 去库利多"
                vc = p["up"]
            elif bias < -0.05:
                verdict = "供需宽松 / 累库利空"
                vc = p["down"]
            else:
                verdict = "供需平衡"
                vc = pal()["sub"]
            self._set(self.sd_tbl, i, 2, verdict, vc)
            sample = (samples[0] if samples else "—")
            self._set(self.sd_tbl, i, 3, sample)
        prepare_table(self.sd_tbl)

    # ------------------------------------------------------------------
    # 资讯逐条渲染：时间 / 来源 / 类别徽标 + 标题 + 核心含义 + 情绪标签
    # ------------------------------------------------------------------
    def _news_core(self, it) -> str:
        """提炼新闻核心含义，帮助用户一眼看懂这条资讯到底在说什么。"""
        content = (it.get("content") or "").strip()
        s = float(it.get("sentiment", 0))
        title = (it.get("title") or "").strip()
        if content and len(content) >= 8:
            return content[:72]
        mood = "偏多" if s > 0.05 else ("偏空" if s < -0.05 else "中性")
        cat = it.get("category", "")
        return f"{title}（{cat}·{mood}）"

    def _add_news_row(self, it, p) -> None:
        s = float(it.get("sentiment", 0))
        col = p["up"] if s > 0.05 else (p["down"] if s < -0.05 else p["sub"])
        tag = "利好" if s > 0.05 else ("利空" if s < -0.05 else "中性")
        src = it.get("source", "")
        cat = it.get("category", "")
        title = (it.get("title") or it.get("content") or "（无标题）").strip()
        ts = (it.get("ctime") and dt.datetime.fromtimestamp(it.get("ctime")).strftime("%m-%d %H:%M")) or ""

        row = QFrame(); row.setObjectName("news-row")
        rv = QVBoxLayout(row); rv.setContentsMargins(8, 6, 8, 6); rv.setSpacing(3)
        # 顶行：时间 + 来源徽标 + 类别徽标 + 情绪标签
        top = QHBoxLayout(); top.setSpacing(6)
        if ts:
            tl = QLabel(ts); tl.setStyleSheet(f"color:{p['sub']};font-size:11px;")
            top.addWidget(tl)
        sb = QLabel(src)
        sb.setStyleSheet(f"background:{p['card']};color:{p['text']};border:1px solid {p['border']};"
                        f"border-radius:6px;padding:1px 6px;font-size:11px;")
        top.addWidget(sb)
        cb = QLabel(cat)
        cb.setStyleSheet(f"background:{p['card']};color:{p['sub']};border:1px solid {p['border']};"
                        f"border-radius:6px;padding:1px 6px;font-size:11px;")
        top.addWidget(cb)
        top.addStretch(1)
        tb = QLabel(tag)
        tb.setStyleSheet(f"background:{col};color:{p['text']};border-radius:6px;"
                        f"padding:1px 8px;font-size:11px;font-weight:bold;")
        top.addWidget(tb)
        rv.addLayout(top)
        # 标题
        ttl = QLabel(title); ttl.setWordWrap(True)
        ttl.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:bold;")
        rv.addWidget(ttl)
        # 核心含义
        core = self._news_core(it)
        if core:
            cl = QLabel(f"核心：{core}"); cl.setWordWrap(True)
            cl.setStyleSheet(f"color:{p['sub']};font-size:12px;")
            rv.addWidget(cl)

        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self.news_list.addItem(item)
        self.news_list.setItemWidget(item, row)
        return

    def _render_ai(self, a, tech=None):
        """渲染右侧 AI 双 Tab：综合研判 + 技术面解读。"""
        # ===== Tab1：AI 综合研判（市场趋势 + 多空对比 + 趋势预测 + 风险）=====
        tone = (a.get("trend") or "").strip()
        risk = (a.get("risk") or "").strip()
        sugg = (a.get("suggestion") or "").strip()
        kes = a.get("key_events") or []
        hot = a.get("hot_symbols") or {}
        act = a.get("actionable_insights") or ""
        model = a.get("model", "heuristic")
        p = pal()
        cov = a.get("source_coverage") or {}
        consensus = a.get("consensus") or {}
        conf = a.get("confidence")
        wbias = a.get("weighted_bias")
        parts = []
        parts.append(f"<h3 style='margin:2px 0 6px;color:{p['text']}'>模型：{model}</h3>")
        # 信源覆盖 / 跨源一致性 / 综合置信度 概览条
        active = cov.get("active_sources", 0)
        tsrc = cov.get("total_sources", 0)
        cov_line = (f"<b style='color:{p['text']}'>信源覆盖</b> {active}/{tsrc}"
                    f"：{('、'.join(cov.get('active', [])) or '—')}")
        if consensus.get("sources", 0) >= 2:
            con_line = (f" ｜ <b style='color:{p['text']}'>跨源一致性</b> "
                        f"{consensus['direction']}（一致度 {consensus['agree']*100:.0f}%，"
                        f"看多 {consensus['bull']}/看空 {consensus['bear']} 源）")
        else:
            con_line = f" ｜ <b style='color:{p['text']}'>跨源一致性</b> 样本不足"
        conf_line = (f" ｜ <b style='color:{p['text']}'>综合置信度</b> "
                     f"{conf*100:.0f}%" if isinstance(conf, (int, float)) else "")
        wb_line = (f" ｜ <b style='color:{p['text']}'>加权偏置</b> {wbias:+.2f}"
                   if isinstance(wbias, (int, float)) else "")
        banner = (f"<div style='background:{p['card']};border:1px solid {p['border']};"
                  f"border-radius:8px;padding:6px 10px;margin:4px 0;font-size:12px;color:{p['sub']}'>"
                  f"{cov_line}{con_line}{conf_line}{wb_line}</div>")
        parts.append(banner)
        # 一句话情报摘要（高亮，直击方向与关键矛盾）
        brief = (a.get("brief") or "").strip()
        if brief:
            parts.append(
                f"<div style='background:linear-gradient(90deg,{p['accent']}22,{p['card']});"
                f"border-left:4px solid {p['accent']};border-radius:8px;padding:8px 12px;"
                f"margin:6px 0;font-size:13px;line-height:1.55;color:{p['text']}'>"
                f"<b style='color:{p['accent']}'>📌 情报摘要</b><br>{brief}</div>")
        # 板块轮动读数（强势 / 弱势板块）
        srot = a.get("sector_rotation") or []
        if srot:
            hot_sectors = [s for s in srot if s.get("score", 0) > 0.05][:3]
            cold_sectors = [s for s in srot if s.get("score", 0) < -0.05][:3]
            hot_html = " ".join(
                f"<span style='background:{p['up']};color:{p['text']};border-radius:6px;"
                f"padding:1px 7px;margin:1px;display:inline-block'>▲ {s['sector']} {s['score']:+.2f}</span>"
                for s in hot_sectors) or "<span style='color:#94a3b8'>暂无</span>"
            cold_html = " ".join(
                f"<span style='background:{p['down']};color:{p['text']};border-radius:6px;"
                f"padding:1px 7px;margin:1px;display:inline-block'>▼ {s['sector']} {s['score']:+.2f}</span>"
                for s in cold_sectors) or "<span style='color:#94a3b8'>暂无</span>"
            parts.append(
                f"<p style='margin:6px 0'><b style='color:{p['text']}'>🔥 板块轮动</b><br>"
                f"<span style='font-size:12px;color:{p['sub']}'>强势：</span>{hot_html} "
                f"<span style='font-size:12px;color:{p['sub']}'>｜ 弱势：</span>{cold_html}</p>")
        # 多空力量对比（技术 + 资讯综合）
        parts.append(self._bullbear_html(tech, consensus, wbias))
        # 全局市场认知框架（多空结构 / 板块轮动 / 资金 / 资讯情绪 / 情景概率）
        parts.append(self._global_framework_html())
        if tone:
            parts.append(f"<p style='margin:6px 0'><b style='color:#3b82f6'>📈 市场趋势研判</b><br>{tone}</p>")
        # 趋势预测与综合研判依据（融合技术面 + 资讯面）
        parts.append(self._outlook_html(a, tech))
        if risk:
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['up']}'>⚠️ 风险提示</b><br>{risk}</p>")
        if sugg:
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['down']}'>💡 关注建议</b><br>{sugg}</p>")
        if kes:
            items = "".join(f"<li style='margin:1px 0'>{k}</li>" for k in kes[:6])
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['text']}'>🔑 关键事件</b></p>"
                         f"<ul style='margin:2px 0;padding-left:18px'>{items}</ul>")
        if hot:
            top = sorted(hot.items(), key=lambda x: -x[1])[:8]
            chips = " ".join(f"<span style='background:{p['card']};border:1px solid {p['border']};"
                             f"border-radius:6px;padding:1px 6px;margin:1px;display:inline-block'>{k}×{v}</span>"
                             for k, v in top)
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['text']}'>🔥 活跃品种</b><br>{chips}</p>")
        if act:
            parts.append(f"<p style='margin:6px 0'><b style='color:#f59e0b'>🎯 可操作洞察</b><br>{act}</p>")
        self.ai_view.setHtml("<div style='font-size:13px;line-height:1.6'>" +
                             "".join(parts) + "</div>")

        # ===== Tab2：技术面解读（当前品种）=====
        self.tech_view.setHtml(self._render_tech(tech))

    # ------------------------------------------------------------------
    # 全局市场认知框架（融合全景市场结构 + 资讯情绪，形成系统认知）
    # ------------------------------------------------------------------
    def _global_framework_html(self):
        p = pal()
        ctx = self._market_ctx
        if not ctx:
            return ""
        bull, bear, neutral = self._news_sent
        ntot = bull + bear + neutral
        breadth = float(ctx.get("breadth", 0.0))
        net = float(ctx.get("net_flow", 0.0))
        avg = float(ctx.get("avg", 0.0))
        lead = ctx.get("lead", "—")
        lag = ctx.get("lag", "—")
        posture = ("多头主导" if breadth >= 0.55 else "偏多震荡" if breadth >= 0.45
                   else "多空均衡" if breadth >= 0.4 else "偏空震荡" if breadth >= 0.25
                   else "空头主导")
        fund_txt = f"{'净流入' if net >= 0 else '净流出'}{abs(net):.1f}亿"
        if ntot:
            news_dir = (f"资讯偏多（利好 {bull}/利空 {bear}）" if bull >= bear
                        else f"资讯偏空（利空 {bear}/利好 {bull}）")
            news_align = ((breadth >= 0.5 and bull >= bear) or
                          (breadth < 0.5 and bear > bull))
        else:
            news_dir = "资讯样本不足"
            news_align = True
        up_score = breadth * 0.6 + ((bull / ntot) if ntot else 0.5) * 0.4
        p_up = max(0.05, min(0.95, up_score))
        p_down = 1 - p_up
        align_txt = "相互印证" if news_align else "出现背离，需警惕"
        return f"""
        <p style='margin:6px 0 2px'><b style='color:#8b5cf6'>🧭 全局市场认知框架</b></p>
        <ul style='margin:2px 0 6px;padding-left:18px;font-size:12.5px;line-height:1.5'>
          <li><b>多空结构</b>：全市场上涨占比 <b>{breadth*100:.0f}%</b>，呈「{posture}」；平均涨跌 {avg:+.2f}%。</li>
          <li><b>板块轮动</b>：领涨 <span style='color:{p['up']}'>{lead}</span> ／ 领跌 <span style='color:{p['down']}'>{lag}</span>，资金在强弱板块间切换。</li>
          <li><b>资金态度</b>：全市场资金{fund_txt}，{'增量资金入场支撑价格' if net>=0 else '资金撤离压制价格'}。</li>
          <li><b>资讯情绪</b>：{news_dir}，与价格结构{align_txt}。</li>
          <li><b>情景概率（综合）</b>：偏多情景 ≈ <b>{p_up*100:.0f}%</b> ｜ 偏空情景 ≈ <b>{p_down*100:.0f}%</b>。</li>
        </ul>
        """

    # ------------------------------------------------------------------
    # 多空力量对比（技术面 + 资讯面综合评分，可视化条形）
    # ------------------------------------------------------------------
    def _bullbear_html(self, tech, consensus, wbias):
        p = pal()
        if not tech:
            # 无技术数据时退化为仅资讯偏置
            nb = wbias if isinstance(wbias, (int, float)) else 0.0
            force = max(-100.0, min(100.0, nb * 100))
        else:
            force = tech.get("force", 0.0)
        bull_pct = max(0.0, min(100.0, (force + 100) / 2))
        bear_pct = 100.0 - bull_pct
        col = (pal()["up"] if force > 15 else pal()["down"] if force < -15 else "#f59e0b")
        verdict = ("多头占优" if force > 35 else "偏多" if force > 15
                   else "空头占优" if force < -35 else "偏空" if force < -15
                   else "多空均衡")
        nb = wbias if isinstance(wbias, (int, float)) else 0.0
        nb_txt = ("偏多" if nb > 0.05 else "偏空" if nb < -0.05 else "中性")
        # 资讯多空源
        bull_src = consensus.get("bull", 0)
        bear_src = consensus.get("bear", 0)
        return (
            f"<div style='margin:6px 0;'>"
            f"<b style='color:{p['text']}'>⚖️ 多空力量对比</b> "
            f"<span style='color:{col};font-weight:bold'>{verdict}</span>"
            f"<span style='color:{p['sub']};font-size:12px'>（资讯偏置 {nb_txt} "
            f"· 看多 {bull_src}/看空 {bear_src} 源）</span><br>"
            f"<div style='position:relative;height:16px;border-radius:8px;overflow:hidden;"
            f"background:{pal()['down']};margin-top:3px;'>"
            f"<div style='position:absolute;left:0;top:0;bottom:0;width:{bull_pct:.0f}%;"
            f"background:{pal()['up']};'></div>"
            f"<div style='position:absolute;width:100%;text-align:center;line-height:16px;"
            f"color:{p['text']};font-size:11px;'>多头 {bull_pct:.0f}% ｜ 空头 {bear_pct:.0f}%</div>"
            f"</div></div>"
        )

    # ------------------------------------------------------------------
    # 趋势预测与综合研判依据（融合技术面形态 + 资讯面）
    # ------------------------------------------------------------------
    def _outlook_html(self, a, tech):
        p = pal()
        # 提取 AI 综合研判给出的方向词
        tone = (a.get("trend") or "")
        if "偏多" in tone or "看多" in tone or "利多" in tone:
            news_dir = "偏多"
        elif "偏空" in tone or "看空" in tone or "利空" in tone:
            news_dir = "偏空"
        else:
            news_dir = "中性"
        tech_dir = "—"
        if tech:
            f = tech.get("force", 0.0)
            tech_dir = "偏多" if f > 15 else "偏空" if f < -15 else "中性"
        if tech_dir == news_dir or tech_dir == "—":
            synth = "技术面与资讯面方向一致，信号共振，研判可靠性较高"
        elif news_dir == "—":
            synth = "资讯面暂无明确倾向，以技术面形态为主要参考"
        else:
            synth = "技术面与资讯面出现分歧，建议等待方向确认、控制仓位"
        # 风险提示补充
        risk_note = ""
        if tech:
            if tech.get("kdj_over"):
                risk_note += "KDJ 已进入超买区，警惕短线回踩；"
            if tech.get("kdj_under"):
                risk_note += "KDJ 已进入超卖区，存在技术反弹需求；"
            if tech.get("rsi_over"):
                risk_note += "RSI 偏高，上行动能或衰减；"
            if tech.get("band_expand"):
                risk_note += "布林带开口向上扩张，趋势或加速但波动加大；"
            if tech.get("golden"):
                risk_note += "MACD 刚金叉，短多信号初现；"
            if tech.get("death"):
                risk_note += "MACD 刚死叉，短空信号初现；"
        return (
            f"<p style='margin:6px 0'><b style='color:#8b5cf6'>🔮 趋势预测与综合研判</b><br>"
            f"结合最新财经资讯（{news_dir}）、技术形态（均线/MACD/布林，{tech_dir}）与图表结构，"
            f"{synth}。"
            + (f"<br><span style='color:{p['sub']};font-size:12px'>形态补充：{risk_note}</span>" if risk_note else "")
            + f"</p>"
        )

    # ------------------------------------------------------------------
    # 技术面研判计算（当前品种：均线 / MACD / 布林 / KDJ / RSI / OBV / 支撑阻力 / 多空力）
    # ------------------------------------------------------------------
    def _compute_technical(self, symbol, period, news_bias=0.0):
        try:
            df = self.mdm.get_bars(symbol, period, 260)
            if df is None or len(df) < 30:
                return None
            ind = add_indicators(df)
            ma = {k: float(ind[f"MA{k}"].iloc[-1]) for k in (5, 10, 20, 60)}
            last = float(ind["close"].iloc[-1])
            bull_align = ma[5] >= ma[10] >= ma[20] >= ma[60]
            bear_align = ma[5] <= ma[10] <= ma[20] <= ma[60]
            # MACD
            dif = float(ind["DIF"].iloc[-1]); dea = float(ind["DEA"].iloc[-1])
            hist = float(ind["MACD"].iloc[-1])
            dif0 = float(ind["DIF"].iloc[-2]); dea0 = float(ind["DEA"].iloc[-2])
            golden = dif0 <= dea0 and dif > dea
            death = dif0 >= dea0 and dif < dea
            macd_bull = dif > dea
            # 布林带
            bup = float(ind["BOLL_UP"].iloc[-1]); bmid = float(ind["BOLL_MID"].iloc[-1])
            blow = float(ind["BOLL_LOW"].iloc[-1])
            band_w = (bup - blow) / bmid * 100 if bmid else 0.0
            bup0 = float(ind["BOLL_UP"].iloc[-2]); blow0 = float(ind["BOLL_LOW"].iloc[-2])
            band_expand = (bup - blow) > (bup0 - blow0)
            pct_b = (last - blow) / (bup - blow) if (bup - blow) else 0.5
            above_mid = last > bmid
            # KDJ / RSI
            k = float(ind["K"].iloc[-1]); d = float(ind["D"].iloc[-1]); j = float(ind["J"].iloc[-1])
            kdj_over = k > 80 and d > 80
            kdj_under = k < 20 and d < 20
            rsi6 = float(ind["RSI6"].iloc[-1]); rsi14 = float(ind["RSI14"].iloc[-1])
            rsi_over = rsi14 > 70; rsi_under = rsi14 < 30
            # OBV 斜率
            obv = ind["OBV"].astype(float)
            obv_slope = float(obv.iloc[-1] - obv.iloc[-10])
            obv_bull = obv_slope > 0
            # 支撑 / 阻力（近 40 根极值 + 布林带 + 均线）
            win = ind.iloc[-40:]
            res_recent = float(win["high"].max())
            sup_recent = float(win["low"].min())
            supports = []
            resist = []
            if sup_recent < last:
                supports.append(sup_recent)
            if blow < last:
                supports.append(blow)
            supports += [ma[60], ma[20]]
            if res_recent > last:
                resist.append(res_recent)
            if bup > last:
                resist.append(bup)
            supports = sorted({round(x, 2) for x in supports if x > 0})
            resist = sorted({round(x, 2) for x in resist if x > 0})
            # 多空力量技术评分
            score = 0.0
            score += 28 if bull_align else (-28 if bear_align else 0)
            score += 22 if macd_bull else -22
            score += 15 if obv_bull else -15
            score += (8 if rsi14 > 55 else -8 if rsi14 < 45 else 0)
            score += (7 if above_mid else -7)
            score = max(-100.0, min(100.0, score))
            force = max(-100.0, min(100.0, 0.62 * score + 0.38 * news_bias * 100))
            return {
                "last": last, "ma": ma, "bull_align": bull_align, "bear_align": bear_align,
                "dif": dif, "dea": dea, "hist": hist, "golden": golden, "death": death,
                "macd_bull": macd_bull,
                "bup": bup, "bmid": bmid, "blow": blow, "band_w": band_w,
                "band_expand": band_expand, "pct_b": pct_b, "above_mid": above_mid,
                "k": k, "d": d, "j": j, "kdj_over": kdj_over, "kdj_under": kdj_under,
                "rsi6": rsi6, "rsi14": rsi14, "rsi_over": rsi_over, "rsi_under": rsi_under,
                "obv_bull": obv_bull, "obv_slope": obv_slope,
                "supports": supports, "resist": resist,
                "score": score, "force": force, "news_bias": news_bias,
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 技术面解读 HTML（逐指标解读 + 支撑阻力）
    # ------------------------------------------------------------------
    def _render_tech(self, tech):
        p = pal()
        if not tech:
            return (f"<div style='font-size:13px;color:{p['sub']};line-height:1.5'>"
                    "当前品种数据不足（至少需要 30 根 K 线），暂无法生成技术面解读。"
                    "请切换至其他合约或更长周期后重试。</div>")
        name = self.cur_symbol
        for r in self.mdm.universe:
            if symbol_code(r) == self.cur_symbol:
                name = r[1]
                break
        last = tech["last"]
        ma = tech["ma"]
        # 均线系统
        align_txt = ("多头排列（MA5>MA10>MA20>MA60），均线向上发散，趋势偏强"
                     if tech["bull_align"] else
                     "空头排列（MA5<MA10<MA20<MA60），均线向下发散，趋势偏弱"
                     if tech["bear_align"] else "均线纠缠，方向待选择")
        ma_lines = (
            f"<li>当前价 <b>{last:,.2f}</b> 位于 "
            f"MA5 <b>{ma[5]:,.2f}</b>（{(last-ma[5])/ma[5]*100:+.2f}%）、"
            f"MA10 <b>{ma[10]:,.2f}</b>、MA20 <b>{ma[20]:,.2f}</b>、"
            f"MA60 <b>{ma[60]:,.2f}</b> 之间。</li>"
            f"<li>均线结构：<b>{align_txt}</b>。</li>"
        )
        # MACD
        macd_state = ("金叉初现（DIF 上穿 DEA），短多信号"
                      if tech["golden"] else "死叉初现（DIF 下穿 DEA），短空信号"
                      if tech["death"] else
                      "DIF 在 DEA 上方，多头动能占优" if tech["macd_bull"]
                      else "DIF 在 DEA 下方，空头动能占优")
        macd_lines = (
            f"<li>DIF <b>{tech['dif']:+.2f}</b>，DEA <b>{tech['dea']:+.2f}</b>，"
            f"柱状体 <b>{tech['hist']:+.2f}</b>。</li>"
            f"<li>状态：<b>{macd_state}</b>。</li>"
        )
        # 布林带
        boll_pos = ("价格运行于布林上轨附近，短期偏强但谨防回落"
                    if tech["pct_b"] > 0.8 else
                    "价格运行于布林下轨附近，短期偏弱但存在反弹"
                    if tech["pct_b"] < 0.2 else
                    "价格在中轨附近震荡，方向不明"
                    if tech["above_mid"] else "价格跌破中轨，偏弱")
        boll_lines = (
            f"<li>上轨 <b>{tech['bup']:,.2f}</b> / 中轨 <b>{tech['bmid']:,.2f}</b> / "
            f"下轨 <b>{tech['blow']:,.2f}</b>，带宽 <b>{tech['band_w']:.2f}%</b>"
            f"（{'扩张' if tech['band_expand'] else '收窄'}）。</li>"
            f"<li>位置：<b>{boll_pos}</b>（%B={tech['pct_b']*100:.0f}%）。</li>"
        )
        # KDJ / RSI
        kdj_state = ("超买（K/D>80），短线回踩风险"
                     if tech["kdj_over"] else "超卖（K/D<20），反弹需求"
                     if tech["kdj_under"] else "中性区间")
        kdj_lines = (
            f"<li>K <b>{tech['k']:.1f}</b> / D <b>{tech['d']:.1f}</b> / J <b>{tech['j']:.1f}</b>"
            f"（{kdj_state}）。</li>"
            f"<li>RSI6 <b>{tech['rsi6']:.1f}</b> / RSI14 <b>{tech['rsi14']:.1f}</b>"
            f"（{'超买' if tech['rsi_over'] else '超卖' if tech['rsi_under'] else '中性'}）。</li>"
        )
        # OBV 量能
        obv_lines = (
            f"<li>OBV 近 10 根 {'走高' if tech['obv_bull'] else '走低'}，"
            f"量能{'配合价格上涨（量价齐升）' if tech['obv_bull'] else '配合价格下跌（量价齐跌）'}"
            f"，斜率 {tech['obv_slope']:+.0f}。</li>"
        )
        # 支撑阻力
        sup_txt = "、".join(f"{x:,.2f}" for x in tech["supports"][:4]) or "—"
        res_txt = "、".join(f"{x:,.2f}" for x in tech["resist"][:4]) or "—"
        sr_lines = (
            f"<li><span style='color:{pal()['up']}'>支撑位</span>：{sup_txt}</li>"
            f"<li><span style='color:{pal()['down']}'>阻力位</span>：{res_txt}</li>"
        )
        fv = tech["force"]
        strength = ("强多" if fv > 35 else "震荡偏多" if fv > 15
                    else "强空" if fv < -35 else "震荡偏空" if fv < -15 else "中性震荡")
        return f"""
        <div style='font-size:13px;line-height:1.6;'>
            <h3 style='margin:2px 0 6px;color:{p['text']}'>📐 {name}（{self.cur_symbol} · {self.cur_period}）技术面解读</h3>

            <p style='margin:6px 0 2px'><b style='color:#3b82f6'>一、均线系统（趋势方向）</b></p>
            <ul style='margin:2px 0 6px;padding-left:18px'>{ma_lines}</ul>

            <p style='margin:6px 0 2px'><b style='color:#3b82f6'>二、MACD（动能与拐点）</b></p>
            <ul style='margin:2px 0 6px;padding-left:18px'>{macd_lines}</ul>

            <p style='margin:6px 0 2px'><b style='color:#3b82f6'>三、布林带（波动与轨道）</b></p>
            <ul style='margin:2px 0 6px;padding-left:18px'>{boll_lines}</ul>

            <p style='margin:6px 0 2px'><b style='color:#3b82f6'>四、KDJ / RSI（摆动超买超卖）</b></p>
            <ul style='margin:2px 0 6px;padding-left:18px'>{kdj_lines}</ul>

            <p style='margin:6px 0 2px'><b style='color:#3b82f6'>五、量能与 OBV（资金态度）</b></p>
            <ul style='margin:2px 0 6px;padding-left:18px'>{obv_lines}</ul>

            <p style='margin:6px 0 2px'><b style='color:#3b82f6'>六、支撑位 / 阻力位（关键价位）</b></p>
            <ul style='margin:2px 0 6px;padding-left:18px'>{sr_lines}</ul>

            <p style='margin:6px 0 2px'><b style='color:#8b5cf6'>七、综合技术结论</b></p>
            <p style='margin:2px 0'>技术多空力评分 <b>{tech['score']:+.0f}</b>（±100），
            结合资讯偏置后综合力 <b>{tech['force']:+.0f}</b>。
            操作上建议以 <b>{'支撑位附近低吸、跌破止损' if tech['force']>0 else '阻力位附近高抛、突破跟随' if tech['force']<0 else '区间波段、等待突破'}</b> 为主，
            并配合右侧 AI 综合研判与最新资讯动态调整。</p>

            <p style='margin:6px 0 2px'><b style='color:#8b5cf6'>八、全局研判思路与关键触发</b></p>
            <p style='margin:2px 0'>趋势强度判定为 <b>{strength}</b>。
            关键触发条件：价格<b>有效突破</b>阻力 <span style='color:{p['down']}'>{res_txt}</span>
            则打开上行空间（可顺势跟随）；<b>有效跌破</b>支撑 <span style='color:{p['up']}'>{sup_txt}</span>
            则趋势转弱（需减仓 / 严格止损）。
            若右侧 AI 综合研判与当前技术方向<b>一致</b>，信号共振、可信度提升；
            若<b>背离</b>，则降低仓位、等待方向确认后再行动。</p>
        </div>
        """

    # ------------------------------------------------------------------
    # 仅重算技术面（切换合约 / 周期时调用，避免重复抓取资讯）
    # ------------------------------------------------------------------
    def _refresh_tech(self):
        if self._ai_analysis is None:
            return
        nb = _news_overall_bias(self._news) if self._news else 0.0
        tech = self._compute_technical(self.cur_symbol, self.cur_period, news_bias=nb)
        self._tech = tech
        self._render_ai(self._ai_analysis, tech)

    # ---- 工具 ----
    def _set(self, table, r, c, text, color=None):
        it = QTableWidgetItem(str(text))
        fg = (QColor(color) if isinstance(color, str) else color) if color is not None \
            else QColor(pal()["text"])
        it.setForeground(fg)
        table.setItem(r, c, it)
        return it

    def _on_pick(self, item):
        name = self.watch.item(item.row(), 0).text()
        for r in self.mdm.universe:
            if r[1] == name:
                idx = self.sym_cb.findData(symbol_code(r))
                if idx >= 0:
                    self.sym_cb.setCurrentIndex(idx)
                break

    def set_theme(self, t: str) -> None:
        super().set_theme(t)
        self._style_cards()
        self.temp_lbl.setStyleSheet("color:%s;" % pal()["sub"])
        for tl in self.status_tiles:
            tl.set_theme(t)
        # 用新主题色重渲染资讯列表与 AI 研判（含四状态灯已随 tiles 更新）
        if self._news is not None:
            self._fill_news(self._news, self._ai_analysis,
                            self._sd_rows, self._tech)
