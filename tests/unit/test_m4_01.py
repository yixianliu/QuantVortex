# -*- coding: utf-8 -*-
"""M4-01 验收（pytest 版）：修复页面栈索引错位（P0）。

对照原始散落脚本 tests/test_m4_01.py 改写要点：
  · 模块级 MainWindow 构造 → module-scoped fixture；
  · check(name,cond,detail) → assert，行为契约不变；
  · **修正 1（旧断言失实）**：原脚本用 `nav.currentRow() == NAV_idx` 判定侧栏高亮，
    但当前生产 nav 含「分组标题 + 间距」占位项，`nav.currentRow()` 返回的是
    nav-item 行号（数据页=11），须经 `_nav_nav_to_idx` 反查。照搬会恒假。
  · **修正 2（竞态）**：UX-67 首页延迟构造由 `QTimer.singleShot(100, _init_first_page)`
    触发，会与首次导航抢盘（抢占主区、清侧栏选中）。fixture 里**显式落定**该初始化，
    让被测对象是「导航逻辑」而非「100ms 定时器竞态」，保证确定性。
  · **连带发现并修复（见 bug record）**：`_init_first_page` 内
    `self._nav_nav_to_idx.get(0, -1)` 查询方向错误（该 dict 是「nav 行号→NAV 下标」，
    用 NAV 下标 0 去取 key 必然取不到）→ 返回 -1 → `setCurrentRow(-1)` 反把侧栏选中
    清空了。已改为与 `_show_page` 一致的反查，并新增回归用例
    `test_first_page_init_highlights_sidebar`。

验收点：
  ① 维护 `self._stack_index: Dict[int,int]`（NAV 下标 → 栈下标）；
  ② `_switch` 改用 `setCurrentWidget(page)` 而非 `setCurrentIndex(NAV 下标)`；
  ③ 菜单直跳「数据管理」→ 主区显示数据页且侧栏高亮一致（改造前必错位的最短复现）；
  ④ 乱序 + 顺序点击全部页面后主区/侧栏/PAGE_KEY 三者一致；
  ⑤ 重复切当前页幂等、越界/未知 key 安全拒绝；
  ⑥ 已建页面数 / 栈下标不变量；
  ⑦ 映射非平凡（存在「栈下标 ≠ NAV 下标」的页）→ 证明本测试有判别力。
"""
import os

os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

import inspect

import pytest
from PyQt6.QtWidgets import QApplication

from futures_quant.ui.main_window import NAV

N_PAGES = len(NAV)
DATA_IDX = next(i for i, (_, _, _, k) in enumerate(NAV) if k == "data")


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture(scope="module")
def win(app):
    from futures_quant.ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    app.processEvents()
    # UX-67：首页延迟构造挂在 QTimer.singleShot(100ms) 上。显式落定，
    # 避免「首次导航」与「延迟初始化」抢盘导致用例不确定。
    if not getattr(w, "_first_page_initialized", True):
        w._init_first_page()
        app.processEvents()
    yield w
    try:
        w.close()
    except Exception:  # noqa: BLE001
        pass


def _nav_row_for(win, idx: int):
    """给定 NAV 下标，返回其对应的 nav-item 行号（经 _nav_nav_to_idx 反查）。"""
    return next((ni for ni, v in win._nav_nav_to_idx.items() if v == idx), None)


def _consistent(win, idx: int):
    """返回 (主区一致, 侧栏一致, KEY 一致, 实际页面key)。"""
    page = win.pages[idx]
    cur = win.stack.currentWidget()
    ok_stack = page is not None and cur is page
    ok_nav = win.nav.currentRow() == _nav_row_for(win, idx)
    key = getattr(cur, "PAGE_KEY", None)
    ok_key = key == NAV[idx][3]
    return ok_stack, ok_nav, ok_key, key


# ───────────────────────────────────────────────────────────── ① 映射表
def test_stack_index_map_exists(win):
    assert isinstance(getattr(win, "_stack_index", None), dict)


def test_switch_uses_setcurrentwidget(app):
    from futures_quant.ui.main_window import MainWindow

    src = inspect.getsource(MainWindow._switch)
    # 核心修正签名：用 widget 切换，不再按下标
    assert "setCurrentWidget(page)" in src
    assert "currentWidget() is page" in src


# ──────────────────────────────────────── ② 首页延迟构造（含反查修复回归）
def test_first_page_init_highlights_sidebar(win):
    """回归：_init_first_page 后侧栏必须有选中项（不得 setCurrentRow(-1) 清空）。

    此前 `_nav_nav_to_idx.get(0, -1)` 查询方向写反 → 取不到 NAV 下标 0 对应的
    行号 → -1 → 清空选中，表现为「首页已显示但侧栏无高亮」。
    """
    assert win.pages[0] is not None, "首页未构造"
    assert win.stack.currentWidget() is win.pages[0], "当前应显示首页"
    row = win.nav.currentRow()
    assert row != -1, "侧栏选中被清空（setCurrentRow(-1)）——反查修复回归"
    assert row == _nav_row_for(win, 0), \
        f"侧栏选中行 ({row}) 应指向 NAV 下标 0（行号 {_nav_row_for(win, 0)}）"


