"""第 3 期回归测试：参数快照 / 执行器等价 / 扫描内存上限 / 落库复跑 / 导出。

覆盖要点：
    1. `BacktestConfig` 所有字段都进入快照，任何字段变化都改变 params_hash；
    2. 新执行器与旧 `Backtester` 直接调用逐位一致（指标 + 逐笔成交摘要）；
    3. 参数扫描边算边汇总：摘要条数/字节受上限约束，Top-K 与全量聚合正确；
    4. `backtest_runs` 落库、幂等 upsert、按 run_id 复跑校验一致；
    5. 导出 CSV/JSON 含 KPI、成交、参数快照与数据指纹；
    6. 老库迁移前自动备份，迁移幂等。
"""
from __future__ import annotations

import json
import os
import sqlite3

import pandas as pd
import pytest

from futures_quant.app.backtest_service import BacktestService
from futures_quant.backtest import export as export_mod
from futures_quant.backtest import runner
from futures_quant.backtest.backtester import Backtester
from futures_quant.backtest.run_config import BacktestConfig
from futures_quant.backtest.sweep import SweepLimits, expand_grid, run_sweep
from futures_quant.backtest.trace import (
    code_version, fingerprint_frame, make_run_id, trades_digest,
)
from futures_quant.config.settings import Config
from futures_quant.data.contract_specs import build_contract
from futures_quant.data.synthetic import SyntheticFeed
from futures_quant.storage.backtest_store import BacktestStore
from futures_quant.strategy.trend_following import TrendFollowing

SYMBOL = "rb.SHFE"
START = "2020-01-01"
END = "2021-06-01"


def _cfg(**overrides) -> BacktestConfig:
    base = Config()
    start = overrides.pop("start", START)
    end = overrides.pop("end", END)
    period = overrides.pop("period", "D")
    warmup = overrides.pop("warmup", 60)
    return BacktestConfig.from_settings(
        base, symbol=SYMBOL, start=start, end=end, period=period,
        warmup=warmup, strategy_name="trend_following", strategy_params={},
        **overrides,
    )


def _feed() -> SyntheticFeed:
    return SyntheticFeed()


# ---------------------------------------------------------------------------
# 1. 参数快照完整性
# ---------------------------------------------------------------------------
def test_snapshot_contains_every_field_and_is_json_serializable():
    cfg = _cfg()
    snap = cfg.params_snapshot()
    # 账户 / 成本 / 风控三段完整展开
    for key in ("initial_capital", "margin_rate", "multiplier",
                "commission_per_lot", "close_today_ratio"):
        assert key in snap["account"], f"账户字段 {key} 未进入快照"
    for key in ("slippage", "fill_mode", "slip_mode", "slip_ratio",
                "slip_atr_k", "atr_window", "limit_up_pct", "limit_down_pct",
                "enable_roll_cost", "roll_spread_mode", "pending_expire_bars",
                "enable_dominant_roll"):
        assert key in snap["backtest"], f"成本/撮合字段 {key} 未进入快照"
    for key in ("non_trading_hours_block", "max_position_per_symbol",
                "margin_halt_ratio"):
        assert key in snap["risk"], f"风控字段 {key} 未进入快照"
    # 显式维度
    assert snap["data"] == {"symbol": SYMBOL, "start": START, "end": END,
                            "period": "D", "warmup": 60}
    assert snap["strategy"]["name"] == "trend_following"
    assert snap["seed"] is not None
    # 必须可 JSON 序列化（落库/导出前提）
    json.dumps(snap, ensure_ascii=False)


@pytest.mark.parametrize("override", [
    {"warmup": 30},
    {"strategy_params": {"slow": 60}},
    {"account_params": {"margin_rate": 0.12}},
    {"account_params": {"initial_capital": 2_000_000.0}},
    {"backtest_params": {"fill_mode": "close"}},
    {"backtest_params": {"slippage": 2.0}},
    {"backtest_params": {"enable_dominant_roll": True}},
    {"backtest_params": {"roll_spread_mode": "charge"}},
    {"risk_params": {"non_trading_hours_block": False}},
    {"seed": 12345},
])
def test_every_field_change_alters_params_hash(override):
    """不允许隐式默认值：任一维度显式变化都必须改变参数指纹。"""
    base = _cfg()
    variant = base.with_overrides(**override)
    assert base.params_hash() != variant.params_hash(), f"{override} 未进入指纹"


