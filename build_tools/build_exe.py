"""打包为桌面 exe（Windows 优先，跨平台亦可）。

前置：
    pip install pyinstaller
运行：
    python build_exe.py
产物：dist/FuturesQuant/ 目录（含 FuturesQuant.exe + 依赖 + config/）。
config/ 已通过 spec 的 datas 打入；首次启动会在 exe 同级创建 data/，
若 exe 在只读目录则回退到 %APPDATA%/FuturesQuant/data（见 futures_quant/runtime.py）。
如需完全自包含字体，把中文字体放入 assets/fonts/ 再构建。

可选代码签名（消除 SmartScreen / 未知发布者警告）：
    设置环境变量后构建会自动对 exe 及捆绑的 dll/pyd 签名，缺失则跳过：
        QV_SIGN=1
        QV_SIGN_THUMBPRINT=<证书 SHA1 指纹>   或   QV_SIGN_SUBJECT=<证书主题名>
        QV_TIMESTAMP_URL=http://timestamp.digicert.com   # 可选
    依赖本机安装 Windows SDK 的 signtool.exe（需在 PATH）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _try_sign(dist_dir: str) -> bool:
    """可选代码签名：仅当 QV_SIGN=1 且本机有 signtool + 证书时执行，否则跳过。"""
    if os.environ.get("QV_SIGN", "0") != "1":
        return False
    signtool = shutil.which("signtool") or shutil.which("signtool.exe")
    if signtool is None:
        print("[签名] 未找到 signtool.exe（Windows SDK），跳过签名。")
        return False
    thumb = os.environ.get("QV_SIGN_THUMBPRINT", "").strip()
    subject = os.environ.get("QV_SIGN_SUBJECT", "").strip()
    if not thumb and not subject:
        print("[签名] 未配置 QV_SIGN_THUMBPRINT / QV_SIGN_SUBJECT，跳过签名。")
        return False
    ts = os.environ.get("QV_TIMESTAMP_URL", "http://timestamp.digicert.com").strip()
    # 收集待签名文件：主 exe + 所有 dll/pyd（提升 SmartScreen 信誉）
    targets = []
    for root, _, files in os.walk(dist_dir):
        for f in files:
            if f.lower().endswith((".exe", ".dll", ".pyd")):
                targets.append(os.path.join(root, f))
    if not targets:
        return False
    if thumb:
        cert_arg = f"/sha1 {thumb}"
    else:
        cert_arg = f'/n "{subject}"'
    ok_all = True
    for t in targets:
        cmd = (f'"{signtool}" sign /tr "{ts}" /td sha256 /fd sha256 '
               f'{cert_arg} "{t}"')
        rc = subprocess.call(cmd, shell=True)
        if rc != 0:
            ok_all = False
            print(f"[签名] 失败：{os.path.basename(t)} (rc={rc})")
        else:
            print(f"[签名] 已签名：{os.path.basename(t)}")
    return ok_all


def main() -> None:
    spec = os.path.join(HERE, "futures_qt.spec")
    if not os.path.exists(spec):
        print("[错误] 未找到 futures_qt.spec")
        sys.exit(1)
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", spec]
    print("[构建] 执行：", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=HERE)
    if rc == 0:
        out = os.path.join(HERE, "dist", "FuturesQuant")
        print("[完成] 可执行文件位于：")
        print(f"        {out}")
        _try_sign(out)
        print("[说明] 把整个 dist/FuturesQuant/ 目录发给用户即可；")
        print("        首次运行会自动在 exe 同级（或 AppData）生成 data/ 存放数据库与配置。")
        print("        如需安装向导，请用 packaging/installer.iss 打包（见 packaging/分发说明.md）。")
    else:
        print(f"[失败] PyInstaller 返回码 {rc}；请确认已安装 pyinstaller 且环境正常。")
    sys.exit(rc)


if __name__ == "__main__":
    main()
