"""过拟合防护模块（M2-06 · 2026-10-01 实装）：真·IS/OOS 切分 + 参数邻域稳健性 + 树深惩罚 + 多重检验校正。

对 M3 域的 AI 层与 M2 域的进化层形成闭环：
- IS 段（默认 70%）用于选择与适应度；
- OOS 段（默认 30%）独立复核：OOS Sharpe >= 0 且 TotalReturn > 0 才视为「样本外一致」；
- 参数邻域稳健性：对候选基因做 N 个参数扰动，`rel_std = std / |mean| < 0.5` 才视为稳定；
- 树深惩罚：超过 2 层每多一层加 3 分（防止 GA 用深树硬拟合）；
- PROFIT_RULES 可从 `config/settings.json#evolution` 外部化重载。

原文件的 `i_o_o_split / evaluate_is_oos / parameter_neighborhood_stability` 全部为 stub
（返回原始日期 / 相同指标 / 恒定 0.5），本轮全部实装。

保留 `i_o_o_split` 作为兼容别名，行为已改为**取数据行数切分**后映射回日期。
"""

from __future__ import annotations

import copy
import json
import logging
import random
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常量（DoD 硬指标 + 可调参数）
# ---------------------------------------------------------------------------

# 树深惩罚：超过 2 层每多一层加 TREE_DEPTH_PENALTY_PER_LEVEL 分
TREE_DEPTH_BASIS = 2
TREE_DEPTH_PENALTY_PER_LEVEL = 3.0

# 参数邻域
NEIGHBORHOOD_PERTURB_RATIO = 0.1           # 每个数字参数扰动比例 ±10%
NEIGHBORHOOD_MIN_SAMPLES = 5               # spec ③ 要求 5 个邻域变体
NEIGHBORHOOD_MAX_SAMPLES = 8
NEIGHBORHOOD_REL_STD_THRESHOLD = 0.5       # spec ③ 要求 std/mean < 0.5
_PERTURB_NODE_PROB = 0.4                   # 每个叶子节点 40% 概率被扰动
_PERTURB_CTRL_PROB = 0.3                   # control 字段 30% 概率被扰动

# IS/OOS
DEFAULT_IS_RATIO = 0.7
MIN_TOTAL_BARS = 30                        # 全样本 <30 根直接拒绝
MIN_IS_BARS = 20                           # IS 段 <20 根视为数据不足
MIN_OOS_BARS = 10                          # OOS 段 <10 根视为数据不足
OOS_MIN_SHARPE = 0.0                       # spec ② 要求 OOS Sharpe >= 0
OOS_MIN_RETURN = 0.0                       # spec ② 要求 OOS TotalReturn > 0

# settings.json 路径（相对本文件定位，便于打包后定位）
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "settings.json"


# ---------------------------------------------------------------------------
# settings.json 外部化
# ---------------------------------------------------------------------------

def reload_thresholds() -> Dict[str, Any]:
    """从 `config/settings.json#evolution` 外部化覆盖常量。

    识别的键：
      - `is_ratio` / `neighborhood_samples` / `neighborhood_rel_std_threshold`
      - `tree_depth_basis` / `tree_depth_penalty_per_level`
      - `oos_min_sharpe` / `oos_min_return`

    返回：`{"reloaded": bool, "changes": {key: value}}`
    """
    changes: Dict[str, Any] = {}
    if not _CONFIG_PATH.exists():
        return {"reloaded": False, "changes": changes}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 evolution 设置失败：%s", e)
        return {"reloaded": False, "changes": changes}

    evolution = data.get("evolution") or {}
    if not isinstance(evolution, dict):
        return {"reloaded": False, "changes": changes}

    def _apply(name, target, caster):
        if name in evolution:
            try:
                v = caster(evolution[name])
                globals()[target] = v
                changes[target] = v
            except Exception as e:  # noqa: BLE001
                logger.warning("evolution.%s=%r 无效，忽略（%s）", name, evolution[name], e)

    _apply("is_ratio", "DEFAULT_IS_RATIO", float)
    _apply("neighborhood_samples", "NEIGHBORHOOD_MIN_SAMPLES", int)
    _apply("neighborhood_rel_std_threshold", "NEIGHBORHOOD_REL_STD_THRESHOLD", float)
    _apply("tree_depth_basis", "TREE_DEPTH_BASIS", int)
    _apply("tree_depth_penalty_per_level", "TREE_DEPTH_PENALTY_PER_LEVEL", float)
    _apply("oos_min_sharpe", "OOS_MIN_SHARPE", float)
    _apply("oos_min_return", "OOS_MIN_RETURN", float)
    return {"reloaded": True, "changes": changes}


