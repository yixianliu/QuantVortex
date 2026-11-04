# -*- coding: utf-8 -*-
"""M4-12 冒烟测试：快捷键与命令面板（offscreen QTest.keyClick 逐键验证）。

覆盖：
    ① Ctrl+K 命令面板（模糊搜索「回测」可命中「页面：回测中心」并跳转）
    ② F5 刷新当前页（duck-typing 命中 _refresh_all）
    ③ Ctrl+E 导出当前表（DataGrid.export_csv 被调用）
    ④ Ctrl+, 打开模型配置（AIConfigDialog 被创建）
    ⑤ Esc 关闭浮层
    ⑥ Ctrl+1..7 切页
    ⑦ 帮助菜单「快捷键」清单（_shortcut_seqs 登记）+ 状态栏 Tooltip
    ⑧ fuzzy_score 打分正确性（子串 > 子序列 > 不命中）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

app = QApplication.instance() or QApplication([])

# ---- ⑧ fuzzy_score 打分 ----
from futures_quant.ui.command_palette import CommandPalette, fuzzy_score

assert fuzzy_score("", "任意") == 1
assert fuzzy_score("回测", "页面：回测中心") > 400, "子串命中应 >400"
assert fuzzy_score("回测", "页面：独立回测") > 400
assert fuzzy_score("回测", "页面：行情全景") == 0, "不命中应为 0"
sub = fuzzy_score("回测", "页面：历史回与测点")   # 子序列（间隔命中）
assert 0 < sub <= 400, f"子序列命中应落 (0,400]: {sub}"
assert fuzzy_score("rb", "品种：RB 螺纹钢") > 400, "大小写不敏感子串"
assert (fuzzy_score("回测", "页面：回测中心")
        > fuzzy_score("回测", "页面：模型配置回测版")), "越靠前越紧凑分越高"

win = __import__("futures_quant.ui.main_window", fromlist=["MainWindow"]).MainWindow()
if getattr(win, "_connect_deferred", None) is not None:
    win._connect_deferred.stop()
win.show()
app.processEvents()

# ---- ⑦ 快捷键登记 + Tooltip ----
seqs = {seq for seq, _d in win._shortcut_seqs}
for need in ("Ctrl+K", "F5", "Ctrl+E", "Ctrl+,", "Esc",
             "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6", "Ctrl+7"):
    assert need in seqs, f"快捷键未登记: {need}"
assert win.status.toolTip(), "状态栏 Tooltip 应包含快捷键速查"

# ---- ⑥ Ctrl+1..7 切页（QTest 实敲） ----
QTest.keyClick(win, Qt.Key.Key_7, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
assert win.stack.currentWidget() is win.pages[6], "Ctrl+7 应切到数据管理页"
assert win.nav.currentRow() == 6, "侧栏高亮应同步"
QTest.keyClick(win, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
assert win.stack.currentWidget() is win.pages[0], "Ctrl+1 应回行情全景"

# ---- ② F5 刷新当前页 ----
page0 = win.pages[0]
fired = []
orig_refresh = page0._refresh_all
page0._refresh_all = lambda: fired.append(1)
QTest.keyClick(win, Qt.Key.Key_F5)
app.processEvents()
page0._refresh_all = orig_refresh
assert fired, "F5 应触发当前页 _refresh_all"

# ---- ③ Ctrl+E 导出当前表 ----
from futures_quant.ui.states import DataGrid

# 负向路径：行情全景页用 RankTable（非 DataGrid），应提示无表格
QTest.keyClick(win, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
assert "无可导出" in win._status_log.text(), \
    f"无表格页应提示: {win._status_log.text()}"
# 正向路径：切到「日志预警」页（含多个 DataGrid）再导出
QTest.keyClick(win, Qt.Key.Key_6, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
assert win.stack.currentWidget() is win.pages[5], "Ctrl+6 应切到日志预警页"
exported = []
orig_export = DataGrid.export_csv
def _fake_export(self, path=None):
    """替身导出：记录调用并返回假路径（不弹对话框）。"""
    exported.append(path or "AUTO")
    return "fake.csv"
DataGrid.export_csv = _fake_export
try:
    QTest.keyClick(win, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
finally:
    DataGrid.export_csv = orig_export
assert exported, "Ctrl+E 应触发 DataGrid.export_csv"
assert "已导出" in win._status_log.text(), f"状态栏应有导出反馈: {win._status_log.text()}"
QTest.keyClick(win, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
app.processEvents()

# ---- ④ Ctrl+, 模型配置 ----
from futures_quant.ui import ai_settings_dialog as _ais

dlg_opened = []
_orig_ai_exec = _ais.AIConfigDialog.exec
_ais.AIConfigDialog.exec = lambda self: (dlg_opened.append(1), 0)[1]
try:
    QTest.keyClick(win, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
finally:
    _ais.AIConfigDialog.exec = _orig_ai_exec
assert dlg_opened, "Ctrl+, 应打开模型配置对话框"

# ---- ① Ctrl+K 命令面板 ----
palette_opened = []
_orig_pal_exec = CommandPalette.exec
def _fake_exec(self):
    """记录面板并真实 show（隐藏控件无法获得焦点/接受按键事件）。"""
    palette_opened.append(self)
    self.show()
    app.processEvents()
    return 0
CommandPalette.exec = _fake_exec
try:
    QTest.keyClick(win, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
finally:
    CommandPalette.exec = _orig_pal_exec
assert palette_opened, "Ctrl+K 应唤起命令面板"
pal = palette_opened[0]
assert pal.isVisible(), "补丁后面板应真实可见"
labels = [pal._items[i][0] for i in range(len(pal._items))]
assert any("回测中心" in lb for lb in labels), "面板条目应含「页面：回测中心」"
assert any(lb.startswith("品种：RB") for lb in labels), "面板条目应含品种"
# 面板内搜索「回测」并回车执行 → 跳转回测中心页
pal.input.setText("回测")
app.processEvents()
assert pal.listw.count() >= 2, "搜「回测」应命中页面+命令多条目"
first_label = pal.listw.item(0).text()
assert "回测" in first_label, f"首条应含「回测」: {first_label}"
# 模拟 Enter 执行（WidgetShortcut Return，需 input 真实持有焦点）
pal.input.setFocus()
app.processEvents()
QTest.keyClick(pal.input, Qt.Key.Key_Return)
app.processEvents()
assert not pal.isVisible(), "执行后面板应关闭"
assert win.stack.currentWidget() is win.pages[2], "执行「回测中心」条目应切页"
pal.close()

# ---- ⑤ Esc 关浮层 ----
overlay = QDialog()
overlay.show()
app.processEvents()
assert overlay.isVisible()
win._close_overlays()
app.processEvents()
assert not overlay.isVisible(), "Esc 处理器应关闭可见浮层"

win.close()
print("M4-12 SMOKE OK")
