"""阶段8 回归测试：进化缓存一致性 + 结果可追溯 + 历史库治理。

覆盖：
1. 缓存命中必须返回**完整评估结果**，评分与首次评估逐字段一致（核心 P0）；
2. 老结构 `(gene, fitness)` 缓存失效并升级；仅存 fitness 的邻域条目会补全评估；
3. 缓存 LRU 上限（完整结果含曲线/成交，必须内存有界）；
4. 进化快照携带 run_id / 数据指纹 / 数据源 / seed / 参数快照 / created_at；
5. 同一参数 + 同一种子 + 同一数据指纹 ⇒ 同一结果（可复现）；
6. 历史库迁移幂等：补列、归档清理空行、老行读取端标记 legacy_missing 且不伪造；
7. add_history 写入可追溯字段 + 空行防护；
8. prune 后按空闲页触发 VACUUM，库体积实测下降。

运行：
    pytest tests/unit/test_phase8_traceability_db.py -q
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

import pytest

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.data.synthetic import SyntheticFeed  # noqa: E402
from futures_quant.storage.backtest_store import BacktestStore  # noqa: E402
from futures_quant.strategy import auto_evolve as ae  # noqa: E402

_BT_START = "2020-01-01"
_BT_END = "2021-12-31"
_UNIVERSE = [("rb", "螺纹钢", 1, "SHFE", 10, 1.0)]


# ---------------------------------------------------------------------------
# 1. 缓存命中：评分与首次评估完全一致（阶段8 核心 P0）
# ---------------------------------------------------------------------------

def _engine(seed: int = 42, pop_size: int = 3) -> ae.EvolutionEngine:
    eng = ae.EvolutionEngine(
        feed=SyntheticFeed(),
        universe=list(_UNIVERSE),
        start=_BT_START,
        end=_BT_END,
        period="D",
        seed=seed,
    )
    eng.POP_SIZE = pop_size
    return eng


def test_cache_hit_scores_identical_to_first_evaluation():
    """同一基因第二次评估命中缓存，fitness/metrics/profitable/成交/曲线必须与首次完全一致。

    修复前：命中缓存返回 metrics={} / profitable=False / trades=[]，
    导致「同一基因第二次评估」被系统性判为不赚钱，污染进化结果与精英选择。
    """
    import random

    eng = _engine(seed=42)
    gene = ae.random_gene(random.Random(5))

    first = eng._evaluate(gene)
    assert not first.get("_cache_hit"), "首次评估不应命中缓存"
    assert first["metrics"], "首次评估应产出非空指标"

    second = eng._evaluate(gene)
    assert second.get("_cache_hit") is True, "同基因第二次评估必须命中缓存"
    assert second["fitness"] == pytest.approx(first["fitness"], rel=0, abs=0), \
        f"缓存命中 fitness 不一致：{second['fitness']} != {first['fitness']}"
    assert second["metrics"] == first["metrics"], "缓存命中 metrics 与首次不一致"
    assert second["profitable"] == first["profitable"], \
        "缓存命中 profitable 与首次不一致（历史上被误判为 False）"
    assert second["reasons"] == first["reasons"]
    assert second["signature"] == first["signature"]
    assert second["gene"] == first["gene"]
    assert len(second["trades"]) == len(first["trades"]), "缓存命中成交数量丢失"
    assert second["equity_curve"] == first["equity_curve"], "缓存命中资金曲线丢失"


def test_cache_hit_preserves_profitable_and_metrics():
    """预置一条「盈利」结果，命中后必须保留 profitable=True 与非空 metrics。"""
    import random

    eng = _engine(seed=43)
    gene = ae.random_gene(random.Random(6))
    key = f"{ae.gene_signature(gene)}|{eng._data_version}"
    eng._fit_cache[key] = {
        "gene": gene, "fitness": 9.9,
        "result": {
            "gene": gene, "desc": ae.describe_gene(gene),
            "signature": ae.gene_signature(gene),
            "metrics": {"sharpe": 1.5, "total_return": 0.2},
            "fitness": 9.9, "profitable": True, "reasons": [],
            "equity_curve": [("2021-01-01", 100.0, 100.0)],
            "trades": [{"symbol": "rb.SHFE"}],
        },
    }
    res = eng._evaluate(gene)
    assert res.get("_cache_hit") is True
    assert res["profitable"] is True, "缓存命中的盈利标记被篡改"
    assert res["metrics"]["sharpe"] == 1.5
    assert len(res["trades"]) == 1
    assert len(res["equity_curve"]) == 1


def test_legacy_tuple_cache_is_invalidated_and_upgraded():
    """老结构 `(gene, fitness)` 缺 metrics/profitable → 视为失效，重新完整评估并升级缓存。"""
    import random

    eng = _engine(seed=44)
    gene = ae.random_gene(random.Random(7))
    legacy_key = f"{ae.gene_signature(gene)}|{eng._data_version}"
    eng._fit_cache[legacy_key] = (gene, -3.0)

    res = eng._evaluate(gene)
    assert not res.get("_cache_hit"), "老结构缓存不得被当作有效命中"
    assert res["metrics"], "失效后必须重新产出完整指标"
    assert legacy_key not in eng._fit_cache, "失效的老条目必须被清除"
    new_key = eng._cache_key(ae.gene_signature(gene), eng.symbol())
    assert isinstance(eng._fit_cache.get(new_key), dict)
    assert eng._fit_cache[new_key]["result"] is not None


def test_fitness_only_entry_triggers_full_evaluation():
    """参数邻域评估只写 fitness（result=None），主评估命中它时必须补全完整结果。"""
    import random

    eng = _engine(seed=45)
    gene = ae.random_gene(random.Random(8))
    key = eng._cache_key(ae.gene_signature(gene), eng.symbol())
    eng._fit_cache[key] = {"gene": gene, "fitness": 0.0, "result": None}

    # 邻域评估读取该条目：直接返回 fitness，不重跑
    assert eng._evaluate_fitness_only(gene) == 0.0

    res = eng._evaluate(gene)
    assert not res.get("_cache_hit"), "仅存 fitness 的条目不得当作完整命中"
    assert res["metrics"], "必须补全完整结果"
    assert eng._fit_cache[key]["result"] is not None


def test_cache_lru_bounds_entries():
    """缓存容量有上限：完整结果含曲线/成交，无上限长跑会累积数百 MB。"""
    import random

    eng = _engine(seed=46)
    eng._fit_cache_max = 5
    gene = ae.random_gene(random.Random(9))
    for i in range(12):
        eng._cache_put(f"k{i}", gene, float(i),
                       {"gene": gene, "fitness": float(i), "metrics": {},
                        "profitable": False, "reasons": [], "equity_curve": [],
                        "trades": [], "desc": "", "signature": ""})
    assert len(eng._fit_cache) == 5
    assert "k7" in eng._fit_cache and "k11" in eng._fit_cache
    assert "k0" not in eng._fit_cache


# ---------------------------------------------------------------------------
# 2. 结果可追溯：快照携带元数据 + 可复现
# ---------------------------------------------------------------------------

def test_step_snapshot_carries_traceability_fields():
    """每代快照必须带 run_id / 数据指纹 / 数据源 / seed / 参数快照 / 写入时间。"""
    eng = _engine(seed=1234, pop_size=3)
    snap = eng.step()

    assert re.fullmatch(r"[0-9a-f]{12}", snap["data_fingerprint"] or ""), \
        f"数据指纹格式异常: {snap.get('data_fingerprint')}"
    assert snap["seed"] == 1234
    assert (snap["run_id"] or "").startswith("run_")
    assert snap["data_source"] == "synthetic"
    assert snap["is_synthetic"] is True
    assert snap["as_of"], "合成行情应带最后更新时间"
    assert snap["created_at"]
    params = snap["params_snapshot"]
    assert params["period"] == "D"
    assert params["universe"] == ["rb"]
    assert params["data_start"] == _BT_START and params["data_end"] == _BT_END
    # run_id 同一次运行内稳定（不随代数变化）
    assert eng._run_id() == snap["run_id"]


def test_same_seed_params_and_fingerprint_reproduce_same_results():
    """同一参数 + 同一种子 + 同一数据指纹 ⇒ 逐基因签名与评分完全一致。"""
    snaps = []
    for _ in range(2):
        eng = _engine(seed=2024, pop_size=3)
        snaps.append(eng.step())
    a, b = snaps

    assert a["data_fingerprint"] == b["data_fingerprint"], "同源数据指纹不一致"
    assert a["params_snapshot"] == b["params_snapshot"], "参数快照不一致"
    assert a["seed"] == b["seed"] == 2024
    assert [(r["signature"], r["fitness"]) for r in a["ranked"]] == \
           [(r["signature"], r["fitness"]) for r in b["ranked"]], \
           "同参数同种子同指纹下结果不一致（不可复现）"


# ---------------------------------------------------------------------------
# 3. 历史库迁移：补列 / 归档空行 / 老行标注
# ---------------------------------------------------------------------------

_OLD_SCHEMA = """
CREATE TABLE evolve_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, symbol TEXT, symbol_name TEXT, period TEXT,
    generation INTEGER, gen_in_symbol INTEGER, pop_size INTEGER,
    best_desc TEXT, best_signature TEXT,
    total_return REAL, annual_return REAL, sharpe REAL,
    max_drawdown REAL, win_rate REAL, trades INTEGER, fitness REAL,
    new_profitable INTEGER, profitable_total INTEGER,
    gene_json TEXT, metrics_json TEXT,
    trades_json TEXT, equity_curve_json TEXT);
