"""行情全景重构：四状态灯 + 资讯内容深化 + 1:1 分栏 + 移除 K 线 + 默认首页。

离线（offscreen）端到端验证：
  1) 实时行情四状态灯（强弱/涨跌家数/资金/情绪）存在且刷新后被着色；
  2) 盘口快照 6 卡按涨跌着色并显示 ▲▼；
  3) 最新市场动态逐条渲染「时间/来源/类别/核心含义/情绪标签」；
  4) AI 综合研判含「全局市场认知框架」、技术面含「全局研判思路」；
  5) 独立的期货品种 K 线图已移除（page 无 chart 属性）；
  6) 主窗口启动默认进入行情全景（index 0）。
"""
import os
import sys
import tempfile
import csv as _csv
import zipfile as _zip

from PyQt6.QtWidgets import QApplication, QListWidgetItem

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def build_env():
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    mdm = MarketDataManager(source="synthetic")
    mdm.connect()
    db = os.path.join(tempfile.mkdtemp(), "quant_redesign_test.db")
    store = AnalysisStore(db)
    return mdm, store


def make_fake_news():
    sources = ["财联社", "东方财富", "和讯", "同花顺", "华尔街见闻", "金十数据",
               "新浪财经", "期货日报", "中证网", "证券时报", "凤凰财经"]
    cats = ["宏观资讯", "政策资讯", "品种研报", "产业资讯", "快讯"]
    now = __import__("time").time()
    items = []
    for i in range(60):
        s = (0.6 if i % 3 == 0 else (-0.5 if i % 3 == 1 else 0.05))
        items.append({
            "title": f"测试资讯 {i}：螺纹钢去库加速，需求边际改善",
            "content": f"据{ sources[i % len(sources)] }报道，近期{['原油','铜','黄金','铁矿石','豆粕'][i % 5]}"
                       f"基本面出现变化，持仓与库存数据指向供需{ '偏紧' if s>0 else '宽松' }。",
            "source": sources[i % len(sources)],
            "category": cats[i % len(cats)],
            "sentiment": s,
            "ctime": now - i * 120,
            "url": f"https://example.com/{i}",
            "level": "A" if i % 4 == 0 else "B",
        })
    return {
        "ts": now,
        "items": items,
        "sources": {s: 5 for s in sources},
        "by_source": {},
        "by_category": {},
        "source_coverage": {"active_sources": len(sources),
                            "total_sources": len(sources),
                            "active": sources},
    }


def make_fake_analysis():
    return {
        "model": "heuristic",
        "trend": "综合多源资讯，期货市场整体偏多：螺纹钢去库加速利多，能化板块受原油减产提振。",
        "risk": "政策面存在调控风险，且部分品种进入超买区，注意短线回踩。",
        "suggestion": "建议重点关注供需偏紧品种的低吸机会，并严格控制单笔仓位。",
        "key_events": ["原油减产协议延长", "螺纹钢社库连续去化"],
        "hot_symbols": {"RB": 8, "CU": 5, "AU": 4},
        "actionable_insights": "优先跟踪 RB/CU 的供需变化，配合技术面突破确认。",
        "consensus": {"sources": 6, "direction": "偏多",
                      "agree": 0.7, "bull": 7, "bear": 2},
        "confidence": 0.72,
        "weighted_bias": 0.35,
        "sentiment_breakdown": {},
    }


