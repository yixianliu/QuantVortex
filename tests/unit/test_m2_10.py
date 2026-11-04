"""M2-10 evolver 三轨变异修复 + distill 基因识别 + export_rules —— pytest 形态。

由散落脚本 ``tests/test_m2_10.py``（模块级 ``print``+``assert``，0 个 ``def test_*``）
机械改写：三段顶层断言收敛成若干 pytest 函数，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- ``export_rules`` 默认写 ``RULES_PATH``；pytest 版改传 ``tmp_path`` 临时路径，
  既保留「rules.json 落盘 + 可读文本」断言，又避免污染仓库 ``data/`` 目录。
"""
from __future__ import annotations

import os

import pytest

from futures_quant.strategy.evolver import EvolutionController, Genome
from futures_quant.strategy import distill


# ---------- fixture：包装 _mutate_track 统计调用次数（按轨） ----------
def _make_ctrl():
    def fitness_fn(genome):
        return 0.0

    return EvolutionController(
        fitness_fn=fitness_fn,
        strategy_generator=lambda rng: {"type": "factor", "name": "ma_cross",
                                        "params": {"fast": 5, "slow": 20}},
        seed=42,
    ), calls_probe()


class _CallsProbe:
    def __init__(self):
        self.calls = {"strategy": 0, "model": 0, "risk": 0}


def calls_probe():
    return _CallsProbe()


def test_mutate_three_tracks_once_each():
    """evolver.mutate：三轨各恰好变异一次（修复前为各 3 次）。"""
    ctrl, probe = _make_ctrl()
    _orig = ctrl._mutate_track

    def counting(track, g, rng):
        probe.calls[track] = probe.calls.get(track, 0) + 1
        return _orig(track, g, rng)

    ctrl._mutate_track = counting

    genome = Genome(
        strategy={"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
        model={"model": "lstm"},
        risk={"stop_mult": 2.0},
    )
    ctrl.mutate(genome)

    assert probe.calls["strategy"] == 1, f"strategy 应变异 1 次，实际 {probe.calls['strategy']}"
    assert probe.calls["model"] == 1, f"model 应变异 1 次，实际 {probe.calls['model']}"
    assert probe.calls["risk"] == 1, f"risk 应变异 1 次，实际 {probe.calls['risk']}"


def test_mutate_single_track_does_not_affect_others():
    """仅指定 model 轨时，不应波及其它轨。"""
    ctrl, probe = _make_ctrl()
    _orig = ctrl._mutate_track

    def counting(track, g, rng):
        probe.calls[track] = probe.calls.get(track, 0) + 1
        return _orig(track, g, rng)

    ctrl._mutate_track = counting

    genome = Genome(
        strategy={"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
        model={"model": "lstm"},
        risk={"stop_mult": 2.0},
    )
    ctrl.mutate(genome, tracks=("model",))
    assert probe.calls.get("strategy", 0) == 0, "仅指定 model 时不应变异 strategy"
    assert probe.calls.get("risk", 0) == 0, "仅指定 model 时不应变异 risk"
    assert probe.calls.get("model", 0) == 1, f"model 应变异 1 次，实际 {probe.calls.get('model')}"


def test_distill_flat_gene():
    """distill 识别扁平基因（entry + 嵌套 params），控制字段不进 params。"""
    flat_gene = {
        "entry": "ma_cross",
        "params": {"fast": 5, "slow": 20},
        "stop_mult": 2.0,
        "tp_mult": 3.0,
        "allow_long": True,
        "allow_short": False,
        "lots": 2,
        "signature": "abc123",
        "fitness": 12.5,
    }
    rule = distill.distill(flat_gene)
    assert rule["factor"] == "ma_cross", f"扁平基因因子名应识别为 ma_cross，实际 {rule['factor']!r}"
    assert rule["factor_label"] == "双均线交叉", f"标签应为双均线交叉，实际 {rule['factor_label']!r}"
    assert rule["risk"]["stop_mult"] == 2.0, f"stop_mult 读取错误：{rule['risk']['stop_mult']}"
    assert rule["risk"]["tp_mult"] == 3.0, f"tp_mult 读取错误：{rule['risk']['tp_mult']}"
    assert rule["risk"]["lots"] == 2, f"lots 读取错误：{rule['risk']['lots']}"
    assert rule["risk"]["allow_short"] is False, "allow_short 读取错误"
    # params 应来自嵌套字典（fast/slow），而非把整个嵌套 dict 塞进去
    assert rule["params"] == {"fast": 5, "slow": 20}, f"params 应为 {{fast:5,slow:20}}，实际 {rule['params']}"
    # 控制字段不应混进 params
    assert "stop_mult" not in rule["params"], "控制字段不应出现在 params 中"
    assert "entry" not in rule["params"], "entry 不应出现在 params 中"


def test_distill_flat_gene_params_inner_fallback():
    """控制字段位于 params 内时也能读到（回退路径）。"""
    g2 = {"entry": "momentum", "params": {"period": 10, "stop_mult": 1.5, "lots": 3}}
    r2 = distill.distill(g2)
    assert r2["risk"]["stop_mult"] == 1.5, f"params 内 stop_mult 未读到：{r2['risk']['stop_mult']}"
    assert r2["risk"]["lots"] == 3, f"params 内 lots 未读到：{r2['risk']['lots']}"


def test_distill_tree_gene():
    """树形基因仍正常：收集两个叶子因子。"""
    tree_gene = {
        "type": "op", "op": "AND",
        "left": {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
        "right": {"type": "factor", "name": "rsi_reversal", "params": {"period": 14}},
        "stop_mult": 2.0,
    }
    r3 = distill.distill(tree_gene)
    assert "ma_cross" in (r3["factor"] or "") and "rsi_reversal" in (r3["factor"] or ""), \
        f"树形基因应收集两个叶子因子，实际 {r3['factor']}"


def test_export_rules_writes_json_and_readable_text(tmp_path):
    """export_rules 落盘 rules.json + format_rules_text 生成可读文本（临时路径，不污染仓库）。"""
    flat_gene = {
        "entry": "ma_cross",
        "params": {"fast": 5, "slow": 20},
        "stop_mult": 2.0,
        "tp_mult": 3.0,
        "allow_long": True,
        "allow_short": False,
        "lots": 2,
        "signature": "abc123",
        "fitness": 12.5,
    }
    tree_gene = {
        "type": "op", "op": "AND",
        "left": {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
        "right": {"type": "factor", "name": "rsi_reversal", "params": {"period": 14}},
        "stop_mult": 2.0,
    }
    entries = [
        {"gene": flat_gene, "fitness": 12.5, "metrics": {"sharpe": 1.2}},
        {"gene": {**flat_gene, "entry": "momentum", "params": {"period": 10}, "fitness": 9.0},
         "fitness": 9.0, "metrics": {"sharpe": 1.0}},
        {"gene": tree_gene, "fitness": 8.0, "metrics": {"sharpe": 0.9}},
    ]
    out_path = str(tmp_path / "rules.json")
    payload = distill.export_rules(entries, k=3, path=out_path)
    assert payload["n_rules"] == 3, f"应有 3 条规则，实际 {payload['n_rules']}"
    assert os.path.exists(payload["path"]), f"rules.json 未生成：{payload['path']}"
    text = distill.format_rules_text(payload)
    assert "【规则 1】" in text and "【规则 3】" in text, "可读文本应含 3 条规则编号"
    assert "双均线交叉" in text, "可读文本应含中文因子标签"
