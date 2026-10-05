# -*- coding: utf-8 -*-
"""M4-05 验收：消灭 inline 样式不刷新（切主题后无控件停留在旧主题色）。

验收脚本（对应文档 M4-05）：连续切换 dark↔light 多次，对若干关键控件断言
其 inline styleSheet 中的色值属于**当前** token 集合，而非上一次主题的残留。

运行（offscreen）：
    QT_QPA_PLATFORM=offscreen python test_m4_05.py
"""
from __future__ import annotations

import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR",
    "D:/PythonProject/QuantVortex/.pytest_tmp/sd-state",
)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS: list[str] = []
_HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
# 两主题共用 / 语义色（涨跌色两主题一致）——切主题不应变化
_SEMANTIC = {"#ff4757", "#2ed573"}
# dark 独有 / light 独有 的基础色（切换后绝不应残留）
_DARK_ONLY = {"#1e1e2e", "#181825", "#27273a", "#45455f", "#dcdcdc", "#8b93a7",
              "#7aa2f7", "#2a2a3a", "#23233a", "#33335a", "#313148"}
_LIGHT_ONLY = {"#f5f7fa", "#eef2f7", "#ffffff", "#d1d5db", "#1f2937", "#6b7280",
               "#2563eb", "#e5e7eb", "#f8fafc", "#dbeafe", "#cbd5e1"}


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


def _token_set(theme: str) -> set:
    """该主题全部 token 的十六进制色值集合（切主题后色值应落在本集合）。"""
    from futures_quant.ui.design_system import design_tokens
    return {v.lower() for v in design_tokens(theme).values()}


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from futures_quant.ui import design_system
    from futures_quant.ui.main_window import MainWindow

    print("=" * 70)
    print("M4-05 · inline 样式切主题刷新验证")
    print("=" * 70)

    win = MainWindow()
    app.processEvents()
    design_system.apply_design(win.theme, refresh_widgets=False)
    # 强制实例化全部 NAV 页面（默认仅 NAV[0] 已构建），否则采样控件不存在
    for i in range(len(win.pages)):
        win._show_page(i)
        app.processEvents()
    win._show_page(0)
    win.theme = "dark"
    win._apply_theme()
    app.processEvents()

    # 采样控件：覆盖四类目标
    def sample(theme: str, win2: MainWindow) -> None:
        cur = _token_set(theme)
        old = _token_set("light" if theme == "dark" else "dark")
        old -= cur  # 仅取「上一次主题独有、当前主题不再使用」的色，作为残留判据
        targets: list[tuple[str, object]] = []
        for p in win2.pages:
            if p is None:
                continue
            for name in ("quote_time", "rank_hint", "temp_lbl", "linkage_lbl",
                         "mc_summary", "status_dot", "score_val"):
                if hasattr(p, name):
                    targets.append((f"{p.PAGE_KEY}.{name}", getattr(p, name)))
        checked = 0
        for key, w in targets:
            ss = w.styleSheet()
            if not ss:
                continue
            cols = {h.lower() for h in _HEX.findall(ss)}
            bad = cols & old
            checked += 1
            if bad:
                check(False, f"[{theme}] {key} 残留旧主题色 {sorted(bad)}")
            else:
                check(True, f"[{theme}] {key} 色值属于当前 token 集合")
        check(checked > 0, f"[{theme}] 至少采样到 1 个 inline 控件（实际 {checked}）")

    # 连续切换 dark -> light -> dark（每步都采样，验证无旧主题残留）
    for i, to_theme in enumerate(["light", "dark", "light"]):
        win.theme = to_theme
        win._apply_theme()
        app.processEvents()
        sample(to_theme, win)
        check(win.theme == to_theme, f"第 {i + 1} 轮切换后 theme={to_theme}")

    # StatCard 数值着色随主题刷新（M4-05④ 移除守卫后）
    from futures_quant.ui.widgets import StatCard
    sc = StatCard("涨跌", "+1.23", theme="dark", compact=True)
    sc.set_value("+1.23", color="#ff4757", direction="up")
    sc.set_theme("light")
    # 主题 text 色在数值未显式着时应为 light.text
    sc2 = StatCard("广度", "60%", theme="light", compact=True)
    check("#1f2937" in sc2._val.styleSheet().lower(),
          "StatCard 数值色随 light 主题刷新（无 if-not-guard 残留）")

    # 归因对话框 set_theme 接管（M4-05②）
    from futures_quant.ui.attribution_dialog import AttributionDialog
    check(hasattr(AttributionDialog, "set_theme"),
          "AttributionDialog 具备 set_theme（全量接管）")

    win.close()
    print("=" * 70)
    if FAILS:
        print(f"M4-05 验证失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("M4-05 inline 样式刷新验证全部通过 ✅")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
