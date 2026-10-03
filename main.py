"""QuantVortex · 启动入口。

职责：
    1. 确保项目根目录在 sys.path 中（开发期直接运行 / 打包后 exe 同级运行均兼容）；
    2. 将 Qt 平台插件目录指向 assets/qt/（如存在），避免找不到平台插件的启动报错；
    3. 调用 futures_quant.ui.main_window.main() 启动桌面端主窗口。

运行方式：
    开发期：  python main.py           或  python -m futures_quant.ui
    打包后：  dist/FuturesQuant/FuturesQuant.exe
"""
from __future__ import annotations

import os
import sys

# 项目根目录：开发期 = 本文件所在目录；打包后 = exe 所在目录（即 dist/FuturesQuant/）。
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---- Qt 平台插件路径（可选）----
# 若存在 assets/qt/ 目录（内含 platforms/qwindows.dll 等），显式设置 QT_QPA_PLATFORM_PLUGIN_PATH，
# 避免 Qt 在找不到系统插件时直接崩溃。未包含时保留默认行为。
_QT_PLUGINS = os.path.join(_ROOT, "assets", "qt")
if os.path.isdir(_QT_PLUGINS):
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _QT_PLUGINS


def main() -> None:
    """启动 QuantVortex 桌面端主窗口。"""
    from futures_quant.ui.main_window import main as _ui_main
    _ui_main()


if __name__ == "__main__":
    main()
