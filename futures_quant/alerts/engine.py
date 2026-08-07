"""预警规则引擎（纯 numpy / pandas，无外部依赖）。

规则类型（kind）：
    price_pct  涨跌幅异动  —— 单日涨跌幅绝对值 ≥ param(%)
    price_break 价格突破  —— 收盘价创 param 日新高或新低
    rsi        RSI 极端   —— RSI(14) ≥ param(超买) 或 ≤ 100-param(超卖)
    macd       MACD 交叉  —— 最新 K 线 DIF 上/下穿 DEA（金叉/死叉）
    fund_flow  资金流异动 —— 单日资金流绝对值 ≥ param(亿)

扫描时对每条规则做冷却去重（默认 1 天），避免重复推送。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# 规则元信息（UI 与引擎共用）
RULE_KINDS: Dict[str, Dict[str, Any]] = {
    "price_pct": {
        "label": "涨跌幅异动", "unit": "%", "default": 3.0,
        "hint": "单日涨跌幅绝对值达到该百分比",
    },
    "price_break": {
        "label": "价格突破", "unit": "日", "default": 20,
        "hint": "收盘价创 N 日新高或新低",
    },
    "rsi": {
        "label": "RSI 极端", "unit": "阈值", "default": 70,
        "hint": "RSI(14) ≥ 阈值（超买）或 ≤ 100-阈值（超卖）",
    },
    "macd": {
        "label": "MACD 交叉", "unit": "—", "default": 0,
        "hint": "检测最新 K 线 MACD 金叉 / 死叉",
    },
    "fund_flow": {
        "label": "资金流异动", "unit": "亿", "default": 2.0,
        "hint": "单日资金流绝对值达到该亿元数",
    },
}

# 触发冷却（秒）：同一规则在冷却窗口内只推送一次
COOLDOWN_SECONDS = 24 * 3600


def rule_label(kind: str) -> str:
    """处理规则标签。
    
        参数:
            kind: str
    
        返回:
            str"""
    return RULE_KINDS.get(kind, {}).get("label", kind)


# ----------------------------- 指标小工具 -----------------------------
def _rsi(close: np.ndarray, n: int = 14) -> float:
    """处理RSI。
    
        参数:
            close: np.ndarray
            n: int
    
        返回:
            float"""
    if len(close) < n + 1:
        return float("nan")
    diffs = np.diff(close.astype(float))
    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)
    # Wilder 平滑
    avg_gain = np.mean(gains[:n])
    avg_loss = np.mean(losses[:n])
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def _macd(close: np.ndarray) -> Tuple[float, float, float]:
    """返回 (DIF, DEA, HIST)。不足样本返回 nan。"""
    if len(close) < 35:
        return float("nan"), float("nan"), float("nan")
    c = close.astype(float)
    ema12 = pd.Series(c).ewm(span=12, adjust=False).mean().to_numpy()
    ema26 = pd.Series(c).ewm(span=26, adjust=False).mean().to_numpy()
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().to_numpy()
    return float(dif[-1]), float(dea[-1]), float((dif[-1] - dea[-1]) * 2)


def _quote_stats(mdm, symbol: str, df: pd.DataFrame) -> Tuple[float, float, float]:
    """返回 (last, chg_pct, fund_flow)。优先用实时 quote，缺失时从日线推算。"""
    last = float(df["close"].iloc[-1])
    chg_pct = float("nan")
    fund_flow = float("nan")
    try:
        q = mdm.get_quote(symbol, "D")
        if q:
            last = float(q.get("last", last))
            chg_pct = float(q.get("chg_pct", float("nan")))
            fund_flow = float(q.get("fund_flow", float("nan")))
    except Exception:
        pass
    if not np.isfinite(chg_pct) and len(df) >= 2:
        prev = float(df["close"].iloc[-2])
        chg_pct = (last / prev - 1.0) * 100 if prev else float("nan")
    if not np.isfinite(fund_flow):
        try:
            mult = float(getattr(mdm, "multiplier", {}) or {})
        except Exception:
            mult = 0.0
        if mult:
            fund_flow = float(((df["close"] - df["open"]) * df["volume"]
                               * df["close"] * mult).tail(5).sum() / 1e8)
        else:
            fund_flow = float("nan")
    return last, chg_pct, fund_flow


# ----------------------------- 单规则评估 -----------------------------
def evaluate_rule(rule: Dict[str, Any], df: pd.DataFrame,
                  mdm=None) -> Optional[Tuple[str, str]]:
    """评估单条规则。返回 (level, message) 或 None（未触发）。

    level ∈ {"提示", "注意", "重要"}。
    """
    if df is None or len(df) < 5:
        return None
    kind = rule.get("kind")
    param = float(rule.get("param") or 0.0)
    symbol = rule.get("symbol", "")
    try:
        last, chg_pct, fund_flow = _quote_stats(mdm, symbol, df)
    except Exception:
        return None
    close = df["close"].to_numpy(dtype=float)

    if kind == "price_pct":
        if not np.isfinite(chg_pct):
            return None
        if abs(chg_pct) >= param:
            lvl = "重要" if abs(chg_pct) >= param * 2 else "注意"
            return lvl, f"单日涨跌幅 {chg_pct:+.2f}%，超过阈值 ±{param:.1f}%"

    elif kind == "price_break":
        n = max(3, int(param))
        if len(close) <= n:
            return None
        window = close[-(n + 1):-1]          # 不含当日
        if close[-1] >= np.max(window):
            return "注意", f"收盘价创 {n} 日新高（{last:,.1f}）"
        if close[-1] <= np.min(window):
            return "注意", f"收盘价创 {n} 日新低（{last:,.1f}）"

    elif kind == "rsi":
        level = max(50, min(95, param))
        r = _rsi(close, 14)
        if not np.isfinite(r):
            return None
        if r >= level:
            return "提示", f"RSI(14) 达 {r:.1f}，进入超买区（阈值 {level:.0f}）"
        if r <= 100 - level:
            return "提示", f"RSI(14) 达 {r:.1f}，进入超卖区（阈值 {100 - level:.0f}）"

    elif kind == "macd":
        if len(close) < 36:
            return None
        dif, dea, _ = _macd(close)
        pdif, pdea, _ = _macd(close[:-1])
        if not (np.isfinite(dif) and np.isfinite(dea)
                and np.isfinite(pdif) and np.isfinite(pdea)):
            return None
        if pdif <= pdea and dif > dea:
            return "提示", "MACD 金叉（DIF 上穿 DEA）"
        if pdif >= pdea and dif < dea:
            return "提示", "MACD 死叉（DIF 下穿 DEA）"

    elif kind == "fund_flow":
        if not np.isfinite(fund_flow):
            return None
        if abs(fund_flow) >= param:
            lvl = "重要" if abs(fund_flow) >= param * 2 else "注意"
            arrow = "流入" if fund_flow > 0 else "流出"
            return lvl, f"资金{arrow} {fund_flow:+,.2f} 亿，超过阈值 ±{param:.1f} 亿"

    return None


# ----------------------------- 扫描 -----------------------------
def scan(mdm, store, rules: List[Dict[str, Any]],
         now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
    """扫描一组（已启用）规则，触发写库并返回本次新触发的预警列表。

    每条规则带 1 天冷却：last_fired 在冷却窗口内则跳过。
    """
    now = now or dt.datetime.now()
    fired: List[Dict[str, Any]] = []
    for rule in rules:
        rid = rule.get("id")
        lf = rule.get("last_fired")
        if lf:
            try:
                if (now - dt.datetime.fromisoformat(lf)).total_seconds() < COOLDOWN_SECONDS:
                    continue
            except Exception:
                pass
        symbol = rule.get("symbol")
        try:
            df = mdm.get_bars(symbol, "D", 130)
        except Exception:
            continue
        if df is None or len(df) < 5:
            continue
        try:
            res = evaluate_rule(rule, df, mdm)
        except Exception:
            continue
        if not res:
            continue
        level, message = res
        ts = now.isoformat(timespec="seconds")
        store.save_alert(ts, symbol, rule_label(rule.get("kind")), level, message)
        if rid is not None:
            store.touch_rule_fired(rid, ts)
        fired.append(dict(ts=ts, symbol=symbol, rule=rule_label(rule.get("kind")),
                          level=level, message=message))
    return fired
