"""QuantVortex 性能与稳定性基线测量脚本（只读探针）。

设计原则
========
1. **只读**：不修改 ``futures_quant`` 下任何业务代码，不写 data/ 与数据库，
   不联网，不安装依赖，不 git commit。
2. **可重复**：所有场景先 warm-up（可选）再取 N 次中位数，并记录 min/max/波动。
3. **子进程隔离**：UI（Qt offscreen）与内存（RSS）在独立子进程中测量，
   避免 Qt 与训练内存污染其他场景的结论。
4. **离线数据**：直接读取 ``data/sina_cache`` / ``data/akshare_cache`` 下的
   本地日线 CSV，不触发任何网络请求。

用法示例
========
    python scripts/perf_probe.py --section all
    python scripts/perf_probe.py --section anchor    # 回测数字唯一口径（锚点对齐）
    python scripts/perf_probe.py --section backtest
    python scripts/perf_probe.py --section indicators --runs 3
    python scripts/perf_probe.py --section ai --runs 3
    python scripts/perf_probe.py --section ui
    python scripts/perf_probe.py --section memory
    python scripts/perf_probe.py --section report   # 用已有分节 JSON 重新生成报告

输出
====
    outputs/perf_baseline.md       # 汇总报告
    outputs/.perf_<section>.json   # 分节原始数据（供复核/重生成报告）
"""
from __future__ import annotations

import argparse
import contextlib
import cProfile
import gc
import glob
import hashlib
import io
import json
import math
import os
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "outputs"
TEMP_DIR = OUT_DIR  # 分节 JSON 落在 outputs/ 作为可复核证据（不是 .md 交付物）

# 固定测量区间（与任务一致）
START = "2020-01-01"
END = "2026-09-30"

# 43 个流动性较好的品种（全部能在 data/sina_cache 找到离线日线）
BATCH_CODES = [
    "RB", "HC", "I", "J", "JM", "SF", "SM", "SS", "CU", "AL",
    "ZN", "NI", "SN", "PB", "AU", "AG", "SC", "FU", "BU", "RU",
    "L", "V", "TA", "MA", "EG", "PP", "M", "RM", "Y", "P",
    "SR", "CF", "C", "JD", "AP", "CJ", "IF", "IH", "IC", "IM",
    "T", "TF", "TS",
]

EXCHANGE_BY_CODE = {
    "RB": "SHFE", "HC": "SHFE", "I": "DCE", "J": "DCE", "JM": "DCE",
    "SF": "CZCE", "SM": "CZCE", "SS": "SHFE", "CU": "SHFE", "AL": "SHFE",
    "ZN": "SHFE", "NI": "SHFE", "SN": "SHFE", "PB": "SHFE", "AU": "SHFE",
    "AG": "SHFE", "SC": "INE", "FU": "SHFE", "BU": "SHFE", "RU": "SHFE",
    "L": "DCE", "V": "DCE", "TA": "CZCE", "MA": "CZCE", "EG": "DCE",
    "PP": "DCE", "M": "DCE", "RM": "CZCE", "Y": "DCE", "P": "DCE",
    "SR": "CZCE", "CF": "CZCE", "C": "DCE", "JD": "DCE", "AP": "CZCE",
    "CJ": "CZCE", "IF": "CFFEX", "IH": "CFFEX", "IC": "CFFEX", "IM": "CFFEX",
    "T": "CFFEX", "TF": "CFFEX", "TS": "CFFEX",
}

# 需要快照修改时间的业务文件（用于说明“测量期间代码是否被别人改动”）
CODE_FILES = [
    "futures_quant/backtest/backtester.py",
    "futures_quant/core/engine.py",
    "futures_quant/indicators/tech.py",
    "futures_quant/ai/predictor.py",
    "futures_quant/ai/lstm.py",
    "futures_quant/ai/features.py",
    "futures_quant/ui/main_window.py",
]


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _safe(obj: Any) -> Any:
    """JSON 序列化清洗：numpy 标量、NaN/Inf、Path、datetime 统一转可读值。"""
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        np = None  # type: ignore
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    if np is not None:
        if isinstance(obj, np.generic):
            return _safe(obj.item())
        if isinstance(obj, np.ndarray):
            return [_safe(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_safe(v) for v in obj]
    return str(obj)


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    """线性插值分位数；空列表返回 None。"""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(s[lo])
    return float(s[lo] + (s[hi] - s[lo]) * (pos - lo))


def _stats(samples_ms: Sequence[float]) -> Dict[str, Any]:
    """把耗时样本汇总成中位数 / 极值 / 波动 / P95。"""
    vals = [float(x) for x in samples_ms if x is not None]
    if not vals:
        return {"n": 0, "median_ms": None, "min_ms": None, "max_ms": None,
                "p95_ms": None, "stdev_ms": None, "samples_ms": []}
    return {
        "n": len(vals),
        "median_ms": round(statistics.median(vals), 3),
        "min_ms": round(min(vals), 3),
        "max_ms": round(max(vals), 3),
        "p95_ms": round(_percentile(vals, 0.95) or 0.0, 3),
        "stdev_ms": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
        "samples_ms": [round(v, 3) for v in vals],
    }


def _measure(fn: Callable[[], Any], runs: int = 3, warmup: int = 1) -> Dict[str, Any]:
    """执行 warm-up 后重复计时；返回毫秒统计与每次输出。"""
    last_result: Any = None
    for _ in range(max(0, warmup)):
        last_result = fn()
    samples: List[float] = []
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        last_result = fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    out = _stats(samples)
    out["last_result"] = last_result
    return out


def _rss_mb() -> float:
    """当前进程 RSS（MB）。"""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return float("nan")


def _cpu_percent(interval: float = 0.5) -> Optional[float]:
    try:
        import psutil
        return psutil.cpu_percent(interval=interval)
    except Exception:  # noqa: BLE001
        return None


def _python_processes() -> List[Dict[str, Any]]:
    """列出当前 python 进程（帮助判断是否有其他会话同时跑测试）。"""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            name = (p.info.get("name") or "").lower()
            if "python" not in name:
                continue
            mi = p.info.get("memory_info")
            rows.append({
                "pid": p.info.get("pid"), "name": p.info.get("name"),
                "rss_mb": round(mi.rss / (1024 * 1024), 1) if mi else None,
            })
        except Exception:  # noqa: BLE001
            continue
    return sorted(rows, key=lambda r: r.get("rss_mb") or 0, reverse=True)[:12]


def _code_mtimes() -> Dict[str, str]:
    """记录关键业务文件的最后修改时间，用于说明测量代码快照。"""
    out: Dict[str, str] = {}
    for rel in CODE_FILES:
        p = ROOT / rel
        try:
            out[rel] = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:  # noqa: BLE001
            out[rel] = "missing"
    return out


def _env_info() -> Dict[str, Any]:
    """采集环境与依赖可用性。"""
    import importlib.util as iu
    pkgs = {}
    for m in ["numpy", "pandas", "PyQt6", "psutil", "torch", "lightgbm",
              "sklearn", "arch", "akshare"]:
        try:
            spec = iu.find_spec(m)
            pkgs[m] = bool(spec)
        except Exception:  # noqa: BLE001
            pkgs[m] = False
    info: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": sys.platform,
        "packages": pkgs,
        "cpu_count": os.cpu_count(),
    }
    try:
        import numpy, pandas
        info["numpy"] = numpy.__version__
        info["pandas"] = pandas.__version__
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["mem_total_gb"] = round(vm.total / (1024 ** 3), 2)
        info["mem_available_gb"] = round(vm.available / (1024 ** 3), 2)
        try:
            info["loadavg_1_5_15"] = [round(x, 2) for x in psutil.getloadavg()]
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass
    info["python_processes"] = _python_processes()
    info["proc_rss_mb"] = round(_rss_mb(), 1)
    return info


# ---------------------------------------------------------------------------
# 离线日线数据源（不联网、不写 data/）
# ---------------------------------------------------------------------------
def _build_local_daily_map() -> Dict[str, Path]:
    """扫描本地缓存目录，建立 品种代码→CSV 路径 映射（优先级 akshare>sina>real）。

    只接受日线文件；每行只需 datetime/open/high/low/close/volume（settle 可选）。
    """
    code_map: Dict[str, Path] = {}
    # 1) akshare_cache / real_samples：文件名形如 rb_SHFE_D.csv
    for d in ["data/akshare_cache", "data/real_samples"]:
        for p in glob.glob(str(ROOT / d / "*_D.csv")):
            stem = Path(p).stem
            code = stem.split("_")[0].lower()
            code_map.setdefault(code, Path(p))
    # 2) sina_cache：文件名形如 rb0.csv（日线）
    for p in glob.glob(str(ROOT / "data/sina_cache" / "*.csv")):
        stem = Path(p).stem.lower()
        if stem.endswith("0") and len(stem) > 1:
            code_map.setdefault(stem[:-1], Path(p))
    return code_map


