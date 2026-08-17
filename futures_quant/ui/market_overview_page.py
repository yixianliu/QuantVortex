"""行情全景 · 统一市场监控总览页。

将原「行情全景（实时行情）」与「市场全景（强弱/量能/资金流）」合并为
一站式的期货市场全景视图，并新增「财经资讯 + 资讯智能解读」板块：

  - 实时行情：K 线图 + 盘口快照（最新价/涨跌/幅度/成交量/持仓量/资金流）+ 全市场速览表；
  - 市场全局：涨跌家数 / 市场广度 / 资金净流入 / 平均涨跌 / 领涨领跌板块 / 温度计 KPI，
             板块强度榜、涨跌分布与温度计；
  - 基本面关键指标：持仓异动（全市场持仓量变化）、供需 / 库存信号（由财经资讯 云端研判得出）；
  - 榜单：领涨榜 / 领跌榜 / 资金流向榜 / 板块明细；
  - 财经资讯 + 资讯解读：并发爬取 11 个财经资讯源（财联社 / 东方财富 / 和讯 / 同花顺 /
             华尔街见闻 / 金十 / 新浪财经 / 期货日报 / 中证网 / 证券时报 / 凤凰财经），
             经 KP模型与规则引擎做情绪 / 供需 / 趋势研判，并基于【可信度加权偏置 +
             跨源一致性 + 信源覆盖度】输出综合置信度、趋势、风险、关注建议、
             关键事件、活跃品种与可操作洞察。

数据依赖：MarketDataManager（行情中枢）与 AnalysisStore（存储）；新闻来自 news_feed。
"""

from __future__ import annotations

import csv
import datetime as dt
import time
import os
import json
import shutil
import tempfile
import zipfile
from typing import Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtProperty, QPropertyAnimation
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QScrollArea, QSplitter, QAbstractItemView, QListWidget, QListWidgetItem,
    QLineEdit, QTabWidget, QFileDialog,
)

