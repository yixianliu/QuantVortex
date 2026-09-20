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
    ValidatePage, LogPage,
)
from .predict_ops_page import PredictOpsPage
from .market_overview_page import MarketOverviewPage
from .backtest_page import BacktestCenterPage
from .ctp_monitor_page import CTPMonitorPage
from .data_page import DataPage
from .simple_backtest_page import SimpleBacktestPage
from .ai_settings_dialog import AIConfigDialog
from ..storage.config_manager import ConfigManager, SessionState
from ..runtime import get_font_paths
from .. import __version__ as APP_VERSION
from .responsive_layout import get_layout_manager

AGNES_API_BASE = "https://api.agnes-ai.cn/v1/chat/completions"

NAV = [
    ("行情全景", MarketOverviewPage, "market", "market"),
    ("预测操作", PredictOpsPage, "predict", "predict_ops"),
    ("回测中心", BacktestCenterPage, "backtest", "backtest"),
    ("独立回测", SimpleBacktestPage, "backtest", "simple_backtest"),
    ("实盘监控", CTPMonitorPage, "ctp", "ctp"),
    ("日志预警", LogPage, "log", "log"),
    ("数据管理", DataPage, "db", "data"),
]


class MainWindow(QMainWindow):
    """主窗口：承载各功能页面与菜单，负责页面切换、会话保活与全局异常处理。
    
        继承: QMainWindow"""
    def __init__(self) -> None:
        """初始化相关对象。"""
        super().__init__()
        # ---- 持久化：配置 + 运行时状态 ----
        self.config = ConfigManager()
        if os.environ.get("QUANTVORTEX_NO_PERSIST", "0") == "1":
            import tempfile
            self.session = SessionState(path=os.path.join(tempfile.mkdtemp(), "session_state.json"))
        else:
            self.session = SessionState()
        self.theme = self.config.get("ui.theme", "dark")

        # ---- 早期初始化 AI 配置：确保环境变量中的 API 密钥尽早加载到单例 ----
        from ..ai.config import get_ai_config
        get_ai_config(self.config)

        from ..data.market_data import MarketDataManager
        from ..storage.analysis_store import AnalysisStore
        src = self.config.get("data.source", "sina")
        self.mdm = MarketDataManager(source=src)
        db_path = self.config.get("data.sqlite_path", "data/quant_analysis.db")
        self.store = AnalysisStore(db_path)
        self.store.maintenance()   # 启动维护：合并 WAL + 限容
        # 数据源探测改为异步：window 先显示，避免网络探测阻塞 10s+
        self._connect_deferred = QTimer(self)
        self._connect_deferred.setSingleShot(True)
        self._connect_deferred.timeout.connect(self._do_connect)
        self._connect_deferred.start(0)  # 下一轮事件循环再执行

        # ---- 响应式布局管理 ----
        self._layout_mgr = get_layout_manager()

        self.setWindowTitle(f"期货智能分析预测系统  v{APP_VERSION}")
        # 根据分辨率动态调整最小尺寸约束
        min_w, min_h = self._layout_mgr.get_min_window_size()
        self.setMinimumWidth(min_w)
        self.setMinimumHeight(min_h)
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

        # 启动默认进入「行情全景」页（需求：程序启动后默认进入行情全景页面，
        # 并自动触发市场数据刷新与新闻资讯解读——由该页 showEvent 自动拉取）。
        self.nav.setCurrentRow(0)
        self.stack.setCurrentIndex(0)

        # ---- 服务注册：解耦 UI 与业务层 ----
        try:
            from futures_quant.app.service_locator import provide
            from futures_quant.app.backtest_service import BacktestService

            # 注册核心服务
            provide("market_data_manager", self.mdm)
            provide("analysis_store", self.store)
            provide("config_manager", self.config)
            provide("session_state", self.session)
            
            # 创建并注册回测服务
            backtest_service = BacktestService(config=self.config, feed=self.mdm.feed)
            provide("backtest_service", backtest_service)
        except ImportError:
            # 如果服务层尚未完全实现，降级为不注册
            pass

    # ------------------------------------------------------------------
    def _build(self) -> None:
        """构建相关对象。"""
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧导航（根据屏幕宽度动态调整）
        self.nav = QListWidget()
        nav_w = self._layout_mgr.nav_width()
        self.nav.setFixedWidth(nav_w)
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
        self.pages: list[QWidget | None] = [None] * len(NAV)
        # 预建首页（行情全景），其余页面延迟到首次点击时实例化，
        # 避免启动时一次性触发 predictor.py 等重型模块导入。
        first_cls, first_key = NAV[0][1], NAV[0][3]
        first_page = first_cls(self.mdm, self.store, self.config, self.session)
        first_page.PAGE_KEY = first_key
        first_page.selection_changed.connect(
            lambda sym, per, k=first_key: self._on_sel(k, sym, per))
        self.pages[0] = first_page
        self.stack.addWidget(first_page)
        # 预连接首页预警信号
        if hasattr(first_page, "alerts_fired"):
            first_page.alerts_fired.connect(self._on_alerts_fired)
        if hasattr(first_page, "scan_status"):
            first_page.scan_status.connect(self._on_scan_status)
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
        # 常驻版本标签：始终与包内 __version__ 同步，避免界面与程序实际版本不一致
        self._status_ver = QLabel(f"v{APP_VERSION}")
        self._status_ver.setObjectName("status-ver")
        self._status_ver.setToolTip(f"当前版本 v{APP_VERSION}")
        self.status.addPermanentWidget(self._status_ver)
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
        """构建菜单。"""
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
        # AI
        ai_menu = mb.addMenu("AI")
        act_ai_config = ai_menu.addAction(icon("settings", self.theme), "模型配置…")
        act_ai_config.triggered.connect(self._open_ai_settings)
        act_ai_status = ai_menu.addAction("API状态")
        act_ai_status.triggered.connect(self._show_ai_status)
        # 帮助
        helpm = mb.addMenu("帮助")
        act_about = helpm.addAction("关于")
        act_about.triggered.connect(self._about)

    # ------------------------------------------------------------------
    def _setup_tray(self) -> None:
        """初始化tray。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(icon("warning", self.theme, size=32))
        self._tray.setToolTip(f"期货智能分析预测系统 v{APP_VERSION}")
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
        """处理about。"""
        from .about_page import show_about_dialog
        show_about_dialog(self)

    def _open_ai_settings(self) -> None:
        """打开 AI 模型配置对话框。"""
        from ..ai.config import get_ai_config
        ai_cfg = get_ai_config(self.config)
        dlg = AIConfigDialog(config=self.config, parent=self)
        dlg.config_applied.connect(self._on_ai_config_applied)
        dlg.exec()

    def _on_ai_config_applied(self) -> None:
        """AI 配置已应用：刷新状态栏 AI 状态提示。"""
        from ..ai.llm_client import api_status
        st = api_status()
        if st.get("usable"):
            self._status_log.setText(f"Agnes AI：已连接")
        elif st.get("configured"):
            self._status_log.setText("云端研判：已配置（未连接）")
        else:
            self._status_log.setText("云端研判：未配置（降级模式）")
        self._status_log.setStyleSheet(f"color:{pal()['sub']};")

    def _show_ai_status(self) -> None:
        """弹出 Agnes AI 状态信息框（只读）。"""
        from PyQt6.QtWidgets import QMessageBox
        from ..ai.llm_client import api_status
        from ..ai.config import get_ai_config
        st = api_status()
        ai = get_ai_config(self.config)
        s = ai.status()
        lines = [
            f"API 密钥：{'已配置' if s.get('api_key_set') else '未配置'}",
            f"端点地址：{AGNES_API_BASE}",
            f"请求超时：{s.get('timeout', 30)} 秒",
            f"requests 可用：{'是' if s.get('requests_available') else '否'}",
            f"整体可用：{'是 ✓' if s.get('usable') else '否'}",
        ]
        QMessageBox.information(self, "Agnes AI 状态", "\n".join(lines))

    def _goto_page(self, key: str) -> None:
        """按页面 key 跳转（菜单快捷入口用）。"""
        for i, (_, _, _, k) in enumerate(NAV):
            if k == key:
                self.nav.setCurrentRow(i)
                self.stack.setCurrentIndex(i)
                break

    # ------------------------------------------------------------------
    def _switch(self, idx: int) -> None:
        """处理switch。"""
        # 延迟初始化目标页面（首次访问时才构建）
        if self.pages[idx] is None:
            title, cls, _, key = NAV[idx]
            page = cls(self.mdm, self.store, self.config, self.session)
            page.PAGE_KEY = key
            page.selection_changed.connect(
                lambda sym, per, k=key: self._on_sel(k, sym, per))
            self.pages[idx] = page
            self.stack.addWidget(page)
            if hasattr(page, "alerts_fired"):
                page.alerts_fired.connect(self._on_alerts_fired)
            if hasattr(page, "scan_status"):
                page.scan_status.connect(self._on_scan_status)
        self.stack.setCurrentIndex(idx)
        self.session.set("last_page", idx)
        self._schedule_session_save()

    def _on_sel(self, key: str, symbol: str, period: str) -> None:
        """各页合约/周期变更 → 写入会话状态，便于崩溃/重启后恢复。"""
        self.session.set_page_selection(key, symbol or "", period or "")
        self._schedule_session_save()

    # ------------------------------------------------------------------
    def _restore_geometry(self) -> None:
        """处理restoregeometry。"""
        w = self.session.get("window", {})
        # 强制默认最大化（用户上次关闭时未最大化也恢复为最大化）
        self._want_max = bool(w.get("maximized", True)) or True
        x, y = w.get("x"), w.get("y")
        # 根据屏幕尺寸调整默认窗口大小
        min_w, min_h = self._layout_mgr.get_min_window_size()
        screen_w, screen_h = self._layout_mgr.width, self._layout_mgr.height
        # 按比例缩放默认窗口大小，但限制在合理范围内
        default_w = int(screen_w * 0.85)  # 默认占屏幕 85% 宽
        default_h = int(screen_h * 0.80)  # 默认占屏幕 80% 高
        default_w = max(min_w, min(default_w, screen_w - 50))
        default_h = max(min_h, min(default_h, screen_h - 50))
        ww, hh = int(w.get("w", default_w) or default_w), int(w.get("h", default_h) or default_h)
        if x is not None and y is not None:
            self.setGeometry(int(x), int(y), ww, hh)
        else:
            self.resize(ww, hh)

    def _schedule_session_save(self) -> None:
        """处理schedule会话save。"""
        if not self._session_timer.isActive():
            self._session_timer.start(600)

    def _save_geometry(self) -> None:
        """保存geometry。"""
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
        """调整大小事件。
        
            参数:
                event"""
        super().resizeEvent(event)
        self._save_geometry()

    def moveEvent(self, event) -> None:  # noqa: N802
        """处理move事件。
        
            参数:
                event"""
        super().moveEvent(event)
        self._save_geometry()

    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭事件。
        
            参数:
                event"""
        self.session.flush()
        try:
            self.store.close()
        except Exception:
            pass
        super().closeEvent(event)

    def _reconnect(self) -> None:
        """处理reconnect。"""
        self.mdm.connect()
        self._update_status()

    def _do_connect(self) -> None:
        """异步数据源探测（由 _connect_deferred 触发），完成后更新状态栏。"""
        self.mdm.connect()
        self.store.add_log(str(dt.datetime.now()), "INFO",
                          f"系统启动 · 数据源：{self.mdm.source_label}")
        self._update_status()
        self._connect_deferred.deleteLater()

    def _update_status(self) -> None:
        """更新状态。"""
        if self.mdm.status.startswith("已连接"):
            self._status_conn.setText("● 已连接")
            self._status_conn.setStyleSheet(f"color:{pal()['up']};")
        else:
            self._status_conn.setText("● 离线")
            self._status_conn.setStyleSheet(f"color:{pal()['down']};")
        self._status_src.setText(f"数据源：{self.mdm.source_label}")

    def _tick_clock(self) -> None:
        """处理Tick 数据clock。"""
        self._status_clock.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))

    # ------------------------------------------------------------------
    def _toggle_theme(self) -> None:
        """切换主题。"""
        self.theme = "light" if self.theme == "dark" else "dark"
        self.config.set("ui.theme", self.theme)
        self.config.save()
        self._apply_theme()

    def _apply_theme(self) -> None:
        """应用主题（M1.2：设计系统一键全量刷新）。"""
        from . import widgets as W
        W.THEME = self.theme
        # M1.2：注入规范色板并全量刷新所有挂接控件（消除页面级 inline 不刷新缺陷）
        try:
            from .design_system import apply_design
            apply_design(self.theme, refresh_widgets=False)  # 刷新由下方遍历负责
        except Exception:
            pass
        qss = DARK_QSS if self.theme == "dark" else LIGHT_QSS
        # 根据分辨率调整 QSS 中的字体大小
        base_size = self._layout_mgr.font_size(13)
        qss = qss.replace("font-size:13px;", f"font-size:{base_size}px;")
        qss = qss.replace("font-size:12px;", f"font-size:{base_size-1}px;")
        qss = qss.replace("font-size:11px;", f"font-size:{base_size-2}px;")
        self.setStyleSheet(qss)
        # 导航图标重渲染
        for i, (_, _, ic, _k) in enumerate(NAV):
            self.nav.item(i).setIcon(icon(ic, self.theme))
        # 主题按钮图标
        self._theme_btn.setIcon(icon("sun" if self.theme == "dark" else "moon", self.theme))
        # 页面与图表
        for p in self.pages:
            if p is None:
                continue
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
QWidget { background:#0f1116; color:#e6e6e6; font-family:'SimHei','Noto Sans SC','Microsoft YaHei',sans-serif; }
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
QComboBox QAbstractItemView { background:#11141c; color:#e6e6e6; selection-background-color:#2563eb; selection-color:#fff; border:1px solid #2a2e3a; border-radius:8px; outline:0; padding:4px; }
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

/* ===== 滚动条（深色） ===== */
QScrollBar:vertical { background:#0f1116; width:12px; border-radius:6px; margin:0; }
QScrollBar::handle:vertical { background:rgba(42,46,58,0.8); border-radius:6px; min-height:32px; margin:1px; }
QScrollBar::handle:vertical:hover { background:rgba(58,65,84,0.95); }
QScrollBar::handle:vertical:pressed { background:#3b82f6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:#0f1116; height:12px; border-radius:6px; margin:0; }
QScrollBar::handle:horizontal { background:rgba(42,46,58,0.8); border-radius:6px; min-width:32px; margin:1px; }
QScrollBar::handle:horizontal:hover { background:rgba(58,65,84,0.95); }
QScrollBar::handle:horizontal:pressed { background:#3b82f6; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }

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
#status-ver { color:#60a5fa; font-weight:bold; font-size:13px; padding:0 6px; }
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

/* ===== 滚动条（浅色） ===== */
QScrollBar:vertical { background:#f1f5f9; width:12px; border-radius:6px; margin:0; }
QScrollBar::handle:vertical { background:rgba(203,213,225,0.8); border-radius:6px; min-height:32px; margin:1px; }
QScrollBar::handle:vertical:hover { background:rgba(148,163,184,0.95); }
QScrollBar::handle:vertical:pressed { background:#2563eb; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:#f1f5f9; height:12px; border-radius:6px; margin:0; }
QScrollBar::handle:horizontal { background:rgba(203,213,225,0.8); border-radius:6px; min-width:32px; margin:1px; }
QScrollBar::handle:horizontal:hover { background:rgba(148,163,184,0.95); }
QScrollBar::handle:horizontal:pressed { background:#2563eb; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }

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
#status-ver { color:#2563eb; font-weight:bold; font-size:13px; padding:0 6px; }
QFrame#chip { border-radius:12px; }
QToolTip { background:#ffffff; color:#1f2937; border:1px solid #d1d5db; border-radius:6px; padding:5px 8px; }
"""


def main() -> None:
    """处理main。"""
    import os
    import sys
    from PyQt6.QtGui import QFont, QFontDatabase
    from PyQt6.QtWidgets import QApplication
    
    # 强制应用安全模式：打包模式下从环境变量加载 API 密钥，清除持久化密钥
    from ..runtime import is_frozen
    from ..ai.llm_client import enforce_security_mode
    enforce_security_mode(is_frozen())
    
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
        # 根据分辨率动态调整基础字体大小
        from .responsive_layout import get_layout_manager
        mgr = get_layout_manager()
        base_size = mgr.font_size(10)
        app.setFont(QFont(chosen_family, base_size))
    else:
        base_size = 10
        app.setFont(QFont("", base_size))  # 让 Qt 走系统默认字体（含 CJK 回退）
    win = MainWindow()

    # ---- 全局崩溃兜底：异常时尽量落盘状态，并写入崩溃日志 ----
    def _excepthook(etype, exc, tb):  # noqa: ANN001
        """处理excepthook。
        
            参数:
                etype
                exc
                tb"""
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
    # 确保窗口在最前面并激活
    win.raise_()
    win.activateWindow()
    app.exec()


if __name__ == "__main__":
    main()