"""M3.4 涨跌停扩板规则验收"""
from __future__ import annotations
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.data.price_limit import limit_pct_for_day, PriceLimitManager


def test_limit_pct():
    up, down = limit_pct_for_day(0)
    assert abs(up - 0.04) < 1e-9
    up, down = limit_pct_for_day(1)
    assert abs(up - 0.06) < 1e-9
    up, down = limit_pct_for_day(2)
    assert abs(up - 0.08) < 1e-9
    up, down = limit_pct_for_day(3)
    assert up == 1.0
    print("limit_pct_for_day OK")


def test_manager_normal():
    m = PriceLimitManager(default_limit=0.04, default_step=0.02, default_max_level=2)
    assert m.update("RB2601", "2026-09-01", 0.02) == 0   # 2% < 4% 正常
    assert m.limit_level("RB2601") == 0
    assert abs(m.threshold("RB2601") - 0.04) < 1e-9


def test_manager_expansion():
    m = PriceLimitManager(default_limit=0.04, default_step=0.02, default_max_level=2)
    d = "2026-09-02"
    assert m.update("AU2612", d, 0.041) == 1   # 第 1 天封板
    assert abs(m.threshold("AU2612") - 0.06) < 1e-9
    assert m.update("AU2612", d, 0.061) == 2   # 第 2 天封板
    assert abs(m.threshold("AU2612") - 0.08) < 1e-9
    assert m.update("AU2612", d, 0.081) == 99  # 第 3 天超 max_level → 封停


def test_manager_new_day_reset():
    m = PriceLimitManager()
    assert m.update("I2701", "2026-09-03", 0.045) == 1
    assert m.update("I2701", "2026-09-04", 0.02) == 0   # 新交易日 + 非封板 → 重置


def test_manager_downside():
    m = PriceLimitManager()
    assert m.update("M2705", "2026-09-05", -0.041) == 1  # 跌停方向同触发


def test_manager_reset():
    m = PriceLimitManager()
    m.update("X", "d1", 0.05)
    m.reset("X")
    assert m.limit_level("X") == 0
    m.update("Y", "d1", 0.05)
    m.reset_all()
    assert m.limit_level("Y") == 0
    print("test_price_limit.py 全绿")


if __name__ == "__main__":
    test_limit_pct()
    test_manager_normal()
    test_manager_expansion()
    test_manager_new_day_reset()
    test_manager_downside()
    test_manager_reset()
