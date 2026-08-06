"""配置层。

从 JSON 文件加载系统配置；若文件不存在则写入默认配置。
所有模块通过 Config 对象读取参数，避免硬编码。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class AccountConfig:
    initial_capital: float = 1_000_000.0
    margin_rate: float = 0.10        # 保证金率（= 1 / leverage）
    leverage: float = 10.0           # 杠杆倍数（与 margin_rate 互为推导，优先用 leverage）
    multiplier: float = 10.0         # 合约乘数（每手对应标的单位数，如 rb=10, IF=300）
    commission_per_lot: float = 3.0   # 每手手续费（元/手）
    close_today_ratio: float = 0.5   # 平今仓手续费折扣（期货 T+0 平今通常减半或免收）


@dataclass
class RiskConfig:
    max_single_loss: float = 5_000.0        # 单笔最大亏损
    max_daily_loss: float = 30_000.0        # 单日最大亏损
    max_drawdown: float = 0.20              # 总资金最大回撤阈值
    max_position_per_symbol: int = 50       # 单品种最大持仓手数
    max_total_position_ratio: float = 0.80  # 总仓位占用上限（占权益）
    max_order_qty: int = 100                # 单笔下单数量上限
    non_trading_hours_block: bool = True     # 非交易时段禁止下单


@dataclass
class BacktestConfig:
    slippage: float = 1.0                   # 滑点（最小变动价位个数）
    fill_mode: str = "next_open"            # 回测撮合：next_open（防未来函数）
    start_cash: float = 1_000_000.0


@dataclass
class UIConfig:
    theme: str = "dark"                      # dark / light


@dataclass
class StorageConfig:
    backend: str = "sqlite"                 # sqlite（默认）| postgres
    sqlite_path: str = "data/futures_quant.db"
    # 生产 / 时序后端连接参数（backend=postgres 时生效）
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_db: str = "futures"
    pg_user: str = "postgres"
    pg_password: str = ""
    pg_timescale: bool = True               # 用 TimescaleDB 超表存 K 线 / 资金曲线


@dataclass
class Config:
    account: AccountConfig = field(default_factory=AccountConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    data_path: str = "data"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        return cls(
            account=AccountConfig(**d.get("account", {})),
            risk=RiskConfig(**d.get("risk", {})),
            backtest=BacktestConfig(**d.get("backtest", {})),
            ui=UIConfig(**d.get("ui", {})),
            storage=StorageConfig(**d.get("storage", {})),
            data_path=d.get("data_path", "data"),
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Config":
        if not os.path.exists(path):
            cfg = cls()
            cfg.save(path)
            return cfg
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
