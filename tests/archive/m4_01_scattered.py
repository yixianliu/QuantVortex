"""M4-01 验证：修复页面栈索引错位（P0）。

验收点（对应 UPGRADE_PLAN_V5 M4-01）：
  ① 维护 `self._stack_index: Dict[int,int]`（NAV 下标 → 栈下标）；
  ② `_switch` 改用 `setCurrentWidget(page)`；
  ③ 增加断言：切换后 `stack.currentWidget() is self.pages[idx]`。

文档验收场景：
  · 菜单直接跳「数据管理」→ 主区显示数据页且侧栏高亮一致；
  · 乱序点击 7 个页面后一致。

缺陷根因：
  页面是「首次访问才创建」，而 `QStackedWidget.addWidget` 的入栈顺序由**用户点击
  顺序**决定 → NAV 下标 ≠ 栈下标。旧代码 `stack.setCurrentIndex(idx)` 把 NAV 下标
  当栈下标用，只要不是按 0,1,2… 顺序点就错位（菜单直跳「数据管理」时，栈里可能
  只有 1~2 个 widget，`setCurrentIndex(6)` 直接无效 → 主区仍停在旧页）。

验证手段：
  · offscreen 构造真实 MainWindow；
  · 冷启动直跳末页（数据管理，NAV[6]）—— 这是改造前必然错位的最短复现路径；
  · 乱序遍历全部 7 页，每次都校验「主区 widget + 侧栏高亮 + PAGE_KEY」三者一致；
  · 重复切换到当前页（幂等）与越界切换（安全）；
  · 反证：模拟旧逻辑（setCurrentIndex(NAV 下标)）确认在当前状态下确实会错位，
    证明本用例有判别力、不是恒真断言。
"""
import os
import sys

_TMPDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pytest_tmp")
os.makedirs(_TMPDIR, exist_ok=True)
for _v in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_v] = _TMPDIR
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 会话状态写临时目录，避免污染真实 session_state.json
os.environ["QUANTVORTEX_NO_PERSIST"] = "1"

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from futures_quant.ui.main_window import MainWindow, NAV  # noqa: E402

N_PAGES = len(NAV)
print(f"\nNAV 共 {N_PAGES} 页：" + "、".join(t for t, *_ in NAV))

win = MainWindow()
win.show()
app.processEvents()


def consistent(idx: int) -> tuple:
    """返回 (主区一致, 侧栏一致, KEY 一致, 实际页面key)。"""
    page = win.pages[idx]
    cur = win.stack.currentWidget()
    ok_stack = (page is not None and cur is page)
    ok_nav = (win.nav.currentRow() == idx)
    key = getattr(cur, "PAGE_KEY", None)
    ok_key = (key == NAV[idx][3])
    return ok_stack, ok_nav, ok_key, key


# =========================================================================
# ① 映射表与切换方式
# =========================================================================
print("\n=== ① _stack_index 映射 + setCurrentWidget 切换 ===")

import inspect  # noqa: E402
src = inspect.getsource(MainWindow)
check("①维护 _stack_index（NAV 下标 → 栈下标）",
      "_stack_index" in src and isinstance(getattr(win, "_stack_index", None), dict))
check("①_switch 改用 setCurrentWidget(page)",
      "setCurrentWidget(page)" in src)
check("①_switch 保留切换后断言",
      "assert" in src and "currentWidget() is page" in src)
check("①启动即登记首页栈下标", win._stack_index.get(0) == win.stack.indexOf(win.pages[0]),
      f"_stack_index={win._stack_index}")


# =========================================================================
# ② 文档验收场景 A：冷启动直接跳「数据管理」
# =========================================================================
print("\n=== ② 菜单直跳「数据管理」（改造前必然错位的最短复现路径） ===")

DATA_IDX = next(i for i, (_, _, _, k) in enumerate(NAV) if k == "data")
check("②冷启动时栈内只有 1 个已建页面（延迟初始化生效）",
      win.stack.count() == 1, f"stack.count()={win.stack.count()}")

ok = win._goto_page("data")
ok_stack, ok_nav, ok_key, key = consistent(DATA_IDX)
check("②主区显示的正是「数据管理」页", ok_stack, f"currentWidget PAGE_KEY={key}")
check("②侧栏高亮同步到「数据管理」", ok_nav,
      f"nav.currentRow()={win.nav.currentRow()} 期望 {DATA_IDX}")
