"""按文件逐个跑 tests/unit，**流式打印每个文件的耗时与结果**。

用途：定位「整套件挂起」时到底是哪一文件慢/卡（``tools/run_unit_per_file.py``
用 ``capture_output`` 缓冲，慢的时候全程无输出）。

设计要点（v5.2.6）：
- **结果来自流式落盘**（``tools/unit_result_logger.py`` 逐用例写 JSONL），
  不看 pytest 的汇总行。原因：某些 Qt 用例文件会在**退出期**被 CRT fast-fail
  打断（0xC0000409），此时汇总行和 ``--junitxml`` 都来不及写，
  只看 stdout 会把整个文件记成 0 个用例 —— 实际用例是「全过」的（见 m7_07）。
- **进程崩溃算失败**：Windows 下 Win32 致命码经 subprocess 出来是**正数**大数
  （0xC0000409 → 3221226505），只判 ``rc < 0`` 会漏掉 Qt 的常见崩溃。
- 跳过 ``_`` 开头文件（与 ``python_files = test_*.py`` 一致），
  它们不被 pytest 收集，但模块级代码照跑，纯浪费时间。

用法：
    python tools/run_unit_timed.py                 # 只打印异常/超时的文件
    python tools/run_unit_timed.py --verbose       # 打印每个文件
    python tools/run_unit_timed.py --only=名字片段  # 只跑匹配的文件（调试用）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PY = sys.executable
ROOT = Path(__file__).resolve().parent.parent
UNIT_DIR = ROOT / "tests" / "unit"
PER_FILE_TIMEOUT = 300         # 单文件超时（秒）
# 实测最慢 legit 文件约 153s（test_m3_03.py 特征/漂移回归，全绿但慢）。
# 早前设 120s → 该文件被 kill，且旧逻辑 **不计任何失败**（只 append 到 slow）→
# 汇总打出「FAILED=0 CRASHED=0」但这个文件的 5 个用例其实一行没跑
# （收集 754 / 汇总 749，缺口恰好 5）。慢 ≠ 绿，超时必须显性计价。
VERBOSE = "--verbose" in sys.argv


def _collect_count(f: Path) -> int | None:
    """取该文件的用例收集数（只在检测到崩溃时调用，正常路径不额外开销）。

    本机这版 pytest 的 ``--collect-only -q`` 输出形如
    ``tests/unit/xxx.py: 27``（不是标准的 ``27 tests collected``）。
    """
    try:
        proc = subprocess.run(
            [PY, "-m", "pytest", str(f), "--collect-only", "--no-header", "-q"],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=PER_FILE_TIMEOUT,
        )
        m = re.search(r":\s*(\d+)\s*$", (proc.stdout or "").strip()[-200:])
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _stream_counts(path: Path) -> dict | None:
    """从 `unit_result_logger` 流式落盘的 JSONL 里取权威计数。

    为什么需要它：某些 Qt 用例文件会在**退出期**被 CRT fast-fail 打断
    （0xC0000409）。pytest 的汇总行和 `--junitxml` 都在最后统一写出，
    进程一崩就全丢，该文件被记成 0 个用例 —— 实际用例是「全过」的。
    逐用例落盘的结果不受退出期崩溃影响。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    passed = failed = errors = skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("when") != "call":
            continue
        out = row.get("outcome")
        if out == "passed":
            passed += 1
        elif out == "failed":
            failed += 1
        elif out == "error":
            errors += 1
        elif out == "skipped":
            skipped += 1
    if passed + failed + errors + skipped == 0:
        return None
    return {"passed": passed, "failed": failed,
            "errors": errors, "skipped": skipped}


