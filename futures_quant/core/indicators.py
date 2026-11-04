"""技术指标库（纯 Python / 列表实现，零 pandas 运行期开销）。

设计要点：
    - 所有函数接受「已发生数据的有限尾部」（deque / list / ndarray 均可）；
    - 仅计算当前 bar 所需的最后一个值，复杂度为 O(window)，常数极小；
    - 回测主循环每根 bar 调用一次，整体复杂度为 O(n * window)，秒级跑完十万根；
    - 例外：macd_last 的 EMA 定义依赖完整历史，仍为 O(n)（未截断以保证数值一致）；
    - 不使用未来数据：唐奇安通道自动排除当前 bar（等价于 .shift(1)）。
如需替换为 TA-Lib 或 numpy 向量化实现，只需在本文件内替换函数体。
"""
from __future__ import annotations

from collections import deque
from typing import Sequence, Tuple


def _tail(seq: Sequence[float], count: int) -> list:
    """取序列尾部 count 个元素，避免 list(seq) 造成 O(n) 全量拷贝。

    list / tuple / ndarray 走切片（O(count)）；deque 不支持切片，改用右端
    负索引（``seq[i - count]``）逐元素取尾部，代价 O(count²) 次指针步进，
    但 count 通常 ≤ 百级，远优于 ``list(seq)`` 的 O(n) 全量转换——这正是
    回测主循环 O(n²) 的根因。调用方需保证 count <= len(seq)。
    """
    n = len(seq)
    if count <= 0:
        return []
    if count >= n:
        return list(seq)
    if isinstance(seq, deque):
        return [seq[i - count] for i in range(count)]
    return list(seq[n - count:])


def sma_last(seq: Sequence[float], period: int) -> float:
    """简单移动平均的最后值。"""
    if len(seq) < period:
        return float("nan")
    w = _tail(seq, period)
    return sum(w) / period


def atr_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
             period: int = 14) -> float:
    """真实波幅 ATR 的最后值（基于最近 period 个真实波幅）。

    M-perf：只取尾部 period+1 根计算 period 个 TR，复杂度 O(period)；
    原实现每根 bar 都对整段历史重建 TR，回测中累计为 O(n²)。
    求和顺序与原实现一致（由旧到新），保证浮点结果逐位一致。
    """
    if len(closes) < period + 1:
        return float("nan")
    h = _tail(highs, period + 1)
    l = _tail(lows, period + 1)
    c = _tail(closes, period + 1)
    trs = []
    for i in range(1, period + 1):
        pc = c[i - 1]
        trs.append(max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc)))
    return sum(trs) / period


def donchian_last(highs: Sequence[float], lows: Sequence[float], period: int = 20
                  ) -> Tuple[float, float]:
    """唐奇安通道（上轨=窗口最高价，下轨=窗口最低价），**排除当前 bar**。

    返回 (upper, lower)，用于突破判断时避免用到「当前尚未收盘」的极值。
    """
    if len(highs) < period + 1 or len(lows) < period + 1:
        return float("nan"), float("nan")
    # 取最近 period+1 根（含当前），再排除最后一根（当前），即窗口内历史极值
    h = _tail(highs, period + 1)
    l = _tail(lows, period + 1)
    upper = max(h[:-1])
    lower = min(l[:-1])
    return upper, lower


def bollinger_last(closes: Sequence[float], period: int = 20, num_std: float = 2.0
                   ) -> Tuple[float, float, float]:
    """布林带最后值，返回 (中轨, 上轨, 下轨)。"""
    if len(closes) < period:
        return float("nan"), float("nan"), float("nan")
    w = _tail(closes, period)
    mean = sum(w) / period
    var = sum((x - mean) ** 2 for x in w) / period
    sd = var ** 0.5
    return mean, mean + num_std * sd, mean - num_std * sd


