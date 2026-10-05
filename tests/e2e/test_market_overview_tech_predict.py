"""行情全景 云端研判扩充 + 预测页副图布局（offscreen 冒烟测试，无网络依赖）。

覆盖两点需求：
  1) 行情全景右侧 AI 面板大幅扩充：技术面解读（均线/MACD/布林/KDJ/RSI/OBV/支撑阻力）
     + 多空力量对比 + 趋势预测与综合研判；双 Tab（AI综合研判 / 技术面解读）。
  2) 预测操作页 K 线下方 MACD/KDJ/RSI 三图改为垂直堆叠、各独占一行、最小高度≥150。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PyQt6.QtWidgets import QApplication, QVBoxLayout
from PyQt6.QtCore import Qt

import futures_quant.ai.news_feed as nf
from PyQt6.QtCore import QTimer


def _app():
    return QApplication.instance() or QApplication([])


def test_market_overview_tech_expansion():
    """验证行情全景右侧 AI 双 Tab + 技术面解读渲染。"""
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.market_overview_page import MarketOverviewPage

    _app()
    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_tech_test.db")
    page = MarketOverviewPage(mdm, store, config=None, session=None)
    page._refresh_all()

    sym = page.cur_symbol
    per = page.cur_period

    # --- 技术面计算 ---
    tech = page._compute_technical(sym, per, news_bias=0.2)
    assert tech is not None, "技术面计算应返回非 None（合成数据足够）"
    for k in ("last", "ma", "bull_align", "bear_align", "dif", "dea", "hist",
              "bup", "bmid", "blow", "k", "d", "j", "rsi6", "rsi14",
              "obv_bull", "supports", "resist", "score", "force"):
        assert k in tech, f"tech 缺字段 {k}"
    assert tech["ma"][60] > 0
    print(f"[技术] {sym}/{per}: 最新价 {tech['last']:.1f} 力评分 {tech['score']:+.0f} "
          f"综合力 {tech['force']:+.0f} 支撑{tech['supports']} 阻力{tech['resist']}")

    # --- 技术面 HTML 应含各指标小节 ---
    thtml = page._render_tech(tech)
    for marker in ("均线系统", "MACD", "布林带", "KDJ", "量能", "支撑位", "阻力位", "综合技术结论"):
        assert marker in thtml, f"技术面解读缺「{marker}」"
    print("[技术] HTML 含 均线/MACD/布林/KDJ/量能/支撑阻力 全部小节")

    # --- 多空力量对比条形 ---
    bb = page._bullbear_html(tech, {"sources": 3, "bull": 2, "bear": 1, "direction": "偏多", "agree": 0.6}, 0.2)
    assert "多空力量对比" in bb and "%" in bb, "多空力量对比应包含可视化条形"
    print("[多空] 多空力量对比条形已生成")

    # --- 综合研判 + 双 Tab 渲染 ---
    now = time.time()
    news = {
        "ts": now,
        "items": [
            {"title": "螺纹钢去库加速利多", "content": "螺纹钢需求旺盛去库加速",
             "url": "u", "ctime": now - 3600, "level": "A", "source": "财联社",
             "category": "市场分析", "sentiment": 0.7},
            {"title": "原油减产", "content": "OPEC减产供应收紧",
             "url": "u2", "ctime": now - 7200, "level": "B", "source": "东方财富",
             "category": "品种研报", "sentiment": 0.5},
        ],
        "sources": {"财联社": 1, "东方财富": 1},
        "by_source": {}, "by_category": {},
        "source_coverage": {"total_sources": 11, "active_sources": 2,
                             "active": ["财联社", "东方财富"]},
    }
    res = {"p_up": 0.58, "expected_return_pct": 1.0, "risk": {"label": "中", "score": 25}}
    analysis = nf.ai_analyze_news(news, res, "螺纹钢", "黑色")
    sd_rows = [("黑色", 0.3, 2, ["样本A"]), ("有色", -0.2, 1, ["样本B"])]
    page._fill_news(news, analysis, sd_rows, tech)

    ai_html = page.ai_view.toHtml()
    tech_html = page.tech_view.toHtml()
    for marker in ("信源覆盖", "综合置信度", "跨源一致性", "多空力量对比",
                   "趋势预测与综合研判", "风险提示", "关注建议"):
        assert marker in ai_html, f"AI综合研判缺「{marker}」"
    assert "均线系统" in tech_html and "布林带" in tech_html
    assert page.ai_tabs.count() == 2, "应有两个 AI Tab"
    print("[渲染] AI综合研判 Tab 含 信源覆盖/多空对比/趋势预测/风险；技术面 Tab 含 均线/布林")
    print(f"[Tab] 标题: {[page.ai_tabs.tabText(i) for i in range(page.ai_tabs.count())]}")

    # --- 仅重算技术（切换合约路径）---
    page._refresh_tech()
    assert "均线系统" in page.tech_view.toHtml()
    print("[刷新] 仅重算技术面 OK（符号切换路径）")

    # 预览
    try:
        pix = page.grab()
        out = "tests/e2e/market_overview_tech_preview.png"
        pix.save(out)
        print(f"[预览] 已保存 {out}")
    except Exception as e:
        print(f"[预览] 跳过（{e}）")
    return page


def test_predict_subcharts_vertical():
    """验证预测操作页副图改为垂直堆叠、各独占一行、高度足够。"""
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.predict_ops_page import PredictOpsPage
    from futures_quant.indicators.tech import add_indicators

    _app()
    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_predict_tech_test.db")
    page = PredictOpsPage(mdm, store, config=None, session=None)

    # 三副图最小高度应≥150（原 70）
    for attr in ("macd", "kdj", "rsi"):
        w = getattr(page, attr)
        assert w.minimumHeight() >= 150, f"{attr} 最小高度={w.minimumHeight()}（应≥150）"
        # 父布局应为垂直（QVBoxLayout），即三图垂直堆叠各独占一行
        parent_layout = w.parent().layout()
        assert isinstance(parent_layout, QVBoxLayout), f"{attr} 父布局应为 QVBoxLayout"
    print("[布局] MACD/KDJ/RSI 三副图均为垂直堆叠、最小高度≥150")

    # 注入真实指标数据验证渲染不崩、高度足够显示
    df = mdm.get_bars(page.cur_symbol, page.cur_period, 300)
    ind = add_indicators(df)
    x = list(range(len(ind)))
    page.macd.set_data(series=[{"name": "DIF", "color": "#3b82f6", "x": x, "y": ind["DIF"].tolist()},
                               {"name": "DEA", "color": "#f59e0b", "x": x, "y": ind["DEA"].tolist()}],
                       title="MACD")
    page.kdj.set_data(series=[{"name": "K", "color": "#3b82f6", "x": x, "y": ind["K"].tolist()},
                              {"name": "D", "color": "#22c55e", "x": x, "y": ind["D"].tolist()},
                              {"name": "J", "color": "#ef4444", "x": x, "y": ind["J"].tolist()}],
                      title="KDJ")
    page.rsi.set_data(series=[{"name": "RSI6", "color": "#a855f7", "x": x, "y": ind["RSI6"].tolist()},
                              {"name": "RSI14", "color": "#06b6d4", "x": x, "y": ind["RSI14"].tolist()}],
                      title="RSI")
    assert page.macd.minimumHeight() >= 150
    print("[数据] 三副图已注入 MACD/KDJ/RSI 指标数据，渲染正常")

    try:
        pix = page.grab()
        out = "tests/e2e/predict_subcharts_preview.png"
        pix.save(out)
        print(f"[预览] 已保存 {out}")
    except Exception as e:
        print(f"[预览] 跳过（{e}）")
    return page


if __name__ == "__main__":
    test_market_overview_tech_expansion()
    test_predict_subcharts_vertical()
    print("\nALL_OK")
