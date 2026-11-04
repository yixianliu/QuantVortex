"""M2-06 补过拟合护栏（pytest 改写版）。

DoD（UPGRADE_PLAN_V5 M2-06）：
  ① ``split_is_oos``：IS 段用于选择与适应度，OOS 段用于复核；
  ② ``is_profitable()`` 要求 OOS 段 Sharpe ≥ 0 且 TotalReturn > 0；
  ③ 参数邻域稳健性：候选基因 5 个邻域变体，fitness std/mean < 0.5；
  ④ 树深惩罚：``penalty += TREE_DEPTH_PENALTY_PER_LEVEL * max(0, depth-2)``；
  ⑤ ``PROFIT_RULES`` / 阈值外置到 ``config/settings.json#evolution``。

与散落脚本的差别（行为契约不变，仅改形态 + 消除真实文件副作用）：
  · 原文直接备份/改写真实 ``config/settings.json`` 并跑 ``EvolutionEngine.step()`` 写
    真实 ``profitable_strategies.json``。本改写通过 monkeypatch 把配置读取重定向到临时
    文件、把进化库落盘指向 tmp，**全程零真实文件副作用**（门禁可重复、不污染工作树）。
  · 断言按常量动态比较（如树深惩罚 == ``TREE_DEPTH_PENALTY_PER_LEVEL``），不写死 3.0，
    避免阈值真被配置改后产生假红。

散落脚本原文：``tests/test_m2_06.py``（约 70 个 check）。
"""
import json
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import futures_quant.strategy.auto_evolve as AE
import futures_quant.strategy.validate as V
from futures_quant.data.synthetic import SyntheticFeed
from futures_quant.strategy.auto_evolve import (
    EvolutionEngine, fitness, is_profitable, load_profitable,
    DEFAULT_PROFIT_RULES, PROFIT_RULES, reload_profit_rules, reset_profit_rules,
)
from futures_quant.strategy.validate import (
    evaluate_is_oos, gene_depth, multiple_testing_correction,
    parameter_neighborhood_stability, perturb_gene, split_is_oos,
    tree_depth_penalty, validate_strategy,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path("D:/PythonProject/QuantVortex").resolve()


def _make_df(n=400, seed=42, trend=0.0, vol=0.01, start=pd.Timestamp("2024-01-01")):
    """构造合成 OHLCV：trend 为每根收益率偏置，vol 为波动率。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(trend, vol, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.3, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.3, n)))
    vol_ = rng.integers(1000, 5000, n).astype(float)
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol_},
        index=idx,
    )


# -------------------------------------------------------------------------
# 配置 / 进化库落盘：重定向到临时文件，零真实文件副作用
# -------------------------------------------------------------------------
@pytest.fixture
def profit_rules_tmp_config(monkeypatch, tmp_path):
    """把 reload_profit_rules 的配置文件读取重定向到临时 settings.json。"""
    real_cfg = Path(AE.__file__).resolve().parent.parent.parent / "config" / "settings.json"
    tmp = tmp_path / "settings.json"
    data = json.loads(real_cfg.read_text(encoding="utf-8"))
    data["evolution"] = {
        "profit_rules": {"sharpe": 0.5, "total_return": 0.05},
        "unknown_key_should_be_ignored": "x",
    }
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    real_open = open

    def _fake_open(p, *a, **k):
        if str(p) == str(real_cfg):
            return real_open(tmp, *a, **k)
        return real_open(p, *a, **k)

    monkeypatch.setattr(AE, "open", _fake_open, raising=False)
    yield tmp
    reset_profit_rules()  # 还原模块级 PROFIT_RULES


@pytest.fixture
def validate_tmp_config(monkeypatch, tmp_path):
    """把 validate.reload_thresholds 的 _CONFIG_PATH 重定向到临时 settings.json。"""
    real_cfg = Path(V.__file__).resolve().parent.parent.parent / "config" / "settings.json"
    tmp = tmp_path / "settings.json"
    data = json.loads(real_cfg.read_text(encoding="utf-8"))
    data["evolution"] = {
        "is_ratio": 0.8,
        "neighborhood_rel_std_threshold": 0.6,
        "tree_depth_penalty_per_level": 5.0,
    }
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(V, "_CONFIG_PATH", tmp)
    orig = (V.DEFAULT_IS_RATIO, V.NEIGHBORHOOD_REL_STD_THRESHOLD,
            V.TREE_DEPTH_PENALTY_PER_LEVEL)
    yield tmp
    V.DEFAULT_IS_RATIO, V.NEIGHBORHOOD_REL_STD_THRESHOLD, V.TREE_DEPTH_PENALTY_PER_LEVEL = orig


@pytest.fixture
def evo_store(monkeypatch, tmp_path):
    """把进化盈利库落盘重定向到临时文件。"""
    store = tmp_path / "profitable_strategies.json"
    monkeypatch.setattr(AE, "STORE_PATH", str(store))
    monkeypatch.setattr(AE, "STORE_DIR", str(tmp_path))
    yield store


# =========================================================================
# ① split_is_oos
# =========================================================================
def test_split_is_oos_rows():
    df = _make_df(n=100)
    is_s, is_e, oos_s, oos_e, n_is, n_oos = split_is_oos(df, is_ratio=0.7)
    assert len((is_s, is_e, oos_s, oos_e, n_is, n_oos)) == 6
    assert n_is == 70 and n_oos == 30, f"is={n_is} oos={n_oos}"
    assert len(is_s) >= 19 and len(oos_e) >= 19, f"is_s={is_s!r} oos_e={oos_e!r}"

    _, _, _, _, n_i2, n_o2 = split_is_oos(df, is_ratio=0.5)
    assert n_i2 == n_o2 == 50, f"is={n_i2} oos={n_o2}"

    with pytest.raises(ValueError):
        split_is_oos(_make_df(n=10), is_ratio=0.7)


# =========================================================================
# ④ gene_depth + tree_depth_penalty
# =========================================================================
def test_gene_depth_and_tree_penalty():
    leaf = {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}}
    op1 = {"type": "op", "op": "AND", "left": leaf,
           "right": {"type": "factor", "name": "rsi_reversal",
                     "params": {"period": 14, "low": 30, "high": 70}}}
    op2 = {"type": "op", "op": "OR", "left": op1,
           "right": {"type": "factor", "name": "momentum", "params": {"period": 20, "th": 0.02}}}
    op3 = {"type": "op", "op": "NOT", "left": op2}

    assert gene_depth(leaf) == 0
    assert gene_depth(op1) == 1
    assert gene_depth(op2) == 2
    assert gene_depth(op3) == 3

    assert tree_depth_penalty(op2) == 0.0
    assert tree_depth_penalty(op3) == V.TREE_DEPTH_PENALTY_PER_LEVEL, \
        f"got={tree_depth_penalty(op3)}"


# =========================================================================
# ③ perturb_gene + parameter_neighborhood_stability
# =========================================================================
def test_perturb_gene():
    orig = {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20},
            "stop_mult": 2.0, "tp_mult": 3.0, "allow_long": True,
            "allow_short": False, "lots": 1}
    var = perturb_gene(orig, random.Random(42))
    assert var is not orig
    assert all(k in var for k in ("stop_mult", "tp_mult", "allow_long", "allow_short", "lots"))
    assert var.get("type") == "factor" and var.get("params")

    bigger = {"type": "factor", "name": "ma_cross", "params": {"fast": 50, "slow": 200},
              "stop_mult": 2.0, "tp_mult": 3.0, "allow_long": True,
              "allow_short": False, "lots": 1}
    variants = [perturb_gene(bigger, random.Random(i)) for i in range(20)]
    params_set = {tuple(sorted(v["params"].items())) for v in variants}
    assert len(params_set) >= 5, f"unique_params={len(params_set)}"


def test_parameter_neighborhood_stability():
    orig = {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20},
            "stop_mult": 2.0, "tp_mult": 3.0, "allow_long": True,
            "allow_short": False, "lots": 1}

    nb_stable = parameter_neighborhood_stability(
        orig, None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
        num_samples=5, rng=random.Random(7), _evaluator=lambda g: 100.0,
    )
    assert nb_stable["rel_std"] == 0.0
    assert nb_stable["passed"] is True
    assert nb_stable["num_variants"] == 5

    cc = {"n": 0}

    def _unstable(g):
        cc["n"] += 1
        return [0.0, 10.0, -5.0, 20.0, -3.0, 15.0][cc["n"] - 1]

    nb_u = parameter_neighborhood_stability(
        orig, None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
        num_samples=5, rng=random.Random(7), _evaluator=_unstable,
    )
    assert nb_u["rel_std"] > V.NEIGHBORHOOD_REL_STD_THRESHOLD, f"rel_std={nb_u['rel_std']:.3f}"
    assert nb_u["passed"] is False
    assert len(nb_u["fits"]) == 6, f"n={len(nb_u['fits'])}"


def test_multiple_testing_correction():
    assert multiple_testing_correction(0.05, 1) == 0.05
    assert abs(multiple_testing_correction(0.05, 10) - 0.005) < 1e-9
    assert abs(multiple_testing_correction(0.05, 10, method="fdr") - 0.0025) < 1e-9


# =========================================================================
# ② is_profitable 的 OOS 复核
# =========================================================================
def test_is_profitable_oos():
    good_is = {"total_return": 0.10, "sharpe": 1.0, "max_drawdown": 0.1,
               "win_rate": 0.6, "num_closing_trades": 10}
    assert is_profitable(good_is)[0] is True

    ok, _ = is_profitable(good_is, oos_metrics={"total_return": 0.05, "sharpe": 0.8})
    assert ok is True

    ok, reasons = is_profitable(good_is, oos_metrics={"total_return": 0.05, "sharpe": -0.5})
    assert ok is False
    assert any("OOS 夏普" in r for r in reasons)

    ok, reasons = is_profitable(good_is, oos_metrics={"total_return": -0.01, "sharpe": 0.5})
    assert ok is False
    assert any("OOS 总收益" in r for r in reasons)


# =========================================================================
# ④ fitness 加 gene 时施加树深惩罚
# =========================================================================
def test_fitness_tree_penalty():
    metrics = {"total_return": 0.10, "sharpe": 1.0, "max_drawdown": 0.1,
               "win_rate": 0.6, "num_closing_trades": 10, "avg_win": 100,
               "avg_loss": -50, "profit_factor": 2.0,
               "max_consecutive_loss": 2, "var_95": -0.01}
    leaf = {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}}
    op2 = {"type": "op", "op": "OR",
           "left": {"type": "op", "op": "AND", "left": leaf,
                    "right": {"type": "factor", "name": "rsi_reversal",
                              "params": {"period": 14, "low": 30, "high": 70}}},
           "right": {"type": "factor", "name": "momentum", "params": {"period": 20, "th": 0.02}}}
    op3 = {"type": "op", "op": "NOT", "left": op2}

    fit_shallow = fitness(metrics)
    fit_deep2 = fitness(metrics, gene=op2)   # depth=2，无惩罚
    fit_deep3 = fitness(metrics, gene=op3)   # depth=3，惩罚
    assert abs(fit_deep2 - fit_shallow) < 1e-6
    assert abs(fit_deep2 - fit_deep3 - V.TREE_DEPTH_PENALTY_PER_LEVEL) < 1e-6, \
        f"delta={fit_deep2 - fit_deep3}"


# =========================================================================
# ⑤ PROFIT_RULES 外部化（配置读取重定向到临时文件，零真实文件副作用）
# =========================================================================
def test_profit_rules_externalization(profit_rules_tmp_config):
    """PROFIT_RULES 默认等于 DEFAULT；reload 从 settings.json#evolution 生效；reset 还原。"""
    assert PROFIT_RULES == DEFAULT_PROFIT_RULES
    assert PROFIT_RULES["total_return"] == 0.02
    assert PROFIT_RULES["sharpe"] == 0.3

    res = reload_profit_rules()
    assert res["reloaded"] is True, f"changes={res.get('changes')}"
    assert PROFIT_RULES["sharpe"] == 0.5
    assert PROFIT_RULES["total_return"] == 0.05
    assert PROFIT_RULES["max_drawdown"] == 0.35  # 未改字段保留

    reset_profit_rules()
    assert PROFIT_RULES["sharpe"] == 0.3
    assert PROFIT_RULES["total_return"] == 0.02


def test_validate_reload_thresholds_externalization(validate_tmp_config):
    """validate.reload_thresholds 从 _CONFIG_PATH 加载 IS_RATIO / 邻域 / 树深惩罚。"""
    res = V.reload_thresholds()
    assert res["reloaded"] is True, f"changes={res.get('changes')}"
    assert V.DEFAULT_IS_RATIO == 0.8
    assert V.NEIGHBORHOOD_REL_STD_THRESHOLD == 0.6
    assert V.TREE_DEPTH_PENALTY_PER_LEVEL == 5.0


# =========================================================================
# ② evaluate_is_oos：样本过短时保守判定
# =========================================================================
def test_evaluate_is_oos_short_sample():
    ok2 = evaluate_is_oos(
        {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20}},
        None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
        _df=_make_df(n=10),
    )
    assert ok2[2] is False, f"consistent={ok2[2]}"
    assert ok2[0] == {"total_return": 0.0, "sharpe": 0.0}


