"""期货智能分析预测系统 · 统一入口。

用法：
    python main.py                 # 启动 PyQt6 桌面端（默认深色主题，合成行情）
    python main.py --theme light   # 浅色主题
    python main.py --test          # 仅校验核心模块可导入（无 UI）

说明：
    - 系统定位为「行情分析 / AI 预测 / 量化研判 / 数据复盘」工具，不做自动交易；
    - 数据源默认 SyntheticFeed（统计特征贴近真实期货的合成行情），
      生产环境在 futures_quant/data/ctp_gateway.py 替换为 CTPFeed 即可接入实盘；
    - 全部依赖仅为 Python3.9+ / PyQt6 / numpy / pandas，可离线运行、可打包 EXE。
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# 安全：尽早安装全局脱敏钩子（必须早于任何业务模块的导入与运行）。
# 它接管 sys.excepthook 与 threading.excepthook，并给 root logger 挂上过滤器，
# 使未捕获异常的 traceback、第三方库日志在输出前都被洗掉敏感信息。
# 桌面程序的崩溃信息经常被用户截图外发，这一步不能省。
try:
    from futures_quant.utils.redact import install_global_redaction
    install_global_redaction()
except Exception:      # 脱敏模块自身出问题也绝不能拖垮启动
    pass


def cmd_ui(theme: str = "dark") -> None:
    from futures_quant.ui.main_window import main as ui_main
    from futures_quant.runtime import is_frozen
    from futures_quant.ai.llm_client import enforce_security_mode

    # 双模式安全强制：打包模式清除持久化密钥，仅允许环境变量注入
    enforce_security_mode(is_frozen())

    # 主题通过环境变量预置，main_window 内部再切换
    os.environ["QV_THEME"] = theme
    ui_main()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="期货智能分析预测系统")
    parser.add_argument("--theme", default="dark", choices=["dark", "light"])
    parser.add_argument("--test", action="store_true", help="仅校验核心模块可导入")
    args = parser.parse_args()

    if args.test:
        import importlib
        for m in [
            "futures_quant.data.market_data",
            "futures_quant.indicators.tech",
            "futures_quant.ai.predictor",
            "futures_quant.analysis.signals",
            "futures_quant.storage.analysis_store",
            "futures_quant.ui.pages",
        ]:
            importlib.import_module(m)
        print("[OK] 核心模块全部可导入")
        return

    cmd_ui(args.theme)


if __name__ == "__main__":
    main()
