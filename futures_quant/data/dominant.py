"""主力合约动态识别（第二轮 P1-1：已提供主力/连续换月映射）。

M3.1：按成交量 + 持仓量综合权重识别主力合约，输出 date→contract 映射。
P1-1：``roll_transitions`` 将「主力合约切换」翻译为换月事件，供回测在
换月日计入 ``roll_cost``；``continuous_symbol_map`` 提供日期→连续合约代码映射。
"""
from __future__ import annotations
import pandas as pd
from typing import Dict

def identify_dominant(
    df: pd.DataFrame,
    symbol_prefix: str,
    vol_col: str = "volume",
    oi_col: str = "open_interest",
) -> Dict[pd.Timestamp, str]:
    """
    参数:
        df: 包含多合约的DataFrame，必须有 columns: ['date','contract','volume','open_interest']。
        symbol_prefix: 品种前缀，如 'rb'。
        vol_col: 成交量列名。
        oi_col: 持仓量列名。
    返回:
        dict: {date: 主力合约代码}
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    # 按日排名
    df["vol_rank"] = df.groupby("date")[vol_col].rank(ascending=False, method="first")
    df["oi_rank"] = df.groupby("date")[oi_col].rank(ascending=False, method="first")
    n = df.groupby("date")[vol_col].transform("count")
    df["vol_score"] = (n - df["vol_rank"] + 1) / n
    df["oi_score"] = (n - df["oi_rank"] + 1) / n
    df["score"] = 0.4 * df["vol_score"] + 0.6 * df["oi_score"]
    idx = df.groupby("date")["score"].idxmax()
    best = df.loc[idx]
    mapping = {row["date"]: row["contract"] for _, row in best.iterrows()}
    return mapping


def roll_transitions(mapping: Dict) -> list:
    """把 date→主力合约映射转成换月事件列表。

    参数:
        mapping: {date: contract}（``identify_dominant`` 的输出）
    返回:
        [(roll_date, from_contract, to_contract), ...]，仅保留发生切换的日期
    """
    items = sorted(mapping.items())
    out = []
    for (_, prev), (d, cur) in zip(items, items[1:]):
        if cur != prev:
            out.append((d, prev, cur))
    return out


def continuous_symbol_map(mapping: Dict) -> Dict:
    """日期→连续合约代码映射（主力代码原样作为连续序列标识）。

    单品种连续回测可直接用返回的映射定位每日应持有的合约；如无需区分，
    调用方可继续直接使用主力代码。
    """
    return {d: str(c) for d, c in sorted(mapping.items())}
