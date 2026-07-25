"""分析预测系统 · 六大功能页。

本文件包含：
    - Worker：后台计算线程（避免 AI 训练/验证阻塞 UI）；
    - MarketPage：模块一 实时行情全景；
    - IndicatorPage：模块二 量化指标分析（共振/背离/趋势）；
    - PredictPage：模块三 AI 智能预测核心；
    - PanoramaPage：模块四 市场全景（强弱/量能/资金流）；
    - ValidatePage：模块五 预测回测验证；
    - LogPage：模块六 日志 / 预警 / 报告。

所有页面共享 MarketDataManager（行情中枢）与 AnalysisStore（存储），
仅依赖 PyQt6 / numpy / pandas，离线可跑。
"""
from __future__ import annotations

import csv
import datetime as dt
import threading
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QDateTime
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QTabWidget,
    QCheckBox, QSpinBox, QDoubleSpinBox, QScrollArea, QSplitter, QSizePolicy,
    QAbstractItemView, QListWidget, QListWidgetItem, QDialog, QFormLayout,
    QLineEdit, QMessageBox,
)

from .widgets import (
    PageHeader, Badge, MetricChip, ConfidenceBar, prepare_table,
    color_pnl, pal, THEME, ToolBar,
)
from .icons import icon
from .chart_widget import KLineChart, PriceChart
from ..data.market_data import MarketDataManager
from ..indicators.tech import add_indicators
from ..ai.predictor import FuturesPredictor
from ..ai.feedback import (
    quick_regime, adaptive_config, calibrated_confidence,
    evaluate_all_open, recommend_text,
)
from ..ai import news_feed
from ..analysis.signals import resonance, trend_score, divergence
from ..storage.analysis_store import AnalysisStore
from ..alerts import scan as alert_scan, RULE_KINDS, rule_label


PERIODS = ["1m", "5m", "15m", "30m", "1h", "4h", "D", "W"]
PERIOD_LABEL = {"1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟",
                "1h": "1小时", "4h": "4小时", "D": "日线", "W": "周线"}


def df_to_bars(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        out.append({
            "datetime": str(r["datetime"])[:19],
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r["volume"]),
            "open_interest": float(r.get("open_interest", 0) or 0),
        })
    return out


def symbol_code(row) -> str:
    return f"{row[0]}.{row[3]}"


def symbol_label(row) -> str:
    return f"{row[1]} ({row[0]}.{row[3]})"


# ============================================================================
# 后台计算线程
# ============================================================================
class Worker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:  # noqa: N802
        try:
            self.finished.emit(self._fn())
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


# ============================================================================
# 页面基类
# ============================================================================
class BasePage(QWidget):
    # 合约/周期变更信号（symbol 可能为空，表示仅周期变化）
    selection_changed = pyqtSignal(str, str)

    def __init__(self, mdm: MarketDataManager, store: AnalysisStore,
                 config=None, session=None) -> None:
        super().__init__()
        self.mdm = mdm
        self.store = store
        self.config = config
        self.session = session
        self._theme = THEME
        self._workers: list[Worker] = []
        self.PAGE_KEY = ""
        self._closed = False          # 窗口关闭标志，防止定时器等对已关 DB 操作

    def closeEvent(self, event) -> None:
        """页面关闭时清理定时器并标记已关闭，防止对已关 DB 的残留回调触发异常。"""
        self._closed = True
        # 停止所有 QTimer（如预警中心周期扫描器）
        from PyQt6.QtCore import QTimer
        for _t in self.findChildren(QTimer):
            if _t.isActive():
                try:
                    _t.stop()
                except Exception:
                    pass
        # 断开信号连接，避免回调在窗口销毁后执行
        try:
            self.mdm.bar_arrived.disconnect(self._on_live)
        except Exception:
            pass
        super().closeEvent(event)

    def set_theme(self, t: str) -> None:
        self._theme = t
        # 向所有具备 set_theme 的子组件递归下发主题（指标卡/徽标/图表/页头等）
        for child in self.findChildren(QWidget):
            fn = getattr(child, "set_theme", None)
            if fn is not None and child is not self:
                try:
                    fn(t)
                except Exception:  # noqa: BLE001
                    pass

    def _run_worker(self, fn: Callable[[], Any], on_done: Callable[[Any], None],
                    on_err: Optional[Callable[[str], None]] = None) -> None:
        w = Worker(fn)
        self._workers.append(w)

        def _safe_remove():
            try:
                self._workers.remove(w)
            except ValueError:
                pass

        def _done(r):
            try:
                on_done(r)
            finally:
                _safe_remove()

        def _err(e):
            try:
                if on_err:
                    on_err(e)
            finally:
                _safe_remove()

        w.finished.connect(_done)
        w.error.connect(_err)
        w.start()


