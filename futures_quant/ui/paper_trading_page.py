"""M1.5 持仓模拟页：模拟账户资金 / 保证金占用 / 风险度仪表盘（>80% 红色告警）。

设计（离线优先、零额外依赖）：
- 逻辑层走 ``broker.paper_portfolio.PaperPortfolio``（资金 / 保证金 / 风险度），
  本页面只做展示与交互（开平仓 / 盯市 / 仪表盘刷新）。
- 主题感知：风险度色块用 ``pal()`` 取色，safe→绿、warn→黄、danger→红。
- 风险提示语（护栏 7）：页首固定「历史表现不代表未来，不构成任何投资建议」。

用法（与 BasePage 一致，由 MainWindow 注入 mdm / store）：
    page = PaperTradingPage(mdm, store)
    page.reload()   # 刷新资金 / 保证金 / 风险度仪表盘
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox, QComboBox,
    QGroupBox,
)

from .pages import BasePage
from .widgets import PageHeader, StatCard, pal
from ..broker.paper_portfolio import PaperPortfolio


def _risk_color(level: str) -> str:
    """风险度等级 → 颜色（safe 绿 / warn 黄 / danger 红）。

    参数:
        level: "safe" / "warn" / "danger"。

    返回:
        str: 十六进制颜色值（取自当前主题 pal）。
    """
    p = pal()
    if level == "danger":
        return p["up"]
    if level == "warn":
        return "#f59e0b"
    return p["down"]


class PaperTradingPage(BasePage):
    """持仓模拟页（资金 / 保证金 / 风险度仪表盘）。"""

    def __init__(self, mdm, store, config=None, session=None) -> None:
        """初始化持仓模拟页。

        参数:
            mdm: MarketDataManager（本页面不依赖其数据，仅走 BasePage 契约）。
            store: AnalysisStore（同上）。
            config: 配置（可选）。
            session: 会话（可选）。"""
        super().__init__(mdm, store, config, session)
        self._portfolio = PaperPortfolio(cash=1_000_000.0, multiplier=10.0,
                                         margin_rate=0.10, commission=0.0)
        self._build()

    # ---------------- 布局 ----------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        root.addWidget(PageHeader("持仓模拟",
                                  "模拟账户资金 · 保证金占用 · 风险度仪表盘（历史表现不代表未来，不构成任何投资建议）"))

        # 参数设置
        param_box = QGroupBox("模拟参数")
        form = QFormLayout(param_box)
        self.spin_cash = QDoubleSpinBox()
        self.spin_cash.setRange(0.0, 1e9)
        self.spin_cash.setValue(1_000_000.0)
        self.spin_cash.setDecimals(0)
        self.spin_mult = QDoubleSpinBox()
        self.spin_mult.setRange(0.0, 1e6)
        self.spin_mult.setValue(10.0)
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 1.0)
        self.spin_margin.setSingleStep(0.01)
        self.spin_margin.setValue(0.10)
        form.addRow("初始资金", self.spin_cash)
        form.addRow("合约乘数", self.spin_mult)
        form.addRow("保证金率", self.spin_margin)
        self.btn_reset = QPushButton("重置组合")
        self.btn_reset.clicked.connect(self._reset)
        form.addRow(self.btn_reset)
        root.addWidget(param_box)

        # 交易区
        trade_box = QGroupBox("模拟交易")
        tf = QFormLayout(trade_box)
        self.spin_price = QDoubleSpinBox()
        self.spin_price.setRange(0.0, 1e7)
        self.spin_price.setValue(100.0)
        self.spin_lots = QSpinBox()
        self.spin_lots.setRange(0, 10000)
        self.spin_lots.setValue(1)
        tf.addRow("当前/成交价", self.spin_price)
        tf.addRow("手数", self.spin_lots)
        row = QHBoxLayout()
        self.btn_open_long = QPushButton("开多")
        self.btn_open_short = QPushButton("开空")
        self.btn_close_long = QPushButton("平多")
        self.btn_close_short = QPushButton("平空")
        self.btn_open_long.clicked.connect(lambda: self._trade("open_long"))
        self.btn_open_short.clicked.connect(lambda: self._trade("open_short"))
        self.btn_close_long.clicked.connect(lambda: self._trade("close_long"))
        self.btn_close_short.clicked.connect(lambda: self._trade("close_short"))
        for b in (self.btn_open_long, self.btn_open_short,
                  self.btn_close_long, self.btn_close_short):
            row.addWidget(b)
        tf.addRow(row)
        root.addWidget(trade_box)

        # 风险度仪表盘
        dash_box = QGroupBox("风险度仪表盘")
        grid = QGridLayout(dash_box)
        self.stat_cash = StatCard("可用资金", "—")
        self.stat_equity = StatCard("账户权益", "—")
        self.stat_margin = StatCard("保证金占用", "—")
        self.stat_risk = StatCard("风险度", "—")
        grid.addWidget(self.stat_cash, 0, 0)
        grid.addWidget(self.stat_equity, 0, 1)
        grid.addWidget(self.stat_margin, 1, 0)
        grid.addWidget(self.stat_risk, 1, 1)
        root.addWidget(dash_box)

        # 持仓明细
        self.pos_label = QLabel("当前持仓：空仓")
        self.pos_label.setWordWrap(True)
        root.addWidget(self.pos_label)
        root.addStretch(1)

        self.reload()

    # ---------------- 行为 ----------------
    def reload(self) -> None:
        """刷新仪表盘（offscreen 构造即调用，无网络、无真实数据依赖）。"""
        s = self._portfolio.summary()
        self._refresh_cards(s)

    def _refresh_cards(self, s: dict) -> None:
        p = pal()
        init = s.get("initial_cash", 0.0)
        cash = s.get("cash", 0.0)
        equity = s.get("equity", 0.0)
        # 资金 / 权益：高于初始 → 涨色（红），低于 → 跌色（绿）
        self.stat_cash.set_value(f"{cash:,.0f}",
                                 color=p["up"] if cash >= init else p["down"],
                                 direction="up" if cash >= init else "down")
        self.stat_equity.set_value(f"{equity:,.0f}",
                                   color=p["up"] if equity >= init else p["down"],
                                   direction="up" if equity >= init else "down")
        self.stat_margin.set_value(f"{s.get('margin_used', 0.0):,.0f}",
                                    color=p["sub"])
        # 风险度：等级色（safe 绿 / warn 黄 / danger 红）
        level = s.get("level", "safe")
        self.stat_risk.set_value(f"{s.get('risk_degree', 0.0) * 100:.1f}%",
                                  color=_risk_color(level))
        # 持仓文字
        ll, sl = s.get("long_lots", 0), s.get("short_lots", 0)
        if ll or sl:
            self.pos_label.setText(
                f"当前持仓：多头 {ll} 手 / 空头 {sl} 手　"
                f"（风险度 {s.get('risk_degree', 0) * 100:.1f}%，"
                f"{'告警' if s.get('alert') else '正常'}）")
        else:
            self.pos_label.setText("当前持仓：空仓")

    def _reset(self) -> None:
        self._portfolio = PaperPortfolio(
            cash=float(self.spin_cash.value()),
            multiplier=float(self.spin_mult.value()),
            margin_rate=float(self.spin_margin.value()),
        )
        self.reload()

    def _trade(self, kind: str) -> None:
        price = float(self.spin_price.value())
        lots = int(self.spin_lots.value())
        sym = "paper"
        if kind == "open_long":
            self._portfolio.open_long(sym, price, lots)
        elif kind == "open_short":
            self._portfolio.open_short(sym, price, lots)
        elif kind == "close_long":
            self._portfolio.close_long(sym, price, lots)
        elif kind == "close_short":
            self._portfolio.close_short(sym, price, lots)
        self._portfolio.mark_to_market(price)
        self.reload()


__all__ = ["PaperTradingPage"]
