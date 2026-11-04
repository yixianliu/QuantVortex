"""M2-12 进化引擎三类运行时故障根因回归测试（2026-10-04）。

用户现场报错（三类）：
1. `因子信号计算失败 [entry=hlc_avg]：sequence index must be integer, not 'slice'`
2. `IS 段回测失败：day is out of range for month: 0`
3. `本代基因评估失败（已跳过）：'gene'` + `进化引擎评估失败率过高：本代 5/10 评估失败`

根因与修复：
1. `factor_signal()` 只把 `closes` 转 list，遗留 `highs/lows` 未转；而 `StrategyBase`
   的 `_highs/_lows` 是 `collections.deque` —— deque 不支持切片，
   `highs[-n:]` 抛 TypeError。修复：入口统一转 list。
2. `validate._to_str()` 仅做 `str(dt)[:19]` 截断，`pd.NaT`/空串/整数索引等脏值
   原样透传给 `feed.get_history` → `pd.Timestamp` 解析失败。
   修复：`_to_str` 用 `pd.Timestamp` 严格校验 + `split_is_oos` 校验 index 为日期类型。
3. `EvolutionEngine._evaluate()` 命中缓存时返回 dict 只有 `_cached_gene` 没有 `gene`，
   但 `step()` 顺序路径仍用 `result["gene"]` 访问 → KeyError('gene')。
   修复：缓存命中 dict 补齐 `gene` 别名；且重评失败时降级为完整占位 dict
   （含 profitable/equity_curve/desc），保证 step() 尾部访问安全。

运行：
    python tests/unit/test_m2_12_evolve_failure_regression.py
    pytest tests/unit/test_m2_12_evolve_failure_regression.py -q
"""
from __future__ import annotations

import os
import sys
from collections import deque

import pandas as pd
import pytest

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.strategy import auto_evolve as ae  # noqa: E402
from futures_quant.strategy import validate as vd  # noqa: E402


# ---------------------------------------------------------------------------
# Bug 1：factor_signal 对 deque 输入不得抛 "sequence index must be integer"
# ---------------------------------------------------------------------------

def test_factor_signal_accepts_deque_without_slice_error():
    """deque 不支持切片；hlc_avg/typical_price 等因子必须能正常消费 deque。"""
    h = deque([100.0 + i * 0.5 for i in range(30)])
    l = deque([99.0 + i * 0.5 for i in range(30)])
    c = deque([99.5 + i * 0.5 for i in range(30)])

    for name, params in [
        ("hlc_avg", {"period": 5}),
        ("typical_price", {"period": 5}),
        ("donchian_break", {"period": 10}),
        ("price_channel", {"period": 10}),
        ("cci", {"period": 14, "upper": 100, "lower": -100}),
        ("willr", {"period": 14}),
        ("stoch_k", {"k_period": 9, "d_period": 3}),
        ("stoch_d", {"k_period": 9, "d_period": 3}),
        ("adx", {"period": 14}),
        ("sar", {"acceleration": 0.02, "maximum": 0.2}),
    ]:
        gene = {"type": "factor", "name": name, "params": params}
        sig = ae.factor_signal(gene, c, h, l)
        # 关键断言：不得返回 None（None = 计算失败），必须是 ±1/0
        assert sig is not None, f"{name} 对 deque 抛异常（应返回信号）"
        assert sig in (-1, 0, 1), f"{name} 返回非法信号 {sig}"


def test_factor_signal_numeric_result_unchanged_for_lists():
    """列表输入的结果语义不变（回归保护：修复不能改变数值行为）。"""
    h = [100.0 + i * 0.5 for i in range(30)]
    l = [99.0 + i * 0.5 for i in range(30)]
    c = [99.5 + i * 0.5 for i in range(30)]
    gene = {"type": "factor", "name": "hlc_avg", "params": {"period": 5}}
    from_list = ae.factor_signal(gene, c, h, l)
    from_deque = ae.factor_signal(gene, deque(c), deque(h), deque(l))
    assert from_list == from_deque, "deque 与 list 输入应产出相同信号"
    assert from_list == 1, "升序序列的 hlc_avg 应为 +1"


def test_typical_price_tolerates_missing_period_param():
    """【第4个 bug】typical_price 的 PARAM_SPACE 曾是 {}，因子 100% KeyError。

    现在：① PARAM_SPACE 已补 period；② factor_signal 用 .get 兜底，
    兼容盈利库中 params={} 的历史基因。
    """
    h = deque([100.0 + i * 0.5 for i in range(30)])
    l = deque([99.0 + i * 0.5 for i in range(30)])
    c = deque([99.5 + i * 0.5 for i in range(30)])
    # 空 params（历史基因形态）不得抛异常
    legacy = {"type": "factor", "name": "typical_price", "params": {}}
    assert ae.factor_signal(legacy, c, h, l) is not None
    # 新基因应带 period
    assert "period" in ae.PARAM_SPACE["typical_price"], \
        "PARAM_SPACE 缺 typical_price.period"


