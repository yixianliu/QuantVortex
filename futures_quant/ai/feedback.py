"""预测学习反馈模块（自动学习闭环）。

职责：
    1. 结算：把「未结算」的预测记录与后续真实行情比对，判定方向是否命中，
       写回 store（actual_return_pct / score(命中标记) / closed_ts）。
    2. 统计：按 总体 / 模型 / 行情状态 / 配置 聚合方向命中率，供看板展示。
    3. 自适应：基于历史命中率，为某行情状态挑选经验最优的模型配置
       （extended_features / use_ensemble），并据历史校准「置信度」。
       默认回退「增强模型」以保证可用性（与「运行预测」一键式设计一致），
       仅当该行情状态双侧配置均积累到足够样本时才启用自适应切换。

所有「实际收益」均为近似：以预测时 last_close 为起点，与当前
向前 horizon 根 K 线的收盘比。合成/实盘源下仅作反馈信号，非精确回测。
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np

from ..indicators.tech import add_indicators
from .predictor import FuturesPredictor


def quick_regime(df) -> str:
    """在不训练模型的前提下，用 ADX + 均线排列快速判断行情状态。"""
    try:
        ind = add_indicators(df)
        last = ind.iloc[-1]
        adx = float(last["ADX"]) if "ADX" in ind else 0.0
        close = ind["close"].astype(float)
        ma5 = float(close.tail(5).mean())
        ma20 = float(close.tail(20).mean())
        if adx > 25 and ma20 and abs(ma5 - ma20) / ma20 > 0.01:
            return "趋势行情"
    except Exception:
        pass
    return "震荡行情"


def evaluate_prediction(store, row: dict, mdm) -> dict | None:
    """结算单条未预测记录，返回 {hit, actual_return_pct, y_up} 或 None（样本不足跳过）。

    y_up = 1 表示 horizon 内实际上涨（close 比预测时 last_close 高），
    是校准系统的「标签」（label），供 reliability_calibration 与
    analysis_store.prediction_stats 统一使用。
    """
    sym = row.get("symbol")
    per = row.get("period") or "D"
    horizon = int(row.get("horizon") or 10)
    last_close = float(row.get("last_close") or 0.0)
    if not sym or last_close <= 0:
        return None
    try:
        # 取 horizon+5 根 bars：horizon 根用于结算，5 根作为安全缓冲
        df = mdm.get_bars(sym, per, limit=horizon + 5)
    except Exception:
        return None
    if df is None or len(df) < 2:
        return None
    # 预测时的 last_close 是最后一条 bar 的 close，实际结果是最后一条 bar 的 close
    actual = float(df["close"].iloc[-1]) / last_close - 1.0
    y_up = 1.0 if actual > 0.0 else 0.0
    p_up = float(row.get("p_up") or 0.5)
    # 方向命中：看多(p_up>=0.5) 且实际上涨，或看空(p_up<0.5) 且实际下跌
    hit = 1 if (p_up >= 0.5 and actual > 0) or (p_up < 0.5 and actual < 0) else 0
    try:
        store.update_prediction_outcome(
            int(row["id"]), round(actual * 100, 3), hit,
            str(dt.datetime.now()), y_up)
    except Exception:
        return None
    return {"hit": hit, "actual_return_pct": actual * 100, "y_up": y_up}


def evaluate_all_open(store, mdm, max_n: int = 50) -> dict:
    """结算所有未结算预测，返回 {evaluated, hits, total} 概要。"""
    open_rows = store.query_open_predictions(limit=max_n)
    evaluated = hits = 0
    for row in open_rows:
        res = evaluate_prediction(store, row, mdm)
        if res is not None:
            evaluated += 1
            hits += res["hit"]
    return {"evaluated": evaluated, "hits": hits,
            "rate": (hits / evaluated) if evaluated else None}


def adaptive_config(store, regime: str, min_samples: int = 20) -> dict:
    """为给定行情状态挑选经验最优配置。

    仅当该行情状态下，『增强』与『基础』两种配置各自积累 >= min_samples
    条已结算样本时，才返回历史命中率更高的那一个；否则回退增强模型
    （保证一键预测始终可用、不依赖历史）。
    """
    stats = store.prediction_stats()
    by_config = stats.get("by_config", {})
    enh = by_config.get("enhanced")
    base = by_config.get("baseline")
    # 仅统计与 regime 相关的样本（prediction_stats 已按 regime 分组）
    by_regime = stats.get("by_regime", {})
    rg = by_regime.get(regime, {})
    # 需要双侧都有足够样本才切换
    enh_n = enh["total"] if enh else 0
    base_n = base["total"] if base else 0
    if enh_n >= min_samples and base_n >= min_samples:
        enh_rate = enh.get("rate")
        base_rate = base.get("rate")
        if enh_rate is not None and base_rate is not None and base_rate > enh_rate:
            return {"extended_features": False, "use_ensemble": False,
                    "source": "adaptive", "rate": round(base_rate, 3)}
    return {"extended_features": True, "use_ensemble": True,
            "source": "default", "rate": round(enh.get("rate"), 3) if enh else None}


def calibrated_confidence(store, regime: str, config: str, base_p_up: float,
                         min_samples: int = 15) -> float:
    """用历史命中率校准置信度：若该 (regime, config) 积累足够样本，
    返回历史方向命中率；否则回退模型自带的 p_up。
    """
    stats = store.prediction_stats()
    by_regime = stats.get("by_regime", {})
    rg = by_regime.get(regime)
    if rg and rg.get("total", 0) >= min_samples and rg.get("rate") is not None:
        return float(rg["rate"])
    return float(base_p_up)


def _fill_none(vals):
    """前后向填充 None；若全为 None 则填 0.5。"""
    n = len(vals)
    out = list(vals)
    last = None
    for i in range(n - 1, -1, -1):
        if out[i] is not None:
            last = out[i]
        elif last is not None:
            out[i] = last
    last = None
    for i in range(n):
        if out[i] is not None:
            last = out[i]
        elif last is not None:
            out[i] = last
    return [(v if v is not None else 0.5) for v in out]


def _pava(y):
    """保序回归（非递减）：用栈合并相邻逆序块，返回长度同 y 的单调序列。"""
    n = len(y)
    stack = []  # 每项为 [加权均值, 计数, 起始索引]
    for i in range(n):
        stack.append([float(y[i]), 1.0, i])
        while len(stack) >= 2 and stack[-1][0] < stack[-2][0]:
            m1, c1, s1 = stack[-2]
            m2, c2, _ = stack[-1]
            stack[-2] = [(m1 * c1 + m2 * c2) / (c1 + c2), c1 + c2, s1]
            stack.pop()
    out = [0.0] * n
    for mean, count, start in stack:
        for k in range(start, start + int(count)):
            out[k] = mean
    return out


def _wilson(p: float, n: int, z: float = 1.96) -> tuple:
    """二项比例 Wilson (1-α) 置信区间（小样本稳健，不截断为 0/1 奇点）。

    返回 (lo, hi)∈[0,1]；n<=0 时退化到整段 [0,1]。
    """
    if n <= 0:
        return (0.0, 1.0)
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def reliability_calibration(store, regime: str | None = None,
                            min_samples: int = 20, nbins: int = 10):
    """构建「预测概率 → 真实命中率」的可靠性校准映射（out-of-time 实证校准）。

    返回 (calib_fn, info)：
      calib_fn(p)：输入模型 p_up∈[0,1]，输出校准后概率；样本不足返回 None。
      info：{"coverage": int, "status": str, "bins": [(center, smoothed, n)]}

    三档回退：① 该行情状态样本 ≥ min_samples → 用其分箱；
             ② 否则用全局样本；③ 仍不足 → 返回 None（调用方回退扁平 regime 命中率）。
    分箱后做保序(PAVA)平滑，保证校准映射单调非递减，抑制小样本抖动过拟合。
    这是把模型「自信度」变成「真实可信度」的闭环——喂给 predictor.calibrate_p_up。
    """
    rows = store.query_closed_for_calibration(limit=4000)

    def _pts(subset):
        out = []
        for r in subset:
            p = r.get("p_up")
            y = r.get("y_up")
            if p is None or y is None:
                continue
            out.append((float(p), float(y)))
        return out

    all_pts = _pts(rows)
    if regime:
        pts = [(float(r["p_up"]), float(r.get("y_up") or 0.0)) for r in rows
               if r.get("p_up") is not None and r.get("y_up") is not None
               and (r.get("regime") or "未知") == regime]
    else:
        pts = [(float(r["p_up"]), float(r.get("y_up") or 0.0)) for r in rows
               if r.get("p_up") is not None and r.get("y_up") is not None]
    if len(pts) < min_samples:
        pts = all_pts  # ② 退全局
    if len(pts) < min_samples:
        return None, {"coverage": len(all_pts), "status": "insufficient"}

    edges = [i / nbins for i in range(nbins + 1)]
    centers = [(edges[i] + edges[i + 1]) / 2 for i in range(nbins)]
    bin_hits = [0] * nbins
    bin_n = [0] * nbins
    for p, h in pts:
        idx = min(nbins - 1, max(0, int(p * nbins)))
        bin_n[idx] += 1
        bin_hits[idx] += h
    emp = [(bin_hits[i] / bin_n[i] if bin_n[i] else None) for i in range(nbins)]
    emp = _fill_none(emp)
    smoothed = _pava(emp)
    # Wilson 95% 置信带：每个分箱经验命中率的区间（小样本稳健），
    # 反映该档概率校准的可信度——空分箱记 (None, None) 不画带。
    bands = []
    for i in range(nbins):
        if bin_n[i] > 0:
            bands.append(_wilson(float(bin_hits[i]) / bin_n[i], bin_n[i]))
        else:
            bands.append((None, None))
    fn = lambda p: float(np.interp(float(p), centers, smoothed))
    return fn, {"coverage": len(pts), "status": "ok",
                "bins": [(round(centers[i], 2), round(float(smoothed[i]), 3),
                          bin_n[i],
                          (round(bands[i][0], 3) if bands[i][0] is not None else None),
                          (round(bands[i][1], 3) if bands[i][1] is not None else None))
                         for i in range(nbins)]}


def calibration_band_at(bins, p_up) -> tuple:
    """在给定 p_up 处，对分箱 (center, smoothed, n, lo, hi) 插值出校准置信区间。

    返回 (lo, hi)（已 clamp 到 [0,1] 的连续插值）；无可用分箱返回 (None, None)。
    用于把校准不确定度直接挂到「本次预测」落点上。
    """
    pts = [(c, lo, hi) for (c, s, n, lo, hi) in (bins or [])
           if lo is not None and hi is not None and n > 0]
    if not pts:
        return (None, None)
    p = float(p_up)
    cs = [t[0] for t in pts]
    los = [t[1] for t in pts]
    his = [t[2] for t in pts]
    return (float(np.interp(p, cs, los)), float(np.interp(p, cs, his)))


def mean_band_width(bins) -> float | None:
    """各分箱（n>=3）Wilson 区间宽度的均值，反映校准整体不确定性（绝对值）。"""
    vals = [hi - lo for (c, s, n, lo, hi) in (bins or [])
            if lo is not None and hi is not None and n >= 3]
    if not vals:
        return None
    return float(np.mean(vals))


def reliability_summary(store, min_samples: int = 20) -> str:
    """生成可靠性校准的看板文本（样本充足时展示分档映射）。"""
    fn, info = reliability_calibration(store, regime=None, min_samples=min_samples)
    if fn is None:
        return (f"可靠性校准：样本不足（需 ≥{min_samples} 条已结算预测），"
                f"暂沿用扁平命中率。")
    lines = [f"可靠性校准已启用（样本 {info['coverage']} 条，out-of-time 实证）："]
    for (c, s, n, *_ ) in info["bins"]:
        if n >= 3:
            lines.append(f"  模型说涨 {c*100:.0f}% → 历史实际命中 {s*100:.0f}%（{n}次）")
    # 校准区间宽度：把 Wilson 置信带的不确定性也写进看板，避免只看点估计
    mbw = mean_band_width(info["bins"])
    if mbw is not None:
        if mbw > 0.20:
            lines.append(f"  校准区间宽度约 {mbw*100:.0f}pp（偏宽，单点校准仅供参考）")
        else:
            lines.append(f"  校准区间宽度约 {mbw*100:.0f}pp（区间较窄，校准较可信）")
    return "\n".join(lines)


def recommend_text(store) -> str:
    """生成「自适应建议」文本，供看板展示。"""
    stats = store.prediction_stats()
    total = stats.get("total", 0)
    rate = stats.get("rate")
    if total == 0 or rate is None:
        return "暂无已结算预测，运行若干次预测后将自动积累学习样本。"
    lines = [f"已结算预测 {total} 次，总体方向命中率 {rate*100:.0f}%。"]
    by_config = stats.get("by_config", {})
    enh = by_config.get("enhanced")
    base = by_config.get("baseline")
    if enh and base and enh.get("rate") is not None and base.get("rate") is not None:
        better = "增强模型" if enh["rate"] >= base["rate"] else "基础模型"
        lines.append(f"历史对比：增强模型命中率 "
                    f"{(enh['rate']*100):.0f}%（{enh['total']}次） vs "
                    f"基础模型 {(base['rate']*100):.0f}%（{base['total']}次），"
                    f"当前倾向使用「{better}」。")
    by_regime = stats.get("by_regime", {})
    if by_regime:
        best = max(by_regime.items(), key=lambda kv: (kv[1].get("rate") or 0))
        if best[1].get("rate") is not None:
            lines.append(f"分行情看，「{best[0]}」方向可辨性最强"
                        f"（命中率 {(best[1]['rate']*100):.0f}%）。")
    # 可靠性校准（样本外实证）：模型概率 → 真实命中率 的映射状态
    lines.append(reliability_summary(store))
    return "\n".join(lines)
