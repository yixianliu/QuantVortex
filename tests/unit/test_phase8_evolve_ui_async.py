# -*- coding: utf-8 -*-
"""第 4 期（阶段8）回归：自进化页的后台化、进度可见性与诚实呈现。

关键约束验证点：
  ① 启动维护（prune 可能触发 VACUUM）不再跑在主线程；
  ② 数据来源水印不再触发主线程取数（复用引擎后台取数缓存的 provenance）；
  ③ 进度区可见「当前代/总代数/已用时/最优 fitness」；
  ④ 每代统计明确「仅 IS 口径、不可当作实盘优势」，中断明确「结果已丢弃」。
"""
from __future__ import annotations

import ast
import os
import threading
import time
import types

import pytest
from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_qapp = QApplication.instance() or QApplication([])


def _src() -> str:
    with open(os.path.join(ROOT, "futures_quant", "ui", "backtest_page.py"),
              "r", encoding="utf-8") as f:
        return f.read()


def _func_body(name: str) -> str:
    src = _src()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"未找到 {name}")


def _mock_mdm() -> types.SimpleNamespace:
    """最小 MarketDataManager 替身（与既有单测保持一致）。"""
    def _no_bars(*a, **k):
        raise RuntimeError("单测不得触发主线程取数")

    return types.SimpleNamespace(
        universe=[("RB", "SHFE", "rb", "SHFE", 10, 1)],
        get_history=lambda *a, **k: None,
        get_quote=lambda *a, **k: {},
        get_bars=_no_bars,
        is_real=False,
    )


@pytest.fixture(scope="module")
def page():
    from futures_quant.storage.evolution_store import reset_evolution_store_for_test
    from futures_quant.ui.backtest_page import BacktestCenterPage
    reset_evolution_store_for_test()
    p = BacktestCenterPage(_mock_mdm(), store=None, config=None)
    yield p
    reset_evolution_store_for_test()


