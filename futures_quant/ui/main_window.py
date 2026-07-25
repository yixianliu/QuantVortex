"""期货智能分析预测系统 · 主窗口外壳。

布局：左侧导航菜单 / 中间功能主区（六页堆叠）/ 底部状态栏（连接状态 + 时钟 + 日志）。
仅依赖 PyQt6 / numpy / pandas，离线可跑；数据默认走合成行情（模拟），
生产环境在 data/ctp_gateway.py 替换为 CTPFeed 即可，本文件零改动。
"""
from __future__ import annotations

import datetime as dt
import os

from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QStackedWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QStatusBar, QFrame, QSizePolicy, QSystemTrayIcon,
)

from .widgets import THEME, pal, PALETTE
from .icons import icon
from .pages import (
    MarketPage, PredictPage, PanoramaPage, ValidatePage, LogPage,
)
from .backtest_page import BacktestCenterPage
from .screening_page import ScreeningPage
from .ctp_monitor_page import CTPMonitorPage
from .data_page import DataPage
from ..storage.config_manager import ConfigManager, SessionState
from ..runtime import get_font_paths

NAV = [
    ("行情全景", MarketPage, "market", "market"),
    ("AI 预测", PredictPage, "predict", "predict"),
    ("市场全景", PanoramaPage, "panorama", "panorama"),
    ("回测中心", BacktestCenterPage, "backtest", "backtest"),
    ("选品机会", ScreeningPage, "filter", "screening"),
    ("实盘监控", CTPMonitorPage, "ctp", "ctp"),
    ("日志预警", LogPage, "log", "log"),
    ("数据管理", DataPage, "db", "data"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # ---- 持久化：配置 + 运行时状态 ----
        self.config = ConfigManager()
        if os.environ.get("QUANTVORTEX_NO_PERSIST", "0") == "1":
            import tempfile
            self.session = SessionState(path=os.path.join(tempfile.mkdtemp(), "session_state.json"))
        else:
            self.session = SessionState()
        self.theme = self.config.get("ui.theme", "dark")

        from ..data.market_data import MarketDataManager
        from ..storage.analysis_store import AnalysisStore
        src = self.config.get("data.source", "sina")
        self.mdm = MarketDataManager(source=src)
        db_path = self.config.get("data.sqlite_path", "data/quant_analysis.db")
        self.store = AnalysisStore(db_path)
        self.store.maintenance()   # 启动维护：合并 WAL + 限容
        self.mdm.connect()
        self.store.add_log(str(dt.datetime.now()), "INFO",
                          f"系统启动 · 数据源：{self.mdm.source_label}")

        self.setWindowTitle("期货智能分析预测系统")
        # 最小尺寸约束：避免窗口过小导致组件挤压 / 遮挡
        self.setMinimumWidth(1100)
        self.setMinimumHeight(680)
        self._build()
        self._apply_theme()
        self._restore_geometry()

        # 时钟
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()

        # 会话状态防抖落盘
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.timeout.connect(lambda: self.session.flush())

        # 恢复上次停留页
        last = int(self.session.get("last_page", 0) or 0)
        if 0 <= last < len(self.pages):
            self.nav.setCurrentRow(last)
            self.stack.setCurrentIndex(last)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧导航
        self.nav = QListWidget()
        self.nav.setFixedWidth(168)
        self.nav.setObjectName("nav")
        self.nav.currentRowChanged.connect(self._switch)
        for title, _, ic, _k in NAV:
            item = QListWidgetItem(icon(ic, "dark"), title)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.nav.addItem(item)
        root.addWidget(self.nav)

        # 右侧主区
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        self.pages = []
        for title, cls, _, key in NAV:
            page = cls(self.mdm, self.store, self.config, self.session)
            page.PAGE_KEY = key
            page.selection_changed.connect(
                lambda sym, per, k=key: self._on_sel(k, sym, per))
            self.pages.append(page)
            self.stack.addWidget(page)
        # 预警托盘通知（有系统托盘时启用）
        self._setup_tray()
        for p in self.pages:
            if hasattr(p, "alerts_fired"):
                p.alerts_fired.connect(self._on_alerts_fired)
            if hasattr(p, "scan_status"):
                p.scan_status.connect(self._on_scan_status)
        right.addWidget(self.stack, 1)

        # 底部状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._status_conn = QLabel("● 离线")
        self._status_conn.setObjectName("status-dot")
        self._status_src = QLabel("数据源：合成行情(模拟)")
        self._status_clock = QLabel("")
        self._status_log = QLabel("")
        self.status.addWidget(self._status_conn)
        self.status.addWidget(self._status_src)
        self.status.addPermanentWidget(self._status_clock)
        self._conn_btn = QPushButton("重连")
        self._conn_btn.setObjectName("secondary")
        self._conn_btn.setFixedHeight(22)
        self._conn_btn.clicked.connect(self._reconnect)
        self.status.addPermanentWidget(self._conn_btn)
        self._theme_btn = QPushButton()
        self._theme_btn.setObjectName("secondary")
        self._theme_btn.setFixedSize(28, 22)
        self._theme_btn.clicked.connect(self._toggle_theme)
        self.status.addPermanentWidget(self._theme_btn)
        self.status.addPermanentWidget(self._status_log)

        # 顶部菜单栏
        self._build_menu()

        rwidget = QWidget()
        rwidget.setLayout(right)
        root.addWidget(rwidget)

    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        mb = self.menuBar()
        mb.setObjectName("menubar")
        # 视图
        view = mb.addMenu("视图")
        act_theme = view.addAction("切换主题（深/浅）")
        act_theme.setShortcut("Ctrl+T")
        act_theme.triggered.connect(self._toggle_theme)
        # 数据
        data = mb.addMenu("数据")
        act_reconnect = data.addAction("重连数据源")
        act_reconnect.triggered.connect(self._reconnect)
        data.addSeparator()
        act_export = data.addAction("数据导出…")
        act_export.triggered.connect(lambda: self._goto_page("data"))
        act_backup = data.addAction("备份 / 恢复…")
        act_backup.triggered.connect(lambda: self._goto_page("data"))
        # 帮助
        helpm = mb.addMenu("帮助")
        act_about = helpm.addAction("关于")
        act_about.triggered.connect(self._about)

    # ------------------------------------------------------------------
    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(icon("warning", self.theme, size=32))
        self._tray.setToolTip("期货智能分析预测系统")
        self._tray.show()

    def _on_alerts_fired(self, fired: list) -> None:
        """预警触发：状态栏 + 托盘气泡（日志由 MarketPage 写入）。"""
        if not fired:
            return
        top = fired[0]
        self._status_log.setText(f"⚠ 预警：{top['symbol']} {top['message']}")
        if self._tray is not None:
            title = f"期货预警 · 新增 {len(fired)} 条"
            body = "\n".join(f"· {f['symbol']} {f['message']}" for f in fired[:5])
            try:
                self._tray.showMessage(
                    title, body, QSystemTrayIcon.MessageIcon.Warning, 4000)
            except Exception:  # noqa: BLE001
                pass

    def _on_scan_status(self, msg: str) -> None:
        """扫描状态反馈：写入底部状态栏（加载 / 成功 / 失败）。"""
        self._status_log.setText(f"◌ {msg}")

    def _about(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "关于",
            "期货智能分析预测系统\n\n"
            "行情分析 · AI 趋势预测 · 量化信号研判 · 数据复盘 · 风险分析\n"
            "数据默认接入新浪实盘日线（可切换合成 / CTP 柜台）。\n\n"
            "本软件仅用于学习与研究，不构成任何投资建议。")

    def _goto_page(self, key: str) -> None:
        """按页面 key 跳转（菜单快捷入口用）。"""
        for i, (_, _, _, k) in enumerate(NAV):
            if k == key:
                self.nav.setCurrentRow(i)
                self.stack.setCurrentIndex(i)
                break

    # ------------------------------------------------------------------
    def _switch(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self.session.set("last_page", idx)
        self._schedule_session_save()

    def _on_sel(self, key: str, symbol: str, period: str) -> None:
        """各页合约/周期变更 → 写入会话状态，便于崩溃/重启后恢复。"""
        self.session.set_page_selection(key, symbol or "", period or "")
        self._schedule_session_save()

    # ------------------------------------------------------------------
    def _restore_geometry(self) -> None:
        w = self.session.get("window", {})
        self._want_max = bool(w.get("maximized", True))
        x, y = w.get("x"), w.get("y")
        ww, hh = int(w.get("w", 1360) or 1360), int(w.get("h", 860) or 860)
        if x is not None and y is not None:
            self.setGeometry(int(x), int(y), ww, hh)
        else:
            self.resize(ww, hh)

    def _schedule_session_save(self) -> None:
        if not self._session_timer.isActive():
            self._session_timer.start(600)

    def _save_geometry(self) -> None:
        if self.isMaximized():
            self.session.set("window", {"maximized": True,
                                        "w": self.width(), "h": self.height()})
        else:
            g = self.geometry()
            self.session.set("window", {"x": g.x(), "y": g.y(),
                                        "w": g.width(), "h": g.height(),
                                        "maximized": False})
        self._schedule_session_save()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._save_geometry()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._save_geometry()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.session.flush()
        try:
            self.store.close()
        except Exception:
            pass
        super().closeEvent(event)

    def _reconnect(self) -> None:
        self.mdm.connect()
        self._update_status()

    def _update_status(self) -> None:
        if self.mdm.status.startswith("已连接"):
            self._status_conn.setText("● 已连接")
            self._status_conn.setStyleSheet("color:#22c55e;")
        else:
            self._status_conn.setText("● 离线")
            self._status_conn.setStyleSheet("color:#ef4444;")
        self._status_src.setText(f"数据源：{self.mdm.source_label}")

    def _tick_clock(self) -> None:
        self._status_clock.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))

    # ------------------------------------------------------------------
    def _toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        self.config.set("ui.theme", self.theme)
        self.config.save()
        self._apply_theme()

    def _apply_theme(self) -> None:
        from . import widgets as W
        W.THEME = self.theme
        qss = DARK_QSS if self.theme == "dark" else LIGHT_QSS
        self.setStyleSheet(qss)
        # 导航图标重渲染
        for i, (_, _, ic, _k) in enumerate(NAV):
            self.nav.item(i).setIcon(icon(ic, self.theme))
        # 主题按钮图标
        self._theme_btn.setIcon(icon("sun" if self.theme == "dark" else "moon", self.theme))
        # 页面与图表
        for p in self.pages:
            p.set_theme(self.theme)
            for attr in ("chart", "macd", "kdj", "rsi", "bar"):
                c = getattr(p, attr, None)
                if c is not None and hasattr(c, "set_theme"):
                    c.set_theme(self.theme)
        self._update_status()


# ============================================================================
# QSS
# ============================================================================
DARK_QSS = """
/* ===== 基础 ===== */
QWidget { background:#0f1116; color:#e6e6e6; font-family:'SimHei','Noto Sans SC','Microsoft YaHei',sans-serif; font-size:13px; }
QMainWindow { background:#0f1116; }
QFrame#toolbar { background:#161a24; border:1px solid #2a2e3a; border-radius:10px; }
QFrame#hsep { background:#1a1d27; border:none; }

/* ===== 侧边导航 ===== */
QListWidget#nav { background:#0b0d12; border:none; padding-top:10px; padding-bottom:10px; outline:0; }
QListWidget#nav::item { color:#9aa3b5; padding:12px 16px; border-left:3px solid transparent; margin:2px 8px; border-radius:8px; }
QListWidget#nav::item:hover { background:#161a24; color:#e6e6e6; }
QListWidget#nav::item:selected { background:#1b2230; color:#fff; border-left:3px solid #2563eb; }

/* ===== 内容区 ===== */
QStackedWidget { background:#0f1116; }

/* ===== 文本 ===== */
QLabel { color:#e6e6e6; background:transparent; }
QLabel#sub { color:#8b93a7; }

/* ===== 按钮 ===== */
QPushButton { background:#2563eb; color:#fff; border:1px solid transparent; border-radius:8px; padding:8px 18px; font-size:13px; font-weight:bold; }
QPushButton:hover { background:#1d4ed8; border-color:#2563eb; }
QPushButton:pressed { background:#1e40af; padding-top:9px; padding-bottom:7px; }
QPushButton:focus { border:1px solid #60a5fa; outline:none; }
QPushButton:disabled { background:#27303f; color:#6b7280; border-color:transparent; }
QPushButton#secondary { background:rgba(255,255,255,0.02); color:#cbd5e1; border:1px solid #2a2e3a; font-weight:500; }
QPushButton#secondary:hover { background:#1a1d27; border-color:#3a4154; color:#fff; }
QPushButton#secondary:pressed { background:#11141c; }
QPushButton#secondary:focus { border-color:#60a5fa; }
QPushButton#primary { background:#2563eb; }
QPushButton#primary:hover { background:#1d4ed8; }
QPushButton#danger { background:#dc2626; }
QPushButton#danger:hover { background:#b91c1c; }
QPushButton#danger:pressed { background:#991b1b; }

/* ===== 输入控件 ===== */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background:#11141c; border:1px solid #2a2e3a; border-radius:8px; padding:6px 10px; color:#e6e6e6; font-size:13px; selection-background-color:#2563eb; selection-color:#fff; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover { border-color:#3a4154; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus { border:1px solid #3b82f6; background:#151923; }
QComboBox::drop-down { border:none; width:20px; }
QComboBox QAbstractItemView { background:#11141c; color:#e6e6e6; selection-background-color:#2563eb; border:1px solid #2a2e3a; border-radius:8px; outline:0; padding:4px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width:16px; border:none; background:transparent; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover { background:#1a1d27; }

/* ===== 表格 ===== */
QTableWidget { background:#11141c; gridline-color:#1a1d27; border:1px solid #2a2e3a; border-radius:10px; outline:0; font-size:12px; }
QTableWidget::item { padding:6px 8px; border:none; }
QTableWidget::item:selected { background:#1f2a44; color:#fff; }
QHeaderView::section { background:#161a24; color:#8b93a7; border:none; padding:8px; font-weight:bold; font-size:12px; }
QHeaderView::section:hover { color:#e6e6e6; }
QTableWidget::item:hover { background:#232838; }

/* ===== 标签页 ===== */
QTabWidget::pane { border:1px solid #2a2e3a; border-radius:10px; top:-1px; }
QTabBar::tab { background:#11141c; color:#8b93a7; padding:9px 16px; margin-right:2px; border-top-left-radius:8px; border-top-right-radius:8px; }
QTabBar::tab:selected { background:#161a24; color:#fff; }
QTabBar::tab:hover { color:#e6e6e6; }

/* ===== 滚动条 ===== */
QScrollBar:vertical { background:#0f1116; width:11px; border-radius:6px; margin:2px; }
QScrollBar::handle:vertical { background:#2a2e3a; border-radius:6px; min-height:28px; }
QScrollBar::handle:vertical:hover { background:#3a4154; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:#0f1116; height:11px; border-radius:6px; margin:2px; }
QScrollBar::handle:horizontal { background:#2a2e3a; border-radius:6px; min-width:28px; }
QScrollBar::handle:horizontal:hover { background:#3a4154; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }

/* ===== 复选框 ===== */
QCheckBox { color:#cbd5e1; spacing:8px; background:transparent; }
QCheckBox::indicator { width:16px; height:16px; border-radius:4px; border:1px solid #3a4154; background:#11141c; }
QCheckBox::indicator:hover { border-color:#3b82f6; }
QCheckBox::indicator:checked { background:#2563eb; border-color:#2563eb; }
QCheckBox::indicator:checked:hover { background:#1d4ed8; }

/* ===== 菜单栏 / 菜单 ===== */
QMenuBar { background:#0b0d12; color:#cbd5e1; padding:3px 6px; border-bottom:1px solid #2a2e3a; spacing:2px; }
QMenuBar::item { background:transparent; padding:6px 14px; border-radius:6px; }
QMenuBar::item:selected { background:#2563eb; color:#fff; }
QMenuBar::item:pressed { background:#1d4ed8; }
QMenu { background:#11141c; color:#e6e6e6; border:1px solid #2a2e3a; border-radius:10px; padding:6px; }
QMenu::item { padding:8px 26px 8px 14px; border-radius:6px; }
QMenu::item:selected { background:#2563eb; color:#fff; }
QMenu::separator { height:1px; background:#2a2e3a; margin:5px 10px; }

/* ===== 状态栏 ===== */
QStatusBar { background:#0b0d12; color:#8b93a7; border-top:1px solid #2a2e3a; padding:5px 12px; }
QStatusBar::item { border:none; }
#status-dot { color:#22c55e; font-weight:bold; font-size:13px; }
QFrame#chip { border-radius:12px; }
QToolTip { background:#161a24; color:#e6e6e6; border:1px solid #2a2e3a; border-radius:6px; padding:5px 8px; }
"""

LIGHT_QSS = """
/* ===== 基础 ===== */
QWidget { background:#f5f7fa; color:#1f2937; font-family:'SimHei','Noto Sans SC','Microsoft YaHei',sans-serif; font-size:13px; }
QMainWindow { background:#f5f7fa; }
QFrame#toolbar { background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; }
QFrame#hsep { background:#e5e7eb; border:none; }

/* ===== 侧边导航 ===== */
QListWidget#nav { background:#eef2f7; border:none; padding-top:10px; padding-bottom:10px; outline:0; }
QListWidget#nav::item { color:#475569; padding:12px 16px; border-left:3px solid transparent; margin:2px 8px; border-radius:8px; }
QListWidget#nav::item:hover { background:#ffffff; color:#111827; }
QListWidget#nav::item:selected { background:#e0ecff; color:#111827; border-left:3px solid #2563eb; }

/* ===== 内容区 ===== */
QStackedWidget { background:#f5f7fa; }

/* ===== 文本 ===== */
QLabel { color:#1f2937; background:transparent; }
QLabel#sub { color:#6b7280; }

/* ===== 按钮 ===== */
QPushButton { background:#2563eb; color:#fff; border:1px solid transparent; border-radius:8px; padding:8px 18px; font-size:13px; font-weight:bold; }
QPushButton:hover { background:#1d4ed8; }
QPushButton:pressed { background:#1e40af; padding-top:9px; padding-bottom:7px; }
QPushButton:focus { border:1px solid #2563eb; outline:none; }
QPushButton:disabled { background:#e2e8f0; color:#94a3b8; border-color:transparent; }
QPushButton#secondary { background:#ffffff; color:#334155; border:1px solid #d1d5db; font-weight:500; }
QPushButton#secondary:hover { background:#f1f5f9; border-color:#94a3b8; }
QPushButton#secondary:pressed { background:#e9eef5; }
QPushButton#secondary:focus { border-color:#2563eb; }
QPushButton#primary { background:#2563eb; }
QPushButton#primary:hover { background:#1d4ed8; }
QPushButton#danger { background:#dc2626; }
QPushButton#danger:hover { background:#b91c1c; }

/* ===== 输入控件 ===== */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background:#ffffff; border:1px solid #d1d5db; border-radius:8px; padding:6px 10px; color:#1f2937; font-size:13px; selection-background-color:#2563eb; selection-color:#fff; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover { border-color:#94a3b8; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus { border:1px solid #2563eb; background:#ffffff; }
QComboBox::drop-down { border:none; width:20px; }
QComboBox QAbstractItemView { background:#ffffff; color:#1f2937; selection-background-color:#2563eb; selection-color:#fff; border:1px solid #d1d5db; border-radius:8px; outline:0; padding:4px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width:16px; border:none; background:transparent; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover { background:#f1f5f9; }

/* ===== 表格 ===== */
QTableWidget { background:#ffffff; gridline-color:#eef2f7; border:1px solid #d1d5db; border-radius:10px; outline:0; font-size:12px; }
QTableWidget::item { padding:6px 8px; border:none; }
QTableWidget::item:selected { background:#dbeafe; color:#111827; }
QHeaderView::section { background:#eef2f7; color:#6b7280; border:none; padding:8px; font-weight:bold; font-size:12px; }
QHeaderView::section:hover { color:#111827; }
QTableWidget::item:hover { background:#eff6ff; }

/* ===== 标签页 ===== */
QTabWidget::pane { border:1px solid #d1d5db; border-radius:10px; top:-1px; }
QTabBar::tab { background:#eef2f7; color:#6b7280; padding:9px 16px; margin-right:2px; border-top-left-radius:8px; border-top-right-radius:8px; }
QTabBar::tab:selected { background:#ffffff; color:#111827; }
QTabBar::tab:hover { color:#111827; }

/* ===== 滚动条 ===== */
QScrollBar:vertical { background:#f5f7fa; width:11px; border-radius:6px; margin:2px; }
QScrollBar::handle:vertical { background:#cbd5e1; border-radius:6px; min-height:28px; }
QScrollBar::handle:vertical:hover { background:#94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:#f5f7fa; height:11px; border-radius:6px; margin:2px; }
QScrollBar::handle:horizontal { background:#cbd5e1; border-radius:6px; min-width:28px; }
QScrollBar::handle:horizontal:hover { background:#94a3b8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }

/* ===== 复选框 ===== */
QCheckBox { color:#334155; spacing:8px; background:transparent; }
QCheckBox::indicator { width:16px; height:16px; border-radius:4px; border:1px solid #94a3b8; background:#ffffff; }
QCheckBox::indicator:hover { border-color:#2563eb; }
QCheckBox::indicator:checked { background:#2563eb; border-color:#2563eb; }
QCheckBox::indicator:checked:hover { background:#1d4ed8; }

/* ===== 菜单栏 / 菜单 ===== */
QMenuBar { background:#eef2f7; color:#334155; padding:3px 6px; border-bottom:1px solid #d1d5db; spacing:2px; }
QMenuBar::item { background:transparent; padding:6px 14px; border-radius:6px; }
QMenuBar::item:selected { background:#2563eb; color:#fff; }
QMenuBar::item:pressed { background:#1d4ed8; }
QMenu { background:#ffffff; color:#1f2937; border:1px solid #d1d5db; border-radius:10px; padding:6px; }
QMenu::item { padding:8px 26px 8px 14px; border-radius:6px; }
QMenu::item:selected { background:#2563eb; color:#fff; }
QMenu::separator { height:1px; background:#e2e8f0; margin:5px 10px; }

/* ===== 状态栏 ===== */
QStatusBar { background:#eef2f7; color:#6b7280; border-top:1px solid #d1d5db; padding:5px 12px; }
QStatusBar::item { border:none; }
#status-dot { color:#16a34a; font-weight:bold; font-size:13px; }
QFrame#chip { border-radius:12px; }
QToolTip { background:#ffffff; color:#1f2937; border:1px solid #d1d5db; border-radius:6px; padding:5px 8px; }
"""


def main() -> None:
    import os
    import sys
    from PyQt6.QtGui import QFont, QFontDatabase
    app = QApplication([])
    # 显式加载中文字体，避免无 CJK 字形时回退成 tofu。
    # 优先用内嵌/系统字体，按注册成功的家族设置；全部失败时退回 Qt 系统默认（含 CJK 回退）。
    chosen_family = ""
    for fp in get_font_paths():
        fid = QFontDatabase.addApplicationFont(fp)
        if fid >= 0:
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                chosen_family = fams[0]
                break
    if chosen_family:
        app.setFont(QFont(chosen_family, 10))
    else:
        app.setFont(QFont("", 10))  # 让 Qt 走系统默认字体（带 CJK 回退）
    win = MainWindow()

    # ---- 全局崩溃兜底：异常时尽量落盘状态，并写入崩溃日志 ----
    def _excepthook(etype, exc, tb):  # noqa: ANN001
        try:
            win.session.flush()
            win.store.add_log(
                str(dt.datetime.now()), "CRASH",
                f"{etype.__name__}: {exc}")
            win.store.close()
        except Exception:
            pass
        sys.__excepthook__(etype, exc, tb)
    sys.excepthook = _excepthook

    # 恢复上次窗口状态（默认最大化）
    if getattr(win, "_want_max", True):
        win.showMaximized()
    else:
        win.show()
    app.exec()


if __name__ == "__main__":
    main()
