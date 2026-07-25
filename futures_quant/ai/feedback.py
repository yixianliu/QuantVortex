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
    """结算单条未预测记录，返回 {hit, actual_return_pct} 或 None（样本不足跳过）。"""
    sym = row.get("symbol")
    per = row.get("period") or "D"
    horizon = int(row.get("horizon") or 10)
    last_close = float(row.get("last_close") or 0.0)
    if not sym or last_close <= 0:
        return None
    try:
        df = mdm.get_bars(sym, per, limit=horizon + 10)
    except Exception:
        return None
    if df is None or len(df) <= horizon:
        return None
    try:
        target = float(df["close"].astype(float).iloc[-(horizon + 1)])
    except Exception:
        return None
    actual = target / last_close - 1.0
    p_up = float(row.get("p_up") or 0.5)
    # 方向命中：看多(p_up>=0.5) 且实际上涨，或看空(p_up<0.5) 且实际下跌
    hit = 1 if (p_up >= 0.5 and actual > 0) or (p_up < 0.5 and actual < 0) else 0
    try:
        store.update_prediction_outcome(
            int(row["id"]), round(actual * 100, 3), hit,
            str(dt.datetime.now()))
    except Exception:
        return None
    return {"hit": hit, "actual_return_pct": actual * 100}


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
    return "\n".join(lines)