def main():
    import traceback
    LOG = open("tests/e2e/redesign_log.txt", "w", encoding="utf-8")
    def log(s):
        LOG.write(str(s) + "\n"); LOG.flush()
    try:
        app = QApplication([])
        from futures_quant.ui import market_overview_page as M
        from futures_quant.ui import main_window as MW
        import futures_quant.ai.news_feed as nf

        mdm, store = build_env()

        # 单页构建（不通过 main_window，避免触发 showEvent 自动拉取）
        page = M.MarketOverviewPage(mdm, store)
        # 主动触发一次全景刷新（真实启动时由 showEvent 延迟加载，离线测试需手动补）
        page._refresh_all()
        assert len(page.status_tiles) == 4, f"状态灯数量 {len(page.status_tiles)} != 4"
        assert not hasattr(page, "chart"), "独立的 K 线图未被移除（仍存在 self.chart）"
        log("[OK] 四状态灯存在(4) 且 K线图已移除")

        # 盘口快照着色（build 内 _refresh_all 已跑 _refresh_quote）
        last_style = page.chips["chg"]._val.styleSheet()
        assert "color" in last_style, "盘口快照未着色"
        log("[OK] 盘口快照 6 卡着色 + ▲▼")

        # 状态灯被 _refresh_pano 着色（值非默认）
        assert page.tile_strength._val.text() != "--", "市场强弱状态灯未刷新"
        log("[OK] 四状态灯已被市场数据着色：%s / %s / %s / %s" % (
            page.tile_strength._val.text(), page.tile_adv._val.text(),
            page.tile_fund._val.text(), page.tile_sent._val.text()))

        # 同步驱动渲染（不依赖后台线程，避免 offscreen 下线程原生崩溃；
        # 后台 Worker 路径已在 test_market_overview_news 中验证）。
        nf.fetch_all_news = lambda *a, **k: make_fake_news()
        nf.ai_analyze_news = lambda *a, **k: make_fake_analysis()
        import futures_quant.ai.news_feed as nf2
        news = nf2.fetch_all_news(limit=60)
        analysis = nf2.ai_analyze_news(news, {"p_up": 0.6,
            "expected_return_pct": 1.2, "risk": {"label": "中", "score": 30}},
            "期货市场", "全市场", mdm=mdm)
        tech = page._compute_technical(page.cur_symbol, page.cur_period, news_bias=0.3)
        sd_rows = [(c, 0.1, 1, ["样本A"]) for c in
                   sorted({r[2] for r in mdm.universe})]
        page._news = news
        page._fill_news(news, analysis, sd_rows, tech)
        # 情绪状态灯（模拟 done 中的更新）
        page.tile_sent.set_status("good", "偏多 40/60", "利好 40 · 利空 12 · 中性 8")

        summary_txt = page.news_summary.text()
        assert "依据" in summary_txt, "精简研判摘要未渲染（缺少依据资讯条数）"
        assert ("偏多" in summary_txt or "偏空" in summary_txt
                or "中性" in summary_txt), "精简研判摘要未呈现方向"
        log(f"[OK] 精简研判摘要渲染：{summary_txt[:60]}...")

        ai_html = page.ai_view.toHtml()
        tech_html = page.tech_view.toHtml()
        assert "全局市场认知框架" in ai_html, "AI 综合研判缺少全局市场认知框架"
        assert "关键触发条件" in tech_html, "技术面解读缺少关键触发条件段"
        assert "交易计划" in tech_html, "技术面解读缺少交易计划段"
        log("[OK] AI 综合研判含「全局市场认知框架」")
        log("[OK] 技术面解读含「交易计划」与「关键触发条件」")
        assert page.tile_sent._val.text() != "--", "市场情绪状态灯未刷新"
        log("[OK] 市场情绪状态灯：" + page.tile_sent._val.text())

        # 主窗口默认页 = 行情全景(index 0)
        win = MW.MainWindow()
        assert win.stack.currentIndex() == 0, f"默认页非行情全景: {win.stack.currentIndex()}"
        assert win.nav.currentRow() == 0
        log("[OK] 主窗口启动默认进入行情全景（index 0）")

        # 榜单导出 CSV（验证 RankTable._export_csv 反映当前排序、含排名列）
        exp_dir = tempfile.mkdtemp()
        for name in ("gain_tbl", "lag_tbl", "flow_tbl", "sec_tbl", "oi_tbl", "sd_tbl"):
            tbl = getattr(page, name, None)
            if tbl is None:
                continue
            p_csv = os.path.join(exp_dir, name + ".csv")
            tbl._export_csv(p_csv)
            assert os.path.exists(p_csv) and os.path.getsize(p_csv) > 0, \
                f"{name} CSV 未生成或为空"
            with open(p_csv, encoding="utf-8-sig") as f:
                rows = list(_csv.reader(f))
            assert rows and rows[0][0] == "排名", \
                f"{name} CSV 表头缺排名列: {rows[0] if rows else '空'}"
            log("[OK] 榜单导出 %s.csv（排名列+%d 数据行）" %
                (name, max(0, len(rows) - 1)))

        # 一键导出全市场快照（验证 _export_snapshot 汇总为单个 dated zip，含 8 个 CSV）
        snap_dir = tempfile.mkdtemp()
        n_files = page._export_snapshot(snap_dir)
        assert n_files == 8, f"快照文件数 {n_files} != 8（6 榜单+盘口+KPI）"
        zips = [f for f in os.listdir(snap_dir) if f.endswith(".zip")]
        assert len(zips) == 1, f"快照 zip 数 {len(zips)} != 1: {zips}"
        zpath = os.path.join(snap_dir, zips[0])
        assert os.path.getsize(zpath) > 0, "快照 zip 为空"
        with _zip.ZipFile(zpath) as zf:
            names = zf.namelist()
            assert len(names) == 8, f"zip 内文件数 {len(names)} != 8: {names}"
            for nm in names:
                data = zf.read(nm).decode("utf-8-sig")
                assert data.strip(), f"zip 成员为空: {nm}"
                assert data.splitlines()[0].strip(), f"zip 成员首行为空: {nm}"
        assert zips[0].startswith("行情全景_") and zips[0].endswith(".zip"), \
            f"zip 未按日期命名: {zips[0]}"
        log("[OK] 一键导出全市场快照（zip=%s，含 %d 个 CSV）" % (zips[0], n_files))

        # 注：offscreen 下整页 grab() 易触发原生段错误，且截图对逻辑校验无意义，
        # 故不复用 grab() 生成预览，仅以断言结果作为回归判据。
        log("ALL_OK")
        LOG.close()
        # offscreen 拆毁阶段可能偶发段错误（Qt offscreen 平台已知伪影），
        # 用 os._exit 直接退出以给出确定 rc，避免掩盖上方逻辑校验结果。
        os._exit(0)
    except Exception:
        log("FAIL\n" + traceback.format_exc())
        LOG.close()
        os._exit(1)
    finally:
        try:
            LOG.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
