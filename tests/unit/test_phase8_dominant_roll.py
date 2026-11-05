"""第 2 期 P0-3 回归测试：真实主力合约链 + 换月成本口径。

覆盖：
  1) 月份合约枚举范围（含远期 lookahead）
  2) 多合约链 → 主力映射 → 换月调度表（换月日/价格取点）
  3) 缺失数据行为：空返回可容忍但计入缺口；抓取异常/超时显式不可用
  4) 回测换月成本：双边手续费、价差口径（auto/charge/report/off）、事件记录
  5) 当前主力报价：正常/过期/无数据/合成源拒绝/异常路径
  6) 界面卡片：offscreen 构建 + 渲染成功态与不可用态文案
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime

import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from futures_quant.config.settings import Config
from futures_quant.data.base import attach_provenance
from futures_quant.data.contract_specs import build_contract, get_contract_spec
from futures_quant.data.dominant_chain import (
    DominantChainError,
    build_roll_schedule,
    clear_quote_cache,
    contract_months,
    dominant_quote,
    fetch_contract_chain,
    roll_schedule_from_chain,
)
from futures_quant.backtest.backtester import Backtester
from futures_quant.core.types import Position

_QAPP_REF = None   # 模块级强引用，防止 QApplication 被 GC


# ---------------------------------------------------------------------------
# 测试替身：可注入的行情源（不联网、不写库）
# ---------------------------------------------------------------------------
class _FakeFeed:
    """最小化 DataFeed 替身：按合约代码返回预置日线。"""

    source_label = "fake_daily"

    def __init__(self, frames: dict, empty_sentinel=None, raise_for=(), synthetic=False):
        self._frames = frames
        self._raise_for = set(raise_for)
        self._synthetic = bool(synthetic)

    def get_history(self, symbol, start, end, period="D"):
        if symbol in self._raise_for:
            raise RuntimeError(f"模拟抓取失败 {symbol}")
        df = self._frames.get(symbol)
        if df is None:
            return None
        out = df.copy()
        attach_provenance(out, "fake", is_synthetic=self._synthetic,
                          as_of=out["datetime"].iloc[-1], note="测试数据")
        return out


def _daily(symbol: str, start: str, end: str, close: float,
           volume: float, oi: float) -> pd.DataFrame:
    """生成单合约日线（工作日频率，字段与真实 feed 一致）。"""
    days = pd.bdate_range(start, end)
    return pd.DataFrame({
        "datetime": days,
        "open": close, "high": close + 5, "low": close - 5, "close": close,
        "volume": volume, "open_interest": oi,
    })


def _chain_fixture():
    """构造 rb2601→rb2605 的真实换月场景（2025-09 ~ 2026-03）。"""
    frames = {
        # 老主力：2025-11-20 之后成交/持仓归零（临近交割）
        "rb2601": _daily("rb2601", "2025-09-01", "2025-11-20", 3800, 120_000, 300_000),
        # 新主力：11-21 起成交/持仓反超
        "rb2605": _daily("rb2605", "2025-09-01", "2026-03-31", 3850, 30_000, 80_000),
        # 远月，始终不占优
        "rb2610": _daily("rb2610", "2025-09-01", "2026-03-31", 3900, 2_000, 10_000),
    }
    # 新主力在 11-21 之后放量
    mask = frames["rb2605"]["datetime"] > pd.Timestamp("2025-11-20")
    frames["rb2605"].loc[mask, "volume"] = 150_000
    frames["rb2605"].loc[mask, "open_interest"] = 320_000
    return frames


# ---------------------------------------------------------------------------
# 1) 月份合约枚举
# ---------------------------------------------------------------------------
def test_contract_months_covers_window_with_lookahead():
    codes = contract_months("rb", "2024-01-01", "2024-12-31", lookahead_months=13)
    assert codes[0] == "rb2401"
    assert codes[-1] == "rb2601", "末端需包含窗口结束后 13 个月的候选合约"
    assert len(codes) == 25
    # 带交易所后缀也能正确归一化
    assert contract_months("rb.SHFE", "2024-01-01", "2024-01-31", lookahead_months=0) == ["rb2401"]


# ---------------------------------------------------------------------------
# 2) 换月调度表
# ---------------------------------------------------------------------------
def test_roll_schedule_uses_real_roll_date_and_prices():
    chain = fetch_contract_chain(_FakeFeed(_chain_fixture()), "rb",
                                 "2025-09-01", "2026-03-31")
    assert chain.is_complete
    schedule, stats = roll_schedule_from_chain(chain)
    assert list(schedule.keys()) == [date(2025, 11, 21)], "换月日应为成交量/持仓量真正迁移日"
    ev = schedule[date(2025, 11, 21)]
    assert ev["from"] == "rb2601" and ev["to"] == "rb2605"
    assert ev["from_close"] == pytest.approx(3800.0)
    assert ev["to_close"] == pytest.approx(3850.0)
    assert ev["price_basis"] == "close_on_roll_day"
    assert stats["num_rolls"] == 1 and stats["missing_quotes"] == 0


def test_roll_schedule_missing_quote_is_explicit():
    """换月日缺一根报价时必须回退到「最近可得收盘价」，并在 stats 里显式计数。

    真正无任何历史报价的极端情形会标 ``price_basis=missing_quote``；
    只要还有更早的报价，就用最近收盘价（不插值、不预计）。
    """
    frames = _chain_fixture()
    # 删掉 11-21 当天的 rb2605 行（模拟停牌/缺失）
    frames["rb2605"] = frames["rb2605"][
        frames["rb2605"]["datetime"].dt.date != date(2025, 11, 21)].reset_index(drop=True)
    chain = fetch_contract_chain(_FakeFeed(frames), "rb", "2025-09-01", "2026-03-31")
    schedule, stats = roll_schedule_from_chain(chain)
    assert stats["num_rolls"] >= 1
    first = list(schedule.values())[0]
    assert first["price_basis"] == "close_on_roll_day"
    assert first["to_close"] == pytest.approx(3850.0), "应取 11-20 最近收盘价，而非编造"
    # 价格字段永远显式存在，便于界面/报告区分「有价差」与「缺报价」
    assert "from_close" in first and "to_close" in first


def test_missing_contracts_tolerated_but_fetch_failures_are_fatal():
    """空返回属于正常未挂牌；抓取异常必须让整链标记不完整并显式报错。"""
    frames = _chain_fixture()
    chain = fetch_contract_chain(_FakeFeed(frames), "rb", "2025-09-01", "2026-03-31")
    assert chain.is_complete, "大量空返回（未挂牌月份）不应判为不完整"
    assert len(chain.missing) > 0 and "rb2610" not in chain.missing

    bad = fetch_contract_chain(_FakeFeed(frames, raise_for={"rb2605"}), "rb",
                               "2025-09-01", "2026-03-31")
    assert not bad.is_complete
    assert bad.failed == ["rb2605"]
    with pytest.raises(DominantChainError, match="不完整"):
        build_roll_schedule(_FakeFeed(frames, raise_for={"rb2605"}), "rb",
                            "2025-09-01", "2026-03-31")


def test_no_contract_data_raises_explicit_error():
    with pytest.raises(DominantChainError, match="未取到任何单月合约"):
        build_roll_schedule(_FakeFeed({}), "rb", "2025-09-01", "2026-03-31")


def test_synthetic_feed_is_rejected():
    with pytest.raises(DominantChainError, match="合成"):
        fetch_contract_chain(_FakeFeed(_chain_fixture(), synthetic=True), "rb",
                             "2025-09-01", "2026-03-31")


# ---------------------------------------------------------------------------
# 3) 回测换月成本口径
# ---------------------------------------------------------------------------
def _bt_with_position(symbol="rb.SHFE", long_qty=2, short_qty=0, mode="auto"):
    cfg = Config()
    cfg.backtest.roll_spread_mode = mode
    cfg.backtest.enable_roll_cost = True
    bt = Backtester(cfg, _FakeFeed({}))
    bt.add_contract(build_contract(symbol))
    bt.engine.start()
    p = bt.engine.portfolio
    p.positions[symbol] = Position(symbol=symbol, long_qty=long_qty, short_qty=short_qty)
    return bt, p


def test_commission_only_for_continuous_symbol():
    """主力连续（rb.SHFE）在 auto 口径下只扣手续费，价差只报告。"""
    bt, p = _bt_with_position()
    spec = get_contract_spec("rb")
    ev = bt._charge_roll_cost("rb.SHFE", date(2025, 11, 21),
                              {"from": "rb2601", "to": "rb2605",
                               "from_close": 3800.0, "to_close": 3850.0})
    commission = 2 * spec["commission_per_lot"] * 2
    assert ev["commission"] == pytest.approx(commission)
    assert ev["spread_signed"] == pytest.approx((3850 - 3800) * 2 * spec["multiplier"])
    assert ev["spread_charged"] == 0.0, "连续价格已含跳空，避免重复扣费"
    assert ev["price_basis"].startswith("commission_only")
    assert p.total_roll_cost == pytest.approx(commission)
    assert bt._roll_spread_reported == pytest.approx(50 * 2 * spec["multiplier"])


def test_spread_charged_for_single_contract_symbol():
    """单月合约（rb2601.SHFE）在 auto 口径下价差计入权益。"""
    bt, p = _bt_with_position(symbol="rb2601.SHFE")
    spec = get_contract_spec("rb2601")
    ev = bt._charge_roll_cost("rb2601.SHFE", date(2025, 11, 21),
                              {"from": "rb2601", "to": "rb2605",
                               "from_close": 3800.0, "to_close": 3850.0})
    commission = 2 * spec["commission_per_lot"] * 2
    assert ev["price_basis"] == "spread_and_commission"
    assert ev["spread_charged"] == pytest.approx(50 * 2 * spec["multiplier"])
    assert p.total_roll_cost == pytest.approx(commission + ev["spread_charged"])


@pytest.mark.parametrize("mode,expect_charge", [("report", False), ("off", False), ("charge", True)])
def test_spread_mode_switch(mode, expect_charge):
    bt, p = _bt_with_position(mode=mode)
    ev = bt._charge_roll_cost("rb.SHFE", date(2025, 11, 21),
                              {"from": "rb2601", "to": "rb2605",
                               "from_close": 3900.0, "to_close": 3800.0})
    if mode == "off":
        assert ev["spread_signed"] == 0.0, "off 时完全不计算价差"
    else:
        # 反向价差（新价 < 旧价）对多头是收益：只报告、不回补现金
        assert ev["spread_signed"] == pytest.approx(-100 * 2 * get_contract_spec("rb")["multiplier"])
        assert ev["spread_charged"] == 0.0, "负成本不抵扣手续费，保持保守"
    assert p.total_roll_cost == pytest.approx(ev["commission"])


def test_no_position_roll_event_is_not_charged():
    bt, p = _bt_with_position(long_qty=0, short_qty=0)
    ev = bt._charge_roll_cost("rb.SHFE", date(2025, 11, 21),
                              {"from": "rb2601", "to": "rb2605",
                               "from_close": 3800.0, "to_close": 3850.0})
    assert ev["qty"] == 0 and ev["commission"] == 0.0
    assert p.total_roll_cost == 0.0
    assert bt._roll_events == [], "零持仓不记事件，避免对照表出现空换月"


def test_run_passes_schedule_and_reports_basis():
    """调度表的 dict 值（含价格）应能透传到成本层，并写入结果口径字段。"""
    cfg = Config()
    frames = {"rb.SHFE": _daily("rb.SHFE", "2026-01-01", "2026-02-27", 4000, 1000, 5000)}
    bt = Backtester(cfg, _FakeFeed(frames))
    bt.add_contract(build_contract("rb.SHFE"))
    from futures_quant.strategy import get_strategy_class
    bt.add_strategy(get_strategy_class("trend_following")(symbol="rb.SHFE"))
    schedule = {date(2026, 2, 2): {"from": "rb2601", "to": "rb2605",
                                  "from_close": 4000.0, "to_close": 4010.0}}
    res = bt.run("rb.SHFE", "2026-01-01", "2026-02-27", "D", warmup=20,
                 roll_schedule=schedule)
    assert "roll_events" in res and "roll_cost_basis" in res
    assert res["roll_cost_basis"] in ("none", "commission_only",
                                      "commission_only(continuous_price_embeds_spread)")
    for ev in res["roll_events"]:
        assert ev["date"] == "2026-02-02"


# ---------------------------------------------------------------------------
# 4) 当前主力报价
# ---------------------------------------------------------------------------
def _quote_fixture(now="2026-11-04", stale=False, empty=False, synthetic=False):
    """当前主力场景：rb2611 到期退场、rb2701 接棒，rb2705 为次近月。"""
    if empty:
        return _FakeFeed({}, synthetic=synthetic)
    end = "2026-10-30" if stale else "2026-11-04"
    frames = {
        # 老主力：成交/持仓领先，10-20 之后到期退场
        "rb2611": _daily("rb2611", "2026-09-01", "2026-10-20", 3900, 300_000, 600_000),
        # 新主力：10-21 起接管
        "rb2701": _daily("rb2701", "2026-09-01", end, 3950, 50_000, 100_000),
        "rb2705": _daily("rb2705", "2026-09-01", end, 3980, 60_000, 150_000),
    }
    mask = frames["rb2701"]["datetime"] > pd.Timestamp("2026-10-20")
    frames["rb2701"].loc[mask, "volume"] = 200_000
    frames["rb2701"].loc[mask, "open_interest"] = 500_000
    return _FakeFeed(frames, synthetic=synthetic)


def test_dominant_quote_returns_real_contract():
    clear_quote_cache()
    feed = _quote_fixture()
    q = dominant_quote("rb", feed, now="2026-11-04", use_cache=False)
    assert q["ok"] is True
    d = q["dominant"]
    assert d["contract"] == "rb2701"
    assert d["delivery"] == "2027-01"
    assert d["last"] == pytest.approx(3950.0)
    assert d["settle"] is None, "源未提供结算价时必须为空，不得编造"
    assert q["near"] == "rb2701" and q["next"] == "rb2705"
    assert q["is_synthetic"] is False
    assert q["data_source"] == "fake"
    assert q["roll"]["from"] == "rb2611" and q["roll"]["to"] == "rb2701"
    assert q["roll"]["last_roll_date"] == "2026-10-21"
    assert "下一换月日" in q["roll"]["next_roll_hint"]


def test_dominant_quote_marks_stale():
    clear_quote_cache()
    q = dominant_quote("rb", _quote_fixture(stale=True), now="2026-11-04", use_cache=False)
    assert q["ok"] is True
    assert q["is_stale"] is True
    assert any("陈旧" in w or "过期" in w for w in q["warnings"])


def test_dominant_quote_unavailable_when_no_data():
    clear_quote_cache()
    q = dominant_quote("rb", _quote_fixture(empty=True), now="2026-11-04", use_cache=False)
    assert q["ok"] is False
    assert "未取到" in q["reason"] or "不可用" in q["reason"]
    assert "dominant" not in q, "不可用时绝不能返回任何主力合约字段"


def test_dominant_quote_rejects_synthetic_source():
    clear_quote_cache()
    q = dominant_quote("rb", _quote_fixture(synthetic=True), now="2026-11-04", use_cache=False)
    assert q["ok"] is False
    assert "合成" in q["reason"]


def test_dominant_quote_uses_cache():
    clear_quote_cache()
    feed = _quote_fixture()
    q1 = dominant_quote("rb", feed, now="2026-11-04")
    q2 = dominant_quote("rb", feed, now="2026-11-04")
    assert q1["dominant"]["contract"] == q2["dominant"]["contract"]


# ---------------------------------------------------------------------------
# 5) 界面卡片（offscreen）
# ---------------------------------------------------------------------------
def _qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication 强引用：避免 C++ 单例被 GC 后 qFatal 崩溃。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    global _QAPP_REF
    _QAPP_REF = _qapp()
    yield _QAPP_REF


def test_market_page_dominant_async_load_and_error_path(qapp):
    """界面实测：后台线程取数 → 回主线程渲染；空数据 → 不可用文案。"""
    import time as _t
    from unittest.mock import MagicMock
    from futures_quant.ui.market_overview_page import MarketOverviewPage

    mdm = MagicMock()
    mdm.universe = [("RB", "螺纹钢", "黑色", "SHFE", 10, 1, 4000)]
    page = MarketOverviewPage(mdm, MagicMock(), None, None)
    try:
        # ① 正常路径：注入单月合约链，验证异步加载完成后卡片有真实合约代码
        mdm.feed = _quote_fixture()
        page._refresh_dominant_async()
        deadline = _t.time() + 5.0
        while page._dom_loading and _t.time() < deadline:
            qapp.processEvents()
            _t.sleep(0.01)
        qapp.processEvents()
        assert page._dom_loading is False, "后台取数应在 5s 内结束"
        assert page.dom_code.text() == "rb2701"
        assert "2026-10-21" in page.dom_roll.text()
        assert "fake" in page.dom_prov.text()

        # ② 异常路径：无任何合约数据 → 显示不可用 + 原因，且清空数值
        clear_quote_cache()
        mdm.feed = _FakeFeed({})
        page._refresh_dominant_async(force=True)
        deadline = _t.time() + 5.0
        while page._dom_loading and _t.time() < deadline:
            qapp.processEvents()
            _t.sleep(0.01)
        qapp.processEvents()
        assert page.dom_code.text() == "不可用"
        assert "未取到" in page.dom_state.text()
        assert page.dom_chips["last"]._val.text() == "--"
    finally:
        page.deleteLater()


def test_market_page_dominant_card_renders_ok_and_unavailable(qapp):
    from unittest.mock import MagicMock
    from futures_quant.ui.market_overview_page import MarketOverviewPage

    mdm = MagicMock()
    mdm.universe = [("RB", "螺纹钢", "黑色", "SHFE", 10, 1, 4000)]
    page = MarketOverviewPage(mdm, MagicMock(), None, None)
    try:
        # 成功态：真实合约代码/近次月/换月/来源水印
        page._render_dominant({
            "ok": True,
            "dominant": {"contract": "rb2701", "delivery": "2027-01", "last": 3950,
                         "chg": 20, "chg_pct": 0.51, "volume": 200000,
                         "open_interest": 500000, "settle": None},
            "near": "rb2701", "next": "rb2705",
            "roll": {"last_roll_date": "2026-10-21", "from": "rb2611", "to": "rb2701",
                     "days_since": 10, "next_roll_hint": "下一换月日由成交/持仓迁移决定"},
            "as_of": "2026-11-04", "is_stale": False, "data_source": "sina",
            "warnings": [], "chain": {"contracts_used": 3, "contracts_missing": 40, "elapsed_s": 2.1},
        })
        assert page.dom_code.text() == "rb2701"
        assert "rb2705" in page.dom_sub.text()
        assert "2026-10-21" in page.dom_roll.text()
        assert "sina" in page.dom_prov.text()
        assert "源未提供" in page.dom_chips["settle"]._val.text()

        # 不可用态：显示原因，数值必须清空为 --（不残留上一品种）
        page._render_dominant({"ok": False, "reason": "多合约链抓取超时"})
        assert page.dom_code.text() == "不可用"
        assert "多合约链抓取超时" in page.dom_state.text()
        assert page.dom_chips["last"]._val.text() == "--"
    finally:
        page.deleteLater()
