"""版本号同步冒烟测试（offscreen）。

验证：界面各处（窗口标题、状态栏版本标签、关于页）均读取包内
futures_quant.__version__ / __release_date__ 单一常量，杜绝硬编码漂移。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication

from futures_quant import __version__, __release_date__
from futures_quant.ui.main_window import MainWindow
from futures_quant.ui.about_page import __app_version__, __app_release_date__


def main() -> None:
    app = QApplication.instance() or QApplication([])

    # 关于页与包级常量必须同源
    assert __app_version__ == __version__, (__app_version__, __version__)
    assert __app_release_date__ == __release_date__, (__app_release_date__, __release_date__)

    # 构造主窗口并校验界面版本展示
    w = MainWindow()
    title = w.windowTitle()
    ver_text = w._status_ver.text()

    assert f"v{__version__}" in title, f"窗口标题未含版本: {title!r}"
    assert ver_text == f"v{__version__}", f"状态栏版本标签异常: {ver_text!r}"
    # 托盘仅在系统支持时创建（offscreen 环境通常为 None，跳过校验）
    if w._tray is not None:
        assert f"v{__version__}" in w._tray.toolTip(), f"托盘提示未含版本: {w._tray.toolTip()!r}"

    print(f"[OK] pkg_version={__version__!r} release_date={__release_date__!r}")
    print(f"[OK] title={title!r}")
    print(f"[OK] status_ver={ver_text!r}")
    print("[OK] 托盘版本校验（环境不支持时跳过）")


if __name__ == "__main__":
    main()
