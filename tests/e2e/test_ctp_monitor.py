"""CTP 实盘监控页 e2e（offscreen）。

覆盖 R9 的「Mock 兜底 + 只读监控页」：
  - 构造 / 渲染不崩（无 CTP 库 / 凭据时走合成兜底）；
  - 诊断面板、盘口表、状态徽章正常填充；
  - 点击「连接柜台」→ 合成源兜底，绝不冒充实盘（is_real 保持 False）；
  - 点击「重新诊断」「刷新盘口」「断开」不崩；
  - 主题切换 / 关闭事件不崩。

运行：
    QT_QPA_PLATFORM=offscreen python tests/e2e/test_ctp_monitor.py
"""
from __future__ import annotations

import os
import sys
import time

# 确保能导入项目模块（tests/e2e -> tests -> 项目根）
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent


def main() -> int:
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, False)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.ctp_monitor_page import CTPMonitorPage

    db_path = "data/quant_analysis_test_ctp.db"
    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path=db_path)

    # 构造 + 展示（offscreen 不弹窗）
    page = CTPMonitorPage(mdm, store, None, None)
    page.show()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()

    # [1] 诊断面板有内容（无 CTP 库时显示「未安装」类诊断）
    diag = page.diag_lbl.text()
    assert diag.strip(), "诊断面板为空"
    print(f"[1] 诊断面板非空 OK ({len(diag)} chars)")

    # [2] 盘口表已填充订阅合约行
    rows = page.qtable.rowCount()
    assert rows > 0, "盘口表无行"
    print(f"[2] 盘口表 {rows} 行 OK")

    # [3] 状态 / 模式徽章已填充
    assert page.src_badge.text().startswith("数据源："), "数据源徽章未填充"
    assert page.mode_badge.text().startswith("模式："), "模式徽章未填充"
    print(f"[3] 状态/模式徽章 OK: {page.src_badge.text()} | {page.mode_badge.text()}")

    # [4] 点击「连接柜台」→ 合成兜底，不崩，保持离线（绝不冒充实盘）
    page._on_connect()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    assert not getattr(mdm, "is_real", False), "合成源不应标记 is_real=True"
    print("[4] 连接柜台(合成兜底) 不崩，is_real=False OK")

    # [5] 刷新盘口 / 重新诊断 / 断开 不崩
    page._refresh_quotes()
    page._on_disconnect()
    page._refresh_diag()
    app.processEvents()
    assert page.diag_lbl.text().strip(), "重新诊断后诊断为空"
    print("[5] 刷新盘口/重新诊断/断开 OK")

    # [6] 主题切换不崩
    page.set_theme("light")
    app.processEvents()
    page.set_theme("dark")
    app.processEvents()
    print("[6] 主题切换 OK")

    # [7] 关闭事件不崩
    page.closeEvent(QCloseEvent())
    print("[7] 关闭事件 OK")

    store.close()
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass
    print("CTPMonitorPage e2e ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
