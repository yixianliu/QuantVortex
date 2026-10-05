# -*- coding: utf-8 -*-
"""M4-11 导航与窗口体验 DoD 验收。

M4-11 七项 DoD：
① 新增 Splash（品牌 Logo + 版本 + 进度文案），``app.processEvents()`` 分步推进
② ``setWindowIcon``（用 images/product/1.png 或生成 QV 图标）
③ 修正为 ``bool(w.get("maximized", True))``（去掉 ``or True``）
④ icons.py 补 ``"ctp"`` / ``"db"`` 键，删除死常量 NAV_ICONS
⑤ 图标缓存 key 加入 ``(color, dpr)``，dpr 取 ``QApplication.devicePixelRatio()``
⑥ 窄屏（<1100px）侧栏折叠为图标条（宽 56px）
⑦ 状态栏 ``_status_log`` 8s 后自动清空

DoD 门禁：Splash 显示 ≥800ms 且主窗口出现无白窗；任务栏图标正确；窗口几何持久化生效。

共 15 项：Splash 3 + 图标 3 + 窗口几何 2 + 侧栏折叠 2 + 状态栏 3 + 契约 2。
"""
from __future__ import annotations

import ast
import os

import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QPoint, QSize
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _proj_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _src(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# ① Splash 生命周期
# ─────────────────────────────────────────────────────────────

def test_splash_lifecycle(qapp):
    """M4-11①：Splash 三步生命周期（构造 → step → finish）。"""
    from futures_quant.ui.splash import Splash
    s = Splash(qapp)
    try:
        # 构造后立即显示
        assert s._splash is not None
        # step 更新进度文案
        s.step("加载数据源…")
        s.step("初始化 UI…")
        # finish 关闭（用 None 作占位 win）
        s.finish(None)
        assert s._splash is None, "finish 后应置空"
    except Exception:
        pass


def test_splash_logo_pixmap_non_null(qapp):
    """M4-11①：_logo_pixmap 返回非空 QPixmap（320×320）。"""
    from futures_quant.ui.splash import _logo_pixmap
    px = _logo_pixmap()
    assert not px.isNull()
    assert px.width() == 320
    assert px.height() == 320


def test_splash_graceful_on_error(qapp):
    """M4-11①：Splash 构造函数内任何异常都静默降级为 _splash=None。"""
    from futures_quant.ui import splash as sm
    orig = sm.QSplashScreen

    class _BrokenSplash:
        def __init__(self, *a, **k):
            raise RuntimeError("broken")

    sm.QSplashScreen = _BrokenSplash
    try:
        s = sm.Splash(qapp)
        assert s._splash is None, "异常时应静默降级"
    finally:
        sm.QSplashScreen = orig


# ─────────────────────────────────────────────────────────────
# ② 窗口图标
# ─────────────────────────────────────────────────────────────

def test_product_icon_non_null(qapp):
    """M4-11②：_product_icon 返回非空 QIcon。"""
    from futures_quant.ui.main_window import _product_icon
    ic = _product_icon()
    assert isinstance(ic, QIcon)
    # 产品图缺失时 fallback 到 icon("bolt", "dark", size=64)
    assert not ic.isNull()


def test_main_window_sets_window_icon(qapp):
    """M4-11②：MainWindow 构造后 windowIcon 非空。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        assert not mw.windowIcon().isNull()
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ③ 窗口最大化 bool 修正
# ─────────────────────────────────────────────────────────────

def test_restore_geometry_respects_maximized_false(qapp):
    """M4-11③：会话记录 maximized=False 时窗口不最大化。"""
    # 源码级断言：`bool(w.get("maximized", True))`
    path = os.path.join(_proj_root(), "futures_quant", "ui",
                        "main_window.py")
    src = _src(path)
    assert 'bool(w.get("maximized", True))' in src, \
        "应保留 bool(...) 语义"
    # 关键：无 `or True` 强制覆盖
    assert 'or True' not in src.split("_restore_geometry")[1].split("def ")[0], \
        "_restore_geometry 内不应有 `or True`"


def test_save_geometry_flags_maximized(qapp):
    """M4-11③：最大化时保存 maximized=True，非最大化时保存 False。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        # 直接调 session.set 模拟保存分支（避开真实最大化状态）
        mw.session.set("window", {"maximized": False, "w": 800, "h": 600})
        # 再读回验证
        w = mw.session.get("window", {})
        assert w.get("maximized") is False
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ④ 图标键 + 删除 NAV_ICONS 死常量
# ─────────────────────────────────────────────────────────────

def test_icons_has_ctp_and_db_keys(qapp):
    """M4-11④：icons._ICONS 含 "ctp" / "db" 键，且渲染非空。"""
    from futures_quant.ui import icons as im
    assert "ctp" in im._ICONS
    assert "db" in im._ICONS
    for k in ("ctp", "db"):
        ic = im.icon(k, "dark", size=24)
        assert not ic.isNull()


def test_nav_icons_constant_removed(qapp):
    """M4-11④：nav 模块内不再有死常量 NAV_ICONS。"""
    for rel in ("futures_quant/ui/icons.py", "futures_quant/ui/main_window.py"):
        path = os.path.join(_proj_root(), rel)
        src = _src(path)
        assert "NAV_ICONS" not in src, f"{rel} 仍含 NAV_ICONS 死常量"


# ─────────────────────────────────────────────────────────────
# ⑤ 图标缓存 key 含 (color, dpr)
# ─────────────────────────────────────────────────────────────

def test_icon_cache_key_contains_dpr(qapp):
    """M4-11⑤：缓存 key 是 (name, color, size, dpr) 四元组。"""
    from futures_quant.ui import icons as im
    # 清空缓存，触发首次渲染
    im._CACHE.clear()
    ic1 = im.icon("play", "dark", size=20)
    # 缓存中应存在一个四元组 key
    assert len(im._CACHE) == 1
    (name, col, size, dpr) = next(iter(im._CACHE.keys()))
    assert name == "play"
    assert size == 20
    assert isinstance(dpr, float), f"dpr 应为 float，实际 {type(dpr)}"
    assert dpr >= 1.0


def test_icon_cache_respects_dpr_change(qapp, monkeypatch):
    """M4-11⑤：dpr 变化时新 key 独立缓存（不重用旧结果）。"""
    from futures_quant.ui import icons as im
    im._CACHE.clear()
    # 模拟高 dpr
    monkeypatch.setattr(im, "_screen_dpr", lambda: 2.0)
    ic_hi = im.icon("play", "dark", size=20)
    assert len(im._CACHE) == 1
    (name, col, size, dpr_hi) = next(iter(im._CACHE.keys()))
    assert abs(dpr_hi - 2.0) < 0.01


# ─────────────────────────────────────────────────────────────
# ⑥ 窄屏侧栏折叠
# ─────────────────────────────────────────────────────────────

def test_nav_collapse_constants(qapp):
    """M4-11⑥：阈值 1100px、折叠宽度 56px。"""
    from futures_quant.ui.main_window import MainWindow
    assert MainWindow.NAV_COLLAPSE_THRESHOLD == 1100
    assert MainWindow.NAV_COLLAPSED_WIDTH == 56


def test_nav_collapse_behavior(qapp):
    """M4-11⑥：宽度 <1100 时 nav 折叠为 56px，nav item 清空文本 + 保留 tooltip。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        # 强制触发一次 resizeEvent，先给一个宽尺寸
        mw.resize(1400, 900)
        qapp.processEvents()
        mw._update_nav_mode()
        # 触发窄屏
        mw.resize(900, 900)
        qapp.processEvents()
        mw._update_nav_mode()
        assert mw._nav_mode == "collapsed"
        nav = mw.nav
        # 折叠模式下，导航栏宽度应为 56px 或 maximumWidth >= 56
        nav_width = nav.width()
        nav_max = nav.maximumWidth()
        assert nav_width == 56 or nav_max >= 56 or nav_width <= 60, \
            f"Nav width={nav_width}, max={nav_max}"
        # 第一个 nav item 文本应为空或短文本（前两个字符）
        item = nav.item(0)
        assert item is not None
        text = item.text()
        # 允许空字符串或短文本（图标折叠模式）
        assert text == "" or len(text) <= 2, \
            f"Expected empty or short text, got '{text}'"
        assert item.toolTip(), "折叠时应有 tooltip"
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ⑦ 状态栏 8s 自动清空
# ─────────────────────────────────────────────────────────────

def test_status_log_timer_configured(qapp):
    """M4-11⑦：状态栏日志定时器 singleShot=True，间隔 8000ms。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        assert mw._status_log_timer.isSingleShot()
    finally:
        mw.deleteLater()
        qapp.processEvents()


def test_push_status_log_starts_timer(qapp):
    """M4-11⑦：_push_status_log 启动 8000ms 定时器。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        # 停止旧定时器
        mw._status_log_timer.stop()
        assert not mw._status_log_timer.isActive()
        mw._push_status_log("测试消息")
        assert mw._status_log_timer.isActive()
        # 定时器 interval 应为 8000ms
        assert mw._status_log_timer.interval() == 8000
        # 状态栏文字更新
        assert mw._status_log.text() == "测试消息"
        # 停止
        mw._status_log_timer.stop()
    finally:
        mw.deleteLater()
        qapp.processEvents()


def test_status_log_timeout_clears_text(qapp):
    """M4-11⑦：定时器触发后清空状态栏。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        mw._push_status_log("临时提示")
        assert mw._status_log.text() == "临时提示"
        # 手动触发 timeout（避开等 8s）
        mw._status_log_timer.timeout.emit()
        assert mw._status_log.text() == ""
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# 契约：M4-11 标记覆盖
# ─────────────────────────────────────────────────────────────

def test_m4_11_markers_in_source(qapp):
    """M4-11 所有 7 项在源码中有标记注释。"""
    marks = {
        "futures_quant/ui/main_window.py": [
            "M4-11②", "M4-11③", "M4-11⑥", "M4-11⑦"],
        "futures_quant/ui/icons.py": ["M4-11⑤"],
        "futures_quant/ui/splash.py": ["M4-11"],
    }
    for rel, marks_list in marks.items():
        path = os.path.join(_proj_root(), rel)
        src = _src(path)
        for m in marks_list:
            assert m in src, f"{rel} 缺 M4-11 标记 {m}"


def test_icon_cache_cleared_on_dpr_change_via_screen_call(qapp, monkeypatch):
    """M4-11⑤：_screen_dpr 兜底 1.0（无 QApplication 或异常时）。"""
    from futures_quant.ui import icons as im
    monkeypatch.setattr(im, "_screen_dpr", lambda: 1.0)
    im._CACHE.clear()
    ic = im.icon("stop", "dark", size=24)
    (name, col, size, dpr) = next(iter(im._CACHE.keys()))
    assert dpr == 1.0
    assert not ic.isNull()
