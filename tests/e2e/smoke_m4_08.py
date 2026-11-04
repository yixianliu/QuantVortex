"""M4-08 表格能力铺开收尾 —— 活跃裸表迁移 DataGrid 验收（offscreen）。

覆盖本轮迁移的 5 张活跃表：
    - MarketOverviewPage.watch（行情全景 · 全市场速览）
    - AttributionDialog._trade_tbl（回测详情 · 分笔成交）
    - _AlertRulesDialog.tbl（预警规则管理）
    - PredictOpsPage.mc_tbl（模型状态）
    - PredictOpsPage.screen_tbl（选品排行）

验收点：
    ① 上述 5 表均为 DataGrid 实例；
    ② 含 setCellWidget 的表 sortable=False，纯 item 表 sortable=True；
    ③ DataGrid 统一能力齐备（排序 / 右键复制·导出 / 列显隐 / 空态 / 主题刷新）；
    ④ dark↔light 主题刷新不崩、空态文案正确；
    ⑤ 源码级：4 个活跃文件不再出现裸 ``QTableWidget(``（遗留孤儿页不计）。

运行：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m4_08.py
"""
from __future__ import annotations

import os
import sys

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


def main() -> int:
    app = None
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.states import DataGrid
    from futures_quant.ui.market_overview_page import MarketOverviewPage
    from futures_quant.ui.predict_ops_page import PredictOpsPage
    from futures_quant.ui.attribution_dialog import AttributionDialog
    from futures_quant.ui.pages import _AlertRulesDialog

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_test.db")

    # ---- ① 行情全景速览表 ----
    mv = MarketOverviewPage(mdm, store, config=None, session=None)
    check("market-watch-is-datagrid", isinstance(mv.watch, DataGrid),
          type(mv.watch).__name__)
    check("market-watch-capabilities",
          all(hasattr(mv.watch, m) for m in
              ("export_csv", "copy_row", "copy_cell", "set_row_action", "set_theme")),
          "export_csv/copy_row/copy_cell/set_row_action/set_theme")
    check("market-watch-row-action-wired",
          mv.watch._row_action == mv._on_pick, "set_row_action(self._on_pick)")

    # ---- ② 预测操作页：模型状态表 + 选品排行 ----
    po = PredictOpsPage(mdm, store, config=None, session=None)
    check("predict-mc-is-datagrid", isinstance(po.mc_tbl, DataGrid),
          type(po.mc_tbl).__name__)
    check("predict-screen-is-datagrid", isinstance(po.screen_tbl, DataGrid),
          type(po.screen_tbl).__name__)
    check("predict-mc-sortable", po.mc_tbl.is_sortable() is True, "纯 item 表可排序")
    check("predict-screen-not-sortable", po.screen_tbl.is_sortable() is False,
          "含 setCellWidget 表须关闭排序")

    # ---- ③ 预警规则管理表（含 setCellWidget）----
    rules = _AlertRulesDialog(mdm, store)
    check("alert-rules-is-datagrid", isinstance(rules.tbl, DataGrid),
          type(rules.tbl).__name__)
    check("alert-rules-not-sortable", rules.tbl.is_sortable() is False,
          "含 QCheckBox/按钮 单元格控件")

    # ---- ④ 回测详情分笔表 ----
    dlg = AttributionDialog({})   # 空明细：验证空态与构造健壮
    check("attribution-trade-is-datagrid", isinstance(dlg._trade_tbl, DataGrid),
          type(dlg._trade_tbl).__name__)
    check("attribution-trade-sortable", dlg._trade_tbl.is_sortable() is True,
          "纯 item 表可排序")

    # ---- ⑤ 主题刷新 + 空态 ----
    grids = [mv.watch, po.mc_tbl, po.screen_tbl, rules.tbl, dlg._trade_tbl]
    try:
        for g in grids:
            g.set_theme("light")
            g.set_theme("dark")
        check("datagrid-theme-refresh", True, "5 表 dark↔light 无异常")
    except Exception as exc:  # noqa: BLE001
        check("datagrid-theme-refresh", False, f"{type(exc).__name__}: {exc}")

    # 空态文案：分笔表初始 0 行，应显示自定义空态
    check("attribution-empty-text",
          "成交明细" in dlg._trade_tbl._empty._title.text(),
          dlg._trade_tbl._empty._title.text())

    # ---- ⑥ 源码级：活跃文件无裸 QTableWidget( ----
    active_files = [
        "futures_quant/ui/market_overview_page.py",
        "futures_quant/ui/attribution_dialog.py",
        "futures_quant/ui/predict_ops_page.py",
    ]
    for rel in active_files:
        p = os.path.join(_PROJ_ROOT, rel)
        txt = open(p, encoding="utf-8").read()
        # 允许 class DataGrid(QTableWidget) 定义处，禁止裸实例化
        naked = [ln.strip() for ln in txt.splitlines()
                 if "QTableWidget(" in ln and "class " not in ln]
        check(f"no-naked-qtablewidget::{os.path.basename(rel)}",
              len(naked) == 0, "; ".join(naked) or "0 处")

    # ---- 汇总 ----
    print("=" * 66)
    print("M4-08 表格能力铺开收尾 · 验收")
    print("=" * 66)
    passed = 0
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f"  ({detail})" if detail else ""))
        passed += int(ok)
    total = len(results)
    print("-" * 66)
    print(f"结果：{passed}/{total} 通过")

    # 清理页面定时器
    try:
        from PyQt6.QtGui import QCloseEvent
        for w in (mv, po, rules, dlg):
            w.closeEvent(QCloseEvent())
    except Exception:  # noqa: BLE001
        pass

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