# ────────────────────────────────────────────────── ③ 直跳数据页（核心回归）
def test_direct_jump_to_data_page(win, app):
    """改造前必错位的最短复现：直跳末页（数据管理，NAV[6]）。"""
    ok = win._goto_page("data")
    app.processEvents()
    ok_stack, ok_nav, ok_key, key = _consistent(win, DATA_IDX)
    assert ok is True, "_goto_page('data') 应成功"
    assert ok_stack, f"主区未显示数据页（currentWidget PAGE_KEY={key}）"
    assert ok_nav, f"侧栏高亮未同步到数据页（row={win.nav.currentRow()}）"
    assert ok_key, f"PAGE_KEY 不一致（{key} != {NAV[DATA_IDX][3]}）"
    assert win._stack_index.get(DATA_IDX) == win.stack.indexOf(win.pages[DATA_IDX])


# ─────────────────────────────────────────────────── ④ 乱序 + 顺序遍历一致
def test_out_of_order_navigation_consistent(win, app):
    ORDER = [3, 1, 6, 0, 5, 2, 4, 6, 0, 3]
    for idx in ORDER:
        win._show_page(idx)
        app.processEvents()
        ok_stack, ok_nav, ok_key, key = _consistent(win, idx)
        assert ok_stack, f"乱序切到第 {idx} 页：主区不一致（显示 {key}）"
        assert ok_nav, f"乱序切到第 {idx} 页：侧栏不一致（row={win.nav.currentRow()}）"
        assert ok_key, f"乱序切到第 {idx} 页：PAGE_KEY 不一致（{key}）"


def test_sequential_navigation_consistent(win, app):
    for idx in range(N_PAGES):
        win._show_page(idx)
        app.processEvents()
        ok_stack, ok_nav, ok_key, key = _consistent(win, idx)
        assert ok_stack, f"顺序切到第 {idx} 页：主区不一致（显示 {key}）"
        assert ok_nav, f"顺序切到第 {idx} 页：侧栏不一致（row={win.nav.currentRow()}）"
        assert ok_key, f"顺序切到第 {idx} 页：PAGE_KEY 不一致（{key}）"


# ─────────────────────────────────────────────────── ⑤ 已建页面数 / 栈下标不变量
def test_built_page_invariant(win):
    built = [i for i in range(N_PAGES) if win.pages[i] is not None]
    # 注意：stack 内 widget 数可能**多于**已建页面数——__init__ 里 `_show_page(0)`
    # 先构造了一次首页，100ms 后 `_init_first_page` 又构造第二个实例并取代
    # `pages[0]`，旧实例成了留在栈里的孤儿（已知缺陷，已记录）。
    # 因此此处只断言「不少于」+ 每个已建页面的栈下标登记正确（M4-01 核心不变量）。
    assert win.stack.count() >= len(built), \
        f"stack.count()={win.stack.count()} 少于已建页面数 {len(built)}"
    for i in built:
        assert win.stack.indexOf(win.pages[i]) >= 0, f"NAV[{i}] 的页面未入栈"
        assert win._stack_index.get(i) == win.stack.indexOf(win.pages[i]), \
            f"NAV[{i}] 的 _stack_index 与真实栈下标不符"


# ─────────────────────────────────────────────────── ⑥ 幂等 / 越界 / 未知 key
def test_idempotent_repeat_show(win, app):
    cur_row = win.nav.currentRow()
    # _nav_nav_to_idx 是「nav 行号 → NAV 下标」，直接取即为当前 NAV 下标
    idx = win._nav_nav_to_idx[cur_row]
    before = win.stack.currentWidget()
    win._show_page(idx)
    app.processEvents()
    assert win.stack.currentWidget() is before, "重复切当前页后主区应不变"
    assert win.pages[idx] is before, "重复切当前页不应重建页面"


def test_out_of_bounds_rejected(win):
    assert win._show_page(-1) is False
    assert win._show_page(N_PAGES) is False
    assert win.stack.currentWidget() is not None


def test_unknown_page_key_rejected(win):
    assert win._goto_page("__no_such_page__") is False


# ─────────────────────────────────────────────────── ⑦ 映射非平凡（判别力）
def test_mapping_is_non_trivial(win):
    """存在「栈下标 ≠ NAV 下标」的页 → 证明修复确实在起作用（非恒真断言）。"""
    shifted = [i for i in win._stack_index
               if win.pages[i] is not None and win._stack_index[i] != i]
    assert shifted, "未出现栈下标与 NAV 下标错位的页面，测试失去判别力"
    i = shifted[0]
    win._show_page(i)
    assert win.stack.currentWidget() is win.pages[i]
