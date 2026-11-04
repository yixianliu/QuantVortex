"""把 QuantVortex 的质量钩子安装为 git 钩子（可重复执行、幂等）。

设计
----
本项目的质量门禁此前**靠人记得跑**：`tools/check.py`、`secret_scan.py`、
`scan_silent_bail.py` 都要手动触发。这份安装器把其中**秒级的两关**
（密钥 + 静默失效）固化进 `pre-commit`，让「带密钥/带静默失效的代码」
在 `git commit` 那一刻就被拦下，而不是流到提交历史里。

为什么用 `core.hooksPath` 而不是直接写 `.git/hooks`
-----------------------------------------------------
`.git/` 不在版本控制里 —— 写在里面的钩子**克隆后丢失**。
把钩子放进 `tools/hooks/`（受控），再用
    git config core.hooksPath tools/hooks
指向它，克隆方跑一次本安装器即可复现门禁。

LFS 兼容（零行为变化）
----------------------
本仓库装了 git-lfs（`.git/hooks/` 里有 LFS 的 4 个钩子）。`core.hooksPath`
一旦指向别处，`.git/hooks` 里的钩子就不再被 git 调用，LFS 行为会悄悄丢失。
安装时会把 `post-checkout / post-commit / post-merge / pre-push`（若存在）
**原样拷贝**进 `tools/hooks/`，保证 LFS 继续工作。若 LFS 钩子尚未生成，
则跳过（无副作用）；后续 `git lfs install` 重新生成后重跑本安装器即可。

用法
----
    python tools/install_hooks.py            # 安装（幂等）
    python tools/install_hooks.py --check    # 只校验当前是否已安装，不改配置

逃生口（在钩子里，不在这里）：
    QV_SKIP_HOOKS=1 git commit ...           # 跳过质量钩子（紧急/批量）
    QV_PREPUSH_FULL_TESTS=1 git push ...     # push 时跑全量门禁
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / "tools" / "hooks"
LFS_HOOKS = [
    "post-checkout", "post-commit", "post-merge", "pre-push",
]


def _git(*args: str, check: bool = True) -> str:
    """跑一条 git 命令，返回 stdout。"""
    proc = subprocess.run(
        ["git", *args], cwd=str(ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc.stdout


def _sync_lfs_hooks() -> list[str]:
    """把 `.git/hooks` 里 LFS 的钩子原样拷进 tools/hooks，返回拷了哪些。

    **绝不覆盖自定义钩子**：若 `tools/hooks/<name>` 已存在且**不是** LFS 占位
    脚本（首行非 LFS 的 `command -v git-lfs` 守卫），说明是我们自己的钩子
    （例如 `pre-push` 已内建 LFS 透传 + 可选门禁），跳过，避免被 LFS 版冲掉。
    """
    git_hooks = Path(_git("rev-parse", "--git-dir", check=False).strip()) / "hooks"
    synced: list[str] = []
    for name in LFS_HOOKS:
        src = git_hooks / name
        if not src.exists():
            continue
        dst = HOOKS_DIR / name
        if dst.exists():
            dst_head = dst.read_text(encoding="utf-8", errors="replace")[:80]
            src_head = src.read_text(encoding="utf-8", errors="replace")[:80]
            if dst_head == src_head:
                synced.append(f"{name}（已是 LFS 原版）")
            else:
                synced.append(f"{name}（自定义钩子，保留不覆盖）")
            continue
        shutil.copyfile(src, dst)
        synced.append(f"{name}（自 .git/hooks 同步）")
    return synced


def install() -> int:
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    for required in ("pre-commit", "pre-push"):
        hook = HOOKS_DIR / required
        if not hook.exists():
            raise SystemExit(f"缺少 {hook.relative_to(ROOT)}（本安装器不负责生成钩子脚本）")

    synced = _sync_lfs_hooks()

    cur = _git("config", "--get", "core.hooksPath", check=False).strip()
    if cur == "tools/hooks":
        print("core.hooksPath 已是 tools/hooks（幂等，无需改动）")
    else:
        _git("config", "core.hooksPath", "tools/hooks")
        print(f"core.hooksPath: {cur or '(未设置)'} → tools/hooks")

    if synced:
        print("LFS 钩子同步：" + "；".join(synced))
    else:
        print("LFS 钩子：.git/hooks 下未见 LFS 钩子，跳过（若已 git lfs install，"
              "重跑本安装器可补齐）")

    print(f"\n✅ 已安装。钩子位于 {HOOKS_DIR.relative_to(ROOT)}/")
    print("   - pre-commit：密钥 + 静默失效（只扫暂存改动，秒级）")
    print("   - pre-push  ：LFS 透传 + 可选全量门禁（QV_PREPUSH_FULL_TESTS=1）")
    print("   逃生口：QV_SKIP_HOOKS=1 git commit …")
    return 0


def check_only() -> int:
    cur = _git("config", "--get", "core.hooksPath", check=False).strip()
    ok = (HOOKS_DIR / "pre-commit").exists() and \
         (HOOKS_DIR / "pre-push").exists()
    print(f"core.hooksPath = {cur or '(未设置)'}；钩子脚本齐全 = {ok}")
    print("已安装" if (cur == "tools/hooks" and ok) else "未安装（运行不带 --check 以安装）")
    return 0 if (cur == "tools/hooks" and ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="安装 QuantVortex git 质量钩子")
    ap.add_argument("--check", action="store_true",
                   help="只校验是否已安装，不改动配置")
    args = ap.parse_args()
    return check_only() if args.check else install()


if __name__ == "__main__":
    raise SystemExit(main())
