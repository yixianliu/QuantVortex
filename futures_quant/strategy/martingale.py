"""策略5：马丁策略（亏损加仓，带硬性层数封顶与止损）。

⚠️ 风险提示：马丁策略在连续亏损时会放大仓位，极端行情下可能快速爆仓。
本实现已强制限制：
    - max_layers 封顶加仓层数；
    - 全局单笔 / 单日 / 回撤风控仍由 risk.RiskManager 兜底；
    - 实盘前务必在仿真环境充分验证，并下调仓位。
逻辑（以多头马丁为例）：
    - RSI 超卖且空仓 -> 以 base_qty * multiplier^layer 开多；
    - 触达止盈 -> 平仓并重置层数；
    - 触达止损 -> 平仓并把层数 +1（下次开仓倍数更大），层数达上限后停止加仓。
"""
from __future__ import annotations

from ..core.indicators import rsi_last
from ..core.types import Bar, Direction, Offset
from .base import StrategyBase


class Martingale(StrategyBase):
    name = "马丁策略"
    default_params = {
        "base_qty": 1,
        "multiplier": 2,
        "max_layers": 4,
        "rsi_period": 14,
        "oversold": 30,
        "overbought": 55,
        "take_profit": 0.01,   # 相对入场价的止盈比例
        "stop_loss": 0.02,     # 相对入场价的止损比例
    }

    def __init__(self, symbol, params=None):
        super().__init__(symbol, params)
        self._layer = 0
        self._entry = None
        self._side = 0  # 1 多 / 0 空仓

    def _window_size(self) -> int:
        return int(self.params["rsi_period"] + 5)

    def on_bar(self, bar: Bar) -> None:
        self._push(bar)
        p = self.params
        if len(self._closes) < p["rsi_period"] + 1:
            return

        r = rsi_last(self._closes, p["rsi_period"])
        long_qty, _ = self.position()

        # 持仓管理：止盈 / 止损
        if long_qty > 0 and self._entry is not None:
            if bar.close >= self._entry * (1 + p["take_profit"]):
                self.send_order(Direction.SHORT, Offset.CLOSE, long_qty)
                self._layer = 0
                self._side = 0
                self._entry = None
                return
            if bar.close <= self._entry * (1 - p["stop_loss"]):
                self.send_order(Direction.SHORT, Offset.CLOSE, long_qty)
                self._layer = min(p["max_layers"], self._layer + 1)
                self._side = 0
                self._entry = None
                # 层数封顶后不再开新仓（空仓等待）
                return

        # 开仓条件：超卖 + 空仓 + 未达层数上限
        if long_qty == 0 and self._side == 0 and r < p["oversold"] and self._layer <= p["max_layers"]:
            qty = p["base_qty"] * (p["multiplier"] ** self._layer)
            self.send_order(Direction.LONG, Offset.OPEN, int(qty))
            self._entry = bar.close
            self._side = 1
