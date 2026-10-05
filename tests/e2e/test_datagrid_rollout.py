# -*- coding: utf-8 -*-
"""M4-08 验收：表格能力铺开（QTableWidget → DataGrid）。

对应文档 M4-08：
    ① backtest_page / screening_page / ctp_monitor_page / pages.py(LogPage) /
       simple_backtest_page 的目标表全部替换为 ``DataGrid``；
    ② 统一右键菜单（复制行 / 复制单元格 / 导出 CSV / 列显隐）；
    ③ 表头点击排序；
    ④ 双击行联动（默认复制整行 + Toast，可由 ``set_row_action`` 自定义）。

验收标准（文档原文）：
    - 每张表右键菜单可用；
    - 导出 CSV 用 ``utf-8-sig`` 且 Excel 打开无乱码。

运行：
    QT_QPA_PLATFORM=offscreen python tests/e2e/test_datagrid_rollout.py
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


def _tmp_store(tag: str) -> str:
    """构造测试用临时库路径（放 D 盘，避开沙箱慢盘）。"""
    base = os.path.join(_PROJ_ROOT, ".pytest_tmp")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"quant_analysis_{tag}.db")


def main() -> int:
    """执行全部验收项。"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from futures_quant.ui.main_window import MainWindow

    print("=" * 70)
    print("M4-08 · 表格能力铺开（QTableWidget → DataGrid）")
    print("=" * 70)

    win = MainWindow()
    # 页面懒加载：强制实例化全部页面
    for i in range(len(getattr(win, "pages", []))):
        try:
            win._show_page(i)
        except Exception:  # noqa: BLE001
            pass

    # ScreeningPage 不在主导航 NAV 中，需单独构造（沿用 test_screening_low_conf 的方式）
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.screening_page import ScreeningPage

    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path=_tmp_store("m4_08"))
    ScreeningPage._run = lambda self: None      # 阻止 __init__ 的后台筛选计算
    sc = ScreeningPage(mdm, store, config=None, session=None)

    # ---- ① 目标表已替换为 DataGrid ----
    print("\n[①] 目标表类型")
    # 说明：backtest_page.py 里的 trade_tbl/metric_tbl/cmp_tbl/sens_tbl/opt_tbl 属于
    # **已死类 BacktestPage**（全仓无引用，待 M4-11 清理），不在运行时页面内，故不列入。
    # (页面类名, 表属性名, 期望 sortable)
    targets = [
        ("BacktestCenterPage", "pop_tbl", True),
        ("BacktestCenterPage", "factor_tbl", True),
        ("BacktestCenterPage", "factor_corr_tbl", True),
        ("BacktestCenterPage", "factor_tune_tbl", True),
        ("BacktestCenterPage", "factor_monitor_tbl", True),
        ("BacktestCenterPage", "lib_tbl", False),      # 用 setCellWidget → 禁排序
        ("BacktestCenterPage", "hist_tbl", False),     # 用 setCellWidget → 禁排序
        ("ScreeningPage", "tbl", True),
        ("ScreeningPage", "ctbl", True),
        ("CTPMonitorPage", "qtable", True),
        ("SimpleBacktestPage", "trade_tbl", True),
        ("LogPage", "tab_log", True),
        ("LogPage", "tab_alert", True),
        ("LogPage", "tab_pred", True),
        ("LogPage", "tab_an", True),
    ]
    pages = {type(p).__name__: p for p in win.pages}
    pages["ScreeningPage"] = sc
    check("BacktestCenterPage" in pages, "回测中心页已实例化")
    check("ScreeningPage" in pages, "选品页已实例化（单独构造）")
    grids: list = []
    for cls_name, attr, sortable in targets:
        page = pages.get(cls_name)
        if page is None:
            check(False, f"{cls_name} 未实例化")
            continue
        tbl = getattr(page, attr, None)
        ok = type(tbl).__name__ == "DataGrid"
        check(ok, f"{cls_name}.{attr} 是 DataGrid（实际 {type(tbl).__name__}）")
        if ok:
            grids.append(tbl)
            check(tbl.is_sortable() == sortable,
                  f"{cls_name}.{attr} sortable={sortable}（实际 {tbl.is_sortable()}）")
            # Qt 自动排序必须保持关闭（开启会破坏 setItem 批量填充，见 states.py 注释）
            check(tbl.isSortingEnabled() is False,
                  f"{cls_name}.{attr} 未开启 Qt 自动排序")

    # ---- ② 右键菜单能力 + CSV 导出（抽样验证，全量接口一致故不必逐表导出） ----
    print("\n[②] 右键菜单与 CSV 导出")
    from PyQt6.QtWidgets import QTableWidgetItem
    sample = grids[0] if grids else None
    if sample is None:
        check(False, "没有可用于抽样的 DataGrid")
        return _finish()

    sample.setRowCount(2)
    for r in range(2):
        for c in range(sample.columnCount()):
            sample.setItem(r, c, QTableWidgetItem(f"r{r}c{c}"))
    # 排序开启时 setItem 可能改变行序，故每次读取前重设当前单元格
    sample.setCurrentCell(0, 0)
    sample.copy_row()
    clip = app.clipboard().text()
    check("\t" in clip, f"复制整行为 Tab 分隔（{clip[:30]}…）")
    # 排序开启时行序可能变化，故以「当前单元格真实文本」为期望值，避免断言依赖行序
    sample.setCurrentCell(0, 0)
    cur = sample.item(sample.currentRow(), sample.currentColumn())
    expect = cur.text() if cur is not None else ""
    sample.copy_cell()
    check(app.clipboard().text() == expect,
          f"复制单元格取当前列（实际 {app.clipboard().text()!r}，期望 {expect!r}）")

    import tempfile
    out_path = os.path.join(tempfile.gettempdir(), "m4_08_rollout.csv")
    written = sample.export_csv(out_path)
    check(written == out_path and os.path.exists(out_path), "导出 CSV 成功")
    if os.path.exists(out_path):
        with open(out_path, "rb") as fh:
            check(fh.read(3) == b"\xef\xbb\xbf", "CSV 带 utf-8-sig BOM（Excel 无乱码）")
        os.remove(out_path)

    # 列显隐对每张表都可用（无需弹菜单，直接调 API 验证）
    print("\n[②b] 列显隐（全表）")
    bad = []
    for g in grids:
        if g.columnCount() == 0:
            continue
        g.setColumnHidden(0, True)
        if not g.isColumnHidden(0):
            bad.append(g)
        g.setColumnHidden(0, False)
    check(not bad, f"全部 {len(grids)} 张表列显隐可用（异常 {len(bad)} 张）")

    # ---- ③ 表头排序 ----
    print("\n[③] 表头排序")
    sortable_tables = [g for g in grids if g.is_sortable() and g.columnCount() > 0]
    # 15 张在运行时页面内（另 5 张属死类 BacktestPage）；其中 lib/hist 用 setCellWidget 禁排序
    check(len(sortable_tables) >= 12, f"可排序表 ≥12 张（实际 {len(sortable_tables)}）")
    s0 = sortable_tables[0]
    s0.setRowCount(3)
    for r, v in enumerate(["c", "a", "b"]):
        s0.setItem(r, 0, QTableWidgetItem(v))
    # 批量填充后单元格必须全部在位（这是关闭 Qt 自动排序要守住的核心契约）
    kept = sum(1 for r in range(3) if s0.item(r, 0) is not None)
    check(kept == 3, f"批量 setItem 后 3 行单元格全部在位（实际 {kept}）")
    # 表头点击 → 升序
    s0.horizontalHeader().sectionClicked.emit(0)
    app.processEvents()
    first = s0.item(0, 0).text() if s0.item(0, 0) else ""
    check(first == "a", f"点击表头升序后首行为 a（实际 {first!r}）")
    # 再次点击同列 → 降序
    s0.horizontalHeader().sectionClicked.emit(0)
    app.processEvents()
    first2 = s0.item(0, 0).text() if s0.item(0, 0) else ""
    check(first2 == "c", f"再次点击表头降序后首行为 c（实际 {first2!r}）")

    # ---- ④ 双击行联动 ----
    print("\n[④] 双击行联动")
    seen_rows: list[int] = []
    s0.row_double_clicked.connect(seen_rows.append)
    s0.setCurrentCell(0, 0)
    s0.cellDoubleClicked.emit(0, 0)
    app.processEvents()
    check(seen_rows == [0], f"双击发出 row_double_clicked（实际 {seen_rows}）")
    check(app.clipboard().text().startswith("a") or "\t" in app.clipboard().text(),
          "默认联动复制整行到剪贴板")

    custom: list[int] = []
    s0.set_row_action(lambda r: custom.append(r))
    s0.cellDoubleClicked.emit(1, 0)
    app.processEvents()
    check(custom == [1], f"set_row_action 自定义动作生效（实际 {custom}）")
    s0.set_row_action(None)

    return _finish()


def _finish() -> int:
    """打印汇总并返回退出码。"""
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
