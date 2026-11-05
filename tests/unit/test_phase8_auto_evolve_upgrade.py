# -*- coding: utf-8 -*-
"""第 4 期（阶段8）回归：自我进化的可复现性、可中断性、结果可靠性口径。

覆盖四项交付要求的可验证部分：
  ① 同 seed + 同参数 + 同数据指纹 ⇒ 完全相同的 fitness 与排名（可复现）；
  ② 基因间让出（inter_gene_yield_ms）只影响调度时序，不改变任何数值；
  ③ 每代提供 best/mean/std，并把「本代最优 vs 上代最优」按噪声带判定，
     而非把随机波动当作进步；
  ④ 中断后不落半截结果：不写盈利库、不推进代数、不推进断点；
     以及同品种行情只取一次（低风险效率优化，数值不变）。

全部用例使用 SyntheticFeed + 临时盈利库，不联网、不写生产 data/。
"""
from __future__ import annotations

import os

import pytest

from futures_quant.strategy import auto_evolve as ae
from futures_quant.data.synthetic import SyntheticFeed
from futures_quant.core.exceptions import InterruptionError

UNIVERSE = [("RB", "螺纹钢", "黑色系", "SHFE", 10, 1.0, 3500.0)]
SEED = 20240921


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """把盈利策略库重定向到临时目录，杜绝污染 data/auto_strategies。"""
    store_dir = tmp_path / "auto_strategies"
    store_dir.mkdir()
    monkeypatch.setattr(ae, "STORE_DIR", str(store_dir))
    monkeypatch.setattr(ae, "STORE_PATH", str(store_dir / "profitable_strategies.json"))
    monkeypatch.setattr(ae, "BACKUP_PATH", str(store_dir / "profitable_strategies.json.backup"))
    return store_dir


def _engine(seed: int = SEED, pop: int = 3, gens: int = 2, feed=None) -> ae.EvolutionEngine:
    """构造小规模引擎（短区间 + 小种群），保证单测快速。"""
    eng = ae.EvolutionEngine(
        feed or SyntheticFeed(), UNIVERSE,
        start="2020-01-01", end="2021-03-31", period="D",
        seed=seed, max_generations=gens, patience=99,
    )
    eng.POP_SIZE = pop
    return eng


def _ranked(snap: dict) -> list:
    """取「签名 + 适应度」的有序列表（排名与数值的双重指纹）。"""
    return [(r["signature"], r["fitness"]) for r in snap["ranked"]]


# ---------------------------------------------------------------- ① 可复现
def test_same_seed_same_genes_and_fitness():
    """同 seed + 同数据 ⇒ 两代排名与适应度逐项完全一致。"""
    a, b = _engine(), _engine()
    sa1, sb1 = a.step(), b.step()
    sa2, sb2 = a.step(), b.step()
    assert _ranked(sa1) == _ranked(sb1)
    assert _ranked(sa2) == _ranked(sb2)


def test_same_seed_same_data_fingerprint_and_fit_range():
    """数据指纹与 IS/OOS 切分也必须一致，否则缓存键不可比。"""
    a, b = _engine(), _engine()
    a.step(); b.step()
    assert a._feed_fingerprints == b._feed_fingerprints
    assert a._fit_periods == b._fit_periods


def test_different_seed_differs():
    """反向证明：seed 不同时结果不应完全相同（排除「假复现」）。"""
    a, b = _engine(seed=SEED), _engine(seed=SEED + 1)
    assert _ranked(a.step()) != _ranked(b.step())


# ---------------------------------------------------------------- ② 让出不改数值
def test_inter_gene_yield_does_not_change_results():
    """让出间隔（0 vs 15ms）只影响调度，不改变 fitness/排名。"""
    a = _engine(pop=3)
    a.inter_gene_yield_ms = 0
    b = _engine(pop=3)
    b.inter_gene_yield_ms = 15
    assert _ranked(a.step()) == _ranked(b.step())


# ---------------------------------------------------------------- ③ 结果可靠性
def test_snapshot_contains_distribution_and_progress():
    """每代快照必须带 best/mean/std + 进步判定 + OOS 口径。"""
    eng = _engine(pop=4)
    s1 = eng.step()
    st = s1["fitness_stats"]
    assert st["n"] == 4
    assert st["best"] is not None and st["mean"] is not None
    assert st["std"] is not None and st["std"] >= 0

    pg = s1["progress"]
    assert pg["level"] == "baseline", "首代无上代基线，不能判成进步"
    assert pg["is_only"] is True
    assert "IS" in pg["note"]

    s2 = eng.step()
    pg2 = s2["progress"]
    assert pg2["prev_best"] is not None
    assert pg2["level"] in {"none", "weak", "meaningful"}
    assert isinstance(pg2["noise_band"], float)

    oo = s2["oos"]
    assert oo["n"] == 4
    assert "固定尾段" in oo["note"] and "非独立锁箱" in oo["note"]
    assert isinstance(oo["oos_pass"], int)