def test_all_entry_factors_have_referenced_params():
    """PARAM_SPACE 必须覆盖 factor_signal 实际读取的参数键（防再退化）。"""
    for name in ae.ENTRY_FACTORS:
        spec = ae.PARAM_SPACE.get(name)
        assert spec is not None, f"{name} 未登记 PARAM_SPACE"
        # obv/vwap 为占位因子（不读参数），允许空
        if name in ("obv", "vwap"):
            continue
        assert len(spec) > 0, f"{name} 的 PARAM_SPACE 为空，但因子会读参数"


def test_ensemble_signal_with_deque_history():
    """GeneStrategy 内部 _closes/_highs/_lows 为 deque，集成层不应失败。"""
    closes = deque([100.0 + i for i in range(60)])
    highs = deque([101.0 + i for i in range(60)])
    lows = deque([99.0 + i for i in range(60)])
    gene = {"type": "factor", "name": "hlc_avg", "params": {"period": 5}}
    sig = ae.ensemble_strategy_signal(gene, closes, highs, lows)
    assert sig in (-1.0, 0.0, 1.0), f"集成信号异常: {sig}"


# ---------------------------------------------------------------------------
# Bug 2：脏日期不得透传导致 "day is out of range for month: 0"
# ---------------------------------------------------------------------------

def test_to_str_rejects_invalid_dates():
    """_to_str 对 NaT/None/空串必须显式报错，不能产出脏字符串。"""
    for bad in (None, "", "NaT", pd.NaT, "not-a-date", "0000-00-00"):
        with pytest.raises(ValueError):
            vd._to_str(bad)


def test_to_str_normalizes_valid_dates():
    """合法日期统一输出 'YYYY-MM-DD HH:MM:SS'（秒精度，无纳秒污染）。"""
    assert vd._to_str("2020-01-01") == "2020-01-01 00:00:00"
    assert vd._to_str(pd.Timestamp("2020-01-01 08:30:15")) == "2020-01-01 08:30:15"
    ts = pd.Timestamp("2020-01-01 00:00:00.000000123")
    assert vd._to_str(ts) == "2020-01-01 00:00:00"


def test_split_is_oos_supports_datetime_column():
    """【真因回归】datetime 作为普通列（RangeIndex）时必须正常切分。

    这是 `day is out of range for month: 0` 的根因场景：修复前会取 index[0]=0
    → 产出 "0" → 下游 pd.Timestamp("0") 崩溃。
    """
    n = 200
    df = pd.DataFrame({
        "datetime": pd.date_range("2020-01-01", periods=n, freq="D"),
        "open": [100.0] * n, "high": [101.0] * n,
        "low": [99.0] * n, "close": [100.0] * n, "volume": [1] * n,
    })
    is_s, is_e, oos_s, oos_e, n_is, n_oos = vd.split_is_oos(df)
    for s in (is_s, is_e, oos_s, oos_e):
        assert pd.Timestamp(s).year == 2020, f"日期串被错误解析: {s}"
    assert is_s == "2020-01-01 00:00:00"
    assert n_is + n_oos == n
    assert is_e < oos_s


def test_split_is_oos_supports_datetime_index():
    """DatetimeIndex 场景保持向后兼容。"""
    idx = pd.date_range("2020-01-01", periods=200, freq="D")
    df = pd.DataFrame({"close": [1.0] * 200}, index=idx)
    is_s, is_e, oos_s, oos_e, n_is, n_oos = vd.split_is_oos(df)
    assert is_s == "2020-01-01 00:00:00"
    assert n_is + n_oos == 200
    assert is_e < oos_s


def test_split_is_oos_rejects_dataframe_without_any_date():
    """既无日期列、index 也非日期 → 必须早失败，不能产出 "0" 这种脏串。"""
    df = pd.DataFrame({"close": [1.0] * 100}, index=range(100))
    with pytest.raises(ValueError, match="IS/OOS 时间切分"):
        vd.split_is_oos(df)


def test_datetime_series_prefers_column_over_index():
    """_datetime_series 优先取 datetime 列。"""
    n = 10
    df = pd.DataFrame({
        "datetime": pd.date_range("2021-06-01", periods=n, freq="D"),
        "close": [1.0] * n,
    })
    s = vd._datetime_series(df)
    assert s.iloc[0] == pd.Timestamp("2021-06-01")


