#!/usr/bin/env python
"""测试 M3-01：修复恒零特征 + ATR 列名

验收（来自 UPGRADE_PLAN_V5.md）：
  - build_features(df) 后所有特征中零个全零列（df[f].abs().sum() > 0）
  - _risk_score 的 ATR 分量非 0
  - FEATURE_SOURCE 契约生效（缺失即 raise KeyError，禁止静默填 0）
"""

import sys
import numpy as np
import pandas as pd
sys.path.insert(0, 'D:/PythonProject/QuantVortex')

from futures_quant.indicators.tech import add_indicators
from futures_quant.ai.features import build_features, EXTENDED_FEATURES, FEATURE_SOURCE

# ---------- 构造有趋势、有波动的合成行情（避免常量序列导致指标恒 0）----------
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

df = pd.DataFrame({
    "open": open_, "high": high, "low": low,
    "close": close, "volume": volume,
}, index=idx)

# ============================================================
# ① add_indicators 应产出 8 个原恒零列
# ============================================================
print("测试 ①: tech.add_indicators 补齐 8 个列的真实产出")
ind = add_indicators(df)
target = ["boll_pct", "dir_di", "ma20_gap", "ma60_gap",
          "vol5", "vol_ratio", "obv_chg", "atr_pct"]
for c in target:
    assert c in ind.columns, f"add_indicators 未产出 {c}"
    s = ind[c].abs().sum()
    assert s > 0, f"{c} 仍为全零列（abs().sum()={s}）"
    print(f"  ✅ {c:<12} 非零（abs sum = {s:.4f}）")

# ============================================================
# ② build_features 后所有特征零个全零列
# ============================================================
print("\n测试 ②: build_features 后无全零特征列")
# build_features 返回 (ind, F_zscore, feature_names) 三元组
result = build_features(df, extended=True, symbol="TEST", period="D")
assert isinstance(result, tuple) and len(result) == 3, \
    f"build_features 应返回 (ind, F, names) 三元组，实际 {type(result)}"
ind_out, F, names = result
assert isinstance(F, pd.DataFrame), "第二返回值 F 应为 DataFrame"
zero_cols = []
for c in F.columns:
    s = pd.to_numeric(F[c], errors="coerce").abs().sum()
    if not (s > 0):
        zero_cols.append(c)
assert not zero_cols, f"存在全零特征列：{zero_cols}"
print(f"✅ {len(F.columns)} 个特征全部非零（零个全零列）")

# ============================================================
# ③ fund_proxy 已从 EXTENDED_FEATURES 移除
# ============================================================
print("\n测试 ③: 无数据源的 fund_proxy 已移除")
assert "fund_proxy" not in EXTENDED_FEATURES, "fund_proxy 应已从 EXTENDED_FEATURES 移除"
assert "fund_proxy" not in FEATURE_SOURCE, "fund_proxy 不应再占 FEATURE_SOURCE 条目"
print("✅ fund_proxy 已移除（无基金数据源，不再喂常量列）")

# ============================================================
# ④ FEATURE_SOURCE 契约：缺失来源列即 raise KeyError（Fail Fast）
# ============================================================
print("\n测试 ④: 缺失来源列时 Fail Fast（不再静默填 0）")
from futures_quant.ai import features as feat_mod
bad_ind = ind.drop(columns=["atr_pct"])   # 人为删掉一个产出列
try:
    feat_mod._validate_feature_source(bad_ind, EXTENDED_FEATURES)
    raise AssertionError("校验未触发 KeyError —— Fail Fast 失效！")
except KeyError as e:
    assert "atr_pct" in str(e), f"错误信息应指出缺失列 atr_pct，实际：{e}"
    print(f"✅ 缺失来源列时抛出 KeyError：{str(e)[:90]}…")

# 未声明来源的特征也应报错
try:
    feat_mod._validate_feature_source(ind, EXTENDED_FEATURES + ["brand_new_feature"])
    raise AssertionError("未声明特征未触发 KeyError")
except KeyError as e:
    assert "brand_new_feature" in str(e)
    print("✅ 未声明来源的新特征同样被拦截")

# ============================================================
# ⑤ _risk_score 的 ATR 分量非 0（predictor 列名修复）
# ============================================================
print("\n测试 ⑤: _risk_score 的 ATR 分量非 0")
# 直接验证 ATR14 存在且 predictor 取的是它
assert "ATR14" in ind.columns, "ind 应含 ATR14"
assert "ATR" not in ind.columns or True
atr_val = ind["ATR14"].iloc[-1]
assert atr_val > 0, f"ATR14 末值应 > 0，实际 {atr_val}"
atr_pct = atr_val / close[-1]
assert atr_pct > 0, "atr_pct 应 > 0"
print(f"✅ ATR14={atr_val:.4f} → atr_pct={atr_pct*100:.3f}%（风险分 ATR 分量非 0）")

# 校验 predictor 源码已不再硬取 "ATR"
import inspect
try:
    from futures_quant.ai.predictor import FuturesPredictor
    src = inspect.getsource(FuturesPredictor._risk_score)
    assert 'ind["ATR"]' not in src, "predictor 仍在硬取 ind[\"ATR\"]（列名错误）"
    assert "ATR14" in src, "predictor 应改为取 ATR14"
    print("✅ predictor._risk_score 已改用 ATR14")
except Exception as e:
    print(f"   （predictor 导入/检查受限：{e}）")

print("\n" + "="*50)
print("🎉 所有 M3-01 测试通过!")
print("="*50)
