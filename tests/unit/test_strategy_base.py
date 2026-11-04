"""M1-05 StrategyBase 缓冲区语义单元测试。

DoD:
    - deque(maxlen=HISTORY_LEN) 真封顶；
    - `_push` 无 while 循环手动 popleft；
    - `_window_size()` 与 `closes()` 长度关系清晰（`_window_size() <= HISTORY_LEN`，
      数据充足时 `len(closes()) == HISTORY_LEN`）；
    - `_buffer_len` / `_buffer_full` 新增接口可用；
    - `reset()` 清空所有 deque。
"""
from __future__ import annotations

import sys
from collections import deque

import pandas as pd
import pytest

from futures_quant.core.types import Bar
from futures_quant.strategy.base import StrategyBase


class _TestStrategy(StrategyBase):
    """最小测试策略：直接 push。"""
    name = "test"

    def __init__(self, symbol="rb.SHFE", params=None):
        super().__init__(symbol, params)

    def on_bar(self, bar: Bar) -> None:
        self._push(bar)

    def _window_size(self) -> int:
        return int(self.params.get("window", 10))


def _bar(i: int) -> Bar:
    return Bar(
        symbol="rb", datetime=i,
        open=100.0 + i * 0.1, high=101.0 + i * 0.1,
        low=99.0 + i * 0.1, close=100.5 + i * 0.1,
        volume=10, open_interest=100,
    )


def test_deque_maxlen_equals_history_len():
    """所有 deque 都有 maxlen=HISTORY_LEN 真封顶。"""
    s = _TestStrategy()
    assert s.HISTORY_LEN == 500
    assert s._closes.maxlen == 500
    assert s._highs.maxlen == 500
    assert s._lows.maxlen == 500
    assert s._bars.maxlen == 500


def test_buffer_caps_at_history_len():
    """推送 2×HISTORY_LEN 根后，缓冲长度恰为 HISTORY_LEN。"""
    s = _TestStrategy()
    for i in range(2 * s.HISTORY_LEN):
        s._push(_bar(i))
    assert len(s._closes) == s.HISTORY_LEN
    assert len(s._highs) == s.HISTORY_LEN
    assert len(s._lows) == s.HISTORY_LEN
    assert len(s._bars) == s.HISTORY_LEN


def test_buffer_keeps_most_recent():
    """封顶后，缓冲保留最近 HISTORY_LEN 根（丢弃最旧）。"""
    s = _TestStrategy()
    for i in range(s.HISTORY_LEN + 50):
        s._push(_bar(i))
    # 最后 HISTORY_LEN 根的 close：从 i=50 开始，直到 i=HISTORY_LEN+49
    assert s._closes[0] == _bar(50).close
    assert s._closes[-1] == _bar(s.HISTORY_LEN + 49).close


def test_buffer_len_and_full_helpers():
    """新增 _buffer_len / _buffer_full 接口。"""
    s = _TestStrategy()
    assert s._buffer_len() == 0
    assert s._buffer_full() is False
    # 推 5 根：未满
    for i in range(5):
        s._push(_bar(i))
    assert s._buffer_len() == 5
    assert s._buffer_full() is False
    # 推满
    for i in range(5, s.HISTORY_LEN):
        s._push(_bar(i))
    assert s._buffer_len() == s.HISTORY_LEN
    assert s._buffer_full() is True


def test_window_size_bounded_by_history_len():
    """_window_size() 必须 ≤ HISTORY_LEN——否则缓冲不足以算指标。"""
    s = _TestStrategy()
    assert s._window_size() <= s.HISTORY_LEN
    # 子类覆盖 params 时也满足
    s2 = _TestStrategy(params={"window": 100})
    assert s2._window_size() <= s2.HISTORY_LEN


def test_window_size_does_not_shrink_buffer():
    """_window_size() 是指标需求窗口，不影响 deque maxlen。"""
    s = _TestStrategy()
    assert s._closes.maxlen == s.HISTORY_LEN
    # _window_size() 更小，但 deque 仍按 HISTORY_LEN 封顶
    for i in range(s.HISTORY_LEN + 20):
        s._push(_bar(i))
    assert len(s._closes) == s.HISTORY_LEN
    assert s._closes.maxlen == s.HISTORY_LEN


def test_reset_clears_all_buffers():
    """reset() 清空所有 deque。"""
    s = _TestStrategy()
    for i in range(50):
        s._push(_bar(i))
    assert len(s._closes) == 50
    s.reset()
    assert len(s._closes) == 0
    assert len(s._highs) == 0
    assert len(s._lows) == 0
    assert len(s._bars) == 0
    assert s._buffer_full() is False


def test_closes_highs_lows_return_series():
    """closes()/highs()/lows() 返回 pd.Series 且长度一致。"""
    s = _TestStrategy()
    for i in range(20):
        s._push(_bar(i))
    c, h, l = s.closes(), s.highs(), s.lows()
    assert isinstance(c, pd.Series)
    assert isinstance(h, pd.Series)
    assert isinstance(l, pd.Series)
    assert len(c) == len(h) == len(l) == 20
    # 最新值等于最后一根 bar
    assert c.iloc[-1] == _bar(19).close
    assert h.iloc[-1] == _bar(19).high
    assert l.iloc[-1] == _bar(19).low


def test_all_builtin_subclasses_respect_history_len():
    """所有内置策略子类的 _window_size() ≤ HISTORY_LEN。"""
    from futures_quant.strategy import build_strategy, list_strategies

    for name in list_strategies():
        if name == "gene":
            continue  # gene 需要真实 gene dict
        s = build_strategy(name, "rb.SHFE")
        assert s._window_size() <= s.HISTORY_LEN, (
            f"{name}: _window_size()={s._window_size()} > HISTORY_LEN={s.HISTORY_LEN}")
        # deque 都应有 maxlen
        assert s._closes.maxlen == s.HISTORY_LEN


def test_no_manual_popleft_in_push():
    """源码断言：_push 里没有 while 循环 popleft（M1-05 核心修复）。

    用 AST 遍历排除 docstring 与注释，只看实际代码节点。
    """
    import ast
    import inspect
    import textwrap
    src = inspect.getsource(StrategyBase._push)
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.While), (
            "_push 应无 ast.While 节点（依赖 deque.maxlen 自动裁剪）")
    # 检查方法体内没有 .popleft() 调用
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "popleft":
            raise AssertionError("_push 不应调用 .popleft()（deque.maxlen 自动处理）")
