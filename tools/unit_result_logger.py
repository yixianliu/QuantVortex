"""pytest 插件：把每个用例的结果**逐条**流式写入 JSONL。

为什么需要它（v5.2.6 实测）：
    某些 Qt 用例文件会在**退出期**被 CRT fast-fail 打断（0xC0000409），
    而 pytest 的 `N passed` 汇总行、`--junitxml` 都在最后统一写出 ——
    进程一崩，整套结果全丢，逐文件跑时该文件的用例数被记成 0，
    于是「25 个用例全过 + 进程 abort」在汇总里变成一个空洞的 0。

    这里在 `pytest_runtest_logreport` 里逐条落盘（另开一行 env 指定路径），
    崩溃发生在哪一条之后，都不会影响已经写出的结果。

启用方式：
    QV_UNIT_RESULT_LOG=<path> pytest ... -p unit_result_logger
"""
from __future__ import annotations

import json
import os

_LOGFILE = os.environ.get("QV_UNIT_RESULT_LOG", "")


def pytest_runtest_logreport(report) -> None:  # noqa: D103 - pytest 钩子
    if not _LOGFILE:
        return
    # setup/call/teardown 三个阶段都记；call 才是真正的用例结果
    try:
        with open(_LOGFILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "nodeid": report.nodeid,
                "when": report.when,
                "outcome": report.outcome,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
