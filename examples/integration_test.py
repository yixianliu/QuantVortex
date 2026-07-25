"""一键集成自测：验证存储 / 回测 / UI 构造 全链路。

运行：
    python examples/integration_test.py

退出码 0 = 全部通过；非 0 = 有失败项（并打印异常）。
"""
from __future__ import annotations

import os
import sys
import tempfile

# UI 构造需无窗口环境（headless），必须在 import PyQt6 前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

PASS = []
FAIL = []


def _ok(name: str) -> None:
    PASS.append(name)
    print(f"[PASS] {name}")


def _bad(name: str, exc: Exception) -> None:
    FAIL.append(name)
    print(f"[FAIL] {name}: {exc!r}")


def test_storage() -> None:
    from futures_quant.config.settings import Config
    from futures_quant.storage import get_storage
    from futures_quant.core.types import Trade, Direction, Offset
    from datetime import datetime

    cfg = Config()
    cfg.storage.sqlite_path = os.path.join(tempfile.gettempdir(), f"it_storage_{os.getpid()}.db")
    db = get_storage(cfg)
    t = Trade("rb.SHFE", Direction.LONG, Offset.OPEN, 2, 3500.0,
              datetime.now(), commission=6.0, pnl=0.0)
    db.insert_trade(t)
    rows = db.query_trades("rb.SHFE")
    assert len(rows) == 1 and rows[0]["commission"] == 6.0
    db.save_param("k", "v")
    assert db.load_param("k") == "v"
    db.close()
    _ok("存储层 SQLite 读写")


def test_backtest() -> None:
    from futures_quant.config.settings import Config
    from futures_quant.data.base import Contract
    from futures_quant.data.synthetic import SyntheticFeed, generate_bars
    from futures_quant.backtest.backtester import Backtester
    from futures_quant.strategy.trend_following import TrendFollowing

    out_dir = os.path.join(tempfile.gettempdir(), "it_bt")
    cfg = Config()
    feed = SyntheticFeed()
    sym = "IT.SHFE"
    feed._cache[(sym, "1m")] = generate_bars(symbol=sym, mode="trend", n=3000, seed=3)
    bt = Backtester(cfg, feed)
    bt.add_contract(Contract(symbol=sym, exchange="SHFE", multiplier=10,
                             min_price_tick=1.0, margin_rate=0.10,
                             commission_per_lot=3.0, trading_hours=[]))
    bt.add_strategy(TrendFollowing(sym, {}))
    out = bt.run(sym, "2024-01-01", "2024-12-31", period="1m", warmup=60)
    files = bt.export(outdir=out_dir, prefix="IT")
    for key, path in files.items():
        assert os.path.exists(path) and os.path.getsize(path) > 0, f"{key} 文件缺失/空"
    m = out["metrics"]
    for k in ("total_return", "sharpe", "max_drawdown", "win_rate", "long_opens", "short_opens"):
        assert k in m, f"指标缺失 {k}"
    assert os.path.getsize(files["html"]) > 2000, "HTML 报告过小"
    _ok("回测引擎 + 三件套 + 报告")


def test_ui() -> None:
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception as exc:  # noqa
        _bad("UI 构造 (PyQt6 不可用)", exc)
        return
    from futures_quant.ui.main_window import MainWindow
    app = QApplication(sys.argv)
    w = MainWindow()
    # 跑几帧仿真，触发 行情→风控→撮合→记账→刷新 链路
    for _ in range(5):
        w._tick()
    assert w.engine is not None
    # 手动下单 / 锁仓 路径
    w.m_dir.setCurrentText("买(多)")
    w.m_off.setCurrentText("开仓")
    w._manual_order()
    w._lock()
    assert w.engine.risk.halted is True

    # 切到预测页并运行预测
    w._select_nav(6)  # 预测页索引
    w.pd_mode.setCurrentText("trend")
    w._run_prediction()
    assert len(w.pred_chart._series) >= 2, "预测图未生成序列"
    assert w.pred_table.rowCount() == w.pd_horizon.value(), "预测表行数不符"
    assert w.pred_summary.toPlainText().strip(), "预测摘要为空"

    # 图表组件直接验证
    from futures_quant.ui.chart_widget import PriceChart
    chart = PriceChart()
    chart.set_data([{"name": "A", "color": "#3b82f6", "x": [0, 1, 2], "y": [1.0, 2.0, 1.5]}],
                   bands=[{"lower": [0.9, 1.9, 1.4], "upper": [1.1, 2.1, 1.6], "color": "#3b82f6", "alpha": 35}])
    assert len(chart._series) == 1 and len(chart._bands) == 1
    chart.update()
    _ok("UI 构造 + 仿真帧 + 手动下单/锁仓 + 预测模块 + 图表组件")


def test_predictor() -> None:
    from futures_quant.data.synthetic import generate_bars
    from futures_quant.analytics import Predictor
    pred = Predictor()
    for mode in ("trend", "range", "mixed"):
        df = generate_bars(symbol="PRED.SHFE", mode=mode, n=300, seed=7)
        res = pred.predict(df["close"].tolist(), df["high"].tolist(), df["low"].tolist(),
                           df["datetime"].tolist(), horizon=20, lookback=120)
        assert len(res.forecast) == len(res.upper) == len(res.lower)
        for lo, fc, hi in zip(res.lower, res.forecast, res.upper):
            assert lo <= fc <= hi and lo > 0
        assert res.direction in ("看涨", "看跌", "震荡")
        assert 0.0 <= res.confidence <= 1.0
    _ok("预测模块 趋势分析 + 外推预测（三模式）")


def main() -> None:
    print("=== FuturesQuant 集成自测 ===")
    for fn in (test_storage, test_backtest, test_ui, test_predictor):
        try:
            fn()
        except Exception as exc:  # noqa
            _bad(fn.__name__, exc)
    print(f"\n结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()
