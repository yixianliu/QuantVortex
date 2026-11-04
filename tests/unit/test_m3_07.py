"""M3-07 修复特征重要性与风险评分 —— pytest 形态。

由散落脚本 ``tests/test_m3_07.py``（模块级 ``PASS/FAIL`` 列表 + ``check(name,cond,detail)``
辅助 + 结尾 ``if FAIL: sys.exit(1)``，0 个 ``def test_*``）机械改写：
每段 ``check(...)`` 收敛成 ``assert cond, f"{name} — {detail}"``，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 保留脚本里捕获 ``futures_quant.ai.predictor`` 日志的 ``_Cap`` handler（两处
  "输出了 warning 日志" 断言依赖它），加/摘 handler 用 try/finally 保证回收。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from futures_quant.ai.predictor import FuturesPredictor
from futures_quant.ai.ensemble import _Ridge
from futures_quant.ai.lstm import LSTM

NAMES = ["f_alpha", "f_beta", "f_gamma"]


class _Cap(logging.Handler):
    """捕获 ``futures_quant.ai.predictor`` 日志到内存（与脚本 _Cap 一致）。"""

    def __init__(self, sink):
        super().__init__()  # 必须初始化基类（filters/level/lock）
        self._sink = sink

    def emit(self, record):  # noqa: D102
        self._sink.append(record.getMessage())


def _captured_warnings(target_pred, sink):
    """对 target 调 ``_feature_importance()`` 期间，捕获的 warning 消息列表。"""
    lg = logging.getLogger("futures_quant.ai.predictor")
    cap = _Cap(sink)
    lg.addHandler(cap)
    try:
        target_pred()
    finally:
        lg.removeHandler(cap)
    return sink


def test_ridge_feature_importance():
    """① 岭回归：注入已知权重，Top1 与预期一致，重要性已归一化。"""
    p = FuturesPredictor()
    p._feat_names = list(NAMES)
    p.seq_len = 2  # 窗口 2 × 特征 3 = 6 维权
    r = _Ridge(alpha=1.0)
    r.w = np.array([0.10, 9.00, 0.20,     # t-1
                    0.10, 8.00, 0.20])    # t
    p._ridge = r
    p.use_lstm = False
    p.lstm = None
    imp = p._feature_importance()
    assert len(imp) > 0, "返回非空"
    assert imp and imp[0]["name"] == "f_beta", f"Top1 = f_beta（与注入的最大权重一致） — {imp}"
    assert abs(sum(i["importance"] for i in imp) - 1.0) < 1e-3, \
        f"重要性之和约为 1（已归一化） — {sum(i['importance'] for i in imp):.4f}"
    assert imp and imp[0]["importance"] > 5 * max(i["importance"] for i in imp[1:]), \
        f"f_beta 占比远高于其他两个 — {[(i['name'], i['importance']) for i in imp]}"


def test_lstm_skips_hidden_block():
    """② LSTM：跳过隐状态分块，特征重要性 Top1 正确且放大隐状态不污染特征。"""
    p2 = FuturesPredictor()
    p2._feat_names = list(NAMES)
    lstm = LSTM(input_size=3, hidden_size=4, output_size=1, seed=1)
    hid = int(getattr(lstm, "hid", 4))
    B = np.full((hid, hid + 3), 1e-3)
    B[:, hid + 1] = 10.0  # 只让「f_beta」这一列很大
    lstm.Wi = B.copy(); lstm.Wf = B.copy(); lstm.Wc = B.copy(); lstm.Wo = B.copy()
    p2.lstm = lstm
    p2.use_lstm = True
    p2._ridge = None
    imp2 = p2._feature_importance()
    assert len(imp2) > 0, "返回非空"
    assert imp2 and imp2[0]["name"] == "f_beta", \
        f"Top1 = f_beta（旧实现会取到隐状态列 → 错误） — {imp2}"
    assert imp2 and imp2[0]["importance"] > 0.99, \
        f"f_beta 占比 > 0.99 — {[(i['name'], i['importance']) for i in imp2]}"

    # 反向验证：把最大权重放在隐状态分块，特征重要性不应把它算进来
    B2 = np.full((hid, hid + 3), 1e-3)
    B2[:, 0] = 99.0  # 只放大「隐状态 0」列
    lstm.Wi = B2.copy(); lstm.Wf = B2.copy(); lstm.Wc = B2.copy(); lstm.Wo = B2.copy()
    imp3 = p2._feature_importance()
    assert len(imp3) == 3 and abs(sum(i["importance"] for i in imp3) - 1.0) < 1e-3, \
        f"只放大隐状态列时，特征重要性不被污染（仍返回 3 个特征且可比） — {[(i['name'], round(i['importance'], 3)) for i in imp3]}"
    assert max(i["importance"] for i in imp3) - min(i["importance"] for i in imp3) < 0.02, \
        f"隐状态放大后三个特征近似均匀（证明未被计入） — {[round(i['importance'], 4) for i in imp3]}"


def test_dimension_mismatch_returns_empty_with_warning():
    """③ 维度不符 → 返回空且告警（不再补 1 / 截断）。"""
    p3 = FuturesPredictor()
    p3._feat_names = list(NAMES)
    p3.seq_len = 2
    r3 = _Ridge(alpha=1.0)
    r3.w = np.arange(17, dtype=float)  # 既不等于 n(3)，也不等于 seq_len*n(6)
    p3._ridge = r3
    p3.use_lstm = False
    p3.lstm = None
    assert p3._feature_importance() == [], f"岭回归维度不匹配 → 返回空 — {p3._feature_importance()}"

    records = []
    _captured_warnings(lambda: p3._feature_importance(), records)
    assert any("特征重要性" in m for m in records), \
        f"维度不符时输出了 warning 日志 — {records[:1]}"


def test_external_model_returns_empty():
    """④ 外部模型 → 明确返回空（不编造均匀分布）。"""
    from futures_quant.ai.calibration_replay import build_external_estimator

    p4 = FuturesPredictor()
    p4._feat_names = list(NAMES)
    p4.external_model = build_external_estimator("tcn", epochs=1)
    assert p4._feature_importance() == [], "外部模型 → 特征重要性返回空"


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


def test_risk_score_atr_present():
    """⑤ 有 ATR14 时风险分 > 0 且 atr_source == ATR14。"""
    p5 = FuturesPredictor()
    p5.levels = []
    r_with = p5._risk_score(_mk_ind(with_atr=True))
    assert r_with.get("atr_source") == "ATR14", f"有 ATR14 时 atr_source == ATR14 — {r_with}"
    assert r_with["score"] > 0, f"有 ATR14 时风险分 > 0 — score={r_with['score']}"


def test_risk_score_atr_missing_fallback():
    """⑤ ATR 缺失时风险分仍 > 0（兜底生效），并告警 + 兜底 atr_pct 量纲合理。"""
    p5 = FuturesPredictor()
    p5.levels = []
    records2 = []
    cap = _Cap(records2)
    lg = logging.getLogger("futures_quant.ai.predictor")
    lg.addHandler(cap)
    try:
        r_no = p5._risk_score(_mk_ind(with_atr=False))
    finally:
        lg.removeHandler(cap)
    assert r_no.get("atr_source") == "ret_std_fallback", \
        f"ATR 缺失时 atr_source == ret_std_fallback — {r_no}"
    assert r_no["score"] > 0, \
        f"ATR 缺失时风险分仍 > 0（兜底生效，不再恒为 0） — score={r_no['score']}, atr_pct={r_no['atr_pct']}"
    assert any("ATR 缺失" in m for m in records2), \
        f"ATR 缺失时输出了 warning 日志 — {records2[:1]}"
    assert 0.002 <= r_no["atr_pct"] / 100.0 <= 0.08, \
        f"兜底 atr_pct 与真实 ATR 量纲相当（0.2%~8%） — atr_pct={r_no['atr_pct']}%（真实≈1.4%）"


def test_risk_score_atr_all_zero_fallback():
    """⑥ ATR 列为 0 时也走兜底，风险分仍 > 0。"""
    p5 = FuturesPredictor()
    p5.levels = []
    ind_zero = _mk_ind(with_atr=True)
    ind_zero["ATR14"] = 0.0
    r_zero = p5._risk_score(ind_zero)
    assert r_zero.get("atr_source") == "ret_std_fallback", \
        f"ATR14 全 0 → 兜底生效 — {r_zero}"
    assert r_zero["score"] > 0, f"ATR14 全 0 → 风险分仍 > 0 — score={r_zero['score']}"
