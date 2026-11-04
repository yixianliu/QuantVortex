"""统一样本外评估口径（第三轮 A · P0）。

本模块是「命中率 / 策略净值」的唯一实现，供 predictor、calibration_replay、
validation 与报告脚本共用，避免同一指标在不同页面各写一套口径。

统一口径
--------
1. 命中判定（方向准确率）
   - `pred` 与 `actual` 必须是**同一样本、同一预测窗口**的收益（推荐对数收益或
     百分比收益），且只允许样本外（OOS）样本进入；
   - `pred > threshold` → 看多，`pred <= threshold` → 看空；`threshold` 默认 0，
     可传标量或逐样本数组（如 walk-forward 每折训练段中位数）；
   - `|pred| <= neutral_band` 的样本判为「中性」，**不计入命中率**，单独统计
     `n_neutral`，避免「不表态也被算作命中」；
   - 实际方向以 `actual > 0` 为涨、`actual <= 0` 为跌（0 视为跌，保守处理）。

2. 基准率（涨跌平衡基线）
   - `base_rate = max(实际上涨占比, 实际下跌占比)`，即「无脑永远做多/做空」的最好
     成绩。命中率必须与基准率同时报告，否则在单边行情里 60% 命中率可能毫无技能；
   - `edge = hit_rate - base_rate`，并给出 Wilson 95% 置信区间；仅当
     `ci_low > base_rate` 才标记 `significant=True`。

3. 策略净值
   - 预测信号 → 仓位（±1/0）→ **下一根真实收益** − 换手成本（手续费 + 滑点），
     禁止再把 `val_preds` 直接当策略收益；
   - 夏普/最大回撤/总收益全部基于扣费后的净值曲线；同时保留毛收益口径用于对照，
     以便量化「原口径虚高多少」。
"""
from __future__ import annotations

import math
from typing import Optional, Sequence, Union

import numpy as np

