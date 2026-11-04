"""忠实复现行情全景 _run_news 的 done() 渲染链路，捕获任何崩溃。
测试多种 AI 返回形态：heuristic(字典) 与 LLM(列表) 形态。不依赖网络。
"""
import sys, traceback, tempfile
sys.path.insert(0, ".")
LOG = open("tests/e2e/probe_done.log", "w", encoding="utf-8")

def log(*a):
    print(*a, file=LOG, flush=True)

try:
    from PyQt6.QtWidgets import QApplication
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ai import news_feed
    from futures_quant.ui import market_overview_page as M

    app = QApplication.instance() or QApplication([])
    mdm = MarketDataManager(source="synthetic")
    mdm.connect()
    store = AnalysisStore(tempfile.mktemp(suffix=".db"))
    page = M.MarketOverviewPage(mdm, store)

    news = {
        "items": [
            {"title": "钢厂限产提振螺纹", "source": "东方财富", "sentiment": 0.6},
            {"title": "库存累积压制油价", "source": "金十数据", "sentiment": -0.4},
        ],
        "source_coverage": {"active_sources": 8, "total_sources": 11},
    }
    news_feed.fetch_all_news = lambda limit=60: news
    page._run_worker = lambda fn, on_done, on_err=None: on_done(fn())

    variants = {
        "heuristic(字典形态)": {
            "trend": "偏多", "confidence": 0.72,
            "brief": "全市场情绪偏多。",
            "key_events": [{"title": "钢厂限产", "source": "东方财富", "sentiment": "利好"}],
            "actionable_insights": "关注 RB 逢低做多。",
            "drivers": ["供给扰动"],
            "scenarios": {"optimistic": {"p": 0.4, "desc": "限产加码"},
                          "base": {"p": 0.4, "desc": "震荡偏多"},
                          "pessimistic": {"p": 0.2, "desc": "需求走弱"}},
            "risk": "限产不及预期。", "suggestion": "控制仓位。",
            "watchlist": ["RB", "SC"],
        },
        "LLM(列表形态)": {
            "trend": "偏多", "confidence": 0.7,
            "brief": "全市场情绪偏多。",
            "key_events": ["钢厂限产", "原油累库"],
            "actionable_insights": ["关注 RB 逢低做多", "关注 SC 逢高做空"],
            "drivers": "供给扰动",
            "scenarios": [{"p": 0.4, "desc": "限产加码"},
                          {"p": 0.4, "desc": "震荡偏多"},
                          {"p": 0.2, "desc": "需求走弱"}],
            "risk": "限产不及预期。", "suggestion": "控制仓位。",
            "watchlist": "RB",
        },
    }

    for name, analysis in variants.items():
        news_feed.ai_analyze_news = lambda *a, **k: analysis
        try:
            page._run_news()
            app.processEvents()
            log(f"[OK] {name}: done() 完整链路无异常")
        except Exception:
            log(f"[CRASH] {name}:\n" + traceback.format_exc())
    log("ALL_DONE")
except Exception:
    log("[HARNESS EXC]\n" + traceback.format_exc())
finally:
    LOG.close()
