"""市场预测分析模块（analytics）。

包含：
    - predictor.Predictor：基于历史 K 线的趋势分析与统计外推预测。

重要声明：
    本模块所有「预测」均为**统计模型外推**，使用历史价格的特征（趋势斜率、
    波动率、均线排列等）给出情景区间与方向概率，绝非确定性预测，更不构成
    任何投资建议。实盘决策须结合自身判断与风险管理。
"""
from __future__ import annotations

from .predictor import Predictor, PredictionResult

__all__ = ["Predictor", "PredictionResult"]
