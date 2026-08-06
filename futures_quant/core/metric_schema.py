"""回测 / 预测 两板块统一指标规范（联动分析基石）。

目标：让「回测中心」与「AI预测」两个板块使用**完全一致**的指标键名、单位
与展示格式，确保数据可无缝对接、联动分析时数字不会出现口径偏差。

- 收益类（total_return / annual_return）：小数 → 百分比（如 0.053 → "5.3%"）
- 比率类（sharpe / profit_factor / calmar）：浮点 → 两位小数
- 风险类（max_drawdown / win_rate）：小数 → 百分比
- 各字段标注 higher_is_better，供 UI 自动着色（红涨绿跌 / 优劣配色统一）
"""
from __future__ import annotations

from typing import Any, Optional

# 规范字段：key -> (中文标签, 类型, 越高越好, 是否百分比)
# kind: "pct" 表示底层为小数、展示为百分比；"ratio" 表示浮点比率。
METRIC_FIELDS = {
    "total_return":      ("总收益率",   "pct",   True,  True),
    "annual_return":     ("年化收益",   "pct",   True,  True),
    "sharpe":            ("夏普比率",   "ratio", True,  False),
    "max_drawdown":      ("最大回撤",   "pct",   False, True),
    "win_rate":          ("胜率",       "pct",   True,  True),
    "profit_factor":     ("盈亏比",     "ratio", True,  False),
    "calmar":            ("卡玛比率",   "ratio", True,  False),
    "num_closing_trades":("平仓笔数",   "int",   True,  False),
}

# 中文标签快捷映射（供 UI 直接取用）
METRIC_LABEL = {k: v[0] for k, v in METRIC_FIELDS.items()}


def format_metric(key: str, value: Any) -> str:
    """按规范格式化单个指标；未知字段原样返回。"""
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    spec = METRIC_FIELDS.get(key)
    if spec is None:
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)
    kind = spec[1]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "int":
        return f"{int(round(v))}"
    return f"{v:.2f}"


def normalize_backtest_metrics(m: dict) -> dict:
    """将回测原始指标（小数口径）规整为统一结构：保留原始值 + 增加展示串。"""
    out: dict = {}
    if not m:
        return out
    for key, spec in METRIC_FIELDS.items():
        if key in m and m[key] is not None:
            out[key] = m[key]
            out[f"{key}__fmt"] = format_metric(key, m[key])
            out[f"{key}__good"] = spec[2]
    return out


def backtest_linkage_for(symbol: str) -> dict:
    """为「AI预测」板块提供回测联动摘要：与预测 res 同构的指标字段。

    返回结构（直接可被预测研判页渲染为「回测联动」卡片）：
        {
          "has_backtest": bool,
          "strategy_count": int,       # 该品种已验证盈利策略数
          "best": {规范化指标...},      # 最优策略的指标（与 METRIC_FIELDS 一致）
          "direction_bias": float,     # 加权方向（-1..1，来自 latest_signal_for）
          "best_desc": str,            # 最优策略中文描述
          "best_fitness": float,
          "best_gene": dict,           # 最优策略基因（供预测页反向回测透传）
        }
    """
    from ..strategy.auto_evolve import load_profitable, latest_signal_for

    out = {
        "has_backtest": False,
        "strategy_count": 0,
        "best": {},
        "direction_bias": 0.0,
        "best_desc": "",
        "best_fitness": None,
        "best_gene": None,
    }
    try:
        entries = [e for e in load_profitable() if e.get("symbol") == symbol]
        if not entries:
            return out
        out["has_backtest"] = True
        out["strategy_count"] = len(entries)
        # 按适应度取最优策略
        best = max(entries, key=lambda x: float(x.get("fitness") or -1e9))
        m = normalize_backtest_metrics(best.get("metrics") or {})
        out["best"] = m
        out["best_desc"] = best.get("desc", "")
        out["best_fitness"] = best.get("fitness")
        out["best_gene"] = best.get("gene")
        # 方向偏置（与预测融合口径一致）
        try:
            sig = latest_signal_for(symbol, None)
            out["direction_bias"] = float(sig.get("bias", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            out["direction_bias"] = 0.0
    except Exception:  # noqa: BLE001
        pass
    return out
