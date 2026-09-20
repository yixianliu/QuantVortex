"""M7.4 反馈再训练调度器（手动 + 可选定时，决策门 D7.1）。

职责：
- 把「实盘/回测交易结果写回 → 达到阈值 → 触发再训练」串成可重复执行的调度单元。
- 默认**手动触发**（``run_once``）；定时触发为可选能力（``start`` 起一个后台计时器，
  每 interval 检查一次），不强制、可 ``stop``。
- 离线安全：所有副作用都通过注入的回调（``write_fn`` / ``retrain_fn``）发生，
  本模块不直接读写行情、不联网、不落密钥；无 torch 时由 retrain_fn 内部降级。

防未来函数：调度只在「已结算」的反馈样本上触发再训练，不使用未来数据。
"""
from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__all__ = ["FeedbackScheduler", "SchedulerEvent"]


@dataclass
class SchedulerEvent:
    """一次调度结果记录。"""
    ts: str
    trigger: str            # "manual" / "interval"
    triggered: bool
    n_samples: int
    message: str


class FeedbackScheduler:
    """反馈再训练调度器。

    参数:
        store: 反馈样本库（需含 feedback_sample_count）。
        retrain_fn: 再训练回调 ``fn(symbol, store) -> dict``。
        min_samples: 触发阈值（默认 20）。
    """

    def __init__(self, store, retrain_fn: Callable[[str, Any], dict],
                 min_samples: int = 20) -> None:
        if retrain_fn is None:
            raise ValueError("retrain_fn 必填")
        self.store = store
        self.retrain_fn = retrain_fn
        self.min_samples = int(min_samples)
        self.history: List[SchedulerEvent] = []
        self._timer: Optional[threading.Timer] = None
        self._interval: float = 0.0
        self._running = False
        self._lock = threading.Lock()

    # ---------------- 核心调度 ----------------
    def _count(self, symbol: str) -> int:
        try:
            return int(self.store.feedback_sample_count(symbol))
        except Exception:
            return 0

    def run_once(self, symbol: str, trigger: str = "manual") -> SchedulerEvent:
        """执行一次反馈检查 + 按需再训练（线程安全，手动入口）。"""
        n = self._count(symbol)
        do = n >= self.min_samples
        if do:
            try:
                res = self.retrain_fn(symbol, self.store)
                msg = f"再训练完成：{res}"
            except Exception as e:  # 再训练失败不应中断调度
                res = None
                msg = f"再训练失败：{e}"
        else:
            res = None
            msg = f"反馈样本 {n} < {self.min_samples}，未触发"
        ev = SchedulerEvent(
            ts=dt.datetime.now().isoformat(timespec="seconds"),
            trigger=trigger, triggered=do, n_samples=n, message=msg,
        )
        with self._lock:
            self.history.append(ev)
            # 保留最近 100 条，防止无限增长
            self.history = self.history[-100:]
        return ev

    # ---------------- 可选定时 ----------------
    def start(self, symbols: List[str], interval_seconds: float = 3600.0) -> None:
        """启动可选定时检查（每 interval 秒对各 symbol 调 run_once）。

        默认不建议开启（决策门 D7.1：定时复杂度高）；开启后可 ``stop()``。
        不阻塞调用方（后台线程计时器）。
        """
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须 > 0")
        if self._running:
            return
        self._interval = float(interval_seconds)
        self._running = True
        self._reschedule(list(symbols))

    def _reschedule(self, symbols: List[str]) -> None:
        def _fire() -> None:
            if not self._running:
                return
            for s in symbols:
                self.run_once(s, trigger="interval")
            if self._running:  # 可能在中途被 stop
                self._timer = threading.Timer(self._interval, _fire)
                self._timer.daemon = True
                self._timer.start()

        self._timer = threading.Timer(self._interval, _fire)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        """停止定时检查（立即生效；已排队的单次 run_once 会跑完）。"""
        self._running = False
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None

    # ---------------- 查询 ----------------
    def last_event(self, symbol: str = "") -> Optional[SchedulerEvent]:
        for ev in reversed(self.history):
            return ev
        return None

    def summary(self) -> Dict[str, Any]:
        triggered = sum(1 for e in self.history if e.triggered)
        return {
            "total_events": len(self.history),
            "triggered": triggered,
            "running": self._running,
            "interval_seconds": self._interval,
        }