#: 默认命中阈值（0 = 以收益正负号判方向）
DEFAULT_HIT_THRESHOLD = 0.0
#: 默认中性带（0 = 任何非零预测都表态）
DEFAULT_NEUTRAL_BAND = 0.0
#: 95% 双侧正态分位数
Z_95 = 1.959963984540054


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson 置信区间（二项比例），小样本下优于正态近似。"""
    if n <= 0:
        return 0.0, 1.0
    p = float(k) / float(n)
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(max(p * (1.0 - p) / n + z * z / (4.0 * n * n), 0.0)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _as_aligned(arr, n: int, default: float = 0.0) -> np.ndarray:
    """把标量/序列统一成与样本数对齐的 float 数组。"""
    if arr is None:
        return np.full(n, float(default), dtype=float)
    a = np.asarray(arr, dtype=float).reshape(-1)
    if a.size == 1:
        return np.full(n, float(a[0]), dtype=float)
    if a.size != n:
        raise ValueError(f"参数长度 {a.size} 与样本数 {n} 不一致")
    return a


def directional_hit_rate(
    pred: Sequence[float],
    actual: Sequence[float],
    threshold: Union[float, Sequence[float]] = DEFAULT_HIT_THRESHOLD,
    neutral_band: Union[float, Sequence[float]] = DEFAULT_NEUTRAL_BAND,
) -> dict:
    """计算统一的样本外方向命中率（含基准率与置信区间）。

    参数:
        pred: 预测收益序列（样本外，同一预测窗口）。
        actual: 对应实际收益序列（与 pred 一一对齐）。
        threshold: 看多/看空分界（标量或逐样本数组）。
        neutral_band: 中性带；`|pred| <= neutral_band` 的样本不计入命中率。

    返回:
        dict，字段见模块 docstring；`n` 为参与判定的有效样本数。
    """
    p = np.asarray(pred, dtype=float).reshape(-1)
    a = np.asarray(actual, dtype=float).reshape(-1)
    if p.size != a.size:
        raise ValueError(f"pred({p.size}) 与 actual({a.size}) 长度不一致")
    n_all = int(p.size)
    if n_all == 0:
        return {
            "n": 0, "n_hit": 0, "hit_rate": 0.0, "base_rate": 0.0, "edge": 0.0,
            "ci_low": 0.0, "ci_high": 1.0, "n_neutral": 0, "up_rate": 0.0,
            "threshold": float(np.asarray(threshold).reshape(-1)[0]) if np.asarray(threshold).size else 0.0,
            "neutral_band": float(np.asarray(neutral_band).reshape(-1)[0]) if np.asarray(neutral_band).size else 0.0,
            "significant": False,
            "criterion": "empty",
        }

    ok = np.isfinite(p) & np.isfinite(a)
    p, a = p[ok], a[ok]
    n_all = int(p.size)
    thr = _as_aligned(threshold, n_all, DEFAULT_HIT_THRESHOLD)
    band = np.abs(_as_aligned(neutral_band, n_all, DEFAULT_NEUTRAL_BAND))

    active = np.abs(p) > band
    n = int(active.sum())
    n_neutral = n_all - n
    if n == 0:
        return {
            "n": 0, "n_hit": 0, "hit_rate": 0.0, "base_rate": 0.0, "edge": 0.0,
            "ci_low": 0.0, "ci_high": 1.0, "n_neutral": n_neutral, "up_rate": 0.0,
            "threshold": float(np.nanmedian(thr)) if n_all else DEFAULT_HIT_THRESHOLD,
            "neutral_band": float(np.nanmedian(band)) if n_all else DEFAULT_NEUTRAL_BAND,
            "significant": False,
            "criterion": "all_neutral",
        }

    pred_up = p[active] > thr[active]
    actual_up = a[active] > 0.0
    hits = pred_up == actual_up
    n_hit = int(hits.sum())
    hit_rate = float(n_hit) / n

    up_rate = float(actual_up.mean())
    base_rate = max(up_rate, 1.0 - up_rate)
    ci_low, ci_high = wilson_interval(n_hit, n)
    edge = hit_rate - base_rate
    return {
        "n": n,
        "n_hit": n_hit,
        "hit_rate": round(hit_rate, 6),
        "base_rate": round(base_rate, 6),
        "edge": round(edge, 6),
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "n_neutral": int(n_neutral),
        "up_rate": round(up_rate, 6),
        "threshold": float(np.nanmedian(thr)),
        "neutral_band": float(np.nanmedian(band)),
        "significant": bool(ci_low > base_rate),
        "criterion": ("pred>threshold=long / actual>0=up；|pred|<=neutral_band 不计入；"
                      "base_rate=max(涨占比,跌占比)；CI=Wilson95%"),
    }


def probability_is_hit(p_up: float, actual_up: int, threshold: float = 0.5) -> int:
    """分类模型单样本命中：`p_up >= threshold` 看多，否则看空；涨跌与预测一致即命中。"""
    return int((p_up >= float(threshold)) == (int(actual_up) == 1))


def probability_hit_rate(
    p_up: Sequence[float],
    actual_up: Sequence[int],
    threshold: float = 0.5,
) -> dict:
    """分类模型（p_up）的统一命中率口径，与回归口径共用基准率/置信区间规则。"""
    p = np.asarray(p_up, dtype=float).reshape(-1)
    a = np.asarray(actual_up, dtype=float).reshape(-1)
    if p.size != a.size:
        raise ValueError(f"p_up({p.size}) 与 actual_up({a.size}) 长度不一致")
    ok = np.isfinite(p) & np.isfinite(a)
    p, a = p[ok], a[ok]
    n = int(p.size)
    if n == 0:
        return {"n": 0, "n_hit": 0, "hit_rate": 0.0, "base_rate": 0.0, "edge": 0.0,
                "ci_low": 0.0, "ci_high": 1.0, "up_rate": 0.0,
                "threshold": float(threshold), "significant": False,
                "criterion": "probability: p_up>=threshold=long; base_rate=max(up,down)"}
    pred_up = p >= float(threshold)
    actual_up = a >= 0.5
    n_hit = int(np.sum(pred_up == actual_up))
    up_rate = float(actual_up.mean())
    base_rate = max(up_rate, 1.0 - up_rate)
    ci_low, ci_high = wilson_interval(n_hit, n)
    return {
        "n": n, "n_hit": n_hit,
        "hit_rate": round(float(n_hit) / n, 6),
        "base_rate": round(base_rate, 6),
        "edge": round(float(n_hit) / n - base_rate, 6),
        "ci_low": round(ci_low, 6), "ci_high": round(ci_high, 6),
        "up_rate": round(up_rate, 6),
        "threshold": float(threshold),
        "significant": bool(ci_low > base_rate),
        "criterion": ("probability: p_up>=threshold=long；actual_up>=0.5=up；"
                      "base_rate=max(涨占比,跌占比)；CI=Wilson95%"),
    }


def positions_from_signals(
    pred: Sequence[float],
    threshold: Union[float, Sequence[float]] = DEFAULT_HIT_THRESHOLD,
    neutral_band: Union[float, Sequence[float]] = DEFAULT_NEUTRAL_BAND,
) -> np.ndarray:
    """预测收益 → 目标仓位（+1 多 / -1 空 / 0 中性）。"""
    p = np.asarray(pred, dtype=float).reshape(-1)
    n = p.size
    thr = _as_aligned(threshold, n, DEFAULT_HIT_THRESHOLD)
    band = np.abs(_as_aligned(neutral_band, n, DEFAULT_NEUTRAL_BAND))
    return np.where(p > thr, 1.0, np.where(p < -band, -1.0, 0.0))


def estimate_cost_rate(
    price: Union[float, Sequence[float]],
    multiplier: float = 10.0,
    commission_per_lot: float = 3.0,
    slippage_ticks: float = 1.0,
    min_price_tick: float = 1.0,
) -> np.ndarray:
    """单边交易成本（占名义价值的比例）。

    与 `BacktestBroker` 默认口径一致：每手固定手续费 + 1 个最小变动价位滑点，
    再按「价格 × 乘数」折算为收益率比例。价格 <= 0 时返回 0（由调用方兜底）。
    """
    px = np.asarray(price, dtype=float)
    safe = np.where(px > 0, px, np.nan)
    fee = commission_per_lot / (safe * float(multiplier))
    slip = float(slippage_ticks) * float(min_price_tick) / safe
    out = np.nan_to_num(fee + slip, nan=0.0, posinf=0.0, neginf=0.0)
    return out


def net_performance(
    pred: Sequence[float],
    actual: Sequence[float],
    cost_rate: Union[float, Sequence[float]] = 0.0,
    threshold: Union[float, Sequence[float]] = DEFAULT_HIT_THRESHOLD,
    neutral_band: Union[float, Sequence[float]] = DEFAULT_NEUTRAL_BAND,
    periods_per_year: int = 252,
    risk_free_annual: float = 0.02,
) -> dict:
    """预测信号 → 扣费后策略净值，产出夏普 / 回撤 / 总收益。

    规则（严格因果）：
      - 第 t 个样本的预测只决定第 t 个样本对应窗口的仓位；
      - 收益取该窗口的**真实下一根收益** `actual[t]`；
      - 换手成本 = `|position[t] - position[t-1]| × cost_rate[t]`，首个样本按从空仓
        建仓计一次成本；
      - 净值 = cumprod(1 + net_returns)；毛口径（成本置 0）同时返回用于对照。
    """
    p = np.asarray(pred, dtype=float).reshape(-1)
    a = np.asarray(actual, dtype=float).reshape(-1)
    if p.size != a.size:
        raise ValueError(f"pred({p.size}) 与 actual({a.size}) 长度不一致")
    n = int(p.size)
    if n == 0:
        return {
            "n": 0, "sharpe": 0.0, "max_drawdown": 0.0, "total_return": 0.0,
            "sharpe_gross": 0.0, "max_drawdown_gross": 0.0,
            "total_return_gross": 0.0, "total_cost": 0.0, "turnover": 0.0,
            "equity_curve": np.empty(0), "net_returns": np.empty(0),
            "avg_cost_bps": 0.0,
        }

    pos = positions_from_signals(p, threshold, neutral_band)
    cost = _as_aligned(cost_rate, n, 0.0)
    prev = np.concatenate([[0.0], pos[:-1]])
    turnover_arr = np.abs(pos - prev)
    net = pos * a - turnover_arr * cost

    def _curve_stats(rets: np.ndarray) -> tuple[float, float, float]:
        if rets.size == 0:
            return 0.0, 0.0, 0.0
        rf_daily = float(risk_free_annual) / float(periods_per_year)
        excess = rets - rf_daily
        sd = float(np.std(excess))
        sharpe = (float(np.mean(excess)) / sd * math.sqrt(periods_per_year)) if sd > 1e-12 else 0.0
        equity = np.cumprod(1.0 + rets)
        peak = np.maximum.accumulate(equity)
        dd = np.where(peak > 0, (equity - peak) / peak, 0.0)
        return (float(sharpe), float(dd.min()) if dd.size else 0.0,
                float(equity[-1] - 1.0) if equity.size else 0.0)

    sharpe, mdd, total = _curve_stats(net)
    sharpe_g, mdd_g, total_g = _curve_stats(pos * a)
    equity = np.cumprod(1.0 + net)

    return {
        "n": n,
        "sharpe": round(sharpe, 6),
        "max_drawdown": round(mdd, 6),
        "total_return": round(total, 6),
        "sharpe_gross": round(sharpe_g, 6),
        "max_drawdown_gross": round(mdd_g, 6),
        "total_return_gross": round(total_g, 6),
        "total_cost": round(float(np.sum(turnover_arr * cost)), 6),
        "turnover": round(float(np.sum(turnover_arr)), 6),
        "avg_cost_bps": round(float(np.mean(cost)) * 1e4, 4) if n else 0.0,
        "equity_curve": equity,
        "net_returns": net,
    }


def summarize_old_vs_new(pred: Sequence[float], actual: Sequence[float],
                         old_thresholds: Optional[Sequence[float]] = None) -> dict:
    """生成「旧口径 vs 新口径」对照（供报告/回归测试使用）。

    旧口径复刻改造前 `_evaluate_core` 的两处写法：
      - 命中率：`(pred > thr) == (actual > thr)`，thr 缺省 0；
      - 夏普/回撤：直接把 `pred` 当策略收益，`cumprod(1 + pred)`。
    """
    p = np.asarray(pred, dtype=float).reshape(-1)
    a = np.asarray(actual, dtype=float).reshape(-1)
    n = int(p.size)
    thr = _as_aligned(old_thresholds if old_thresholds is not None else 0.0, n, 0.0)
    old_hit = float(np.mean((p > thr).astype(int) == (a > thr).astype(int))) if n else 0.0
    old_sharpe = 0.0
    old_mdd = 0.0
    if n and float(np.std(p)) > 1e-12:
        rf = 0.02 / 252.0
        excess = p - rf
        old_sharpe = float(np.mean(excess) / np.std(excess) * math.sqrt(252.0))
        eq = np.cumprod(1.0 + p)
        peak = np.maximum.accumulate(eq)
        old_mdd = float(((eq - peak) / peak).min())
    new_hit = directional_hit_rate(p, a)
    return {
        "old_hit_rate": round(old_hit, 6),
        "new_hit_rate": new_hit["hit_rate"],
        "base_rate": new_hit["base_rate"],
        "old_sharpe": round(old_sharpe, 6),
        "old_max_drawdown": round(old_mdd, 6),
        "n": n,
    }


# ---------------------------------------------------------------------------
# 第六轮：预测区间「真实覆盖率」回溯
# ---------------------------------------------------------------------------
#: 区间覆盖率的最小样本门槛；少于该门槛一律返回 None + 原因，不给出伪精确数字
MIN_INTERVAL_SAMPLES = 30
#: ±1σ 正态区间的名义覆盖率
NOMINAL_ONE_SIGMA = 0.6826894921370859


def nominal_coverage_from_multiplier(k: float) -> float:
    """由 σ 乘数 k 计算正态假设下的名义覆盖率：``erf(k / sqrt(2))``。"""
    try:
        k = float(k)
        if not math.isfinite(k) or k <= 0:
            return NOMINAL_ONE_SIGMA
        return float(math.erf(k / math.sqrt(2.0)))
    except (TypeError, ValueError):
        return NOMINAL_ONE_SIGMA


def _row_get(row, key, default=None):
    """兼容 dict / sqlite.Row / 普通对象的字段读取。"""
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return getattr(row, key, default)


def _finite(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _prepare_interval_rows(rows, actual_return_is_pct: bool = True) -> list[dict]:
    """把已结算预测整理成区间核算样本。

    必需字段：``last_close / lower / upper / actual_return_pct``。
    - ``actual_return_pct`` 默认按「百分比收益」解释（与 predictions 表口径一致）；
    - 老数据 ``lower/upper`` 为 NULL，或上下界非正/倒挂、价格非有限，一律剔除；
    - 只做事实核算，**不**用残差 σ 现算区间补洞。
    """
    out: list[dict] = []
    for row in rows or []:
        last = _finite(_row_get(row, "last_close"))
        lo = _finite(_row_get(row, "lower"))
        up = _finite(_row_get(row, "upper"))
        act_pct = _finite(_row_get(row, "actual_return_pct"))
        if last is None or last <= 0 or lo is None or up is None or act_pct is None:
            continue
        if lo <= 0 or up <= lo:
            continue
        try:
            h = int(_finite(_row_get(row, "horizon")) or 0)
        except (TypeError, ValueError):
            h = 0
        actual_price = last * (1.0 + act_pct / 100.0) if actual_return_is_pct \
            else last * (1.0 + act_pct)
        if not math.isfinite(actual_price) or actual_price <= 0:
            continue
        # 区间必须换算成「相对预测起点价的 log 收益」后再标准化；
        # 直接对绝对价格取 log 会把 ln(last_close) 当成漂移，导致 z 爆炸。
        rel_up = math.log(up / last)
        rel_lo = math.log(lo / last)
        center_log = 0.5 * (rel_up + rel_lo)
        half_log = 0.5 * (rel_up - rel_lo)
        if not math.isfinite(half_log) or half_log <= 0:
            continue
        z = abs(math.log(actual_price / last) - center_log) / half_log
        sigma = _finite(_row_get(row, "band_sigma"))
        sigma_h = float(sigma) * math.sqrt(h) if (sigma and sigma > 0 and h > 0) \
            else half_log
        if not math.isfinite(sigma_h) or sigma_h <= 0:
            sigma_h = half_log
        out.append({
            "symbol": str(_row_get(row, "symbol") or "UNKNOWN"),
            "horizon": h,
            "hit": bool(lo <= actual_price <= up),
            "z": float(z),
            "half_log": float(half_log),
            "sigma_h": float(sigma_h),
            "rel_sigma": float(sigma_h) / float(last),
            "last_close": float(last),
            "actual_price": float(actual_price),
            # 校准切分必须按「预测时间」排序，不能按写库时间（回放时写库时间相同）
            "ts": str(_row_get(row, "ts") or _row_get(row, "closed_ts") or ""),
        })
    return out


def _coverage_stats(samples: list[dict], nominal: float,
                    min_samples: int, reason_empty: str = "无可用区间样本") -> dict:
    """计算单组的命中比例、Wilson 区间与「过度覆盖/覆盖不足」判定。"""
    n = len(samples)
    hits = int(sum(1 for s in samples if s["hit"]))
    base = {
        "n": n,
        "n_hit": hits,
        "nominal": round(float(nominal), 6),
    }
    if n == 0:
        base.update({"coverage": None, "ci_low": None, "ci_high": None,
                     "deviation_pp": None, "verdict": "insufficient",
                     "verdict_text": "无样本", "reason": reason_empty})
        return base
    coverage = hits / n
    ci_low, ci_high = wilson_interval(hits, n)
    base.update({"coverage": round(coverage, 6),
                 "ci_low": round(ci_low, 6), "ci_high": round(ci_high, 6)})
    if n < int(min_samples):
        # 样本不足：只回观测比例供排查，coverage 必须为 None，禁止伪精确结论
        base.update({"coverage": None, "ci_low": None, "ci_high": None,
                     "observed_rate": round(coverage, 6),
                     "deviation_pp": round((coverage - nominal) * 100.0, 2),
                     "verdict": "insufficient", "verdict_text": "样本不足",
                     "reason": f"样本数 {n} < {min_samples}，不给覆盖率结论"})
        return base
    if ci_low > nominal:
        verdict, text = "over", "过度覆盖"
    elif ci_high < nominal:
        verdict, text = "under", "覆盖不足"
    else:
        verdict, text = "aligned", "与名义水平一致"
    base.update({"deviation_pp": round((coverage - nominal) * 100.0, 2),
                 "verdict": verdict, "verdict_text": text, "reason": None})
    return base


def _nominal_from_samples(samples: list[dict], default: float = NOMINAL_ONE_SIGMA) -> float:
    """由「区间半宽 / (band_sigma*sqrt(h))」的中位数反推名义覆盖率。

    落库区间按 ±1σ 构造时该比值约为 1（名义 68.27%）；若历史上修改过
    乘数，这里能自动跟随，避免拿错名义水平做判定。
    """
    ks = [s["half_log"] / s["sigma_h"] for s in samples
          if s.get("sigma_h") and s["sigma_h"] > 0]
    if not ks:
        return float(default)
    return nominal_coverage_from_multiplier(float(np.median(ks)))


def _sort_by_time(samples: list[dict]) -> list[dict]:
    """按时间升序排序；时间缺失时保持原顺序并原样返回。"""
    if samples and all(s.get("ts") for s in samples):
        return sorted(samples, key=lambda s: s["ts"])
    return samples


def _as_interval_samples(rows) -> list[dict]:
    """接受「原始预测行」或「已整理样本」两种输入，统一成整理后的样本。"""
    rows = list(rows or [])
    if rows and all(isinstance(r, dict) and "z" in r and "half_log" in r for r in rows):
        return rows
    return _prepare_interval_rows(rows)


def interval_coverage(rows, nominal: Optional[float] = None,
                      min_samples: int = MIN_INTERVAL_SAMPLES,
                      actual_return_is_pct: bool = True) -> dict:
    """计算已结算预测的**真实区间覆盖率**（第六轮核心口径）。

    参数
    ----
    rows : 来自 ``AnalysisStore.query_closed_with_bands`` 的字典序列；也可传
        任意含 ``last_close/lower/upper/actual_return_pct/symbol/horizon`` 的行。
    nominal : 名义覆盖率；缺省时按落库的 σ 乘数反推（±1σ ≈ 68.27%）。
    min_samples : 少于该样本数分组一律返回 None + 原因（默认 30）。
    actual_return_is_pct : ``actual_return_pct`` 是否为百分比口径（默认 True）。

    返回
    ----
    dict：``coverage``（None 表示不可用）、``n``、``ci_low/ci_high``、
    ``verdict``（over/under/aligned/insufficient）、``by_symbol``、
    ``by_horizon``、``by_volatility``、``calibration``。UI 接口必须原样透传
    None 与 ``reason``，**禁止**回退成残差 σ 近似值。
    """
    samples = _prepare_interval_rows(rows, actual_return_is_pct=actual_return_is_pct)
    nominal_value = float(nominal) if nominal is not None else \
        _nominal_from_samples(samples)

    overall = _coverage_stats(samples, nominal_value, min_samples)
    reason = overall.get("reason")
    if overall["n"] == 0:
        reason = "无可用区间样本（lower/upper 为空；迁移前老数据需新预测落库后才有真实覆盖率）"
        overall["reason"] = reason

    # 按品种
    by_symbol: dict[str, dict] = {}
    for sym in sorted({s["symbol"] for s in samples}):
        by_symbol[sym] = _coverage_stats(
            [s for s in samples if s["symbol"] == sym], nominal_value, min_samples)

    # 按 horizon
    by_horizon: dict[str, dict] = {}
    for h in sorted({s["horizon"] for s in samples}):
        by_horizon[str(h)] = _coverage_stats(
            [s for s in samples if s["horizon"] == h], nominal_value, min_samples,
            reason_empty=f"horizon={h} 无可用样本")

    # 按波动分层（相对区间宽度 = sigma_h / last_close，三分位）
    by_vol: dict[str, dict] = {}
    rel = np.asarray([s["rel_sigma"] for s in samples], dtype=float)
    if rel.size >= 3:
        q1, q2 = np.quantile(rel, [1.0 / 3.0, 2.0 / 3.0])
        buckets = {"low": [], "mid": [], "high": []}
        for s in samples:
            v = s["rel_sigma"]
            key = "low" if v <= q1 else ("mid" if v <= q2 else "high")
            buckets[key].append(s)
        for key in ("low", "mid", "high"):
            by_vol[key] = _coverage_stats(buckets[key], nominal_value, min_samples,
                                          reason_empty=f"波动分层 {key} 无可用样本")
        by_vol["cut_points"] = [round(float(q1), 8), round(float(q2), 8)]
    elif samples:
        by_vol["insufficient"] = {
            "n": int(rel.size), "coverage": None,
            "reason": "波动分层至少需要 3 个样本", "verdict": "insufficient",
        }

    calibration = recommend_band_multiplier(
        rows, target=nominal_value, min_train=min_samples, min_test=min_samples,
        actual_return_is_pct=actual_return_is_pct)

    return {
        "available": overall.get("coverage") is not None,
        "coverage": overall.get("coverage"),
        "observed_rate": overall.get("observed_rate"),
        "n": overall["n"],
        "n_hit": overall["n_hit"],
        "nominal": round(nominal_value, 6),
        "ci_low": overall.get("ci_low"),
        "ci_high": overall.get("ci_high"),
        "deviation_pp": overall.get("deviation_pp"),
        "verdict": overall.get("verdict"),
        "verdict_text": overall.get("verdict_text"),
        "reason": overall.get("reason"),
        "criterion": "实际价格是否落在预测产出时落库的 [lower, upper]；不是按残差 σ 现算的近似",
        "by_symbol": by_symbol,
        "by_horizon": by_horizon,
        "by_volatility": by_vol,
        "calibration": calibration,
    }


def recommend_band_multiplier(rows, target: Optional[float] = None,
                              min_train: int = MIN_INTERVAL_SAMPLES,
                              min_test: int = MIN_INTERVAL_SAMPLES,
                              train_ratio: float = 0.7,
                              actual_return_is_pct: bool = True) -> dict:
    """在**训练段**拟合 σ 乘数 k'，在**测试段**验证（严禁用测试段定参）。

    做法：对每个样本取标准化残差
    ``z = |ln(实际价/预测基准价) - 区间中心| / 区间半宽``，
    在训练段取 ``target`` 分位数得到 ``k'``；再用 k' 在测试段重算命中率。
    若训练/测试任一段样本不足，返回 ``k_prime=None`` 与原因。

    ``target`` 缺省时用训练段区间反推的名义覆盖率（默认 ±1σ ≈ 68.27%）。
    """
    samples = _sort_by_time(_as_interval_samples(rows))
    if samples and isinstance(samples[0], dict) and "actual_return_pct" in samples[0]:
        # 原始预测行：按调用方给定的收益口径重新整理
        samples = _sort_by_time(_prepare_interval_rows(
            rows, actual_return_is_pct=actual_return_is_pct))
    n = len(samples)
    if n < int(min_train) + int(min_test):
        return {"available": False, "k_prime": None, "k_old": None,
                "train_n": max(0, min(n, int(n * train_ratio))), "test_n": 0,
                "reason": f"样本数 {n} < 训练门槛 {min_train} + 测试门槛 {min_test}"}
    cut = int(n * float(train_ratio))
    cut = max(int(min_train), min(cut, n - int(min_test)))
    train, test = samples[:cut], samples[cut:]
    target_value = float(target) if target is not None else \
        _nominal_from_samples(train)

    # 旧乘数：训练段「半宽 / (band_sigma*sqrt(h))」的中位数（缺字段时按 1σ）
    old_ks = [s["half_log"] / s["sigma_h"] for s in train
              if s.get("sigma_h") and s["sigma_h"] > 0]
    k_old = float(np.median(old_ks)) if old_ks else 1.0

    z_train = np.asarray([s["z"] for s in train], dtype=float)
    z_test = np.asarray([s["z"] for s in test], dtype=float)
    try:
        k_prime = float(np.quantile(z_train, target_value))
    except (TypeError, ValueError):
        k_prime = None
    if k_prime is None or not math.isfinite(k_prime) or k_prime <= 0:
        return {"available": False, "k_prime": None, "k_old": round(k_old, 6),
                "train_n": len(train), "test_n": len(test),
                "reason": "训练段无法得到有效分位数（z 非有限）"}

    train_cov = float(np.mean(z_train <= k_prime))
    test_cov = float(np.mean(z_test <= k_prime))
    test_hits = int(np.sum(z_test <= k_prime))
    ci_test = wilson_interval(test_hits, int(z_test.size))
    old_test_cov = float(np.mean(z_test <= k_old))
    if ci_test[0] <= target_value <= ci_test[1]:
        verdict, text = "validated", "校准可用（训练段拟合，测试段验证通过）"
    else:
        verdict, text = "rejected", "不建议仅靠乘数缩放（测试段仍偏离名义水平）"
    return {
        "available": True,
        "k_old": round(k_old, 6),
        "k_prime": round(k_prime, 6),
        "target": round(target_value, 6),
        "train_n": len(train),
        "test_n": len(test),
        "train_coverage_at_k_prime": round(train_cov, 6),
        "test_coverage_at_k_old": round(old_test_cov, 6),
        "test_coverage_at_k_prime": round(test_cov, 6),
        "test_ci_low": round(ci_test[0], 6),
        "test_ci_high": round(ci_test[1], 6),
        "verdict": verdict,
        "verdict_text": text,
        "reason": None if verdict == "validated" else text,
        "rule": "k' 仅由训练段分位数确定；测试段只做验证，不参与定参",
    }


def evaluate_interval_coverage(store=None, rows=None, limit: int = 4000,
                               nominal: Optional[float] = None,
                               min_samples: int = MIN_INTERVAL_SAMPLES) -> dict:
    """UI/报告统一入口：从预测库读已结算样本并计算真实覆盖率。

    返回结构保证：
    - 有足够样本 → 给出真实 ``coverage`` 与判定；
    - 无样本 / 老数据 ``lower/upper`` 全为 NULL → ``coverage=None`` 且
      ``reason`` 明确，**绝不**用残差 σ 近似值冒充。
    """
    if rows is None:
        if store is None:
            return {"available": False, "coverage": None, "n": 0,
                    "reason": "未提供预测库或样本，无法计算真实区间覆盖率"}
        try:
            rows = store.query_closed_with_bands(limit=limit)
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "coverage": None, "n": 0,
                    "reason": f"读取已结算预测失败：{exc}"}
    rows = list(rows or [])
    result = interval_coverage(rows, nominal=nominal, min_samples=min_samples)
    result["total_rows"] = len(rows)
    result["usable_rows"] = result.get("n", 0)
    if result.get("coverage") is None and result.get("reason") is None:
        result["reason"] = "样本不足或区间字段缺失，无法给出真实覆盖率"
    return result
