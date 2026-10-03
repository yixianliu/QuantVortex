"""关于对话框（M6-05 视觉层次与主题化版）。

五段式信息架构：
    ① Hero：品牌头像（104px 渐变 + QV）+ 产品名 + slogan + 版本 Pill（胶囊标签）
    ② 功能亮点：功能 chip 横排（AI 多模型预测 / GA 策略自进化 / 13 源消息面 / 单机离线）
    ③ 联系开发者：信息行（图标 + 标签 + 值 + 复制按钮），hover 高亮，✓ 动效
    ④ 二维码双组：带图标分区标题（🤝 添加我好友 / ☕ 支付打赏）+ 网格卡片
    ⑤ 页脚：免责声明（警告卡片，warning 左边框）+ 版权行 + 「系统诊断」「检查更新」

主题化约定（M4-04 / M6-05）：
    - 全部色值走 ``pal()`` / ``design_tokens(theme)``，**零硬编码色**；
      半透明色由 token 经 :func:`_alpha` 派生；
    - ``set_theme(t)`` 覆盖全部子控件（Hero/chip/信息行/分区标题/页脚），
      **不再反向写全局 ``W.THEME``**（主题唯一生效路径是全局 QSS + apply_design）；
    - 每个自绘控件在 ``paintEvent`` 里实时读 ``pal()``，天然随主题刷新。
"""
from __future__ import annotations

import os
from typing import List, Optional

from PyQt6 import QtCore
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QLinearGradient, QBrush, QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QWidget,
    QApplication, QSizePolicy, QScrollArea, QFrame, QMessageBox,
)

from .widgets import pal, THEME, FlowLayout
from .qr_card import QRCard
from .responsive_layout import get_layout_manager
from .. import __version__ as __app_version__, __release_date__ as __app_release_date__

# 二维码图片路径
from ..runtime import get_images_dir
_QRCODE_LINK_DIR = os.path.join(get_images_dir(), "link_qrcode")
_QRCODE_PAY_DIR = os.path.join(get_images_dir(), "pay_qrcode")

# 添加好友二维码
_QR_LINK_QQ = os.path.join(_QRCODE_LINK_DIR, "qq.png")
_QR_LINK_WX = os.path.join(_QRCODE_LINK_DIR, "wx.png")

# 支付二维码
_QR_PAY_ALI = os.path.join(_QRCODE_PAY_DIR, "ali-pay.png")
_QR_PAY_WX = os.path.join(_QRCODE_PAY_DIR, "wx-pay.png")


def _alpha(hex_color: str, a: int) -> str:
    """token 色派生半透明 rgba 串（替代硬编码 rgba(...)）。"""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a / 255.0:.3f})"


def _font(size: int, bold: bool = False) -> QFont:
    """统一字体构造（保证跨平台 CJK 可用）。

    M6-04①：字号经 ``layout_manager.font_size()`` 响应式缩放（三档钳制）。
    """
    try:
        size = get_layout_manager().font_size(size)
    except Exception:  # noqa: BLE001
        pass
    return QFont('Microsoft YaHei', size,
                 QFont.Weight.Bold if bold else QFont.Weight.Normal)


def _scaled(px: int) -> int:
    """M6-04①：间距 / 尺寸按 ``layout_manager.scale`` 缩放。"""
    try:
        return max(1, int(px * get_layout_manager().scale))
    except Exception:  # noqa: BLE001
        return px


