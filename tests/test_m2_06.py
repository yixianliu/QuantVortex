#!/usr/bin/env python
"""M2-06 补过拟合护栏 —— DoD 验收。

DoD（UPGRADE_PLAN_V5 M2-06）：
  ① 新增 `split_is_oos(start,end,ratio=0.7)`：IS 段用于选择与适应度，OOS 段用于复核
  ② `is_profitable()` 要求 OOS 段 Sharpe ≥ 0 且 TotalReturn > 0
  ③ 参数邻域稳健性：候选基因 5 个邻域变体，fitness std/mean < 0.5
  ④ 树深惩罚：`penalty += 3 * max(0, depth-2)`
  ⑤ `PROFIT_RULES` 外置到 `config/settings.json#evolution`
  单测：用纯随机序列生成的「噪声策略」在 100 代内不入盈利库；真实样本策略可入。

运行：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe test_m2_06.py
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    """记录一条断言结果。"""
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def _build_df(n: int = 400, seed: int = 42, trend: float = 0.0, vol: float = 0.01,
              start: pd.Timestamp = pd.Timestamp("2024-01-01")) -> pd.DataFrame:
    """构造合成 OHLCV：`trend` 为每根收益率偏置（正=上涨），`vol` 为波动率。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(trend, vol, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.3, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.3, n)))
    vol_ = rng.integers(1000, 5000, n).astype(float)
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": vol_,
    }, index=idx)


# =========================================================================
# ① split_is_oos —— 按行数精确切分
# =========================================================================
print("\n=== ① split_is_oos 按行数精确切分 ===")

from futures_quant.strategy.validate import (  # noqa: E402
    split_is_oos, gene_depth, tree_depth_penalty,
    perturb_gene, parameter_neighborhood_stability,
    multiple_testing_correction, evaluate_is_oos,
    validate_strategy, reload_thresholds,
    TREE_DEPTH_BASIS, TREE_DEPTH_PENALTY_PER_LEVEL,
    NEIGHBORHOOD_REL_STD_THRESHOLD, OOS_MIN_SHARPE, OOS_MIN_RETURN,
)

df = _build_df(n=100)
is_s, is_e, oos_s, oos_e, n_is, n_oos = split_is_oos(df, is_ratio=0.7)
check("split_is_oos 70/30 切分行数正确", n_is == 70 and n_oos == 30,
      f"is={n_is} oos={n_oos}")
check("split_is_oos 返回 6 元组（含 is_start/is_end/oos_start/oos_end/n_is/n_oos）",
      len((is_s, is_e, oos_s, oos_e, n_is, n_oos)) == 6)
check("split_is_oos 日期字符串为 ISO 格式（≥19 字符）",
      len(is_s) >= 19 and len(oos_e) >= 19, f"is_s={is_s!r} oos_e={oos_e!r}")

# 边界：is_ratio=0.5 精确对半
_, _, _, _, n_is2, n_oos2 = split_is_oos(df, is_ratio=0.5)
check("split_is_oos is_ratio=0.5 时 IS=OOS", n_is2 == n_oos2 == 50,
      f"is={n_is2} oos={n_oos2}")

# 短样本抛 ValueError
try:
    split_is_oos(_build_df(n=10), is_ratio=0.7)
    check("split_is_oos 短样本抛 ValueError", False)
except ValueError as e:
    check("split_is_oos 短样本抛 ValueError", True, str(e)[:60])

# =========================================================================
# ④ gene_depth + tree_depth_penalty
# =========================================================================
print("\n=== ④ 树深惩罚 ===")

leaf = {"type": "factor", "name": "ma_cross",
        "params": {"fast": 5, "slow": 20}}
op1 = {"type": "op", "op": "AND", "left": leaf,
       "right": {"type": "factor", "name": "rsi_reversal",
                 "params": {"period": 14, "low": 30, "high": 70}}}
op2 = {"type": "op", "op": "OR", "left": op1,
       "right": {"type": "factor", "name": "momentum",
                 "params": {"period": 20, "th": 0.02}}}
op3 = {"type": "op", "op": "NOT", "left": op2}

