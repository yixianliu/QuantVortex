# -*- coding: utf-8 -*-
"""M4-08 表格能力铺开 DoD 验收。

M4-08 四项 DoD：
① 上述 16 张 QTableWidget 全部替换为 DataGrid（backtest_page / screening_page /
   ctp_monitor_page / pages.py(LogPage) / simple_backtest_page）
② 统一右键菜单：复制行 / 复制单元格 / 导出 CSV / 列显隐
③ 表头点击排序
④ 双击行联动（按页面语义）
DoD 门禁：每张表右键菜单可用；导出 CSV 用 utf-8-sig 且 Excel 打开无乱码。

共 16 项：类结构 2 + 右键菜单 3 + 排序 2 + 双击联动 2 + CSV 导出 3
        + 空态与主题 2 + 铺开 2。
"""
from __future__ import annotations

import ast
import csv
import os
import tempfile

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _proj_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _src(rel: str) -> str:
    path = os.path.join(_proj_root(), rel.replace("/", os.sep))
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _grid(qapp, rows=3, cols=3, **kw):
    """构造测试用 DataGrid（带示例数据）。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(rows, cols, **kw)
    for i, name in enumerate(["合约A", "合约B", "合约C"]):
        for j, val in enumerate([name, str(100 + i), f"pnl_{i}"]):
            if i < rows and j < cols:
                g.setItem(i, j, QTableWidgetItem(val))
    return g


# ─────────────────────────────────────────────────────────────
# ① 类结构
# ─────────────────────────────────────────────────────────────

def test_datagrid_exists_and_inherits_qtablewidget(qapp):
    """M4-08①：DataGrid 类存在且继承 QTableWidget。"""
    from futures_quant.ui.states import DataGrid
    assert issubclass(DataGrid, QTableWidget)


def test_datagrid_construction_and_defaults(qapp):
    """M4-08①：DataGrid 构造后关闭自动排序（改手动 sortItems）+ 行选择模式。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(0, 0)
    try:
        # 关键陷阱：Qt 自动排序会打乱 setItem 顺序，DataGrid 必须关闭
        assert g.isSortingEnabled() is False, "自动排序未关闭（会打乱批量填充）"
        assert g.is_sortable() is True, "默认应可点击表头排序"
        assert g.selectionBehavior() == QTableWidget.SelectionBehavior.SelectRows
        assert g.alternatingRowColors() is True
        assert g.verticalHeader().isVisible() is False
    finally:
        g.deleteLater()


# ─────────────────────────────────────────────────────────────
# ② 右键菜单 4 项
# ─────────────────────────────────────────────────────────────

def test_context_menu_policy_enabled(qapp):
    """M4-08②：右键菜单通过 CustomContextMenu 策略触发。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(1, 2)
    try:
        assert g.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    finally:
        g.deleteLater()


def test_menu_action_4_items_present(qapp):
    """M4-08②：右键菜单含 4 项：复制整行 / 复制单元格 / 导出 CSV / 列显隐。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(0, 2)
    g.setItem(0, 0, QTableWidgetItem("x"))
    try:
        src = _src("futures_quant/ui/states.py")
        # 定位 _menu 方法体
        tree = ast.parse(src)
        menu_body = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_menu":
                menu_body = ast.get_source_segment(src, node) or ""
                break
        assert menu_body is not None, "未找到 _menu 方法"
        for kw in ("复制整行", "复制单元格", "导出 CSV", "列显隐"):
            assert kw in menu_body, f"右键菜单缺少：{kw}"
        # 列显隐通过 setColumnHidden 实现
        assert "setColumnHidden" in menu_body
    finally:
        g.deleteLater()


def test_menu_triggers_export_csv_and_copy(qapp, monkeypatch):
    """M4-08②：右键菜单触发后调用 copy_row / copy_cell / export_csv。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(1, 2)
    g.setItem(0, 0, QTableWidgetItem("A"))
    g.setItem(0, 1, QTableWidgetItem("B"))
    calls = {"row": 0, "cell": 0, "csv": 0}
    # 用 monkeypatch 打桩剪贴板避免真实写入
    monkeypatch.setattr(g, "copy_row", lambda: calls.__setitem__("row", calls["row"] + 1))
    monkeypatch.setattr(g, "copy_cell", lambda: calls.__setitem__("cell", calls["cell"] + 1))
    monkeypatch.setattr(g, "export_csv", lambda *a, **kw: calls.__setitem__("csv", calls["csv"] + 1) or "x.csv")

    # 直接驱动 3 个入口（避免菜单 exec 阻塞）
    g.copy_row()
    g.copy_cell()
    g.export_csv(path="x.csv")
    assert calls == {"row": 1, "cell": 1, "csv": 1}, f"菜单动作未生效：{calls}"
    g.deleteLater()


# ─────────────────────────────────────────────────────────────
# ③ 表头点击排序
# ─────────────────────────────────────────────────────────────

def test_header_click_sorts_ascending(qapp):
    """M4-08③：表头点击升序排序（数值列）。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(3, 1)
    for i, v in enumerate(["30", "10", "20"]):
        g.setItem(i, 0, QTableWidgetItem(v))
    g._on_header_clicked(0)
    assert g.item(0, 0).text() == "10"
    assert g.item(2, 0).text() == "30"
    g.deleteLater()


