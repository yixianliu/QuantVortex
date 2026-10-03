"""期货智能分析预测系统 · 主窗口外壳。

布局：左侧导航菜单 / 中间功能主区（六页堆叠）/ 底部状态栏（连接状态 + 时钟 + 日志）。
仅依赖 PyQt6 / numpy / pandas，离线可跑；数据默认走合成行情（模拟），
生产环境在 data/ctp_gateway.py 替换为 CTPFeed 即可，本文件零改动。
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re

from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QColor, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QStackedWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QStatusBar, QFrame, QSizePolicy, QSystemTrayIcon,
)

from .widgets import THEME, pal, PALETTE
from .icons import icon
from .pages import LogPage, Worker
from .states import DataGrid
from .predict_ops_page import PredictOpsPage
from .market_overview_page import MarketOverviewPage
from .backtest_page import BacktestCenterPage
from .ctp_monitor_page import CTPMonitorPage
from .data_page import DataPage
from .simple_backtest_page import SimpleBacktestPage

logger = logging.getLogger(__name__)
from .ai_settings_dialog import AIConfigDialog
from ..storage.config_manager import ConfigManager, SessionState
from ..runtime import get_font_paths
from .. import __version__ as APP_VERSION
from .responsive_layout import get_layout_manager

AGNES_API_BASE = "https://api.agnes-ai.cn/v1/chat/completions"


def _product_icon() -> QIcon:
    """M4-11②：应用图标 —— 优先 images/product/1.png，缺失时退回内置图标。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    p = os.path.join(root, "images", "product", "1.png")
    if os.path.exists(p):
        ic = QIcon(p)
        if not ic.isNull():
            return ic
    return icon("bolt", "dark", size=64)

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

        # M4-11②：窗口/应用图标（产品图，缺失自动降级内置图标）
        app_icon = _product_icon()
        self.setWindowIcon(app_icon)
        try:
            if QApplication.instance() is not None:
                QApplication.instance().setWindowIcon(app_icon)
        except Exception:  # noqa: BLE001
            pass

        # M4-11（修 M4-10 遗留）：MainWindow 也需要 worker 登记列表，
        # `_reconnect` 调用的 `_run_worker` 此前只存在于 BasePage —— 运行时 AttributeError
        self._workers: list[Worker] = []

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
        self._connect_deferred.timeout.connect(self._reconnect)
        self._connect_deferred.start(0)  # 下一轮事件循环再执行

        # ---- 响应式布局管理 ----
        self._layout_mgr = get_layout_manager()
        # M4-14④：恢复用户字号缩放（90/100/110/125%，持久化于 ui.font_scale）
        self._layout_mgr.set_user_font_scale(
            float(self.config.get("ui.font_scale", 100)) / 100.0)

        self.setWindowTitle(f"期货智能分析预测系统  v{APP_VERSION}")
        # 根据分辨率动态调整最小尺寸约束
        min_w, min_h = self._layout_mgr.get_min_window_size()
        self.setMinimumWidth(min_w)
        self.setMinimumHeight(min_h)
        self._build()
        self._apply_theme()
        self._restore_geometry()
        # M4-11⑥：初始导航模式（窄屏折叠 / 宽屏完整）——resize 前先校正一次
        self._update_nav_mode()

        # 时钟
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()

        # 会话状态防抖落盘
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.timeout.connect(lambda: self.session.flush())

        # M4-11⑦：状态栏日志 8s 自动清空（单次定时器，_push_status_log 内重启）
        self._status_log_timer = QTimer(self)
        self._status_log_timer.setSingleShot(True)
        self._status_log_timer.timeout.connect(
            lambda: self._status_log.setText(""))

        # 启动默认进入「行情全景」页（需求：程序启动后默认进入行情全景页面，
        # 并自动触发市场数据刷新与新闻资讯解读——由该页 showEvent 自动拉取）。
        # M4-01：走统一入口（会同步侧栏高亮 + 断言校验），不再直接 setCurrentIndex
        self._show_page(0)

        # M4-12：全局快捷键统一注册（Ctrl+K 面板 / F5 刷新 / Ctrl+E 导出 /
        # Ctrl+, 模型配置 / Esc 关浮层 / Ctrl+1..7 切页）
        self._shortcut_seqs: list[tuple[str, str]] = []   # (序列, 说明) 供帮助菜单
        self._setup_shortcuts()

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
        central.setObjectName("central")
        central.setAutoFillBackground(True)
        central.setStyleSheet("background:#1e1e2e;")  # 保底深色背景
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
        self.stack.setAutoFillBackground(True)
        self.stack.setStyleSheet("background:#1e1e2e;")  # 保底深色背景
        self.pages: list[QWidget | None] = [None] * len(NAV)
        # M4-01：NAV 下标 → QStackedWidget 下标 的**显式映射**。
        # 页面是「首次访问才创建」（延迟初始化），而 addWidget 的入栈顺序取决于
        # 用户点击顺序 —— 因此 NAV 下标 ≠ 栈下标。此前代码直接
        # `stack.setCurrentIndex(idx)`，只要用户不是按 0,1,2... 顺序点，就会错位
        # （典型：菜单直接跳「数据管理」→ 主区仍显示上一个页面，且侧栏高亮与
        # 主区内容不一致）。此后一律用 `setCurrentWidget(page)`，索引只作诊断。
        self._stack_index: dict[int, int] = {}
        # 预建首页（行情全景），其余页面延迟到首次点击时实例化，
        # 避免启动时一次性触发 predictor.py 等重型模块导入。
        first_cls, first_key = NAV[0][1], NAV[0][3]
        first_page = first_cls(self.mdm, self.store, self.config, self.session)
        first_page.PAGE_KEY = first_key
        first_page.selection_changed.connect(
            lambda sym, per, k=first_key: self._on_sel(k, sym, per))
        self.pages[0] = first_page
        self.stack.addWidget(first_page)
        self._stack_index[0] = self.stack.indexOf(first_page)
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

        # M4-14②：关键控件无障碍名称/描述（读屏器可辨识）
        self.nav.setAccessibleName("主导航")
        self.nav.setAccessibleDescription(
            "功能页面切换列表，Ctrl+1..7 快速切页，Ctrl+K 命令面板可搜索")
        self._status_conn.setAccessibleName("数据源连接状态")
        self._status_src.setAccessibleName("当前数据源")
        self._status_clock.setAccessibleName("当前时间")
        self._status_log.setAccessibleName("状态日志")
        self._conn_btn.setAccessibleName("重连数据源")
        self._conn_btn.setAccessibleDescription("重新连接行情数据源")
        self._theme_btn.setAccessibleName("切换主题")
        self._theme_btn.setAccessibleDescription("在深色与浅色主题间切换")

        # 顶部菜单栏
        self._build_menu()

        rwidget = QWidget()
        rwidget.setObjectName("content-panel")
        rwidget.setAutoFillBackground(True)
        rwidget.setStyleSheet("background:#1e1e2e;")  # 保底深色背景
        rwidget.setLayout(right)
        root.addWidget(rwidget)

        # M3-13 ④：模型漂移定时检测（默认 1h 一轮）
        # 只对「已预测过」的品种扫描，超阈值写 alerts 表 + 托盘冒泡。
        # 后台守护线程，不影响界面；关闭窗口时 stop（见 closeEvent）。
        self.drift_monitor = None
        try:
            self._start_drift_monitor()
        except Exception as e:  # 漂移检测接线失败绝不能阻断启动
            logger.warning("模型漂移定时检测未启用：%s", e)

    # ------------------------------------------------------------------
    def _start_drift_monitor(self) -> None:
        """拉起模型漂移定时检测（默认间隔取 DriftConfig.scheduler_interval_min）。"""
        from ..app.scheduler import DriftMonitor
        self.drift_monitor = DriftMonitor(
            self.store, notify_fn=self._on_drift_alert)
        self.drift_monitor.start()      # 默认 1h

    def _push_status_log(self, text: str) -> None:
        """M4-11⑦：写状态栏日志并重启 8s 自动清空定时器。"""
        self._status_log.setText(text)
        try:
            self._status_log_timer.start(8000)
        except Exception:  # noqa: BLE001
            pass

    def _on_drift_alert(self, message: str, level: str) -> None:
        """模型漂移告警：状态栏提示 + 托盘气泡（与预警同一套呈现）。"""
        if not message:
            return
        self._push_status_log(f"📉 {message}")
        if getattr(self, "_tray", None) is not None and level == "drift":
            try:
                self._tray.showMessage(
                    "模型漂移预警", message,
                    QSystemTrayIcon.MessageIcon.Warning, 5000)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # M4-12：全局快捷键与命令面板
    # ------------------------------------------------------------------
    def _setup_shortcuts(self) -> None:
        """M4-12①③：全局快捷键统一注册入口（帮助菜单清单同步取自这里）。"""

        def _sc(seq: str, desc: str, fn) -> None:
            """注册单个快捷键并登记到帮助清单。"""
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)
            self._shortcut_seqs.append((seq, desc))

        _sc("Ctrl+K", "命令面板", self._open_palette)
        _sc("F5", "刷新当前页", self._refresh_current_page)
        _sc("Ctrl+E", "导出当前表", self._export_current_table)
        _sc("Ctrl+,", "模型配置", self._open_ai_settings)
        # M7-07：AI 对话框局部快捷键说明（作用于模型配置对话框打开期间，
        # 登记进帮助清单；对话框内实现见 AIConfigDialog.keyPressEvent）
        for seq, desc in (("Ctrl+S（AI 对话框）", "应用并保存"),
                          ("Ctrl+Enter（AI 对话框）", "测试连接"),
                          ("Ctrl+R（AI 对话框）", "恢复默认")):
            self._shortcut_seqs.append((seq, desc))
        _sc("Esc", "关闭浮层", self._close_overlays)
        for i in range(len(NAV)):
            _sc(f"Ctrl+{i + 1}", f"切到「{NAV[i][0]}」页",
                lambda idx=i: self._show_page(idx))
        # M4-12③：状态栏 Tooltip 快捷键速查
        self.status.setToolTip(
            "快捷键：" + " · ".join(f"{seq} {d}" for seq, d in self._shortcut_seqs))

    def _open_palette(self) -> None:
        """Ctrl+K：唤起命令面板（页面 / 品种 / 命令模糊搜索）。"""
        from .command_palette import CommandPalette
        dlg = CommandPalette(self, self._palette_items())
        dlg.exec()

    def _palette_items(self) -> list:
        """装配面板条目：页面 → 全局命令 → 品种（mdm.universe）。"""
        items: list = []
        for idx, (title, _cls, _ic, _k) in enumerate(NAV):
            items.append((f"页面：{title}", "页面",
                          lambda i=idx: self._show_page(i)))
        items += [
            ("命令：切换主题（深/浅）", "命令", self._toggle_theme),
            ("命令：重连数据源", "命令", self._reconnect),
            ("命令：模型配置…", "命令", self._open_ai_settings),
            ("命令：数据导出…", "命令", lambda: self._goto_page("data")),
            ("命令：备份 / 恢复…", "命令", lambda: self._goto_page("data")),
            ("命令：API状态", "命令", self._show_ai_status),
            ("命令：导出当前表（Ctrl+E）", "命令", self._export_current_table),
            ("命令：刷新当前页（F5）", "命令", self._refresh_current_page),
            ("命令：关于", "命令", self._about),
        ]
        for row in (getattr(self.mdm, "universe", None) or []):
            sym, name = row[0], row[1]
            items.append((f"品种：{sym} {name}", "品种",
                          lambda s=sym: self._goto_symbol(s)))
        return items

    def _goto_symbol(self, symbol: str) -> None:
        """面板品种动作：跳到「行情全景」并把合约下拉切到目标品种。"""
        self._goto_page("market")
        page = self.pages[0]
        cb = getattr(page, "sym_cb", None)
        if cb is None:
            return
        for i in range(cb.count()):
            if cb.itemData(i) == symbol:
                if cb.currentIndex() != i:
                    cb.setCurrentIndex(i)   # 触发 _on_symbol → 重置并刷新
                return

    def _refresh_current_page(self) -> None:
        """F5：刷新当前页（duck-typing 兼容各页刷新方法命名）。"""
        page = self.stack.currentWidget()
        for name in ("_refresh_all", "refresh", "_refresh", "reload", "_reload"):
            fn = getattr(page, name, None)
            if callable(fn):
                fn()
                return
        self._push_status_log("当前页不支持刷新")

    def _export_current_table(self, path: str | None = None) -> None:
        """Ctrl+E：导出当前页表格（DataGrid.export_csv，utf-8-sig）。"""
        page = self.stack.currentWidget()
        grids = [g for g in page.findChildren(DataGrid) if g.isVisibleTo(page)]
        if not grids:
            grids = list(page.findChildren(DataGrid))
        if not grids:
            self._push_status_log("当前页无可导出的表格")
            return
        grid = next((g for g in grids if g.hasFocus()), grids[0])
        out = grid.export_csv(path)
        if out:
            self._push_status_log(f"✓ 已导出：{out}")
        else:
            self._push_status_log("导出取消或失败")

    def _close_overlays(self) -> None:
        """Esc：关闭主窗口唤起的可见浮层（对话框/命令面板）。"""
        from PyQt6.QtWidgets import QDialog
        closed = 0
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible() and w is not self:
                w.close()
                closed += 1
        if not closed:
            self._push_status_log("无浮层可关闭")

    def _show_shortcuts(self) -> None:
        """M4-12②：帮助菜单「快捷键」清单（数据源自 _setup_shortcuts 登记）。"""
        from PyQt6.QtWidgets import QMessageBox
        lines = [f"{seq}\t{desc}" for seq, desc in self._shortcut_seqs]
        QMessageBox.information(
            self, "快捷键", "\n".join(lines) +
            "\n\n提示：Ctrl+K 命令面板可搜索页面 / 品种 / 命令")

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
        # M4-14④：字号缩放设置项（90/100/110/125%）
        fmenu = view.addMenu("字号缩放")
        self._font_scale_group = []
        for pct in (90, 100, 110, 125):
            act = fmenu.addAction(f"{pct}%")
            act.setCheckable(True)
            act.setChecked(
                int(self.config.get("ui.font_scale", 100)) == pct)
            act.triggered.connect(lambda _c=False, p=pct: self._set_font_scale(p))
            self._font_scale_group.append((pct, act))
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
        act_sc = helpm.addAction("快捷键…")
        act_sc.setShortcut("Ctrl+/")
        act_sc.triggered.connect(self._show_shortcuts)
        helpm.addSeparator()
        # M1-09：系统诊断面板
        act_diag = helpm.addAction("系统诊断…")
        act_diag.setShortcut("Ctrl+Shift+D")
        act_diag.triggered.connect(self._show_diagnostics)
        helpm.addSeparator()
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
        self._push_status_log(f"⚠ 预警：{top['symbol']} {top['message']}")
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
        self._push_status_log(f"◌ {msg}")

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
            self._push_status_log("Agnes AI：已连接")
        elif st.get("configured"):
            self._push_status_log("云端研判：已配置（未连接）")
        else:
            self._push_status_log("云端研判：未配置（降级模式）")
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

    def _show_diagnostics(self) -> None:
        """M1-09：打开系统诊断面板。"""
        import os
        from .diagnostics_dialog import DiagnosticsDialog

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(root, "data")
        disk_dir = root
        # 密钥指纹：只取首尾，永不显示全文
        try:
            from ..ai.config import get_ai_config
            ai_cfg = get_ai_config(self.config)
            key_fp = ai_cfg.api_key_fingerprint() if hasattr(ai_cfg, "api_key_fingerprint") else None
        except Exception:  # noqa: BLE001
            key_fp = None
        if not key_fp:
            env_key = os.environ.get("QV_AGNES_API_KEY", "")
            key_fp = env_key if len(env_key) <= 12 else (
                env_key[:3] + "…" + env_key[-4:] if len(env_key) > 8 else None)

        ctx = {
            "data_dir": data_dir,
            "disk_dir": disk_dir,
            "data_feed": getattr(self, "_mdm", None) or getattr(self, "mdm", None),
            "api_key_fingerprint": key_fp,
            "qr_gate_enabled": bool(getattr(self, "_qr_gate_enabled", False)),
        }
        dlg = DiagnosticsDialog(context=ctx, parent=self)
        dlg.exec()

    def _goto_page(self, key: str) -> bool:
        """按页面 key 跳转（菜单快捷入口用）。返回是否命中并切换成功。

        M4-01：原来这里 `nav.setCurrentRow(i)` + `stack.setCurrentIndex(i)` 两行分开做，
        既重复了 `_switch` 的职责（延迟创建、信号连接、会话记录都没走），又直接
        用 NAV 下标当栈下标（错位根因）。改为统一走 `_show_page`。
        """
        for i, (_, _, _, k) in enumerate(NAV):
            if k == key:
                return self._show_page(i)
        logger.warning("未找到页面 key=%s", key)
        return False

    def _show_page(self, idx: int) -> bool:
        """切换到 NAV 第 idx 页（幂等，侧栏高亮与主区同步）。

        M4-01：单独抽出是为了处理「目标页 == 当前页」的情况 —— 此时
        `nav.setCurrentRow(idx)` **不会**发出 currentRowChanged，`_switch` 不会被
        触发，若直接返回就会漏掉「菜单点了但页面没切（例如尚未创建）」的情形。
        """
        if idx < 0 or idx >= len(NAV):
            logger.warning("页面下标越界：%d（共 %d 页）", idx, len(NAV))
            return False
        if self.nav.currentRow() != idx:
            self.nav.setCurrentRow(idx)      # 会触发 _switch(idx)
        else:
            self._switch(idx)                # 已在当前行，手动补一次（幂等）
        page = self.pages[idx]
        return page is not None and self.stack.currentWidget() is page

    # ------------------------------------------------------------------
    def _switch(self, idx: int) -> None:
        """处理switch。

        M4-01：切换改用 `setCurrentWidget(page)` —— 页面栈的下标与 NAV 的下标
        在「延迟初始化 + 乱序点击」下并不相等，用下标切换必然错位。
        """
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
        page = self.pages[idx]
        # M4-01：按**widget**切换，不再按下标；同时登记真实栈下标供诊断
        self._stack_index[idx] = self.stack.indexOf(page)
        self.stack.setCurrentWidget(page)
        # M4-01 ③：断言切换结果（错位会在开发/测试期立刻炸出来，而不是静默显示错页）
        ok = self.stack.currentWidget() is page
        if not ok:
            logger.error(
                "页面栈切换错位：NAV[%d]=%s 期望显示 %r，实际 %r（栈下标=%s）",
                idx, NAV[idx][0], page, self.stack.currentWidget(),
                self._stack_index.get(idx))
        assert ok, (
            f"页面栈切换错位：NAV 下标 {idx}（{NAV[idx][0]}）切换后 "
            f"stack.currentWidget() 不是该页")
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
        # M4-11③：尊重会话记录（去掉原 `or True` —— 它把用户上次「非最大化」
        # 的偏好强制覆盖为最大化，导致记忆失效）
        self._want_max = bool(w.get("maximized", True))
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
        # M4-11⑥：窄屏（<1100px）侧栏自动折叠为 56px 图标条
        self._update_nav_mode()
        self._save_geometry()

    # M4-11⑥：窄屏折叠阈值与折叠宽度
    NAV_COLLAPSE_THRESHOLD = 1100
    NAV_COLLAPSED_WIDTH = 56

    def _update_nav_mode(self) -> None:
        """窗口宽度 <1100px 时把侧栏折叠为 56px 图标条，加宽时还原文字。

        幂等：模式未变化时不做任何事（resize 高频触发，避免每帧重写文本）。
        """
        nav = getattr(self, "nav", None)
        if nav is None:
            return
        narrow = self.width() < self.NAV_COLLAPSE_THRESHOLD
        if narrow == getattr(self, "_nav_collapsed", None):
            return
        self._nav_collapsed = narrow
        try:
            if narrow:
                nav.setFixedWidth(self.NAV_COLLAPSED_WIDTH)
                for i, (title, _, _, _k) in enumerate(NAV):
                    item = nav.item(i)
                    item.setToolTip(title)
                    item.setText("")
            else:
                nav.setFixedWidth(self._layout_mgr.nav_width())
                for i, (title, _, _, _k) in enumerate(NAV):
                    item = nav.item(i)
                    item.setToolTip("")
                    item.setText(title)
        except Exception:  # noqa: BLE001
            pass

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
        # M3-13：停掉漂移定时检测，避免进程退出后定时器仍在跑
        try:
            mon = getattr(self, "drift_monitor", None)
            if mon is not None:
                mon.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.store.close()
        except Exception:
            pass
        super().closeEvent(event)

    def _run_worker(self, fn, on_done, on_err=None, on_progress=None,
                    on_timeout=None, on_interrupted=None, timeout_ms: int = 0,
                    connect_status=None) -> "Worker":
        """MainWindow 版 worker 运行器（修复 M4-10 遗留 AttributeError）。

        ``_reconnect`` 调用的 ``self._run_worker`` 此前只定义在 BasePage 上，
        MainWindow 并未继承 —— 首次启动（``_connect_deferred`` → ``_reconnect``）
        必然抛 AttributeError。本方法与 ``BasePage._run_worker`` 语义一致
        （超时守护定时器建在主线程、结束后从 ``self._workers`` 移除），
        仅 ``connect_status`` 分支改为直接刷新主窗口状态栏。
        """
        w = Worker(fn, timeout_ms=timeout_ms)
        self._workers.append(w)
        guard = None
        if timeout_ms > 0:
            guard = QTimer(self)
            guard.setSingleShot(True)
            guard.timeout.connect(w._on_timeout)

        def _safe_remove():
            """任务结束后从存活列表移除并停掉守护定时器。"""
            try:
                self._workers.remove(w)
            except ValueError:
                pass
            if guard is not None and guard.isActive():
                guard.stop()

        def _done(r):
            """成功回调。"""
            try:
                if on_done:
                    on_done(r)
            finally:
                _safe_remove()

        def _err(e):
            """失败回调。"""
            try:
                if on_err:
                    on_err(e)
            finally:
                _safe_remove()

        w.finished.connect(_done)
        w.error.connect(_err)
        w.interrupted.connect(_safe_remove)
        if on_interrupted is not None:
            w.interrupted.connect(on_interrupted)
        if on_progress is not None:
            w.progress.connect(on_progress)
        if on_timeout is not None:
            def _timeout(msg):
                """超时回调。"""
                try:
                    on_timeout(msg)
                finally:
                    _safe_remove()
            w.timeout.connect(_timeout)
        if connect_status:
            # M4-10：连接结果经 connect_ready 送达主线程后刷新状态栏
            w.connect_ready.connect(lambda: self._update_status())
        w.start()
        if guard is not None:
            guard.start(int(timeout_ms))
        return w

    def _reconnect(self) -> None:
        """处理reconnect。

        M4-10：``mdm.connect()`` 移入 Worker 线程执行，避免在主线程阻塞；
        连接结果经 ``Worker.connect_ready`` 信号回传主线程更新状态栏。
        """
        def _do_connect():
            self.mdm.connect()
            return self.mdm.source_label
        # M4-11（修 M4-10 遗留）：on_done 直接刷新状态栏 —— Worker.connect_ready
        # 信号当前无发射端（全工程 grep 仅定义/连接、无 emit），不能依赖它；
        # `finished` 必然触发，作为状态刷新的可靠路径。
        self._run_worker(_do_connect, lambda _r=None: self._update_status(),
                         on_progress=None,
                         on_interrupted=None,
                         timeout_ms=15000,
                         connect_status=self.mdm.source_label)

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
    def _set_font_scale(self, pct: int) -> None:
        """M4-14④：应用字号缩放设置项（持久化 + 全量刷新）。"""
        self.config.set("ui.font_scale", int(pct))
        self.config.save()
        self._layout_mgr.set_user_font_scale(pct / 100.0)
        # 同步应用级基础字体（main() 的初始 setFont 不再适用新缩放）
        try:
            app = QApplication.instance()
            if app is not None:
                f = app.font()
                f.setPointSize(self._layout_mgr.font_size(10))
                app.setFont(f)
        except Exception:  # noqa: BLE001
            pass
        # 菜单勾选互斥
        for p, act in getattr(self, "_font_scale_group", []):
            try:
                act.setChecked(p == pct)
            except RuntimeError:
                pass
        self._apply_theme()
        self._push_status_log(f"字号缩放：{pct}%")

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
            from .design_system import apply_design, build_qss
            apply_design(self.theme, refresh_widgets=True)  # M4-04：全量刷新打开
        except Exception:
            pass
        # M4-04：QSS 由 design_system.build_qss 从 DESIGN token 生成（单一事实来源）
        qss = scale_qss_fonts(build_qss(self.theme), self._layout_mgr)
        self.setStyleSheet(qss)
        # 保底深色背景：设置 Palette（QSS 在某些环境可能不生效）
        from PyQt6.QtGui import QPalette, QColor
        bg = pal()["bg"]
        pal_color = QColor(bg)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, pal_color)
        palette.setColor(QPalette.ColorRole.Base, pal_color)
        self.setPalette(palette)
        # 保底深色背景（内联，主题切换时同步更新）
        central = self.centralWidget()
        if central:
            central.setStyleSheet(f"background:{bg};")
            cpalette = central.palette()
            cpalette.setColor(QPalette.ColorRole.Window, pal_color)
            cpalette.setColor(QPalette.ColorRole.Base, pal_color)
            central.setPalette(cpalette)
            rwidget = central.layout().itemAt(1).widget() if central.layout() and central.layout().count() > 1 else None
            if rwidget:
                rwidget.setStyleSheet(f"background:{bg};")
                rpal = rwidget.palette()
                rpal.setColor(QPalette.ColorRole.Window, pal_color)
                rpal.setColor(QPalette.ColorRole.Base, pal_color)
                rwidget.setPalette(rpal)
            if self.stack:
                self.stack.setStyleSheet(f"background:{bg};")
                spal = self.stack.palette()
                spal.setColor(QPalette.ColorRole.Window, pal_color)
                spal.setColor(QPalette.ColorRole.Base, pal_color)
                self.stack.setPalette(spal)
        # M4-04③：首次生成结果写入 config/style.qss 作为可读快照（运行时仍走生成）
        self._write_style_snapshot(qss)
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
        # M4-05②：打开中的对话框（如绩效归因）也随主题刷新（不改变对话框行为）
        try:
            from PyQt6.QtWidgets import QDialog
            for dlg in self.findChildren(QDialog):
                if hasattr(dlg, "set_theme"):
                    dlg.set_theme(self.theme)
        except Exception:
            pass
        self._update_status()

    def _write_style_snapshot(self, qss: str) -> None:
        """把生成的 QSS 写入 config/style.qss 作为可读快照（仅首次生成时写）。

        运行时仍走 build_qss 动态生成，本文件仅用于人工审阅/调试。
        """
        try:
            snap = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), "config", "style.qss")
            if os.path.exists(snap):
                return
            os.makedirs(os.path.dirname(snap), exist_ok=True)
            with open(snap, "w", encoding="utf-8") as fh:
                fh.write(qss)
        except Exception:  # noqa: BLE001
            pass


