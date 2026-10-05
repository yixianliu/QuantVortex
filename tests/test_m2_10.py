#!/usr/bin/env python
"""测试 M2-10：① evolver 三轨重复变异修复 ② distill 扁平基因/params 读取修复"""

import sys
import random
sys.path.insert(0, 'D:/PythonProject/QuantVortex')

from futures_quant.strategy.evolver import EvolutionController, Genome
from futures_quant.strategy import distill

# ============================================================
# ① evolver.mutate：三轨应各变异一次（而非 9 次）
# ============================================================
print("测试 ①: evolver.mutate 三轨各变异一次")

# 统计 _mutate_track 被调用的次数（按轨）
calls = {"strategy": 0, "model": 0, "risk": 0}

def fitness_fn(genome):
    return 0.0

ctrl = EvolutionController(
    fitness_fn=fitness_fn,
    strategy_generator=lambda rng: {"type": "factor", "name": "ma_cross",
                                    "params": {"fast": 5, "slow": 20}},
    seed=42,
)
# 包装 _mutate_track 统计调用
_orig = ctrl._mutate_track
def counting(track, g, rng):
    calls[track] = calls.get(track, 0) + 1
    return _orig(track, g, rng)
ctrl._mutate_track = counting

genome = Genome(
    strategy={"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
    model={"model": "lstm"},
    risk={"stop_mult": 2.0},
)
ctrl.mutate(genome)

# 修复前：for t in tracks(3次) × 每轮三轨全变异 → 各 3 次
# 修复后：各恰好 1 次
assert calls["strategy"] == 1, f"strategy 应变异 1 次，实际 {calls['strategy']}"
assert calls["model"] == 1, f"model 应变异 1 次，实际 {calls['model']}"
assert calls["risk"] == 1, f"risk 应变异 1 次，实际 {calls['risk']}"
print(f"✅ 三轨各变异一次（strategy={calls['strategy']}, model={calls['model']}, risk={calls['risk']}）")

# 单轨时不应波及其它轨
calls.clear()
ctrl.mutate(genome, tracks=("model",))
assert calls.get("strategy", 0) == 0, "仅指定 model 时不应变异 strategy"
assert calls.get("risk", 0) == 0, "仅指定 model 时不应变异 risk"
assert calls.get("model", 0) == 1, f"model 应变异 1 次，实际 {calls.get('model')}"
print("✅ 单轨变异不波及其它轨")

# ============================================================
# ② distill：扁平基因（entry + 嵌套 params）应正确识别
# ============================================================
print("\n测试 ②: distill 识别扁平基因 entry / 嵌套 params")

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
print(f"✅ 扁平基因 → 因子={rule['factor']} 标签={rule['factor_label']} params={rule['params']}")

# 控制字段位于 params 内时也能读到（回退路径）
g2 = {"entry": "momentum", "params": {"period": 10, "stop_mult": 1.5, "lots": 3}}
r2 = distill.distill(g2)
assert r2["risk"]["stop_mult"] == 1.5, f"params 内 stop_mult 未读到：{r2['risk']['stop_mult']}"
assert r2["risk"]["lots"] == 3, f"params 内 lots 未读到：{r2['risk']['lots']}"
print("✅ 控制字段位于 params 内时也能正确读取（回退）")

# 树形基因仍正常
tree_gene = {
    "type": "op", "op": "AND",
    "left": {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
    "right": {"type": "factor", "name": "rsi_reversal", "params": {"period": 14}},
    "stop_mult": 2.0,
}
r3 = distill.distill(tree_gene)
assert "ma_cross" in (r3["factor"] or "") and "rsi_reversal" in (r3["factor"] or ""), \
    f"树形基因应收集两个叶子因子，实际 {r3['factor']}"
print(f"✅ 树形基因仍正常 → 因子={r3['factor']}")

# ============================================================
# ③ export_rules + format_rules_text（rules.json 落盘与可读文本）
# ============================================================
print("\n测试 ③: export_rules 落盘 + format_rules_text 可读文本")
entries = [
    {"gene": flat_gene, "fitness": 12.5, "metrics": {"sharpe": 1.2}},
    {"gene": {**flat_gene, "entry": "momentum", "params": {"period": 10}, "fitness": 9.0},
     "fitness": 9.0, "metrics": {"sharpe": 1.0}},
    {"gene": tree_gene, "fitness": 8.0, "metrics": {"sharpe": 0.9}},
]
payload = distill.export_rules(entries, k=3)
assert payload["n_rules"] == 3, f"应有 3 条规则，实际 {payload['n_rules']}"
import os
assert os.path.exists(payload["path"]), f"rules.json 未生成：{payload['path']}"
text = distill.format_rules_text(payload)
assert "【规则 1】" in text and "【规则 3】" in text, "可读文本应含 3 条规则编号"
assert "双均线交叉" in text, "可读文本应含中文因子标签"
print(f"✅ rules.json 已生成（{payload['n_rules']} 条）：{payload['path']}")
print("\n----- 可读文本预览 -----")
print(text[:400])
print("------------------------")

print("\n" + "="*50)
print("🎉 所有 M2-10 核心测试通过!")
print("="*50)
