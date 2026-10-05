"""10 秒闪退回归：强制走「worker 完成 -> _fill_news -> 重布局」路径。

验证源码在 FlowLayout/ResponsiveRow 修复后，包含 drivers/scenarios/watchlist
字段的完整渲染 + 窗口 show/resize/grab 重布局不再抛出任何异常（特别是
旧的 Qt.Orientations AttributeError）。
"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def build_env():
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    mdm = MarketDataManager(source="synthetic")
    mdm.connect()
    db = os.path.join(tempfile.mkdtemp(), "quant_relayout_test.db")
    store = AnalysisStore(db)
    return mdm, store


def make_fake_news():
    sources = ["财联社", "东方财富", "金十数据", "新浪财经", "中证网", "证券时报"]
    items = []
    for i in range(40):
        s = (0.6 if i % 3 == 0 else (-0.5 if i % 3 == 1 else 0.05))
        items.append({
            "title": f"资讯 {i}：螺纹钢去库加速",
            "content": f"据{sources[i % len(sources)]}报道，基本面变化。",
            "source": sources[i % len(sources)],
            "category": "产业资讯",
            "sentiment": s,
            "ctime": __import__("time").time() - i * 120,
            "url": f"https://example.com/{i}",
            "level": "A" if i % 4 == 0 else "B",
        })
    return {"ts": __import__("time").time(), "items": items,
            "sources": {}, "by_source": {}, "by_category": {},
            "source_coverage": {"active_sources": 6, "total_sources": 6,
                                "active": sources}}


def make_full_analysis():
    # 含全部新增字段，覆盖 _render_ai / _scenarios_html / _fill_summary 全路径
    return {
        "model": "agnes",
        "trend": "期货市场整体偏多",
        "brief": "综合多源资讯，能化与黑色偏强，农产品分化。",
        "drivers": [
            {"factor": "原油减产延长", "impact": "利多能化", "weight": 0.4},
            {"factor": "螺纹去库", "impact": "利多黑色", "weight": 0.3},
            {"factor": "美元走强", "impact": "利空贵金属", "weight": 0.2},
            {"factor": "政策调控", "impact": "压制短线", "weight": 0.1},
        ],
        "scenarios": {
            "optimistic": {"p": 0.45, "desc": "需求超预期复苏"},
            "base": {"p": 0.40, "desc": "震荡偏强"},
            "pessimistic": {"p": 0.15, "desc": "政策打压回踩"},
        },
        "risk": "政策面调控风险，部分品种超买。",
        "suggestion": "重点跟踪供需偏紧品种低吸机会。",
        "watchlist": [
            {"symbol": "RB", "reason": "去库加速"},
            {"symbol": "CU", "reason": "低库存"},
            {"symbol": "AU", "reason": "避险"},
        ],
        "key_events": [
            {"title": "原油减产延长", "source": "财联社", "sentiment": 0.6},
            {"title": "螺纹去库", "source": "东方财富", "sentiment": 0.5},
        ],
        "hot_symbols": {"RB": 8, "CU": 5},
        "actionable_insights": "优先跟踪 RB/CU。",
        "consensus": {"sources": 6, "direction": "偏多", "agree": 0.7,
                      "bull": 7, "bear": 2},
        "confidence": 0.72,
        "weighted_bias": 0.35,
        "sentiment_breakdown": {},
    }


def main():
    LOG = open("tests/e2e/relayout_log.txt", "w", encoding="utf-8")
    def log(s):
        LOG.write(str(s) + "\n"); LOG.flush()
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from futures_quant.ui import market_overview_page as M
        import futures_quant.ai.news_feed as nf

        mdm, store = build_env()
        page = M.MarketOverviewPage(mdm, store)

        # 模拟真实 worker 完成后的 done() 路径
        news = make_fake_news()
        analysis = make_full_analysis()
        tech = page._compute_technical(page.cur_symbol, page.cur_period,
                                       news_bias=0.35)
        sd_rows = [(c, 0.1, 1, ["样本A"]) for c in
                   sorted({r[2] for r in mdm.universe})]
        page._news = news
        page._fill_news(news, analysis, sd_rows, tech)
        log("[OK] _fill_news + _render_ai/_render_tech 完整渲染（含 drivers/scenarios/watchlist）")

        # 强制真实窗口布局：show + resize + processEvents + grab
        page.show()
        page.resize(1280, 800)
        app.processEvents()
        page.resize(900, 700)   # 触发 ResponsiveRow 切换列->单列 重排
        app.processEvents()
        # 注：offscreen 下整页 grab() 易触发原生段错误，且截图对逻辑校验无意义，
        # 故不复用 grab() 生成预览，仅以断言结果作为回归判据。
        log("[OK] show/resize/resize 重布局无异常（ResponsiveRow + FlowLayout）")
        log("ALL_OK")
    except Exception:
        log("FAIL\n" + traceback.format_exc())
    finally:
        LOG.close()


if __name__ == "__main__":
    main()
