"""实盘监控页（只读）。

定位（按路线图方向二·2.2）：
    - 只读监控面板：实时真实行情 + 持仓 / 委托监控原型；
    - 交易侧**绝不**在此实现（系统定位为「分析预测」，不做自动交易，见 docs/ctp_wiring.md）。

本页能力：
    1) 柜台连接状态卡：数据源 / 连接状态 / 模式（SimNow 仿真 / 期货公司实盘 / 合成回退）；
    2) 诊断面板：ctp_diagnose() 展示「还差什么才能连上」（CTP 库 / 凭据 / 模式 / 订阅列表）；
    3) 订阅合约实时盘口表：由 MarketDataManager 的行情回报驱动刷新；
    4) 持仓 / 委托只读占位：明确标注「交易侧未启用」。

⚠️ 本沙箱默认数据源为 sina（真实日线），CTP 未配置时盘口取自当前源；
   配置好 ctp_settings.json 并点击「连接柜台」后，将切换为 CTP 实时盘口（需本机装有 CTP 库）。
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from .pages import BasePage
from .widgets import PageHeader, Badge, SectionHeader, prepare_table, color_pnl, pal
from .pages import symbol_code
from ..data.market_data import MarketDataManager
from ..data.ctp_gateway import ctp_diagnose


class CTPMonitorPage(BasePage):
    """实盘监控（只读）。"""

    def __init__(self, mdm: MarketDataManager, store, config=None, session=None) -> None:
        """初始化相关对象。
        
            参数:
                mdm: MarketDataManager
                store
                config
                session"""
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "ctp"
        self._watch: list[str] = []
        self._build()
        # 接入行情中枢信号（盘口刷新 / 状态变化）
        self.mdm.quote_updated.connect(self._on_quote)
        self.mdm.bar_arrived.connect(self._on_bar)
        self.mdm.status_changed.connect(self._on_status)
        # 首次填充
        self._refresh_diag()
        self._refresh_status()
        self._build_watch()
        self._refresh_quotes()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        """构建相关对象。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "实盘监控（只读）",
            "CTP / SimNow 柜台连接状态 · 订阅合约实时盘口 · 持仓委托只读原型"))

        # ---- 连接状态卡 ----
        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(10, 8, 10, 8); cl.setSpacing(6)
        ctl = QHBoxLayout()
        self.src_badge = Badge("数据源：—", bg=pal()["badge_bg"], fg=pal()["text"])
        self.mode_badge = Badge("模式：—", bg=pal()["badge_bg"], fg=pal()["text"])
        self.status_dot = QLabel("● 离线"); self.status_dot.setObjectName("status-dot")
        self.status_lbl = QLabel("—")
        ctl.addWidget(QLabel("柜台连接"))
        ctl.addWidget(self.src_badge)
        ctl.addWidget(self.mode_badge)
        ctl.addWidget(self.status_dot)
        ctl.addWidget(self.status_lbl, 1)
        cl.addLayout(ctl)

        btn = QHBoxLayout()
        self.connect_btn = QPushButton("连接柜台")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self._on_connect)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setObjectName("secondary")
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        self.diag_btn = QPushButton("重新诊断")
        self.diag_btn.setObjectName("secondary")
        self.diag_btn.clicked.connect(self._refresh_diag)
        self.refresh_btn = QPushButton("刷新盘口")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self._refresh_quotes)
        btn.addWidget(self.connect_btn)
        btn.addWidget(self.disconnect_btn)
        btn.addWidget(self.diag_btn)
        btn.addWidget(self.refresh_btn)
        btn.addStretch(1)
        cl.addLayout(btn)
        root.addWidget(card)

        # ---- 诊断卡 ----
        dcard = QFrame(); dcard.setObjectName("card")
        dl = QVBoxLayout(dcard); dl.setContentsMargins(10, 8, 10, 8); dl.setSpacing(4)
        dl.addWidget(SectionHeader("连接诊断（还差什么才能连上柜台）",
                                   accent="#f59e0b"))
        self.diag_lbl = QLabel("—")
        self.diag_lbl.setObjectName("hint")
        self.diag_lbl.setWordWrap(True)
        dl.addWidget(self.diag_lbl)
        root.addWidget(dcard)

        # ---- 订阅合约盘口表 ----
        qcard = QFrame(); qcard.setObjectName("card")
        ql = QVBoxLayout(qcard); ql.setContentsMargins(10, 8, 10, 8); ql.setSpacing(4)
        self.watch_hdr = SectionHeader("订阅合约实时盘口", accent="#3b82f6",
                                       badge="实时盘口")
        ql.addWidget(self.watch_hdr)
        self.qtable = QTableWidget(0, 7)
        self.qtable.setHorizontalHeaderLabels(
            ["合约", "最新价", "涨跌幅%", "成交量", "持仓量", "资金流(亿)", "数据源"])
        self.qtable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.qtable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        ql.addWidget(self.qtable, 1)
        root.addWidget(qcard, 1)

        # ---- 持仓 / 委托只读占位 ----
        pcard = QFrame(); pcard.setObjectName("card")
        pl = QVBoxLayout(pcard); pl.setContentsMargins(10, 8, 10, 8); pl.setSpacing(4)
        pl.addWidget(SectionHeader("持仓 / 委托（只读原型）", accent="#8b5cf6"))
        note = QLabel("⚠️ 交易侧未启用：本系统定位为「行情分析 / KP预测 / 量化研判」，"
                      "不做自动交易。下单、持仓、委托功能需用户明确确认后另行开发，"
                      "且须在期货公司模拟盘充分验证风控（见 docs/ctp_wiring.md）。")
        note.setObjectName("hint"); note.setWordWrap(True)
        pl.addWidget(note)
        self.pos_lbl = QLabel("当前无持仓 / 委托数据（只读占位）")
        pl.addWidget(self.pos_lbl)
        root.addWidget(pcard)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _build_watch(self) -> None:
        """构建watch。"""
        diag = ctp_diagnose()
        sub = diag.get("subscribe") or []
        # 仅保留行情中枢 universe 内存在的合约；为空则用前 5 个作为演示
        universe_codes = {symbol_code(r) for r in self.mdm.universe}
        watch = [s for s in sub if s in universe_codes]
        if not watch:
            watch = [symbol_code(r) for r in self.mdm.universe[:5]]
        self._watch = watch
        self.watch_hdr.set_badge(f"{len(watch)} 合约")
        self.qtable.setRowCount(len(watch))
        for i, sym in enumerate(watch):
            self.qtable.setItem(i, 0, QTableWidgetItem(sym))
            for c in range(1, 7):
                self.qtable.setItem(i, c, QTableWidgetItem("--"))
            self._set_row(sym, i)

    def _set_row(self, sym: str, row: int) -> None:
        """设置行。
        
            参数:
                sym: str
                row: int"""
        q = self.mdm.get_quote(sym)
        if not q:
            return
        last = q.get("last", 0.0)
        pct = q.get("chg_pct", 0.0)
        self.qtable.setItem(row, 1, QTableWidgetItem(f"{last:.2f}"))
        it = QTableWidgetItem(f"{pct:+.2f}")
        color_pnl(it, pct)
        self.qtable.setItem(row, 2, it)
        self.qtable.setItem(row, 3, QTableWidgetItem(f"{q.get('volume', 0):,.0f}"))
        self.qtable.setItem(row, 4, QTableWidgetItem(f"{q.get('open_interest', 0):,.0f}"))
        self.qtable.setItem(row, 5, QTableWidgetItem(f"{q.get('fund_flow', 0):.3f}"))
        self.qtable.setItem(row, 6, QTableWidgetItem(self.mdm.source_label))

    def _refresh_quotes(self) -> None:
        """刷新quotes。"""
        for i, sym in enumerate(self._watch):
            self._set_row(sym, i)

    # ------------------------------------------------------------------
    # 状态 / 诊断
    # ------------------------------------------------------------------
    def _refresh_status(self) -> None:
        """刷新状态。"""
        diag = ctp_diagnose()
        self.src_badge.set_text(f"数据源：{self.mdm.source_label}")
        self.mode_badge.set_text(f"模式：{diag.get('mode_label', '—')}")
        connected = getattr(self.mdm, "is_real", False)
        if connected:
            self.status_dot.setText("● 已连接")
            self.status_dot.setStyleSheet(f"color:{pal()['up']};")
        else:
            self.status_dot.setText("● 离线")
            self.status_dot.setStyleSheet(f"color:{pal()['down']};")
        self.status_lbl.setText(self.mdm.status)

    def _refresh_diag(self) -> None:
        """刷新diag。"""
        d = ctp_diagnose()
        lines = []
        lib = "✅ 已安装" if d["lib_available"] else "❌ 未安装"
        lines.append(f"CTP 库：{lib}（{d.get('lib_name') or 'vnpy_ctp / ctpbee'}）")
        cred = "✅ 完整" if d["creds_complete"] else "❌ 不完整（请配置 ctp_settings.json）"
        lines.append(f"凭据：{cred}")
        lines.append(f"模式：{d.get('mode_label', '—')}")
        subs = d.get("subscribe") or []
        lines.append(f"订阅合约：{len(subs)} 个（{', '.join(subs) if subs else '无'}）")
        if not d["lib_available"]:
            lines.append("→ 安装：pip install vnpy_ctp  或  pip install ctpbee（并准备期货公司 CTP 动态库）")
        if not d["creds_complete"]:
            lines.append("→ 复制 config/ctp_settings.example.json 为 ctp_settings.json 并填入你的柜台账号/密码/前置机")
        lines.append("→ 自动连接：在 config/settings.json 把 data.source 设为 \"ctp\"（本页「连接柜台」按钮亦可手动触发）")
        self.diag_lbl.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_connect(self) -> None:
        """处理onconnect。"""
        self.mdm.connect()
        self._refresh_status()
        self._refresh_diag()

    def _on_disconnect(self) -> None:
        """处理ondisconnect。"""
        self.mdm.disconnect()
        self._refresh_status()

    def _on_quote(self, sym: str) -> None:
        """处理onquote。
        
            参数:
                sym: str"""
        if sym in self._watch:
            self._set_row(sym, self._watch.index(sym))

    def _on_bar(self, bar) -> None:
        """处理onK线。
        
            参数:
                bar"""
        sym = bar.get("symbol") if isinstance(bar, dict) else None
        if sym and sym in self._watch:
            self._set_row(sym, self._watch.index(sym))

    def _on_status(self, text: str) -> None:
        """处理on状态。
        
            参数:
                text: str"""
        self.status_lbl.setText(text)
        self._refresh_status()
        self._toast(f"📡 连接状态：{text}", duration=3000)