class _BrandAvatar(QWidget):
    """品牌头像：渐变圆形 + QV 文字标识（M6-05①：88→104px）。"""

    def __init__(self, size: int = 104) -> None:
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = pal()
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor(c['accent']))
        grad.setColorAt(1, QColor(c['accent2']))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        r = int(self._size * 0.45)
        cx, cy = self.width() // 2, self.height() // 2
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        p.setPen(QPen(QColor('#ffffff'), 2))
        p.setFont(QFont('Microsoft YaHei', int(self._size * 0.28),
                        QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'QV')
        p.end()


class _VersionPill(QLabel):
    """版本 Pill（M6-05①）：accent 描边胶囊标签。"""

    def __init__(self) -> None:
        super().__init__(f"v{__app_version__} · {__app_release_date__}")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retheme()

    def retheme(self) -> None:
        """随主题刷新（token：accent 描边 + accent 文字）。"""
        p = pal()
        self.setFont(_font(10, bold=True))
        self.setStyleSheet(
            f"color:{p['accent']};border:1px solid {p['accent']};"
            f"border-radius:12px;padding:3px 14px;"
            f"background:{_alpha(p['accent'], 26)};")


class _FeatureChip(QLabel):
    """功能亮点 chip（M6-05②）：圆角小胶囊。"""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.retheme()

    def retheme(self) -> None:
        """随主题刷新（token：card 底 + border 描边 + sub 文字）。"""
        p = pal()
        self.setFont(_font(11))
        self.setStyleSheet(
            f"color:{p['text']};background:{p['card']};"
            f"border:1px solid {p['border']};border-radius:11px;"
            f"padding:4px 12px;")


class _CopyButton(QLabel):
    """复制按钮（M6-03⑤）：点击复制，✓ 动效 1.2s 后复原。"""

    def __init__(self, get_text, accessible: str) -> None:
        super().__init__("复制")
        # 兼容两种入参：可调用对象（动态取值）或普通字符串（_InfoRow 直接传值）。
        # 历史上 _InfoRow 传的是字符串而 _do_copy 按 callable 调用，
        # 导致鼠标点击复制静默抛 TypeError —— 复制功能实际不可用。
        self._get_text = (get_text if callable(get_text)
                          else (lambda: str(get_text)))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._restore)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # M6-06③：复制按钮可键盘聚焦 + Enter/空格激活
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # M6-06④：accessibleName 形如「复制QQ号」
        self.setAccessibleName(
            accessible if accessible.endswith("号") else f"复制{accessible}号")
        self.setAccessibleDescription("复制该联系方式到剪贴板")
        self.retheme()

    def retheme(self) -> None:
        """随主题刷新。"""
        p = pal()
        self.setFont(_font(10))
        self.setStyleSheet(
            f"color:{p['accent']};background:{_alpha(p['accent'], 30)};"
            f"border:1px solid {_alpha(p['accent'], 90)};"
            f"border-radius:9px;padding:2px 10px;")

    def _restore(self) -> None:
        """动效结束：文案与配色复原。"""
        self.setText("复制")
        self.retheme()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._do_copy()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """M6-06③：复制按钮可键盘激活（Enter / 空格）。"""
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._do_copy()
            e.accept()
            return
        super().keyPressEvent(e)

    def _do_copy(self) -> None:
        """M6-06⑤：复制 → 剪贴板 + 文案「已复制 ✓」 + QToolTip 提示，1.2s 复原。"""
        text = self._get_text()
        QApplication.clipboard().setText(text)
        p = pal()
        self.setText("已复制 ✓")
        self.setStyleSheet(
            f"color:{p['down']};background:{_alpha(p['down'], 40)};"
            f"border:1px solid {p['down']};border-radius:9px;padding:2px 10px;")
        # ⑤：QToolTip 即时反馈（全局坐标定位到按钮右下角）
        try:
            from PyQt6.QtWidgets import QToolTip
            pos = self.mapToGlobal(QtCore.QPoint(self.width(), self.height()))
            QToolTip.showText(pos, f"已复制：{text}", self, self.rect(), 1200)
        except Exception:  # noqa: BLE001
            pass
        self._timer.start(1200)


