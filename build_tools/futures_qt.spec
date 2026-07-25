# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格（单文件夹 exe，Windows 桌面程序）。

构建：
    pip install pyinstaller
    python build_exe.py            # 自动调用本 spec
或：
    pyinstaller futures_qt.spec

产物：
    dist/FuturesQuant/ 目录（含 FuturesQuant.exe + 依赖 + config/）。
    首次启动会在 exe 同级创建 data/（数据库/用户配置/会话）；
    若 exe 位于只读目录（如 C:\\Program Files），自动回退到
    %APPDATA%/FuturesQuant/data。

字体：
    主程序优先注册内嵌 assets/fonts/ 下的中文字体，否则回退系统
    C:/Windows/Fonts/simhei.ttf（Windows 普遍自带）。如需完全自包含，
    把任一 OFL 许可的中文字体（如 NotoSansSC-Regular.otf）放入
    assets/fonts/ 再构建即可。
"""
import os
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# PyInstaller 在 spec 命名空间中提供 SPECPATH（spec 文件所在目录），
# 注意：spec 被执行时 __file__ 未定义，不能用 os.path.abspath(__file__)。
HERE = SPECPATH

# ---- 需要随包分发的数据/资源 ----
datas = []
if os.path.isdir(os.path.join(HERE, "config")):
    datas.append(("config", "config"))
# 可选：内嵌中文字体（放入 assets/fonts/ 后自动打进 exe）
fonts_dir = os.path.join(HERE, "assets", "fonts")
if os.path.isdir(fonts_dir):
    datas.append((fonts_dir, "assets/fonts"))

# ★ 关键修复：将整个 futures_quant 包目录作为数据文件打入
# collect_submodules() 在 anaconda 环境可能只返回少量模块，
# 所以直接复制整个包目录保证所有代码都被包含
pkg_dir = os.path.join(HERE, "futures_quant")
if os.path.isdir(pkg_dir):
    datas.append((pkg_dir, "futures_quant"))

# 收集整个 futures_quant 包，避免漏掉动态/延迟导入的子模块
hiddenimports = collect_submodules("futures_quant") + [
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui",
    # 新增模块（方向二/三）显式声明：
    "futures_quant.ui.ctp_monitor_page",
    "futures_quant.data.ctp_gateway",
    "futures_quant.alerts.engine",
    "futures_quant.ai.features",
    "futures_quant.ai.ensemble",
    "futures_quant.ai.evaluate",
    "futures_quant.ui.screening_page",
]

a = Analysis(
    ["main.py"],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 巨型/无关依赖，打包无需带：
        "matplotlib", "tkinter", "PyQt5", "PySide2", "PySide6",
        "scipy", "sklearn", "torch", "tensorflow",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FuturesQuant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,            # 桌面程序，不弹黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FuturesQuant",
)
