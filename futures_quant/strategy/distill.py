"""M7.6 知识蒸馏：把进化出的最强策略基因压缩为可读规则集，导出 UI 可读的 rules.json。

设计（离线、无未来函数）：
- 输入：一组已评估策略基因（``gene + metrics``，来自进化档案 / 盈利策略库）。
- 选出适应度最高的 top-K，把它们抽象为「入场规则 + 离场规则 + 风控参数」的
  人类可读规则集（而非原始基因树），写 ``data/auto_strategies/rules.json``。
- 蒸馏保真度评估：把蒸馏规则用 ``GeneStrategy`` 解释回测，与原始基因回测的夏普对比，
  要求下降 <10%（通过注入的 backtest_fn 计算，保持可离线单测）。

接口：
- ``select_top(entries, k)`` → 按 fitness 取前 k。
- ``distill(gene)`` → 单基因 → 规则 dict（因子/参数/风控的可读标签）。
- ``export_rules(entries, k, path)`` → 写 rules.json，返回 {path, n_rules, top}。
- ``fidelity(original_metrics, distilled_metrics)`` → 夏普相对下降比例（<0.10 合格）。
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Sequence

__all__ = [
    "RULES_PATH",
    "select_top",
    "distill",
    "export_rules",
    "format_rules_text",
    "fidelity",
    "FIDELITY_TOLERANCE",
]

# 项目根（futures_quant/strategy -> futures_quant -> root）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_PATH: str = os.path.join(ROOT, "data", "auto_strategies", "rules.json")

# 蒸馏保真度容差：蒸馏后夏普相对原始夏普下降不超过 10%
FIDELITY_TOLERANCE: float = 0.10

# 因子名 → 中文标签（与 auto_evolve.FACTOR_LABEL 对齐，缺省回退原始键名）
try:
    from .auto_evolve import FACTOR_LABEL as _FACTOR_LABEL
except Exception:  # pragma: no cover - 导入失败时用本地兜底
    _FACTOR_LABEL: Dict[str, str] = {}
_FALLBACK_LABELS: Dict[str, str] = {
    "ma_cross": "双均线交叉", "donchian_break": "唐奇安通道突破",
    "rsi_reversal": "RSI 超买超卖反转", "boll_break": "布林带突破",
    "boll_revert": "布林带均值回归", "momentum": "动量追踪",
    "macd_signal": "MACD 信号", "cci": "CCI 通道", "roc": "ROC 动量",
}
_LABELS = {**_FALLBACK_LABELS, **_FACTOR_LABEL}


def _label(name: str) -> str:
    return _LABELS.get(name, name)


def select_top(entries: Sequence[Dict[str, Any]], k: int = 3) -> List[Dict[str, Any]]:
    """按 fitness 降序取前 k（不足则全取）。fitness 缺失记 -inf。"""
    if not entries:
        return []
    ranked = sorted(entries, key=lambda e: float(e.get("fitness") or float("-inf")), reverse=True)
    return ranked[: max(1, k)]


def distill(gene: Dict[str, Any]) -> Dict[str, Any]:
    """把单个策略基因压缩为可读规则 dict。

    返回结构（UI 可直接渲染）：
        ``{rule_id, factor, factor_label, entry_desc, exit_desc, risk}``。
    支持扁平基因（``factor`` 键）与树结构基因（``type=="op"`` + ``left``/``right``，
    自动展开叶子因子）。
    """
    g = dict(gene or {})
    is_tree = g.get("type") == "op" or ("left" in g and "right" in g)
    # M2-10：兼容扁平基因（M4.6 契约用 `entry` 存因子名、因子参数嵌套在 `params` 内），
    # 控制字段（stop_mult/tp_mult/lots/allow_*）可在顶层或 params 内，顶层优先。
    nested = g.get("params") if isinstance(g.get("params"), dict) else {}

    def _ctrl(key, default=None):
        """读取控制字段：顶层优先，回退到嵌套 params。"""
        if g.get(key) is not None:
            return g.get(key)
        return nested.get(key, default)

    factor = g.get("factor") or g.get("entry") or nested.get("factor") or nested.get("entry")
    if factor is None and is_tree:
        leaves = _collect_leaves(g)
        factor = "+".join(sorted({l for l in leaves if l})) or "composite"
    factor_label = _label(factor) if isinstance(factor, str) else "组合因子"
    entry_desc = f"入场：{factor_label}" + (f"（{g.get('op')} 组合）" if is_tree else "")
    stop_mult = _ctrl("stop_mult")
    tp_mult = _ctrl("tp_mult")
    exit_desc = "离场：" + "、".join(filter(None, [
        _desc_exit("stop_mult", stop_mult, "ATR 跟踪止损"),
        _desc_exit("tp_mult", tp_mult, "ATR 止盈"),
    ]))
    risk = {
        "stop_mult": stop_mult,
        "tp_mult": tp_mult,
        "lots": _ctrl("lots"),
        "allow_long": _ctrl("allow_long", True),
        "allow_short": _ctrl("allow_short", True),
    }
    # 参数细节（均线周期等）：扁平基因直接取嵌套 params；树/遗留基因取顶层剩余键
    if nested:
        params = {k: v for k, v in nested.items()
                  if k not in ("stop_mult", "tp_mult", "lots",
                               "allow_long", "allow_short")}
    else:
        params = {k: v for k, v in g.items()
                  if k not in ("factor", "entry", "params", "stop_mult", "tp_mult", "lots",
                               "allow_long", "allow_short", "op", "left", "right",
                               "type", "name", "signature", "fitness", "desc",
                               "symbol", "symbol_name", "period", "metrics")}
    return {
        "rule_id": str(g.get("signature") or _sig_of(g)),
        "factor": factor,
        "factor_label": factor_label,
        "entry_desc": entry_desc,
        "exit_desc": exit_desc,
        "risk": risk,
        "params": params,
        "fitness": g.get("fitness"),
    }


def _desc_exit(key: str, val, prefix: str) -> Optional[str]:
    if val is None or val == 0 or val == 0.0:
        return None
    return f"{prefix}({val})"


def _sig_of(gene: Dict[str, Any]) -> str:
    import hashlib
    raw = json.dumps(gene, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _collect_leaves(node: Dict[str, Any]) -> List[str]:
    """递归收集树结构基因的叶子因子名。"""
    out: List[str] = []
    def rec(n):
        if not isinstance(n, dict):
            return
        if "left" in n and "right" in n:
            rec(n.get("left"))
            rec(n.get("right"))
        else:
            f = n.get("factor") or n.get("name")
            if f:
                out.append(str(f))
    rec(node)
    return out


def export_rules(entries: Sequence[Dict[str, Any]], k: int = 3,
                 path: Optional[str] = None) -> Dict[str, Any]:
    """选出 top-K 基因并蒸馏，写入 rules.json，返回摘要。

    返回:
        ``{path, n_rules, top: [rule...], best_fitness}``。
    写入失败（如只读目录）仍返回规则（不阻塞内存使用）。
    """
    top = select_top(entries, k)
    rules = [distill(e.get("gene") or e.get("genes") or {}) for e in top]
    out_path = path or RULES_PATH
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        payload = {
            "version": 1,
            "n_rules": len(rules),
            "rules": rules,
            "best_fitness": top[0].get("fitness") if top else None,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        ok = True
    except Exception:
        ok = False
    return {"path": out_path, "n_rules": len(rules), "top": rules,
            "best_fitness": top[0].get("fitness") if top else None, "written": ok}


def format_rules_text(payload: Dict[str, Any]) -> str:
    """把 ``export_rules`` 的产出渲染为人类可读文本（UI Tab 直接展示）。

    M2-10：回测中心「蒸馏规则」按钮点击后在 Tab 内展示此文本。
    """
    # export_rules 返回体用 "top" 承载规则列表，rules.json 文件体用 "rules"，两者兼容
    rules = (payload or {}).get("rules") or (payload or {}).get("top") or []
    if not rules:
        return "暂无可蒸馏的规则（盈利策略库为空或尚无合格策略）。"
    lines = [f"蒸馏规则集：共 {len(rules)} 条（取自盈利策略库 top-{len(rules)}）", ""]
    for i, r in enumerate(rules, 1):
        risk = r.get("risk") or {}
        params = r.get("params") or {}
        allow = []
        if risk.get("allow_long"):
            allow.append("做多")
        if risk.get("allow_short"):
            allow.append("做空")
        lines.append(f"【规则 {i}】{r.get('factor_label') or r.get('factor')}")
        lines.append(f"  {r.get('entry_desc', '')}")
        lines.append(f"  {r.get('exit_desc', '')}")
        lines.append(
            f"  风控：手数 {risk.get('lots') or 1}｜方向 {'/'.join(allow) or '无'}"
            f"｜止损×{risk.get('stop_mult')}｜止盈×{risk.get('tp_mult')}")
        if params:
            ps = "、".join(f"{k}={v}" for k, v in list(params.items())[:8])
            lines.append(f"  参数：{ps}")
        lines.append("")
    return "\n".join(lines)


def fidelity(original_metrics: Dict[str, Any], distilled_metrics: Dict[str, Any]) -> float:
    """蒸馏保真度：夏普相对下降比例。

    返回 ``max(0, (o_sharpe - d_sharpe) / max(|o_sharpe|, 1e-9))``；
    下降 ≤ FIDELITY_TOLERANCE 视为合格。原始夏普缺失或为 0 时返回 0.0（无参照）。
    """
    o = float(original_metrics.get("sharpe") or 0.0)
    d = float(distilled_metrics.get("sharpe") or 0.0)
    if abs(o) <= 1e-9:
        return 0.0
    drop = (o - d) / abs(o)
    return round(max(0.0, drop), 6)
