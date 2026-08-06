"""AI 模型配置设置对话框（简化版）。

功能：
    - Agnes AI API 密钥输入（仅此一项）
    - 连通性测试
    - 热更新：修改后点「应用」立即生效，无需重启

双模式安全约定（2026-08）：
    - 调试模式：可填写 API 密钥到内存
    - 打包模式：隐藏密钥输入框，显示环境变量注入说明

安全约定：
    - API 密钥仅在内存中持有，不落盘到配置文件
    - 固定使用 https://api.agnes-ai.cn/v1/chat/completions 端点

调用方式：
    from futures_quant.ui.ai_settings_dialog import AIConfigDialog
    dlg = AIConfigDialog(config=main_window.config)
    dlg.exec()
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QGroupBox, QFormLayout, QMessageBox,
)

from .widgets import PageHeader, pal, THEME
from .icons import icon
from ..runtime import is_frozen

# 固定的 Agnes AI 端点
AGNES_API_BASE = "https://api.agnes-ai.cn/v1/chat/completions"

# 环境变量名
_ENV_KEY = "QV_AGNES_API_KEY"


class AIConfigDialog(QDialog):
    """AI 模型配置设置对话框（仅 API 密钥）。"""

    # 信号：配置已应用（供主窗口状态栏刷新）
    config_applied = pyqtSignal()

    def __init__(self, config=None, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._theme = THEME
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._do_apply)
        self._frozen = is_frozen()
        self.setWindowTitle("AI 模型配置" if not self._frozen else "AI 模型状态")
        self.setFixedSize(480, 280)
        self._build()
        self._load()
        self._refresh_status()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部标题栏
        self._header = PageHeader("Agnes AI 配置", "API 密钥管理", theme=self._theme)
        root.addWidget(self._header)

        # 内容区
        scroll = QFrame()
        scroll.setObjectName("panel")
        scroll_v = QVBoxLayout(scroll)
        scroll_v.setContentsMargins(16, 12, 16, 12)
        scroll_v.setSpacing(12)

        # API 密钥配置
        grp_key = QGroupBox("API 密钥")
        grp_key.setObjectName("ai-group")
        form_key = QFormLayout(grp_key)
        form_key.setSpacing(10)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("请输入 Agnes AI API 密钥")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setObjectName("ai-input")

        # 打包模式：隐藏输入框，显示环境变量说明
        if self._frozen:
            self._api_key_edit.setVisible(False)
            self._env_hint_label = QLabel(
                f"打包模式下，API 密钥通过环境变量注入：<br>"
                f"<code style='background:#f0f0f0;padding:2px 6px;border-radius:4px;'>{_ENV_KEY}=sk-xxx</code><br>"
                f"<span style='color:#666;font-size:11px;'>示例：set {_ENV_KEY}=sk-xxx &amp; FuturesQuant.exe</span>"
            )
            self._env_hint_label.setObjectName("sub")
            self._env_hint_label.setWordWrap(True)
            form_key.addRow("注入方式", self._env_hint_label)
        else:
            form_key.addRow("API 密钥", self._api_key_edit)

        # 端点信息（只读）
        self._endpoint_label = QLabel(f"端点：{AGNES_API_BASE}")
        self._endpoint_label.setObjectName("sub")
        form_key.addRow("API 端点", self._endpoint_label)

        scroll_v.addWidget(grp_key)

        # 状态指示区
        grp_status = QGroupBox("连接状态")
        grp_status.setObjectName("ai-group")
        status_v = QVBoxLayout(grp_status)
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

        scroll_v.addWidget(grp_status)

        scroll_v.addStretch(1)
        root.addWidget(scroll)

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

        btn_h.addStretch(1)

        self._cancel_btn = QPushButton("关闭" if self._frozen else "取消")
        self._cancel_btn.setObjectName("secondary")
        self._cancel_btn.setFixedHeight(34)
        self._cancel_btn.clicked.connect(self.reject)
        btn_h.addWidget(self._cancel_btn)

        # 打包模式：隐藏「应用」按钮
        if not self._frozen:
            self._save_btn = QPushButton("应用")
            self._save_btn.setObjectName("primary")
            self._save_btn.setFixedHeight(34)
            self._save_btn.clicked.connect(self._on_apply)
            btn_h.addWidget(self._save_btn)
        else:
            self._save_btn = None

        root.addWidget(btn_bar)
        self._apply_theme()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        """从 ConfigManager 加载当前配置值。"""
        from ..ai.config import get_ai_config
        ai_cfg = get_ai_config(self._config)
        api_key = ai_cfg.get_api_key()
        if self._api_key_edit.isVisible():
            self._api_key_edit.setText(api_key or "")

    def _save_to_config(self) -> None:
        """将 UI 值写回 ConfigManager（密钥仅内存，不持久化）。"""
        from ..ai.config import get_ai_config
        ai_cfg = get_ai_config(self._config)
        api_key = self._api_key_edit.text().strip()
        ai_cfg.set_api_key(api_key)

    # ------------------------------------------------------------------
    def _refresh_status(self) -> None:
        """刷新 API 状态展示（不含敏感值）。"""
        from ..ai.llm_client import api_status
        from ..ai.config import get_ai_config
        st = api_status()
        ai_cfg = get_ai_config(self._config)

        dot = self._status_dot
        label = self._status_label
        detail = self._status_detail

        if st.get("usable"):
            dot.setStyleSheet("color:#22c55e;font-size:16px;font-weight:bold;")
            label.setText("已连接")
            label.setStyleSheet("color:#22c55e;font-size:13px;font-weight:bold;")
            detail.setText(f"Agnes AI API 可用\n端点：{AGNES_API_BASE}")
        elif st.get("configured"):
            dot.setStyleSheet("color:#f59e0b;font-size:16px;font-weight:bold;")
            label.setText("已配置（未测试）")
            label.setStyleSheet("color:#f59e0b;font-size:13px;font-weight:bold;")
            if self._frozen:
                detail.setText(f"API 密钥已从环境变量注入，端点：{AGNES_API_BASE}\n点击「测试连接」验证。")
            else:
                detail.setText(f"API 密钥已配置，端点：{AGNES_API_BASE}\n请确保网络通畅后点击「测试连接」验证。")
        else:
            dot.setStyleSheet("color:#6b7280;font-size:16px;font-weight:bold;")
            label.setText("未配置" if not self._frozen else "未注入")
            label.setStyleSheet("color:#6b7280;font-size:13px;")
            if self._frozen:
                detail.setText(
                    f"打包模式：未检测到环境变量 {_ENV_KEY}\n"
                    f"请在启动前设置该环境变量，或改用调试模式运行。"
                )
            else:
                detail.setText(
                    f"Agnes AI API 未配置。\n"
                    f"请在上方输入 API 密钥后点击「应用」，再点「测试连接」验证。"
                )

    def _on_test(self) -> None:
        """执行连通性测试（异步，不阻塞 UI）。"""
        self._test_btn.setEnabled(False)
        self._test_btn.setText("测试中…")
        QTimer.singleShot(50, self._run_test)

    def _run_test(self) -> None:
        """实际执行 API 连通性检测。"""
        from ..ai.llm_client import get_client
        client = get_client()
        if not client.available():
            if self._frozen:
                QMessageBox.warning(self, "连通性测试",
                                    f"未检测到环境变量 {_ENV_KEY}，请先设置后重试。")
            else:
                QMessageBox.warning(self, "连通性测试",
                                    "API 密钥未配置，请先填写密钥并点击「应用」。")
            self._test_btn.setEnabled(True)
            self._test_btn.setText("测试连接")
            return
        try:
            import requests as _req
            # 发送一个轻量级请求测试连通性
            resp = _req.post(
                client.base,
                headers={
                    "Authorization": f"Bearer {client.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "agnes-flash",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                timeout=min(client.timeout, 10),
            )
            if resp.status_code == 200:
                QMessageBox.information(self, "连通性测试", "API 连接正常 ✓")
            else:
                QMessageBox.warning(self, "连通性测试",
                                    f"API 返回异常状态码：{resp.status_code}\n"
                                    f"请检查 API 密钥是否正确。")
        except Exception as e:
            QMessageBox.critical(self, "连通性测试",
                                 f"无法连接到 Agnes AI API：\n{e}")
        self._test_btn.setEnabled(True)
        self._test_btn.setText("测试连接")
        self._refresh_status()

    def _on_apply(self) -> None:
        """应用配置（先保存，再热更新客户端）。"""
        # 打包模式不允许应用
        if self._frozen:
            return
        self._save_to_config()
        # 延迟 50ms 执行，让 UI 有瞬间反馈
        self._apply_timer.start(50)

    def _do_apply(self) -> None:
        """真正执行热更新。"""
        from ..ai.config import get_ai_config
        ai_cfg = get_ai_config(self._config)
        ai_cfg.apply()
        self.config_applied.emit()
        self._refresh_status()
        QMessageBox.information(self, "已应用",
                                "AI 配置已生效（无需重启程序）。")
        self.accept()

    def _on_reset(self) -> None:
        """重置配置（清除密钥）。"""
        ok = QMessageBox.question(
            self, "重置配置",
            "确定要清除 API 密钥吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        from ..ai.config import get_ai_config
        ai_cfg = get_ai_config(self._config)
        ai_cfg.reset_to_defaults()
        self._load()
        self._refresh_status()

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
            QLineEdit#ai-input {{
                background:{p['panel']}; border:1px solid {p['border']};
                border-radius:8px; padding:6px 10px; color:{p['text']};
            }}
            QLineEdit#ai-input:focus {{ border:1px solid {p['accent']}; }}
            #btn-bar {{ background:{p['panel']}; border-top:1px solid {p['border']}; }}
        """)

    def set_theme(self, t: str) -> None:
        global THEME
        THEME = t
        self._theme = t
        self._header.set_theme(t)
        self._apply_theme()
        self._refresh_btn.setIcon(icon("refresh", t))
        self._test_btn.setIcon(icon("send", t))
