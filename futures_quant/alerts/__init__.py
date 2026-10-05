"""预警增强模块。

提供可配置的阈值预警规则（涨跌幅 / 价格突破 / RSI 极端 / MACD 交叉 / 资金流异动），
对自选品种进行周期扫描，触发后写入 AnalysisStore.alerts 并通过信号推送本地通知。

M8.6：新增宏观/政策事件「事件 → 阈值 → 通知」链路（``event`` 规则类型 +
:func:`scan_events` 专项扫描），基于 M8.4 MacroCalendar，冷却去重，单事件一次推送。
"""
from .engine import (
    RULE_KINDS,
    evaluate_rule,
    scan,
    scan_events,
    rule_label,
)

__all__ = ["RULE_KINDS", "evaluate_rule", "scan", "scan_events", "rule_label"]
