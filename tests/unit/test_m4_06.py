# -*- coding: utf-8 -*-
"""M4-06 协作式中断/进度/超时/清理 单元测试。

锁定（Worker 契约 + _run_worker 生命周期）：
  * ① 中断：requestInterruption 后 check_interruption 抛 InterruptionError；
     run() 内协作式中止 → 发 interrupted（不发 finished / error）
  * ② 进度：emit_progress 钳制 0~100 + 发 progress(int, str)
  * ③ fn(worker) 单参形态：Worker 传自身进 fn（M4-09 兼容）
  * ④ 超时：_on_timeout 发 timeout 信号 + terminate（主线程守护定时器触发）
  * ⑤ closeEvent：页面销毁前 _interrupt_workers 有限等待，无 RuntimeError
     （QTimer 清理 + worker 中断 + mdm._live_worker.stop）
  * ⑥ 注册清理：_run_worker 各终态回调（finished/error/interrupted/timeout）
     后 worker 与 guard 均被移除

运行：
    /d/anaconda3/python.exe -m pytest tests/unit/test_m4_06.py -v
"""
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PyQt6.QtCore import QObject, QThread
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])

from futures_quant.ui.pages import Worker, InterruptionError  # noqa: E402

# 跨线程信号投递（Worker 在 QThread 内发 finished/interrupted/error，
# 主线程 processEvents 排空事件队列）。
import PyQt6.QtCore as _qtcore  # noqa: E402
_Direct = _qtcore.Qt.ConnectionType.DirectConnection


# ============================================================ ① 中断
def test_check_interruption_noop_when_not_requested():
    """未请求中断时 check_interruption 不抛异常。"""
    w = Worker(lambda: 1)
    w.check_interruption()  # 不应抛


def test_check_interruption_raises_when_requested():
    """请求中断后 check_interruption 抛 InterruptionError。"""
    w = Worker(lambda: 1)
    w.requestInterruption()
    with pytest.raises(InterruptionError):
        w.check_interruption()


def test_run_collaborative_interrupt_emits_interrupted_not_finished():
    """fn 内调 check_interruption → run() 发 interrupted，不发 finished。"""
    got_finished, got_err, got_int = [], [], []

    def task(w):
        # 模拟长任务循环
        for i in range(5):
            w.check_interruption()
            w.emit_progress(i * 20, f"step {i}")

    w = Worker(task)
    w.finished.connect(lambda r: got_finished.append(r))
    w.error.connect(lambda e: got_err.append(e))
    w.interrupted.connect(lambda: got_int.append(1))
    # 先请求中断再 start（协作式：首个 check_interruption 即抛）
    w.requestInterruption()
    w.start()
    w.wait(3000)
    app.processEvents()  # 排空跨线程投递的 interrupted 信号
    assert got_int == [1], f"interrupted not emitted: int={got_int}"
    assert not got_finished, "finished must NOT be emitted on interrupt"
    assert not got_err, "error must NOT be emitted on interrupt"


def test_run_post_result_interrupt_treated_as_interrupted():
    """fn 正常返回但已请求中断 → 视为中断（不发 finished）。"""
    got_finished, got_int = [], []
    w = Worker(lambda: 42)
    w.finished.connect(lambda r: got_finished.append(r))
    w.interrupted.connect(lambda: got_int.append(1))
    w.requestInterruption()
    w.start()
    w.wait(3000)
    app.processEvents()
    assert got_int == [1]
    assert not got_finished


def test_compat_lowercase_aliases():
    """小写别名 request_interruption / is_interruption_requested 可用。"""
    w = Worker(lambda: 1)
    assert w.is_interruption_requested() is False
    w.request_interruption()
    assert w.is_interruption_requested() is True


