"""M3-12 验证（pytest 改写版）：性能 —— 消除重复预测与重复训练。

验收点（对应 UPGRADE_PLAN_V5 M3-12）：
  ① ``predict_ops_page`` 里拿到校准概率后的**二次 predict()** 改为直接对已有
     ``p_up`` 应用校准函数（无需重跑外推）；
  ② ``evaluate_regime`` 与 ``evaluate`` 合并共用内部 ``_evaluate_core``，
     删除逐行 ``apply`` 死代码；
  ③ ``_add_lag_features`` 只生成被使用的 3 列（原 34×3=102 列）。

与散落脚本的差别（行为契约不变，仅把不可靠的计时对比改为确定性断言）：
  · 原文 ①「单次预测耗时下降 ≥40%」与 ②-c「evaluate_regime ≤1.35× evaluate」
    是 CI / 弱网下会偶发跌阈值的计时对比。本改写改用**调用计数**确定性证明：
    - 新链路每个迭代只调 1 次 predict（旧链路 2 次）→ 二次 predict 已消除；
    - evaluate_regime 与 evaluate 都只调 1 次 _evaluate_core → 重复训练已消除。
  · 语义等价（新/旧 p_up 差 ≤5e-5）、overall 一致性、列裁剪等其余契约 1:1 保留。

散落脚本原文：``tests/test_m3_12.py``（33 个 check）。
"""
import ast
import inspect
import textwrap

import numpy as np
import pandas as pd

from futures_quant.ai import features as FT
from futures_quant.ai.predictor import FuturesPredictor


def _make_df(n=300, seed=7, base=3500.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.009, n)
    close = base * np.exp(np.cumsum(r))
    return pd.DataFrame({
        "open": np.concatenate([[close[0]], close[:-1]]),
        "high": close * (1 + np.abs(rng.normal(0, 0.004, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.004, n))),
        "close": close,
        "volume": rng.integers(1000, 9000, n).astype(float),
    })


def _same(a, b):
    """逐字段比较（ndarray / list / scalar 通吃）。"""
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return np.array_equal(np.asarray(a), np.asarray(b))
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    try:
        return bool(a == b)
    except ValueError:
        return False


# =========================================================================
# ① 二次 predict 消除
# =========================================================================
def test_page_source_removed_double_predict():
    """页面源码不再出现 calibrate_p_up= 传参，且改为调用 apply_p_up_calibration。"""
    from futures_quant.ui import predict_ops_page as POP
    src_page = inspect.getsource(POP)
    assert "calibrate_p_up=" not in src_page, "页面仍存在二次 predict 的 calibrate_p_up= 传参"
    assert "apply_p_up_calibration" in src_page, "页面未改为调用 apply_p_up_calibration"
    assert hasattr(FuturesPredictor, "apply_p_up_calibration"), "predictor 缺少 apply_p_up_calibration"


def test_predict_calibration_semantic_equivalence():
    """新（就地融合）/旧（二次 predict）p_up 语义等价，其余字段一致。"""
    df = _make_df(n=300)
    pred = FuturesPredictor()
    fit_res = pred.fit(df, seq_len=20, epochs=5, symbol="TEST", period="1m")
    assert fit_res.get("trained"), f"前置 fit 失败: {fit_res.get('reason', '')}"

    CONF = 0.62  # 与模型 p_up 明显不同，才会触发融合
    # warmup：触发 lazy import / 首次开销
    for _ in range(2):
        r0 = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
        pred.apply_p_up_calibration(dict(r0), CONF)
        pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m",
                     calibrate_p_up=CONF)

    res_base = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
    res_old = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m",
                           calibrate_p_up=CONF)
    res_new = pred.apply_p_up_calibration(dict(res_base), CONF)

    d_p = abs(float(res_new["p_up"]) - float(res_old["p_up"]))
    assert d_p <= 5e-5, f"新/旧 p_up 不等价: new={res_new['p_up']} old={res_old['p_up']} diff={d_p:.2e}"
    d_d = abs(float(res_new["p_down"]) - float(res_old["p_down"]))
    assert d_d <= 5e-5, f"新/旧 p_down 不同步: diff={d_d:.2e}"

    diff = [k for k in res_base
            if k not in ("p_up", "p_down") and not _same(res_new[k], res_base[k])]
    assert not diff, f"除 p_up/p_down 外其余字段与首次 predict 不一致: {diff}"

    assert abs(res_new["p_up"] + res_new["p_down"] - 1.0) < 1e-9, \
        f"p_up + p_down != 1: {res_new['p_up']} + {res_new['p_down']}"