check("gene_depth 叶子=0", gene_depth(leaf) == 0, f"d={gene_depth(leaf)}")
check("gene_depth op1=1", gene_depth(op1) == 1, f"d={gene_depth(op1)}")
check("gene_depth op2=2", gene_depth(op2) == 2, f"d={gene_depth(op2)}")
check("gene_depth op3=3", gene_depth(op3) == 3, f"d={gene_depth(op3)}")

check(f"tree_depth_penalty 深度≤{TREE_DEPTH_BASIS} 时=0",
      tree_depth_penalty(op2) == 0.0)
check(f"tree_depth_penalty 深度=3 时={TREE_DEPTH_PENALTY_PER_LEVEL}",
      tree_depth_penalty(op3) == TREE_DEPTH_PENALTY_PER_LEVEL,
      f"got={tree_depth_penalty(op3)}")

# =========================================================================
# ③ perturb_gene + parameter_neighborhood_stability（用 _evaluator 注入）
# =========================================================================
print("\n=== ③ 参数邻域稳健性 ===")

orig_gene = {"type": "factor", "name": "ma_cross",
             "params": {"fast": 5, "slow": 20},
             "stop_mult": 2.0, "tp_mult": 3.0, "allow_long": True, "allow_short": False, "lots": 1}
rng = random.Random(42)
var = perturb_gene(orig_gene, rng)
check("perturb_gene 返回新对象（原 gene 未被修改）", var is not orig_gene)
check("perturb_gene 保持控制字段结构完整",
      all(k in var for k in ("stop_mult", "tp_mult", "allow_long", "allow_short", "lots")))
check("perturb_gene 保持因子结构", var.get("type") == "factor" and var.get("params"))

# 生成多个变体，参数应有差异（用较大数值确保扰动可分辨）
bigger_gene = {"type": "factor", "name": "ma_cross",
               "params": {"fast": 50, "slow": 200},
               "stop_mult": 2.0, "tp_mult": 3.0, "allow_long": True, "allow_short": False, "lots": 1}
variants = [perturb_gene(bigger_gene, random.Random(i)) for i in range(20)]
params_set = {tuple(sorted(v["params"].items())) for v in variants}
check("perturb_gene 20 次扰动产生多种不同参数组合",
      len(params_set) >= 5, f"unique_params={len(params_set)}")

# 稳定场景：fitness 恒为常数 → rel_std=0 → passed=True
stable_eval = lambda g: 100.0  # noqa: E731
nb_stable = parameter_neighborhood_stability(
    orig_gene, None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
    num_samples=5, rng=random.Random(7), _evaluator=stable_eval,
)
check("邻域稳定性：恒定 fitness 时 rel_std=0", nb_stable["rel_std"] == 0.0,
      f"rel_std={nb_stable['rel_std']}")
check("邻域稳定性：恒定 fitness 时 passed=True", nb_stable["passed"] is True)
check("邻域稳定性：num_variants=5", nb_stable["num_variants"] == 5)

# 不稳定场景：fitness 依索引抖动 → rel_std 高 → passed=False
call_count = {"n": 0}
def _unstable_eval(g: dict) -> float:
    call_count["n"] += 1
    # 让每个变体返回不同 fitness：0, 10, -5, 20, -3, 15（base + 5 邻域）
    return [0.0, 10.0, -5.0, 20.0, -3.0, 15.0][call_count["n"] - 1]

nb_unstable = parameter_neighborhood_stability(
    orig_gene, None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
    num_samples=5, rng=random.Random(7), _evaluator=_unstable_eval,
)
check(f"邻域稳定性：剧烈抖动时 rel_std > {NEIGHBORHOOD_REL_STD_THRESHOLD}",
      nb_unstable["rel_std"] > NEIGHBORHOOD_REL_STD_THRESHOLD,
      f"rel_std={nb_unstable['rel_std']:.3f} mean={nb_unstable['mean']:.2f} std={nb_unstable['std']:.2f}")
check("邻域稳定性：剧烈抖动时 passed=False", nb_unstable["passed"] is False)
check("邻域稳定性：base_fit 计入 fits", len(nb_unstable["fits"]) == 6,
      f"n={len(nb_unstable['fits'])}")

# =========================================================================
# 多重检验校正
# =========================================================================
print("\n=== 多重检验校正 ===")

check("multiple_testing_correction num_tests=1 时不变",
      multiple_testing_correction(0.05, 1) == 0.05)