# ============================================================================
# 模块一：实时行情全景
# ============================================================================
class MarketPage(BasePage):
    # 预警触发信号（供主窗口做托盘通知）
    alerts_fired = pyqtSignal(list)
    # 扫描状态信号（供主窗口状态栏提示：加载 / 成功 / 失败）
    scan_status = pyqtSignal(str)

    def __init__(self, mdm, store, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "market"
        dft = symbol_code(mdm.universe[0])
        if session is not None:
            self.cur_symbol, self.cur_period = session.get_page_selection("market", dft, "1m")
        else:
            self.cur_symbol, self.cur_period = dft, "1m"
        self._live = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader("实时行情全景", "全市场合约行情 · 盘口快照 · 自选监控"))

        # 控制条
        ctl = QHBoxLayout()
        self.sym_cb = QComboBox(); self.sym_cb.setMinimumWidth(180)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        self.sym_cb.setCurrentIndex(max(0, self.sym_cb.findData(self.cur_symbol)))
        self.sym_cb.currentIndexChanged.connect(self._on_symbol)
        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(self._on_period)
        self.live_btn = QPushButton("启动实时")
        self.live_btn.setObjectName("secondary")
        self.live_btn.clicked.connect(self._toggle_live)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(lambda: self._refresh())
        ctl.addWidget(QLabel("合约"))
        ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("周期"))
        ctl.addWidget(self.per_cb)
        ctl.addWidget(self.live_btn)
        ctl.addWidget(self.refresh_btn)
        ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        # 盘口快照
        self.chips = {
            "last": MetricChip("最新价", "--"),
            "chg": MetricChip("涨跌", "--"),
            "pct": MetricChip("涨跌幅", "--"),
            "vol": MetricChip("成交量", "--"),
            "oi": MetricChip("持仓量", "--"),
            "fund": MetricChip("资金流(亿)", "--"),
        }
        cstrip = QHBoxLayout()
        for c in self.chips.values():
            cstrip.addWidget(c, 1)
        root.addLayout(cstrip)

        # 主图 + 自选表
        split = QSplitter(Qt.Orientation.Horizontal)
        self.chart = KLineChart()
        split.addWidget(self.chart)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("自选 / 全市场速览（按涨跌幅）"))
        self.watch = QTableWidget(0, 5)
        self.watch.setHorizontalHeaderLabels(["合约", "最新价", "涨跌幅%", "量比", "资金流(亿)"])
        self.watch.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.watch.itemDoubleClicked.connect(self._on_pick)
        rv.addWidget(self.watch)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        # 预警中心（规则管理 + 周期扫描 + 触发记录）
        self._build_alert_center(root)

        self._refresh()
        self._refresh_watch()
        self._scan_alerts()

    # ---- 预警中心 ----
    def _build_alert_center(self, root: QVBoxLayout) -> None:
        box = QFrame()
        box.setObjectName("card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(6)

        ctl = QHBoxLayout()
        self.rule_badge = Badge("预警规则 0", bg=pal()["badge_bg"], fg=pal()["text"])
        self.manage_btn = QPushButton("管理规则")
        self.manage_btn.setObjectName("secondary")
        self.manage_btn.clicked.connect(self._on_manage_rules)
        self.scan_btn = QPushButton("立即扫描")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(lambda: self._scan_alerts(manual=True))
        ctl.addWidget(QLabel("预警中心"))
        ctl.addWidget(self.rule_badge)
        ctl.addStretch(1)
        ctl.addWidget(self.manage_btn)
        ctl.addWidget(self.scan_btn)
        bl.addLayout(ctl)

        # 扫描状态反馈（加载 / 成功 / 失败）
        self.alert_status = QLabel("上次扫描：—")
        self.alert_status.setObjectName("hint")
        bl.addWidget(self.alert_status)

        self.alert_list = QListWidget()
        self.alert_list.setMaximumHeight(110)
        self.alert_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        bl.addWidget(self.alert_list)
        root.addWidget(box)

        # 周期扫描（每 30 秒）
        from PyQt6.QtCore import QTimer
        self._alert_timer = QTimer(self)
        self._alert_timer.timeout.connect(lambda: self._scan_alerts())
        self._alert_timer.start(30_000)
        self._refresh_rule_badge()
        self._refresh_alert_list()

    def _scan_alerts(self, manual: bool = False) -> None:
        """后台扫描已启用规则；触发写库并推送 alerts_fired 信号。

        点击「立即扫描」或周期定时器都会进入这里。为给出明确反馈：
        - 进入时按钮显示「扫描中…」并禁用，避免重复触发；
        - 完成（成功/失败）后恢复按钮，并更新状态行 + 状态栏信号。
        """
        if getattr(self, "_closed", False):
            return
        if getattr(self, "_scanning", False):
            return
        try:
            rules = self.store.list_alert_rules(enabled_only=True)
        except Exception:
            return
        if not rules and not manual:
            return
        # 加载状态
        self._scanning = True
        self.scan_btn.setText("扫描中…")
        self.scan_btn.setEnabled(False)
        self.alert_status.setText("扫描中…（后台读取行情并评估规则）")
        self._run_worker(
            lambda: alert_scan(self.mdm, self.store, rules),
            self._on_alert_done,
            self._on_alert_err,
        )

    def _restore_scan_btn(self) -> None:
        self._scanning = False
        self.scan_btn.setText("立即扫描")
        self.scan_btn.setEnabled(True)

    def _on_alert_done(self, fired: list) -> None:
        try:
            self._refresh_alert_list()
            self._refresh_rule_badge()
            ts = dt.datetime.now().strftime("%H:%M:%S")
            if fired:
                self.alert_status.setText(f"上次扫描 {ts} · 触发 {len(fired)} 条预警")
                self.scan_status.emit(f"预警扫描完成：触发 {len(fired)} 条（{ts}）")
                self.alerts_fired.emit(fired)
                self.store.add_log(
                    dt.datetime.now().isoformat(timespec="seconds"), "WARN",
                    f"预警触发 {len(fired)} 条：" + "；".join(
                        f"{f['symbol']} {f['message']}" for f in fired[:5]))
            else:
                self.alert_status.setText(f"上次扫描 {ts} · 未触发预警")
                self.scan_status.emit(f"预警扫描完成：未触发（{ts}）")
        finally:
            self._restore_scan_btn()

    def _on_alert_err(self, msg: str) -> None:
        try:
            ts = dt.datetime.now().strftime("%H:%M:%S")
            self.alert_status.setText(f"上次扫描 {ts} · 失败：{msg}")
            self.scan_status.emit(f"预警扫描失败：{msg}（{ts}）")
            self.store.add_log(
                dt.datetime.now().isoformat(timespec="seconds"), "ERROR",
                f"预警扫描失败：{msg}")
        finally:
            self._restore_scan_btn()

    def _refresh_alert_list(self) -> None:
        rows = self.store.query_alerts(limit=30)
        self.alert_list.clear()
        if not rows:
            self.alert_list.addItem(QListWidgetItem(
                "（暂无触发记录；设置规则后周期扫描会自动监控）"))
            return
        for r in rows:
            d = (r.get("ts") or "")[:16]
            lvl = r.get("level") or ""
            msg = r.get("message") or ""
            self.alert_list.addItem(QListWidgetItem(
                f"{d} 〔{r.get('symbol')}·{r.get('rule')}·{lvl}〕 {msg}"))

    def _refresh_rule_badge(self) -> None:
        n = len(self.store.list_alert_rules(enabled_only=True))
        self.rule_badge.set_text(f"预警规则 {n}")

    def _on_manage_rules(self) -> None:
        dlg = _AlertRulesDialog(self.mdm, self.store, parent=self)
        dlg.exec()
        self._refresh_rule_badge()
        self._refresh_alert_list()

    def _on_symbol(self, i):
        self.cur_symbol = self.sym_cb.itemData(i)
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        self._refresh()

    def _on_period(self, i):
        self.cur_period = self.per_cb.itemData(i)
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        self._refresh()

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
            self._refresh()

    def _refresh(self):
        df = self.mdm.get_bars(self.cur_symbol, self.cur_period, 240)
        if df.empty:
            return
        ind = add_indicators(df)
        bars = df_to_bars(df)
        self.chart.set_data(bars, ma={"MA10": ind["MA10"].tolist(),
                                      "MA20": ind["MA20"].tolist(),
                                      "MA60": ind["MA60"].tolist()})
        self.chart.set_watermark(f"{self.cur_symbol} · {self.cur_period}")
        q = self.mdm.get_quote(self.cur_symbol, self.cur_period)
        if not q:
            return
        upc = pal()["up"] if q["chg"] >= 0 else pal()["down"]
        self.chips["last"].set_value(f"{q['last']:,.1f}")
        self.chips["chg"].set_value(f"{q['chg']:+,.1f}", upc)
        self.chips["pct"].set_value(f"{q['chg_pct']:+,.2f}%", upc)
        self.chips["vol"].set_value(f"{q['volume']:,.0f}")
        self.chips["oi"].set_value(f"{q['open_interest']:,.0f}")
        self.chips["fund"].set_value(f"{q['fund_flow']:+,.2f}",
                                     pal()["up"] if q["fund_flow"] >= 0 else pal()["down"])

    def _refresh_watch(self):
        pan = self.mdm.compute_panorama("D")
        if pan.empty:
            return
        self.watch.setRowCount(len(pan))
        for i, (_, r) in enumerate(pan.iterrows()):
            self.watch.setItem(i, 0, QTableWidgetItem(r["name"]))
            self.watch.setItem(i, 1, QTableWidgetItem(f"{r['last']:,.1f}"))
            pct = QTableWidgetItem(f"{r['chg_pct']:+,.2f}")
            color_pnl(pct, r["chg_pct"])
            self.watch.setItem(i, 2, pct)
            self.watch.setItem(i, 3, QTableWidgetItem(f"{r['vol_ratio']:,.2f}"))
            ff = QTableWidgetItem(f"{r['fund_flow']:+,.2f}")
            color_pnl(ff, r["fund_flow"])
            self.watch.setItem(i, 4, ff)
        prepare_table(self.watch)

    def _on_pick(self, item):
        name = self.watch.item(item.row(), 0).text()
        for r in self.mdm.universe:
            if r[1] == name:
                idx = self.sym_cb.findData(symbol_code(r))
                if idx >= 0:
                    self.sym_cb.setCurrentIndex(idx)
                break


# ============================================================================
# 预警规则对话框
# ============================================================================
class _AlertRuleEditDialog(QDialog):
    """新增 / 编辑单条预警规则。"""

    def __init__(self, mdm, store, parent=None, rule: Optional[dict] = None):
        super().__init__(parent)
        self.mdm = mdm
        self.store = store
        self.rule = rule
        self.setWindowTitle("编辑预警规则" if rule else "新增预警规则")
        self.setMinimumWidth(360)

        sym = symbol_code(mdm.universe[0]) if mdm.universe else ""
        self._sym_cb = QComboBox()
        for r in mdm.universe:
            self._sym_cb.addItem(symbol_label(r), symbol_code(r))
        if rule:
            i = self._sym_cb.findData(rule.get("symbol", sym))
            if i >= 0:
                self._sym_cb.setCurrentIndex(i)

        self._kind_cb = QComboBox()
        for k, meta in RULE_KINDS.items():
            self._kind_cb.addItem(f"{meta['label']}", k)
        if rule:
            i = self._kind_cb.findData(rule.get("kind"))
            if i >= 0:
                self._kind_cb.setCurrentIndex(i)
        self._kind_cb.currentIndexChanged.connect(self._sync_param)

        self._param = QDoubleSpinBox()
        self._param.setRange(0, 1000)
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setObjectName("muted")

        self._enabled = QCheckBox("启用该规则")
        self._enabled.setChecked(bool(rule.get("enabled", 1)) if rule else True)

        self._note = QLineEdit()
        self._note.setPlaceholderText("可选备注（如：突破追多）")
        if rule:
            self._note.setText(rule.get("note") or "")

        form = QFormLayout()
        form.addRow("品种", self._sym_cb)
        form.addRow("类型", self._kind_cb)
        form.addRow("阈值", self._param)
        form.addRow("", self._hint)
        form.addRow("", self._enabled)
        form.addRow("备注", self._note)
        self._sync_param()

        btns = QHBoxLayout()
        ok = QPushButton("保存")
        ok.setObjectName("primary")
        ok.clicked.connect(self._on_save)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addLayout(form)
        root.addLayout(btns)

    def _sync_param(self) -> None:
        kind = self._kind_cb.currentData()
        meta = RULE_KINDS.get(kind, {})
        unit = meta.get("unit", "")
        self._hint.setText(meta.get("hint", ""))
        if kind == "price_break":
            self._param.setDecimals(0)
            self._param.setRange(2, 250)
            self._param.setSingleStep(1)
        else:
            self._param.setDecimals(1)
            self._param.setRange(0, 1000)
            self._param.setSingleStep(0.5)
        suffix = f" {unit}" if unit not in ("—", "") else ""
        self._param.setSuffix(suffix)
        if self.rule and self.rule.get("kind") == kind:
            self._param.setValue(float(self.rule.get("param") or meta.get("default", 0)))
        else:
            self._param.setValue(float(meta.get("default", 0)))

    def _on_save(self) -> None:
        rec = dict(
            symbol=self._sym_cb.currentData(),
            kind=self._kind_cb.currentData(),
            param=self._param.value(),
            enabled=self._enabled.isChecked(),
            note=self._note.text().strip(),
            created_ts=dt.datetime.now().isoformat(timespec="seconds"),
        )
        if self.rule:
            self.store.update_alert_rule(self.rule["id"], **rec)
        else:
            self.store.add_alert_rule(rec)
        self.accept()


class _AlertRulesDialog(QDialog):
    """规则管理：列表 + 新增 / 编辑 / 删除 / 启停。"""

    def __init__(self, mdm, store, parent=None):
        super().__init__(parent)
        self.mdm = mdm
        self.store = store
        self.setWindowTitle("预警规则管理")
        self.setMinimumWidth(520)
        self.setMinimumHeight(360)

        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(["启用", "品种", "类型", "阈值", "操作"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        add_btn = QPushButton("新增规则")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._on_add)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.accept)
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(add_btn)
        bar.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(QLabel("已配置预警规则（周期扫描自动监控，触发后推送通知）"))
        root.addWidget(self.tbl, 1)
        root.addLayout(bar)
        self._reload()

    def _reload(self) -> None:
        rules = self.store.list_alert_rules()
        self.tbl.setRowCount(len(rules))
        for i, r in enumerate(rules):
            cb = QCheckBox()
            cb.setChecked(bool(r.get("enabled")))
            cb.stateChanged.connect(
                lambda s, rid=r["id"]: self._on_toggle(rid, s))
            self.tbl.setCellWidget(i, 0, cb)
            self.tbl.setItem(i, 1, QTableWidgetItem(r.get("symbol", "")))
            self.tbl.setItem(i, 2, QTableWidgetItem(rule_label(r.get("kind"))))
            meta = RULE_KINDS.get(r.get("kind"), {})
            unit = meta.get("unit", "")
            suffix = f" {unit}" if unit not in ("—", "") else ""
            self.tbl.setItem(i, 3, QTableWidgetItem(f"{r.get('param')}{suffix}"))

            op = QWidget()
            ol = QHBoxLayout(op)
            ol.setContentsMargins(2, 2, 2, 2)
            edit = QPushButton("编辑")
            edit.setObjectName("secondary")
            edit.setFixedWidth(48)
            edit.clicked.connect(lambda _=False, rid=r["id"]: self._on_edit(rid))
            dele = QPushButton("删除")
            dele.setObjectName("danger")
            dele.setFixedWidth(48)
            dele.clicked.connect(lambda _=False, rid=r["id"]: self._on_delete(rid))
            ol.addWidget(edit)
            ol.addWidget(dele)
            self.tbl.setCellWidget(i, 4, op)
        prepare_table(self.tbl)

    def _on_add(self) -> None:
        dlg = _AlertRuleEditDialog(self.mdm, self.store, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._reload()

    def _on_edit(self, rid: int) -> None:
        r = self.store.get_alert_rule(rid)
        if not r:
            return
        dlg = _AlertRuleEditDialog(self.mdm, self.store, parent=self, rule=r)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._reload()

    def _on_delete(self, rid: int) -> None:
        self.store.remove_alert_rule(rid)
        self._reload()

    def _on_toggle(self, rid: int, state) -> None:
        self.store.set_alert_rule_enabled(rid, bool(state))


# ============================================================================
# 模块二：量化指标分析
# ============================================================================
class IndicatorPage(BasePage):
    def __init__(self, mdm, store, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "indicator"
        dft = symbol_code(mdm.universe[0])
        if session is not None:
            self.cur_symbol, self.cur_period = session.get_page_selection("indicator", dft, "D")
        else:
            self.cur_symbol, self.cur_period = dft, "D"
        self._build()

    def _on_change(self):
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        self.selection_changed.emit(self.cur_symbol, self.cur_period)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader("量化指标分析", "多指标共振 · 背离检测 · 趋势强弱打分"))

        ctl = QHBoxLayout()
        self.sym_cb = QComboBox(); self.sym_cb.setMinimumWidth(180)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        self.sym_cb.setCurrentIndex(max(0, self.sym_cb.findData(self.cur_symbol)))
        self.sym_cb.currentIndexChanged.connect(lambda i: self._on_change())
        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(lambda i: self._on_change())
        self.ma_chk = QCheckBox("均线"); self.ma_chk.setChecked(True)
        self.ma_chk.stateChanged.connect(lambda: self._on_change())
        self.boll_chk = QCheckBox("BOLL"); self.boll_chk.setChecked(True)
        self.boll_chk.stateChanged.connect(lambda: self._on_change())
        self.refresh_btn = QPushButton("刷新"); self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(lambda: self._on_change())
        ctl.addWidget(QLabel("合约")); ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("周期")); ctl.addWidget(self.per_cb)
        ctl.addWidget(self.ma_chk); ctl.addWidget(self.boll_chk)
        ctl.addWidget(self.refresh_btn); ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        # 研判条
        self.verdict = Badge("--", pal()["accent"], "#fff")
        self.score_bar = ConfidenceBar(0.5)
        self.state_badge = Badge("--")
        top = QHBoxLayout()
        top.addWidget(QLabel("综合研判:")); top.addWidget(self.verdict)
        top.addSpacing(20); top.addWidget(QLabel("多空分:")); top.addWidget(self.score_bar)
        top.addSpacing(20); top.addWidget(QLabel("趋势:")); top.addWidget(self.state_badge)
        top.addStretch(1)
        root.addLayout(top)

        # K线 + 副图
        self.chart = KLineChart()
        self.chart.setMinimumHeight(220)
        root.addWidget(self.chart, 3)
        self.macd = PriceChart(); self.macd.setMinimumHeight(90)
        self.kdj = PriceChart(); self.kdj.setMinimumHeight(90)
        self.rsi = PriceChart(); self.rsi.setMinimumHeight(90)
        root.addWidget(self.macd, 1); root.addWidget(self.kdj, 1); root.addWidget(self.rsi, 1)
        self._refresh()

    def _refresh(self):
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        df = self.mdm.get_bars(self.cur_symbol, self.cur_period, 300)
        if df.empty:
            return
        ind = add_indicators(df)
        bars = df_to_bars(df)
        ma = {}
        if self.ma_chk.isChecked():
            ma = {"MA5": ind["MA5"].tolist(), "MA10": ind["MA10"].tolist(),
                  "MA20": ind["MA20"].tolist()}
        self.chart.set_data(bars, ma=ma)
        self.chart.set_watermark(f"{self.cur_symbol} · {self.cur_period}")
        self.chart.set_levels([])  # 指标页不叠加 S/R

        res = resonance(ind)
        self.verdict.setText(res["verdict"])
        col = (pal()["up"] if res["score"] > 20 else pal()["down"] if res["score"] < -20 else pal()["sub"])
        self.verdict.set_color(col, "#fff")
        self.score_bar.set_pct((res["score"] + 100) / 200)

        # 研判记录入库（历史记录可靠保存）
        try:
            self.store.save_analysis(
                str(dt.datetime.now()), self.cur_symbol, "resonance",
                f"{res['verdict']} 多空分{res['score']:+.0f}",
                f"趋势强弱 {trend_score(ind)['state']}")
        except Exception:  # noqa: BLE001
            pass

        tr = trend_score(ind)
        self.state_badge.setText(tr["state"])
        self.state_badge.set_color(pal()["accent"], "#fff")

        # 副图
        x = list(range(len(ind)))
        self.macd.set_data(
            series=[{"name": "DIF", "color": "#3b82f6", "x": x, "y": ind["DIF"].tolist()},
                    {"name": "DEA", "color": "#f59e0b", "x": x, "y": ind["DEA"].tolist()}],
            title="MACD")
        self.kdj.set_data(
            series=[{"name": "K", "color": "#3b82f6", "x": x, "y": ind["K"].tolist()},
                    {"name": "D", "color": "#22c55e", "x": x, "y": ind["D"].tolist()},
                    {"name": "J", "color": "#ef4444", "x": x, "y": ind["J"].tolist()}],
            title="KDJ")
        self.rsi.set_data(
            series=[{"name": "RSI6", "color": "#a855f7", "x": x, "y": ind["RSI6"].tolist()},
                    {"name": "RSI14", "color": "#06b6d4", "x": x, "y": ind["RSI14"].tolist()}],
            title="RSI")


# ============================================================================
# 模块三：AI 智能预测核心
# ============================================================================
class PredictPage(BasePage):
    def __init__(self, mdm, store, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "predict"
        dft = symbol_code(mdm.universe[0])
        if session is not None:
            self.cur_symbol, self.cur_period = session.get_page_selection("predict", dft, "D")
        else:
            self.cur_symbol, self.cur_period = dft, "D"
        self.predictor = FuturesPredictor()
        self._build()

    def _on_sel(self, *_):
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        self.selection_changed.emit(self.cur_symbol, self.cur_period)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader("AI 智能预测核心", "LSTM 趋势预测 · 涨跌概率 · 压力支撑 · 风险度 ｜ 一键运行即自动完成：结算历史 · 抓取资讯 · 自适应选参 · AI预测 · 学习校准"))

        ctl = QHBoxLayout()
        self.sym_cb = QComboBox(); self.sym_cb.setMinimumWidth(180)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        self.sym_cb.setCurrentIndex(max(0, self.sym_cb.findData(self.cur_symbol)))
        self.sym_cb.currentIndexChanged.connect(self._on_sel)
        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(self._on_sel)
        self.hor_spin = QSpinBox(); self.hor_spin.setRange(3, 30); self.hor_spin.setValue(12)
        self.run_btn = QPushButton("运行预测"); self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        ctl.addWidget(QLabel("合约")); ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("周期")); ctl.addWidget(self.per_cb)
        ctl.addWidget(QLabel("预测步数")); ctl.addWidget(self.hor_spin)
        ctl.addWidget(self.run_btn)
        # 一键运行：直接执行【完整预测流程】，自动串联以下全部步骤，
        # 无需任何额外操作：
        #   ① 结算历史预测（与真实行情比对，更新命中率）
        #   ② 获取最新资讯（cls.cn 快讯，融入涨跌概率偏置）
        #   ③ 自适应选参 / 置信度校准（基于历史经验）
        #   ④ 运行增强模型预测 + 渲染解读 / 资讯 / 学习看板
        self.auto_lbl = QLabel("点「运行预测」即自动完成：结算历史 · 抓取资讯 · 自适应选参 · AI预测 · 学习校准")
        self.auto_lbl.setObjectName("sub")
        self.auto_lbl.setWordWrap(True)
        ctl.addStretch(1)
        ctl.addWidget(self.auto_lbl)
        root.addWidget(ToolBar(ctl))

        # 结果卡片
        self.chips = {
            "exp": MetricChip("预期收益", "--"),
            "pup": MetricChip("上涨概率", "--"),
            "risk": MetricChip("风险度", "--"),
            "regime": MetricChip("行情状态", "--"),
            "model": MetricChip("模型", "--"),
            "conf": MetricChip("校准置信度", "--"),
            "news": MetricChip("资讯偏置", "--"),
        }
        cstrip = QHBoxLayout()
        for c in self.chips.values():
            cstrip.addWidget(c, 1)
        root.addLayout(cstrip)

        # 指标共振研判条（指标分析并入 AI 预测：多指标共振 + 趋势强弱，
        # 与下方 AI 预测方向交叉印证，构成「指标面 + AI面」双重研判）
        self.verdict_badge = Badge("--", pal()["accent"], "#fff")
        self.score_bar = ConfidenceBar(0.5)
        self.trend_badge = Badge("--")
        ind_row = QHBoxLayout()
        ind_row.addWidget(QLabel("指标共振:"))
        ind_row.addWidget(self.verdict_badge)
        ind_row.addSpacing(16)
        ind_row.addWidget(QLabel("多空分:"))
        ind_row.addWidget(self.score_bar)
        ind_row.addSpacing(16)
        ind_row.addWidget(QLabel("趋势:"))
        ind_row.addWidget(self.trend_badge)
        ind_row.addStretch(1)
        root.addLayout(ind_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        # 左侧：主 K 线 + MACD/KDJ/RSI 副图（指标分析）
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        self.chart = KLineChart()
        lv.addWidget(self.chart, 3)
        self.macd = PriceChart(); self.macd.setMinimumHeight(80)
        self.kdj = PriceChart(); self.kdj.setMinimumHeight(80)
        self.rsi = PriceChart(); self.rsi.setMinimumHeight(80)
        lv.addWidget(self.macd, 1); lv.addWidget(self.kdj, 1); lv.addWidget(self.rsi, 1)
        split.addWidget(left)
        # 右侧：综合预测解读（资讯情报 + 学习看板已并入此单页，无需切换）
        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.long_bar = ConfidenceBar(0.5); self.short_bar = ConfidenceBar(0.5)
        rl = QHBoxLayout(); rl.addWidget(QLabel("做多性价比")); rl.addWidget(self.long_bar)
        rs = QHBoxLayout(); rs.addWidget(QLabel("做空性价比")); rs.addWidget(self.short_bar)
        rv.addLayout(rl); rv.addLayout(rs)
        self.rec_badge = Badge("--")
        rh = QHBoxLayout(); rh.addWidget(QLabel("综合建议:")); rh.addWidget(self.rec_badge); rh.addStretch(1)
        rv.addLayout(rh)
        rv.addWidget(QLabel("预测解读（白话专业版 · 技术面 / 模型面 / 资讯面 / 基本面 / 历史表现）"))
        self.detail = QTextEdit(); self.detail.setReadOnly(True)
        self.detail.setHtml(
            "<p style='color:#94a3b8'>点击「运行预测」后，这里将给出专业、详细的白话版解读："
            "能不能入手、什么时候入手、为什么不能入手，以及技术面 / 模型面 / "
            "资讯面 / 基本面 / 历史表现 的全面分析与操作建议。</p>")
        rv.addWidget(self.detail, 1)

        split.addWidget(right)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
        self._base_refresh()

    def _base_refresh(self):
        df = self.mdm.get_bars(self.cur_symbol, self.cur_period, 300)
        if df.empty:
            return
        ind = add_indicators(df)
        self.chart.set_data(df_to_bars(df),
                           ma={"MA10": ind["MA10"].tolist(), "MA20": ind["MA20"].tolist()})
        self.chart.set_watermark(f"{self.cur_symbol} · {self.cur_period}")

    def _run(self):
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        horizon = self.hor_spin.value()
        self.run_btn.setEnabled(False)
        self.run_btn.setText("预测中…")
        sym, per = self.cur_symbol, self.cur_period

        store, mdm = self.store, self.mdm
        # 品种中文名/板块（用于资讯关键词匹配）
        name = category = ""
        for r in mdm.universe:
            if symbol_code(r) == sym:
                name, category = r[1], r[2]
                break

        def work():
            # ① 学习结算：先把到期的历史预测与真实行情比对结算，
            #    使后续「自适应选参 / 置信度校准」用到最新的经验数据。
            try:
                settle = evaluate_all_open(store, mdm, max_n=40)
            except Exception:
                settle = {"evaluated": 0, "hits": 0, "rate": None}
            df = self.mdm.get_bars(sym, per, 600)
            # ② 自适应选参：按当前行情状态挑选历史命中率更高的配置；
            #    经验不足时回退增强模型（保持一键可用）。
            regime0 = quick_regime(df)
            try:
                cfg = adaptive_config(store, regime0)
            except Exception:
                cfg = {"extended_features": True, "use_ensemble": True,
                       "source": "default", "rate": None}
            # ③ 多源资讯：强制聚合 财联社 + 东方财富 + 和讯 三源（已限频+
            #    缓存+优雅降级，任一源失败不影响其余），归一化、分类、情感标注；
            #    对本品种/板块命中的快讯做情感分析，作为温和的概率偏置。
            #    这一步已随「运行预测」自动完成，无需单独点「获取最新资讯」。
            try:
                all_news = news_feed.fetch_all_news(limit=60, force=True)
                bias_info = news_feed.news_bias_for_symbol(sym, name, category, all_news)
            except Exception:
                bias_info = {"bias": 0.0, "matched": 0, "samples": []}
                all_news = {"items": [], "sources": {}, "by_source": {},
                            "by_category": {}}
            # ④ 完整预测流程：一键执行（允许耗时适度增加）。
            fit = self.predictor.fit(df, seq_len=20, epochs=25,
                                     extended_features=cfg["extended_features"],
                                     use_ensemble=cfg["use_ensemble"])
            res = self.predictor.predict(df, horizon=horizon,
                                          news_bias=bias_info["bias"],
                                          news_samples=bias_info["samples"])
            # ⑤ 置信度校准：若该行情状态积累了足够历史样本，
            #    用历史方向命中率与模型概率融合，重出一次预测结论。
            cfg_key = "enhanced" if cfg["extended_features"] else "baseline"
            try:
                conf = calibrated_confidence(store, res["regime"], cfg_key, res["p_up"])
            except Exception:
                conf = res["p_up"]
            if abs(conf - res["p_up"]) > 1e-9:
                res = self.predictor.predict(df, horizon=horizon,
                                              news_bias=bias_info["bias"],
                                              news_samples=bias_info["samples"],
                                              calibrate_p_up=conf)
            res["symbol"] = sym; res["period"] = per
            # ⑥ AI 多维研判（趋势/风险/建议）：已配置 LLM 则调用，否则规则兜底
            try:
                ai_report = news_feed.ai_analyze_news(all_news, res, name, category, self.mdm)
            except Exception:
                ai_report = {"model": "heuristic", "trend": "", "risk": "",
                             "suggestion": "", "by_category": {}}
            return res, fit, cfg, bias_info, conf, settle, all_news, ai_report

        self._run_worker(work, self._on_done,
                         on_err=lambda e: (self.run_btn.setEnabled(True),
                                           self.run_btn.setText("运行预测"),
                                           print("预测错误:", e)))

    def _on_done(self, payload):
        (res, fit, cfg, bias_info, conf, settle, all_news,
         ai_report) = payload
        self.run_btn.setEnabled(True); self.run_btn.setText("运行预测")
        df = self.mdm.get_bars(res["symbol"], res["period"], 300)
        ind = add_indicators(df)
        bars = df_to_bars(df)
        self.chart.set_data(bars, ma={"MA10": ind["MA10"].tolist(), "MA20": ind["MA20"].tolist()})
        self.chart.set_watermark(f"{res['symbol']} · {res['period']} · AI预测")
        self.chart.set_forecast(res["forecast"], res["upper"], res["lower"])
        self.chart.set_levels(res["levels"])

        # 指标分析副图（MACD / KDJ / RSI）与多指标共振研判
        x = list(range(len(ind)))
        self.macd.set_data(
            series=[{"name": "DIF", "color": "#3b82f6", "x": x, "y": ind["DIF"].tolist()},
                    {"name": "DEA", "color": "#f59e0b", "x": x, "y": ind["DEA"].tolist()}],
            title="MACD")
        self.kdj.set_data(
            series=[{"name": "K", "color": "#3b82f6", "x": x, "y": ind["K"].tolist()},
                    {"name": "D", "color": "#22c55e", "x": x, "y": ind["D"].tolist()},
                    {"name": "J", "color": "#ef4444", "x": x, "y": ind["J"].tolist()}],
            title="KDJ")
        self.rsi.set_data(
            series=[{"name": "RSI6", "color": "#a855f7", "x": x, "y": ind["RSI6"].tolist()},
                    {"name": "RSI14", "color": "#06b6d4", "x": x, "y": ind["RSI14"].tolist()}],
            title="RSI")
        # 多指标共振 + 趋势强弱（指标分析核心结论，与 AI 预测交叉印证）
        try:
            reso = resonance(ind)
            tr = trend_score(ind)
        except Exception:
            reso = {"verdict": "信号不明", "score": 0}
            tr = {"state": "未知"}
        self.verdict_badge.setText(reso["verdict"])
        vcol = (pal()["up"] if reso["score"] > 20 else
                pal()["down"] if reso["score"] < -20 else pal()["sub"])
        self.verdict_badge.set_color(vcol, "#fff")
        self.score_bar.set_pct((reso["score"] + 100) / 200)
        self.trend_badge.setText(tr["state"])
        self.trend_badge.set_color(pal()["accent"], "#fff")
        ind_info = {"verdict": reso["verdict"], "score": reso["score"], "state": tr["state"]}

        # 品种中文名/板块（用于资讯深度解读匹配）
        sym = res["symbol"]; name = category = ""
        for r in self.mdm.universe:
            if symbol_code(r) == sym:
                name, category = r[1], r[2]
                break
        # 资讯深度解读：基于真实抓取正文 + 情感 + 重要度
        try:
            news_an = news_feed.analyze_symbol_news(sym, name, category, all_news)
        except Exception:
            news_an = {"bias": bias_info.get("bias", 0.0),
                       "matched": bias_info.get("matched", 0),
                       "bull": 0, "bear": 0, "items": []}

        col = pal()["up"] if res["expected_return_pct"] >= 0 else pal()["down"]
        self.chips["exp"].set_value(f"{res['expected_return_pct']:+,.2f}%", col)
        self.chips["pup"].set_value(f"{res['p_up']*100:,.1f}%")
        self.chips["risk"].set_value(f"{res['risk']['label']} {res['risk']['score']:.0f}")
        self.chips["regime"].set_value(res["regime"])
        self.chips["model"].set_value(res["model"])
        self.chips["conf"].set_value(f"{conf*100:,.0f}%")
        nb = res.get("news_bias", 0.0)
        nb_txt = ("中性" if abs(nb) < 0.05 else
                  f"偏多 {nb:+.2f}" if nb > 0 else f"偏空 {nb:+.2f}")
        self.chips["news"].set_value(nb_txt,
                                     pal()["up"] if nb > 0.05 else
                                     pal()["down"] if nb < -0.05 else "")
        self.long_bar.set_pct(res["long_short"]["long"] / 100)
        self.short_bar.set_pct(res["long_short"]["short"] / 100)
        self.rec_badge.setText("建议:" + res["long_short"]["recommend"])
        self.rec_badge.set_color(pal()["accent"], "#fff")

        # 基本面/资金面：从全景聚合取该品种与所属板块的资金、持仓、量能数据
        fund_info = {"sym_flow": None, "sym_oi": None, "sym_vr": None, "sym_chg": None,
                     "cat_avg": None, "cat_rank": None, "cat_n": 0, "cat_flow": None}
        try:
            pan = self.mdm.compute_panorama(res["period"])
            if not pan.empty:
                srow = pan[pan["symbol"] == sym]
                if not srow.empty:
                    sr = srow.iloc[0]
                    fund_info.update(sym_flow=float(sr["fund_flow"]),
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
        # 历史表现（学习看板已并入解读，这里直接取数据）
        try:
            stats = self.store.prediction_stats()
        except Exception:
            stats = {"total": 0, "rate": None, "by_config": {}, "by_regime": {}, "by_model": {}}
        try:
            closed = self.store.query_closed_predictions(limit=6)
        except Exception:
            closed = []

        # 预测解读（专业详细白话版，资讯面/学习看板已并入单一面板）
        self.detail.setHtml(self._detail_html(
            res, cfg, bias_info, conf, news_an, name, category,
            ind_info, fund_info, stats, closed, settle,
            ai_report=ai_report, all_news=all_news))

        # 存库（带置信度与配置来源，形成「记录→结算→学习」闭环）
        cfg_key = "enhanced" if cfg["extended_features"] else "baseline"
        self.store.save_prediction({
            "ts": str(dt.datetime.now()), "symbol": res["symbol"], "period": res["period"],
            "horizon": res["horizon"], "last_close": res["last_close"],
            "expected_return_pct": res["expected_return_pct"], "p_up": res["p_up"],
            "p_down": res["p_down"], "risk_score": res["risk"]["score"],
            "risk_label": res["risk"]["label"], "model": res["model"], "regime": res["regime"],
            "verdict": res["resonance"]["verdict"], "score": res["resonance"]["score"],
            "forecast": str([round(x, 2) for x in res["forecast"]]),
            "confidence": round(float(conf), 4), "status": "open", "config": cfg_key,
        })

    # ----------------------------- 预测解读（专业详细白话版） -----------------------------
    @staticmethod
    def _detail_html(res, cfg, bias_info, conf, news_an, name, category,
                     ind_info=None, fund_info=None, stats=None,
                     closed=None, settle=None, ai_report=None,
                     all_news=None) -> str:
        p = pal()
        up_c, dn_c, tx_c, mut_c = p["up"], p["down"], p["text"], "#94a3b8"
        p_up = float(res["p_up"]); p_dn = float(res["p_down"])
        last = float(res["last_close"])
        target = float(res["forecast"][-1])
        opt = float(res["upper"][-1]); pes = float(res["lower"][-1])
        exp = float(res["expected_return_pct"]); horizon = int(res["horizon"])
        risk_score = float(res["risk"]["score"]); risk_label = res["risk"]["label"]
        reso = (ind_info or {}).get("verdict", "—")
        ind_score = float((ind_info or {}).get("score", 0) or 0)

        # 方向
        if p_up >= 0.55:
            dir_word, ccol = "上涨", up_c
        elif p_up <= 0.45:
            dir_word, ccol = "下跌", dn_c
        else:
            dir_word, ccol = "震荡", mut_c

        # 能不能入手
        if p_up >= 0.55 and ind_score > 0 and risk_score < 60:
            enter, enter_col = "可以入手（偏多）", up_c
            enter_reason = [
                f"模型看涨概率 {p_up*100:.0f}%、指标共振偏多（{reso}），多空分 {ind_score:+.0f}，方向有技术支撑；",
                f"风险度「{risk_label}」（{risk_score:.0f} 分）可控，可按计划仓位参与。",
            ]
        elif p_up <= 0.45 or ind_score < 0:
            enter, enter_col = "暂不建议入手（偏空）", dn_c
            enter_reason = [
                f"模型看跌概率 {p_dn*100:.0f}% 或指标共振偏空（{reso}），顺势做多胜率偏低；",
                f"已持仓宜减仓/对冲，未持仓等待企稳信号更稳妥。",
            ]
        else:
            enter, enter_col = "谨慎观望（方向不明）", "#f59e0b"
            enter_reason = [
                f"涨跌概率接近（涨 {p_up*100:.0f}% / 跌 {p_dn*100:.0f}%），指标多空分 {ind_score:+.0f} 中性；",
                f"建议轻仓或观望，等放量突破压力或跌破支撑确认方向后再动手。",
            ]

        # 关键价位
        res_lv = sup_lv = None
        for lv in res.get("levels", []):
            pr = float(lv.get("price", 0))
            if pr > last and (res_lv is None or pr < res_lv[0]):
                res_lv = (pr, lv.get("label", ""))
            if pr < last and (sup_lv is None or pr > sup_lv[0]):
                sup_lv = (pr, lv.get("label", ""))

        # 什么时候入手
        timing = []
        if enter.startswith("可以"):
            if sup_lv:
                timing.append(f"回踩支撑 <b>{sup_lv[0]:,.1f}</b>（{sup_lv[1]}）不破，可分批低吸；")
            if res_lv:
                timing.append(f"或放量突破压力 <b>{res_lv[0]:,.1f}</b>（{res_lv[1]}）后顺势跟进；")
            timing.append(f"以 {horizon} 根K线为持有周期，不追单根大阳线。")
        elif enter.startswith("暂不"):
            timing.append(f"等待回落至支撑 <b>{sup_lv[0]:,.1f}</b>（若有）并出现企稳K线，"
                          f"或模型概率重新站上 55% 再评估。")
        else:
            timing.append(f"先观察：放量站上压力 <b>{res_lv[0]:,.1f}</b> 转多、或跌穿支撑 <b>{sup_lv[0]:,.1f}</b> 转空，再顺势而为。")

        # 为什么不能入手（风险阻挡，始终给出）
        nb = res.get("news_bias", 0.0)
        fi = fund_info or {}
        blockers = []
        if risk_score >= 70:
            blockers.append(f"风险度偏高（{risk_label} {risk_score:.0f} 分），波动大、逆风易止损；")
        if res_lv and (res_lv[0] - last) / last * 100 > 3:
            blockers.append(f"现价距上方压力 {res_lv[0]:,.1f} 仅 {(res_lv[0]-last)/last*100:.1f}%，上行空间有限、追高性价比低；")
        if ind_score < -20:
            blockers.append(f"指标共振偏空（{reso}），短期均线压制，反弹多为减仓机会；")
        if nb < -0.05:
            blockers.append(f"资讯面偏空（偏置 {nb:+.2f}），消息端暂不支持做多；")
        if fi.get("sym_flow") is not None and fi["sym_flow"] < 0:
            blockers.append(f"资金净流出 {abs(fi['sym_flow']):.2f} 亿，短期或继续承压；")
        if not blockers:
            blockers.append("当前未识别到明确阻挡因素，但仍须设好止损、控制单笔仓位。")

        def row(k, v, color=""):
            c = f" style='color:{color}'" if color else ""
            return (f"<tr><td style='color:{mut_c};padding:3px 12px 3px 0;white-space:nowrap'>{k}</td>"
                    f"<td{c}>{v}</td></tr>")
        rows = [
            row("当前价", f"{last:,.1f}"),
            row("目标价（预测终点）", f"{target:,.1f}（{(target/last-1)*100:+.2f}%）",
                up_c if target >= last else dn_c),
            row("乐观情形可看到", f"{opt:,.1f}", up_c),
            row("悲观情形需防守", f"{pes:,.1f}", dn_c),
        ]
        if res_lv:
            rows.append(row("上方最近压力", f"{res_lv[0]:,.1f}（{res_lv[1]}）—— 冲高至此易受阻"))
        if sup_lv:
            rows.append(row("下方最近支撑", f"{sup_lv[0]:,.1f}（{sup_lv[1]}）—— 回落至此有承接"))

        # 技术面
        ind_dir = ("偏多" if ind_score > 20 else "偏空" if ind_score < -20 else "中性")
        ind_state = (ind_info or {}).get("state", "—")

        # 资讯面（多源聚合 + AI 多维研判）
        def _lv_badge(level):
            cmap = {"A": ("#fef3c7", "#92400e"), "B": ("#e0f2fe", "#075985"),
                     "C": ("#f1f5f9", "#475569")}
            bg, fg = cmap.get((level or "C").upper(), ("#f1f5f9", "#475569"))
            return (f"<span style='background:{bg};color:{fg};border-radius:3px;"
                    f"padding:0 4px;font-size:11px'>{level or 'C'}</span>")
        def _src_badge(src):
            cmap = {"东方财富": ("#ecfdf5", "#047857"),
                     "和讯": ("#eff6ff", "#1d4ed"),
                     "财联社": ("#fef2f2", "#b91c1c")}
            bg, fg = cmap.get(src, ("#f1f5f9", "#475569"))
            return (f"<span style='background:{bg};color:{fg};border-radius:3px;"
                    f"padding:0 4px;font-size:10px'>{src}</span>")
        def _cat_badge(cat):
            cmap = {"行情动态": ("#f0f9ff", "#1e40af"), "市场分析": ("#f5f3ff", "#6d28d9"),
                     "政策资讯": ("#fef2f2", "#b91c1c"), "品种研报": ("#ecfdf5", "#047857"),
                     "其他": ("#f1f5f9", "#475569")}
            bg, fg = cmap.get(cat, ("#f1f5f9", "#475569"))
            return (f"<span style='background:{bg};color:{fg};border-radius:3px;"
                    f"padding:0 4px;font-size:10px'>{cat}</span>")

        # —— AI 多维研判（趋势 / 风险 / 建议）——
        ar = ai_report or {}
        ai_html = ""
        if ar.get("trend") or ar.get("risk") or ar.get("suggestion"):
            tag = ("LLM 模型" if str(ar.get("model", "")) not in
                  ("heuristic", "", "llm") else "规则合成")
            ai_html = (
                f"<div style='border:1px solid {mut_c};border-radius:6px;"
                f"padding:8px 10px;margin:4px 0'>"
                f"<p style='margin:0 0 4px;font-weight:bold;color:{ccol}'>"
                f"AI 多维资讯研判（{tag}）</p>")
            if ar.get("trend"):
                ai_html += (f"<p style='margin:2px 0'><b style='color:"
                            f"{up_c if nb>0.05 else (dn_c if nb<-0.05 else tx_c)}'>"
                            f"趋势研判：</b><span style='color:{tx_c}'>{ar['trend']}</span></p>")
            if ar.get("risk"):
                ai_html += (f"<p style='margin:2px 0'><b style='color:{dn_c}'>"
                            f"风险提示：</b><span style='color:{tx_c}'>{ar['risk']}</span></p>")
            if ar.get("suggestion"):
                ai_html += (f"<p style='margin:2px 0'><b style='color:{up_c}'>"
                            f"品种关注建议：</b><span style='color:{tx_c}'>"
                            f"{ar['suggestion']}</span></p>")
            ai_html += "</div>"

        # —— 多源概览 + 分类汇总 ——
        an = all_news or {}
        src_items = an.get("by_source", {})
        cat_items = an.get("by_category", {})
        overview_html = ""
        if src_items or cat_items:
            parts = []
            if src_items:
                parts.append("来源：" + " ｜ ".join(f"{k} {v}" for k, v in src_items.items()))
            if cat_items:
                parts.append("分类：" + " ｜ ".join(f"{k} {v}" for k, v in cat_items.items()))
            overview_html = (f"<p style='margin:2px 0;color:{mut_c};font-size:12px'>"
                              f"共覆盖 <b style='color:{tx_c}'>{len(an.get('items', []))}</b> 条多源资讯 ｜ "
                              + " ｜ ".join(parts) + "</p>")
        items = (news_an or {}).get("items", [])
        matched = (news_an or {}).get("matched", 0)
        if items:
            lis = []
            for it in items[:8]:
                s = float(it.get("sentiment", 0.0))
                c = up_c if s > 0 else (dn_c if s < 0 else mut_c)
                tone = "偏多" if s > 0 else ("偏空" if s < 0 else "中性")
                src = it.get("source", "")
                cat = it.get("category", "")
                lis.append(
                    f"<li style='margin:4px 0 4px 0'>"
                    f"<span style='color:{c}'>●</span> "
                    f"<span style='color:{mut_c};font-size:11px'>{it.get('ts','')}</span> "
                    f"{_lv_badge(it.get('level',''))} {_src_badge(src)} {_cat_badge(cat)} "
                    f"<span style='color:{c};font-weight:bold'>[{tone}]</span> "
                    f"<span style='color:{tx_c}'>{it.get('snippet','')}</span></li>")
            bull = (news_an or {}).get("bull", 0); bear = (news_an or {}).get("bear", 0)
            bias_c = up_c if nb > 0.05 else (dn_c if nb < -0.05 else mut_c)
            news_html = (
                f"<p style='margin:2px 0'>命中 <b>{matched}</b> 条与「{name}/{category}」"
                f"相关快讯（偏多 {bull} · 偏空 {bear}），综合情绪偏置 "
                f"<b style='color:{bias_c}'>{nb:+.2f}</b>：</p>"
                f"<ul style='margin:2px 0 0 14px;padding:0'>{''.join(lis)}</ul>")
        else:
            news_html = (f"<p style='color:{mut_c}'>暂无命中「{name}/{category}」品种的快讯，"
                         f"预测以技术模型为主，资讯偏置按中性处理。</p>")

        # 基本面 / 资金面
        sym_flow = fi.get("sym_flow"); sym_oi = fi.get("sym_oi")
        sym_vr = fi.get("sym_vr"); sym_chg = fi.get("sym_chg")
        cat_avg = fi.get("cat_avg"); cat_rank = fi.get("cat_rank")
        cat_n = fi.get("cat_n"); cat_flow = fi.get("cat_flow")
        fund_rows = []
        if sym_flow is not None:
            fund_rows.append(("本品种资金流", f"{sym_flow:+.2f} 亿", up_c if sym_flow >= 0 else dn_c))
        if sym_oi is not None:
            fund_rows.append(("持仓变化", f"{sym_oi:+.1f}%", up_c if sym_oi >= 0 else dn_c))
        if sym_vr is not None:
            fund_rows.append(("量能比", f"{sym_vr:.2f} 倍", ""))
        if cat_avg is not None:
            fund_rows.append((f"所属「{category}」板块均涨跌", f"{cat_avg:+.2f}%",
                             up_c if cat_avg >= 0 else dn_c))
        if cat_rank is not None and cat_n:
            fund_rows.append((f"板块内强弱排名", f"第 {cat_rank}/{cat_n} 名", ""))
        if cat_flow is not None:
            fund_rows.append((f"板块资金净流", f"{cat_flow:+.2f} 亿", up_c if cat_flow >= 0 else dn_c))
        if fund_rows:
            fund_html = "<table style='border-collapse:collapse'>" + "".join(
                row(k, v, c) for k, v, c in fund_rows) + "</table>"
        else:
            fund_html = f"<p style='color:{mut_c}'>暂无全景资金数据（行情源未提供资金/持仓）。</p>"

        # 历史表现（原学习看板）
        def _rc(rt):
            if rt is None:
                return "#94a3b8"
            if rt >= 0.55:
                return "#10b981"
            if rt >= 0.45:
                return "#f59e0b"
            return "#ef4444"
        st = stats or {}
        total = st.get("total", 0); rate = st.get("rate")
        if rate is not None:
            head = (f"已结算 {total} 次 · 总体方向命中率 "
                    f"<b style='color:{_rc(rate)}'>{rate*100:.0f}%</b>")
        else:
            head = f"已结算 {total} 次（样本积累中）"
        if settle and settle.get("evaluated"):
            head += f" ｜ 本次自动结算 {settle['evaluated']} 条"
        hist_html = f"<p style='margin:2px 0'>{head}</p>"
        if total:
            for title, bucket in [("按模型配置", st.get("by_config", {})),
                                  ("按行情状态", st.get("by_regime", {}))]:
                if not bucket:
                    continue
                b_rows = ""
                for k2, v in bucket.items():
                    r2 = v.get("rate")
                    if r2 is None:
                        continue
                    b_rows += (f"<tr><td style='padding:2px 8px 2px 0;color:{mut_c}'>{k2}</td>"
                               f"<td style='padding-left:8px;color:{_rc(r2)}'>{r2*100:.0f}%（{v['total']}次）</td></tr>")
                if b_rows:
                    hist_html += (f"<p style='margin:6px 0 2px;font-weight:bold'>{title}</p>"
                                 f"<table style='border-collapse:collapse;font-size:12px'>{b_rows}</table>")
        closed = closed or []
        if closed:
            c_rows = ""
            for c in closed[:5]:
                hit = int(c.get("score") or 0) == 1
                act = float(c.get("actual_return_pct") or 0.0)
                col = "#10b981" if hit else "#ef4444"
                c_rows += (f"<tr><td style='padding:2px 6px 2px 0;color:{mut_c}'>{c.get('symbol','')}</td>"
                           f"<td style='padding:2px 6px;color:{mut_c}'>{c.get('verdict','')}</td>"
                           f"<td style='padding:2px 6px;color:{col}'>{'命中' if hit else '未中'}</td>"
                           f"<td style='padding:2px 6px;color:{col}'>{act:+.2f}%</td></tr>")
            hist_html += (f"<p style='margin:8px 0 2px;font-weight:bold'>最近已结算</p>"
                         f"<table style='border-collapse:collapse;font-size:12px'>"
                         f"<tr style='color:{mut_c};font-size:11px'>"
                         f"<td style='padding:2px 6px'>品种</td><td style='padding:2px 6px'>结论</td>"
                         f"<td style='padding:2px 6px'>结果</td><td style='padding:2px 6px'>实际</td></tr>"
                         f"{c_rows}</table>")

        # 操作建议
        stop = sup_lv[0] if sup_lv else last * 0.985
        pos = ("轻仓 ≤30%" if risk_score >= 70 else
               "中性 30~50%" if risk_score >= 50 else "常态 50~70%")
        plan_rows = [
            row("建议方向", f"<b style='color:{enter_col}'>{enter}</b>"),
            row("关注区间", (f"{sup_lv[0]:,.1f} ~ {res_lv[0]:,.1f}"
                 if sup_lv and res_lv else f"现价 {last:,.1f} 附近")),
            row("止损参考", f"跌破 {stop:,.1f} 离场"),
            row("仓位建议", f"风险度「{risk_label}」→ {pos}"),
        ]

        # 三面对齐提示
        model_dir = ("偏多" if p_up >= 0.55 else "偏空" if p_up <= 0.45 else "中性")
        news_dir = ("偏多" if nb > 0.05 else "偏空" if nb < -0.05 else "中性")
        if model_dir != "中性" and news_dir == model_dir and ind_dir == model_dir:
            note = (f"<p style='margin:6px 0;color:{mut_c}'>✓ 指标面 / 模型面 / 资讯面 "
                     f"三方一致（{model_dir}），信号相互印证、可信度最高，可重点参考。</p>")
        elif news_dir != "中性" and model_dir != news_dir:
            note = (f"<p style='margin:6px 0;color:{mut_c}'>⚠ 模型面「{model_dir}」与资讯面「{news_dir}」"
                     f"存在分歧，建议结合仓位管理、降低单笔风险。</p>")
        else:
            note = ""

        sec = lambda t: f"<p style='margin:12px 0 3px;font-weight:bold;color:{p['text']};font-size:13px'>{t}</p>"
        li = lambda xs: "<ul style='margin:2px 0 0 16px'>" + "".join(
            f"<li style='margin:3px 0'>{x}</li>" for x in xs) + "</ul>"
        return (
            f"<div style='color:{tx_c};font-size:13px;line-height:1.6'>"
            f"<p style='font-size:16px;font-weight:bold;color:{ccol};margin:2px 0'>"
            f"结论：未来 {horizon} 根K线偏向{dir_word}，预期涨跌 {exp:+.2f}%，综合建议「{enter}」</p>"

            f"{sec('① 能不能入手')}"
            f"<ul style='margin:2px 0 0 16px'>{''.join(f'<li style=\'margin:3px 0\'>{x}</li>' for x in enter_reason)}</ul>"

            f"{sec('② 什么时候入手（时机）')}{li(timing)}"

            f"{sec('③ 为什么不能入手 / 风险阻挡')}{li(blockers)}"

            f"{sec('④ 关键价位')}<table style='border-collapse:collapse'>{''.join(rows)}</table>"

            f"{sec('⑤ 技术面（指标分析 · 已并入 AI 预测）')}"
            f"<p style='margin:2px 0'>指标共振「<b>{reso}</b>」（多空分 {ind_score:+.0f}），"
            f"趋势「{ind_state}」，方向 <b>{ind_dir}</b>；"
            f"MACD / KDJ / RSI 三副图可见：{ind_dir}信号已由 AI 预测方向辅助印证。</p>"

            f"{sec('⑥ 模型面')}"
            f"<p style='margin:2px 0'>上涨概率 <b>{p_up*100:.0f}%</b> / 下跌 <b>{p_dn*100:.0f}%</b>，"
            f"校准后置信度 <b>{conf*100:.0f}%</b>；模型 <b>{res['model']}</b>"
            f"（{'自适应选参' if cfg.get('source')=='adaptive' else '默认增强配置'}）；"
            f"风险度「{risk_label}」（{risk_score:.0f} 分）。</p>"

            f"{sec('⑦ 资讯面')}{ai_html}{overview_html}{news_html}"

            f"{sec('⑧ 基本面 / 资金面')}{fund_html}"

            f"{sec('⑨ 历史表现（持续自我学习）')}{hist_html}{note}"

            f"{sec('⑩ 操作建议')}<table style='border-collapse:collapse'>{''.join(plan_rows)}</table>"

            f"<p style='margin:12px 0 0;color:{mut_c};font-size:11px'>"
            f"提示：预测为概率参考而非投资建议；系统会在预测到期后自动用真实行情结算命中情况，持续自我校准。</p>"
            f"</div>"
        )

    # ----------------------------- 模型评估 -----------------------------
    # 「模型评估」已并入「运行预测」自动流程：每次运行都会先结算历史预测、
    # 再据历史命中率做自适应选参与置信度校准，结果在学习看板中持续展示，
    # 因此不再需要单独的评估按钮。


# ============================================================================
# 模块四：市场全景
# ============================================================================
# ============================================================================
# 模块四：市场全景
# ============================================================================
class PanoramaPage(BasePage):
    def __init__(self, mdm, store, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "panorama"
        if session is not None:
            _, self.cur_period = session.get_page_selection("panorama", "rb.SHFE", "D")
        else:
            self.cur_period = "D"
        self._build()

    def _on_change(self):
        self.cur_period = self.per_cb.currentData()
        self.selection_changed.emit("", self.cur_period)
        self._refresh()

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
        c._val.setStyleSheet("color:%s;font-size:17px;font-weight:bold;" % (color or pal()["text"]))

    def _style_cards(self):
        p = pal()
        for c in self._kpi_cards.values():
            c.setStyleSheet(
                "QFrame#kpi-card{background:%s;border:1px solid %s;border-radius:10px;}"
                % (p["card"], p["border"]))

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "期货市场全景",
            "全市场涨跌家数 · 板块强弱轮动 · 资金流向 · 大环境温度计 —— 一眼看清当前期货市场的整体状况"))

        ctl = QHBoxLayout()
        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(lambda i: self._on_change())
        self.cat_cb = QComboBox()
        cats = ["全部"] + sorted({r[2] for r in self.mdm.universe})
        for c in cats:
            self.cat_cb.addItem(c)
        self.cat_cb.currentIndexChanged.connect(lambda i: self._refresh())
        self.refresh_btn = QPushButton("刷新"); self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(lambda: self._refresh())
        ctl.addWidget(QLabel("周期")); ctl.addWidget(self.per_cb)
        ctl.addWidget(QLabel("板块")); ctl.addWidget(self.cat_cb)
        ctl.addWidget(self.refresh_btn); ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self._dash = QWidget(); d = QVBoxLayout(self._dash)
        d.setContentsMargins(2, 2, 2, 2); d.setSpacing(10)

        # 1) KPI 英雄条
        self._kpi = QHBoxLayout(); self._kpi.setSpacing(8)
        self._kpi_cards = {}
        for key, label in [("up", "上涨家数"), ("down", "下跌家数"), ("flat", "平盘"),
                             ("breadth", "市场广度"), ("flow", "资金净流入"), ("avg", "平均涨跌"),
                             ("lead", "领涨板块"), ("lag", "领跌板块"), ("temp", "市场温度计")]:
            card = self._mk_card(label)
            self._kpi_cards[key] = card
            self._kpi.addWidget(card)
        d.addLayout(self._kpi)
        self._style_cards()

        # 2) 图表区：板块强度 + 涨跌分布/温度计
        charts = QHBoxLayout(); charts.setSpacing(10)
        lc = QWidget(); lcv = QVBoxLayout(lc); lcv.setContentsMargins(0, 0, 0, 0); lcv.setSpacing(4)
        lcv.addWidget(QLabel("板块强度榜（各板块成分品种平均涨跌幅，越长越强）"))
        self.bar = PriceChart(); self.bar.setMinimumHeight(220)
        lcv.addWidget(self.bar)
        rc = QWidget(); rcv = QVBoxLayout(rc); rcv.setContentsMargins(0, 0, 0, 0); rcv.setSpacing(6)
        rcv.addWidget(QLabel("全市场涨跌分布（红涨 / 绿跌 / 灰平）"))
        self.breadth_lbl = QLabel(); self.breadth_lbl.setWordWrap(True); self.breadth_lbl.setMinimumHeight(70)
        rcv.addWidget(self.breadth_lbl)
        rcv.addWidget(QLabel("市场温度计（广度越高越「热」）"))
        self.temp_bar = ConfidenceBar(0.5); self.temp_bar.setMinimumHeight(18)
        rcv.addWidget(self.temp_bar)
        self.temp_lbl = QLabel("—"); rcv.addWidget(self.temp_lbl)
        charts.addWidget(lc, 2); charts.addWidget(rc, 1)
        d.addLayout(charts)

        # 3) 领涨 / 领跌
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
        d.addLayout(gain)

        # 4) 资金流向 + 板块明细
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
        d.addLayout(bot)

        scroll.setWidget(self._dash)
        root.addWidget(scroll, 1)
        self._refresh()

    def _set(self, table, r, c, text, color=None):
        it = QTableWidgetItem(str(text))
        fg = (QColor(color) if isinstance(color, str) else color) if color is not None \
            else QColor(pal()["text"])
        it.setForeground(fg)
        table.setItem(r, c, it)
        return it

    def _refresh(self):
        self.cur_period = self.per_cb.currentData()
        cat = self.cat_cb.currentText()
        pan_all = self.mdm.compute_panorama(self.cur_period)
        if pan_all is None or pan_all.empty:
            return
        pan = pan_all if cat == "全部" else pan_all[pan_all["category"] == cat]

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
                      "#22c55e" if breadth >= 0.5 else ("#f59e0b" if breadth >= 0.4 else "#ef4444"))
        self._set_card("flow", f"{net_flow:+.1f}亿", "#22c55e" if net_flow >= 0 else "#ef4444")
        self._set_card("avg", f"{avg:+.2f}%", "#22c55e" if avg >= 0 else "#ef4444")
        grp = pan_all.groupby("category")["chg_pct"].mean().sort_values(ascending=False)
        lead = grp.index[0] if len(grp) else "—"
        lag = grp.index[-1] if len(grp) else "—"
        self._set_card("lead", lead, "#22c55e")
        self._set_card("lag", lag, "#ef4444")
        self.temp_bar.set_pct(breadth)
        temp = ("偏热" if breadth >= 0.55 else "中性偏暖" if breadth >= 0.45
                 else "中性" if breadth >= 0.4 else "偏冷")
        self.temp_lbl.setText(f"广度 {breadth*100:.0f}% · {temp}")
        self.temp_lbl.setStyleSheet("color:%s;" % pal()["sub"])

        # 涨跌分布（HTML 横条）
        def pct(n):
            return (n / total * 100) if total else 0.0
        p = pal()
        self.breadth_lbl.setText(
            f"<div style='font-size:13px'>"
            f"<div style='background:{p['up']};color:#fff;border-radius:4px;padding:3px 8px;margin:2px 0'>"
            f"上涨 {up} 家（{pct(up):.0f}%）</div>"
            f"<div style='background:{p['down']};color:#fff;border-radius:4px;padding:3px 8px;margin:2px 0'>"
            f"下跌 {down} 家（{pct(down):.0f}%）</div>"
            f"<div style='background:{p['sub']};color:#fff;border-radius:4px;padding:3px 8px;margin:2px 0'>"
            f"平盘 {flat} 家（{pct(flat):.0f}%）</div></div>")

        # 板块强度图（全市场板块，便于横向对比）
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

        # 板块明细表
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

    def set_theme(self, t: str) -> None:
        super().set_theme(t)
        self._style_cards()
        self.temp_lbl.setStyleSheet("color:%s;" % pal()["sub"])

