"""M1-06 ComboStrategy 权重口径单元测试。

DoD:
    - 缺 get_signal 子策略剔除并 warning；
    - 权重归一化校验 abs(sum(weights)-1) < 1e-6；
    - on_bar 加权平均与阈值开仓正确。
"""
from __future__ import annotations

import logging
from typing import List, Tuple

import pytest

from futures_quant.core.types import Bar, Direction, Offset
from futures_quant.strategy.base import StrategyBase
from futures_quant.strategy.combo import ComboStrategy


class _StubStrategy(StrategyBase):
    """可控信号策略：get_signal 返回预设值。"""
    name = "stub"

    def __init__(self, signal: float = 0.0) -> None:
        super().__init__(symbol="rb")
        self._signal = signal

    def get_signal(self, bar: Bar) -> float:
        return self._signal

    def on_bar(self, bar: Bar) -> None:
        pass


class _BrokenStrategy(StrategyBase):
    """无 get_signal 的策略。"""
    name = "broken"

    def __init__(self) -> None:
        super().__init__(symbol="rb")

    def on_bar(self, bar: Bar) -> None:
        pass


class _RecordingCombo(ComboStrategy):
    """记录 send_order 调用的组合策略。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.orders: List[Tuple[Direction, Offset, int]] = []

    def send_order(self, direction, offset, quantity, **kw):  # type: ignore[override]
        self.orders.append((direction, offset, quantity))


def _bar() -> Bar:
    return Bar(symbol="rb", datetime=0, open=100.0, high=101.0,
               low=99.0, close=100.5, volume=10)


# ---------- 权重归一化 ----------
def test_weights_normalized_when_not_unit():
    """权重 (2, 3) 应归一化为 (0.4, 0.6)。"""
    combo = ComboStrategy("rb", [
        (_StubStrategy(0.5), 2.0),
        (_StubStrategy(-0.5), 3.0),
    ])
    ws = combo.weights_sum
    assert abs(ws - 1.0) < 1e-6, f"权重和应为 1，实际 {ws}"
    s1, w1 = combo.strategies_weights[0]
    s2, w2 = combo.strategies_weights[1]
    assert abs(w1 - 0.4) < 1e-6
    assert abs(w2 - 0.6) < 1e-6


def test_weights_already_normalized_unchanged():
    """已经和为 1 的权重保持不变。"""
    combo = ComboStrategy("rb", [
        (_StubStrategy(0.5), 0.3),
        (_StubStrategy(-0.5), 0.7),
    ])
    assert abs(combo.weights_sum - 1.0) < 1e-6
    _, w1 = combo.strategies_weights[0]
    _, w2 = combo.strategies_weights[1]
    assert abs(w1 - 0.3) < 1e-6
    assert abs(w2 - 0.7) < 1e-6


def test_single_strategy_weight_normalized_to_1():
    """单个子策略的权重归一化为 1。"""
    combo = ComboStrategy("rb", [(_StubStrategy(0.5), 0.5)])
    assert abs(combo.weights_sum - 1.0) < 1e-6
    _, w = combo.strategies_weights[0]
    assert abs(w - 1.0) < 1e-6


# ---------- 缺 get_signal 剔除 ----------
def test_broken_strategy_dropped(caplog):
    """缺 get_signal 子策略被剔除，并 warning。"""
    caplog.set_level(logging.WARNING)
    combo = ComboStrategy("rb", [
        (_StubStrategy(0.5), 1.0),
        (_BrokenStrategy(), 1.0),  # 缺 get_signal
    ])
    assert len(combo.strategies_weights) == 1
    assert isinstance(combo.strategies_weights[0][0], _StubStrategy)
    # 剔除后归一化为 1
    assert abs(combo.weights_sum - 1.0) < 1e-6
    msg = caplog.text
    assert "缺 get_signal" in msg or "剔除" in msg


def test_mixed_valid_and_broken_all_dropped():
    """只有 1 个 broken + 1 个有效 → 只剩有效。"""
    combo = ComboStrategy("rb", [
        (_BrokenStrategy(), 1.0),
        (_StubStrategy(0.5), 2.0),
    ])
    assert len(combo.strategies_weights) == 1
    assert isinstance(combo.strategies_weights[0][0], _StubStrategy)
    assert abs(combo.weights_sum - 1.0) < 1e-6


def test_all_broken_leaves_empty():
    """全部 broken → 组合无有效子策略。"""
    combo = ComboStrategy("rb", [
        (_BrokenStrategy(), 1.0),
        (_BrokenStrategy(), 2.0),
    ])
    assert combo.strategies_weights == []
    assert combo.weights_sum == 0.0
    # on_bar 应静默返回
    combo.on_bar(_bar())


def test_invalid_weight_type_dropped(caplog):
    """非数值权重被剔除并 warning。"""
    caplog.set_level(logging.WARNING)
    combo = ComboStrategy("rb", [
        (_StubStrategy(0.5), "not_a_float"),  # 类型错误
        (_StubStrategy(0.5), 1.0),
    ])
    assert len(combo.strategies_weights) == 1
    assert abs(combo.weights_sum - 1.0) < 1e-6
    assert "权重非法" in caplog.text or "剔除" in caplog.text


# ---------- on_bar 加权平均 ----------
def test_on_bar_signal_above_threshold_opens_long():
    """组合信号 > threshold → 开多。"""
    combo = _RecordingCombo("rb", [
        (_StubStrategy(0.8), 1.0),
        (_StubStrategy(0.6), 1.0),
    ])
    combo.on_bar(_bar())
    assert len(combo.orders) == 1
    direction, _, _ = combo.orders[0]
    assert direction == Direction.LONG


def test_on_bar_signal_below_neg_threshold_opens_short():
    """组合信号 < -threshold → 开空。"""
    combo = _RecordingCombo("rb", [
        (_StubStrategy(-0.8), 1.0),
        (_StubStrategy(-0.6), 1.0),
    ])
    combo.on_bar(_bar())
    assert len(combo.orders) == 1
    direction, _, _ = combo.orders[0]
    assert direction == Direction.SHORT


def test_on_bar_neutral_signal_no_order():
    """信号在阈值内 → 不开仓。"""
    combo = _RecordingCombo("rb", [
        (_StubStrategy(0.2), 1.0),
        (_StubStrategy(-0.2), 1.0),
    ], params={"threshold": 0.5})
    combo.on_bar(_bar())
    assert combo.orders == []


def test_on_bar_empty_no_crash():
    """空组合 on_bar 不崩。"""
    combo = _RecordingCombo("rb", [])
    combo.on_bar(_bar())
    assert combo.orders == []


def test_on_bar_ignores_broken_substrategies():
    """on_bar 不受缺 get_signal 子策略影响。"""
    combo = _RecordingCombo("rb", [
        (_StubStrategy(0.8), 1.0),
        (_BrokenStrategy(), 1.0),
        (_StubStrategy(0.6), 1.0),
    ])
    combo.on_bar(_bar())
    # 剩下两个有效策略，加权 (0.8 + 0.6) / 2 = 0.7 > 0.5
    assert len(combo.orders) == 1
    assert combo.orders[0][0] == Direction.LONG


# ---------- _window_size ----------
def test_window_size_uses_only_valid():
    """_window_size 只考虑有效子策略。"""
    combo = ComboStrategy("rb", [
        (_StubStrategy(0.5), 1.0),
        (_BrokenStrategy(), 1.0),
    ])
    # broken 被剔除，窗口只来自 stub
    assert combo._window_size() == combo.strategies_weights[0][0]._window_size()


def test_window_size_empty_returns_default():
    """空组合 _window_size 返回 HISTORY_LEN。"""
    combo = ComboStrategy("rb", [])
    assert combo._window_size() == combo.HISTORY_LEN


# ---------- 归一化 DoD 校验 ----------
def test_normalization_dod_invariant():
    """M1-06 DoD：任何有效组合的权重和都在 1e-6 精度内等于 1。"""
    cases = [
        [1.0, 1.0],
        [2.0, 3.0],
        [0.1, 0.5, 0.3],
        [0.5, 1.5, 0.5, 1.5],
        [100.0, 1.0],  # 极不均衡
        [0.001, 0.999],
    ]
    for weights in cases:
        combo = ComboStrategy(
            "rb",
            [(_StubStrategy(0.0), w) for w in weights],
        )
        assert abs(combo.weights_sum - 1.0) < 1e-6, (
            f"权重 {weights} 归一化后 sum={combo.weights_sum}"
        )
