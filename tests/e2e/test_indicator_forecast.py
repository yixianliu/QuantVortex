"""指标预测曲线 + 双向联动 回归测试（offscreen）。

验证：
- 品种入手机会排行：移除「板块」列后共 5 列，其余字段均分列宽。
- MACD/KDJ/RSI 图上叠加未来走势预测曲线（虚线 + 置信带），按 PriceChart
  下标对齐逻辑：历史段以 None 占位，前景段落右侧。
- 联动总线：回测库反哺调参画像结构正确；预测推送待验证信号可被回测中心消费。
运行：
    QT_QPA_PLATFORM=offscreen python tests/e2e/test_indicator_forecast.py
"""
from __future__ import annotations

import sys
import os

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


def _paint(chart):
    """offscreen 下直接驱动一次 paintEvent，验证绘制不崩。"""
    from PyQt6.QtGui import QPaintEvent
    from PyQt6.QtCore import QRect
    chart.resize(360, 240)
    chart.show()
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    chart.paintEvent(QPaintEvent(chart.rect()))


def main() -> None:
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, False)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.indicators.tech import add_indicators
    from futures_quant.ai.linkage_bus import BUS

    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_test.db")

    from futures_quant.ui.predict_ops_page import PredictOpsPage
    page = PredictOpsPage(mdm, store, config=None, session=None)

    passed = 0
    failed = 0
    errors = []

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"✅ {name}")
        else:
            failed += 1
            errors.append(name)
            print(f"❌ {name}")

    # ---- 1. 机会排行：5 列，无「板块」 ----
    hdr = [page.screen_tbl.horizontalHeaderItem(c).text()
           for c in range(page.screen_tbl.columnCount())]
    check("机会排行列数=5", page.screen_tbl.columnCount() == 5)
    check("机会排行已移除板块列", "板块" not in hdr)
    check("机会排行保留品种/评分/20日%/AI方向/操作",
          hdr == ["品种", "评分", "20日%", "AI方向", "操作"])

    # ---- 2. 指标预测曲线：历史段 None 占位、前景段落右侧 ----
    sym = page.cur_symbol
    df = mdm.get_bars(sym, "D", 200)
    ind = add_indicators(df)
    page._render_indicators(ind)
    app.processEvents()

    # MACD 图应含 DIF（历史）+ DIF预测（含 None 占位）+ DEA
    macd_series = page.macd._series
    names = [s.get("name") for s in macd_series]
    check("MACD 含 DIF 历史序列", "DIF" in names)
    check("MACD 含 DIF 预测序列", "DIF预测" in names)
    fc_series = next(s for s in macd_series if s.get("name") == "DIF预测")
    n_hist = len(ind["DIF"].dropna())
    n_fc = len(fc_series["y"])
    # 前景序列长度 = n_hist-1(None) + 1(衔接) + H(外推)
    check("预测序列长度 = 历史-1 + 1 + 步数",
          n_fc == n_hist - 1 + 1 + page.ind_horizon)
    # 前 n_hist-1 个为 None 占位（跳过），末点 + 外推为有限值
    head_none = all(v is None for v in fc_series["y"][:n_hist - 1])
    tail_finite = all(v is not None for v in fc_series["y"][n_hist - 1:])
    check("预测序列历史段为 None 占位", head_none)
    check("预测序列前景段为有限值", tail_finite)
    # 置信带全程有限（历史段零宽）
    check("MACD 含置信带", len(page.macd._bands) >= 1)
    band = page.macd._bands[0]
    check("置信带长度 = 历史 + 步数", len(band["lower"]) == n_hist + page.ind_horizon)
    check("置信带全程有限", all(v is not None for v in band["lower"])
          and all(v is not None for v in band["upper"]))

    # KDJ / RSI 同样含预测序列
    kdj_names = [s.get("name") for s in page.kdj._series]
    rsi_names = [s.get("name") for s in page.rsi._series]
    check("KDJ 含 K 预测序列", "K预测" in kdj_names)
    check("RSI 含 RSI6 预测序列", "RSI6预测" in rsi_names)

    # 绘制不崩
    try:
        _paint(page.macd); _paint(page.kdj); _paint(page.rsi)
        check("指标图 offscreen 绘制不崩", True)
    except Exception as e:  # noqa: BLE001
        check(f"指标图 offscreen 绘制不崩（{e}）", False)

    # 关闭预测曲线开关后重渲染：无预测序列
    page.ind_fc_chk.setChecked(False)
    page._render_indicators(ind)
    app.processEvents()
    names_off = [s.get("name") for s in page.macd._series]
    check("关闭预测开关后无预测序列", "DIF预测" not in names_off)
    page.ind_fc_chk.setChecked(True)

    # ---- 3. 指标预测算法：确定性 + 有界回归 ----
    y = [float(v) for v in ind["RSI6"].dropna().tolist()[-40:]]
    fc, lo, hi = page._indicator_forecast(y, 10, 0.0, 100.0)
    check("RSI 预测长度=10", len(fc) == 10)
    check("RSI 预测全程有限", all(v is not None and -1e6 < v < 1e6 for v in fc))
    check("RSI 预测夹紧在 0~100", all(0.0 <= v <= 100.0 for v in fc))
    check("RSI 置信带宽度随步数扩张", (hi[-1] - lo[-1]) >= (hi[0] - lo[0]))

    # ---- 4. 联动总线：调参画像结构 + 预测↔回测 推送 ----
    t = BUS.get_tuning(sym)
    check("联动画像含 global 字段", "global" in t)
    g = t["global"]
    check("global 含方向一致/反哺权重",
          {"consensus", "strat_weight_base"}.issubset(g.keys()))
    check("反哺权重在 0.30~0.85 区间", 0.30 <= g["strat_weight_base"] <= 0.85)

    # 预测 → 回测：推送待验证信号
    BUS.push_prediction(sym, {"p_up": 0.6, "expected_return_pct": 1.2, "horizon": 12})
    check("预测信号已入总线", BUS.pending_count() >= 1)
    pending = BUS.consume_pending_predictions()
    check("回测中心可消费待验证信号", len(pending) >= 1
          and pending[0].get("symbol") == sym)

    # 回测 → 预测：推送结果触发画像重建且不崩
    BUS.push_backtest_result(sym, {"entry": "ma_cross", "params": {"fast": 5, "slow": 20}},
                             {"total_return": 0.1, "sharpe": 1.2, "max_drawdown": 0.05,
                              "win_rate": 0.55, "profit_factor": 1.5})
    check("回测结果推送不崩", True)

    print("=" * 60)
    print(f"指标预测 + 双向联动 回归：{passed} 通过 / {failed} 失败")
    if errors:
        print("失败项：", errors)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
