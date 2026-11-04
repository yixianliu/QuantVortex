"""M7.4 反馈再训练调度器（手动 + 可选定时，决策门 D7.1）+ M3-13 模型漂移定时检测。

职责：
- 把「实盘/回测交易结果写回 → 达到阈值 → 触发再训练」串成可重复执行的调度单元。
- 默认**手动触发**（``run_once``）；定时触发为可选能力（``start`` 起一个后台计时器，
  每 interval 检查一次），不强制、可 ``stop``。
- M3-13 ④：`DriftMonitor` 定时（默认 **1 小时**）对「已预测品种」跑漂移检测，
  超阈值 → 写 `alerts` 表 + 通过 `notify_fn` 冒泡托盘。
- 离线安全：所有副作用都通过注入的回调（``write_fn`` / ``retrain_fn`` / ``notify_fn``）
  发生，本模块不直接读写行情、不联网、不落密钥；无 torch 时由 retrain_fn 内部降级。

防未来函数：调度只在「已结算」的反馈样本上触发再训练 / 漂移判定，不使用未来数据。
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["FeedbackScheduler", "SchedulerEvent", "DriftMonitor", "DriftEvent"]


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
        # M1-01：store 现统一提供 feedback_sample_count（AnalysisStore）。
        # 缺失时在日志中暴露（不再静默吞成 0 而让再训练永不触发），但保持降级返回 0。
        fn = getattr(self.store, "feedback_sample_count", None)
        if fn is None:
            logger.warning(
                "store 缺少 feedback_sample_count 方法，定时再训练将永不触发")
            return 0
        try:
            return int(fn(symbol))
        except Exception as e:
            logger.warning("feedback_sample_count 调用失败：%s", e)
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


# ---------------------------------------------------------------------------
# M3-13 ④：模型漂移定时检测
# ---------------------------------------------------------------------------
@dataclass
class DriftEvent:
    """一次漂移检测的结果记录。"""
    ts: str
    symbol: str
    level: str            # "ok" / "drift" / "no_data"
    drift_score: float
    window_mean: float
    baseline_mean: float
    message: str
    alerted: bool         # 是否已写入 alerts 表


class DriftMonitor:
    """定时对「已预测品种」跑模型漂移检测，超阈值写 `alerts` 表并冒泡托盘。

    M3-13 ④。与 `FeedbackScheduler` 一样**默认手动**（`check_once` / `check_all`），
    定时为可选（`start`，默认间隔取 `DriftConfig.scheduler_interval_min` = 60 分钟）。

    参数:
        store: `AnalysisStore`，需 `predicted_symbols` / `daily_hit_rates` / `save_alert`。
        notify_fn: 托盘冒泡回调 ``fn(message: str, level: str)``；None 则只记日志。
        schedule_fn: 定时底层（便于单测注入假时钟）；默认 ``threading.Timer``。

    幂等与去噪：同一个品种在同一 ``level`` 下**只告警一次**，直到状态发生变化
    （ok→drift 或 drift→ok），避免每小时重复冒泡刷屏。
    """

    def __init__(self, store, notify_fn: Optional[Callable[[str, str], None]] = None,
                 schedule_fn: Optional[Callable[[float, Callable], Any]] = None,
                 threshold: float | None = None,
                 max_symbols: int | None = None) -> None:
        self.store = store
        self.notify_fn = notify_fn
        self.threshold = threshold      # None → 取 DriftConfig.threshold（运行期可改）
        self.max_symbols = max_symbols  # None → 取 DriftConfig.scheduler_max_symbols
        self._schedule_fn = schedule_fn
        self.history: List[DriftEvent] = []
        self._last_level: Dict[str, str] = {}
        self._timer: Any = None
        self._interval: float = 0.0
        self._running = False
        self._lock = threading.Lock()

    # ---------------- 检测 ----------------
    def check_once(self, symbol: str, write_alert: bool = True) -> DriftEvent:
        """检测单个品种（不抛异常：任何失败都降级为 no_data 事件）。"""
        from ..ai.drift import detect_from_store
        try:
            res = detect_from_store(self.store, symbol, threshold=self.threshold)
        except Exception as e:  # 单品种失败不应中断整轮扫描
            logger.warning("漂移检测失败（%s）：%s", symbol, e)
            res = {"drift_score": 0.0, "window_mean": 0.0, "baseline_mean": 0.0,
                   "level": "no_data", "status": "no_data",
                   "message": f"{symbol} 漂移检测异常：{e}"}

        level = str(res.get("level") or "no_data")
        prev = self._last_level.get(symbol)
        # 去噪：状态未变化 → 不再重复告警（但仍记录事件，便于审计）
        should_alert = bool(write_alert) and level == "drift" and prev != "drift"
        if write_alert and level == "drift" and should_alert:
            self._write_alert(symbol, res)
            self._notify(res)
        self._last_level[symbol] = level

        ev = DriftEvent(
            ts=dt.datetime.now().isoformat(timespec="seconds"),
            symbol=symbol, level=level,
            drift_score=float(res.get("drift_score") or 0.0),
            window_mean=float(res.get("window_mean") or 0.0),
            baseline_mean=float(res.get("baseline_mean") or 0.0),
            message=str(res.get("message") or ""),
            alerted=should_alert,
        )
        with self._lock:
            self.history.append(ev)
            self.history = self.history[-200:]
        return ev

    def _write_alert(self, symbol: str, res: dict) -> None:
        """把漂移告警写入 `alerts` 表（rule 固定为 ``model_drift``）。"""
        fn = getattr(self.store, "save_alert", None)
        if fn is None:
            logger.warning("store 缺少 save_alert，漂移告警无法落库")
            return
        try:
            fn(dt.datetime.now().isoformat(timespec="seconds"), symbol,
               "model_drift", "drift", str(res.get("message") or ""), 1)
        except Exception as e:  # noqa: BLE001
            logger.warning("写入漂移告警失败（%s）：%s", symbol, e)

    def _notify(self, res: dict) -> None:
        if self.notify_fn is None:
            logger.info("模型漂移告警（无托盘回调）：%s", res.get("message"))
            return
        try:
            self.notify_fn(str(res.get("message") or ""), "drift")
        except Exception as e:  # noqa: BLE001
            logger.warning("托盘冒泡失败：%s", e)

    def check_all(self, write_alert: bool = True) -> List[DriftEvent]:
        """扫描全部已预测品种（受 ``max_symbols`` 限制），返回事件列表。"""
        fn = getattr(self.store, "predicted_symbols", None)
        if fn is None:
            logger.warning("store 缺少 predicted_symbols，无法扫描漂移")
            return []
        try:
            limit = self.max_symbols
            if limit is None:
                from ..ai.constants import DRIFT
                limit = DRIFT.scheduler_max_symbols
            symbols = list(fn(int(limit)) or [])
        except Exception as e:  # noqa: BLE001
            logger.warning("获取已预测品种失败：%s", e)
            return []
        return [self.check_once(s, write_alert=write_alert) for s in symbols]

    # ---------------- 可选定时 ----------------
    def start(self, interval_minutes: float | None = None) -> None:
        """启动定时漂移检测（默认 60 分钟一轮）。不阻塞调用方。"""
        if interval_minutes is None:
            from ..ai.constants import DRIFT
            interval_minutes = DRIFT.scheduler_interval_min
        seconds = float(interval_minutes) * 60.0
        if seconds <= 0:
            raise ValueError("interval_minutes 必须 > 0")
        if self._running:
            return
        self._interval = seconds
        self._running = True
        self._reschedule()

    def _reschedule(self) -> None:
        def _fire() -> None:
            if not self._running:
                return
            try:
                self.check_all()
            except Exception as e:  # 本轮失败也要继续排下一轮
                logger.warning("定时漂移检测失败：%s", e)
            if self._running:
                self._spawn()

        self._spawn(_fire)

    def _spawn(self, _fire=None) -> None:
        fn = self._schedule_fn
        if fn is not None:
            self._timer = fn(self._interval, _fire)
            return
        t = threading.Timer(self._interval, _fire)
        t.daemon = True
        t.start()
        self._timer = t

    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:  # noqa: BLE001
                pass
            self._timer = None

    # ---------------- 查询 ----------------
    def latest(self, symbol: str) -> Optional[DriftEvent]:
        for ev in reversed(self.history):
            if ev.symbol == symbol:
                return ev
        return None

    def summary(self) -> Dict[str, Any]:
        n_drift = sum(1 for e in self.history if e.level == "drift")
        return {
            "total_events": len(self.history),
            "drifted": n_drift,
            "alerted": sum(1 for e in self.history if e.alerted),
            "running": self._running,
            "interval_minutes": (self._interval / 60.0) if self._interval else 0.0,
            "symbols_tracked": len(self._last_level),
        }
