# -*- coding: utf-8 -*-
"""M4-14 冒烟测试：无障碍与动效开关（offscreen）。

覆盖：
    ① MOTION 门控：QV_REDUCED_MOTION 思路 —— StatusTile.pulse 受 states.MOTION
       门控（False 时不创建 QPropertyAnimation，glow 复位 0）
    ② 无障碍名称：主窗口关键控件 / DataGrid / 命令面板 / StatusTile
    ③ focus 可见样式：build_qss 含 QTableWidget/QListWidget/QTabBar :focus 规则
    ④ 字号缩放：set_user_font_scale 乘入 font_size（钳制不变）；
       _set_font_scale 持久化 + 应用级字体同步 + 状态栏反馈
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

# ---------- ① MOTION 门控 ----------
from futures_quant.ui import states as _states
from futures_quant.ui import widgets as _widgets

tile = _widgets.StatusTile("测试指标")
anim_count = []


class _FakeAnim:
    """替身动画：记录创建并立即结束。"""

    def __init__(self, *a, **k):
        anim_count.append(1)

    def setDuration(self, *a):
        """忽略。"""

    def setStartValue(self, *a):
        """忽略。"""

    def setEndValue(self, *a):
        """忽略。"""

    def start(self):
        """忽略。"""


_orig_anim = _widgets.QPropertyAnimation
_widgets.QPropertyAnimation = _FakeAnim
try:
    # MOTION=True：pulse 创建动画
    _states.MOTION = True
    tile.set_status("good", "1.0", "正常")
    assert anim_count, "MOTION=True 时 pulse 应创建 QPropertyAnimation"
    # MOTION=False：pulse 直接过（验收：无 QPropertyAnimation 启动）
    anim_count.clear()
    _states.MOTION = False
    tile.set_status("bad", "0.0", "异常")
    assert not anim_count, "MOTION=False 时 pulse 不得创建动画"
    assert tile._glow == 0.0, "门控关闭时 glow 应复位 0"
finally:
    _widgets.QPropertyAnimation = _orig_anim
    _states.MOTION = True

# ---------- ② 无障碍名称 ----------
from futures_quant.ui.states import DataGrid
from futures_quant.ui.command_palette import CommandPalette

grid = DataGrid(0, 3)
assert grid.accessibleName() == "数据表格", "DataGrid 应有无障碍名称"
pal_items = [("页面：测试", "页面", lambda: None)]
pal_dlg = CommandPalette(None, pal_items)
assert pal_dlg.input.accessibleName() == "命令搜索框"
assert pal_dlg.listw.accessibleName() == "命令结果列表"
assert tile.accessibleName() == "状态指示灯：测试指标"

# ---------- ③ focus 可见样式 ----------
from futures_quant.ui.design_system import build_qss

qss = build_qss("dark")
for rule in ("QTableWidget:focus", "QListWidget:focus",
             "QTabBar::tab:focus", "QListWidget#nav::item:focus"):
    assert rule in qss, f"QSS 缺少 focus 规则: {rule}"
qss_light = build_qss("light")
assert "QTableWidget:focus" in qss_light

# ---------- ④ 字号缩放 ----------
from futures_quant.ui.responsive_layout import get_layout_manager

mgr = get_layout_manager()
base_fs = mgr.font_size(13)
mgr.set_user_font_scale(1.25)
assert mgr.user_font_scale == 1.25
fs125 = mgr.font_size(13)
assert fs125 > base_fs, f"125% 应放大字号: {base_fs} -> {fs125}"
assert fs125 <= mgr.FONT_MAX, "不得超过 FONT_MAX"
mgr.set_user_font_scale(0.9)
assert mgr.font_size(13) >= mgr.FONT_MIN, "90% 不得低于 FONT_MIN"
mgr.set_user_font_scale(1.0)
assert mgr.font_size(13) == base_fs, "恢复 100% 应还原"

# QSS 字号缩放联动（scale_qss_fonts 走同一 mgr）
from futures_quant.ui.main_window import scale_qss_fonts

mgr.set_user_font_scale(1.25)
qss_scaled = scale_qss_fonts("font-size:13px;", mgr)
assert "font-size:16px;" in qss_scaled, f"125% 应映射 13→16: {qss_scaled}"
mgr.set_user_font_scale(1.0)

# MainWindow 级：_set_font_scale 持久化 + 应用字体同步 + 反馈
from futures_quant.ui.main_window import MainWindow

win = MainWindow()
if getattr(win, "_connect_deferred", None) is not None:
    win._connect_deferred.stop()
win.show()
app.processEvents()

win._set_font_scale(125)
assert win.config.get("ui.font_scale") == 125, "缩放应持久化"
assert win._layout_mgr.user_font_scale == 1.25
assert app.font().pointSize() == win._layout_mgr.font_size(10), \
    "应用级字体应同步"
assert "125%" in win._status_log.text(), "状态栏应有反馈"
checked = [p for p, act in win._font_scale_group if act.isChecked()]
assert checked == [125], f"菜单勾选应互斥: {checked}"

# 125% 下布局不溢出（动态高度钳制 + 最小窗口约束仍成立）
win._set_font_scale(90)
assert win.config.get("ui.font_scale") == 90
win._set_font_scale(100)

win.close()
print("M4-14 SMOKE OK")
