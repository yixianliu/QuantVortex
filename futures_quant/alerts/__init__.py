"""预警增强模块。

提供可配置的阈值预警规则（涨跌幅 / 价格突破 / RSI 极端 / MACD 交叉 / 资金流异动），
对自选品种进行周期扫描，触发后写入 AnalysisStore.alerts 并通过信号推送本地通知。
"""
from .engine import (
    RULE_KINDS,
    evaluate_rule,
    scan,
    rule_label,
)

__all__ = ["RULE_KINDS", "evaluate_rule", "scan", "rule_label"]
