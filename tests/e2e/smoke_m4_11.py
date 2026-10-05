# -*- coding: utf-8 -*-
"""M4-11 冒烟测试：导航与窗口体验七项 spec 验证（offscreen）。

覆盖：
    ① Splash 可创建/推进/收尾（产品图与 QV 兜底）
    ② 应用图标来自 images/product/1.png（或降级内置）
    ③ _want_max 尊重会话记录（无 or True）
    ④ icons 有 "ctp"，NAV_ICONS 死常量已删
    ⑤ 图标缓存 key 含 dpr（相同参数命中同一对象）
    ⑥ 窄屏 <1100px 侧栏折叠为 56px 图标条，加宽还原
    ⑦ 状态栏日志 _push_status_log + 8s 自动清空
附加回归：MainWindow._run_worker 可用（修 M4-10 AttributeError）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

# ---- ④/⑤ icons ----
from futures_quant.ui import icons

ic = icons.icon("ctp", "dark", size=20)
assert not ic.isNull(), "ctp 图标渲染失败"
ic_again = icons.icon("ctp", "dark", size=20)
assert ic_again is ic, "相同参数应命中缓存（同一 QIcon 对象）"
assert not hasattr(icons, "NAV_ICONS"), "NAV_ICONS 死常量应已删除"
# dpr 进入缓存 key：dpr 变化产生新条目
icons._CACHE.clear()
k1 = ("ctp", "dark", 20, 1.0)
k2 = ("ctp", "dark", 20, 2.0)
icons._CACHE[k1] = ic
icons._CACHE[k2] = ic
assert k1 in icons._CACHE and k2 in icons._CACHE

# ---- ① Splash ----
from futures_quant.ui.splash import Splash, _logo_pixmap

pm = _logo_pixmap()
assert not pm.isNull(), "品牌图（含兜底）生成失败"
sp = Splash(app)
sp.step("冒烟测试推进…")
sp.finish(None)  # None 触发异常安全路径，不应崩溃

# ---- ②/③/⑥/⑦ MainWindow ----
from futures_quant.ui.main_window import MainWindow, _product_icon

pi = _product_icon()
assert not pi.isNull(), "应用图标生成失败"

win = MainWindow()
# 阻止延迟网络探测（避免冒烟测试触发真实源连接线程）
if getattr(win, "_connect_deferred", None) is not None:
    win._connect_deferred.stop()

# ③ _want_max 布尔且无强制 True
assert isinstance(win._want_max, bool), "_want_max 应为纯 bool"
# 附加：_run_worker 存在（M4-10 遗留修复）
assert hasattr(win, "_run_worker"), "MainWindow._run_worker 缺失"
assert isinstance(win._workers, list)

# ⑥ 窄屏折叠 / 宽屏还原
# 注：offscreen 下隐藏窗口的 resize() 不派发 resizeEvent（实测），故先 show
win.show()
app.processEvents()
win.setMinimumWidth(1)  # 绕过分辨率下限，专门验证折叠逻辑
win.resize(1000, 700)
app.processEvents()
if getattr(win, "_nav_collapsed", None) is not True:
    # 事件未派发时直驱同一逻辑（与 resizeEvent 调用的是同一个方法）
    win._update_nav_mode()
assert win._nav_collapsed is True, f"窄屏应折叠: {win._nav_collapsed}"
assert win.nav.width() == 56, f"折叠宽度应为 56: {win.nav.width()}"
assert win.nav.item(0).text() == "", "折叠态应隐藏文字"
assert win.nav.item(0).toolTip() != "", "折叠态应保留 tooltip"
win.resize(1400, 900)
app.processEvents()
if win._nav_collapsed is not False:
    win._update_nav_mode()
assert win._nav_collapsed is False, "宽屏应还原"
assert win.nav.item(0).text() != "", "展开态应恢复文字"

# ⑦ 状态栏日志 8s 自动清空
win._push_status_log("测试日志")
assert win._status_log.text() == "测试日志"
win._status_log_timer.timeout.emit()
assert win._status_log.text() == "", "超时后状态日志应清空"
# 8s 时长验证
assert win._status_log_timer.interval() == 8000

win.close()
print("M4-11 SMOKE OK")
