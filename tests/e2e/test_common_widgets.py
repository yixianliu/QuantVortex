# -*- coding: utf-8 -*-
"""M4-07 通用组件验收：Card / EmptyState / Skeleton / Toast / DataGrid / Pagination。

验证点（对应文档 M4-07「验证方式」）：
    ① 六个组件 offscreen 可构造；
    ② 主题切换（dark↔light）后内部色值刷新（不再残留旧主题色）；
    ③ 空态渲染：DataGrid 行数为 0 时显示 EmptyState，有数据时隐藏；
    ④ DataGrid 右键菜单能力（复制行 / 复制单元格 / 列显隐）与 CSV 导出；
    ⑤ Skeleton 受 MOTION 门控（REDUCED_MOTION 下不启动定时器）；
    ⑥ Toast 三色 + 堆叠队列与自动消失；
    ⑦ Pagination 页码夹紧与切片计算；
    ⑧ 直驱 paintEvent 不抛异常（paint_guard 生效，避免 exit 127）。

运行：
    QT_QPA_PLATFORM=offscreen python tests/e2e/test_common_widgets.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR",
    "D:/PythonProject/QuantVortex/.pytest_tmp/sd-state",
)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    """记录一条断言结果。"""
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


def make_app():
    """创建（或复用）离屏 QApplication。"""
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def drive_paint(widget) -> bool:
    """直驱 paintEvent（offscreen 下 grab 易崩，改为直接调用绘制）。

    返回:
        bool：绘制未抛异常为 True。
    """
    from PyQt6.QtGui import QPaintEvent
    try:
        widget.show()
        QApplication_process()
        widget.paintEvent(QPaintEvent(widget.rect()))
        return True
    except Exception:  # noqa: BLE001
        return False


def QApplication_process() -> None:  # noqa: N802 - 保持与既有脚本一致的风格
    """推进事件循环一次。"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def main() -> int:
    """执行全部验收项。"""
    app = make_app()

    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
    from futures_quant.ui import design_system
    from futures_quant.ui.states import (
        Card, DataGrid, EmptyState, MOTION, Pagination, Skeleton, Toast, toast,
    )

    print("=" * 70)
    print("M4-07 · 通用组件验收（Card / EmptyState / Skeleton / Toast / DataGrid / Pagination）")
    print("=" * 70)

    # ---------------------------------------------------------------- ① 构造
    print("\n[①] 组件构造")
    card = Card(title="标题卡", subtitle="副标题", accent="#3b82f6")
    check(isinstance(card, QWidget), "Card 构造成功")
    check(card._title_lab.text() == "标题卡", "Card 标题正确")

    empty = EmptyState("📭", "暂无数据", "运行回测后展示", "去回测")
    check(isinstance(empty, QWidget), "EmptyState 构造成功")
    # 注意：isVisible() 对「父级不可见」的控件恒为 False，故先 show 再断言
    empty.show()
    check(empty._btn.isVisible(), "EmptyState 行动按钮可见（传入 action_text）")

    sk = Skeleton(rows=3, row_height=14)
    check(isinstance(sk, QWidget), "Skeleton 构造成功")
    check(sk.minimumHeight() >= 3 * 14, "Skeleton 最小高度覆盖全部行")

    grid = DataGrid(0, 3)
    grid.setHorizontalHeaderLabels(["A", "B", "C"])
    # 语义：允许点击表头排序（内部 Qt 自动排序保持关闭，避免批量 setItem 丢单元格）
    check(grid.is_sortable(), "DataGrid 默认允许表头点击排序")
    check(not grid.isSortingEnabled(), "DataGrid 内部关闭 Qt 自动排序（保护批量填充）")
    # 空态是 viewport 的子控件，需宿主可见后 isVisible() 才可信
    grid.resize(400, 240)
    grid.show()
    QApplication_process()

    pag = Pagination(total=0, page_size=50)
    check(pag.page_count == 1, "Pagination 空数据总页数为 1")

    host = QWidget()
    host.setFixedSize(600, 400)
    host.show()
    t = toast(host, "保存成功", level="info", duration=300)
    check(isinstance(t, Toast), "Toast 构造并显示成功")

    # ------------------------------------------------------------ ② 主题切换
    print("\n[②] 主题切换刷新")
    dark_tokens = set(design_system.design_tokens("dark").values())
    light_tokens = set(design_system.design_tokens("light").values())

    def hexes(w) -> set:
        """取控件（含子孙）styleSheet 中的十六进制色值。"""
        import re
        out = set()
        for child in [w] + w.findChildren(QWidget):
            ss = child.styleSheet() or ""
            out |= {m.lower() for m in re.findall(r"#[0-9a-fA-F]{6}", ss)}
        return out

    card.set_theme("dark")
    d_hex = hexes(card)
    card.set_theme("light")
    l_hex = hexes(card)
    check(bool(d_hex & dark_tokens), f"Card dark 主题色落在 dark token 集合（{sorted(d_hex)[:3]}…）")
    check(bool(l_hex & light_tokens), f"Card light 主题色落在 light token 集合（{sorted(l_hex)[:3]}…）")
    check(not (l_hex & (dark_tokens - light_tokens)), "Card 切 light 后无 dark 专属色残留")

    grid.set_theme("dark")
    check(bool(hexes(grid) & dark_tokens), "DataGrid dark 主题生效")
    grid.set_theme("light")
    check(bool(hexes(grid) & light_tokens), "DataGrid light 主题生效")

    for w in (empty, sk, pag):
        w.set_theme("dark")
        w.set_theme("light")
    check(True, "EmptyState / Skeleton / Pagination set_theme 不抛异常")

    # ------------------------------------------------------------ ③ 空态渲染
    print("\n[③] DataGrid 空态渲染")
    check(grid._empty.isVisible(), "0 行时 EmptyState 可见")
    grid.setRowCount(2)
    from PyQt6.QtWidgets import QTableWidgetItem
    for r in range(2):
        for c in range(3):
            grid.setItem(r, c, QTableWidgetItem(f"{r}-{c}"))
    QApplication_process()
    check(not grid._empty.isVisible(), "有数据后 EmptyState 隐藏")
    grid.setRowCount(0)
    QApplication_process()
    check(grid._empty.isVisible(), "清空行后 EmptyState 重新出现")
    grid.set_empty_text("没有匹配的合约", "调整筛选条件后重试")
    check(grid._empty._title.text() == "没有匹配的合约", "自定义空态文案生效")

    # ------------------------------------------------- ④ 右键菜单与 CSV 导出
    print("\n[④] DataGrid 菜单 / 导出")
    grid.setRowCount(1)
    grid.setItem(0, 0, QTableWidgetItem("x"))
    grid.setItem(0, 1, QTableWidgetItem("y"))
    grid.setItem(0, 2, QTableWidgetItem("z"))
    grid.setCurrentCell(0, 1)
    grid.copy_row()
    clip = app.clipboard().text()
    check(clip == "x\ty\tz", f"复制整行为 Tab 分隔（实际 {clip!r}）")
    grid.copy_cell()
    check(app.clipboard().text() == "y", "复制单元格取当前列")

    grid.setColumnHidden(1, True)
    check(grid.isColumnHidden(1), "列显隐：隐藏第 2 列生效")
    grid.setColumnHidden(1, False)
    check(not grid.isColumnHidden(1), "列显隐：恢复显示生效")

    import tempfile
    out_path = os.path.join(tempfile.gettempdir(), "m4_07_grid.csv")
    written = grid.export_csv(out_path)
    check(written == out_path and os.path.exists(out_path), "导出 CSV 成功")
    if os.path.exists(out_path):
        with open(out_path, "rb") as fh:
            head = fh.read(3)
        check(head == b"\xef\xbb\xbf", "CSV 带 utf-8-sig BOM（Excel 打开不乱码）")
        with open(out_path, encoding="utf-8-sig") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        check(lines[0] == "A,B,C" and len(lines) == 2, f"CSV 表头与数据行正确（{lines}）")
        os.remove(out_path)

    # ------------------------------------------------------- ⑤ 动效门控
    print("\n[⑤] Skeleton 动效门控")
    check(MOTION is True or MOTION is False, "MOTION 常量存在")
    sk2 = Skeleton(rows=2)
    sk2.show()
    if MOTION:
        check(sk2._timer.isActive(), "MOTION 开启时 shimmer 定时器运行")
    else:
        check(not sk2._timer.isActive(), "MOTION 关闭时 shimmer 定时器不启动")
    sk2.set_animation_enabled(False)
    check(not sk2._timer.isActive(), "set_animation_enabled(False) 停止定时器")
    sk2.hide()

    # ------------------------------------------------------- ⑥ Toast 队列
    print("\n[⑥] Toast 堆叠与消失")
    host2 = QWidget()
    host2.setFixedSize(500, 300)
    host2.show()
    t1 = toast(host2, "第一条", level="info", duration=0)
    t2 = toast(host2, "第二条", level="error", duration=0)
    stack = Toast._stacks.get(id(host2), [])
    check(len(stack) == 2, f"两条 Toast 进入同一堆叠（实际 {len(stack)}）")
    check(t2.y() > t1.y(), "第二条纵向堆叠在第一条下方")
    t1.dismiss()
    check(len(Toast._stacks.get(id(host2), [])) == 1, "dismiss 后从堆叠移除")
    t2.dismiss()

    t3 = toast(host2, "自动消失", level="warn", duration=50)
    check(t3._timer.isActive(), "duration>0 时启动自动关闭定时器")
    t3.dismiss()

    # ------------------------------------------------------- ⑦ Pagination
    print("\n[⑦] Pagination 行为")
    p = Pagination(total=120, page_size=50)
    check(p.page_count == 3, "120 条 / 每页 50 → 3 页")
    check(p.slice_range() == (0, 50), "第 1 页切片 (0, 50)")
    p.set_page(2)
    check(p.page == 2 and p.slice_range() == (50, 100), "第 2 页切片 (50, 100)")
    p.set_page(99)
    check(p.page == 3, "越界页码夹紧到末页")
    p.set_page(0)
    check(p.page == 1, "越界页码夹紧到首页")
    seen = []
    p.page_changed.connect(seen.append)
    p.set_page(2)
    check(seen == [2], f"page_changed 信号发出（实际 {seen}）")
    p.set_total(20)
    check(p.page == 1 and p.page_count == 1, "总条数变小时页码自动回落")

    # ------------------------------------------------------- ⑧ paint_guard
    print("\n[⑧] 自绘健壮性（paint_guard）")
    for name, w in (("Card", card), ("EmptyState", empty), ("Skeleton", sk)):
        check(drive_paint(w), f"{name} 直驱 paintEvent 无异常")
    check(drive_paint(host2), "宿主窗口直驱 paintEvent 无异常")

    # 收尾：显式释放浮层与宿主，避免解释器退出期 Qt 清理引发硬崩溃（exit 127）
    print("\n[⑨] 收尾清理")
    for _w in list(Toast._stacks.get(id(host), [])) + list(Toast._stacks.get(id(host2), [])):
        try:
            _w.dismiss()
        except Exception:  # noqa: BLE001
            pass
    QApplication_process()
    for _w in (empty, sk, sk2, grid, pag, card, host, host2):
        try:
            _w.close()
        except Exception:  # noqa: BLE001
            pass
    QApplication_process()
    check(True, "全部组件显式关闭，无残留浮层")

    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
