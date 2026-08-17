"""关于对话框：简洁版（头像 + 联系信息）。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QLinearGradient, QBrush
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QApplication
)

from .widgets import pal, THEME
from .. import __version__ as __app_version__


class AvatarWidget(QWidget):
    """简约头像：圆角背景 + 中心图标。"""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(80, 80)
        self.setMaximumSize(80, 80)

    def paintEvent(self, e: object) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = int(min(self.width(), self.height()) * 0.45)
        cx, cy = self.width() // 2, self.height() // 2
        c = pal()
        # 渐变背景
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor(c['accent']))
        grad.setColorAt(1, QColor(c['accent2']))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        # 中心图标
        p.setPen(QPen(QColor('#ffffff'), 2))
        p.setFont(QFont('Microsoft YaHei', 22, QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'QV')
        p.end()


class AboutDialog(QDialog):
    """简洁版关于对话框。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # 使用标准对话框框架，避免无边框导致的渲染问题
        self.setMinimumWidth(380)
        self.setMaximumWidth(480)
        self.setWindowTitle("关于期货智能分析预测系统")
        self.setModal(True)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # 头像
        avatar = AvatarWidget()
        root.addWidget(avatar, 0, Qt.AlignmentFlag.AlignCenter)

        # 标题
        title = QLabel("期货智能分析预测系统")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont('Microsoft YaHei', 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #e6e6e6; padding: 8px 0;")
        root.addWidget(title)

        # 副标题
        sub = QLabel(f"QuantVortex v{__app_version__}")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont('Microsoft YaHei', 12))
        sub.setStyleSheet("color: #8b93a7; padding: 4px 0;")
        root.addWidget(sub)

        # 版本更新日期
        upd = QLabel("更新日期：2026-08-09")
        upd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        upd.setFont(QFont('Microsoft YaHei', 10))
        upd.setStyleSheet("color: #6b7280; padding: 0 0 4px 0;")
        root.addWidget(upd)

        # 分隔线
        sep = QLabel("─" * 30)
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep.setStyleSheet("color: #2a2e3a;")
        root.addWidget(sep)

        # 联系信息
        info = QLabel("如需联系开发者，请通过以下方式：\n\n")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setFont(QFont('Microsoft YaHei', 11))
        info.setStyleSheet("color: #cbd5e1; padding: 8px 0;")
        root.addWidget(info)

        # QQ
        qq = QLabel("📱 QQ：1153602036  （点击复制）")
        qq.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qq.setFont(QFont('Microsoft YaHei', 13))
        qq.setStyleSheet("""
            color: #4ade80;
            padding: 10px;
            background: rgba(74, 222, 128, 0.1);
            border-radius: 8px;
            border: 1px solid rgba(74, 222, 128, 0.3);
        """)
        qq.setToolTip("点击复制 QQ 号码")
        qq.mousePressEvent = lambda e: QApplication.clipboard().setText("1153602036")
        root.addWidget(qq)

        # 手机号
        phone = QLabel("📞 手机：19258585274  （点击复制）")
        phone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        phone.setFont(QFont('Microsoft YaHei', 13))
        phone.setStyleSheet("""
            color: #60a5fa;
            padding: 10px;
            background: rgba(96, 165, 250, 0.1);
            border-radius: 8px;
            border: 1px solid rgba(96, 165, 250, 0.3);
        """)
        phone.setToolTip("点击复制手机号码")
        phone.mousePressEvent = lambda e: QApplication.clipboard().setText("19258585274")
        root.addWidget(phone)

        # 工作室
        studio = QLabel("KP 工作室")
        studio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        studio.setFont(QFont('Microsoft YaHei', 11))
        studio.setStyleSheet("""
            color: #f59e0b;
            padding: 8px 0;
            font-weight: bold;
        """)
        root.addWidget(studio)

        # 分隔
        sep2 = QLabel("─" * 30)
        sep2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep2.setStyleSheet("color: #2a2e3a;")
        root.addWidget(sep2)

        # 声明
        note = QLabel("本软件仅用于学习与研究，不构成任何投资建议。\n\n© 2026 QuantVortex All Rights Reserved.")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setFont(QFont('Microsoft YaHei', 10))
        note.setStyleSheet("color: #6b7280; padding: 8px 0;")
        root.addWidget(note)

        # 关闭按钮
        btn = QWidget()
        btn.setLayout(QHBoxLayout())
        btn.layout().setContentsMargins(0, 8, 0, 0)
        btn.layout().setSpacing(0)
        close_btn = QLabel("✕ 关闭")
        close_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        close_btn.setStyleSheet("""
            QLabel {
                color: #8b93a7;
                padding: 8px 24px;
                background: rgba(255,255,255,0.05);
                border-radius: 6px;
            }
            QLabel:hover {
                color: #e6e6e6;
                background: rgba(255,255,255,0.1);
            }
        """)
        close_btn.mousePressEvent = lambda e: self.close()
        btn.layout().addWidget(close_btn, 0, Qt.AlignmentFlag.AlignCenter)
        root.addWidget(btn)

    def set_theme(self, theme: str) -> None:
        """同步主题。"""
        from . import widgets as W
        W.THEME = theme
        self.setStyleSheet(f"""
            QDialog {{
                background: {pal()['panel']};
                border: 1px solid {pal()['border']};
                border-radius: 12px;
            }}
        """)


def show_about_dialog(parent=None) -> None:
    """显示关于对话框。"""
    dlg = AboutDialog(parent)
    dlg.exec()