def _wait_until(pred, timeout: float = 10.0) -> bool:
    """在测试里手动泵 Qt 事件循环，等待 worker 回调回到主线程。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _qapp.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    _qapp.processEvents()
    return pred()


class _FakeStore:
    """只记录「prune 在哪个线程执行」，不碰真实数据库。"""

    def __init__(self, boom: bool = False):
        self.boom = boom
        self.threads = []
        self.checkpointed = 0
        self.logs = []

    def prune(self):
        self.threads.append(threading.current_thread().name)
        time.sleep(0.15)
        if self.boom:
            raise OSError("simulated vacuum failure")
        return {"deleted": 3, "vacuumed": False}

    def checkpoint(self):
        self.checkpointed += 1

    def add_log(self, text: str):
        # page._log 会写日志表；替身必须实现，否则会在 Qt 槽内抛异常导致原生崩溃
        self.logs.append(text)


# ---------------------------------------------------------------- ① 维护后台化
def test_start_auto_does_not_prune_on_main_thread():
    """源码门禁：_start_auto 内不得再同步调用 prune()/checkpoint()。"""
    body = _func_body("_start_auto")
    assert "prune(" not in body, "启动路径不得在主线程同步 prune（会卡 UI）"
    assert "checkpoint(" not in body
    assert "_run_maintenance_async" in body, "维护应交给后台 worker + 完成回调"


def test_maintenance_runs_in_background_thread(page):
    """prune/checkpoint 实际执行线程不是主线程，且完成后回调。"""
    store = _FakeStore()
    page._bt_store = store
    done = {"called": False}
    try:
        page._run_maintenance_async(lambda: done.__setitem__("called", True))
        assert _wait_until(lambda: done["called"]), "维护完成回调未触发"
    finally:
        page._bt_store = None
    assert store.threads, "prune 未被调用"
    assert store.threads[0] != threading.main_thread().name, \
        "数据库维护必须在后台线程执行（原实现阻塞主线程）"
    assert store.checkpointed == 1
    assert page._maintenance_worker is None, "结束后应清理后台句柄"


def test_maintenance_failure_still_calls_done(page):
    """维护失败（VACUUM 异常等）必须降级为「跳过」并继续启动，不阻断进化。"""
    store = _FakeStore(boom=True)
    page._bt_store = store
    done = {"called": False}
    try:
        page._run_maintenance_async(lambda: done.__setitem__("called", True))
        assert _wait_until(lambda: done["called"])
    finally:
        page._bt_store = None
    assert store.checkpointed == 0, "prune 抛错后不应继续 checkpoint"


# ---------------------------------------------------------------- ② 水印不取数
def test_update_evo_prov_never_fetches_on_main_thread(page, monkeypatch):
    """水印刷新不得调用 mdm.get_bars（原实现每代在主线程真取数）。"""
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("不应在主线程取数")

    monkeypatch.setattr(page.mdm, "get_bars", _boom)
    eng = types.SimpleNamespace(
        symbol=lambda: "RB",
        _feed_provenances={"RB": {"data_source": "synthetic", "is_synthetic": True,
                                  "is_stale": False, "as_of": "2026-11-04 12:00:00"}},
    )
    page._engine = eng
    page._update_evo_prov()
    assert calls["n"] == 0, "水印必须复用后台缓存，不得触发主线程取数"
    assert "合成" in page.evo_prov.text()
    page._engine = None


def test_update_evo_prov_pending_text_is_explicit(page):
    """无 provenance 时明确写「待确认」，不推测、不隐去来源。"""
    page._engine = types.SimpleNamespace(symbol=lambda: "RB", _feed_provenances={})
    page._update_evo_prov()
    txt = page.evo_prov.text()
    assert "完成后确认" in txt and "不推测" in txt
    assert "数据来源" in txt
    page._engine = None


# ---------------------------------------------------------------- ③ 进度可见性
def test_progress_label_shows_gen_total_elapsed_and_best(page):
    """进度区必须含「第 n/总 代 / 已用 / 历史最优 fitness」。"""
    page._engine = types.SimpleNamespace(max_generations=200, _best_fitness=12.3)
    page._cur_gen_no = 3
    page._evo_elapsed_start = QTime.currentTime().addSecs(-65)
    page._on_evolution_progress(40, "基因 4/10")
    txt = page._evo_stage_label.text()
    assert "第 3/200 代" in txt
    assert "基因 4/10" in txt
    assert "已用 01:0" in txt
    assert "12.3" in txt
    assert "已用" in page._evo_eta_label.text() and "预计剩余" in page._evo_eta_label.text()
    page._engine = None


def test_progress_label_handles_infinite_best(page):
    """历史最优仍是 -inf（首代未完成）时显示占位，不打印 -inf。"""
    page._engine = types.SimpleNamespace(max_generations=200,
                                        _best_fitness=float("-inf"))
    page._cur_gen_no = 1
    page._evo_elapsed_start = QTime.currentTime()
    page._on_evolution_progress(10, "基因 1/10")
    assert "-inf" not in page._evo_stage_label.text()
    assert "--" in page._evo_stage_label.text()
    page._engine = None


# ---------------------------------------------------------------- ④ 诚实呈现
def test_evo_stats_label_is_only_disclaimer(page):
    """统计区必须写明「仅 IS」与「不可当作实盘优势」，并带分布数字。"""
    snap = {
        "generation": 5,
        "fitness_stats": {"n": 10, "best": 21.5, "mean": 8.2, "std": 6.1,
                          "median": 7.4, "min": -3.0},
        "progress": {"prev_best": 20.0, "delta": 1.5, "noise_band": 6.1,
                     "level": "weak", "best_carried_over": False,
                     "note": "高于上代最优但未超过离散度（Δ=+1.50 ≤ 噪声带 6.10），"
                             "可能只是随机波动"},
        "oos": {"n": 10, "is_pass": 2, "oos_pass": 0, "best_is_oos_pass": False,
                "note": "OOS 为固定尾段且逐代复用（非独立锁箱）"},
    }
    page._update_evo_stats(snap)
    txt = page._evo_stats_label.text()
    assert "最优 21.5" in txt and "均值 8.2" in txt and "± 6.1" in txt
    assert "疑似随机波动" in txt
    assert "OOS" in txt and "0/10" in txt
    assert "样本内(IS)" in txt
    assert "不可当作实盘优势" in txt
    # 常驻说明必须一直可见
    assert "不可当作实盘优势" in page._evo_is_note.text()


def test_evo_stats_baseline_generation(page):
    """首代统计显示「基准代」，不得写「进步」。"""
    page._update_evo_stats({
        "generation": 1,
        "fitness_stats": {"n": 10, "best": 5.0, "mean": 2.0, "std": 1.5,
                          "median": 2.0, "min": 0.0},
        "progress": {"prev_best": None, "delta": None, "noise_band": 1.5,
                     "level": "baseline", "note": "首代基准：无上代最优可比（仅 IS 口径）"},
        "oos": {"n": 10, "is_pass": 1, "oos_pass": 1, "best_is_oos_pass": False,
                "note": "OOS 固定尾段"},
    })
    txt = page._evo_stats_label.text()
    assert "基准代" in txt
    assert "不计为进步" not in txt and "IS 内进步" not in txt


def test_interrupted_text_states_results_discarded(page):
    """中断文案必须明确「未完成结果已丢弃、未写历史库、断点未推进」。"""
    page._evolution_stopped = False
    page._on_evolution_interrupted()
    assert "已丢弃" in page._evo_stats_label.text()
    assert "未写入历史库" in page.info.text()


def test_gen_done_log_uses_snapshot_best_fitness_key():
    """回归：旧代码读 snap.get('best_fit')，日志永远 N/A；必须读 best_fitness。"""
    body = _func_body("_next_generation")
    assert "best_fitness" in body