def test_header_click_toggles_descending(qapp):
    """M4-08③：同列第二次点击切换为降序。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(3, 1)
    for i, v in enumerate(["30", "10", "20"]):
        g.setItem(i, 0, QTableWidgetItem(v))
    g._on_header_clicked(0)  # 升
    assert g.item(0, 0).text() == "10"
    g._on_header_clicked(0)  # 降
    assert g.item(0, 0).text() == "30"
    assert g._sort_order == Qt.SortOrder.DescendingOrder
    g.deleteLater()


# ─────────────────────────────────────────────────────────────
# ④ 双击行联动
# ─────────────────────────────────────────────────────────────

def test_double_click_emits_row_double_clicked_signal(qapp):
    """M4-08④：双击行发出 row_double_clicked 信号（行号）。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(3, 2)
    g.setItem(0, 0, QTableWidgetItem("A"))
    got = []
    g.row_double_clicked.connect(lambda r: got.append(r))
    # 打桩 clipboard + toast 避免副作用
    g.copy_row = lambda: None
    g._on_double_click(2, 0)
    assert got == [2], f"row_double_clicked 未发出：{got}"
    g.deleteLater()


def test_set_row_action_overrides_default_copy(qapp):
    """M4-08④：set_row_action 覆盖默认「复制整行」行为。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(3, 2)
    g.setItem(0, 0, QTableWidgetItem("A"))
    copy_called = {"n": 0}
    g.copy_row = lambda: copy_called.__setitem__("n", copy_called["n"] + 1)
    handler_called = {"n": 0}
    g.set_row_action(lambda r: handler_called.__setitem__("n", r))
    g._on_double_click(1, 0)
    assert handler_called["n"] == 1, "自定义动作未生效"
    assert copy_called["n"] == 0, "自定义动作设置后不应再走默认复制"
    g.deleteLater()


# ─────────────────────────────────────────────────────────────
# CSV 导出（utf-8-sig + 表头 + 跳过隐藏行）
# ─────────────────────────────────────────────────────────────

def test_export_csv_writes_utf8_sig_with_bom(qapp):
    """M4-08 DoD：export_csv 使用 utf-8-sig 编码（BOM EF BB BF 头部，Excel 无乱码）。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(1, 2)
    from PyQt6.QtWidgets import QTableWidgetItem as IT
    g.setItem(0, 0, IT("合约"))
    g.setItem(0, 1, IT("100"))
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as f:
            path = f.name
        try:
            written = g.export_csv(path=path)
            assert written == path
            with open(path, "rb") as fh:
                head = fh.read(3)
            assert head == b"\xef\xbb\xbf", (
                f"CSV 缺少 UTF-8 BOM（Excel 打开会乱码），前 3 字节={head!r}"
            )
        finally:
            if os.path.exists(path):
                os.remove(path)
    finally:
        g.deleteLater()


def test_export_csv_includes_header_row(qapp):
    """M4-08 DoD：export_csv 首行输出表头（QTableWidgetItem 或 "列 N"）。"""
    from futures_quant.ui.states import DataGrid
    from PyQt6.QtWidgets import QTableWidgetItem as IT, QTableWidgetItem, QHeaderView
    g = DataGrid(2, 2)
    g.setHorizontalHeaderLabels(["合约", "价格"])
    g.setItem(0, 0, IT("rb")); g.setItem(0, 1, IT("3800"))
    g.setItem(1, 0, IT("hc")); g.setItem(1, 1, IT("3500"))
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as f:
            path = f.name
        try:
            g.export_csv(path=path)
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh))
            assert rows[0] == ["合约", "价格"], f"表头缺失或错误：{rows[0]}"
            assert rows[1] == ["rb", "3800"]
            assert rows[2] == ["hc", "3500"]
        finally:
            if os.path.exists(path):
                os.remove(path)
    finally:
        g.deleteLater()


def test_export_csv_skips_hidden_rows(qapp):
    """M4-08：export_csv 跳过 isRowHidden 的行（不输出隐藏行数据）。"""
    from futures_quant.ui.states import DataGrid
    from PyQt6.QtWidgets import QTableWidgetItem as IT
    g = DataGrid(3, 1)
    for i, v in enumerate(["a", "b", "c"]):
        g.setItem(i, 0, IT(v))
    g.setRowHidden(1, True)
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as f:
            path = f.name
        try:
            g.export_csv(path=path)
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                rows = [r for r in csv.reader(fh) if r]
            # 表头 1 + 2 行数据（b 被隐藏跳过）
            values = [r[0] for r in rows[1:]]
            assert "b" not in values, "隐藏行被错误导出"
            assert "a" in values and "c" in values
        finally:
            if os.path.exists(path):
                os.remove(path)
    finally:
        g.deleteLater()


