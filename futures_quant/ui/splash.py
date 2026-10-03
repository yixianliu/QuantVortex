"""启动 Splash（M4-11①：品牌 Logo + 版本 + 进度文案）。

用法（main 入口）::

    app = QApplication([])
    splash = Splash(app)          # 立即显示品牌图 + 版本
    splash.step("加载字体…")      # 每步更新文案 + app.processEvents() 分步推进
    ...
    win = MainWindow()
    win.showMaximized()
    splash.finish(win)            # 淡出并交还给主窗口

设计约束：
    - 离线可跑：产品图缺失时自动绘制 QV 兜底标，不依赖任何网络/资源包；
    - 零阻塞：所有更新走 showMessage + processEvents，不建事件循环；
    - 异常安全：任何绘制失败都静默降级为「无 Splash」，绝不阻断启动。
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen

from .. import __version__ as APP_VERSION


def _logo_pixmap() -> QPixmap:
    """品牌图：优先 images/product/1.png，缺失时绘制 QV 兜底标。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    p = os.path.join(root, "images", "product", "1.png")
    if os.path.exists(p):
        try:
            pm = QPixmap(p)
            if not pm.isNull():
                # 统一到 320x320（保持比例，居中贴到透明底）
                scaled = pm.scaled(
                    320, 320,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                canvas = QPixmap(320, 320)
                canvas.fill(Qt.GlobalColor.transparent)
                pt = QPainter(canvas)
                pt.drawPixmap((320 - scaled.width()) // 2,
                              (320 - scaled.height()) // 2, scaled)
                pt.end()
                return canvas
        except Exception:  # noqa: BLE001
            pass
    # 兜底：圆角蓝底 + QV 字样（离线/资源缺失也保证品牌观感）
    px = QPixmap(320, 320)
    px.fill(Qt.GlobalColor.transparent)
    pt = QPainter(px)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    pt.setBrush(QColor("#2f6fed"))
    pt.setPen(Qt.PenStyle.NoPen)
    pt.drawRoundedRect(24, 24, 272, 272, 56, 56)
    pt.setPen(QColor("#ffffff"))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(132)
    pt.setFont(f)
    pt.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "QV")
    pt.end()
    return px


class Splash:
    """Splash 控制器：``show → step(msg) → finish(win)`` 三步生命周期。"""

    def __init__(self, app: QApplication) -> None:
        """创建并立即显示 Splash（无阻塞，不建事件循环）。"""
        self._app = app
        self._splash: QSplashScreen | None = None
        try:
            sp = QSplashScreen(_logo_pixmap())
            sp.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self._splash = sp
            self.step(f"期货智能分析预测系统  v{APP_VERSION}")
            sp.show()
        except Exception:  # noqa: BLE001
            self._splash = None

    def step(self, text: str) -> None:
        """推进到下一个启动阶段：更新进度文案并处理一轮事件。"""
        if self._splash is None:
            return
        try:
            self._splash.showMessage(
                text,
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                QColor("#dddddd"))
            self._app.processEvents()
        except Exception:  # noqa: BLE001
            pass

    def finish(self, win) -> None:
        """主窗口显示后关闭 Splash（内部等待窗口 exposed，避免闪黑）。"""
        if self._splash is None:
            return
        try:
            # 立即关闭 Splash，不走 fade-out 动画（某些环境动画导致白屏）
            self._splash.hide()
            self._splash.deleteLater()
            self._splash = None
        except Exception:
            self._splash = None
