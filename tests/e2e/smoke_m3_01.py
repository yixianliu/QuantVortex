"""M3-01 恒零特征 + ATR 列名 - E2E smoke 验收。

DoD:
1) build_features(df) 后 34 个 EXTENDED_FEATURES 中**零个全零列**
   （断言 `df[f].abs().sum() > 0`）。
2) `_risk_score` 的 ATR 分量非 0（`atr_pct` 应来自 `ATR14` 而非恒 0）。
3) tech.add_indicators 产出全部 8 个 M3-01 补齐列。
4) FEATURE_SOURCE 契约 Fail-Fast：故意缺失一列 → KeyError。
5) EXTENDED_FEATURES 与 FEATURE_SOURCE 键集完全一致（防漂移）。

运行方式:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_01.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QT_QPA_PLATFORM_DEFAULT = os.environ.get("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_QPA_PLATFORM"] = QT_QPA_PLATFORM_DEFAULT


# ============================================================
# 合成一份"真" OHLCV 数据：随机游走的收盘价 + 合理的开高低收量
# ============================================================
def _make_sample(n: int = 500, seed: int = 20260930) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(loc=0.0002, scale=0.012, size=n)
    close = 100.0 * np.exp(np.cumsum(ret))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(close, open_) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(close, open_) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.integers(1_000_000, 20_000_000, size=n).astype(float)
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ============================================================
# 测试用例
# ============================================================

def test_1_add_indicators_produces_all_m3_01_columns() -> None:
    """tech.add_indicators 应产出 M3-01 补齐的 8 个特征列。"""
    from futures_quant.indicators import tech

    df = _make_sample(300)
    out = tech.add_indicators(df)

    required = {"boll_pct", "dir_di", "ma20_gap", "ma60_gap",
                "vol5", "vol_ratio", "obv_chg", "atr_pct"}
    missing = required - set(out.columns)
    assert not missing, f"add_indicators 未产出 M3-01 特征列: {sorted(missing)}"
    # ATR14 也是必需的（供 _risk_score 使用）
    assert "ATR14" in out.columns, "add_indicators 未产出 ATR14 列"
    print("[1/5] PASS add_indicators produces all 8 M3-01 features + ATR14")


def test_2_build_features_no_zero_columns() -> None:
    """DoD #1：build_features 后 34 个 EXTENDED_FEATURES 中零个全零列。"""
    from futures_quant.ai.features import build_features, EXTENDED_FEATURES

    df = _make_sample(500)
    ind, F, feature_names = build_features(
        df, extended=True, symbol="TEST", period="1d"
    )

    # 定位 EXTENDED_FEATURES 在 F 中的列
    found = []
    for f in EXTENDED_FEATURES:
        if f in F.columns:
            found.append(f)

    zero_cols = []
    for f in found:
        col = F[f]
        # 排除 NaN 后，检查绝对值之和
        s = col.replace([np.inf, -np.inf], np.nan).dropna().abs().sum()
        if s == 0:
            zero_cols.append(f)

    assert not zero_cols, (
        f"以下特征列全为 0（M3-01 DoD 违反）：{zero_cols}"
    )
    print(f"[2/5] PASS build_features: {len(found)}/{len(EXTENDED_FEATURES)} 特征列全部非零")


def test_3_predictor_risk_score_atr_nonzero() -> None:
    """DoD #2：_risk_score 的 atr_pct 应非零（来自 ATR14 而非静默 0）。"""
    from futures_quant.ai.predictor import FuturesPredictor
    from futures_quant.indicators import tech

    df = _make_sample(500)
    ind = tech.add_indicators(df)

    pred = FuturesPredictor()
    result = pred._risk_score(ind)

    assert isinstance(result, dict)
    atr_pct_val = result.get("atr_pct", 0.0)
    assert atr_pct_val > 0, f"_risk_score.atr_pct 为 0（M3-01 DoD 违反）：{result}"
    atr_source = result.get("atr_source", "")
    assert atr_source == "ATR14", (
        f"atr_source 应来自 ATR14 列而非 fallback，实际为 {atr_source!r}"
    )
    print(f"[3/5] PASS _risk_score.atr_pct = {atr_pct_val} (来源: {atr_source})")


def test_4_feature_source_fail_fast() -> None:
    """FEATURE_SOURCE 契约：故意让一列缺失，应抛 KeyError 而非静默填 0。"""
    from futures_quant.ai.features import _validate_feature_source, EXTENDED_FEATURES

    df = _make_sample(200)
    # 只保留部分列 —— 制造缺失场景
    minimal_ind = df.copy()
    try:
        _validate_feature_source(minimal_ind, EXTENDED_FEATURES)
    except KeyError as e:
        # 期望抛出：至少包含 "特征来源列缺失" 或 "未在 FEATURE_SOURCE 中声明"
        assert "FEATURE_SOURCE" in str(e) or "特征来源列缺失" in str(e) or "declared" in str(e), (
            f"错误消息未提契约：{e}"
        )
    else:
        raise AssertionError(
            "缺失关键列时未抛 KeyError —— 违反了 Fail-Fast 契约"
        )
    print("[4/5] PASS FEATURE_SOURCE raises KeyError on missing source column")


def test_5_extended_features_matches_feature_source_keys() -> None:
    """EXTENDED_FEATURES 与 FEATURE_SOURCE 键集应完全一致（防漂移）。"""
    from futures_quant.ai.features import EXTENDED_FEATURES, FEATURE_SOURCE

    ext_set = set(EXTENDED_FEATURES)
    src_set = set(FEATURE_SOURCE.keys())

    missing_in_src = ext_set - src_set
    extra_in_src = src_set - ext_set
    assert not missing_in_src, (
        f"EXTENDED_FEATURES 中以下特征未在 FEATURE_SOURCE 声明：{sorted(missing_in_src)}"
    )
    assert not extra_in_src, (
        f"FEATURE_SOURCE 声明了 EXTENDED_FEATURES 未包含的特征：{sorted(extra_in_src)}"
    )
    print(f"[5/5] PASS EXTENDED_FEATURES ↔ FEATURE_SOURCE 键集一致 ({len(ext_set)} 项)")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)

    tests = [
        test_1_add_indicators_produces_all_m3_01_columns,
        test_2_build_features_no_zero_columns,
        test_3_predictor_risk_score_atr_nonzero,
        test_4_feature_source_fail_fast,
        test_5_extended_features_matches_feature_source_keys,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc!r}")

    total = len(tests)
    passed = total - failed
    print(f"\n=== M3-01 smoke: {passed}/{total} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