class _InfoRow(QWidget):
    """信息行（M6-05③）：图标 + 标签 + 值 + 复制按钮，hover 高亮，全 token。"""

    def __init__(self, icon: str, label: str, value: str,
                 copy_text: str = "") -> None:
        super().__init__()
        self._copy_text = copy_text or value
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFont(_font(15))
        self._icon_lbl.setFixedWidth(26)
        layout.addWidget(self._icon_lbl)

        self._label_widget = QLabel(label)
        self._label_widget.setFont(_font(11))
        self._label_widget.setFixedWidth(64)
        layout.addWidget(self._label_widget)

        self._value_widget = QLabel(value)
        self._value_widget.setFont(_font(12, bold=True))
        # M6-04③：值列必须可收缩——否则长值（如手机号）把整行 minimumSizeHint
        # 顶到 371px，两列合计 750px，窄屏下内容横向溢出且横向滚动条被关闭。
        self._value_widget.setMinimumWidth(0)
        self._value_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._value_widget, 1)

        self._copy_btn = _CopyButton(self._copy_text, label)
        layout.addWidget(self._copy_btn)

        self.setAccessibleName(f"{label}信息行")
        self.setToolTip("点击「复制」按钮复制到剪贴板")
        self.retheme()

    def retheme(self) -> None:
        """随主题刷新（token：card 底 + border 描边 + accent 图标/值）。"""
        p = pal()
        self._icon_lbl.setStyleSheet(f"color:{p['accent']};")
        self._label_widget.setStyleSheet(f"color:{p['sub']};")
        self._value_widget.setStyleSheet(f"color:{p['text']};")
        self._copy_btn.retheme()
        self.setObjectName("info-row")
        self.setStyleSheet(
            f"QWidget#info-row{{background:{p['card']};"
            f"border:1px solid {p['border']};border-radius:10px;}}"
            f"QWidget#info-row:hover{{border:1px solid {p['accent']};}}")


class _InfoGrid(QWidget):
    """联系方式网格（M6-04③）：双列 ↔ 单列自适应，与二维码网格同规则。"""

    TWO_COL_MIN_W = 520

    def __init__(self, rows: List[tuple]) -> None:
        super().__init__()
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(_scaled(10))
        self._rows: List[_InfoRow] = []
        for icon, label, value, copy_text in rows:
            row = _InfoRow(icon, label, value, copy_text)
            self._rows.append(row)
        self._relayout()

    def _relayout(self) -> None:
        """按可用宽度决定 2 列 / 1 列并重排。"""
        avail = self.width() or self.TWO_COL_MIN_W
        cols = 2 if avail >= self.TWO_COL_MIN_W else 1
        # 同 _QRSection：只 takeAt，不 setParent(None)，保住 Tab 焦点链
        while self._grid.count():
            self._grid.takeAt(0)
        for i, row in enumerate(self._rows):
            r, c = divmod(i, cols)
            self._grid.addWidget(row, r, c)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1 if cols == 2 else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """宽度变化时重算列数。"""
        if event.oldSize().width() != event.size().width() and self._rows:
            self._relayout()
        super().resizeEvent(event)

    def retheme(self) -> None:
        """随主题刷新。"""
        for r in self._rows:
            r.retheme()


class _SectionTitle(QWidget):
    """分区标题（M6-05④）：图标 + 文字 + token 分隔线（QFrame[HLine]）。"""

    def __init__(self, text: str, icon_char: str = "",
                 token_key: str = "accent") -> None:
        super().__init__()
        self._token_key = token_key
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._icon_lbl = QLabel(icon_char)
        self._icon_lbl.setFont(_font(14))
        layout.addWidget(self._icon_lbl)

        self._title = QLabel(text)
        self._title.setFont(_font(13, bold=True))
        layout.addWidget(self._title)

        # M4-05④：分隔线用 QFrame[HLine] + token 色
        self._line = QFrame()
        self._line.setFrameShape(QFrame.Shape.HLine)
        self._line.setFixedHeight(1)
        layout.addWidget(self._line, 1)
        self.retheme()

    def retheme(self) -> None:
        """随主题刷新（token 色标题 + 半透明分隔线）。"""
        p = pal()
        col = p.get(self._token_key, p["accent"])
        self._icon_lbl.setStyleSheet(f"color:{col};")
        self._title.setStyleSheet(f"color:{col};")
        self._line.setStyleSheet(
            f"background:{_alpha(col, 90)};border:none;")


class _QRCard(QWidget):
    """二维码卡片容器（M6-02：委托到独立 ``QRCard`` 组件）。

    保留旧的 ``label/img_path/token_key`` 构造签名，内部改用
    :class:`~.qr_card.QRCard`（hover / 点击放大 / 右键存图 / DPR 感知 / 白底）。
    """

    def __init__(self, label: str, img_path: str,
                 token_key: str = "accent",
                 min_width: int = 120, max_width: int = 200,
                 subtitle: str = "", caption: str = "") -> None:
        super().__init__()
        self._label = label
        self._img_path = img_path
        self._token_key = token_key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._card = QRCard(
            title=label, subtitle=subtitle, img_path=img_path,
            accent=token_key, caption=caption, action_hint="点击放大")
        self._card.setMinimumWidth(max(150, min_width))
        self._card.setMaximumWidth(max(200, max_width))
        layout.addWidget(self._card, 0, Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"二维码：{label}")

    def retheme(self) -> None:
        """随主题刷新（委托内部卡片）。"""
        self._card.retheme()


