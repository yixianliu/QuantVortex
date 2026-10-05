"""历史波动率（HV）分位突破波动率交易策略。

M4.4 波动率交易：HV 分位突破。
"""
from __future__ import annotations
from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset
import pandas as pd
import numpy as np

class HVPercentile(StrategyBase):
    def __init__(self, symbol: str, params=None):
        super().__init__(symbol, params)
        self.hv_window = self.params.get("hv_window", 20) if self.params else 20
        self.percentile_window = self.params.get("percentile_window", 100) if self.params else 100
        self.entry_threshold = self.params.get("entry_threshold", 80.0) if self.params else 80.0  # 高于此分位做空
        self.exit_threshold = self.params.get("exit_threshold", 20.0) if self.params else 20.0   # 低于此分位做多

    def _window_size(self) -> int:
        # 需要足够的数据来计算HV和其分位数
        return self.hv_window + self.percentile_window + 5

    def on_bar(self, bar: Bar):
        self._push(bar)
        closes = pd.Series(self._closes)
        if len(closes) < self.hv_window + 1:
            # 计算HV至少需要hv_window+1根收盘价（因为需要计算收益率）
            return
        # 计算对数收益率
        log_returns = np.log(closes / closes.shift(1))
        # 计算历史波动率（年化，这里我们不年化，因为只用于分位比较）
        # 使用hv_window窗口的标准差
        hv = log_returns.rolling(self.hv_window).std().iloc[-1]
        if len(closes) < self.hv_window + self.percentile_window:
            # 不足以计算分位数，先积累数据
            return
        # 获取过去percentile_window根的HV序列（不包括当前Bar？我们使用历史数据）
        # 我们需要得到过去percentile_window根的HV值（每根Bar对应一个HV，但HV需要hv_window根才能算）
        # 为了简化，我们对收盘价序列直接计算滚动HV序列，然后取其过去percentile_window根的分位数
        hv_series = log_returns.rolling(self.hv_window).std()
        # 去除NaN
        hv_series = hv_series.dropna()
        if len(hv_series) < self.percentile_window:
            return
        current_hv = hv_series.iloc[-1]
        # 计算当前HV在过去percentile_window根中的分位数（0-100）
        percentile = (hv_series.iloc[-self.percentile_window:] <= current_hv).mean() * 100
        # 交易逻辑：
        #   当HV分位数高于entry_threshold（例如80），认为波动率偏高，将来会回落 -> 做空波动率（即做空资产？）
        #   这里我们做简化：假设高波动率对应资价下跌的概率增加，所以做空；低波动率对应资价上涨的概率增加，所以做多。
        #   实际波动率交易可能更复杂，这里仅作演示。
        if percentile > self.entry_threshold:
            self.send_order(Direction.SHORT, Offset.OPEN, 1)
        elif percentile < self.exit_threshold:
            self.send_order(Direction.LONG, Offset.OPEN, 1)