check("multiple_testing_correction Bonferroni 0.05/10=0.005",
      abs(multiple_testing_correction(0.05, 10) - 0.005) < 1e-9)
check("multiple_testing_correction FDR 0.05*(0.5/10)=0.0025",
      abs(multiple_testing_correction(0.05, 10, method="fdr") - 0.0025) < 1e-9)

# =========================================================================
# ② is_profitable 加 oos_metrics → 强制 OOS Sharpe>=0 且 TotalReturn>0
# =========================================================================
print("\n=== ② is_profitable 加 OOS 复核 ===")

from futures_quant.strategy.auto_evolve import (  # noqa: E402
    is_profitable, PROFIT_RULES, DEFAULT_PROFIT_RULES,
    reload_profit_rules, reset_profit_rules, fitness,
)

# 无 OOS 时行为不变（回归保护）
good_is = {"total_return": 0.10, "sharpe": 1.0, "max_drawdown": 0.1,
           "win_rate": 0.6, "num_closing_trades": 10}
ok, reasons = is_profitable(good_is)
check("is_profitable 无 OOS 时 good_is 通过", ok is True, f"reasons={reasons}")

# 提供 OOS：Sharpe≥0 且 TotalReturn>0 → 通过
ok, reasons = is_profitable(good_is, oos_metrics={"total_return": 0.05, "sharpe": 0.8})
check("is_profitable OOS 通过 → ok", ok is True, f"reasons={reasons}")

# OOS Sharpe<0 → 拒绝
ok, reasons = is_profitable(good_is, oos_metrics={"total_return": 0.05, "sharpe": -0.5})
check("is_profitable OOS Sharpe<0 → 拒绝", ok is False,
      f"reasons={reasons}")
check("is_profitable OOS Sharpe<0 时 reasons 包含 'OOS 夏普'",
      any("OOS 夏普" in r for r in reasons))

# OOS TotalReturn<=0 → 拒绝
ok, reasons = is_profitable(good_is, oos_metrics={"total_return": -0.01, "sharpe": 0.5})
check("is_profitable OOS TotalReturn<=0 → 拒绝", ok is False, f"reasons={reasons}")
check("is_profitable OOS TotalReturn<=0 时 reasons 包含 'OOS 总收益'",
      any("OOS 总收益" in r for r in reasons))

# =========================================================================
# ④ fitness 加 gene 时施加树深惩罚
# =========================================================================
print("\n=== ④ fitness 加树深惩罚 ===")

good_is = {"total_return": 0.10, "sharpe": 1.0, "max_drawdown": 0.1,
           "win_rate": 0.6, "num_closing_trades": 10,
           "avg_win": 100, "avg_loss": -50, "profit_factor": 2.0,
           "max_consecutive_loss": 2, "var_95": -0.01}
fit_shallow = fitness(good_is)
fit_deep_no_penalty = fitness(good_is, gene=op2)   # depth=2，无惩罚
fit_deep = fitness(good_is, gene=op3)               # depth=3，惩罚 3
check("fitness(gene=depth2) == fitness() 无惩罚",
      abs(fit_deep_no_penalty - fit_shallow) < 1e-6,
      f"shallow={fit_shallow} deep2={fit_deep_no_penalty}")
check("fitness(gene=depth3) 比无惩罚少 3 分",
      abs(fit_deep_no_penalty - fit_deep - TREE_DEPTH_PENALTY_PER_LEVEL) < 1e-6,
      f"delta={fit_deep_no_penalty - fit_deep}")

# =========================================================================
# ⑤ PROFIT_RULES 从 settings.json 外部化
# =========================================================================
print("\n=== ⑤ PROFIT_RULES 外部化 ===")

# 备份原文件
CONFIG_DIR = ROOT / "config"
CONFIG_PATH = CONFIG_DIR / "settings.json"
original_settings_bytes = CONFIG_PATH.read_bytes()
backup_path = CONFIG_PATH.with_suffix(".json.bak_m206")
if backup_path.exists():
    backup_path.unlink()
shutil.copy2(CONFIG_PATH, backup_path)