def test_progress_levels_follow_noise_band():
    """直接验证判定函数：低于上代=不计进步，≤噪声带=弱信号，>噪声带=IS 进步。"""
    eng = _engine(pop=2)
    eng._prev_gen_best = 10.0
    eng._prev_gen_std = 2.0      # 噪声带取 max(本代 std=1.0, 上代 2.0) = 2.0

    res = [{"fitness": 11.0, "signature": "a", "_is_ok": True, "_oos_ok": False},
           {"fitness": 9.0, "signature": "b", "_is_ok": False, "_oos_ok": True}]
    _, pg, _ = eng._summarize_generation(res)
    assert pg["delta"] == pytest.approx(1.0)
    assert pg["level"] == "weak", "Δ 1.0 未超过噪声带 2.0，不得当作进步"
    assert "随机波动" in pg["note"]

    res_hi = [{"fitness": 15.0, "signature": "c", "_is_ok": True, "_oos_ok": True},
              {"fitness": 13.0, "signature": "d", "_is_ok": False, "_oos_ok": False}]
    _, pg_hi, _ = eng._summarize_generation(res_hi)
    assert pg_hi["level"] == "meaningful"
    assert "OOS" in pg_hi["note"]

    res_lo = [{"fitness": 8.0, "signature": "e", "_is_ok": False, "_oos_ok": False},
              {"fitness": 7.0, "signature": "f", "_is_ok": False, "_oos_ok": False}]
    _, pg_lo, _ = eng._summarize_generation(res_lo)
    assert pg_lo["level"] == "none"


def test_first_generation_is_baseline_not_progress():
    """首代必须判为 baseline，避免第一次就宣称「进步」。"""
    eng = _engine(pop=2)
    st, pg, oo = eng._summarize_generation(
        [{"fitness": 5.0, "signature": "a", "_is_ok": True, "_oos_ok": True},
         {"fitness": 1.0, "signature": "b", "_is_ok": False, "_oos_ok": False}])
    assert pg["level"] == "baseline"
    assert pg["prev_best"] is None
    assert oo["best_is_oos_pass"] is True


# ---------------------------------------------------------------- ④ 中断不留半截
def test_interruption_leaves_no_partial_state():
    """第一代中途中断：不写盈利库、代数不推进、断点不产生。"""
    eng = _engine(pop=3)
    fired = {"n": 0}

    def on_prog(done, total, text):
        fired["n"] = done

    with pytest.raises(InterruptionError):
        eng.step(should_abort=lambda: fired["n"] >= 1, on_progress=on_prog)

    assert fired["n"] == 1, "应在第 1 个基因后立即中断"
    assert eng.generation == 0, "中断不得推进代数"
    assert eng._prev_gen_best is None, "中断不得产生进步基线"
    assert not os.path.exists(ae.STORE_PATH), "中断不得写盈利策略库"
    assert ae.load_profitable() == [], "临时库应为空"


def test_interruption_keeps_breakpoint_state_reusable():
    """中断后引擎状态仍可继续：同一实例再跑一代可正常完成并推进代数。"""
    eng = _engine(pop=3)
    fired = {"n": 0}
    with pytest.raises(InterruptionError):
        eng.step(should_abort=lambda: fired["n"] >= 1,
                 on_progress=lambda d, t, x: fired.__setitem__("n", d))
    eng.step()                        # 不应抛异常
    assert eng.generation == 1


def test_state_roundtrip_keeps_progress_baseline():
    """断点必须携带进步基线，续跑后不会把「上代最优」当首代。"""
    eng = _engine(pop=3)
    eng.step()
    st = eng.to_state()
    assert st["prev_gen_best"] is not None
    assert st["prev_gen_best_sig"] is not None

    fresh = _engine(pop=3)
    assert fresh.restore_state(st) is True
    assert fresh._prev_gen_best == st["prev_gen_best"]
    assert fresh._prev_gen_best_sig == st["prev_gen_best_sig"]


# ---------------------------------------------------------------- 效率（数值不变）
def test_same_symbol_history_is_fetched_once():
    """IS/OOS 切分 + 数据指纹共用一次取数（原实现各取一次）。"""

    class _CountingFeed:
        def __init__(self, inner):
            self.inner, self.calls = inner, 0

        def get_history(self, *a, **k):
            self.calls += 1
            return self.inner.get_history(*a, **k)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    cf = _CountingFeed(SyntheticFeed())
    eng = _engine(feed=cf)
    eng._fit_range("RB")
    eng._feed_fingerprint("RB")
    assert cf.calls == 1, "切分与指纹必须复用同一份行情"


def test_provenance_is_cached_for_watermark():
    """取数时顺带缓存 provenance，供界面水印使用（不需要主线程另取数）。"""
    eng = _engine()
    eng._feed_fingerprint("RB")
    prov = eng._feed_provenances["RB"]
    assert set(prov) == {"data_source", "is_synthetic", "is_stale", "as_of"}
    assert isinstance(prov["is_synthetic"], bool)
