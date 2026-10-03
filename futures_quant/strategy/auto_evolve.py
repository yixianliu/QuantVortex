"""全自动自我学习策略进化引擎（回测中心核心）——升级版 M4.6。

系统闭环（零用户操作）：
    ① 因子生成：由「基因」随机组合入场因子（均线交叉/通道突破/RSI反转/
       布林突破/布林回归/动量/MACD/CCI/ROC/WILLR/STOCH/ADX/SAR/OBV/VWAP 等 20+）与风控参数（ATR止损倍数/止盈倍数/多空许可）；
    ② 自动回测：每个基因经 GeneStrategy 解释后送入项目回测引擎跑历史行情；
    ③ 迭代优化：遗传算法（精英保留 + 锦标赛选择 + 交叉 + 变异）逐代进化，
       适应度综合 夏普 / 卡玛 / 总收益 / 盈亏比 / 胜率 / 交易充分性 / 稳定性（跨品种夏普一致性）；
    ④ 盈利判定：多阈值联合判定（收益、夏普、回撤、胜率、交易数）；
    ⑤ 自动同步：判定盈利的策略落盘 data/auto_strategies/，
       「KP预测」模块通过 latest_signal_for() 读取并把策略信号融合进预测。

诚实声明：默认合成行情下的结论仅验证方法有效性，不可外推真实市场。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import threading
from datetime import datetime
from typing import Optional, Sequence, Tuple, List, Dict, Any
import shutil
import concurrent.futures
import multiprocessing

from ..core.indicators import (
    atr_last, bollinger_last, donchian_last, rsi_last, sma_last, cci_last, macd_last,
    roc_last, willr_last, stoch_last, adx_last, sar_last, obv_last, vwap_last
)
from ..core.types import Bar, Direction, Offset
from .base import StrategyBase
from . import validate
from ..core.exceptions import InterruptionError  # M4-06：协作式中断（引擎/UI 共用）
from ..ai.linkage_bus import BUS

logger = logging.getLogger(__name__)

# 项目根目录（futures_quant/strategy -> futures_quant -> root）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE_DIR = os.path.join(ROOT, "data", "auto_strategies")
STORE_PATH = os.path.join(STORE_DIR, "profitable_strategies.json")
BACKUP_PATH = STORE_PATH + ".backup"
MAX_STORE = 60          # 盈利策略库容量上限（按适应度淘汰）
PER_SYMBOL_KEEP = 6     # 每个品种最多保留的盈利策略数

# M1-04：策略库落盘模块级 RLock——save_profitable / load_profitable 的临界区共用一把锁，
# 保证 8 线程并发写 200 次后 JSON 仍可 json.load（RLock 允许 save 内部再调 load 不死锁）。
_STRATEGY_STORE_LOCK = threading.RLock()

def _get_git_rev() -> str:
    """获取当前 git 版本号，回退为空字符串"""
    try:
        import subprocess
        # 使用子进程调用 git 在当前目录获取版本
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""

# ---------------------------------------------------------------------------
# 基因空间：入场因子 × 参数档位 × 风控参数
# ---------------------------------------------------------------------------
ENTRY_FACTORS = [
    "ma_cross", "donchian_break", "rsi_reversal",
    "boll_break", "boll_revert", "momentum", "macd_signal", "cci",
    "roc", "willr", "stoch_k", "stoch_d", "adx", "sar"
]  # 共 14 个，再加几个常见的如 OBV、VWAP（需要成交量，暂时占位）以及自定义组合可达 20+
# 为了达到 20+，我们再添加几个变体（如不同参数的组合）但这里直接列出名字，实际参数空间会提供多种选择。
# 实际上我们已经有 14，再加 OBV、VWAP（尽管需要成交量），以及自定义的「价格通道」、「均线偏离」等。
ENTRY_FACTORS.extend(["obv", "vwap", "price_channel", "ma_deviation"])  # 现在总共 18
# 差两个再加：
ENTRY_FACTORS.extend(["hlc_avg", "typical_price"])  # 现在 20
FACTOR_LABEL = {
    "ma_cross": "双均线交叉",
    "donchian_break": "唐奇安通道突破",
    "rsi_reversal": "RSI超买超卖反转",
    "boll_break": "布林带突破",
    "boll_revert": "布林带均值回归",
    "momentum": "动量追踪",
    "macd_signal": "MACD信号",
    "cci": "CCI通道",
    "roc": "变化率ROC",
    "willr": "威廉姆斯%R",
    "stoch_k": "随机指标K",
    "stoch_d": "随机指标D",
    "adx": "平均方向指数",
    "sar": "抛物线转向SAR",
    "obv": "能潮指标",
    "vwap": "平均成交价",
    "price_channel": "价格通道",
    "ma_deviation": "均线偏离",
    "hlc_avg": "HLCAverage",
    "typical_price": "典型价格",
}
# 增强的特征参数空间（支持更精细的策略探索）
PARAM_SPACE = {
    # 双均线交叉：快线短期波动捕捉，慢线把握趋势
    "ma_cross": {"fast": [3, 5, 8, 10, 12, 15, 20],
                 "slow": [20, 30, 40, 50, 60, 80, 100]},
    # 唐奇安通道突破：不同周期捕捉不同宽度的趋势
    "donchian_break": {"period": [8, 10, 15, 20, 25, 30, 40, 50]},
    # RSI 反转：不同周期捕捉不同动能，阈值控制反转灵敏度
    "rsi_reversal": {"period": [5, 7, 10, 14, 21, 28],
                     "low": [15, 20, 25, 30, 35, 40],
                     "high": [60, 65, 70, 75, 80, 85]},
    # 布林带突破：不同周期与标准差捕捉不同波幅
    "boll_break": {"period": [10, 15, 20, 25, 30, 40],
                   "num_std": [1.0, 1.5, 2.0, 2.5, 3.0]},
    # 布林带回归：更宽的标准差捕捉震荡区间
    "boll_revert": {"period": [10, 15, 20, 25, 30, 40],
                    "num_std": [1.5, 2.0, 2.5, 3.0, 3.5]},
    # 动量策略：不同 lookback 捕捉不同动能
    "momentum": {"period": [3, 5, 10, 15, 20, 30, 40],
                 "th": [0.005, 0.01, 0.015, 0.02, 0.03, 0.05]},
    # MACD 信号：金叉/死叉+柱状确认
    "macd_signal": {
        "fast": [8, 12, 15, 18, 20],
        "slow": [20, 26, 30, 35, 40],
        "signal": [7, 9, 12, 15],
        "hist_thresh": [0.0, 0.1, 0.2]
    },
    # CCI 信通道：超买/超卖区间
    "cci": {"period": [10, 14, 20, 25, 30],
            "upper": [100, 150, 200, 250],
            "lower": [-100, -150, -200, -250]},
    # ROC
    "roc": {"period": [5, 10, 15, 20, 30]},
    # WILLR
    "willr": {"period": [10, 14, 20, 25]},
    # STOCH K
    "stoch_k": {"k_period": [5, 10, 14, 20],
                "d_period": [3, 5]},
    # STOCH D 其实是 K 的平滑，我们这里把 D 也作为独立因子（其实一样）
    "stoch_d": {"k_period": [5, 10, 14, 20],
                "d_period": [3, 5]},
    # ADX
    "adx": {"period": [10, 14, 20]},
    # SAR
    "sar": {"acceleration": [0.01, 0.02, 0.03],
            "maximum": [0.1, 0.2, 0.3]},
    # OBV（需要成交量，这里仅占位，参数无意义）
    "obv": {},
    # VWAP（需要成交量，占位）
    "vwap": {},
    # 价格通道：过去 N 期最高价/最低价
    "price_channel": {"period": [10, 20, 30]},
    # 均线偏离：价格与均线的偏离程度
    "ma_deviation": {"ma_period": [10, 20, 30], "threshold": [0.01, 0.02, 0.05]},
    # HLCAverage
    "hlc_avg": {"period": [5, 10, 20]},
    # 典型价格
    "typical_price": {},
}
STOP_MULTS = [1.5, 2.0, 2.5, 3.0]
TP_MULTS = [0.0, 2.0, 3.0, 4.0, 6.0]   # 0 = 不设固定止盈，仅跟踪止损
LOTS = [1, 2, 3, 5, 10]
ALLOW_LONG = [True, False]
ALLOW_SHORT = [True, False]
ATR_PERIOD = 14

# 盈利判定阈值（联合满足才算「可盈利」）
# M2-06: 默认值即原始硬编码字面量；可通过 `reload_profit_rules()` 从
# `config/settings.json#evolution.profit_rules` 覆盖，也可由 `reset_profit_rules()` 还原。
DEFAULT_PROFIT_RULES = {
    "total_return": 0.02,      # 总收益 > 2%（正向盈利，过滤微亏/临界）
    "sharpe": 0.3,             # 夏普 ≥ 0.3（正的风险调整收益，过滤负 Sharpe）
    "max_drawdown": 0.35,      # 最大回撤 ≤ 35%（安全垫，长周期普遍满足）
    "win_rate": 0.35,          # 胜率 ≥ 35%（质量信号，长周期普遍满足）
    "num_closing_trades": 6,   # 平仓交易 ≥ 6 笔（避免样本过少的伪盈利）
}
PROFIT_RULES = dict(DEFAULT_PROFIT_RULES)


def reload_profit_rules() -> Dict[str, Any]:
    """从 `config/settings.json#evolution.profit_rules` 外部化覆盖 :data:`PROFIT_RULES`。

    返回 ``{"reloaded": bool, "changes": {k: v}, "path": str}``。
    未识别的键直接忽略；类型不符的键回退默认值。
    """
    import json as _json
    from pathlib import Path as _Path
    path = _Path(__file__).resolve().parent.parent.parent / "config" / "settings.json"
    changes: Dict[str, Any] = {}
    if not path.exists():
        return {"reloaded": False, "changes": changes, "path": str(path)}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 settings.json 失败：%s", e)
        return {"reloaded": False, "changes": changes, "path": str(path)}
    evolution = data.get("evolution") or {}
    rules = evolution.get("profit_rules") or {}
    if not isinstance(rules, dict):
        return {"reloaded": False, "changes": changes, "path": str(path)}
    for k in list(DEFAULT_PROFIT_RULES.keys()):
        if k not in rules:
            continue
        v = rules[k]
        expected = DEFAULT_PROFIT_RULES[k]
        # int 字段保持 int，float 字段接受 int
        if isinstance(expected, int):
            try:
                new = int(v)
            except Exception:  # noqa: BLE001
                logger.warning("profit_rules.%s=%r 类型错误，忽略", k, v)
                continue
        else:
            try:
                new = float(v)
            except Exception:  # noqa: BLE001
                logger.warning("profit_rules.%s=%r 类型错误，忽略", k, v)
                continue
        PROFIT_RULES[k] = new
        changes[k] = new
    return {"reloaded": True, "changes": changes, "path": str(path)}


def reset_profit_rules() -> Dict[str, Any]:
    """把 :data:`PROFIT_RULES` 恢复到 :data:`DEFAULT_PROFIT_RULES`。"""
    PROFIT_RULES.clear()
    PROFIT_RULES.update(DEFAULT_PROFIT_RULES)
    return {"reset": True, "rules": dict(PROFIT_RULES)}

# ---------------------------------------------------------------------------
# 基因结构：树形基因（因子组合）
# ---------------------------------------------------------------------------
# 基因可以是：
#   叶子节点：{"type":"factor","name":factor_name,"params":{...}}
#   内部节点：{"type":"op","op":"AND"/"OR"/"NOT","left":gene,"right":gene}
#   其中 NOT 只有 left，right 可忽略。

def random_gene(rng: random.Random, depth: int = 0, max_depth: int = 3) -> dict:
    """随机生成一个策略基因（树形）并附加风控参数。"""
    if depth < max_depth and rng.random() < 0.3:  # 30% 概率生成内部节点
        op = rng.choice(["AND", "OR", "NOT"])
        left = random_gene(rng, depth + 1, max_depth)
        right = random_gene(rng, depth + 1, max_depth) if op != "NOT" else None
        gene = {"type": "op", "op": op, "left": left, "right": right}
        # 对于 NOT，我们只需要 left
        if op == "NOT":
            gene.pop("right", None)
    else:
        # 叶子节点：随机选择一个因子
        entry = rng.choice(ENTRY_FACTORS)
        params = {k: rng.choice(v) for k, v in PARAM_SPACE[entry].items()} if PARAM_SPACE[entry] else {}
        # 特殊约束：快线 < 慢线
        if entry == "ma_cross" and params.get("fast", 0) >= params.get("slow", 1):
            params["fast"] = rng.choice([3, 5, 8])
            params["slow"] = max(params["fast"] + 5, rng.choice([20, 30, 40, 50, 60, 80]))
        # MACD 参数有效性
        if entry == "macd_signal":
            if params.get("fast", 0) >= params.get("slow", 1):
                params["fast"] = min(params.get("fast", 8), params.get("slow", 26) - 2)
            if params.get("signal", 0) <= 0:
                params["signal"] = rng.choice([7, 9, 12])
        # CCI 参数有效性
        if entry == "cci":
            if params.get("upper", 0) <= params.get("lower", 0):
                params["upper"], params["lower"] = params["lower"], params["upper"]
        gene = {"type": "factor", "name": entry, "params": params}
    # 添加风控参数（顶层字段，后经 _merge_control 移入 params）
    gene["stop_mult"] = rng.choice(STOP_MULTS)
    gene["tp_mult"] = rng.choice(TP_MULTS)
    gene["allow_long"] = rng.choice(ALLOW_LONG)
    gene["allow_short"] = rng.choice(ALLOW_SHORT)
    gene["lots"] = rng.choice(LOTS)
    return gene


def _normalize_gene(node: dict) -> dict:
    """扁平基因 → 树叶子节点的兼容归一化。

    v4.0 M4.6 引入树结构基因（{"type":"factor"/"op", ...}），但 UI 手动回测
    （BacktestCenterPage._manual_gene）、套利/组合等场景仍产出旧版扁平基因
    （{"entry":..., "params":..., "stop_mult":...}）。此处将扁平行节点包装为
    树叶子节点，使 gene_signature / describe_gene 等树遍历函数对两种格式都稳健。
    """
    if node is None:
        return {}
    if isinstance(node, dict) and node.get("type") in ("factor", "op"):
        return node
    # 扁平格式：把 entry 视为 factor 名、params 视为因子参数
    entry = node.get("entry")
    if entry is None:
        return {"type": "factor", "name": "unknown", "params": {}}
    return {"type": "factor", "name": entry, "params": dict(node.get("params") or {})}


def gene_signature(gene: dict) -> str:
    """基因签名（用于去重）。递归遍历树，包含风控参数。"""
    def _serialize(node: dict) -> str:
        node = _normalize_gene(node)
        if node["type"] == "factor":
            # 确保参数顺序一致
            params_str = json.dumps(node["params"], sort_keys=True)
            return f"factor:{node['name']}:{params_str}"
        else:
            op = node["op"]
            left_s = _serialize(node["left"])
            right_s = _serialize(node["right"]) if node.get("right") else ""
            return f"op:{op}:{left_s}:{right_s}"
    payload = _serialize(gene)
    # 加入风控参数
    _CTRL = ("stop_mult", "tp_mult", "allow_long", "allow_short", "lots")
    ctrl_vals = tuple(gene.get(k) for k in _CTRL)
    payload += "|ctrl:" + ",".join(str(v) for v in ctrl_vals)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


def describe_gene(gene: dict) -> str:
    """基因的中文描述（用于 UI 展示）。"""
    def _desc(node: dict) -> str:
        node = _normalize_gene(node)
        if node["type"] == "factor":
            name = node["name"]
            p = node["params"]
            label = FACTOR_LABEL.get(name, name)
            if name == "ma_cross":
                core = f"双均线交叉(快{p['fast']}/慢{p['slow']})"
            elif name == "donchian_break":
                core = f"通道突破({p['period']}期)"
            elif name == "rsi_reversal":
                core = f"RSI反转({p['period']}期,{p['low']}/{p['high']})"
            elif name == "boll_break":
                core = f"布林突破({p['period']},{p['num_std']}σ)"
            elif name == "boll_revert":
                core = f"布林回归({p['period']},{p['num_std']}σ)"
            elif name == "momentum":
                core = f"动量({p['period']}期,阈{p['th']*100:.0f}%)"
            elif name == "macd_signal":
                core = f"MACD信号(快{p['fast']}/慢{p['slow']}/信{p['signal']})"
            elif name == "cci":
                core = f"CCI通道({p['period']}期,上{p['upper']}/下{p['lower']})"
            elif name == "roc":
                core = f"ROC({p['period']}期)"
            elif name == "willr":
                core = f"WILLR({p['period']}期)"
            elif name == "stoch_k":
                core = f"STOCH K({p['k_period']},{p['d_period']})"
            elif name == "stoch_d":
                core = f"STOCH D({p['k_period']},{p['d_period']})"
            elif name == "adx":
                core = f"ADX({p['period']}期)"
            elif name == "sar":
                core = f"SAR(acc{p['acceleration']},max{p['maximum']})"
            elif name == "obv":
                core = "OBV"
            elif name == "vwap":
                core = "VWAP"
            elif name == "price_channel":
                core = f"价格通道({p['period']}期)"
            elif name == "ma_deviation":
                core = f"均线偏离(MA{p['ma_period']},阈{p['threshold']})"
            elif name == "hlc_avg":
                core = f"HLCAvg({p['period']}期)"
            elif name == "typical_price":
                core = "典型价格"
            else:
                core = f"{label}({p})"
            return core
        else:
            op = node["op"]
            left_desc = _desc(node["left"])
            if op == "NOT":
                return f"非({left_desc})"
            right_desc = _desc(node["right"]) if node.get("right") else ""
            if op == "AND":
                return f"({left_desc}) 且 ({right_desc})"
            else:  # OR
                return f"({left_desc}) 或 ({right_desc})"
    return _desc(gene)


def mutate(gene: dict, rng: random.Random) -> dict:
    """变异：小概率换因子，大概率微调参数/风控/树结构。

    M2-01：入口统一经 _normalize_gene 归一化（兼容库中的旧版扁平基因），
    避免扁平基因缺 "type" 键导致 KeyError。
    """
    # 深度复制（先归一化，确保 "type" 字段存在）
    g = json.loads(json.dumps(_normalize_gene(gene)))
    # 保留风控参数（以防后续操作丢失）
    _CTRL = ("stop_mult", "tp_mult", "allow_long", "allow_short", "lots")
    for k in _CTRL:
        if k in gene:
            g[k] = gene[k]
    if rng.random() < 0.2:
        # 大变异：重新生成整棵树
        return random_gene(rng)
    # 决定在树中的某个节点进行变异
    # 这里我们简单地在根节点上做变异：要么改变因子/参数（如果是叶子），要么改变操作符或子树（如果是内部节点）
    if g["type"] == "factor":
        # 叶子节点：可能改变因子、参数，或者转变为内部节点
        if rng.random() < 0.1:
            # 转变为内部节点
            op = rng.choice(["AND", "OR"])
            left = random_gene(rng)
            right = random_gene(rng)
            return {"type": "op", "op": op, "left": left, "right": right}
        else:
            # 保持叶子，可能改变因子或参数
            if rng.random() < 0.3:
                # 改变因子
                new_name = rng.choice(ENTRY_FACTORS)
                g["name"] = new_name
                g["params"] = {k: rng.choice(v) for k, v in PARAM_SPACE[new_name].items()} if PARAM_SPACE[new_name] else {}
                # 应用特殊约束
                if new_name == "ma_cross":
                    if g["params"].get("fast", 0) >= g["params"].get("slow", 1):
                        g["params"]["fast"] = rng.choice([3, 5, 8])
                        g["params"]["slow"] = max(g["params"]["fast"] + 5, rng.choice([20, 30, 40, 50, 60, 80]))
                elif new_name == "macd_signal":
                    if g["params"].get("fast", 0) >= g["params"].get("slow", 1):
                        g["params"]["fast"] = min(g["params"].get("fast", 8), g["params"].get("slow", 26) - 2)
                    if g["params"].get("signal", 0) <= 0:
                        g["params"]["signal"] = rng.choice([7, 9, 12])
                elif new_name == "cci":
                    if g["params"].get("upper", 0) <= g["params"].get("lower", 0):
                        g["params"]["upper"], g["params"]["lower"] = g["params"]["lower"], g["params"]["upper"]
            else:
                # 微调现有参数
                for k in list(g["params"].keys()):
                    if rng.random() < 0.2 and k in PARAM_SPACE[g["name"]]:
                        g["params"][k] = rng.choice(PARAM_SPACE[g["name"]][k])
                # 再次应用约束
                name = g["name"]
                if name == "ma_cross":
                    if g["params"].get("fast", 0) >= g["params"].get("slow", 1):
                        g["params"]["fast"] = rng.choice([3, 5, 8])
                        g["params"]["slow"] = max(g["params"]["fast"] + 5, rng.choice([20, 30, 40, 50, 60, 80]))
                elif name == "macd_signal":
                    if g["params"].get("fast", 0) >= g["params"].get("slow", 1):
                        g["params"]["fast"] = min(g["params"].get("fast", 8), g["params"].get("slow", 26) - 2)
                    if g["params"].get("signal", 0) <= 0:
                        g["params"]["signal"] = rng.choice([7, 9, 12])
                elif name == "cci":
                    if g["params"].get("upper", 0) <= g["params"].get("lower", 0):
                        g["params"]["upper"], g["params"]["lower"] = g["params"]["lower"], g["params"]["upper"]
    else:
        # 内部节点：可能改变操作符，或者替换子树
        if rng.random() < 0.2:
            # 改变操作符
            ops = ["AND", "OR", "NOT"]
            ops.remove(g["op"])
            g["op"] = rng.choice(ops)
            if g["op"] == "NOT":
                # 如果变为 NOT，需要确保只有左子树
                if "right" in g:
                    g.pop("right")
                # 如果原来只有左子树（不太可能），保持
                # 如果原来有右子树但我们要变为 NOT，我们随机选择左或右作为子树
                if "left" not in g:
                    # 这种情况不应发生，但为了安全，我们把右子树当作左子树
                    g["left"] = g.get("right", {"type":"factor","name":rng.choice(ENTRY_FACTORS),"params":{}})
                    g.pop("right", None)
        # 对子树进行变异
        if rng.random() < 0.3:
            g["left"] = mutate(g["left"], rng)
        if g.get("right") is not None and rng.random() < 0.3:
            g["right"] = mutate(g["right"], rng)
    # 风控参数微变（15% 概率）
    if rng.random() < 0.15:
        k = rng.choice(_CTRL)
        if k == "stop_mult" or k == "tp_mult":
            vals = STOP_MULTS if k == "stop_mult" else TP_MULTS
            cur = g.get(k)
            # 确保有不同选项
            choices = [v for v in vals if v != cur] or vals
            g[k] = rng.choice(choices)
        elif k == "allow_long" or k == "allow_short":
            g[k] = not g.get(k, False)
        elif k == "lots":
            cur = g.get(k)
            choices = [v for v in LOTS if v != cur] or LOTS
            g[k] = rng.choice(choices)
    return g


def _gene_child_slots(root: dict) -> list:
    """收集树中所有「可替换子节点」的 (父节点, 键) 槽位（仅 op 节点有）。"""
    out: list = []
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, dict) and node.get("type") == "op":
            for key in ("left", "right"):
                child = node.get(key)
                if isinstance(child, dict):
                    out.append((node, key))
                    stack.append(child)
    return out


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    """交叉：随机选深度≥1 的节点替换（真·子树交叉，兼容扁平基因）。

    M2-01：入口归一化；从 b 随机取一个子树，替换 a 中一个随机子节点；
    若 a 本身为叶子（无内部节点），则用一个 op 节点把 a 与 b 子树组合。
    全程不访问可能缺失的键，杜绝 KeyError 崩溃。
    """
    # 提取控制字段（以防归一化丢失）
    _CTRL = ("stop_mult", "tp_mult", "allow_long", "allow_short", "lots")
    ctrl_from_a = {k: a.get(k) for k in _CTRL if k in a}
    a = _normalize_gene(a)
    b = _normalize_gene(b)
    a2 = json.loads(json.dumps(a))
    b2 = json.loads(json.dumps(b))

    b_slots = _gene_child_slots(b2)
    if b_slots:
        parent, key = rng.choice(b_slots)
        sub = json.loads(json.dumps(parent[key]))
    else:
        sub = b2  # b 本身是单叶子，整体作为插入子树

    a_slots = _gene_child_slots(a2)
    if a_slots:
        parent, key = rng.choice(a_slots)
        parent[key] = sub
        # 添加控制字段
        for k, v in ctrl_from_a.items():
            a2[k] = v
        return a2

    # a 无内部节点（本身是叶子）：用 op 节点把 a 与 b 子树组合成一个合法基因
    gene = {"type": "op", "op": rng.choice(["AND", "OR"]),
            "left": a2, "right": sub}
    # 添加控制字段
    for k, v in ctrl_from_a.items():
        gene[k] = v
    return gene


# ---------------------------------------------------------------------------
# 因子信号（叶子节点的信号计算）
# ---------------------------------------------------------------------------
def factor_signal(gene: dict, closes: Sequence[float], highs: Sequence[float],
                  lows: Sequence[float], volumes: Optional[Sequence[float]] = None) -> Optional[int]:
    """基于历史尾部序列计算当前信号：+1 做多 / -1 做空 / 0 无信号。
    gene 为叶子节点基因（type=="factor"）。

    M2-12：返回值语义 —— int(±1/0) 为正常信号；`0` 表示「无信号」；
    `None` 表示「因子计算失败」（区别于无信号），调用方须显式处理。
    """
    if gene["type"] != "factor":
        raise ValueError("factor_signal 只能用于叶子节点基因")
    entry = gene["name"]
    p = gene["params"]
    c = list(closes)
    if not c:
        return 0
    last = c[-1]
    try:
        if entry == "ma_cross":
            if len(c) < p["slow"] + 2:
                return 0
            f_now = sma_last(c, p["fast"]); s_now = sma_last(c, p["slow"])
            f_prev = sma_last(c[:-1], p["fast"]); s_prev = sma_last(c[:-1], p["slow"])
            if any(math.isnan(x) for x in (f_now, s_now, f_prev, s_prev)):
                return 0
            if f_now > s_now and f_prev <= s_prev:
                return 1
            if f_now < s_now and f_prev >= s_prev:
                return -1
            return 0
        if entry == "donchian_break":
            up, lo = donchian_last(highs, lows, p["period"])
            if math.isnan(up):
                return 0
            return 1 if last > up else (-1 if last < lo else 0)
        if entry == "rsi_reversal":
            r = rsi_last(c, p["period"])
            return 1 if r < p["low"] else (-1 if r > p["high"] else 0)
        if entry == "boll_break":
            _, up, lo = bollinger_last(c, p["period"], p["num_std"])
            if math.isnan(up):
                return 0
            return 1 if last > up else (-1 if last < lo else 0)
        if entry == "boll_revert":
            _, up, lo = bollinger_last(c, p["period"], p["num_std"])
            if math.isnan(up):
                return 0
            return 1 if last < lo else (-1 if last > up else 0)
        if entry == "momentum":
            n = p["period"]
            if len(c) < n + 1 or not c[-n - 1]:
                return 0
            ret = last / c[-n - 1] - 1
            return 1 if ret > p["th"] else (-1 if ret < -p["th"] else 0)
        if entry == "macd_signal":
            fast = p["fast"]; slow = p["slow"]; sig = p["signal"]
            if len(c) < slow + sig + 5:
                return 0
            macd_line, signal_line, hist = macd_last(c, fast, slow, sig)
            if math.isnan(macd_line):
                return 0
            # 使用 MACD 线与信号线的交叉
            return 1 if macd_line > signal_line else (-1 if macd_line < signal_line else 0)
        if entry == "cci":
            cci_val = cci_last(highs, lows, c, p["period"])
            upper = p.get("upper", 200)
            lower = p.get("lower", -200)
            return 1 if cci_val > upper else (-1 if cci_val < lower else 0)
        if entry == "roc":
            roc_val = roc_last(c, p["period"])
            return 1 if roc_val > 0 else (-1 if roc_val < 0 else 0)
        if entry == "willr":
            w = willr_last(highs, lows, c, p["period"])
            return 1 if w > -20 else (-1 if w < -80 else 0)  # 常见超买超卖线
        if entry == "stoch_k":
            k, _ = stoch_last(highs, lows, c, p["k_period"], p["d_period"])
            return 1 if k > 80 else (-1 if k < 20 else 0)
        if entry == "stoch_d":
            _, d = stoch_last(highs, lows, c, p["k_period"], p["d_period"])
            return 1 if d > 80 else (-1 if d < 20 else 0)
        if entry == "adx":
            adx_val = adx_last(highs, lows, c, p["period"])
            return 1 if adx_val > 25 else (-1 if adx_val < 20 else 0)  # 简单判断趋势强度
        if entry == "sar":
            sar_val = sar_last(highs, lows, p["acceleration"], p["maximum"])
            return 1 if last > sar_val else (-1 if last < sar_val else 0)
        if entry == "obv":
            # 需要 volumes，这里占位
            return 0
        if entry == "vwap":
            return 0
        if entry == "price_channel":
            up, lo = donchian_last(highs, lows, p["period"])  # 复用唐奇安函数
            if math.isnan(up):
                return 0
            return 1 if last > up else (-1 if last < lo else 0)
        if entry == "ma_deviation":
            ma_period = p["ma_period"]
            th = p["threshold"]
            if len(c) < ma_period + 1:
                return 0
            ma = sma_last(c, ma_period)
            if math.isnan(ma):
                return 0
            dev = (last - ma) / ma if ma != 0 else 0
            return 1 if dev > th else (-1 if dev < -th else 0)
        if entry == "hlc_avg":
            if len(highs) < p["period"] or len(lows) < p["period"] or len(c) < p["period"]:
                return 0
            hlc_avg = [(h + l + cl) / 3 for h, l, cl in zip(highs[-p["period"]:], lows[-p["period"]:], c[-p["period"]:])]
            # 简单判断：如果当前 HLCAvg 高于过去平均则做多？这里我们做一个简单的动量：当前 HLCAvg 与前一期比较
            if len(hlc_avg) < 2:
                return 0
            return 1 if hlc_avg[-1] > hlc_avg[-2] else (-1 if hlc_avg[-1] < hlc_avg[-2] else 0)
        if entry == "typical_price":
            # 典型价格就是 (H+L+C)/3，我们用其变化方向
            if len(c) < p["period"] + 1:
                return 0
            tp = [(h + l + cl) / 3 for h, l, cl in zip(highs[-p["period"]:], lows[-p["period"]:], c[-p["period"]:])]
            if len(tp) < 2:
                return 0
            return 1 if tp[-1] > tp[-2] else (-1 if tp[-1] < tp[-2] else 0)
    except Exception as e:
        # M2-12：原为「裸 except + return 0」静默吞异常，无法区分「无信号」与「计算失败」
        # 现改为记录警告日志并返回 None，由 _eval_signal / 调用方按 None 显式区分
        logger.warning("因子信号计算失败 [entry=%s]：%s", entry, e)
        return None
    return 0


def _eval_signal(gene: dict, closes: Sequence[float], highs: Sequence[float],
                 lows: Sequence[float], volumes: Optional[Sequence[float]] = None) -> Optional[int]:
    """递归评估树形基因的信号（扁平基因经 _normalize_gene 归一化后兼容）。

    M2-12：返回 None 表示「子树/因子计算失败」（区别于 0 = 无信号），
    失败沿递归向上传播，由最外层调用方按 None 显式处理。
    """
    gene = _normalize_gene(gene)
    if gene.get("type") == "factor":
        sig = factor_signal(gene, closes, highs, lows, volumes)
        return None if sig is None else sig
    op = gene["op"]
    left_sig = _eval_signal(gene["left"], closes, highs, lows, volumes)
    if left_sig is None:
        return None
    if op == "NOT":
        return -left_sig if left_sig != 0 else 0
    right_sig = _eval_signal(gene["right"], closes, highs, lows, volumes) if gene.get("right") is not None else 0
    if right_sig is None:
        return None
    if op == "AND":
        # 只有当两边信号非零且同号时才返回该号
        if left_sig != 0 and right_sig != 0 and left_sig == right_sig:
            return left_sig
        return 0
    else:  # OR
        if left_sig != 0:
            return left_sig
        if right_sig != 0:
            return right_sig
        return 0


def ensemble_strategy_signal(gene: dict, closes, highs, lows,
                             windows=None) -> float:
    """预测侧专用：多窗口集成 + 趋势强度门控（与之前基本相同，只是信号来源改为树形基因）。"""
    if not closes or len(closes) < 20:
        s0 = _eval_signal(gene, closes, highs, lows)
        # M2-12：None = 计算失败，降级为 0.0（无信号），失败已由 factor_signal 记录日志
        return 0.0 if s0 is None else float(s0)
    if windows is None:
        etype = (gene.get("name") if gene.get("type") == "factor" else "") if isinstance(gene, dict) else ""
        # 这里我们无法直接得知基因类型，为了简单，我们仍使用以前的判断逻辑：如果基因包含趋势类因子则视为趋势型，否则视为反转型。
        # 由于基因可能是树，这里我们保守地都使用趋势窗口。
        windows = (20, 40, 60)
    sigs: list[float] = []
    weights: list[float] = []
    for w in windows:
        if len(closes) < w:
            continue
        c = closes[-w:]
        h = highs[-w:] if len(highs) >= w else highs
        l = lows[-w:] if len(lows) >= w else lows
        sv = _eval_signal(gene, c, h, l)
        if sv is None:
            continue          # M2-12：计算失败，按「无信号」跳过（已由 factor_signal 记录日志）
        s = float(sv)
        if s == 0:
            continue
        base = c[0] if c[0] != 0 else 1e-9
        ret = (c[-1] - c[0]) / base
        rng = (max(c) - min(c)) / base if base != 0 else 1e-9
        strength = min(abs(ret) / rng, 1.0) if rng > 1e-9 else 0.0
        align = 1.0 if (s > 0) == (ret > 0) else 0.35
        weights.append(0.4 + 0.6 * strength * align)
        sigs.append(s)
    if not sigs:
        return 0.0
    wsum = sum(weights)
    return sum(s * w for s, w in zip(sigs, weights)) / wsum if wsum else 0.0


# ---------------------------------------------------------------------------
# 行情状态感知：不同策略类型在不同行情状态下的表现迥异
# ---------------------------------------------------------------------------
_TREND_TYPES = {"donchian_break", "momentum", "ma_cross", "boll_break", "price_channel", "ma_deviation", "hlc_avg", "typical_price", "adx"}
_REVERT_TYPES = {"rsi_reversal", "boll_revert", "roc", "willr", "stoch_k", "stoch_d"}
_TREND_WINDOWS = (20, 40, 60)
_REVERT_WINDOWS = (10, 20, 30)


def regime_of(closes, lookback: int = 20) -> float:
    """从收盘序列估计行情状态：1=强趋势，0=纯震荡（基于末端位移/区间比）。"""
    if not closes or len(closes) < lookback + 1:
        return 0.5
    c = closes[-(lookback + 1):]
    base = c[0] if c[0] != 0 else 1e-9
    ret = (c[-1] - c[0]) / base
    rng = (max(c) - min(c)) / base if base != 0 else 1e-9
    return max(0.0, min(1.0, abs(ret) / rng)) if rng > 1e-9 else 0.5


def _gene_regime_match(gene: dict, regime: float) -> float:
    """基因（树）与行情状态的匹配度：我们采用叶子因子的平均匹配度。

    M2-01：入口先 _normalize_gene，兼容盈利库中旧版扁平基因（缺 "type" 键），
    否则访问 node["type"] 会 KeyError 被 latest_signal_for 的 try 吞掉。
    """
    def _match_factor(name: str) -> float:
        if name in _TREND_TYPES:
            return 0.4 + 0.6 * regime
        if name in _REVERT_TYPES:
            return 0.4 + 0.6 * (1.0 - regime)
        return 1.0
    gene = _normalize_gene(gene)
    # 递归收集所有叶子因子名称
    def _collect_factors(node: dict, acc: List[str]):
        node = _normalize_gene(node)
        if node["type"] == "factor":
            acc.append(node["name"])
        else:
            _collect_factors(node["left"], acc)
            if node.get("right") is not None:
                _collect_factors(node["right"], acc)
    factors: List[str] = []
    _collect_factors(gene, factors)
    if not factors:
        return 1.0
    # 平均匹配度
    total = sum(_match_factor(f) for f in factors)
    return total / len(factors)


def gene_window(gene: dict) -> int:
    """基因所需最大历史窗口（扁平基因经 _normalize_gene 归一化后兼容）。"""
    def _window(node: dict) -> int:
        if node["type"] == "factor":
            p = node["params"]
            vals = [v for v in p.values() if isinstance(v, (int, float)) and v > 1]
            return int(max([ATR_PERIOD] + [int(v) for v in vals]) + 6)
        else:
            left_w = _window(node["left"])
            right_w = _window(node["right"]) if node.get("right") is not None else 0
            return max(left_w, right_w)
    return _window(_normalize_gene(gene))


# ---------------------------------------------------------------------------
# 基因解释器策略：把基因翻译成可回测的 StrategyBase
# ---------------------------------------------------------------------------
class GeneStrategy(StrategyBase):
    """自进化策略：入场由因子信号驱动，离场用 ATR 跟踪止损 + 可选止盈。"""

    name = "自进化策略"
    default_params: dict = {}

    def __init__(self, symbol: str, gene: dict):
        super().__init__(symbol, {})
        # 扁平基因（UI 手动回测 _manual_gene / 盈利库历史条目）归一化为树形，
        # 使 gene_window / _eval_signal 对两种格式都稳健（M4.6 树基因与
        # 旧扁平基因共存的契约缺口修复）。
        self.gene = self._merge_control(gene)
        self._stop: Optional[float] = None
        self._tp: Optional[float] = None

    @staticmethod
    def _merge_control(gene: dict) -> dict:
        """归一化树形节点并把控制参数字段并入叶子 params，使 on_bar 消费统一。

        旧扁平基因：{"entry","params","stop_mult","tp_mult","allow_long","allow_short","lots"}
        新树形基因：{"type":"factor","name","params"} 或 {"type":"op",...}
        控制字段可放在顶层或 params 内。统一后 on_bar 直接读 params，
        使 旧UI手动/盈利库历史条目 与 新进化树基因 都能驱动。
        """
        n = _normalize_gene(gene)
        if not isinstance(n, dict):
            n = {}
        out = dict(n)
        p = dict(out.get("params") or {})
        _CTRL = ("stop_mult", "tp_mult", "allow_long", "allow_short", "lots")
        for k in _CTRL:
            if k in out:
                p.setdefault(k, out[k])
            out.pop(k, None)
        out["params"] = p
        return out

    def _window_size(self) -> int:
        return gene_window(self.gene)

    def on_bar(self, bar: Bar) -> None:
        self._push(bar)
        g = self.gene
        if len(self._closes) < self._window_size() - 3:
            return
        a = atr_last(self._highs, self._lows, self._closes, ATR_PERIOD)
        if math.isnan(a) or a <= 0:
            return
        sig = _eval_signal(g, self._closes, self._highs, self._lows)
        if sig is None:
            return            # M2-12：因子计算失败 → 本 bar 不开仓（失败已由 factor_signal 记录日志）
        p = g.get("params") or {}
        stop_mult = float(p.get("stop_mult", 2.0))
        tp_mult = float(p.get("tp_mult", 0.0))
        allow_long = bool(p.get("allow_long", True))
        allow_short = bool(p.get("allow_short", True))
        lots = int(p.get("lots", 1))
        long_qty, short_qty = self.position()

        # ---- 持多仓：跟踪止损上移 / 止盈 / 反向信号离场 ----
        if long_qty > 0:
            self._stop = max(self._stop or -1e18,
                             bar.close - stop_mult * a)
            hit_tp = self._tp is not None and bar.close >= self._tp
            if bar.close < self._stop or hit_tp or sig == -1:
                self.send_order(Direction.SHORT, Offset.CLOSE, long_qty)
                self._stop = self._tp = None
            return
        # ---- 持空仓：对称处理 ----
        if short_qty > 0:
            self._stop = min(self._stop or 1e18,
                             bar.close + stop_mult * a)
            hit_tp = self._tp is not None and bar.close <= self._tp
            if bar.close > self._stop or hit_tp or sig == 1:
                self.send_order(Direction.LONG, Offset.CLOSE, short_qty)
                self._stop = self._tp = None
            return
        # ---- 空仓：按信号开仓 ----
        if sig == 1 and allow_long:
            self._stop = bar.close - stop_mult * a
            self._tp = (bar.close + tp_mult * a) if tp_mult else None
            self.send_order(Direction.LONG, Offset.OPEN, lots)
        elif sig == -1 and allow_short:
            self._stop = bar.close + stop_mult * a
            self._tp = (bar.close - tp_mult * a) if tp_mult else None
            self.send_order(Direction.SHORT, Offset.OPEN, lots)

# ---------------------------------------------------------------------------
# 适应度与盈利判定（加入稳定性维度）
# ---------------------------------------------------------------------------
def fitness(m: dict, gene: Optional[dict] = None) -> float:
    """综合适应度：多维度评估策略质量，加入稳定性（此处简化为夏普的绝对值，实际应跨品种一致性）。

    M2-06: 传入 `gene` 时叠加**树深惩罚**（超过 2 层每多一层扣 3 分），防止 GA 用深树硬拟合。
    """
    if not m:
        return -100.0
    
    sharpe = m.get("sharpe") or 0.0
    tr = m.get("total_return") or 0.0
    dd = m.get("max_drawdown") or 0.0
    wr = m.get("win_rate") or 0.0
    nt = m.get("num_closing_trades") or 0
    avg_win = m.get("avg_win") or 0.0
    avg_loss = m.get("avg_loss") or 0.0
    profit_factor = m.get("profit_factor") or 0.0
    max_consecutive_loss = m.get("max_consecutive_loss") or 0
    var_95 = m.get("var_95") or 0.0
    
    # 1. 夏普比率评分 (0-30分)
    sharpe_score = 30.0 * max(min(sharpe / 2.0, 1.0), -1.0)
    
    # 2. 卡玛比率评分 (0-20分)
    calmar = tr / dd if dd > 0 else 0.0
    calmar_score = 20.0 * max(min(calmar / 3.0, 1.0), -1.0)
    
    # 3. 总收益评分 (0-15分)
    return_score = 15.0 * max(min(tr / 0.5, 1.0), -1.0)
    
    # 4. 盈亏比评分 (0-15分)
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    payoff_score = 15.0 * max(min(payoff_ratio / 2.0, 1.0), -1.0)
    
    # 5. 胜率评分 (0-10分)
    wr_score = 10.0 * max(min(wr / 0.6, 1.0), -1.0)
    
    # 6. 交易充分性 (0.3-1.0 倍数)
    adequacy = 0.3 + 0.7 * min(nt / 20.0, 1.0)
    
    # 稳定性评分：这里简单用夏普的绝对值作为代理（实际应用中应计算跨品种夏普的一致性）
    stability_score = 10.0 * max(min(abs(sharpe) / 1.0, 1.0), 0.0)  # 0-10分
    
    # 惩罚项
    penalty = 0.0
    if nt < 10:
        penalty += (10 - nt) * 2.0
    if max_consecutive_loss > 5:
        penalty += (max_consecutive_loss - 5) * 3.0
    if var_95 < -0.05:
        penalty += abs(var_95) * 100
    # M2-06 奖励项
    bonus = 0.0
    if profit_factor > 1.5:
        bonus += (profit_factor - 1.5) * 5.0
    
    score = sharpe_score + calmar_score + return_score + payoff_score + wr_score + stability_score + bonus - penalty
    final_score = score * adequacy
    # M2-06 树深惩罚：绝对扣分（不受 adequacy 缩放），保证 spec 「penalty += 3 * max(0, depth-2)」字面成立
    if gene is not None:
        final_score -= validate.tree_depth_penalty(gene)
    return round(final_score, 2)


def is_profitable(m: dict, risk_trigger_count: int = 0, risk_trigger_threshold: int = 0,
                  oos_metrics: Optional[dict] = None) -> tuple[bool, list[str]]:
    """盈利判定：IS 段通过 + OOS 段一致（若提供）才算可盈利。

    M2-06: 新增 `oos_metrics` 参数——当传入时**强制要求** `oos.total_return > 0`
    且 `oos.sharpe >= 0`，否则降级为「仅观察」不入盈利库。
    """
    if not m:
        return False, ["无绩效数据"]
    reasons = []
    if (m.get("total_return") or 0) <= PROFIT_RULES["total_return"]:
        reasons.append(f"总收益 ≤ {PROFIT_RULES['total_return']*100:.0f}%")
    if (m.get("sharpe") or 0) < PROFIT_RULES["sharpe"]:
        reasons.append(f"夏普 < {PROFIT_RULES['sharpe']}")
    if (m.get("max_drawdown") or 1) > PROFIT_RULES["max_drawdown"]:
        reasons.append(f"回撤 > {PROFIT_RULES['max_drawdown']*100:.0f}%")
    if (m.get("win_rate") or 0) < PROFIT_RULES["win_rate"]:
        reasons.append(f"胜率 < {PROFIT_RULES['win_rate']*100:.0f}%")
    if (m.get("num_closing_trades") or 0) < PROFIT_RULES["num_closing_trades"]:
        reasons.append(f"交易 < {PROFIT_RULES['num_closing_trades']}笔")
    if risk_trigger_count > risk_trigger_threshold:
        reasons.append(f"风控触发次数 > {risk_trigger_threshold}")
    # M2-06 ②: OOS 段独立复核
    if oos_metrics is not None:
        oos_tr = float(oos_metrics.get("total_return") or 0)
        oos_sh = float(oos_metrics.get("sharpe") or 0)
        if oos_tr <= 0.0:
            reasons.append(f"OOS 总收益 ≤ 0（{oos_tr*100:.1f}%），降级为仅观察")
        if oos_sh < 0.0:
            reasons.append(f"OOS 夏普 < 0（{oos_sh:.2f}），降级为仅观察")
    return (len(reasons) == 0), reasons


# ---------------------------------------------------------------------------
# 盈利策略库（落盘 + 供 KP预测读取）
# ---------------------------------------------------------------------------
def load_profitable() -> list[dict]:
    """Load profitable strategies with fallback to backup.

    M1-04：读路径也用 RLock（与 save 共用），保证读到的是某一版完整 JSON 而非半截。
    RLock 允许 save_profitable 内部再调 load_profitable 不死锁。
    """
    with _STRATEGY_STORE_LOCK:
        def _load_json(path: str) -> list[dict]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("strategies", []) if isinstance(data, dict) else []
            except Exception:
                return []
        # Try main file first
        strategies = _load_json(STORE_PATH)
        if strategies:
            return strategies
        # Fallback to backup
        strategies = _load_json(BACKUP_PATH)
        if strategies:
            # Optionally restore main file from backup
            try:
                import shutil
                shutil.copy2(BACKUP_PATH, STORE_PATH)
            except Exception:
                pass
            return strategies
        return []


def save_profitable(new_entries: list[dict]) -> int:
    """保存盈利策略库。

    M1-04：整条临界区由模块级 RLock 保护；备份顺序修正为「先 copy 主→backup，再
    os.replace tmp→主」，避免 replace 失败时主文件消失（旧代码 replace 完再备份，
    若备份失败会丢失备份链）。
    """
    with _STRATEGY_STORE_LOCK:
        if not new_entries:
            return len(load_profitable())
        os.makedirs(STORE_DIR, exist_ok=True)
        lib = {(e.get("symbol"), e.get("signature")): e for e in load_profitable()}
        for e in new_entries:
            key = (e.get("symbol"), e.get("signature"))
            old = lib.get(key)
            if old is None or (e.get("fitness") or -1e9) > (old.get("fitness") or -1e9):
                lib[key] = e
        entries = sorted(lib.values(),
                         key=lambda x: x.get("fitness") or -1e9, reverse=True)
        per_sym: dict = {}
        kept = []
        for e in entries:
            n = per_sym.get(e.get("symbol"), 0)
            if n >= PER_SYMBOL_KEEP:
                continue
            per_sym[e.get("symbol")] = n + 1
            kept.append(e)
            if len(kept) >= MAX_STORE:
                break
        tmp = STORE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"updated_at": datetime.now().isoformat(timespec="seconds"),
                       "strategies": kept}, f, ensure_ascii=False, indent=1)
        # M1-04：先备份旧主→backup，再 os.replace tmp→主（保证备份链不丢）
        if os.path.exists(STORE_PATH):
            try:
                shutil.copy2(STORE_PATH, BACKUP_PATH)
            except Exception:
                logger.warning("备份策略库失败（继续写入）：STORE_PATH=%s", STORE_PATH)
        os.replace(tmp, STORE_PATH)
        # 首次写入（原主文件不存在）也确保有 .backup
        if not os.path.exists(BACKUP_PATH):
            try:
                shutil.copy2(STORE_PATH, BACKUP_PATH)
            except Exception:
                logger.warning("首次写入后备份失败：STORE_PATH=%s", STORE_PATH)
        return len(kept)


def make_entry(symbol: str, symbol_name: str, period: str, gene: dict,
               metrics: dict, fit: float) -> dict:
    return {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "period": period,
        "signature": gene_signature(gene),
        "gene": gene,
        "desc": describe_gene(gene),
        "metrics": {k: metrics.get(k) for k in
                    ("total_return", "annual_return", "sharpe", "max_drawdown",
                     "win_rate", "profit_factor", "num_closing_trades")},
        "fitness": fit,
        "found_at": datetime.now().isoformat(timespec="seconds"),
        "synced": True,
    }


def latest_signal_for(symbol: str, df) -> dict:
    out = {"n": 0, "bias": 0.0, "long": 0, "short": 0, "detail": []}
    try:
        entries = [e for e in load_profitable() if e.get("symbol") == symbol]
        if not entries or df is None or len(df) < 10:
            return out
        closes = [float(x) for x in df["close"].tolist()]
        highs = [float(x) for x in df["high"].tolist()]
        lows = [float(x) for x in df["low"].tolist()]
        regime = regime_of(closes)
        wsum = 0.0
        acc = 0.0
        for e in entries:
            gene = e.get("gene") or {}
            sig = ensemble_strategy_signal(gene, closes, highs, lows)
            base_w = max(float(e.get("fitness") or 1.0), 1.0)
            m = e.get("metrics") or {}
            sharpe = float(m.get("sharpe") or 0.0)
            wr = float(m.get("win_rate") or 0.0)
            qual = 0.5 + 0.4 * max(sharpe, 0.0) + 0.6 * max(wr - 0.3, 0.0)
            qual = max(0.25, min(2.5, qual))
            rmatch = _gene_regime_match(gene, regime)
            w = base_w * qual * rmatch
            acc += sig * w
            wsum += w
            if sig > 0:
                out["long"] += 1
            elif sig < 0:
                out["short"] += 1
            m = e.get("metrics") or {}
            out["detail"].append({
                "desc": e.get("desc", ""),
                "signal": sig,
                "fitness": e.get("fitness"),
                "total_return": m.get("total_return"),
                "sharpe": m.get("sharpe"),
            })
        out["n"] = len(entries)
        out["bias"] = round(max(-1.0, min(1.0, acc / wsum)), 3) if wsum else 0.0
    except Exception as e:
        # M2-12：移除「整体 except: pass」静默吞异常 —— 记录完整堆栈，
        # 并在返回值中标记 error，调用方据此显示「暂无进化信号」而非当作 bias=0
        logger.exception("latest_signal_for(%s) 计算异常", symbol)
        out["error"] = str(e)
    return out


# ---------------------------------------------------------------------------
# 进化引擎：一次 step() = 一代（生成 → 回测 → 排名 → 判定 → 落盘 → 换代）
# ---------------------------------------------------------------------------
class EvolutionEngine:
    POP_SIZE = 10
    ELITES = 2
    GENS_PER_SYMBOL = 4

    def __init__(self, feed, universe: list, start: str = "2000-01-01",
                 end: str = "2100-01-01", period: str = "D",
                 capital: float = 1_000_000.0, seed: Optional[int] = None,
                 futures_params: Optional[dict] = None, parallel: bool = False,
                 max_generations: int = 200, patience: int = 30, target_fitness: Optional[float] = None):
        self.feed = feed
        self.universe = list(universe)
        self.start, self.end, self.period = start, end, period
        self.capital = capital
        self.futures_params: dict = dict(futures_params or {})
        self.rng = random.Random(seed)
        # M2-09: 记录随机种子以支持可复现性
        self.seed = seed
        self.sym_idx = 0
        self.generation = 0
        self.gen_in_symbol = 0
        self.population: Optional[list] = None
        self.evaluated_total = 0
        self.profitable_total = len(load_profitable())
        self.best_overall: Optional[dict] = None
        self._sym_best_curve: Optional[list] = None
        # M2-07: Fitness cache for performance optimization
        self._fit_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self._data_version = f"{start}_{end}_{period}"
        # M2-07: Parallel execution control (default False for offscreen e2e stability)
        self._parallel = parallel
        # M2-08: Termination conditions and experiment recording
        self.max_generations = max_generations
        self.patience = patience
        self.target_fitness = target_fitness
        self._best_fitness = -float('inf')
        self._stagnation_count = 0
        self._experiment = {
            "seed": seed,
            "data_start": start,
            "data_end": end,
            "params": {
                "period": period,
                "capital": capital,
                "max_generations": max_generations,
                "patience": patience,
                "target_fitness": target_fitness,
                "universe": [u[0] for u in universe],
            },
            "started_at": datetime.now().isoformat(),
            "git_rev": _get_git_rev(),
        }

    def to_state(self) -> dict:
        return {
            "version": 1,
            "sym_idx": self.sym_idx,
            "generation": self.generation,
            "gen_in_symbol": self.gen_in_symbol,
            "population": self.population,
            "evaluated_total": self.evaluated_total,
            "profitable_total": self.profitable_total,
            "best_overall": self.best_overall,
            "sym_best_curve": self._sym_best_curve,
            "period": self.period,
            "futures_params": self.futures_params,
            # M2-08: Experiment record
            "experiment": self._experiment,
            "max_generations": self.max_generations,
            "patience": self.patience,
            "target_fitness": self.target_fitness,
            "best_fitness": self._best_fitness,
            "stagnation_count": self._stagnation_count,
            # M2-09: 可复现性 —— 保存 seed 与 RNG 完整状态
            "seed": self.seed,
            "rng_state": self._dump_rng_state(),
        }

    def _dump_rng_state(self) -> Optional[list]:
        """M2-09：把 `random.Random` 状态序列化为 JSON 友好的嵌套 list。

        `Random.getstate()` 返回 `(version, tuple(625 ints), gauss_next)`，
        元组无法直接进 JSON，这里逐层转 list；失败时返回 None（降级：仅靠 seed 重建）。
        """
        try:
            version, internal, gauss = self.rng.getstate()
            return [int(version),
                    [int(x) for x in internal],
                    (None if gauss is None else float(gauss))]
        except Exception:
            return None

    @staticmethod
    def _load_rng_state(rng: random.Random, data) -> bool:
        """M2-09：把 `_dump_rng_state` 的产出还原进 rng。"""
        if not isinstance(data, list) or len(data) != 3:
            return False
        try:
            version = int(data[0])
            internal = tuple(int(x) for x in data[1])
            gauss = None if data[2] is None else float(data[2])
            rng.setstate((version, internal, gauss))
            return True
        except Exception:
            return False

    def restore_state(self, st: dict) -> bool:
        try:
            if not st or int(st.get("version", 0)) != 1:
                return False
            self.sym_idx = int(st.get("sym_idx", 0)) % max(len(self.universe), 1)
            self.generation = int(st.get("generation", 0))
            self.gen_in_symbol = int(st.get("gen_in_symbol", 0))
            pop = st.get("population")
            self.population = pop if isinstance(pop, list) and pop else None
            self.evaluated_total = int(st.get("evaluated_total", 0))
            # M2-09: profitable_total 恢复存档值，而非当前库实际长度
            # （库可能被外部增删，存档值才是与该断点配套的一致口径）
            self.profitable_total = int(st.get("profitable_total", len(load_profitable())))
            bo = st.get("best_overall")
            self.best_overall = bo if isinstance(bo, dict) else None
            curve = st.get("sym_best_curve")
            self._sym_best_curve = curve if isinstance(curve, list) else None
            fp = st.get("futures_params")
            if isinstance(fp, dict):
                self.futures_params = fp
            # M2-08: Restore experiment data
            if "experiment" in st and isinstance(st["experiment"], dict):
                self._experiment = st["experiment"]
            if "max_generations" in st:
                self.max_generations = int(st["max_generations"])
            if "patience" in st:
                self.patience = int(st["patience"])
            if "target_fitness" in st:
                self.target_fitness = st["target_fitness"]
            if "best_fitness" in st:
                self._best_fitness = float(st["best_fitness"])
            if "stagnation_count" in st:
                self._stagnation_count = int(st["stagnation_count"])
            # M2-09: 可复现性 —— 恢复 seed 与 RNG 状态
            if "seed" in st:
                self.seed = st["seed"]
            rng_state = st.get("rng_state")
            if rng_state is not None:
                self._load_rng_state(self.rng, rng_state)
            return True
        except Exception:
            return False

    def _row(self):
        return self.universe[self.sym_idx % len(self.universe)]

    def symbol(self) -> str:
        r = self._row()
        return f"{r[0]}.{r[3]}"

    def symbol_name(self) -> str:
        return self._row()[1]

    def _contract(self):
        from ..data.base import Contract
        r = self._row()
        fp = self.futures_params
        return Contract(symbol=self.symbol(), exchange=r[3],
                        multiplier=float(fp.get("multiplier", r[4])),
                        min_price_tick=float(r[5]),
                        lot_size=1,
                        margin_rate=float(fp.get("margin_rate", 0.10)),
                        commission_per_lot=float(fp.get("commission_per_lot", 3.0)),
                        trading_hours=None,
                        delivery_date=fp.get("delivery_date"),
                        leverage=fp.get("leverage"),
                        close_today_commission_ratio=float(fp.get("close_today_ratio", 0.5)))

    def _config(self):
        from ..config.settings import Config
        cfg = Config()
        fp = self.futures_params
        lev = float(fp.get("leverage", 10.0))
        margin_rate = float(fp.get("margin_rate", 1.0 / lev))
        mult = float(fp.get("multiplier", self._row()[4]))
        cfg.account.leverage = lev
        cfg.account.margin_rate = margin_rate
        cfg.account.multiplier = mult
        cfg.account.close_today_ratio = float(fp.get("close_today_ratio", 0.5))
        if not cfg.risk.strict_mode:
            cfg.risk.max_single_loss = 1e12
            cfg.risk.max_daily_loss = 1e12
        cfg.risk.max_drawdown = 0.99
        cfg.risk.max_position_per_symbol = 100
        cfg.risk.max_total_position_ratio = 0.98
        cfg.risk.max_order_qty = 100
        cfg.backtest.start_cash = self.capital
        cfg.account.initial_capital = self.capital
        return cfg

    def _seed_population(self) -> list:
        pop = []
        seeds = [e["gene"] for e in load_profitable()
                 if e.get("symbol") == self.symbol()][:3]
        for g in seeds:
            # M2-01：种子可能来自旧版扁平基因库，先归一化再繁育
            ng = _normalize_gene(g)
            pop.append(json.loads(json.dumps(ng)))
            pop.append(mutate(ng, self.rng))
        while len(pop) < self.POP_SIZE:
            pop.append(random_gene(self.rng))
        return pop[:self.POP_SIZE]
    def _evaluate_fitness_only(self, gene: dict, sym: Optional[str] = None) -> float:
        """M2-06 参数邻域评估专用：只算 fitness，不走 IS/OOS + 邻域验证（避免递归）。

        优先走 M2-07 的 ``_fit_cache``；缓存未命中时独立回测一次并写入缓存。
        """
        from ..backtest.backtester import Backtester
        sym = sym if sym is not None else self.symbol()
        gene_sig = gene_signature(gene)
        cache_key = f"{gene_sig}|{self._data_version}"
        if cache_key in self._fit_cache:
            _, cached_fitness = self._fit_cache[cache_key]
            return float(cached_fitness)
        try:
            bt = Backtester(self._config(), self.feed)
            bt.add_contract(self._contract())
            bt.add_strategy(GeneStrategy(sym, gene))
            res = bt.run(sym, self.start, self.end, self.period, warmup=60)
            m = res["metrics"]
            f = float(fitness(m, gene=gene))
        except Exception as e:  # noqa: BLE001
            logger.warning("邻域变体回测失败（gene=%s）：%s", gene_sig, e)
            return 0.0
        self._fit_cache[cache_key] = (gene, f)
        return f

    def _evaluate(self, gene: dict) -> dict:
        # M2-07: Check fitness cache first to avoid re-backtesting identical genes
        gene_sig = gene_signature(gene)
        cache_key = f"{gene_sig}|{self._data_version}"
        if cache_key in self._fit_cache:
            # Return cached fitness with a flag to indicate cache hit
            # The caller will need to handle this appropriately
            cached_gene, cached_fitness = self._fit_cache[cache_key]
            return {"_cache_hit": True, "_cache_key": cache_key, 
                   "_cached_fitness": cached_fitness, "_cached_gene": cached_gene}
        
        from ..backtest.backtester import Backtester
        sym = self.symbol()
        bt = Backtester(self._config(), self.feed)
        bt.add_contract(self._contract())
        bt.add_strategy(GeneStrategy(sym, gene))
        res = bt.run(sym, self.start, self.end, self.period, warmup=60)
        m = res["metrics"]
        # M2-06: 传入 gene 让 fitness 叠加树深惩罚（超过 2 层每多一层扣 3 分）
        fit = fitness(m, gene=gene)
        risk_trigger_count = bt.engine.risk._trigger_count
        risk_trigger_threshold = self._config().risk.risk_trigger_threshold
        
        # Existing profitability check
        ok_base, reasons_base = is_profitable(m, risk_trigger_count, risk_trigger_threshold)
        
        # Overfitting protection check (M2-06)
        ok_valid, reasons_valid, validation_metrics = validate.validate_strategy(
            gene, self._config(), self.feed, self._contract(), sym,
            self.start, self.end, self.period, warmup=60,
            generation_num=self.generation, population_size=self.POP_SIZE,
            _evaluator=lambda g: self._evaluate_fitness_only(g, sym)
        )
        
        # M2-06: 把 OOS 段结果显式喂给 is_profitable 做二次确认（defense-in-depth）
        # validate.validate_strategy 已经要求 OOS 通过；这里再检查一遍，理由会合并进 reasons
        oos_metrics = validation_metrics.get("oos_metrics") if isinstance(validation_metrics, dict) else None
        if ok_base and ok_valid and oos_metrics:
            oos_ok, oos_reasons = is_profitable(m, risk_trigger_count, risk_trigger_threshold,
                                                oos_metrics=oos_metrics)
            if not oos_ok:
                ok_valid = False
                reasons_valid.extend(oos_reasons)
        
        # Combine results: strategy is profitable only if both checks pass
        ok = ok_base and ok_valid
        reasons = reasons_base + reasons_valid
        
        result = {"gene": gene, "desc": describe_gene(gene),
                "signature": gene_signature(gene), "metrics": m,
                "fitness": fit, "profitable": ok, "reasons": reasons,
                "equity_curve": res["equity_curve"],
                "trades": res.get("trades", [])}
        
# M2-07: Store in cache for future use
        self._fit_cache[cache_key] = (gene, fit)
        
        return result

    def step(self, should_abort: "Optional[Callable[[], bool]]" = None,
              on_progress: "Optional[Callable[[int, int, str], None]]" = None) -> dict:
        """执行一代进化：生成 → 回测 → 排名 → 判定 → 落盘 → 换代

        M4-09：支持协作式中断与实时进度上报（不改动既有业务逻辑）。

        参数:
            should_abort: Optional[Callable[[], bool]]
                由 UI 注入的中断谓词；返回 True 时本代在当前基因评估后抛出
                ``InterruptionError``，由 ``Worker.run`` 转为 ``interrupted`` 信号。
            on_progress: Optional[Callable[[int, int, str], None]]
                每评估完一个基因回调一次 ``(done, total, text)``，供进度条/状态灯更新。
        """
        # M2-08: Check if evolution is already terminated
        if self.generation > 0:
            max_gen_reached = self.generation >= self.max_generations
            patience_reached = self._stagnation_count >= self.patience
            target_reached = (self.target_fitness is not None and 
                             self._best_fitness >= self.target_fitness)
            if max_gen_reached or patience_reached or target_reached:
                # Evolution already terminated, return empty snapshot with termination info
                return {
                    "generation": self.generation,
                    "evolution_done": True,
                    "termination_reason": (
                        f"已达最大代数上限 ({self.max_generations})" if max_gen_reached else
                        f"已停滞 {self.patience} 代无改进" if patience_reached else
                        f"已达到目标适应度 ({self.target_fitness})"
                    ),
                    "experiment": self._experiment,
                    "best_fitness": self._best_fitness,
                    "stagnation_count": self._stagnation_count,
                }
        
        sym, sym_name = self.symbol(), self.symbol_name()
        if self.population is None:
            self.population = self._seed_population()
            self._sym_best_curve = None

        # M2-07: Load profitable strategies once per generation (instead of per evaluation)
        profitable_strategies = load_profitable()
        self.profitable_total = len(profitable_strategies)
        
        # M2-07: Evaluate population with caching and optional parallel execution
        results = []
        # M2-12: 本代评估失败计数（原 except: continue 静默吞异常，现统计并告警）
        failed_count = 0
        
        if self._parallel and len(self.population) > 1:
            # Parallel evaluation using ProcessPoolExecutor
            # We'll evaluate non-cached genes in parallel, then combine results
            uncached_genes = []
            cached_results = {}
            
            # First pass: identify cached genes and collect uncached ones
            for i, gene in enumerate(self.population):
                gene_sig = gene_signature(gene)
                cache_key = f"{gene_sig}|{self._data_version}"
                if cache_key in self._fit_cache:
                    # Cache hit: use cached fitness
                    cached_gene, cached_fitness = self._fit_cache[cache_key]
                    # Create a minimal result structure for cached genes
                    # We'll need to run a quick evaluation to get the full result for linkage notification
                    # For now, let's mark it for later full evaluation if needed for linkage
                    cached_results[i] = {"_cache_hit": True, "_cache_key": cache_key, 
                                       "_cached_fitness": cached_fitness, "_index": i}
                else:
                    uncached_genes.append((i, gene))
            
            # Evaluate uncached genes in parallel
            if uncached_genes:
                # Prepare evaluation function for parallel execution
                def evaluate_gene_pair(index_gene_tuple):
                    index, gene = index_gene_tuple
                    try:
                        from ..backtest.backtester import Backtester
                        sym = self.symbol()
                        bt = Backtester(self._config(), self.feed)
                        bt.add_contract(self._contract())
                        bt.add_strategy(GeneStrategy(sym, gene))
                        res = bt.run(sym, self.start, self.end, self.period, warmup=60)
                        m = res["metrics"]
                        fit = fitness(m)
                        risk_trigger_count = bt.engine.risk._trigger_count
                        risk_trigger_threshold = self._config().risk.risk_trigger_threshold
                        
                        # Existing profitability check
                        ok_base, reasons_base = is_profitable(m, risk_trigger_count, risk_trigger_threshold)
                        
                        # Overfitting protection check (M2-06)
                        ok_valid, reasons_valid, validation_metrics = validate.validate_strategy(
                            gene, self._config(), self.feed, self._contract(), sym,
                            self.start, self.end, self.period, warmup=60,
                            generation_num=self.generation, population_size=self.POP_SIZE
                        )
                        
                        # Combine results: strategy is profitable only if both checks pass
                        ok = ok_base and ok_valid
                        reasons = reasons_base + reasons_valid
                        
                        result = {"gene": gene, "desc": describe_gene(gene),
                                "signature": gene_signature(gene), "metrics": m,
                                "fitness": fit, "profitable": ok, "reasons": reasons,
                                "equity_curve": res["equity_curve"],
                                "trades": res.get("trades", [])}
                        
                        # Store in cache
                        gene_sig = gene_signature(gene)
                        cache_key = f"{gene_sig}|{self._data_version}"
                        self._fit_cache[cache_key] = (gene, fit)
                        
                        return index, result
                    except Exception as e:
                        logger.warning("基因评估失败: %s", e)
                        return index, None
                
                # Execute parallel evaluation
                max_workers = min(4, multiprocessing.cpu_count())
                with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    future_to_index = {executor.submit(evaluate_gene_pair, ug): ug[0] for ug in uncached_genes}
                    total = len(uncached_genes)
                    done = 0
                    gen_no = self.generation + 1
                    for future in concurrent.futures.as_completed(future_to_index):
                        index = future_to_index[future]
                        try:
                            result = future.result()
                            if result is not None:
                                idx, res = result
                                if res is not None:
                                    results.append((idx, res))
                        except Exception as e:
                            logger.warning("并行评估任务失败: %s", e)
                        # M4-09：并行路径逐任务上报进度（无法在中途中止子进程，
                        # 「停止」在代边界经 _evolution_stopped 生效）
                        done += 1
                        if on_progress is not None:
                            try:
                                on_progress(done, total, f"基因 {done}/{total}")
                            except Exception:  # noqa: BLE001
                                pass
            
            # Process cached genes (need full evaluation for linkage notification if profitable)
            for i, gene in enumerate(self.population):
                gene_sig = gene_signature(gene)
                cache_key = f"{gene_sig}|{self._data_version}"
                if cache_key in self._fit_cache:
                    # Cache hit: we need to check if it's profitable for linkage notification
                    # Run a lightweight check to determine profitability without full backtest
                    # For simplicity, we'll re-evaluate if it might be profitable for linkage
                    # In practice, we could store more in the cache, but let's keep it simple
                    cached_gene, cached_fitness = self._fit_cache[cache_key]
                    
                    # Quick profitability check using cached fitness and basic metrics
                    # This is approximate - for exact linkage notification, we'd need full eval
                    # But since linkage is only for profitable strategies, and we have fitness,
                    # we can approximate: if cached_fitness is high enough, it's likely profitable
                    # Let's do a quick check: if fitness > 0, run full eval for linkage
                    if cached_fitness > 0:  # Arbitrary threshold, could be improved
                        # Need full evaluation for accurate linkage notification
                        try:
                            from ..backtest.backtester import Backtester
                            sym = self.symbol()
                            bt = Backtester(self._config(), self.feed)
                            bt.add_contract(self._contract())
                            bt.add_strategy(GeneStrategy(sym, gene))
                            res = bt.run(sym, self.start, self.end, self.period, warmup=60)
                            m = res["metrics"]
                            fit = fitness(m)
                            risk_trigger_count = bt.engine.risk._trigger_count
                            risk_trigger_threshold = self._config().risk.risk_trigger_threshold
                            
                            # Existing profitability check
                            ok_base, reasons_base = is_profitable(m, risk_trigger_count, risk_trigger_threshold)
                            
                            # Overfitting protection check (M2-06)
                            ok_valid, reasons_valid, validation_metrics = validate.validate_strategy(
                                gene, self._config(), self.feed, self._contract(), sym,
                                self.start, self.end, self.period, warmup=60,
                                generation_num=self.generation, population_size=self.POP_SIZE
                            )
                            
                            # Combine results: strategy is profitable only if both checks pass
                            ok = ok_base and ok_valid
                            reasons = reasons_base + reasons_valid
                            
                            result = {"gene": gene, "desc": describe_gene(gene),
                                    "signature": gene_signature(gene), "metrics": m,
                                    "fitness": fit, "profitable": ok, "reasons": reasons,
                                    "equity_curve": res["equity_curve"],
                                    "trades": res.get("trades", [])}
                            
                            # Update cache with full result info (though we mainly cached fitness)
                            self._fit_cache[cache_key] = (gene, fit)
                            
                            if result["profitable"]:
                                BUS.push_backtest_result(
                                    symbol=sym,
                                    gene=result["gene"],
                                    metrics=result["metrics"],
                                    direction_bias=None,
                                    regime=None
                                )
                            results.append((i, result))
                        except Exception:
                            # If full eval fails, skip linkage notification but keep cached result
                            results.append((i, {"gene": gene, "fitness": cached_fitness, "_cache_hit": True}))
                    else:
                        # Low fitness, unlikely to be profitable, skip linkage notification
                        results.append((i, {"gene": gene, "fitness": cached_fitness, "_cache_hit": True}))
                else:
                    # Uncached gene - should have been processed in parallel section
                    pass
            
            # Sort results by index to maintain order
            results.sort(key=lambda x: x[0])
            # Extract just the result objects
            results = [r[1] for r in results if r[1] is not None]
        else:
            # Sequential evaluation (default for offscreen e2e stability)
            total = len(self.population)
            done = 0
            gen_no = self.generation + 1
            for idx, gene in enumerate(self.population):
                # M4-09：协作式中断（基因粒度检查，保证「停止」能及时生效）
                if should_abort is not None and should_abort():
                    raise InterruptionError(
                        f"进化被用户中断（第 {gen_no} 代 · 基因 {done}/{total}）")
                try:
                    result = self._evaluate(gene)
                    # Handle cache hit from _evaluate method
                    if result.get("_cache_hit"):
                        # This is a cache hit - we need to check if profitable for linkage
                        gene_sig = gene_signature(result["gene"])
                        cache_key = f"{gene_sig}|{self._data_version}"
                        if cache_key in self._fit_cache:
                            cached_gene, cached_fitness = self._fit_cache[cache_key]
                            # For linkage notification, we need to know if it's actually profitable
                            # Since we only cached fitness, we'll do a quick check
                            # In a full implementation, we might cache more info
                            # For now, if fitness > 0, we'll do a quick evaluation for linkage
                            if cached_fitness > 0:
                                try:
                                    from ..backtest.backtester import Backtester
                                    sym = self.symbol()
                                    bt = Backtester(self._config(), self.feed)
                                    bt.add_contract(self._contract())
                                    bt.add_strategy(GeneStrategy(sym, result["gene"]))
                                    res = bt.run(sym, self.start, self.end, self.period, warmup=60)
                                    m = res["metrics"]
                                    fit = fitness(m)
                                    risk_trigger_count = bt.engine.risk._trigger_count
                                    risk_trigger_threshold = self._config().risk.risk_trigger_threshold
                                    
                                    # Existing profitability check
                                    ok_base, reasons_base = is_profitable(m, risk_trigger_count, risk_trigger_threshold)
                                    
                                    # Overfitting protection check (M2-06)
                                    ok_valid, reasons_valid, validation_metrics = validate.validate_strategy(
                                        result["gene"], self._config(), self.feed, self._contract(), sym,
                                        self.start, self.end, self.period, warmup=60,
                                        generation_num=self.generation, population_size=self.POP_SIZE
                                    )
                                    
                                    # Combine results: strategy is profitable only if both checks pass
                                    ok = ok_base and ok_valid
                                    reasons = reasons_base + reasons_valid
                                    
                                    result = {"gene": result["gene"], "desc": describe_gene(result["gene"]),
                                            "signature": gene_signature(result["gene"]), "metrics": m,
                                            "fitness": fit, "profitable": ok, "reasons": reasons,
                                            "equity_curve": res["equity_curve"],
                                            "trades": res.get("trades", [])}
                                except Exception:
                                    # If we can't do full eval, skip linkage but keep the gene
                                    pass
                            
                            # Check if profitable for linkage notification
                            if result.get("profitable", False):
                                BUS.push_backtest_result(
                                    symbol=sym,
                                    gene=result["gene"],
                                    metrics=result["metrics"],
                                    direction_bias=None,
                                    regime=None
                                )
                    else:
                        # Regular evaluation result
                        if result.get("profitable", False):
                            BUS.push_backtest_result(
                                symbol=sym,
                                gene=result["gene"],
                                metrics=result["metrics"],
                                direction_bias=None,
                                regime=None
                            )
                    results.append(result)
                except InterruptionError:
                    # 中断信号不可被吞：原样上抛，由 Worker 转为 interrupted
                    raise
                except Exception as e:
                    # M2-12：原为静默 continue，现记录日志并计入失败数
                    failed_count += 1
                    logger.warning("本代基因评估失败（已跳过）：%s", e)
                # M4-09：每评估完一个基因上报进度（成功/失败均计入分母）
                done += 1
                if on_progress is not None:
                    try:
                        on_progress(done, total, f"基因 {done}/{total}")
                    except Exception:  # noqa: BLE001
                        pass
        # M2-12: 失败率 >30% 时向 UI 抛告警
        pop_n = len(self.population or [])
        fail_warn = None
        if pop_n and failed_count / pop_n > 0.30:
            fail_warn = f"本代 {failed_count}/{pop_n} 评估失败"
            logger.warning("进化引擎评估失败率过高：%s", fail_warn)
        self.evaluated_total += len(results)
        results.sort(key=lambda x: x["fitness"], reverse=True)

        new_entries = [make_entry(sym, sym_name, self.period,
                                  r["gene"], r["metrics"], r["fitness"])
                       for r in results if r["profitable"]]
        if new_entries:
            self.profitable_total = save_profitable(new_entries)
        else:
            self.profitable_total = len(load_profitable())

        gen_best = results[0] if results else None
        if gen_best is not None:
            self._sym_best_curve = gen_best["equity_curve"]
            if (self.best_overall is None
                    or gen_best["fitness"] > self.best_overall["fitness"]):
                self.best_overall = {
                    "symbol": sym, "symbol_name": sym_name,
                    "desc": gen_best["desc"], "fitness": gen_best["fitness"],
                    "metrics": gen_best["metrics"],
                    "equity_curve": gen_best["equity_curve"],
                }

        next_pop = [json.loads(json.dumps(r["gene"]))
                    for r in results[:self.ELITES]]
        # M2-01(B3)：繁育循环整体包 try，异常时降级为随机基因，避免整代作废
        try:
            while len(next_pop) < self.POP_SIZE and results:
                a = self._tournament(results)
                b = self._tournament(results)
                child = crossover(a, b, self.rng) if self.rng.random() < 0.6 \
                    else json.loads(json.dumps(a))
                if self.rng.random() < 0.5:
                    child = mutate(child, self.rng)
                next_pop.append(child)
        except Exception as e:
            logger.warning("繁育循环异常，降级为随机基因：%s", e)
        while len(next_pop) < self.POP_SIZE:
            next_pop.append(random_gene(self.rng))

        self.generation += 1
        self.gen_in_symbol += 1
        
        # M2-08: Track best fitness for termination conditions
        if gen_best is not None:
            current_fitness = gen_best["fitness"]
            if current_fitness > self._best_fitness:
                self._best_fitness = current_fitness
                self._stagnation_count = 0
            else:
                self._stagnation_count += 1
        
        # M2-08: Check termination conditions
        max_gen_reached = self.generation >= self.max_generations
        patience_reached = self._stagnation_count >= self.patience
        target_reached = (self.target_fitness is not None and 
                         self._best_fitness >= self.target_fitness)
        evolution_done = max_gen_reached or patience_reached or target_reached
        
        snapshot = {
            "generation": self.generation,
            "gen_in_symbol": self.gen_in_symbol,
            "gens_per_symbol": self.GENS_PER_SYMBOL,
            "symbol": sym, "symbol_name": sym_name,
            "period": self.period,
            "ranked": [{k: r[k] for k in
                        ("desc", "signature", "gene", "metrics", "fitness",
                         "profitable", "reasons")} for r in results],
            "gen_best_curve": gen_best["equity_curve"] if gen_best else [],
            "gen_best_trades": gen_best.get("trades", []) if gen_best else [],
            "best_overall": self.best_overall,
            "new_profitable": new_entries,
            "evaluated_total": self.evaluated_total,
            "profitable_total": self.profitable_total,
            "library": load_profitable(),
            "symbol_done": self.gen_in_symbol >= self.GENS_PER_SYMBOL,
            # M2-12: 评估失败统计（供 UI 显示「本代 n/10 评估失败」）
            "failed_count": failed_count,
            "eval_fail_warn": fail_warn,
            # M2-08: Termination info and experiment record
            "experiment": self._experiment,
            "max_generations": self.max_generations,
            "patience": self.patience,
            "target_fitness": self.target_fitness,
            "best_fitness": self._best_fitness,
            "stagnation_count": self._stagnation_count,
            "termination_reason": None,
            "evolution_done": evolution_done,
        }
        
        # Determine termination reason
        if max_gen_reached:
            snapshot["termination_reason"] = f"已达最大代数上限 ({self.max_generations})"
        elif patience_reached:
            snapshot["termination_reason"] = f"已停滞 {self.patience} 代无改进"
        elif target_reached:
            snapshot["termination_reason"] = f"已达到目标适应度 ({self.target_fitness})"

        if self.gen_in_symbol >= self.GENS_PER_SYMBOL:
            self.sym_idx = (self.sym_idx + 1) % len(self.universe)
            self.gen_in_symbol = 0
            self.population = None
            snapshot["next_symbol"] = self.symbol()
            snapshot["next_symbol_name"] = self.symbol_name()
        else:
            self.population = next_pop
        return snapshot

    def _tournament(self, results: list, k: int = 3) -> dict:
        cand = self.rng.sample(results, k=min(k, len(results)))
        return max(cand, key=lambda x: x["fitness"])["gene"]