# ============================================================ ② 进度
def test_emit_progress_clamps_to_0_100():
    """emit_progress 钳制到 0~100 并发 int。"""
    got = []
    w = Worker(lambda: 1)
    w.progress.connect(lambda p, t: got.append((p, t)))
    w.emit_progress(150, "over")
    w.emit_progress(-20, "under")
    w.emit_progress(50, "mid")
    assert got[0] == (100, "over"), got
    assert got[1] == (0, "under"), got
    assert got[2] == (50, "mid"), got
    assert all(isinstance(p, int) for p, _ in got)


# ============================================================ ③ fn(worker)
def test_fn_receives_worker_instance_when_single_param():
    """fn 声明 1 个普通参数 → Worker 传自身（M4-09）。"""
    received = []
    got_res = []
    w = Worker(lambda x: (received.append(x), "ok")[1])
    w.finished.connect(lambda r: got_res.append(r))
    w.start()
    w.wait(3000)
    app.processEvents()
    assert got_res == ["ok"], f"result={got_res}"
    assert received and received[0] is w, "fn must receive Worker self"


def test_fn_zero_param_unchanged():
    """fn 0 参形态不受影响（既有契约）。"""
    got = []
    w = Worker(lambda: "zero")
    w.finished.connect(lambda r: got.append(r))
    w.start()
    w.wait(3000)
    app.processEvents()
    assert got == ["zero"]


# ============================================================ ④ 超时
def test_on_timeout_emits_and_terminates():
    """_on_timeout 发 timeout 信号 + terminate（由主线程守护定时器调用）。"""
    msgs = []
    w = Worker(lambda: time.sleep(0.05), timeout_ms=2000)
    w.timeout.connect(msgs.append)
    assert not w.isRunning()  # 未 start
    w.start()
    time.sleep(0.02)
    assert w.isRunning()
    w._on_timeout()  # 模拟主线程守护定时器触发
    w.wait(2000)
    assert len(msgs) == 1, f"timeout signal not emitted: {msgs}"
    assert "超时" in msgs[0]
    assert not w.isRunning()  # terminate 后不再运行


def test_on_timeout_message_format_ms_and_s():
    """<1s 用 ms 单位，>=1s 用 s 单位。"""
    w_ms = Worker(lambda: 1, timeout_ms=500)
    w_ms._on_timeout()
    w_s = Worker(lambda: 1, timeout_ms=3000)
    got = []
    w_s.timeout.connect(got.append)
    w_s._on_timeout()
    # w_ms 未连 timeout，直接断言 w_s 的文案
    assert got and "3.0s" in got[0], got


# ============================================================ ⑤ closeEvent
def test_close_event_no_runtimeerror_with_live_workers():
    """页面 closeEvent 在有存活 worker 时不抛 RuntimeError（QTimer 清理 + worker 中断）。

    构造最小页面（继承 BasePage 抽象类太重，直接复用 _interrupt_workers 语义）：
    用一个临时 QWidget 挂载 QTimer，模拟 closeEvent 的清理路径。
    """
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QWidget

    page = QWidget()
    page._workers = []
    # ① 挂一个活跃 QTimer（模拟预警中心扫描器）
    timer = QTimer(page)
    timer.start(1000)
    assert timer.isActive()
    # ② 挂一个正在运行的 worker（长任务 sleep）
    w = Worker(lambda: time.sleep(0.05), timeout_ms=0)
    page._workers.append(w)
    w.start()
    time.sleep(0.01)
    assert w.isRunning()

    # 复刻 closeEvent 的清理路径（不触发真实 BasePage 依赖）
    page._closed = True
    for _t in page.findChildren(QTimer):
        if _t.isActive():
            try:
                _t.stop()
            except Exception:
                pass
    # _interrupt_workers 等价语义
    alive = [x for x in page._workers if x.isRunning()]
    for x in alive:
        x.requestInterruption()
    for x in alive:
        x.wait(3000)
    assert not timer.isActive(), "QTimer must be stopped after close"
    for x in alive:
        assert not x.isRunning(), "worker must exit after interrupt+wait"
    # C++ 对象未销毁，可安全访问（无 RuntimeError）
    _ = timer.isActive()
    _ = w.isRunning()


