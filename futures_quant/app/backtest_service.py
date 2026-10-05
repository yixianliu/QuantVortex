"""回测服务：封装回测引擎，提供简单易用的接口。

UI 层只需调用 run_backtest(symbol, start, end, period, strategy_cfg) 获得结果，
无需直接处理 Backtester、TradingEngine、数据源等细节。

M1-03（2026-10-01）：策略注册表统一化
    - `run_backtest_with_params()` 删除 5 层 if/elif 白名单，改为查
      `futures_quant.strategy.STRATEGY_REGISTRY`；
    - 新增 `run_backtest_with_gene()`：把「基因→策略」的构造路径也纳入
      本服务，使 EvolutionEngine 的评估链路与手动回测共享同一入口（消除
      平行路径）。
"""
from __future__ import annotations

import os
from typing import Dict, Any, Optional

from futures_quant.config.settings import Config
from futures_quant.data.base import DataFeed
from futures_quant.backtest.backtester import Backtester
from futures_quant.strategy import (
    StrategyBase,
    get_strategy_class,
    list_strategies,
)


class BacktestService:
    def __init__(self, config: Config, feed: DataFeed) -> None:
        self.config = config
        self.feed = feed

    # ---------- 内部工具 ----------
    def _make_backtester(self, contract: Any, strategy: StrategyBase) -> Backtester:
        """统一的 Backtester 构造入口（M1-03）。

        EvolutionEngine / 手动回测 / run_backtest_with_gene 都通过此方法构造，
        避免出现平行路径。
        """
        bt = Backtester(self.config, self.feed)
        bt.add_contract(contract)
        bt.add_strategy(strategy)
        return bt

    # ---------- 公共 API ----------
    def run_backtest(
        self,
        symbol: str,
        start: str,
        end: str,
        period: str = "1m",
        warmup: int = 0,
        strategy: Optional[StrategyBase] = None,
        generate_report: bool = True,
    ) -> Dict[str, Any]:
        """执行一次回测并返回结果字典。

        参数:
            symbol: 合约代码，如 "rb.SHFE"
            start: 起始日期字符串，格式 "YYYY-MM-DD"
            end: 结束日期字符串，格式 "YYYY-MM-DD"
            period: K线周期，默认 "1m"
            warmup: 预热根数，默认 0
            strategy: 已实例化的策略对象；若为 None，则使用默认的 TrendFollowing（均线）。
            generate_report: 是否生成HTML报告，默认 True
        返回:
            包含 metrics、equity_curve、trades 和 report（可选）的字典。
        """
        # 使用传入的策略或默认策略
        if strategy is None:
            strategy = get_strategy_class("trend_following")(symbol=symbol)

        from futures_quant.data.contract_specs import build_contract
        contract = build_contract(symbol)

        backtester = self._make_backtester(contract, strategy)
        result = backtester.run(symbol, start, end, period, warmup)

        # 生成报告（如果需要）
        report_path = None
        if generate_report:
            ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            outdir = os.path.join(ROOT, "data", "backtest_reports")
            os.makedirs(outdir, exist_ok=True)
            paths = backtester.export(outdir, prefix=f"bt_{symbol.replace('.', '_')}_{period}")
            report_path = paths["html"]

        return {
            "metrics": result["metrics"],
            "equity_curve": result["equity_curve"],
            "trades": result["trades"],
            "report": report_path,
        }

    def run_backtest_with_params(
        self,
        symbol: str,
        start: str,
        end: str,
        period: str = "1m",
        warmup: int = 0,
        strategy_name: str = "trend_following",
        strategy_params: Optional[Dict[str, Any]] = None,
        generate_report: bool = True,
    ) -> Dict[str, Any]:
        """根据策略名称和参数运行回测。

        M1-03：策略名走 `STRATEGY_REGISTRY`；未知名字抛 ``ValueError``。

        可用策略名（``list_strategies()``）示例:
            trend_following, mean_reversion, breakout, grid, martingale, gene
        """
        strategy_params = strategy_params or {}
        # M1-03：注册表查找，未知名抛 ValueError（不静默回退）
        cls = get_strategy_class(strategy_name)
        # 所有内置策略统一签名 __init__(self, symbol, params=None)
        strategy = cls(symbol=symbol, params=strategy_params)
        return self.run_backtest(symbol, start, end, period, warmup, strategy, generate_report)

    def run_backtest_with_gene(
        self,
        symbol: str,
        start: str,
        end: str,
        gene: Dict[str, Any],
        period: str = "1m",
        warmup: int = 60,
        generate_report: bool = False,
    ) -> Dict[str, Any]:
        """按基因执行回测（M1-03）。

        统一「基因 → GeneStrategy → Backtester」的构造路径，EvolutionEngine
        的评估可以通过本方法或直接构造 GeneStrategy，避免平行路径。

        参数:
            symbol: 合约代码
            start: 起始日期
            end: 结束日期
            gene: 树形基因 dict（含 type/factor/op 等键）
            period: K线周期
            warmup: 预热根数，默认 60（与 EvolutionEngine 默认一致）
            generate_report: 是否生成报告，默认 False（进化场景频繁回测不需要）

        返回:
            与 run_backtest 相同格式的结果字典。
        """
        # 延迟导入 GeneStrategy，避免包加载期循环
        from futures_quant.strategy.auto_evolve import GeneStrategy

        strategy = GeneStrategy(symbol, gene)
        return self.run_backtest(
            symbol, start, end,
            period=period, warmup=warmup,
            strategy=strategy, generate_report=generate_report,
        )


__all__ = ["BacktestService", "list_strategies"]
