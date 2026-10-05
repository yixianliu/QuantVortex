"""二维码卡片组件（M6-02：尺寸 / hover / 放大 / 保存）。

独立抽出，供关于页（about_page）与其他需要展示二维码的场景复用。

设计要点：
    - **展示尺寸**：图像区固定正方形，逻辑尺寸按分辨率档位
      ``160×160``（compact）/ ``180×180``（standard）/ ``200×200``（wide）；
      卡片整体 ``minWidth=150, maxWidth=280``。
    - **高分屏**：``devicePixelRatio`` 感知——
      ``pixmap.setDevicePixelRatio(dpr)`` +
      ``scaled(size*dpr, KeepAspectRatio, SmoothTransformation)``。
    - **白底衬**：二维码在深色主题下必须白底（padding 10px，圆角 14px），
      否则扫码识别率骤降。
    - **hover**：自绘 1px accent 描边 + 卡片上移 2px（**禁 QGraphicsEffect**，
      阴影在 ``paintEvent`` 里自己画，规避项目已知黑底 BUG）。
    - **点击放大**：``QrLightBox`` 模态浮层（420×420 大图 + 文案 + 保存按钮，
      Esc / 点击遮罩关闭）。
    - **右键菜单**：复制图片 / 保存图片到…
    - **加载失败**：虚线框占位 + 相对路径提示 + 「打开目录」按钮。

硬约束（项目规范）：
    - 纯 QPainter 自绘，禁止 QGraphicsEffect；
    - 所有 ``paintEvent`` 走 :func:`~.states.paint_guard` 装饰器；
    - hover 位移受 :data:`~.states.MOTION` 门控（REDUCED_MOTION 时不上移）；
    - 色值一律走 ``pal()`` token，零硬编码。
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QSize, QPoint
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QPixmap, QImage, QAction, QCursor,
)
from PyQt6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
    QMenu, QFileDialog, QApplication, QPushButton, QDialog,
)

from .widgets import pal
from .states import MOTION, paint_guard
from .responsive_layout import get_layout_manager

__all__ = ["QRCard", "QrLightBox", "QR_SIZE_BY_CLASS"]

#: 各分辨率档位的二维码逻辑边长（px）
QR_SIZE_BY_CLASS = {"compact": 160, "standard": 180, "wide": 200}

#: 白底衬内边距（二维码四周留白，保证扫码识别率）
_QR_PAD = 10
#: 卡片圆角
_CARD_RADIUS = 14
#: hover 时卡片上移距离（px）
_HOVER_LIFT = 2


def _alpha(hex_color: str, a: int) -> str:
    """token 色派生半透明 rgba 串。"""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a / 255.0:.3f})"


def _font(size: int, bold: bool = False) -> QFont:
    """统一字体构造（跨平台 CJK 可用）。"""
    return QFont("Microsoft YaHei", size,
                 QFont.Weight.Bold if bold else QFont.Weight.Normal)


def _qr_logical_size() -> int:
    """按当前分辨率档位返回二维码逻辑边长。"""
    try:
        lm = get_layout_manager()
        cls = getattr(lm, "_resolution_class", "standard")
        return QR_SIZE_BY_CLASS.get(cls, 180)
    except Exception:  # noqa: BLE001
        return 180


class QRCard(QFrame):
    """二维码卡片：白底圆角二维码 + 主/副标题 + hover + 点击放大 + 右键存图。

    参数:
        title: 主标题（如「添加 QQ 好友」）
        subtitle: 副标题（如「QQ：1153602036」）
        img_path: 二维码图片绝对路径
        accent: 强调色 token 键（默认 ``"accent"``）
        caption: 底部引导文案（可选）
        action_hint: 交互提示（如「点击放大」，可选）
    """

    def __init__(self, title: str, subtitle: str = "", img_path: str = "",
                 accent: str = "accent", caption: str = "",
                 action_hint: str = "点击放大", parent: Optional[QWidget] = None
                 ) -> None:
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._img_path = img_path
        self._accent = accent
        self._caption = caption
        self._action_hint = action_hint
        self._pixmap: Optional[QPixmap] = None
        self._hover = False

        self.setMinimumWidth(150)
        self.setMaximumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        # M6-06③：二维码卡可键盘聚焦 + Enter/空格激活（放大）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"二维码卡片：{title}")
        self.setAccessibleDescription(
            f"{subtitle}。{action_hint}；右键可复制图片或保存到本地。")
        self.setToolTip(action_hint or "点击放大")

        self._load_pixmap()
        self._build()
        self._retheme()

    # ------------------------------------------------------------------ 资源
    def _load_pixmap(self) -> None:
        """加载图片（文件系统优先，失败则留空由 paintEvent 画占位）。"""
        if self._img_path and os.path.isfile(self._img_path):
            px = QPixmap(self._img_path)
            if not px.isNull():
                self._pixmap = px

    def _build(self) -> None:
        """构建卡片内部布局（图片区 + 标题 + 副标题 + 引导文案）。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(6)

        # 图片区：正方形，逻辑尺寸按档位
        side = _qr_logical_size()
        self._img_host = QWidget()
        self._img_host.setFixedSize(side + _QR_PAD * 2, side + _QR_PAD * 2)
        self._img_host.setSizePolicy(QSizePolicy.Policy.Fixed,
                                     QSizePolicy.Policy.Fixed)
        root.addWidget(self._img_host, 0, Qt.AlignmentFlag.AlignCenter)

        self._title_lbl = QLabel(self._title)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setFont(_font(12, bold=True))
        root.addWidget(self._title_lbl)

        if self._subtitle:
            self._sub_lbl = QLabel(self._subtitle)
            self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._sub_lbl.setFont(_font(10))
            self._sub_lbl.setWordWrap(True)
            root.addWidget(self._sub_lbl)
        else:
            self._sub_lbl = None

        if self._caption:
            self._cap_lbl = QLabel(self._caption)
            self._cap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cap_lbl.setFont(_font(9))
            self._cap_lbl.setWordWrap(True)
            root.addWidget(self._cap_lbl)
        else:
            self._cap_lbl = None

    # ------------------------------------------------------------------ 主题
    def _retheme(self) -> None:
        """随主题刷新（token 色，零硬编码）。"""
        p = pal()
        col = p.get(self._accent, p["accent"])
        self.setStyleSheet(
            f"QRCard{{background:{_alpha(col, 16)};"
            f"border:1px solid {_alpha(col, 80)};"
            f"border-radius:{_CARD_RADIUS}px;}}")
        self._title_lbl.setStyleSheet(f"color:{p['text']};")
        if self._sub_lbl is not None:
            self._sub_lbl.setStyleSheet(f"color:{col};")
        if self._cap_lbl is not None:
            self._cap_lbl.setStyleSheet(f"color:{p['sub']};")

    def retheme(self) -> None:
        """对外主题刷新入口（供父级统一调用）。"""
        self._retheme()
        self.update()

    # ------------------------------------------------------------------ 交互
    def enterEvent(self, event) -> None:  # noqa: N802
        """进入：置 hover 态（上移受 MOTION 门控）。"""
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        """离开：清 hover 态。"""
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        """键盘聚焦时复用 hover 视觉（M6-06③：让焦点位置可见）。"""
        self._hover = True
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        """失焦还原。"""
        self._hover = False
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """M6-06③：Enter / 空格（含小键盘 Enter）激活放大。"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                           Qt.Key.Key_Space):
            self._open_lightbox()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """左键点击放大；右键弹出菜单。"""
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_lightbox()
            return
        super().mousePressEvent(event)

    def _show_context_menu(self, global_pos: QPoint) -> None:
        """右键菜单：复制图片 / 保存图片到…"""
        menu = QMenu(self)
        copy_act = QAction("复制图片", self)
        copy_act.triggered.connect(self._copy_image)
        save_act = QAction("保存图片到…", self)
        save_act.triggered.connect(self._save_image_as)
        menu.addAction(copy_act)
        menu.addAction(save_act)
        has_img = self._pixmap is not None and not self._pixmap.isNull()
        copy_act.setEnabled(has_img)
        save_act.setEnabled(has_img)
        menu.exec(global_pos)

    def _copy_image(self) -> None:
        """复制二维码图片到剪贴板。"""
        if self._pixmap is None:
            return
        QApplication.clipboard().setPixmap(self._pixmap)

    def _save_image_as(self) -> None:
        """保存二维码图片到指定路径。"""
        if self._pixmap is None:
            return
        default = os.path.basename(self._img_path) or "qrcode.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存二维码图片", default, "PNG 图片 (*.png)")
        if path:
            self._pixmap.save(path, "PNG")

    def _open_lightbox(self) -> None:
        """打开放大灯箱（无图时仍弹出，展示占位与路径提示）。"""
        box = QrLightBox(title=self._title, subtitle=self._subtitle,
                         img_path=self._img_path, accent=self._accent,
                         pixmap=self._pixmap, parent=self)
        box.exec()

    def _open_image_dir(self) -> None:
        """打开图片所在目录（占位态的「打开目录」按钮）。"""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        d = os.path.dirname(self._img_path) if self._img_path else ""
        if d and os.path.isdir(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    # ------------------------------------------------------------------ 绘制
    @paint_guard
    def paintEvent(self, event) -> None:  # noqa: N802
        """自绘：hover 描边 + 上移 + 白底二维码 + 失败占位。

        禁用 QGraphicsEffect，阴影/描边全部手绘，规避黑底 BUG。
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = pal()
        col = QColor(c.get(self._accent, c["accent"]))

        # hover：整体上移 2px（MOTION 关闭时不位移，仅描边）
        lift = _HOVER_LIFT if (self._hover and MOTION) else 0
        card_rect = self.rect().adjusted(0, -lift, 0, -lift)

        # 卡片底（hover 时底色加深）
        base_a = 40 if self._hover else 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_alpha(c.get(self._accent, c["accent"]), base_a)))
        p.drawRoundedRect(QRectF(card_rect), _CARD_RADIUS, _CARD_RADIUS)

        # hover 描边：1px accent
        if self._hover:
            p.setPen(QPen(col, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(card_rect).adjusted(
                0.5, 0.5, -0.5, -0.5), _CARD_RADIUS, _CARD_RADIUS)

        self._draw_qr(p, lift)
        p.end()

    def _draw_qr(self, p: QPainter, lift: int) -> None:
        """绘制白底二维码区（或失败占位）。"""
        host = self._img_host
        # 图片区在卡片坐标系中的位置（随 hover 上移）
        geo = host.geometry()
        rect = QRect(geo.x(), geo.y() - lift, geo.width(), geo.height())
        c = pal()

        # 白底圆角衬（深色主题下必须白底）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(rect), _CARD_RADIUS, _CARD_RADIUS)

        inner = rect.adjusted(_QR_PAD, _QR_PAD, -_QR_PAD, -_QR_PAD)
        if self._pixmap is not None and not self._pixmap.isNull():
            dpr = self.devicePixelRatioF() or 1.0
            pm = self._pixmap
            pm.setDevicePixelRatio(dpr)
            scaled = pm.scaled(
                int(inner.width() * dpr), int(inner.height() * dpr),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            sx = inner.x() + (inner.width() - scaled.width() / dpr) // 2
            sy = inner.y() + (inner.height() - scaled.height() / dpr) // 2
            p.drawPixmap(int(sx), int(sy), scaled)
        else:
            # 失败占位：虚线框 + 相对路径 + 提示
            p.setPen(QPen(QColor(c["border"]), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(inner), 8, 8)
            p.setPen(QColor(c["sub"]))
            p.setFont(_font(9))
            rel = self._img_path or "(未指定)"
            try:
                rel = os.path.relpath(self._img_path)
            except Exception:  # noqa: BLE001
                pass
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter,
                       f"图片未找到\n{rel}")

    def sizeHint(self) -> QSize:  # noqa: N802
        """建议尺寸（供布局计算，不用 setFixedHeight 避免递归）。"""
        side = _qr_logical_size() + _QR_PAD * 2
        extra = 12 * 2 + 6 * 3 + 20  # 外边距 + 间距 + 标题行
        if self._sub_lbl is not None:
            extra += 18
        if self._cap_lbl is not None:
            extra += 32
        return QSize(min(280, side + 24), side + extra)


class QrLightBox(QDialog):
    """二维码放大灯箱（M6-02④）：420×420 大图 + 文案 + 保存按钮。

    模态浮层，Esc 或点击遮罩关闭。
    """

    #: 大图尺寸
    BIG = 420

    def __init__(self, title: str, subtitle: str = "", img_path: str = "",
                 accent: str = "accent", pixmap: Optional[QPixmap] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._img_path = img_path
        self._pixmap = pixmap
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(460, 560)
        self._build(subtitle, accent)

    def _build(self, subtitle: str, accent: str) -> None:
        """构建灯箱内容。"""
        p = pal()
        col = p.get(accent, p["accent"])
        self.setStyleSheet(f"QrLightBox{{background:{p['panel']};}}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        t = QLabel(self._title)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setFont(_font(16, bold=True))
        t.setStyleSheet(f"color:{col};")
        root.addWidget(t)

        if subtitle:
            s = QLabel(subtitle)
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s.setFont(_font(11))
            s.setStyleSheet(f"color:{p['sub']};")
            root.addWidget(s)

        # 白底大图
        img_host = QLabel()
        img_host.setFixedSize(self.BIG, self.BIG)
        img_host.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_host.setStyleSheet(
            "background:#ffffff;border-radius:14px;")
        if self._pixmap is not None and not self._pixmap.isNull():
            img_host.setPixmap(self._pixmap.scaled(
                self.BIG - 20, self.BIG - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            img_host.setText("图片未找到")
            img_host.setStyleSheet(
                f"background:#ffffff;border-radius:14px;color:{p['sub']};")
        root.addWidget(img_host, 0, Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("按 Esc 或点击空白处关闭")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(_font(9))
        hint.setStyleSheet(f"color:{p['sub']};")
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        save_btn = QPushButton("保存图片")
        save_btn.setObjectName("primary")
        save_btn.setAccessibleName("保存二维码图片")
        save_btn.clicked.connect(self._save)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _save(self) -> None:
        """保存大图到本地。"""
        if self._pixmap is None:
            return
        default = os.path.basename(self._img_path) or "qrcode.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存二维码图片", default, "PNG 图片 (*.png)")
        if path:
            self._pixmap.save(path, "PNG")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Esc 关闭。"""
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """点击图片外的空白区域关闭（遮罩语义）。"""
        child = self.childAt(event.position().toPoint())
        if child is None:
            self.accept()
            return
        super().mousePressEvent(event)
