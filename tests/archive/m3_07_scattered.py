"""M3-07 验证：修复特征重要性与风险评分。

验收点（对应 UPGRADE_PLAN_V5 M3-07）：
  ① 特征重要性只取输入特征分块（跳过隐状态），岭回归按时间步平均；
  ② 维度不符时 logger.warning 并返回空，不再返回无意义值；
  ③ 注入已知权重 → Top1 特征与预期一致；
  ④ ATR 缺失时风险分仍 > 0（兜底）。
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


from futures_quant.ai.predictor import FuturesPredictor  # noqa: E402
from futures_quant.ai.ensemble import _Ridge  # noqa: E402
from futures_quant.ai.lstm import LSTM  # noqa: E402

NAMES = ["f_alpha", "f_beta", "f_gamma"]

print("\n测试 ①: 岭回归 —— 注入已知权重，Top1 与预期一致")
p = FuturesPredictor()
p._feat_names = list(NAMES)
p.seq_len = 2                      # 窗口 2 × 特征 3 = 6 维权
r = _Ridge(alpha=1.0)
r.w = np.array([0.10, 9.00, 0.20,     # t-1
                0.10, 8.00, 0.20])    # t
p._ridge = r
p.use_lstm = False
p.lstm = None
imp = p._feature_importance()
check("返回非空", len(imp) > 0)
check("Top1 = f_beta（与注入的最大权重一致）",
      imp and imp[0]["name"] == "f_beta", str(imp))
check("重要性之和约为 1（已归一化）",
      abs(sum(i["importance"] for i in imp) - 1.0) < 1e-3,
      f"{sum(i['importance'] for i in imp):.4f}")
check("f_beta 占比远高于其他两个",
      imp and imp[0]["importance"] > 5 * max(i["importance"] for i in imp[1:]),
      str([(i["name"], i["importance"]) for i in imp]))

print("\n测试 ②: LSTM —— 跳过隐状态分块，Top1 与预期一致")
p2 = FuturesPredictor()
p2._feat_names = list(NAMES)
lstm = LSTM(input_size=3, hidden_size=4, output_size=1, seed=1)
hid = int(getattr(lstm, "hid", 4))
# 门控权重形状 (hidden, hidden+input)：列 [隐状态 0..3 | 特征 0..2]
B = np.full((hid, hid + 3), 1e-3)
B[:, hid + 1] = 10.0               # 只让「f_beta」这一列很大
lstm.Wi = B.copy(); lstm.Wf = B.copy(); lstm.Wc = B.copy(); lstm.Wo = B.copy()
p2.lstm = lstm
p2.use_lstm = True
p2._ridge = None
imp2 = p2._feature_importance()
check("返回非空", len(imp2) > 0)
check("Top1 = f_beta（旧实现会取到隐状态列 → 错误）",
      imp2 and imp2[0]["name"] == "f_beta", str(imp2))
check("f_beta 占比 > 0.99",
      imp2 and imp2[0]["importance"] > 0.99, str([(i["name"], i["importance"]) for i in imp2]))

# 反向验证：把最大权重放在隐状态分块，特征重要性**不应**把它算进来
B2 = np.full((hid, hid + 3), 1e-3)
B2[:, 0] = 99.0                    # 只放大「隐状态 0」列
lstm.Wi = B2.copy(); lstm.Wf = B2.copy(); lstm.Wc = B2.copy(); lstm.Wo = B2.copy()
imp3 = p2._feature_importance()
check("只放大隐状态列时，特征重要性不被污染（仍返回 3 个特征且可比）",
      len(imp3) == 3 and abs(sum(i["importance"] for i in imp3) - 1.0) < 1e-3,
      str([(i["name"], round(i["importance"], 3)) for i in imp3]))
check("隐状态放大后三个特征近似均匀（证明未被计入）",
      max(i["importance"] for i in imp3) - min(i["importance"] for i in imp3) < 0.02,
      str([round(i["importance"], 4) for i in imp3]))

print("\n测试 ③: 维度不符 → 返回空且告警（不再补 1 / 截断）")
p3 = FuturesPredictor()
p3._feat_names = list(NAMES)
p3.seq_len = 2
r3 = _Ridge(alpha=1.0)
r3.w = np.arange(17, dtype=float)      # 既不等于 n(3)，也不等于 seq_len*n(6)
p3._ridge = r3
p3.use_lstm = False
p3.lstm = None
check("岭回归维度不匹配 → 返回空", p3._feature_importance() == [],
      str(p3._feature_importance()))

import logging  # noqa: E402

records = []


class _Cap(logging.Handler):
    def __init__(self, sink):
        super().__init__()          # 必须初始化基类（filters/level/lock）
        self._sink = sink

    def emit(self, record):  # noqa: D102
        self._sink.append(record.getMessage())


lg = logging.getLogger("futures_quant.ai.predictor")
cap = _Cap(records)
lg.addHandler(cap)
try:
    p3._feature_importance()
finally:
    lg.removeHandler(cap)
check("维度不符时输出了 warning 日志", any("特征重要性" in m for m in records),
      str(records[:1]))

print("\n测试 ④: 外部模型 → 明确返回空（不编造均匀分布）")
from futures_quant.ai.calibration_replay import build_external_estimator  # noqa: E402

p4 = FuturesPredictor()
p4._feat_names = list(NAMES)
p4.external_model = build_external_estimator("tcn", epochs=1)
check("外部模型 → 特征重要性返回空", p4._feature_importance() == [])

print("\n测试 ⑤: ATR 缺失时风险分仍 > 0（兜底生效）")


def _mk_ind(n=120, with_atr=True, seed=5):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 0.012, n)
    close = 3500.0 * np.exp(np.cumsum(ret))
    ind = pd.DataFrame({
        "open": np.concatenate([[close[0]], close[:-1]]),
        "high": close * (1 + np.abs(rng.normal(0, 0.006, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.006, n))),
        "close": close,
        "volume": rng.integers(1000, 9000, n).astype(float),
        "ADX": rng.uniform(10, 40, n),
    })
    ind["ret"] = ind["close"].pct_change()
    if with_atr:
        ind["ATR14"] = close * 0.014
    return ind


p5 = FuturesPredictor()
p5.levels = []
r_with = p5._risk_score(_mk_ind(with_atr=True))
check("有 ATR14 时 atr_source == ATR14", r_with.get("atr_source") == "ATR14",
      str(r_with))
check("有 ATR14 时风险分 > 0", r_with["score"] > 0, f"score={r_with['score']}")

records2 = []
cap2 = _Cap(records2)
lg.addHandler(cap2)
try:
    r_no = p5._risk_score(_mk_ind(with_atr=False))
finally:
    lg.removeHandler(cap2)
check("ATR 缺失时 atr_source == ret_std_fallback",
      r_no.get("atr_source") == "ret_std_fallback", str(r_no))
check("ATR 缺失时风险分仍 > 0（兜底生效，不再恒为 0）", r_no["score"] > 0,
      f"score={r_no['score']}, atr_pct={r_no['atr_pct']}")
check("ATR 缺失时输出了 warning 日志", any("ATR 缺失" in m for m in records2),
      str(records2[:1]))
check("兜底 atr_pct 与真实 ATR 量纲相当（0.2%~8%）",
      0.002 <= r_no["atr_pct"] / 100.0 <= 0.08,
      f"atr_pct={r_no['atr_pct']}%（真实≈1.4%）")

print("\n测试 ⑥: ATR 列为 0 时也走兜底")
ind_zero = _mk_ind(with_atr=True)
ind_zero["ATR14"] = 0.0
r_zero = p5._risk_score(ind_zero)
check("ATR14 全 0 → 兜底生效", r_zero.get("atr_source") == "ret_std_fallback", str(r_zero))
check("ATR14 全 0 → 风险分仍 > 0", r_zero["score"] > 0, f"score={r_zero['score']}")

print(f"\n{'=' * 60}")
print(f"M3-07 验证结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("test_m3_07.py 全绿")
