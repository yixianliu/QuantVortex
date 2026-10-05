"""Keltner Channel CTA 策略。"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase
import pandas as pd

class Keltner(StrategyBase):
    def __init__(self, n: int = 20, k: float = 1.5):
        self.n = n
        self.k = k

    def generate_signals(self, df):
        atr = (df['high'] - df['low']).rolling(self.n).mean()
        mid = df['close'].rolling(self.n).mean()
        up = mid + self.k * atr
        dn = mid - self.k * atr
        signals = []
        for i in range(len(df)):
            if df['close'].iloc[i] > up.iloc[i]:
                signals.append(1)
            elif df['close'].iloc[i] < dn.iloc[i]:
                signals.append(-1)
            else:
                signals.append(0)
        return signals
