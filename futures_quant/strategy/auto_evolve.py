"""全自动自我学习策略进化引擎（回测中心核心）。

系统闭环（零用户操作）：
    ① 因子生成：由「基因」随机组合入场因子（均线交叉/通道突破/RSI反转/
       布林突破/布林回归/动量）与风控参数（ATR止损倍数/止盈倍数/多空许可）；
    ② 自动回测：每个基因经 GeneStrategy 解释后送入项目回测引擎跑历史行情；
    ③ 迭代优化：遗传算法（精英保留 + 锦标赛选择 + 交叉 + 变异）逐代进化，
       适应度综合 夏普 / 总收益 / 回撤 / 胜率 / 成交充分性；
    ④ 盈利判定：多阈值联合判定（收益、夏普、回撤、胜率、交易数）；
    ⑤ 自动同步：判定盈利的策略落盘 data/auto_strategies/，
       「AI预测」模块通过 latest_signal_for() 读取并把策略信号融合进预测。

诚实声明：默认合成行情下的结论仅验证方法有效性，不可外推真实市场。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from datetime import datetime
from typing import Optional, Sequence

from ..core.indicators import (
    atr_last, bollinger_last, donchian_last, rsi_last, sma_last,
)
from ..core.types import Bar, Direction, Offset
from .base import StrategyBase

# 项目根目录（futures_quant/strategy -> futures_quant -> root）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE_DIR = os.path.join(ROOT, "data", "auto_strategies")
STORE_PATH = os.path.join(STORE_DIR, "profitable_strategies.json")
MAX_STORE = 60          # 盈利策略库容量上限（按适应度淘汰）
PER_SYMBOL_KEEP = 6     # 每个品种最多保留的盈利策略数

# ---------------------------------------------------------------------------
# 基因空间：入场因子 × 参数档位 × 风控参数
# ---------------------------------------------------------------------------
ENTRY_FACTORS = ["ma_cross", "donchian_break", "rsi_reversal",
                 "boll_break", "boll_revert", "momentum"]
FACTOR_LABEL = {
    "ma_cross": "双均线交叉",
    "donchian_break": "唐奇安通道突破",
    "rsi_reversal": "RSI超买超卖反转",
    "boll_break": "布林带突破",
    "boll_revert": "布林带均值回归",
    "momentum": "动量追踪",
}
PARAM_SPACE = {
    "ma_cross": {"fast": [3, 5, 8, 10, 12, 15], "slow": [20, 30, 40, 60]},
    "donchian_break": {"period": [10, 15, 20, 30, 40]},
    "rsi_reversal": {"period": [7, 10, 14, 21],
                     "low": [20, 25, 30, 35], "high": [65, 70, 75, 80]},
    "boll_break": {"period": [15, 20, 30], "num_std": [1.5, 2.0, 2.5]},
    "boll_revert": {"period": [15, 20, 30], "num_std": [1.5, 2.0, 2.5]},
    "momentum": {"period": [5, 10, 20, 40], "th": [0.01, 0.02, 0.03, 0.05]},
}
STOP_MULTS = [1.5, 2.0, 2.5, 3.0]
TP_MULTS = [0.0, 2.0, 3.0, 4.0, 6.0]   # 0 = 不设固定止盈，仅跟踪止损
ATR_PERIOD = 14

# 盈利判定阈值（联合满足才算「可盈利」）
# 阈值依据真实样本回测分布标定（rb.SHFE 日线 2009–2026，单基因因子+ATR止损）：
#   原 sharpe≥0.8 / total_return>5% 在 17 年长周期上几乎不可达（实测最佳 sharpe≈0.47、
#   return≈5%），导致盈利库长期为空。下调到「正向盈利 + 正风险调整收益 + 充分样本」
#   的现实门槛，使自我学习引擎能稳定沉淀可复用策略。
PROFIT_RULES = {
    "total_return": 0.02,      # 总收益 > 2%（正向盈利，过滤微亏/临界）
    "sharpe": 0.3,             # 夏普 ≥ 0.3（正的风险调整收益，过滤负 Sharpe）
    "max_drawdown": 0.35,      # 最大回撤 ≤ 35%（安全垫，长周期普遍满足）
    "win_rate": 0.35,          # 胜率 ≥ 35%（质量信号，长周期普遍满足）
    "num_closing_trades": 6,   # 平仓交易 ≥ 6 笔（避免样本过少的伪盈利）
}


# ---------------------------------------------------------------------------
# 基因操作
# ---------------------------------------------------------------------------
def random_gene(rng: random.Random) -> dict:
    """随机生成一个策略基因。"""
    entry = rng.choice(ENTRY_FACTORS)
    params = {k: rng.choice(v) for k, v in PARAM_SPACE[entry].items()}
    # 双均线约束：快线必须小于慢线
    if entry == "ma_cross" and params["fast"] >= params["slow"]:
        params["fast"] = rng.choice([3, 5, 8])
    gene = {
        "entry": entry,
        "params": params,
        "stop_mult": rng.choice(STOP_MULTS),
        "tp_mult": rng.choice(TP_MULTS),
        "allow_long": True,
        "allow_short": rng.random() < 0.85,   # 少量纯多基因增加多样性
        "lots": 1,
    }
    if not gene["allow_short"] and rng.random() < 0.5:
        gene["allow_long"], gene["allow_short"] = True, True
    return gene


def gene_signature(gene: dict) -> str:
    """基因签名（用于去重）。"""
    payload = json.dumps(
        {k: gene[k] for k in ("entry", "params", "stop_mult", "tp_mult",
                              "allow_long", "allow_short")},
        sort_keys=True, ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


def describe_gene(gene: dict) -> str:
    """基因的中文描述（用于 UI 展示）。"""
    entry = gene["entry"]
    p = gene["params"]
    if entry == "ma_cross":
        core = f"双均线交叉(快{p['fast']}/慢{p['slow']})"
    elif entry == "donchian_break":
        core = f"通道突破({p['period']}期)"
    elif entry == "rsi_reversal":
        core = f"RSI反转({p['period']}期,{p['low']}/{p['high']})"
    elif entry == "boll_break":
        core = f"布林突破({p['period']},{p['num_std']}σ)"
    elif entry == "boll_revert":
        core = f"布林回归({p['period']},{p['num_std']}σ)"
    else:
        core = f"动量({p['period']}期,阈{p['th']*100:.0f}%)"
    tp = f"止盈×{gene['tp_mult']}" if gene.get("tp_mult") else "跟踪离场"
    side = ("多空双向" if gene.get("allow_long") and gene.get("allow_short")
            else ("仅做多" if gene.get("allow_long") else "仅做空"))
    return f"{core} + ATR止损×{gene['stop_mult']} + {tp} · {side}"


def mutate(gene: dict, rng: random.Random) -> dict:
    """变异：小概率换因子，大概率微调参数/风控。"""
    g = json.loads(json.dumps(gene))
    if rng.random() < 0.20:
        return random_gene(rng)  # 大变异：整体重掷，保持探索
    entry = g["entry"]
    space = PARAM_SPACE[entry]
    # 随机挑 1~2 个参数重掷
    keys = list(space.keys())
    for k in rng.sample(keys, k=min(len(keys), rng.choice([1, 2]))):
        g["params"][k] = rng.choice(space[k])
    if entry == "ma_cross" and g["params"]["fast"] >= g["params"]["slow"]:
        g["params"]["fast"] = rng.choice([3, 5, 8])
    if rng.random() < 0.4:
        g["stop_mult"] = rng.choice(STOP_MULTS)
    if rng.random() < 0.3:
        g["tp_mult"] = rng.choice(TP_MULTS)
    if rng.random() < 0.15:
        g["allow_short"] = not g["allow_short"] or not g["allow_long"]
    return g


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    """交叉：同因子时融合参数，异因子时取一方核心 + 另一方风控。"""
    if a["entry"] == b["entry"]:
        child = json.loads(json.dumps(a))
        for k in child["params"]:
            if rng.random() < 0.5:
                child["params"][k] = b["params"][k]
        if child["entry"] == "ma_cross" and \
                child["params"]["fast"] >= child["params"]["slow"]:
            child["params"]["fast"] = 5
    else:
        child = json.loads(json.dumps(a if rng.random() < 0.5 else b))
    donor = b if rng.random() < 0.5 else a
    child["stop_mult"] = donor["stop_mult"]
    child["tp_mult"] = donor["tp_mult"]
    return child


# ---------------------------------------------------------------------------
# 因子信号（策略与 AI 预测共用，保证「回测的」与「同步给预测的」一致）
# ---------------------------------------------------------------------------
def factor_signal(gene: dict, closes: Sequence[float], highs: Sequence[float],
                  lows: Sequence[float]) -> int:
    """基于历史尾部序列计算当前信号：+1 做多 / -1 做空 / 0 无信号。"""
    entry = gene["entry"]
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
    except Exception:
        return 0
    return 0


def ensemble_strategy_signal(gene: dict, closes, highs, lows,
                             windows=None) -> float:
    """预测侧专用：多窗口集成 + 趋势强度门控，提升策略信号的稳健性与方向纯度。

    相比单窗口 ``factor_signal``（只回看整段、纯二值）：
      * 按基因类型自动选取回看窗口：趋势型用较长窗口（20/40/60）确认趋势，
        反转型用较短窗口（10/20/30）捕捉快速折返；
      * 趋势强度门控：信号方向与窗口内趋势方向一致时权重放大，反向时削弱，
        规避震荡收敛行情里假突破带来的反向噪音。

    仅用于预测研判，**不影响回测 fitness**（回测仍用 ``factor_signal`` 单窗口）。
    """
    if not closes or len(closes) < 20:
        return float(factor_signal(gene, closes, highs, lows))
    if windows is None:
        etype = (gene.get("entry") or "") if isinstance(gene, dict) else ""
        windows = _REVERT_WINDOWS if etype in _REVERT_TYPES else _TREND_WINDOWS
    sigs: list[float] = []
    weights: list[float] = []
    for w in windows:
        if len(closes) < w:
            continue
        c = closes[-w:]
        h = highs[-w:] if len(highs) >= w else highs
        l = lows[-w:] if len(lows) >= w else lows
        s = float(factor_signal(gene, c, h, l))
        if s == 0:
            continue
        base = c[0] if c[0] != 0 else 1e-9
        ret = (c[-1] - c[0]) / base                       # 窗口内趋势方向/幅度
        rng = (max(c) - min(c)) / base if base != 0 else 1e-9
        strength = min(abs(ret) / rng, 1.0) if rng > 1e-9 else 0.0   # 0..1，越高越趋势化
        align = 1.0 if (s > 0) == (ret > 0) else 0.35     # 信号与趋势同向才放大
        weights.append(0.4 + 0.6 * strength * align)
        sigs.append(s)
    if not sigs:
        return 0.0
    wsum = sum(weights)
    return sum(s * w for s, w in zip(sigs, weights)) / wsum if wsum else 0.0


# ---------------------------------------------------------------------------
# 行情状态感知：不同策略类型在不同行情状态下的表现迥异
#   趋势跟踪型（donchian_break / momentum / ma_cross / boll_break）：趋势行情强、震荡易假突破
#   均值反转型（rsi_reversal / boll_revert）：震荡行情强、强趋势中反向易亏损
# 融合时按「基因类型 × 当前行情状态」自适应加权，让信号源在各自擅长的状态被放大。
# ---------------------------------------------------------------------------
_TREND_TYPES = {"donchian_break", "momentum", "ma_cross", "boll_break"}
_REVERT_TYPES = {"rsi_reversal", "boll_revert"}
_TREND_WINDOWS = (20, 40, 60)     # 趋势型：较长窗口确认趋势
_REVERT_WINDOWS = (10, 20, 30)    # 反转型：较短窗口捕捉快速折返


def regime_of(closes, lookback: int = 20) -> float:
    """从收盘序列估计行情状态：1=强趋势，0=纯震荡（基于末端位移/区间比）。"""
    if not closes or len(closes) < lookback + 1:
        return 0.5
    c = closes[-(lookback + 1):]
    base = c[0] if c[0] != 0 else 1e-9
    ret = (c[-1] - c[0]) / base
    rng = (max(c) - min(c)) / base if base != 0 else 1e-9
    return max(0.0, min(1.0, abs(ret) / rng)) if rng > 1e-9 else 0.5


def _gene_regime_match(etype: str, regime: float) -> float:
    """基因类型与行情状态的匹配度（0.4..1.0）：趋势型在趋势行情放大、反转型在震荡放大。"""
    if etype in _TREND_TYPES:
        return 0.4 + 0.6 * regime
    if etype in _REVERT_TYPES:
        return 0.4 + 0.6 * (1.0 - regime)
    return 1.0


def gene_window(gene: dict) -> int:
    """基因所需最大历史窗口。"""
    p = gene["params"]
    vals = [v for v in p.values() if isinstance(v, (int, float)) and v > 1]
    return int(max([ATR_PERIOD] + [int(v) for v in vals]) + 6)


# ---------------------------------------------------------------------------
# 基因解释器策略：把基因翻译成可回测的 StrategyBase
# ---------------------------------------------------------------------------
class GeneStrategy(StrategyBase):
    """自进化策略：入场由因子信号驱动，离场用 ATR 跟踪止损 + 可选止盈。"""

    name = "自进化策略"
    default_params: dict = {}

    def __init__(self, symbol: str, gene: dict):
        super().__init__(symbol, {})
        self.gene = gene
        self._stop: Optional[float] = None
        self._tp: Optional[float] = None

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
        sig = factor_signal(g, self._closes, self._highs, self._lows)
        long_qty, short_qty = self.position()

        # ---- 持多仓：跟踪止损上移 / 止盈 / 反向信号离场 ----
        if long_qty > 0:
            self._stop = max(self._stop or -1e18,
                             bar.close - g["stop_mult"] * a)
            hit_tp = self._tp is not None and bar.close >= self._tp
            if bar.close < self._stop or hit_tp or sig == -1:
                self.send_order(Direction.SHORT, Offset.CLOSE, long_qty)
                self._stop = self._tp = None
            return
        # ---- 持空仓：对称处理 ----
        if short_qty > 0:
            self._stop = min(self._stop or 1e18,
                             bar.close + g["stop_mult"] * a)
            hit_tp = self._tp is not None and bar.close <= self._tp
            if bar.close > self._stop or hit_tp or sig == 1:
                self.send_order(Direction.LONG, Offset.CLOSE, short_qty)
                self._stop = self._tp = None
            return

        # ---- 空仓：按信号开仓 ----
        if sig == 1 and g.get("allow_long", True):
            self._stop = bar.close - g["stop_mult"] * a
            self._tp = (bar.close + g["tp_mult"] * a) if g.get("tp_mult") else None
            self.send_order(Direction.LONG, Offset.OPEN, int(g.get("lots", 1)))
        elif sig == -1 and g.get("allow_short", True):
            self._stop = bar.close + g["stop_mult"] * a
            self._tp = (bar.close - g["tp_mult"] * a) if g.get("tp_mult") else None
            self.send_order(Direction.SHORT, Offset.OPEN, int(g.get("lots", 1)))


# ---------------------------------------------------------------------------
# 适应度与盈利判定
# ---------------------------------------------------------------------------
def fitness(m: dict) -> float:
    """综合适应度：夏普 40 + 收益 30 + 回撤 -20 + 胜率 10，乘成交充分性。"""
    if not m:
        return -100.0
    sharpe = m.get("sharpe") or 0.0
    tr = m.get("total_return") or 0.0
    dd = m.get("max_drawdown") or 0.0
    wr = m.get("win_rate") or 0.0
    nt = m.get("num_closing_trades") or 0
    score = (40.0 * max(min(sharpe / 2.0, 1.0), -1.0)
             + 30.0 * max(min(tr / 0.5, 1.0), -1.0)
             - 20.0 * min(dd / 0.3, 1.5)
             + 10.0 * wr)
    adequacy = 0.3 + 0.7 * min(nt / 10.0, 1.0)   # 交易太少 → 结论不可信，打折
    return round(score * adequacy, 2)


def is_profitable(m: dict) -> tuple[bool, list[str]]:
    """盈利判定：返回 (是否盈利, 未达标原因列表)。"""
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
    return (len(reasons) == 0), reasons


# ---------------------------------------------------------------------------
# 盈利策略库（落盘 + 供 AI 预测读取）
# ---------------------------------------------------------------------------
def load_profitable() -> list[dict]:
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("strategies", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_profitable(new_entries: list[dict]) -> int:
    """合并写入盈利策略库；按 (品种, 基因签名) 去重、保留高适应度。

    返回库中当前策略总数。
    """
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
    # 每品种限量 + 总量限额
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
    os.replace(tmp, STORE_PATH)
    return len(kept)


def make_entry(symbol: str, symbol_name: str, period: str, gene: dict,
               metrics: dict, fit: float) -> dict:
    """构造一条盈利策略库记录（synced=True 表示已同步 AI 预测）。"""
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
    """供「AI预测」调用：汇总该品种盈利策略在最新行情上的方向信号。

    返回 {"n": 策略数, "bias": -1..1 加权方向, "long": 看多数, "short": 看空数,
          "detail": [{desc, signal, fitness, total_return, sharpe}]}
    """
    out = {"n": 0, "bias": 0.0, "long": 0, "short": 0, "detail": []}
    try:
        entries = [e for e in load_profitable() if e.get("symbol") == symbol]
        if not entries or df is None or len(df) < 10:
            return out
        closes = [float(x) for x in df["close"].tolist()]
        highs = [float(x) for x in df["high"].tolist()]
        lows = [float(x) for x in df["low"].tolist()]
        regime = regime_of(closes)        # 当前行情状态：1=强趋势 / 0=纯震荡
        wsum = 0.0
        acc = 0.0
        for e in entries:
            gene = e.get("gene") or {}
            sig = ensemble_strategy_signal(gene, closes, highs, lows)
            base_w = max(float(e.get("fitness") or 1.0), 1.0)
            m = e.get("metrics") or {}
            sharpe = float(m.get("sharpe") or 0.0)
            wr = float(m.get("win_rate") or 0.0)
            # 质量因子：夏普越高、胜率越高，方向权重越大（抑制低质伪盈利策略的噪音）
            qual = 0.5 + 0.4 * max(sharpe, 0.0) + 0.6 * max(wr - 0.3, 0.0)
            qual = max(0.25, min(2.5, qual))
            # 行情状态匹配：趋势型策略在趋势行情放大、反转型在震荡放大
            rmatch = _gene_regime_match(gene.get("entry", ""), regime)
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
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 进化引擎：一次 step() = 一代（生成 → 回测 → 排名 → 判定 → 落盘 → 换代）
# ---------------------------------------------------------------------------
class EvolutionEngine:
    """全自动策略进化引擎（由回测中心页驱动，一次 step 跑一代）。"""

    POP_SIZE = 10          # 种群规模
    ELITES = 2             # 精英保留数
    GENS_PER_SYMBOL = 4    # 每个品种进化代数，随后轮换下一品种

    def __init__(self, feed, universe: list, start: str = "2000-01-01",
                 end: str = "2100-01-01", period: str = "D",
                 capital: float = 1_000_000.0, seed: Optional[int] = None,
                 futures_params: Optional[dict] = None):
        self.feed = feed
        self.universe = list(universe)
        self.start, self.end, self.period = start, end, period
        self.capital = capital
        # 期货特有参数（杠杆 / 保证金率 / 合约乘数 / 交割日 / 平今折扣），
        # 由回测中心 UI 配置，下代回测即时生效；缺省走合约/账户默认。
        self.futures_params: dict = dict(futures_params or {})
        self.rng = random.Random(seed)
        self.sym_idx = 0
        self.generation = 0            # 全局代数
        self.gen_in_symbol = 0         # 当前品种内代数
        self.population: Optional[list] = None
        self.evaluated_total = 0
        self.profitable_total = len(load_profitable())
        self.best_overall: Optional[dict] = None   # 历史最优（跨品种）
        self._sym_best_curve: Optional[list] = None

    # ---- 断点状态：导出 / 恢复（供本地数据库持久化，重启无缝续跑）----
    def to_state(self) -> dict:
        """导出可 JSON 序列化的引擎断点状态。"""
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
        }

    def restore_state(self, st: dict) -> bool:
        """从断点状态恢复；失败返回 False（保持全新状态）。"""
        try:
            if not st or int(st.get("version", 0)) != 1:
                return False
            self.sym_idx = int(st.get("sym_idx", 0)) % max(len(self.universe), 1)
            self.generation = int(st.get("generation", 0))
            self.gen_in_symbol = int(st.get("gen_in_symbol", 0))
            pop = st.get("population")
            self.population = pop if isinstance(pop, list) and pop else None
            self.evaluated_total = int(st.get("evaluated_total", 0))
            self.profitable_total = len(load_profitable())
            bo = st.get("best_overall")
            self.best_overall = bo if isinstance(bo, dict) else None
            curve = st.get("sym_best_curve")
            self._sym_best_curve = curve if isinstance(curve, list) else None
            fp = st.get("futures_params")
            if isinstance(fp, dict):
                self.futures_params = fp
            return True
        except Exception:  # noqa: BLE001
            return False

    # ---- 品种/合约 ----
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
        # 期货参数：杠杆 → 保证金率（互为推导，杠杆优先）
        lev = float(fp.get("leverage", 10.0))
        margin_rate = float(fp.get("margin_rate", 1.0 / lev))
        # 合约乘数：UI 未指定则取合约默认（universe 行第5列）
        mult = float(fp.get("multiplier", self._row()[4]))
        cfg.account.leverage = lev
        cfg.account.margin_rate = margin_rate
        cfg.account.multiplier = mult
        cfg.account.close_today_ratio = float(fp.get("close_today_ratio", 0.5))
        # 放松风控展示策略原始表现（与手动回测页一致）
        cfg.risk.max_single_loss = 1e12
        cfg.risk.max_daily_loss = 1e12
        cfg.risk.max_drawdown = 0.99
        cfg.risk.max_position_per_symbol = 100
        cfg.risk.max_total_position_ratio = 0.98
        cfg.risk.max_order_qty = 100
        cfg.backtest.start_cash = self.capital
        cfg.account.initial_capital = self.capital
        return cfg

    # ---- 种群初始化：随机 + 盈利库定向播种 ----
    def _seed_population(self) -> list:
        pop = []
        seeds = [e["gene"] for e in load_profitable()
                 if e.get("symbol") == self.symbol()][:3]
        for g in seeds:
            pop.append(json.loads(json.dumps(g)))       # 已验证基因直接入池
            pop.append(mutate(g, self.rng))             # 及其变体
        while len(pop) < self.POP_SIZE:
            pop.append(random_gene(self.rng))
        return pop[:self.POP_SIZE]

    # ---- 单基因回测评估 ----
    def _evaluate(self, gene: dict) -> dict:
        from ..backtest.backtester import Backtester
        sym = self.symbol()
        bt = Backtester(self._config(), self.feed)
        bt.add_contract(self._contract())
        bt.add_strategy(GeneStrategy(sym, gene))
        res = bt.run(sym, self.start, self.end, self.period, warmup=60)
        m = res["metrics"]
        fit = fitness(m)
        ok, reasons = is_profitable(m)
        return {"gene": gene, "desc": describe_gene(gene),
                "signature": gene_signature(gene), "metrics": m,
                "fitness": fit, "profitable": ok, "reasons": reasons,
                "equity_curve": res["equity_curve"],
                # R6：成交记录（用于归因对话框的「分笔成交表」）
                "trades": res.get("trades", [])}

    # ---- 一代进化 ----
    def step(self) -> dict:
        """跑一代：评估当前种群 → 判定盈利并落盘 → 产生下一代 → 返回快照。"""
        sym, sym_name = self.symbol(), self.symbol_name()
        if self.population is None:
            self.population = self._seed_population()
            self._sym_best_curve = None

        results = []
        for gene in self.population:
            try:
                results.append(self._evaluate(gene))
            except Exception:
                continue
        self.evaluated_total += len(results)
        results.sort(key=lambda x: x["fitness"], reverse=True)

        # 盈利判定 + 自动同步（落盘即视为已同步：AI预测实时读取该库）
        new_entries = [make_entry(sym, sym_name, self.period,
                                  r["gene"], r["metrics"], r["fitness"])
                       for r in results if r["profitable"]]
        if new_entries:
            self.profitable_total = save_profitable(new_entries)
        else:
            self.profitable_total = len(load_profitable())

        # 更新最优
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

        # 产生下一代（精英保留 + 锦标赛 + 交叉 + 变异）
        next_pop = [json.loads(json.dumps(r["gene"]))
                    for r in results[:self.ELITES]]
        while len(next_pop) < self.POP_SIZE and results:
            a = self._tournament(results)
            b = self._tournament(results)
            child = crossover(a, b, self.rng) if self.rng.random() < 0.6 \
                else json.loads(json.dumps(a))
            if self.rng.random() < 0.5:
                child = mutate(child, self.rng)
            next_pop.append(child)
        while len(next_pop) < self.POP_SIZE:
            next_pop.append(random_gene(self.rng))

        self.generation += 1
        self.gen_in_symbol += 1
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
            # R6：最优策略成交记录（仅当前代最优，序列化后单条历史约 10~30KB，
            # 不入 ranked 是为了避免每代 10 条重复占用内存）
            "gen_best_trades": gen_best.get("trades", []) if gen_best else [],
            "best_overall": self.best_overall,
            "new_profitable": new_entries,
            "evaluated_total": self.evaluated_total,
            "profitable_total": self.profitable_total,
            "library": load_profitable(),
            "symbol_done": self.gen_in_symbol >= self.GENS_PER_SYMBOL,
        }

        # 品种轮换
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
        """锦标赛选择：随机抽 k 个取适应度最高者的基因。"""
        cand = self.rng.sample(results, k=min(k, len(results)))
        return max(cand, key=lambda x: x["fitness"])["gene"]