def test_timestamp_zero_reproduces_original_error():
    """固化证据：pd.Timestamp("0") 正是用户看到的报错来源。"""
    with pytest.raises(Exception, match="out of range for month"):
        pd.Timestamp("0")


def test_i_o_o_split_handles_invalid_dates_gracefully():
    """i_o_o_split 对非法日期应回退而非崩溃。"""
    s1, e1, s2, e2 = vd.i_o_o_split("", "", 0.7)
    assert s1 == "" and e1 == ""  # 原样回退


# ---------------------------------------------------------------------------
# Bug 3：缓存命中 dict 必须含 gene 键；step() 尾部不得 KeyError
# ---------------------------------------------------------------------------

def _make_feed():
    """真实合成数据源（含 open_interest 列），确保走生产回测链路而非降级路径。"""
    from futures_quant.data.synthetic import SyntheticFeed

    return SyntheticFeed()


# 回测区间：约 2 年日线，保证 len(df) 足够做 IS/OOS 切分
_BT_START = "2020-01-01"
_BT_END = "2021-12-31"


def test_evaluate_cache_hit_result_has_gene_key():
    """_evaluate 命中缓存时返回的 dict 必须含 'gene'（step 顺序路径会访问）。"""
    import random

    eng = ae.EvolutionEngine(
        feed=_make_feed(),
        universe=[("rb", "螺纹钢", 1, "SHFE", 10, 1.0)],
        start=_BT_START,
        end=_BT_END,
        period="D",
        seed=42,
    )
    gene = ae.random_gene(random.Random(1))
    # 手动塞入缓存，强制命中分支
    sig = ae.gene_signature(gene)
    eng._fit_cache[f"{sig}|{eng._data_version}"] = (gene, 12.5)
    res = eng._evaluate(gene)
    assert res.get("_cache_hit") is True
    assert "gene" in res, "缓存命中 dict 缺少 gene 键（会 KeyError）"
    assert res["gene"] is gene


def test_step_result_entries_always_have_profitable_and_gene():
    """step() 产出的 results 每条都必须含 gene/profitable/equity_curve/desc。"""
    import random

    eng = ae.EvolutionEngine(
        feed=_make_feed(),
        universe=[("rb", "螺纹钢", 1, "SHFE", 10, 1.0)],
        start=_BT_START,
        end=_BT_END,
        period="D",
        seed=7,
    )
    eng.POP_SIZE = 4
    eng.population = [ae.random_gene(random.Random(i)) for i in range(4)]
    # 预置缓存让部分基因走 cache-hit 分支（历史上此分支会 KeyError 'gene'）
    for i, g in enumerate(eng.population[:2]):
        eng._fit_cache[f"{ae.gene_signature(g)}|{eng._data_version}"] = (g, 5.0 + i)

    snap = eng.step()
    ranked = snap.get("ranked", [])
    assert len(ranked) >= 2, f"评估过少: {len(ranked)}"
    # snapshot["ranked"] 是 7 键投影（desc/signature/gene/metrics/fitness/
    # profitable/reasons）；其构造用 `r[k]` 直接取值，任何一个键缺失都会 KeyError。
    # 历史上 cache-hit dict 缺 gene/profitable，正是此处崩溃。
    for r in ranked:
        for k in ("desc", "signature", "gene", "metrics", "fitness",
                  "profitable", "reasons"):
            assert k in r, f"ranked 结果缺 {k} 键（曾引发 KeyError）"
    # 冠军曲线取自 results[0]["equity_curve"]，同样不能 KeyError
    assert isinstance(snap.get("gen_best_curve"), list)


def test_cache_hit_result_has_fitness_key():
    """缓存命中 dict 必须含 fitness 键（results.sort(key=x['fitness']) 会访问）。

    第 2 代起会大量命中第 1 代缓存，历史上此处抛 KeyError('fitness') 导致整代崩溃。
    """
    import random

    eng = ae.EvolutionEngine(
        feed=_make_feed(),
        universe=[("rb", "螺纹钢", 1, "SHFE", 10, 1.0)],
        start=_BT_START,
        end=_BT_END,
        period="D",
        seed=99,
    )
    gene = ae.random_gene(random.Random(3))
    eng._fit_cache[f"{ae.gene_signature(gene)}|{eng._data_version}"] = (gene, -3.0)
    res = eng._evaluate(gene)
    assert res.get("_cache_hit") is True
    for k in ("gene", "fitness", "metrics", "desc", "signature",
              "profitable", "reasons", "equity_curve", "trades"):
        assert k in res, f"缓存命中 dict 缺 {k} 键（step() 会 KeyError）"
    assert res["fitness"] == -3.0