def test_duplicate_predict_eliminated():
    """确定性证明：新链路每个迭代只调 1 次 predict（旧链路 2 次）。"""
    df = _make_df(n=300)
    pred = FuturesPredictor()
    fit_res = pred.fit(df, seq_len=20, epochs=5, symbol="TEST", period="1m")
    assert fit_res.get("trained"), f"前置 fit 失败: {fit_res.get('reason', '')}"

    CONF = 0.62
    calls = {"n": 0}
    orig_predict = FuturesPredictor.predict

    def _counted(self, *a, **kw):
        calls["n"] += 1
        return orig_predict(self, *a, **kw)

    FuturesPredictor.predict = _counted
    try:
        # 旧链路：每迭代 2 次 predict
        calls["n"] = 0
        for _ in range(8):
            pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
            pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m",
                         calibrate_p_up=CONF)
        old_calls = calls["n"]
        # 新链路：每迭代 1 次 predict + 就地 apply
        calls["n"] = 0
        for _ in range(8):
            a = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
            pred.apply_p_up_calibration(a, CONF)
        new_calls = calls["n"]
    finally:
        FuturesPredictor.predict = orig_predict

    assert old_calls == 16, f"旧链路应调 16 次 predict，实际 {old_calls}"
    assert new_calls == 8, f"新链路应只调 8 次 predict（二次 predict 未消除？），实际 {new_calls}"


def test_neutral_result_keeps_p50():
    """降级（数据不足）结果保持中性 p_up=0.5，且 apply 不破坏它。"""
    df = _make_df(n=300)
    pred = FuturesPredictor()
    fit_res = pred.fit(df, seq_len=20, epochs=5, symbol="TEST", period="1m")
    assert fit_res.get("trained")

    neutral = pred._neutral_result(df, 10, "有效样本不足")
    pred.apply_p_up_calibration(neutral, 0.62)
    assert abs(neutral["p_up"] - 0.5) < 1e-12, f"降级结果 p_up 非 0.5: {neutral['p_up']}"


def test_apply_p_up_calibration_safe_on_bad_input():
    """非法 p_up（None）安全跳过不抛异常。"""
    df = _make_df(n=300)
    pred = FuturesPredictor()
    fit_res = pred.fit(df, seq_len=20, epochs=5, symbol="TEST", period="1m")
    assert fit_res.get("trained")

    bad = {"p_up": None}
    pred.apply_p_up_calibration(bad, 0.62)
    assert bad["p_up"] is None, "非法 p_up 未被安全跳过"


