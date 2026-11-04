"""第三轮 B：标签体系改造实验（严格样本外，只做研究，不改生产代码/权重）。

目标
----
在「方向分类没有可交易边际」的前提下，检验是否有**其他预测目标**能在同一套
日线数据上产生可验证的边际。所有结论只依赖样本外（test）区间，验证段只用于
选超参/阈值，测试段不参与任何调参或特征选择。

实验口径
--------
- 数据：`data/sina_cache/*0.csv`（主力连续日线，本地缓存，不联网）；
- 切分：train 2016-01-01 ~ 2020-12-31 / validation 2021-01-01 ~ 2021-12-31 /
  test 2022-01-01 ~ 数据末端（2026-11-03）；
- 特征：因果时序特征 + 同日横截面特征（板块动量、相对强弱、OI 变化、量价背离）；
  标准化/缺失填充只在 train 上拟合；测试段特征只依赖当日及更早的 bar；
- 标签（逐个独立评估）：
  L0 方向分类（对照基线）；L1 未来 5 日已实现波动率三分位；
  L2 |未来 5 日收益| 超训练期 70 分位；L3 三分类（大跌/震荡/大涨，训练期 30/70 分位）；
  L4 横截面未来 5 日相对强弱（rank IC 为主指标，含 IC 衰减）；
  L5 预测区间覆盖率（80% 名义区间）；
- 评估：统一调用 `futures_quant.ai.evaluation`（Wilson 95% CI / 基准率 /
  扣手续费+滑点后的净收益夏普），横截面类补 rank IC 与 IC 衰减。

用法
----
    python scripts/research/label_research.py
    python scripts/research/label_research.py --symbols rb,i,cu,IF --seed 7
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import warnings
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.ai.evaluation import (  # noqa: E402
    estimate_cost_rate,
    net_performance,
    probability_hit_rate,
    wilson_interval,
)
from futures_quant.data.contract_specs import get_contract_spec  # noqa: E402

CACHE_DIR = os.path.join(_PROJ_ROOT, "data", "sina_cache")
DEFAULT_OUT = os.path.join(_PROJ_ROOT, "scripts", "research", "output",
                           "label_research_results.json")

# ---------------------------------------------------------------------------
# 实验配置（固定值，保证可复现）
# ---------------------------------------------------------------------------
SEED = 20261104
TRAIN_START = pd.Timestamp("2016-01-01")
VAL_START = pd.Timestamp("2021-01-01")
TEST_START = pd.Timestamp("2022-01-01")
TEST_END = pd.Timestamp("2026-11-03")

# symbol, category, exchange
SYMBOLS: list[tuple[str, str, str]] = [
    ("rb", "黑色系", "SHFE"),
    ("hc", "黑色系", "SHFE"),
    ("i", "黑色系", "DCE"),
    ("j", "黑色系", "DCE"),
    ("jm", "黑色系", "DCE"),
    ("cu", "有色金属", "SHFE"),
    ("al", "有色金属", "SHFE"),
    ("zn", "有色金属", "SHFE"),
    ("au", "贵金属", "SHFE"),
    ("ag", "贵金属", "SHFE"),
    ("ta", "能源化工", "CZCE"),
    ("ma", "能源化工", "CZCE"),
    ("ru", "能源化工", "SHFE"),
    ("bu", "能源化工", "SHFE"),
    ("m", "农产品", "DCE"),
    ("y", "农产品", "DCE"),
    ("sr", "农产品", "CZCE"),
    ("cf", "农产品", "CZCE"),
    ("IF", "金融", "CFFEX"),
    ("IC", "金融", "CFFEX"),
    ("IH", "金融", "CFFEX"),
]

TS_FEATURES = [
    "ret1", "mom5", "mom20", "mom60", "vol20", "vol60", "atr14",
    "range_pos", "oi_chg5", "oi_chg20", "vol_ratio", "amp", "vp_div", "ret_skew20",
]
XS_FEATURES = [
    "xs_mom5", "xs_mom20", "xs_vol20", "xs_oi_chg5", "xs_vol_ratio", "xs_range_pos",
    "xs_mom20_cat", "xs_oi_chg5_cat", "xs_vol20_cat",
    "sector_mom5", "sector_mom20", "rel_mom20",
]
FEATURES = TS_FEATURES + XS_FEATURES

LABEL_KEYS = [
    "L0_direction", "L1_vol_regime", "L2_abs_move",
    "L3_three_class", "L4_cross_section", "L5_interval",
]


# ---------------------------------------------------------------------------
# 数据加载与特征（全部因果：t 时点特征只用 <= t 的 bar）
# ---------------------------------------------------------------------------
def _cache_path(code: str) -> str:
    """按品种代码找到缓存 CSV（大小写不敏感，形如 rb0.csv / IF0.csv）。"""
    target = f"{code.lower()}0.csv"
    for name in os.listdir(CACHE_DIR):
        if name.lower() == target:
            return os.path.join(CACHE_DIR, name)
    raise FileNotFoundError(f"缓存缺失: {code} ({target})")


def _load_raw(code: str) -> pd.DataFrame:
    """读取单个品种日线并按日期排序、去重。"""
    d = pd.read_csv(_cache_path(code))
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.drop_duplicates("datetime").sort_values("datetime").set_index("datetime")
    for col in ("open", "high", "low", "close", "volume", "open_interest"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def _ts_features(d: pd.DataFrame) -> pd.DataFrame:
    """构造时序特征（只使用当日及更早的 bar，滚动窗口均为因果窗口）。"""
    c, h, l, v, oi = d["close"], d["high"], d["low"], d["volume"], d["open_interest"]
    r1 = c.pct_change(fill_method=None)
    f = pd.DataFrame(index=d.index)
    f["ret1"] = r1
    f["mom5"] = c / c.shift(5) - 1
    f["mom20"] = c / c.shift(20) - 1
    f["mom60"] = c / c.shift(60) - 1
    f["vol20"] = r1.rolling(20).std()
    f["vol60"] = r1.rolling(60).std()
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    f["atr14"] = tr.rolling(14).mean() / c
    rng = h.rolling(20).max() - l.rolling(20).min()
    f["range_pos"] = (c - l.rolling(20).min()) / rng.where(rng > 0)
    f["oi_chg5"] = oi.pct_change(5, fill_method=None)
    f["oi_chg20"] = oi.pct_change(20, fill_method=None)
    f["vol_ratio"] = v / v.rolling(20).mean()
    f["amp"] = (h - l) / c
    f["vp_div"] = r1.rolling(20).corr(v.pct_change(fill_method=None))
    f["ret_skew20"] = r1.rolling(20).skew()
    return f.replace([np.inf, -np.inf], np.nan)


def _labels(d: pd.DataFrame) -> pd.DataFrame:
    """构造未来收益/波动标签（只作为标签，绝不进入特征）。"""
    c, r1 = d["close"], d["close"].pct_change(fill_method=None)
    y = pd.DataFrame(index=d.index)
    y["fwd1"] = c.shift(-1) / c - 1
    y["fwd3"] = c.shift(-3) / c - 1
    y["fwd5"] = c.shift(-5) / c - 1
    y["fwd10"] = c.shift(-10) / c - 1
    # t 时点的未来 5 日已实现波动 = std(r[t+1..t+5])，下式在 t 对齐
    y["rv5"] = r1.shift(-1).rolling(5).std().shift(-4)
    y["absfwd5"] = y["fwd5"].abs()
    return y.replace([np.inf, -np.inf], np.nan)


def _build_panel(codes: Iterable[str]) -> tuple[pd.DataFrame, dict]:
    """组装多品种面板 + 横截面特征，并返回数据版本指纹。"""
    frames = []
    meta_sym = {}
    for code, category, exchange in SYMBOLS:
        if code not in codes:
            continue
        d = _load_raw(code)
        f = pd.concat([_ts_features(d), _labels(d)], axis=1)
        f["symbol"] = code
        f["category"] = category
        f["exchange"] = exchange
        f["close"] = d["close"]
        frames.append(f.reset_index())
        meta_sym[code] = {
            "file": os.path.basename(_cache_path(code)),
            "rows": int(len(d)),
            "first": str(d.index[0].date()),
            "last": str(d.index[-1].date()),
            "category": category,
            "exchange": exchange,
        }
    panel = pd.concat(frames, ignore_index=True)

    # ---- 横截面特征：同一天、不同品种之间的相对位置（不含任何未来信息） ----
    g = panel.groupby("datetime", sort=False)
    for col in ("mom5", "mom20", "vol20", "oi_chg5", "vol_ratio", "range_pos"):
        panel[f"xs_{col}"] = g[col].rank(pct=True) - 0.5
    gcat = panel.groupby(["datetime", "category"], sort=False)
    for col in ("mom20", "oi_chg5", "vol20"):
        panel[f"xs_{col}_cat"] = gcat[col].rank(pct=True) - 0.5
    # 板块动量与该品种相对板块的强弱
    panel["sector_mom5"] = gcat["mom5"].transform("mean")
    panel["sector_mom20"] = gcat["mom20"].transform("mean")
    panel["rel_mom20"] = panel["mom20"] - panel["sector_mom20"]

    files = [meta_sym[c]["file"] for c in meta_sym]
    fingerprint = _fingerprint([_cache_path(c) for c in meta_sym])
    meta = {
        "data_version": fingerprint,
        "fingerprint_scope": "所选品种缓存 CSV 内容 sha256 前 16 位",
        "files": files,
        "symbols": meta_sym,
        "rows_total": int(len(panel)),
        "cache_dir": os.path.relpath(CACHE_DIR, _PROJ_ROOT).replace("\\", "/"),
    }
    return panel, meta


def _fingerprint(paths: list[str]) -> str:
    """对输入文件内容做 sha256，作为可复现的数据版本指纹。"""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(os.path.basename(p).encode("utf-8"))
        with open(p, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# 切分 / 建模
# ---------------------------------------------------------------------------
COMMON_LABELS = ["fwd1", "fwd5", "rv5"]


def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """严格时间序列三分；三个标签相关的公共字段必须齐全，保证跨标签样本对齐。"""
    tr = df[(df.index >= TRAIN_START) & (df.index < VAL_START)]
    va = df[(df.index >= VAL_START) & (df.index < TEST_START)]
    te = df[(df.index >= TEST_START) & (df.index <= TEST_END)]
    return tr.dropna(subset=COMMON_LABELS), va.dropna(subset=COMMON_LABELS), te.dropna(subset=COMMON_LABELS)


def _make_reg(alpha: float) -> Pipeline:
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", RobustScaler(quantile_range=(5.0, 95.0))),
        ("m", Ridge(alpha=float(alpha))),
    ])


def _make_clf(c: float) -> Pipeline:
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", RobustScaler(quantile_range=(5.0, 95.0))),
        ("m", LogisticRegression(C=float(c), max_iter=3000)),
    ])


def _fit_regression(Xtr, ytr, Xva, yva, alphas=(0.1, 1.0, 10.0)) -> tuple[Pipeline, float, float]:
    """在验证段按 MSE 选 alpha（测试段不参与）。"""
    best = None
    for a in alphas:
        m = _make_reg(a).fit(Xtr, ytr)
        mse = float(np.mean((m.predict(Xva) - yva) ** 2))
        if best is None or mse < best[0]:
            best = (mse, a, m)
    return best[2], best[1], best[0]


def _fit_classifier(Xtr, ytr, Xva, yva, cs=(0.1, 1.0, 10.0)) -> tuple[Pipeline, float, float]:
    """在验证段按准确率选 C（测试段不参与）。"""
    best = None
    for c in cs:
        m = _make_clf(c).fit(Xtr, ytr)
        acc = float(np.mean(m.predict(Xva) == yva))
        if best is None or acc > best[0]:
            best = (acc, c, m)
    return best[2], best[1], best[0]


def _prob_up(model: Pipeline, X) -> np.ndarray:
    """二分类 pipeline 的 P(上涨)。"""
    proba = model.predict_proba(X)
    classes = list(model.classes_)
    if 1 not in classes:
        return np.zeros(len(X), dtype=float)
    return proba[:, classes.index(1)]


def _net(pred, actual, cost) -> dict:
    """统一走 evaluation.net_performance（扣手续费+1 tick 滑点）。"""
    r = net_performance(pred, actual, cost_rate=cost)
    keys = ("n", "sharpe", "max_drawdown", "total_return", "sharpe_gross",
            "max_drawdown_gross", "total_return_gross", "total_cost",
            "turnover", "avg_cost_bps")
    out = {}
    for k in keys:
        v = r[k]
        out[k] = int(v) if k == "n" else float(v)
    return out


def _accuracy(pred_cls, true_cls) -> dict:
    """三分类准确率 + 基准率（测试段多数类占比）+ Wilson CI。"""
    pred = np.asarray(pred_cls)
    true = np.asarray(true_cls)
    n = int(len(true))
    n_hit = int(np.sum(pred == true))
    acc = n_hit / n if n else 0.0
    counts = np.bincount(true.astype(int)) if n else np.array([0])
    base = float(counts.max()) / n if n else 0.0
    lo, hi = wilson_interval(n_hit, n)
    return {
        "n": n, "n_hit": n_hit, "accuracy": round(acc, 6),
        "base_rate": round(base, 6), "edge": round(acc - base, 6),
        "ci_low": round(lo, 6), "ci_high": round(hi, 6),
        "class_counts": [int(x) for x in counts],
        "significant": bool(lo > base),
    }


def _interval_stats(actual, lower, upper) -> dict:
    """区间覆盖率（名义 80%）+ Wilson CI；偏离 80% 视为显著（过度/不足覆盖）。"""
    a = np.asarray(actual, float)
    lo = np.asarray(lower, float)
    hi = np.asarray(upper, float)
    ok = np.isfinite(a) & np.isfinite(lo) & np.isfinite(hi)
    a, lo, hi = a[ok], lo[ok], hi[ok]
    n = int(len(a))
    k = int(np.sum((a >= lo) & (a <= hi)))
    cov = k / n if n else 0.0
    wlo, whi = wilson_interval(k, n)
    return {
        "n": n, "n_covered": k, "coverage": round(cov, 6),
        "nominal": 0.8, "ci_low": round(wlo, 6), "ci_high": round(whi, 6),
        "significant": bool(n > 0 and (wlo > 0.8 or whi < 0.8)),
    }


def _sharpe(rets, periods_per_year: int = 252, rf_annual: float = 0.02) -> float:
    """与 evaluation.net_performance 同口径的夏普（日频，扣费后收益序列）。"""
    r = np.asarray(rets, float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    excess = r - rf_annual / periods_per_year
    sd = float(np.std(excess))
    if sd < 1e-12:
        return 0.0
    return float(np.mean(excess) / sd * math.sqrt(periods_per_year))


# ---------------------------------------------------------------------------
# 单品种实验：训练模型，产出样本外原始预测（指标统一在外层计算）
# ---------------------------------------------------------------------------
def _run_symbol(df: pd.DataFrame, code: str) -> dict:
    """单品种：训练/验证/测试三分，逐个标签产出测试段原始预测。"""
    tr, va, te = _split(df)
    if len(tr) < 200 or len(va) < 60 or len(te) < 200:
        return {"raw": {}, "params": {"skipped": f"样本不足 tr={len(tr)} va={len(va)} te={len(te)}"}}

    Xcols = FEATURES
    spec = get_contract_spec(code)
    cost_te = estimate_cost_rate(
        te["close"].values, multiplier=spec["multiplier"],
        commission_per_lot=spec["commission_per_lot"],
        slippage_ticks=1.0, min_price_tick=spec["min_price_tick"],
    )
    cost_va = estimate_cost_rate(
        va["close"].values, multiplier=spec["multiplier"],
        commission_per_lot=spec["commission_per_lot"],
        slippage_ticks=1.0, min_price_tick=spec["min_price_tick"],
    )

    out: dict = {"raw": {}, "params": {}}
    Xtr, Xva, Xte = tr[Xcols].values, va[Xcols].values, te[Xcols].values
    dates_te = pd.DatetimeIndex(te.index)

    # ---------------- L0：方向分类（对照基线） ----------------
    ytr = (tr["fwd1"].values > 0).astype(int)
    yva = (va["fwd1"].values > 0).astype(int)
    model, C, vacc = _fit_classifier(Xtr, ytr, Xva, yva)
    pva = _prob_up(model, Xva)
    pte = _prob_up(model, Xte)
    out["raw"]["L0_direction"] = {
        "kind": "binary", "p_up": pte,
        "actual": te["fwd1"].values.astype(float),
        "pred_num": pte - 0.5, "cost": cost_te, "dates": dates_te,
    }
    out["params"]["L0_C"] = C
    out["params"]["L0_val_acc"] = round(vacc, 6)

    # ---------------- L1：未来 5 日波动率三分位 ----------------
    q_vol = tr["rv5"].quantile([1.0 / 3.0, 2.0 / 3.0]).values
    cls = lambda s: np.where(s.values <= q_vol[0], 0,
                             np.where(s.values <= q_vol[1], 1, 2)).astype(int)
    ytr_v, yva_v, yte_v = cls(tr["rv5"]), cls(va["rv5"]), cls(te["rv5"])
    if len(np.unique(ytr_v)) >= 2:
        model_v, C_v, vacc_v = _fit_classifier(Xtr, ytr_v, Xva, yva_v)
        cls_va = model_v.predict(Xva).astype(int)
        cls_te = model_v.predict(Xte).astype(int)
        # 无技能对照：直接预测训练段多数类
        counts_v = np.bincount(ytr_v, minlength=3)
        out["params"]["L1_train_majority"] = int(np.argmax(counts_v))
        out["params"]["L1_train_class_counts"] = [int(x) for x in counts_v]
        # 门控：用验证段选择「只在预测为某波动档时交易」的档位
        gates = {}
        for k in (0, 1, 2):
            sig = (pva - 0.5) * (cls_va == k)
            gates[k] = _net(sig, va["fwd1"].values.astype(float), cost_va)["sharpe"]
        best_k = int(max(gates, key=lambda k: gates[k]))
        out["raw"]["L1_vol_regime"] = {
            "kind": "multi", "pred_cls": cls_te, "true_cls": yte_v,
            "pred_num": (pte - 0.5) * (cls_te == best_k),
            "actual": te["fwd1"].values.astype(float),
            "cost": cost_te, "dates": dates_te,
        }
        out["params"]["L1_vol_gate"] = best_k
        out["params"]["L1_gate_val_sharpe"] = round(gates[best_k], 6)
        out["params"]["L1_C"] = C_v
    out["params"]["L1_q_vol"] = [round(float(x), 8) for x in q_vol]

    # ---------------- L2：|未来 5 日收益| 超训练期 70 分位 ----------------
    q_abs = float(tr["absfwd5"].quantile(0.70))
    ytr_a = (tr["absfwd5"].values > q_abs).astype(int)
    yva_a = (va["absfwd5"].values > q_abs).astype(int)
    if len(np.unique(ytr_a)) == 2:
        model_a, C_a, vacc_a = _fit_classifier(Xtr, ytr_a, Xva, yva_a)
        pva_a = _prob_up(model_a, Xva)
        pte_a = _prob_up(model_a, Xte)
        # 门控阈值 tau：验证段选，测试段只执行
        taus = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
        gsh = {}
        for tau in taus:
            sig = (pva - 0.5) * (pva_a >= tau)
            gsh[tau] = _net(sig, va["fwd1"].values.astype(float), cost_va)["sharpe"]
        best_tau = float(max(gsh, key=lambda t: gsh[t]))
        out["raw"]["L2_abs_move"] = {
            "kind": "binary", "p_up": pte_a,
            "actual": te["fwd1"].values.astype(float),
            "pred_num": (pte - 0.5) * (pte_a >= best_tau),
            "cost": cost_te, "dates": dates_te,
        }
        out["params"]["L2_abs_q70"] = round(q_abs, 8)
        out["params"]["L2_tau"] = best_tau
        out["params"]["L2_tau_val_sharpe"] = round(gsh[best_tau], 6)
        out["params"]["L2_C"] = C_a

    # ---------------- L3：三分类（大跌 / 震荡 / 大涨） ----------------
    q3 = tr["fwd5"].quantile([0.30, 0.70]).values
    cls3 = lambda s: np.where(s.values <= q3[0], 0,
                              np.where(s.values >= q3[1], 2, 1)).astype(int)
    ytr_3, yva_3, yte_3 = cls3(tr["fwd5"]), cls3(va["fwd5"]), cls3(te["fwd5"])
    if len(np.unique(ytr_3)) >= 2:
        model_3, C_3, vacc_3 = _fit_classifier(Xtr, ytr_3, Xva, yva_3)
        pred3 = model_3.predict(Xte).astype(int)
        pos_map = {0: -1.0, 1: 0.0, 2: 1.0}
        counts_3 = np.bincount(ytr_3, minlength=3)
        out["params"]["L3_train_majority"] = int(np.argmax(counts_3))
        out["params"]["L3_train_class_counts"] = [int(x) for x in counts_3]
        out["raw"]["L3_three_class"] = {
            "kind": "multi", "pred_cls": pred3, "true_cls": yte_3,
            "pred_num": np.array([pos_map[int(c)] for c in pred3]),
            "actual": te["fwd1"].values.astype(float),
            "cost": cost_te, "dates": dates_te,
        }
        out["params"]["L3_q30_q70"] = [round(float(x), 8) for x in q3]
        out["params"]["L3_C"] = C_3

    # ---------------- L5：Ridge 点预测 + 验证残差分位 → 80% 区间 ----------------
    model_r, alpha, vmse = _fit_regression(
        Xtr, tr["fwd1"].values.astype(float), Xva, va["fwd1"].values.astype(float))
    pred_va = model_r.predict(Xva)
    pred_te = model_r.predict(Xte)
    res = va["fwd1"].values.astype(float) - pred_va
    q_lo, q_hi = np.quantile(res, [0.10, 0.90])
    lower = pred_te + q_lo
    upper = pred_te + q_hi
    pos = np.where(lower > 0, 1.0, np.where(upper < 0, -1.0, 0.0))
    out["raw"]["L5_interval"] = {
        "kind": "interval", "actual": te["fwd1"].values.astype(float),
        "lower": lower, "upper": upper, "pred_num": pos,
        "cost": cost_te, "dates": dates_te,
    }
    out["params"]["L5_alpha"] = alpha
    out["params"]["L5_val_mse"] = round(vmse, 8)
    out["params"]["L5_res_q10_q90"] = [round(float(q_lo), 8), round(float(q_hi), 8)]

    return out


# ---------------------------------------------------------------------------
# 指标汇总（单品种 / 跨品种 pooled / 分年度）
# ---------------------------------------------------------------------------
def _years(dates: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(dates.year)


def _clustered(per_date_value: pd.Series, base: float) -> dict:
    """按交易日聚类的均值与 95% CI（同日 21 个品种相关，不能按 2.4 万独立样本算）。

    显著性仍与**无技能基准**（多数类占比 / 50% / 80%）比较，而不是与逐日最大类占比比较：
    后者相当于「每天都知道市场整体方向」的上帝视角，不是无技能基线。
    """
    v = per_date_value.replace([np.inf, -np.inf], np.nan).dropna()
    n = int(len(v))
    if n == 0:
        return {"n_dates": 0}
    mean = float(v.mean())
    sd = float(v.std(ddof=0))
    se = sd / math.sqrt(n) if n > 1 else 0.0
    diff = mean - float(base)
    t = diff / se if se > 1e-12 else 0.0
    p = math.erfc(abs(t) / math.sqrt(2.0))
    return {
        "n_dates": n, "mean": round(mean, 6),
        "ci_low": round(mean - 1.96 * se, 6), "ci_high": round(mean + 1.96 * se, 6),
        "base": round(float(base), 6),
        "t_stat_vs_base": round(t, 6), "p_value_vs_base": round(p, 8),
        "significant": bool(mean - 1.96 * se > float(base)),
    }


def _binary_block(dates, p_up, actual, pred_num, cost) -> dict:
    hit = probability_hit_rate(p_up, (actual > 0).astype(int))
    net = _net(pred_num, actual, cost)
    # 日期聚类稳健性
    tmp = pd.DataFrame({"d": pd.DatetimeIndex(dates),
                        "hit": ((p_up >= 0.5) == (actual > 0)).astype(float),
                        "up": (actual > 0).astype(float)})
    grp = tmp.groupby("d")
    clustered = _clustered(grp["hit"].mean(), hit["base_rate"])
    per_year = {}
    for y in sorted(set(dates.year.tolist())):
        idx = _years(dates) == y
        per_year[str(int(y))] = {
            "n": int(idx.sum()),
            "hit": probability_hit_rate(p_up[idx], (actual[idx] > 0).astype(int)),
            "net_sharpe": _net(pred_num[idx], actual[idx], cost[idx])["sharpe"],
        }
    return {"hit": hit, "net": net, "clustered": clustered, "per_year": per_year}


def _multi_block(dates, pred_cls, true_cls, pred_num, actual, cost) -> dict:
    acc = _accuracy(pred_cls, true_cls)
    net = _net(pred_num, actual, cost)
    tmp = pd.DataFrame({"d": pd.DatetimeIndex(dates),
                        "hit": (np.asarray(pred_cls) == np.asarray(true_cls)).astype(float),
                        "cls": np.asarray(true_cls).astype(int)})

    grp = tmp.groupby("d")
    clustered = _clustered(grp["hit"].mean(), acc["base_rate"])
    per_year = {}
    for y in sorted(set(dates.year.tolist())):
        idx = _years(dates) == y
        per_year[str(int(y))] = {
            "n": int(idx.sum()),
            "accuracy": _accuracy(pred_cls[idx], true_cls[idx]),
            "net_sharpe": _net(pred_num[idx], actual[idx], cost[idx])["sharpe"],
        }
    return {"accuracy": acc, "net": net, "clustered": clustered, "per_year": per_year}


def _interval_block(dates, actual, lower, upper, pred_num, cost) -> dict:
    cov = _interval_stats(actual, lower, upper)
    net = _net(pred_num, actual, cost)
    tmp = pd.DataFrame({"d": pd.DatetimeIndex(dates),
                        "hit": ((actual >= lower) & (actual <= upper)).astype(float)})
    grp = tmp.groupby("d")
    clustered = _clustered(grp["hit"].mean(), 0.8)
    per_year = {}
    for y in sorted(set(dates.year.tolist())):
        idx = _years(dates) == y
        per_year[str(int(y))] = {
            "n": int(idx.sum()),
            "coverage": _interval_stats(actual[idx], lower[idx], upper[idx]),
            "net_sharpe": _net(pred_num[idx], actual[idx], cost[idx])["sharpe"],
        }
    return {"coverage": cov, "net": net, "clustered": clustered, "per_year": per_year}


def _concat(raws: list[dict], field: str) -> np.ndarray:
    return np.concatenate([np.asarray(r[field]) for r in raws])


def _pool_raw(raws: list[dict]) -> dict:
    """把多个品种的测试段原始预测拼接（用于跨品种 pooled 指标）。"""
    if not raws:
        return {}
    dates = pd.DatetimeIndex(np.concatenate([r["dates"].values for r in raws]))
    actual = _concat(raws, "actual")
    cost = _concat(raws, "cost")
    pred_num = _concat(raws, "pred_num")
    base = {"dates": dates, "actual": actual, "cost": cost, "pred_num": pred_num,
            "kind": raws[0]["kind"]}
    if base["kind"] == "binary":
        base["p_up"] = _concat(raws, "p_up")
    elif base["kind"] == "multi":
        base["pred_cls"] = _concat(raws, "pred_cls")
        base["true_cls"] = _concat(raws, "true_cls")
    elif base["kind"] == "interval":
        base["lower"] = _concat(raws, "lower")
        base["upper"] = _concat(raws, "upper")
    return base


def _metrics_for(raw: dict) -> dict:
    if not raw:
        return {}
    if raw["kind"] == "binary":
        return _binary_block(raw["dates"], raw["p_up"], raw["actual"],
                             raw["pred_num"], raw["cost"])
    if raw["kind"] == "multi":
        return _multi_block(raw["dates"], raw["pred_cls"], raw["true_cls"],
                            raw["pred_num"], raw["actual"], raw["cost"])
    return _interval_block(raw["dates"], raw["actual"], raw["lower"],
                           raw["upper"], raw["pred_num"], raw["cost"])


# ---------------------------------------------------------------------------
# L4：横截面相对强弱（rank IC / IC 衰减 / 多空组合净夏普）
# ---------------------------------------------------------------------------
def _spearman(x, y) -> float:
    sx = pd.Series(np.asarray(x, float)).rank()
    sy = pd.Series(np.asarray(y, float)).rank()
    if float(sx.std()) < 1e-12 or float(sy.std()) < 1e-12:
        return np.nan
    return float(np.corrcoef(sx.values, sy.values)[0, 1])


def _ic_series(frame: pd.DataFrame, score_col: str, ret_col: str, min_n: int = 6) -> pd.Series:
    """逐日横截面 Spearman IC。"""
    out = {}
    for d, g in frame.groupby("datetime", sort=True):
        sub = g[[score_col, ret_col]].dropna()
        if len(sub) >= min_n:
            ic = _spearman(sub[score_col].values, sub[ret_col].values)
            if np.isfinite(ic):
                out[d] = ic
    s = pd.Series(out, dtype=float).sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


def _ic_summary(ic: pd.Series, horizon: int) -> dict:
    """IC 均值/波动/t 值/CI/胜率；t 值按 horizon 重叠做保守修正。"""
    if ic.empty:
        return {"n_dates": 0, "n_effective": 0}
    n = int(len(ic))
    n_eff = max(1, int(round(n / max(1, horizon))))
    mean = float(ic.mean())
    std = float(ic.std(ddof=0))
    se = std / math.sqrt(n_eff)
    t = mean / se if se > 1e-12 else 0.0
    p = math.erfc(abs(t) / math.sqrt(2.0))
    ci_lo, ci_hi = mean - 1.96 * se, mean + 1.96 * se
    hit_ratio = float((ic > 0).mean())
    k = int((ic > 0).sum())
    wlo, whi = wilson_interval(k, n)
    return {
        "n_dates": n, "n_effective": n_eff,
        "mean_ic": round(mean, 6), "std_ic": round(std, 6),
        "ic_ir": round(mean / std, 6) if std > 1e-12 else 0.0,
        "t_stat": round(t, 6), "p_value": round(p, 8),
        "ci_low": round(ci_lo, 6), "ci_high": round(ci_hi, 6),
        "positive_ratio": round(hit_ratio, 6),
        "positive_ratio_ci": [round(wlo, 6), round(whi, 6)],
        "significant": bool(ci_lo > 0 or ci_hi < 0),
    }


def _run_cross_section(panel: pd.DataFrame) -> dict:
    """横截面模型：同日特征 → 未来 5 日相对收益；主指标 rank IC。"""
    Xcols = XS_FEATURES
    df = panel.dropna(subset=["fwd5", "fwd1"])
    tr = df[(df["datetime"] >= TRAIN_START) & (df["datetime"] < VAL_START)]
    va = df[(df["datetime"] >= VAL_START) & (df["datetime"] < TEST_START)]
    te = df[(df["datetime"] >= TEST_START) & (df["datetime"] <= TEST_END)]

    best = None
    for a in (0.1, 1.0, 10.0):
        model = _make_reg(a).fit(tr[Xcols].values, tr["fwd5"].values)
        tmp = va.copy()
        tmp["score"] = model.predict(tmp[Xcols].values)
        ic = _ic_series(tmp, "score", "fwd5")
        mean_ic = float(ic.mean()) if len(ic) else -np.inf
        if best is None or mean_ic > best[0]:
            best = (mean_ic, a, model)
    _, alpha, model = best

    # 验证段只报告用（不参与测试段任何选择）
    va_eval = va.copy()
    va_eval["score"] = model.predict(va_eval[Xcols].values)
    ic_val = _ic_summary(_ic_series(va_eval, "score", "fwd5"), horizon=5)

    te = te.copy()
    te["score"] = model.predict(te[Xcols].values)
    te["cost"] = 0.0
    for code in te["symbol"].unique():
        spec = get_contract_spec(code)
        mask = (te["symbol"] == code).values
        te.loc[mask, "cost"] = estimate_cost_rate(
            te.loc[mask, "close"].values, multiplier=spec["multiplier"],
            commission_per_lot=spec["commission_per_lot"],
            slippage_ticks=1.0, min_price_tick=spec["min_price_tick"],
        )

    ic_main = _ic_summary(_ic_series(te, "score", "fwd5"), horizon=5)
    decay = {}
    for h, col in ((1, "fwd1"), (3, "fwd3"), (5, "fwd5"), (10, "fwd10")):
        decay[str(h)] = _ic_summary(_ic_series(te, "score", col), horizon=h)

    # 逐日 IC（用于分年度/分板块复现）
    daily_ic = _ic_series(te, "score", "fwd5")
    per_year = {}
    for y in sorted(set(te["datetime"].dt.year.tolist())):
        s = daily_ic[daily_ic.index.year == y]
        per_year[str(int(y))] = _ic_summary(s, horizon=5)
    per_category = {}
    for cat, g in te.groupby("category"):
        icc = _ic_series(g, "score", "fwd5", min_n=4)
        per_category[cat] = _ic_summary(icc, horizon=5)

    # 多空组合：每日按得分分三档，做多头部/做空尾部，等权，按 fwd1 计日收益
    score = te.pivot_table(index="datetime", columns="symbol", values="score")
    fwd1 = te.pivot_table(index="datetime", columns="symbol", values="fwd1")
    cost = te.pivot_table(index="datetime", columns="symbol", values="cost")
    ranks = score.rank(axis=1, pct=True)
    long_mask = ranks >= 2.0 / 3.0
    short_mask = ranks <= 1.0 / 3.0
    n_long = long_mask.sum(axis=1).replace(0, np.nan)
    n_short = short_mask.sum(axis=1).replace(0, np.nan)
    weights = long_mask.div(n_long, axis=0).fillna(0.0) - short_mask.div(n_short, axis=0).fillna(0.0)
    gross = (weights * fwd1).sum(axis=1, min_count=1)
    prev_w = weights.shift(1).fillna(0.0)
    turnover = (weights - prev_w).abs().sum(axis=1)
    cost_series = ((weights - prev_w).abs() * cost).sum(axis=1, min_count=1)
    net = gross - cost_series
    equity = (1 + net.fillna(0.0)).cumprod()
    peak = equity.cummax()
    mdd = float((equity / peak - 1).min()) if len(equity) else 0.0
    return {
        "alpha": alpha,
        "features": Xcols,
        "validation_ic": ic_val,
        "test_ic_fwd5": ic_main,
        "ic_decay": decay,
        "per_year": per_year,
        "per_category": per_category,
        "portfolio": {
            "n_dates": int(len(net)),
            "sharpe_net": round(_sharpe(net.values), 6),
            "sharpe_gross": round(_sharpe(gross.values), 6),
            "total_return_net": round(float(equity.iloc[-1] - 1.0), 6) if len(equity) else 0.0,
            "max_drawdown_net": round(mdd, 6),
            "avg_daily_turnover": round(float(turnover.mean()), 6),
            "avg_cost_per_day": round(float(cost_series.mean()), 8),
            "n_symbols": int(score.shape[1]),
        },
    }


def _majority_baseline(per_symbol_raw: dict, params: dict, codes: list[str],
                       key: str, pkey: str) -> dict:
    """无技能对照：每个品种都预测「训练段多数类」，看测试段准确率。"""
    per_symbol = {}
    hit_total, n_total = 0, 0
    for c in codes:
        raw = per_symbol_raw.get(c, {}).get(key)
        maj = params.get(c, {}).get(pkey)
        if not raw or maj is None:
            continue
        true = np.asarray(raw["true_cls"])
        n = int(len(true))
        k = int(np.sum(true == int(maj)))
        per_symbol[c] = {"n": n, "accuracy": round(k / n, 6) if n else 0.0}
        hit_total += k
        n_total += n
    return {
        "pooled_accuracy": round(hit_total / n_total, 6) if n_total else 0.0,
        "per_symbol": per_symbol,
        "note": "多数类取自 train 标签分布，测试段只评估不调参",
    }


def _shuffle_control(panel: pd.DataFrame, codes: list[str], key: str,
                     seed: int, n_rep: int = 3) -> dict:
    """训练标签随机打乱对照：若准确率回落到基准率，说明原结果不是流程泄漏。"""
    rng = np.random.default_rng(seed)
    runs = []
    for _ in range(n_rep):
        preds, trues = [], []
        for code in codes:
            sub = panel[panel["symbol"] == code].set_index("datetime").sort_index()
            tr, _, te = _split(sub)
            if len(tr) < 200 or len(te) < 200:
                continue
            if key == "L1_vol_regime":
                q = tr["rv5"].quantile([1.0 / 3.0, 2.0 / 3.0]).values
                ytr = np.where(tr["rv5"].values <= q[0], 0,
                               np.where(tr["rv5"].values <= q[1], 1, 2)).astype(int)
                yte = np.where(te["rv5"].values <= q[0], 0,
                               np.where(te["rv5"].values <= q[1], 1, 2)).astype(int)
            else:
                ytr = (tr["fwd1"].values > 0).astype(int)
                yte = (te["fwd1"].values > 0).astype(int)
            ysh = ytr.copy()
            rng.shuffle(ysh)
            model = _make_clf(1.0).fit(tr[FEATURES].values, ysh)
            preds.append(model.predict(te[FEATURES].values).astype(int))
            trues.append(yte)
        acc = _accuracy(np.concatenate(preds), np.concatenate(trues))
        runs.append({"accuracy": acc["accuracy"], "base_rate": acc["base_rate"],
                     "n": acc["n"]})
    return {
        "n_rep": n_rep,
        "runs": runs,
        "mean_accuracy": round(float(np.mean([r["accuracy"] for r in runs])), 6)
        if runs else 0.0,
        "note": "训练标签随机打乱后重训（C=1 固定）；准确率应与基准率接近",
    }


# ---------------------------------------------------------------------------
# 因果性自检：扰动未来 bar，检查历史特征是否逐值不变
# ---------------------------------------------------------------------------
def _causality_check() -> dict:
    """严格证据：把第 301 根之后的行情整体放大，前 301 行特征必须完全不变。"""
    d = _load_raw("rb")
    f1 = _ts_features(d)
    d2 = d.copy()
    d2.iloc[301:, :] = d2.iloc[301:, :] * 1.5
    f2 = _ts_features(d2)
    a = f1.iloc[:301].values
    b = f2.iloc[:301].values
    same = bool(np.allclose(a, b, equal_nan=True))
    changed = bool(not np.allclose(f1.iloc[301:].values, f2.iloc[301:].values, equal_nan=True))
    return {
        "passed": same and changed,
        "checked_rows": 301,
        "history_features_unchanged": same,
        "future_features_changed": changed,
        "note": "扰动第 301 行之后的 OHLCV/OI，若前 301 行特征不变即证明无未来 bar 泄漏",
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _clean(obj):
    """把 numpy 标量/NaN 转成可 JSON 序列化的原生类型。"""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, dt.datetime)):
        return str(obj)
    return obj


def main() -> dict:
    parser = argparse.ArgumentParser(description="第三轮 B：标签体系改造实验（严格样本外）")
    parser.add_argument("--symbols", default="", help="逗号分隔的品种代码；默认使用内置 21 品种")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    warnings.filterwarnings("ignore")

    codes = [c.strip() for c in args.symbols.split(",") if c.strip()] or [s[0] for s in SYMBOLS]
    panel, meta = _build_panel(set(codes))
    print(f"[数据] 品种 {len(codes)} 个，面板 {len(panel)} 行，指纹 {meta['data_version']}")

    per_symbol_raw: dict[str, dict] = {}
    params: dict[str, dict] = {}
    n_test: dict[str, int] = {}
    for code in codes:
        sub = panel[panel["symbol"] == code].set_index("datetime").sort_index()
        res = _run_symbol(sub, code)
        per_symbol_raw[code] = res["raw"]
        params[code] = res["params"]
        tr, va, te = _split(sub)
        n_test[code] = int(len(te))
        print(f"  - {code}: train={len(tr)} val={len(va)} test={len(te)}")

    # 逐标签：per_symbol / pooled / 分年度
    labels_out: dict[str, dict] = {}
    for key in LABEL_KEYS:
        if key == "L4_cross_section":
            continue
        raws = [per_symbol_raw[c].get(key, {}) for c in codes]
        raws = [r for r in raws if r]
        if not raws:
            labels_out[key] = {"skipped": True}
            continue
        per_symbol = {c: _metrics_for(per_symbol_raw[c][key])
                      for c in codes if key in per_symbol_raw[c]}
        pooled = _metrics_for(_pool_raw(raws))
        labels_out[key] = {"pooled": pooled, "per_symbol": per_symbol}

    labels_out["L4_cross_section"] = _run_cross_section(panel)

    # 无技能对照 + 打乱标签对照（L1/L3 多分类重点核查）
    labels_out["L1_vol_regime"]["majority_train_baseline"] = _majority_baseline(
        per_symbol_raw, params, codes, "L1_vol_regime", "L1_train_majority")
    labels_out["L3_three_class"]["majority_train_baseline"] = _majority_baseline(
        per_symbol_raw, params, codes, "L3_three_class", "L3_train_majority")
    labels_out["L1_vol_regime"]["control_shuffled_labels"] = _shuffle_control(
        panel, codes, "L1_vol_regime", args.seed)
    labels_out["L0_direction"]["control_shuffled_labels"] = _shuffle_control(
        panel, codes, "L0_direction", args.seed)

    # 显著品种计数（跨品种可复现性）
    for key, metric in (("L0_direction", "hit"), ("L1_vol_regime", "accuracy"),
                        ("L2_abs_move", "hit"), ("L3_three_class", "accuracy"),
                        ("L5_interval", "coverage")):
        blocks = labels_out.get(key, {}).get("per_symbol", {})
        n_sig = sum(int(blk.get(metric, {}).get("significant", False))
                    for blk in blocks.values())
        if blocks:
            labels_out[key]["n_significant_symbols"] = n_sig
            labels_out[key]["n_symbols_evaluated"] = len(blocks)

    causality = _causality_check()

    # 缺口清单（如实记录，不夸大）
    gaps = [
        "无历史分钟线（缓存 0/71 品种有 5/15 分钟数据），无法构造日内特征与日内标签",
        "仅有主力连续合约（*0.csv），无近月/远月单合约，无法计算期限结构、基差、月差",
        "持仓量只有总量，无分席位/多空持仓结构，无法构造席位拥挤度特征",
        "无跨品种价差/比价数据（本实验仅用同日横截面排名做相对强弱）",
        "主力连续拼接未做复权/换月价差调整，跳空会污染收益与波动标签",
        "免费数据源无成交明细/盘口，无法构造订单流与微观结构特征",
    ]

    result = {
        "meta": {
            "experiment": "第三轮 B · 标签体系改造实验",
            "seed": args.seed,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "windows": {
                "train": [str(TRAIN_START.date()), "2020-12-31"],
                "validation": ["2021-01-01", "2021-12-31"],
                "test": ["2022-01-01", str(TEST_END.date())],
                "rule": "test 段不参与任何调参/特征选择；标准化与阈值只在 train 拟合",
            },
            "features_ts": TS_FEATURES,
            "features_xs": XS_FEATURES,
            "labels": {
                "L0_direction": "fwd1 涨跌方向（对照基线）",
                "L1_vol_regime": "fwd5 已实现波动率三分位（训练期分位阈值）",
                "L2_abs_move": "|fwd5| > 训练期 70 分位（门控基线信号）",
                "L3_three_class": "fwd5 大跌/震荡/大涨（训练期 30/70 分位）",
                "L4_cross_section": "同日横截面未来 5 日相对强弱（rank IC）",
                "L5_interval": "Ridge 点预测 + 验证残差 10/90 分位 → 80% 区间",
            },
            "cost_model": "手续费按手 + 1 个最小变动价位滑点（与 net_performance 一致）",
            "n_test_per_symbol": n_test,
            "symbols": meta["symbols"],
            "data_version": meta["data_version"],
            "fingerprint_scope": meta["fingerprint_scope"],
            "versions": {
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "sklearn": __import__("sklearn").__version__,
            },
        },
        "params": params,
        "labels": labels_out,
        "causality_check": causality,
        "gaps": gaps,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(_clean(result), fh, ensure_ascii=False, indent=2)

    _print_summary(result)
    print(f"\n[输出] {os.path.relpath(args.out, _PROJ_ROOT)}")
    return result


def _fmt_pct(x, nd=2):
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def _fmt(x, nd=3):
    return "n/a" if x is None else f"{float(x):.{nd}f}"


def _print_summary(res: dict) -> None:
    print("\n" + "=" * 96)
    print("标签体系对照表（全部为样本外 test 段；扣手续费+滑点）")
    print("=" * 96)
    head = f"{'标签':<16}{'n':>7}{'指标':>9}{'基准':>9}{'95%CI下':>9}{'95%CI上':>9}{'显著':>6}{'净夏普':>9}{'毛夏普':>9}"
    print(head)
    for key in LABEL_KEYS:
        blk = res["labels"].get(key, {})
        if key == "L4_cross_section":
            ic = blk["test_ic_fwd5"]
            pf = blk["portfolio"]
            if ic.get("n_dates", 0) == 0:
                print(f"{key:<16}   0     n/a   （品种数不足，rank IC 需同日 >=6 个品种）")
                continue
            print(f"{key:<16}{ic['n_dates']:>7}{_fmt(ic['mean_ic'], 4):>9}"
                  f"{'0.000':>9}{_fmt(ic['ci_low'], 4):>9}{_fmt(ic['ci_high'], 4):>9}"
                  f"{str(ic['significant']):>6}{_fmt(pf['sharpe_net']):>9}{_fmt(pf['sharpe_gross']):>9}")
            continue
        pooled = blk.get("pooled", {})
        if not pooled:
            print(f"{key:<16} skipped")
            continue
        if key == "L5_interval":
            cov = pooled["coverage"]
            net = pooled["net"]
            print(f"{key:<16}{cov['n']:>7}{_fmt_pct(cov['coverage']):>9}{'80.00%':>9}"
                  f"{_fmt_pct(cov['ci_low']):>9}{_fmt_pct(cov['ci_high']):>9}"
                  f"{str(cov['significant']):>6}{_fmt(net['sharpe']):>9}{_fmt(net['sharpe_gross']):>9}")
            continue
        if key in ("L1_vol_regime", "L3_three_class"):
            acc = pooled["accuracy"]
            metric = _fmt_pct(acc["accuracy"])
            base = _fmt_pct(acc["base_rate"])
            lo, hi = _fmt_pct(acc["ci_low"]), _fmt_pct(acc["ci_high"])
            n = acc["n"]
            sig = acc["significant"]
        else:
            hit = pooled["hit"]
            metric = _fmt_pct(hit["hit_rate"])
            base = _fmt_pct(hit["base_rate"])
            lo, hi = _fmt_pct(hit["ci_low"]), _fmt_pct(hit["ci_high"])
            n = hit["n"]
            sig = hit["significant"]
        net = pooled["net"]
        print(f"{key:<16}{n:>7}{metric:>9}{base:>9}{lo:>9}{hi:>9}"
              f"{str(sig):>6}{_fmt(net['sharpe']):>9}{_fmt(net['sharpe_gross']):>9}")
    print("=" * 96)
    l1 = res["labels"].get("L1_vol_regime", {})
    if l1:
        maj = l1.get("majority_train_baseline", {}).get("pooled_accuracy")
        shuf = l1.get("control_shuffled_labels", {}).get("mean_accuracy")
        acc = l1.get("pooled", {}).get("accuracy", {}).get("accuracy")
        print(f"L1 无技能对照: 训练多数类={_fmt_pct(maj)}；打乱训练标签后准确率={_fmt_pct(shuf)}；"
              f"原模型={_fmt_pct(acc)}")
        print(f"L1 显著品种: {l1.get('n_significant_symbols')}/{l1.get('n_symbols_evaluated')}")
    for key in ("L0_direction", "L2_abs_move", "L3_three_class", "L5_interval"):
        blk = res["labels"].get(key, {})
        if blk.get("n_symbols_evaluated"):
            print(f"{key} 显著品种: {blk.get('n_significant_symbols')}/{blk.get('n_symbols_evaluated')}")
    print("\n日期聚类稳健性（同日多品种相关，按交易日聚合 95% CI）:")
    for key in ("L0_direction", "L1_vol_regime", "L2_abs_move", "L3_three_class", "L5_interval"):
        cl = res["labels"].get(key, {}).get("pooled", {}).get("clustered", {})
        if cl.get("n_dates"):
            print(f"  {key:<16} mean={_fmt_pct(cl['mean'])} "
                  f"CI=[{_fmt_pct(cl['ci_low'])},{_fmt_pct(cl['ci_high'])}] "
                  f"base={_fmt_pct(cl['base'])} sig={cl['significant']}")
    ic = res["labels"]["L4_cross_section"]["ic_decay"]
    if ic.get("5", {}).get("n_dates", 0):
        print("L4 IC 衰减（同分数 vs 未来 1/3/5/10 日收益）: "
              + ", ".join(f"{h}日={_fmt(ic[h]['mean_ic'], 4)}" for h in ("1", "3", "5", "10")))
    else:
        print("L4 IC 衰减: 无可计算日期（品种数不足）")
    print(f"因果性自检: {'PASS' if res['causality_check']['passed'] else 'FAIL'}"
          f"（前 {res['causality_check']['checked_rows']} 行特征不受未来扰动影响）")


if __name__ == "__main__":
    main()
