"""策略基类。

所有策略继承 StrategyBase，实现 on_bar(bar) 并在满足条件时通过
self.engine.send_order(...) 发出委托。引擎负责把委托送入风控、经纪商撮合、
组合记账，形成「策略只管信号、其余交给引擎」的低耦合结构。
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import pandas as pd

from ..core.types import Bar, Direction, Offset, OrderType


class StrategyBase:
    """策略抽象基类：定义 on_bar 信号回调与持仓辅助方法，子类实现具体交易逻辑。"""
    name: str = "base"
    # 默认参数，子类覆盖
    default_params: dict = {}
    # 历史缓冲上限（根）。所有 deque 都用 maxlen=HISTORY_LEN 真封顶，
    # 每根 bar 的指标计算复杂度是 O(HISTORY_LEN) 而非 O(n)，
    # 整体回测从 O(n^2) 降为 O(n * HISTORY_LEN)，杜绝缓冲无界增长。
    HISTORY_LEN: int = 500

    def __init__(self, symbol: str, params: Optional[dict] = None) -> None:
        """初始化相关对象。

            参数:
                symbol: str
                params: Optional[dict]"""
        self.symbol = symbol
        self.params = dict(self.default_params)
        if params:
            self.params.update(params)
        self.engine = None  # 由引擎注入
        # 历史序列用 deque(maxlen=HISTORY_LEN) 真封顶——append 时 Python 自动丢弃
        # 最旧元素，O(1)；不再需要 _push 手动 while 循环 popleft。
        # 子类若覆盖 _window_size() 返回更小值（如 max(fast, slow, atr) + 5），
        # 必须保证 _window_size() <= HISTORY_LEN，否则缓冲不足以完整算指标。
        cap = self.HISTORY_LEN
        self._closes: deque = deque(maxlen=cap)
        self._highs: deque = deque(maxlen=cap)
        self._lows: deque = deque(maxlen=cap)
        self._bars: deque = deque(maxlen=cap)

    # ---------- 引擎交互 ----------
    def send_order(
        self,
        direction: Direction,
        offset: Offset,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
    ) -> None:
        """发送订单。
        
            参数:
                direction: Direction
                offset: Offset
                quantity: int
                order_type: OrderType
                limit_price: Optional[float]"""
        if self.engine is None:
            raise RuntimeError("策略未注册到引擎，无法下单。")
        self.engine.send_order(
            symbol=self.symbol,
            direction=direction,
            offset=offset,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
        )

    # ---------- 持仓查询助手 ----------
    def position(self) -> tuple[int, int]:
        """返回 (多头手数, 空头手数)。"""
        if self.engine is None:
            return 0, 0
        return self.engine.get_position(self.symbol)

    # ---------- 子类实现 ----------
    def on_bar(self, bar: Bar) -> None:
        """处理onK线。
        
            参数:
                bar: Bar"""
        raise NotImplementedError

    # ---------- 指标历史维护 ----------
    def _window_size(self) -> int:
        """指标计算所需的最大历史窗口（根）。

        子类应按自身参数覆盖，例如 max(fast, slow, atr_period) + 余量。
        返回值 ≤ HISTORY_LEN（deque maxlen）——这样 deque 自动裁剪后，
        ``len(closes())`` 就足以容纳完整指标窗口，杜绝未来函数与越界。
        """
        return int(self.HISTORY_LEN)

    def _buffer_len(self) -> int:
        """当前缓冲实际长度（供指标函数断言用；与 deque.maxlen 一致封顶）。"""
        return len(self._closes)

    def _buffer_full(self) -> bool:
        """缓冲是否已填满（长度达到 maxlen）。"""
        return len(self._closes) >= self.HISTORY_LEN

    def _push(self, bar: Bar) -> None:
        """推送一根 bar 到所有历史缓冲。

        deque(maxlen=HISTORY_LEN) 会在 append 时自动丢弃最旧元素（O(1)），
        无需手动 while 循环 popleft——这是 M1-05 的关键修复。
        """
        self._closes.append(bar.close)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._bars.append(bar)

    def closes(self) -> pd.Series:
        """处理closes。
        
            返回:
                pd.Series"""
        return pd.Series(self._closes)

    def highs(self) -> pd.Series:
        """处理highs。
        
            返回:
                pd.Series"""
        return pd.Series(self._highs)

    def lows(self) -> pd.Series:
        """处理lows。
        
            返回:
                pd.Series"""
        return pd.Series(self._lows)

    def reset(self) -> None:
        """重置相关对象。"""
        self._closes.clear()
        self._highs.clear()
        self._lows.clear()
        self._bars.clear()
