"""按文件逐个跑 tests/unit 并汇总通过/失败数（规避整套件挂起）。

用法：
    python tools/run_unit_per_file.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PY = sys.executable
ROOT = Path(__file__).resolve().parent.parent
UNIT_DIR = ROOT / "tests" / "unit"


def main() -> int:
    files = sorted(UNIT_DIR.glob("*.py"))
    total_passed = 0
    total_failed = 0
    problem_files: list[str] = []

    for f in files:
        try:
            proc = subprocess.run(
                # 注意：项目 pytest.ini 的 addopts 含 `-q`，会覆盖 -v，
                # 因此只能解析汇总行（"18 passed in 23.47s"）。
                [PY, "-m", "pytest", str(f), "-p", "no:cacheprovider"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            out = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            problem_files.append(f"{f.name} (TIMEOUT)")
            continue

        import re

        m = re.search(r"(\d+) passed", out)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+) failed", out)
        failed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+) error", out)
        errors = int(m.group(1)) if m else 0
        total_passed += passed
        total_failed += failed + errors
        # rc=5 = 未收集到用例（下划线前缀文件被 python_files=test_*.py 排除）
        skipped_nocollect = proc.returncode == 5
        if failed or errors or (proc.returncode != 0 and not skipped_nocollect):
            problem_files.append(
                f"{f.name} (failed={failed} err={errors} rc={proc.returncode})")
        elif skipped_nocollect:
            problem_files.append(f"{f.name} (无用例，pytest 未收集)")

    print("=" * 60)
    print(f"tests/unit 逐文件汇总：PASSED={total_passed}  FAILED={total_failed}")
    if problem_files:
        print("\n问题文件：")
        for p in problem_files:
            print(f"  - {p}")
    else:
        print("全部文件通过 ✅")
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