"""


def _make_legacy_db(path: str) -> None:
    """构造迁移前的旧库：1 条正常记录 + 1 条全空脏记录。"""
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_SCHEMA)
    conn.execute(
        "INSERT INTO evolve_history(ts, symbol, symbol_name, period, generation, "
        "pop_size, best_desc, best_signature, total_return, sharpe, fitness, "
        "metrics_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-09-01T10:00:00", "rb.SHFE", "螺纹钢", "D", 3, 10,
         "双均线", "sig_rb_1", 0.12, 1.35, 6.5, '{"sharpe": 1.35}'))
    conn.execute(
        "INSERT INTO evolve_history(ts, generation, metrics_json) VALUES(?,?,?)",
        ("2026-09-02T10:00:00", 65, "{}"))
    conn.commit()
    conn.close()


def test_migration_is_idempotent_and_archives_empty_rows(tmp_path):
    db = str(tmp_path / "legacy.db")
    _make_legacy_db(db)
    store = BacktestStore(db)

    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(evolve_history)")}
    for col in ("run_id", "data_fingerprint", "seed", "params_json",
                "data_source", "created_at", "is_synthetic", "as_of"):
        assert col in cols, f"迁移未补列 {col}"

    stats = store.db_stats()
    assert stats["history_rows"] == 1, "空行应被清理"
    assert stats["archived_rows"] == 1, "空行必须先归档再删除"
    archived = json.loads(store.conn.execute(
        "SELECT payload_json FROM evolve_history_archive WHERE reason='empty_row'"
    ).fetchone()[0])
    assert archived["id"] and archived["metrics_json"] == "{}", "归档内容必须保留原始整行"

    # 正常行内容不得被改动
    row = dict(store.conn.execute(
        "SELECT * FROM evolve_history WHERE symbol='rb.SHFE'").fetchone())
    assert row["best_signature"] == "sig_rb_1"
    assert row["total_return"] == pytest.approx(0.12)
    assert row["data_fingerprint"] is None, "老行不得伪造指纹"

    # 读取端显式标注老记录缺指纹
    recs = store.recent_history()
    assert recs[0]["trace_status"] == "legacy_missing"
    assert recs[0]["trace_note"] and "老记录无指纹" in recs[0]["trace_note"]
    assert recs[0]["data_fingerprint"] is None
    assert recs[0]["seed"] is None and recs[0]["run_id"] is None

    detail = store.get_history_detail(recs[0]["id"])
    assert detail["trace_status"] == "legacy_missing"
    assert detail["params"] is None, "老行参数必须为 None，不得用默认值填充"

    # 幂等：再次打开（再次迁移）不得重复归档或重复补列
    store2 = BacktestStore(db)
    stats2 = store2.db_stats()
    assert stats2["history_rows"] == stats["history_rows"]
    assert stats2["archived_rows"] == stats["archived_rows"]
    store.close()
    store2.close()


def test_add_history_writes_trace_fields_and_rejects_empty_rows(tmp_path):
    store = BacktestStore(str(tmp_path / "write.db"))
    snap = {
        "symbol": "rb.SHFE", "symbol_name": "螺纹钢", "period": "D",
        "generation": 5, "gen_in_symbol": 1,
        "ranked": [{"desc": "双均线", "signature": "sig_x",
                    "gene": {"type": "ma_cross", "params": {}},
                    "metrics": {"sharpe": 0.8}, "fitness": 2.0,
                    "profitable": True, "reasons": []}],
        "new_profitable": [{"signature": "sig_x"}], "profitable_total": 3,
        "run_id": "run_abc123456789",
        "data_fingerprint": "deadbeefcafe",
        "seed": 42,
        "data_source": "synthetic",
        "is_synthetic": True,
        "as_of": "2021-12-31 00:00:00",
        "created_at": "2026-11-04T17:30:00",
        "params_snapshot": {"period": "D", "universe": ["rb"],
                            "futures_params": {"rb.SHFE": {"multiplier": 10}}},
    }
    hid = store.add_history(snap)
    assert hid is not None
    rec = store.get_history_detail(hid)
    assert rec["trace_status"] == "ok"
    assert rec["run_id"] == "run_abc123456789"
    assert rec["data_fingerprint"] == "deadbeefcafe"
    assert rec["seed"] == 42
    assert rec["data_source"] == "synthetic"
    assert rec["is_synthetic"] == 1
    assert rec["as_of"] == "2021-12-31 00:00:00"
    assert rec["created_at"] == "2026-11-04T17:30:00"
    assert rec["params"]["futures_params"]["rb.SHFE"]["multiplier"] == 10

    before = store.db_stats()["history_rows"]
    assert store.add_history({"ranked": []}) is None, "无 ranked 的空行必须拒绝写入"
    assert store.add_history({"symbol": "rb.SHFE", "ranked": []}) is None, \
        "无排名的空行必须拒绝写入"
    assert store.db_stats()["history_rows"] == before
    store.close()


def test_prune_triggers_vacuum_and_shrinks_db(tmp_path):
    """prune 之后库体积必须可见下降：删除的页进入 freelist，需要 VACUUM 才真正回收。"""
    db = str(tmp_path / "prune.db")
    store = BacktestStore(db)
    store._PRUNE = {"evolve_history": 5, "evolve_log": 500}
    base_clock = [("2021-01-01", 1e6, 1e6)] * 4000  # 每条约 100KB 资金曲线
    for i in range(40):
        store.add_history({
            "symbol": "rb.SHFE", "symbol_name": "螺纹钢", "period": "D",
            "generation": i, "gen_in_symbol": 0,
            "ranked": [{"desc": f"g{i}", "signature": f"sig{i}",
                        "gene": {}, "metrics": {"sharpe": 0.1},
                        "fitness": 0.1, "profitable": False, "reasons": []}],
            "gen_best_curve": base_clock,
            "new_profitable": [], "profitable_total": 0,
        })
    store.checkpoint()
    before = store.db_stats()

    result = store.prune()
    assert result["deleted"] == 35, f"按限容应删除 35 行，实际 {result['deleted']}"
    assert result["vacuumed"] is True, "空闲页超过门槛时必须执行 VACUUM"
    after = store.db_stats()
    assert after["history_rows"] == 5
    assert after["freelist_pages"] < before["freelist_pages"] + 1
    assert result["size_after"] < result["size_before"], \
        f"VACUUM 后体积未下降：{result['size_before']} -> {result['size_after']}"
    assert result["reclaimed_bytes"] > 0
    store.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