class _QRSection(QWidget):
    """二维码区域：分区标题 + 响应式网格卡片（M6-04②：双列 ↔ 单列）。

    列数由可用宽度决定：``is_wide_screen()`` 或宽度 ≥ ``TWO_COL_MIN_W``(620)
    → 双列；否则单列（卡片居中，宽度 ``min(280, avail-32)``）。
    重排只改 grid 位置与卡片最大宽度，**不调 setFixedHeight**（M6-04④，
    高度交给 ``sizeHint`` + ``QSizePolicy``，避免递归）。
    """

    #: 双列所需的最小可用宽度（px）
    TWO_COL_MIN_W = 620
    #: 单列时卡片最大宽度
    SINGLE_MAX_W = 280

    def __init__(self, title: str, icon_char: str, cards_data: List[dict],
                 token_key: str = "accent") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_scaled(12))

        self._title = _SectionTitle(title, icon_char, token_key)
        layout.addWidget(self._title)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(8, 0, 8, 0)
        self._grid.setSpacing(_scaled(16))
        self._cards: List[_QRCard] = []
        for card_info in cards_data:
            card = _QRCard(
                label=card_info["label"],
                img_path=card_info["path"],
                token_key=card_info.get("token", token_key),
                min_width=card_info.get("min_width", 130),
                max_width=card_info.get("max_width", 220),
                # M6-03①：四段式结构 —— 副标题 + 引导文案
                subtitle=card_info.get("subtitle", ""),
                caption=card_info.get("caption", ""),
            )
            self._cards.append(card)
        layout.addLayout(self._grid)
        self._relayout()

    # ------------------------------------------------------------------ 响应式
    def _columns_for(self, avail_w: int) -> int:
        """按可用宽度决定列数（2 或 1）。"""
        try:
            wide = get_layout_manager().is_wide_screen()
        except Exception:  # noqa: BLE001
            wide = True
        return 2 if (wide and avail_w >= self.TWO_COL_MIN_W) else 1

    def _relayout(self) -> None:
        """重排卡片：按当前可用宽度设置列数与卡片宽度上限。"""
        avail = self.width() or self.parent().width() if self.parent() else 0
        if not avail:
            avail = self.TWO_COL_MIN_W  # 未布局时按双列排
        cols = self._columns_for(avail)

        # 清出 grid：只 takeAt，**不做 setParent(None)**——
        # 解除父子关系会重置 Tab 焦点链（M6-06② 的坑），响应式重排后
        # 焦点顺序会退回创建顺序。保持父子关系即可安全重排。
        while self._grid.count():
            self._grid.takeAt(0)

        for i, card in enumerate(self._cards):
            r, c = divmod(i, cols)
            self._grid.addWidget(card, r, c,
                                 Qt.AlignmentFlag.AlignCenter)

        # 单列时卡片居中且限宽 min(280, avail-32)
        if cols == 1:
            max_w = max(150, min(self.SINGLE_MAX_W, avail - 32))
            for card in self._cards:
                card.setMaximumWidth(max_w)
                card._card.setMaximumWidth(max_w)
        else:
            for card in self._cards:
                card.setMaximumWidth(280)
                card._card.setMaximumWidth(280)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1 if cols == 2 else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """宽度变化时重算列数（M6-04②：2 → 1 自动切换）。"""
        old_w = event.oldSize().width()
        new_w = event.size().width()
        if old_w != new_w and self._cards:
            self._relayout()
        super().resizeEvent(event)

    def retheme(self) -> None:
        """随主题刷新。"""
        self._title.retheme()
        for c in self._cards:
            c.retheme()


