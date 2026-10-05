"""Ichimoku CTA 策略。"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase

class Ichimoku(StrategyBase):
    def __init__(self):
        pass

    def generate_signals(self, df):
        signals = []
        for i in range(len(df)):
            if i < 26:
                signals.append(0)
                continue
            tenkan = (df['high'].iloc[i-9:i+1].max() + df['low'].iloc[i-9:i+1].min())/2
            kijun = (df['high'].iloc[i-25:i+1].max() + df['low'].iloc[i-25:i+1].min())/2
            signal = 1 if tenkan > kijun else -1 if tenkan < kijun else 0
            signals.append(signal)
        return signals