# =========================================================================
# ②+③+④ 集成：validate_strategy 用 _evaluator 短路回测
# =========================================================================
def test_validate_strategy_integration():
    gene = {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20},
            "stop_mult": 2.0, "tp_mult": 3.0, "allow_long": True,
            "allow_short": False, "lots": 1}

    valid_ok, reasons, metrics = validate_strategy(
        gene, None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
        _evaluator=lambda g: 100.0, _rng=random.Random(1),
        _enable_is_oos=False, _enable_neighborhood=True, population_size=10,
    )
    assert valid_ok is True, f"reasons={reasons}"
    assert metrics["neighborhood"]["rel_std"] == 0.0
    assert abs(metrics["corrected_sharpe_threshold"] - 0.03) < 1e-6, \
        f"got={metrics['corrected_sharpe_threshold']}"
    assert metrics["tree_penalty"] == 0.0, f"depth={metrics['tree_depth']}"

    uc = {"n": 0}

    def _unstable(g):
        uc["n"] += 1
        return [0.0, 50.0, -30.0, 80.0, -50.0, 100.0][uc["n"] - 1]

    ok2, reasons2, _ = validate_strategy(
        gene, None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
        _evaluator=_unstable, _rng=random.Random(1),
        _enable_is_oos=False, _enable_neighborhood=True, population_size=10,
    )
    assert ok2 is False
    assert any("参数邻域" in r for r in reasons2)

    deep_gene = {"type": "op", "op": "NOT",
                 "left": {"type": "op", "op": "OR",
                          "left": {"type": "op", "op": "AND",
                                   "left": gene, "right": gene},
                          "right": gene}}
    _, _, m3 = validate_strategy(
        deep_gene, None, None, None, "SYM", "2024-01-01", "2024-12-31", "D",
        _evaluator=lambda g: 100.0, _rng=random.Random(1),
        _enable_is_oos=False, _enable_neighborhood=True, population_size=10,
    )
    assert m3["tree_depth"] == 3, f"depth={m3['tree_depth']}"
    assert abs(m3["tree_penalty"] - V.TREE_DEPTH_PENALTY_PER_LEVEL) < 1e-9, \
        f"penalty={m3['tree_penalty']}"