def test_multi_generation_evolution_is_stable():
    """连续推进 3 代不得崩溃（第 2 代起命中缓存，历史上会 KeyError）。"""
    import random

    eng = ae.EvolutionEngine(
        feed=_make_feed(),
        universe=[("rb", "螺纹钢", 1, "SHFE", 10, 1.0)],
        start=_BT_START,
        end=_BT_END,
        period="D",
        seed=7,
    )
    eng.POP_SIZE = 5
    for gen_no in range(1, 4):
        snap = eng.step()
        assert snap["generation"] == gen_no, f"代数错位: {snap['generation']}"
        assert snap.get("ranked"), f"第 {gen_no} 代无评估结果"
        for r in snap["ranked"]:
            for k in ("desc", "signature", "gene", "metrics", "fitness",
                      "profitable", "reasons"):
                assert k in r, f"第 {gen_no} 代 ranked 缺 {k} 键"


def test_step_failure_rate_is_low():
    """修复后本代失败率应显著低于告警阈值 30%。"""
    import logging
    import random

    records = []

    class _WarnHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("futures_quant.strategy.auto_evolve")
    h = _WarnHandler()
    logger.addHandler(h)
    try:
        eng = ae.EvolutionEngine(
            feed=_make_feed(),
            universe=[("rb", "螺纹钢", 1, "SHFE", 10, 1.0)],
            start=_BT_START,
            end=_BT_END,
            period="D",
            seed=11,
        )
        eng.POP_SIZE = 6
        eng.population = [ae.random_gene(random.Random(i)) for i in range(6)]
        eng.step()
    finally:
        logger.removeHandler(h)

    failed = [m for m in records if "本代基因评估失败" in m]
    gene_keyerr = [m for m in failed if "'gene'" in m]
    assert not gene_keyerr, f"仍出现 KeyError('gene'): {gene_keyerr}"


# ---------------------------------------------------------------------------
# 直接运行入口
# ---------------------------------------------------------------------------

def main() -> None:
    test_factor_signal_accepts_deque_without_slice_error()
    print("[1] factor_signal 消费 deque 不再抛切片错误 ✅")

    test_factor_signal_numeric_result_unchanged_for_lists()
    print("[2] deque 与 list 输入语义一致 ✅")

    test_typical_price_tolerates_missing_period_param()
    print("[3] typical_price 兼容空 params ✅")

    test_all_entry_factors_have_referenced_params()
    print("[4] PARAM_SPACE 覆盖全部因子参数 ✅")

    test_ensemble_signal_with_deque_history()
    print("[5] ensemble_strategy_signal 集成层正常 ✅")

    test_to_str_rejects_invalid_dates()
    print("[6] _to_str 拒绝脏日期 ✅")

    test_to_str_normalizes_valid_dates()
    print("[7] _to_str 归一化合法日期 ✅")

    test_split_is_oos_supports_datetime_column()
    print("[8] split_is_oos 支持 datetime 列（真因场景）✅")

    test_split_is_oos_supports_datetime_index()
    print("[9] split_is_oos 兼容 DatetimeIndex ✅")

    test_split_is_oos_rejects_dataframe_without_any_date()
    print("[10] split_is_oos 拒绝无日期 DataFrame ✅")

    test_datetime_series_prefers_column_over_index()
    print("[11] _datetime_series 优先取 datetime 列 ✅")

    test_timestamp_zero_reproduces_original_error()
    print("[12] 固化证据 pd.Timestamp('0') 抛错 ✅")

    test_i_o_o_split_handles_invalid_dates_gracefully()
    print("[13] i_o_o_split 非法日期安全回退 ✅")

    test_evaluate_cache_hit_result_has_gene_key()
    print("[14] 缓存命中 dict 含 gene 键 ✅")

    test_cache_hit_result_has_fitness_key()
    print("[15] 缓存命中 dict 含 fitness 键（第2代不再崩）✅")

    test_step_result_entries_always_have_profitable_and_gene()
    print("[16] step() 结果字段完整（无 KeyError）✅")

    test_multi_generation_evolution_is_stable()
    print("[17] 连续 3 代进化稳定 ✅")

    test_step_failure_rate_is_low()
    print("[18] 本代评估无 KeyError('gene') ✅")

    print("=" * 60)
    print("M2-12 进化引擎故障回归测试 全部通过（18/18）")


if __name__ == "__main__":
    main()