class AboutDialog(QDialog):
    """专业版关于对话框（五段式信息架构）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 QuantVortex")
        self.setModal(True)
        self._apply_responsive_size()
        self._themables: List[object] = []   # 具备 retheme() 的子控件
        self._build()
        self._apply_theme()

    def _apply_responsive_size(self) -> None:
        """M6-04①：对话框三档尺寸（min / default / max），按屏幕缩放。

        - min     = 480 × 560
        - default = min(680, 屏宽*0.6) × min(760, 屏高*0.85)
        - max     = 880 × 900
        """
        try:
            lm = get_layout_manager()
            sw, sh = lm.width, lm.height
        except Exception:  # noqa: BLE001
            sw, sh = 1920, 1080
        self.setMinimumSize(480, 560)
        self.setMaximumSize(880, 900)
        self.resize(min(680, int(sw * 0.6)), min(760, int(sh * 0.85)))

    # ------------------------------------------------------------------
    def _build(self) -> None:
        """构建五段式布局。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(content)
        # M6-04①：间距经 layout_manager.scale 缩放
        root.setContentsMargins(_scaled(28), _scaled(24),
                                _scaled(28), _scaled(20))
        root.setSpacing(_scaled(16))

        # ===== ① Hero =====
        hero = QVBoxLayout()
        hero.setSpacing(8)
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar = _BrandAvatar(104)
        self._themables.append(avatar)
        hero.addWidget(avatar, 0, Qt.AlignmentFlag.AlignCenter)

        title = QLabel("QuantVortex")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(_font(24, bold=True))
        self._title_lbl = title
        hero.addWidget(title)

        slogan = QLabel("期货智能分析预测系统")
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slogan.setFont(_font(13))
        self._slogan_lbl = slogan
        hero.addWidget(slogan)

        pill = _VersionPill()
        self._themables.append(pill)
        hero.addWidget(pill, 0, Qt.AlignmentFlag.AlignCenter)
        root.addLayout(hero)

        # ===== ② 功能亮点 chips =====
        # M6-04④：chips 改流式布局（自动换行）——原 QHBoxLayout 的
        # minimumSize 达 593px，直接把内容最小宽顶到 639px，窄屏横向溢出
        # 且横向滚动条被关闭（视觉截断）。
        chips_row = FlowLayout(spacing=_scaled(8))
        for text in ("AI 多模型预测", "GA 策略自进化", "13 源消息面", "单机离线"):
            chip = _FeatureChip(text)
            self._themables.append(chip)
            chips_row.addWidget(chip)
        root.addLayout(chips_row)

        # 分隔线（token）
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(self._sep)

        # ===== ③ 联系开发者 =====
        contact_title = _SectionTitle("联系开发者", "📬", "accent2")
        self._themables.append(contact_title)
        root.addWidget(contact_title)

        # M6-04③：联系方式行改响应式网格（双列 ↔ 单列）
        self._info_grid = _InfoGrid([
            ("💬", "QQ", "1153602036", "1153602036"),
            ("📱", "微信", "QV_Team", "QV_Team"),
            ("📞", "手机", "19258585274", "19258585274"),
            ("🏢", "工作室", "KP Studio", ""),
        ])
        self._themables.append(self._info_grid)
        root.addWidget(self._info_grid)

        # ===== ④ 二维码双组 =====
        link_section = _QRSection("添加我好友", "🤝", [
            {"label": "添加 QQ 好友", "path": _QR_LINK_QQ, "token": "down",
             "subtitle": "QQ：1153602036",
             "caption": "扫码或点击复制 QQ 号，申请时备注『QV』，"
                        "工作日 2 小时内通过"},
            {"label": "添加微信好友", "path": _QR_LINK_WX, "token": "accent2",
             "subtitle": "微信号：QV_Team",
             "caption": "扫码添加，可加入量化交流群，"
                        "获取版本更新与策略库共享"},
        ], token_key="down")
        self._themables.append(link_section)
        root.addWidget(link_section)

        pay_section = _QRSection("支付 / 打赏", "☕", [
            {"label": "支付宝打赏", "path": _QR_PAY_ALI, "token": "accent",
             "caption": "如果 QuantVortex 帮到了你，欢迎请作者喝杯咖啡 ☕。"
                        "打赏时请备注昵称，将列入「致谢名单」"},
            {"label": "微信打赏", "path": _QR_PAY_WX, "token": "warning",
             "caption": "金额随意，心意最重要。打赏后可私信获取进阶用法文档"},
        ], token_key="warning")
        self._themables.append(pay_section)
        root.addWidget(pay_section)

        # 组尾统一说明（M6-03④）
        pay_note = QLabel("打赏不构成任何服务承诺，软件功能与打赏无关")
        pay_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pay_note.setFont(_font(9))
        # M6-04：CJK 标签必须可收缩——否则其 sizeHint（315px）会成为内容最小宽，
        # 窄屏下对话框被顶宽、横向溢出（横向滚动条又被关闭）
        pay_note.setWordWrap(True)
        pay_note.setMinimumWidth(0)
        pay_note.setSizePolicy(QSizePolicy.Policy.Ignored,
                               QSizePolicy.Policy.Preferred)
        self._pay_note = pay_note
        root.addWidget(pay_note)

        # ===== ⑤ 页脚 =====
        self._disclaimer = QLabel(
            "⚠ 免责声明：本软件仅供学习研究与技术交流使用，不构成任何投资建议。\n"
            "期货交易存在杠杆风险，历史表现不代表未来收益，请谨慎决策、自担风险。")
        self._disclaimer.setWordWrap(True)
        self._disclaimer.setFont(_font(9))

        copyright_lbl = QLabel(
            f"© 2026 QuantVortex All Rights Reserved · v{__app_version__}")
        copyright_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_lbl.setFont(_font(9))
        # M6-04：同上，版权行 sizeHint 曾达 705px（撑宽内容），必须可收缩
        copyright_lbl.setWordWrap(True)
        copyright_lbl.setMinimumWidth(0)
        copyright_lbl.setSizePolicy(QSizePolicy.Policy.Ignored,
                                    QSizePolicy.Policy.Preferred)
        self._copyright_lbl = copyright_lbl

        # M6-06⑥：三个页脚按钮；按钮行改 FlowLayout（窄屏自动换行，避免溢出）
        btn_row = FlowLayout(spacing=_scaled(10))
        from PyQt6.QtWidgets import QPushButton
        self._diag_btn = QPushButton("系统诊断")
        self._diag_btn.setObjectName("secondary")
        self._diag_btn.setAccessibleName("系统诊断")
        self._diag_btn.clicked.connect(self._show_diagnostics)
        self._update_btn = QPushButton("检查更新")
        self._update_btn.setObjectName("secondary")
        self._update_btn.setAccessibleName("检查更新")
        self._update_btn.clicked.connect(self._check_update)
        self._copy_ver_btn = QPushButton("复制版本信息")
        self._copy_ver_btn.setObjectName("secondary")
        self._copy_ver_btn.setAccessibleName("复制版本信息")
        self._copy_ver_btn.setAccessibleDescription(
            "一键复制版本与环境信息，便于反馈问题")
        self._copy_ver_btn.clicked.connect(self._copy_version_info)
        btn_row.addWidget(self._diag_btn)
        btn_row.addWidget(self._update_btn)
        btn_row.addWidget(self._copy_ver_btn)

        root.addWidget(self._disclaimer)
        root.addWidget(copyright_lbl)
        root.addLayout(btn_row)
        root.addStretch(1)

        scroll.setWidget(content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        # M6-06②：Tab 焦点顺序 Hero → 信息行 → 二维码卡 → 页脚按钮
        self._setup_tab_order()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """宽度变化后重挂 Tab 顺序。

        M6-06② 关键坑：``_QRSection._relayout`` / ``_InfoGrid._relayout`` 会用
        ``setParent(None)`` 重新挂载卡片，**重挂载会重置 Tab 顺序**，
        导致响应式重排后焦点链退回创建顺序。故在布局稳定后（singleShot 0）
        重设一次。
        """
        super().resizeEvent(event)
        QTimer.singleShot(0, self._setup_tab_order)

    # ------------------------------------------------------------------
    def _setup_tab_order(self) -> None:
        """M6-06②：显式 setTabOrder，保证 Tab 遍历顺序符合视觉阅读顺序。

        顺序：信息行复制按钮 → 二维码卡 → 页脚按钮（Hero / 标题为非交互控件，
        不参与焦点链）。
        """
        chain = []
        # ① 信息行的复制按钮
        grid = getattr(self, "_info_grid", None)
        if grid is not None:
            chain.extend(r._copy_btn for r in grid._rows)
        # ② 二维码卡（按分区顺序）
        for sec in self.findChildren(_QRSection):
            for card in sec._cards:
                chain.append(card._card)
        # ③ 页脚按钮
        chain.extend([self._diag_btn, self._update_btn, self._copy_ver_btn])

        prev = None
        for widget in chain:
            if prev is not None:
                self.setTabOrder(prev, widget)
            prev = widget

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """M6-06①：Esc 关闭对话框（灯箱打开时不抢其 Esc）。"""
        if event.key() == Qt.Key.Key_Escape:
            # 若当前有模态灯箱，交给它处理（不重复关闭）
            if QApplication.activeModalWidget() not in (None, self):
                super().keyPressEvent(event)
                return
            self.reject()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    def _show_diagnostics(self) -> None:
        """系统诊断：汇总版本 / Python / Qt 环境信息。"""
        import sys as _sys
        from PyQt6.QtCore import QT_VERSION_STR
        info = (
            f"QuantVortex v{__app_version__} ({__app_release_date__})\n"
            f"Python {_sys.version.split()[0]}\n"
            f"PyQt6 / Qt {QT_VERSION_STR}\n"
            f"平台：{_sys.platform}")
        QMessageBox.information(self, "系统诊断", info)

    def _check_update(self) -> None:
        """检查更新（离线软件：提示当前已是最新，附版本号）。"""
        QMessageBox.information(
            self, "检查更新",
            f"当前版本 v{__app_version__}（{__app_release_date__}）已是最新。\n"
            "新版本请关注 QQ 群 / 微信公众号公告。")

    def version_info_text(self) -> str:
        """M6-06⑥：一键复制的版本 + 环境信息串。"""
        import sys as _sys
        from PyQt6.QtCore import QT_VERSION_STR
        return (f"QuantVortex v{__app_version__} ({__app_release_date__}) / "
                f"Python {_sys.version.split()[0]} / PyQt6 {QT_VERSION_STR}")

    def _copy_version_info(self) -> None:
        """复制版本信息到剪贴板，按钮文案临时变「已复制 ✓」（1.2s 复原）。"""
        text = self.version_info_text()
        QApplication.clipboard().setText(text)
        btn = self._copy_ver_btn
        btn.setText("已复制 ✓")
        try:
            from PyQt6.QtWidgets import QToolTip
            pos = btn.mapToGlobal(QtCore.QPoint(btn.width(), btn.height()))
            QToolTip.showText(pos, f"已复制：{text}", btn, btn.rect(), 1200)
        except Exception:  # noqa: BLE001
            pass
        QTimer.singleShot(1200, lambda: btn.setText("复制版本信息"))

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        """主题应用：对话框骨架 + 全部 themable 子控件（token 化）。"""
        p = pal()
        self._title_lbl.setStyleSheet(
            f"color:{p['text']};letter-spacing:1px;")
        self._slogan_lbl.setStyleSheet(
            f"color:{p['sub']};letter-spacing:0.5px;")
        self._sep.setStyleSheet(
            f"background:{p['border']};border:none;min-height:1px;")
        self._pay_note.setStyleSheet(f"color:{p['sub']};")
        self._disclaimer.setStyleSheet(
            f"color:{p['text']};background:{_alpha(p['warning'], 26)};"
            f"border:1px solid {_alpha(p['warning'], 100)};"
            f"border-left:4px solid {p['warning']};"
            f"border-radius:8px;padding:10px 12px;")
        self._copyright_lbl.setStyleSheet(f"color:{p['sub']};")
        self.setStyleSheet(f"""
            QDialog {{
                background: {p['panel']};
                border: 1px solid {p['border']};
                border-radius: 14px;
            }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 8px;
                border-radius: 4px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {p['border']}; border-radius: 4px; min-height: 40px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {p['accent']}; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        for t in self._themables:
            try:
                t.retheme()
            except Exception:  # noqa: BLE001
                continue

    def set_theme(self, theme: str) -> None:
        """同步主题（M6-05③：不再反向写全局 W.THEME）。

        全局 ``W.THEME`` 已由 ``apply_design`` 更新后才轮到本方法，
        这里只负责把新 token 刷到全部子控件。
        """
        self._apply_theme()


def show_about_dialog(parent=None) -> None:
    """显示关于对话框。"""
    dlg = AboutDialog(parent)
    dlg.exec()