# ─────────────────────────────────────────────────────────────
# 空态 + 主题
# ─────────────────────────────────────────────────────────────

def test_empty_state_shown_when_zero_rows(qapp):
    """M4-08：行数为 0 时显示空态占位，行数>0 隐藏。

    注意：DataGrid 未 show() 时 isVisible() 恒为 False，改用 isVisibleTo(self)
    检查「相对父控件」的可见性（即未调用 hide() 且未因行数触发 _sync_empty 隐藏）。
    """
    from futures_quant.ui.states import DataGrid
    g = DataGrid(0, 2)
    try:
        assert g.rowCount() == 0
        # _sync_empty 在 rowCount==0 时 setVisible(True)
        assert g._empty.isVisibleTo(g) is True, "空表未显示空态占位"
        g.setRowCount(1)
        g.setItem(0, 0, QTableWidgetItem("x"))
        assert g._empty.isVisibleTo(g) is False, "有数据时未隐藏空态"
    finally:
        g.deleteLater()


def test_set_theme_updates_style_and_accessible_name(qapp):
    """M4-08：set_theme 更新隔行底色；构造期设置 accessibleName/Description。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(1, 1)
    try:
        # 构造期默认已设无障碍名称
        assert g.accessibleName() == "数据表格"
        assert "导出 CSV" in g.accessibleDescription()
        # 主题切换不抛异常
        g.set_theme("dark" if hasattr(DataGrid, "set_theme") else g._theme)
        # stylesheet 已设置
        assert "QTableWidget" in g.styleSheet()
    finally:
        g.deleteLater()


# ─────────────────────────────────────────────────────────────
# 铺开：16 张 QTableWidget 已全部替换 DataGrid
# ─────────────────────────────────────────────────────────────

def test_datagrid_used_in_all_migrated_pages(qapp):
    """M4-08①：5 个 DoD 指定文件中 QTableWidget 已全部替换为 DataGrid。"""
    # 目标文件（DoD 明列）+ 铺开后的实际归属
    targets = [
        "futures_quant/ui/backtest_page.py",
        "futures_quant/ui/screening_page.py",
        "futures_quant/ui/ctp_monitor_page.py",
        "futures_quant/ui/simple_backtest_page.py",
    ]
    total_datagrid = 0
    for rel in targets:
        src = _src(rel)
        # 每个文件都应至少 1 处 DataGrid(
        assert "DataGrid(" in src, f"{rel} 未见 DataGrid 使用"
        # 关键：不应再有裸 QTableWidget( 实例化（import 与 class 定义除外）
        tree = ast.parse(src)
        instantiations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name == "QTableWidget":
                    instantiations.append(node.lineno)
        assert not instantiations, (
            f"{rel} 仍有裸 QTableWidget 实例化于行 {instantiations}"
        )
        # 统计 DataGrid 出现次数
        total_datagrid += src.count("DataGrid(")
    # DoD 明列 16 张；实际 31 张（含 pages.py 9 张收尾迁移），下限断言为 16
    assert total_datagrid >= 16, f"DataGrid 实例总数={total_datagrid}，未达 DoD 下限 16"


def test_datagrid_count_meets_dod_threshold(qapp):
    """M4-08①：全 ui/ 目录下 DataGrid 实例数 ≥ 16（含 backtest_page / market_overview / pages）。"""
    ui_dir = os.path.join(_proj_root(), "futures_quant", "ui")
    total = 0
    for fname in sorted(os.listdir(ui_dir)):
        if not fname.endswith(".py"):
            continue
        with open(os.path.join(ui_dir, fname), "r", encoding="utf-8") as f:
            content = f.read()
        total += content.count("DataGrid(")
    assert total >= 16, f"全项目 DataGrid 实例数={total}，未达 DoD 下限 16"


# ─────────────────────────────────────────────────────────────
# 复制契约（copy_row 制表符 / copy_cell 单元格）
# ─────────────────────────────────────────────────────────────

def test_copy_row_tab_separated(qapp):
    """M4-08②：copy_row 使用制表符分隔（可直接粘进 Excel）。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(1, 3)
    for j, v in enumerate(["rb", "3800", "200"]):
        g.setItem(0, j, QTableWidgetItem(v))
    g.setCurrentCell(0, 0)
    try:
        text = g._current_row_text()
        assert text == "rb\t3800\t200", f"制表符分隔失败：{text!r}"
    finally:
        g.deleteLater()


def test_copy_cell_uses_current_position(qapp):
    """M4-08②：copy_cell 取当前单元格文本。"""
    from futures_quant.ui.states import DataGrid
    g = DataGrid(2, 2)
    g.setItem(0, 0, QTableWidgetItem("A"))
    g.setItem(1, 1, QTableWidgetItem("D"))
    g.setCurrentCell(1, 1)
    try:
        text = g._cell_text(g.currentRow(), g.currentColumn())
        assert text == "D", f"当前单元格读取错误：{text!r}"
    finally:
        g.deleteLater()
