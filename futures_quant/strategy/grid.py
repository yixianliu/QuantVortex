"""策略3：网格交易（多头网格，价格越低买得越多）。

    - 以 center_price 为中枢，按 grid_step 划分网格；
    - 价格每下跌一个网格，加买 lots_per_grid 手；每上涨一个网格，减仓对应手数；
    - 通过「目标持仓 = f(价格偏离)」实现自动再平衡，天然低买高卖。
说明：此处实现为多头网格（最常用）；若要双向网格，可在价格高于中枢时反向做空，
只需扩展 target 计算并受风控约束。grid_count 限制最大持仓，防止无底加仓。
"""
from __future__ import annotations

from ..core.types import Bar, Direction, Offset
from .base import StrategyBase


class Grid(StrategyBase):
    """网格策略：在价格区间内挂双向网格单，低买高卖赚取波动收益。
    
        继承: StrategyBase"""
    name = "网格交易"
    default_params = {
        "center_price": None,   # None 时用首根收盘价作为中枢
        "grid_step": 20.0,      # 每个网格的价格间距
        "grid_count": 10,       # 最大网格层数（=最大持仓手数上限）
        "lots_per_grid": 1,
    }

    def __init__(self, symbol, params=None):
        """初始化相关对象。
        
            参数:
                symbol
                params"""
        super().__init__(symbol, params)
        self._center = None

    def on_bar(self, bar: Bar) -> None:
        """处理onK线。
        
            参数:
                bar: Bar"""
        self._push(bar)
        p = self.params
        if self._center is None:
            self._center = p["center_price"] if p["center_price"] else bar.close

        long_qty, _ = self.position()
        # 价格低于中枢的网格层数（向下取整，>=0）
        level = int((self._center - bar.close) / p["grid_step"])
        level = max(0, min(p["grid_count"], level))
        target_long = level * p["lots_per_grid"]

        diff = target_long - long_qty
        if diff > 0:
            self.send_order(Direction.LONG, Offset.OPEN, diff)
        elif diff < 0:
            self.send_order(Direction.SHORT, Offset.CLOSE, -diff)
