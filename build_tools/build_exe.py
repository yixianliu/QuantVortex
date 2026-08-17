"""打包为桌面 exe（Windows 优先，跨平台亦可）。

前置：
    pip install pyinstaller
运行：
    python build_exe.py
产物：dist/FuturesQuant/ 目录（含 FuturesQuant.exe + 依赖 + config/）。
config/ 已通过 spec 的 datas 打入；首次启动会在 exe 同级创建 data/，
若 exe 在只读目录则回退到 %APPDATA%/FuturesQuant/data（见 futures_quant/runtime.py）。
如需完全自包含字体，把中文字体放入 assets/fonts/ 再构建。

密钥扫描门禁（强制，无法通过环境变量关闭）：
    构建前扫描源码树，构建后扫描 dist/ 二进制产物。
    任一环节发现疑似密钥立即中止，绝不产出带密钥的安装包。
    确属误报时，在对应代码行加注释 `# secret-scan: allow` 显式放行 ——
    这是唯一的逃生口，且会留在代码里被 review 看到。

    追查已知历史泄露密钥：
        QV_SCAN_LITERALS="<key1>,<key2>"   # 逗号分隔，仅本机环境变量，不入库

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
ROOT = os.path.dirname(HERE)   # 项目根目录：main.py / dist 都在这里

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import secret_scan  # noqa: E402

# 按设计存放本地真实凭据的文件名，绝不允许出现在公开分发的产物里。
# 与 futures_qt.spec 的 CONFIG_DENY 对应：spec 在源头不收集，这里在产物侧复查，
# 防止将来改了打包方式（换 spec、加 --add-data、换 hook）后重新漏出去。
_FORBIDDEN_IN_ARTIFACT = {
    "ctp_settings.json",      # 实盘/仿真期货账户凭据
    "secrets.json",
    "credentials.json",
    "upstream.json",          # 上游 AI 密钥（历史遗留名），任何情况下都不入产物
    ".env",
}
# 公开 CA 信任链，只含公钥证书，不是私钥；certifi / botocore 都会带一份。
# （若里面真混了私钥块，构建后的字节级密钥扫描会单独拦下。）
_ARTIFACT_CRED_ALLOW = {"cacert.pem"}


def _literals() -> list[str]:
    """从环境变量读取需要精确追查的历史泄露密钥。"""
    raw = os.environ.get("QV_SCAN_LITERALS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _gate_source() -> None:
    """构建前门禁：源码树不得含硬编码密钥。"""
    print("[门禁] 构建前扫描源码树 ...")
    findings = secret_scan.scan_paths(
        [ROOT], literals=_literals(),
        skip_dirs=["dist", "build", "installer_out", "tmp", "__pycache__"])
    if findings:
        print(f"[阻断] 源码中发现 {len(findings)} 处疑似密钥，已中止打包：",
              file=sys.stderr)
        for f in findings:
            print(str(f), file=sys.stderr)
        print("\n密钥不得进入客户端。请改由用户在运行时通过环境变量注入。",
              file=sys.stderr)
        sys.exit(3)
    print("[门禁] 源码扫描通过。")


def _verify_artifact(dist_dir: str) -> None:
    """构建后验证：产物二进制中不得出现任何密钥。"""
    print("[验证] 扫描打包产物（含 exe / pyc / dll 字节级）...")
    findings = secret_scan.scan_paths(
        [dist_dir], literals=_literals(), binary_only=True)
    if findings:
        print(f"[阻断] 产物中发现 {len(findings)} 处疑似密钥：", file=sys.stderr)
        for f in findings:
            print(str(f), file=sys.stderr)
        print("\n该产物不可分发，请排查后重新构建。", file=sys.stderr)
        sys.exit(4)

    # 凭据文件黑名单：密钥扫描按 sk-/PRIVATE KEY 等特征匹配，抓不到
    # 「期货账号 + 密码」这类没有固定前缀的凭据，只能靠文件名兜底。
    # 这些文件按设计存放开发者本地的真实凭据，绝不能进入公开分发的产物。
    leaked_cred_files = []
    for root, dirs, files in os.walk(dist_dir):
        for f in files:
            low = f.lower()
            if low in _ARTIFACT_CRED_ALLOW:
                continue
            if low in _FORBIDDEN_IN_ARTIFACT or low.endswith(
                    (".local.json", ".secret.json", ".pem", ".key")):
                leaked_cred_files.append(
                    os.path.relpath(os.path.join(root, f), dist_dir))
    if leaked_cred_files:
        print(f"[阻断] 产物中混入 {len(leaked_cred_files)} 个本地凭据文件：",
              file=sys.stderr)
        for p in leaked_cred_files[:20]:
            print(f"        {p}", file=sys.stderr)
        print("\n这些文件按设计存放真实账户凭据，不得随公开产物分发。\n"
              "请从 futures_qt.spec 的 datas 收集逻辑中排除后重新构建。",
              file=sys.stderr)
        sys.exit(7)
    print("[验证] 产物中无本地凭据文件混入。")

    # 检查 user_settings.json 是否包含 ai.api_key（打包模式下不应存在）
    settings_file = os.path.join(dist_dir, "data", "user_settings.json")
    if os.path.exists(settings_file):
        try:
            import json
            with open(settings_file, "r", encoding="utf-8") as fh:
                content = fh.read()
            if '"api_key"' in content or "'api_key'" in content:
                print("[阻断] 产物中 user_settings.json 包含 ai.api_key 字段！",
                      file=sys.stderr)
                print("        打包模式下密钥不得持久化，请检查 AIConfig 实现。",
                      file=sys.stderr)
                sys.exit(8)
            print("[验证] 产物中 user_settings.json 无 ai.api_key 字段。")
        except Exception as e:
            print(f"[警告] 无法读取 user_settings.json：{e}", file=sys.stderr)

    # 顺带确认字节码缓存没有混进产物（历史泄露路径）
    stray = []
    for root, dirs, files in os.walk(dist_dir):
        if "__pycache__" in dirs:
            stray.append(os.path.join(root, "__pycache__"))
    if stray:
        print(f"[警告] 产物中仍存在 {len(stray)} 个 __pycache__ 目录：")
        for p in stray[:5]:
            print(f"        {os.path.relpath(p, dist_dir)}")
        print("        （已通过密钥扫描，但建议从 spec 的 datas 中剔除）")
    else:
        print("[验证] 产物中无 __pycache__ 残留。")
    print("[验证] 产物扫描通过：未发现任何密钥。")


def _summarize(dist_dir: str) -> None:
    """产物完整性摘要：文件数、体积、主 exe 是否就位。"""
    exe_path = os.path.join(dist_dir, "FuturesQuant.exe")
    count = 0
    total = 0
    for root, _, files in os.walk(dist_dir):
        for f in files:
            count += 1
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    print(f"[产物] 主程序：{'存在' if os.path.exists(exe_path) else '缺失！'}"
          f"  文件数：{count}  总体积：{total / 1024 / 1024:.1f} MB")
    if not os.path.exists(exe_path):
        print("[失败] 未生成 FuturesQuant.exe", file=sys.stderr)
        sys.exit(5)


def _prepare_dist(dist_dir: str) -> str | None:
    """腾空目标产物目录，返回被归档的旧目录路径（无则 None）。

    PyInstaller 的 COLLECT 在写入前会强制清空 distpath 下的同名目录。
    在删除受限的环境里（CI 沙箱、回收站不可用、目录被占用、只读挂载）
    这一步会抛 PermissionError / OSError 直接终止构建 —— 而此时
    Analysis/PYZ/EXE 都已经跑完，白白浪费十几分钟。

    所以提前处理：先尝试删除，删不掉就重命名归档（rename 不需要删除权限），
    两者都失败才报错退出。
    """
    if not os.path.isdir(dist_dir):
        return None
    try:
        shutil.rmtree(dist_dir)
        print(f"[准备] 已清除旧产物目录：{os.path.basename(dist_dir)}")
        return None
    except Exception as exc:                      # noqa: BLE001 - 环境相关，任何异常都要兜底
        print(f"[准备] 旧产物目录无法删除（{type(exc).__name__}），改为归档重命名。")
    import time
    archived = f"{dist_dir}.old-{int(time.time())}"
    try:
        os.rename(dist_dir, archived)
    except OSError as exc:
        print(f"[失败] 旧产物目录既不能删除也不能重命名：{dist_dir}\n        {exc}",
              file=sys.stderr)
        print("        请手动移走后重试，或用 --distpath 指定新的输出目录。",
              file=sys.stderr)
        sys.exit(6)
    print(f"[准备] 旧产物已归档为：{os.path.basename(archived)}")
    return archived


def _cleanup_archived(archived: str | None) -> None:
    """构建成功后尽力清掉归档的旧产物；删不掉只提示，不影响构建结果。"""
    if not archived or not os.path.isdir(archived):
        return
    try:
        shutil.rmtree(archived)
        print(f"[清理] 已删除归档的旧产物：{os.path.basename(archived)}")
    except Exception:                             # noqa: BLE001
        print(f"[清理] 归档的旧产物未能自动删除，可手动移除：{archived}")


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

    # 1) 构建前门禁：源码里有密钥就不许打包
    _gate_source()

    # 2) 打包
    # 用带时间戳的全新 workpath，而不是 --clean 去删旧缓存：
    # 前者在任何环境下都能保证「干净构建」，后者在目录被占用或
    # 删除受限的环境（CI 沙箱、只读挂载）里会直接失败。
    import time
    workpath = os.path.join(ROOT, "build", f"pyi_{int(time.time())}")
    os.makedirs(workpath, exist_ok=True)
    # 旧产物目录必须在 PyInstaller 启动前腾空，否则 COLLECT 阶段
    # （已耗时十几分钟之后）才会因删除失败而崩溃。
    archived = _prepare_dist(os.path.join(ROOT, "dist", "FuturesQuant"))
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
           "--workpath", workpath,
           "--distpath", os.path.join(ROOT, "dist"), spec]
    print("[构建] 执行：", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        print(f"[失败] PyInstaller 返回码 {rc}；请确认已安装 pyinstaller 且环境正常。")
        sys.exit(rc)

    out = os.path.join(ROOT, "dist", "FuturesQuant")

    # 3) 构建后验证：产物字节级无密钥 + 完整性摘要
    _summarize(out)
    _verify_artifact(out)
    _cleanup_archived(archived)

    print("[完成] 可执行文件位于：")
    print(f"        {out}")
    _try_sign(out)
    print("[说明] 把整个 dist/FuturesQuant/ 目录发给用户即可；")
    print("        首次运行会自动在 exe 同级（或 AppData）生成 data/ 存放数据库与配置。")
    print("        客户端不含任何上游密钥：云端研判能力需由用户通过环境变量 QV_AGNES_API_KEY 注入，")
    print("        未注入时自动降级为本地规则合成，功能不中断。")
    print("        如需安装向导，请用 packaging/installer.iss 打包（见 packaging/分发说明.md）。")
    sys.exit(0)


if __name__ == "__main__":
    main()
