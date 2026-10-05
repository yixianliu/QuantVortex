"""版本防漂移护栏（offscreen，纯静态扫描）。

确保「界面所展示的版本」全部取自包内单一数据源 futures_quant.__version__，
不在展示处硬编码版本字面量。将来有人改版本号却漏改界面时，本测试会失败，
把「界面版本 ≠ 程序实际版本」的漂移在 CI/回归阶段拦下来。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from futures_quant import __version__ as _APP_VERSION

# 界面展示文件：其版本文本必须来自 __version__ 常量，禁止硬编码字面量。
_GUI_FILES = [
    os.path.join(ROOT, "futures_quant", "ui", "main_window.py"),
    os.path.join(ROOT, "futures_quant", "ui", "about_page.py"),
]
# spec 通过 _APP_VERSION 动态生成版本资源，允许「导入失败兜底」里出现一次字面量。
_SPEC_FILE = os.path.join(ROOT, "build_tools", "futures_qt.spec")

# 匹配展示处可能出现的版本字面量，如 "1.0.0" / 'v1.0.0' / "v1.2.3"
_VER_LITERAL = re.compile(r"""["']v?\d+\.\d+\.\d+["']""")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main() -> None:
    print(f"[OK] 包版本 __version__={_APP_VERSION!r}")

    for f in _GUI_FILES:
        src = _read(f)
        assert "__version__" in src, f"{f} 未引用包版本常量，存在漂移风险"
        hits = _VER_LITERAL.findall(src)
        assert not hits, f"{f} 仍硬编码版本字面量 {hits}，应与 __version__ 同步而非写死"
        print(f"[OK] 展示文件无硬编码版本：{os.path.relpath(f, ROOT)}")

    # spec：必须引用 __version__ 并动态生成版本资源（不应把版本写死成字面量用于展示）。
    spec = _read(_SPEC_FILE)
    assert "__version__" in spec, "futures_qt.spec 未引用包版本常量"
    assert "version=_VER_FILE" in spec, "futures_qt.spec 未将版本资源传给 EXE(version=...)"
    # 排除「导入失败兜底」行与文档示例后，spec 展示用途不应出现版本字面量。
    spec_body = "\n".join(
        ln for ln in spec.splitlines()
        if "except Exception" not in ln and "_APP_RELEASE_DATE =" not in ln)
    hits = _VER_LITERAL.findall(spec_body)
    assert not hits, f"futures_qt.spec 版本资源存在硬编码字面量 {hits}，应与 __version__ 同步"
    print("[OK] futures_qt.spec 动态引用 __version__ 并传给 EXE(version=...)")

    print("[完成] 版本防漂移护栏通过：界面与打包均绑定单一数据源，无硬编码版本。")


if __name__ == "__main__":
    main()
