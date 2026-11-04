"""第三轮 A · P1 回归测试：数据新鲜度阈值在取数层生效。

口径：
- 日线：最后一根日线与当前日期相差 > 1 个交易日 → stale；
- 分钟线：> 5 分钟（且不小于 5 个周期长度）→ stale；
- 周线：> 7 个自然日 → stale。
"""
from __future__ import annotations

import pandas as pd

from futures_quant.data.base import evaluate_staleness


def test_daily_stale_after_more_than_one_trading_day():
    # 周五收盘，周一早上：仍新鲜（只隔 1 个工作日以内）
    assert evaluate_staleness("2026-10-30 15:00", "D", now="2026-11-02 09:00")[0] is False
    # 周二早上：周五之后已过 2 个交易日 → stale
    stale, why = evaluate_staleness("2026-10-30 15:00", "D", now="2026-11-03 09:00")
    assert stale is True
    assert "交易日" in why


def test_minute_stale_after_five_minutes():
    assert evaluate_staleness("2026-11-03 10:00:00", "1m",
                              now="2026-11-03 10:03:00")[0] is False
    stale, why = evaluate_staleness("2026-11-03 09:55:00", "1m",
                                    now="2026-11-03 10:00:30")
    assert stale is True
    assert "秒" in why


def test_five_minute_period_uses_five_bar_window():
    # 5m 线：阈值 25 分钟（不小于 5 分钟）
    assert evaluate_staleness("2026-11-03 09:35", "5m",
                              now="2026-11-03 09:58")[0] is False
    assert evaluate_staleness("2026-11-03 09:35", "5m",
                              now="2026-11-03 10:05")[0] is True


def test_weekly_and_unknown_period():
    assert evaluate_staleness("2026-10-26", "W", now="2026-11-02")[0] is False
    assert evaluate_staleness("2026-10-19", "W", now="2026-11-02")[0] is True
    # 未知周期不误报
    assert evaluate_staleness("2020-01-01", "tick", now="2026-11-02")[0] is False


def test_market_data_get_bars_marks_stale(monkeypatch):
    """取数层：真实源最后一根日线过旧时，get_bars 返回 is_stale=True。"""
    from futures_quant.data import market_data as md

    class _Mgr(md.MarketDataManager):
        def __init__(self):  # 绕过网络/线程初始化
            self.source = "csv"
            self._full = {}

    mgr = _Mgr()
    df = pd.DataFrame({
        "datetime": pd.bdate_range("2026-09-01", periods=5),
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
        "volume": 1.0, "open_interest": 1.0,
    })
    from futures_quant.data.base import attach_provenance
    attach_provenance(df, "csv", as_of="2026-09-05")
    mgr._full[("rb.SHFE", "D")] = df
    out = mgr.get_bars("rb.SHFE", "D", limit=5)
    assert out.attrs["is_stale"] is True
    assert "过期" in out.attrs["note"]
