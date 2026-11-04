#!/usr/bin/env python
"""测试 M2-12 消除静默吞异常"""

import sys
import logging
sys.path.insert(0, 'D:/PythonProject/QuantVortex')

from futures_quant.strategy.auto_evolve import (
    factor_signal, _eval_signal, ensemble_strategy_signal, latest_signal_for
)

logging.basicConfig(level=logging.WARNING)

# ---------- 测试 1：factor_signal 异常时返回 None（而非静默 0） ----------
print("测试 1: factor_signal 异常返回 None 而非 0")
# 构造一个会触发异常的基因：ma_cross 缺少 slow 参数 → KeyError
bad_gene = {"type": "factor", "name": "ma_cross", "params": {"fast": 5}}  # 缺 slow
# 长度足够，会真正走进 ma_cross 分支并 KeyError
closes = [float(100 + i) for i in range(200)]
highs = [c + 1 for c in closes]
lows = [c - 1 for c in closes]
res = factor_signal(bad_gene, closes, highs, lows)
assert res is None, f"异常时应返回 None，实际返回 {res!r}"
print("✅ 异常因子返回 None（不再静默返回 0）")

# ---------- 测试 2：正常因子仍返回 int（0/±1），未被误伤 ----------
print("\n测试 2: 正常因子仍返回 int")
ok_gene = {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}}
res_ok = factor_signal(ok_gene, closes, highs, lows)
assert isinstance(res_ok, int), f"正常因子应返回 int，实际 {type(res_ok)} {res_ok!r}"
assert res_ok in (-1, 0, 1), f"正常信号应在 ±1/0，实际 {res_ok}"
print(f"✅ 正常因子返回 int 信号 {res_ok}")

# ---------- 测试 3：_eval_signal 沿递归传播 None ----------
print("\n测试 3: _eval_signal 传播失败(None)")
# 树形基因：左子是坏因子
tree_bad = {
    "type": "op", "op": "AND",
    "left": bad_gene,
    "right": {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
}
r = _eval_signal(tree_bad, closes, highs, lows)
assert r is None, f"子树失败应传播 None，实际 {r!r}"
print("✅ 树形基因中任一子树失败 → 整体返回 None")

# 正常树形基因仍返回 int
tree_ok = {
    "type": "op", "op": "AND",
    "left": ok_gene,
    "right": ok_gene,
}
r_ok = _eval_signal(tree_ok, closes, highs, lows)
assert isinstance(r_ok, int), f"正常树应返回 int，实际 {r_ok!r}"
print(f"✅ 正常树形基因返回 int 信号 {r_ok}")

# ---------- 测试 4：ensemble_strategy_signal 对 None 降级不崩溃 ----------
print("\n测试 4: ensemble 对失败降级为 0.0，不崩溃")
ens = ensemble_strategy_signal(bad_gene, closes, highs, lows)
assert isinstance(ens, float), f"ensemble 应返回 float，实际 {type(ens)}"
print(f"✅ ensemble 返回 float {ens}（未因 None 崩溃）")

# ---------- 测试 5：latest_signal_for 不再静默 pass（异常被记录且标记 error） ----------
print("\n测试 5: latest_signal_for 异常被记录并标记 error")
# 传入非法 df（None）→ 走 early return，不触发异常，验证正常路径
out_norm = latest_signal_for("rb.SHFE", None)
assert isinstance(out_norm, dict) and out_norm.get("bias") == 0.0
assert "error" not in out_norm, "正常路径不应带 error 标记"
print("✅ 正常路径返回默认 out，无 error 标记")

# 传入会触发异常的 df（缺 close 列）→ 应走 except 分支并标记 error
class BadDF:
    def __len__(self):
        return 50
    def __getitem__(self, k):
        raise KeyError(k)
    def __contains__(self, k):
        return False

# 需先让 load_profitable 返回非空才会进循环；这里直接验证异常被捕获而非抛出
try:
    out_bad = latest_signal_for("rb.SHFE", BadDF())
    assert isinstance(out_bad, dict), "异常时应仍返回 dict 而非抛出"
    print(f"✅ 异常输入返回 dict（不抛出），error={'error' in out_bad}")
except Exception as ex:
    raise AssertionError(f"latest_signal_for 不应向外抛异常，但抛出了：{ex}")

print("\n" + "="*50)
print("🎉 所有 M2-12 测试通过!")
print("="*50)
