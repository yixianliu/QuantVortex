"""R6 端到端验证：绩效归因对话框（分笔 / 月度收益 / 持仓时长）。

offscreen 直接跑。验证链路：
  A. 真实回测（CsvFeed + 真实合约规格）→ 产生 trades / equity_curve / metrics
  B. BacktestStore.add_history 落库（含 trades_json / equity_curve_json），返回行 id
  C. get_history_detail 按 id 取回 → trades / equity_curve 还原正确
  D. AttributionDialog(detail) 构造后：分笔表（配对回合）非空、月度图/持仓图已渲染、
     摘要卡字段已填充

运行：
  QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/test_backtest_attribution.py \
      > tests/e2e/test_backtest_attribution.log 2>&1; echo rc=$?
"""
from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt6.QtWidgets import QApplication

from futures_quant.data.contract_specs import get_contract_spec, build_contract
from futures_quant.data.csv_feed import CsvFeed
from futures_quant.backtest.backtester import Backtester
from futures_quant.config.settings import Config
from futures_quant.strategy.trend_following import TrendFollowing
from futures_quant.storage.backtest_store import BacktestStore
from futures_quant.ui.attribution_dialog import AttributionDialog

SYM = "rb.SHFE"
START, END, PERIOD = "2018-01-01", "2024-12-31", "D"


def _run_real_backtest():
    """用真实样本 + 真实规格跑一遍，返回 (res, cfg, contract)。"""
    feed = CsvFeed(SYM)
    df = feed.get_history(SYM, START, END, PERIOD)
    assert len(df) > 100, "真实样本应足够长"

    spec = get_contract_spec(SYM)
    contract = build_contract(SYM)

    cfg = Config()
    cfg.account.leverage = spec["leverage"]
    cfg.account.margin_rate = spec["margin_rate"]
    cfg.account.multiplier = spec["multiplier"]
    cfg.account.commission_per_lot = spec["commission_per_lot"]
    cfg.account.close_today_ratio = spec.get("close_today_ratio", 0.0)
    # 放松风控，让策略原始表现充分展现（与回测页一致）
    cfg.risk.max_single_loss = 1e12
    cfg.risk.max_daily_loss = 1e12
    cfg.risk.max_drawdown = 0.99
    cfg.risk.max_position_per_symbol = 100
    cfg.risk.max_total_position_ratio = 0.98
    cfg.risk.max_order_qty = 100
    cfg.backtest.start_cash = 1_000_000
    cfg.account.initial_capital = 1_000_000

    strat = TrendFollowing(SYM, {"fast": 5, "slow": 20})
    bt = Backtester(cfg, feed)
    bt.add_contract(contract)
    bt.add_strategy(strat)
    res = bt.run(SYM, START, END, PERIOD, warmup=60)
    return res, cfg, contract


def test_attribution_roundtrip_and_dialog():
    app = QApplication.instance() or QApplication([])

    # A. 真实回测
    res, _cfg, _contract = _run_real_backtest()
    trades = res.get("trades") or []
    curve = res.get("equity_curve") or []
    metrics = res.get("metrics") or {}
    print(f"A. 真实回测：{len(trades)} 笔成交 / {len(curve)} 点资金曲线")
    assert len(trades) > 0, "回测应产生成交"
    assert len(curve) > 0, "回测应产生资金曲线"
    assert "total_return" in metrics, "metrics 应含 total_return"

    # B. 落库（含 trades_json / equity_curve_json）
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    try:
        store = BacktestStore(tmp)
        snap = {
            "symbol": SYM, "symbol_name": "螺纹钢", "period": PERIOD,
            "generation": 1, "gen_in_symbol": 1,
            "ranked": [{
                "desc": "双均线 5/20", "signature": "sig_r6",
                "gene": {"fast": 5, "slow": 20}, "metrics": metrics,
                "fitness": metrics.get("sharpe", 0.0),
                "profitable": True, "reasons": []}],
            "gen_best_trades": trades,
            "gen_best_curve": curve,
            "new_profitable": [], "profitable_total": 1,
            "library": [], "symbol_done": False,
        }
        hid = store.add_history(snap)
        assert isinstance(hid, int) and hid > 0, "add_history 应返回有效行 id"

        # C. 取回详情，trades / equity_curve 还原正确
        detail = store.get_history_detail(hid)
        assert detail is not None, "应取回详情"
        assert len(detail["trades"]) == len(trades), \
            f"trades 还原数应一致：{len(detail['trades'])} vs {len(trades)}"
        assert len(detail["equity_curve"]) == len(curve), \
            f"equity_curve 还原数应一致：{len(detail['equity_curve'])} vs {len(curve)}"
        print(f"C. 详情还原：trades={len(detail['trades'])}, "
              f"curve={len(detail['equity_curve'])}, id={hid}")

        # D. 打开归因对话框，验证渲染
        dlg = AttributionDialog(detail)
        app.processEvents()
        rows = dlg._trade_tbl.rowCount()
        print(f"D. 归因对话框：分笔表 {rows} 行（配对回合），"
              f"月度图标题='{dlg._month_chart._title}', "
              f"持仓图标题='{dlg._hold_chart._title}'")
        assert rows > 0, "归因对话框分笔表应至少 1 行（配对回合）"
        assert dlg._summary is not None, "摘要卡应已构建"
        # 月度图标题应含「月」字（有数据时）
        assert "月" in (dlg._month_chart._title or ""), "月度收益图应渲染数据"
        # 摘要卡应填了 收益 字段（非空）
        ret_text = dlg._summary._cells["return"].text()
        assert ret_text not in (None, "", "—"), "摘要卡收益字段应已填充"
        dlg.close()
        store.close()
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    print("\n=== R6 e2e 全部通过 ===")


if __name__ == "__main__":
    test_attribution_roundtrip_and_dialog()
