"""涨跌停扩板规则。

M3.4：正常 4%，扩板第1天 6%，第2天 8%，第3天封停。
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Tuple

def limit_pct_for_day(continuous_limit_days: int) -> Tuple[float, float]:
    """根据连续涨跌停天数返回涨跌幅阈值。
    
    参数:
        continuous_limit_days: 连续封板天数，0 表示非封板。
    返回:
        (up_pct, down_pct)
    """
    if continuous_limit_days == 0:
        return 0.04, 0.04
    if continuous_limit_days == 1:
        return 0.06, 0.06
    if continuous_limit_days == 2:
        return 0.08, 0.08
    # >=3 天封停
    return 1.0, 1.0  # 封停视为 100% 限制

def detect_limit_level(prev_close: float, open_price: float, high: float, low: float, close: float) -> Tuple[bool, bool, int]:
    """检测涨跌停状态。
    
    返回:
        is_up_limit, is_down_limit, limit_level（0正常，1扩板1，2扩板2，99封停）
    """
    if prev_close <= 0:
        return False, False, 0
    up_thresh = (high - prev_close) / prev_close
    down_thresh = (prev_close - low) / prev_close
    is_up = close >= high >= prev_close * 1.04 or close >= prev_close * 1.04
    is_down = close <= low <= prev_close * 0.96 or close <= prev_close * 0.96
    # 简化判断
    level = 0
    if is_up or is_down:
        level = 1
    return is_up, is_down, level


class PriceLimitManager:
    """涨跌停扩板状态管理器（多合约独立状态）。

    M3.4：连续封板天数驱动扩板等级。
        level=0  正常（阈值 = default_limit，如 4%）
        level=1  第 1 天扩板（阈值 = default_limit + step）
        level=2  第 2 天扩板（阈值 = default_limit + 2*step）
        level=99 封停（连续封板超过 default_max_level 天，反向单全拒）

    状态机由 update(symbol, day_key, pct) 驱动：
        - pct = 当日 (close-open)/open 涨跌幅；
        - 当 |pct| >= 当前阈值，记一次「封板日」，连续封板天数 +1；
        - 连续封板天数 > default_max_level → level=99；
        - 否则 level = min(连续封板天数, default_max_level)（封顶在 max_level）；
        - 非封板日重置连续天数为 0、level=0。

    仅用「当前及之前」bar 数据，杜绝未来函数。
    """

    SEALING_LEVEL = 99  # 封停等级

    def __init__(self, default_limit: float = 0.04, default_step: float = 0.02,
                 default_max_level: int = 2) -> None:
        """
        参数:
            default_limit: 正常涨跌停幅度（如 0.04 = 4%）
            default_step: 每日扩板步进（如 0.02 = 2%）
            default_max_level: 最大扩板天数（超过即封停，默认 2 → 第 3 天封停）
        """
        self.default_limit = float(default_limit)
        self.default_step = float(default_step)
        self.default_max_level = int(default_max_level)
        # symbol -> {consec_days: 连续封板天数, level: 当前扩板等级, last_day: 最近处理日}
        self._state: dict = {}

    def _entry(self, symbol: str) -> dict:
        return self._state.setdefault(symbol, {"consec_days": 0, "level": 0, "last_day": ""})

    def update(self, symbol: str, day_key: str, pct: float) -> int:
        """喂入一根 bar 的当日涨跌幅 pct，更新该合约扩板状态。

        参数:
            symbol: 合约代码
            day_key: 交易日键（用于「新交易日重置」判断）
            pct: 当日涨跌幅 (close-open)/open
        返回:
            当前扩板等级（0/1/2/99）
        """
        st = self._entry(symbol)
        # 新交易日：重置连续封板计数（扩板只按「连续交易日」累计）
        if day_key and st["last_day"] and day_key != st["last_day"]:
            st["consec_days"] = 0
            st["level"] = 0
        st["last_day"] = day_key

        # 当前生效阈值 = default_limit + step * 当前等级
        cur_level = st["level"]
        effective = self.default_limit + self.default_step * cur_level
        if abs(pct) >= effective:
            st["consec_days"] += 1
            if st["consec_days"] > self.default_max_level:
                st["level"] = self.SEALING_LEVEL
            else:
                st["level"] = min(st["consec_days"], self.default_max_level)
        else:
            st["consec_days"] = 0
            st["level"] = 0
        return st["level"]

    def limit_level(self, symbol: str) -> int:
        """返回合约当前扩板等级（0 正常 / 1 / 2 / 99 封停）。"""
        return self._entry(symbol)["level"]

    def threshold(self, symbol: str) -> float:
        """返回合约当前生效涨跌停阈值。"""
        return self.default_limit + self.default_step * self._entry(symbol)["level"]

    def reset(self, symbol: str) -> None:
        """重置合约扩板状态。"""
        self._state.pop(symbol, None)

    def reset_all(self) -> None:
        """重置全部合约状态。"""
        self._state.clear()
