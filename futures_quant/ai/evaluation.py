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
