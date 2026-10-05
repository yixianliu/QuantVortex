"""全页面 GUI 冒烟测试（offscreen，不显示窗口）。

验证所有 9 个页面能正常构造、主题切换、基础交互。
运行：
    python examples/test_all_pages.py
"""
from __future__ import annotations

import sys
import os

# 确保能导入项目模块（tests/e2e -> tests -> 项目根）
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


def main() -> None:
    app = QApplication(sys.argv)
    # 强制使用 offscreen 平台插件
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, False)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.main_window import NAV
    from futures_quant.ui.widgets import THEME

    print("=" * 70)
    print("全页面 GUI 冒烟测试")
    print("=" * 70)

    # 初始化行情管理器和存储
    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_test.db")

    page_count = len(NAV)
    passed = 0
    failed = 0
    errors = []

    for i, (name, PageCls, page_key, icon_key) in enumerate(NAV, 1):
        try:
            session = None
            cfg = None
            page = PageCls(mdm, store, config=cfg, session=session)
            print(f"[{i}/{page_count}] {name:8s} - 构造 OK, PAGE_KEY={page.PAGE_KEY}")

            # 测试主题切换
            page.set_theme("dark")
            page.set_theme("light")
            page.set_theme("dark")
            print(f"                   主题切换 OK")

            # 测试 closeEvent (清理定时器/信号)
            from PyQt6.QtGui import QCloseEvent
            fake_event = QCloseEvent()
            page.closeEvent(fake_event)
            print(f"                   关闭保护 OK")

            passed += 1

        except Exception as e:
            failed += 1
            err_msg = f"{type(e).__name__}: {e}"
            errors.append((name, err_msg))
            print(f"[{i}/{page_count}] {name:8s} - FAIL: {err_msg}")

    # 清理测试 DB
    try:
        store.close()
        if os.path.exists("data/quant_analysis_test.db"):
            os.remove("data/quant_analysis_test.db")
    except Exception:
        pass

    print("=" * 70)
    print(f"测试结果: {passed}/{page_count} 通过, {failed}/{page_count} 失败")
    if errors:
        print("\n失败详情:")
        for name, err in errors:
            print(f"  - {name}: {err}")
    else:
        print("所有页面均正常！")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
