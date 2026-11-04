"""pytest 插件：整套件挂起时把 Python 栈 dump 出来。

为什么需要它：本项目的 Qt 用例文件在**退出期**偶尔挂起（不是崩溃 —— 崩溃有
``0xC0000409`` 之类的退出码可查，挂起什么都没有，只能干等）。

为什么不用信号（``faulthandler.register``）：Windows 上 signal 投递不可靠
（只有控制台控制事件能触发），``os.kill(SIGABRT)`` 走的是 TerminateProcess，
进程直接死、栈也拿不到。而 ``dump_traceback_later`` 是**独立看门狗线程**，
到点自己醒、直接把栈写进文件 —— 在 Windows 上这才是能用的那一个。

用法：
    QV_HANG_TIMEOUT=180 QV_HANG_LOG=.../hang.txt pytest tests/unit \\
        -p hang_watchdog
    cat <QV_HANG_LOG>          # 挂住时在这里看栈
"""
from __future__ import annotations

import faulthandler
import os


def pytest_configure(config) -> None:
    """装看门狗：``QV_HANG_TIMEOUT`` 秒后强制 dump 全线程栈并退出。"""
    secs = float(os.environ.get("QV_HANG_TIMEOUT", "240"))
    path = os.environ.get("QV_HANG_LOG", ".pytest_tmp/hang_traceback.txt")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # 注意：3.13 的 dump_traceback_later 不接受 all_threads 关键字
    # （连 inspect.signature 都读不出它的签名）。看门狗线程 dump 到的就是
    # 主线程栈，而挂起本来也发生在主线程，够用。
    with open(path, "w", encoding="utf-8") as fh:
        faulthandler.dump_traceback_later(secs, exit=True, file=fh)
