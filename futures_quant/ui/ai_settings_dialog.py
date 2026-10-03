"""AI 模型配置设置对话框（M7-01 向导式分组重构）。

功能：
    - 左侧分段导航（凭据 / 模型 / 高级 / 诊断）+ 右侧 QStackedWidget
    - 窄屏（宽 < 620px）自动折叠为顶部 QTabWidget
    - A 连接凭据：API 密钥（Password + 👁 显隐）、密钥来源 Badge、
      端点只读 + 复制、打包模式说明条
    - B 模型参数：模型名（可编辑 QComboBox + 预置）、最大令牌数
      （QSpinBox 256-8192/256）、温度（QDoubleSpinBox 0.0-2.0/0.05 +
      预设按钮）、超时（QSpinBox 5-300 秒）
    - C 高级：重试次数、退避基数、并发上限、代理 Base、
      响应日志脱敏开关、请求超时看门狗
    - D 诊断：连接状态（M7-05 将扩展为完整诊断页）
    - 连通性测试、热更新、配置持久化（模型参数落盘，密钥仅内存）

双模式约定：
    - 调试模式：所有参数可通过界面输入，密钥仅内存持有
    - 打包模式：密钥通过界面输入（不落盘），其他参数可持久化到配置文件

安全约定：
    - API 密钥仅在内存中持有，不落盘到配置文件
    - 固定使用 https://api.agnes-ai.cn/v1/chat/completions 端点

调用方式：
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    dlg = AIConfigDialog(config=main_window.config)
    dlg.exec()
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox,
    QStackedLayout, QStackedWidget, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

from .states import MOTION, Toast, paint_guard
from .widgets import PageHeader, pal, THEME
from .icons import icon
from ..runtime import is_frozen

# M7-02①：requests 为可选依赖，缺失时置 None（连通性测试按钮应禁用并提示）。
try:
    import requests  # noqa: F401  （连通性测试在函数内以 _req 局部导入使用）
except Exception:  # pragma: no cover - 依赖缺失场景
    requests = None

# 固定的 Agnes AI 端点
AGNES_API_BASE = "https://api.agnes-ai.cn/v1/chat/completions"

# 环境变量名
_ENV_KEY = "QV_AGNES_API_KEY"

# M7-01：分段导航条目（顺序即 QStackedWidget 页序）
NAV_ITEMS = ("连接凭据", "模型参数", "高级", "诊断")

# M7-01：响应式断点与尺寸规范
NAV_WIDTH = 148
COMPACT_BREAKPOINT = 620
DIALOG_MIN = (560, 600)
DIALOG_DEFAULT = (680, 680)
DIALOG_MAX = (900, 820)

# M7-01 分组 B：温度预设（标签, 值）
TEMPERATURE_PRESETS = (("精确", 0.1), ("均衡", 0.3), ("创意", 0.7))

# M7-01 分组 C：高级参数默认值（持久化到 user_settings.json 的 ai.* 命名空间）
ADVANCED_DEFAULTS = {
    "retry": 2,
    "backoff_base": 1.0,
    "concurrency": 2,
    "proxy": "",
    "redact_log": True,
    "watchdog": True,
}

# M7-06：导出文件 schema 与版本
EXPORT_SCHEMA = "quantvortex.ai-config"
EXPORT_VERSION = 1

# M7-06：导入字段校验规格（类型 + 可选范围；bool 必须先于 int 判定）
_IMPORT_SPEC: dict[str, tuple[type, Optional[tuple[float, float]]]] = {
    "model": (str, None),
    "timeout": (int, (5, 300)),
    "max_tokens": (int, (256, 8192)),
    "temperature": (float, (0.0, 2.0)),
    "retry": (int, (0, 5)),
    "backoff_base": (float, (0.1, 10.0)),
    "concurrency": (int, (1, 8)),
    "proxy": (str, None),
    "redact_log": (bool, None),
    "watchdog": (bool, None),
}

# 配置日志
_logger = logging.getLogger(__name__)


class _SaveSpinner(QWidget):
    """保存中的小旋转 spinner（自绘弧线，走 paint_guard；MOTION 门控）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化 spinner（默认隐藏，start() 后旋转）。"""
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self) -> None:
        """推进旋转角并重绘。"""
        self._angle = (self._angle + 30) % 360
        self.update()

    def start(self) -> None:
        """开始旋转并显示（REDUCED_MOTION 时显示静态弧线不旋转）。"""
        if MOTION:
            self._timer.start()
        self.show()
        self.update()

    def stop(self) -> None:
        """停止旋转并隐藏。"""
        self._timer.stop()
        self.hide()

    @paint_guard
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制旋转弧线（accent 色，圆头笔帽）。"""
        pp = QPainter(self)
        pp.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(pal()["accent"]), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pp.setPen(pen)
        pp.drawArc(self.rect().adjusted(2, 2, -2, -2),
                   self._angle * 16, 100 * 16)