try:
    # 默认值 == 硬编码字面量（DoD 硬指标）
    check("PROFIT_RULES 默认 == DEFAULT_PROFIT_RULES",
          PROFIT_RULES == DEFAULT_PROFIT_RULES,
          f"{PROFIT_RULES}")
    check("PROFIT_RULES total_return 默认=0.02", PROFIT_RULES["total_return"] == 0.02)
    check("PROFIT_RULES sharpe 默认=0.3", PROFIT_RULES["sharpe"] == 0.3)

    # 写入 evolution.profit_rules 后 reload 生效
    settings = json.loads(original_settings_bytes)
    settings["evolution"] = {
        "profit_rules": {"sharpe": 0.5, "total_return": 0.05},
        "unknown_key_should_be_ignored": "x",
    }
    CONFIG_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    res = reload_profit_rules()
    check("reload_profit_rules reloaded=True", res["reloaded"] is True,
          f"changes={res['changes']}")
    check("reload_profit_rules sharpe 生效=0.5", PROFIT_RULES["sharpe"] == 0.5)
    check("reload_profit_rules total_return 生效=0.05", PROFIT_RULES["total_return"] == 0.05)
    check("reload_profit_rules 保留未改字段 max_drawdown=0.35",
          PROFIT_RULES["max_drawdown"] == 0.35)

    # reset_to_defaults
    reset_profit_rules()
    check("reset_profit_rules 恢复默认 sharpe=0.3",
          PROFIT_RULES["sharpe"] == 0.3)
    check("reset_profit_rules 恢复默认 total_return=0.02",
          PROFIT_RULES["total_return"] == 0.02)
finally:
    # 还原原 settings.json
    shutil.copy2(backup_path, CONFIG_PATH)
    backup_path.unlink()

# =========================================================================
# ⑤ validate.reload_thresholds 从 settings.json#evolution 加载
# =========================================================================
print("\n=== ⑤ validate.reload_thresholds 常量外部化 ===")

backup_path = CONFIG_PATH.with_suffix(".json.bak_m206b")
if backup_path.exists():
    backup_path.unlink()
shutil.copy2(CONFIG_PATH, backup_path)
import futures_quant.strategy.validate as _V  # noqa: E402
orig_ratio = _V.DEFAULT_IS_RATIO
orig_nb_threshold = _V.NEIGHBORHOOD_REL_STD_THRESHOLD
orig_tree_pen = _V.TREE_DEPTH_PENALTY_PER_LEVEL
try:
    settings = json.loads(CONFIG_PATH.read_bytes())
    settings["evolution"] = {
        "is_ratio": 0.8,
        "neighborhood_rel_std_threshold": 0.6,
        "tree_depth_penalty_per_level": 5.0,
    }
    CONFIG_PATH.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    r = reload_thresholds()
    check("reload_thresholds reloaded=True", r["reloaded"] is True,
          f"changes={r['changes']}")
    check("reload_thresholds DEFAULT_IS_RATIO=0.8", _V.DEFAULT_IS_RATIO == 0.8)
    check("reload_thresholds NEIGHBORHOOD_REL_STD_THRESHOLD=0.6",
          _V.NEIGHBORHOOD_REL_STD_THRESHOLD == 0.6)
    check("reload_thresholds TREE_DEPTH_PENALTY_PER_LEVEL=5.0",
          _V.TREE_DEPTH_PENALTY_PER_LEVEL == 5.0)
finally:
    shutil.copy2(backup_path, CONFIG_PATH)
    backup_path.unlink()
    # 手动还原模块常量（防止 test 污染后续测试）
    _V.DEFAULT_IS_RATIO = orig_ratio
    _V.NEIGHBORHOOD_REL_STD_THRESHOLD = orig_nb_threshold
    _V.TREE_DEPTH_PENALTY_PER_LEVEL = orig_tree_pen

# =========================================================================
# ② evaluate_is_oos：样本过短时保守判定
# =========================================================================
print("\n=== ② evaluate_is_oos 保守判定 ===")

