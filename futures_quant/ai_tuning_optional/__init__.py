"""M1-07 孤模块处置：AI 模型辅助调优处理模块（可选，惰性导入）。

M1-07：本包从 `futures_quant/ai/tuning/` 迁移到 `futures_quant/ai_tuning_optional/`，
并统一在子模块顶层添加 `_HAVE_SKLEARN` 开关（缺 sklearn 时 import 不崩）。
顶层不做任何重导出，避免 sklearn 缺失时 import 即抛错——所有子模块按需显式 import：
    from futures_quant.ai_tuning_optional.data_preprocessor import DataPreprocessor
    from futures_quant.ai_tuning_optional.data_validator import FuturesDataValidator
    from futures_quant.ai_tuning_optional.parameter_optimizer import ParameterOptimizer
    from futures_quant.ai_tuning_optional.performance_evaluator import PerformanceEvaluator
    from futures_quant.ai_tuning_optional.visualizer import Visualizer

M5-04/M2-11 会进一步接入本包（数据质量校验 / 超参搜索器），届时会在
`docs/ORPHAN_MODULES.md` 更新台账状态。
"""

# 空 __init__：刻意不做任何 import，确保 `import futures_quant.ai_tuning_optional`
# 在无 sklearn 环境下也不抛 ModuleNotFoundError。