def _iter_files(pattern: str | None = None):
    """只跑 pytest 会收集的正式用例文件。

    ``pattern`` 用于 `--only` 定向调试（如只跑某个崩溃的文件）。

    **必须用 rglob**：``tests/unit/contracts/`` 这类子目录里有正式用例
    （``test_ux_contracts.py`` 就是 31 个）。曾用非递归 ``glob``
    静默漏掉它们，逐文件口径（547）与整套件口径（578）差了整整 31 个用例 ——
    测量口径必须和 ``pytest`` 自己的 ``python_files`` 对齐，别自己造第二套规则。

    过滤条件就一条：**文件名以 ``test_`` 开头**，与 ``pytest.ini`` 的
    ``python_files = test_*.py`` 完全一致。
    ``_test_data_page.py`` / ``_test_data_transfer.py`` / ``_test_mysql_roundtrip.py``
    因此被排除（它们本来就不被 pytest 收集，且 ``_test_data_transfer.py``
    导入就 >120s，逐文件跑纯属浪费几分钟）。
    """
    for f in sorted(UNIT_DIR.rglob("*.py")):
        if not f.name.startswith("test_"):
            continue
        if pattern and pattern not in f.name:
            continue
        yield f


def main() -> int:
    only = next((a.split("=", 1)[1] for a in sys.argv
                 if a.startswith("--only=")), None)
    files = list(_iter_files(only))
    total_passed = 0
    total_failed = 0
    crashed_files: list[str] = []
    slow: list[str] = []
    problems: list[str] = []

    # 结果目录必须落在项目内（D 盘）：tempfile 默认会落到 E:\Temp，
    # 在本机那是有名的慢盘，还会拖慢/干扰子进程启动。
    tmpdir = ROOT / ".pytest_tmp" / "qv_unit_results"
    tmpdir.mkdir(parents=True, exist_ok=True)
    return _loop(files, tmpdir)


