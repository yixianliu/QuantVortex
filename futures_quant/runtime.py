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
    """探测目录是否可写（写探针文件验证）。

    M2-12 修复：原实现把「探针写入」与「探针删除」放在同一个 try 里，
    `os.remove(probe)` 失败会让整个函数返回 False —— 明明刚成功写入，
    却被判定为不可写，进而把数据目录误切到 AppData（用户原有数据"消失"）。

    更危险的是：安全软件/沙箱对 `os.remove` 的拦截可能抛出
    ``SystemExit``（属 BaseException，**不是** Exception 子类），
    会直接穿透 `except Exception` 向上炸掉整个 AnalysisStore 构造。

    现在拆成三段：建目录 / 写探针（真正的可写性判据）/ 清理（尽力而为）。
    """
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:  # noqa: BLE001
        return False
    probe = os.path.join(path, ".write_test")
    try:
        with open(probe, "w") as fh:
            fh.write("")
    except Exception:  # noqa: BLE001
        return False
    # 清理失败不应否定「刚写入成功」这一事实。
    # 这里显式捕获 BaseException：SystemExit/KeyboardInterrupt 级别的拦截
    # （杀软、沙箱 shim）绝不能让整个数据目录判定流程崩溃。
    try:
        os.remove(probe)
    except BaseException:  # noqa: BLE001  # 刻意：清理是尽力而为
        pass
    return True


_DATA_DIR_CACHE: Optional[str] = None


def get_data_dir() -> str:
    """返回运行时可写数据目录（数据库/用户配置/会话/缓存）。

    M2-12：结果做进程内缓存。原实现每次调用都新建+删除 `.write_test` 探针，
    高频调用（每次 AnalysisStore 构造都会走 normalize_data_path）会持续
    制造文件删除动作，易被杀软/沙箱的删除守卫拦截。
    """
    global _DATA_DIR_CACHE
    if _DATA_DIR_CACHE is not None:
        return _DATA_DIR_CACHE

    candidate = os.path.join(app_base_dir(), "data")
    if _is_writable(candidate):
        _DATA_DIR_CACHE = candidate
        return _DATA_DIR_CACHE
    # 只读安装位置（如 Program Files）：回退到用户 AppData
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    fallback = os.path.join(appdata, "FuturesQuant", "data")
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    _DATA_DIR_CACHE = fallback
    return _DATA_DIR_CACHE


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


def get_images_dir() -> str:
    """返回图片资源目录。打包时从内部资源加载，开发期从文件系统。

    M6-01：统一图片目录访问入口，打包后使用 sys._MEIPASS/images。
    """
    if is_frozen():
        # 打包后从内部资源加载
        return os.path.join(sys._MEIPASS, "images")
    # 开发期从项目根目录的 images 文件夹
    return os.path.join(app_base_dir(), "images")


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
