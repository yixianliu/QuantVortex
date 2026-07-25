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


def cmd_ui(theme: str = "dark") -> None:
    from futures_quant.ui.main_window import main as ui_main
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