def _reset_result_log(path: Path) -> None:
    """把结果日志**截断为空**（父进程创建、子进程 append），而不是删掉再建。

    踩过的坑：``unlink`` 会被沙箱安全删除守卫拦下，而它抛的是
    ``SystemExit`` —— ``except Exception`` 兜不住，异常从 ``finally`` 里
    把 ``return code`` 顶掉，一次 **全绿**的运行被报成 ``rc=1``。
    退出码是 CI 的唯一凭据，被清理逻辑污染比不清理危险得多。
    改「截断」后既不需要任何删除操作，也顺带解决了 append 模式
    残留上一轮日志导致计数翻倍（27 记成 54）的问题。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except BaseException as exc:         # SystemExit / 权限 / 只读
        print(f"[result log reset skipped] {type(exc).__name__}: {exc}")
        sys.stdout.flush()


def _loop(files: list[Path], tmpdir: Path) -> int:
    """逐个跑文件并汇总，返回进程退出码（0 全绿 / 1 有失败）。"""
    total_passed = 0
    total_failed = 0
    crashed_files: list[Path] = []
    timed_out: list[Path] = []
    slow: list[str] = []
    problems: list[str] = []
    warnings: list[str] = []

    for f in files:
        t0 = time.time()
        result_log = tmpdir / f"{f.stem}.results.jsonl"
        _reset_result_log(result_log)    # 截断而非删除：见 _reset_result_log 注释
        env = dict(os.environ)
        env["QV_UNIT_RESULT_LOG"] = str(result_log)
        # tools/ 要在 PYTHONPATH 里，unit_result_logger 才能被 -p 加载
        env["PYTHONPATH"] = str(ROOT / "tools") + os.pathsep + env.get(
            "PYTHONPATH", "")
        try:
            proc = subprocess.run(
                [PY, "-m", "pytest", str(f), "-p", "no:cacheprovider",
                 "-p", "unit_result_logger"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                env=env,
                encoding="utf-8",
                errors="replace",
                timeout=PER_FILE_TIMEOUT,
            )
            out = proc.stdout + proc.stderr
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            # 超时 = 该文件的用例**一行没跑完**，结果不可信。
            # 绝不能只是记进 slow 就 continue：那样汇总会显示「FAILED=0」，
            # 但总用例数比收集数少一截（静默失真，见 TIMEOUT 注释）。
            timed_out.append(f)
            slow.append(f"{f.name} (>={PER_FILE_TIMEOUT}s TIMEOUT)")
            problems.append(
                f"{f.name} (超时 >={PER_FILE_TIMEOUT}s 未完成：该文件用例数未计入，"
                f"汇总不可信)")
            print(f"[TIMEOUT {PER_FILE_TIMEOUT}s] {f.name}  ← 用例未跑完，计为失败")
            sys.stdout.flush()
            continue

        # 优先用流式结果：退出期崩溃时 stdout 那行汇总和 junit 都来不及写，
        # 只看 stdout 会把整个文件记成 0 用例（用例其实全过了）。
        jc = _stream_counts(result_log)
        if jc:
            passed = jc["passed"]
            failed, errors = jc["failed"], jc["errors"]
        else:
            m = re.search(r"(\d+) passed", out)
            passed = int(m.group(1)) if m else 0
            m = re.search(r"(\d+) failed", out)
            failed = int(m.group(1)) if m else 0
            m = re.search(r"(\d+) error", out)
            errors = int(m.group(1)) if m else 0
        total_passed += passed
        total_failed += failed + errors

        elapsed = time.time() - t0
        flag = ""
        # 进程崩溃：Windows 下 subprocess 对信号给负数（如 SIGSEGV -11），
        # 对 Win32 致命码（0xC0000409 / 0xC0000135）给**正数**大数，
        # 所以两个区间都要判（只判 rc<0 会漏掉 Qt 的常见崩溃）。
        # 崩溃必须计为失败，否则该文件静默贡献 0 用例 —— 旧版就是这个坑，
        # 把「25 个用例全过 + 退出期 abort」读成了 0 passed。
        if rc is not None and (rc < 0 or rc > 255):
            # 区分「Qt 退出期 abort 但用例全绿」与「真崩在用例上」：
            # 只有「已通过数 == 收集数」且无失败/错误，才认定断言层面全过
            # （offscreen Qt 清理问题），否则算真失败。
            collected = _collect_count(f)
            complete = (collected == passed and failed == 0 and errors == 0)
            crashed_files.append(f)
            if complete:
                warnings.append(
                    f"{f.name} (退出期 abort，但 {passed}/{collected} 用例全绿，"
                    f"rc={rc} —— offscreen Qt 清理问题，非断言失败)")
                flag = " ~~ "
            else:
                total_failed += 1
                problems.append(
                    f"{f.name} (进程崩溃 passed={passed}/{collected} rc={rc} "
                    f"fail={failed} err={errors})")
                flag = " !! "
        elif failed or errors or (rc != 0 and rc != 5):
            problems.append(
                f"{f.name} (passed={passed} failed={failed} err={errors} rc={rc})")
            flag = " !! "
        elif rc == 5:
            problems.append(f"{f.name} (无用例，pytest 未收集)")
            flag = " -- "
        elif elapsed >= 20:
            slow.append(f"{f.name} ({elapsed:.1f}s)")
            flag = " ++ "

        if VERBOSE or flag:
            print(f"{flag}{f.name:<48} passed={passed:<4} {elapsed:6.1f}s rc={rc}")
            sys.stdout.flush()

    print("=" * 60)
    print(f"tests/unit 逐文件汇总（{len(files)} 个文件）："
          f"PASSED={total_passed}  FAILED={total_failed}  "
          f"CRASHED={len(crashed_files)}  TIMEOUT={len(timed_out)}")
    if timed_out:
        print("\n超时文件（用例未跑完 —— 汇总 PASSED 数**少于**收集数，不可信）：")
        for t in timed_out:
            print(f"  - {t.name}")
    if crashed_files:
        print("\n崩溃文件（已用流式结果找回用例数，仍需处理）：")
        for c in crashed_files:
            print(f"  - {c.name}")
    if warnings:
        print("\n告警（不含失败的崩溃）：")
        for w in warnings:
            print(f"  - {w}")
    if problems:
        print("\n问题文件：")
        for p in problems:
            print(f"  - {p}")
    if slow:
        print("\n慢文件：")
        for p in slow:
            print(f"  - {p}")
    # 超时必须让门禁变红：否则「慢」被读成「绿」。
    return 1 if (total_failed or timed_out) else 0


if __name__ == "__main__":
    raise SystemExit(main())
