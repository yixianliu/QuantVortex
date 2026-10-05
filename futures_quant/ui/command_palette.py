"""命令面板（M4-12①）：``Ctrl+K`` 唤起，页面 / 品种 / 命令模糊搜索。

交互约定：
    - 输入即过滤（子串 > 子序列两级打分），空查询展示全部条目；
    - ``↑``/``↓`` 在结果间移动，``Enter`` 执行选中项，``Esc`` 关闭（QDialog 默认）；
    - 鼠标单击 / 双击亦可执行；
    - 条目为 ``(label, category, callback)`` 三元组，label 需自带分类前缀
      （如「页面：回测中心」「品种：RB 螺纹钢」「命令：切换主题」），
      模糊匹配直接作用于 label，天然支持中文关键词（搜「回测」命中页面）。

零业务依赖：本模块不 import 任何页面/数据层，条目完全由调用方注入。
"""
from __future__ import annotations

from typing import Callable, Iterable, List, Tuple

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
)

# 条目类型：(显示文案, 分类, 动作)
PaletteItem = Tuple[str, str, Callable[[], None]]


def fuzzy_score(query: str, text: str) -> int:
    """「回测」级模糊打分：子串精确命中 > 子序列命中 > 不命中(0)。

    打分只用于排序，数值含义：
        - 子串命中：1000 - 首次出现位置*5 - 尾部长度（越靠前越紧凑分越高）；
        - 子序列命中：400 - 累计间隔（字符按顺序出现即可，间隔越小越高）；
        - 空查询：1（展示全部、保持注入顺序）。
    """
    if not query:
        return 1
    q, t = query.lower(), text.lower()
    idx = t.find(q)
    if idx >= 0:
        return 1000 - idx * 5 - (len(t) - len(q))
    ti, gaps = 0, 0
    for ch in q:
        f = t.find(ch, ti)
        if f < 0:
            return 0
        gaps += f - ti
        ti = f + 1
    return max(1, 400 - gaps * 3)


class CommandPalette(QDialog):
    """模态命令面板：搜索框 + 结果列表，纯 UI 组件、零业务依赖。"""

    def __init__(self, parent, items: Iterable[PaletteItem]) -> None:
        """初始化相关对象。

            参数:
                parent: 父窗口（定位与模态归属）
                items: PaletteItem 可迭代（label 自带「页面:/品种:/命令:」前缀）
        """
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self._items: List[PaletteItem] = list(items)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "搜索页面 / 品种 / 命令…（Enter 执行 · Esc 关闭 · Ctrl+K 唤起）")
        self.listw = QListWidget()
        v.addWidget(self.input)
        v.addWidget(self.listw, 1)
        self.resize(520, 420)

        # 面板自身快捷键：Enter 在搜索框内也要能执行
        sc = QShortcut(QKeySequence("Return"), self.input)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(self._exec_current)
        sc_dn = QShortcut(QKeySequence("Down"), self.input)
        sc_dn.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc_dn.activated.connect(lambda: self._move(1))
        sc_up = QShortcut(QKeySequence("Up"), self.input)
        sc_up.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc_up.activated.connect(lambda: self._move(-1))

        self.input.textChanged.connect(self._refill)
        self.listw.itemActivated.connect(self._exec)
        self.listw.itemClicked.connect(self._exec)
        # M4-14②：无障碍名称/描述
        self.setAccessibleName("命令面板")
        self.input.setAccessibleName("命令搜索框")
        self.input.setAccessibleDescription(
            "输入关键词模糊搜索页面/品种/命令，Enter 执行选中项")
        self.listw.setAccessibleName("命令结果列表")
        self.listw.setAccessibleDescription(
            "上下键选择，Enter 执行，Esc 关闭")
        self._refill("")
        # 定位到父窗口顶部居中
        if parent is not None:
            try:
                g = parent.geometry()
                self.move(g.x() + (g.width() - self.width()) // 2,
                          g.y() + 80)
            except Exception:  # noqa: BLE001
                pass
        self.input.setFocus()

    # ------------------------------------------------------------------
    def _refill(self, query: str) -> None:
        """按模糊分重排并填充结果列表（空查询 = 全部、保持注入顺序）。"""
        scored = []
        for i, it in enumerate(self._items):
            s = fuzzy_score(query, it[0])
            if s > 0:
                scored.append((s, i, it))
        scored.sort(key=lambda x: (-x[0], x[1]))
        self.listw.clear()
        for _s, _i, (label, category, cb) in scored:
            item = QListWidgetItem(label)
            item.setToolTip(f"{category} · Enter 执行")
            item.setData(Qt.ItemDataRole.UserRole, cb)
            self.listw.addItem(item)
        if self.listw.count() > 0:
            self.listw.setCurrentRow(0)

    def _move(self, delta: int) -> None:
        """↑/↓ 移动选中行（保持焦点在搜索框，输入不中断）。"""
        row = self.listw.currentRow() + delta
        if 0 <= row < self.listw.count():
            self.listw.setCurrentRow(row)

    def _exec_current(self) -> None:
        """执行当前选中项（Enter 路径）。"""
        item = self.listw.currentItem()
        if item is not None:
            self._exec(item)

    def _exec(self, item: QListWidgetItem) -> None:
        """执行条目回调：先关面板再执行（避免模态叠模态）。"""
        cb = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if callable(cb):
            cb()

    def eventFilter(self, obj, event):  # noqa: N802
        """搜索框内 Esc 交给 QDialog 默认关闭（无需额外处理，兜底透传）。"""
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)
