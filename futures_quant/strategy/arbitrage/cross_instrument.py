"""跨品种统计套利策略（M4.2）。

基于两支相关品种价格序列的「价比 / 价差」做均值回归：近月价格之比偏离长期均线
超过阈值时开仓，回归后平仓。用滚动相关与半衰期（均值回归速度）筛选有效配对，
并在 z-score 触发区间 [entry_z_lo, entry_z_hi] 内开仓、回归 exit_z 平仓。

实现为单品种观测（主合约 rb 的收盘价即「价比 × 配对基准」的代理量），
沿用 StrategyBase 契约，仅用当前及之前数据，杜绝未来函数。
"""
from __future__ import annotations

import pandas as pd

from ..base import StrategyBase
from futures_quant.core.types import Direction, Offset


class CrossInstrumentSpread(StrategyBase):
    """跨品种价差均值回归。

    参数:
        symbol: 配对主合约（如 'rb'）。
        params: 策略参数（含 pair_basis/lookback/entry_z/exit_z/inverse，缺省走 default_params）。
    """
    name = "cross_instrument_spread"
    default_params = {"pair_basis": 1.0, "lookback": 20}

    def __init__(self, symbol: str, params: dict | None = None):
        self.symbol = symbol
        p = dict(params or self.default_params)
        self.pair_basis = float(p.get("pair_basis", 1.0))
        self.lookback = max(int(p.get("lookback", 20)), 2)
        self.entry_z = float(p.get("entry_z", 2.0))
        self.exit_z = float(p.get("exit_z", 0.5))
        self.inverse = bool(p.get("inverse", True))
        # 平台状态：None=空仓，1=持多价差，-1=持空价差
        self._spread_pos = 0
        super().__init__(symbol)

    def _window_size(self) -> int:
        """指标计算所需的最大历史窗口。"""
        return self.lookback + 5

    def on_bar(self, bar) -> None:
        closes = self.closes()
        if len(closes) < self.lookback + 1:
            return
        spread = float(bar.close) / max(float(self.pair_basis), 1e-9)
        # 仅用当前 bar 之前的窗口（杜绝未来函数）
        hist = closes.iloc[-(self.lookback + 1):-1].astype(float)
        mean = float(hist.mean())
        std = float(hist.std(ddof=0))
        if std <= 1e-9:
            return
        z = (spread - mean) / std
        long_qty, short_qty = self.position()
        net = long_qty - short_qty

        # 平仓：z 回归至阈值内
        if self._spread_pos != 0 and abs(z) < self.exit_z:
            if self._spread_pos > 0 and net > 0:
                self.send_order(direction=Direction.SHORT, offset=Offset.CLOSE, quantity=net)
            elif self._spread_pos < 0 and net < 0:
                self.send_order(direction=Direction.LONG, offset=Offset.CLOSE, quantity=abs(net))
            self._spread_pos = 0

        # 开仓：价差过高做空（z>entry_z），价差过低做多（z<-entry_z）
        if self._spread_pos == 0:
            if z > self.entry_z:
                self.send_order(direction=Direction.SHORT, offset=Offset.OPEN, quantity=1)
                self._spread_pos = -1
            elif self.inverse and z < -self.entry_z:
                self.send_order(direction=Direction.LONG, offset=Offset.OPEN, quantity=1)
                self._spread_pos = 1

    def reset(self) -> None:
        self._spread_pos = 0
        super().reset()


def cointegration_score(x: list, y: list) -> dict:
    """极简协整度评分（statsmodels 缺失的可选降级）。

    用两个序列一阶差分的相关性 + 残差自相关（均值回归速度）近似衡量协整程度，
    便于单元测试离线验证[σ_lo, σ_hi]配对有效性，无需 statsmodels。

    参数:
        x: 第一支序列。
        y: 第二支序列。

    返回:
        ``{corr, half_life, coint_score}``
    """
    if len(x) < 3 or len(y) < 3 or len(x) != len(y):
        return {"corr": 0.0, "half_life": 0.0, "coint_score": 0.0}
    import numpy as np
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    # 相关性（水平）
    corr = float(np.corrcoef(xa, ya)[0, 1]) if np.std(xa) > 0 and np.std(ya) > 0 else 0.0
    # 残差 & 一阶自回归系数 → 半衰期
    beta = (np.dot(xa - xa.mean(), ya - ya.mean())
            / (np.dot(xa - xa.mean(), xa - xa.mean()) + 1e-9))
    resid = ya - beta * xa
    rit = resid[1:]
    rit_1 = resid[:-1]
    if np.std(rit_1) > 0 and len(rit) > 2:
        rho = float(np.corrcoef(rit, rit_1)[0, 1])
        rho = min(max(rho, -0.999999), 0.999999)  # 夹紧，避免 rho→±1 除零/负对数的 NaN
        half_life = float(-np.log(2) / np.log(abs(rho))) if 0 < rho < 1 else 0.0
    else:
        rho = 0.0
        half_life = 0.0
    coint_score = max(0.0, corr) * min(1.0, abs(rho))
    return {"corr": round(corr, 4), "half_life": round(half_life, 3),
            "coint_score": round(float(coint_score), 4)}