def rsi_last(closes: Sequence[float], period: int = 14) -> float:
    """相对强弱指标 RSI 的最后值（Wilder 式均值，数据不足时返回中性 50）。"""
    if len(closes) < period + 1:
        return 50.0
    w = _tail(closes, period + 1)
    deltas = [w[i] - w[i - 1] for i in range(1, len(w))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    g = sum(gains) / period
    ls = sum(losses) / period
    if ls == 0:
        return 100.0 if g > 0 else 50.0
    rs = g / ls
    return 100.0 - 100.0 / (1.0 + rs)


def cci_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
             period: int = 20) -> float:
    """商业情绪指数 CCI 的最后值（基于典型价格均值，超买超卖区间 ±100）。"""
    if len(closes) < period:
        return 0.0
    h = _tail(highs, period)
    l = _tail(lows, period)
    c = _tail(closes, period)
    tp = [(h[i] + l[i] + c[i]) / 3 for i in range(period)]
    ma = sum(tp) / period
    variance = sum((x - ma) ** 2 for x in tp) / period
    sd = variance ** 0.5
    if sd == 0:
        return 0.0
    return (tp[-1] - ma) / sd


def macd_last(closes: Sequence[float], fast_period: int = 12,
              slow_period: int = 26, signal_period: int = 9) -> Tuple[float, float, float]:
    """MACD 指标：返回 (MACD 线, 信号线, 柱状图)。"""
    c = list(closes)
    if len(c) < slow_period + signal_period:
        return 0.0, 0.0, 0.0

    # 计算 EMA（Wilder 式指数平滑）
    def ema(arr: Sequence[float], period: int) -> float:
        if len(arr) < period:
            return arr[-1] if arr else 0.0
        k = 2.0 / (period + 1)
        ema_val = sum(arr[:period]) / period
        for price in arr[period:]:
            ema_val = price + k * (ema_val - price)
        return ema_val

    macd_line = ema(c, fast_period) - ema(c, slow_period)
    signal_line = ema([macd_line], signal_period) if len(c) >= slow_period else macd_line
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def roc_last(closes: Sequence[float], period: int = 12) -> float:
    """变化率 ROC：(当前收盘价 - N周期前收盘价) / N周期前收盘价 * 100。"""
    if len(closes) < period + 1:
        return float("nan")
    w = _tail(closes, period + 1)
    return (w[-1] - w[0]) / w[0] * 100.0


def willr_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               period: int = 14) -> float:
    """威廉姆斯 %R：(最高价 - 收盘价) / (最高价 - 最低价) * -100。"""
    if len(closes) < period:
        return float("nan")
    h = _tail(highs, period)
    l = _tail(lows, period)
    highest_high = max(h)
    lowest_low = min(l)
    if highest_high == lowest_low:
        return -50.0
    return (highest_high - closes[-1]) / (highest_high - lowest_low) * -100.0


def stoch_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               k_period: int = 14, d_period: int = 3) -> Tuple[float, float]:
    """随机指标 K, D。"""
    if len(closes) < k_period:
        return float("nan"), float("nan")
    l = _tail(lows, k_period)
    h = _tail(highs, k_period)
    lowest_low = min(l)
    highest_high = max(h)
    if highest_high == lowest_low:
        k = 50.0
    else:
        k = (closes[-1] - lowest_low) / (highest_high - lowest_low) * 100.0
    # 简单的 D 为 K 的移动平均（这里用 SMA 近似）
    # 为了不引入额外状态，我们近似为最近 d_period 次 K 的平均（但我们没有历史 K）。
    # 这里我们直接返回 K 为 D 的近似（在实际中应维护 K 序列）。
    d = k  # 简化处理
    return k, d


def adx_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
             period: int = 14) -> float:
    """平均方向指数 ADX（简化版，仅用于演示）。"""
    # 这里我们返回一个占位值，实际应用中应实现完整 ADX 计算。
    # 为保持示例可运行，我们返回 20.
    return 20.0


def sar_last(highs: Sequence[float], lows: Sequence[float],
             acceleration: float = 0.02, maximum: float = 0.2) -> float:
    """抛物线转向指标 SAR（简化版）。"""
    # 占位返回当前低价；仅需最后一个元素，避免 list() 全量拷贝。
    # 用 len() 判空而非真值判断：ndarray 的 `not seq` 会抛出歧义真值异常。
    if len(highs) == 0 or len(lows) == 0:
        return float("nan")
    return lows[-1]


def obv_last(closes: Sequence[float], volumes: Sequence[float]) -> float:
    """能潮指标 OBV（简化版，需要成交量序列）。"""
    # 由于 factor_signal 未传入 volumes，这里返回 0 作为占位。
    return 0.0


def vwap_last(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
              volumes: Sequence[float]) -> float:
    """平均成交价 VWAP（简化版，需要成交量序列）。"""
    # 占位
    return 0.0