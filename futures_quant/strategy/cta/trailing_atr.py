"""Trailing ATR CTA 策略。"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase

class TrailingATR(StrategyBase):
    def __init__(self, n: int = 14, k: float = 3.0):
        self.n = n
        self.k = k

    def generate_signals(self, df):
        atr = (df['high'] - df['low']).rolling(self.n).mean()
        signals = []
        for i in range(len(df)):
            if df['close'].iloc[i] > df['close'].iloc[max(0,i-1)] + self.k*atr.iloc[i]:
                signals.append(1)
            elif df['close'].iloc[i] < df['close'].iloc[max(0,i-1)] - self.k*atr.iloc[i]:
                signals.append(-1)
            else:
                signals.append(0)
        return signals
