"""自证 `tools/check.py` 的「失败转储」路径真的能产出定位证据。

为什么存在
----------
`check.py` 的价值在于「一条命令判 CI」。但门禁脚本自己的**失败分支**一旦不工作
（比如转储写不进去、回显切片取错段），失败时只会打印一个 `PASSED=560` 的数字，
定位成本又全推回给人 —— 这正是本项目反复踩的「测量失真」：
**能报绿色的工具，不代表失败时也能报Why**。

所以这个脚本故意制造一个非 0 退出的子进程，验证三件事：
1. `run()` 非 0 时确实落盘 `.pytest_tmp/check_fail_<key>.log`；
2. 落盘内容里有 `rc=` 与命令原文；
3. `_echo_tail()` 能取到尾部可诊断的行。

用法
----
    python tools/check_selftest.py          # 全量（含真跑单测，约 5 分钟）
    python tools/check_selftest.py --quick  # 只测转储路径（秒级）

退出码：0 = 自证通过；1 = 门禁失败分支失效。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def _test_dump_path(quick: bool) -> int:
    """验证失败转储：造一个必失败的-child，看 check.run 有没有留下证据。"""
    sys.path.insert(0, str(ROOT / "tools"))
    import check  # noqa: PLC0415

    env = check._base_env()
    key = "selftest_quick" if quick else "selftest"

    # 造一个必失败、且 stderr 里带可辨识 token 的子进程，用来验证转储内容
    child = [PY, "-c", "import sys; sys.stderr.write('boom-from-child\\n');"
                       " sys.exit(3)"]
    rc, summary = check.run(child, env, note=lambda _out: "fake-facts", key=key)

    dump = ROOT / ".pytest_tmp" / f"check_fail_{key}.log"
    ok = True

    if rc != 3:
        print(f"  [FAIL] run() 未返回子进程退出码：rc={rc}")
        ok = False
    else:
        print(f"  [PASS] run() 透传子进程退出码：{summary.strip()}")

    if not dump.exists():
        print(f"  [FAIL] 失败转储未落盘：{dump}")
        return 1
    text = dump.read_text(encoding="utf-8", errors="replace")
    for token in ("rc=3", "boom-from-child"):
        if token in text:
            print(f"  [PASS] 转储含诊断证据：{token}")
        else:
            print(f"  [FAIL] 转储缺少诊断证据：{token}")
            ok = False

    tail = check._echo_tail(text, limit=5).splitlines()
    if tail and tail[-1].startswith("        ") and "boom-from-child" in tail[-1]:
        print("  [PASS] 尾部回显取到最后一行诊断信息")
    else:
        print(f"  [FAIL] 尾部回显取错段落：{tail}")
        ok = False

    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    quick = "--quick" in (argv or sys.argv[1:])
    print("=" * 68)
    print(f"check.py 失败分支自证（{'quick' if quick else 'full'}）")
    print("=" * 68)

    # 注意 `== 0` 而不是直接当布尔：_test_dump_path 成功时返回 **0**，
    # 直接赋给 ok 会被当 falsy，自证自己报失败（这次就是这么栽的）。
    ok = _test_dump_path(quick) == 0

    if not quick:
        t0 = time.time()
        proc = subprocess.run([PY, "tools/check.py"], cwd=str(ROOT),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        elapsed = time.time() - t0
        print(f"\n  [{'PASS' if proc.returncode == 0 else 'FAIL'}] "
              f"python tools/check.py  rc={proc.returncode}  {elapsed:.1f}s")
        ok = ok and proc.returncode == 0

    print("=" * 68)
    print("自证通过 ✅" if ok else "自证失败 ❌（门禁失败分支不可信）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
