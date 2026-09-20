"""M1.5 e2e：持仓模拟组合（资金 / 保证金占用 / 风险度仪表盘），离线验证。

验证点：
- 风险度 = margin_used/equity，等级判定（<0.8 safe / ≥0.8 warn / ≥1.0 danger）。
- 开仓扣保证金 + 手续费；资金不足按可承受手数部分成交。
- 平仓释放保证金 + 结算盈亏。
- mark_to_market 盯市刷新浮动盈亏与风险度。
- 参数非法优雅降级（不抛错）。
- 多空对称：开多赚则开空亏（镜像）。
"""
from __future__ import annotations

import unittest

from futures_quant.broker.paper_portfolio import (
    ALERT_THRESHOLD,
    LIQUIDATE_THRESHOLD,
    PaperPortfolio,
)


def _make(cash: float = 1_000_000.0, multiplier: float = 10.0,
         margin_rate: float = 0.10, commission: float = 0.0) -> PaperPortfolio:
    return PaperPortfolio(cash=cash, multiplier=multiplier,
                          margin_rate=margin_rate, commission=commission)


class TestRiskDegree(unittest.TestCase):
    def test_no_position_risk_zero(self) -> None:
        p = _make()
        self.assertEqual(p.risk_degree(100.0), 0.0)

    def test_risk_degree_formula(self) -> None:
        p = _make(cash=1_000_000, multiplier=10, margin_rate=0.10)
        # 开 100 手 @100：margin=100*100*10*0.10=100000
        p.open_long("rb", 100.0, 100)
        rd = p.risk_degree(100.0)
        # equity = cash_after_open（无浮动盈亏，开仓价=盯市价）
        exp_margin = 100 * 100.0 * 10 * 0.10
        self.assertAlmostEqual(rd, exp_margin / p.equity(100.0), places=6)
        self.assertLess(rd, ALERT_THRESHOLD)

    def test_alert_level(self) -> None:
        p = _make(cash=100_000, multiplier=10, margin_rate=0.20)
        # 开大仓位使风险度 ≥ 0.8
        p.open_long("rb", 100.0, 400)
        st = p.risk_status(100.0)
        self.assertGreaterEqual(st["risk_degree"], ALERT_THRESHOLD)
        self.assertIn(st["level"], ("warn", "danger"))
        self.assertTrue(st["alert"])

    def test_liquidate_level(self) -> None:
        p = _make(cash=50_000, multiplier=10, margin_rate=0.30)
        p.open_long("rb", 100.0, 2000)  # 极端仓位 → 权益被吃穿
        st = p.risk_status(90.0)  # 价格下跌，浮动亏损
        self.assertGreaterEqual(st["risk_degree"], LIQUIDATE_THRESHOLD)
        self.assertTrue(st["liquidate"])


class TestOpenClose(unittest.TestCase):
    def test_open_deducts_margin(self) -> None:
        p = _make(cash=1_000_000, multiplier=10, margin_rate=0.10, commission=1.0)
        cash0 = p.cash
        p.open_long("rb", 100.0, 10)
        # 扣 = 10手 × (100×10×0.10 + 1.0) = 10 × 101 = 1010
        self.assertAlmostEqual(p.cash, cash0 - 1010.0, places=2)
        self.assertEqual(p.long_pos.lots, 10)

    def test_insufficient_funds_partial_fill(self) -> None:
        p = _make(cash=1000, multiplier=10, margin_rate=0.5, commission=0.0)
        # 每手保证金 = 100×10×0.5=500；1000 资金最多 2 手
        res = p.open_long("rb", 100.0, 10)
        self.assertTrue(res["ok"])
        self.assertEqual(res["filled_lots"], 2)

    def test_close_settles_pnl(self) -> None:
        p = _make(cash=1_000_000, multiplier=10, margin_rate=0.10, commission=0.0)
        p.open_long("rb", 100.0, 10)
        res = p.close_long("rb", 120.0)
        # 盈亏 = (120-100)×10×10 = 2000
        self.assertAlmostEqual(res["realized_pnl"], 2000.0, places=2)
        self.assertEqual(p.long_pos.lots, 0)
        # 现金 = 初始 - 开仓占用 + 平仓释放(120×10×10×0.1=1200) + 盈亏2000
        self.assertGreater(p.cash, 1_000_000)  # 盈利后资金增加

    def test_short_mirror_pnl(self) -> None:
        p = _make(cash=1_000_000, multiplier=10, margin_rate=0.10)
        p.open_short("rb", 100.0, 10)
        res = p.close_short("rb", 80.0)  # 价格下跌，空头赚
        self.assertGreater(res["realized_pnl"], 0.0)

    def test_close_no_position(self) -> None:
        p = _make()
        res = p.close_long("rb", 100.0)
        self.assertFalse(res["ok"])


class TestMarkToMarket(unittest.TestCase):
    def test_mt_updates_unrealized(self) -> None:
        p = _make(cash=1_000_000, multiplier=10, margin_rate=0.10)
        p.open_long("rb", 100.0, 10)
        st = p.mark_to_market(110.0)
        # 浮动盈利 = (110-100)×10×10 = 1000 → equity > 开仓后
        self.assertGreater(st["equity"], p.cash)
        self.assertEqual(p._mark_price, 110.0)

    def test_summary_uses_mark_price_when_zero(self) -> None:
        p = _make(cash=1_000_000, multiplier=10, margin_rate=0.10)
        p.open_long("rb", 100.0, 10)
        p.mark_to_market(105.0)
        s = p.summary(price=0.0)
        self.assertEqual(s["mark_price"], 105.0)
        self.assertEqual(s["long_lots"], 10)


class TestDegradation(unittest.TestCase):
    def test_invalid_cash_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PaperPortfolio(cash=0)

    def test_invalid_price_degrades(self) -> None:
        p = _make()
        self.assertEqual(p.open_long("rb", 0.0, 10)["filled_lots"], 0)
        self.assertEqual(p.open_long("rb", -5.0, 10)["filled_lots"], 0)
        self.assertEqual(p.margin_used(0.0), 0.0)
        self.assertEqual(p.risk_degree(-1.0), 0.0)

    def test_zero_lots_rejected(self) -> None:
        p = _make()
        self.assertFalse(p.open_long("rb", 100.0, 0)["ok"])
        self.assertFalse(p.close_long("rb", 100.0, 0)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