class AIConfigDialog(QDialog):
    """AI 模型配置设置对话框（向导式分组；密钥仅内存，模型参数持久化）。"""

    # 信号：配置已应用（供主窗口状态栏刷新）
    config_applied = pyqtSignal()
    # 信号：请求打开系统诊断（M7-05 ④，主窗口可接住跳转关于页）
    system_diag_requested = pyqtSignal()

    def __init__(self, config=None, parent=None) -> None:
        """初始化对话框。

        参数:
            config: ConfigManager 实例，用于持久化模型参数
            parent: 父窗口
        """
        super().__init__(parent)
        self._config = config
        self._theme = THEME
        # M7-07⑤：保存由 _apply_timer（单发 150ms）驱动，避免 50ms 魔法延迟，
        # 同时让「保存中…」态可被 UI 刷新后观察到（M7-03 契约）
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._finish_apply)
        self._frozen = is_frozen()
        self._pages: list[tuple[str, QWidget]] = []
        self._compact: Optional[bool] = None
        # M7-03：字段元数据（hint/error 包装 + 校验）、dirty 与加载抑制标志
        self._fields: dict[str, dict] = {}
        self._dirty = False
        self._loading = True
        # M7-04：连通性测试后台线程 + 取消标志 + 轮询定时器
        self._test_state = "idle"          # idle / running
        self._test_cancel = threading.Event()
        self._test_result: Optional[dict] = None
        self._test_history: list[dict] = []  # 最新在前，最多 5 条
        self._test_poll = QTimer(self)
        self._test_poll.setInterval(100)
        self._test_poll.timeout.connect(self._poll_test)
        # M7-07②：记录最后一次状态样式级别，主题切换时重放防旧色残留
        self._last_status_level = "off"
        self.setWindowTitle("AI 模型配置")
        self.setMinimumSize(*DIALOG_MIN)
        self.resize(*DIALOG_DEFAULT)
        self.setMaximumSize(*DIALOG_MAX)
        self._build()
        self._load_with_fallback()
        self._loading = False
        self._revalidate()
        self._clear_dirty()
        self._refresh_status()
        self._sync_mode()

    # ------------------------------------------------------------------
    # 布局骨架（M7-01 ①）
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """构建 UI 界面：标题栏 + 分段主体 + 底部按钮栏。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部标题栏（右侧挂「● 未保存」dirty 角标，M7-03）
        self._header = PageHeader("Agnes AI 配置", "模型参数配置与连通性测试",
                                  theme=self._theme)
        header_row = QWidget()
        header_h = QHBoxLayout(header_row)
        header_h.setContentsMargins(0, 0, 0, 0)
        header_h.setSpacing(8)
        header_h.addWidget(self._header, 1)
        self._dirty_badge = QLabel("● 未保存")
        self._dirty_badge.setObjectName("ai-dirty")
        self._dirty_badge.setToolTip("有未保存的修改；点击「应用并保存」生效")
        self._dirty_badge.hide()
        header_h.addWidget(self._dirty_badge)
        header_h.addSpacing(16)
        root.addWidget(header_row)

        # 主体：两种模式共用同一批页面 widget
        #   wide   → 左侧 QListWidget 分段导航 + 右侧 QStackedWidget
        #   narrow → 顶部 QTabWidget
        self._nav = QListWidget()
        self._nav.setObjectName("ai-nav")
        self._nav.setFixedWidth(NAV_WIDTH)
        self._nav.currentRowChanged.connect(self._on_nav_changed)

        self._stack = QStackedWidget()
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)

        self._build_pages()
        for title, _ in self._pages:
            self._nav.addItem(title)
        for _, page in self._pages:
            self._stack.addWidget(page)

        body = QWidget()
        self._body_lay = QStackedLayout(body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        wide = QWidget()
        wide_l = QHBoxLayout(wide)
        wide_l.setContentsMargins(12, 12, 12, 0)
        wide_l.setSpacing(12)
        wide_l.addWidget(self._nav)
        wide_l.addWidget(self._stack, 1)
        narrow = QWidget()
        narrow_l = QVBoxLayout(narrow)
        narrow_l.setContentsMargins(0, 0, 0, 0)
        narrow_l.addWidget(self._tabs)
        self._body_lay.addWidget(wide)
        self._body_lay.addWidget(narrow)
        root.addWidget(body, 1)

        # 底部按钮栏
        btn_bar = QFrame()
        btn_bar.setObjectName("btn-bar")
        btn_h = QHBoxLayout(btn_bar)
        btn_h.setContentsMargins(16, 10, 16, 14)
        btn_h.setSpacing(10)

        self._test_btn = QPushButton(icon("send", self._theme), "测试连接")
        self._test_btn.setObjectName("secondary")
        self._test_btn.setFixedHeight(34)
        self._test_btn.clicked.connect(self._on_test)
        btn_h.addWidget(self._test_btn)
        # M7-04 ⑥：测试期间的旋转 spinner（自绘，MOTION 门控）
        self._test_spinner = _SaveSpinner(btn_bar)
        self._test_spinner.hide()
        btn_h.addWidget(self._test_spinner)
        # M7-02：requests 缺失时禁用测试按钮并给出提示
        if requests is None:
            self._test_btn.setEnabled(False)
            self._test_btn.setToolTip("未安装 requests 库，无法进行连通性测试"
                                      "（pip install requests）")

        btn_h.addStretch(1)

        # M7-06 ③：接线 _on_reset（原先已实现但无入口）
        self._reset_btn = QPushButton("恢复默认")
        self._reset_btn.setObjectName("secondary")
        self._reset_btn.setFixedHeight(34)
        self._reset_btn.setToolTip("清除密钥并将全部参数恢复为默认值")
        self._reset_btn.clicked.connect(self._on_reset)
        btn_h.addWidget(self._reset_btn)

        self._cancel_btn = QPushButton("关闭" if self._frozen else "取消")
        self._cancel_btn.setObjectName("secondary")
        self._cancel_btn.setFixedHeight(34)
        self._cancel_btn.clicked.connect(self.reject)
        btn_h.addWidget(self._cancel_btn)

        self._save_spinner = _SaveSpinner(btn_bar)
        self._save_spinner.hide()
        btn_h.addWidget(self._save_spinner)
        self._save_btn = QPushButton("应用并保存")
        # M7-03 ②：默认 secondary；dirty 后 _mark_dirty 切为 primary 高亮
        self._save_btn.setObjectName("secondary")
        self._save_btn.setFixedHeight(34)
        self._save_btn.clicked.connect(self._on_apply)
        btn_h.addWidget(self._save_btn)

        root.addWidget(btn_bar)
        self._connect_dirty()
        self._nav.setCurrentRow(0)
        self._apply_theme()

    def _build_pages(self) -> None:
        """构建四个分段页面并按导航顺序增量登记（供 _wrap_field 记页索引）。"""
        self._pages = []
        self._pages.append((NAV_ITEMS[0], self._build_credentials_page()))
        self._pages.append((NAV_ITEMS[1], self._build_model_page()))
        self._pages.append((NAV_ITEMS[2], self._build_advanced_page()))
        self._pages.append((NAV_ITEMS[3], self._build_diag_page()))
        # M7-03④：后置修正 —— _wrap_field 里 `len(self._pages)-1` 计算的
        # page 值在所有 _pages.append 完成前都是错位的（例如模型页字段
        # 被记为 page=0，实际应为 page=1）。用 isAncestorOf 反查真实归属。
        self._reindex_field_pages()

    def _reindex_field_pages(self) -> None:
        """按 _pages 实际内容重算每个 _fields[key]["page"]（M7-03④ 定位准确）。"""
        for _key, meta in self._fields.items():
            w = meta.get("widget")
            if w is None:
                continue
            for i, (_title, page) in enumerate(self._pages):
                if page is None:
                    continue
                if page is w or page.isAncestorOf(w):
                    meta["page"] = i
                    break

    # ------------------------------------------------------------------
    # M7-03：字段包装（Hint/Error）+ dirty 跟踪 + 就地校验
    # ------------------------------------------------------------------
    def _wrap_field(self, key: str, widget: QWidget, hint: str) -> QWidget:
        """把控件包装为「控件 + 灰色 Hint + 隐藏 Error」三层容器并登记。

        参数:
            key: 字段标识（校验/焦点跳转用）
            widget: 实际输入控件（或控件组合行）
            hint: 灰色 11px 说明文字（含单位/取值范围）
        """
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        v.addWidget(widget)
        hint_lbl = QLabel(hint)
        hint_lbl.setObjectName("ai-hint")
        hint_lbl.setWordWrap(True)
        v.addWidget(hint_lbl)
        err_lbl = QLabel("")
        err_lbl.setObjectName("ai-error")
        err_lbl.setWordWrap(True)
        err_lbl.hide()
        v.addWidget(err_lbl)
        self._fields[key] = {
            "widget": widget, "error": err_lbl, "hint": hint_lbl,
            "page": max(0, len(self._pages) - 1),
        }
        return box

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        """让 objectName / 动态属性变更立即重新应用 QSS。"""
        st = widget.style()
        st.unpolish(widget)
        st.polish(widget)

    def _connect_dirty(self) -> None:
        """任一字段变更 → 即时校验 + dirty 标记（M7-03 ②）。"""
        self._api_key_edit.textChanged.connect(self._on_field_changed)
        self._model_combo.currentTextChanged.connect(self._on_field_changed)
        self._max_tokens_spin.valueChanged.connect(self._on_field_changed)
        self._temperature_spin.valueChanged.connect(self._on_field_changed)
        self._timeout_spin.valueChanged.connect(self._on_field_changed)
        self._retry_spin.valueChanged.connect(self._on_field_changed)
        self._backoff_spin.valueChanged.connect(self._on_field_changed)
        self._concurrency_spin.valueChanged.connect(self._on_field_changed)
        self._proxy_edit.textChanged.connect(self._on_field_changed)
        self._redact_check.toggled.connect(self._on_field_changed)
        self._watchdog_check.toggled.connect(self._on_field_changed)

    def _on_field_changed(self, *_args) -> None:
        """字段变更回调：加载期间抑制，运行期即时校验 + 标记 dirty。"""
        if self._loading:
            return
        self._revalidate()
        self._mark_dirty()

    def _field_errors(self) -> dict[str, str]:
        """收集硬错误（阻断保存；M7-03 ④ 不再走 QMessageBox）。"""
        errs: dict[str, str] = {}
        if not self._model_combo.currentText().strip():
            errs["model"] = "模型名称不能为空"
        proxy = self._proxy_edit.text().strip()
        if proxy and not proxy.lower().startswith(("http://", "https://")):
            errs["proxy"] = "代理地址需以 http:// 或 https:// 开头（留空不启用）"
        return errs

    def _show_field(self, key: str, text: str, level: str) -> None:
        """设置字段提示态：``error``（红，阻断）/ ``warn``（橙，提示）/ 清除。"""
        meta = self._fields.get(key)
        if meta is None:
            return
        err = meta["error"]
        widget = meta["widget"]
        if level == "none" or not text:
            err.clear()
            err.hide()
            widget.setProperty("error", False)
        else:
            color = pal()["down"] if level == "error" else pal()["warning"]
            err.setText(text)
            err.setStyleSheet(f"color:{color};")
            err.show()
            widget.setProperty("error", level == "error")
        self._repolish(widget)

    def _revalidate(self) -> None:
        """即时校验全部字段：错误就地显示 + 应用按钮可用性联动。"""
        errs = self._field_errors()
        for key in self._fields:
            if key == "api_key":
                continue  # 密钥允许留空，无硬校验
            if key in errs:
                self._show_field(key, errs[key], "error")
            else:
                self._show_field(key, "", "none")
        # 软性提示（不阻断）：温度过高
        if "temperature" not in errs:
            temp = self._temperature_spin.value()
            if temp > 1.2:
                self._show_field(
                    "temperature",
                    f"温度 {temp:.2f} 偏高，输出随机性较大（建议 0.1–0.7）",
                    "warn")
        blocked = bool(errs)
        self._save_btn.setEnabled(not blocked and
                                  not self._save_btn.text().startswith("保存中"))
        self._save_btn.setToolTip("" if not blocked else "存在未修正的字段错误")

    def _mark_dirty(self) -> None:
        """标记「未保存」：标题栏角标显示 + 应用按钮 primary 高亮。"""
        if self._dirty:
            return
        self._dirty = True
        self._dirty_badge.show()
        self._save_btn.setObjectName("primary")
        self._repolish(self._save_btn)

    def _clear_dirty(self) -> None:
        """清除 dirty 标记（保存成功 / 加载完成后调用）。"""
        self._dirty = False
        self._dirty_badge.hide()
        self._save_btn.setObjectName("secondary")
        self._repolish(self._save_btn)

    def _focus_first_error(self) -> None:
        """自动跳转到第一个出错字段所在分段并聚焦（替代弹窗滚动定位）。"""
        errs = self._field_errors()
        if not errs:
            return
        meta = self._fields.get(next(iter(errs)))
        if meta is None:
            return
        self._apply_current_index(meta["page"])
        meta["widget"].setFocus()

    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时切换宽/窄布局模式。"""
        super().resizeEvent(event)
        self._sync_mode()

    def _sync_mode(self) -> None:
        """按当前宽度决定分段导航形态（≥620px 侧栏，<620px 顶部 Tab）。"""
        self._set_compact(self.width() < COMPACT_BREAKPOINT)

    def _set_compact(self, compact: bool) -> None:
        """切换 wide（侧栏导航）/ narrow（顶部 Tab）两种布局。

        页面 widget 只有一份，切换时在 QStackedWidget 与 QTabWidget
        之间迁移父级，用户已编辑的控件状态天然保持。
        """
        if self._compact is compact or not self._pages:
            return
        self._compact = compact
        cur = max(0, self._nav.currentRow())
        if compact:
            while self._stack.count():
                self._stack.removeWidget(self._stack.widget(0))
            for title, page in self._pages:
                self._tabs.addTab(page, title)
            self._body_lay.setCurrentIndex(1)
        else:
            while self._tabs.count():
                self._tabs.removeTab(0)
            for _, page in self._pages:
                self._stack.addWidget(page)
            self._body_lay.setCurrentIndex(0)
        self._apply_current_index(cur)

    def _apply_current_index(self, idx: int) -> None:
        """将当前分段同步到导航列表与可见容器。"""
        idx = max(0, min(idx, len(self._pages) - 1))
        self._nav.setCurrentRow(idx)
        if self._compact:
            self._tabs.setCurrentIndex(idx)
        else:
            self._stack.setCurrentIndex(idx)

    def _on_nav_changed(self, idx: int) -> None:
        """左侧导航切换 → 联动右侧容器。"""
        if idx < 0 or self._compact is None:
            return
        if self._compact:
            self._tabs.setCurrentIndex(idx)
        else:
            self._stack.setCurrentIndex(idx)

    def _on_tab_changed(self, idx: int) -> None:
        """窄屏 Tab 切换 → 联动左侧导航（保持状态一致）。"""
        if self._compact and 0 <= idx < self._nav.count() \
                and self._nav.currentRow() != idx:
            self._nav.setCurrentRow(idx)

    # ------------------------------------------------------------------
    # 分组 A：连接凭据
    # ------------------------------------------------------------------
    def _build_credentials_page(self) -> QWidget:
        """构建「连接凭据」页：密钥 + 来源 Badge + 端点 + 模式说明条。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(12)

        grp = QGroupBox("API 凭据")
        grp.setObjectName("ai-group")
        form = QFormLayout(grp)
        form.setSpacing(10)

        # API 密钥：Password 回显 + 👁 显隐切换
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("请输入 Agnes AI API 密钥")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setObjectName("ai-input")
        self._api_key_edit.setToolTip("密钥仅在内存中保存，程序关闭后失效，"
                                      "不会写入配置文件")
        # M7-07④：补全可访问性描述（原仅 tooltip）
        self._api_key_edit.setAccessibleName("API 密钥")
        self._api_key_edit.setAccessibleDescription(
            "Agnes AI API 密钥，仅内存持有，不落盘")
        self._eye_btn = QPushButton("👁")
        self._eye_btn.setObjectName("ai-eye")
        self._eye_btn.setCheckable(True)
        self._eye_btn.setFixedSize(38, 30)
        self._eye_btn.setToolTip("显示 / 隐藏密钥")
        self._eye_btn.setAccessibleName("显示或隐藏密钥")
        self._eye_btn.toggled.connect(self._on_toggle_key_visible)
        # M7-03 ⑥：打包模式密钥只读（环境变量注入），隐藏 👁 并给出说明
        if self._frozen:
            self._api_key_edit.setReadOnly(True)
            self._api_key_edit.setToolTip(
                f"打包版密钥由环境变量 {_ENV_KEY} 注入，无需手动输入")
            self._eye_btn.hide()
        key_row = QWidget()
        key_h = QHBoxLayout(key_row)
        key_h.setContentsMargins(0, 0, 0, 0)
        key_h.setSpacing(6)
        key_h.addWidget(self._api_key_edit, 1)
        key_h.addWidget(self._eye_btn)
        key_hint = (f"打包版密钥由环境变量 {_ENV_KEY} 注入，无需手动输入"
                    if self._frozen else
                    "密钥仅在内存中保存，程序关闭后失效，不写入配置文件")
        form.addRow("API 密钥", self._wrap_field("api_key", key_row, key_hint))

        # 密钥来源 Badge（胶囊）
        self._key_source_label = QLabel("")
        self._key_source_label.setObjectName("ai-badge")
        form.addRow("密钥来源", self._key_source_label)

        # 端点：只读 + 复制
        self._endpoint_edit = QLineEdit(AGNES_API_BASE)
        self._endpoint_edit.setReadOnly(True)
        self._endpoint_edit.setObjectName("ai-input")
        self._endpoint_edit.setToolTip("端点固定，不可修改")
        self._copy_btn = QPushButton("复制")
        self._copy_btn.setObjectName("secondary")
        self._copy_btn.setFixedSize(64, 30)
        self._copy_btn.setToolTip("复制端点地址到剪贴板")
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(
            lambda: self._copy_btn.setText("复制"))
        self._copy_btn.clicked.connect(self._on_copy_endpoint)
        ep_row = QWidget()
        ep_h = QHBoxLayout(ep_row)
        ep_h.setContentsMargins(0, 0, 0, 0)
        ep_h.setSpacing(6)
        ep_h.addWidget(self._endpoint_edit, 1)
        ep_h.addWidget(self._copy_btn)
        form.addRow("API 端点", ep_row)

        v.addWidget(grp)

        # 双模式说明条
        note = QFrame()
        note.setObjectName("ai-note")
        note_l = QHBoxLayout(note)
        note_l.setContentsMargins(12, 8, 12, 8)
        note_text = (
            f"打包模式：密钥通过环境变量 {_ENV_KEY} 注入，仅在内存持有，"
            "不落盘；模型参数仍可持久化。"
            if self._frozen else
            "调试模式：密钥仅在内存中保存，程序关闭后失效；"
            "模型参数与高级参数将持久化到 user_settings.json。")
        note_lbl = QLabel(note_text)
        note_lbl.setWordWrap(True)
        note_l.addWidget(note_lbl, 1)
        v.addWidget(note)
        v.addStretch(1)
        return page

    def _on_toggle_key_visible(self, checked: bool) -> None:
        """👁 切换密钥回显模式。"""
        mode = (QLineEdit.EchoMode.Normal if checked
                else QLineEdit.EchoMode.Password)
        self._api_key_edit.setEchoMode(mode)

    def _on_copy_endpoint(self) -> None:
        """复制端点地址并给出短暂反馈。"""
        QApplication.clipboard().setText(AGNES_API_BASE)
        self._copy_btn.setText("已复制 ✓")
        self._copy_timer.start(1200)

    # ------------------------------------------------------------------
    # 分组 B：模型参数
    # ------------------------------------------------------------------
    def _build_model_page(self) -> QWidget:
        """构建「模型参数」页：模型名 / 令牌数 / 温度 / 超时。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(12)

        grp = QGroupBox("模型参数（持久化保存）")
        grp.setObjectName("ai-group")
        form = QFormLayout(grp)
        form.setSpacing(10)

        # 模型名称：可编辑下拉（预置常用模型）
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._model_combo.addItems(["agnes-3.0-flash", "agnes-3.0-pro"])
        self._model_combo.setObjectName("ai-input")
        self._model_combo.setToolTip("从预置模型选择，或直接输入自定义模型名"
                                     "（需与服务商文档一致）")
        form.addRow("模型名称",
                    self._wrap_field("model", self._model_combo,
                                     "从预置模型选择，或输入自定义名称"
                                     "（需与服务商文档一致）"))

        # 最大令牌数：QSpinBox 256-8192，步长 256
        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(256, 8192)
        self._max_tokens_spin.setSingleStep(256)
        self._max_tokens_spin.setValue(1024)
        self._max_tokens_spin.setSuffix(" tokens")
        self._max_tokens_spin.setObjectName("ai-input")
        self._max_tokens_spin.setToolTip("单次请求最大生成令牌数，"
                                         "过大可能增加延迟和费用")
        form.addRow("最大令牌数",
                    self._wrap_field("max_tokens", self._max_tokens_spin,
                                     "单次请求最大生成令牌数，过大可能增加"
                                     "延迟和费用（256–8192 tokens）"))

        # 温度：QDoubleSpinBox 0.0-2.0，步长 0.05 + 预设按钮
        self._temperature_spin = QDoubleSpinBox()
        self._temperature_spin.setRange(0.0, 2.0)
        self._temperature_spin.setSingleStep(0.05)
        self._temperature_spin.setDecimals(2)
        self._temperature_spin.setValue(0.3)
        self._temperature_spin.setObjectName("ai-input")
        self._temperature_spin.setToolTip("控制生成随机性：越低越确定，"
                                          "越高越有创意")
        temp_row = QWidget()
        temp_h = QHBoxLayout(temp_row)
        temp_h.setContentsMargins(0, 0, 0, 0)
        temp_h.setSpacing(6)
        temp_h.addWidget(self._temperature_spin, 1)
        for label, value in TEMPERATURE_PRESETS:
            btn = QPushButton(f"{label} {value}")
            btn.setObjectName("secondary")
            btn.setFixedHeight(30)
            btn.setToolTip(f"温度预设：{label}")
            btn.clicked.connect(
                lambda _=False, val=value: self._temperature_spin.setValue(val))
            temp_h.addWidget(btn)
        form.addRow("温度参数",
                    self._wrap_field("temperature", temp_row,
                                     "控制生成随机性：越低越确定，越高越有"
                                     "创意（0.0–2.0，建议 0.1–0.7）"))

        # 超时：QSpinBox 5-300 秒
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 300)
        self._timeout_spin.setValue(30)
        self._timeout_spin.setSuffix(" 秒")
        self._timeout_spin.setObjectName("ai-input")
        self._timeout_spin.setToolTip("请求超时时间，网络较差时可适当增加")
        form.addRow("超时时间",
                    self._wrap_field("timeout", self._timeout_spin,
                                     "请求超时时间，网络较差时可适当增加"
                                     "（5–300 秒）"))

        v.addWidget(grp)
        v.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # 分组 C：高级
    # ------------------------------------------------------------------
    def _build_advanced_page(self) -> QWidget:
        """构建「高级」页：重试 / 退避 / 并发 / 代理 / 脱敏 / 看门狗。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(12)

        grp = QGroupBox("高级参数（持久化保存）")
        grp.setObjectName("ai-group")
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(0, 5)
        self._retry_spin.setValue(int(ADVANCED_DEFAULTS["retry"]))
        self._retry_spin.setSuffix(" 次")
        self._retry_spin.setObjectName("ai-input")
        self._retry_spin.setToolTip("请求失败后的自动重试次数，0 表示不重试")
        form.addRow("重试次数",
                    self._wrap_field("retry", self._retry_spin,
                                     "请求失败后的自动重试次数，"
                                     "0 表示不重试（0–5 次）"))

        self._backoff_spin = QDoubleSpinBox()
        self._backoff_spin.setRange(0.1, 10.0)
        self._backoff_spin.setSingleStep(0.5)
        self._backoff_spin.setDecimals(1)
        self._backoff_spin.setValue(float(ADVANCED_DEFAULTS["backoff_base"]))
        self._backoff_spin.setSuffix(" 秒")
        self._backoff_spin.setObjectName("ai-input")
        self._backoff_spin.setToolTip("重试退避基数：第 n 次重试约等待"
                                      " 基数 × 2^(n-1) 秒")
        form.addRow("退避基数",
                    self._wrap_field("backoff_base", self._backoff_spin,
                                     "重试退避基数：第 n 次重试约等待"
                                     " 基数 × 2^(n-1) 秒"))

        self._concurrency_spin = QSpinBox()
        self._concurrency_spin.setRange(1, 8)
        self._concurrency_spin.setValue(int(ADVANCED_DEFAULTS["concurrency"]))
        self._concurrency_spin.setObjectName("ai-input")
        self._concurrency_spin.setToolTip("批量请求的最大并发数，"
                                          "过高可能触发服务端限流")
        form.addRow("并发上限",
                    self._wrap_field("concurrency", self._concurrency_spin,
                                     "批量请求的最大并发数，过高可能触发"
                                     "服务端限流（1–8）"))

        self._proxy_edit = QLineEdit()
        self._proxy_edit.setPlaceholderText("可选：http://127.0.0.1:7890，"
                                            "留空不启用")
        self._proxy_edit.setObjectName("ai-input")
        self._proxy_edit.setToolTip("HTTP 代理地址（Base URL），仅内存使用")
        form.addRow("代理 Base",
                    self._wrap_field("proxy", self._proxy_edit,
                                     "可选 HTTP 代理 Base URL，留空不启用；"
                                     "需以 http:// 或 https:// 开头"))

        self._redact_check = QCheckBox("响应日志脱敏（隐藏密钥与敏感字段）")
        self._redact_check.setChecked(bool(ADVANCED_DEFAULTS["redact_log"]))
        self._redact_check.setToolTip("开启后日志中不会出现 API 密钥明文")
        form.addRow(self._redact_check)

        self._watchdog_check = QCheckBox("启用请求超时看门狗（超时前主动中断）")
        self._watchdog_check.setChecked(bool(ADVANCED_DEFAULTS["watchdog"]))
        self._watchdog_check.setToolTip("避免网络异常导致请求长期挂起")
        form.addRow(self._watchdog_check)

        v.addWidget(grp)

        # M7-06 ①②：配置导入 / 导出（JSON，不含密钥）
        grp_io = QGroupBox("配置迁移（JSON，不含密钥）")
        grp_io.setObjectName("ai-group")
        io_row = QHBoxLayout(grp_io)
        io_row.setContentsMargins(12, 8, 12, 8)
        io_row.setSpacing(8)
        self._export_btn = QPushButton("导出配置 JSON")
        self._export_btn.setObjectName("secondary")
        self._export_btn.setFixedHeight(30)
        self._export_btn.setToolTip("导出模型参数与高级参数；"
                                    "出于安全考虑不包含 API 密钥")
        self._export_btn.clicked.connect(self._on_export_config)
        io_row.addWidget(self._export_btn)
        self._import_btn = QPushButton("导入配置…")
        self._import_btn.setObjectName("secondary")
        self._import_btn.setFixedHeight(30)
        self._import_btn.setToolTip("从导出的 JSON 恢复配置；"
                                    "导入后需点击「应用并保存」生效")
        self._import_btn.clicked.connect(self._on_import_config)
        io_row.addWidget(self._import_btn)
        io_row.addStretch(1)
        v.addWidget(grp_io)
        v.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # 分组 D：诊断（M7-05 将扩展为完整诊断页）
    # ------------------------------------------------------------------
    def _build_diag_page(self) -> QWidget:
        """构建「诊断」页：连接状态 + 后续诊断信息占位。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(12)

        grp = QGroupBox("连接状态")
        grp.setObjectName("ai-group")
        status_v = QVBoxLayout(grp)
        status_v.setSpacing(8)

        self._status_row = QHBoxLayout()
        self._status_row.setSpacing(12)
        self._status_dot = QLabel("●")
        self._status_dot.setObjectName("ai-status-dot")
        self._status_label = QLabel("未配置")
        self._status_label.setObjectName("sub")
        self._status_row.addWidget(self._status_dot)
        self._status_row.addWidget(self._status_label)
        self._status_row.addStretch(1)
        self._refresh_btn = QPushButton(icon("refresh", self._theme), "刷新")
        self._refresh_btn.setObjectName("secondary")
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.clicked.connect(self._refresh_status)
        self._status_row.addWidget(self._refresh_btn)
        status_v.addLayout(self._status_row)

        self._status_detail = QLabel("")
        self._status_detail.setObjectName("sub")
        self._status_detail.setWordWrap(True)
        status_v.addWidget(self._status_detail)

        v.addWidget(grp)

        # M7-04 ②：结构化测试结果卡（四元组：状态码/耗时/模型/时间）
        grp_result = QGroupBox("连通性测试结果")
        grp_result.setObjectName("ai-group")
        res_v = QVBoxLayout(grp_result)
        res_v.setSpacing(6)
        self._test_summary = QLabel("尚未测试；点击底部「测试连接」开始。")
        self._test_summary.setObjectName("sub")
        self._test_summary.setWordWrap(True)
        res_v.addWidget(self._test_summary)
        # M7-04 ④：错误分类的可执行建议
        self._test_advice = QLabel("")
        self._test_advice.setObjectName("ai-hint")
        self._test_advice.setWordWrap(True)
        self._test_advice.hide()
        res_v.addWidget(self._test_advice)
        # M7-04 ③：原始响应折叠区（默认收起，内容已脱敏）
        self._raw_toggle = QPushButton("展开原始响应 ▸")
        self._raw_toggle.setObjectName("secondary")
        self._raw_toggle.setFixedHeight(26)
        self._raw_toggle.hide()
        self._raw_toggle.clicked.connect(self._on_toggle_raw)
        res_v.addWidget(self._raw_toggle)
        self._raw_view = QTextEdit()
        self._raw_view.setReadOnly(True)
        self._raw_view.setObjectName("ai-raw")
        self._raw_view.setMaximumHeight(120)
        self._raw_view.hide()
        res_v.addWidget(self._raw_view)
        v.addWidget(grp_result)

        # M7-04 ⑤：最近 5 次测试历史（时间 + 结果 + 耗时，最新在前）
        grp_hist = QGroupBox("最近 5 次测试")
        grp_hist.setObjectName("ai-group")
        hist_v = QVBoxLayout(grp_hist)
        hist_v.setSpacing(6)
        self._history_list = QListWidget()
        self._history_list.setObjectName("ai-nav")
        self._history_list.setMaximumHeight(5 * 26 + 18)
        self._history_list.setToolTip("最近 5 次连通性测试记录（仅本次会话）")
        hist_v.addWidget(self._history_list)
        v.addWidget(grp_hist)

        # M7-05 ①：诊断信息（SDK/端点/生效参数/密钥来源与指纹/
        # requests 可用性/环境变量注入/降级状态；均不含密钥明文）
        grp_info = QGroupBox("诊断信息")
        grp_info.setObjectName("ai-group")
        info_form = QFormLayout(grp_info)
        info_form.setSpacing(6)
        self._diag_labels: dict[str, QLabel] = {}
        for name in ("SDK 版本", "requests 可用性", "端点", "生效参数",
                     "密钥来源", "密钥指纹", "环境变量注入", "降级状态"):
            lbl = QLabel("…")
            lbl.setObjectName("sub")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self._diag_labels[name] = lbl
            info_form.addRow(name, lbl)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._copy_diag_btn = QPushButton("复制诊断信息")
        self._copy_diag_btn.setObjectName("secondary")
        self._copy_diag_btn.setFixedHeight(28)
        self._copy_diag_btn.setToolTip("复制脱敏后的诊断信息到剪贴板"
                                       "（不含密钥明文）")
        self._copy_diag_btn.clicked.connect(self._on_copy_diag)
        btn_row.addWidget(self._copy_diag_btn)
        self._open_log_btn = QPushButton("打开日志目录")
        self._open_log_btn.setObjectName("secondary")
        self._open_log_btn.setFixedHeight(28)
        self._open_log_btn.clicked.connect(self._on_open_log_dir)
        btn_row.addWidget(self._open_log_btn)
        self._sysdiag_btn = QPushButton("系统诊断…")
        self._sysdiag_btn.setObjectName("secondary")
        self._sysdiag_btn.setFixedHeight(28)
        self._sysdiag_btn.setToolTip("查看应用 / Python / Qt 环境信息"
                                     "（与关于页一致）")
        self._sysdiag_btn.clicked.connect(self._on_system_diag)
        btn_row.addWidget(self._sysdiag_btn)
        btn_row.addStretch(1)
        info_form.addRow(btn_row)
        v.addWidget(grp_info)

        hint = QLabel("诊断信息不含密钥明文（指纹仅显示末 4 位）；"
                      "遇到问题可一键复制反馈。")
        hint.setObjectName("sub")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        return page

    def _on_toggle_raw(self) -> None:
        """展开 / 收起原始响应折叠区（M7-04 ③）。"""
        visible = self._raw_view.isVisible()
        self._raw_view.setVisible(not visible)
        self._raw_toggle.setText(
            "收起原始响应 ▾" if not visible else "展开原始响应 ▸")

    # ------------------------------------------------------------------
    # 配置加载 / 保存
    # ------------------------------------------------------------------
    def _load_with_fallback(self) -> None:
        """从 ConfigManager 加载配置，失败时回退到默认值并记录日志。"""
        try:
            from ..ai.config import get_ai_config
            ai_cfg = get_ai_config(self._config)

            # 加载 API 密钥（仅内存）
            api_key = ai_cfg.get_api_key()
            self._api_key_edit.setText(api_key or "")
            self._update_key_source_label(api_key)

            # 加载模型参数（持久化；QSpinBox/QDoubleSpinBox 自动钳制越界值）
            self._timeout_spin.setValue(int(ai_cfg.get("timeout", 30)))
            self._model_combo.setCurrentText(
                str(ai_cfg.get("model", "agnes-3.0-flash")))
            self._max_tokens_spin.setValue(int(ai_cfg.get("max_tokens", 1024)))
            self._temperature_spin.setValue(
                float(ai_cfg.get("temperature", 0.3)))
            self._load_advanced(ai_cfg)

            _logger.info(
                "AI 配置加载成功：timeout=%s, model=%s, max_tokens=%s, "
                "temperature=%s",
                ai_cfg.get("timeout"), ai_cfg.get("model"),
                ai_cfg.get("max_tokens"), ai_cfg.get("temperature"))

        except Exception as e:
            _logger.exception("AI 配置加载失败，使用默认值: %s", e)
            self._timeout_spin.setValue(30)
            self._model_combo.setCurrentText("agnes-3.0-flash")
            self._max_tokens_spin.setValue(1024)
            self._temperature_spin.setValue(0.3)
            self._api_key_edit.setText("")
            self._update_key_source_label(None)

    def _load_advanced(self, ai_cfg) -> None:
        """加载高级参数（分组 C），失败时保留控件默认值。"""
        try:
            self._retry_spin.setValue(int(ai_cfg.get("retry",
                                                     ADVANCED_DEFAULTS["retry"])))
            self._backoff_spin.setValue(
                float(ai_cfg.get("backoff_base",
                                 ADVANCED_DEFAULTS["backoff_base"])))
            self._concurrency_spin.setValue(
                int(ai_cfg.get("concurrency",
                               ADVANCED_DEFAULTS["concurrency"])))
            self._proxy_edit.setText(str(ai_cfg.get("proxy", "") or ""))
            self._redact_check.setChecked(
                bool(ai_cfg.get("redact_log",
                                ADVANCED_DEFAULTS["redact_log"])))
            self._watchdog_check.setChecked(
                bool(ai_cfg.get("watchdog",
                                ADVANCED_DEFAULTS["watchdog"])))
        except Exception as e:
            _logger.warning("高级参数加载失败，保留默认值: %s", e)

    def _update_key_source_label(self, api_key: Optional[str]) -> None:
        """更新密钥来源 Badge（胶囊样式，色值取自主题色板）。"""
        p = pal()
        if not api_key:
            text, fg = "未配置密钥", p["sub"]
        elif self._frozen:
            text, fg = "打包模式 · 环境变量注入", p["warning"]
        else:
            text, fg = "调试模式 · 仅内存", p["down"]
        self._key_source_label.setText(text)
        self._key_source_label.setStyleSheet(
            f"color:{fg};background:{p['chip_bg']};"
            f"border:1px solid {p['border']};border-radius:9px;"
            f"padding:2px 10px;")

    def _save_to_config(self) -> bool:
        """将 UI 值写回 ConfigManager（密钥仅内存，不持久化；其余持久化）。

        M7-01：数值字段全部改为 SpinBox 控件，越界值由控件自动钳制，
        不再需要手工解析/校验文本。

        返回:
            bool: 保存是否成功
        """
        from ..ai.config import get_ai_config

        try:
            ai_cfg = get_ai_config(self._config)

            # 保存 API 密钥（仅内存）
            api_key = self._api_key_edit.text().strip()
            ai_cfg.set_api_key(api_key)

            # 模型名称（可编辑下拉，仍需非空校验；正常路径已被就地校验拦截）
            model = self._model_combo.currentText().strip()
            if not model:
                Toast(self, "模型名称不能为空", level="warn",
                      duration=2500).present()
                return False

            # 模型参数（SpinBox 已保证范围）
            timeout = int(self._timeout_spin.value())
            max_tokens = int(self._max_tokens_spin.value())
            temperature = round(float(self._temperature_spin.value()), 2)
            ai_cfg.set("timeout", timeout)
            ai_cfg.set("model", model)
            ai_cfg.set("max_tokens", max_tokens)
            ai_cfg.set("temperature", temperature)

            # 高级参数（分组 C，M7-01）
            ai_cfg.set("retry", int(self._retry_spin.value()))
            ai_cfg.set("backoff_base", float(self._backoff_spin.value()))
            ai_cfg.set("concurrency", int(self._concurrency_spin.value()))
            ai_cfg.set("proxy", self._proxy_edit.text().strip())
            ai_cfg.set("redact_log", bool(self._redact_check.isChecked()))
            ai_cfg.set("watchdog", bool(self._watchdog_check.isChecked()))

            # 所有验证通过，保存配置到磁盘
            save_ok = ai_cfg.save()
            if not save_ok:
                _logger.error("AI 配置保存失败（ConfigManager.save() 返回 False）")
                Toast(self, "配置写入磁盘失败，请检查 data 目录写入权限",
                      level="error", duration=3500).present()
                return False

            _logger.info(
                "AI 配置保存成功：timeout=%d, model=%s, max_tokens=%d, "
                "temperature=%.2f, retry=%d, concurrency=%d",
                timeout, model, max_tokens, temperature,
                int(self._retry_spin.value()),
                int(self._concurrency_spin.value()))
            return True

        except Exception as e:
            _logger.exception("AI 配置保存异常: %s", e)
            Toast(self, f"保存异常：{type(e).__name__}: {e}",
                  level="error", duration=3500).present()
            return False

    # ------------------------------------------------------------------
    # 状态与连通性测试
    # ------------------------------------------------------------------
    def _refresh_status(self) -> None:
        """刷新 API 状态展示（不含敏感值）。"""
        self._refresh_diag_info()  # M7-05：诊断信息随状态一起刷新
        try:
            from ..ai.llm_client import api_status, get_client
            from ..ai.config import get_ai_config
            st = api_status()
            ai_cfg = get_ai_config(self._config)
            c = get_client()

            dot = self._status_dot
            label = self._status_label
            detail = self._status_detail

            if st.get("usable"):
                self._style_status("ok")
                label.setText("已连接")
                detail.setText(
                    f"Agnes AI API 可用\n"
                    f"端点：{AGNES_API_BASE}\n"
                    f"模型：{c.model}\n"
                    f"最大令牌数：{c.max_tokens}\n"
                    f"温度：{c.temperature}\n"
                    f"超时时间：{c.timeout}秒"
                )
            elif st.get("configured"):
                self._style_status("warn")
                label.setText("已配置（未测试）")
                if self._frozen:
                    detail.setText(
                        f"打包模式：API 密钥已从环境变量注入\n"
                        f"端点：{AGNES_API_BASE}\n"
                        f"模型：{ai_cfg.get('model', 'agnes-3.0-flash')}\n"
                        f"最大令牌数：{ai_cfg.get('max_tokens', 1024)}\n"
                        f"温度：{ai_cfg.get('temperature', 0.3)}\n"
                        f"超时时间：{ai_cfg.get('timeout', 30)}秒\n"
                        f"点击「测试连接」验证。"
                    )
                else:
                    detail.setText(
                        f"API 密钥已配置，端点：{AGNES_API_BASE}\n"
                        f"模型：{ai_cfg.get('model', 'agnes-3.0-flash')}\n"
                        f"最大令牌数：{ai_cfg.get('max_tokens', 1024)}\n"
                        f"温度：{ai_cfg.get('temperature', 0.3)}\n"
                        f"超时时间：{ai_cfg.get('timeout', 30)}秒\n"
                        f"请确保网络通畅后点击「测试连接」验证。"
                    )
            else:
                self._style_status("off")
                label.setText("未配置" if not self._frozen else "未注入")
                if self._frozen:
                    detail.setText(
                        f"打包模式：未检测到环境变量 {_ENV_KEY}\n"
                        f"请在启动前设置该环境变量，或改用调试模式运行。"
                    )
                else:
                    detail.setText(
                        f"Agnes AI API 未配置。\n"
                        f"请在「连接凭据」页输入 API 密钥后点击「应用并保存」，"
                        f"再点「测试连接」验证。"
                    )
        except Exception as e:
            _logger.exception("刷新 AI 状态失败: %s", e)
            self._style_status("error")
            self._status_label.setText("状态刷新失败")
            self._status_detail.setText(f"状态刷新异常：{type(e).__name__}: {e}")

    def _style_status(self, level: str) -> None:
        """M7-07①：状态点/状态文案样式统一走 token（主题切换零残留）。"""
        self._last_status_level = level
        p = pal()
        colors = {"ok": p["down"], "warn": p["warning"],
                  "off": p["sub"], "error": p["up"]}
        color = colors.get(level, p["sub"])
        dot_qss = f"color:{color};font-size:16px;font-weight:bold;"
        label_qss = (f"color:{color};font-size:13px;"
                      + ("font-weight:bold;" if level in ("ok", "warn") else ""))
        self._status_dot.setStyleSheet(dot_qss)
        self._status_label.setStyleSheet(label_qss)
        self._repolish(self._status_dot)
        self._repolish(self._status_label)

    def _on_test(self) -> None:
        """连通性测试入口：运行中再点 = 请求取消（M7-04 ⑥）。"""
        if self._test_state == "running":
            self._test_cancel.set()
            self._test_btn.setText("取消中…")
            self._test_btn.setEnabled(False)
            return

        from ..ai.llm_client import get_client
        client = get_client()
        if not client.available():
            # 未满足前置条件：就地显示建议（不再弹 QMessageBox）
            reason = "no_requests" if requests is None else "no_key"
            self._show_test_result({"ok": False, "reason": reason,
                                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "elapsed_ms": 0, "status": 0,
                                    "model": client.model or "-",
                                    "body": "", "attempts": 0,
                                    "cancelled": False,
                                    "breaker_open": False})
            self._apply_current_index(3)  # 跳到诊断页查看结果
            return

        self._test_state = "running"
        self._test_cancel.clear()
        self._test_result = None
        self._test_btn.setText("测试中… 点击取消")
        self._test_spinner.show()
        self._test_summary.setText("测试中…")
        self._raw_toggle.hide()
        self._raw_view.hide()
        self._test_poll.start()
        threading.Thread(target=self._probe_worker, daemon=True).start()

    def _probe_worker(self) -> None:
        """后台线程：执行 probe（复用 M3-08 重试与熔断），结果交轮询读取。"""
        from ..ai.llm_client import get_client
        client = get_client()
        self._test_result = client.probe(
            should_abort=self._test_cancel.is_set)

    def _poll_test(self) -> None:
        """UI 线程轮询：后台 probe 完成后回到 UI 线程更新结果卡。"""
        if self._test_state != "running" or self._test_result is None:
            return
        self._test_poll.stop()
        self._test_state = "idle"
        self._test_spinner.hide()
        self._test_btn.setEnabled(True)
        self._test_btn.setText("测试连接")
        self._show_test_result(self._test_result)
        self._test_result = None

    # ------------------------------------------------------------------
    # M7-04 ②④⑤：结构化结果卡 + 可执行建议 + 历史
    # ------------------------------------------------------------------
    _TEST_ADVICE = {
        "no_key": ("未配置 API 密钥：请在「连接凭据」页填写后点击"
                   f"「应用并保存」；打包模式请设置环境变量 {_ENV_KEY}。"),
        "no_requests": "未安装 requests 库：请先 pip install requests 后重试。",
        "circuit_open": ("熔断已打开（连续失败 5 次）：60 秒内快速失败。"
                         "请排查网络/密钥后稍候再试。"),
        "Timeout": "请求超时：可在「模型参数」页增大超时时间，"
                   "或检查网络/代理设置。",
        "ConnectTimeout": "连接超时：请检查网络是否通畅、代理设置是否正确。",
        "ConnectionError": "无法连接服务器：请检查网络、代理与防火墙设置。",
        "SSLError": "SSL 证书校验失败：请检查系统时间与代理中间人设置。",
        "401": "未授权：API 密钥不正确或已过期，请到服务商控制台重新生成。",
        "404": "模型不存在：请核对模型名称拼写（区分大小写），"
               "或改用预置模型 agnes-3.0-flash。",
        "503": "服务不可用：可能为维护/限流/无模型权限/余额不足。"
               "建议稍等 1–2 分钟重试，或登录服务商控制台检查账户状态。",
    }

    def _test_advice_for(self, res: dict) -> str:
        """按结果分类给出可执行建议（M7-04 ④）。"""
        if res.get("ok"):
            return "连接正常，AI 功能可正常使用。"
        if res.get("cancelled"):
            return "测试已取消。"
        reason = str(res.get("reason", ""))
        # "HTTP 503" → 按状态码 "503" 查表；异常类名直接查表
        code = reason.split(" ")[-1] if reason.startswith("HTTP ") else reason
        return self._TEST_ADVICE.get(
            code, f"测试失败：{reason or '未知原因'}")

    def _show_test_result(self, res: dict) -> None:
        """把 probe 结果渲染为结构化卡片 + 建议 + 历史（UI 线程）。"""
        p = pal()
        ok = bool(res.get("ok"))
        cancelled = bool(res.get("cancelled"))
        code = res.get("status") or 0
        ms = int(res.get("elapsed_ms") or 0)
        model = res.get("model") or "-"
        ts = res.get("time") or time.strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            mark = "✓"
            color = p["down"]    # 成功 = 绿
        elif cancelled:
            mark = "−"
            color = p["warning"]
        else:
            mark = "✗"
            color = p["up"]      # 失败 = 红
        head = (f"HTTP {code} {mark}" if code else
                ("已取消" if cancelled else "请求异常"))
        self._test_summary.setText(
            f"{head} · {ms} ms · {model} · {ts}")
        self._test_summary.setStyleSheet(f"color:{color};font-weight:bold;")
        advice = self._test_advice_for(res)
        self._test_advice.setText(f"建议：{advice}")
        self._test_advice.show()
        body = res.get("body") or ""
        if body and not cancelled:
            self._raw_view.setPlainText(body)
            self._raw_toggle.setText("展开原始响应 ▸")
            self._raw_toggle.show()
            self._raw_view.hide()
        else:
            self._raw_view.hide()
            self._raw_toggle.hide()
        if not cancelled:
            self._record_history(res)
        self._refresh_status()

    def _record_history(self, res: dict) -> None:
        """记录一次测试到历史列表（最新在前，保留 5 条；M7-04 ⑤）。"""
        ok = bool(res.get("ok"))
        code = res.get("status") or 0
        ms = int(res.get("elapsed_ms") or 0)
        ts = (res.get("time") or time.strftime("%Y-%m-%d %H:%M:%S"))
        item_text = (f"{ts}   HTTP {code} {'✓' if ok else '✗'}   {ms} ms   "
                     f"{res.get('model', '-')}")
        self._test_history.insert(0, {"time": ts, "ok": ok,
                                      "code": code, "ms": ms})
        del self._test_history[5:]
        self._history_list.insertItem(0, item_text)
        while self._history_list.count() > 5:
            self._history_list.takeItem(self._history_list.count() - 1)

    # ------------------------------------------------------------------
    # M7-05：诊断页（信息汇总 / 复制 / 日志目录 / 系统诊断联动）
    # ------------------------------------------------------------------
    @staticmethod
    def _key_fingerprint(key: Optional[str]) -> str:
        """密钥指纹：仅显示末 4 位，永不显示全文（M7-05 ①）。"""
        if not key:
            return "未配置"
        return f"…{key[-4:]}"

    def _diag_data(self) -> dict[str, str]:
        """汇总诊断信息（全部不含密钥明文）。"""
        from ..ai.config import get_ai_config
        ai_cfg = get_ai_config(self._config)
        try:
            from ..ai.llm_client import api_status
            st = api_status()
        except Exception:  # noqa: BLE001 - 诊断页自身不允许抛
            st = {}

        req_ok = requests is not None
        sdk = (getattr(requests, "__version__", "未知")
               if req_ok else "不可用")
        key = ai_cfg.get_api_key()
        source = ai_cfg.key_source()
        env_set = bool(os.environ.get(_ENV_KEY))
        source_txt = {
            "memory": "内存（本次会话输入，关闭程序即失效）",
            "env": f"环境变量 {_ENV_KEY}",
            "none": "未配置",
        }[source]
        params = (f"{ai_cfg.get('model', '-')} / "
                  f"{ai_cfg.get('max_tokens', '-')} tokens / "
                  f"温度 {ai_cfg.get('temperature', '-')} / "
                  f"超时 {ai_cfg.get('timeout', '-')} 秒")
        if st.get("usable"):
            degrade = "正常（在线调用）"
        elif st.get("configured"):
            cb = st.get("circuit") or {}
            degrade = ("已配置（连通性未验证）；熔断打开中"
                       if cb.get("open") else "已配置（连通性未验证）")
        else:
            degrade = "未配置 → AI 功能将降级为本地规则"
        return {
            "SDK 版本": f"requests {sdk}",
            "requests 可用性": "✓ 可用" if req_ok else "✗ 不可用",
            "端点": AGNES_API_BASE,
            "生效参数": params,
            "密钥来源": source_txt,
            "密钥指纹": self._key_fingerprint(key),
            "环境变量注入": (f"已设置 {_ENV_KEY}" if env_set
                            else f"未设置 {_ENV_KEY}"),
            "降级状态": degrade,
        }

    def _refresh_diag_info(self) -> None:
        """把诊断数据刷到标签（任何异常都不允许影响页面）。"""
        try:
            for name, value in self._diag_data().items():
                lbl = self._diag_labels.get(name)
                if lbl is not None:
                    lbl.setText(value)
        except Exception as e:  # noqa: BLE001
            _logger.warning("刷新诊断信息失败: %s", e)

    def _on_copy_diag(self) -> None:
        """复制脱敏诊断信息到剪贴板（M7-05 ②）。"""
        data = self._diag_data()
        text = "QuantVortex AI 诊断信息\n" + "\n".join(
            f"{k}：{v}" for k, v in data.items())
        QApplication.clipboard().setText(text)
        Toast(self, "诊断信息已复制（不含密钥明文）", level="info",
              duration=2500).present()

    def _on_open_log_dir(self) -> None:
        """打开日志目录（logs/，不存在则创建；M7-05 ③）。"""
        log_dir = os.path.join(os.getcwd(), "logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            _logger.warning("创建日志目录失败: %s", e)
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))

    def _on_system_diag(self) -> None:
        """系统诊断联动（M7-05 ④）：优先发信号由主窗口跳转，
        无接收者时就地显示与环境页一致的环境信息。"""
        self.system_diag_requested.emit()
        if self.receivers(self.system_diag_requested) > 0:
            return
        import sys as _sys
        from PyQt6.QtCore import QT_VERSION_STR
        try:
            from .. import __version__ as app_ver
            ver = f"QuantVortex v{app_ver}"
        except Exception:  # noqa: BLE001
            ver = "QuantVortex"
        QMessageBox.information(
            self, "系统诊断",
            f"{ver}\n"
            f"Python {_sys.version.split()[0]}\n"
            f"PyQt6 / Qt {QT_VERSION_STR}\n"
            f"平台：{_sys.platform}")

    # ------------------------------------------------------------------
    # M7-06：配置导出 / 导入 / 重置
    # ------------------------------------------------------------------
    def _current_config_dict(self) -> dict:
        """收集当前 UI 值为可导出的 config 字典（不含 api_key）。"""
        return {
            "model": self._model_combo.currentText().strip(),
            "timeout": int(self._timeout_spin.value()),
            "max_tokens": int(self._max_tokens_spin.value()),
            "temperature": round(float(self._temperature_spin.value()), 2),
            "retry": int(self._retry_spin.value()),
            "backoff_base": float(self._backoff_spin.value()),
            "concurrency": int(self._concurrency_spin.value()),
            "proxy": self._proxy_edit.text().strip(),
            "redact_log": bool(self._redact_check.isChecked()),
            "watchdog": bool(self._watchdog_check.isChecked()),
        }

    def _on_export_config(self) -> None:
        """导出配置 JSON（不含密钥；导出后弹窗提示，M7-06 ①）。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 AI 配置", "ai_config_backup.json", "JSON (*.json)")
        if not path:
            return
        data = {
            "schema": EXPORT_SCHEMA,
            "version": EXPORT_VERSION,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "config": self._current_config_dict(),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            _logger.exception("导出 AI 配置失败: %s", e)
            Toast(self, f"导出失败：{type(e).__name__}: {e}",
                  level="error", duration=3500).present()
            return
        QMessageBox.information(
            self, "导出成功",
            f"配置已导出到：\n{path}\n\n"
            "出于安全考虑，API 密钥未包含在导出文件中。")

    def _validate_import(self, data: object) -> Optional[str]:
        """校验导入数据；返回错误说明（None 表示合法）。"""
        if not isinstance(data, dict):
            return "根节点必须是 JSON 对象"
        if data.get("schema") != EXPORT_SCHEMA:
            return f"schema 不匹配（期望 {EXPORT_SCHEMA}）"
        ver = data.get("version")
        if not isinstance(ver, int) or isinstance(ver, bool) \
                or ver > EXPORT_VERSION:
            return f"不支持的 schema 版本：{ver!r}"
        cfg = data.get("config")
        if not isinstance(cfg, dict):
            return "缺少 config 对象"
        for k, v in cfg.items():
            spec = _IMPORT_SPEC.get(k)
            if spec is None:
                continue  # 未知键忽略，向前兼容
            typ, rng = spec
            if typ is bool:
                if not isinstance(v, bool):
                    return f"字段 {k} 应为布尔值（true/false）"
                continue
            # bool 是 int 子类，先排除
            if isinstance(v, bool) or not isinstance(v, typ):
                return (f"字段 {k} 类型错误"
                        f"（期望 {typ.__name__}，实际 {type(v).__name__}）")
            if rng is not None and not (rng[0] <= v <= rng[1]):
                return f"字段 {k} 超出允许范围 {rng[0]}–{rng[1]}"
        model = cfg.get("model")
        if isinstance(model, str) and not model.strip():
            return "字段 model 不能为空"
        return None

    def _apply_imported(self, cfg: dict) -> None:
        """把合法的导入配置写入控件（不直接落盘，等用户确认应用）。"""
        if "model" in cfg:
            self._model_combo.setCurrentText(cfg["model"])
        if "timeout" in cfg:
            self._timeout_spin.setValue(int(cfg["timeout"]))
        if "max_tokens" in cfg:
            self._max_tokens_spin.setValue(int(cfg["max_tokens"]))
        if "temperature" in cfg:
            self._temperature_spin.setValue(float(cfg["temperature"]))
        if "retry" in cfg:
            self._retry_spin.setValue(int(cfg["retry"]))
        if "backoff_base" in cfg:
            self._backoff_spin.setValue(float(cfg["backoff_base"]))
        if "concurrency" in cfg:
            self._concurrency_spin.setValue(int(cfg["concurrency"]))
        if "proxy" in cfg:
            self._proxy_edit.setText(str(cfg["proxy"]))
        if "redact_log" in cfg:
            self._redact_check.setChecked(bool(cfg["redact_log"]))
        if "watchdog" in cfg:
            self._watchdog_check.setChecked(bool(cfg["watchdog"]))
        self._revalidate()
        self._mark_dirty()

    def _on_import_config(self) -> None:
        """导入配置 JSON（校验 schema 版本；非法给出明确错误，M7-06 ②）。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 AI 配置", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:  # noqa: BLE001
            Toast(self, f"导入失败：文件读取/解析错误（{e}）",
                  level="error", duration=3500).present()
            return
        err = self._validate_import(data)
        if err is not None:
            Toast(self, f"导入失败：{err}", level="error",
                  duration=3500).present()
            return
        self._apply_current_index(2)  # 跳到高级页让用户查看导入结果
        self._apply_imported(data["config"])
        Toast(self, "已导入配置，请检查后点击「应用并保存」",
              level="info", duration=3000).present()

    def _on_reset(self) -> None:
        """恢复默认（M7-06 ③④）：二次确认 → 密钥清空 + 参数回默认 + Toast。"""
        ok = QMessageBox.question(
            self, "重置配置",
            "确定要清除 API 密钥并恢复默认参数吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            from ..ai.config import get_ai_config
            ai_cfg = get_ai_config(self._config)
            ai_cfg.set_api_key(None)   # 密钥清空（仅内存）
            ai_cfg.reset_to_defaults()  # 4 个核心参数回默认并 apply
            for k, v in ADVANCED_DEFAULTS.items():
                ai_cfg.set(k, v)        # 高级参数回默认（不在 DEFAULTS 内）
            ai_cfg.save()
            self._load_with_fallback()
            self._loading = False
            self._revalidate()
            self._clear_dirty()
            self._refresh_status()
            Toast(self, "已恢复默认 ✓", level="info",
                  duration=2500).present()
        except Exception as e:
            _logger.exception("重置配置失败: %s", e)
            Toast(self, f"重置失败：{type(e).__name__}: {e}",
                  level="error", duration=3500).present()

    # ------------------------------------------------------------------
    # 应用 / 重置
    # ------------------------------------------------------------------
    def _on_apply(self) -> None:
        """应用配置：先就地校验（无弹窗），再「保存中…」+ 保存 + 热更新。"""
        errs = self._field_errors()
        if errs:
            # M7-03 ④：就地错误已显示，跳转到首个出错字段并聚焦
            self._revalidate()
            self._focus_first_error()
            Toast(self, "请先修正标红的字段", level="warn",
                  duration=2500).present()
            return
        # M7-07⑤：保存动作改为「异步可观察」——先展示「保存中…」态（spinner 可见）
        # 再交给带间隔的单发 QTimer（150ms）执行保存 + 热更新，完成后恢复按钮。
        # 既保留 M7-03 的保存中可观测契约（test processEvents 后 timer 未触发），
        # 又避免 50ms 魔法延迟。
        self._set_saving(True)
        self._apply_timer.setInterval(150)
        self._apply_timer.start()

    def _set_saving(self, saving: bool) -> None:
        """切换「保存中」态：按钮禁用 + 文案 + 自绘 spinner（M7-03 ③）。"""
        if saving:
            self._save_btn.setEnabled(False)
            self._save_btn.setText("保存中…")
            self._save_spinner.start()
        else:
            self._save_btn.setText("应用并保存")
            self._save_btn.setEnabled(not self._field_errors())
            self._save_spinner.stop()

    def _finish_apply(self) -> None:
        """QTimer 单发触发：执行保存 + 热更新，并恢复按钮「应用并保存」态。"""
        self._do_apply()
        self._set_saving(False)

    def _do_apply(self) -> None:
        """执行保存 + 热更新（成功 → Toast + 清 dirty；失败 → 错误 Toast）。"""
        try:
            if not self._save_to_config():
                return
            from ..ai.config import get_ai_config
            ai_cfg = get_ai_config(self._config)
            ai_cfg.apply()
            self.config_applied.emit()
            self._refresh_status()
            self._update_key_source_label(ai_cfg.get_api_key())
            self._clear_dirty()
            # M7-03 ⑤：非阻断 Toast 2.5s 自动消失（对话框保持打开，便于继续调整）
            Toast(self, "已保存并生效 ✓（无需重启）", level="info",
                  duration=2500).present()
        except Exception as e:
            _logger.exception("应用 AI 配置失败: %s", e)
            Toast(self, f"应用失败：{type(e).__name__}: {e}",
                  level="error", duration=3500).present()

    def keyPressEvent(self, event) -> None:
        """M7-07③：对话框局部快捷键（模态期间不抢占主窗口全局键）。

        - Ctrl+S   → 应用并保存
        - Ctrl+Enter → 测试连接
        - Ctrl+R   → 恢复默认
        - Esc      → 关闭对话框（reject，不保存未应用改动）
        """
        # Esc：单独处理，不用修饰键
        if event.key() == Qt.Key.Key_Escape and not event.modifiers():
            self.reject()
            return
        mod = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if mod and event.key() in (Qt.Key.Key_S, Qt.Key.Key_Return,
                                   Qt.Key.Key_Enter, Qt.Key.Key_R):
            if event.key() == Qt.Key.Key_S:
                self._on_apply()
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_test()
            else:
                self._on_reset()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        """应用主题样式到各子组件。"""
        p = pal()
        self.setStyleSheet(f"""
            QDialog {{ background:{p['bg']}; }}
            QGroupBox#ai-group {{
                border:1px solid {p['border']}; border-radius:10px;
                margin-top:8px; padding-top:12px;
                font-weight:bold; color:{p['text']};
            }}
            QGroupBox#ai-group::title {{
                subcontrol-origin: margin; left:12px; padding:0 6px;
            }}
            QLineEdit#ai-input, QSpinBox#ai-input, QDoubleSpinBox#ai-input,
            QComboBox#ai-input {{
                background:{p['panel']}; border:1px solid {p['border']};
                border-radius:8px; padding:5px 10px; color:{p['text']};
            }}
            QLineEdit#ai-input:focus, QSpinBox#ai-input:focus,
            QDoubleSpinBox#ai-input:focus, QComboBox#ai-input:focus {{
                border:1px solid {p['accent']};
            }}
            QListWidget#ai-nav {{
                background:{p['panel']}; border:1px solid {p['border']};
                border-radius:10px; padding:6px; outline:0;
                color:{p['sub']}; font-size:13px;
            }}
            QListWidget#ai-nav::item {{
                padding:8px 10px; border-radius:8px; margin:2px 0;
            }}
            QListWidget#ai-nav::item:selected {{
                background:{p['row_sel']}; color:{p['text']};
            }}
            QTabWidget::pane {{ border:0; top:-1px; }}
            QTabBar::tab {{
                padding:8px 14px; color:{p['sub']};
                background:transparent; border-bottom:2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color:{p['accent']}; border-bottom:2px solid {p['accent']};
            }}
            QPushButton#ai-eye {{
                background:{p['panel']}; border:1px solid {p['border']};
                border-radius:8px; color:{p['sub']}; font-size:14px;
            }}
            QPushButton#ai-eye:checked {{ border:1px solid {p['accent']}; }}
            QCheckBox {{ color:{p['text']}; }}
            QFrame#ai-note {{
                background:{p['badge_bg']}; border:1px solid {p['border']};
                border-radius:10px;
            }}
            QFrame#ai-note QLabel {{ color:{p['sub']}; font-size:12px; }}
            QTextEdit#ai-raw {{
                background:{p['panel']}; border:1px solid {p['border']};
                border-radius:8px; color:{p['sub']}; font-size:11px;
            }}
            QLabel#ai-hint {{ color:{p['sub']}; font-size:11px; }}
            QLabel#ai-error {{ font-size:11px; font-weight:bold; }}
            QLabel#ai-dirty {{
                color:{p['warning']}; background:{p['chip_bg']};
                border:1px solid {p['warning']}; border-radius:9px;
                padding:2px 10px; font-size:12px; font-weight:bold;
            }}
            QLineEdit#ai-input[error="true"], QSpinBox#ai-input[error="true"],
            QDoubleSpinBox#ai-input[error="true"],
            QComboBox#ai-input[error="true"] {{
                border:1px solid {p['down']};
            }}
            #btn-bar {{ background:{p['panel']}; border-top:1px solid {p['border']}; }}
        """)

    def set_theme(self, t: str) -> None:
        """设置主题（M7-07②：递归覆盖全部分段与字段，主题切换零残留）。

        参数:
            t: str
        """
        global THEME
        # 与 main_window 的全局主题约定一致：同步模块级 THEME，
        # 否则后续 pal()（setStyleSheet 内）仍读旧主题 → 色值残留
        from . import widgets as _w
        THEME = t
        _w.THEME = t
        self._theme = t
        self._header.set_theme(t)
        self._apply_theme()
        self._refresh_btn.setIcon(icon("refresh", t))
        self._test_btn.setIcon(icon("send", t))
        # 状态点/状态文案重放，消除「状态内联样式不随主题刷新」的残留
        self._style_status(getattr(self, "_last_status_level", "off"))
