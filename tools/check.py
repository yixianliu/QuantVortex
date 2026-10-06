"""统一门禁入口：一条命令跑完全部质量闸门。

本项目此前是**每个门禁各跑各的**（``scan_silent_bail.py`` / ``run_unit_timed.py``
/ ``run_version_checks.py`` / ``perf_ui_budget.py``），日常开发得记四套命令；
而且「跑没跑全、跑了多少用例」没人能一句话回答。这个脚本把它们串成一条，
并给出**可自证的计数**（不是 pytest 的汇总行 —— 本项目 Qt 用例在退出期
经常吞掉汇总行，数字必须以逐用例落盘为准）。

门禁清单
--------
1. ``scan_silent_bail``       AST 静态门禁：`except` 钉死 None → 判空静默 return
                              的「静默失效」链式反模式（存在未留痕 CHAIN 即失败）。
2. ``pytest tests/unit``      单测（逐用例 JSONL 计数，崩溃也算失败）。
3. ``run_version_checks``     版本单一数据源：包版本 / 打包资源 / 界面防漂移。
4. ``perf_ui_budget``         性能预算：主题全量刷新 / 表格填充 / K 线 paint p95 等。

用法
----
    python tools/check.py              # 跑全部
    python tools/check.py --skip perf  # 跳过慢的性能预算
    python tools/check.py --step unit  # 只跑单测

退出码：全部 PASS → 0；任一 FAIL → 1（CI 直接判这个）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
RESULTS = ROOT / ".pytest_tmp" / "check_results.jsonl"

# Qt 依赖的门禁子步（需要 PyQt6）；scan 是纯 AST，不依赖 Qt。
# 在「无 PyQt6 的解释器」下跑这些子步会退化成「一堆 ModuleNotFoundError 被
# 记成 N 个 FAILED」的**误导性假红**（曾把 3.13.12 无 PyQt6 的运行误读成
# 85 条用例失败）。因此对「这些子步将真正执行且当前解释器缺 PyQt6」做
# 提前快速失败，给出可解释的原因，而不是让错误数字冒出来。
_QT_STEPS = {"unit", "version", "perf"}


def _pyqt6_available() -> bool:
    """当前解释器（== PY）能否 import PyQt6。check.py 就运行在 PY 里，
    故直接在本进程探测即可（无需再 fork 一个子进程）。"""
    try:
        import PyQt6  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _should_fast_fail(steps_running: list[str], pyqt6_ok: bool) -> bool:
    """纯判定：「将执行的门禁里含 Qt 子步」且「当前解释器缺 PyQt6」→ True。

    抽出为纯函数（与 scan_silent_bail 的 scan_source 同款），便于
    check_selftest 直接喂 fixture 锁定这道分支 —— 否则该预检一旦退化
    （例如误删 _QT_STEPS、把 scan 也算进 Qt 步）只会「一直放行」或
    「一直拦」，没有任何测试会红。判定不含副作用、可被直接复算。
    """
    qt_will_run = [k for k in steps_running if k in _QT_STEPS]
    return bool(qt_will_run) and not pyqt6_ok


def _base_env() -> dict:
    r"""统一子进程环境：**必须为 offscreen**，且 TMP/TEMP 钉在项目内。

    TMP 默认会落到 ``E:\Temp``，本机那是有名的慢盘，还会干扰 Qt 子进程启动。
    """
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    tmp = str(ROOT / ".pytest_tmp")
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = tmp
    extra = os.pathsep.join([str(ROOT / "tools"), str(ROOT)])
    env["PYTHONPATH"] = os.pathsep.join([extra, env.get("PYTHONPATH", "")])
    return env


def _scan_facts() -> str:
    """从 scan_silent_bail 的 JSON 里取「未留痕 CHAIN 数」作为可证数字。"""
    try:
        rows = json.loads(RESULTS.read_text(encoding="utf-8") or "[]")
        silent = [r for r in rows
                  if r.get("rule") == "CHAIN" and r.get("silent")]
        chain = [r for r in rows if r.get("rule") == "CHAIN"]
        return f"CHAIN {len(chain)} / 未留痕 {len(silent)}"
    except Exception:
        return "计数不可用"


def _unit_facts(out: str) -> str:
    """取逐文件 runner 的汇总计数，并**验证它自己报了什么**。

    「跑了多少用例」这类数字在本项目出过多次静默失真
    （残留日志让 27 记成 54、清理异常把全绿报成 rc=1），所以摘要直接从
    runner 的汇总行解析，和实际 rc 一起看。
    """
    m = re.search(r"PASSED=(\d+)\s+FAILED=(\d+)\s+CRASHED=(\d+)", out or "")
    return f"PASSED={m.group(1)} FAILED={m.group(2)} CRASHED={m.group(3)}" if m \
        else "计数不可用"


def run(args: list[str], env: dict, note=None, key: str = "") -> tuple[int, str]:
    """跑一个门禁，返回 (rc, 摘要)。

    **失败必须回显**：本项目「全绿但 rc=1」「跑了多少用例但不知道哪个文件挂了」
    都出过。所以非 0 退出时把 stdout+stderr 落盘，并回打尾部若干行 ——
    否则门禁只给一个数字，等于把定位成本又推回给人。
    """
    t0 = time.time()
    proc = subprocess.run(args, cwd=str(ROOT), env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    if proc.returncode != 0:
        dump = ROOT / ".pytest_tmp" / f"check_fail_{key}.log"
        try:
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump.write_text(
                f"$ {' '.join(args)}\n"
                f"rc={proc.returncode}\n\n--- stdout ---\n{proc.stdout}\n"
                f"--- stderr ---\n{proc.stderr}\n",
                encoding="utf-8")
        except BaseException as exc:  # 沙箱守卫抛 SystemExit，非 Exception
            print(f"  [dump skipped] {type(exc).__name__}: {exc}")
            sys.stdout.flush()

    facts = note(proc.stdout) if note else ""
    return proc.returncode, f"{facts}  {elapsed:.1f}s" if facts else f"{elapsed:.1f}s"


def _echo_tail(text: str, limit: int = 60) -> str:
    """取尾部若干非空行（失败日志往往很长，只打尾巴就够定位）。"""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return "\n".join("        " + ln for ln in lines[-limit:])


def main() -> int:
    ap = argparse.ArgumentParser(description="QuantVortex 统一质量门禁")
    ap.add_argument("--skip", nargs="*", default=[],
                    help="跳过的门禁（如 perf）")
    ap.add_argument("--step", default=None, help="只跑某个门禁")
    a = ap.parse_args()

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    env = _base_env()

    # ---- 快速失败护栏：Qt 子步需要 PyQt6，当前解释器缺了就别硬跑 ----
    # 否则 unit 会报「PASSED=… FAILED=85」这类误导数字（其实是收集期
    # ModuleNotFoundError），version/perf 直接 ModuleNotFoundError，全红。
    running = []
    for key in ("scan", "unit", "version", "perf"):
        if a.step and key != a.step:
            continue
        if key in a.skip:
            continue
        running.append(key)
    if _should_fast_fail(running, _pyqt6_available()):
        qt_steps_running = [k for k in running if k in _QT_STEPS]
        print("=" * 68)
        print("QuantVortex 统一质量门禁 —— PyQt6 预检未通过 ❌")
        print("=" * 68)
        print(f"  当前解释器：{PY}")
        print("  缺 PyQt6。以下需要 Qt 的门禁会假红：" + ", ".join(qt_steps_running))
        print("  请改用项目运行解释器（含 PyQt6）跑本门禁，例如：")
        print("      /d/anaconda3/python.exe tools/check.py")
        print("  （纯静态的 scan 步不依赖 Qt，可用 --step scan 单独跑。）")
        return 2

    # (key, 显示名, 命令, 摘要函数)；key 用于 --skip/--step（别用中文做键）
    steps = [
        ("scan", "静态门禁 scan_silent_bail",
         [PY, "tools/scan_silent_bail.py", "--min-severity", "high",
          "--format", "json", "--output", str(RESULTS)],
         lambda _out: _scan_facts()),
        # **故意不用整套件 `pytest tests/unit`**：整套件在本机是间歇性挂的
        # （实测卡在 test_m4_08_data_grid.py，16 分钟不动；跑得顺时 2m17s）。
        # 逐文件串行跑更慢一点但从不挂，还能给出「哪个文件有问题」，
        # 且 rglob 已覆盖 contracts/ 子目录，覆盖量与整套件等价。
        ("unit", "单元测试 tests/unit",
         [PY, "tools/run_unit_timed.py"],
         lambda _out: _unit_facts(_out)),
        ("version", "版本防漂移",
         [PY, "tests/e2e/run_version_checks.py"], None),
        ("perf", "性能预算",
         [PY, "tools/perf_ui_budget.py"], None),
    ]

    print("=" * 68)
    print("QuantVortex 统一质量门禁")
    print("=" * 68)

    failed = 0
    for key, name, cmd, note in steps:
        if a.step and key != a.step:
            continue
        if key in a.skip:
            print(f"  [SKIP] {name}")
            continue
        rc, summary = run(cmd, env, note, key)
        ok = rc == 0
        failed += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<30} {summary}")
        sys.stdout.flush()
        if not ok:
            dump = ROOT / ".pytest_tmp" / f"check_fail_{key}.log"
            if dump.exists():
                # 打**整份尾部**而不是某一段：失败最有用的信息（pytest 的
                # FAILED 明细、runner 的逐文件计数）总在末尾，切段反而把
                # “$ 命令 / rc=” 这些噪音顶到前面。
                text = dump.read_text(encoding="utf-8", errors="replace")
                print(_echo_tail(text))
                print(f"        （完整输出：{dump}）")
            sys.stdout.flush()

    print("=" * 68)
    print("全部通过 ✅" if not failed else f"存在 {failed} 项失败 ❌")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