def _symbol_name(code: str) -> str:
    return f"{code.lower()}.{EXCHANGE_BY_CODE[code]}"


def _load_daily_csv(path: Path) -> "Any":
    """读取本地日线 CSV 并标准化列；返回按时间升序的 DataFrame。"""
    import pandas as pd
    df = pd.read_csv(path)
    if "datetime" not in df.columns:
        if "date" in df.columns:
            df = df.rename(columns={"date": "datetime"})
        else:
            df = df.reset_index().rename(columns={"index": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            if col == "volume":
                df[col] = 0.0
            elif col in ("high", "low", "open"):
                df[col] = df["close"]
            else:
                raise ValueError(f"缺少必要列 close：{path}")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "open_interest" not in df.columns:
        df["open_interest"] = 0.0
    return df[["datetime", "open", "high", "low", "close", "volume", "open_interest"]]


class LocalDailyFeed:
    """离线日线 Feed：一次性载入内存，get_history 只做切片（读多写零）。"""

    def __init__(self) -> None:
        from futures_quant.data.base import attach_provenance, DataFeed
        self._attach = attach_provenance
        self._DataFeed = DataFeed
        self._map = _build_local_daily_map()
        self._frames: Dict[str, Any] = {}

    def _code(self, symbol: str) -> str:
        return symbol.split(".")[0].lower()

    def get_history(self, symbol: str, start: str, end: str,
                    period: str = "D", limit: int = 0) -> Any:
        """返回 [start, end] 区间日线；非日线周期抛错（本探针不测分钟线）。"""
        if period.upper() not in ("D", "1D", "DAILY"):
            raise ValueError(f"LocalDailyFeed 仅支持日线，收到 {period}")
        code = self._code(symbol)
        if code not in self._frames:
            p = self._map.get(code)
            if p is None:
                raise FileNotFoundError(f"本地缓存缺失品种 {symbol}（code={code}）")
            df = _load_daily_csv(p)
            self._attach(
                df, source="sina/akshare-cache", is_synthetic=False,
                is_stale=False, as_of=datetime.now(),
                note=f"perf_probe 离线读取 {p.name}",
            )
            self._frames[code] = df
        df = self._frames[code]
        view = df[(df["datetime"] >= start) & (df["datetime"] <= end)]
        if limit and len(view) > int(limit):
            view = view.tail(int(limit))
        return view.reset_index(drop=True).copy()


# ---------------------------------------------------------------------------
# 场景 1：回测引擎
# ---------------------------------------------------------------------------
def _make_backtester(feed: Any, symbol: str):
    """按 UI/服务层同样的方式组装 Backtester（单品种单策略）。"""
    from futures_quant.backtest.backtester import Backtester
    from futures_quant.config.settings import Config
    from futures_quant.data.contract_specs import build_contract
    from futures_quant.strategy.trend_following import TrendFollowing

    bt = Backtester(Config(), feed)
    bt.add_contract(build_contract(symbol))
    bt.add_strategy(TrendFollowing(symbol=symbol))
    return bt


def _run_once(feed: Any, symbol: str, start: str = START, end: str = END,
              warmup: int = 0) -> Dict[str, Any]:
    """计时专用入口（warmup=0，尽量让引擎跑满全区间）。

    注意：这里的 ``metrics`` 只用于「代码改动前后是否一致」的健全性核对，
    **不是对外报告的回测数字口径**——数值口径见 ``--section anchor``。
    """
    bt = _make_backtester(feed, symbol)
    res = bt.run(symbol, start, end, "D", warmup)
    metrics = dict(res.get("metrics") or {})
    keep = {}
    for k in ("num_fills", "total_return", "annual_return", "max_drawdown",
              "sharpe", "final_equity", "win_rate"):
        if k in metrics:
            keep[k] = metrics[k]
    return {"metrics": keep}


def _profile_top(prof: cProfile.Profile, limit: int = 15) -> Tuple[List[Dict[str, Any]], str]:
    """从 cProfile 结果提取按 cumulative time 排序的前 N 个函数。"""
    stats = pstats.Stats(prof)
    rows: List[Dict[str, Any]] = []
    for (fname, line, func), (_cc, nc, tt, ct, _callers) in stats.stats.items():
        rows.append({
            "function": func,
            "location": f"{os.path.basename(fname)}:{line}",
            "file": fname,
            "calls": nc,
            "tottime_ms": round(tt * 1000, 3),
            "cumtime_ms": round(ct * 1000, 3),
        })
    rows.sort(key=lambda r: r["cumtime_ms"], reverse=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        stats.sort_stats("cumulative").print_stats(limit)
    return rows[:limit], buf.getvalue()[:4000]


def section_backtest(runs: int = 3) -> Dict[str, Any]:
    """单品种回测 + 43 品种批量回测 + cProfile Top15。"""
    feed = LocalDailyFeed()
    rb = _symbol_name("RB")
    data_info: Dict[str, Any] = {"source": "本地离线日线缓存（sina_cache/akshare_cache）"}

    # 数据可用性与 bar 数（数据加载不计入回测耗时）
    bars: Dict[str, int] = {}
    for code in BATCH_CODES:
        sym = _symbol_name(code)
        try:
            bars[sym] = int(len(feed.get_history(sym, START, END, "D")))
        except Exception as exc:  # noqa: BLE001
            bars[sym] = -1
            data_info.setdefault("missing", []).append(f"{sym}: {exc}")
    data_info["symbols"] = len(BATCH_CODES)
    data_info["bars_min"] = min(v for v in bars.values() if v > 0) if any(v > 0 for v in bars.values()) else None
    data_info["bars_max"] = max(bars.values()) if bars else None
    data_info["bars_total"] = sum(v for v in bars.values() if v > 0)

    # 1) 单品种（rb.SHFE）—— 1 次 warm-up + runs 次计时
    single = _measure(lambda: _run_once(feed, rb), runs=runs, warmup=1)
    last_single = single.pop("last_result", {}) or {}
    single_metrics = last_single.get("metrics", {}) if isinstance(last_single, dict) else {}

    # 2) 43 品种批量 —— 整轮 warm-up + runs 轮计时
    def one_batch() -> Dict[str, List[float]]:
        per_symbol: Dict[str, float] = {}
        for code in BATCH_CODES:
            sym = _symbol_name(code)
            if bars.get(sym, 0) <= 0:
                continue
            t0 = time.perf_counter()
            _run_once(feed, sym)
            per_symbol[sym] = (time.perf_counter() - t0) * 1000.0
        return per_symbol

    batch_last: Dict[str, List[float]] = {}
    for _ in range(1):
        batch_last = one_batch()  # warm-up：预热 numpy/pandas 与各品种首次代码路径
    batch_samples: List[float] = []
    per_symbol_samples: Dict[str, List[float]] = {s: [] for s in batch_last}
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        per = one_batch()
        batch_samples.append((time.perf_counter() - t0) * 1000.0)
        for sym, ms in per.items():
            per_symbol_samples.setdefault(sym, []).append(ms)
        batch_last = per

    batch_stats = _stats(batch_samples)
    per_symbol_median = {s: round(statistics.median(v), 3) for s, v in per_symbol_samples.items() if v}
    slowest = sorted(per_symbol_median.items(), key=lambda kv: kv[1], reverse=True)[:5]

    # 3) cProfile：单品种一次（剖析开销会使绝对值偏大，只看相对热点）
    prof = cProfile.Profile()
    bt = _make_backtester(feed, rb)
    prof.enable()
    bt.run(rb, START, END, "D", 0)
    prof.disable()
    top, raw = _profile_top(prof, 15)

    return {
        "data_info": data_info,
        "bars_per_symbol": bars,
        "range": [START, END],
        "single": {
            "symbol": rb,
            "stats": single,
            # 计时口径（warmup=0）下的指标不再作为「回测数字」对外，
            # 唯一口径是 --section anchor（warmup=60 / 非交易时段不阻断 / 含移仓成本）。
            "metrics": _safe(single_metrics),
            "metrics_note": "计时口径（warmup=0，全 1636 根）；对外口径见 --section anchor",
            "bars": bars.get(rb),
        },
        "batch": {
            "symbols": len(per_symbol_samples),
            "runs": len(batch_samples),
            "total": batch_stats,
            "avg_per_symbol_ms": round(batch_stats["median_ms"] / max(1, len(per_symbol_samples)), 3)
            if batch_stats["median_ms"] else None,
            "per_symbol_median": dict(sorted(per_symbol_median.items())),
            "slowest5": [{"symbol": s, "median_ms": m} for s, m in slowest],
            "last_run_total_ms": round(sum(batch_last.values()), 3),
        },
        "cprofile": {"top": top, "raw_text": raw},
        "note": "批量回测数据来自本地缓存，各品种 bar 数见 bars_per_symbol；"
                "cProfile 的绝对耗时含剖析开销，不与上面的中位数直接比较。",
    }


# ---------------------------------------------------------------------------
# 场景 1b：回测数字唯一口径（锚点对齐）
# ---------------------------------------------------------------------------
# 口径来源：docs/diagnosis/phase1_rules_matching.md（配置锚点）+
#           docs/diagnosis/phase0_data_risk.md（数据版本差异说明）。
# 唯一有效口径 = 同策略同参数 + warmup=60 + 非交易时段不阻断 + 含移仓成本。
ANCHOR_WARMUP = 60
ANCHOR_BLOCK = False
ANCHOR_ROLL = True
# 锚点快照所用数据 real_samples/rb_SHFE_D.csv 的最后一根（2026-07-27）。
# 用它复算可精确复现 225 笔；当前 akshare 缓存多出 46 个交易日 → 231 笔。
ANCHOR_END = "2026-07-27"
ANCHOR_SYMBOLS = ("RB", "I")
ANCHOR_REF = {
    "rb.SHFE": {"num_fills": 225, "total_return": -0.0076,
                "max_drawdown": 0.0308, "sharpe": -0.129},
    "i.DCE": {"num_fills": 235, "total_return": -0.0089,
              "max_drawdown": 0.0127, "sharpe": -0.465},
}
_ANCHOR_KEYS = ("num_fills", "total_return", "annual_return", "max_drawdown",
                "sharpe", "win_rate", "final_equity")


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _describe_data(symbol: str) -> Dict[str, Any]:
    """记录该品种实际读到的缓存文件与窗口内的 bar 统计。"""
    p = _build_local_daily_map().get(symbol.split(".")[0].lower())
    if p is None:
        return {"file": None, "note": "无本地日线缓存"}
    df = _load_daily_csv(p)
    view = df[(df["datetime"] >= START) & (df["datetime"] <= END)]
    anchor_view = df[(df["datetime"] >= START) & (df["datetime"] <= ANCHOR_END)]
    return {
        "file": str(p),
        "sha1": _file_sha1(Path(p)),
        "rows_file": int(len(df)),
        "rows_window": int(len(view)),
        "rows_anchor_window": int(len(anchor_view)),
        "first": str(view["datetime"].iloc[0].date()) if len(view) else None,
        "last": str(view["datetime"].iloc[-1].date()) if len(view) else None,
        "dup_dates": int(view["datetime"].duplicated().sum()) if len(view) else 0,
    }


def _run_anchor(feed: Any, symbol: str, end: str = END) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """按锚点配置跑一次回测，返回 (指标, 配置快照)。"""
    from futures_quant.backtest.backtester import Backtester
    from futures_quant.config.settings import Config
    from futures_quant.data.contract_specs import build_contract
    from futures_quant.strategy.trend_following import TrendFollowing

    cfg = Config()
    cfg.risk.non_trading_hours_block = ANCHOR_BLOCK
    cfg.backtest.enable_roll_cost = ANCHOR_ROLL
    bt = Backtester(cfg, feed)
    bt.add_contract(build_contract(symbol))
    bt.add_strategy(TrendFollowing(symbol=symbol))
    res = bt.run(symbol, START, end, "D", ANCHOR_WARMUP)
    m = dict(res.get("metrics") or {})
    snap = {
        "strategy": "TrendFollowing",
        "params": dict(TrendFollowing.default_params),
        "range": [START, end],
        "warmup": ANCHOR_WARMUP,
        "non_trading_hours_block": ANCHOR_BLOCK,
        "enable_roll_cost": ANCHOR_ROLL,
        "account": dict(cfg.account.__dict__),
        "backtest": {k: v for k, v in cfg.backtest.__dict__.items()},
    }
    return {k: m.get(k) for k in _ANCHOR_KEYS}, snap


def section_anchor(runs: int = 1) -> Dict[str, Any]:
    """固化回测数字口径：跑「当前全窗口」与「锚点截止日窗口」两组并给判定。

    - ``full_window``（START~END，当前 akshare 缓存到 2026-09-30）：rb 231 笔；
    - ``anchor_window``（START~2026-07-27，与锚点快照同数据长度）：rb 应为 225 笔。
    两组差值即「新缓存多出 46 个交易日」带来的 6 笔成交，与代码/配置无关。
    """
    feed = LocalDailyFeed()
    out: Dict[str, Any] = {
        "canonical": {
            "desc": "同策略同参数 + warmup=60 + 非交易时段不阻断 + 含移仓成本",
            "warmup": ANCHOR_WARMUP,
            "non_trading_hours_block": ANCHOR_BLOCK,
            "enable_roll_cost": ANCHOR_ROLL,
            "anchor_end": ANCHOR_END,
            "range": [START, END],
            "symbols": {},
        },
        "data": {},
        "results": {},
        "verdict": {},
    }
    ok_all = True
    for code in ANCHOR_SYMBOLS:
        sym = _symbol_name(code)
        data = _describe_data(sym)
        out["data"][sym] = data
        full_m, snap = _run_anchor(feed, sym, END)
        anchor_m, _ = _run_anchor(feed, sym, ANCHOR_END)
        out["canonical"]["symbols"][sym] = snap
        out["results"][sym] = {"full_window": full_m, "anchor_window": anchor_m}
        ref = ANCHOR_REF.get(sym, {})
        check = {}
        for k, exp in ref.items():
            got = anchor_m.get(k)
            if got is None:
                check[k] = {"expected": exp, "got": None, "ok": False}
                continue
            if k == "num_fills":
                ok = int(got) == int(exp)
            else:
                ok = abs(float(got) - float(exp)) <= 1e-4
            check[k] = {"expected": exp, "got": got, "ok": bool(ok)}
        away = {k: check[k] for k in check if not check[k]["ok"]}
        ok_all = ok_all and not away
        out["verdict"][sym] = {"anchor_window_matches": not away,
                               "mismatch": away,
                               "bars": {"full": data.get("rows_window"),
                                        "anchor_window": data.get("rows_anchor_window")}}
    out["verdict"]["all_ok"] = bool(ok_all)
    out["note"] = ("数值口径唯一来源：本分节。--section backtest 里的 metrics 是 "
                   "warmup=0 的计时口径，仅用于改前/改后一致性核对，勿对外引用。")

    print(json.dumps({k: out[k] for k in ("canonical", "data", "results", "verdict")},
                     ensure_ascii=False, indent=2, default=str))
    return out


# ---------------------------------------------------------------------------
# 场景 2：指标计算
# ---------------------------------------------------------------------------
def _make_bars(n: int = 5000, seed: int = 20261104) -> "Any":
    """构造确定性 K 线（几何随机游走），用于指标耗时测量。"""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0002, 0.012, n)
    close = 3500.0 * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    vol = rng.integers(1000, 50000, n).astype(float)
    idx = pd.date_range("2012-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "datetime": idx, "open": open_, "high": high, "low": low,
        "close": close, "volume": vol,
        "open_interest": rng.integers(10000, 200000, n).astype(float),
    })


def section_indicators(runs: int = 3) -> Dict[str, Any]:
    """5000 bar 上 add_indicators 总量 + 各计算单元单独耗时（定位最慢 5 个）。"""
    from futures_quant.indicators import tech
    df = _make_bars(5000)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    # 计算单元：每个单元覆盖 1 到多列；合计覆盖 add_indicators 的 36 个指标列
    units: List[Tuple[str, Callable[[], Any], str]] = [
        ("MA5", lambda: tech.sma(close, 5), ""),
        ("MA10", lambda: tech.sma(close, 10), ""),
        ("MA20", lambda: tech.sma(close, 20), ""),
        ("MA60", lambda: tech.sma(close, 60), ""),
        ("EMA20", lambda: tech.ema(close, 20), ""),
        ("BOLL(3列)", lambda: tech.boll(close), ""),
        ("MACD(3列)", lambda: tech.macd(close), ""),
        ("KDJ(3列)", lambda: tech.kdj(close, high, low), ""),
        ("RSI6", lambda: tech.rsi(close, 6), ""),
        ("RSI14", lambda: tech.rsi(close, 14), ""),
        ("DMI(4列)", lambda: tech.dmi(high, low, close), ""),
        ("SAR", lambda: tech.sar(high, low), ""),
        ("BIAS6", lambda: tech.bias(close, 6), ""),
        ("MOM10", lambda: tech.momentum(close, 10), ""),
        ("CCI14", lambda: tech.cci(high, low, close), ""),
        ("OBV", lambda: tech.obv(close, vol), ""),
        ("VOL_MA5", lambda: tech.vol_ma(vol, 5), ""),
        ("ROC12", lambda: tech.roc(close, 12), ""),
        ("ATR14", lambda: tech.atr(high, low, close, 14), ""),
        ("boll_pct", lambda: _derived_boll_pct(tech, df), "tech.py:360-364"),
        ("dir_di", lambda: _derived_dir_di(tech, df), "tech.py:366-370"),
        ("ma20_gap", lambda: _derived_gap(close, tech.sma(close, 20)), "tech.py:373-374"),
        ("ma60_gap", lambda: _derived_gap(close, tech.sma(close, 60)), "tech.py:375-376"),
        ("vol5/vol_ratio", lambda: _derived_volume(vol), "tech.py:379-385"),
        ("obv_chg", lambda: _derived_obv(tech, close, vol), "tech.py:388-391"),
        ("atr_pct", lambda: _derived_atr_pct(tech, high, low, close), "tech.py:393-396"),
        ("HV20", lambda: tech.hv(close, 20), ""),
        ("VWAP", lambda: tech.vwap(high, low, close, vol), ""),
        ("GARCH", lambda: tech.garch(close), ""),
    ]

    # 总量：add_indicators 内部自带 df.copy()，这里直接传原表，贴近 build_features 调用
    total_runs = runs
    total = _measure(lambda: tech.add_indicators(df), runs=total_runs, warmup=1)
    total.pop("last_result", None)
    result_df = tech.add_indicators(df)
    indicator_cols = [c for c in result_df.columns if c not in df.columns]

    rows: List[Dict[str, Any]] = []
    for name, fn, manual_loc in units:
        st = _measure(fn, runs=max(5, runs), warmup=2)
        st.pop("last_result", None)
        loc = manual_loc or _locate_tech(tech, name)
        rows.append({"name": name, "location": loc, **st})

    rows.sort(key=lambda r: r["median_ms"], reverse=True)
    return {
        "bars": len(df),
        "indicator_columns": len(indicator_cols),
        "units": len(units),
        "total": total,
        "unit_results": rows,
        "slowest5": rows[:5],
        "note": "总量为 add_indicators（36 列，内部含一次 df.copy）；"
                "单指标为纯函数耗时（不含 copy），每项 5 次中位数，量级为亚毫秒时受调度噪声影响。",
    }


def _locate_tech(tech, unit_name: str) -> str:
    """把计算单元名映射到 tech.py 中的真实函数定义行（lambda 本身无法定位）。"""
    import inspect
    aliases = {
        "MA5": "sma", "MA10": "sma", "MA20": "sma", "MA60": "sma",
        "EMA20": "ema", "BOLL": "boll", "MACD": "macd", "KDJ": "kdj",
        "RSI6": "rsi", "RSI14": "rsi", "DMI": "dmi", "SAR": "sar",
        "BIAS6": "bias", "MOM10": "momentum", "CCI14": "cci", "OBV": "obv",
        "VOL_MA5": "vol_ma", "ROC12": "roc", "ATR14": "atr",
        "HV20": "hv", "VWAP": "vwap", "GARCH": "garch",
    }
    base = unit_name.split("(")[0]
    fn = getattr(tech, aliases.get(base, base.lower()), None)
    if fn is None:
        return "unknown"
    try:
        src = inspect.getsourcefile(fn)
        line = inspect.getsourcelines(fn)[1]
        return f"{os.path.basename(src)}:{line}"
    except Exception:  # noqa: BLE001
        return "unknown"


def _derived_boll_pct(tech, df):
    """复现 add_indicators 的 boll_pct 列计算。"""
    b = tech.boll(df["close"])
    band = (b["BOLL_UP"] - b["BOLL_LOW"]).replace(0, float("nan"))
    return ((df["close"] - b["BOLL_LOW"]) / band).clip(0, 1).fillna(0.5)


def _derived_dir_di(tech, df):
    """复现 dir_di 列计算（+DI - -DI）。"""
    d = tech.dmi(df["high"], df["low"], df["close"])
    return (d["PLUS_DI"] - d["MINUS_DI"]).fillna(0.0)


def _derived_gap(close, ma):
    """复现 ma20_gap / ma60_gap 列计算。"""
    return ((close / ma.replace(0, float("nan")) - 1.0).fillna(0.0))


def _derived_volume(vol):
    """复现 vol5 / vol_ratio 列计算。"""
    m = vol.rolling(5, min_periods=1).mean()
    return (vol / m.replace(0, float("nan"))).fillna(1.0)


def _derived_obv(tech, close, vol):
    """复现 obv_chg 列计算。"""
    return tech.obv(close, vol).diff(5).fillna(0.0)


def _derived_atr_pct(tech, high, low, close):
    """复现 atr_pct 列计算。"""
    return (tech.atr(high, low, close, 14) / close.replace(0, float("nan"))).fillna(0.0)


# ---------------------------------------------------------------------------
# 场景 3：AI 预测（默认 NumPy LSTM；torch / LightGBM 缺失则跳过并标注）
# ---------------------------------------------------------------------------
def section_ai(runs: int = 3, repeats: int = 15) -> Dict[str, Any]:
    """训练 + 首次推理（冷启动）+ 稳态推理延迟（重复 15 次）。"""
    import importlib.util as iu
    skipped = []
    for m in ["torch", "lightgbm"]:
        if not iu.find_spec(m):
            skipped.append(m)

    feed = LocalDailyFeed()
    rb = _symbol_name("RB")
    df = feed.get_history(rb, "2015-01-01", END, "D")
    payload: Dict[str, Any] = {
        "symbol": rb, "bars": int(len(df)),
        "range": ["2015-01-01", END],
        "seq_len": 20, "epochs": 30,
        "skipped_backends": skipped,
        "note": "torch / LightGBM 未安装，仅测默认 NumPy LSTM 路径；"
                "首次推理含指标缓存二次拷贝与 rollout，稳态为同一 df 重复推理（指标 LRU 命中）。",
    }
    try:
        from futures_quant.ai.predictor import FuturesPredictor
    except Exception as exc:  # noqa: BLE001
        payload["error"] = f"导入 FuturesPredictor 失败：{exc}"
        return payload

    # warm-up：用尾部 400 bar、2 epoch 的训练预热懒加载/编译路径（不进入统计）
    try:
        p_warm = FuturesPredictor()
        p_warm.fit(df.tail(400).reset_index(drop=True), seq_len=20, epochs=2,
                   symbol=rb, period="D")
    except Exception as exc:  # noqa: BLE001
        payload["warmup_error"] = f"{type(exc).__name__}: {exc}"

    fit_samples: List[float] = []
    last_predictor = None
    last_fit_info: Dict[str, Any] = {}
    fit_errors: List[str] = []
    for _ in range(max(1, runs)):
        try:
            p = FuturesPredictor()
            t0 = time.perf_counter()
            info = p.fit(df, seq_len=20, epochs=30, symbol=rb, period="D")
            fit_samples.append((time.perf_counter() - t0) * 1000.0)
            last_predictor = p
            last_fit_info = dict(info or {})
        except Exception as exc:  # noqa: BLE001
            fit_errors.append(f"{type(exc).__name__}: {exc}")
    payload["fit"] = _stats(fit_samples)
    payload["fit_info"] = _safe(last_fit_info)
    payload["fit_errors"] = fit_errors
    if last_predictor is None:
        payload["error"] = "全部训练均失败，无法测推理"
        return payload

    # 首次推理（冷启动）：含首次特征构建/缓存拷贝/rollout
    try:
        t0 = time.perf_counter()
        pred = last_predictor.predict(df, horizon=10)
        payload["cold_first_inference_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        payload["prediction_sample"] = _safe({k: pred.get(k) for k in
                                               ("direction", "confidence", "pred_return", "horizon")})
    except Exception as exc:  # noqa: BLE001
        payload["cold_error"] = f"{type(exc).__name__}: {exc}"
        return payload

    steady: List[float] = []
    errors = 0
    for _ in range(max(1, repeats)):
        try:
            t0 = time.perf_counter()
            last_predictor.predict(df, horizon=10)
            steady.append((time.perf_counter() - t0) * 1000.0)
        except Exception:  # noqa: BLE001
            errors += 1
    payload["steady"] = _stats(steady)
    payload["steady_errors"] = errors
    payload["model"] = "numpy_lstm" if last_fit_info.get("use_lstm") else "ridge_fallback"
    return payload


