# -*- coding: utf-8 -*-
"""M4-02 验证：修复 MarketPage 必崩 + 孤儿页面处置。

验收点：
    1. pages.py 全部页面类可构造（offscreen 冒烟 rc=0）；
    2. main_window.py 死导入 ValidatePage 已移除；
    3. _build_alert_center 签名接受 margin 形参（修复 NameError 根因）；
    4. 孤儿页 MarketPage/PredictPage/PanoramaPage 标注 @deprecated；
       IndicatorPage/ValidatePage/LogPage 不标注（M4-11 决定 / 仍在使用）。

运行（offscreen）：
    QT_QPA_PLATFORM=offscreen python test_m4_02.py
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

# offscreen 平台 + 守卫重定向（避免 E:\Temp 极慢/锁超时）
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


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    import futures_quant.ui.pages as pages_mod
    from futures_quant.ui import pages as P

    mdm = MarketDataManager(source="synthetic")
    db_path = os.path.join(ROOT, ".pytest_tmp", "m4_02_pages.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
    store = AnalysisStore(path=db_path)

    page_classes = [
        ("MarketPage", P.MarketPage),
        ("IndicatorPage", P.IndicatorPage),
        ("PredictPage", P.PredictPage),
        ("PanoramaPage", P.PanoramaPage),
        ("ValidatePage", P.ValidatePage),
        ("LogPage", P.LogPage),
    ]

    print("=" * 70)
    print("M4-02 · pages.py 全页面类构造冒烟")
    print("=" * 70)

    for name, Cls in page_classes:
        try:
            page = Cls(mdm, store, config=None, session=None)
            page.set_theme("dark")
            page.set_theme("light")
            page.set_theme("dark")
            from PyQt6.QtWidgets import QApplication as _QApp
            _QApp.processEvents()
            from PyQt6.QtGui import QCloseEvent
            page.closeEvent(QCloseEvent())
            deprecated = getattr(Cls, "__deprecated__", False)
            print(f"  [OK]  {name:14s} 构造+主题+关闭 OK  (deprecated={deprecated})")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {name:14s} 构造异常: {type(e).__name__}: {e}")
            traceback.print_exc()
            FAILS.append(f"{name} 构造异常: {e}")

    # ---- 验收 3：_build_alert_center 接受 margin ----
    sig = inspect.signature(P.MarketPage._build_alert_center)
    check("margin" in sig.parameters,
          "MarketPage._build_alert_center 签名含 margin 形参（修复 NameError 根因）")
    check(sig.parameters["margin"].default is None,
          "_build_alert_center(margin=None) 默认值为 None")

    # ---- 验收 4：deprecated 标记正确性 ----
    check(getattr(P.MarketPage, "__deprecated__", False) is True,
          "MarketPage 标注 @deprecated")
    check(getattr(P.PredictPage, "__deprecated__", False) is True,
          "PredictPage 标注 @deprecated")
    check(getattr(P.PanoramaPage, "__deprecated__", False) is True,
          "PanoramaPage 标注 @deprecated")
    check(getattr(P.IndicatorPage, "__deprecated__", False) is not True,
          "IndicatorPage 未标注（M4-11 决定）")
    check(getattr(P.ValidatePage, "__deprecated__", False) is not True,
          "ValidatePage 未标注（M4-11 决定）")
    check(getattr(P.LogPage, "__deprecated__", False) is not True,
          "LogPage 未标注（仍在 NAV 使用）")

    # ---- 验收 2：main_window 死导入 ValidatePage 已移除 ----
    mw_path = os.path.join(ROOT, "futures_quant", "ui", "main_window.py")
    with open(mw_path, "r", encoding="utf-8") as fh:
        mw_src = fh.read()
    import re
    # 仅检查 from .pages import (...) 这一行内是否还带 ValidatePage
    bad = re.search(r"from\s+\.pages\s+import[^\n]*ValidatePage", mw_src)
    check(bad is None,
          "main_window.py 不再从 .pages 导入 ValidatePage（死导入已移除）")

    # 反向确认 LogPage 仍被导入（功能页面保留）
    ok = re.search(r"from\s+\.pages\s+import[^\n]*LogPage", mw_src)
    check(ok is not None,
          "main_window.py 仍导入 LogPage（活跃页面保留）")

    # 模块级 helper 存在性
    check(hasattr(P.BasePage, "_page_margin"),
          "BasePage._page_margin 已新增（提供统一边距）")
    check(callable(getattr(pages_mod, "_deprecated", None)),
          "pages._deprecated 装饰器已定义")

    store.close()
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass

    print("=" * 70)
    if FAILS:
        print(f"M4-02 验证失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("M4-02 全部验收通过 ✅")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
