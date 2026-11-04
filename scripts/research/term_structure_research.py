"""第四轮第 2 步：期限结构特征 + 横截面 rank IC 评估（严格样本外）。

前置结论（第 1 步探针）
-----------------------
新浪 `futures_zh_daily_sina` 可稳定返回单合约日线（含结算价/成交量/持仓量），
已到期合约同样可取；单合约生命周期约 250 个交易日，因此拼 3 年近月序列必须
批量抓取多个月份合约。本脚本按品种标准合约月循环抓取所需合约并缓存到
`scripts/research/output/phase4_contract_data/`，重跑时命中缓存不再联网。

有界约束
--------
- 3 个品种（rb / i / cu），按各自标准合约月循环抓取 2023-12 ~ 2027-01 到期合约；
- 串行请求，单请求超时 20s，本次联网硬上限 180s；超限即停止并如实记录缺口，
  重跑可续抓（缓存命中不重复下载）；
- 不装包、不改 data/ 既有文件、不 commit。

实验口径
--------
- 特征（全部因果，同日收盘即可知）：
  近月-次近月价差 spread_pct、年化 carry、曲线斜率符号、carry 变化、carry 的
  滚动 z 值、近月剩余到期天数、近月持仓占比、主力-近月价差（无现货，作基差代理）、
  跨品种价差（rb-hc / i-j / cu-al，用本地主力连续）、20 日波动。
- 标签：主力连续未来 1/3/5/10 日收益（收益取主力连续，避免近月换月跳跃污染标签）。
- 切分：train 2023-01-01~2024-06-30 / validation 2024-07-01~2025-06-30 /
  test 2025-07-01~2026-11-03；标准化/缺失填充只在 train 拟合，alpha 只在 val 选。
- 评估：`futures_quant.ai.evaluation`（net_performance 毛/净夏普、回撤、换手、
  estimate_cost_rate 手续费+1 tick 滑点）；横截面 rank IC 与 IC 衰减（1/3/5/10）。
- 因果自检：扰动未来 bar 后，历史特征必须逐值不变。

用法
----
    python scripts/research/term_structure_research.py
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import threading
import time
import warnings
from concurrent.futures import TimeoutError as FutTimeout

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings("ignore")

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.ai.evaluation import (  # noqa: E402
    estimate_cost_rate,
    net_performance,
    positions_from_signals,
)
from futures_quant.data.contract_specs import get_contract_spec  # noqa: E402

SEED = 20261104
TRAIN_START = pd.Timestamp("2023-01-01")
TRAIN_END = pd.Timestamp("2024-06-30")
VAL_START = pd.Timestamp("2024-07-01")
VAL_END = pd.Timestamp("2025-06-30")
TEST_START = pd.Timestamp("2025-07-01")
TEST_END = pd.Timestamp("2026-11-03")

CACHE_DIR = os.path.join(_PROJ_ROOT, "data", "sina_cache")
OUT_DIR = os.path.join(_PROJ_ROOT, "scripts", "research", "output")
CONTRACT_DIR = os.path.join(OUT_DIR, "phase4_contract_data")
OUT_JSON = os.path.join(OUT_DIR, "phase4_term_structure_results.json")

REQ_TIMEOUT = 20.0
FETCH_BUDGET = 180.0

# 品种 -> (标准合约月循环, 板块, 跨品种伙伴代码)
SYMBOLS = {
    "rb": {"cycle": [1, 5, 10], "category": "黑色系", "partner": "hc"},
    "i": {"cycle": [1, 5, 9], "category": "黑色系", "partner": "j"},
    "cu": {"cycle": list(range(1, 13)), "category": "有色金属", "partner": "al"},
}

# 需要覆盖的到期月份（近月序列从 2023-01 起，延伸到 2027-01 是为了取到 2026-11 的近月）
EXPIRY_FIRST = (2023, 12)
EXPIRY_LAST = (2027, 1)

TERM_FEATURES = [
    "spread_pct", "carry_ann", "slope", "carry_chg5", "carry_z",
    "dte_near", "near_oi_share", "gap_main_near",
    "pair_spread", "pair_mom5", "vol20",
]

# 近月流动性过滤档位：none=原有口径；loose=日成交量≥1000 手或持仓≥1万手；
# strict=日成交量≥2000 手且持仓≥2万手。门槛越严，越能避免 i 那种「近月只有 60 手」的噪声。
LIQ_MODES: dict[str, dict | None] = {
    "none": None,
    "loose": {"volume": 1000, "oi": 10000, "logic": "or"},
    "strict": {"volume": 2000, "oi": 20000, "logic": "and"},
}


# ---------------------------------------------------------------------------
# 有界抓取
# ---------------------------------------------------------------------------
def _call(fn, *args, timeout: float = REQ_TIMEOUT, **kwargs):
    """守护线程内执行一次网络调用，超时抛 FutTimeout（避免不可控等待）。"""
    box: dict = {}

    def _run():
        try:
            box["value"] = fn(*args, **kwargs)
        except Exception as exc:
            box["error"] = exc

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise FutTimeout(f"{getattr(fn, '__name__', 'call')} 超时 >{timeout}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _needed_contracts(sym: str) -> list[str]:
    """按标准合约月循环生成需要抓取的合约代码（YYMM）。"""
    cycle = SYMBOLS[sym]["cycle"]
    out: list[str] = []
    y, m = EXPIRY_FIRST
    while (y, m) <= EXPIRY_LAST:
        if m in cycle:
            out.append(f"{sym.upper()}{str(y)[2:]}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _norm_daily(df: pd.DataFrame) -> pd.DataFrame:
    """统一新浪日线列名。"""
    ren = {"date": "datetime", "日期": "datetime", "open": "open", "开盘价": "open",
           "high": "high", "最高价": "high", "low": "low", "最低价": "low",
           "close": "close", "收盘价": "close", "volume": "volume", "成交量": "volume",
           "hold": "open_interest", "持仓量": "open_interest",
           "settle": "settle", "结算价": "settle", "动态结算价": "settle"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    keep = [c for c in ("datetime", "open", "high", "low", "close", "volume",
                        "open_interest", "settle") if c in df.columns]
    df = df[keep].copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)


def fetch_contracts() -> dict:
    """缓存优先抓取所需单合约日线；超时/失败如实记录。"""
    import akshare as ak

    os.makedirs(CONTRACT_DIR, exist_ok=True)
    start = time.time()
    report = {"fetched": [], "cached": [], "missing": [], "failed": [], "elapsed_sec": 0.0}
    for sym in SYMBOLS:
        for code in _needed_contracts(sym):
            path = os.path.join(CONTRACT_DIR, f"{code}.csv")
            if os.path.exists(path):
                report["cached"].append(code)
                continue
            if time.time() - start > FETCH_BUDGET:
                report["missing"].append({"contract": code, "error": "本次联网预算耗尽，重跑可续抓"})
                continue
            t0 = time.time()
            try:
                raw = _call(ak.futures_zh_daily_sina, symbol=code)
            except FutTimeout:
                report["failed"].append({"contract": code, "error": f"超时 >{REQ_TIMEOUT}s"})
                continue
            except Exception as exc:
                report["failed"].append({"contract": code, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if raw is None or len(raw) == 0:
                report["failed"].append({"contract": code, "error": "接口返回空表"})
                continue
            df = _norm_daily(raw)
            df.to_csv(path, index=False)
            report["fetched"].append({"contract": code, "rows": int(len(df)),
                                      "first": str(df["datetime"].iloc[0].date()),
                                      "last": str(df["datetime"].iloc[-1].date()),
                                      "sec": round(time.time() - t0, 2)})
    report["elapsed_sec"] = round(time.time() - start, 2)
    return report


# ---------------------------------------------------------------------------
# 特征构建（因果）
# ---------------------------------------------------------------------------
def _contract_frames(sym: str) -> dict[str, pd.DataFrame]:
    """读入该品种已缓存的合约日线。"""
    out: dict[str, pd.DataFrame] = {}
    if not os.path.isdir(CONTRACT_DIR):
        return out
    for name in sorted(os.listdir(CONTRACT_DIR)):
        if not name.lower().endswith(".csv"):
            continue
        code = os.path.splitext(name)[0]
        if not code.lower().startswith(sym):
            continue
        d = pd.read_csv(os.path.join(CONTRACT_DIR, name))
        if len(d) == 0:
            continue
        d["datetime"] = pd.to_datetime(d["datetime"])
        out[code] = d.sort_values("datetime").reset_index(drop=True)
    return out


def _read_main(code: str) -> pd.DataFrame:
    """读本地主力连续缓存。"""
    path = os.path.join(CACHE_DIR, f"{code}0.csv")
    d = pd.read_csv(path)
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.drop_duplicates("datetime").sort_values("datetime").set_index("datetime")
    for col in ("open", "high", "low", "close", "volume", "open_interest"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def _build_symbol_panel(sym: str, frames: dict[str, pd.DataFrame],
                        main: pd.DataFrame, partner: pd.DataFrame,
                        liq: str = "none", label_mode: str = "main") -> pd.DataFrame:
    """由合约日线拼出该品种的期限结构日频面板（只用当日及更早数据）。

    liq         : 近月流动性过滤档位（none / loose / strict）
    label_mode  : main=标签用本地主力连续；rolled=用近月链比例复权后的连续价格
    """
    if not frames:
        return pd.DataFrame()
    rows = []
    for code, d in frames.items():
        expiry = d["datetime"].max()
        tmp = pd.DataFrame({
            "datetime": d["datetime"],
            "contract": code,
            "close": d["close"],
            "oi": d.get("open_interest"),
            "volume": d.get("volume"),
        })
        tmp["expiry"] = expiry
        tmp["dte"] = (expiry - tmp["datetime"]).dt.days
        rows.append(tmp)
    allc = pd.concat(rows, ignore_index=True)

    # ---- 流动性过滤：避免把「只有几十手成交」的合约当作近月 ----
    cfg = LIQ_MODES.get(liq)
    if cfg:
        v = pd.to_numeric(allc["volume"], errors="coerce").fillna(0.0)
        o = pd.to_numeric(allc["oi"], errors="coerce").fillna(0.0)
        if cfg["logic"] == "or":
            allc = allc[(v >= cfg["volume"]) | (o >= cfg["oi"])]
        else:
            allc = allc[(v >= cfg["volume"]) & (o >= cfg["oi"])]
        allc = allc.copy()

    # 交割月内（剩余 <5 天）不参与「近月」，避免逼仓/流动性失真
    allc = allc[allc["dte"] >= 5].sort_values(["datetime", "dte"])
    allc["rk"] = allc.groupby("datetime").cumcount()
    near = allc[allc["rk"] == 0].set_index("datetime")
    nxt = allc[allc["rk"] == 1].set_index("datetime")

    panel = pd.DataFrame(index=near.index)
    panel["near_contract"] = near["contract"]
    panel["next_contract"] = nxt["contract"]
    panel["near_close"] = near["close"]
    panel["next_close"] = nxt["close"]
    panel["near_oi"] = near["oi"]
    panel["next_oi"] = nxt["oi"]
    panel["dte_near"] = near["dte"]
    panel["dte_next"] = nxt["dte"]

    # 价差 / 年化 carry / 曲线斜率
    panel["spread_pct"] = (panel["near_close"] - panel["next_close"]) / panel["next_close"]
    gap_days = (panel["dte_near"] - panel["dte_next"]).replace(0, np.nan)
    panel["carry_ann"] = panel["spread_pct"] * (365.0 / gap_days)
    panel["slope"] = np.sign(panel["spread_pct"])
    total_oi = (panel["near_oi"].fillna(0) + panel["next_oi"].fillna(0)).replace(0, np.nan)
    panel["near_oi_share"] = panel["near_oi"].fillna(0) / total_oi

    # 换月会带来价差水平跳变，carry 变化量在换月窗口内置空，避免假信号
    roll = panel["near_contract"] != panel["near_contract"].shift(1)
    roll_win = roll.rolling(5, min_periods=1).max().astype(bool)
    panel["carry_chg5"] = panel["carry_ann"].diff(5).where(~roll_win)
    # 滚动 z（只用过去 120 个交易日，含训练段），不做全样本标准化
    roll_mean = panel["carry_ann"].rolling(120, min_periods=40).mean()
    roll_std = panel["carry_ann"].rolling(120, min_periods=40).std()
    panel["carry_z"] = (panel["carry_ann"] - roll_mean) / roll_std.replace(0, np.nan)

    # 无现货数据：用主力连续对近月的溢价作为基差代理，报告中明确标注
    m = main.reindex(panel.index)
    panel["main_close"] = m["close"]
    panel["gap_main_near"] = panel["main_close"] / panel["near_close"] - 1

    # 跨品种价差（本地主力连续，同一天收盘）
    p = partner.reindex(panel.index)["close"]
    panel["pair_spread"] = m["close"] / p - 1
    panel["pair_mom5"] = panel["pair_spread"] - panel["pair_spread"].shift(5)

    # 波动与标签：main=本地主力连续；rolled=近月链比例复权（换月日按「新合约当日收盘/
    # 旧合约前日收盘」链接收益，等价于比例后复权，避免换月价格跳变污染 fwd 收益）
    if label_mode == "rolled":
        ret_near = panel["near_close"].pct_change(fill_method=None).fillna(0.0)
        base_close = (1.0 + ret_near).cumprod() * float(panel["near_close"].iloc[0])
    else:
        base_close = m["close"]
    panel["label_close"] = base_close
    r1 = base_close.pct_change(fill_method=None)
    panel["vol20"] = r1.rolling(20).std()
    for k in (1, 3, 5, 10):
        panel[f"fwd{k}"] = base_close.shift(-k) / base_close - 1
    panel["symbol"] = sym
    panel["category"] = SYMBOLS[sym]["category"]
    return panel.replace([np.inf, -np.inf], np.nan)


def _assemble(liq: str = "none", label_mode: str = "main") -> tuple[pd.DataFrame, dict, dict]:
    """组装三品种面板，返回 (panel, 覆盖信息, 抓取报告指纹)。"""
    parts, coverage = [], {}
    for sym in SYMBOLS:
        frames = _contract_frames(sym)
        main = _read_main(sym)
        partner = _read_main(SYMBOLS[sym]["partner"])
        p = _build_symbol_panel(sym, frames, main, partner, liq=liq, label_mode=label_mode)
        if p.empty:
            coverage[sym] = {"ok": False, "contracts": 0}
            continue
        p = p[(p.index >= TRAIN_START) & (p.index <= TEST_END)]
        p = p.dropna(subset=["fwd1", "fwd5", "carry_ann"])
        p = p[~p.index.duplicated()]
        coverage[sym] = {
            "ok": True,
            "contracts": len(frames),
            "rows": int(len(p)),
            "first": str(p.index[0].date()),
            "last": str(p.index[-1].date()),
            "near_contracts_used": int(p["near_contract"].nunique()),
            "roll_days": int((p["near_contract"] != p["near_contract"].shift(1)).sum()),
        }
        parts.append(p)
    panel = pd.concat(parts).sort_index()
    return panel, coverage, {}


def _fingerprint() -> dict:
    """数据版本指纹：合约缓存 + 主力连续缓存内容 sha256 前 16 位。"""
    files = []
    if os.path.isdir(CONTRACT_DIR):
        files += [os.path.join(CONTRACT_DIR, f) for f in sorted(os.listdir(CONTRACT_DIR))
                  if f.endswith(".csv")]
    for sym in SYMBOLS:
        for code in (sym, SYMBOLS[sym]["partner"]):
            p = os.path.join(CACHE_DIR, f"{code}0.csv")
            if os.path.exists(p):
                files.append(p)
    h = hashlib.sha256()
    for p in files:
        h.update(os.path.basename(p).encode("utf-8"))
        with open(p, "rb") as fh:
            h.update(fh.read())
    return {"data_version": h.hexdigest()[:16], "n_files": len(files)}


def _split(df: pd.DataFrame):
    tr = df[(df.index >= TRAIN_START) & (df.index <= TRAIN_END)]
    va = df[(df.index >= VAL_START) & (df.index <= VAL_END)]
    te = df[(df.index >= TEST_START) & (df.index <= TEST_END)]
    return tr, va, te


# ---------------------------------------------------------------------------
# 统计工具
# ---------------------------------------------------------------------------
def _spearman(a, b, min_obs: int = 4) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < min_obs:
        return np.nan
    ra = pd.Series(a[m]).rank().to_numpy()
    rb = pd.Series(b[m]).rank().to_numpy()
    if np.std(ra) < 1e-12 or np.std(rb) < 1e-12:
        return np.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def _ic_series(df: pd.DataFrame, sig: str, lab: str) -> float:
    return _spearman(df[sig], df[lab])


def _tstat(x: np.ndarray) -> tuple[float, float, float]:
    """均值 / t 值 / 双尾 p（正态近似）。"""
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n < 3:
        return float(np.nan), float(np.nan), float(np.nan)
    mean = float(x.mean())
    se = float(x.std(ddof=1) / math.sqrt(n))
    if se < 1e-12:
        return mean, float("nan"), float("nan")
    t = mean / se
    p = math.erfc(abs(t) / math.sqrt(2.0))
    return mean, float(t), float(p)


def _sharpe(rets: np.ndarray, periods: int = 252, rf: float = 0.02) -> float:
    rets = np.asarray(rets, dtype=float)
    if rets.size < 2:
        return 0.0
    ex = rets - rf / periods
    sd = float(np.std(ex))
    return float(np.mean(ex) / sd * math.sqrt(periods)) if sd > 1e-12 else 0.0


def _mdd(rets: np.ndarray) -> float:
    if rets.size == 0:
        return 0.0
    eq = np.cumprod(1.0 + np.asarray(rets, dtype=float))
    peak = np.maximum.accumulate(eq)
    return float(np.min(np.where(peak > 0, (eq - peak) / peak, 0.0)))


def _make_model(alpha: float) -> Pipeline:
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", RobustScaler(quantile_range=(5.0, 95.0))),
        ("m", Ridge(alpha=float(alpha))),
    ])


def _fit_with_val(df: pd.DataFrame, feats: list[str], label: str):
    """train 拟合 + val 选 alpha；测试段完全不参与。"""
    tr, va, te = _split(df)
    tr = tr.dropna(subset=[label])
    va = va.dropna(subset=[label])
    best = None
    for a in (0.1, 1.0, 10.0, 100.0):
        m = _make_model(a).fit(tr[feats], tr[label])
        mse = float(np.mean((m.predict(va[feats]) - va[label]) ** 2))
        if best is None or mse < best[0]:
            best = (mse, a, m)
    mse, alpha, model = best
    te2 = te.dropna(subset=[label])
    pred = model.predict(te2[feats]) if len(te2) else np.empty(0)
    return {"alpha": alpha, "val_mse": round(mse, 8), "model": model,
            "test": te2.assign(pred=pred) if len(te2) else te2, "train_n": int(len(tr)),
            "val_n": int(len(va)), "test_n": int(len(te2))}


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------
def _per_symbol_ics(te: pd.DataFrame, sig: str) -> dict:
    """逐品种、逐 horizon 的时序 Spearman IC（测试段）。"""
    out = {}
    for sym, g in te.groupby("symbol"):
        out[sym] = {f"ic_fwd{k}": round(_ic_series(g, sig, f"fwd{k}"), 6)
                    for k in (1, 3, 5, 10)}
        out[sym]["n"] = int(len(g))
    # 合并样本（跨品种 pooled）
    out["pooled"] = {f"ic_fwd{k}": round(_ic_series(te, sig, f"fwd{k}"), 6) for k in (1, 3, 5, 10)}
    out["pooled"]["n"] = int(len(te))
    return out


def _cross_section_ic(te: pd.DataFrame, sig: str) -> dict:
    """逐日横截面 rank IC（同日 3 个品种），同时给 1/3/5/10 日衰减。"""
    res = {}
    for k in (1, 3, 5, 10):
        lab = f"fwd{k}"
        daily = {}
        for dt, g in te.groupby(level=0):
            g = g.dropna(subset=[sig, lab])
            if len(g) < 3:
                continue
            ic = _spearman(g[sig], g[lab], min_obs=3)
            if np.isfinite(ic):
                daily[dt] = ic
        s = pd.Series(daily, dtype=float).sort_index()
        mean, t, p = _tstat(s.to_numpy())
        res[f"fwd{k}"] = {
            "n_dates": int(s.size), "mean_ic": round(float(mean), 6),
            "std": round(float(s.std(ddof=1)), 6) if s.size > 2 else None,
            "t_stat": round(float(t), 4) if np.isfinite(t) else None,
            "p_value": round(float(p), 4) if np.isfinite(p) else None,
            "significant_5pct": bool(np.isfinite(p) and p < 0.05),
            "mean_abs_ic": round(float(s.abs().mean()), 6) if s.size else 0.0,
            "daily_ic": {str(d.date()): round(float(v), 4) for d, v in s.items()},
        }
    return res


def _cost_rate(sym: str, price: float) -> float:
    spec = get_contract_spec(sym)
    c = estimate_cost_rate(price, spec["multiplier"], spec["commission_per_lot"],
                           1.0, spec["min_price_tick"])
    return float(np.asarray(c).reshape(-1)[0])


def _portfolio(te: pd.DataFrame, sig: str, direction: float = 1.0,
               smooth: int = 1, thr: float = 0.0, hold: int = 1,
               demean: bool = False) -> dict:
    """等权多空组合（每品种按信号符号持仓），显式计入换手成本。

    参数（方向/平滑/阈值/持有期）只允许在验证段选择，测试段仅用于评估。
    hold>1 表示「每 hold 个交易日调仓一次并持有」，用于匹配 5/10 日信号的有效期。
    demean=True 表示先做同日横截面去均值（真正的横截面多空），再取符号。
    """
    cost_by_sym = {}
    for sym, g in te.groupby("symbol"):
        px = float(np.nanmedian(g["near_close"]))
        cost_by_sym[sym] = _cost_rate(sym, px)
    zdf = None
    if demean:
        zdf = te.pivot_table(index=te.index, columns="symbol", values=sig, aggfunc="first")
        if smooth > 1:
            zdf = zdf.rolling(smooth, min_periods=1).mean()
        zdf = (zdf.sub(zdf.mean(axis=1), axis=0)) * direction
    frames = []
    for sym, g in te.groupby("symbol"):
        g = g.sort_index()
        if demean and zdf is not None:
            z = zdf[sym].reindex(g.index)
        else:
            z = pd.Series(g[sig].to_numpy() * direction, index=g.index)
            if smooth > 1:
                z = z.rolling(smooth, min_periods=1).mean()
        target = positions_from_signals(z.to_numpy(), thr, thr)
        if hold > 1:
            # 分块持有：调仓日取目标仓位，块内保持不变
            pos = target[(np.arange(len(target)) // hold) * hold]
        else:
            pos = target
        prev = np.concatenate([[0.0], pos[:-1]])
        turn = np.abs(pos - prev)
        frames.append(pd.DataFrame({
            "gross": pos * g["fwd1"].to_numpy(),
            "net": pos * g["fwd1"].to_numpy() - turn * cost_by_sym[sym],
            "turn": turn,
        }, index=g.index))
    allf = pd.concat(frames)
    daily = allf.groupby(level=0).mean(numeric_only=True).sort_index()
    n_years = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    return {
        "n_days": int(len(daily)),
        "sharpe_gross": round(_sharpe(daily["gross"].to_numpy()), 4),
        "sharpe_net": round(_sharpe(daily["net"].to_numpy()), 4),
        "mdd_gross": round(_mdd(daily["gross"].to_numpy()), 4),
        "mdd_net": round(_mdd(daily["net"].to_numpy()), 4),
        "total_return_gross": round(float(np.prod(1 + daily["gross"]) - 1), 4),
        "total_return_net": round(float(np.prod(1 + daily["net"]) - 1), 4),
        "annual_turnover": round(float(daily["turn"].sum() / n_years), 3),
        "avg_cost_bps": round(float(np.mean([c for c in cost_by_sym.values()]) * 1e4), 3),
        "cost_by_symbol": {k: round(v, 6) for k, v in cost_by_sym.items()},
    }


def _per_symbol_net(te: pd.DataFrame, sig: str, direction: float = 1.0,
                    smooth: int = 1, thr: float = 0.0, hold: int = 1,
                    demean: bool = False) -> dict:
    """逐品种 net_performance（复用统一评估模块），毛/净夏普 + 换手。"""
    out = {}
    zdf = None
    if demean:
        zdf = te.pivot_table(index=te.index, columns="symbol", values=sig, aggfunc="first")
        if smooth > 1:
            zdf = zdf.rolling(smooth, min_periods=1).mean()
        zdf = (zdf.sub(zdf.mean(axis=1), axis=0)) * direction
    for sym, g in te.groupby("symbol"):
        g = g.sort_index()
        if demean and zdf is not None:
            z = zdf[sym].reindex(g.index)
        else:
            z = pd.Series(g[sig].to_numpy() * direction, index=g.index)
            if smooth > 1:
                z = z.rolling(smooth, min_periods=1).mean()
        pred = z.to_numpy()
        if hold > 1:
            pred = pred[(np.arange(len(pred)) // hold) * hold]
        cost = _cost_rate(sym, float(np.nanmedian(g["near_close"])))
        r = net_performance(pred, g["fwd1"].to_numpy(), cost, thr, thr)
        out[sym] = {k: (round(v, 4) if isinstance(v, (int, float)) else None)
                    for k, v in r.items() if k not in ("equity_curve", "net_returns")}
        out[sym]["cost_rate"] = round(cost, 6)
    return out


def _yearly(te: pd.DataFrame, sig: str) -> dict:
    """分年度稳定性：IC + 逐品种净夏普。"""
    out = {}
    for year, g in te.groupby(te.index.year):
        out[str(year)] = {
            "n": int(len(g)),
            "ic_fwd1": round(_ic_series(g, sig, "fwd1"), 4),
            "ic_fwd5": round(_ic_series(g, sig, "fwd5"), 4),
            "by_symbol": {s: round(_ic_series(gg, sig, "fwd5"), 4)
                          for s, gg in g.groupby("symbol")},
        }
    return out


def _causality_check() -> dict:
    """扰动未来 bar，历史特征必须逐值不变。"""
    sym = "rb"
    frames = _contract_frames(sym)
    main = _read_main(sym)
    partner = _read_main(SYMBOLS[sym]["partner"])
    base = _build_symbol_panel(sym, frames, main, partner)
    if base.empty:
        return {"pass": False, "reason": "无数据"}
    cutoff = base.index[len(base) // 3]
    pert = {c: d.copy() for c, d in frames.items()}
    for d in pert.values():
        m = d["datetime"] > cutoff
        for col in ("open", "high", "low", "close", "volume", "open_interest", "settle"):
            if col in d.columns:
                d[col] = pd.to_numeric(d[col], errors="coerce").astype(float)
                d.loc[m, col] = d.loc[m, col] * 1.5
    after = _build_symbol_panel(sym, pert, main, partner)
    cols = [c for c in TERM_FEATURES if c in base.columns]
    hist = base.index[base.index <= cutoff]
    a = base.loc[hist, cols].astype(float)
    b = after.reindex(hist)[cols].astype(float)
    diff = float(np.nanmax(np.abs(a.to_numpy() - b.to_numpy()))) if len(hist) else 0.0
    return {"pass": bool(diff < 1e-9), "max_abs_diff": diff,
            "cutoff": str(cutoff.date()), "n_rows": int(len(hist)),
            "method": "rb 全部合约在 cutoff 之后的价格/量/持仓统一 ×1.5 后重建特征，比较 cutoff 前逐值"}


def main() -> int:
    t_start = time.time()
    fetch = fetch_contracts()
    print(f"[抓取] 新抓 {len(fetch['fetched'])}，缓存命中 {len(fetch['cached'])}，"
          f"失败 {len(fetch['failed'])}，缺口 {len(fetch['missing'])}，"
          f"耗时 {fetch['elapsed_sec']}s")

    panel, coverage, _ = _assemble()
    fp = _fingerprint()
    print(f"[覆盖] 品种 {len(coverage)}，样本 {len(panel)} 行，指纹 {fp['data_version']}")

    result: dict = {
        "meta": {
            "seed": SEED, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "windows": {"train": [str(TRAIN_START.date()), str(TRAIN_END.date())],
                        "validation": [str(VAL_START.date()), str(VAL_END.date())],
                        "test": [str(TEST_START.date()), str(TEST_END.date())]},
            "features": TERM_FEATURES,
            "data_version": fp["data_version"],
            "fingerprint_files": fp["n_files"],
            "fetch_sec": fetch["elapsed_sec"],
        },
        "availability": {
            "local_single_contract_before_probe": 0,
            "probe": "见 docs/diagnosis/phase4_term_structure.md 第 1 节（term_structure_probe.py）",
            "fetch": fetch,
        },
        "coverage": coverage,
    }

    if panel.empty or len(coverage) < 2:
        result["conclusion"] = {"term_structure_tradable_edge": False,
                                "reason": "可用品种不足，无法构成横截面"}
        with open(OUT_JSON, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2, default=str)
        print("数据不足，已写出部分结果。")
        return 1

    # ---- 标签与 IC ----
    tr_all = panel[(panel.index >= TRAIN_START) & (panel.index <= TRAIN_END)]
    va_all = panel[(panel.index >= VAL_START) & (panel.index <= VAL_END)]
    te_all = panel[(panel.index >= TEST_START) & (panel.index <= TEST_END)]
    result["coverage"]["split_rows"] = {
        "train": int(len(tr_all)), "validation": int(len(va_all)), "test": int(len(te_all)),
        "test_by_symbol": {s: int(len(g)) for s, g in te_all.groupby("symbol")},
        "test_dates": int(te_all.index.nunique()),
    }
    result["labels"] = {
        "ic_time_series_carry_ann": _per_symbol_ics(te_all, "carry_ann"),
        "ic_time_series_carry_z": _per_symbol_ics(te_all, "carry_z"),
        "cross_section_rank_ic_carry_z": _cross_section_ic(te_all, "carry_z"),
        "yearly": _yearly(te_all, "carry_z"),
    }

    # ---- 模型（Ridge，train 拟合 / val 选 alpha / test 只评估）----
    model_res = {}
    for sym, g in panel.groupby("symbol"):
        info = _fit_with_val(g, TERM_FEATURES, "fwd5")
        test = info.pop("test")
        info.pop("model", None)  # 模型对象不落 JSON
        model_res[sym] = {
            **info,
            "ic_fwd5_test": round(_ic_series(test, "pred", "fwd5"), 4) if len(test) else None,
            "ic_fwd1_test": round(_ic_series(test, "pred", "fwd1"), 4) if len(test) else None,
        }
    result["ridge"] = model_res

    # ---- 方向与组合参数：只在验证段选择（测试段不参与）----
    val_ics = {s: _ic_series(g, "carry_z", "fwd1") for s, g in va_all.groupby("symbol")}
    finite_ics = [v for v in val_ics.values() if np.isfinite(v)]
    mean_val_ic = float(np.nanmean(finite_ics)) if finite_ics else 0.0
    direction = -1.0 if mean_val_ic < 0 else 1.0
    variants = {
        "raw": {"direction": direction, "smooth": 1, "thr": 0.0},
        "smooth5": {"direction": direction, "smooth": 5, "thr": 0.0},
        "thresh03": {"direction": direction, "smooth": 1, "thr": 0.3},
    }
    val_scores = {name: _portfolio(va_all, "carry_z", **cfg) for name, cfg in variants.items()}
    best_name = max(val_scores, key=lambda k: val_scores[k]["sharpe_net"])
    result["selection"] = {
        "val_ic_fwd1_by_symbol": {k: round(float(v), 4) for k, v in val_ics.items()},
        "val_mean_ic_fwd1": round(mean_val_ic, 4),
        "direction": direction,
        "direction_rule": "验证段平均 IC<0 则反向做多（只用验证段决定，测试段不参与）",
        "val_sharpe_net_by_variant": {k: v["sharpe_net"] for k, v in val_scores.items()},
        "chosen_variant": best_name,
    }

    # ---- 组合层（carry_z 信号，含全部变体在测试段的对照）----
    result["portfolio"] = {
        "signal": "carry_z",
        "variants_test": {name: _portfolio(te_all, "carry_z", **cfg)
                          for name, cfg in variants.items()},
        "pooled_equal_weight": _portfolio(te_all, "carry_z", **variants[best_name]),
        "per_symbol_net_performance": _per_symbol_net(te_all, "carry_z",
                                                      **variants[best_name]),
    }

    # ---- 因果自检 ----
    result["causality"] = _causality_check()

    # ---- 结论 ----
    cs = result["labels"]["cross_section_rank_ic_carry_z"]["fwd5"]
    pf = result["portfolio"]["pooled_equal_weight"]
    sym_net = [v["sharpe"] for v in result["portfolio"]["per_symbol_net_performance"].values()]
    edge = bool(cs["significant_5pct"] and pf["sharpe_net"] > 0.5)
    result["conclusion"] = {
        "term_structure_tradable_edge": edge,
        "cross_section_ic_fwd5": cs["mean_ic"],
        "cross_section_p": cs["p_value"],
        "pooled_sharpe_gross": pf["sharpe_gross"],
        "pooled_sharpe_net": pf["sharpe_net"],
        "per_symbol_net_sharpe": {k: v["sharpe"] for k, v in
                                  result["portfolio"]["per_symbol_net_performance"].items()},
        "per_symbol_net_sharpe_median": round(float(np.median(sym_net)), 4) if sym_net else None,
        "n_positive_net": int(sum(1 for v in sym_net if v > 0)),
        "causality_pass": result["causality"]["pass"],
        "test_rows": int(len(te_all)),
    }

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, default=str)

    # ---- 控制台摘要 ----
    print("\n=== 覆盖 ===")
    for s, c in coverage.items():
        print(f"  {s}: {c}")
    print("\n=== 测试段 IC（carry_ann，逐品种）===")
    for s, v in result["labels"]["ic_time_series_carry_ann"].items():
        print(f"  {s}: {v}")
    print("\n=== 横截面 rank IC（carry_z，3 品种逐日）===")
    for k, v in result["labels"]["cross_section_rank_ic_carry_z"].items():
        print(f"  {k}: mean={v['mean_ic']} t={v['t_stat']} p={v['p_value']} "
              f"sig={v['significant_5pct']} n_dates={v['n_dates']}")
    print("\n=== 验证段选参（方向/变体）===")
    print(f"  val IC(fwd1) 逐品种 {result['selection']['val_ic_fwd1_by_symbol']} "
          f"均值 {result['selection']['val_mean_ic_fwd1']} -> direction {result['selection']['direction']}")
    print(f"  验证段净夏普 {result['selection']['val_sharpe_net_by_variant']} -> 选用 {result['selection']['chosen_variant']}")
    print("\n=== 组合（carry_z，扣成本）===")
    print(f"  毛夏普 {pf['sharpe_gross']} / 净夏普 {pf['sharpe_net']} / "
          f"净MDD {pf['mdd_net']} / 年换手 {pf['annual_turnover']} / 成本 {pf['avg_cost_bps']}bps")
    print("\n=== 逐品种净夏普 ===")
    for s, v in result["portfolio"]["per_symbol_net_performance"].items():
        print(f"  {s}: 净 {v['sharpe']} 毛 {v['sharpe_gross']} 换手 {v['turnover']}")
    print(f"\n因果自检: {result['causality']['pass']} (max_diff={result['causality']['max_abs_diff']})")
    print(f"总耗时 {time.time() - t_start:.1f}s -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