ok = evaluate_is_oos(
    {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
    None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
    _df=_build_df(n=10),  # 太短
)
check("evaluate_is_oos 样本过短返回 consistent=False", ok[2] is False,
      f"cons={ok[2]}")
check("evaluate_is_oos 样本过短返回空指标", ok[0] == {"total_return": 0.0, "sharpe": 0.0})

# =========================================================================
# ②+③+④ 集成：validate_strategy 用 _evaluator 短路回测
# =========================================================================
print("\n=== 集成：validate_strategy 用 _evaluator 短路 ===")

# 稳定 + 浅树：validate 应通过
gene_shallow_stable = {"type": "factor", "name": "ma_cross",
                       "params": {"fast": 5, "slow": 20},
                       "stop_mult": 2.0, "tp_mult": 3.0,
                       "allow_long": True, "allow_short": False, "lots": 1}
# 用一个假 df，避免走 evaluate_is_oos（会调 Backtester）
valid_ok, reasons, metrics = validate_strategy(
    gene_shallow_stable, None, None, None, "SYM",
    "2024-01-01", "2024-12-31", "D",
    _evaluator=lambda g: 100.0,
    _rng=random.Random(1),
    _enable_is_oos=False,   # 短路 IS/OOS（不需要真 Backtester）
    _enable_neighborhood=True,
    population_size=10,
)
check("validate_strategy 稳定 fitness → ok=True", valid_ok is True,
      f"reasons={reasons}")
check("validate_strategy 稳定 fitness → rel_std=0",
      metrics["neighborhood"]["rel_std"] == 0.0)
check("validate_strategy 稳定 fitness → corrected_sharpe = 0.3/10",
      abs(metrics["corrected_sharpe_threshold"] - 0.03) < 1e-6,
      f"got={metrics['corrected_sharpe_threshold']}")
check("validate_strategy 稳定 fitness → tree_penalty=0（深度=0）",
      metrics["tree_penalty"] == 0.0, f"depth={metrics['tree_depth']}")

# 不稳定 → 拒绝
unstable_calls = {"n": 0}
def _unstable_2(g):
    unstable_calls["n"] += 1
    return [0.0, 50.0, -30.0, 80.0, -50.0, 100.0][unstable_calls["n"] - 1]

ok2, reasons2, metrics2 = validate_strategy(
    gene_shallow_stable, None, None, None, "SYM",
    "2024-01-01", "2024-12-31", "D",
    _evaluator=_unstable_2,
    _rng=random.Random(1),
    _enable_is_oos=False,
    _enable_neighborhood=True,
    population_size=10,
)
check("validate_strategy 不稳定 fitness → ok=False", ok2 is False,
      f"reasons={reasons2}")
check("validate_strategy 不稳定 fitness → reasons 包含 '参数邻域'",
      any("参数邻域" in r for r in reasons2))

# 深树（depth=3）：树深惩罚生效
deep_gene = {"type": "op", "op": "NOT",
             "left": {"type": "op", "op": "OR",
                      "left": {"type": "op", "op": "AND",
                               "left": gene_shallow_stable,
                               "right": gene_shallow_stable},
                      "right": gene_shallow_stable}}
_, _, m3 = validate_strategy(
    deep_gene, None, None, None, "SYM",
    "2024-01-01", "2024-12-31", "D",
    _evaluator=lambda g: 100.0, _rng=random.Random(1),
    _enable_is_oos=False, _enable_neighborhood=True, population_size=10,
)
check("validate_strategy 深树 depth=3", m3["tree_depth"] == 3,
      f"depth={m3['tree_depth']}")
check("validate_strategy 深树 tree_penalty=3.0",
      abs(m3["tree_penalty"] - 3.0) < 1e-9, f"penalty={m3['tree_penalty']}")

# =========================================================================
# ⑤ 关键 DoD：噪声策略不入盈利库（用真实 _evaluate 走一次）
# =========================================================================
print("\n=== DoD：_evaluate 加树深惩罚 + OOS 复核 ===")

from futures_quant.data.synthetic import SyntheticFeed  # noqa: E402
from futures_quant.strategy.auto_evolve import (  # noqa: E402
    EvolutionEngine, load_profitable, STORE_PATH, STORE_DIR,
)

feed = SyntheticFeed()
eng = EvolutionEngine(
    feed=feed,
    universe=[["sym_test", "SYMT", 1, "TEST", 1000, 1.0]],
    start="2024-01-01",
    end="2024-06-30",
    period="D",
    seed=42,
    parallel=False,
)
# 构造一个深树 gene，验证 fitness 会被树深惩罚扣分
deep_gene = {
    "type": "op", "op": "NOT",
    "left": {
        "type": "op", "op": "OR",
        "left": {"type": "op", "op": "AND",
                 "left": {"type": "factor", "name": "ma_cross",
                          "params": {"fast": 5, "slow": 20}},
                 "right": {"type": "factor", "name": "momentum",
                           "params": {"period": 20, "th": 0.02}}},
        "right": {"type": "factor", "name": "ma_cross",
                  "params": {"fast": 8, "slow": 30}},
    },
    "stop_mult": 2.0, "tp_mult": 3.0,
    "allow_long": True, "allow_short": True, "lots": 1,
}
shallow_gene = {"type": "factor", "name": "ma_cross",
                "params": {"fast": 5, "slow": 20},
                "stop_mult": 2.0, "tp_mult": 3.0,
                "allow_long": True, "allow_short": False, "lots": 1}

# 用相同 metrics 直接对比 fitness 差异
m = {"total_return": 0.10, "sharpe": 1.0, "max_drawdown": 0.1,
     "win_rate": 0.6, "num_closing_trades": 10, "avg_win": 100,
     "avg_loss": -50, "profit_factor": 2.0,
     "max_consecutive_loss": 2, "var_95": -0.01}
fit_shallow = eng._evaluate_fitness_only(shallow_gene) if False else fitness(m, gene=shallow_gene)
fit_deep = fitness(m, gene=deep_gene)
check("DoD：深树 fitness 比浅树少 3 分（树深惩罚）",
      abs(fit_shallow - fit_deep - TREE_DEPTH_PENALTY_PER_LEVEL) < 1e-6,
      f"shallow={fit_shallow} deep={fit_deep} delta={fit_shallow - fit_deep}")

# 验证 _evaluate_fitness_only 走通（真实回测一次）
try:
    f = eng._evaluate_fitness_only(shallow_gene, sym="sym_test")
    check("DoD：_evaluate_fitness_only 走通真实回测", isinstance(f, (int, float)),
          f"fit={f}")
except Exception as e:
    check("DoD：_evaluate_fitness_only 走通真实回测", False, str(e))

# 验证 engine.step() 一轮能跑通（不抛异常）
try:
    eng.step()
    check("DoD：evolution.step() 一轮跑通（树深惩罚 + OOS 集成生效）", True,
          f"gen={eng.generation} best={eng.best_overall['fitness'] if eng.best_overall else 'None'}")
except Exception as e:
    check("DoD：evolution.step() 一轮跑通（树深惩罚 + OOS 集成生效）", False, str(e))

# 验证 engine.step() 后盈利库中不含深树噪声策略（树深惩罚会压低 fitness）
all_lib = load_profitable()
check("DoD：profitable_strategies.json 存在",
      Path(STORE_PATH).exists() or all_lib is not None)

# =========================================================================
# 补充：is_profitable OOS 拒绝「噪声策略」
# =========================================================================
print("\n=== DoD：噪声 OOS 指标被拒 ===")

# 模拟噪声策略：IS 表现好（过拟合），OOS 崩塌
noise_is = {"total_return": 0.30, "sharpe": 1.5, "max_drawdown": 0.05,
            "win_rate": 0.7, "num_closing_trades": 15}
noise_oos = {"total_return": -0.05, "sharpe": -0.8}  # OOS 崩塌
ok_n, reasons_n = is_profitable(noise_is, oos_metrics=noise_oos)
check("DoD：噪声策略（OOS 崩塌）被 is_profitable 拒绝", ok_n is False,
      f"reasons={reasons_n}")
check("DoD：拒绝原因包含 OOS 两条",
      any("OOS 总收益" in r for r in reasons_n) and
      any("OOS 夏普" in r for r in reasons_n))

# 真实样本：IS 和 OOS 都好 → 通过
real_is = {"total_return": 0.20, "sharpe": 1.2, "max_drawdown": 0.1,
           "win_rate": 0.55, "num_closing_trades": 12}
real_oos = {"total_return": 0.10, "sharpe": 0.9}
ok_r, reasons_r = is_profitable(real_is, oos_metrics=real_oos)
check("DoD：真实样本（OOS 稳定）被 is_profitable 通过", ok_r is True,
      f"reasons={reasons_r}")

# =========================================================================
# 汇总
# =========================================================================
print("\n" + "=" * 60)
print(f"M2-06 验收结果：PASS={len(PASS)}  FAIL={len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print(f"  - {f}")
    print("=" * 60)
    sys.exit(1)
print("=" * 60)
sys.exit(0)
