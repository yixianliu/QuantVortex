"""M1-10 pytest 全局钩子：统一路径 / 环境变量。

职责：
    1) 把项目根注入 ``sys.path``，让 tests 下的测试文件不必再各自 ``sys.path.insert``；
    2) 将 Windows 临时目录指向项目内 ``.pytest_tmp``（沙箱 ``E:\\Temp`` 极慢）；
    3) 若 tests/e2e 目录存在，默认注入 ``QT_QPA_PLATFORM=offscreen``，
       保证无头环境下所有 PyQt6 UI 测试可跑。

设计取舍：
    - ``setdefault`` 而非强制覆盖：允许外部脚本 / 用户 shell 显式覆盖（例如本地开发时
      想让窗口显示就用 ``QT_QPA_PLATFORM=windowspytest`` 覆盖）；
    - ``pytest_configure`` 钩子只做轻量环境准备，不注册任何 fixture；
    - 不做任何项目语义判断（"当前跑的是 e2e 还是 unit"），因为
      pytest 无法在 collect 前区分。改为"e2e 目录存在就设 offscreen"——
      unit 测试一般不引 Qt，就算引了 offscreen 也无副作用。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------- 路径 ----------------------------
_TESTS_DIR = Path(__file__).resolve().parent
ROOT = _TESTS_DIR.parent  # 项目根

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ------------------------- 环境变量 ---------------------------
# Windows 沙箱环境 E:\Temp 极慢，改用项目内 .pytest_tmp
_pytest_tmp = ROOT / ".pytest_tmp"
try:
    _pytest_tmp.mkdir(parents=True, exist_ok=True)
except OSError:
    pass  # 只读文件系统时不影响测试，交给 pytest 默认 TMPDIR

for _var in ("TMP", "TEMP", "TMPDIR"):
    os.environ.setdefault(_var, str(_pytest_tmp))

# e2e 目录存在 → 默认 offscreen。用户可用 shell 环境变量覆盖。
if (_TESTS_DIR / "e2e").is_dir():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# --------------------------- 钩子 -----------------------------


def pytest_configure(config):
    """pytest 初始化钩子：记录关键路径便于排查。

    在 conftest 顶层已完成 sys.path / env 注入；这里仅打印一份配置快照到
    调试环境（``-s --debug-config`` 时可见）。正常 ``-q`` 模式下不产生输出。
    """
    config._qv_paths = {  # noqa: SLF001 - 内部诊断用
        "root": str(ROOT),
        "pytest_tmp": str(_pytest_tmp),
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", "<default>"),
    }


def pytest_addoption(parser):
    """注册 --qv-summary 选项：结束时打印路径诊断快照。"""
    group = parser.getgroup("quantvortex")
    group.addoption(
        "--qv-summary",
        action="store_true",
        default=False,
        help="结束时打印 QuantVortex 测试环境诊断快照",
    )


def pytest_sessionfinish(session, exitstatus):
    """打印诊断快照（可选，需 --qv-summary）。"""
    if session.config.getoption("--qv-summary"):
        paths = getattr(session.config, "_qv_paths", None)
        if paths:
            print("\n" + "=" * 60)
            print("QuantVortex pytest environment:")
            for k, v in paths.items():
                print(f"  {k:>12}: {v}")
            print("=" * 60)
        del session.config._qv_summary_printed  # type: ignore[attr-defined]
    return None
