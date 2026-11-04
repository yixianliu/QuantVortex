"""回测经纪商：委托在下一根 bar 开盘价撮合（杜绝未来函数）。

M2.3 撮合引擎差异化（期货规则严谨性）：
    - 差异化费率：开仓 / 平昨 / 平今 三种费率，按合约 commission_per_lot 与
      close_today_commission_ratio 计算，成交记录回填 Trade.commission。
      平今仓费（CLOSE_TODAY）= 开仓费 × close_today_commission_ratio，
      平昨仓费（CLOSE_YESTERDAY）= 开仓费（ratio=1.0）。
    - 滑点三模式（slip_mode）：
        * fixed：开盘价 ± slippage × min_tick（默认，向后兼容）
        * ratio：开盘价 ± 滑点价格（= open × slip_ratio）再对齐 tick
        * atr  ：波动率自适应，slip_ticks = max(1, slip_atr_k × ATR/close × 100)，
                 滑点价格 = slip_ticks × min_tick；ATR 取当前 bar 及其前
                 atr_window 根真实波幅均值，仅用历史数据（防未来函数）
    - 涨跌停拦截（第二轮 P0-7 修正）：限价带以「上一交易日结算价 × (1 ± 幅度)」
      为唯一基准，禁止用当根 close 判断当根 open 能否成交（消除未来函数）。
      仅比较当根开盘价：开盘即处于涨停价 → 买入方向（开多/平空）不能成交；
      开盘即处于跌停价 → 卖出方向（开空/平多）不能成交。
    - 扩板状态机未启用：交易所扩板规则无法在本轮回测内核对，保留入参
      ``limit_level`` 仅为 API 兼容，实际撮合一律使用基准幅度，不做扩板。
    - 挂单过期（第二轮 P1-5）：同品种每经过一根未成交 K 线累加存活根数，
      达到 ``pending_expire_bars`` 即撤单，防止陈旧限价单长期滞留。
    - 品种过滤（第二轮 P1-5）：只撮合 ``order.symbol == bar.symbol`` 的委托，
      禁止跨品种串单成交。

设计约束：
    - 平今/平昨识别基于订单下单日与订单方向对应的开仓日比较（T+0 当日开平为平今，
      否则为平昨），与 core.types.Offset 语义严格对齐；识别失败时回落原 offset。
    - 撮合严格「下一根 bar 开盘价」，委托在 bar N 产生，在 bar N+1 撮合。
"""
from __future__ import annotations

from datetime import date as _date
from typing import Optional

from ..core.types import Direction, Offset, Order, OrderStatus, OrderType, Trade
from .base import BrokerBase


