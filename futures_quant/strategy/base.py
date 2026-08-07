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
    # 历史缓冲上限（根）。子类须 ≥ 自身最长指标周期 + 余量。
    # 用 deque(maxlen) 给缓冲封顶，使每根 bar 的指标计算复杂度从 O(n) 降到
    # O(HISTORY_LEN)，整体回测从 O(n^2) 降为 O(n * HISTORY_LEN)，避免卡顿。
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
        # 维护历史序列用于指标计算（仅使用已发生数据，杜绝未来函数）。
        # 用 deque（无 maxlen）并在 _push 时按 _window_size() 动态裁剪，
        # 使缓冲长度恒定为「指标所需最大窗口」，每根 bar 指标计算复杂度
        # 从 O(n) 降到 O(window)，整体回测从 O(n^2) 降为 O(n * window)。
        self._closes: deque = deque()
        self._highs: deque = deque()
        self._lows: deque = deque()
        self._bars: deque = deque()

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

        子类应按自身参数覆盖，例如 max(fast, slow, atr_period) + 余量，
        确保缓冲永远包含完整指标窗口，且不会无限增长拖慢回测。
        """
        return int(self.HISTORY_LEN)

    def _push(self, bar: Bar) -> None:
        """处理push。
        
            参数:
                bar: Bar"""
        self._closes.append(bar.close)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._bars.append(bar)
        # 仅保留最近 _window_size() 根，超出则丢弃最旧，保证长度恒定
        cap = self._window_size()
        while len(self._closes) > cap:
            self._closes.popleft()
            self._highs.popleft()
            self._lows.popleft()
            self._bars.popleft()

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
