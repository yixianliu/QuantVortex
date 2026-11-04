"""第二轮 P0-4 回归测试：合约乘数 / 最小变动价位 / 基准价的精确匹配。

数据来源（交易所公开合约细则，2024-2026 版本）：
  - 上期所 SHFE：螺纹 RB、铜 CU、黄金 AU、纸浆 SP 等合约附件
  - 大商所 DCE：铁矿 I、焦炭 J、焦煤 JM、生猪 LH 等合约附件
  - 郑商所 CZCE：纯碱 SA、尿素 UR、菜油 OI、对二甲苯 PX 等合约附件
  - 中金所 CFFEX：IF/IH/IC/IM 与 T/TF/TS/TL 合约附件
  - 上期能源 INE：国际铜 BC、20 号胶 NR、低硫燃料油 LU、集运指数 EC 合约附件
基准价属于「参考价」，非交易所合约细则字段；表中区间取自 akshare 公开行情量级，
仅用于验证精确匹配没有串到别的品种（例如 IF 不能拿到铁矿石 850 的基准价）。
"""
from __future__ import annotations

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from futures_quant.data.contract_specs import get_contract_spec
from futures_quant.data.synthetic import FUTURES_UNIVERSE, find_universe_row, universe_code


# (代码, 乘数, 最小变动价位) —— 交易所公开合约细则
SPEC_TABLE = [
    ("RB", 10, 1.0), ("I", 100, 0.5), ("J", 100, 0.5), ("JM", 60, 0.5),
    ("CU", 5, 10.0), ("AU", 1000, 0.02),
    ("IF", 300, 0.2), ("IH", 300, 0.2), ("IC", 200, 0.2), ("IM", 200, 0.2),
    ("T", 10000, 0.005), ("TF", 10000, 0.005), ("TS", 10000, 0.005), ("TL", 10000, 0.005),
    ("SA", 20, 1.0), ("UR", 20, 1.0), ("OI", 10, 1.0), ("CS", 10, 1.0),
    ("LH", 16, 5.0), ("AO", 20, 1.0), ("EC", 50, 0.1),
    ("BC", 5, 5.0), ("NR", 10, 1.0), ("LU", 10, 1.0), ("SP", 10, 2.0),
    ("PX", 5, 2.0), ("PR", 15, 2.0),
]

# (代码, 基准价下限, 基准价上限) —— akshare 公开行情量级参考（非交易所细则）
PRICE_BAND = [
    ("I", 500, 1300), ("IF", 2800, 4800),
    ("JM", 900, 3000), ("CU", 40000, 90000),
    ("AU", 300, 900), ("EC", 800, 3000),
]


def test_spec_table_matches_exchange_rules():
    """表驱动：乘数与最小变动价位必须与交易所公开细则一致。"""
    for code, mult, tick in SPEC_TABLE:
        spec = get_contract_spec(f"{code}.SHFE")
        assert spec["symbol"] == code, f"{code}: 归一化命中错误 {spec['symbol']}"
        assert spec["multiplier"] == float(mult), f"{code}: 乘数 {spec['multiplier']} != {mult}"
        assert spec["min_price_tick"] == float(tick), f"{code}: tick {spec['min_price_tick']} != {tick}"


def test_base_price_band():
    """基准价落在公开行情量级内，且未串到其它品种。"""
    for code, lo, hi in PRICE_BAND:
        spec = get_contract_spec(code)
        assert lo <= spec["typical_price"] <= hi, \
            f"{code}: 基准价 {spec['typical_price']} 不在 {lo}-{hi} 量级"


def test_exact_match_no_prefix_collision():
    """P0-4 回归：IF/IH/IC/IM 不得命中 I；JM 不得命中 J。"""
    assert get_contract_spec("IF.CFFEX")["multiplier"] == 300.0
    assert get_contract_spec("IH.CFFEX")["multiplier"] == 300.0
    assert get_contract_spec("IC.CFFEX")["multiplier"] == 200.0
    assert get_contract_spec("IM.CFFEX")["multiplier"] == 200.0
    assert get_contract_spec("I.DCE")["multiplier"] == 100.0
    assert get_contract_spec("JM.DCE")["multiplier"] == 60.0
    assert get_contract_spec("J.DCE")["multiplier"] == 100.0
    # 具体月份合约同样精确命中品种，而不是靠字符串前缀
    assert get_contract_spec("IF2601.CFFEX")["multiplier"] == 300.0
    assert get_contract_spec("i2409.DCE")["multiplier"] == 100.0
    assert get_contract_spec("rb2410.SHFE")["multiplier"] == 10.0


def test_universe_helper_exact():
    assert universe_code("rb2410.SHFE") == "RB"
    assert universe_code("IF2601") == "IF"
    assert universe_code("IM2601") == "IM"
    assert find_universe_row("IF.CFFEX")[4] == 300
    assert find_universe_row("I.DCE")[4] == 100
    assert find_universe_row("PD.SHFE") is None, "伪品种 PD 必须已从品种表移除"


def test_pd_removed_and_unknown_fallback():
    """移除伪品种 PD；未知代码只能返回显式兜底，不得静默套用某品种规格。"""
    codes = {row[0] for row in FUTURES_UNIVERSE}
    assert "PD" not in codes
    spec = get_contract_spec("PD.SHFE")
    assert spec["symbol"] == "UNKNOWN"
    assert spec["multiplier"] == 10.0