class BacktestBroker(BrokerBase):
    """回测 broker：按 M2.3 差异化费率 / 滑点 / 涨跌停规则撮合。

    继承: BrokerBase
    """

    def __init__(
        self,
        slippage: float = 1.0,
        min_tick: float = 1.0,
        contracts: Optional[dict] = None,
        multiplier: float = 10.0,
        slip_mode: str = "fixed",
        slip_ratio: float = 0.0,
        slip_atr_k: float = 0.5,
        atr_window: int = 14,
        limit_up_pct: float = 0.04,
        limit_down_pct: float = 0.04,
        pending_expire_bars: int = 5,
        logger=None,
    ) -> None:
        """初始化相关对象。

        参数:
            slippage: fixed 模式下的 tick 数（默认 1 tick）
            min_tick: 无合约时的默认最小变动价位
            contracts: {symbol: Contract}，含 commission_per_lot / min_price_tick /
                       multiplier / close_today_commission_ratio 等品种规格
            multiplier: 合约未知时的默认乘数
            slip_mode: "fixed" | "ratio" | "atr"
            slip_ratio: 比例滑点系数（ratio 模式）
            slip_atr_k: ATR 自适应系数 k（atr 模式），slip_ticks = k × ATR/close × 100
            atr_window: ATR 平滑窗口（atr 模式）
            limit_up_pct / limit_down_pct: 涨跌停幅度（相对上一交易日结算价）
            pending_expire_bars: 挂单最多存活的同品种 K 线根数（达到即撤单）
            logger: 日志器（拒单时输出 warning）
        """
        self.slippage = float(slippage)
        self.min_tick = float(min_tick)
        self.contracts = contracts or {}
        self.multiplier = float(multiplier)
        self.pending: list[Order] = []
        self.slip_mode = slip_mode
        self.slip_ratio = float(slip_ratio)
        self.slip_atr_k = float(slip_atr_k)
        self.atr_window = int(atr_window)
        self.limit_up_pct = float(limit_up_pct)
        self.limit_down_pct = float(limit_down_pct)
        self.pending_expire_bars = max(1, int(pending_expire_bars))
        self.logger = logger
        # 实例属性（每 broker 独立，避免类变量共享）
        self._open_history: list = []       # (symbol, direction, open_date) 开仓记录
        self._history_closes: dict = {}     # {symbol: [close, ...]}
        self._history_highs: dict = {}
        self._history_lows: dict = {}
        self._last_bar_symbol = None
        self._last_bar_close = 0.0

    # ---------- 工具 ----------
    def _tick(self, symbol: str) -> float:
        """取合约最小变动价位，未知合约回落默认 tick。"""
        c = self.contracts.get(symbol)
        return float(c.min_price_tick) if c else self.min_tick

    @staticmethod
    def _order_date(order: Order) -> Optional[_date]:
        """解析订单 datetime 为 date；失败返回 None。"""
        dt = order.datetime
        if dt is None:
            return None
        if hasattr(dt, "date"):
            try:
                return dt.date()
            except Exception:  # noqa: BLE001
                return None
        try:
            return _date.fromisoformat(str(dt))
        except Exception:  # noqa: BLE001
            return None

    def _classify_offset(self, order: Order) -> Offset:
        """区分平仓单为平今还是平昨（T+0 期货规则）。

        平仓方向与开仓方向相反：
            平多单（direction=SHORT，offset=CLOSE）对应「多头开仓」（LONG + OPEN）
            平空单（direction=LONG ，offset=CLOSE）对应「空头开仓」（SHORT + OPEN）
        若开仓记录与下单日同日 → 平今（CLOSE_TODAY），否则平昨（CLOSE_YESTERDAY）。
        订单未带 datetime 或查不到开仓记录时，回落原 offset（保持兼容）。
        防未来函数：仅比较当前时点已知日期，不读未来。
        """
        if order.offset == Offset.OPEN:
            return Offset.OPEN
        od = self._order_date(order)
        if od is None:
            return order.offset
        open_dir = Direction.LONG if order.direction == Direction.SHORT else Direction.SHORT
        for sym, odir, odate in self._open_history:
            if sym == order.symbol and odir == open_dir and odate == od:
                return Offset.CLOSE_TODAY
        return Offset.CLOSE_YESTERDAY

    def _slip_ticks(self, bar, symbol: str) -> float:
        """按 slip_mode 计算滑点 tick 数（≥1，防 0 滑点失真）。

        防未来函数：ATR 仅用当前 bar 及其前 atr_window 根的 high/low/close。
        """
        if self.slip_mode == "fixed":
            return max(1.0, self.slippage)
        if self.slip_mode == "ratio":
            ref = float(getattr(bar, "open", 0.0) or 0.0)
            tick = self._tick(symbol)
            if ref <= 0 or tick <= 0:
                return max(1.0, self.slippage)
            slip_price = ref * self.slip_ratio
            return max(1.0, slip_price / tick)
        # atr 模式：波动率自适应 slip = k × ATR / price × 100（单位：tick 数近似）
        # 防未来函数：仅用当前 bar 及历史（_history_* 在每次 match 时累积，不含未来）
        if self.slip_atr_k <= 0:
            return max(1.0, self.slippage)
        highs = self._history_highs.get(symbol, [])
        lows = self._history_lows.get(symbol, [])
        closes = self._history_closes.get(symbol, [])
        # _history_* 已在 match() 入口累积当前 bar，n = 当前 bar 位置（含）
        # TR[i] = max(hi_i - lo_i, |hi_i - close_{i-1}|, |lo_i - close_{i-1}|)
        # i 的有效范围是 1 ~ n-1（i=0 无 close_{-1}，跳过）
        n = min(len(highs), len(lows), len(closes))
        trs = []
        for i in range(1, n):
            hi = highs[i]
            lo = lows[i]
            pc = closes[i - 1]
            trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
        if not trs:
            return max(1.0, self.slippage)
        window_trs = trs[-self.atr_window:]
        atr_val = sum(window_trs) / len(window_trs)
        price = float(getattr(bar, "close", 0.0) or 0.0)
        if price <= 0:
            return max(1.0, self.slippage)
        slip_ticks = self.slip_atr_k * (atr_val / price) * 100.0
        return max(1.0, slip_ticks)

    # ---------- 撮合 ----------
    def submit(self, order: Order) -> None:
        """接收委托入队；回测模式下委托在下一根 bar 撮合（防未来函数）。"""
        order.status = OrderStatus.SUBMITTED
        self.pending.append(order)
        od = self._order_date(order)
        if order.offset == Offset.OPEN and od is not None:
            self._open_history.append((order.symbol, order.direction, od))
            if len(self._open_history) > 200:
                self._open_history = self._open_history[-200:]

    def match(
        self,
        bar,
        limit_level: Optional[int] = None,
        limit_up_pct: Optional[float] = None,
        limit_down_pct: Optional[float] = None,
    ) -> list[Trade]:
        """撮合当前 bar 的委托并返回成交列表（回测专用）。

        防未来函数：策略在 bar N 产生的信号委托不会在 bar N 内成交，
        而是在下一根 bar（即调用本方法时传入的 bar）的开盘价撮合。

        参数:
            bar: 当前用于撮合的 K 线（信号产生后的下一根 bar）；其 ``prev_settle``
                 字段为上一交易日结算价（涨跌停限价带的唯一基准）
            limit_level: 已停用（扩板状态机未启用），仅为 API 兼容保留
            limit_up_pct: 当日有效涨停幅度（覆盖实例默认值，None 用默认）
            limit_down_pct: 当日有效跌停幅度（覆盖实例默认值，None 用默认）

        返回:
            list[Trade]: 本根 bar 内成交的 Trade 列表
        """
        sym = getattr(bar, "symbol", None)
        # 记录当前 bar 的 OHLC 供后续 ATR 滑点使用（防未来函数：仅累积历史）
        self._history_closes.setdefault(sym, []).append(float(bar.close))
        self._history_highs.setdefault(sym, []).append(float(bar.high))
        self._history_lows.setdefault(sym, []).append(float(bar.low))
        self._last_bar_symbol = sym
        self._last_bar_close = float(bar.close)

        # 涨跌停判定（P0-7）：基准 = 上一交易日结算价 × (1 ± 幅度)
        # 仅用「已知的昨结算」与「当根开盘价」，绝不使用当根 close。
        up = limit_up_pct if limit_up_pct is not None else self.limit_up_pct
        down = limit_down_pct if limit_down_pct is not None else self.limit_down_pct
        o = float(bar.open)
        prev_settle = getattr(bar, "prev_settle", None)
        # 未显式注入昨结算时「不判涨跌停」（fail-open）：用上一根分钟收盘冒充结算价
        # 会把正常波动误判为封板，宁可不拦截也不能错杀。Backtester 会逐根注入。
        locked_up = False
        locked_down = False
        if prev_settle is not None and prev_settle > 0 and o > 0:
            limit_up_price = prev_settle * (1.0 + up)
            limit_down_price = prev_settle * (1.0 - down)
            locked_up = o >= limit_up_price
            locked_down = o <= limit_down_price
        trades: list[Trade] = []
        still_pending: list[Order] = []
        for order in self.pending:
            # 品种过滤（P1-5）：只撮合本根 bar 所属品种，其余委托原样保留
            if order.symbol != sym:
                still_pending.append(order)
                continue

            contract = self.contracts.get(order.symbol)
            tick = self._tick(order.symbol)
            slip_ticks = self._slip_ticks(bar, order.symbol)
            if order.direction == Direction.LONG:
                fill = o + slip_ticks * tick
            else:
                fill = o - slip_ticks * tick

            # 限价单未触发：累计存活根数，超期撤单
            if order.order_type == OrderType.LIMIT and order.limit_price is not None:
                not_triggered = (
                    (order.direction == Direction.LONG and fill > order.limit_price)
                    or (order.direction == Direction.SHORT and fill < order.limit_price)
                )
                if not_triggered:
                    order.bars_alive += 1
                    if order.bars_alive >= self.pending_expire_bars:
                        order.status = OrderStatus.CANCELLED
                        order.reject_reason = f"挂单超过 {self.pending_expire_bars} 根未成交撤单"
                        if self.logger:
                            self.logger.warning(
                                f"[撤单] {order.symbol} {order.order_id} 挂单超时")
                    else:
                        still_pending.append(order)
                    continue

            # 涨跌停方向拦截（买入方向=开多/平空；卖出方向=开空/平多）
            #   涨停：买入不能成交；跌停：卖出不能成交。
            is_buy = order.direction == Direction.LONG   # OPEN+LONG 或 CLOSE+LONG(平空)
            is_sell = order.direction == Direction.SHORT  # OPEN+SHORT 或 CLOSE+SHORT(平多)
            rejected = (locked_up and is_buy) or (locked_down and is_sell)
            if rejected:
                order.status = OrderStatus.REJECTED
                order.reject_reason = ("涨停：买入方向不可成交" if locked_up
                                       else "跌停：卖出方向不可成交")
                if self.logger:
                    self.logger.warning(
                        f"[拒单] {order.symbol} {order.direction.value} "
                        f"{order.offset.value} {order.reject_reason}（昨结算={prev_settle}）")
                continue

            # 平今 / 平昨识别（M2.3 差异化费率）
            real_offset = self._classify_offset(order)
            order.offset = real_offset
            mult = float(contract.multiplier) if contract else self.multiplier
            base_fee = float(contract.commission_per_lot) if contract else 3.0
            if real_offset == Offset.CLOSE_TODAY:
                ratio = (float(contract.close_today_commission_ratio)
                         if contract and contract.close_today_commission_ratio is not None
                         else 1.0)
                fee = abs(order.quantity) * base_fee * ratio
            else:
                fee = abs(order.quantity) * base_fee

            trade = Trade(
                symbol=order.symbol,
                direction=order.direction,
                offset=real_offset,
                quantity=order.quantity,
                price=round(fill, 4),
                datetime=bar.datetime,
                order_id=order.order_id,
                multiplier=mult,
                commission=fee,
            )
            order.status = OrderStatus.FILLED
            order.filled_price = fill
            order.filled_quantity = order.quantity
            trades.append(trade)
        self.pending = still_pending
        return trades

    # ---------- 生命周期 ----------
    def reset(self) -> None:
        """重置待成交队列与开仓历史（新回测会话前调用）。"""
        self.pending = []
        self._open_history = []
        self._history_closes = {}
        self._history_highs = {}
        self._history_lows = {}
