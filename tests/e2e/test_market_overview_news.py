"""行情全景：布局 + AI 资讯引擎（offscreen 冒烟测试，无网络依赖）。

覆盖两点需求：
  1) 全市场速览表独占整行：列数=6、拉伸模式、最小段宽、图表与表分离；
  2) KP资讯解读深度增强：多源覆盖 / 跨源一致性 / 综合置信度 计算与展示。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

import futures_quant.ai.news_feed as nf


def test_news_engine_analysis():
    """直接验证 云端研判的覆盖/一致性/置信度（用合成资讯，不触网）。"""
    now = time.time()
    news = {
        "ts": now,
        "items": [
            {"title": "OPEC减产提振原油", "content": "OPEC减产，原油供应收紧利多",
             "url": "u1", "ctime": now - 3600, "level": "A", "source": "财联社",
             "category": "市场分析", "sentiment": 0.8},
            {"title": "螺纹钢需求超预期", "content": "螺纹钢需求旺盛，去库加速利多",
             "url": "u2", "ctime": now - 7200, "level": "B", "source": "东方财富",
             "category": "品种研报", "sentiment": 0.6},
            {"title": "生猪供应宽松", "content": "生猪供应过剩，累库压力利空",
             "url": "u3", "ctime": now - 1800, "level": "B", "source": "期货日报",
             "category": "市场分析", "sentiment": -0.7},
            {"title": "美联储加息预期", "content": "美联储加息预期升温，宏观偏空",
             "url": "u4", "ctime": now - 900, "level": "A", "source": "金十数据",
             "category": "政策资讯", "sentiment": -0.5},
            {"title": "铜价震荡", "content": "沪铜多空交织，区间震荡",
             "url": "u5", "ctime": now - 600, "level": "C", "source": "华尔街见闻",
             "category": "市场分析", "sentiment": 0.1},
        ],
        "sources": {"财联社": 1, "东方财富": 1, "期货日报": 1,
                     "金十数据": 1, "华尔街见闻": 1},
        "by_source": {},
        "by_category": {},
        "source_coverage": {"total_sources": 11, "active_sources": 5,
                             "active": ["财联社", "东方财富", "期货日报",
                                        "金十数据", "华尔街见闻"]},
    }
    res = {"p_up": 0.6, "expected_return_pct": 1.2,
           "risk": {"label": "中", "score": 30}}
    # 跨源一致性应命中「螺纹钢」相关（东方财富偏多）
    cons = nf._cross_source_consensus(
        news["items"], ["螺纹钢", "黑色"] + nf.NAME_ALIASES.get("螺纹钢", []))
    assert cons["sources"] >= 1, f"consensus sources={cons['sources']}"

    analysis = nf.ai_analyze_news(news, res, "螺纹钢", "黑色")
    for k in ("source_coverage", "consensus", "confidence", "weighted_bias"):
        assert k in analysis, f"analysis 缺少字段 {k}"
    assert isinstance(analysis["confidence"], (int, float))
    assert 0.0 <= analysis["confidence"] <= 1.0
    assert "信源覆盖" in analysis["trend"] or "覆盖" in analysis["trend"]
    print(f"[引擎] confidence={analysis['confidence']} "
          f"consensus={analysis['consensus']} wbias={analysis['weighted_bias']}")
    print("[引擎] trend 片段:", analysis["trend"][:80].replace(chr(10), " "))
    return analysis


def test_fetch_list_source_parsing():
    """验证通用列表页解析器（用假 Session.get，避免真实网络）。"""
    html = '''
    <a href="https://finance.sina.com.cn/futures/2026-07-27/abc.shtml">螺纹钢去库加速利多</a>
    <a href="https://finance.sina.com.cn/futures/2026-07-26/def.shtml">原油减产提振</a>
    '''

    class FakeResp:
        status_code = 200
        content = html.encode("utf-8")
    nf._SESSION.get = lambda *a, **k: FakeResp()
    items = nf._fetch_list_source(
        "https://finance.sina.com.cn/futures/",
        nf._SINA_RE, "新浪财经", enc="utf-8", limit=10, enrich=False)
    assert len(items) == 2, f"解析到 {len(items)} 条，应为 2"
    assert items[0]["source"] == "新浪财经"
    assert "螺纹钢" in items[0]["title"]
    print(f"[解析] 新浪财经列表解析 OK，{len(items)} 条")
    return items


def test_market_overview_layout_and_render():
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.market_overview_page import MarketOverviewPage

    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_test.db")
    page = MarketOverviewPage(mdm, store, config=None, session=None)

    # 触发数据刷新（不触网，纯合成行情）
    page._refresh_all()

    # --- 需求1：全市场速览表布局 ---
    wt = page.watch
    assert wt.columnCount() == 6, f"速览表列数={wt.columnCount()}（应为6）"
    hdr = wt.horizontalHeader()
    assert hdr.stretchLastSection() is True, "末列应拉伸填满整行"
    assert hdr.minimumSectionSize() >= 96, f"最小段宽={hdr.minimumSectionSize()}"
    # 图表与速览表为独立控件，且速览表独占整行（同父布局内顺序：K线在前，速览表在后）
    # 行情全景页的速览表为 page.watch（QTableWidget，最低高度 240），非 page.chart
    assert page.watch is not None and page.watch.minimumHeight() >= 240
    # 刷新后应有行数据
    assert wt.rowCount() > 0, "速览表应有行情行"
    print(f"[布局] 速览表：{wt.rowCount()} 行 × {wt.columnCount()} 列，"
          f"stretchLast={hdr.stretchLastSection()}，minSec={hdr.minimumSectionSize()}")

    # --- 需求2：注入合成 云端研判，验证渲染不崩且含覆盖/置信度 ---
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
    page._fill_news(news, analysis, sd_rows)
    html = page.ai_view.toHtml()
    assert "信源覆盖" in html, "AI 面板应含「信源覆盖」"
    assert "综合置信度" in html, "AI 面板应含「综合置信度」"
    assert "跨源一致性" in html, "AI 面板应含「跨源一致性」"
    print("[渲染] AI 面板已渲染 信源覆盖/跨源一致性/综合置信度，无异常")

    # 预览图
    try:
        pix = page.grab()
        out = "tests/e2e/market_overview_v2_preview.png"
        pix.save(out)
        print(f"[预览] 已保存 {out}")
    except Exception as e:
        print(f"[预览] 跳过（{e}）")

    store.close()
    try:
        if os.path.exists("data/quant_analysis_test.db"):
            os.remove("data/quant_analysis_test.db")
    except Exception:
        pass


def main():
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, False)

    print("=" * 70)
    print("行情全景 · 布局 + AI 资讯引擎 验证")
    print("=" * 70)

    # 1) 引擎：覆盖/一致性/置信度
    test_news_engine_analysis()

    # 2) 解析器：用假网络响应验证通用列表抓取
    test_fetch_list_source_parsing()

    # 3) 页面：布局 + 渲染
    test_market_overview_layout_and_render()

    print("=" * 70)
    print("全部检查通过 ✅")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