def test_to_settings_roundtrip_keeps_values():
    raw = Config()
    raw.risk.non_trading_hours_block = False
    raw.backtest.slippage = 2.5
    cfg = BacktestConfig.from_settings(raw, symbol=SYMBOL, start=START, end=END,
                                       period="D", warmup=60)
    rebuilt = cfg.to_settings()
    assert rebuilt.risk.non_trading_hours_block is False
    assert rebuilt.backtest.slippage == 2.5
    assert rebuilt.account.initial_capital == raw.account.initial_capital


def test_from_snapshot_roundtrip():
    cfg = _cfg()
    snap = json.loads(cfg.params_json())
    restored = BacktestConfig.from_snapshot(snap)
    assert restored.params_hash() == cfg.params_hash()
    assert restored.symbol == cfg.symbol
    assert restored.enable_dominant_roll == cfg.enable_dominant_roll


# ---------------------------------------------------------------------------
# 2. 执行器与旧路径逐位等价
# ---------------------------------------------------------------------------
def test_runner_matches_legacy_backtester_exactly():
    feed = _feed()
    cfg = _cfg()
    new_res = runner.execute(cfg, feed)

    legacy = Backtester(cfg.to_settings(), feed)
    legacy.add_contract(build_contract(SYMBOL))
    legacy.add_strategy(TrendFollowing(symbol=SYMBOL))
    old_res = legacy.run(SYMBOL, START, END, "D", 60)

    assert new_res["metrics"] == old_res["metrics"]
    assert trades_digest(new_res["trades"]) == trades_digest(old_res["trades"])
    assert [str(p[0]) for p in new_res["equity_curve"]] == \
           [str(p[0]) for p in old_res["equity_curve"]]
    assert [round(p[1], 6) for p in new_res["equity_curve"]] == \
           [round(p[1], 6) for p in old_res["equity_curve"]]
    # 指纹字段为新增，且旧路径已同步具备
    assert len(new_res["data_fingerprint"]) == 40
    assert new_res["data_fingerprint"] == old_res["data_fingerprint"]
    # 快照记录策略生效参数（含类默认值），不是调用方传入的空字典
    eff_cfg = cfg.with_overrides(strategy_params=dict(TrendFollowing(symbol=SYMBOL).params))
    assert new_res["params_hash"] == eff_cfg.params_hash()
    assert "slow" in new_res["params_snapshot"]["strategy"]["params"]


def test_run_id_and_result_hash_are_deterministic():
    feed = _feed()
    cfg = _cfg()
    r1 = runner.execute(cfg, feed)
    r2 = runner.execute(cfg, feed)
    assert r1["run_id"] == r2["run_id"]
    assert r1["result_hash"] == r2["result_hash"]
    assert r1["trades_digest"] == r2["trades_digest"]
    assert r1["equity_digest"] == r2["equity_digest"]

    changed = cfg.with_overrides(strategy_params={"fast": 12})
    r3 = runner.execute(changed, feed)
    assert r3["run_id"] != r1["run_id"]
    assert r3["params_hash"] != r1["params_hash"]


def test_fingerprint_changes_with_data_window():
    feed = _feed()
    df1 = feed.get_history(SYMBOL, START, END, "D")
    df2 = feed.get_history(SYMBOL, START, "2021-03-01", "D")
    fp1 = fingerprint_frame(df1)
    fp2 = fingerprint_frame(df2)
    assert fp1.sha1 != fp2.sha1
    assert fp1.rows != fp2.rows
    # 同窗口重复读取必须同指纹
    assert fingerprint_frame(df1.copy()).sha1 == fp1.sha1


def test_code_version_is_read_only_and_recorded():
    ver = code_version()
    assert "commit" in ver and "package_version" in ver
    assert make_run_id("a", "b", ver) == make_run_id("a", "b", ver)


# ---------------------------------------------------------------------------
# 3. 参数扫描：边算边汇总 + 内存上限
# ---------------------------------------------------------------------------
def test_expand_grid_is_stable_and_complete():
    grid = {"fast": [5, 10], "slow": [30, 60], "stop_mult": [1.5, 2.0]}
    combos = expand_grid(grid)
    assert len(combos) == 8
    assert combos == expand_grid(grid)
    assert combos[0] == {"fast": 5, "slow": 30, "stop_mult": 1.5}


