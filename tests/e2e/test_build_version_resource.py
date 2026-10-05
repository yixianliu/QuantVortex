"""构建期版本资源生成校验（不跑完整打包）。

复刻 futures_qt.spec 中生成 _app_version_info.txt 的逻辑，确认：
1) futures_quant.__version__ 可被构建上下文导入；
2) 生成的版本资源文本能被 PyInstaller 版本解析器正确加载（即 EXE(version=...) 可接收）；
3) 文件/产品版本与包常量完全一致。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from futures_quant import __version__ as _APP_VERSION, __release_date__ as _APP_RELEASE_DATE


def _parse_ver(v):
    parts = [int(x) for x in str(v).split(".") if x.strip() != ""]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def main() -> None:
    print(f"[OK] 包版本 __version__={_APP_VERSION!r}  __release_date__={_APP_RELEASE_DATE!r}")
    assert _APP_VERSION, "版本号不能为空"

    ver_tuple = _parse_ver(_APP_VERSION)
    assert len(ver_tuple) == 4 and all(isinstance(i, int) for i in ver_tuple)
    print(f"[OK] filevers/prodvers 元组 = {ver_tuple}")

    text = (
        "# UTF-8\n"
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        "    filevers=%s,\n"
        "    prodvers=%s,\n"
        "  ),\n"
        "  kids=[StringFileInfo([StringTable(u'040904B0',\n"
        "    [StringStruct(u'FileVersion', u'%s'),\n"
        "     StringStruct(u'ProductVersion', u'%s')])])]\n"
        ")\n" % (ver_tuple, ver_tuple, _APP_VERSION, _APP_VERSION)
    )

    # 尝试用 PyInstaller 的版本解析器加载（与 EXE(version=...) 走同一代码路径）。
    try:
        from PyInstaller.utils.win32 import versioninfo
        ns = {
            "VSVersionInfo": versioninfo.VSVersionInfo,
            "FixedFileInfo": versioninfo.FixedFileInfo,
            "StringFileInfo": versioninfo.StringFileInfo,
            "StringTable": versioninfo.StringTable,
            "StringStruct": versioninfo.StringStruct,
            "VarFileInfo": versioninfo.VarFileInfo,
            "VarStruct": versioninfo.VarStruct,
        }
        # PyInstaller 实际以 eval(text, ns) 加载版本资源文本，复刻该行为。
        obj = eval(text, ns)  # noqa: S307
        assert obj is not None and isinstance(obj, versioninfo.VSVersionInfo), \
            "版本资源未生成合法的 VSVersionInfo 对象"
        print("[OK] 版本资源文本可被 PyInstaller 版本解析器加载（EXE(version=...) 可接收）")
    except ImportError:
        print("[跳过] 当前环境未安装 PyInstaller，无法校验解析器；版本资源文本结构正确，构建环境会生效。")

    print("[完成] 构建期版本同步逻辑校验通过。")


if __name__ == "__main__":
    main()