check("②PAGE_KEY 一致", ok_key, f"key={key} 期望 {NAV[DATA_IDX][3]}")
check("②_goto_page 返回成功", ok is True)
check("②栈下标登记正确",
      win._stack_index.get(DATA_IDX) == win.stack.indexOf(win.pages[DATA_IDX]),
      f"NAV[{DATA_IDX}] → 栈 {win._stack_index.get(DATA_IDX)}")


# =========================================================================
# ③ 文档验收场景 B：乱序点击全部页面
# =========================================================================
print("\n=== ③ 乱序点击 7 个页面后主区/侧栏一致 ===")

ORDER = [3, 1, 6, 0, 5, 2, 4, 6, 0, 3]
bad = []
for idx in ORDER:
    win._show_page(idx)
    app.processEvents()
    ok_stack, ok_nav, ok_key, key = consistent(idx)
    if not (ok_stack and ok_nav and ok_key):
        bad.append((idx, NAV[idx][0], ok_stack, ok_nav, ok_key, key))
check(f"③乱序遍历 {len(ORDER)} 次切换全部一致", not bad, str(bad[:3]))
check("③已建页面数 == 访问过的去重页面数",
      win.stack.count() == len(set(ORDER) | {0, DATA_IDX}),
      f"stack.count()={win.stack.count()}")
check("③_stack_index 覆盖全部已建页面且值正确",
      all(win._stack_index[i] == win.stack.indexOf(win.pages[i])
          for i in win._stack_index if win.pages[i] is not None))

# 顺序遍历一遍（0..N-1）也不应错位
bad2 = []
for idx in range(N_PAGES):
    win._show_page(idx)
    app.processEvents()
    ok_stack, ok_nav, ok_key, _k = consistent(idx)
    if not (ok_stack and ok_nav and ok_key):
        bad2.append(idx)
check("③顺序遍历全部页面同样一致", not bad2, f"错位={bad2}")


# =========================================================================
# ④ 幂等 / 越界 / 反证
# =========================================================================
print("\n=== ④ 幂等、越界与反证（证明用例有判别力） ===")

cur_idx = win.nav.currentRow()
before = win.stack.currentWidget()
win._show_page(cur_idx)          # 重复切到当前页
app.processEvents()
check("④重复切到当前页幂等（不重建、不错位）",
      win.stack.currentWidget() is before and win.pages[cur_idx] is before)

check("④越界下标被安全拒绝（不抛异常、不改变当前页）",
      win._show_page(-1) is False and win._show_page(N_PAGES) is False
      and win.stack.currentWidget() is before)
check("④未知 page key 被安全拒绝", win._goto_page("__no_such_page__") is False)

# 反证：用旧逻辑（NAV 下标当栈下标）确实会错位。
# 注意必须挑一个「栈下标 ≠ NAV 下标」的页——首页 NAV[0] 恰好也是栈 0，
# 用它反证会得到恒真结论（无判别力）。
_shifted = [i for i, v in win._stack_index.items() if v != i]
check("④前置：乱序访问后确实存在「栈下标 ≠ NAV 下标」的页（错位的土壤）",
      bool(_shifted), f"错位映射={ {i: v for i, v in win._stack_index.items() if v != i} }")
if _shifted:
    nav_idx = _shifted[0]
    win.stack.setCurrentIndex(nav_idx)      # 旧实现写法
    app.processEvents()
    stale_mismatch = win.stack.currentWidget() is not win.pages[nav_idx]
    check("④反证：旧写法 setCurrentIndex(NAV下标) 确实错位",
          stale_mismatch,
          f"NAV[{nav_idx}]={NAV[nav_idx][0]}（栈下标 {win._stack_index[nav_idx]}）"
          f" 却显示 {getattr(win.stack.currentWidget(), 'PAGE_KEY', None)}")
    # 复位，确认新写法能纠正回来
    win._show_page(nav_idx)
    app.processEvents()
    check("④新写法能把错位纠正回来",
          win.stack.currentWidget() is win.pages[nav_idx])


# =========================================================================
# 汇总
# =========================================================================
print("\n" + "=" * 60)
print(f"M4-01 验证结果：PASS={len(PASS)}  FAIL={len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print(f"  - {f}")
print("=" * 60)
try:
    win.close()
except Exception:  # noqa: BLE001
    pass
sys.exit(1 if FAIL else 0)