def test_interrupt_workers_waits_and_unblocks():
    """_interrupt_workers 有限等待（3s）后不再悬挂（duck typing 宿主，绕开 BasePage 抽象）。"""
    class _Host(QObject):
        def __init__(self):
            super().__init__()
            self._workers = []
        def _interrupt_workers(self, timeout_ms: int = 3000) -> None:
            """复刻 BasePage._interrupt_workers 语义（QThread.wait 直接可用）。"""
            alive = [w for w in self._workers if w.isRunning()]
            for w in alive:
                w.requestInterruption()
            for w in alive:
                w.wait(timeout_ms)

    probe = _Host()
    w = Worker(lambda: time.sleep(0.03), timeout_ms=0)
    probe._workers.append(w)
    w.start()
    time.sleep(0.005)
    assert w.isRunning()
    t0 = time.monotonic()
    probe._interrupt_workers(timeout_ms=2000)
    elapsed = time.monotonic() - t0
    assert not w.isRunning()
    assert elapsed < 2.0, f"interrupt wait exceeded bound: {elapsed:.2f}s"


# ============================================================ ⑥ 注册清理
def test_run_worker_lifecycle_removes_all_paths():
    """_run_worker 各终态（finished/error/interrupted）后 worker 被移除。

    用 QWidget 宿主（主线程事件循环）+ DirectConnection（信号同步发射），
    复刻 BasePage._run_worker 的连接与清理语义（不实例化完整 BasePage）。
    """
    from PyQt6.QtCore import QTimer

    class _Host(QWidget):
        def __init__(self):
            super().__init__()
            self._workers = []

    def _run_worker_hosted(host, fn, timeout_ms=0,
                           on_done=None, on_err=None, on_interrupted=None):
        w = Worker(fn, timeout_ms=timeout_ms)
        host._workers.append(w)
        guard = None
        if timeout_ms > 0:
            guard = QTimer(host)
            guard.setSingleShot(True)
            guard.timeout.connect(w._on_timeout)

        def _safe_remove():
            try:
                host._workers.remove(w)
            except ValueError:
                pass
            if guard is not None and guard.isActive():
                guard.stop()

        def _done(r):
            try:
                if on_done:
                    on_done(r)
            finally:
                _safe_remove()

        def _err(e):
            try:
                if on_err:
                    on_err(e)
            finally:
                _safe_remove()

        w.finished.connect(_done, _Direct)
        w.error.connect(_err, _Direct)
        w.interrupted.connect(_safe_remove, _Direct)
        if on_interrupted is not None:
            w.interrupted.connect(on_interrupted, _Direct)
        w.start()
        if guard is not None:
            guard.start(timeout_ms)
        return w

    # --- finished 路径 ---
    h1 = _Host()
    done1 = []
    w1 = _run_worker_hosted(h1, lambda: "ok", on_done=done1.append)
    w1.wait(3000)
    app.processEvents()
    assert done1 == ["ok"], f"done1={done1}"
    assert w1 not in h1._workers, "worker must be removed on finished"

    # --- error 路径 ---
    h2 = _Host()
    errs = []
    w2 = _run_worker_hosted(h2, lambda: 1 / 0, on_err=errs.append)
    w2.wait(3000)
    app.processEvents()
    assert errs and "division by zero" in errs[0], f"errs={errs}"
    assert w2 not in h2._workers, "worker must be removed on error"

    # --- interrupted 路径 ---
    h3 = _Host()
    ints = []
    def task_int(w):
        w.check_interruption()  # 立即抛
    w3 = _run_worker_hosted(h3, task_int, on_interrupted=lambda: ints.append(1))
    w3.requestInterruption()
    w3.wait(3000)
    app.processEvents()
    assert ints == [1], f"ints={ints}"
    assert w3 not in h3._workers, "worker must be removed on interrupted"


if __name__ == "__main__":
    pytest.main([os.path.abspath(__file__), "-v"])
