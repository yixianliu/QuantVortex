# -*- coding: utf-8 -*-
"""DataPage GUI 离屏自测：页面构建、控件齐全、导出联动。"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

from futures_quant.storage.analysis_store import AnalysisStore
from futures_quant.ui.data_page import DataPage
from futures_quant.ui import main_window  # 确认主窗口模块（含 NAV 注册）可导入

app = QApplication([])

tmp = tempfile.mkdtemp(prefix="qv_ui_")
store = AnalysisStore(os.path.join(tmp, "ui_test.db"))
store.add_log("2026-07-25", "INFO", "ui test")


class FakeMDM:
    source_label = "测试"
    status = "已连接"


page = DataPage(FakeMDM(), store, None, None)
page.resize(1200, 800)
page.show()

# 控件存在性
for name in ("btn_export", "btn_export_zip", "btn_backup_file",
             "btn_restore_file", "btn_my_test", "btn_my_backup",
             "btn_my_restore", "fmt_combo", "my_host", "my_port",
             "log_view"):
    assert hasattr(page, name), f"缺少控件 {name}"
print("[OK] all widgets present")

# NAV 注册检查
keys = [k for _, _, _, k in main_window.NAV]
assert "data" in keys, keys
titles = [t for t, *_ in main_window.NAV]
assert "数据管理" in titles
print("[OK] NAV registered:", titles)

# 表勾选与格式
assert len(page._sel_tables()) == 8
page.fmt_combo.setCurrentIndex(1)
assert page._fmt() == "json"
print("[OK] table checks & format combo")

# 进度信号 → 日志区
page.progress.emit("测试进度消息")
app.processEvents()
assert "测试进度消息" in page.log_view.toPlainText()
print("[OK] progress signal -> log view")

# 主题切换不崩
page.set_theme("light")
page.set_theme("dark")
print("[OK] theme switch")

# db 图标已注册
from futures_quant.ui.icons import _ICONS
assert "db" in _ICONS
print("[OK] db icon registered")

store.close()
print("\nALL GUI TESTS PASSED")
