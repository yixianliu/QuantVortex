"""M8.1 消息聚合器 e2e：4 源并发 + 去重 + TF-IDF 情绪打分。

说明：沙箱内网络不可用，aggregate 离线降级 → items 为空但结构完整；
本测试重点验证「离线降级不阻塞主流程」+ 「tfidf_sentiment 对纯文本可算」。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai.news_feed import NewsAggregator  # noqa: E402


def main() -> int:
    ag = NewsAggregator(sources=["cls", "eastmoney", "ths", "exchange"])

    # --- 离线降级：aggregate 不抛异常，返回结构完整 ---
    res = ag.aggregate(limit=50)
    assert "items" in res and "sources" in res and "total" in res
    assert isinstance(res["items"], list)
    assert set(res["sources"].keys()) == {"cls", "eastmoney", "ths", "exchange"}
    for s in res["sources"].values():
        assert isinstance(s, int) and s >= 0
    print(f"[OK] aggregate offline-degraded: total={res['total']} sources={res['sources']}")

    # --- tfidf_sentiment 纯文本可算（离线、确定性）---
    # 全多头文本 → 高分
    bull_items = [{"title": "螺纹钢期货大幅上涨 库存减少 资金流入 多头加仓", "url": "u1"}]
    s_bull = ag.tfidf_sentiment(bull_items)
    assert s_bull > 0.5, f"bull text should be >0.5, got {s_bull}"

    # 全空头文本 → 低分
    bear_items = [{"title": "螺纹暴跌 库存堆积 价格下跌 空头获利 利空消息", "url": "u2"}]
    s_bear = ag.tfidf_sentiment(bear_items)
    assert s_bear < 0.5, f"bear text should be <0.5, got {s_bear}"

    # 混合文本 → 中间值
    mixed_items = [
        {"title": "螺纹上涨 库存减少", "url": "u3"},
        {"title": "螺纹下跌 库存堆积", "url": "u4"},
    ]
    s_mixed = ag.tfidf_sentiment(mixed_items)
    assert 0.0 <= s_mixed <= 1.0
    print(f"[OK] tfidf_sentiment bull={s_bull:.3f} bear={s_bear:.3f} mixed={s_mixed:.3f}")

    # 空 items → 中性 0.5
    assert ag.tfidf_sentiment([]) == 0.5
    print("[OK] empty items -> 0.5")

    # 自定义源列表
    ag2 = NewsAggregator(sources=["cls"])
    r2 = ag2.aggregate(limit=10)
    assert set(r2["sources"].keys()) == {"cls"}
    print("[OK] custom single source")

    print("ALL-OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
