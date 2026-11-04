# -*- coding: utf-8 -*-
"""M3-02 特征契约测试（P0，依赖 M3-01）。

验收（来自 UPGRADE_PLAN_V5.md）：
  ① 断言 FEATURE_SOURCE 每个值都在 tech.add_indicators 产出列集合内；
  ② 断言 EXTENDED_FEATURES 与 predictor 实际消费列一致；
  ③ 断言无前视：对 df 截断到 t，特征在 [0,t] 的值与全量计算一致（误差 <1e-12）；
  ④ 人为删除一个产出列 → 测试 Fail（Fail Fast 生效）。

注：项目尚未建 pytest.ini / tests/conftest.py（M1-10 未实施），
故此处沿用既有单测惯例自行注入 sys.path。
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.indicators.tech import add_indicators
from futures_quant.ai.features import (
    build_features,
    BASE_FEATURES,
    EXTENDED_FEATURES,
    FEATURE_SOURCE,
    _validate_feature_source,
)


# ---------------------------------------------------------------------------
# 测试数据：有趋势 + 有波动的合成行情（避免常量序列让指标恒 0）
# ---------------------------------------------------------------------------
def _make_df(n: int = 300, seed: int = 11) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    trend = np.linspace(100, 130, n)
    close = trend + np.cumsum(rng.randn(n)) * 0.8
    high = close + np.abs(rng.randn(n)) * 1.5
    low = close - np.abs(rng.randn(n)) * 1.5
    open_ = close + rng.randn(n) * 0.3
    volume = np.abs(rng.randn(n)) * 1000 + 5000
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


# ---------------------------------------------------------------------------
# ① FEATURE_SOURCE 的每个来源列都必须真实存在
# ---------------------------------------------------------------------------
def test_feature_source_columns_exist():
    """FEATURE_SOURCE 声明的来源列，必须都在 add_indicators 产出列集合内。"""
    ind = add_indicators(_make_df())
    produced = set(ind.columns)
    bad = [
        (f, src) for f, src in FEATURE_SOURCE.items()
        if src is not None and src not in produced
    ]
    assert not bad, (
        f"FEATURE_SOURCE 声明了 add_indicators 不产出的列：{bad}。"
        f"请在 tech.add_indicators 补齐，或修正映射表")


def test_build_features_fails_when_indicator_missing(monkeypatch):
    """端到端反向验证：让 add_indicators 少产出一个列 → build_features 必须报错。

    模拟「tech 侧回归导致某列不再产出」的真实故障场景，确认契约会在
    特征构建阶段就抛错，而不是再次退化成静默填 0。
    """
    import futures_quant.ai.features as fm

    orig = fm.add_indicators

    def _broken_add_indicators(df, *args, **kwargs):
        out = orig(df, *args, **kwargs)
        # 人为掐掉一个产出列（模拟 tech 侧回归）
        return out.drop(columns=["atr_pct"])

    monkeypatch.setattr(fm, "add_indicators", _broken_add_indicators)
    with pytest.raises(KeyError) as exc:
        build_features(_make_df(), extended=True, symbol="BROKEN", period="D")
    assert "atr_pct" in str(exc.value), f"错误信息应指出缺失列 atr_pct，实际：{exc.value}"


def test_dynamic_features_eventually_exist():
    """标记为 None（内部动态计算）的特征，最终必须真的出现在 ind 中。

    防止「免校验」退化成「无人负责」——声明为动态计算就必须被算出来。
    """
    df = _make_df()
    ind, _F, _names = build_features(df, extended=True, symbol="DYN", period="D")
    dynamic = [f for f, src in FEATURE_SOURCE.items() if src is None]
    missing = [f for f in dynamic if f not in ind.columns]
    assert not missing, f"声明为动态计算却未被产出：{missing}"
    assert dynamic, "FEATURE_SOURCE 中应存在动态计算特征（否则该断言无意义）"


def test_feature_source_covers_all_extended_features():
    """EXTENDED_FEATURES 中每个特征都必须在 FEATURE_SOURCE 中声明（无漏网之鱼）。"""
    undeclared = [f for f in EXTENDED_FEATURES if f not in FEATURE_SOURCE]
    assert not undeclared, f"以下特征未在 FEATURE_SOURCE 声明：{undeclared}"


def test_missing_source_column_fails_fast():
    """人为删除一个产出列 → _validate_feature_source 必须抛 KeyError（禁止静默填 0）。"""
    ind = add_indicators(_make_df())
    # 逐个删除每个「有来源」的特征列，确保删任何一个都会被拦截
    checked = 0
    for f, src in FEATURE_SOURCE.items():
        if src is None or src not in ind.columns:
            continue
        broken = ind.drop(columns=[src])
        with pytest.raises(KeyError):
            _validate_feature_source(broken, EXTENDED_FEATURES)
        checked += 1
    assert checked >= 8, f"至少应校验 8 个原恒零特征来源列，实际只测了 {checked} 个"


# ---------------------------------------------------------------------------
# ② EXTENDED_FEATURES 与 predictor 实际消费列一致
# ---------------------------------------------------------------------------
def test_extended_features_match_predictor_consumption():
    """predictor 经 build_features 消费 names；extended 时须等于 EXTENDED_FEATURES。"""
    df = _make_df()
    # extended=True：predictor 默认消费扩展特征集
    _ind, _F, names = build_features(df, extended=True, symbol="C_EXT", period="D")
    assert list(names) == list(EXTENDED_FEATURES), (
        f"build_features(extended=True) 返回的 names 与 EXTENDED_FEATURES 不一致。"
        f"差异：{set(names) ^ set(EXTENDED_FEATURES)}")

    # extended=False：须等于 BASE_FEATURES
    _ind2, _F2, names2 = build_features(df, extended=False, symbol="C_BASE", period="D")
    assert list(names2) == list(BASE_FEATURES), (
        f"build_features(extended=False) 返回的 names 与 BASE_FEATURES 不一致。"
        f"差异：{set(names2) ^ set(BASE_FEATURES)}")


def test_base_features_are_subset_of_extended():
    """基础特征集必须是扩展特征集的子集（列序契约）。"""
    missing = [f for f in BASE_FEATURES if f not in EXTENDED_FEATURES]
    assert not missing, f"BASE_FEATURES 中有特征不在 EXTENDED_FEATURES 内：{missing}"


def test_feature_matrix_columns_match_names():
    """build_features 返回的特征矩阵列，必须与 feature_names 完全一致。"""
    _ind, F, names = build_features(_make_df(), extended=True, symbol="C_COLS", period="D")
    assert list(F.columns) == list(names), "特征矩阵列名与 feature_names 不一致"


# ---------------------------------------------------------------------------
# ③ 无前视（Look-ahead）校验
# ---------------------------------------------------------------------------
def test_no_lookahead_on_truncated_data():
    """截断到 t 后，[0,t) 区间的特征值必须与全量计算完全一致（误差 <1e-12）。

    这条是防未来函数的核心契约：若某特征偷偷用了 t 之后的数据，
    截断后该位置的值就会与全量结果不同。
    """
    n, t = 300, 200
    df = _make_df(n)
    _ind_full, F_full, names = build_features(df, extended=True, symbol="LK_FULL", period="D")

    # 截断到前 t 行（用不同 symbol 确保不命中 LRU 缓存）
    df_trunc = df.iloc[:t].copy()
    _ind_t, F_trunc, _names_t = build_features(
        df_trunc, extended=True, symbol="LK_TRUNC", period="D")

    assert len(F_trunc) == t, f"截断后应有 {t} 行，实际 {len(F_trunc)}"

    # 逐列比对 [0, t) 区间
    mismatched = []
    for col in names:
        a = pd.to_numeric(F_full[col].iloc[:t], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(F_trunc[col], errors="coerce").to_numpy(dtype=float)
        # NaN 位置视作相等（前 min_periods 窗口不足时两边都为 NaN/0）
        both_nan = np.isnan(a) & np.isnan(b)
        diff = np.abs(a - b)
        diff = np.where(both_nan, 0.0, diff)
        diff = np.nan_to_num(diff, nan=np.inf)
        if not np.all(diff < 1e-12):
            bad_idx = int(np.argmax(diff))
            mismatched.append((col, float(diff[bad_idx]), bad_idx))
    assert not mismatched, (
        f"以下特征存在前视（截断后取值与全量不符）：{mismatched}")


def test_no_lookahead_at_multiple_cut_points():
    """在多个截断点上重复无前视校验，避免只在单一 t 上碰巧通过。"""
    n = 300
    df = _make_df(n)
    _ind_full, F_full, names = build_features(df, extended=True, symbol="LKM_FULL", period="D")

    for t in (150, 220, 260):
        df_t = df.iloc[:t].copy()
        _ind_t, F_t, _ = build_features(
            df_t, extended=True, symbol=f"LKM_{t}", period="D")
        for col in names:
            a = pd.to_numeric(F_full[col].iloc[:t], errors="coerce").to_numpy(dtype=float)
            b = pd.to_numeric(F_t[col], errors="coerce").to_numpy(dtype=float)
            both_nan = np.isnan(a) & np.isnan(b)
            diff = np.abs(a - b)
            diff = np.where(both_nan, 0.0, diff)
            diff = np.nan_to_num(diff, nan=np.inf)
            assert np.all(diff < 1e-12), (
                f"截断点 t={t} 处特征 {col} 存在前视（最大偏差 {np.max(diff)}）")