# ============================================================================
# QSS
# ============================================================================
# M4-03④：单趟字号替换，避免链式 replace 在「目标值 == 另一档源串」时把层级压平。
# 说明：QSS 含大量 CSS 大括号，无法用 str.format("{fs13}...")（会触发 KeyError），
# 故改用正则单次替换 11/12/13px 三档，每档映射到 responsive_layout.font_size 的三档钳制值。
_QSS_FONT_RE = re.compile(r"font-size:(11|12|13)px;")


def scale_qss_fonts(qss: str, mgr) -> str:
    """按响应式三档钳制替换 QSS 中的 11/12/13px 字号（单趟、防串味）。

        参数:
            qss: 原始 QSS 字符串。
            mgr: ResponsiveLayoutManager（提供 font_size 三档钳制）。

        返回:
            str: 字号已按比例替换的 QSS。
    """
    sizes = {11: mgr.font_size(11), 12: mgr.font_size(12), 13: mgr.font_size(13)}

    def _sub(m):
        """将匹配到的字号替换为对应钳制值。"""
        return f"font-size:{sizes[int(m.group(1))]}px;"

    return _QSS_FONT_RE.sub(_sub, qss)




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

    # M4-11①：Splash 先行（品牌 Logo + 版本 + 进度文案，processEvents 分步推进）
    from .splash import Splash
    splash = Splash(app)
    splash.step("加载字体…")

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

    splash.step("初始化主窗口…")
    win = MainWindow()
    # M4-14④：MainWindow 已从配置恢复用户字号缩放，同步应用级基础字体
    try:
        from .responsive_layout import get_layout_manager as _glm
        f = app.font()
        f.setPointSize(_glm().font_size(10))
        app.setFont(f)
    except Exception:  # noqa: BLE001
        pass

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

    # 恢复上次窗口状态（尊重会话记录；M4-11③ 已去掉强制最大化）
    if getattr(win, "_want_max", True):
        win.showMaximized()
    else:
        win.show()
    # M4-11①：主窗口已显示，关闭 Splash 交还焦点
    splash.finish(win)
    # 确保窗口在最前面并激活
    win.raise_()
    win.activateWindow()
    app.exec()


if __name__ == "__main__":
    main()