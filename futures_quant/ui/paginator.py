"""分页器组件（期货量化系统 UI）。

设计目标：
    - 支持 1k/5k/10k/自定义 四档分页；
    - 密度切换（紧凑/标准/宽松）并持久化；
    - 与 DataGrid 深度集成；
    - 纯 PyQt6 + QPainter，无第三方依赖。

使用方式：
    pager = Paginator(page_size=1000)
    pager.connect(grid, store)  # 绑定数据表和数据源
    pager.total_changed.connect(on_total_changed)
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QSpinBox, QComboBox,
    QHBoxLayout, QVBoxLayout, QSizePolicy,
)

from .widgets import PALETTE, THEME, pal, _responsive_font, _responsive_size
from .states import paint_guard


class Paginator(QFrame):
    """分页器：支持多档分页大小 + 密度切换 + 上一页/下一页/跳转。"""

    PAGE_SIZES = [1000, 2000, 5000, 10000, 0]  # 0 = 自定义

    SIGNALS = {
        "page_changed": pyqtSignal(int),
        "page_size_changed": pyqtSignal(int),
        "density_changed": pyqtSignal(str),
    }

    def __init__(self, page_size: int = 1000, density: str = "standard",
                 theme: Optional[str] = None) -> None:
        super().__init__()
        self.setObjectName("paginator")
        self._theme = THEME if theme is None else theme
        self._total = 0
        self._page = 1
        self._page_size = page_size
        self._density = density
        self._custom_size = 0

        # 信号
        self.page_changed = self.SIGNALS["page_changed"]
        self.page_size_changed = self.SIGNALS["page_size_changed"]
        self.density_changed = self.SIGNALS["density_changed"]

        self._build()
        self._apply()

    def _build(self) -> None:
        """构建 UI。"""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(_responsive_size(8), _responsive_size(4), _responsive_size(8), _responsive_size(4))
        lay.setSpacing(_responsive_size(8))

        # 总行数
        self._total_lbl = QLabel("0 行")
        lay.addWidget(self._total_lbl)

        # 分页大小
        self._size_cb = QComboBox()
        for s in self.PAGE_SIZES[:-1]:
            self._size_cb.addItem(f"{s:,}")
        self._size_cb.addItem("自定义")
        idx = self._size_cb.findText(f"{self._page_size:,}")
        self._size_cb.setCurrentIndex(idx if idx >= 0 else 0)
        self._size_cb.currentIndexChanged.connect(self._on_size_changed)
        lay.addWidget(self._size_cb)

        # 自定义输入
        self._custom_sb = QSpinBox()
        self._custom_sb.setRange(1, 100000)
        self._custom_sb.setSuffix(" 行")
        self._custom_sb.setVisible(False)
        self._custom_sb.valueChanged.connect(self._on_custom_size)
        lay.addWidget(self._custom_sb)

        lay.addStretch(1)

        # 分页信息
        self._info_lbl = QLabel("1 / 1")
        lay.addWidget(self._info_lbl)

        # 上一页
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(28)
        self._prev_btn.clicked.connect(self._prev_page)
        lay.addWidget(self._prev_btn)

        # 下一页
        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(28)
        self._next_btn.clicked.connect(self._next_page)
        lay.addWidget(self._next_btn)

        # 跳转输入
        self._jump_sb = QSpinBox()
        self._jump_sb.setRange(1, 1)
        self._jump_sb.setSuffix(" / 1")
        self._jump_sb.valueChanged.connect(self._jump)
        lay.addWidget(self._jump_sb)

        # 密度切换
        self._density_cb = QComboBox()
        self._density_cb.addItem("紧凑", "compact")
        self._density_cb.addItem("标准", "standard")
        self._density_cb.addItem("宽松", "relaxed")
        idx = self._density_cb.findData(self._density)
        self._density_cb.setCurrentIndex(idx if idx >= 0 else 1)
        self._density_cb.currentIndexChanged.connect(self._on_density_changed)
        lay.addWidget(self._density_cb)

    def set_total(self, total: int) -> None:
        """设置总行数并重新计算页数。"""
        self._total = max(0, int(total))
        self.page_count = max(1, (self._total + self._page_size - 1) // self._page_size)
        if self._page > self.page_count:
            self._page = self.page_count
        self._update_info()

    def set_page(self, page: int) -> None:
        """设置当前页码。"""
        page = max(1, min(page, self.page_count))
        if page != self._page:
            self._page = page
            self._update_info()
            self.page_changed.emit(page)

    def next_page(self) -> None:
        self._next_page()

    def prev_page(self) -> None:
        self._prev_page()

    def _next_page(self) -> None:
        if self._page < self.page_count:
            self.set_page(self._page + 1)

    def _prev_page(self) -> None:
        if self._page > 1:
            self.set_page(self._page - 1)

    def _jump(self, page: int) -> None:
        self.set_page(page)

    def _on_size_changed(self, idx: int) -> None:
        text = self._size_cb.currentText()
        if text == "自定义":
            self._custom_sb.setVisible(True)
            self._custom_sb.setFocus()
        else:
            self._custom_sb.setVisible(False)
            self._page_size = int(text.replace(",", ""))
            self._update_info()
            self.page_size_changed.emit(self._page_size)

    def _on_custom_size(self, val: int) -> None:
        self._page_size = val
        self._update_info()
        self.page_size_changed.emit(self._page_size)

    def _on_density_changed(self, idx: int) -> None:
        self._density = self._density_cb.currentData()
        self._apply()
        self.density_changed.emit(self._density)

    def _update_info(self) -> None:
        """更新分页信息标签。"""
        self._total_lbl.setText(f"{self._total:,} 行")
        pc = max(1, (self._total + self._page_size - 1) // self._page_size) if self._total > 0 else 1
        self.page_count = pc
        self._info_lbl.setText(f"{self._page} / {pc}")
        self._jump_sb.setRange(1, pc)
        self._jump_sb.setValue(self._page)
        self._jump_sb.setSuffix(f" / {pc}")

    def set_theme(self, t: str) -> None:
        self._theme = t
        self._apply()

    def _apply(self) -> None:
        """应用主题样式。"""
        p = PALETTE[self._theme]
        token = design_tokens(self._theme)
        radius = token['radius_sm']
        btn_qss = f"QPushButton{{background:{p['card']};color:{p['text']};border:1px solid {p['border']};border-radius:{radius}px;padding:2px 8px;}}"
        for btn in (self._prev_btn, self._next_btn):
            btn.setStyleSheet(btn_qss)
            btn.setEnabled(self._page > 1 if btn is self._prev_btn else self._page < self.page_count)
        # 密度影响行高
        pad = {"compact": 2, "standard": 4, "relaxed": 8}.get(self._density, 4)
        self.setStyleSheet(
            f"QFrame#paginator{{background:{p['panel']};border:1px solid {p['border']};"
            f"border-radius:{token['radius_md']}px;padding:{pad}px {pad*2}px;}}"
            f"QLabel{{color:{p['sub']};font-size:{_responsive_font(11)}px;}}"
            f"QComboBox{{color:{p['text']};background:{p['card']};border:1px solid {p['border']};"
            f"border-radius:{radius}px;padding:1px 6px;font-size:{_responsive_font(11)}px;}}"
            f"QSpinBox{{color:{p['text']};background:{p['card']};border:1px solid {p['border']};"
            f"border-radius:{radius}px;padding:1px 4px;font-size:{_responsive_font(11)}px;}}")


# 延迟导入避免循环依赖
from .design_system import design_tokens  # noqa: E402