def test_sweep_summary_matches_single_run_and_respects_caps(tmp_path):
    feed = _feed()
    base = _cfg()
    grid = {"fast": [5, 10], "slow": [30]}
    combos = expand_grid(grid)

    # 先单独跑一条，作为数值对照
    solo_cfg = base.with_overrides(strategy_params=combos[0])
    solo = runner.execute(solo_cfg, feed)

    sink = str(tmp_path / "summaries.jsonl")
    report = run_sweep(feed, base, grid, limits=SweepLimits(
        max_summaries_in_memory=1, memory_budget_mb=0.02, top_k=1,
        summary_sink=sink))

    assert report["run_count"] == 2
    assert report["retained"] <= 1
    assert report["spooled"] >= 1
    assert len(report["top"]) == 1
    # 落盘摘要行数与溢出条数一致
    with open(sink, "r", encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    assert len(lines) == report["spooled"]

    # 保留/落盘的摘要必须与单跑数值一致
    merged = {s["combo_index"]: s for s in report["summaries"]}
    merged.update({s["combo_index"]: s for s in lines})
    assert merged[0]["kpi"]["num_fills"] == solo["metrics"]["num_fills"]
    assert merged[0]["result_hash"] == solo["result_hash"]
    assert merged[0]["trades_digest"] == solo["trades_digest"]
    # 全量聚合在溢出后依然准确
    assert report["aggregate"]["best"] is not None


def test_sweep_multi_symbol_and_detail_sink(tmp_path):
    feed = _feed()
    base = _cfg()
    grid = {"fast": [5, 10], "slow": [30]}
    detail = str(tmp_path / "details.jsonl")
    report = run_sweep(feed, base, grid, symbols=["rb.SHFE", "i.DCE"],
                       limits=SweepLimits(top_k=2, max_summaries_in_memory=100),
                       detail_sink=detail)
    assert report["run_count"] == 4
    assert len(report["symbols"]) == 2
    assert report["spooled"] == 0 and report["dropped"] == 0
    with open(detail, "r", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert len(rows) == 4
    assert all("trades" in r and "params_snapshot" in r for r in rows)
    assert all(r["run_id"] for r in rows)


def test_sweep_drops_when_no_sink(tmp_path):
    feed = _feed()
    report = run_sweep(feed, _cfg(), {"fast": [5, 10]}, limits=SweepLimits(
        max_summaries_in_memory=1, memory_budget_mb=0.02, top_k=0))
    assert report["run_count"] == 2
    assert report["retained"] == 1
    assert report["dropped"] == 1
    assert report["spooled"] == 0
    assert report["aggregate"]["best"] is not None


def test_sweep_covers_atr_and_lots_dimensions(tmp_path):
    """网格对任意策略参数生效（不止 fast/slow：atr_period / lots 也需可扫）。"""
    feed = _feed()
    grid = {"atr_period": [10, 14], "lots": [1, 2]}
    report = run_sweep(feed, _cfg(), grid, limits=SweepLimits(
        max_summaries_in_memory=100, top_k=1))
    assert report["run_count"] == 4
    seen = {(s["params"]["atr_period"], s["params"]["lots"])
            for s in report["summaries"]}
    assert seen == {(10, 1), (10, 2), (14, 1), (14, 2)}
    # 参数确实进入每条摘要（可追溯到具体组合）
    assert all(s["params"] for s in report["summaries"])


# ---------------------------------------------------------------------------
# 4. 落库 / 复跑 / 导出
# ---------------------------------------------------------------------------
def test_store_save_get_and_replay(tmp_path):
    feed = _feed()
    cfg = _cfg()
    result = runner.execute(cfg, feed)
    store = BacktestStore(str(tmp_path / "bt.db"))

    assert store.save_run(runner.record_from_result(result)) is not None
    rec = store.get_run(result["run_id"])
    assert rec is not None
    assert rec["params_hash"] == result["params_hash"]
    assert rec["data_fingerprint"] == result["data_fingerprint"]
    assert json.dumps(rec["metrics"], sort_keys=True, default=str) == \
           json.dumps(result["metrics"], sort_keys=True, default=str)
    assert rec["trace_status"] == "ok"

    # 幂等 upsert：同 run_id 再写一次只增加 attempts，不新增行
    assert store.save_run(runner.record_from_result(result)) is not None
    assert store.count_runs() == 1
    assert store.get_run(result["run_id"])["attempts"] == 2

    replay = runner.replay_run(store, result["run_id"], feed)
    assert replay["ok"] is True
    assert all(c["ok"] for c in replay["checks"])
    assert replay["result"]["result_hash"] == result["result_hash"]

    # 数据指纹不一致时必须判失败（不得假装通过）
    other = runner.execute(_cfg(start="2020-01-01", end="2020-12-01"), feed)
    store.save_run(runner.record_from_result(other))
    mismatch = runner.replay_run(store, other["run_id"],
                                 _feed_with_window(feed, START, END))
    assert mismatch["ok"] is False
    failed = {c["name"] for c in mismatch["checks"] if not c["ok"]}
    assert "data_fingerprint" in failed


def _feed_with_window(base_feed: SyntheticFeed, start: str, end: str):
    """构造一个「只返回给定窗口」的 feed，用于制造数据指纹不一致。"""
    class _WindowFeed:
        source_label = "test-window"

        def get_history(self, symbol, s, e, period="D", limit=0):
            return base_feed.get_history(symbol, start, end, period, limit)
    return _WindowFeed()


def test_export_result_and_stored_run(tmp_path):
    feed = _feed()
    result = runner.execute(_cfg(), feed)
    paths = export_mod.export_result(result, str(tmp_path), prefix="demo")
    for key in ("kpi", "trades", "equity", "json"):
        assert os.path.exists(paths[key]), f"缺少导出文件 {key}"

    with open(paths["kpi"], encoding="utf-8") as fh:
        kpi_text = fh.read()
    assert result["data_fingerprint"] in kpi_text
    assert "run_id" in kpi_text

    with open(paths["json"], encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["params_snapshot"]["data"]["symbol"] == SYMBOL
    assert payload["trace"]["data_fingerprint"] == result["data_fingerprint"]
    assert len(payload["trades"]) == len(result["trades"])

    store = BacktestStore(str(tmp_path / "bt.db"))
    store.save_run(runner.record_from_result(result))
    stored = export_mod.export_stored_run(store, result["run_id"], str(tmp_path))
    with open(stored["json"], encoding="utf-8") as fh:
        snap = json.load(fh)
    assert snap["params_snapshot"]["strategy"]["name"] == "trend_following"
    assert snap["data_fingerprint"] == result["data_fingerprint"]


# ---------------------------------------------------------------------------
# 5. 迁移：幂等 + 迁移前备份
# ---------------------------------------------------------------------------
def test_run_table_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dummy(id INTEGER)")
    conn.commit()
    conn.close()

    store = BacktestStore(path)
    backup_dir = tmp_path / "backups"
    assert backup_dir.is_dir(), "老库升级前必须生成备份"
    assert any(p.suffix == ".db" for p in backup_dir.iterdir())

    store.save_run(runner.record_from_result(runner.execute(_cfg(), _feed())))
    store.close()

    # 第二次打开：不重复备份、不清空数据
    store2 = BacktestStore(path)
    assert store2.count_runs() == 1
    assert len(list(backup_dir.iterdir())) == 1
    store2.close()


def test_service_config_entry_persists_and_replays(tmp_path):
    """服务层配置入口与 runner 共享同一路径，可直接落库并复跑。"""
    feed = _feed()
    cfg = _cfg()
    svc = BacktestService(Config(), feed)
    store = BacktestStore(str(tmp_path / "bt.db"))
    result = svc.run_backtest_with_config(cfg, persist=True, store=store)
    assert result["run_id"] == runner.execute(cfg, feed)["run_id"]
    replay = svc.replay(result["run_id"], store=store, feed=feed)
    assert replay["ok"] is True


def test_service_legacy_signature_still_works():
    """兼容性：原 run_backtest 返回键集合仍存在，且新增追溯字段。"""
    feed = _feed()
    svc = BacktestService(Config(), feed)
    res = svc.run_backtest(SYMBOL, START, END, "D", 60, generate_report=False)
    for key in ("metrics", "equity_curve", "trades", "report", "data_source",
                "is_synthetic", "roll_mode", "total_roll_cost"):
        assert key in res
    assert res["run_id"] and res["data_fingerprint"]
    direct = runner.execute(_cfg(), feed)
    assert json.dumps(res["metrics"], sort_keys=True, default=str) == \
           json.dumps(direct["metrics"], sort_keys=True, default=str)
    assert res["trades_digest"] == direct["trades_digest"]