# ---------------------------------------------------------------------------
# IS/OOS 切分
# ---------------------------------------------------------------------------

def _to_str(dt: Any) -> str:
    """datetime / Timestamp → `YYYY-MM-DDTHH:MM:SS` 字符串（Backtester.run 接受的最短形式）。"""
    s = str(dt)
    return s[:19] if len(s) >= 19 else s


def split_is_oos(df, is_ratio: float = DEFAULT_IS_RATIO
                 ) -> Tuple[str, str, str, str, int, int]:
    """按**行数**切 df 为 IS/OOS 段（70/30），返回 `(is_start, is_end, oos_start, oos_end, n_is, n_oos)`。

    说明：不依赖字符串日期解析，直接按 df.index 顺序切；比 spec 里 `i_o_o_split` 只回传
    原始日期的做法更精确。
    """
    if df is None:
        raise ValueError("df 不能为 None")
    if len(df) < MIN_TOTAL_BARS:
        raise ValueError(f"数据太短（{len(df)} < {MIN_TOTAL_BARS}），无法 IS/OOS 切分")
    is_ratio = min(max(is_ratio, 0.3), 0.9)
    n = len(df)
    split_idx = max(1, min(n - 1, int(round(n * is_ratio))))
    is_df = df.iloc[:split_idx]
    oos_df = df.iloc[split_idx:]
    if len(is_df) < MIN_IS_BARS or len(oos_df) < MIN_OOS_BARS:
        raise ValueError(
            f"IS/OOS 分段过短 is={len(is_df)} oos={len(oos_df)}"
            f"（要求 ≥{MIN_IS_BARS}/≥{MIN_OOS_BARS}）"
        )
    return (
        _to_str(is_df.index[0]),
        _to_str(is_df.index[-1]),
        _to_str(oos_df.index[0]),
        _to_str(oos_df.index[-1]),
        len(is_df),
        len(oos_df),
    )


def i_o_o_split(start_date: str, end_date: str, is_ratio: float = DEFAULT_IS_RATIO
                ) -> Tuple[str, str, str, str]:
    """兼容别名：按 start/end 日期字符串近似切（不推荐生产使用，仅老代码回退）。

    新代码请用 :func:`split_is_oos`（真实取 df）。这里保留是为 M2-06 之前的调用方兼容。
    """
    try:
        import pandas as pd
        s = pd.Timestamp(start_date)
        e = pd.Timestamp(end_date)
    except Exception:  # noqa: BLE001
        # 非标准日期字符串：退化为「原样返回 + 原样返回」旧行为，避免生产报错
        return start_date, end_date, start_date, end_date
    n = int((e - s).total_seconds())
    if n <= 0:
        return start_date, end_date, start_date, end_date
    cut = s + pd.Timedelta(seconds=n * is_ratio)
    return str(s), str(cut), str(cut), str(e)


# ---------------------------------------------------------------------------
# 双段回测
# ---------------------------------------------------------------------------

