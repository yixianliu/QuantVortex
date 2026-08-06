"""运行时路径与资源解析（开发模式 / PyInstaller 打包后通用）。

为什么需要它：
    直接 `python main.py` 时，当前工作目录（CWD）就是项目根，相对路径 `data/...`
    能正常工作。但打包成单文件夹 EXE 后，用户可能从任意目录（甚至只读的
    C:\\Program Files）双击启动，此时：
      - 若仍用「相对 CWD」的路径写数据库/用户配置，会写到错误位置或写不进去；
      - 字体若只依赖系统目录，目标机缺字体就会显示 tofu。
    本模块统一收口这些决策，让开发期与分发期行为一致且健壮。

关键约定：
    - app_base_dir()：开发期=项目根目录；打包后=exe 所在目录（而非 CWD）。
    - get_data_dir()：运行时可写数据目录。优先 exe 同级的 data/，若该目录不可写
      （如安装到 Program Files），自动回退到用户 AppData/FuturesQuant/data。
    - get_config_dir()：随包分发的只读配置目录（含 settings.json 模板）。
    - get_font_paths()：候选中文字体，内嵌资源优先，其次系统字体。
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional


def is_frozen() -> bool:
    """PyInstaller 打包后（sys.frozen + sys._MEIPASS）返回 True。"""
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> str:
    """应用基准目录：打包后取 exe 目录，开发时取项目根目录。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    # 本文件位于 <项目根>/futures_quant/runtime.py
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w") as fh:
            fh.write("")
        os.remove(probe)
        return True
    except Exception:
        return False


def get_data_dir() -> str:
    """返回运行时可写数据目录（数据库/用户配置/会话/缓存）。"""
    candidate = os.path.join(app_base_dir(), "data")
    if _is_writable(candidate):
        return candidate
    # 只读安装位置（如 Program Files）：回退到用户 AppData
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    fallback = os.path.join(appdata, "FuturesQuant", "data")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def get_config_dir() -> str:
    """返回随包分发的只读配置目录（含 settings.json 模板）。"""
    return os.path.join(app_base_dir(), "config")


def normalize_data_path(p: Optional[str], default_name: str) -> str:
    """把数据库/数据路径归一化到可写 data 目录。

    - p 为 None              -> <data_dir>/<default_name>
    - p 为绝对路径           -> 原样使用
    - p 为相对路径（如旧值 "data/xxx.db"） -> <data_dir>/<basename>
    这样无论旧配置里写的是相对还是绝对路径，最终都落在可写目录，杜绝 CWD 依赖。
    """
    if not p:
        return os.path.join(get_data_dir(), default_name)
    if os.path.isabs(p):
        return p
    return os.path.join(get_data_dir(), os.path.basename(p))


def get_font_paths() -> List[str]:
    """返回候选中文字体文件路径，按优先级排序（去重保序）。

    1) 内嵌字体：打包后的 sys._MEIPASS，或开发期/分发期的 <base>/assets/fonts；
    2) 系统字体：Windows 普遍自带 SimHei，作为兜底。
    """
    found: List[str] = []
    bundled_dirs: List[str] = []
    if is_frozen():
        bundled_dirs.append(sys._MEIPASS)
    bundled_dirs.append(os.path.join(app_base_dir(), "assets", "fonts"))
    for d in bundled_dirs:
        if os.path.isdir(d):
            for name in ("simhei.ttf", "NotoSansSC-VF.ttf", "NotoSansSC-Regular.otf",
                         "msyh.ttc", "wqy-microhei.ttc"):
                fp = os.path.join(d, name)
                if os.path.exists(fp):
                    found.append(fp)
    for fp in ("C:/Windows/Fonts/simhei.ttf",
               "C:/Windows/Fonts/NotoSansSC-VF.ttf",
               "C:/Windows/Fonts/msyh.ttc"):
        if os.path.exists(fp):
            found.append(fp)
    seen = set()
    out: List[str] = []
    for fp in found:
        if fp not in seen:
            seen.add(fp)
            out.append(fp)
    return out
