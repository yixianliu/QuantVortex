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
# 本 spec 位于 build_tools/，真正的项目根是其父目录 —— main.py / config /
# futures_quant 都在项目根，不是 build_tools/。
HERE = SPECPATH
ROOT = os.path.dirname(SPECPATH)

# ---- 需要随包分发的数据/资源 ----
#
# 安全约束（不要图省事改回 datas.append((cfg_dir, "config"))）：
#   config/ 里混放着两类文件 —— 可公开的模板（*.example.json）和
#   开发者本地的真实凭据（ctp_settings.json 存实盘账号/密码，正因如此
#   它在 .gitignore 里）。整目录打包会把后者一并塞进面向公众分发的 exe。
#   密钥扫描器按 sk-/PRIVATE KEY 等特征匹配，抓不到「期货账号+密码」这类
#   凭据，所以这里必须靠文件名黑名单在源头拦住。
#   最终用户自己在 exe 同级 data/ 或 config/ 放 ctp_settings.json 即可，
#   运行时查找逻辑不变。
CONFIG_DENY = {
    "ctp_settings.json",      # 实盘/仿真账户凭据
    "secrets.json",
    "credentials.json",
    "upstream.json",          # 上游 AI 密钥（历史遗留名，任何情况下都不入产物）
}
CONFIG_DENY_SUFFIX = (".local.json", ".secret.json", ".key", ".pem")

datas = []
cfg_dir = os.path.join(ROOT, "config")
if os.path.isdir(cfg_dir):
    for _name in sorted(os.listdir(cfg_dir)):
        _src = os.path.join(cfg_dir, _name)
        if not os.path.isfile(_src):
            continue
        if _name in CONFIG_DENY or _name.endswith(CONFIG_DENY_SUFFIX):
            print(f"[spec][安全] 跳过本地凭据文件，不打入产物：config/{_name}")
            continue
        datas.append((_src, "config"))
# 可选：内嵌中文字体（放入 assets/fonts/ 后自动打进 exe）
fonts_dir = os.path.join(ROOT, "assets", "fonts")
if os.path.isdir(fonts_dir):
    datas.append((fonts_dir, "assets/fonts"))

# ★ 关键：将 futures_quant 包目录作为数据文件打入
# collect_submodules() 在 anaconda 环境可能只返回少量模块，
# 所以直接复制包目录保证所有代码都被包含。
#
# 安全约束（不要图省事改回 datas.append((pkg_dir, "futures_quant"))）：
#   直接整目录打入会连 __pycache__/*.pyc 一起带进产物。编译不是加密 ——
#   .pyc 里的字符串常量原样可读，本项目历史上正是在 __pycache__ 里
#   泄露过真实密钥。这里逐文件收集并显式剔除字节码缓存。
pkg_dir = os.path.join(ROOT, "futures_quant")
if os.path.isdir(pkg_dir):
    for _dirpath, _dirnames, _filenames in os.walk(pkg_dir):
        _dirnames[:] = [d for d in _dirnames if d != "__pycache__"]
        _rel = os.path.relpath(_dirpath, ROOT).replace("\\", "/")
        for _name in _filenames:
            if _name.endswith((".pyc", ".pyo")):
                continue
            datas.append((os.path.join(_dirpath, _name), _rel))

# 收集整个 futures_quant 包，避免漏掉动态/延迟导入的子模块
hiddenimports = collect_submodules("futures_quant") + [
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui",
    # 新增模块（方向二/三）显式声明：
    "futures_quant.ui.ctp_monitor_page",
    "futures_quant.data.ctp_gateway",
    "futures_quant.alerts.engine",
    "futures_quant.ai.features",
    "futures_quant.ai.ensemble",
    "futures_quant.ai.config",
    "futures_quant.ui.screening_page",
    "futures_quant.ui.ai_settings_dialog",
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除清单不只是为了瘦身 —— **每个捆绑进去的依赖都是攻击面**。
    # 本项目从 anaconda base 环境打包，PyInstaller 会顺着 hook 把整个科学计算栈
    # 扒进产物：曾经打出 1349 MB 的包，里面躺着 notebook / jupyterlab / tornado
    # （一个完整的 Web 服务器）/ panel / bokeh / botocore。一个公开分发的桌面
    # 客户端捆绑 Jupyter 全家桶，等于白白背上一大堆与业务无关的 CVE 维护责任。
    #
    # 下列包均已核实：futures_quant/ 与 main.py 中零引用（grep import 全为 0）。
    # 增删本清单后务必跑 tests/tmp 之外的冒烟测试确认 exe 仍能启动。
    excludes=[
        # 巨型/无关依赖，打包无需带：
        "matplotlib", "tkinter", "PyQt5", "PySide2", "PySide6",
        "scipy", "sklearn", "torch", "tensorflow",
        # 开发/科学/文档类，客户端运行时绝不依赖，且会拖慢 Analysis：
        # （客户端不在 futures_quant 内使用 PyJWT/cryptography；redact.py 里的
        #  JWT 相关正则仅是日志脱敏的匹配模式，不做任何签名校验）
        "numba", "llvmlite", "IPython", "astroid",
        "sphinx", "docutils", "jedi", "parso",
        "pytest", "black", "cryptography", "bcrypt",
        # Jupyter / 交互式笔记本栈（含 tornado Web 服务器，攻击面大头）：
        "notebook", "notebook_shim", "jupyterlab", "jupyterlab_server",
        "jupyter", "jupyter_core", "jupyter_client", "jupyter_server",
        "nbformat", "nbconvert", "nbclient", "ipykernel", "ipywidgets",
        "tornado", "zmq", "pyzmq", "traitlets", "qtconsole",
        # 可视化/仪表盘栈（本项目用 QPainter 自绘图表，不依赖任何一个）：
        "panel", "bokeh", "holoviews", "hvplot", "param", "pyviz_comms",
        "plotly", "altair", "seaborn", "datashader",
        # 云 SDK / 分布式计算 / 列存，客户端完全用不到：
        "boto3", "botocore", "s3transfer", "awscli",
        "dask", "distributed", "pyarrow", "fastparquet",
        # 其他科学计算重件：
        "statsmodels", "sympy", "h5py", "tables",
        # 刻意不排除 PIL / numexpr / networkx：产物里各自只有几百 KB～几 MB，
        # 但 akshare 等数据源库存在延迟导入的可能，排掉的收益不抵踩雷的风险。
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
