"""主力合约动态识别。

M3.1：按成交量 + 持仓量综合权重识别主力合约，输出 date→contract 映射。
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
