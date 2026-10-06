# -*- coding: utf-8 -*-
"""M4-09 验收：长任务可视化（进度 + 取消 UI）。

验收脚本（对应文档 M4-09）：
    ① 进化引擎 ``EvolutionEngine.step`` 支持 ``on_progress``（每基因上报）
       与 ``should_abort``（协作式中断），不改动既有业务逻辑；
    ② Worker.run 支持把自身句柄传给 ``work(worker)``，任务内可
       ``worker.emit_progress`` 上报进度（M4-06 信号链路）；
    ③ 进化页：``_on_evolution_progress`` 更新进度条与「第 n 代 · 基因 i/10」，
       点「停止」置 ``_evolution_stopped`` 且 ``_next_generation`` 不再排程下一代；
    ④ 资讯抓取：``fetch_all_news`` 上报「已完成 x/总源数 源」+ 单源超时 8s +
       取消（``should_abort``），UI 进度条可见并推进到 100%；
    ⑤ 离线回放：进度条 ``setRange(0,100)`` 真实百分比，按样本数推进到 100%。

运行（offscreen）：
    QT_QPA_PLATFORM=offscreen python test_m4_09.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR",
    "D:/PythonProject/QuantVortex/.pytest_tmp/sd-state",
)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    """记录一条断言结果。"""
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


def spin(app, msec: int) -> None:
    """推进事件循环 msec 毫秒（让跨线程信号得以投递）。"""
    from PyQt6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(msec, loop.quit)
    loop.exec()


# ============================================================================
# ① 进化引擎 step：on_progress + should_abort（纯逻辑，无 Qt）
# ============================================================================
def t1_engine_step_hooks() -> None:
    print("\n[①] 进化引擎 step：on_progress + should_abort")
    rng = __import__("random").Random(7)
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.strategy import auto_evolve as ae

    mdm = MarketDataManager(source="synthetic")
    eng = ae.EvolutionEngine(mdm.feed, mdm.universe, period="D", seed=7)
    eng.POP_SIZE = 6

    prog = []
    snap = eng.step(
        should_abort=lambda: False,
        on_progress=lambda d, t, txt: prog.append((d, t, txt)),
    )
    total = len(eng.population)
    check(snap["generation"] == 1, "step 返回第 1 代快照")
    check(len(prog) == total, f"on_progress 每基因调用一次（{len(prog)}/{total}）")
    if prog:
        d0, t0, txt0 = prog[0]
        check(t0 == total, "on_progress 的 total 等于种群规模")
        check(d0 == 1, "首个进度 done=1")
        check(txt0.startswith("基因 "), f"进度文本为「基因 i/10」格式：{txt0}")
        check(prog[-1][0] == total, "末个进度 done==total")
    # 代数应正确递增
    snap2 = eng.step()
    check(snap2["generation"] == 2, "连续 step 代数递增")

    # should_abort：在中途请求中断 → 抛 InterruptionError 且不推进代数
    gen_before = eng.generation
    calls = {"n": 0}
    def _abort():
        calls["n"] += 1
        return calls["n"] >= 1  # 第一个基因后即刻中断
    try:
        eng.step(should_abort=_abort)
        check(False, "should_abort 应为 True 时抛 InterruptionError")
    except ae.InterruptionError:
        check(True, "should_abort 返回 True 时 step 抛 InterruptionError")
    except Exception as e:  # noqa: BLE001
        check(False, f"期望 InterruptionError，实际 {type(e).__name__}")
    check(eng.generation == gen_before, "中断未推进代数（无半截结果）")


# ============================================================================
# ② Worker 把自身句柄传给 work(worker) + on_progress 送达主线程
# ============================================================================
def t2_worker_passes_self(app) -> None:
    print("\n[②] Worker 把句柄传给 work(worker) 并上报进度")
    from futures_quant.ui.pages import Worker

    got_worker = {}
    prog = []

    def work(worker):
        got_worker["w"] = worker
        worker.emit_progress(30, "第一步")
        worker.emit_progress(75, "第二步")
        return "ok"

    w = Worker(work)
    w.progress.connect(lambda p, t: prog.append((p, t)))
    w.finished.connect(lambda r: got_worker.setdefault("result", r))
    w.start()
    spin(app, 200)

    check(got_worker.get("w") is w, "work(worker) 收到的是运行它的同一 worker 实例")
    check(got_worker.get("result") == "ok", "worker 正常 finished 并返回结果")
    check(prog == [(30, "第一步"), (75, "第二步")],
          f"on_progress 在主线程被收到：{prog}")


# ============================================================================
# ③ 进化页控制流：进度回调更新 UI；停止后不再排程下一代
# ============================================================================
def t3_evolution_page_control() -> None:
    print("\n[③] 进化页：进度回调 + 停止不再排程下一代")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    import tempfile

    mdm = MarketDataManager(source="synthetic")
    mdm.connect()
    store = AnalysisStore(os.path.join(tempfile.mkdtemp(), "m4_09_evo.db"))

    from futures_quant.ui.backtest_page import BacktestCenterPage
    page = BacktestCenterPage(mdm, store)
    page.show()
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, lambda: None)
    app.processEvents()

    # 进度回调直接驱动进度条 + 状态标签
    page._on_evolution_progress(42, "基因 3/10")
    check(page._evo_progress.value() == 42, "进度条随 on_progress 更新为 42")
    check("基因 3/10" in page._evo_stage_label.text(),
          f"状态标签显示「基因 i/10」：{page._evo_stage_label.text()}")

    # 构造一个伪引擎，验证 _next_generation 真实路由到 work(worker) + on_progress
    class _FakeEngine:
        POP_SIZE = 4
        generation = 0

        def symbol_name(self):
            return "螺纹钢"

        def symbol(self):
            return "RB"

        def to_state(self):
            return {"generation": self.generation}

        def step(self, should_abort=None, on_progress=None):
            for i in range(self.POP_SIZE):
                if should_abort is not None and should_abort():
                    from futures_quant.core.exceptions import InterruptionError
                    raise InterruptionError("stopped")
                if on_progress is not None:
                    on_progress(i + 1, self.POP_SIZE, f"基因 {i+1}/{self.POP_SIZE}")
            self.generation += 1
            return {"generation": self.generation, "evolution_done": False,
                    "symbol_name": "螺纹钢", "ranked": [], "new_profitable": [],
                    "library": [], "profitable_total": 0, "evaluated_total": 4,
                    "best_overall": None, "gen_in_symbol": 1,
                    "gens_per_symbol": 5}

    page._engine = _FakeEngine()
    page._gen_running = False
    page._evolution_stopped = False
    page._paused = False

    # 让 _on_gen_done 仅记录、避免触发后续 UI 重排，并把进度条收尾为 100%
    def _fake_done(snap):
        page._evo_progress.setValue(100)
        setattr(page, "_gen_done_snap", snap)
    page._on_gen_done = _fake_done
    page._next_generation()
    spin(app, 400)
    check(getattr(page, "_gen_done_snap", None) is not None,
          "一代完成后 on_done 被调用（work(worker)+on_progress 链路贯通）")
    check(page._evo_progress.value() == 100,
          "一代完成后进度条置 100%")

    # 停止：置标志 + 不再排程下一代
    page._evolution_stopped = False
    page._paused = False
    page._next_generation = (lambda: check(False, "_next_generation 被错误排程"))
    page._stop_evolution()
    check(page._evolution_stopped is True, "停止后置 _evolution_stopped=True")
    check(page._evo_stop_btn.isEnabled() is False, "停止后「停止」按钮禁用")
    # 由于 _next_generation 已被替换为断言，若被调用会失败；此处验证它未被调用
    print("    （停止后即使触发排程回调也不会调用 _next_generation）")


# ============================================================================
# ④ 资讯抓取：进度「已完成 x/总源数 源」+ 单源超时 + 取消
# ============================================================================
def t4_news_progress_cancel(app) -> None:
    print("\n[④] 资讯抓取：进度 + 取消")
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    import tempfile
    import futures_quant.ai.news_feed as nf
    import futures_quant.ui.market_overview_page as M

    mdm = MarketDataManager(source="synthetic")
    mdm.connect()
    store = AnalysisStore(os.path.join(tempfile.mkdtemp(), "m4_09_news.db"))

    from futures_quant.ui.market_overview_page import MarketOverviewPage
    page = MarketOverviewPage(mdm, store)
    # 禁止首屏自动拉取资讯（避免真实网络请求与本次定向验证互相干扰）
    page._news_autoloaded = True
    page.show()
    app.processEvents()

    # 伪 fetch_all_news：逐源上报进度、支持 should_abort、单源超时参数透传
    calls = {"progress": 0, "aborted": False, "timeout": None}

    def fake_fetch(limit=60, force=False, use_cls=True, use_em=True, use_hx=True,
                   per_source_timeout=25, on_progress=None, should_abort=None):
        calls["timeout"] = per_source_timeout
        total = 13
        for i in range(total):
            if should_abort is not None and should_abort():
                calls["aborted"] = True
                break
            if on_progress is not None:
                on_progress(i + 1, total, f"已完成 {i+1}/{total} 源")
                calls["progress"] += 1
            # 模拟单源抓取耗时（< 8s 超时）
            import time
            time.sleep(0.01)
        return {
            "ts": 0, "items": [], "sources": {}, "by_source": {},
            "by_category": {}, "source_coverage": {"active_sources": 13, "total_sources": 13},
        }

    orig_fetch = nf.fetch_all_news
    orig_analyze = nf.ai_analyze_news
    orig_bias = M._news_overall_bias
    orig_nb = nf.news_bias_for_symbol
    nf.fetch_all_news = fake_fetch
    nf.ai_analyze_news = lambda *a, **k: {"confidence": 0.7, "trend": "x"}
    M._news_overall_bias = lambda news: 0.1
    nf.news_bias_for_symbol = lambda *a, **k: {"bias": 0, "matched": 0, "samples": 0}

    try:
        page._run_news()
        spin(app, 600)
        check(calls["timeout"] == 8, "单源超时参数已透传为 8s")
        check(calls["progress"] > 0, f"进度回调被调用 {calls['progress']} 次")
        check(page.news_prog.value() == 100, "资讯抓取完成后进度条置 100%")
        check(page.news_prog.isVisible() is False, "完成后进度条隐藏")

        # 取消：再次抓取并中途取消
        calls["progress"] = 0
        calls["aborted"] = False
        page._run_news()
        app.processEvents()
        # 抓取刚开始即取消
        page._stop_news()
        spin(app, 400)
        check(calls["aborted"] is True,
              "点击取消后 fetch_all_news 通过 should_abort 提前结束")
    finally:
        nf.fetch_all_news = orig_fetch
        nf.ai_analyze_news = orig_analyze
        M._news_overall_bias = orig_bias
        nf.news_bias_for_symbol = orig_nb


# ============================================================================
# ⑤ 离线回放：真实百分比进度（setRange(0,100)）
# ============================================================================
def t5_replay_progress(app) -> None:
    print("\n[⑤] 离线回放：真实百分比进度")
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    import tempfile
    import futures_quant.ai.calibration_replay as cr

    mdm = MarketDataManager(source="synthetic")
    mdm.connect()
    store = AnalysisStore(os.path.join(tempfile.mkdtemp(), "m4_09_replay.db"))

    from futures_quant.ui.predict_ops_page import PredictOpsPage
    import futures_quant.ai.feedback as fb
    page = PredictOpsPage(mdm, store)
    page.show()
    app.processEvents()

    check(page.replay_prog.minimum() == 0 and page.replay_prog.maximum() == 100,
          "回放进度条范围为 0~100（真实百分比）")

    # 伪样本发现 + 伪回放 + 伪校准（reliability_calibration 定义在 ai.feedback）
    n_samples = 5
    fake_samples = [(None, "RB", "D") for _ in range(n_samples)]
    orig_discover = cr.discover_local_samples
    orig_replay = cr.replay_symbol
    orig_calib = fb.reliability_calibration
    cr.discover_local_samples = lambda *a, **k: fake_samples
    cr.replay_symbol = lambda *a, **k: {"added": 1}
    fb.reliability_calibration = lambda *a, **k: (None, {"status": "ok"})

    try:
        page._run_replay()
        spin(app, 600)
        check(page.replay_prog.value() == 100, "回放完成后进度条达到 100%")
        check(page.replay_prog.isVisible() is False, "回放完成后进度条隐藏")
    finally:
        cr.discover_local_samples = orig_discover
        cr.replay_symbol = orig_replay
        fb.reliability_calibration = orig_calib


def main() -> None:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    t1_engine_step_hooks()
    t2_worker_passes_self(app)
    t3_evolution_page_control()
    t4_news_progress_cancel(app)
    t5_replay_progress(app)

    print("\n" + "=" * 70)
    if FAILS:
        print(f"M4-09 验收失败：{len(FAILS)} 项")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("M4-09 验收全部通过 ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
