"""市场数据管理器（分析系统的数据中枢）。

职责：
    - 统一对外提供「某合约某周期最近 N 根 K 线」；
    - 计算盘口快照（最新价 / 涨跌 / 幅度 / 成交量 / 持仓量 / 资金流代理）；
    - 全市场全景聚合（涨跌幅 / 强弱 / 量能变化 / 持仓异动 / 资金流）；
    - 模拟实时流（QTimer 按节奏吐出下一根 K 线，制造「实时」观感）。

数据源通过 DataFeed 接口注入：默认 SyntheticFeed（合成行情），
生产环境替换为 CTPFeed（见 data/ctp_gateway.py）即可，上层零改动。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .synthetic import SyntheticFeed, FUTURES_UNIVERSE, resample_bars, find_universe_row
from .base import (attach_provenance, evaluate_staleness, get_feed_factory,
                   get_provenance, provenance_label)
from ..runtime import get_data_dir

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# 真实行情源（非合成）。用于判定是否允许随机游走模拟 tick。
REAL_SOURCES = ("sina", "akshare", "csv", "ctp", "tqsdk")


# 实时数据节流配置（M4-10 spec ④：真实源 get_recent 节流至 2s，避免主线程高频阻塞）
LIVE_RECENT_INTERVAL_MS = 2000       # 真实源 get_recent 调用间隔（2s，原为 1s）
LIVE_RECENT_TTL_SEC = 2.0            # get_recent 结果有效窗口（2s）


class LiveDataWorker(QThread):
    """实时数据刷新工作线程（M4-10 spec ④）。

    真实源模式：在子线程中按节流间隔（2s）调用 ``feed.get_recent`` 刷新最新真实棒，
    避免在主线程高频阻塞。合成源模式：保持 QTimer 周期随机游走，不受此线程影响。

    线程安全：仅线程内调用 feed 方法，不触碰信号（信号由主线程 QTimer 下发）。
    """

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, feed, symbol: str, period: str, interval_ms: int = 1000) -> None:
        """初始化相关对象。

        参数:
            feed: 数据源对象（feed.get_recent）
            symbol: 当前实时品种代码
            period: 实时周期
            interval_ms: 基础节奏（合成源用，毫秒）
        """
        super().__init__()
        self._feed = feed
        self._symbol = symbol
        self._period = period
        self._interval_ms = int(interval_ms or 0)
        self._live: dict = {}          # 按周期缓存最近 get_recent 结果，防重复调用
        self._stop_event = threading.Event()
        self._active = True

    # ---- 停止 ----
    def stop(self) -> None:
        """停止工作线程（退出标志 + 标记完成 + 等待线程收尾）。

        M4-10④：LiveDataWorker 实为 QThread；``stop_live`` 在 stop() 后立即把
        句柄置 None，若不 wait 收尾存在 QThread 被 GC 时仍在运行的隐患，
        故此处阻塞等待线程结束（上限 500ms，正常 <1ms 即退）。"""
        self._active = False
        self._stop_event.set()
        if self.isRunning():
            self.wait(500)

    @property
    def is_active(self) -> bool:
        """是否仍在运行。"""
        return self._active

    # ---- 主循环（子线程内）----
    def run(self) -> None:
        """运行实时数据刷新循环。

        每 LIVE_RECENT_INTERVAL_MS（2s）执行一次真实源 get_recent 刷新，
        通过缓存避免对同一周期重复调用；结果仅更新本地 df，不触发信号。
        """
        while self._active:
            self._stop_event.wait(LIVE_RECENT_INTERVAL_MS / 1000.0)
            if not self._active:
                break
            self._refresh_once()

    def _refresh_once(self) -> None:
        """执行一次真实源 get_recent 刷新（节流间隔内只调一次）。"""
        try:
            cache_key = (self._symbol, self._period)
            cached = self._live.get(cache_key)
            fresh_ts = time.time() - LIVE_RECENT_TTL_SEC
            if cached is not None and fresh_ts < 0:
                return  # 仍在有效窗口内，跳过
            # 超出窗口或首次调用：拉取最新真实棒
            fresh = self._feed.get_recent(self._symbol, self._period, limit=3)
            if fresh is None or fresh.empty:
                self._live[cache_key] = None
                return
            self._live[cache_key] = fresh
        except Exception:  # noqa: BLE001
            logger.warning("实时数据刷新失败 symbol=%s period=%s",
                           self._symbol, self._period)


def _load_config() -> dict:
    """读取项目根 config/settings.json（不存在则给默认值）。"""
    try:
        with open(os.path.join(_ROOT, "config", "settings.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 周期 -> 聚合参考窗（用于取数窗口长度，不再用于“当日涨跌幅”基准）
PERIOD_SESSION_BARS = {
    "1m": 240, "5m": 48, "15m": 16, "30m": 8, "1h": 4, "4h": 2, "D": 1, "W": 5, "M": 22,
}


def trading_day_key(dt) -> object:
    """把时间戳映射到所属交易日（夜盘 18:00 之后归属下一交易日）。

    夜盘 21:00（日历日 D）属于交易日 D+1；凌晨 00:00-02:30 仍属 D+1。
    仅用于聚合当日口径，不参与撮合。
    """
    d = pd.Timestamp(dt)
    if d.hour >= 18:
        return (d + pd.Timedelta(days=1)).date()
    return d.date()


def daily_snapshot(df: pd.DataFrame, mult: float = 1.0) -> dict:
    """按「交易日」口径计算当日涨跌幅 / 当日 OI 变化 / 当日资金流。

    第二轮修正（P0-2）：不再用窗口首根或半窗口累计，统一为
        - 当日涨跌幅 = 当日最后价 / 上一交易日收盘 - 1
        - 当日 OI 变化 = 当日最后 OI - 上一交易日最后 OI
        - 当日资金流 = Σ(当日每根 (close-open) × volume × 乘数) / 1e8（亿元）
    夜盘/休市通过交易日键分组，跨日不会产生假涨跌；缺少上一交易日时
    对应字段返回 0 / None，并标记 has_prev_day=False。

    参数:
        df: 含 datetime/open/close/volume/open_interest 的行情（按时间升序）
        mult: 合约乘数（资金流用）
    返回:
        dict（字段名保持向后兼容）
    """
    out = {
        "last": 0.0, "prev_close": None, "chg": 0.0, "chg_pct": 0.0,
        "oi_now": 0.0, "oi_prev": None, "oi_chg": 0.0, "oi_chg_pct": 0.0,
        "volume_day": 0.0, "fund_flow": 0.0, "has_prev_day": False,
        "trading_day": None, "prev_trading_day": None,
    }
    if df is None or len(df) == 0 or "datetime" not in df:
        return out
    keys = df["datetime"].map(trading_day_key)
    last_key = keys.iloc[-1]
    last_day = df[keys == last_key]
    prev_keys = [k for k in keys.unique().tolist() if k != last_key]
    prev_key = prev_keys[-1] if prev_keys else None
    prev_day = df[keys == prev_key] if prev_key is not None else None

    last = float(last_day["close"].iloc[-1])
    out["last"] = last
    out["trading_day"] = last_key
    out["prev_trading_day"] = prev_key
    out["volume_day"] = float(last_day["volume"].sum()) if "volume" in last_day else 0.0
    if "open_interest" in last_day and len(last_day):
        out["oi_now"] = float(last_day["open_interest"].iloc[-1])
    fund_cols = {"open", "close", "volume"}
    if fund_cols.issubset(set(df.columns)):
        out["fund_flow"] = float(
            ((last_day["close"] - last_day["open"]) * last_day["volume"] * mult).sum() / 1e8)

    if prev_day is not None and len(prev_day):
        prev_close = float(prev_day["close"].iloc[-1])
        out["prev_close"] = prev_close
        out["has_prev_day"] = True
        if prev_close:
            out["chg"] = last - prev_close
            out["chg_pct"] = (last / prev_close - 1.0) * 100.0
        if "open_interest" in prev_day and len(prev_day):
            oi_prev = float(prev_day["open_interest"].iloc[-1])
            out["oi_prev"] = oi_prev
            out["oi_chg"] = out["oi_now"] - oi_prev
            if oi_prev:
                out["oi_chg_pct"] = (out["oi_now"] / oi_prev - 1.0) * 100.0
    return out


def default_symbol() -> str:
    """配置里的默认探测品种（模块级，供 _build_feed 与管理器共用）。"""
    cfg = _load_config()
    return cfg.get("analysis", {}).get("default_symbol", "rb.SHFE")


# 最近一次构建数据源时的降级原因，供 UI / 日志展示（避免静默降级无从排查）
LAST_FEED_ERROR: str = ""


def _probe(feed, label: str) -> bool:
    """轻量探测：拉取默认品种最近 3 根日线，判定该源是否真的可用。"""
    global LAST_FEED_ERROR
    try:
        probe = feed.get_recent(default_symbol(), "D", 3)
    except Exception as exc:                       # noqa: BLE001 - 需记录具体原因
        LAST_FEED_ERROR = f"{label} 探测异常: {type(exc).__name__}: {exc}"
        logger.warning("数据源 %s 探测失败，将降级为合成行情：%s", label, exc)
        return False
    if probe is None or getattr(probe, "empty", True):
        LAST_FEED_ERROR = f"{label} 探测返回空数据"
        logger.warning("数据源 %s 探测返回空数据，将降级为合成行情", label)
        return False
    return True


def _build_feed(source: str, data_path: str):
    """按 source 构建数据源；探测失败自动回退 synthetic。返回 (feed, effective_source)。

    降级不再静默：失败原因写入模块级 LAST_FEED_ERROR 并打日志。
    """
    global LAST_FEED_ERROR
    LAST_FEED_ERROR = ""
    synth = SyntheticFeed()

    if source == "sina":
        try:
            from .sina_feed import SinaFeed
            f = SinaFeed(cache_dir=os.path.join(data_path, "sina_cache"))
            if _probe(f, "sina"):
                return f, "sina"
        except Exception as exc:                   # noqa: BLE001
            LAST_FEED_ERROR = f"sina 初始化失败: {type(exc).__name__}: {exc}"
            logger.warning("sina 数据源初始化失败：%s", exc)
        return synth, "synthetic"

    if source == "ctp":
        try:
            from .ctp_gateway import CTPFeed
            return CTPFeed(), "ctp"
        except Exception as exc:                   # noqa: BLE001
            LAST_FEED_ERROR = f"ctp 初始化失败: {type(exc).__name__}: {exc}"
            logger.warning("CTP 数据源初始化失败：%s", exc)
            return synth, "synthetic"

    if source == "akshare":
        try:
            from .akshare_feed import AkshareFeed
            f = AkshareFeed()
            if _probe(f, "akshare"):
                return f, "akshare"
        except Exception as exc:                   # noqa: BLE001
            LAST_FEED_ERROR = f"akshare 初始化失败: {type(exc).__name__}: {exc}"
            logger.warning("akshare 数据源初始化失败：%s", exc)
        return synth, "synthetic"

    if source == "csv":
        try:
            from .csv_feed import CsvFeed
            f = CsvFeed()
            if _probe(f, "csv"):
                return f, "csv"
        except Exception as exc:                   # noqa: BLE001
            LAST_FEED_ERROR = f"csv 初始化失败: {type(exc).__name__}: {exc}"
            logger.warning("csv 数据源初始化失败：%s", exc)
        return synth, "synthetic"

    if source == "tqsdk":
        # TqSdk 适配器自身不产出合成行情：这里只构建（懒连接），
        # 真正的可用性在 connect() 中探测并以状态文本显式呈现，绝不静默降级。
        try:
            from .tqsdk_feed import TqSdkFeed
            tq_cfg = (_load_config().get("data", {}) or {}).get("tqsdk", {}) or {}
            return TqSdkFeed(
                user_env=tq_cfg.get("user_env", "TQ_USER"),
                password_env=tq_cfg.get("password_env", "TQ_PASSWORD"),
                creds_path=tq_cfg.get("creds_path") or None,
            ), "tqsdk"
        except Exception as exc:                   # noqa: BLE001
            LAST_FEED_ERROR = f"tqsdk 初始化失败: {type(exc).__name__}: {exc}"
            logger.warning("TqSdk 数据源初始化失败：%s", exc)
            return synth, "synthetic"

    # 阶段 0：可插拔数据源（为未来 TqSdk / 真实 CTP 前置预留，本阶段不内置实现）
    factory = get_feed_factory(source)
    if factory is not None:
        try:
            f = factory()
            if _probe(f, source):
                return f, source
            LAST_FEED_ERROR = f"{source} 探测失败"
            return synth, "synthetic"
        except Exception as exc:                   # noqa: BLE001
            LAST_FEED_ERROR = f"{source} 初始化失败: {type(exc).__name__}: {exc}"
            logger.warning("%s 数据源初始化失败：%s", source, exc)
            return synth, "synthetic"

    return synth, "synthetic"


class MarketDataManager(QObject):
    """行情中枢：缓存 + 快照 + 全景 + 模拟实时。"""

    bar_arrived = pyqtSignal(object)      # 实时新增的一根 Bar(dict)
    quote_updated = pyqtSignal(str)       # symbol
    status_changed = pyqtSignal(str)      # 连接状态文本

    def __init__(self, feed=None, source: str | None = None) -> None:
        """初始化相关对象。
        
            参数:
                feed
                source: str | None"""
        super().__init__()
        cfg = _load_config()
        data_path = cfg.get("data_path", "data")
        # 归一化到可写数据目录：相对路径/None -> get_data_dir()，绝对路径原样
        if not data_path or not os.path.isabs(data_path):
            data_path = get_data_dir()
        if source is None:
            source = cfg.get("data", {}).get("source", "synthetic")
        self.requested_source = source
        if feed is not None:
            self.feed = feed
            self.source = "custom"
            self.allow_sim = True
        else:
            self.feed, self.source = _build_feed(source, data_path)
        # 真实源一律禁止随机游走伪造；只有合成/自定义源才允许模拟 tick
        if feed is None:
            self.allow_sim = (self.source not in REAL_SOURCES)
        self.feed_error = LAST_FEED_ERROR          # 降级原因（供 UI 展示，空串表示无降级）
        self.is_real = False                        # 是否存在「真正连上的实盘源」
        self.universe = FUTURES_UNIVERSE
        self._full: dict[str, pd.DataFrame] = {}     # (symbol, period) -> 完整序列
        self._live: dict[str, dict] = {}             # symbol -> 实时游标状态
        self._live_worker: Optional[LiveDataWorker] = None  # 真实源实时刷新工作线程（M4-10 spec ④）
        self._synth = SyntheticFeed()                # 日内/失败回退用
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._interval_ms = 1000
        self.status = "离线"
        self._live_symbol: Optional[str] = None     # 当前实时品种（用于 worker 回调）
        # 最近一次 get_bars 的来源元数据，供 UI 常驻水印读取
        self.last_provenance: dict = {}

    # ------------------------------------------------------------------
    def _default_symbol(self) -> str:
        """处理default合约代码。
        
            返回:
                str"""
        return default_symbol()

    def _period_real(self, period: str) -> bool:
        """该周期是否有真实数据。

        - 非真实源（合成 / 真实源探测失败回退）：一律按合成处理；
        - sina / akshare / csv 为日线级免费源，仅 D/W 真实（无分钟线）；
        - ctp 连上时全部周期真实。
        """
        if not self.is_real:
            return False
        if self.source in ("sina", "akshare", "csv"):
            return period in ("D", "1D", "W", "1W")
        return True

    # 日线级真实源的展示名（探测成功后用于状态栏）
    _DAILY_SOURCE_LABEL = {
        "sina": "新浪实盘日线", "akshare": "akshare日线(真实)", "csv": "本地CSV回放(真实)",
    }

    def connect(self) -> None:
        """建立数据源连接（按 source）。日线级真实源探测失败时回退合成并标注原因；
        ctp 未连上时明确报告「未连接」并允许合成回退（绝不冒充实盘）。"""
        self.is_real = False
        if self.source in self._DAILY_SOURCE_LABEL:
            label = self._DAILY_SOURCE_LABEL[self.source]
            try:
                probe = self.feed.get_recent(self._default_symbol(), "D", 3)
            except Exception as exc:               # noqa: BLE001
                logger.warning("%s 连接探测异常：%s", self.source, exc)
                probe = None
            if probe is None or getattr(probe, "empty", True):
                failed = self.source
                self.feed_error = (self.feed_error or
                                   f"{failed} 探测返回空数据")
                self.feed = self._synth
                self.source = "synthetic"
                self.allow_sim = True
                # 明确标注「演示数据」，禁止在界面伪装成实盘
                self.status = f"已连接 · 合成行情(模拟, {failed}获取失败)"
            else:
                self.is_real = True
                self.allow_sim = False
                self.status = f"已连接 · {label}"
        elif self.source == "ctp":
            self._wire_ctp_feed()
            ok = self.feed.connect()
            self.is_real = ok
            # 阶段 0：CTP 当前历史 K 线仍由合成回退提供，状态文本必须如实标注，
            # 不能只显示「实盘已连接」而让用户以为历史行情也是真实的。
            label = self.feed.source_label
            if ok and not getattr(self.feed, "history_real", False):
                label = f"{label} · 历史K线为合成"
                self.feed_error = "CTP 历史K线回退合成"
            self.status = label
            if ok:
                self.allow_sim = False          # 实盘源：到达末尾不伪造，尝试刷新真实棒
                self._start_reconnect_watch()
            else:
                self.allow_sim = True           # CTP 未连上：允许合成回退并清晰标注
        elif self.source == "tqsdk":
            # 阶段 5：TqSdk 探测失败时保留具名错误，**不回退合成**（不伪造任何 tick）。
            label = self.feed.source_label
            try:
                probe = self.feed.get_recent(self._default_symbol(), "D", 3)
                ok = probe is not None and not probe.empty
                err = "" if ok else "探测返回空数据"
            except Exception as exc:               # noqa: BLE001 - 需按错误类型展示
                ok = False
                err = getattr(exc, "user_message", "") or f"{type(exc).__name__}: {exc}"
            self.is_real = ok
            self.allow_sim = False
            self.feed_error = "" if ok else err
            self.status = f"已连接 · {label}" if ok else f"TqSdk 不可用 · {err}"
        else:
            self.status = "已连接 · 合成行情(模拟)"
        self.status_changed.emit(self.status)

    # ------------------------------------------------------------------
    # CTP 实时流 / 自动重连
    # ------------------------------------------------------------------
    def _wire_ctp_feed(self) -> None:
        """把 CTP 行情回调接到本中枢：状态回传 + on_bar 实时棒广播。"""
        feed = self.feed
        feed.on_status = lambda txt: (
            setattr(self, "status", txt), self.status_changed.emit(txt))
        feed.on_bar = self._on_ctp_bar

    def _on_ctp_bar(self, bar: dict) -> None:
        """CTP 行情回报 → 累加到实时游标并广播（供监控页刷新盘口）。"""
        sym = bar.get("symbol")
        if not sym:
            return
        st = self._live.get(sym)
        if st is not None:
            df = st["df"]
            nb = pd.DataFrame([bar])
            df = pd.concat([df, nb], ignore_index=True)
            st["df"] = df
            st["cursor"] = len(df) - 1
        self.bar_arrived.emit(bar)
        self.quote_updated.emit(sym)

    def _start_reconnect_watch(self) -> None:
        """启动reconnectwatch。"""
        if not hasattr(self, "_reconnect_timer"):
            self._reconnect_timer = QTimer()
            self._reconnect_timer.timeout.connect(self._reconnect_tick)
        self._reconnect_timer.start(30000)   # 每 30s 检查 CTP 断线并重连

    def _reconnect_tick(self) -> None:
        """处理reconnectTick 数据。"""
        if self.source != "ctp" or not hasattr(self, "_reconnect_timer"):
            if hasattr(self, "_reconnect_timer"):
                self._reconnect_timer.stop()
            return
        if not self.feed.connected:
            self.feed.maybe_reconnect()
            self.is_real = self.feed.connected

    def disconnect(self) -> None:
        """断开连接相关对象。"""
        self._timer.stop()
        if hasattr(self, "_reconnect_timer"):
            self._reconnect_timer.stop()
        if self.source == "ctp" and getattr(self.feed, "connected", False):
            try:
                self.feed.disconnect()
            except Exception:
                pass
        if self.source == "tqsdk":
            # 释放 TqApi 长连接，避免进程残留连接线程
            try:
                self.feed.close()
            except Exception:
                pass
        self.is_real = False
        self.status = "离线"
        self.status_changed.emit(self.status)

    @property
    def source_label(self) -> str:
        """处理source标签。
        
            返回:
                str"""
        return getattr(self.feed, "source_label", "合成行情(模拟)")

    # ------------------------------------------------------------------
    def _ensure_full(self, symbol: str, period: str = "1m") -> pd.DataFrame:
        """确保full。
        
            参数:
                symbol: str
                period: str
        
            返回:
                pd.DataFrame"""
        key = (symbol, period)
        if key not in self._full:
            try:
                df = self.feed.get_history(
                    symbol, "2000-01-01", "2100-01-01", period=period, limit=6000)
            except Exception as exc:               # noqa: BLE001
                if self.source != "tqsdk":
                    raise
                # 阶段 5：TqSdk 失败必须显式呈现，绝不生成合成行情
                self.feed_error = (getattr(exc, "user_message", "")
                                   or f"{type(exc).__name__}: {exc}")
                df = None
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                if self.source == "tqsdk":
                    # 明确错误：返回空表 + 错误说明，由 UI 空态呈现，不伪装真实/合成
                    df = pd.DataFrame(columns=[
                        "datetime", "open", "high", "low", "close",
                        "volume", "open_interest"])
                    attach_provenance(
                        df, "tqsdk", is_synthetic=False, is_stale=False,
                        as_of=None, note=f"TqSdk 取数失败：{self.feed_error}")
                else:
                    # 阶段 0：回退合成不再静默 —— 写入 note，UI/回测可据此显示水印
                    requested = self.source
                    reason = f"{requested} 无 {period} 周期数据，回退合成"
                    if self.feed_error:
                        reason += f"（{self.feed_error}）"
                    df = self._synth.get_history(
                        symbol, "2000-01-01", "2100-01-01", period=period, limit=6000)
                    as_of = df["datetime"].iloc[-1] if len(df) else None
                    attach_provenance(df, "synthetic", is_synthetic=True, is_stale=False,
                                      as_of=as_of, note=reason)
            else:
                prov = get_provenance(df)
                if prov["data_source"] == "unknown":
                    # 自定义 feed 未标注：按当前源补标，避免下游拿到「来源未知」
                    as_of = df["datetime"].iloc[-1] if "datetime" in df else None
                    attach_provenance(df, self.source, is_synthetic=False, as_of=as_of)
            self._full[key] = df
        return self._full[key]

    def get_bars(self, symbol: str, period: str = "1m", limit: int = 600) -> pd.DataFrame:
        """取某合约某周期最近 limit 根 K 线（携带来源元数据）。

        第三轮 A：`is_stale` 在此按周期阈值落地（日线 >1 交易日、分钟 >5 分钟、
        周线 >7 天）；合成数据不做时效判定（其时间轴由生成器决定）。
        """
        full = self._ensure_full(symbol, period)
        out = full.tail(limit).reset_index(drop=True)
        # pandas 的切片/重置索引可能丢失 attrs，这里显式回写，保证 UI 水印可靠
        prov = get_provenance(full)
        stale, why = evaluate_staleness(prov["as_of"], period)
        if stale and not prov["is_synthetic"]:
            prov["is_stale"] = True
            prov["note"] = (f"{prov['note']}；" if prov["note"] else "") + why
        attach_provenance(out, prov["data_source"], prov["is_synthetic"],
                          prov["is_stale"], prov["as_of"], prov["note"])
        self.last_provenance = dict(prov)
        return out

    # ------------------------------------------------------------------
    def get_quote(self, symbol: str, period: str = "1m") -> dict:
        """盘口快照。sina 模式下日内周期回退到真实日线计算，避免冒充实盘。"""
        eff = period if self._period_real(period) else "D"
        win = PERIOD_SESSION_BARS.get(eff, 240)
        limit = win + 2 if eff in ("D", "W", "M") else max(win * 2 + 2, 600)
        df = self.get_bars(symbol, eff, limit=limit)
        if df.empty:
            return {}
        # 精确匹配品种乘数（禁止前缀匹配：IF 不得命中 I）
        row = find_universe_row(symbol)
        mult = float(row[4]) if row else 10.0
        # 第二轮修正（P0-2）：当日口径（当日涨跌幅 / 当日 OI / 当日资金流）
        snap = daily_snapshot(df, mult)
        last = snap["last"]
        prev = snap["prev_close"] if snap["prev_close"] is not None else last
        ref = prev
        chg = snap["chg"]
        chg_pct = snap["chg_pct"]
        vol = snap["volume_day"]
        oi = snap["oi_now"]
        fund = snap["fund_flow"]
        prov = get_provenance(df)
        return {
            "symbol": symbol, "last": last, "ref": ref, "prev": prev,
            "chg": chg, "chg_pct": chg_pct, "volume": vol, "open_interest": oi,
            "amount": last * vol * mult / 1e4, "fund_flow": fund,
            # 当日口径附加字段（新增字段，保证向后兼容）
            "oi_prev": snap["oi_prev"], "oi_chg": snap["oi_chg"],
            "oi_chg_pct": snap["oi_chg_pct"], "has_prev_day": snap["has_prev_day"],
            "trading_day": snap["trading_day"],
            # 阶段 0：来源元数据（默认值保证向后兼容）
            "data_source": prov["data_source"], "is_synthetic": prov["is_synthetic"],
            "is_stale": prov["is_stale"], "as_of": prov["as_of"], "note": prov["note"],
        }

    # ------------------------------------------------------------------
    def compute_panorama(self, period: str = "D") -> pd.DataFrame:
        """全市场全景聚合。sina 模式下强制用真实日线。"""
        eff = period if self._period_real(period) else "D"
        rows = []
        sources: set = set()
        synthetic_count = 0
        stale_count = 0
        win = PERIOD_SESSION_BARS.get(eff, 240)
        limit = win + 60 if eff in ("D", "W", "M") else max(win * 2 + 60, 600)
        for row in self.universe:
            sym = f"{row[0]}.{row[3]}"
            try:
                # 真实源模式必须取 eff 周期（原实现误用请求周期，导致回退到合成数据）
                df = self.get_bars(sym, eff, limit=limit)
            except Exception:
                continue
            if len(df) < 3:
                continue
            prov = get_provenance(df)
            sources.add(prov["data_source"])
            if prov["is_synthetic"]:
                synthetic_count += 1
            if prov["is_stale"]:
                stale_count += 1
            # 第二轮修正（P0-2）：当日口径，取代窗口首根/半窗口/30 根累计
            snap = daily_snapshot(df, float(row[4]))
            last = snap["last"]
            chg_pct = snap["chg_pct"]
            vol_recent = snap["volume_day"]
            half = max(1, len(df) // 2)
            vol_prior = float(df["volume"].head(half).mean())
            vol_ratio = (float(df["volume"].tail(half).mean()) / vol_prior) if vol_prior else 1.0
            rows.append({
                "symbol": sym, "name": row[1], "category": row[2],
                "last": last, "chg_pct": round(chg_pct, 2),
                "volume": vol_recent, "vol_ratio": round(vol_ratio, 2),
                "oi_chg": round(snap["oi_chg_pct"], 2),
                "oi_chg_abs": round(snap["oi_chg"], 0),
                "fund_flow": round(snap["fund_flow"], 3),
                "has_prev_day": snap["has_prev_day"],
            })
        pan = pd.DataFrame(rows)
        if pan.empty:
            return pan
        from datetime import datetime as _dt
        note_parts = []
        if synthetic_count:
            note_parts.append(f"{synthetic_count}/{len(pan)} 个品种为合成数据")
        if stale_count:
            note_parts.append(f"{stale_count} 个品种为过期缓存")
        attach_provenance(
            pan, "mixed" if len(sources) > 1 else (next(iter(sources)) if sources else "unknown"),
            is_synthetic=bool(synthetic_count), is_stale=bool(stale_count),
            as_of=_dt.now(), note="；".join(note_parts))
        # 强弱分：动量 60% + 量能 40%（分位排名）
        if len(pan) > 1:
            pan["strength"] = (
                0.6 * pan["chg_pct"].rank(pct=True)
                + 0.4 * pan["vol_ratio"].rank(pct=True)
            ).round(3)
        else:
            pan["strength"] = 0.5
        return pan.sort_values("chg_pct", ascending=False).reset_index(drop=True)

    # ------------------------------------------------------------------
    # 模拟实时流
    # ------------------------------------------------------------------
    def start_live(self, symbol: str, period: str = "1m", interval_ms: int = 1000) -> None:
        """启动live。

        参数:
            symbol: str
            period: str
            interval_ms: int

        M4-10 spec ④：真实源模式（非合成）的 get_recent 调用节流至 2s，并在
        子线程（LiveDataWorker）中执行，避免主线程高频阻塞。合成源模式保持
        QTimer 周期随机游走。
        """
        self._interval_ms = interval_ms
        # 使用目标周期的基准序列（避免 1 分钟重采样日线只剩几根）
        base = self.feed.get_recent(symbol, period, limit=2000)
        if base is None or base.empty:
            base = self._synth.get_recent(symbol, period, limit=2000)
        if base is None or base.empty:
            base = self._ensure_full(symbol, period)
        self._live[symbol] = {"period": period, "df": base.copy(), "cursor": len(base) - 1}
        self._live_symbol = symbol

        # M4-10 spec ④：真实源实时刷新改由子线程 + 节流（2s）驱动
        if self.allow_sim and self.source not in REAL_SOURCES:
            # 合成源：由 QTimer 周期随机游走驱动
            if not self._timer.isActive():
                self._timer.start(interval_ms)
            return

        # 真实源：启动 LiveDataWorker 节流刷新
        self._live_worker = LiveDataWorker(self.feed, symbol, period, interval_ms)
        self._live_worker._refresh_once()  # 立即刷新一次
        t = self._live_worker
        t.finished.connect(self._on_live_worker_finished)
        t.error.connect(self._on_live_worker_error)
        self._live_worker.start()

    def stop_live(self, symbol: str | None = None) -> None:
        """停止live。

        参数:
            symbol: str | None"""
        if symbol:
            self._live.pop(symbol, None)
            if self._live_worker is not None and self._live_worker._symbol == symbol:
                self._live_worker.stop()
                self._live_worker = None
        if symbol is None and not self._live:
            if self._live_worker is not None:
                self._live_worker.stop()
                self._live_worker = None
            if not self._timer.isActive():
                self._timer.stop()

    def _on_live_worker_finished(self) -> None:
        """LiveDataWorker 完成：更新状态灯（真实源实时流已刷新一次）。"""
        sym = getattr(self, "_live_symbol", None)
        if sym and sym in self._live:
            st = self._live[sym]
            last = st["df"].iloc[-1]
            bar = {
                "datetime": str(last["datetime"])[:19],
                "open": float(last["open"]), "high": float(last["high"]),
                "low": float(last["low"]), "close": float(last["close"]),
                "volume": float(last["volume"]),
                "open_interest": float(last["open_interest"]),
                "symbol": sym,
            }
            self.bar_arrived.emit(bar)
            self.quote_updated.emit(sym)

    def _on_live_worker_error(self, msg: str) -> None:
        """LiveDataWorker 异常：记录日志，保持实时流可用（合成游走兜底）。"""
        logger.warning("实时数据刷新异常: %s", msg)
        sym = getattr(self, "_live_symbol", None)
        if sym and sym in self._live:
            st = self._live[sym]
            last = st["df"].iloc[-1]
            bar = {
                "datetime": str(last["datetime"])[:19],
                "open": float(last["open"]), "high": float(last["high"]),
                "low": float(last["low"]), "close": float(last["close"]),
                "volume": float(last["volume"]),
                "open_interest": float(last["open_interest"]),
                "symbol": sym,
            }
            self.bar_arrived.emit(bar)
            self.quote_updated.emit(sym)

    def _tick(self) -> None:
        """处理Tick 数据（仅合成/模拟源；真实源实时刷新由 LiveDataWorker 负责）。"""
        for sym, st in list(self._live.items()):
            df = st["df"]
            period = st["period"]
            c = st["cursor"] + 1
            if c < len(df):
                st["cursor"] = c
            else:
                if self.allow_sim:
                    # 序列用尽：以前一根为基准随机游走生成下一根（仅合成源）
                    last = df.iloc[-1]
                    rng = np.random.default_rng(int(float(last["close"]) * 1000) + c)
                    ret = rng.normal(0, 0.0012)
                    nc = float(last["close"]) * (1 + ret)
                    no = nc * (1 + rng.normal(0, 0.0004))
                    hi = max(no, nc) * (1 + abs(rng.normal(0, 0.0006)))
                    lo = min(no, nc) * (1 - abs(rng.normal(0, 0.0006)))
                    nb = pd.DataFrame([{
                        "datetime": pd.to_datetime(last["datetime"]) + pd.Timedelta(minutes=1),
                        "open": no, "high": hi, "low": lo, "close": nc,
                        "volume": float(rng.integers(800, 1500)),
                        "open_interest": float(last["open_interest"]),
                    }])
                    df = pd.concat([df, nb], ignore_index=True)
                    st["df"] = df
                    st["cursor"] = c
                else:
                    # 实盘源：到达末尾后由 LiveDataWorker 每 2s 刷新真实棒
                    # 此处不再立即调用 feed.get_recent，避免主线程阻塞
                    pass
            bar = df.iloc[st["cursor"]].to_dict()
            bar["symbol"] = sym
            self.bar_arrived.emit(bar)
            self.quote_updated.emit(sym)
