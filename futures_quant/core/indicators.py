"""技术指标库（纯 Python / 列表实现，零 pandas 运行期开销）。

设计要点：
    - 所有函数接受「已发生数据的有限尾部」（deque / list / ndarray 均可）；
    - 仅计算当前 bar 所需的最后一个值，复杂度为 O(window)，常数极小；
    - 回测主循环每根 bar 调用一次，整体复杂度 O(n * window)，秒级跑完十万根；
    - 不使用未来数据：唐奇安通道自动排除当前 bar（等价于 .shift(1)）。
如需替换为 TA-Lib 或 numpy 向量化实现，只需在本文件内替换函数体。
"""
from __future__ import annotations

from typing import Sequence, Tuple


def sma_last(seq: Sequence[float], period: int) -> float:
    """简单移动平均的最后值。"""
    s = list(seq)
    if len(s) < period:
        return float("nan")
    return sum(s[-period:]) / period


def atr_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
             period: int = 14) -> float:
    """真实波幅 ATR 的最后值（基于最近 period 个真实波幅）。"""
    h, l, c = list(highs), list(lows), list(closes)
    if len(c) < period + 1:
        return float("nan")
    trs = []
    for i in range(1, len(c)):
        pc = c[i - 1]
        trs.append(max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc)))
    if len(trs) < period:
        return float("nan")
    return sum(trs[-period:]) / period


def donchian_last(highs: Sequence[float], lows: Sequence[float], period: int = 20
                  ) -> Tuple[float, float]:
    """唐奇安通道（上轨=窗口最高价，下轨=窗口最低价），**排除当前 bar**。

    返回 (upper, lower)，用于突破判断时避免用到「当前尚未收盘」的极值。
    """
    h, l = list(highs), list(lows)
    if len(h) < period + 1:
        return float("nan"), float("nan")
    # 取最近 period+1 根（含当前），再排除最后一根（当前），即窗口内历史极值
    upper = max(h[-(period + 1):-1])
    lower = min(l[-(period + 1):-1])
    return upper, lower


def bollinger_last(closes: Sequence[float], period: int = 20, num_std: float = 2.0
                   ) -> Tuple[float, float, float]:
    """布林带最后值，返回 (中轨, 上轨, 下轨)。"""
    c = list(closes)
    if len(c) < period:
        return float("nan"), float("nan"), float("nan")
    w = c[-period:]
    mean = sum(w) / period
    var = sum((x - mean) ** 2 for x in w) / period
    sd = var ** 0.5
    return mean, mean + num_std * sd, mean - num_std * sd


def rsi_last(closes: Sequence[float], period: int = 14) -> float:
    """相对强弱指标 RSI 的最后值（Wilder 式均值，数据不足时返回中性 50）。"""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    g = sum(gains[-period:]) / period
    ls = sum(losses[-period:]) / period
    if ls == 0:
        return 100.0 if g > 0 else 50.0
    rs = g / ls
    return 100.0 - 100.0 / (1.0 + rs)
