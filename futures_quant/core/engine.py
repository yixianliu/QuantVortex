"""交易引擎（回测 / 仿真 / 实盘共用核心）。

职责：
    1) 接收策略信号 -> 风控校验 -> 经纪商撮合 -> 组合记账；
    2) 每根 bar 更新权益、执行风控后检、记录资金曲线；
    3) 风控触发时平仓锁仓。
回测与仿真的差异仅在撮合时机（next_open vs 即时），由 broker 决定。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..broker.backtest_broker import BacktestBroker
from ..broker.paper import PaperBroker
from ..config.settings import Config
from ..core.portfolio import Portfolio
from ..core.types import Bar, Direction, Offset, Order, OrderStatus, Trade
from ..risk.risk_manager import RiskManager
from ..storage import StorageBackend


def _parse_delivery(value) -> Optional[object]:
    """将交割日字符串解析为 date 对象；支持 'YYYY-MM-DD' / 'YYYYMMDD'；非法返回 None。"""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:  # noqa: BLE001
            continue
    return None


class TradingEngine:
    def __init__(self, config: Config, logger=None, mode: str = "backtest", db: Optional[StorageBackend] = None,
                 multiplier: Optional[float] = None) -> None:
        self.config = config
        self.mode = mode
        self.logger = logger
        self.db = db

        acc = config.account
        self.portfolio = Portfolio(
            initial_capital=acc.initial_capital,
            margin_rate=acc.margin_rate,
            commission_per_lot=acc.commission_per_lot,
            logger=logger,
            multiplier=multiplier if multiplier else acc.multiplier,
            close_today_ratio=acc.close_today_ratio,
        )
        self.risk = RiskManager(config.risk, logger)

        self.contracts: dict = {}
        self.strategies: list = []
        self.equity_curve: List[tuple] = []   # (datetime, equity, available)
        self.trades_log: List[Trade] = []
        self._order_seq = 0
        self._current_dt = None
        self._equity_peak = 0.0  # 增量维护资金峰值，避免每根 bar 全量扫描 O(n^2)

        bt = config.backtest
        if mode == "backtest":
            self.broker = BacktestBroker(slippage=bt.slippage, contracts=self.contracts)
        else:
            self.broker = PaperBroker(slippage=bt.slippage, contracts=self.contracts)

    # ---------- 注册 ----------
    def add_contract(self, contract) -> None:
        self.contracts[contract.symbol] = contract

    def register_strategy(self, strategy) -> None:
        strategy.engine = self
        self.strategies.append(strategy)

    def get_position(self, symbol: str) -> tuple:
        pos = self.portfolio.positions.get(symbol)
        return (pos.long_qty, pos.short_qty) if pos else (0, 0)

    # ---------- 下单 ----------
    def send_order(
        self, symbol, direction: Direction, offset: Offset, quantity: int,
        order_type=None, limit_price=None,
    ) -> Optional[Order]:
        from ..core.types import OrderType
        order_type = order_type or OrderType.MARKET
        self._order_seq += 1
        order = Order(
            symbol=symbol, direction=direction, offset=offset, quantity=quantity,
            order_type=order_type, limit_price=limit_price,
            datetime=self._current_dt, order_id=f"O{self._order_seq:06d}",
        )
        contract = self.contracts.get(symbol)
        ok, reason = self.risk.check_order(order, self.portfolio, contract, self._current_dt)
        if not ok:
            order.status = OrderStatus.REJECTED
            order.reject_reason = reason
            if self.logger:
                self.logger.warning(f"[拒单] {symbol} {direction.value} {offset.value} "
                                    f"{quantity} -> {reason}")
            if self.db:
                self.db.insert_order(order)
            return order

        if self.db:
            self.db.insert_order(order)

        if self.mode == "backtest":
            self.broker.submit(order)
        else:
            price = self.portfolio._current_prices.get(symbol)
            for t in self.broker.fill_now(order, price):
                self._accept_trade(t)
        return order

    def _accept_trade(self, trade: Trade) -> None:
        self.portfolio.process_trade(trade)
        self.trades_log.append(trade)
        if self.db:
            self.db.insert_trade(trade)

    # ---------- 主循环（按 bar 驱动） ----------
    def process_bar(self, bar: Bar) -> None:
        self._current_dt = bar.datetime
        self.portfolio.update_price(bar.symbol, bar.close)

        # 交割日临近强制平仓（期货不能持有进入交割月/交割日之后）
        contract = self.contracts.get(bar.symbol)
        ddate = _parse_delivery(contract.delivery_date) if contract else None
        if ddate is not None:
            try:
                bdate = bar.datetime.date() if hasattr(bar.datetime, "date") else None
            except Exception:  # noqa: BLE001
                bdate = None
            if bdate is not None and bdate >= ddate:
                pos = self.portfolio.positions.get(bar.symbol)
                if pos and (pos.long_qty or pos.short_qty):
                    if self.logger:
                        self.logger.warning(
                            f"[交割] {bar.symbol} 临近交割日 {contract.delivery_date}，"
                            f"强制平掉全部持仓")
                    self.flatten_all()

        if self.mode == "backtest":
            for t in self.broker.match(bar):
                self._accept_trade(t)

        for strat in self.strategies:
            if strat.symbol == bar.symbol:
                try:
                    strat.on_bar(bar)
                except Exception as exc:
                    if self.logger:
                        self.logger.error(f"[策略异常] {strat.name}: {exc}")

        triggered = self.risk.on_new_bar(self.portfolio, bar.datetime)
        if triggered:
            self.flatten_all()

        eq = self.portfolio.equity()
        avail = self.portfolio.available()
        if eq > self._equity_peak:
            self._equity_peak = eq
        peak = self._equity_peak
        dd = (peak - eq) / peak if peak > 0 else 0.0
        self.equity_curve.append((bar.datetime, eq, avail))

        # 行情 / 资金曲线落地（仅 live / 仿真模式逐笔写入；回测量大且已有文件导出，跳过以保性能）
        if self.db and self.mode != "backtest":
            self.db.insert_bars([bar])
            self.db.save_equity_point(bar.datetime, eq, avail, dd)

    def flatten_all(self) -> None:
        """风控触发时平掉所有持仓（锁仓）。"""
        for sym, pos in list(self.portfolio.positions.items()):
            if pos.long_qty > 0:
                self.send_order(sym, Direction.SHORT, Offset.CLOSE, pos.long_qty)
            if pos.short_qty > 0:
                self.send_order(sym, Direction.LONG, Offset.CLOSE, pos.short_qty)

    def start(self) -> None:
        self.risk.start(self.portfolio)
