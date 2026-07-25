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
import os
import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .synthetic import SyntheticFeed, FUTURES_UNIVERSE, resample_bars
from ..runtime import get_data_dir

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_config() -> dict:
    """读取项目根 config/settings.json（不存在则给默认值）。"""
    try:
        with open(os.path.join(_ROOT, "config", "settings.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 周期 -> 聚合参考窗（用于计算"涨跌幅"的基准，近似一个交易时段）
PERIOD_SESSION_BARS = {
    "1m": 240, "5m": 48, "15m": 16, "30m": 8, "1h": 4, "4h": 2, "D": 1, "W": 1,
}


def _build_feed(source: str, data_path: str):
    """按 source 构建数据源；sina 探测失败自动回退 synthetic。返回 (feed, effective_source)。"""
    synth = SyntheticFeed()
    if source == "sina":
        try:
            from .sina_feed import SinaFeed
            cache = os.path.join(data_path, "sina_cache")
            f = SinaFeed(cache_dir=cache)
            # 轻量探测：拉取默认品种最近 3 根日线，失败则回退
            probe = f.get_recent("rb.SHFE", "D", 3)
            if probe is not None and not probe.empty:
                return f, "sina"
        except Exception:
            pass
        return synth, "synthetic"
    if source == "ctp":
        try:
            from .ctp_gateway import CTPFeed
            return CTPFeed(), "ctp"
        except Exception:
            return synth, "synthetic"
    return synth, "synthetic"


class MarketDataManager(QObject):
    """行情中枢：缓存 + 快照 + 全景 + 模拟实时。"""

    bar_arrived = pyqtSignal(object)      # 实时新增的一根 Bar(dict)
    quote_updated = pyqtSignal(str)       # symbol
    status_changed = pyqtSignal(str)      # 连接状态文本

    def __init__(self, feed=None, source: str | None = None) -> None:
        super().__init__()
        cfg = _load_config()
        data_path = cfg.get("data_path", "data")
        # 归一化到可写数据目录：相对路径/None -> get_data_dir()，绝对路径原样
        if not data_path or not os.path.isabs(data_path):
            data_path = get_data_dir()
        if source is None:
            source = cfg.get("data", {}).get("source", "synthetic")
        if feed is not None:
            self.feed = feed
            self.source = "custom"
            self.allow_sim = True
        else:
            self.feed, self.source = _build_feed(source, data_path)
        self.allow_sim = (self.source != "sina")   # 仅 sina 为真实源，禁止随机游走伪造
        self.is_real = False                        # 是否存在「真正连上的实盘源」
        self.universe = FUTURES_UNIVERSE
        self._full: dict[str, pd.DataFrame] = {}     # (symbol, period) -> 完整序列
        self._live: dict[str, dict] = {}             # symbol -> 实时游标状态
        self._synth = SyntheticFeed()                # 日内/失败回退用
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._interval_ms = 1000
        self.status = "离线"

    # ------------------------------------------------------------------
    def _default_symbol(self) -> str:
        cfg = _load_config()
        return cfg.get("analysis", {}).get("default_symbol", "rb.SHFE")

    def _period_real(self, period: str) -> bool:
        """该周期是否有真实数据。

        - 非真实源（合成 / sina 获取失败回退）：一律按合成处理；
        - sina 连上时仅 D/W 真实（免费接口无分钟线）；
        - ctp 连上时全部周期真实。
        """
        if not self.is_real:
            return False
        if self.source == "sina":
            return period in ("D", "1D", "W", "1W")
        return True

    def connect(self) -> None:
        """建立数据源连接（按 source）。sina 实时不可达时自动回退合成；
        ctp 未连上时明确报告「未连接」并允许合成回退（绝不冒充实盘）。"""
        self.is_real = False
        if self.source == "sina":
            probe = self.feed.get_recent(self._default_symbol(), "D", 3)
            if probe is None or probe.empty:
                self.feed = self._synth
                self.source = "synthetic"
                self.allow_sim = True
                self.status = "已连接 · 合成行情(模拟, 实盘获取失败)"
            else:
                self.is_real = True
                self.status = "已连接 · 新浪实盘日线"
        elif self.source == "ctp":
            self._wire_ctp_feed()
            ok = self.feed.connect()
            self.is_real = ok
            self.status = self.feed.source_label
            if ok:
                self.allow_sim = False          # 实盘源：到达末尾不伪造，尝试刷新真实棒
                self._start_reconnect_watch()
            else:
                self.allow_sim = True           # CTP 未连上：允许合成回退并清晰标注
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
        if not hasattr(self, "_reconnect_timer"):
            self._reconnect_timer = QTimer()
            self._reconnect_timer.timeout.connect(self._reconnect_tick)
        self._reconnect_timer.start(30000)   # 每 30s 检查 CTP 断线并重连

    def _reconnect_tick(self) -> None:
        if self.source != "ctp" or not hasattr(self, "_reconnect_timer"):
            if hasattr(self, "_reconnect_timer"):
                self._reconnect_timer.stop()
            return
        if not self.feed.connected:
            self.feed.maybe_reconnect()
            self.is_real = self.feed.connected

    def disconnect(self) -> None:
        self._timer.stop()
        if hasattr(self, "_reconnect_timer"):
            self._reconnect_timer.stop()
        if self.source == "ctp" and getattr(self.feed, "connected", False):
            try:
                self.feed.disconnect()
            except Exception:
                pass
        self.is_real = False
        self.status = "离线"
        self.status_changed.emit(self.status)

    @property
    def source_label(self) -> str:
        return getattr(self.feed, "source_label", "合成行情(模拟)")

    # ------------------------------------------------------------------
    def _ensure_full(self, symbol: str, period: str = "1m") -> pd.DataFrame:
        key = (symbol, period)
        if key not in self._full:
            df = self.feed.get_history(
                symbol, "2000-01-01", "2100-01-01", period=period, limit=6000)
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                df = self._synth.get_history(
                    symbol, "2000-01-01", "2100-01-01", period=period, limit=6000)
            self._full[key] = df
        return self._full[key]

    def get_bars(self, symbol: str, period: str = "1m", limit: int = 600) -> pd.DataFrame:
        """取某合约某周期最近 limit 根 K 线。"""
        full = self._ensure_full(symbol, period)
        return full.tail(limit).reset_index(drop=True)

    # ------------------------------------------------------------------
    def get_quote(self, symbol: str, period: str = "1m") -> dict:
        """盘口快照。sina 模式下日内周期回退到真实日线计算，避免冒充实盘。"""
        eff = period if self._period_real(period) else "D"
        df = self.get_bars(symbol, eff, limit=PERIOD_SESSION_BARS.get(eff, 240) + 2)
        if df.empty:
            return {}
        last = float(df["close"].iloc[-1])
        ref = float(df["close"].iloc[0])          # 时段开盘基准
        prev = float(df["close"].iloc[-2]) if len(df) > 1 else last
        chg = last - ref
        chg_pct = (chg / ref * 100.0) if ref else 0.0
        mult = 10.0
        for row in self.universe:
            if symbol.startswith(row[0]):
                mult = row[5]
                break
        vol = float(df["volume"].iloc[-1]) if "volume" in df else 0.0
        oi = float(df["open_interest"].iloc[-1]) if "open_interest" in df else 0.0
        # 资金流代理：近期 (收-开)*量*价*乘数（亿元），正为净流入
        recent = df.tail(20)
        fund = float(((recent["close"] - recent["open"]) * recent["volume"] * recent["close"] * mult).sum() / 1e8)
        return {
            "symbol": symbol, "last": last, "ref": ref, "prev": prev,
            "chg": chg, "chg_pct": chg_pct, "volume": vol, "open_interest": oi,
            "amount": last * vol * mult / 1e4, "fund_flow": fund,
        }

    # ------------------------------------------------------------------
    def compute_panorama(self, period: str = "D") -> pd.DataFrame:
        """全市场全景聚合。sina 模式下强制用真实日线。"""
        eff = period if self._period_real(period) else "D"
        rows = []
        win = PERIOD_SESSION_BARS.get(eff, 240)
        for row in self.universe:
            sym = f"{row[0]}.{row[3]}"
            try:
                df = self.get_bars(sym, period, limit=win + 60)
            except Exception:
                continue
            if len(df) < 3:
                continue
            last = float(df["close"].iloc[-1])
            ref = float(df["close"].iloc[0])
            chg_pct = (last - ref) / ref * 100.0 if ref else 0.0
            half = max(1, len(df) // 2)
            vol_recent = float(df["volume"].tail(half).mean())
            vol_prior = float(df["volume"].head(half).mean())
            vol_ratio = (vol_recent / vol_prior) if vol_prior else 1.0
            oi_now = float(df["open_interest"].iloc[-1]) if "open_interest" in df else 0.0
            oi_prev = float(df["open_interest"].iloc[half]) if "open_interest" in df else 0.0
            oi_chg = (oi_now - oi_prev) / oi_prev * 100.0 if oi_prev else 0.0
            mult = row[5]
            fund = float(((df["close"] - df["open"]) * df["volume"] * df["close"] * mult).tail(half).sum() / 1e8)
            rows.append({
                "symbol": sym, "name": row[1], "category": row[2],
                "last": last, "chg_pct": round(chg_pct, 2),
                "volume": vol_recent, "vol_ratio": round(vol_ratio, 2),
                "oi_chg": round(oi_chg, 2), "fund_flow": round(fund, 3),
            })
        pan = pd.DataFrame(rows)
        if pan.empty:
            return pan
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
        self._interval_ms = interval_ms
        # 使用目标周期的基准序列（避免 1 分钟重采样日线只剩几根）
        base = self.feed.get_recent(symbol, period, limit=2000)
        if base is None or base.empty:
            base = self._synth.get_recent(symbol, period, limit=2000)
        if base is None or base.empty:
            base = self._ensure_full(symbol, period)
        self._live[symbol] = {"period": period, "df": base.copy(), "cursor": len(base) - 1}
        if not self._timer.isActive():
            self._timer.start(self._interval_ms)

    def stop_live(self, symbol: str | None = None) -> None:
        if symbol:
            self._live.pop(symbol, None)
        if not self._live:
            self._timer.stop()

    def _tick(self) -> None:
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
                    # 实盘源：到达末尾后尝试刷新最新真实棒；无更新则保持末棒，绝不伪造
                    fresh = self.feed.get_recent(sym, period, limit=3)
                    if (fresh is not None and not fresh.empty
                            and pd.to_datetime(fresh["datetime"].iloc[-1])
                            > pd.to_datetime(df["datetime"].iloc[-1])):
                        nb = fresh.tail(1).copy()
                        nb["datetime"] = pd.to_datetime(nb["datetime"])
                        df = pd.concat([df, nb], ignore_index=True)
                        st["df"] = df
                        st["cursor"] = len(df) - 1
                    # 否则保持末棒不变
            bar = df.iloc[st["cursor"]].to_dict()
            bar["symbol"] = sym
            self.bar_arrived.emit(bar)
            self.quote_updated.emit(sym)
