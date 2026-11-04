"""M6.3 / M8.5 多因子打分卡：技术面 / 量能 / AI 概率 / 板块因子 +（M8.5）消息面 / 持仓 / 基差 / 事件。

设计原则：
- 各子项均归一到 [0,1] 再加权求和 ×100。
- 任一子项缺失 → 该子项取 0.5 中性，不改变综合分可复现性（缺失项贡献 0.5×权重，分母恒为全部权重和=1）。
- 默认 4 项权重：``技术面 0.40 / 量能 0.20 / AI概率 0.25 / 板块因子 0.15``（和=1.0，M6.3）。
- M8.5 全项权重 ``FULL_WEIGHTS``：``技术面 0.25 / 量能 0.15 / AI概率 0.20 / 板块 0.10 / 消息面 0.10 / 持仓 0.05 / 基差 0.08 / 事件 0.07``（和=1.0）。
- ``include_full=True`` 时启用消息面/持仓/基差/事件四子项并采用 FULL_WEIGHTS；否则保持 M6.3 行为不变。

M8.5 新增子项计算（均只用 t 时刻及之前数据，缺失→0.5 中性）：
- 消息面：M8.1 tfidf_sentiment ∈ [0,1]（0.5 中性，>0.5 偏多，<0.5 偏空）。
- 持仓：M8.2 position_long_short_ratio → tanh 映射（多头占比高→偏多）。
- 基差：M8.3 basis_rank ∈ [0,1]（基差走强→偏多）。
- 事件：M8.4 事件冲击度 event_impact ∈ [-1,1] → (x+1)/2（正值利好，负值利空，0 中性）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

__all__ = ["SubScore", "Scorecard", "DEFAULT_WEIGHTS", "FULL_WEIGHTS"]

DEFAULT_WEIGHTS: Dict[str, float] = {
    "technical": 0.40,
    "volume": 0.20,
    "ai_prob": 0.25,
    "sector": 0.15,
}

# M8.5：全因子 8 项权重（和=1.0），含消息面/持仓/基差/事件。
FULL_WEIGHTS: Dict[str, float] = {
    "technical": 0.25,
    "volume": 0.15,
    "ai_prob": 0.20,
    "sector": 0.10,
    "news": 0.10,
    "position": 0.05,
    "basis": 0.08,
    "event": 0.07,
}


@dataclass
class SubScore:
    """单个子项得分。"""
    raw: float            # 原始输入
    normalized: float    # [0,1]
    available: bool      # 该子项是否有效


class Scorecard:
    """多因子打分卡（M6.3 基础 4 项 + M8.5 可选 4 项）。

    参数:
        df: DataFrame（close / volume / high / low 等）。
        ai_prob: 可选，AI 模型给出的方向概率 [0,1]。
        sector_rank: 可选，品种在板块内的 20 日收益 rank（1=最强）。
        sector_size: 可选，板块内有效品种数量。
        weights: 可选，子项权重；不传则按 include_full 选 DEFAULT / FULL。
        include_full: 是否启用 M8.5 全因子（默认 False，保持 M6.3 行为）。
        news_sentiment: 可选，M8.1 消息面得分 [0,1]（0.5 中性）。
        position_long_short_ratio: 可选，M8.2 多/空持仓比（浮点，>1 偏多）。
        basis_rank: 可选，M8.3 基差强度分位 [0,1]（>0.5 偏多）。
        event_impact: 可选，M8.4 事件冲击度 [-1,1]（0 中性，正利好负利空）。
    """

    def __init__(
        self,
        df: pd.DataFrame,
        ai_prob: Optional[float] = None,
        sector_rank: Optional[int] = None,
        sector_size: Optional[int] = None,
        weights: Optional[Dict[str, float]] = None,
        include_full: bool = False,
        news_sentiment: Optional[float] = None,
        position_long_short_ratio: Optional[float] = None,
        basis_rank: Optional[float] = None,
        event_impact: Optional[float] = None,
    ) -> None:
        self.df = df
        self.ai_prob = ai_prob
        self.sector_rank = sector_rank
        self.sector_size = sector_size
        self.include_full = include_full
        self.news_sentiment = news_sentiment
        self.position_long_short_ratio = position_long_short_ratio
        self.basis_rank = basis_rank
        self.event_impact = event_impact

        base = weights if weights is not None else (FULL_WEIGHTS if include_full else DEFAULT_WEIGHTS)
        w = dict(base)
        if include_full:
            # 启用全因子：补全 4 项
            for k in ("news", "position", "basis", "event"):
                w.setdefault(k, FULL_WEIGHTS.get(k, 0.0))
        else:
            # M6.3 行为：只保留基础 4 项（即使传入额外键也忽略，避免改变旧契约）
            for k in ("news", "position", "basis", "event"):
                w.pop(k, None)
        total = sum(v for v in w.values() if v > 0)
        self.weights = {k: v / total for k, v in w.items()}

    # --- 子项计算 ---
    def _technical(self) -> SubScore:
        close = self.df["close"].astype(float).dropna()
        if len(close) < 60:
            return SubScore(0.0, 0.5, available=False)
        ma = close.iloc[-60:].mean()
        if ma == 0:
            return SubScore(0.0, 0.5, available=False)
        bias = float(close.iloc[-1] / ma - 1.0)
        # sigmoid 映射：bias=0 → 0.5，bias=±5% → 0.73/0.27，bias=±10% → 0.88/0.12
        norm = 1.0 / (1.0 + math.exp(-bias * 40.0))
        return SubScore(bias, norm, available=True)

    def _volume(self) -> SubScore:
        vol = self.df.get("volume")
        if vol is None:
            return SubScore(0.0, 0.5, available=False)
        vol = vol.astype(float).dropna()
        if len(vol) < 60:
            return SubScore(0.0, 0.5, available=False)
        recent = vol.iloc[-5:].mean()
        base = vol.iloc[-60:].mean()
        if base == 0:
            return SubScore(0.0, 0.5, available=False)
        ratio = float(recent / base)
        # 量比映射：0.5 → 0.5，2.0 → 1.0，0.25 → 0.0（饱和）
        norm = min(max((ratio - 0.5) / 1.5, 0.0), 1.0)
        return SubScore(ratio, norm, available=True)

    def _ai_prob(self) -> SubScore:
        if self.ai_prob is None:
            return SubScore(0.0, 0.5, available=False)
        p = float(self.ai_prob)
        p = min(max(p, 0.0), 1.0)
        return SubScore(p, p, available=True)

    def _sector(self) -> SubScore:
        if self.sector_rank is None or self.sector_size is None or self.sector_size < 1:
            return SubScore(0.0, 0.5, available=False)
        r = int(self.sector_rank)
        n = int(self.sector_size)
        # rank=1 最强 → norm=1；rank=n 最弱 → norm=0
        norm = (n - r + 1) / n
        norm = min(max(norm, 0.0), 1.0)
        return SubScore(r / n, norm, available=True)

    # --- M8.5 新增子项 ---
    def _news(self) -> SubScore:
        """消息面：M8.1 tfidf_sentiment ∈ [0,1]，0.5 中性。缺失→0.5。"""
        if self.news_sentiment is None:
            return SubScore(0.0, 0.5, available=False)
        x = float(self.news_sentiment)
        x = min(max(x, 0.0), 1.0)
        return SubScore(x, x, available=True)

    def _position(self) -> SubScore:
        """持仓：M8.2 多/空持仓比 → tanh 映射到 [0,1]。
        ratio=1（多空平衡）→0.5；ratio>>1（多头主导）→→1；ratio<<1（空头主导）→→0。
        """
        if self.position_long_short_ratio is None:
            return SubScore(0.0, 0.5, available=False)
        r = float(self.position_long_short_ratio)
        if not np.isfinite(r) or r <= 0:
            return SubScore(r, 0.5, available=False)
        # tanh(log r) ∈ (-1,1) → (x+1)/2 ∈ (0,1)；log(1)=0 → 0.5
        t = math.tanh(math.log(r))
        norm = (t + 1.0) / 2.0
        return SubScore(r, norm, available=True)

    def _basis(self) -> SubScore:
        """基差：M8.3 basis_rank ∈ [0,1]（0=最弱基差，1=最强）。缺失→0.5。"""
        if self.basis_rank is None:
            return SubScore(0.0, 0.5, available=False)
        x = float(self.basis_rank)
        x = min(max(x, 0.0), 1.0)
        return SubScore(x, x, available=True)

    def _event(self) -> SubScore:
        """事件：M8.4 event_impact ∈ [-1,1] → (x+1)/2。0 中性，+1 强利好，-1 强利空。缺失→0.5。"""
        if self.event_impact is None:
            return SubScore(0.0, 0.5, available=False)
        x = float(self.event_impact)
        x = min(max(x, -1.0), 1.0)
        norm = (x + 1.0) / 2.0
        return SubScore(x, norm, available=True)

    def sub_scores(self) -> Dict[str, SubScore]:
        subs: Dict[str, SubScore] = {
            "technical": self._technical(),
            "volume": self._volume(),
            "ai_prob": self._ai_prob(),
            "sector": self._sector(),
        }
        if self.include_full:
            subs["news"] = self._news()
            subs["position"] = self._position()
            subs["basis"] = self._basis()
            subs["event"] = self._event()
        return subs

    def composite(self) -> float:
        """0-100 综合分。缺失子项取 0.5 中性，分母恒为全部启用子项权重和（=1）。

        逻辑：可用项贡献 normalized×权重；缺失项贡献 0.5×权重；
        总权重和恒为 1（含缺失项），故综合分直接为加权和×100，可复现。
        """
        subs = self.sub_scores()
        score = 0.0
        for k, s in subs.items():
            w = self.weights.get(k, 0.0)
            norm = s.normalized if s.available else 0.5
            score += w * norm
        return round(min(max(score, 0.0), 1.0) * 100.0, 2)

    def detail(self) -> Dict[str, float]:
        """返回各子项 normalized 值与综合分。"""
        subs = self.sub_scores()
        out = {f"{k}_norm": s.normalized for k, s in subs.items()}
        out["composite"] = self.composite()
        return out


def rank_scorecards(
    data: Dict[str, pd.DataFrame],
    ai_probs: Optional[Dict[str, float]] = None,
    sector_ranks: Optional[Dict[str, int]] = None,
    sector_sizes: Optional[Dict[str, int]] = None,
    weights: Optional[Dict[str, float]] = None,
    include_full: bool = False,
    news_sentiments: Optional[Dict[str, float]] = None,
    position_ratios: Optional[Dict[str, float]] = None,
    basis_ranks: Optional[Dict[str, float]] = None,
    event_impacts: Optional[Dict[str, float]] = None,
) -> List[Dict]:
    """批量打分并返回按综合分降序排列的列表。

    每个元素：``{symbol, composite, detail}``。
    include_full=True 时启用 M8.5 全因子（消息面/持仓/基差/事件）。
    """
    results: List[Dict] = []
    for sym, df in data.items():
        sc = Scorecard(
            df,
            ai_prob=(ai_probs or {}).get(sym),
            sector_rank=(sector_ranks or {}).get(sym),
            sector_size=(sector_sizes or {}).get(sym),
            weights=weights,
            include_full=include_full,
            news_sentiment=(news_sentiments or {}).get(sym),
            position_long_short_ratio=(position_ratios or {}).get(sym),
            basis_rank=(basis_ranks or {}).get(sym),
            event_impact=(event_impacts or {}).get(sym),
        )
        results.append({"symbol": sym, "composite": sc.composite(), "detail": sc.detail()})
    results.sort(key=lambda x: -x["composite"])
    return results
