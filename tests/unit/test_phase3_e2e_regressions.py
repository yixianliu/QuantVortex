"""阶段 3 e2e 修复配套回归测试（纯逻辑，无 GUI 依赖）。

覆盖两处会让 e2e 长期飘红/失真的产品缺陷：
1. 日线 K 线时间戳为 00:00:00，旧逻辑按「交易时段」拦截，导致真实日线回测
   零成交、资金曲线恒为平直（test_backtest_real_akshare 三项失败的根因）；
2. 漂移检测样本不足时 correlation 返回 0.0，调用方会把「无数据」误读成
   「无相关性」这一真实结论；应降级为 None。
"""
from __future__ import annotations

from datetime import datetime

from futures_quant.ai.drift import detect_drift
from futures_quant.config.settings import RiskConfig
from futures_quant.core.types import Direction, Offset, Order
from futures_quant.data.contract_specs import build_contract
from futures_quant.risk.risk_manager import RiskManager

SYM = "rb.SHFE"


class _PortfolioStub:
    """RiskManager.check_order 所需的最小组合接口（避免引入真实账户状态）。"""

    def __init__(self) -> None:
        self.positions: dict = {}
        self.margin_rate = 0.10
        self._current_prices = {SYM: 3500.0}

    def used_margin(self) -> float:
        return 0.0

    def equity(self) -> float:
        return 1_000_000.0

    def available(self) -> float:
        return self.equity() - self.used_margin()

    def _multiplier(self, _symbol: str) -> float:
        return 10.0


def _order(qty: int = 1) -> Order:
    return Order(symbol=SYM, direction=Direction.LONG, offset=Offset.OPEN, quantity=qty)


def test_daily_bar_not_blocked_by_trading_hours():
    """00:00:00 日线时间戳必须跳过交易时段校验，否则日线回测恒零成交。"""
    rm = RiskManager(RiskConfig())
    contract = build_contract(SYM)
    pf = _PortfolioStub()

    ok, reason = rm.check_order(_order(), pf, contract=contract,
                                dt=datetime(2024, 1, 2, 0, 0, 0))
    assert ok, f"日线 bar 应允许下单，实际被拒：{reason}"

    # 日内 bar 仍严格按时段校验：09:15 在交易时段内 → 通过。
    ok, reason = rm.check_order(_order(), pf, contract=contract,
                                dt=datetime(2024, 1, 2, 9, 15, 0))
    assert ok, f"09:15 应允许下单，实际被拒：{reason}"

    # 12:00 处于午间休市 → 必须拦截，证明修正没有放宽日内风控。
    ok, reason = rm.check_order(_order(), pf, contract=contract,
                                dt=datetime(2024, 1, 2, 12, 0, 0))
    assert not ok and "非交易时段" in reason


def test_drift_no_data_correlation_is_none():
    """样本不足时 correlation 应为 None（无数据 ≠ 零相关）。"""
    res = detect_drift([0.5, 0.5, 0.5], 0.5, min_days=10)
    assert res.status == "no_data"
    assert res.correlation is None
    assert res.to_dict()["correlation"] is None


# ---------------------------------------------------------------------------
# 阶段 3 第二批：预测结论诚实呈现（只读既有 API，不改 ai/ 评估逻辑）
# ---------------------------------------------------------------------------
def test_band_cov_text_consumes_real_interface_without_fallback():
    """区间覆盖率：②行文案只吃真实覆盖率接口，None 时严禁回退近似值。

    契约变更（第六轮）：旧 ``_band_coverage`` 用当前残差 σ 现算近似覆盖率，口径不对，
    已删除；改为 ``ai.evaluation.evaluate_interval_coverage`` 的真实口径。
    """
    from futures_quant.ai.evaluation import evaluate_interval_coverage
    from futures_quant.ui.predict_ops_page import PredictOpsPage

    # 老数据（lower/upper 为 NULL）→ coverage=None 且给出原因
    info = evaluate_interval_coverage(rows=[{
        "symbol": "rb.SHFE", "horizon": 5, "last_close": 3500.0,
        "actual_return_pct": 0.3, "lower": None, "upper": None,
    }])
    assert info["coverage"] is None and info.get("reason"), info

    txt = PredictOpsPage._band_cov_text(info)
    assert "样本不足" in txt and "不回退近似值" in txt, txt

    # 尚未算出（None）只显示「计算中…」，不得出现任何覆盖率数字
    pending = PredictOpsPage._band_cov_text(None)
    assert "计算中" in pending and "%" not in pending, pending

    # 有真实样本：显示实测覆盖率 + 样本量 + 95% CI
    txt2 = PredictOpsPage._band_cov_text(
        {"coverage": 0.71, "n": 120, "ci_low": 0.62, "ci_high": 0.79})
    assert "71.0%" in txt2 and "n=120" in txt2 and "95% CI" in txt2, txt2


def test_oos_stats_calls_existing_hit_rate_api():
    """样本外统计：空库降级为 not usable；有样本时委托既有命中率 API。"""
    from types import SimpleNamespace

    from futures_quant.ui.predict_ops_page import PredictOpsPage

    class _EmptyStore:
        def query_closed_for_calibration(self, limit=2000):
            return []

    class _RowsStore:
        def query_closed_for_calibration(self, limit=2000):
            rows = [{"p_up": 0.6, "y_up": 1} for _ in range(100)]
            rows += [{"p_up": 0.4, "y_up": 0} for _ in range(100)]
            rows += [{"p_up": 0.5, "y_up": None}]   # 未结算：必须被剔除
            return rows

    empty = PredictOpsPage._oos_stats(SimpleNamespace(store=_EmptyStore()))
    assert empty["usable"] is False and empty["n"] == 0

    st = PredictOpsPage._oos_stats(SimpleNamespace(store=_RowsStore()))
    assert st["usable"] is True and st["n"] == 200
    assert st["hit_rate"] == 1.0 and st["base_rate"] == 0.5
    assert st["significant"] is True


def test_backtest_service_accepts_should_abort():
    """独立回测「取消」依赖服务层透传 should_abort（内核检查点未改）。"""
    import inspect

    from futures_quant.app.backtest_service import BacktestService

    sig = inspect.signature(BacktestService.run_backtest)
    assert "should_abort" in sig.parameters
    assert sig.parameters["should_abort"].default is None