from .widgets import (
    PageHeader, StatCard, ConfidenceBar, prepare_table,
    color_pnl, pal, ToolBar, THEME, SectionHeader, StatusTile,
    ResponsiveRow, FlowLayout, RankTable, _fmt_hands, _fmt_yi,
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
        """初始化相关对象。
        
            参数:
                mdm
                store
                config
                session"""
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
        self.temp_lbl = QLabel("—")  # 市场温度计标签（默认值，防止 set_theme 报错）
        self.temp_bar = ConfidenceBar(0.5)  # 市场温度计条（默认值，防止 refresh_pano 报错）
        self.breadth_ext_lbl = QLabel()  # 涨跌分布扩展统计标签（默认值，防止 refresh_pano 报错）
        self.breadth_ext_lbl.setWordWrap(False)
        self._build()

    # ==================================================================
    # 构建
    # ==================================================================
    def _build(self):
        """构建相关对象。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "行情全景",
            "全市场实时行情 · 板块强弱轮动 · 持仓 / 供需基本面 · 财经资讯 资讯智能解读 —— 一站式期货市场全景"))

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
        self.news_btn = QPushButton("KP资讯解读")
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

        # ---- 双栏仪表盘：左=综合仪表板（顶部KPI+行情速览），右=财经资讯 ----
        # 顶部综合仪表板：实时行情 + 市场全局 + 基本面 + 榜单（独立滚动）
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(6)

        # 左栏：综合仪表板（所有行情数据）
        left = QScrollArea()
        left.setWidgetResizable(True)
        # 杜绝横向滚动：内容宽度被约束到视口，由内部响应式布局自动重排
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.setFrameShadow(QFrame.Shadow.Sunken)
        left.setFrameShape(QFrame.Shape.StyledPanel)
        lwid = QWidget()
        lcol = QVBoxLayout(lwid)
        lcol.setContentsMargins(4, 4, 4, 4)
        lcol.setSpacing(6)
        lcol.addWidget(self._build_dashboard())
        lcol.addStretch(1)
        left.setWidget(lwid)
        split.addWidget(left)

        # 右栏：财经资讯 + 资讯智能解读（常驻醒目宽栏）
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right.setFrameShadow(QFrame.Shadow.Sunken)
        right.setFrameShape(QFrame.Shape.StyledPanel)
        rwid = QWidget()
        rcol = QVBoxLayout(rwid)
        rcol.setContentsMargins(4, 4, 4, 4)
        rcol.setSpacing(6)
        rcol.addWidget(self._build_news(), 1)
        right.setWidget(rwid)
        split.addWidget(right)

        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------
    # 综合仪表板：顶部核心指标 + 市场状态 + 板块强度 + 涨跌分布
    # ------------------------------------------------------------------
    def _build_dashboard(self) -> QFrame:
        """构建综合仪表板，整合实时行情、市场全局、基本面、榜单。"""
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(8, 6, 8, 6); bl.setSpacing(6)

        # 标题栏
        bl.addWidget(self._section_header(
            "📊 综合仪表板", "#3b82f6"))

        # 操作条：一键导出当前全景快照（盘口 + KPI + 六榜单 -> CSV）
        act_bar = QHBoxLayout(); act_bar.setContentsMargins(0, 0, 0, 0)
        act_bar.addStretch(1)
        self._export_btn = QPushButton("⬇ 导出全部榜单 CSV")
        self._export_btn.setObjectName("export-btn")
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.clicked.connect(self._on_export_all)
        act_bar.addWidget(self._export_btn)
        bl.addLayout(act_bar)

        # 第一部分：当前品种实时行情 + 市场状态总览（响应式两列，窄屏自动堆叠）

        # 左侧：实时行情卡片（StatCard 两层级：主指标一行 + 次指标一行带单位）
        rt_card = QFrame(); rt_card.setObjectName("card")
        rt_lay = QVBoxLayout(rt_card); rt_lay.setContentsMargins(8, 6, 8, 6); rt_lay.setSpacing(6)
        rt_lay.addWidget(self._section_header("实时行情", "#3b82f6", badge="当前品种"))
        self.chips = {
            "last": StatCard("最新价", "--", value_size=20, theme=self._theme),
            "chg": StatCard("涨跌", "--", value_size=20, theme=self._theme),
            "pct": StatCard("涨跌幅", "--", value_size=20, theme=self._theme),
            "vol": StatCard("成交量", "--", unit="手", theme=self._theme),
            "oi": StatCard("持仓量", "--", unit="手", theme=self._theme),
            "fund": StatCard("资金流", "--", unit="亿", theme=self._theme),
        }
        # 主指标：最新价 / 涨跌 / 涨跌幅（视觉权重最高）
        rt_primary = QHBoxLayout(); rt_primary.setSpacing(6)
        for k in ("last", "chg", "pct"):
            rt_primary.addWidget(self.chips[k], 1)
        rt_lay.addLayout(rt_primary)
        # 次指标：成交量 / 持仓量 / 资金流（带显式单位，保证数值精准可读）
        rt_secondary = QHBoxLayout(); rt_secondary.setSpacing(6)
        for k in ("vol", "oi", "fund"):
            rt_secondary.addWidget(self.chips[k], 1)
        rt_lay.addLayout(rt_secondary)
        self.quote_time = QLabel("行情更新：—")
        self.quote_time.setObjectName("quote-time")
        self.quote_time.setStyleSheet("font-size:11px;color:#64748b;")
        rt_lay.addWidget(self.quote_time)

        # 右侧：市场状态卡片
        st_card = QFrame(); st_card.setObjectName("card")
        st_lay = QVBoxLayout(st_card); st_lay.setContentsMargins(8, 6, 8, 6); st_lay.setSpacing(4)
        st_lay.addWidget(self._section_header("市场状态", "#8b5cf6"))
        self.tile_strength = StatusTile("强弱", self._theme)
        self.tile_adv = StatusTile("涨跌", self._theme)
        self.tile_fund = StatusTile("资金", self._theme)
        self.tile_sent = StatusTile("情绪", self._theme)
        for t in (self.tile_strength, self.tile_adv, self.tile_fund, self.tile_sent):
            self.status_tiles.append(t)
        st_strip = QHBoxLayout(); st_strip.setSpacing(6)
        for t in (self.tile_strength, self.tile_adv, self.tile_fund, self.tile_sent):
            st_strip.addWidget(t, 1)
        st_lay.addLayout(st_strip)

        bl.addWidget(ResponsiveRow(rt_card, st_card))

        # 第二部分：市场全局概览（KPI + 板块强度 + 涨跌分布）
        market_card = QFrame(); market_card.setObjectName("card")
        mkt_lay = QVBoxLayout(market_card); mkt_lay.setContentsMargins(8, 6, 8, 6); mkt_lay.setSpacing(6)
        mkt_lay.addWidget(self._section_header("市场全局概览", "#0ea5e9"))

        # KPI 英雄条（统一 StatCard 紧凑模式：标签 + 数值 + 单位，配色随数据）
        self._kpi_cards = {}
        self._kpi = QFrame(); self._kpi.setObjectName("kpi-panel")
        kpi_wrap = QVBoxLayout(self._kpi); kpi_wrap.setContentsMargins(0, 0, 0, 0); kpi_wrap.setSpacing(6)
        row1 = QHBoxLayout(); row1.setSpacing(6)
        row2 = QHBoxLayout(); row2.setSpacing(6)
        kpi_keys = [("up", "上涨"), ("down", "下跌"), ("flat", "平盘"),
                    ("breadth", "广度"), ("flow", "资金流"), ("avg", "平均"),
                    ("lead", "领涨"), ("lag", "领跌"), ("temp", "温度计")]
        kpi_subs = {
            "up": "Top 8 上涨合约",
            "down": "Top 8 下跌合约",
            "flat": "持仓 ±0.5% 区间",
            "breadth": "涨跌家数占比",
            "flow": "净资金净流",
            "avg": "涨跌均值",
            "lead": "涨幅前 8 名",
            "lag": "跌幅前 8 名",
            "temp": "市场情绪指数",
        }
        for i, (key, label) in enumerate(kpi_keys):
            card = StatCard(label, "—", sub=kpi_subs.get(key, ""),
                            value_size=15, compact=True, theme=self._theme)
            self._kpi_cards[key] = card
            if i < 6:
                row1.addWidget(card, 1)
            else:
                row2.addWidget(card, 1)
        # 家数类指标显式单位，强化数值精度与可读性
        for k in ("up", "down", "flat"):
            self._kpi_cards[k].set_unit("家")
        kpi_wrap.addLayout(row1)
        kpi_wrap.addLayout(row2)
        mkt_lay.addWidget(self._kpi)

        # 第三部分：板块强度 + 涨跌分布（响应式两列，板块强度条自动换行）
        # 板块强度
        sec_card = QFrame(); sec_card.setObjectName("card")
        sec_lay = QVBoxLayout(sec_card); sec_lay.setContentsMargins(6, 4, 6, 4); sec_lay.setSpacing(2)
        sec_lay.addWidget(QLabel("板块强度"))
        self.sector_strip = QWidget(); self.sector_strip.setMinimumHeight(32)
        # 改用 FlowLayout：板块标签按宽度自动换行，避免横向溢出
        self.sector_lay = FlowLayout(self.sector_strip); self.sector_lay.setSpacing(6)
        sec_lay.addWidget(self.sector_strip)

        # 涨跌分布
        brd_card = QFrame(); brd_card.setObjectName("card")
        brd_lay = QVBoxLayout(brd_card); brd_lay.setContentsMargins(6, 4, 6, 4); brd_lay.setSpacing(2)
        brd_lay.addWidget(QLabel("涨跌分布（横向）"))
        self.breadth_gauge = QWidget(); self.breadth_gauge.setMinimumHeight(28)
        bg_lay = QHBoxLayout(self.breadth_gauge); bg_lay.setContentsMargins(0, 0, 0, 0); bg_lay.setSpacing(0)
        self._bg_up = QLabel(); self._bg_up.setObjectName("bg-up")
        self._bg_flat = QLabel(); self._bg_flat.setObjectName("bg-flat")
        self._bg_down = QLabel(); self._bg_down.setObjectName("bg-down")
        for w in (self._bg_up, self._bg_flat, self._bg_down):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.setStyleSheet("color:#fff;font-size:11px;font-weight:bold;")
        bg_lay.addWidget(self._bg_up, 1); bg_lay.addWidget(self._bg_flat, 1); bg_lay.addWidget(self._bg_down, 1)
        brd_lay.addWidget(self.breadth_gauge)
        self.breadth_lbl = QLabel(); self.breadth_lbl.setWordWrap(True)
        self.breadth_lbl.setStyleSheet("font-size:11px;")
        brd_lay.addWidget(self.breadth_lbl)

        mkt_lay.addWidget(ResponsiveRow(sec_card, brd_card))
        bl.addWidget(market_card)

        # 第四部分：基本面关键指标（核心摘要 + 持仓异动 + 供需/库存信号）
        fund_card = QFrame(); fund_card.setObjectName("card")
        fund_lay = QVBoxLayout(fund_card); fund_lay.setContentsMargins(8, 6, 8, 6); fund_lay.setSpacing(6)
        fund_lay.addWidget(self._section_header("基本面关键指标", "#f59e0b"))

        # 核心摘要：突出「增仓首位 / 减仓首位 / 资金净流入首位 / 净增仓品种数」四项最关键数据
        self._fund_kpi = {}
        fk = QHBoxLayout(); fk.setSpacing(6)
        for key, label in (("inc", "增仓首位"), ("dec", "减仓首位"),
                           ("fund", "资金净流入首位"), ("net", "净增仓品种")):
            c = StatCard(label, "--", theme=self._theme, compact=True, value_size=15)
            c.setMinimumHeight(48)
            self._fund_kpi[key] = c
            fk.addWidget(c, 1)
        fund_lay.addLayout(fk)

        b1 = QWidget(); b1l = QVBoxLayout(b1); b1l.setContentsMargins(0, 0, 0, 0); b1l.setSpacing(2)
        self._oi_hdr = QLabel("持仓异动（按 |持仓变%| 排序，点击表头可重排）")
        self._oi_hdr.setStyleSheet(f"font-size:11px;font-weight:bold;color:{pal()['sub']};")
        b1l.addWidget(self._oi_hdr)
        self.oi_tbl = RankTable(
            [("name", "合约", "text"), ("category", "板块", "text"),
             ("oi_chg", "持仓变%", "bar")], theme=self._theme)
        b1l.addWidget(self.oi_tbl)
        b2 = QWidget(); b2l = QVBoxLayout(b2); b2l.setContentsMargins(0, 0, 0, 0); b2l.setSpacing(2)
        self._sd_hdr = QLabel("供需 / 库存信号（财经资讯 云端研判）")
        self._sd_hdr.setStyleSheet(f"font-size:11px;font-weight:bold;color:{pal()['sub']};")
        b2l.addWidget(self._sd_hdr)
        # 5 列 -> 4 列：合并「方向 + 研判」为单「信号」列，降低列宽压力、提升信息密度
        self.sd_tbl = RankTable(
            [("cat", "板块", "text"), ("strength", "信号强度", "bar"),
             ("signal", "信号", "text"), ("sample", "依据", "text")], theme=self._theme)
        b2l.addWidget(self.sd_tbl)
        fund_lay.addWidget(ResponsiveRow(b1, b2))
        bl.addWidget(fund_card)

        # 第五部分：榜单（排名列 + 比例条 + 点击表头排序）
        rank_card = QFrame(); rank_card.setObjectName("card")
        rank_lay = QVBoxLayout(rank_card); rank_lay.setContentsMargins(8, 6, 8, 6); rank_lay.setSpacing(6)
        rank_lay.addWidget(self._section_header("榜单（点击表头可排序，前三名奖牌色）", "#10b981"))
        self.rank_hint = QLabel()
        self.rank_hint.setObjectName("rank-hint")
        self.rank_hint.setStyleSheet(f"font-size:11px;color:{pal()['sub']};")
        self.rank_hint.setText(
            "领涨 / 领跌 / 资金流向 各取 Top 8 · 板块明细含强弱/资金/品种数 · "
            "点击表头可排序，前三名奖牌色")
        rank_lay.addWidget(self.rank_hint)
        g1 = QWidget(); g1l = QVBoxLayout(g1); g1l.setContentsMargins(0, 0, 0, 0); g1l.setSpacing(2)
        g1l.addWidget(QLabel("领涨 Top 8"))
        self.gain_tbl = RankTable(
            [("name", "合约", "text"), ("category", "板块", "text"),
             ("chg", "涨跌幅%", "bar")], theme=self._theme)
        g1l.addWidget(self.gain_tbl)
        g2 = QWidget(); g2l = QVBoxLayout(g2); g2l.setContentsMargins(0, 0, 0, 0); g2l.setSpacing(2)
        g2l.addWidget(QLabel("领跌 Top 8"))
        self.lag_tbl = RankTable(
            [("name", "合约", "text"), ("category", "板块", "text"),
             ("chg", "涨跌幅%", "bar")], theme=self._theme)
        g2l.addWidget(self.lag_tbl)
        rank_lay.addWidget(ResponsiveRow(g1, g2))
        rb1 = QWidget(); rb1l = QVBoxLayout(rb1); rb1l.setContentsMargins(0, 0, 0, 0); rb1l.setSpacing(2)
        rb1l.addWidget(QLabel("资金流向 Top 8（亿）"))
        self.flow_tbl = RankTable(
            [("name", "合约", "text"), ("category", "板块", "text"),
             ("fund", "资金流(亿)", "bar")], theme=self._theme)
        rb1l.addWidget(self.flow_tbl)
        rb2 = QWidget(); rb2l = QVBoxLayout(rb2); rb2l.setContentsMargins(0, 0, 0, 0); rb2l.setSpacing(2)
        rb2l.addWidget(QLabel("板块明细（强弱 / 资金 / 品种数）"))
        self.sec_tbl = RankTable(
            [("category", "板块", "text"), ("mean_chg", "平均涨跌%", "bar"),
             ("flow", "资金流(亿)", "bar"), ("count", "品种数", "num")], theme=self._theme)
        rb2l.addWidget(self.sec_tbl)
        rank_lay.addWidget(ResponsiveRow(rb1, rb2))
        bl.addWidget(rank_card)

        return box

    # ------------------------------------------------------------------
    # 区块标题栏（强调色 + 粗体）助手
    # ------------------------------------------------------------------
    def _section_header(self, title, accent="#3b82f6", badge=None):
        """带强调色竖条 + 粗体标题的区块标题栏，提升信息层级与扫描效率。

        现复用共享组件 widgets.SectionHeader（强调色竖条 + 粗体标题 + 可选
        徽标），与全应用视觉语言统一；主题色由 BasePage.set_theme 递归下发。
        """
        return SectionHeader(title, accent, badge, theme=self._theme)

    def _set_card(self, key, text, color="", direction="", tooltip=""):
        """设置 KPI 卡片数值（兼容 StatCard.set_value）。"""
        c = self._kpi_cards.get(key)
        if not c:
            return
        c.set_value(text, color or pal()["text"],
                    direction=direction,
                    tooltip=tooltip or f"{text}")

    def _style_cards(self):
        """KPI 卡片统一重绘主题（StatCard 自身已处理配色，此处仅兜底刷新）。"""
        for c in self._kpi_cards.values():
            c.set_theme(self._theme)

    # ------------------------------------------------------------------
    # 区块五：财经资讯 + 资讯智能解读
    # ------------------------------------------------------------------
    def _build_news(self) -> QFrame:
        """构建news。
        
            返回:
                QFrame"""
        box = QFrame(); box.setObjectName("card")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 8, 10, 8); bl.setSpacing(8)

        ctl = QHBoxLayout()
        ctl.addWidget(self._section_header("财经资讯 + AI智能解读", "#8b5cf6"))
        self.news_status = QLabel("页面打开自动生成 云端研判；也可点击「KP资讯解读」手动刷新")
        self.news_status.setObjectName("hint")
        ctl.addWidget(self.news_status, 1)
        bl.addLayout(ctl)

        # 精简研判摘要：直接呈现「由财经资讯推导出的结果 / 趋势」，不再罗列新闻列表
        self.news_summary = QLabel(
            "正在解读全市场财经资讯，推导多空趋势与核心驱动，请稍候…")
        self.news_summary.setObjectName("news-summary")
        self.news_summary.setWordWrap(True)
        self.news_summary.setMinimumHeight(96)
        bl.addWidget(self.news_summary)

        # 云端研判：双 Tab 深度扩展（综合研判 + 技术面解读）
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
        """处理on合约代码。
        
            参数:
                i"""
        self.cur_symbol = self.sym_cb.itemData(i)
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        self._refresh_quote()
        self._refresh_tech()

    def _on_period(self, i):
        """处理on周期。
        
            参数:
                i"""
        self.cur_period = self.per_cb.itemData(i)
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        self._refresh_quote()
        self._refresh_pano()
        self._refresh_tech()

    def _on_cat(self, i):
        """处理oncat。
        
            参数:
                i"""
        self.cur_cat = self.cat_cb.currentText()
        self._refresh_pano()

    def _toggle_live(self):
        """切换live。"""
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
        """处理onlive。
        
            参数:
                bar"""
        if bar.get("symbol") == self.cur_symbol:
            self._refresh_quote()

    def _refresh_all(self):
        """刷新all。"""
        self._refresh_quote()
        self._refresh_pano()

    # ------------------------------------------------------------------
    # 一键导出：当前全景快照（盘口 + 市场全局 KPI + 六榜单 -> CSV）
    # ------------------------------------------------------------------
    def _on_export_all(self) -> None:
        """导出全部：弹出文件夹选择框后落盘快照。"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择导出文件夹", os.path.expanduser("~"))
        if not folder:
            return
        n = self._export_snapshot(folder)
        self._export_btn.setText(f"✓ 已导出 {n} 个文件")
        QTimer.singleShot(2000, lambda: self._export_btn.setText(
            "⬇ 导出全部榜单 CSV"))

    def _export_snapshot(self, folder: str) -> int:
        """把当前全景（盘口 + 市场全局 KPI + 六榜单）导出为单个 zip 归档。

        归档名自动按日期时间命名：行情全景_YYYYMMDD_HHMMSS.zip，
        内含 8 个 CSV（utf-8-sig），临时落盘目录在打包后清理。

        参数:
            folder: 目标文件夹（zip 写入此处）
        返回:
            归档内 CSV 文件数量"""
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp = tempfile.mkdtemp(prefix="qv_snap_")
        try:
            count = self._write_snapshot_csvs(tmp)
            zip_path = os.path.join(folder, f"行情全景_{stamp}.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fn in sorted(os.listdir(tmp)):
                    zf.write(os.path.join(tmp, fn), arcname=fn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return count

    def _write_snapshot_csvs(self, folder: str) -> int:
        """把当前全景写入 folder 下的 8 个 CSV（utf-8-sig）。返回文件数。"""
        os.makedirs(folder, exist_ok=True)
        count = 0
        # 六榜单
        rank_map = [
            ("领涨榜", self.gain_tbl), ("领跌榜", self.lag_tbl),
            ("资金流向榜", self.flow_tbl), ("板块明细", self.sec_tbl),
            ("持仓异动", self.oi_tbl), ("供需库存信号", self.sd_tbl),
        ]
        for label, tbl in rank_map:
            if tbl is None:
                continue
            path = os.path.join(folder, f"行情全景_{label}.csv")
            tbl._export_csv(path)
            count += 1
        # 盘口快照
        qp = os.path.join(folder, "行情全景_盘口快照.csv")
        with open(qp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["指标", "数值", "单位"])
            for key in ("last", "chg", "pct", "vol", "oi", "fund"):
                c = self.chips.get(key)
                if c:
                    w.writerow([c._lab.text(), c._val.text(), c._unit.text()])
            w.writerow(["行情更新", self.quote_time.text(), ""])
        count += 1
        # 市场全局 KPI
        kp = os.path.join(folder, "行情全景_市场全局KPI.csv")
        with open(kp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["指标", "数值"])
            for c in self._kpi_cards.values():
                w.writerow([c._lab.text(), c._val.text()])
        count += 1
        return count

    # ------------------------------------------------------------------
    # 自动加载：页面首次显示（行情全景为默认首页，启动即触发）时，
    # 自动拉取一次多源财经资讯 + 云端研判 + 供需信号，无需手动点击。
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """显示事件。
        
            参数:
                event"""
        super().showEvent(event)
        # 首次显示：延迟加载全景（行情 + 速览 + 自选列表），避免构造期间阻塞主线程
        if not self._pano_lazy:
            self._pano_lazy = True
            QTimer.singleShot(100, self._refresh_all)
        if not self._news_autoloaded:
            self._news_autoloaded = True
            self.news_status.setText("正在自动获取全市场资讯与 云端研判…")
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
        # 成交量 / 持仓量：自动 万/亿手 单位，数值色用文本色（精准可读，不再灰显）
        v_num, v_unit = _fmt_hands(q["volume"])
        self.chips["vol"].set_value(v_num, pal()["text"])
        self.chips["vol"].set_unit(v_unit)
        o_num, o_unit = _fmt_hands(q["open_interest"])
        self.chips["oi"].set_value(o_num, pal()["text"])
        self.chips["oi"].set_unit(o_unit)
        # 资金流：带方向副提示
        f_num, f_unit = _fmt_yi(q["fund_flow"])
        fcol = pal()["up"] if q["fund_flow"] >= 0 else pal()["down"]
        self.chips["fund"].set_value(f_num, fcol)
        self.chips["fund"].set_unit(f_unit)
        self.chips["fund"].set_sub("净流入" if q["fund_flow"] >= 0 else "净流出")
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
        self._set_card("up", str(up), pal()["up"], direction="up",
                        tooltip=f"上涨 {up} 家 · 共 {total} 品种")
        self._set_card("down", str(down), pal()["down"], direction="down",
                        tooltip=f"下跌 {down} 家 · 共 {total} 品种")
        self._set_card("flat", str(flat), pal()["sub"], direction="flat",
                        tooltip=f"平盘 {flat} 家")
        self._set_card("breadth", f"{breadth*100:.0f}%",
                      f"{p['up']}" if breadth >= 0.5 else (f"{p['accent2']}" if breadth >= 0.4 else f"{p['down']}"),
                      direction=("up" if breadth >= 0.45 else "down" if breadth < 0.4 else "flat"),
                      tooltip=f"市场广度 {breadth*100:.0f}%（上涨占比）")
        self._set_card("flow", f"{net_flow:+.1f}亿", f"{p['up']}" if net_flow >= 0 else f"{p['down']}",
                        direction=("up" if net_flow >= 0 else "down"),
                        tooltip=f"全市场资金净{(net_flow>=0 and '流入' or '流出')} {net_flow:+.1f}亿")
        self._set_card("avg", f"{avg:+.2f}%", f"{p['up']}" if avg >= 0 else f"{p['down']}",
                        direction=("up" if avg >= 0 else "down"),
                        tooltip=f"全品种平均涨跌 {avg:+.2f}%")
        grp = pan_all.groupby("category")["chg_pct"].mean().sort_values(ascending=False)
        lead = grp.index[0] if len(grp) else "—"
        lag = grp.index[-1] if len(grp) else "—"
        self._set_card("lead", lead, p["up"], direction="up",
                        tooltip=f"领涨板块：{lead}")
        self._set_card("lag", lag, p["down"], direction="down",
                        tooltip=f"领跌板块：{lag}")
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
        f_num, f_unit = _fmt_yi(net_flow)
        self.tile_fund.set_status(
            f_level, f"{f_num}{f_unit}",
            "全市场资金净流入" if net_flow >= 0 else "全市场资金净流出")

        # 涨跌分布（单行横向三段条 + 扩展明细）
        def pct(n):
            """处理pct。

                参数:
                    n"""
            return (n / total * 100) if total else 0.0
        p = pal()
        # 三段条：按家数比例分配水平 stretch，段内显示百分比
        bg_lay = self.breadth_gauge.layout()
        bg_lay.setStretch(0, max(up, 1))
        bg_lay.setStretch(1, max(flat, 1))
        bg_lay.setStretch(2, max(down, 1))
        self._bg_up.setText(f"▲ {pct(up):.0f}%")
        self._bg_flat.setText(f"— {pct(flat):.0f}%")
        self._bg_down.setText(f"▼ {pct(down):.0f}%")
        self._bg_up.setStyleSheet(f"background:{p['up']};color:#fff;font-size:12px;font-weight:bold;border-radius:0;")
        self._bg_flat.setStyleSheet(f"background:{p['sub']};color:{p['bg']};font-size:12px;font-weight:bold;border-radius:0;")
        self._bg_down.setStyleSheet(f"background:{p['down']};color:#fff;font-size:12px;font-weight:bold;border-radius:0;")
        # 单行明细文字
        self.breadth_lbl.setText(
            f"<span style='color:{p['up']};font-weight:bold;font-size:13px;'>▲ 上涨 {up} 家 ({pct(up):.1f}%)</span>　"
            f"<span style='color:{p['sub']};font-weight:bold;font-size:13px;'>— 平盘 {flat} 家 ({pct(flat):.1f}%)</span>　"
            f"<span style='color:{p['down']};font-weight:bold;font-size:13px;'>▼ 下跌 {down} 家 ({pct(down):.1f}%)</span>　"
            f"<span style='color:{p['text']};font-size:12px;'>共 {total} 品种 · 广度 {breadth*100:.0f}%</span>")
        # 扩展统计：中位数、标准差
        median_chg = float(pan["chg_pct"].median()) if not pan.empty else 0.0
        std_chg = float(pan["chg_pct"].std()) if len(pan) > 1 else 0.0
        self.breadth_ext_lbl.setText(
            f"<span style='color:{p['sub']};font-size:11px;'>中位数涨跌 {median_chg:+.2f}% · 标准差 {std_chg:.2f}% · "
            f"最大涨幅 {pan['chg_pct'].max():+.2f}% · 最大跌幅 {pan['chg_pct'].min():+.2f}%</span>")

        # 板块强度图（改为单行横向显示）
        agg = (pan_all.groupby("category")
                    .agg(mean_chg=("chg_pct", "mean"),
                         sum_flow=("fund_flow", "sum"),
                         count=("chg_pct", "count"))
                    .reset_index().sort_values("mean_chg", ascending=False))
        cats = agg["category"].tolist(); n = len(cats)
        # 清空旧布局
        while self.sector_lay.count():
            child = self.sector_lay.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        # 横向展示每个板块（使用 cat 而非枚举索引 i）
        p = pal()
        for idx, cat in enumerate(cats):
            row = agg[agg["category"] == cat].iloc[0]
            chg = row["mean_chg"]
            flow = row["sum_flow"]
            cnt = int(row["count"])
            # 板块名称标签
            name_lbl = QLabel(cat)
            name_lbl.setStyleSheet(f"font-size:12px;font-weight:bold;color:{p['text']};")
            self.sector_lay.addWidget(name_lbl)
            # 涨跌幅标签（带颜色）
            chg_color = p["up"] if chg >= 0 else p["down"]
            chg_lbl = QLabel(f"{chg:+.2f}%")
            chg_lbl.setStyleSheet(f"font-size:13px;font-weight:bold;color:{chg_color};background:{p['card']};padding:2px 8px;border-radius:4px;")
            self.sector_lay.addWidget(chg_lbl)
            # 资金流标签
            flow_color = p["up"] if flow >= 0 else p["down"]
            flow_lbl = QLabel(f"{flow:+.1f}亿")
            flow_lbl.setStyleSheet(f"font-size:11px;color:{flow_color};background:{p['card']};padding:2px 6px;border-radius:4px;")
            self.sector_lay.addWidget(flow_lbl)
            # 品种数标签
            cnt_lbl = QLabel(f"{cnt}只")
            cnt_lbl.setStyleSheet(f"font-size:11px;color:{p['sub']};background:{p['card']};padding:2px 6px;border-radius:4px;")
            self.sector_lay.addWidget(cnt_lbl)
            # 分隔线（最后一个板块后不加分隔）
            if idx < n - 1:
                sep = QLabel("│")
                sep.setStyleSheet(f"color:{p['border']};font-size:14px;")
                self.sector_lay.addWidget(sep)

        # 持仓异动（全市场，按 |oi_chg| 排序 Top 10）
        oi_sorted = pan_all.assign(abs_oi=pan_all["oi_chg"].abs()) \
            .sort_values("abs_oi", ascending=False).head(10)
        self.oi_tbl.set_rows([
            {"name": r["name"], "category": r["category"], "oi_chg": float(r["oi_chg"])}
            for _, r in oi_sorted.iterrows()
        ])

        # 基本面核心摘要：增仓首位 / 减仓首位 / 资金净流入首位 / 净增仓品种数（突出核心数据）
        if not pan_all.empty:
            inc_top = pan_all.loc[pan_all["oi_chg"].idxmax()]
            dec_top = pan_all.loc[pan_all["oi_chg"].idxmin()]
            fund_top = pan_all.loc[pan_all["fund_flow"].idxmax()]
            n_inc = int((pan_all["oi_chg"] > 0).sum())
            n_dec = int((pan_all["oi_chg"] < 0).sum())
            self._fund_kpi["inc"].set_value(f"{inc_top['name']}", pal()["up"], direction="up",
                                        tooltip=f"增仓首位：{inc_top['name']} · 持仓变化 {inc_top['oi_chg']:+.2f}%")
            self._fund_kpi["inc"].set_sub(f"持仓 {inc_top['oi_chg']:+.2f}%")
            self._fund_kpi["dec"].set_value(f"{dec_top['name']}", pal()["down"], direction="down",
                                        tooltip=f"减仓首位：{dec_top['name']} · 持仓变化 {dec_top['oi_chg']:+.2f}%")
            self._fund_kpi["dec"].set_sub(f"持仓 {dec_top['oi_chg']:+.2f}%")
            fund_dir = "up" if fund_top["fund_flow"] >= 0 else "down"
            self._fund_kpi["fund"].set_value(f"{fund_top['name']}",
                                             pal()["up"] if fund_top["fund_flow"] >= 0 else pal()["down"],
                                             direction=fund_dir,
                                             tooltip=f"资金净流入首位：{fund_top['name']} · 资金 {fund_top['fund_flow']:+.1f}亿")
            self._fund_kpi["fund"].set_sub(f"资金 {fund_top['fund_flow']:+.1f}亿")
            net_dir = "up" if n_inc >= n_dec else "down"
            self._fund_kpi["net"].set_value(f"{n_inc}", pal()["text"], direction=net_dir,
                                            tooltip=f"净增仓品种 {n_inc} 个 / 净减仓 {n_dec} 个")
            self._fund_kpi["net"].set_sub(f"增 {n_inc} · 减 {n_dec} 品种")

        # 子表实时条数标注（提升信息密度）
        self._oi_hdr.setText(
            f"持仓异动（{len(oi_sorted)} 条 · 按 |持仓变%| 排序，点击表头可重排）")
        # 榜单范围提示随板块筛选联动
        scope = "全市场" if self.cur_cat == "全部" else self.cur_cat
        self.rank_hint.setText(
            f"范围：{scope} · 领涨/领跌/资金流 各 Top 8 · 板块明细 {len(agg)} 板块 · "
            f"点击表头可排序（前三名奖牌色）")

        # 板块明细
        rows_sec = [
            {"category": r["category"], "mean_chg": float(r["mean_chg"]),
             "flow": float(r["sum_flow"]), "count": int(r["count"])}
            for _, r in agg.iterrows()
        ]
        self.sec_tbl.set_rows(rows_sec)
        self.sec_tbl.set_tooltip_template("{category} · 平均涨跌 {mean_chg:+.2f}% · 资金流 {flow:+.1f}亿 · {count}只")

        # 领涨 / 领跌 / 资金流（受板块筛选影响）
        if pan.empty:
            return
        top = pan.sort_values("chg_pct", ascending=False).head(8)
        bot = pan.sort_values("chg_pct", ascending=True).head(8)
        fl = pan.sort_values("fund_flow", ascending=False).head(8)
        rows_gain = [{"name": r["name"], "category": r["category"],
                      "chg": float(r["chg_pct"])} for _, r in top.iterrows()]
        self.gain_tbl.set_rows(rows_gain)
        self.gain_tbl.set_on_activate(self._on_rank_activated)
        self.gain_tbl.set_tooltip_template("{name} · {category} · 涨跌幅 {chg:+.2f}%")
        rows_lag = [{"name": r["name"], "category": r["category"],
                     "chg": float(r["chg_pct"])} for _, r in bot.iterrows()]
        self.lag_tbl.set_rows(rows_lag)
        self.lag_tbl.set_on_activate(self._on_rank_activated)
        self.lag_tbl.set_tooltip_template("{name} · {category} · 涨跌幅 {chg:+.2f}%")
        rows_flow = [{"name": r["name"], "category": r["category"],
                      "fund": float(r["fund_flow"])} for _, r in fl.iterrows()]
        self.flow_tbl.set_rows(rows_flow)
        self.flow_tbl.set_on_activate(self._on_rank_activated)
        self.flow_tbl.set_tooltip_template("{name} · {category} · 资金流 {fund:+.1f}亿")

    # ---- 资讯 + 资讯解读 ----
    def _run_news(self):
        """运行news。"""
        if getattr(self, "_news_running", False):
            return
        self._news_running = True
        self.news_btn.setEnabled(False)
        self.news_btn.setText("解读中…")
        self.news_status.setText("正在并发爬取 11 个财经资讯源（财联社/东方财富/和讯/同花顺/"
                                  "华尔街见闻/金十/新浪财经/期货日报/中证网/证券时报/凤凰财经）…")

        def work():
            """处理work。"""
            news = news_feed.fetch_all_news(limit=60)
            # 市场级 云端研判
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
            """处理done。
            
                参数:
                    payload"""
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
                f"已更新 {ts} · 抓取 {total} 条 · 信源覆盖 {active}/{tsrc}{conf_txt} · 云端研判完成")
            self._restore_news_btn()

        def err(msg):
            """处理err。
            
                参数:
                    msg"""
            self.news_status.setText(f"资讯获取失败：{msg}（将使用已有缓存或稍后重试）")
            self._restore_news_btn()

        self._run_worker(work, done, err)

    def _restore_news_btn(self):
        """处理restorenewsbtn。"""
        self._news_running = False
        self.news_btn.setEnabled(True)
        self.news_btn.setText("KP资讯解读")

    def _on_rank_activated(self, row: dict) -> None:
        """领涨/领跌/资金流榜单点击回调：同步到 symbol/period 并刷新。

            参数:
                row: dict，含 name/category/chg 等字段"""
        name = row.get("name", "")
        for r in self.mdm.universe:
            if r[1] == name:
                idx = self.sym_cb.findData(symbol_code(r))
                if idx >= 0:
                    self.sym_cb.setCurrentIndex(idx)
                break

    def _fill_news(self, news, analysis, sd_rows, tech=None):
        """处理fillnews。
        
            参数:
                news
                analysis
                sd_rows
                tech"""
        self._sd_rows = sd_rows
        p = pal()

        # 精简研判摘要：由财经资讯直接推导「结果 / 趋势」，不再罗列新闻列表
        self._fill_summary(news, analysis, p)

        # 保存并渲染（综合研判 + 技术面解读）
        self._ai_analysis = analysis
        self._tech = tech
        self._render_ai(analysis, tech)

        # 供需 / 库存信号表（RankTable：排名列 + 信号强度比例条 + 点击排序）
        # 方向 + 研判 合并为单「信号」列（如「▲ 偏紧 · 去库利多」），降低列宽压力、提升可读性
        sd_out = []
        for (c, bias, matched, samples) in sd_rows:
            if bias > 0.05:
                direction, verdict = "▲ 偏紧", "去库利多"
            elif bias < -0.05:
                direction, verdict = "▼ 宽松", "累库利空"
            else:
                direction, verdict = "● 平衡", "供需平衡"
            sd_out.append({
                "cat": c,
                "strength": float(bias),
                "strength_txt": f"{bias*100:+.0f}%",
                "signal": f"{direction} {verdict}",
                "sample": (samples[0] if samples else "—"),
            })
        self.sd_tbl.set_rows(sd_out)
        self._sd_hdr.setText(
            f"供需 / 库存信号（{len(sd_out)} 个板块 · 财经资讯 云端研判）")

    # ------------------------------------------------------------------
    # 精简研判摘要：直接呈现「由财经资讯推导出的结果 / 趋势」
    # ------------------------------------------------------------------
    def _fill_summary(self, news: dict, analysis: dict, p: dict) -> None:
        """根据多源资讯与 AI 研判，生成一行精简摘要（方向 + 依据 + 关键事件）。

        参数:
            news: 抓取到的多源资讯
            analysis: ai_analyze_news 返回的研判结果
            p: 主题调色板"""
        items = news.get("items", [])
        total = len(items)
        cov = analysis.get("source_coverage") or news.get("source_coverage") or {}
        active = cov.get("active_sources", 0)
        tsrc = cov.get("total_sources", 0)
        conf = analysis.get("confidence")
        bias = float(analysis.get("weighted_bias") or 0.0)
        if bias > 0.05:
            direction, dcol = "偏多", p["up"]
        elif bias < -0.05:
            direction, dcol = "偏空", p["down"]
        else:
            direction, dcol = "中性", p["sub"]
        arrow = "▲" if bias > 0.05 else ("▼" if bias < -0.05 else "●")
        conf_txt = f" · 综合置信度 {conf*100:.0f}%" if isinstance(conf, (int, float)) else ""
        src_txt = (f"依据 <b>{total}</b> 条资讯 / <b>{active}/{tsrc}</b> 信源{conf_txt}，"
                   f"资讯面整体<b style='color:{dcol}'>{direction} {arrow}</b>。")

        # 一句话研判（brief 已由 LLM/规则合成，含方向与关键矛盾）
        brief = (analysis.get("brief") or "").strip()
        # 关键驱动事件（Top 3）—— 兼容 dict / str 两种元素格式
        kes = analysis.get("key_events") or []
        kes_html = ""
        if kes:
            li = []
            for k in kes[:3]:
                if isinstance(k, dict):
                    li.append(f"<li style='margin:1px 0'>{self._escape(k.get('title', ''))}"
                              f"<span style='color:{p['sub']}'>（{self._escape(k.get('source', ''))}·"
                              f"{k.get('sentiment', '')}）</span></li>")
                else:
                    li.append(f"<li style='margin:1px 0'>{self._escape(k)}</li>")
            lis = "".join(li)
            kes_html = (f"<p style='margin:4px 0 0'><b style='color:{p['text']}'>"
                        f"🔑 关键驱动事件</b></p>"
                        f"<ul style='margin:2px 0;padding-left:18px;font-size:12.5px'>{lis}</ul>")
        # 可操作洞察（兼容 LLM 返回字符串或列表两种形态）
        act_raw = analysis.get("actionable_insights") or ""
        if isinstance(act_raw, list):
            act = "；".join(str(x) for x in act_raw)
        else:
            act = str(act_raw).strip()
        act_html = (f"<p style='margin:4px 0 0'><b style='color:#f59e0b'>🎯 关注建议</b> {act}</p>"
                    if act else "")

        self.news_summary.setStyleSheet(
            f"background:{p['card']};border:1px solid {p['border']};"
            f"border-radius:8px;padding:8px 10px;")
        # QLabel 通过 setText 承载富文本（无 setHtml 方法）
        self.news_summary.setTextFormat(Qt.TextFormat.RichText)
        self.news_summary.setText(
            f"<div style='font-size:13px;line-height:1.6;color:{p['text']}'>"
            f"{src_txt}"
            + (f"<p style='margin:4px 0 0'>{brief}</p>" if brief else "")
            + kes_html + act_html + "</div>")

    @staticmethod
    def _escape(text: str) -> str:
        """转义 HTML 特殊字符，避免资讯标题破坏摘要排版。"""
        return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

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
        # 核心驱动因素（兼容 LLM 返回字符串 / 列表两种形态）
        drivers = a.get("drivers") or []
        if not isinstance(drivers, list):
            drivers = [drivers]
        if drivers:
            d_html = "".join(
                f"<li style='margin:1px 0'>{self._escape(d)}</li>" for d in drivers)
            parts.append(
                f"<p style='margin:6px 0'><b style='color:#8b5cf6'>🧩 核心驱动因素</b></p>"
                f"<ul style='margin:2px 0;padding-left:18px;font-size:12.5px;line-height:1.5'>"
                f"{d_html}</ul>")
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
        # 情景分析（乐观 / 中性 / 悲观三档概率）
        sc = a.get("scenarios") or {}
        if sc:
            parts.append(self._scenarios_html(sc, p))
        # 趋势预测与综合研判依据（融合技术面 + 资讯面）
        parts.append(self._outlook_html(a, tech))
        if risk:
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['up']}'>⚠️ 风险提示</b><br>{risk}</p>")
        if sugg:
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['down']}'>💡 关注建议</b><br>{sugg}</p>")
        if kes:
            li = []
            for k in kes[:6]:
                if isinstance(k, dict):
                    li.append(f"<li style='margin:1px 0'>{self._escape(k.get('title', ''))}"
                              f"<span style='color:{p['sub']}'>（{self._escape(k.get('source', ''))}·"
                              f"{k.get('sentiment', '')}）</span></li>")
                else:
                    li.append(f"<li style='margin:1px 0'>{self._escape(k)}</li>")
            items = "".join(li)
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['text']}'>🔑 关键事件</b></p>"
                         f"<ul style='margin:2px 0;padding-left:18px'>{items}</ul>")
        # 关注品种与逻辑（兼容 LLM 返回字符串 / 列表两种形态）
        wl = a.get("watchlist") or []
        if not isinstance(wl, list):
            wl = [wl]
        if wl:
            wl_html = " ".join(
                f"<span style='background:{p['card']};border:1px solid {p['border']};"
                f"border-radius:6px;padding:2px 8px;margin:1px;display:inline-block;"
                f"font-size:12px;color:{p['text']}'>👁 {self._escape(w)}</span>"
                for w in wl)
            parts.append(f"<p style='margin:6px 0'><b style='color:{p['text']}'>👁 关注品种</b><br>{wl_html}</p>")
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
        """处理globalframeworkhtml。"""
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
        """处理bullbearhtml。
        
            参数:
                tech
                consensus
                wbias"""
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
        """处理outlookhtml。
        
            参数:
                a
                tech"""
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
    # 情景分析（乐观 / 中性 / 悲观三档概率条）
    # ------------------------------------------------------------------
    def _scenarios_html(self, sc: dict, p: dict) -> str:
        """渲染情景分析（乐观 / 中性 / 悲观三档概率条）。

        兼容 LLM 返回字典 {optimistic, base, pessimistic} 或列表（按顺序映射）两种形态。

            参数:
                sc: 三档情景（dict 或 list）
                p: 主题调色板"""
        if isinstance(sc, list):
            # 模型可能返回三档列表，按顺序映射到 乐观/中性/悲观
            labels = ["乐观", "中性", "悲观"]
            cols = [p["up"], "#f59e0b", p["down"]]
            rows = []
            for i in range(3):
                item = sc[i] if i < len(sc) and isinstance(sc[i], dict) else {}
                rows.append((labels[i], item, cols[i]))
        elif isinstance(sc, dict):
            rows = [
                ("乐观", sc.get("optimistic", {}) or {}, p["up"]),
                ("中性", sc.get("base", {}) or {}, "#f59e0b"),
                ("悲观", sc.get("pessimistic", {}) or {}, p["down"]),
            ]
        else:
            return ""
        blocks = []
        for label, item, col in rows:
            if not isinstance(item, dict):
                item = {}
            prob = float(item.get("p", 0.0) or 0.0)
            desc = self._escape(item.get("desc", ""))
            pct = max(0.0, min(100.0, prob * 100))
            blocks.append(
                f"<div style='margin:4px 0'>"
                f"<div style='display:flex;justify-content:space-between;font-size:12px;"
                f"color:{p['text']}'><span>{label}</span><b>{pct:.0f}%</b></div>"
                f"<div style='position:relative;height:10px;border-radius:5px;overflow:hidden;"
                f"background:{p['card']};margin-top:2px'>"
                f"<div style='position:absolute;left:0;top:0;bottom:0;width:{pct:.0f}%;"
                f"background:{col};'></div></div>"
                f"<div style='font-size:11px;color:{p['sub']};margin-top:1px'>{desc}</div>"
                f"</div>")
        return (f"<p style='margin:6px 0'><b style='color:#10b981'>🎲 情景分析</b></p>"
                f"<div style='font-size:12.5px;line-height:1.4'>{''.join(blocks)}</div>")

    # ------------------------------------------------------------------
    # 技术面研判计算（当前品种：均线 / MACD / 布林 / KDJ / RSI / OBV / 支撑阻力 / 多空力）
    # ------------------------------------------------------------------
    def _compute_technical(self, symbol, period, news_bias=0.0):
        """计算technical。
        
            参数:
                symbol
                period
                news_bias"""
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
            # 量能诊断（量比 + 量价背离）
            vol = ind["volume"].astype(float)
            vol_ma = float(vol.iloc[-20:].mean()) if len(vol) >= 20 else float(vol.mean())
            vol_recent = float(vol.iloc[-5:].mean())
            vol_ratio = (vol_recent / vol_ma) if vol_ma else 1.0
            price_up = last >= float(ind["close"].iloc[-2])
            # 价涨而 OBV 走平/下行，或价跌而 OBV 上行 → 量价背离
            vol_divergence = (price_up and not obv_bull) or ((not price_up) and obv_bull)
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
            # 趋势强度标签（依赖 force，须在 force 定义之后计算）
            if force > 35:
                strength_label = "强多"
            elif force > 15:
                strength_label = "震荡偏多"
            elif force < -35:
                strength_label = "强空"
            elif force < -15:
                strength_label = "震荡偏空"
            else:
                strength_label = "中性震荡"
            # 交易计划（依 force 与支撑/阻力推导具体入场/止损/目标）
            stop_long = supports[0] if supports else round(last * 0.98, 2)
            entry_long = round((last + supports[0]) / 2, 2) if supports else last
            target_long = resist[0] if resist else round(last * 1.02, 2)
            entry_short = round((last + resist[0]) / 2, 2) if resist else last
            stop_short = resist[0] if resist else round(last * 1.02, 2)
            trade_plan = {
                "direction": "多" if force > 0 else ("空" if force < 0 else "观望"),
                "entry_long": entry_long, "stop_long": stop_long,
                "target_long": target_long,
                "entry_short": entry_short, "stop_short": stop_short,
            }
            return {
                "last": last, "ma": ma, "bull_align": bull_align, "bear_align": bear_align,
                "dif": dif, "dea": dea, "hist": hist, "golden": golden, "death": death,
                "macd_bull": macd_bull,
                "bup": bup, "bmid": bmid, "blow": blow, "band_w": band_w,
                "band_expand": band_expand, "pct_b": pct_b, "above_mid": above_mid,
                "k": k, "d": d, "j": j, "kdj_over": kdj_over, "kdj_under": kdj_under,
                "rsi6": rsi6, "rsi14": rsi14, "rsi_over": rsi_over, "rsi_under": rsi_under,
                "obv_bull": obv_bull, "obv_slope": obv_slope,
                "vol_ratio": vol_ratio, "vol_divergence": vol_divergence,
                "strength_label": strength_label,
                "supports": supports, "resist": resist,
                "score": score, "force": force, "news_bias": news_bias,
                "trade_plan": trade_plan,
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 技术面解读 HTML（逐指标解读 + 支撑阻力）
    # ------------------------------------------------------------------
    def _render_tech(self, tech):
        """渲染tech。
        
            参数:
                tech"""
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
        # OBV 量能 + 量能诊断
        vol_ratio = float(tech.get("vol_ratio", 1.0))
        vol_div = bool(tech.get("vol_divergence", False))
        obv_lines = (
            f"<li>OBV 近 10 根 {'走高' if tech['obv_bull'] else '走低'}，"
            f"量能{'配合价格上涨（量价齐升）' if tech['obv_bull'] else '配合价格下跌（量价齐跌）'}"
            f"，斜率 {tech['obv_slope']:+.0f}。</li>"
            f"<li>近 5 根均量 / 20 根均量 = <b>{vol_ratio:.2f}</b>"
            f"（{'放量' if vol_ratio > 1.2 else '缩量' if vol_ratio < 0.8 else '温和'}）。</li>"
        )
        if vol_div:
            obv_lines += ("<li style='color:#f59e0b'><b>⚠ 量价背离</b>："
                          "价格与 OBV 方向不一致，当前趋势持续性存疑，警惕反转。</li>")
        # 支撑阻力
        sup_txt = "、".join(f"{x:,.2f}" for x in tech["supports"][:4]) or "—"
        res_txt = "、".join(f"{x:,.2f}" for x in tech["resist"][:4]) or "—"
        sr_lines = (
            f"<li><span style='color:{p['up']}'>支撑位</span>：{sup_txt}</li>"
            f"<li><span style='color:{p['down']}'>阻力位</span>：{res_txt}</li>"
        )
        # 交易计划（依 force 与支撑/阻力推导）
        tp = tech.get("trade_plan", {}) or {}
        fv = tech["force"]
        strength = tech.get("strength_label") or (
            "强多" if fv > 35 else "震荡偏多" if fv > 15
            else "强空" if fv < -35 else "震荡偏空" if fv < -15 else "中性震荡")
        if fv > 0:
            plan_lines = (
                f"<li>倾向<b style='color:{p['up']}'>低吸 / 逢回调做多</b>："
                f"回踩支撑 <b>{tp.get('entry_long')}</b> 附近分批介入，"
                f"止损 <b>{tp.get('stop_long')}</b>（跌破支撑），"
                f"目标 <b>{tp.get('target_long')}</b>（上方阻力）。</li>"
            )
        elif fv < 0:
            plan_lines = (
                f"<li>倾向<b style='color:{p['down']}'>高抛 / 逢高做空</b>："
                f"反弹至 <b>{tp.get('entry_short')}</b> 附近承压则空，"
                f"止损 <b>{tp.get('stop_short')}</b>（突破阻力），"
                f"目标 <b>{tp.get('stop_long')}</b>（下方支撑）。</li>"
            )
        else:
            plan_lines = ("<li>方向不明，建议<b>区间波段、轻仓观望</b>，"
                          "等待价格有效突破阻力或跌破支撑后再顺势跟进。</li>")
        plan_lines += (
            f"<li>技术综合力 <b>{fv:+.0f}</b>、资讯偏置 <b>{tech.get('news_bias', 0):+.2f}</b>："
            f"若与右侧 AI 综合研判<b>一致</b>则信号共振、可信度提升；"
            f"若<b>背离</b>则降低仓位、等待确认。</li>"
        )
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

            <p style='margin:6px 0 2px'><b style='color:#8b5cf6'>七、趋势强度与综合结论</b></p>
            <p style='margin:2px 0'>趋势强度判定为 <b>{strength}</b>；
            技术多空力评分 <b>{tech['score']:+.0f}</b>（±100），
            结合资讯偏置后综合力 <b>{tech['force']:+.0f}</b>。
            与右侧 AI 综合研判方向一致时信号共振、可信度提升；背离时降低仓位、等待确认。</p>

            <p style='margin:6px 0 2px'><b style='color:#8b5cf6'>八、交易计划（入场 / 止损 / 目标）</b></p>
            <ul style='margin:2px 0 6px;padding-left:18px'>{plan_lines}</ul>

            <p style='margin:6px 0 2px'><b style='color:#8b5cf6'>九、关键触发条件</b></p>
            <p style='margin:2px 0'>价格<b>有效突破</b>阻力 <span style='color:{p['down']}'>{res_txt}</span>
            则打开上行空间（可顺势跟随）；<b>有效跌破</b>支撑 <span style='color:{p['up']}'>{sup_txt}</span>
            则趋势转弱（需减仓 / 严格止损）。</p>
        </div>
        """

    # ------------------------------------------------------------------
    # 仅重算技术面（切换合约 / 周期时调用，避免重复抓取资讯）
    # ------------------------------------------------------------------
    def _refresh_tech(self):
        """刷新tech。"""
        if self._ai_analysis is None:
            return
        nb = _news_overall_bias(self._news) if self._news else 0.0
        tech = self._compute_technical(self.cur_symbol, self.cur_period, news_bias=nb)
        self._tech = tech
        self._render_ai(self._ai_analysis, tech)

    # ---- 工具 ----
    def _set(self, table, r, c, text, color=None):
        """设置相关对象。
        
            参数:
                table
                r
                c
                text
                color"""
        it = QTableWidgetItem(str(text))
        fg = (QColor(color) if isinstance(color, str) else color) if color is not None \
            else QColor(pal()["text"])
        it.setForeground(fg)
        table.setItem(r, c, it)
        return it

    def _on_pick(self, item):
        """处理onpick。
        
            参数:
                item"""
        name = self.watch.item(item.row(), 0).text()
        for r in self.mdm.universe:
            if r[1] == name:
                idx = self.sym_cb.findData(symbol_code(r))
                if idx >= 0:
                    self.sym_cb.setCurrentIndex(idx)
                break

    def set_theme(self, t: str) -> None:
        """设置主题。
        
            参数:
                t: str"""
        super().set_theme(t)
        self._style_cards()
        self.temp_lbl.setStyleSheet("color:%s;" % pal()["sub"])
        for tl in self.status_tiles:
            tl.set_theme(t)
        # 用新主题色重渲染资讯列表与 云端研判（含四状态灯已随 tiles 更新）
        if self._news is not None:
            self._fill_news(self._news, self._ai_analysis,
                            self._sd_rows, self._tech)
