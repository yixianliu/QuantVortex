"""合约规格注册表（真实期货品种级参数）。

R4 目标之一：把「合成 universe 里只有 multiplier/tick，其余全硬编码 0.10/3.0」
升级为「品种级真实规格」：乘数、最小变动价位、保证金率、按手手续费（近似）、
默认杠杆、平今仓优惠、交割日（主力连续无单月交割日，填 None）。

说明：
- 保证金率/手续费为常见期货公司默认值（交易所最低+公司加收），可经交易所公告
  或 akshare 实时校准；本表是「离线、确定、可复现」的真实规格基线。
- 手续费模型为「按手固定元」（`Portfolio` 的计算口径），而真实市场多为「成交金额
  比例」，此处取按手近似真实值，误差在回测可接受范围。
- 交割日：主力连续合约（akshare 拉到的 rb0 等）无单月交割日，填 None；若日后接入
  单月合约，可经 build_contract(symbol, delivery_date="2026-05-15") 覆盖。

get_contract_spec(symbol) -> dict（含全部字段，带品种无关兜底）
build_contract(symbol, **overrides) -> Contract（供回测引擎构造真实合约）
"""
from __future__ import annotations

from .base import Contract
from .synthetic import FUTURES_UNIVERSE


# 平今仓免收手续费的品种（真实交易所规则）：上期所部分、中金所全部
_CLOSE_TODAY_FREE = {"rb", "hc", "ru", "au", "ag", "IF", "IH", "T", "IC", "IM"}

# 少数品种的手续费/保证金微调（其余按 category 规则生成）
_SPEC_TUNING = {
    # 金融期货：手续费按手较高（成交金额万分之 0.x），保证金率最高
    "IF": {"commission_per_lot": 25.0, "margin_rate": 0.12},
    "IH": {"commission_per_lot": 25.0, "margin_rate": 0.12},
    "IC": {"commission_per_lot": 25.0, "margin_rate": 0.12},
    "IM": {"commission_per_lot": 25.0, "margin_rate": 0.12},
    "T":  {"commission_per_lot": 5.0,  "margin_rate": 0.03},
    # 贵金属/能源：高价值，按手手续费偏高
    "au": {"commission_per_lot": 10.0, "margin_rate": 0.08},
    "ag": {"commission_per_lot": 5.0,  "margin_rate": 0.10},
    "sc": {"commission_per_lot": 10.0, "margin_rate": 0.10},
    # 有色金属：按手中等
    "cu": {"commission_per_lot": 5.0},
    "al": {"commission_per_lot": 5.0},
    "zn": {"commission_per_lot": 5.0},
    "ni": {"commission_per_lot": 5.0},
    "sn": {"commission_per_lot": 5.0},
    "pb": {"commission_per_lot": 5.0},
}


def _build_specs() -> dict:
    """由 FUTURES_UNIVERSE 生成品种级真实规格表。"""
    specs: dict = {}
    for row in FUTURES_UNIVERSE:
        code = row[0]
        name, cat, exch = row[1], row[2], row[3]
        mult, tick, price = row[4], row[5], row[6]

        # 保证金率：金融最高、贵金属略低，其余 10%
        margin = 0.10
        if cat == "金融":
            margin = 0.12
        elif cat == "贵金属":
            margin = 0.08

        # 按手手续费：按合约价值粗略分级（近似真实，非精确比例）
        commission = 3.0
        if mult >= 1000:           # 黄金/原油/国债等高价值
            commission = 10.0
        elif mult >= 100:          # 铁矿/焦炭等高乘数
            commission = 5.0
        elif price < 3000 and mult <= 10:   # 低价农产品
            commission = 1.5

        lev = round(1.0 / margin) if margin > 0 else 10
        close_today = 0.0 if code in _CLOSE_TODAY_FREE else 0.5

        specs[code] = {
            "symbol": code,
            "name": name,
            "category": cat,
            "exchange": exch,
            "multiplier": float(mult),
            "min_price_tick": float(tick),
            "typical_price": float(price),
            "margin_rate": float(margin),
            "commission_per_lot": float(commission),
            "leverage": lev,
            "close_today_commission_ratio": close_today,
            "delivery_date": None,
        }

    # 应用微调
    for code, ov in _SPEC_TUNING.items():
        if code in specs:
            specs[code].update(ov)
            if "margin_rate" in ov and ov["margin_rate"] > 0:
                specs[code]["leverage"] = round(1.0 / ov["margin_rate"])
    return specs


CONTRACT_SPECS: dict = _build_specs()

# 兜底（未知品种）使用中性默认值
_FALLBACK = {
    "symbol": "UNKNOWN", "name": "未知", "category": "未知", "exchange": "SHFE",
    "multiplier": 10.0, "min_price_tick": 1.0, "typical_price": 1000.0,
    "margin_rate": 0.10, "commission_per_lot": 3.0, "leverage": 10,
    "close_today_commission_ratio": 0.5, "delivery_date": None,
}


def _norm(symbol: str) -> str:
    """归一化 symbol（如 rb.SHFE / RB / rb0）到规格表 key。"""
    code = symbol.split(".")[0]
    if code in CONTRACT_SPECS:
        return code
    low = code.lower()
    up = code.upper()
    for cand in (up, low, code):
        if cand in CONTRACT_SPECS:
            return cand
    # 去掉可能的 "0" 主力后缀（rb0 -> rb）
    if len(code) > 1 and code[-1] == "0":
        base = code[:-1]
        if base in CONTRACT_SPECS:
            return base
        if base.lower() in CONTRACT_SPECS:
            return base.lower()
    return code


def get_contract_spec(symbol: str) -> dict:
    """返回某合约的品种级真实规格（dict）。未知品种返回中性兜底。"""
    key = _norm(symbol)
    if key in CONTRACT_SPECS:
        return dict(CONTRACT_SPECS[key])
    return dict(_FALLBACK)


def build_contract(symbol: str, **overrides) -> Contract:
    """构造带真实品种规格的 Contract；overrides 可覆盖任意字段（如用户手动参数）。"""
    spec = get_contract_spec(symbol)
    spec.update(overrides)
    return Contract(
        symbol=symbol,
        exchange=spec["exchange"],
        multiplier=spec["multiplier"],
        min_price_tick=spec["min_price_tick"],
        margin_rate=spec["margin_rate"],
        commission_per_lot=spec["commission_per_lot"],
        trading_hours=None,
        delivery_date=spec.get("delivery_date"),
        leverage=spec["leverage"],
        close_today_commission_ratio=spec.get("close_today_commission_ratio", 0.5),
    )
