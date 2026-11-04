"""第五轮第 2 步：波动率门控验证（21 品种，与标签实验同一测试段）。

基线 = 标签实验的方向模型（L0，p_up − 0.5 取符号）；
门控 = 用 L1 波动率三分位预测调仓：低波动×1.5、中×1.0、高×0.5；可选高波动收紧止损。
明确说明：这是**风险管理层面的仓位/止损调整，不是方向信号**。

三种口径
--------
1. before   ：仅 L0 方向信号，仓位 ±1（对照组）；
2. gate_only：L0 方向 × 波动率档位缩放（1.5 / 1.0 / 0.5），不止损；
3. gate_stop：在 gate_only 基础上，高波动档把止损从 3.0×ATR 收紧到 1.5×ATR，
              交易累计浮亏超过阈值即平仓，信号翻转后重新入场。

约束：全部离线（复用 data/sina_cache），不联网、不装包、不改 ui/ 与数据库。
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PROJ_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import label_research as lr  # noqa: E402
from futures_quant.ai.evaluation import estimate_cost_rate  # noqa: E402
from futures_quant.data.contract_specs import get_contract_spec  # noqa: E402

OUT_JSON = os.path.join(_PROJ_ROOT, "scripts", "research", "output", "phase5_vol_gating.json")
SCALE = {0: 1.5, 1: 1.0, 2: 0.5}   # 低波动放大、高波动降杠杆
STOP_K = {0: 3.0, 1: 3.0, 2: 1.5}  # 高波动收紧止损（ATR 倍数）
FIELDS = ("before", "gate_only", "gate_stop")


def _mdd(rets: np.ndarray) -> float:
    """最大回撤（净值口径，负值）。"""
    if rets.size == 0:
        return 0.0
    eq = np.cumprod(1.0 + np.asarray(rets, float))
    peak = np.maximum.accumulate(eq)
    return float(np.min(np.where(peak > 0, (eq - peak) / peak, 0.0)))


def _metrics(net: np.ndarray, gross: np.ndarray, turn: np.ndarray,
             pos: np.ndarray, periods_per_year: int = 252) -> dict:
    """与 evaluation.net_performance 同口径的日频指标。"""
    net = np.asarray(net, float)
    gross = np.asarray(gross, float)
    turn = np.asarray(turn, float)
    pos = np.asarray(pos, float)
    n = int(net.size)
    n_years = max(n / float(periods_per_year), 1e-9)
    return {
        "n": n,
        "sharpe_net": round(lr._sharpe(net), 4),
        "sharpe_gross": round(lr._sharpe(gross), 4),
        "mdd_net": round(_mdd(net), 4),
        "mdd_gross": round(_mdd(gross), 4),
        "total_return_net": round(float(np.prod(1 + net) - 1), 4),
        "annual_turnover": round(float(np.sum(turn) / n_years), 3),
        "avg_abs_pos": round(float(np.mean(np.abs(pos))), 4),
    }


def _stopped_positions(base_dir: np.ndarray, actual: np.ndarray,
                       atr: np.ndarray, regime: np.ndarray) -> np.ndarray:
    """止损版仓位：交易累计浮亏超过 k×ATR 即平仓，信号翻转后重新入场。

    说明：cum 与 atr 都是**归一化收益**量纲（atr14 已是 ATR/收盘价），
    因此同量纲可直接比较；仓位带缩放后浮亏也按缩放后的手数累计。
    """
    n = len(base_dir)
    pos = np.zeros(n, float)
    state = 0.0
    cum = 0.0
    for i in range(n):
        pos[i] = state
        if state != 0.0:
            cum += state * actual[i]
            k = STOP_K.get(2, 3.0) if not np.isfinite(regime[i]) else STOP_K.get(int(regime[i]), 3.0)
            if cum <= -k * atr[i]:
                state, cum = 0.0, 0.0
        sig = base_dir[i]
        if state != 0.0 and sig != state:
            state, cum = 0.0, 0.0
        if state == 0.0 and np.isfinite(sig) and sig != 0.0:
            state, cum = sig, 0.0
    return pos


def _book(pos: np.ndarray, actual: np.ndarray, cost: float, idx: pd.Index) -> tuple[dict, pd.DataFrame]:
    """把仓位序列结算成指标 + 逐日净值序列（供等权合并）。"""
    prev = np.concatenate([[0.0], pos[:-1]])
    turn = np.abs(pos - prev)
    gross = pos * actual
    net = gross - turn * cost
    met = _metrics(net, gross, turn, pos)
    ser = pd.DataFrame({"net": net, "gross": gross, "turn": turn, "pos": pos},
                       index=idx)
    return met, ser


def _run_symbol(df: pd.DataFrame, code: str) -> dict:
    """单品种：训练 L0 方向 + L1 波动率模型，产出三种口径的结果与逐日序列。"""
    tr, va, te = lr._split(df)
    if len(tr) < 200 or len(va) < 60 or len(te) < 200:
        return {"ok": False, "reason": f"样本不足 tr={len(tr)} va={len(va)} te={len(te)}"}

    Xtr, Xva, Xte = tr[lr.FEATURES].values, va[lr.FEATURES].values, te[lr.FEATURES].values

    # 方向模型（与标签实验一致：验证段选 C，测试段不参与）
    model, C, _ = lr._fit_classifier(Xtr, (tr["fwd1"].values > 0).astype(int),
                                     Xva, (va["fwd1"].values > 0).astype(int))
    p_te = lr._prob_up(model, Xte)
    base_dir = np.sign(p_te - 0.5)

    # 波动率三分位模型（L1）：分档阈值只在训练段拟合，验证段选 C
    q_vol = tr["rv5"].quantile([1.0 / 3.0, 2.0 / 3.0]).values

    def _cls(s: pd.Series) -> np.ndarray:
        v = s.values
        return np.where(v <= q_vol[0], 0, np.where(v <= q_vol[1], 1, 2)).astype(int)

    model_v, C_v, vacc_v = lr._fit_classifier(Xtr, _cls(tr["rv5"]), Xva, _cls(va["rv5"]))
    regime = model_v.predict(Xte).astype(int)

    spec = get_contract_spec(code)
    cost = float(np.asarray(estimate_cost_rate(
        te["close"].values, multiplier=spec["multiplier"],
        commission_per_lot=spec["commission_per_lot"],
        slippage_ticks=1.0, min_price_tick=spec["min_price_tick"])).reshape(-1)[0])

    actual = te["fwd1"].values.astype(float)
    atr = te["atr14"].values.astype(float)
    idx = te.index

    scale = np.array([SCALE.get(int(r), 1.0) for r in regime])
    pos_gate = base_dir * scale
    pos_stop = _stopped_positions(pos_gate, actual, atr, regime)

    metrics: dict = {}
    series: dict = {}
    for field, pos in (("before", base_dir), ("gate_only", pos_gate), ("gate_stop", pos_stop)):
        metrics[field], series[field] = _book(pos, actual, cost, idx)

    return {
        "ok": True, "n_test": int(len(te)), "cost_rate": round(cost, 6),
        "params": {
            "L0_C": float(C), "L1_C": float(C_v), "L1_val_acc": round(float(vacc_v), 6),
            "q_vol": [round(float(x), 8) for x in q_vol],
            "regime_counts": [int(x) for x in np.bincount(regime, minlength=3)],
        },
        "metrics": metrics, "series": series,
        "baseline_net_performance": lr._net(base_dir, actual, cost),
    }


def _pooled(series_map: dict[str, pd.DataFrame], field: str) -> dict:
    """多品种等权合并：逐日净值取横截面均值后重算指标（分散化效应）。"""
    frames = [s[field] for s in series_map.values() if field in s]
    if not frames:
        return {"n_days": 0, "sharpe_net": 0.0, "sharpe_gross": 0.0, "mdd_net": 0.0,
                "annual_turnover": 0.0, "avg_abs_pos": 0.0, "n_symbols": 0}
    allf = pd.concat(frames, axis=0)
    daily = allf.groupby(level=0).mean().sort_index()
    met = _metrics(daily["net"].to_numpy(), daily["gross"].to_numpy(),
                   daily["turn"].to_numpy(), daily["pos"].to_numpy())
    met["n_days"] = int(len(daily))
    met["n_symbols"] = len(frames)
    return met


def main() -> int:
    t0 = time.time()
    codes = [s[0] for s in lr.SYMBOLS]
    panel, meta = lr._build_panel(codes)
    panel = panel.set_index("datetime").sort_index()

    rows: dict = {}
    series_map: dict = {}
    skipped: dict = {}
    for code in codes:
        df = panel[panel["symbol"] == code]
        r = _run_symbol(df, code)
        if not r.get("ok"):
            skipped[code] = r.get("reason", "unknown")
            continue
        series_map[code] = r.pop("series")
        rows[code] = r

    pooled = {f: _pooled(series_map, f) for f in FIELDS}
    by_category: dict = {}
    for code, r in rows.items():
        cat = lr.SYMBOLS[[s[0] for s in lr.SYMBOLS].index(code)][1]
        by_category.setdefault(cat, {"symbols": [], "before": [], "gate_only": [], "gate_stop": []})
        by_category[cat]["symbols"].append(code)
        for f in FIELDS:
            by_category[cat][f].append(r["metrics"][f]["sharpe_net"])
    for cat, d in by_category.items():
        d["mean_sharpe_net"] = {
            f: round(float(np.nanmean(d[f])), 4) for f in FIELDS
        }

    out = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seed": lr.SEED, "data_version": meta["data_version"],
            "test_window": [str(lr.TEST_START.date()), str(lr.TEST_END.date())],
            "n_symbols": len(rows), "skipped": skipped,
            "scale": {str(k): v for k, v in SCALE.items()},
            "stop_k": {str(k): v for k, v in STOP_K.items()},
            "note": ("波动率门控是风险管理（仓位/止损），不是方向信号；"
                     "基线方向模型本身无边际，门控只改变风险暴露"),
        },
        "pooled": pooled, "by_category": by_category,
        "per_symbol": rows,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, default=str)

    print(f"完成 {len(rows)} 品种，跳过 {len(skipped)}，耗时 {time.time() - t0:.1f}s")
    print(f"{'口径':<12}{'净夏普':>9}{'毛夏普':>9}{'净MDD':>9}{'年换手':>9}{'均仓位':>9}")
    for f in FIELDS:
        m = pooled[f]
        print(f"{f:<12}{m['sharpe_net']:>9.4f}{m['sharpe_gross']:>9.4f}"
              f"{m['mdd_net']:>9.4f}{m['annual_turnover']:>9.3f}{m['avg_abs_pos']:>9.4f}")
    print(f"-> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