class ValidatePage(BasePage):
    def __init__(self, mdm, store, config=None, session=None, header: bool = True):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "validate"
        self._show_header = header
        dft = symbol_code(mdm.universe[0])
        if session is not None:
            self.cur_symbol, self.cur_period = session.get_page_selection("validate", dft, "D")
        else:
            self.cur_symbol, self.cur_period = dft, "D"
        self._build()

    def _on_sel(self, *_):
        self.cur_symbol = self.sym_cb.currentData()
        self.cur_period = self.per_cb.currentData()
        self.selection_changed.emit(self.cur_symbol, self.cur_period)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        if self._show_header:
            root.addWidget(PageHeader("预测回测验证", "滚动起点评估 · 预测胜率 · 偏差统计"))

        ctl = QHBoxLayout()
        self.sym_cb = QComboBox(); self.sym_cb.setMinimumWidth(180)
        for r in self.mdm.universe:
            self.sym_cb.addItem(symbol_label(r), symbol_code(r))
        self.sym_cb.setCurrentIndex(max(0, self.sym_cb.findData(self.cur_symbol)))
        self.sym_cb.currentIndexChanged.connect(self._on_sel)
        self.per_cb = QComboBox()
        for p in PERIODS:
            self.per_cb.addItem(PERIOD_LABEL[p], p)
        self.per_cb.setCurrentIndex(max(0, self.per_cb.findData(self.cur_period)))
        self.per_cb.currentIndexChanged.connect(self._on_sel)
        self.hor_spin = QSpinBox(); self.hor_spin.setRange(3, 20); self.hor_spin.setValue(5)
        self.orig_spin = QSpinBox(); self.orig_spin.setRange(3, 15); self.orig_spin.setValue(6)
        self.lstm_chk = QCheckBox("用LSTM(较慢)"); self.lstm_chk.setChecked(False)
        self.run_btn = QPushButton("开始验证"); self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        ctl.addWidget(QLabel("合约")); ctl.addWidget(self.sym_cb)
        ctl.addWidget(QLabel("周期")); ctl.addWidget(self.per_cb)
        ctl.addWidget(QLabel("预测步")); ctl.addWidget(self.hor_spin)
        ctl.addWidget(QLabel("起点数")); ctl.addWidget(self.orig_spin)
        ctl.addWidget(self.lstm_chk); ctl.addWidget(self.run_btn)
        ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        self.metrics = QLabel("点击「开始验证」评估该品种预测模型的准确性。")
        self.metrics.setWordWrap(True)
        root.addWidget(self.metrics)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.chart = PriceChart(); self.chart.setMinimumHeight(240)
        split.addWidget(self.chart)
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["起点", "方向胜率%", "平均误差", "最大偏差"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        split.addWidget(self.tbl)
        split.setStretchFactor(0, 2); split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

    def _run(self):
        sym = self.sym_cb.currentData(); per = self.per_cb.currentData()
        horizon = self.hor_spin.value(); n_orig = self.orig_spin.value()
        use_lstm = self.lstm_chk.isChecked()
        self.run_btn.setEnabled(False); self.run_btn.setText("验证中…")
        df_full = self.mdm.get_bars(sym, per, 800)

        def work():
            rows = []; ex_actual = []; ex_pred = []
            total = len(df_full)
            step = max(1, (total - horizon - 60) // max(1, n_orig))
            origins = list(range(60, total - horizon, max(1, step)))[:n_orig]
            for oi, origin in enumerate(origins):
                train = df_full.iloc[:origin]
                test = df_full.iloc[origin:origin + horizon + 1]
                if len(train) < 40 or len(test) <= horizon:
                    continue
                p = FuturesPredictor()
                p.fit(train, seq_len=20, epochs=(20 if use_lstm else 1),
                      force_ridge=not use_lstm)
                res = p.predict(train, horizon=horizon)
                actual = test["close"].values[:horizon + 1]
                pred = np.array(res["forecast"][:horizon + 1])
                if len(pred) != len(actual):
                    continue
                direc_ok = sum(1 for k in range(1, len(actual))
                               if (actual[k] - actual[k-1]) * (pred[k] - pred[k-1]) > 0)
                direc_rate = direc_ok / (len(actual) - 1) * 100
                errs = np.abs(pred - actual) / actual * 100
                rows.append((origin, direc_rate, errs.mean(), errs.max()))
                if oi == len(origins) - 1:
                    ex_actual = actual.tolist(); ex_pred = pred.tolist()
            return {"rows": rows, "ex_actual": ex_actual, "ex_pred": ex_pred,
                    "sym": sym, "per": per, "horizon": horizon, "use_lstm": use_lstm}

        self._run_worker(work, self._on_done,
                         on_err=lambda e: (print("验证错误:", e),
                                           self.run_btn.setEnabled(True),
                                           self.run_btn.setText("开始验证")))

    def _on_done(self, r):
        self.run_btn.setEnabled(True); self.run_btn.setText("开始验证")
        if not r["rows"]:
            self.metrics.setText("数据不足，无法验证。")
            return
        import statistics as st
        dr = [x[1] for x in r["rows"]]
        ae = [x[2] for x in r["rows"]]
        me = [x[3] for x in r["rows"]]
        self.metrics.setText(
            f"品种 {r['sym']} · 周期 {PERIOD_LABEL.get(r['per'], r['per'])} · 预测步 {r['horizon']} · "
            f"模型 {'LSTM' if r['use_lstm'] else '岭回归'}\n"
            f"方向胜率：均值 {st.mean(dr):.1f}%（min {min(dr):.1f} / max {max(dr):.1f}）\n"
            f"平均相对误差：{st.mean(ae):.2f}%　最大单点偏差：{max(me):.2f}%\n"
            f"趋势捕捉率（方向胜率>50% 的起点占比）：{sum(1 for x in dr if x>50)/len(dr)*100:.0f}%")
        self.tbl.setRowCount(len(r["rows"]))
        for i, row in enumerate(r["rows"]):
            self.tbl.setItem(i, 0, QTableWidgetItem(str(row[0])))
            self.tbl.setItem(i, 1, QTableWidgetItem(f"{row[1]:.1f}"))
            self.tbl.setItem(i, 2, QTableWidgetItem(f"{row[2]:.2f}%"))
            self.tbl.setItem(i, 3, QTableWidgetItem(f"{row[3]:.2f}%"))
        prepare_table(self.tbl)
        n = len(r["ex_actual"])
        self.chart.set_data(series=[
            {"name": "实际", "color": "#3b82f6", "x": list(range(n)), "y": r["ex_actual"]},
            {"name": "预测", "color": "#f59e0b", "x": list(range(n)), "y": r["ex_pred"], "dashed": True},
        ], title=f"{r['sym']} 末起点 实际 vs 预测")


# ============================================================================
# 模块六：日志 / 预警 / 报告
# ============================================================================
class LogPage(BasePage):
    def __init__(self, mdm, store, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "log"
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader("日志 / 预警 / 报告", "运行日志 · 预警触发 · 预测与研判存档 · 导出"))

        ctl = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新"); self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self._refresh)
        self.export_btn = QPushButton("导出CSV"); self.export_btn.setObjectName("secondary")
        self.export_btn.clicked.connect(self._export)
        ctl.addWidget(self.refresh_btn); ctl.addWidget(self.export_btn); ctl.addStretch(1)
        root.addWidget(ToolBar(ctl))

        self.tabs = QTabWidget()
        self.tab_log = QTableWidget(0, 3)
        self.tab_log.setHorizontalHeaderLabels(["时间", "级别", "内容"])
        self.tab_alert = QTableWidget(0, 5)
        self.tab_alert.setHorizontalHeaderLabels(["时间", "合约", "规则", "级别", "内容"])
        self.tab_pred = QTableWidget(0, 7)
        self.tab_pred.setHorizontalHeaderLabels(
            ["时间", "合约", "周期", "预期收益%", "涨概", "风险", "模型"])
        self.tab_an = QTableWidget(0, 4)
        self.tab_an.setHorizontalHeaderLabels(["时间", "合约", "类型", "结论"])
        for t in (self.tab_log, self.tab_alert, self.tab_pred, self.tab_an):
            t.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.tab_log, "运行日志")
        self.tabs.addTab(self.tab_alert, "预警记录")
        self.tabs.addTab(self.tab_pred, "预测存档")
        self.tabs.addTab(self.tab_an, "研判存档")
        root.addWidget(self.tabs, 1)
        self._refresh()

    def _refresh(self):
        logs = self.store.query_logs(300)
        self.tab_log.setRowCount(len(logs))
        for i, r in enumerate(logs):
            self.tab_log.setItem(i, 0, QTableWidgetItem(str(r["ts"])[11:19]))
            self.tab_log.setItem(i, 1, QTableWidgetItem(str(r["level"])))
            self.tab_log.setItem(i, 2, QTableWidgetItem(str(r["message"])))
        prepare_table(self.tab_log)

        alerts = self.store.query_alerts(200)
        self.tab_alert.setRowCount(len(alerts))
        for i, r in enumerate(alerts):
            self.tab_alert.setItem(i, 0, QTableWidgetItem(str(r["ts"])[11:19]))
            self.tab_alert.setItem(i, 1, QTableWidgetItem(str(r["symbol"])))
            self.tab_alert.setItem(i, 2, QTableWidgetItem(str(r["rule"])))
            self.tab_alert.setItem(i, 3, QTableWidgetItem(str(r["level"])))
            self.tab_alert.setItem(i, 4, QTableWidgetItem(str(r["message"])))
        prepare_table(self.tab_alert)

        preds = self.store.query_predictions(200)
        self.tab_pred.setRowCount(len(preds))
        for i, r in enumerate(preds):
            self.tab_pred.setItem(i, 0, QTableWidgetItem(str(r["ts"])[11:19]))
            self.tab_pred.setItem(i, 1, QTableWidgetItem(str(r["symbol"])))
            self.tab_pred.setItem(i, 2, QTableWidgetItem(str(r["period"])))
            self.tab_pred.setItem(i, 3, QTableWidgetItem(f"{r['expected_return_pct']:.2f}"))
            self.tab_pred.setItem(i, 4, QTableWidgetItem(f"{r['p_up']*100:.1f}%"))
            self.tab_pred.setItem(i, 5, QTableWidgetItem(f"{r['risk_label']}"))
            self.tab_pred.setItem(i, 6, QTableWidgetItem(str(r["model"])))
        prepare_table(self.tab_pred)

        an = self.store.query_analysis(200)
        self.tab_an.setRowCount(len(an))
        for i, r in enumerate(an):
            self.tab_an.setItem(i, 0, QTableWidgetItem(str(r["ts"])[11:19]))
            self.tab_an.setItem(i, 1, QTableWidgetItem(str(r["symbol"])))
            self.tab_an.setItem(i, 2, QTableWidgetItem(str(r["kind"])))
            self.tab_an.setItem(i, 3, QTableWidgetItem(str(r["summary"])))
        prepare_table(self.tab_an)

    def _export(self):
        idx = self.tabs.currentIndex()
        table = ["logs", "alerts", "predictions", "analysis"][idx]
        path = f"data/export_{table}.csv"
        ok = self.store.export_csv(table, path)
        self.store.add_log(str(dt.datetime.now()), "INFO",
                           f"导出 {table} -> {path} {'成功' if ok else '失败'}")
        self._refresh()