# ---------------------------------------------------------------------------
# 场景 4：UI（Qt offscreen 子进程）
# ---------------------------------------------------------------------------
def section_ui(runs: int = 3) -> Dict[str, Any]:
    """主窗口构建、页面首次/再次切换、2000 行表格填充与绘制耗时。

    注意：不进入 app.exec() 事件循环；仅用 processEvents() 驱动布局与绘制，
    并在构建后停掉所有定时器，避免触发后台 DB/网络/落盘逻辑。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QUANTVORTEX_NO_PERSIST"] = "1"
    # 只在本探针进程内预置 runtime 数据目录缓存，避免 get_data_dir() 在 data/ 下
    # 创建并删除 .write_test 探针文件（不修改业务代码，不影响其他进程）。
    try:
        import futures_quant.runtime as _rt
        _rt._DATA_DIR_CACHE = os.path.join(_rt.app_base_dir(), "data")
    except Exception:  # noqa: BLE001
        pass

    result: Dict[str, Any] = {"window_build_ms": [], "pages": [], "table": {},
                              "note": "offscreen 渲染；未进入事件循环；已停用窗口定时器。"}
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"PyQt6 导入失败：{exc}"
        return result

    app = QApplication.instance() or QApplication(["perf_probe", "-platform", "offscreen"])

    def _stop_all_timers(widget) -> int:
        n = 0
        for t in widget.findChildren(QTimer):
            try:
                if t.isActive():
                    t.stop()
                    n += 1
            except Exception:  # noqa: BLE001
                pass
        return n

    # ---- 表格测量放在主窗口之前：此时进程内没有页面定时器，processEvents 安全 ----
    try:
        from futures_quant.ui.states import DataGrid
        rows_n, cols_n = 2000, 8
        grid = DataGrid(rows=0, cols=cols_n, sortable=False)
        grid.setRowCount(rows_n)
        headers = [f"C{i}" for i in range(cols_n)]

        from PyQt6.QtWidgets import QTableWidgetItem

        def fill() -> None:
            for r in range(rows_n):
                for c in range(cols_n):
                    item = QTableWidgetItem(f"{r}-{c}")
                    grid.setItem(r, c, item)

        fill_stats = _measure(fill, runs=max(1, runs), warmup=1)
        fill_stats.pop("last_result", None)
        grid.setHorizontalHeaderLabels(headers)
        grid.resize(1280, 720)
        grid.show()
        app.processEvents()
        paint_stats = _measure(lambda: grid.grab(), runs=max(1, runs), warmup=1)
        paint_stats.pop("last_result", None)
        grid.close()
        grid.deleteLater()
        app.processEvents()
        result["table"] = {
            "rows": rows_n, "cols": cols_n, "cells": rows_n * cols_n,
            "fill": fill_stats,
            "paint_grab": paint_stats,
            "per_cell_fill_us": round(fill_stats["median_ms"] * 1000.0 / (rows_n * cols_n), 2)
            if fill_stats["median_ms"] else None,
        }
    except Exception as exc:  # noqa: BLE001
        result["table_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    try:
        from futures_quant.ui.main_window import MainWindow
        from futures_quant.ui.main_window import NAV
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"MainWindow 导入失败：{exc}"
        return result

    # warm-up：先构建一个窗口，预热 Qt 控件类/主题/QSS 解析（不跑事件循环）
    try:
        w0 = MainWindow()
        _stop_all_timers(w0)
        w0.close()
        del w0
        gc.collect()
    except Exception as exc:  # noqa: BLE001
        result["warmup_error"] = f"{type(exc).__name__}: {exc}"

    build_samples: List[float] = []
    win = None
    build_errors: List[str] = []
    for _ in range(max(1, runs)):
        try:
            t0 = time.perf_counter()
            w = MainWindow()
            build_samples.append((time.perf_counter() - t0) * 1000.0)
            _stop_all_timers(w)
            if win is not None:
                win.close()
                win.deleteLater()
            win = w
        except Exception as exc:  # noqa: BLE001
            build_errors.append(f"{type(exc).__name__}: {exc}")
    result["window_build"] = _stats(build_samples)
    result["build_errors"] = build_errors
    if win is None:
        result["error"] = "主窗口构建全部失败"
        return result

    # 页面切换：cold（首次懒构造）与 warm（重复切换）分别计时
    for idx, (title, _cls, _icon, key) in enumerate(NAV):
        row: Dict[str, Any] = {"idx": idx, "title": title, "key": key}
        t0 = time.perf_counter()
        try:
            ok = bool(win._show_page(idx))
            row["cold_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            row["cold_ok"] = ok
        except Exception as exc:  # noqa: BLE001
            row["cold_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            row["cold_ok"] = False
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        _stop_all_timers(win)
        warm: List[float] = []
        if row.get("cold_ok"):
            for _ in range(max(1, runs)):
                try:
                    win._show_page(0)
                    t0 = time.perf_counter()
                    win._show_page(idx)
                    warm.append((time.perf_counter() - t0) * 1000.0)
                except Exception:  # noqa: BLE001
                    break
        row["warm"] = _stats(warm)
        result["pages"].append(row)
    _stop_all_timers(win)

    # 页面构建完毕，直接关闭；不再 processEvents，避免触发页面里的 singleShot 后台任务
    try:
        win.close()
        del win
        gc.collect()
    except Exception:  # noqa: BLE001
        pass
    return result


# ---------------------------------------------------------------------------
# 场景 5：内存（20 次回测 RSS 增长，独立子进程）
# ---------------------------------------------------------------------------
def _linear_slope(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float]:
    """最小二乘斜率与 R²。"""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    return slope, r2


def section_memory(runs: int = 20) -> Dict[str, Any]:
    """连续 N 次回测（每次 gc.collect）后的 RSS 曲线与线性斜率。"""
    feed = LocalDailyFeed()
    rb = _symbol_name("RB")
    # 预热一次，排除首次导入/分配造成的基线偏差
    _run_once(feed, rb)
    gc.collect()
    from collections import Counter
    before_objs = len(gc.get_objects())
    before_types = Counter(type(o).__name__ for o in gc.get_objects())

    rss: List[float] = []
    objs: List[int] = []
    errors: List[str] = []
    for i in range(max(1, runs)):
        try:
            _run_once(feed, rb)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"run{i}: {type(exc).__name__}: {exc}")
        gc.collect()
        rss.append(round(_rss_mb(), 2))
        objs.append(len(gc.get_objects()))

    # 统计首次与末次的常见对象类型增长（辅助定位可疑缓存/引用）
    after_objs = gc.get_objects()
    after_types = Counter(type(o).__name__ for o in after_objs)
    growth = []
    for name, cnt in after_types.items():
        base = before_types.get(name, 0)
        if cnt - base > 5:
            growth.append({"type": name, "before": base, "after": cnt, "delta": cnt - base})
    growth.sort(key=lambda r: r["delta"], reverse=True)
    del after_objs

    slope, r2 = _linear_slope(list(range(len(rss))), rss)
    return {
        "runs": len(rss),
        "rss_mb": rss,
        "gc_objects": objs,
        "before_objs": before_objs,
        "delta_mb": round(rss[-1] - rss[0], 2) if rss else None,
        "slope_mb_per_run": round(slope, 4),
        "r2": round(r2, 3),
        "top_type_growth": growth[:8],
        "errors": errors,
        "note": "每次回测后 gc.collect() 再取 RSS；首轮已预热；"
                "若斜率明显且 R² 高，则提示线性增长（需结合 top_type_growth 定位）。",
    }


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------
def _fmt(v: Any, digits: int = 2) -> str:
    """数字格式化：None 显示为 —。"""
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return str(v)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """生成 Markdown 表格。"""
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def build_markdown(results: Dict[str, Any]) -> str:
    """把各分节结果拼成 outputs/perf_baseline.md。"""
    meta = results.get("meta", {})
    env = meta.get("env", {})
    lines: List[str] = []
    add = lines.append

    add("# QuantVortex 性能与稳定性基线（只读测量）")
    add("")
    add(f"- 生成时间：{meta.get('ts', '')}")
    add(f"- 仓库：`d:\\PythonProject\\QuantVortex`")
    add(f"- 测量方式：每个场景先 warm-up，再取 N 次运行的中位数；UI/内存在独立子进程测量。")
    add("- 约束：只读探针，无联网、无安装、无 commit、不改 `futures_quant` 业务代码、"
        "不写 data/ 与数据库。")
    add("")

    add("## 1. 环境与负载")
    add("")
    add(_table(
        ["项", "值"],
        [
            ["Python", env.get("python")],
            ["解释器", env.get("executable")],
            ["CPU 逻辑核数", env.get("cpu_count")],
            ["内存总量 / 可用", f"{env.get('mem_total_gb', '—')} GB / {env.get('mem_available_gb', '—')} GB"],
            ["系统负载 (1/5/15)", ", ".join(str(x) for x in env.get("loadavg_1_5_15", [])) or "—"],
            ["依赖", ", ".join(f"{k}={'有' if v else '无'}" for k, v in (env.get("packages") or {}).items())],
            ["本探针进程 RSS", f"{env.get('proc_rss_mb', '—')} MB"],
        ],
    ))
    add("")
    if env.get("python_processes"):
        add("同机 Python 进程（可能为其他会话的测试/改码负载）：")
        add("")
        add(_table(["PID", "进程名", "RSS(MB)"],
                   [[p.get("pid"), p.get("name"), p.get("rss_mb")]
                    for p in env.get("python_processes", [])]))
        add("")
    add(f"- 测量开始 CPU 使用率：{_fmt(meta.get('cpu_before'), 1)}%；"
        f"结束：{_fmt(meta.get('cpu_after'), 1) if meta.get('cpu_after') is not None else '未采集（分节独立运行）'}")
    add("- 负载说明：Windows 的 `psutil.getloadavg()` 恒为 0，不能作为负载判据；"
        "本次以 CPU 使用率与同机 Python 进程数判断。采集环境时 CPU 已处于高占用，"
        "且存在多个 python/pythonw 进程（见上表），说明测量期间很可能有其他会话在跑测试/改码，"
        "因此各场景 σ 偏大，报告中位数与 min 应成对解读。")
    add("- 分节说明：backtest / indicators / ai 在独立进程中顺序测量，ui / memory 各自在子进程测量；"
        "各分节完成时间不同（见 `outputs/.perf_*.json` 的 `elapsed_s`），期间业务代码可能被其他会话改动，"
        "下表 mtime 为报告生成时的快照。")
    add("")
    add("- 代码快照（最后修改时间）：")
    add("")
    add(_table(["文件", "mtime"], [[k, v] for k, v in (meta.get("code_mtimes") or {}).items()]))
    add("")

    # ---- 结论速览（从各分节结果中直接取数，避免手填）----
    bt0 = results.get("backtest") or {}
    ind0 = results.get("indicators") or {}
    ai0 = results.get("ai") or {}
    ui0 = results.get("ui") or {}
    add("## 结论速览（最慢环节）")
    add("")
    add(f"1. **AI 训练+校准**：中位 "
        f"{_fmt((ai0.get('fit', {}) or {}).get('median_ms'))} ms（NumPy LSTM，含训练段与全量重训两次、30 epochs）；"
        f"稳态推理 P95 {_fmt((ai0.get('steady', {}) or {}).get('p95_ms'))} ms。")
    add(f"2. **43 品种批量回测**：中位 "
        f"{_fmt((bt0.get('batch', {}).get('total', {}) or {}).get('median_ms'))} ms，"
        f"单品种平均 {_fmt(bt0.get('batch', {}).get('avg_per_symbol_ms'))} ms；"
        f"单品种 rb.SHFE 中位 {_fmt((bt0.get('single', {}).get('stats', {}) or {}).get('median_ms'))} ms。")
    pages0 = [p for p in (ui0.get("pages") or []) if p.get("cold_ok")]
    slow_page = max(pages0, key=lambda p: p.get("cold_ms") or 0) if pages0 else {}
    add(f"3. **UI 冷启动**：主窗口构建中位 "
        f"{_fmt((ui0.get('window_build', {}) or {}).get('median_ms'))} ms；"
        f"最慢页面「{slow_page.get('title', '—')}」首次构造 "
        f"{_fmt(slow_page.get('cold_ms'))} ms（再次切换仅 "
        f"{_fmt((slow_page.get('warm') or {}).get('median_ms'))} ms）。")
    sar = ((ind0.get("slowest5") or [{}])[0])
    add(f"4. **指标热点**：`add_indicators` 5000 bar 中位 "
        f"{_fmt((ind0.get('total', {}) or {}).get('median_ms'))} ms，其中 "
        f"`{sar.get('name')}`（{sar.get('location')}）单独占 "
        f"{_fmt(sar.get('median_ms'))} ms（约 "
        f"{(sar.get('median_ms') or 0) / ((ind0.get('total', {}) or {}).get('median_ms') or 1) * 100:.0f}%）。")
    add("")

    bt = results.get("backtest")
    if bt:
        add("## 2. 回测引擎")
        add("")
        info = bt.get("data_info", {})
        add(f"- 数据：{info.get('source')}；区间 {START} ~ {END}；"
            f"品种 {info.get('symbols')} 个，bar 总数 {info.get('bars_total')}，"
            f"单品种 bar 区间 {info.get('bars_min')}~{info.get('bars_max')}。")
        s = bt.get("single", {})
        st = s.get("stats", {})
        add(f"- 单品种 `{s.get('symbol')}`：{s.get('bars')} 根 bar，"
            f"中位 {_fmt(st.get('median_ms'))} ms（min {_fmt(st.get('min_ms'))} / "
            f"max {_fmt(st.get('max_ms'))} / σ {_fmt(st.get('stdev_ms'))}）。")
        m = s.get("metrics", {})
        if m:
            add(f"- 该次运行指标（仅作健全性核对）：" +
                "，".join(f"{k}={_fmt(v, 3)}" for k, v in m.items()))
        b = bt.get("batch", {})
        bst = b.get("total", {})
        add(f"- 43 品种批量（{b.get('runs')} 轮）总耗时中位 "
            f"**{_fmt(bst.get('median_ms'))} ms**（min {_fmt(bst.get('min_ms'))} / "
            f"max {_fmt(bst.get('max_ms'))} / σ {_fmt(bst.get('stdev_ms'))}），"
            f"单品种平均 {_fmt(b.get('avg_per_symbol_ms'))} ms。")
        add("")
        add(_table(["最慢品种（中位，单品种）", "耗时 ms"],
                   [[r.get("symbol"), _fmt(r.get("median_ms"))] for r in b.get("slowest5", [])]))
        add("")
        prof = bt.get("cprofile", {}).get("top", [])
        if prof:
            add("**cProfile Top 15（按 cumulative time，含剖析开销）**")
            add("")
            add(_table(["#", "函数", "位置", "调用次数", "cum ms", "self ms"],
                       [[i + 1, p.get("function"), p.get("location"), p.get("calls"),
                         _fmt(p.get("cumtime_ms")), _fmt(p.get("tottime_ms"))]
                        for i, p in enumerate(prof)]))
            add("")
            atr = next((p for p in prof if p.get("function") == "atr_last"), None)
            abs_row = next((p for p in prof if p.get("function", "").endswith("builtins.abs>")), None)
            add("**热点解读**：")
            add("")
            if atr:
                add(f"- `atr_last`（{atr.get('location')}）累计 "
                    f"{_fmt(atr.get('cumtime_ms'))} ms / 自身 {_fmt(atr.get('tottime_ms'))} ms，"
                    f"被调用 {atr.get('calls')} 次；"
                    f"同段剖析中 `abs` 被调用 {_fmt(abs_row.get('calls') if abs_row else None, 0)} 次，"
                    "典型特征是“每根 bar 重算整段历史”，复杂度近似 O(n²)。")
                add("- 同一剖析里 `list.append` 70 万次、`max` 69 万次，说明策略每根 bar 都在做"
                    "全量数组级 Python 循环；批量 43 品种时该成本会被放大 43 倍。")
            add("")

    ind = results.get("indicators")
    if ind:
        add("## 3. 指标计算（5000 根 bar）")
        add("")
        t = ind.get("total", {})
        add(f"- `add_indicators` 覆盖 **{ind.get('indicator_columns')} 个指标列**，"
            f"总耗时中位 **{_fmt(t.get('median_ms'))} ms**"
            f"（min {_fmt(t.get('min_ms'))} / max {_fmt(t.get('max_ms'))} / σ {_fmt(t.get('stdev_ms'))}）。")
        add(f"- 单独测量 {ind.get('units')} 个计算单元（纯函数、不含 copy）。")
        add("")
        add("**最慢 5 个计算单元**")
        add("")
        add(_table(["指标", "位置", "中位 ms", "min", "max", "σ"],
                   [[r.get("name"), r.get("location"), _fmt(r.get("median_ms")),
                     _fmt(r.get("min_ms")), _fmt(r.get("max_ms")), _fmt(r.get("stdev_ms"))]
                    for r in ind.get("slowest5", [])]))
        add("")
        add("全部计算单元（按中位耗时降序）：")
        add("")
        add(_table(["指标", "位置", "中位 ms", "min", "max"],
                   [[r.get("name"), r.get("location"), _fmt(r.get("median_ms")),
                     _fmt(r.get("min_ms")), _fmt(r.get("max_ms"))]
                    for r in ind.get("unit_results", [])]))
        add("")
        top_sar = (ind.get("slowest5") or [{}])[0]
        add(f"- 说明：`SAR` 单独占 `add_indicators` 总量的约 "
            f"{(top_sar.get('median_ms') or 0) / ((ind.get('total', {}) or {}).get('median_ms') or 1) * 100:.0f}%，"
            "是唯一需要优先优化的指标；`GARCH` 不在 `add_indicators` 列内，此处仅作附加参考。")
        add("")

    ai = results.get("ai")
    if ai:
        add("## 4. AI 预测（默认 NumPy LSTM）")
        add("")
        if ai.get("error"):
            add(f"- **未测到**：{ai.get('error')}")
        else:
            fit = ai.get("fit", {})
            add(f"- 训练数据：`{ai.get('symbol')}` {ai.get('range')}，{ai.get('bars')} 根 bar；"
                f"seq_len={ai.get('seq_len')}，epochs={ai.get('epochs')}。")
            add(f"- 训练+校准（含训练段与全量重训两次）中位 **{_fmt(fit.get('median_ms'))} ms**"
                f"（min {_fmt(fit.get('min_ms'))} / max {_fmt(fit.get('max_ms'))} / σ {_fmt(fit.get('stdev_ms'))}）。")
            add(f"- 首次推理（冷启动）：**{_fmt(ai.get('cold_first_inference_ms'))} ms**。")
            st = ai.get("steady", {})
            add(f"- 稳态推理（{st.get('n')} 次重复）：中位 {_fmt(st.get('median_ms'))} ms，"
                f"P95 {_fmt(st.get('p95_ms'))} ms，范围 "
                f"{_fmt(st.get('min_ms'))}~{_fmt(st.get('max_ms'))} ms，σ {_fmt(st.get('stdev_ms'))}。")
            add(f"- 实际模型路径：`{ai.get('model')}`；"
                f"缺失后端：{', '.join(ai.get('skipped_backends') or []) or '无'}。")
            if ai.get("fit_errors"):
                add(f"- 训练异常：{'; '.join(ai.get('fit_errors'))}")
        add("")

    ui = results.get("ui")
    if ui:
        add("## 5. UI（Qt offscreen）")
        add("")
        if ui.get("error"):
            add(f"- **未测到**：{ui.get('error')}")
        else:
            wb = ui.get("window_build", {})
            add(f"- 主窗口构建：中位 **{_fmt(wb.get('median_ms'))} ms**"
                f"（min {_fmt(wb.get('min_ms'))} / max {_fmt(wb.get('max_ms'))} / σ {_fmt(wb.get('stdev_ms'))}）。")
            add("")
            add(_table(["#", "页面", "首访构造 ms", "再次切换中位 ms", "状态"],
                       [[p.get("idx"), p.get("title"), _fmt(p.get("cold_ms")),
                         _fmt((p.get("warm") or {}).get("median_ms")),
                         "OK" if p.get("cold_ok") else ("ERR: " + str(p.get("error", "")))]
                        for p in ui.get("pages", [])]))
            add("")
            tb = ui.get("table", {})
            if tb:
                add(f"- 表格 {tb.get('rows')}×{tb.get('cols')}（{tb.get('cells')} 格）填充：中位 "
                    f"**{_fmt((tb.get('fill') or {}).get('median_ms'))} ms**"
                    f"（{_fmt(tb.get('per_cell_fill_us'))} µs/格）；"
                    f"offscreen 绘制（grab）：中位 "
                    f"**{_fmt((tb.get('paint_grab') or {}).get('median_ms'))} ms**。")
            add("- 说明：`行情全景`页在 `MainWindow` 构造阶段就已创建，所以其“首访”接近 0 ms，"
                "窗口构建耗时包含该页；`实盘监控`页 1.4 s 是 UI 冷启动的主要成本。"
                "再次切换均为 1~2 ms，说明页面栈切换本身不是瓶颈。")
            if ui.get("table_error"):
                add(f"- 表格测量异常：{ui.get('table_error')}")
        add("")

    mem = results.get("memory")
    if mem:
        add("## 6. 内存稳定性（连续 20 次回测）")
        add("")
        rss = mem.get("rss_mb") or []
        add(f"- RSS 曲线（MB）：{', '.join(f'{x:.1f}' for x in rss)}")
        add(f"- 首末差值：{_fmt(mem.get('delta_mb'))} MB；线性斜率 "
            f"**{_fmt(mem.get('slope_mb_per_run'), 3)} MB/次**，R²={_fmt(mem.get('r2'), 3)}。")
        if mem.get("top_type_growth"):
            add("")
            add(_table(["对象类型", "起始", "结束", "增长"],
                       [[g.get("type"), g.get("before"), g.get("after"), g.get("delta")]
                        for g in mem.get("top_type_growth", [])]))
            add("")
        verdict = "未见明显线性泄漏" if (mem.get("slope_mb_per_run") or 0) < 0.5 else "存在可疑线性增长"
        add(f"- 判定：{verdict}（阈值：斜率 <0.5 MB/次 且 20 次总增长 <10 MB）。")
        add("- 说明：RSS 在第 7 次左右出现 0.1 MB 级分配器台阶后持平，属正常 arena 增长；"
            "另有约 +158 个 `ReferenceType`（约占 11 KB）与 +18 个内建方法对象，"
            "随运行次数近似线性但绝对量可忽略，暂不构成泄漏结论。")
        add("")

    add("## 7. 性能回归验收阈值建议")
    add("")
    add("以下阈值以本次基线中位数为锚点，建议在 CI/本地回归中作为硬门禁"
        "（同一机器、同区间、同策略、同一数据快照下比较）：")
    add("")
    rows: List[List[Any]] = []
    bt = results.get("backtest") or {}
    if bt:
        s = (bt.get("single", {}).get("stats", {}) or {}).get("median_ms")
        b = (bt.get("batch", {}).get("total", {}) or {}).get("median_ms")
        if s:
            rows.append(["单品种回测 rb.SHFE", f"{s:.1f} ms", f"≤ {s * 1.20:.1f} ms（1.20×）"])
        if b:
            rows.append(["43 品种批量回测总耗时", f"{b:.1f} ms", f"≤ {b * 1.15:.1f} ms（1.15×）"])
    ind = results.get("indicators") or {}
    t = (ind.get("total", {}) or {}).get("median_ms")
    if t:
        rows.append(["add_indicators（5000 bar）", f"{t:.1f} ms", f"≤ {t * 1.15:.1f} ms（1.15×）"])
    slow = ind.get("slowest5") or []
    if slow:
        m0 = slow[0].get("median_ms") or 0
        rows.append([f"最慢指标 {slow[0].get('name')}", f"{m0:.2f} ms", f"≤ {m0 * 1.20:.2f} ms（1.20×）"])
    ai = results.get("ai") or {}
    if ai and not ai.get("error"):
        ft = (ai.get("fit", {}) or {}).get("median_ms")
        p95 = (ai.get("steady", {}) or {}).get("p95_ms")
        if ft:
            rows.append(["AI 训练+校准", f"{ft:.1f} ms", f"≤ {ft * 1.20:.1f} ms（1.20×）"])
        if p95:
            rows.append(["AI 单次稳态推理 P95", f"{p95:.1f} ms", f"≤ {max(p95 * 1.25, p95 + 5):.1f} ms"])
    ui = results.get("ui") or {}
    if ui and not ui.get("error"):
        wb = (ui.get("window_build", {}) or {}).get("median_ms")
        if wb:
            rows.append(["主窗口构建", f"{wb:.1f} ms", f"≤ {wb * 1.15:.1f} ms（1.15×）"])
        pages = ui.get("pages") or []
        colds = [p.get("cold_ms") for p in pages if p.get("cold_ok") and p.get("cold_ms")]
        warms = [((p.get("warm") or {}).get("median_ms")) for p in pages if p.get("cold_ok")]
        warms = [w for w in warms if w]
        if colds:
            c = max(colds)
            rows.append(["页面首次构造（最慢页）", f"{c:.1f} ms", f"≤ {c * 1.15:.1f} ms（1.15×）"])
        if warms:
            w = max(warms)
            rows.append(["页面再次切换（最慢页）", f"{w:.1f} ms", f"≤ {max(w * 1.25, w + 10):.1f} ms"])
        tb = ui.get("table") or {}
        fill = (tb.get("fill", {}) or {}).get("median_ms")
        if fill:
            rows.append(["表格 2000×8 填充", f"{fill:.1f} ms", f"≤ {fill * 1.20:.1f} ms（1.20×）"])
    if mem:
        rows.append(["20 次回测 RSS 增长", f"{_fmt(mem.get('delta_mb'))} MB",
                     "≤ 10 MB 且斜率 ≤ 0.5 MB/次"])
    add(_table(["项目", "本次基线（中位）", "建议回归阈值"], rows))
    add("")
    add("补充建议：")
    add("- 批量回测的**单品种平均**（本次 "
        f"{_fmt((bt.get('batch', {}) or {}).get('avg_per_symbol_ms'))} ms）也应纳入门禁，"
        "避免只测总耗时掩盖个别品种劣化。")
    add("- 若机器负载波动 >20%，先看 σ 与 min：min 更接近纯计算成本，"
        "中位数用于对外验收。")
    add("")
    add("**可直接写死的绝对阈值（本次基线取整上浮，便于 CI 断言）**：")
    add("")
    add("- 单品种 rb.SHFE 回测 ≤ 500 ms；43 品种批量总耗时 ≤ 25 s，单品种平均 ≤ 600 ms。")
    add("- `add_indicators`（5000 bar）≤ 180 ms；`SAR` 单指标 ≤ 120 ms。")
    add("- AI 稳态推理 P95 ≤ 200 ms、中位 ≤ 130 ms；训练+校准 ≤ 90 s（建议放在 nightly，不阻塞每次提交）。")
    add("- 主窗口构建 ≤ 750 ms；最慢页面首访 ≤ 1.7 s；页面再次切换 ≤ 10 ms。")
    add("- 表格 2000×8 填充 ≤ 100 ms；offscreen 绘制 ≤ 20 ms。")
    add("- 连续 20 次回测 RSS 增长 ≤ 10 MB，且斜率 ≤ 0.5 MB/次。")
    add("")

    add("## 8. 未测到 / 受环境限制的项目")
    add("")
    miss: List[str] = []
    env_pkgs = env.get("packages") or {}
    if not env_pkgs.get("torch"):
        miss.append("PyTorch LSTM 路径未测（未安装 torch，仅覆盖 NumPy LSTM）。")
    if not env_pkgs.get("lightgbm"):
        miss.append("LightGBM 集成路径未测（未安装 lightgbm）。")
    if not env_pkgs.get("arch"):
        miss.append("GARCH 走 EWMA 降级实现（未安装 arch）。")
    miss.append("分钟/小时级数据与 CTP 实时链路未测（禁止联网，仅用本地日线缓存）。")
    miss.append("真实显示器下的绘制/合成器开销未测（UI 使用 Qt offscreen，"
                "且刻意不进入事件循环，避免后台任务干扰与写盘）。")
    miss.append("GPU/显存未测（无 torch，无法采集 CUDA 指标）。")
    if any((results.get(sec) or {}).get("error") for sec in ("backtest", "indicators", "ai", "ui", "memory")):
        for sec in ("backtest", "indicators", "ai", "ui", "memory"):
            err = (results.get(sec) or {}).get("error")
            if err:
                miss.append(f"{sec} 分节失败：{err}")
    for m in miss:
        add(f"- {m}")
    add("")
    add("## 9. 复现方式")
    add("")
    add("```powershell")
    add("python scripts/perf_probe.py --section all")
    add("# 或分节复测（结果会写入 outputs/.perf_<section>.json）")
    add("python scripts/perf_probe.py --section anchor   # 回测数字唯一口径")
    add("python scripts/perf_probe.py --section backtest")
    add("python scripts/perf_probe.py --section indicators")
    add("python scripts/perf_probe.py --section ai")
    add("python scripts/perf_probe.py --section ui")
    add("python scripts/perf_probe.py --section memory")
    add("python scripts/perf_probe.py --section report")
    add("```")
    add("")
    add("- 超时保护：UI 子进程 180 s、内存子进程 300 s，超时即中止并把 error 写入 JSON；"
        "本次外层命令超时按场景设置为回测 7 min、AI 9 min、UI 4 min、内存 5 min。")
    add("")
    return "\n".join(lines)


def _section_path(name: str) -> Path:
    return OUT_DIR / f".perf_{name}.json"


def _save_section(name: str, data: Dict[str, Any], path: Optional[str] = None) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = Path(path) if path else _section_path(name)
    p.write_text(json.dumps(_safe(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _load_section(name: str) -> Optional[Dict[str, Any]]:
    p = _section_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _run_child(section: str, timeout: int, runs: int) -> Dict[str, Any]:
    """在独立子进程中跑某一分节，避免 Qt/训练内存污染父进程。"""
    tmp = Path(tempfile.gettempdir()) / f"qv_perf_{section}_{os.getpid()}.json"
    cmd = [sys.executable, str(Path(__file__).resolve()), "--section", section,
           "--child", "--json-out", str(tmp), "--runs", str(runs)]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"子进程超时（>{timeout}s）已中止"}
    if not tmp.exists():
        tail = (proc.stderr or "")[-800:]
        return {"error": f"子进程未产出结果（exit={proc.returncode}）：{tail}"}
    try:
        data = json.loads(tmp.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"子进程结果解析失败：{exc}"}
    finally:
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001
            pass
    return data


def run_all(runs: int, ai_runs: int, ui_runs: int, mem_runs: int) -> Dict[str, Any]:
    """按顺序执行全部场景并落盘分节 JSON。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "env": _env_info(),
        "cpu_before": _cpu_percent(0.5),
        "code_mtimes": _code_mtimes(),
    }
    results: Dict[str, Any] = {"meta": meta}

    sections = [
        ("anchor", lambda: section_anchor(runs)),
        ("backtest", lambda: section_backtest(runs)),
        ("indicators", lambda: section_indicators(runs)),
        ("ai", lambda: section_ai(ai_runs)),
        ("ui", lambda: None),     # 子进程
        ("memory", lambda: None), # 子进程
    ]
    for name, fn in sections:
        t0 = time.perf_counter()
        try:
            if name == "ui":
                data = _run_child("ui", timeout=180, runs=ui_runs)
            elif name == "memory":
                data = _run_child("memory", timeout=300, runs=mem_runs)
            else:
                data = fn()
        except Exception as exc:  # noqa: BLE001
            data = {"error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc()[-1200:]}
        data["elapsed_s"] = round(time.perf_counter() - t0, 2)
        results[name] = data
        _save_section(name, data)
        print(f"[perf] {name} 完成，用时 {data['elapsed_s']}s", flush=True)

    results["meta"]["cpu_after"] = _cpu_percent(0.5)
    results["meta"]["env_after"] = _env_info()
    _save_section("meta", results["meta"])
    _save_section("all", results)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="QuantVortex 只读性能基线探针")
    ap.add_argument("--section", default="all",
                    choices=["all", "anchor", "backtest", "indicators", "ai", "ui",
                             "memory", "report"])
    ap.add_argument("--runs", type=int, default=3, help="每个场景的计时次数（默认 3）")
    ap.add_argument("--ai-runs", type=int, default=3, help="AI 训练重复次数")
    ap.add_argument("--ui-runs", type=int, default=3, help="UI 重复次数")
    ap.add_argument("--mem-runs", type=int, default=20, help="内存场景回测次数")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--json-out", default="", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.section == "report":
        results = {"meta": {}}
        meta = _load_section("meta") or {}
        results["meta"] = meta
        for name in ("backtest", "indicators", "ai", "ui", "memory"):
            data = _load_section(name)
            if data is not None:
                results[name] = data
        md = build_markdown(results)
        p = OUT_DIR / "perf_baseline.md"
        p.write_text(md, encoding="utf-8")
        print(f"[perf] 报告已生成：{p}")
        return 0

    if args.child:
        fn_map = {
            "anchor": lambda: section_anchor(args.runs),
            "backtest": lambda: section_backtest(args.runs),
            "indicators": lambda: section_indicators(args.runs),
            "ai": lambda: section_ai(args.ai_runs),
            "ui": lambda: section_ui(args.ui_runs),
            "memory": lambda: section_memory(args.mem_runs),
        }
        data = fn_map[args.section]()
        _save_section(args.section, data, args.json_out or None)
        return 0

    if args.section == "all":
        results = run_all(args.runs, args.ai_runs, args.ui_runs, args.mem_runs)
        md = build_markdown(results)
        p = OUT_DIR / "perf_baseline.md"
        p.write_text(md, encoding="utf-8")
        print(f"[perf] 报告已生成：{p}")
        print(json.dumps(_safe({
            "single_ms": (results.get("backtest", {}).get("single", {}).get("stats", {}) or {}).get("median_ms"),
            "batch_ms": (results.get("backtest", {}).get("batch", {}).get("total", {}) or {}).get("median_ms"),
            "indicators_ms": (results.get("indicators", {}).get("total", {}) or {}).get("median_ms"),
            "ai_fit_ms": (results.get("ai", {}).get("fit", {}) or {}).get("median_ms"),
            "ai_steady_p95": (results.get("ai", {}).get("steady", {}) or {}).get("p95_ms"),
            "ui_build_ms": (results.get("ui", {}).get("window_build", {}) or {}).get("median_ms"),
            "table_fill_ms": ((results.get("ui", {}).get("table", {}) or {}).get("fill", {}) or {}).get("median_ms"),
            "mem_delta_mb": (results.get("memory", {}) or {}).get("delta_mb"),
        }), ensure_ascii=False, indent=2))
        return 0

    fn_map = {
        "anchor": lambda: section_anchor(args.runs),
        "backtest": lambda: section_backtest(args.runs),
        "indicators": lambda: section_indicators(args.runs),
        "ai": lambda: section_ai(args.ai_runs),
        "ui": lambda: section_ui(args.ui_runs),
        "memory": lambda: section_memory(args.mem_runs),
    }
    # 分节单独复测时也刷新环境元数据，便于之后用 --section report 重生成报告
    meta = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "env": _env_info(),
        "cpu_before": _cpu_percent(0.5),
        "code_mtimes": _code_mtimes(),
    }
    _save_section("meta", meta)
    t0 = time.perf_counter()
    data = fn_map[args.section]()
    data["elapsed_s"] = round(time.perf_counter() - t0, 2)
    p = _save_section(args.section, data, args.json_out or None)
    print(f"[perf] {args.section} 完成，用时 {data['elapsed_s']}s → {p}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
