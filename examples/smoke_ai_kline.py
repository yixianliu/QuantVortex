"""离线冒烟测试：实例化主界面，绘制 K 线图与预测图，运行 AI 分析路径。

用法（离线渲染）：
    QT_QPA_PLATFORM=offscreen python examples/smoke_ai_kline.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter

from futures_quant.ui.main_window import MainWindow


def _render(widget, name):
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    widget.render(p)
    p.end()
    assert not widget.size().isEmpty(), f"{name} 尺寸为空"
    print(f"  [OK] 渲染 {name} ({widget.width()}x{widget.height()})")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()

    # 推进若干 tick，填充 K 线
    for _ in range(60):
        win._tick()
    app.processEvents()

    # K 线图数据校验
    bars = win.market_chart._bars
    ma = win.market_chart._ma
    assert len(bars) > 0, "K 线无数据"
    assert any(ma.get("MA5")), "MA 序列为空"
    print(f"  [OK] K 线数据：{len(bars)} 根，MA keys={list(ma.keys())}")

    _render(win.market_chart, "KLineChart(深)")
    _render(win.pred_chart, "PriceChart(深)")
    _render(win.market_table, "MarketTable(深)")
    _render(win.pos_table, "PosTable(深)")

    # 运行 AI 分析（rb.SHFE）
    win.pd_symbol.setCurrentText("rb.SHFE 螺纹钢")
    win.pd_mode.setCurrentText("trend")
    win.pd_look.setValue(120)
    win.pd_horizon.setValue(20)
    win._run_prediction()
    app.processEvents()
    summary = win.pred_summary.toPlainText()
    assert "AI 分析结论" in summary, "AI 结论未生成"
    assert win.pred_table.rowCount() == 20, f"预测表行数异常: {win.pred_table.rowCount()}"
    print(f"  [OK] AI 分析完成，结论长度={len(summary)}，预测表行数={win.pred_table.rowCount()}")
    print("  ----- AI 结论预览 -----")
    print("\n".join(summary.splitlines()[:8]))

    # 新组件校验
    assert win.pd_badge.text() != "--", "方向 Badge 未更新"
    assert win.pd_conf._pct > 0, "置信度条未更新"
    assert win.pd_target._val.text() not in ("--", ""), "预测中枢卡未更新"
    assert win.mc_price._val.text() not in ("--", ""), "行情快照卡未更新"
    _render(win.pred_card, "PredCard(深)")
    print(f"  [OK] 卡片组件：方向={win.pd_badge.text()} 置信度={win.pd_conf._pct:.0%}")

    # 切浅色再渲染一次，验证主题一致性
    win._toggle_theme()
    app.processEvents()
    _render(win.market_chart, "KLineChart(浅)")
    print("  [OK] 浅色主题渲染通过")

    # hover 十字光标路径（模拟鼠标移动）
    win.market_chart._hover = 10
    win.market_chart.update()
    app.processEvents()
    _render(win.market_chart, "KLineChart(hover)")
    print("  [OK] 悬浮十字光标渲染通过")

    # 自选品种：数量 / 分类筛选 / 图标
    total = win.market_table.rowCount()
    assert total >= 30, f"自选品种过少: {total}"
    print(f"  [OK] 自选品种总数={total}（覆盖六大板块）")
    win.wl_cat.setCurrentText("贵金属")
    app.processEvents()
    metal_rows = win.market_table.rowCount()
    assert 0 < metal_rows < total, f"板块筛选异常: {metal_rows}"
    win.wl_cat.setCurrentText("全部")
    app.processEvents()
    print(f"  [OK] 板块筛选：贵金属={metal_rows} 行，全部={win.market_table.rowCount()} 行")

    # 导航 SVG 图标非空
    for i, btn in enumerate(win._nav_buttons):
        assert not btn.icon().isNull(), f"导航图标 {i} 为空"
    assert not win.theme_btn.icon().isNull(), "主题按钮图标为空"
    print("  [OK] 导航/主题 SVG 图标渲染通过（7 个导航 + 主题）")

    # 双击切换主图品种
    before = win.symbol
    win._on_wl_double_click(0, 0)
    app.processEvents()
    after = win.symbol
    assert after != before, f"双击切换未生效: {before} -> {after}"
    print(f"  [OK] 双击切换主图：{before} -> {after}")

    print("\n冒烟测试全部通过 ✅")


if __name__ == "__main__":
    main()
