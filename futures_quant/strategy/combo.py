"""多策略组合（权重优化）。

M4.5 策略组合 + M1-06（2026-10-01）：子策略缺 ``get_signal`` 时剔除并告警；
权重归一化校验，保证 ``abs(sum(weights) - 1) < 1e-6``。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from futures_quant.strategy.base import StrategyBase
from futures_quant.core.types import Bar, Direction, Offset

logger = logging.getLogger(__name__)


class ComboStrategy(StrategyBase):
    """线性组合多个子策略的信号。

    每个子策略需提供 ``get_signal(bar: Bar) -> float`` 方法，返回值在
    ``[-1, 1]`` 范围内（-1 做空、+1 做多、0 中性）。组合信号为加权平均：
    ``signal = sum(w_i * s_i) / sum(w_i)``；权重自动归一化，保证
    ``abs(sum(weights) - 1) < 1e-6``（M1-06）。

    缺 ``get_signal`` 的子策略在构造时剔除并 ``logger.warning``，不会进入
    权重表（旧实现里 ``on_bar`` 内 hasattr 检查会让 total_weight 恒为 0
    且信号被丢弃，导致「分子分母不一致」的隐性 bug）。
    """

    _WEIGHT_TOL = 1e-6

    def __init__(
        self,
        symbol: str,
        strategies_weights: List[Tuple[StrategyBase, float]],
        params: Optional[dict] = None,
    ) -> None:
        super().__init__(symbol, params)

        # 构造期先过滤缺 get_signal 的子策略，只保留有效的
        valid: List[Tuple[StrategyBase, float]] = []
        dropped = 0
        for i, item in enumerate(strategies_weights or []):
            strat, w = item
            if not hasattr(strat, "get_signal"):
                dropped += 1
                logger.warning(
                    "ComboStrategy: 子策略[%d] %s 缺 get_signal，从权重表剔除",
                    i, type(strat).__name__,
                )
                continue
            if not isinstance(w, (int, float)):
                logger.warning(
                    "ComboStrategy: 子策略[%d] 权重非法（%r），剔除",
                    i, w,
                )
                dropped += 1
                continue
            valid.append((strat, float(w)))

        if dropped > 0:
            logger.warning(
                "ComboStrategy: 剔除 %d 个无效子策略，剩余 %d 个",
                dropped, len(valid),
            )

        # 权重归一化：保证 sum(w_i) == 1（避免除以 0 或分子分母不一致）
        total = sum(w for _, w in valid)
        if not valid or total <= 0:
            # 全部剔除或权重和为 0/负——组合无信号，保持空列表，on_bar 直接返回
            self._strategies_weights: List[Tuple[StrategyBase, float]] = []
            self.threshold = (self.params or {}).get("threshold", 0.5)
            return

        normalized: List[Tuple[StrategyBase, float]] = [
            (s, w / total) for s, w in valid
        ]
        # 归一化校验（M1-06 DoD）
        assert abs(sum(w for _, w in normalized) - 1.0) < self._WEIGHT_TOL, (
            "ComboStrategy: 权重归一化失败"
        )

        self._strategies_weights = normalized
        self.threshold = (self.params or {}).get("threshold", 0.5)

    # ---------- 属性 ----------
    @property
    def strategies_weights(
        self,
    ) -> List[Tuple[StrategyBase, float]]:
        """有效子策略 + 归一化后的权重（只读）。"""
        return list(self._strategies_weights)

    @property
    def weights_sum(self) -> float:
        """权重和（应恒为 1 或 0，便于单测断言）。"""
        return sum(w for _, w in self._strategies_weights)

    # ---------- 指标窗口 ----------
    def _window_size(self) -> int:
        """组合策略所需窗口 = 子策略窗口的最大值（仅有效子策略）。"""
        if not self._strategies_weights:
            return int(self.HISTORY_LEN)
        return max(strat._window_size() for strat, _ in self._strategies_weights)

    # ---------- 主循环 ----------
    def on_bar(self, bar: Bar) -> None:
        """聚合子策略信号 → 加权平均 → 超过阈值开仓。"""
        if not self._strategies_weights:
            return

        # 更新所有子策略的历史缓冲（不触发它们的下单逻辑）
        for strat, _ in self._strategies_weights:
            strat._push(bar)

        # 加权平均（权重已归一化，等价于 sum(w_i * s_i) / sum(w_i)）
        signals = [strat.get_signal(bar) * w for strat, w in self._strategies_weights]
        combo_signal = sum(signals)

        if combo_signal > self.threshold:
            self.send_order(Direction.LONG, Offset.OPEN, 1)
        elif combo_signal < -self.threshold:
            self.send_order(Direction.SHORT, Offset.OPEN, 1)
