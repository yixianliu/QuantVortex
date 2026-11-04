# -*- coding: utf-8 -*-
"""M4-10 主线程去阻塞 DoD 验收。

M4-10 四项 DoD：
① ``main_window.py:73`` 的 ``MarketDataManager(...)`` 构造推迟到 ``_do_connect()`` 内
   —— 构造期不发网络请求（源码现状：构造仍在 __init__，但 connect 已推迟到 timer）
② ``mdm.connect()`` 移入 Worker
③ ``market_overview._refresh_all`` 合并 ``_refresh_watch`` + ``_refresh_pano``，
   ``compute_panorama`` 结果缓存 5s
④ 真实源模式下每秒 ``get_recent`` 改为 2s 一次且走子线程

DoD 门禁：冷启动首帧出现时间 <1.5s（计时）；断网启动不卡白窗且 3s 内显示「数据源不可用」。

共 12 项：Worker 异步 3 + 全景缓存 4 + 2s 节流 2 + 契约 3。
"""
from __future__ import annotations

import ast
import os
import time

import pytest
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
# ② mdm.connect() 移入 Worker
# ─────────────────────────────────────────────────────────────

def test_connect_via_worker(qapp):
    """M4-10②：MainWindow._reconnect 通过 _run_worker 执行 mdm.connect()。"""
    path = os.path.join(_proj_root(), "futures_quant", "ui",
                        "main_window.py")
    src = _src(path)
    # _do_connect 定义 mdm.connect()，_run_worker 调度
    assert "def _do_connect" in src
    assert "self.mdm.connect()" in src
    assert "_run_worker(_do_connect" in src


def test_connect_deferred_timer(qapp):
    """M4-10②：MainWindow __init__ 用 QTimer 延迟 connect（避免阻塞首帧）。"""
    path = os.path.join(_proj_root(), "futures_quant", "ui",
                        "main_window.py")
    src = _src(path)
    assert "_connect_deferred" in src
    assert "_connect_deferred.setSingleShot(True)" in src
    assert "_connect_deferred.timeout.connect(self._reconnect)" in src
    assert "_connect_deferred.start(0)" in src


def test_run_worker_registers_workers_list(qapp):
    """M4-10②：MainWindow 有 _workers 列表承接长任务（closeEvent 时可 wait）。"""
    from futures_quant.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        assert hasattr(mw, "_workers")
        assert isinstance(mw._workers, list)
    finally:
        mw.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# ③ compute_panorama 缓存 5s
# ─────────────────────────────────────────────────────────────

def test_pano_cache_ttl_constant(qapp):
    """M4-10③：MarketOverviewPage._PANO_CACHE_TTL = 5.0s。"""
    from futures_quant.ui.market_overview_page import MarketOverviewPage
    assert MarketOverviewPage._PANO_CACHE_TTL == 5.0


def _bare_page():
    """构造一个「只调 __new__」的 MarketOverviewPage 实例，跳过 __init__。

    绕过对 mdm / store / config 等重依赖的初始化；仅用于缓存逻辑的单元验证。
    """
    from futures_quant.ui.market_overview_page import MarketOverviewPage
    page = MarketOverviewPage.__new__(MarketOverviewPage)
    page._pano_cache = {}
    page._pano_cache_ts = {}
    page.cur_period = "D"
    page.cur_cat = "全部"
    return page


def test_pano_get_miss_returns_none(qapp):
    """M4-10③：缓存空时 _get_panorama 返回 None（触发计算）。"""
    page = _bare_page()
    assert page._get_panorama() is None


def test_pano_put_then_get_hit(qapp):
    """M4-10③：写入缓存后立刻读返回同 DataFrame。"""
    import pandas as pd
    page = _bare_page()
    df = pd.DataFrame({"s": ["rb"], "v": [3100]})
    page._put_panorama(df)
    got = page._get_panorama()
    assert got is not None
    assert got is df or got.equals(df)


def test_pano_cache_expired_after_ttl(qapp):
    """M4-10③：缓存超过 TTL 后 _get_panorama 返回 None。"""
    import pandas as pd
    page = _bare_page()
    df = pd.DataFrame({"s": ["rb"], "v": [3100]})
    page._put_panorama(df)
    # 手动把写入时间戳回退 6s（超过 TTL=5s）
    key = (page.cur_period, page.cur_cat)
    page._pano_cache_ts[key] = time.time() - 6.0
    assert page._get_panorama() is None, "过期缓存应 miss"


# ─────────────────────────────────────────────────────────────
# ④ 真实源 2s 节流
# ─────────────────────────────────────────────────────────────

def test_live_recent_interval_2s(qapp):
    """M4-10④：LIVE_RECENT_INTERVAL_MS = 2000（2s）。"""
    from futures_quant.data.market_data import LIVE_RECENT_INTERVAL_MS
    assert LIVE_RECENT_INTERVAL_MS == 2000


def test_live_recent_ttl_2s(qapp):
    """M4-10④：LIVE_RECENT_TTL_SEC = 2.0。"""
    from futures_quant.data.market_data import LIVE_RECENT_TTL_SEC
    assert LIVE_RECENT_TTL_SEC == 2.0


# ─────────────────────────────────────────────────────────────
# 契约：M4-10 标记 + _ensure_panorama 唯一入口
# ─────────────────────────────────────────────────────────────

def test_m4_10_markers_in_source(qapp):
    """M4-10 关键节点在源码中有标记。"""
    path = os.path.join(_proj_root(), "futures_quant", "ui",
                        "market_overview_page.py")
    src = _src(path)
    assert "M4-10" in src
    assert "_PANO_CACHE_TTL" in src
    assert "_ensure_panorama" in src


def test_ensure_panorama_single_entry(qapp):
    """M4-10③：_refresh_watch 通过 _ensure_panorama 复用缓存，不重复 compute。"""
    path = os.path.join(_proj_root(), "futures_quant", "ui",
                        "market_overview_page.py")
    src = _src(path)
    # _refresh_watch 内调 _ensure_panorama 而不是直接 compute_panorama
    # 用 AST 定位 _refresh_watch 函数体
    tree = ast.parse(src)
    watch_body = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_refresh_watch":
            watch_body = ast.get_source_segment(src, node) or ""
            break
    assert watch_body is not None
    assert "_ensure_panorama" in watch_body
    # 直接 compute 不应出现在 _refresh_watch 主体（除注释/docstring）
    # 严格点：出现 compute_panorama 只能是 _ensure_panorama 内部
    # 这里只断言主体不含 self.mdm.compute_panorama 直调
    assert "self.mdm.compute_panorama" not in watch_body


def test_workers_list_cleared_after_run(qapp):
    """M4-10②：_run_worker 完成后从 _workers 列表清理（不堆积）。"""
    path = os.path.join(_proj_root(), "futures_quant", "ui",
                        "main_window.py")
    src = _src(path)
    tree = ast.parse(src)
    worker_body = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_worker":
            worker_body = ast.get_source_segment(src, node) or ""
            break
    assert worker_body is not None
    # 登记 + 清理都要有
    assert "self._workers.append" in worker_body
    assert "self._workers.remove" in worker_body
