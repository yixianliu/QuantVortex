"""期现套利策略（M4.2）。

基差 = 期货价 − 现货价。当基差显著偏离其历史均线（升水/贴水极端）时，
做空/做多期货并配以现货头寸对冲，基差回归时平仓。此策略在单合约回测框架内
以「期货合约价差 = 基差代理」实现，标的物固定在期货侧，现货价格为外部锚点。

沿用 StrategyBase 契约，仅用当前及之前数据，杜绝未来函数。
"""
from __future__ import annotations

import pandas as pd

from ..base import StrategyBase
from futures_quant.core.types import Direction, Offset


class SpotFuturesBasis(StrategyBase):
    """期现基差均值回归策略。

    参数:
        symbol: 期货合约。
        spot_price_path: 现货价格序列源（可为 DataFrame 或可迭代），
            通过 ``set_spot_prices`` 注入以对齐时间。
        lookback: 基差均线窗口（根）。
        entry_z: 开仓 z-score。
        exit_z: 平仓 z-score。
    """
    name = "spot_futures_basis"
    default_params = {"lookback": 20}

    def __init__(self, symbol: str, params: dict | None = None):
        """兼容回测页 ``strat_cls(symbol, params_dict)`` 调用。

        参数:
            symbol: 期货合约。
            params: 策略参数（含 lookback/entry_z/exit_z，缺省走 default_params）。
        """
        self.symbol = symbol
        p = dict(params or self.default_params)
        self.lookback = max(int(p.get("lookback", 20)), 2)
        self.entry_z = float(p.get("entry_z", 2.0))
        self.exit_z = float(p.get("exit_z", 0.5))
        super().__init__(symbol)
        self._spot_iter = None
        self._spot = 0.0
        self._basis_pos = 0
        self._spot_iter = None
        self._spot = 0.0
        self._basis_pos = 0
        super().__init__(symbol, params=params)

    def set_spot_prices(self, spot_prices) -> None:
        """注入现货价格序列（与期货 bar 同一时间索引对齐）。"""
        self._spot_iter = iter(spot_prices)

    def _next_spot(self) -> float:
        """取当前现货价（对齐到当前 bar）。"""
        if self._spot_iter is None:
            # 无现货源：用期货收盘近似（零基差），仅展示框架
            return 0.0
        try:
            v = next(self._spot_iter)
            if hasattr(v, "close"):
                v = v.close
            self._spot = float(v)
        except StopIteration:
            pass
        return self._spot

    def _window_size(self) -> int:
        return self.lookback + 5

    def on_bar(self, bar) -> None:
        spot = self._next_spot()
        # 基差 = 期货 − 现货
        basis = float(bar.close) - spot
        closes = self.closes()
        if len(closes) < self.lookback + 1:
            return
        # 仅用当前 bar 之前的窗口（杜绝未来函数）
        hist = closes.iloc[-(self.lookback + 1):-1].astype(float)
        mean = float(hist.mean()) - spot
        std = float(hist.std(ddof=0))
        if std <= 1e-9:
            return
        z = (basis - mean) / std

        long_qty, short_qty = self.position()
        net = long_qty - short_qty

        # 平仓：基差回归
        if self._basis_pos != 0 and abs(z) < self.exit_z:
            if self._basis_pos > 0 and net > 0:
                self.send_order(direction=Direction.SHORT, offset=Offset.CLOSE, quantity=net)
            elif self._basis_pos < 0 and net < 0:
                self.send_order(direction=Direction.LONG, offset=Offset.CLOSE, quantity=abs(net))
            self._basis_pos = 0

        # 开仓：期货升水过大（z>entry）→ 卖期货；贴水过大（z<-entry）→ 买期货
        if self._basis_pos == 0:
            if z > self.entry_z:
                self.send_order(direction=Direction.SHORT, offset=Offset.OPEN, quantity=1)
                self._basis_pos = -1
            elif z < -self.entry_z:
                self.send_order(direction=Direction.LONG, offset=Offset.OPEN, quantity=1)
                self._basis_pos = 1

    def reset(self) -> None:
        self._basis_pos = 0
        self._spot = 0.0
        self._spot_iter = None
        super().reset()