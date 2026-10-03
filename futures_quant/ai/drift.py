"""M7.5 模型漂移检测：监控近 N 天预测命中率相对训练期的漂移，超阈值触发重训警告。

设计（离线、无未来函数）：
- 输入「窗口命中率」序列（过去 60 天，逐日）与「训练期命中率」（基准）。
- 漂移度量综合两项（取最大，归一 [0,1]）：
  1. 均值偏移 abs_dev：|窗口均值 − 基准| / dev_norm（模型平均水平整体漂移）；
  2. 一致性惩罚 corr_penalty：consistency × magnitude —— 逐日命中率**持续**
     高于基准（持续偏多）或**持续**低于基准（持续偏空）时该惩罚增大；均值正常
     且围绕基准上下波动时 consistency≈0 → 惩罚 ≈0（不漂移）。
- 漂移 > threshold（默认 0.20）→ 触发重训警告。
- 样本不足（窗口 < min_days）时优雅降级为「no_data」，不误报。

防未来函数：只用 t 及之前的已结算命中率；训练期基准为固定历史值。

M3-13 改动（UPGRADE_PLAN_V5 §5.2-C10）：
  ① `corr_penalty` 原本被**硬编码为 0.0**（`:103`），漂移分实际只由均值偏移决定，
     模块 docstring 承诺的「一致性惩罚」从未生效 —— 已恢复为真实计算；
  ② `rolling_hit_drift` 原先把 `min_days` 绑成 `window`（默认 60）→ 不足 60 天
     的历史永远返回 no_data，新上线品种根本跑不出漂移 —— 已解耦，`min_days`
     独立默认 10 天；
  ③ 阈值集中到 `ai/constants.py` 的 `DriftConfig`（与 M3-11 一致），
     支持 `config/settings.json#ai.thresholds.drift.*` 覆盖。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from .constants import DRIFT as _DC

__all__ = [
    "DriftResult",
    "detect_drift",
    "rolling_hit_drift",
    "detect_for_symbol",
    "detect_from_store",
    "DEFAULT_THRESHOLD",
]

# 历史导出，保留兼容；真实默认值已集中到 constants.DriftConfig.threshold
DEFAULT_THRESHOLD: float = 0.20


@dataclass
class DriftResult:
    """漂移检测结果。"""
    drift_score: float          # [0,1] 综合漂移分（越大越漂移）
    window_mean: float          # 近窗口命中率均值
    baseline_mean: float        # 训练期命中率
    correlation: float          # 窗口命中率随时间的趋势相关（诊断用）
    triggered: bool            # 是否超过阈值触发重训
    status: str               # "ok" / "drift" / "no_data"
    # M3-13 ①：两个分量拆开输出，便于 UI 解释「为什么漂移」
    mean_shift: float = 0.0     # 分量① 均值偏移
    corr_penalty: float = 0.0   # 分量② 一致性惩罚
    n_days: int = 0             # 实际参与计算的天数
    detail: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "drift_score": self.drift_score,
            "window_mean": self.window_mean,
            "baseline_mean": self.baseline_mean,
            "correlation": self.correlation,
            "triggered": self.triggered,
            "status": self.status,
            "mean_shift": self.mean_shift,
            "corr_penalty": self.corr_penalty,
            "n_days": self.n_days,
            "detail": dict(self.detail),
        }


def _pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """皮尔逊相关；样本 < 2 或零方差返回 None。"""
    a = np.asarray(list(a), dtype=float)
    b = np.asarray(list(b), dtype=float)
    if a.size < 2 or b.size < 2 or a.size != b.size:
        return None
    a, b = a - a.mean(), b - b.mean()
    denom = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    if denom <= 1e-12:
        return None
    return float((a * b).sum() / denom)


def detect_drift(
    window_rates: Sequence[float],
    baseline_rate: float,
    threshold: float | None = None,
    min_days: int | None = None,
) -> DriftResult:
    """检测近窗口命中率相对训练期基准的漂移。

    参数:
        window_rates: 过去 N 天（推荐 60）逐日方向命中率（[0,1]）。
        baseline_rate: 训练期（历史）方向命中率（[0,1]）。
        threshold: 漂移分阈值；None → 取 `DriftConfig.threshold`（默认 0.20）。
        min_days: 窗口最小样本数，不足则 no_data 降级；
            None → 取 `DriftConfig.min_days`（默认 10，**与 window 解耦**）。

    返回:
        ``DriftResult``。

    M3-13 ①：`corr_penalty` 的真实计算
    -----------------------------------
    逐日偏离 ``d_i = window_i − baseline``，拆成两个正交的观测量：

    * ``consistency = |mean(sign(d_i))|`` ∈ [0,1] —— **方向一致性**。每天都同向
      偏离（持续偏多 / 持续偏空）→ 1；围绕基准上下波动 → ≈0。这正是模块 docstring
      承诺但从未实装的「一致性」分量。
    * ``magnitude = mean(|d_i|) / mag_norm`` ∈ [0,1] —— **平均偏离幅度**归一。

    二者相乘：只有「**持续**且**幅度不小**」才罚，避免把随机噪声或小抖动放大成
    漂移。`noise_band` 内的单日偏离视为噪声、不计方向（防止 0.001 级数值抖动
    被当成「每天都系统性偏离」）。

    【已注明假设】文档只写了「恢复为真实计算」，未给出公式。此处按上面两个
    正交分量的乘积实现，阈值口径保持 `max(mean_shift, corr_penalty)` 不变。
    """
    thr = _DC.threshold if threshold is None else float(threshold)
    md = _DC.min_days if min_days is None else int(min_days)
    window = np.asarray([min(max(float(x), 0.0), 1.0)
                         for x in (window_rates or [])], dtype=float)
    baseline_rate = min(max(float(baseline_rate), 0.0), 1.0)
    if window.size < md:
        return DriftResult(0.0, float(np.mean(window)) if window.size else 0.0,
                           baseline_rate, 0.0, False, "no_data",
                           n_days=int(window.size),
                           detail={"reason": f"样本不足（{window.size} < {md}）"})

    window_mean = float(np.mean(window))
    d = window - baseline_rate

    # 1) 均值偏移：窗口整体偏离基准的幅度（归一 [0,1]）
    abs_dev = min(max(abs(window_mean - baseline_rate) / _DC.dev_norm, 0.0), 1.0)

    # 2) 一致性惩罚（M3-13 ①：真实计算，替代原先的硬编码 0.0）
    signed = np.where(np.abs(d) > _DC.noise_band, np.sign(d), 0.0)
    consistency = float(abs(np.mean(signed))) if signed.size else 0.0
    magnitude = min(float(np.mean(np.abs(d))) / _DC.mag_norm, 1.0)
    corr_penalty = min(max(consistency * magnitude, 0.0), 1.0)

    # 诊断：命中率随时间的趋势相关（<0 = 在恶化，>0 = 在改善）。
    # 【说明】改造前这里是 pearson(window, [0.5]*n) —— 常数列零方差导致恒返回
    # None→0.0，是个永远没有信息的死输出；改为与时间索引相关，判别力真实可用。
    trend = np.arange(window.size, dtype=float)
    corr = _pearson(window, trend)
    if corr is None:
        corr = 0.0

    drift_score = round(min(max(max(abs_dev, corr_penalty), 0.0), 1.0), 6)
    triggered = drift_score > thr
    status = "drift" if triggered else "ok"
    return DriftResult(drift_score, window_mean, baseline_rate, float(corr),
                       triggered, status, mean_shift=round(abs_dev, 6),
                       corr_penalty=round(corr_penalty, 6),
                       n_days=int(window.size),
                       detail={"consistency": round(consistency, 6),
                               "magnitude": round(magnitude, 6),
                               "threshold": thr, "min_days": md})


def rolling_hit_drift(
    daily_rates: Sequence[float],
    baseline_rate: float,
    window: int | None = None,
    threshold: float | None = None,
    min_days: int | None = None,
) -> DriftResult:
    """对完整日命中率序列取最后 ``window`` 天做漂移检测（便捷入口）。

    M3-13 ②：`min_days` 与 `window` **解耦**。
    改造前本函数把 `min_days=window`（默认 60）传给 `detect_drift`，意味着
    历史上不满 60 个交易日的品种**永远**返回 no_data —— 新上线品种在前两个月
    完全没有漂移保护。现在 `min_days` 独立取 `DrfitConfig.min_days`（默认 10），
    即「只要有 10 天就能出结论」，需要更严格时可显式传入。
    """
    w = _DC.window if window is None else int(window)
    arr = list(daily_rates or [])
    return detect_drift(arr[-w:] if len(arr) > w else arr,
                        baseline_rate, threshold=threshold, min_days=min_days)


def _weighted_rate(rows) -> float:
    """按样本数加权的历史命中率（避免「某天只有 1 条且命中」把基准拉到 1.0）。"""
    tot_n = sum(int(r[2]) for r in rows)
    if tot_n <= 0:
        return float(np.mean([float(r[1]) for r in rows])) if rows else 0.5
    return float(sum(float(r[1]) * int(r[2]) for r in rows) / tot_n)


def detect_from_store(
    store,
    symbol: str,
    window: int | None = None,
    threshold: float | None = None,
    min_days: int | None = None,
    baseline_mode: str = "pre_window",
) -> dict:
    """M3-13：从反馈库直接算某个品种的模型漂移（UI 指示灯 / scheduler 共用）。

    参数:
        store: `AnalysisStore`（需 `daily_hit_rates`；缺失时降级为 no_data）。
        symbol: 品种代码。
        baseline_mode:
            ``"pre_window"``（默认）基准 = **窗口之前**的历史命中率（按样本数
            加权），最贴近「相对训练期是否漂移」的语义；
            ``"all"`` 基准 = 全部历史命中率（窗口段也计入，偏保守、漂移分更小）。
            窗口前无数据时自动回退 ``"all"``。

    返回:
        `detect_for_symbol` 的字典（含 level / message / checked_at）。
    """
    fn = getattr(store, "daily_hit_rates", None)
    if fn is None:
        return {"drift_score": 0.0, "status": "no_data", "triggered": False,
                "level": "no_data", "symbol": symbol, "n_days": 0,
                "message": f"{symbol} 漂移检测不可用：store 缺少 daily_hit_rates"}
    try:
        rows = list(fn(symbol) or [])
    except Exception as e:  # noqa: BLE001
        return {"drift_score": 0.0, "status": "no_data", "triggered": False,
                "level": "no_data", "symbol": symbol, "n_days": 0,
                "message": f"{symbol} 漂移检测失败：{e}"}
    if not rows:
        out = detect_for_symbol([], 0.5, symbol=symbol, threshold=threshold,
                                min_days=min_days)
        # detect_for_symbol 的文案里已带 symbol，这里不要再拼一次
        out["message"] = "暂无已结算样本，漂移检测跳过"
        return out

    w = _DC.window if window is None else int(window)
    win_rows = rows[-w:] if len(rows) > w else rows
    pre_rows = rows[:-w] if len(rows) > w else []
    if baseline_mode == "all" or not pre_rows:
        baseline = _weighted_rate(rows)
    else:
        baseline = _weighted_rate(pre_rows)
    return detect_for_symbol([float(r[1]) for r in win_rows], baseline,
                             symbol=symbol, threshold=threshold,
                             min_days=min_days)


def detect_for_symbol(
    daily_rates: Sequence[float],
    baseline_rate: float,
    symbol: str = "",
    window: int | None = None,
    threshold: float | None = None,
    min_days: int | None = None,
) -> dict:
    """M3-13 ④：scheduler / UI 的单一入口 —— 漂移检测 + 可落库/可展示的字典。

    在 `DriftResult` 之上补上 `symbol`、`checked_at`（UTC ISO）、`level`
    （ok / warn / drift / no_data）与一句人话 `message`，供托盘冒泡与
    `alerts` 表直接消费，避免每个调用方各写一套文案。
    """
    from datetime import datetime, timezone
    res = rolling_hit_drift(daily_rates, baseline_rate, window=window,
                            threshold=threshold, min_days=min_days)
    out = res.to_dict()
    if res.status == "no_data":
        level = "no_data"
        msg = f"{symbol} 漂移检测：样本不足，暂不判定"
    elif res.status == "drift":
        level = "drift"
        msg = (f"{symbol} 模型漂移 {res.drift_score:.2f}"
               f"（近期命中率 {res.window_mean:.2f} vs 训练期 {res.baseline_mean:.2f}），"
               f"建议重训")
    else:
        level = "ok"
        msg = f"{symbol} 漂移分 {res.drift_score:.2f}，正常"
    out.update({"symbol": symbol, "level": level, "message": msg,
                "checked_at": datetime.now(timezone.utc).isoformat()})
    return out


if __name__ == "__main__":
    import numpy as _np
    rng = _np.random.default_rng(0)
    stable = [0.5 + rng.normal(0, 0.01) for _ in range(60)]
    print("stable →", detect_drift(stable, 0.5).to_dict())
    drifting = [max(0.0, min(1.0, 0.5 + i / 200.0 + rng.normal(0, 0.01))) for i in range(60)]
    print("drifting →", detect_drift(drifting, 0.5).to_dict())
    print("no_data →", detect_drift([0.5, 0.5], 0.5).to_dict())
    # M3-13 验收样例：命中率从 60% 跌到 30%
    collapse = [0.6] * 10 + [0.3] * 20
    print("60%→30% →", detect_for_symbol(collapse, 0.6, symbol="rb2601"))
    # M3-13 ②：不足 60 天也能出结论（改造前恒为 no_data）
    print("30天 →", rolling_hit_drift([0.3] * 30, 0.6))
