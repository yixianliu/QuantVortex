"""CTA Dual Thrust 策略。

M4.1 扩展 CTA。
"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase

class DualThrust(StrategyBase):
    def __init__(self, n: int = 20, k: float = 0.5):
        self.n = n
        self.k = k

    def generate_signals(self, df):
        high = df["high"].rolling(self.n).max()
        low = df["low"].rolling(self.n).min()
        range_ = high - low
        up = df["close"].shift(1) + self.k * range_
        dn = df["close"].shift(1) - self.k * range_
        signal = 0
        signals = []
        for i in range(len(df)):
            if df["high"].iloc[i] >= up.iloc[i]:
                signal = 1
            elif df["low"].iloc[i] <= dn.iloc[i]:
                signal = -1
            signals.append(signal)
        return signals
