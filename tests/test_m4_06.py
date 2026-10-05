# -*- coding: utf-8 -*-
"""M4-06 验收：异步框架统一（取消 / 进度 / 超时）。

验收脚本（对应文档 M4-06）：
    ① Worker.requestInterruption() / isInterruptionRequested() / check_interruption()；
    ② progress(int, str) 信号可送达主线程；
    ③ BasePage._run_worker 返回 worker 句柄；
    ④ closeEvent 对存活 worker 协作式中断并 wait(3000)，不产生
       ``RuntimeError: wrapped C/C++ object has been deleted``；
    ⑤ 可选 timeout_ms 超时触发 timeout(str) 信号；
    ⑥ async_worker.TaskRunner 死代码已删除（不再导出）；
    ⑦ Backtester.run(should_abort=...) 在检查点抛 InterruptionError；
    ⑧ 回测页「停止」按钮存在，且中断后按钮态能恢复。

运行（offscreen）：
    QT_QPA_PLATFORM=offscreen python test_m4_06.py
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR",
    "D:/PythonProject/QuantVortex/.pytest_tmp/sd-state",
)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    """记录一条断言结果。"""
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


def spin(app, msec: int) -> None:
    """推进事件循环 msec 毫秒（让跨线程信号得以投递）。"""
    from PyQt6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(msec, loop.quit)
    loop.exec()


# ============================================================================
# ① Worker 取消语义（纯线程，不依赖窗口）
# ============================================================================
def t1_worker_cancellation(app) -> None:
    """验证 Worker 的取消标志与协作式中止抛出。"""
    print("\n[①] Worker 取消语义")
    from futures_quant.ui.pages import Worker, InterruptionError

    w = Worker(lambda: None)
    check(w.isInterruptionRequested() is False, "初始未请求中断")
    w.requestInterruption()
    check(w.isInterruptionRequested() is True, "requestInterruption 后标志为 True")
    try:
        w.check_interruption()
        check(False, "check_interruption 应抛 InterruptionError")
    except InterruptionError:
        check(True, "check_interruption 抛出 InterruptionError")
    # 兼容命名（停止按钮等外部调用）
    check(w.is_interruption_requested() is True, "is_interruption_requested 兼容别名可用")

    # 中断路径：任务内循环检查 → 不发 finished，只发 interrupted
    got = {"finished": 0, "interrupted": 0, "error": 0}

    def long_task():
        for _ in range(2000):
            w2.check_interruption()
            time.sleep(0.001)
        return "done"

    w2 = Worker(long_task)
    w2.finished.connect(lambda r: got.__setitem__("finished", got["finished"] + 1))
    w2.interrupted.connect(lambda: got.__setitem__("interrupted", got["interrupted"] + 1))
    w2.error.connect(lambda e: got.__setitem__("error", got["error"] + 1))
    w2.start()
    spin(app, 100)
    w2.requestInterruption()
    w2.wait(5000)
    spin(app, 200)
    check(got["finished"] == 0, "中断后不发出 finished（避免半截结果被当成功）")
    check(got["interrupted"] == 1, "中断后发出 interrupted 信号（1 次）")
    check(got["error"] == 0, "中断不算错误，不发 error")


# ============================================================================
# ② progress(int, str) 信号
# ============================================================================
def t2_progress_signal(app) -> None:
    """验证进度信号能从工作线程送达主线程。"""
    print("\n[②] progress 信号")
    from futures_quant.ui.pages import Worker

    seen: list[tuple] = []

    def task():
        w.emit_progress(50, "一半")
        return "ok"

    w = Worker(task)
    w.progress.connect(lambda pct, txt: seen.append((pct, txt)))
    done = {"v": 0}
    w.finished.connect(lambda r: done.__setitem__("v", 1))
    w.start()
    w.wait(5000)
    spin(app, 200)
    check(done["v"] == 1, "任务正常完成并发 finished")
    check(seen == [(50, "一半")], f"收到进度 (50, '一半')，实际 {seen}")


# ============================================================================
# ③ _run_worker 返回句柄 + ⑤ 超时
# ============================================================================
def t3_run_worker_handle_and_timeout(app) -> None:
    """验证 _run_worker 返回 worker 句柄，以及 timeout_ms 超时信号。"""
    print("\n[③] _run_worker 句柄 / [⑤] 超时")
    from PyQt6.QtWidgets import QWidget
    from futures_quant.ui.pages import BasePage, Worker

    class _P(BasePage):
        """测试用最小页面。"""
        def __init__(self) -> None:
            super().__init__(None, None)

    page = _P()
    handle = page._run_worker(lambda: 1, lambda r: None)
    check(isinstance(handle, Worker), "_run_worker 返回 Worker 句柄")
    check(handle in page._workers, "worker 已登记到 page._workers")
    handle.wait(5000)

    # 超时：任务 3s，超时阈值 300ms
    timeout_msgs: list[str] = []

    def slow():
        time.sleep(3.0)
        return "never"

    page._run_worker(slow, lambda r: None, on_timeout=timeout_msgs.append,
                     timeout_ms=300)
    spin(app, 1200)
    check(len(timeout_msgs) >= 1, f"超时触发 timeout 信号，实际 {timeout_msgs}")
    # 超时 worker 结束后应被移出存活列表
    spin(app, 200)
    check(all(not w.isRunning() for w in page._workers), "超时后无存活 worker 残留")

    # 进度回调能经 _run_worker 透传
    prg: list[tuple] = []

    def with_progress():
        w = page._workers[-1]
        w.emit_progress(25, "step1")
        return 1

    page._run_worker(with_progress, lambda r: None, on_progress=lambda p, t: prg.append((p, t)))
    spin(app, 800)
    check(prg == [(25, "step1")], f"on_progress 回调收到进度，实际 {prg}")


# ============================================================================
# ④ closeEvent 协作式中断，无 C/C++ 对象悬挂
# ============================================================================
def t4_close_event(app) -> None:
    """验证页面关闭时请求中断并等待，不抛 RuntimeError。"""
    print("\n[④] closeEvent 中断")
    from futures_quant.ui.pages import BasePage

    class _P(BasePage):
        """测试用最小页面。"""
        def __init__(self) -> None:
            super().__init__(None, None)

    page = _P()

    def long_task():
        for _ in range(5000):
            page._workers[-1].check_interruption()
            time.sleep(0.001)
        return "x"

    page._run_worker(long_task, lambda r: None)
    spin(app, 100)
    check(len(page._workers) == 1 and page._workers[0].isRunning(), "关闭前确有存活 worker")

    err = None
    try:
        page.close()
        spin(app, 200)
    except RuntimeError as e:      # wrapped C/C++ object has been deleted
        err = str(e)
    check(err is None, f"closeEvent 未抛 RuntimeError（实际 {err}）")
    check(all(not w.isRunning() for w in page._workers), "关闭后 worker 均已退出")


# ============================================================================
# ⑥ async_worker 门面（TaskRunner 死代码已删）
# ============================================================================
def t6_async_worker_facade() -> None:
    """验证 async_worker 仅导出 Worker/InterruptionError，TaskRunner 已移除。"""
    print("\n[⑥] async_worker 门面")
    import futures_quant.ui.async_worker as aw

    check(not hasattr(aw, "TaskRunner"), "TaskRunner 死代码已删除")
    check(not hasattr(aw, "task_runner"), "task_runner 全局实例已删除")
    check(hasattr(aw, "Worker") and hasattr(aw, "InterruptionError"),
          "门面仍导出 Worker / InterruptionError（兼容旧 import 路径）")
    from futures_quant.ui.pages import Worker
    check(aw.Worker is Worker, "门面 Worker 与 pages.Worker 是同一类型")


# ============================================================================
# ⑦ Backtester should_abort 检查点
# ============================================================================
def t7_backtester_abort() -> None:
    """验证回测引擎在中断谓词为真时抛 InterruptionError。"""
    print("\n[⑦] Backtester 中断检查点")
    import pandas as pd
    from futures_quant.backtest.backtester import Backtester
    from futures_quant.core.exceptions import InterruptionError
    from futures_quant.config.settings import Config

    n = 600  # 超过 _ABORT_CHECK_EVERY，确保循环内至少一次检查
    idx = pd.date_range("2024-01-01", periods=n, freq="1min")
    df = pd.DataFrame({
        "datetime": idx, "open": 3500.0, "high": 3510.0, "low": 3490.0,
        "close": 3500.0, "volume": 100.0, "open_interest": 1000.0,
    })

    class _Feed:
        """最小行情源：直接返回构造好的 DataFrame。"""
        def get_history(self, symbol, start, end, period):
            return df

    bt = Backtester(Config(), _Feed())
    try:
        bt.run("rb2510", "2024-01-01", "2024-01-02", "1m", warmup=0,
               should_abort=lambda: True)
        check(False, "should_abort=True 时应抛 InterruptionError")
    except InterruptionError:
        check(True, "should_abort=True 时抛出 InterruptionError")
    except Exception as e:  # noqa: BLE001
        check(False, f"应抛 InterruptionError，实际 {type(e).__name__}: {e}")


# ============================================================================
# ⑧ 回测页「停止」按钮
# ============================================================================
def t8_backtest_page_stop(app) -> None:
    """验证回测页有停止按钮，中断后按钮态恢复（验收：2s 内恢复）。"""
    print("\n[⑧] 回测页停止按钮")
    from PyQt6.QtWidgets import QApplication, QPushButton
    from futures_quant.ui.main_window import MainWindow

    win = MainWindow()
    # 页面懒加载：默认只构建 NAV[0]，需逐个切换以强制实例化全部页面
    for i in range(len(getattr(win, "pages", []))):
        try:
            win._show_page(i)
        except Exception:  # noqa: BLE001
            pass
    try:
        idx = next(i for i, p in enumerate(win.pages)
                   if type(p).__name__ == "BacktestCenterPage")
    except StopIteration:
        names = [type(p).__name__ for p in win.pages]
        check(False, f"未找到 BacktestCenterPage（实际页面：{names}）")
        return
    page = win.pages[idx]

    check(hasattr(page, "_manual_stop_btn"), "回测中心存在手动回测停止按钮")
    check(isinstance(page._manual_stop_btn, QPushButton), "停止按钮是 QPushButton")
    check(page._manual_stop_btn.isEnabled() is False, "空闲时停止按钮默认禁用")

    # 模拟：手动回测进行中 → 点停止 → 按钮恢复（验收要求 2s 内）
    page._manual_run_btn.setEnabled(False)
    page._manual_stop_btn.setEnabled(True)
    page._manual_running = True

    def long_task():
        for _ in range(5000):
            page._workers[-1].check_interruption()
            time.sleep(0.001)
        return {}

    page._run_worker(long_task, page._on_manual_done,
                     on_interrupted=page._on_manual_interrupted)
    spin(app, 100)
    check(page._manual_stop_btn.isEnabled() is True, "任务进行中停止按钮可用")

    t0 = time.time()
    page._stop_manual()
    spin(app, 1500)
    elapsed = time.time() - t0
    check(page._manual_run_btn.isEnabled() is True, "停止后运行按钮恢复可用")
    check(page._manual_stop_btn.isEnabled() is False, "停止后停止按钮禁用")
    check(page._manual_running is False, "停止后 _manual_running 复位")
    check(elapsed < 2.0, f"停止到按钮恢复耗时 {elapsed:.2f}s < 2s")


def t9_predict_page_stop(app) -> None:
    """验证预测页「开始预测」与「历史回放」均有协作式停止入口。"""
    print("\n[⑨] 预测页停止按钮")
    from PyQt6.QtWidgets import QApplication, QPushButton
    from futures_quant.ui.main_window import MainWindow

    win = MainWindow()
    for i in range(len(getattr(win, "pages", []))):
        try:
            win._show_page(i)
        except Exception:  # noqa: BLE001
            pass
    try:
        page = next(p for p in win.pages if type(p).__name__ == "PredictOpsPage")
    except StopIteration:
        names = [type(p).__name__ for p in win.pages]
        check(False, f"未找到 PredictOpsPage（实际页面：{names}）")
        return

    for attr in ("stop_btn", "replay_stop_btn"):
        btn = getattr(page, attr, None)
        check(isinstance(btn, QPushButton), f"预测页存在 {attr}")
        check(btn is not None and btn.isEnabled() is False, f"空闲时 {attr} 默认禁用")

    # 主预测流程：进行中 → 停止 → 按钮恢复
    page.start_btn.setEnabled(False)
    page.start_btn.setText("预测中…")
    page.stop_btn.setEnabled(True)

    def long_task():
        for _ in range(5000):
            page._workers[-1].check_interruption()
            time.sleep(0.001)
        return {}

    page._run_worker(long_task, lambda r: None, on_interrupted=page._on_pred_interrupted)
    spin(app, 100)
    check(page.stop_btn.isEnabled() is True, "预测进行中 stop_btn 可用")

    t0 = time.time()
    page._stop_prediction()
    spin(app, 1500)
    elapsed = time.time() - t0
    check(page.start_btn.isEnabled() is True, "停止后 start_btn 恢复可用")
    check(page.start_btn.text() == "🚀 开始预测", "停止后 start_btn 文案恢复")
    check(page.stop_btn.isEnabled() is False, "停止后 stop_btn 禁用")
    check(elapsed < 2.0, f"停止到按钮恢复耗时 {elapsed:.2f}s < 2s")

    # 历史回放：同样路径
    page.replay_btn.setEnabled(False)
    page.replay_stop_btn.setEnabled(True)
    page._replaying = True
    page._run_worker(long_task, lambda r: None, on_interrupted=page._on_replay_interrupted)
    spin(app, 100)
    page._stop_replay()
    spin(app, 1500)
    check(page.replay_btn.isEnabled() is True, "停止后 replay_btn 恢复可用")
    check(page.replay_stop_btn.isEnabled() is False, "停止后 replay_stop_btn 禁用")
    check(page._replaying is False, "停止后 _replaying 复位")


def main() -> int:
    """执行全部验收项。"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    print("=" * 70)
    print("M4-06 · 异步框架统一（取消 / 进度 / 超时）验证")
    print("=" * 70)

    t6_async_worker_facade()
    t7_backtester_abort()
    t1_worker_cancellation(app)
    t2_progress_signal(app)
    t3_run_worker_handle_and_timeout(app)
    t4_close_event(app)
    t8_backtest_page_stop(app)
    t9_predict_page_stop(app)

    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
