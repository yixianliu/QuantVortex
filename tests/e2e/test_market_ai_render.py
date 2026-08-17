"""行情全景 · AI 综合研判渲染回归测试（锁定 hot 变量名冲突崩溃修复）。

直接驱动 MarketOverviewPage._render_ai，传入同时含 sector_rotation(list) 与
hot_symbols(dict) 的分析字典 —— 该组合曾在 2026-07-31 触发
'list' object has no attribute 'items' 崩溃（板块轮动局部变量覆盖了 hot_symbols）。
"""
from __future__ import annotations

import os
import sys

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


def main() -> None:
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, False)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.market_overview_page import MarketOverviewPage

    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_render_test.db")
    page = MarketOverviewPage(mdm, store, config=None, session=None)
    # 渲染依赖的上下文默认占位
    page._news_sent = (0, 0, 0)
    page._market_ctx = {}

    analysis = {
        "model": "heuristic",
        "trend": "整体情绪中性偏多，短线资金回流。",
        "risk": "关注上方压力位与持仓量变化。",
        "suggestion": "沿强势板块逢回调关注多单机会。",
        "key_events": ["某品种库存超预期下降", "政策面释放稳增长信号"],
        "hot_symbols": {"rb": 12, "au": 8, "i": 5},          # dict：活跃品种
        "actionable_insights": "沿化工板块逢回调关注多单，预期 +1.8%、置信 51%。",
        "source_coverage": {"active_sources": 3, "total_sources": 5,
                             "active": ["财讯", "研报", "舆情"]},
        "consensus": {"sources": 2, "direction": "看多", "agree": 0.6,
                      "bull": 2, "bear": 1},
        "confidence": 0.51,
        "weighted_bias": 0.28,
        "brief": "化工与有色获资金共振，短线偏多但需防追高。",
        "sector_rotation": [                                      # list：板块轮动
            {"sector": "化工", "score": 0.35},
            {"sector": "有色", "score": 0.22},
            {"sector": "农产品", "score": -0.18},
        ],
    }

    try:
        page._render_ai(analysis, tech=None)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: _render_ai raised {type(e).__name__}: {e}")
        store.close()
        sys.exit(1)

    html = page.ai_view.toHtml()
    for marker in ("板块轮动", "活跃品种", "情报摘要", "可操作洞察"):
        assert marker in html, f"渲染缺失区块: {marker}"
    print("PASS: _render_ai 正常渲染（板块轮动+活跃品种双路径）")
    store.close()
    try:
        os.remove("data/quant_analysis_render_test.db")
    except OSError:
        pass


if __name__ == "__main__":
    main()