def evaluate_is_oos(
    gene: Dict[str, Any],
    config: Any,
    feed: Any,
    contract: Any,
    symbol: str,
    start: str,
    end: str,
    period: str,
    warmup: int = 60,
    is_ratio: float = DEFAULT_IS_RATIO,
    _df: Optional[Any] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    """真·IS/OOS 切分 + 双段回测。

    Returns:
        `(is_metrics, oos_metrics, is_consistent)`：
          - `is_consistent=True` 当且仅当 `oos.total_return > OOS_MIN_RETURN` 且
            `oos.sharpe >= OOS_MIN_SHARPE`（spec ②）。

    样本过短（<MIN_TOTAL_BARS 或切分后 IS/OOS 段太短）时返回
    `({"total_return":0, "sharpe":0}, {"total_return":0, "sharpe":0}, False)` 保守判定。
    """
    from ..backtest.backtester import Backtester
    from .auto_evolve import GeneStrategy

    df = _df if _df is not None else feed.get_history(symbol, start, end, period)
    empty = {"total_return": 0.0, "sharpe": 0.0}
    if df is None or len(df) < MIN_TOTAL_BARS:
        logger.warning("样本过短 %s，跳过 IS/OOS（保守判定为不一致）",
                       0 if df is None else len(df))
        return dict(empty), dict(empty), False
    try:
        is_start, is_end, oos_start, oos_end, _, _ = split_is_oos(df, is_ratio)
    except ValueError as e:
        logger.warning("IS/OOS 切分失败：%s", e)
        return dict(empty), dict(empty), False

    def _run(s: str, e: str) -> Dict[str, Any]:
        bt = Backtester(config, feed)
        bt.add_contract(contract)
        bt.add_strategy(GeneStrategy(symbol, gene))
        return bt.run(symbol, s, e, period, warmup=warmup)["metrics"]

    try:
        is_m = _run(is_start, is_end)
    except Exception as e:  # noqa: BLE001
        logger.warning("IS 段回测失败：%s", e)
        return dict(empty), dict(empty), False
    try:
        oos_m = _run(oos_start, oos_end)
    except Exception as e:  # noqa: BLE001
        logger.warning("OOS 段回测失败：%s", e)
        return is_m, dict(empty), False

    oos_tr = float(oos_m.get("total_return") or 0)
    oos_sharpe = float(oos_m.get("sharpe") or 0)
    consistent = (oos_tr > OOS_MIN_RETURN) and (oos_sharpe >= OOS_MIN_SHARPE)
    return is_m, oos_m, consistent


# ---------------------------------------------------------------------------
# 树深
# ---------------------------------------------------------------------------

def gene_depth(gene: Dict[str, Any]) -> int:
    """基因树深度（叶子=0，根为最大深度）。"""
    def _d(node: Any) -> int:
        if not isinstance(node, dict):
            return 0
        if node.get("type") == "factor":
            return 0
        ld = _d(node.get("left"))
        rd = _d(node.get("right"))
        return 1 + max(ld, rd)
    return _d(gene) if isinstance(gene, dict) else 0


def tree_depth_penalty(gene: Dict[str, Any]) -> float:
    """超过 TREE_DEPTH_BASIS 后每多一层加 TREE_DEPTH_PENALTY_PER_LEVEL。"""
    d = gene_depth(gene)
    return float(TREE_DEPTH_PENALTY_PER_LEVEL * max(0, d - TREE_DEPTH_BASIS))


# ---------------------------------------------------------------------------
# 参数邻域扰动
# ---------------------------------------------------------------------------

def _perturb_node(node: Any, rng: random.Random, ratio: float) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "factor":
        for k, val in list(node.get("params", {}).items()):
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                if val == 0:
                    continue
                if rng.random() >= _PERTURB_NODE_PROB:
                    continue
                new = val * (1 + rng.uniform(-ratio, ratio))
                node["params"][k] = (
                    int(round(new)) if isinstance(val, int) else round(float(new), 3)
                )
        return
    _perturb_node(node.get("left"), rng, ratio)
    _perturb_node(node.get("right"), rng, ratio)


def perturb_gene(gene: Dict[str, Any], rng: Optional[random.Random] = None,
                 ratio: float = NEIGHBORHOOD_PERTURB_RATIO) -> Dict[str, Any]:
    """生成一个邻域基因变体（深拷贝 + 参数扰动 + control 字段微扰）。"""
    v = copy.deepcopy(gene)
    if rng is None:
        rng = random.Random()
    _perturb_node(v, rng, ratio)
    # control 字段微扰
    if isinstance(v.get("stop_mult"), (int, float)) and rng.random() < _PERTURB_CTRL_PROB:
        v["stop_mult"] = round(float(v["stop_mult"]) * (1 + rng.uniform(-ratio, ratio)), 1)
    if isinstance(v.get("tp_mult"), (int, float)) and rng.random() < _PERTURB_CTRL_PROB \
            and float(v["tp_mult"]) > 0:
        v["tp_mult"] = round(float(v["tp_mult"]) * (1 + rng.uniform(-ratio, ratio)), 1)
    return v


def parameter_neighborhood_stability(
    gene: Dict[str, Any],
    config: Any,
    feed: Any,
    contract: Any,
    symbol: str,
    start: str,
    end: str,
    period: str,
    warmup: int = 60,
    num_samples: int = NEIGHBORHOOD_MIN_SAMPLES,
    rng: Optional[random.Random] = None,
    _evaluator: Optional[Callable[[dict], float]] = None,
) -> Dict[str, Any]:
    """参数邻域稳健性：N 个变体的 fitness 分布。

    Args:
      _evaluator: 可选回调 `gene -> fitness`；生产由 EvolutionEngine 注入（可走 M2-07 缓存），
        避免重复回测。生产未注入时回退到独立回测（性能慢但正确）。

    Returns:
      ``{"base_fit", "fits", "mean", "std", "rel_std", "stability", "num_variants", "passed"}``
      `passed = rel_std < NEIGHBORHOOD_REL_STD_THRESHOLD`。
    """
    from .auto_evolve import GeneStrategy, fitness as _fitness
    from ..backtest.backtester import Backtester

    if rng is None:
        rng = random.Random()
    num_samples = max(2, min(num_samples, NEIGHBORHOOD_MAX_SAMPLES))

    def _eval(g: dict) -> float:
        if _evaluator is not None:
            try:
                return float(_evaluator(g))
            except Exception as e:  # noqa: BLE001
                logger.warning("邻域变体评估失败：%s", e)
                return 0.0
        try:
            bt = Backtester(config, feed)
            bt.add_contract(contract)
            bt.add_strategy(GeneStrategy(symbol, g))
            return float(_fitness(bt.run(symbol, start, end, period, warmup=warmup)["metrics"]))
        except Exception as e:  # noqa: BLE001
            logger.warning("邻域变体回测失败：%s", e)
            return 0.0

    base_fit = _eval(gene)
    fits = [base_fit]
    for _ in range(num_samples):
        v = perturb_gene(gene, rng)
        fits.append(_eval(v))

    arr = np.asarray(fits, dtype=float)
    mean = float(arr.mean()) if arr.size else 0.0
    std = float(arr.std()) if arr.size else 0.0
    if abs(mean) > 1e-9:
        rel_std = std / abs(mean)
    else:
        rel_std = 0.0 if std < 1e-9 else 1.0
    stability = max(0.0, 1.0 - rel_std)
    return {
        "base_fit": base_fit,
        "fits": [float(x) for x in fits],
        "mean": mean,
        "std": std,
        "rel_std": rel_std,
        "stability": stability,
        "num_variants": len(fits) - 1,
        "passed": bool(rel_std < NEIGHBORHOOD_REL_STD_THRESHOLD),
    }


# ---------------------------------------------------------------------------
# 多重检验校正
# ---------------------------------------------------------------------------

def multiple_testing_correction(base_threshold: float, num_tests: int,
                                method: str = "bonferroni") -> float:
    """多重检验校正：Bonferroni / FDR 近似。"""
    if num_tests <= 1:
        return float(base_threshold)
    if method == "bonferroni":
        return float(base_threshold) / num_tests
    if method == "fdr":
        return float(base_threshold) * (0.5 / num_tests)
    return float(base_threshold) / num_tests  # fallback


# ---------------------------------------------------------------------------
# 综合验证
# ---------------------------------------------------------------------------

def validate_strategy(
    gene: Dict[str, Any],
    config: Any,
    feed: Any,
    contract: Any,
    symbol: str,
    start: str,
    end: str,
    period: str,
    warmup: int = 60,
    generation_num: int = 0,
    population_size: int = 0,
    is_ratio: float = DEFAULT_IS_RATIO,
    num_variants: int = NEIGHBORHOOD_MIN_SAMPLES,
    _df: Optional[Any] = None,
    _evaluator: Optional[Callable[[dict], float]] = None,
    _rng: Optional[random.Random] = None,
    _enable_is_oos: bool = True,
    _enable_neighborhood: bool = True,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """综合验证：IS/OOS + 参数邻域 + 树深惩罚 + 多重检验校正。

    Args:
      _enable_is_oos / _enable_neighborhood: 允许测试或数据不足时按位关闭某一环节。
      _evaluator: 邻域评估回调（生产建议传入复用 M2-07 缓存）。

    Returns:
      `(is_valid, reasons, metrics)`。
    """
    reasons: List[str] = []
    metrics: Dict[str, Any] = {}

    # 1) IS/OOS 切分验证
    if _enable_is_oos:
        is_m, oos_m, consistent = evaluate_is_oos(
            gene, config, feed, contract, symbol, start, end, period,
            warmup, is_ratio, _df=_df,
        )
        metrics["is_metrics"] = is_m
        metrics["oos_metrics"] = oos_m
        metrics["is_oos_consistent"] = consistent
        if not consistent:
            oos_tr = float(oos_m.get("total_return") or 0)
            oos_sh = float(oos_m.get("sharpe") or 0)
            reasons.append(
                f"OOS 未通过（total_return={oos_tr:.4f} sharpe={oos_sh:.3f}；"
                f"要求 tr>{OOS_MIN_RETURN} sharpe>={OOS_MIN_SHARPE}）"
            )
    else:
        metrics["is_oos_consistent"] = True
        metrics["is_metrics"] = {}
        metrics["oos_metrics"] = {}

    # 2) 参数邻域稳健性
    if _enable_neighborhood:
        nb = parameter_neighborhood_stability(
            gene, config, feed, contract, symbol, start, end, period,
            warmup, num_samples=num_variants, rng=_rng, _evaluator=_evaluator,
        )
        metrics["neighborhood"] = nb
        if not nb["passed"]:
            reasons.append(
                f"参数邻域不稳定（rel_std={nb['rel_std']:.3f} > {NEIGHBORHOOD_REL_STD_THRESHOLD}）"
            )
    else:
        metrics["neighborhood"] = {"passed": True, "note": "skipped"}

    # 3) 树深惩罚（仅提示，实际扣分由 fitness 施加）
    depth = gene_depth(gene)
    tree_pen = tree_depth_penalty(gene)
    metrics["tree_depth"] = depth
    metrics["tree_penalty"] = tree_pen

    # 4) 多重检验校正提示
    num_tests = population_size if population_size > 0 else 1
    from .auto_evolve import PROFIT_RULES
    corrected_sharpe = multiple_testing_correction(
        PROFIT_RULES.get("sharpe", 0.3), num_tests, method="bonferroni"
    )
    metrics["corrected_sharpe_threshold"] = corrected_sharpe

    return len(reasons) == 0, reasons, metrics