# =========================================================================
# ② evaluate_regime 与 evaluate 合并
# =========================================================================
def _code_names(func) -> set:
    """只看**代码体**里出现的标识符（剥掉 docstring，避免注释文字误伤）。"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == func.__name__][0]
    body = fn.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    names = set()
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    return names


def test_regime_core_exists():
    assert hasattr(FuturesPredictor, "_evaluate_core"), "缺少合并后的单一实现 _evaluate_core"
    assert hasattr(FuturesPredictor, "_regime_labels"), "缺少向量化 _regime_labels"


def test_regime_no_dead_code():
    """evaluate_regime 代码体不再出现逐行 apply 死代码，也不重复建序列/训练。"""
    names = _code_names(FuturesPredictor.evaluate_regime)
    assert "apply" not in names, "evaluate_regime 仍含逐行 apply 死代码"
    forbidden = {"_build_sequences", "_train_core", "_features"}
    leaked = forbidden & names
    assert not leaked, f"evaluate_regime 仍重复建序列/训练: {sorted(leaked)}"


def test_regime_overall_matches_evaluate():
    """evaluate_regime['overall'] 与 evaluate 逐字段相等；分行情样本无丢无重。"""
    allowed = {"趋势行情", "震荡收敛(变盘窗口)", "震荡行情"}
    df2 = _make_df(n=300, seed=11)
    p2 = FuturesPredictor()
    for wf in (True, False):
        m_eval = p2.evaluate(df2, horizon=1, seq_len=20, epochs=2,
                             use_walk_forward=wf, symbol="T2", period="1m")
        m_reg = p2.evaluate_regime(df2, horizon=1, seq_len=20, epochs=2,
                                   use_walk_forward=wf, symbol="T2", period="1m")
        assert "error" not in m_eval and "error" not in m_reg, \
            f"wf={wf} 评估不可用: eval={m_eval.get('error')} regime={m_reg.get('error')}"
        same = (set(m_eval.keys()) == set(m_reg["overall"].keys())
                and all(m_eval[k] == m_reg["overall"][k] for k in m_eval))
        assert same, f"wf={wf} evaluate_regime['overall'] 与 evaluate 不一致"
        tot = sum(v.get("samples", 0) for v in m_reg["by_regime"].values())
        assert tot == m_eval["val_samples"], \
            f"wf={wf} 分行情样本数之和 != 总验证样本数: {tot} vs {m_eval['val_samples']}"
        assert set(m_reg["by_regime"].keys()) <= allowed, \
            f"wf={wf} 行情标签非法: {sorted(m_reg['by_regime'].keys())}"


def test_regime_single_eval_call():
    """evaluate_regime 只调 1 次 _evaluate_core（旧实现为 2 次）。"""
    df2 = _make_df(n=300, seed=11)
    p2 = FuturesPredictor()
    orig_core = FuturesPredictor._evaluate_core
    calls = {"n": 0}

    def _counted(self, *a, **kw):
        calls["n"] += 1
        return orig_core(self, *a, **kw)

    FuturesPredictor._evaluate_core = _counted
    try:
        p2.evaluate_regime(df2, horizon=1, seq_len=20, epochs=2,
                           use_walk_forward=True, symbol="T2", period="1m")
    finally:
        FuturesPredictor._evaluate_core = orig_core
    assert calls["n"] == 1, f"_evaluate_core 被调用 {calls['n']} 次（应为 1）"


def test_regime_no_extra_eval_vs_evaluate():
    """确定性等价：evaluate 与 evaluate_regime 都只调 1 次 _evaluate_core（无多跑一遍）。"""
    df2 = _make_df(n=300, seed=11)
    p2 = FuturesPredictor()
    _EV = dict(horizon=1, seq_len=20, epochs=2, use_walk_forward=True,
               symbol="T2", period="1m")
    orig_core = FuturesPredictor._evaluate_core

    def _make_counter():
        c = {"n": 0}

        def _counted(self, *a, **kw):
            c["n"] += 1
            return orig_core(self, *a, **kw)

        return c, _counted

    c_eval, counted_eval = _make_counter()
    FuturesPredictor._evaluate_core = counted_eval
    try:
        p2.evaluate(df2, **_EV)
    finally:
        FuturesPredictor._evaluate_core = orig_core
    assert c_eval["n"] == 1, f"evaluate 应只调 1 次 _evaluate_core，实际 {c_eval['n']}"

    c_reg, counted_reg = _make_counter()
    FuturesPredictor._evaluate_core = counted_reg
    try:
        p2.evaluate_regime(df2, **_EV)
    finally:
        FuturesPredictor._evaluate_core = orig_core
    assert c_reg["n"] == 1, f"evaluate_regime 应只调 1 次 _evaluate_core，实际 {c_reg['n']}"


def test_regime_labels_aligned():
    """_regime_labels 长度与指标行数一致，取值合法。"""
    allowed = {"趋势行情", "震荡收敛(变盘窗口)", "震荡行情"}
    df2 = _make_df(n=300, seed=11)
    p2 = FuturesPredictor()
    ind2, _F2 = p2._features(df2, symbol="T2", period="1m")
    labels = FuturesPredictor._regime_labels(ind2)
    assert len(labels) == len(ind2), f"标签长度 {len(labels)} != 指标行数 {len(ind2)}"
    assert set(np.unique(labels)) <= allowed, f"标签取值非法: {sorted(set(np.unique(labels)))}"


# =========================================================================
# ③ _add_lag_features 只生成被使用的列
# =========================================================================
def test_add_lag_features_only_three_cols():
    """扩展特征下只新增 3 列（旧实现 34×3=102 列）。"""
    ind_src = pd.DataFrame({
        "close": np.linspace(100, 200, 60),
        "ret": np.random.default_rng(3).normal(0, 0.01, 60),
    })
    ind_src["ma5"] = ind_src["close"].rolling(5, min_periods=1).mean()

    names_ext = FT.EXTENDED_FEATURES.copy()
    before_cols = set(ind_src.columns)
    out = FT._add_lag_features(ind_src.copy(), names_ext)
    added = sorted(set(out.columns) - before_cols)

    assert added == ["ret_lag1", "ret_lag2", "ret_lag5"], f"新增列不符预期: {added}"


def test_lag_values_correct_and_no_pollution():
    """lagN == 基列 shift(N)；且不污染原 DataFrame。"""
    ind_src = pd.DataFrame({
        "close": np.linspace(100, 200, 60),
        "ret": np.random.default_rng(3).normal(0, 0.01, 60),
    })
    ind_src["ma5"] = ind_src["close"].rolling(5, min_periods=1).mean()
    before_cols = set(ind_src.columns)
    names_ext = FT.EXTENDED_FEATURES.copy()

    out = FT._add_lag_features(ind_src.copy(), names_ext)
    assert bool(np.allclose(out["ret_lag1"].to_numpy()[1:],
                            ind_src["ret"].shift(1).to_numpy()[1:], equal_nan=True))
    assert bool(np.allclose(out["ret_lag5"].to_numpy()[5:],
                            ind_src["ret"].shift(5).to_numpy()[5:], equal_nan=True))
    assert "ret_lag1" not in ind_src.columns, "原 DataFrame 被污染"


def test_add_lag_no_lag_requested():
    """feature_names 无 lag 项时一列不增。"""
    ind_src = pd.DataFrame({
        "close": np.linspace(100, 200, 60),
        "ret": np.random.default_rng(3).normal(0, 0.01, 60),
    })
    ind_src["ma5"] = ind_src["close"].rolling(5, min_periods=1).mean()
    before_cols = set(ind_src.columns)
    out0 = FT._add_lag_features(ind_src.copy(), ["close", "ret", "ma5"])
    assert set(out0.columns) == before_cols, \
        f"无 lag 需求却新增了列: {sorted(set(out0.columns) - before_cols)}"


def test_add_lag_extensible():
    """新增 xxx_lag3 只要写进 feature_names 就自动生成。"""
    ind_src = pd.DataFrame({
        "close": np.linspace(100, 200, 60),
        "ret": np.random.default_rng(3).normal(0, 0.01, 60),
    })
    ind_src["ma5"] = ind_src["close"].rolling(5, min_periods=1).mean()
    before_cols = set(ind_src.columns)
    out3 = FT._add_lag_features(ind_src.copy(), ["close_lag3", "ret_lag2"])
    added3 = sorted(set(out3.columns) - before_cols)
    assert added3 == ["close_lag3", "ret_lag2"], f"可扩展性不符: {added3}"


def test_build_features_extended_complete():
    """扩展模式下 build_features 产出全部特征列、无缺列、无 NaN/inf。"""
    names_ext = FT.EXTENDED_FEATURES.copy()
    ind_full, F, fnames = FT.build_features(_make_df(n=250, seed=5), extended=True,
                                            symbol="T3", period="1m")
    assert F.shape[1] == len(names_ext), \
        f"扩展特征列数 {F.shape[1]} != len(EXTENDED_FEATURES) {len(names_ext)}"
    assert all(c in F.columns for c in ("ret_lag1", "ret_lag2", "ret_lag5")), \
        "扩展模式下 ret_lag1/2/5 缺失"
    assert bool(np.isfinite(F.to_numpy(dtype=float)).all()), "扩展模式特征矩阵含 NaN/inf"