# =========================================================================
# ⑤ 关键 DoD：噪声策略被拒（IS 过拟合 / OOS 崩塌）；真实样本通过
# =========================================================================
def test_is_profitable_noise_rejection():
    noise_is = {"total_return": 0.30, "sharpe": 1.5, "max_drawdown": 0.05,
                "win_rate": 0.7, "num_closing_trades": 15}
    noise_oos = {"total_return": -0.05, "sharpe": -0.8}
    ok_n, reasons_n = is_profitable(noise_is, oos_metrics=noise_oos)
    assert ok_n is False, f"reasons={reasons_n}"
    assert any("OOS 总收益" in r for r in reasons_n)
    assert any("OOS 夏普" in r for r in reasons_n)

    real_is = {"total_return": 0.20, "sharpe": 1.2, "max_drawdown": 0.1,
               "win_rate": 0.55, "num_closing_trades": 12}
    real_oos = {"total_return": 0.10, "sharpe": 0.9}
    ok_r, reasons_r = is_profitable(real_is, oos_metrics=real_oos)
    assert ok_r is True, f"reasons={reasons_r}"


# =========================================================================
# ⑤ DoD：EvolutionEngine 真实回测 + step 跑通（进化库落盘重定向到 tmp）
# =========================================================================
def test_evolution_engine_integration(evo_store):
    shallow = {"type": "factor", "name": "ma_cross", "params": {"fast": 5, "slow": 20},
               "stop_mult": 2.0, "tp_mult": 3.0, "allow_long": True,
               "allow_short": False, "lots": 1}
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
    m = {"total_return": 0.10, "sharpe": 1.0, "max_drawdown": 0.1,
         "win_rate": 0.6, "num_closing_trades": 10, "avg_win": 100,
         "avg_loss": -50, "profit_factor": 2.0,
         "max_consecutive_loss": 2, "var_95": -0.01}
    fit_shallow = fitness(m, gene=shallow)
    fit_deep = fitness(m, gene=deep_gene)
    assert abs(fit_shallow - fit_deep - V.TREE_DEPTH_PENALTY_PER_LEVEL) < 1e-6, \
        f"shallow={fit_shallow} deep={fit_deep} delta={fit_shallow - fit_deep}"

    feed = SyntheticFeed()
    eng = EvolutionEngine(
        feed=feed, universe=[["sym_test", "SYMT", 1, "TEST", 1000, 1.0]],
        start="2024-01-01", end="2024-06-30", period="D", seed=42, parallel=False,
    )
    f = eng._evaluate_fitness_only(shallow, sym="sym_test")
    assert isinstance(f, (int, float)), f"fit={f}"

    eng.step()  # 真实回测一轮，树深惩罚 + OOS 集成应跑通
    all_lib = load_profitable()
    assert all_lib is None or isinstance(all_lib, (list, dict))
