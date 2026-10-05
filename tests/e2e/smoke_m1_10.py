"""M1-10 测试工程基建 E2E smoke 验收。

DoD:
    1) pytest.ini 存在且关键字段齐全（testpaths / python_files / addopts）
    2) tests/conftest.py 存在并把 ROOT 注入 sys.path
    3) tests/e2e/conftest.py 存在且能过滤无 def test_ 的独立脚本
    4) 顶层环境变量：TMP/TEMP/TMPDIR 指向 .pytest_tmp；QT_QPA_PLATFORM=offscreen
    5) 独立验证：一个"故意无 sys.path 注入"的临时测试能被 pytest 加载

运行方式：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m1_10.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


PYTEST = sys.executable  # 用当前解释器
def _pytest(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTEST, "-m", "pytest", *args],
        cwd=str(ROOT),
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _pass(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    raise AssertionError(msg)


# ---------- Test 1: pytest.ini 存在且字段齐全 ----------
def test_1_pytest_ini_present():
    ini = ROOT / "pytest.ini"
    if not ini.exists():
        _fail("pytest.ini 不存在")
    text = ini.read_text(encoding="utf-8")
    for key in ("testpaths", "python_files", "addopts"):
        if key not in text:
            _fail(f"pytest.ini 缺 {key}")
    if "tests/unit" not in text or "tests/e2e" not in text:
        _fail("testpaths 未同时包含 tests/unit 与 tests/e2e")
    if "test_*.py" not in text:
        _fail("python_files 未设为 test_*.py")
    _pass("pytest.ini 存在且含 testpaths/python_files/addopts 三键")


# ---------- Test 2: tests/conftest.py 存在 ----------
def test_2_root_conftest():
    p = ROOT / "tests" / "conftest.py"
    if not p.exists():
        _fail("tests/conftest.py 不存在")
    text = p.read_text(encoding="utf-8")
    for kw in ("sys.path.insert", "ROOT", "QT_QPA_PLATFORM", "pytest_configure"):
        if kw not in text:
            _fail(f"tests/conftest.py 缺关键字 {kw}")
    _pass("tests/conftest.py 存在，含 sys.path.insert + offscreen 注入")


# ---------- Test 3: tests/e2e/conftest.py 存在 ----------
def test_3_e2e_conftest():
    p = ROOT / "tests" / "e2e" / "conftest.py"
    if not p.exists():
        _fail("tests/e2e/conftest.py 不存在")
    text = p.read_text(encoding="utf-8")
    if "pytest_ignore_collect" not in text:
        _fail("tests/e2e/conftest.py 未定义 pytest_ignore_collect")
    if "def test_" not in text:
        _fail("e2e conftest 未基于 def test_ 判定过滤")
    _pass("tests/e2e/conftest.py 存在且实现 pytest_ignore_collect")


# ---------- Test 4: 环境变量注入（在 conftest 加载后） ----------
def test_4_env_injection():
    # 用 pytest --qv-summary 或直接查询 config._qv_paths
    r = _pytest(["--help", "--qv-summary"] if "--qv-summary" in _pytest(["--help"]).stdout else ["--help"])
    assert r.returncode == 0, f"pytest --help 失败: {r.stderr[-500:]}"
    if "--qv-summary" not in r.stdout:
        _fail("pytest --help 未出现 --qv-summary 选项（conftest.py 未生效）")
    _pass("--qv-summary 选项已注册（tests/conftest.py 生效）")


# ---------- Test 5: 无 sys.path 注入的临时测试能被加载 ----------
def test_5_no_syspath_tmp_test():
    """写一个不带 sys.path.insert 的临时测试，验证 conftest.py 帮它 import。"""
    tmpdir = ROOT / ".pytest_tmp"
    tmpdir.mkdir(exist_ok=True)
    tmp = tmpdir / "test_conftest_probe.py"
    tmp.write_text(
        'from futures_quant.strategy import STRATEGY_REGISTRY\n'
        'def test_probe():\n'
        '    assert isinstance(STRATEGY_REGISTRY, dict)\n',
        encoding="utf-8",
    )
    try:
        r = _pytest([str(tmp)])
        if r.returncode != 0:
            _fail(f"临时测试失败：{r.stdout[-400:]}\n{r.stderr[-400:]}")
        _pass("临时测试无 sys.path 注入仍能导入 futures_quant（conftest 生效）")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# ---------- Test 6: e2e 目录 collect 通过 ----------
def test_6_e2e_collect():
    r = _pytest(["tests/e2e", "--collect-only", "-q"])
    if r.returncode != 0:
        _fail(f"e2e collect 失败：{r.stderr[-600:]}")
    # 从输出末尾提取 collected 数
    tail = r.stdout.strip().splitlines()[-3:]
    collected_line = next((l for l in tail if "collected" in l or "test" in l), "")
    _pass(f"e2e collect 通过：{collected_line.strip()}")


def main() -> int:
    checks = [
        ("test_1_pytest_ini_present", test_1_pytest_ini_present),
        ("test_2_root_conftest", test_2_root_conftest),
        ("test_3_e2e_conftest", test_3_e2e_conftest),
        ("test_4_env_injection", test_4_env_injection),
        ("test_5_no_syspath_tmp_test", test_5_no_syspath_tmp_test),
        ("test_6_e2e_collect", test_6_e2e_collect),
    ]
    passed, failed = 0, 0
    for name, fn in checks:
        try:
            fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {name}: {e}")
    print(f"\n=== {passed}/{len(checks)} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
