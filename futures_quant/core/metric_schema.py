"""回测 / 预测 两板块统一指标规范（联动分析基石）。

目标：让「回测中心」与「KP预测」两个板块使用**完全一致**的指标键名、单位
与展示格式，确保数据可无缝对接、联动分析时数字不会出现口径偏差。

- 收益类（total_return / annual_return）：小数 → 百分比（如 0.053 → "5.3%"）
- 比率类（sharpe / profit_factor / calmar）：浮点 → 两位小数
- 风险类（max_drawdown / win_rate）：小数 → 百分比
- 各字段标注 higher_is_better，供 UI 自动着色（红涨绿跌 / 优劣配色统一）

M2.5 扩展（2026-09-19）：新增 METRIC_KEYS 单一事实来源 + compute_extended_metrics，
覆盖 Calmar / Sortino / VaR(95)/CVaR(95)/VaR(99)/CVaR(99) / 最大连续盈利亏损次数 /
月度收益热力图。旧 METRIC_FIELDS（回测展示格式化）保留不动，消费侧零破坏。
"""
from __future__ import annotations

import math
from typing import Any

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
    "num_closing_trades": ("平仓笔数",  "int",   True,  False),
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
    """为「KP预测」板块提供回测联动摘要：与预测 res 同构的指标字段。

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


# ============================================================================
# M2.5 · 扩展绩效指标 Schema（单一事实来源）
# ============================================================================
# 所有回测/绩效/UI 展示统一从这里 import，禁止他处硬编码同构 dict。
# 字段分组：收益 / 风险 / 交易 / 资金 / 质量。
# 消费侧一律 .get() 容错，旧数据文件仍可被新 UI 渲染。
METRIC_KEYS: dict[str, str] = {
    # ── 收益类 ─────────────────────────────────────────
    "total_return_pct":      "总收益率(%)",
    "annual_return_pct":     "年化收益率(%)",
    "volatility":            "年化波动率(%)",
    "sortino_ratio":         "Sortino 比率",
    "profit_loss_ratio":     "盈亏比(单笔均值)",
    "win_rate":              "胜率(%)",
    "payoff_ratio":          "盈亏比(总盈利/总亏损)",
    # ── 风险类 ─────────────────────────────────────────
    "max_drawdown_pct":      "最大回撤(%)",
    "max_drawdown_duration": "最长回撤持续(根bar)",
    "var_95_pct":            "VaR(95%,单笔)",
    "cvar_95_pct":           "CVaR(95%,均值超额)",
    "var_99_pct":            "VaR(99%,单笔)",
    "cvar_99_pct":           "CVaR(99%,均值超额)",
    "calmar_ratio":          "Calmar 比率",
    "tail_risk_flag":        "尾部风险标记(0=正常/1=异常)",
    # ── 交易类 ─────────────────────────────────────────
    "n_trades":              "总成交笔数",
    "avg_trades_per_month":  "月均成交笔数",
    "n_win_streak":          "当前连胜笔数",
    "n_loss_streak":         "当前连亏笔数",
    "max_win_streak":        "历史最长连胜",
    "max_loss_streak":       "历史最长连亏",
    "exposure":              "持仓暴露率(%)",
    "turnover":              "换手率(笔/百bar)",
    # ── 资金类 ─────────────────────────────────────────
    "avg_position_ratio":    "平均仓位占比(%)",
    "peak_margin_ratio":     "峰值保证金占用(%)",
    "avg_margin_ratio":      "平均保证金占用(%)",
    "end_equity":           "期末权益",
    "start_equity":         "期初权益",
    "monthly_heatmap":      "月度收益热力图(嵌套dict)",
    # ── 质量类 ─────────────────────────────────────────
    "sample_bars":           "样本bar数",
    "data_quality_flag":     "数据质量标记(0=正常)",
    "confidence_pct":        "绩效置信度(%)",
}

# 全量字段名集合（消费侧校验用）
ALL_METRIC_NAMES: frozenset[str] = frozenset(METRIC_KEYS.keys())


def build_metrics_schema(*keys: str) -> dict[str, str]:
    """从 METRIC_KEYS 取指定 key 的子集；空参 = 全量。"""
    if not keys:
        return dict(METRIC_KEYS)
    out: dict[str, str] = {}
    for k in keys:
        out[k] = METRIC_KEYS.get(k, k)
    return out


def _percentile(sorted_arr: list[float], q: float) -> float:
    """线性插值分位数（纯 Python，避免对空/单元素数组的 numpy 依赖）。"""
    if not sorted_arr:
        return float("nan")
    n = len(sorted_arr)
    if n == 1:
        return sorted_arr[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_arr[lo] * (1 - frac) + sorted_arr[hi] * frac


def compute_extended_metrics(
    equity_curve: list[float],
    trades: list[dict],
    bars_per_year: int = 252,
) -> dict[str, Any]:
    """从「资金曲线 + 平仓交易」一函数算出 M2.5 扩展绩效指标。

    参数:
        equity_curve: 逐 bar 权益（长度 = bar 数），float 序列。
        trades:       平仓交易列表，每项含 "pnl"（单笔盈亏，元）。
        bars_per_year: 年 bar 数（日线 252，分钟线按实际 bar 数年化）。

    返回:
        符合 METRIC_KEYS 的 dict（monthly_heatmap 返回空占位，由回测引擎填充）。

    防未来函数：全部计算仅依赖历史资金曲线与已完成交易。
    """
    eq = [float(x) for x in equity_curve if x is not None and x == x]
    if len(eq) < 2:
        return {k: 0.0 for k in METRIC_KEYS if k != "monthly_heatmap"} | {"monthly_heatmap": {}}

    start, end = eq[0], eq[-1]
    total_ret = (end / start - 1.0) if start != 0 else 0.0
    n_bars = len(eq) - 1
    years = max(n_bars / bars_per_year, 1e-9)
    annual_ret = ((end / start) ** (1.0 / years) - 1.0) if start > 0 and end > 0 else 0.0

    # 逐 bar 收益率序列（防未来函数：i 时刻只读 eq[:i]）
    rets: list[float] = []
    for i in range(1, len(eq)):
        base = eq[i - 1]
        rets.append(eq[i] / base - 1.0 if base != 0 else 0.0)

    mean_r = sum(rets) / len(rets) if rets else 0.0
    var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets) if rets else 0.0
    std_r = math.sqrt(var_r)
    volatility = std_r * math.sqrt(bars_per_year)

    # 下行标准差（Sortino 用）
    downside = [r for r in rets if r < 0]
    downside_std = math.sqrt(sum(r ** 2 for r in downside) / len(rets)) if rets else 0.0
    sortino = (annual_ret / downside_std * math.sqrt(bars_per_year)) if downside_std > 1e-12 else 0.0

    # 最大回撤 + 持续
    peak = eq[0]
    mdd = 0.0
    mdd_dur = 0
    cur_dur = 0
    for v in eq:
        if v > peak:
            peak = v
            cur_dur = 0
        else:
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > mdd:
                mdd = dd
            cur_dur += 1
            mdd_dur = max(mdd_dur, cur_dur)

    calmar = (annual_ret / mdd) if mdd > 1e-12 else 0.0

    # 交易类指标
    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    n_trades = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = (len(wins) / n_trades * 100.0) if n_trades else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    payoff = (gross_win / gross_loss) if gross_loss > 1e-12 else (float(len(wins)) if wins else 0.0)
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 1e-12 else 0.0

    # 最大连续盈利 / 亏损次数
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for p in pnls:
        if p > 0:
            cur_win += 1
            cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        elif p < 0:
            cur_loss += 1
            cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
        else:
            cur_win = cur_loss = 0
    n_win_streak = cur_win
    n_loss_streak = cur_loss

    # VaR / CVaR（历史法，单笔收益率分布）
    sorted_rets = sorted(rets)
    var_95 = -_percentile(sorted_rets, 0.05)
    var_99 = -_percentile(sorted_rets, 0.01)
    # CVaR = 损失超过 VaR 的条件期望（取负号使正数 = 平均超额损失）
    tail_95 = [r for r in sorted_rets if r < -var_95]
    cvar_95 = -(sum(tail_95) / len(tail_95)) if tail_95 else var_95
    tail_99 = [r for r in sorted_rets if r < -var_99]
    cvar_99 = -(sum(tail_99) / len(tail_99)) if tail_99 else var_99

    # 尾部风险标记：CVaR(99) > 2x VaR(95) 视为异常厚尾
    tail_flag = 1 if (cvar_99 > 2.0 * var_95 + 1e-9) else 0

    out: dict[str, Any] = {
        "total_return_pct": total_ret * 100.0,
        "annual_return_pct": annual_ret * 100.0,
        "volatility": volatility * 100.0,
        "sortino_ratio": sortino,
        "profit_loss_ratio": pl_ratio,
        "win_rate": win_rate,
        "payoff_ratio": payoff,
        "max_drawdown_pct": mdd * 100.0,
        "max_drawdown_duration": mdd_dur,
        "var_95_pct": var_95 * 100.0,
        "cvar_95_pct": cvar_95 * 100.0,
        "var_99_pct": var_99 * 100.0,
        "cvar_99_pct": cvar_99 * 100.0,
        "calmar_ratio": calmar,
        "tail_risk_flag": tail_flag,
        "n_trades": n_trades,
        "avg_trades_per_month": (n_trades / years * 12.0) if n_trades else 0.0,
        "n_win_streak": n_win_streak,
        "n_loss_streak": n_loss_streak,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "exposure": 0.0,
        "turnover": (n_trades / n_bars * 100.0) if n_bars else 0.0,
        "avg_position_ratio": 0.0,
        "peak_margin_ratio": 0.0,
        "avg_margin_ratio": 0.0,
        "end_equity": end,
        "start_equity": start,
        "monthly_heatmap": {},
        "sample_bars": n_bars,
        "data_quality_flag": 0,
        "confidence_pct": 100.0,
    }
    return out


def build_monthly_heatmap(equity_curve: list[float], dates: list) -> dict[str, dict[str, float]]:
    """构建月度收益热力图：{YYYY-MM: {pnl_pct, win_rate, n_trades}}。

    参数:
        equity_curve: 逐 bar 权益。
        dates:        与 equity_curve 等长的日期序列（datetime / Timestamp / 字符串）。
    防未来函数：仅按已完成 bar 的日期分组。
    """
    if not dates or len(dates) != len(equity_curve):
        return {}
    out: dict[str, dict] = {}
    for i in range(1, len(equity_curve)):
        base = equity_curve[i - 1]
        pnl = (equity_curve[i] / base - 1.0) * 100.0 if base != 0 else 0.0
        d = dates[i]
        try:
            key = f"{d.year:04d}-{d.month:02d}"
        except AttributeError:
            key = str(d)[:7]
        slot = out.setdefault(key, {"pnl_pct": 0.0, "win_count": 0, "n": 0})
        slot["pnl_pct"] += pnl
        slot["n"] += 1
        if pnl > 0:
            slot["win_count"] += 1
    final: dict[str, dict[str, float]] = {}
    for k, v in out.items():
        n = int(v["n"]) or 1
        final[k] = {
            "pnl_pct": round(v["pnl_pct"], 2),
            "win_rate": round(float(v["win_count"]) / n * 100.0, 1),
            "n_trades": n,
        }
    return final