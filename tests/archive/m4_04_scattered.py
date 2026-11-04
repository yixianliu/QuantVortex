# -*- coding: utf-8 -*-
"""M4-04 集成验证：MainWindow 构造经 build_qss 应用 QSS 并写出快照。

验收点：
    1. MainWindow 可 offscreen 构造（_apply_theme 不抛异常）；
    2. 构造后 config/style.qss 快照被写出且非空（首次生成）；
    3. 主窗口 styleSheet 非空且含 DESIGN[theme].bg（build_qss 生效）；
    4. 切换主题（_toggle_theme）后仍正常应用、无异常。

运行（offscreen）：
    QT_QPA_PLATFORM=offscreen python test_m4_04.py
"""
from __future__ import annotations

import os
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
SNAP = os.path.join(ROOT, "config", "style.qss")


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from futures_quant.ui.design_system import DESIGN

    # 构造前清掉已有快照，确保验证「首次生成」写入
    if os.path.exists(SNAP):
        try:
            os.remove(SNAP)
        except Exception:
            pass

    print("=" * 70)
    print("M4-04 · MainWindow 集成验证（build_qss 落地）")
    print("=" * 70)

    try:
        from futures_quant.ui.main_window import MainWindow
        win = MainWindow()
        app.processEvents()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"MainWindow 构造失败: {type(e).__name__}: {e}")
        return 1

    check(True, "MainWindow offscreen 构造成功")

    # ---- 验收 2：快照写出 ----
    check(os.path.exists(SNAP), "config/style.qss 快照已写出")
    if os.path.exists(SNAP):
        with open(SNAP, encoding="utf-8") as fh:
            snap_txt = fh.read()
        check(len(snap_txt) > 200, f"快照内容非空（长度 {len(snap_txt)}）")
        check("QWidget" in snap_txt and "QPushButton" in snap_txt,
              "快照含基础选择器（QWidget/QPushButton）")

    # ---- 验收 3：styleSheet 已应用且含 DESIGN.bg ----
    ss = win.styleSheet()
    check(bool(ss) and len(ss) > 200, f"主窗口 styleSheet 已应用（长度 {len(ss)}）")
    bg = DESIGN[win.theme]["bg"].lower()
    check(bg in ss.lower(), f"styleSheet 含 DESIGN[{win.theme}].bg={bg}（build_qss 生效）")

    # ---- 验收 4：切换主题不抛异常 ----
    try:
        before = win.theme
        win._toggle_theme()
        app.processEvents()
        after = win.theme
        check(before != after, f"主题已切换（{before} -> {after}）")
        ss2 = win.styleSheet()
        bg2 = DESIGN[after]["bg"].lower()
        check(bg2 in ss2.lower(), f"切换后 styleSheet 含 DESIGN[{after}].bg={bg2}")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"主题切换抛异常: {e}")

    # 清理
    try:
        win.closeEvent(__import__("PyQt6.QtGui").QtGui.QCloseEvent())
    except Exception:
        pass
    try:
        win.deleteLater()
    except Exception:
        pass

    print("=" * 70)
    if FAILS:
        print(f"M4-04 集成验证失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("M4-04 集成验证全部通过 ✅")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
