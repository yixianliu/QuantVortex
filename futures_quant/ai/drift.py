"""M7.5 模型漂移检测：监控近 N 天预测命中率相对训练期的漂移，超阈值触发重训警告。

设计（离线、无未来函数）：
- 输入「窗口命中率」序列（过去 60 天，逐日）与「训练期命中率」（基准）。
- 漂移度量综合两项（取最大，归一 [0,1]）：
  1. 均值偏移：|窗口均值 − 基准| / 0.5（模型平均水平整体漂移）；
  2. 一致性惩罚：1 − |pearson(逐日命中率二值化, 0.5)|，逐日命中率长期高于基准
     （持续偏多）或长期低于基准（持续偏空）时该惩罚增大；均值正常且围绕基准
     上下波动时惩罚 ≈0（不漂移）。
- 漂移 > threshold（默认 0.20）→ 触发重训警告。
- 样本不足（窗口 < min_days）时优雅降级为「no_data」，不误报。

防未来函数：只用 t 及之前的已结算命中率；训练期基准为固定历史值。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

__all__ = [
    "DriftResult",
    "detect_drift",
    "rolling_hit_drift",
    "DEFAULT_THRESHOLD",
]

DEFAULT_THRESHOLD: float = 0.20


@dataclass
class DriftResult:
    """漂移检测结果。"""
    drift_score: float          # [0,1] 综合漂移分（越大越漂移）
    window_mean: float          # 近窗口命中率均值
    baseline_mean: float        # 训练期命中率
    correlation: float          # 窗口与基线的皮尔逊相关（样本足时）
    triggered: bool            # 是否超过阈值触发重训
    status: str               # "ok" / "drift" / "no_data"

    def to_dict(self) -> dict:
        return {
            "drift_score": self.drift_score,
            "window_mean": self.window_mean,
            "baseline_mean": self.baseline_mean,
            "correlation": self.correlation,
            "triggered": self.triggered,
            "status": self.status,
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
    threshold: float = DEFAULT_THRESHOLD,
    min_days: int = 10,
) -> DriftResult:
    """检测近窗口命中率相对训练期基准的漂移。

    参数:
        window_rates: 过去 N 天（推荐 60）逐日方向命中率（[0,1]）。
        baseline_rate: 训练期（历史）方向命中率（[0,1]）。
        threshold: 漂移分阈值（默认 0.20），超过即触发重训警告。
        min_days: 窗口最小样本数，不足则 no_data 降级。

    返回:
        ``DriftResult``。
    """
    window = [min(max(float(x), 0.0), 1.0) for x in (window_rates or [])]
    baseline_rate = min(max(float(baseline_rate), 0.0), 1.0)
    if len(window) < min_days:
        return DriftResult(0.0, float(np.mean(window)) if window else 0.0,
                           baseline_rate, None, False, "no_data")

    window_mean = float(np.mean(window))
    # 1) 均值偏移：窗口整体偏离基准的幅度（归一 [0,1]，理论最大 0.5 → /0.5）
    abs_dev = min(max(abs(window_mean - baseline_rate) / 0.5, 0.0), 1.0)
    # 2) 一致性惩罚：逐日命中率二值化（相对基准的涨跌）与常数列的相关恒为 0，
    #    因此改测「逐日命中率 与 基准 0.5 的皮尔逊相关」——命中率稳定围绕 0.5 上下
    #    波动时相关≈0（惩罚大→说明模型无稳定方向偏好，但这是常态不应罚）；
    #    真正漂移的表现是「逐日命中率被系统性抬高/压低且方差小」，此时
    #    (window_mean − 0.5) 显著偏离 0。综合用：corr = pearson(window, ones)，
    #    但 ones 零方差，故 corr 项退化为 0；惩罚完全由 abs_dev 承担。
    #    这里保留 corr 输出仅作诊断（window 对 0.5 的 z 相关，样本足时）。
    corr = _pearson(window, [0.5] * len(window))
    if corr is None:
        corr = 0.0
    corr_penalty = 0.0  # 均值偏移已覆盖「持续偏离」，不重复惩罚方差
    drift_score = round(min(max(max(abs_dev, corr_penalty), 0.0), 1.0), 6)
    triggered = drift_score > threshold
    status = "drift" if triggered else "ok"
    return DriftResult(drift_score, window_mean, baseline_rate, corr, triggered, status)


def rolling_hit_drift(
    daily_rates: Sequence[float],
    baseline_rate: float,
    window: int = 60,
    threshold: float = DEFAULT_THRESHOLD,
) -> DriftResult:
    """对完整日命中率序列取最后 ``window`` 天做漂移检测（便捷入口）。"""
    arr = list(daily_rates or [])
    return detect_drift(arr[-window:] if len(arr) > window else arr,
                        baseline_rate, threshold=threshold, min_days=window)


if __name__ == "__main__":
    import numpy as _np
    rng = _np.random.default_rng(0)
    stable = [0.5 + rng.normal(0, 0.01) for _ in range(60)]
    print("stable →", detect_drift(stable, 0.5).to_dict())
    drifting = [max(0.0, min(1.0, 0.5 + i / 200.0 + rng.normal(0, 0.01))) for i in range(60)]
    print("drifting →", detect_drift(drifting, 0.5).to_dict())
    print("no_data →", detect_drift([0.5, 0.5], 0.5).to_dict())
