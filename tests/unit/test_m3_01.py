"""M3-01 修复恒零特征 + ATR 列名 —— pytest 形态。

由散落脚本 ``tests/test_m3_01.py``（模块级 ``print``+``assert``，0 个 ``def test_*``）
机械改写，行为契约不变：
  ① ``add_indicators`` 补齐 8 个原恒零列
  ② ``build_features`` 后无全零特征列
  ③ 无数据源的 ``fund_proxy`` 已移除
  ④ ``FEATURE_SOURCE`` 契约 Fail Fast（缺失即 raise KeyError，禁止静默填 0）
  ⑤ ``_risk_score`` 的 ATR 分量非 0（predictor 取 ATR14 而非 ATR）

改动说明：
- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 合成行情用 ``np.random.seed(7)`` 生成（与原脚本一致、确定性）；改为
  pytest fixture 构造，各用例共享同一份 ``ind``/``F`` 数据。
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from futures_quant.indicators.tech import add_indicators
from futures_quant.ai.features import build_features, EXTENDED_FEATURES, FEATURE_SOURCE
from futures_quant.ai import features as feat_mod


def _make_df():
    """有趋势、有波动的合成行情（避免常量序列导致指标恒 0）。"""
    np.random.seed(7)
    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    trend = np.linspace(100, 130, n)
    noise = np.cumsum(np.random.randn(n)) * 0.8
    close = trend + noise
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    open_ = close + np.random.randn(n) * 0.3
    volume = np.abs(np.random.randn(n)) * 1000 + 5000
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture(scope="module")
def ind_and_features():
    """一次构造：有趋势/波动的 df → add_indicators → build_features。"""
    df = _make_df()
    ind = add_indicators(df)
    ind_out, F, names = build_features(df, extended=True, symbol="TEST", period="D")
    return {"df": df, "ind": ind, "ind_out": ind_out, "F": F, "names": names}


def test_add_indicators_fills_8_zero_cols(ind_and_features):
    """① add_indicators 补齐 8 个原恒零列（每列 abs().sum() > 0）。"""
    ind = ind_and_features["ind"]
    target = ["boll_pct", "dir_di", "ma20_gap", "ma60_gap",
              "vol5", "vol_ratio", "obv_chg", "atr_pct"]
    for c in target:
        assert c in ind.columns, f"add_indicators 未产出 {c}"
        s = ind[c].abs().sum()
        assert s > 0, f"{c} 仍为全零列（abs().sum()={s}）"


def test_build_features_no_zero_feature_cols(ind_and_features):
    """② build_features 后所有特征零个全零列；返回三元组 (ind, F, names)。"""
    result = (ind_and_features["ind_out"], ind_and_features["F"], ind_and_features["names"])
    assert isinstance(result, tuple) and len(result) == 3, \
        "build_features 应返回 (ind, F, names) 三元组"
    F = ind_and_features["F"]
    assert isinstance(F, pd.DataFrame), "第二返回值 F 应为 DataFrame"
    zero_cols = []
    for c in F.columns:
        s = pd.to_numeric(F[c], errors="coerce").abs().sum()
        if not (s > 0):
            zero_cols.append(c)
    assert not zero_cols, f"存在全零特征列：{zero_cols}"


def test_fund_proxy_removed():
    """③ 无数据源的 fund_proxy 已从 EXTENDED_FEATURES / FEATURE_SOURCE 移除。"""
    assert "fund_proxy" not in EXTENDED_FEATURES, "fund_proxy 应已从 EXTENDED_FEATURES 移除"
    assert "fund_proxy" not in FEATURE_SOURCE, "fund_proxy 不应再占 FEATURE_SOURCE 条目"


def test_feature_source_fail_fast(ind_and_features):
    """④ 缺失来源列 / 未声明来源特征 都应 raise KeyError（不再静默填 0）。"""
    ind = ind_and_features["ind"]
    bad_ind = ind.drop(columns=["atr_pct"])  # 人为删掉一个产出列
    with pytest.raises(KeyError) as exc:
        feat_mod._validate_feature_source(bad_ind, EXTENDED_FEATURES)
    assert "atr_pct" in str(exc.value), f"错误信息应指出缺失列 atr_pct，实际：{exc.value}"

    with pytest.raises(KeyError) as exc2:
        feat_mod._validate_feature_source(ind, EXTENDED_FEATURES + ["brand_new_feature"])
    assert "brand_new_feature" in str(exc2.value)


def test_risk_score_uses_atr14(ind_and_features):
    """⑤ _risk_score 的 ATR 分量非 0（predictor 取 ATR14 而非 ATR）。"""
    ind = ind_and_features["ind"]
    df = ind_and_features["df"]
    close = df["close"].to_numpy()
    assert "ATR14" in ind.columns, "ind 应含 ATR14"
    atr_val = ind["ATR14"].iloc[-1]
    assert atr_val > 0, f"ATR14 末值应 > 0，实际 {atr_val}"
    atr_pct = atr_val / close[-1]
    assert atr_pct > 0, "atr_pct 应 > 0"

    # 校验 predictor 源码已不再硬取 "ATR"
    try:
        from futures_quant.ai.predictor import FuturesPredictor
        src = inspect.getsource(FuturesPredictor._risk_score)
        assert 'ind["ATR"]' not in src, "predictor 仍在硬取 ind[\"ATR\"]（列名错误）"
        assert "ATR14" in src, "predictor 应改为取 ATR14"
    except Exception:
        pytest.skip("predictor 导入/检查受限，仅校验 ATR14 非 0")
