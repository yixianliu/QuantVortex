"""M4-09 长任务可视化（进度 + 取消 UI）—— 验收冒烟（offscreen）。

M4-09 三个目标点代码已落地，本测试补齐 DoD 要求的可执行验收：
  ① 进化（BacktestCenterPage）：状态灯「第 n 代 · 基因 i/10」+ 真实百分比进度条
     + 暂停/停止按钮；`_on_evolution_progress` / `_on_evolution_interrupted` /
     `_stop_evolution` 协作式中止不排程下一代。
  ② 资讯抓取（MarketOverviewPage）：`_on_news_progress` 显示「已完成 x/13 源」，
     单源超时 8s，`_on_news_interrupted` 保留已完成结果并恢复按钮。
  ③ 离线回放（PredictOpsPage）：`replay_prog` 用 `setRange(0,100)` 真实百分比，
     `_on_replay_progress` / `_stop_replay` / `_on_replay_interrupted` 协作式取消。

运行：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m4_09.py
"""
from __future__ import annotations

import os
import sys

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


def main() -> int:
    app = None
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.backtest_page import BacktestCenterPage
    from futures_quant.ui.market_overview_page import MarketOverviewPage
    from futures_quant.ui.predict_ops_page import PredictOpsPage

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_test.db")

    # ---------------- ① 进化（BacktestCenterPage） ----------------
    bp = BacktestCenterPage(mdm, store, config=None, session=None)
    check("evo-progress-range-0to100",
          bp._evo_progress.minimum() == 0 and bp._evo_progress.maximum() == 100,
          f"range={bp._evo_progress.minimum()}-{bp._evo_progress.maximum()}")
    check("evo-controls-exist",
          hasattr(bp, "_evo_pause_btn") and hasattr(bp, "_evo_stop_btn")
          and hasattr(bp, "_evo_stage_label"),
          "pause/stop/stage 控件齐备")

    # 直驱进度回调：断言「第 n 代 · 基因 i/10」渲染 + 百分比同步
    bp._cur_gen_no = 3
    bp._on_evolution_progress(40, "基因 4/10")
    check("evo-progress-render",
          bp._evo_progress.value() == 40
          and bp._evo_stage_label.text() == "⚙️ 第 3 代 · 基因 4/10"
          and "第 3 代" in bp._evo_progress.format(),
          f"value={bp._evo_progress.value()} fmt={bp._evo_progress.format()!r}")

    # 停止：置 _evolution_stopped，按钮进入「重新开始」态
    bp._stop_evolution()
    check("evo-stop-flags",
          bp._evolution_stopped is True and bp._paused is False,
          f"stopped={bp._evolution_stopped}")
    check("evo-stop-pausebtn-restart",
          bp._evo_pause_btn.text() == "🔄 重新开始"
          and bp._evo_pause_btn.isEnabled(),
          bp._evo_pause_btn.text())

    # 暂停/继续/重启三态
    bp._toggle_pause()  # stopped 态 → 走 _restart_evolution
    check("evo-restart-clears-stopped",
          bp._evolution_stopped is False, f"stopped={bp._evolution_stopped}")

    # ---------------- ② 资讯抓取（MarketOverviewPage） ----------------
    mp = MarketOverviewPage(mdm, store, config=None, session=None)
    check("news-progress-range-0to100",
          mp.news_prog.minimum() == 0 and mp.news_prog.maximum() == 100,
          f"range={mp.news_prog.minimum()}-{mp.news_prog.maximum()}")
    # 单源超时 8s：验证 _run_news 传给引擎的 per_source_timeout
    import inspect
    src = inspect.getsource(mp._run_news)
    check("news-per-source-timeout-8s", "per_source_timeout=8" in src,
          "单源超时 8s 已声明")

    mp._on_news_progress(54, "已完成 7/13 源")
    check("news-progress-render",
          mp.news_prog.value() == 54 and "7/13" in mp.news_status.text(),
          f"value={mp.news_prog.value()} status={mp.news_status.text()!r}")

    mp._on_news_interrupted()
    check("news-interrupted-restores",
          mp.news_btn.isEnabled() and "取消" in mp.news_status.text(),
          f"btn={mp.news_btn.isEnabled()} status={mp.news_status.text()!r}")

    # ---------------- ③ 离线回放（PredictOpsPage） ----------------
    pp = PredictOpsPage(mdm, store, config=None, session=None)
    check("replay-progress-range-0to100",
          pp.replay_prog.minimum() == 0 and pp.replay_prog.maximum() == 100,
          "M4-09：真实百分比（按样本数推进）")

    pp._on_replay_progress(30, "回放 3/10")
    check("replay-progress-render",
          pp.replay_prog.value() == 30 and "3/10" in pp.replay_status.text(),
          f"value={pp.replay_prog.value()} status={pp.replay_status.text()!r}")

    # 取消入口存在且无残留 worker 时走 _end_replay
    check("replay-stop-btn-exists", hasattr(pp, "replay_stop_btn"),
          "协作式停止入口齐备")
    pp._replaying = False
    pp._workers = []
    pp._stop_replay()  # 空 worker 分支：直接 _end_replay，不崩
    check("replay-stop-no-worker-safe",
          pp._replaying is False, "无活跃 worker 时停止不崩")

    # ---------------- 汇总 ----------------
    print("=" * 62)
    print("M4-09 长任务可视化（进度 + 取消 UI）· 验收")
    print("=" * 62)
    passed = 0
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f"  ({detail})" if detail else ""))
        passed += int(ok)
    total = len(results)
    print("-" * 62)
    print(f"结果：{passed}/{total} 通过")

    try:
        from PyQt6.QtGui import QCloseEvent
        for w in (bp, mp, pp):
            w.closeEvent(QCloseEvent())
    except Exception:  # noqa: BLE001
        pass

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
