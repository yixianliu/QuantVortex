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


def _test_preflight() -> int:
    """锁定 PyQt6 预检判定（``_should_fast_fail``）的 fixture 边界。

    这是 v5.2.12 那道"跑错解释器时给出可解释原因、而非误导性 85-fail"的
    门禁分支。它若退化（误删 ``_QT_STEPS``、把 scan 误算进 Qt 步、逻辑写反）
    只会"一直放行"或"一直拦"，其它任何测试都不会红 —— 正是本项目反复强调的
    「测判定/采集链路，不只测它生效时」。故直接喂 fixture 复算纯函数锁定边界。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import check  # noqa: PLC0415

    # (steps_running, pyqt6_ok, 期望, 说明)
    cases = [
        (["scan", "unit", "version", "perf"], False, True,
         "含 Qt 子步且缺 PyQt6 → 必须快速失败"),
        (["unit"], False, True,
         "单个 Qt 子步、缺 PyQt6 → 快速失败"),
        (["version", "perf"], False, True,
         "只含 Qt 子步、缺 PyQt6 → 快速失败"),
        (["scan"], False, False,
         "纯静态 scan、缺 PyQt6 → 仍放行（不该被拦）"),
        (["scan", "unit"], True, False,
         "有 Qt 子步但 PyQt6 可用 → 放行"),
        (["unit", "version", "perf"], True, False,
         "全 Qt 子步、PyQt6 可用 → 放行"),
        ([], False, False,
         "没有任何步要跑 → 不快速失败"),
    ]
    ok = True
    for steps, pyqt6, expect, why in cases:
        got = check._should_fast_fail(list(steps), pyqt6)
        if got == expect:
            print(f"  [PASS] 预检判 {got}（{why}）")
        else:
            print(f"  [FAIL] _should_fast_fail({steps}, pyqt6={pyqt6})"
                  f" = {got}，期望 {expect}（{why}）")
            ok = False

    # 额外锁一道：scan 绝不计入 Qt 子步，否则"只跑 scan"会被 PyQt6 预检误拦。
    if "scan" in check._QT_STEPS:
        print("  [FAIL] 'scan' 不应计入 Qt 子步（_QT_STEPS 被误改）")
        ok = False
    else:
        print("  [PASS] _QT_STEPS 不含 scan（纯静态步不被 PyQt6 预检拦）")

    return 0 if ok else 1


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

    # 注意 `== 0` 而不是直接当布尔：_test_* 成功时返回 **0**，
    # 直接赋给 ok 会被当 falsy，自证自己报失败（dump 这条就是这么栽的）。
    ok = _test_dump_path(quick) == 0
    # PyQt6 预检判定是纯函数、无副作用、快 —— 不论 quick/full 都要锁，
    # 它是 v5.2.12 那道"跑错解释器别甩误导性假红"的门禁分支。
    ok = ok and _test_preflight() == 0

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
