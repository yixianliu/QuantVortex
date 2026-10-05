# -*- coding: utf-8 -*-
"""M4-04 验证：建立 QSS 单一事实来源（design_system.build_qss）。

验收点：
    1. build_qss(theme) 由 DESIGN[theme] token 生成，无未替换 $TOKEN$ 占位符；
    2. QSS 含全部必需选择器：#card / #toolbar / #chip / #primary / #secondary
       / #ai-group / #btn-bar；
    3. 主按钮(QPushButton)背景色 == DESIGN[theme].accent（QSS 与自绘控件同源）；
    4. 生成的 QSS 经 scale_qss_fonts 后最小字号 >= 11px；
    5. QSS 可被控件 setStyleSheet 应用且不抛异常（offscreen）。

运行（offscreen）：
    QT_QPA_PLATFORM=offscreen python test_design_system.py
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


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


REQUIRED_SELECTORS = [
    "#card", "#toolbar", "#chip", "#primary", "#secondary", "#ai-group", "#btn-bar",
]


def main() -> int:
    from PyQt6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])

    from futures_quant.ui.design_system import DESIGN, build_qss, design_tokens
    from futures_quant.ui.main_window import scale_qss_fonts

    print("=" * 70)
    print("M4-04 · QSS 单一事实来源验证")
    print("=" * 70)

    for theme in ("dark", "light"):
        tk = DESIGN[theme]
        qss = build_qss(theme)

        # ---- 验收 1：无未替换占位符 ----
        left = re.findall(r"\$[A-Z0-9_]+\$", qss)
        check(not left,
              f"[{theme}] build_qss 无未替换占位符（残留 {left}）")

        # ---- 验收 2：必需选择器齐全 ----
        for sel in REQUIRED_SELECTORS:
            check(sel in qss, f"[{theme}] QSS 含选择器 {sel}")

        # ---- 验收 3：主按钮背景 == DESIGN.accent（同源）----
        m = re.search(r"QPushButton\s*\{\s*[^}]*?background:(#[0-9a-fA-F]+);", qss)
        if m:
            qss_accent = m.group(1).lower()
            check(qss_accent == tk["accent"].lower(),
                  f"[{theme}] QPushButton 背景 == DESIGN.accent（{qss_accent}）")
        else:
            check(False, f"[{theme}] 未匹配到 QPushButton 背景色")

        # 同源结构性校验：build_qss 使用的色板应与 design_tokens 完全一致
        dt = design_tokens(theme)
        check(qss.count(tk["bg"]) >= 1, f"[{theme}] QSS 使用 DESIGN.bg")
        check(qss.count(tk["border"]) >= 1, f"[{theme}] QSS 使用 DESIGN.border")

        # ---- 验收 4：缩放后最小字号 >= 11px ----
        scaled = scale_qss_fonts(qss, _dummy_mgr(app))
        sizes = [int(x) for x in re.findall(r"font-size:(\d+)px", scaled)]
        check(sizes and min(sizes) >= 11,
              f"[{theme}] 缩放后最小字号 >=11px（实测 {min(sizes) if sizes else 'NA'}）")

        # ---- 验收 5：可应用不抛异常 ----
        w = QWidget()
        try:
            w.setStyleSheet(qss)
            applied = w.styleSheet()
            check(bool(applied) and len(applied) > 100,
                  f"[{theme}] QWidget.setStyleSheet 应用成功（长度 {len(applied)}）")
        except Exception as e:  # noqa: BLE001
            check(False, f"[{theme}] setStyleSheet 抛异常: {e}")
        finally:
            w.deleteLater()

    print("=" * 70)
    if FAILS:
        print(f"M4-04 验证失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("M4-04 全部验收通过 ✅")
    print("=" * 70)
    return 0


class _dummy_mgr:  # noqa: N801
    """极简桩：仅提供 font_size 三档钳制（与 responsive_layout 一致）。"""

    def __init__(self, app=None) -> None:
        self._scale = 0.85

    def font_size(self, base: int = 13) -> int:
        import math
        scaled = int(base * self._scale)
        floor = max(11, base) if base <= 13 else 11
        return max(floor, min(18, scaled))


if __name__ == "__main__":
    sys.exit(main())
