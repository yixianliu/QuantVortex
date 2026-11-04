"""Vortix CTA 策略。"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase

class Vortix(StrategyBase):
    def __init__(self, n: int = 14):
        self.n = n

    def generate_signals(self, df):
        signals = []
        for i in range(len(df)):
            if i < self.n:
                signals.append(0)
                continue
            # 简化 VM+ - VI-
            vm = max(df['high'].iloc[i-self.n:i].max(), df['close'].iloc[i-1]) - min(df['low'].iloc[i-self.n:i].min(), df['close'].iloc[i-1])
            vi = max(df['high'].iloc[i-self.n:i].max(), df['close'].iloc[i-1]) - min(df['low'].iloc[i-self.n:i].min(), df['close'].iloc[i-1])
            if vm > vi:
                signals.append(1)
            elif vm < vi:
                signals.append(-1)
            else:
                signals.append(0)
        return signals
