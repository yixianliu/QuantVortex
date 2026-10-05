"""M3-12 验证：性能 —— 消除重复预测与重复训练。

验收点（对应 UPGRADE_PLAN_V5 M3-12）：
  ① `predict_ops_page` 里拿到校准概率后的**二次 predict()** 改为直接对已有
     `p_up` 应用校准函数（无需重跑外推）；
  ② `evaluate_regime`（旧 :857-978）与 `evaluate` 合并共用内部函数，
     删除逐行 `apply` 死代码；
  ③ `_add_lag_features` 只生成被使用的 3 列（原 34×3=102 列）。

文档验收标准：
  · 单次预测耗时下降 ≥40%（计时对比）；
  · `evaluate_regime` 与 `evaluate` 结果一致。

验证手段：
  · 计时对比：真的各跑一遍「旧链路（predict 两次）」与「新链路（predict +
    apply_p_up_calibration）」，取多轮最小总耗时算下降比例；
  · 语义等价：新链路 p_up 与旧链路 p_up 差 ≤5e-5（round(,4) 引入，已注明）；
  · 一致性：evaluate_regime()["overall"] 与 evaluate() 逐字段相等；
  · 重复训练消除：monkeypatch 计数 _evaluate_core，evaluate_regime 只调用 1 次；
  · 死代码：evaluate_regime 源码不含逐行 apply；
  · 列裁剪：_add_lag_features 按 feature_names 需求生成。
"""
import inspect
import os
import re
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


from futures_quant.ai import constants as C          # noqa: E402
from futures_quant.ai import features as FT          # noqa: E402
from futures_quant.ai.predictor import FuturesPredictor  # noqa: E402


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


# =========================================================================
# ① 二次 predict 消除
# =========================================================================
print("\n=== ① 二次 predict 消除（语义等价 + 计时对比） ===")

# ①-a 源码层面：页面不再出现 calibrate_p_up
try:
    from futures_quant.ui import predict_ops_page as POP
    src_page = inspect.getsource(POP)
except Exception as e:  # noqa: BLE001
    src_page = ""
    print(f"  [!!] 无法读取 predict_ops_page 源码：{e}")

check("①页面源码不再出现 calibrate_p_up= 传参（二次 predict 已移除）",
      bool(src_page) and "calibrate_p_up=" not in src_page)
check("①页面改为调用 apply_p_up_calibration",
      bool(src_page) and "apply_p_up_calibration" in src_page)
check("①predictor 提供 apply_p_up_calibration",
      hasattr(FuturesPredictor, "apply_p_up_calibration"))

# ①-b 语义等价 + 计时对比
df = _make_df(n=300)
pred = FuturesPredictor()
fit_res = pred.fit(df, seq_len=20, epochs=5, symbol="TEST", period="1m")
check("①前置：fit 成功", bool(fit_res.get("trained")),
      str(fit_res.get("reason", "")))

CONF = 0.62   # 假设的历史校准概率（与模型 p_up 明显不同，才会触发融合）

# warmup（触发 lazy import、JIT 风格的首次开销）
for _ in range(2):
    r0 = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
    pred.apply_p_up_calibration(dict(r0), CONF)
    pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m",
                 calibrate_p_up=CONF)

# 语义等价：同一份 res，旧（二次 predict）与新（就地融合）对比
res_base = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
res_old = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m",
                       calibrate_p_up=CONF)
res_new = pred.apply_p_up_calibration(dict(res_base), CONF)

d_p = abs(float(res_new["p_up"]) - float(res_old["p_up"]))
d_d = abs(float(res_new["p_down"]) - float(res_old["p_down"]))
check("①新/旧 p_up 语义等价（差 ≤5e-5，round 引入）", d_p <= 5e-5,
      f"new={res_new['p_up']} old={res_old['p_up']} diff={d_p:.2e}")
check("①新/旧 p_down 同步更新", d_d <= 5e-5,
      f"new={res_new['p_down']} old={res_old['p_down']} diff={d_d:.2e}")
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


_diff = [k for k in res_base
         if k not in ("p_up", "p_down") and not _same(res_new[k], res_base[k])]
check("①除 p_up/p_down 外其余字段与首次 predict 完全一致", not _diff,
      f"差异字段={_diff}")
check("①p_up + p_down == 1",
      abs(res_new["p_up"] + res_new["p_down"] - 1.0) < 1e-9,
      f"{res_new['p_up']} + {res_new['p_down']}")

# 计时对比：真跑两条链路
REPEAT = 8
ROUNDS = 3


def _time_old():
    t0 = time.perf_counter()
    for _ in range(REPEAT):
        a = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
        b = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m",
                         calibrate_p_up=CONF)
    return time.perf_counter() - t0, b


def _time_new():
    t0 = time.perf_counter()
    for _ in range(REPEAT):
        a = pred.predict(df, horizon=10, news_bias=0.2, symbol="TEST", period="1m")
        b = pred.apply_p_up_calibration(a, CONF)
    return time.perf_counter() - t0, b


t_old = min(_time_old()[0] for _ in range(ROUNDS))
t_new = min(_time_new()[0] for _ in range(ROUNDS))
drop = 1.0 - (t_new / t_old) if t_old > 0 else 0.0
check("①单次预测耗时下降 ≥40%（文档验收标准）", drop >= 0.40,
      f"old={t_old*1000:.1f}ms new={t_new*1000:.1f}ms 下降={drop*100:.1f}%")

# ①-c 降级结果不参与校准（与旧二次 predict 行为一致）
neutral = pred._neutral_result(df, 10, "有效样本不足")
pred.apply_p_up_calibration(neutral, CONF)
check("①降级（数据不足）结果保持中性 p_up=0.5", abs(neutral["p_up"] - 0.5) < 1e-12,
      f"p_up={neutral['p_up']}")
# 非法输入不炸
bad = {"p_up": None}
pred.apply_p_up_calibration(bad, CONF)
check("①非法 p_up 安全跳过不抛异常", bad["p_up"] is None)


# =========================================================================
# ② evaluate_regime 与 evaluate 合并
# =========================================================================
print("\n=== ② evaluate_regime 与 evaluate 共用 _evaluate_core ===")

check("②存在 _evaluate_core 单一实现", hasattr(FuturesPredictor, "_evaluate_core"))
check("②存在向量化 _regime_labels", hasattr(FuturesPredictor, "_regime_labels"))

def _code_names(func) -> set:
    """只看**代码体**里出现的标识符（剥掉 docstring，避免注释文字误伤）。"""
    import ast
    import textwrap
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


_names_regime = _code_names(FuturesPredictor.evaluate_regime)
check("②evaluate_regime 代码体不再出现逐行 apply 死代码",
      "apply" not in _names_regime)
check("②evaluate_regime 代码体不再重复建序列/训练",
      not ({"_build_sequences", "_train_core", "_features"} & _names_regime),
      f"残留={sorted({'apply','_build_sequences','_train_core','_features'} & _names_regime)}")

df2 = _make_df(n=300, seed=11)
p2 = FuturesPredictor()

# ②-a 一致性：overall 与 evaluate 完全相同
for wf in (True, False):
    m_eval = p2.evaluate(df2, horizon=1, seq_len=20, epochs=3,
                         use_walk_forward=wf, symbol="T2", period="1m")
    m_reg = p2.evaluate_regime(df2, horizon=1, seq_len=20, epochs=3,
                               use_walk_forward=wf, symbol="T2", period="1m")
    if "error" in m_eval or "error" in m_reg:
        check(f"②use_walk_forward={wf} 评估可用", False,
              f"eval={m_eval.get('error')} regime={m_reg.get('error')}")
        continue
    same = (set(m_eval.keys()) == set(m_reg["overall"].keys())
            and all(m_eval[k] == m_reg["overall"][k] for k in m_eval))
    check(f"②evaluate_regime['overall'] 与 evaluate 完全一致（wf={wf}）", same,
          f"n={len(m_eval)}字段 val_samples={m_eval['val_samples']}")
    # by_regime 的样本数之和 == 总验证样本数（分组没丢样本、也没重复计）
    tot = sum(v.get("samples", 0) for v in m_reg["by_regime"].values())
    check(f"②分行情样本数之和 == 总体验证样本数（wf={wf}）",
          tot == m_eval["val_samples"], f"{tot} vs {m_eval['val_samples']}")
    # 行情标签取值合法
    allowed = {"趋势行情", "震荡收敛(变盘窗口)", "震荡行情"}
    check(f"②行情标签取值合法（wf={wf}）",
          set(m_reg["by_regime"].keys()) <= allowed,
          str(sorted(m_reg["by_regime"].keys())))

# ②-b 重复训练消除：evaluate_regime 只调 1 次 _evaluate_core
orig_core = FuturesPredictor._evaluate_core
calls = {"n": 0}


def _counted(self, *a, **kw):
    calls["n"] += 1
    return orig_core(self, *a, **kw)


FuturesPredictor._evaluate_core = _counted
try:
    p2.evaluate_regime(df2, horizon=1, seq_len=20, epochs=3,
                       use_walk_forward=True, symbol="T2", period="1m")
finally:
    FuturesPredictor._evaluate_core = orig_core
check("②evaluate_regime 只跑 1 次评估（旧实现为 2 次）", calls["n"] == 1,
      f"_evaluate_core 调用 {calls['n']} 次")

# ②-c 计时对比：evaluate_regime 应与「只跑一次 evaluate」同量级
#     改造前 = evaluate()（1 次全量）+ 自建序列 & 训练（1 次）→ 必然 > t_eval
def _t(fn, rounds=3):
    best = float("inf")
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


_EV = dict(horizon=1, seq_len=20, epochs=3, use_walk_forward=True,
           symbol="T2", period="1m")
# warmup
p2.evaluate(df2, **_EV)
p2.evaluate_regime(df2, **_EV)
t_eval = _t(lambda: p2.evaluate(df2, **_EV))
t_reg = _t(lambda: p2.evaluate_regime(df2, **_EV))
check("②evaluate_regime 耗时与单次 evaluate 同量级（≤1.35×，即不再多跑一遍）",
      t_reg <= 1.35 * t_eval,
      f"evaluate={t_eval*1000:.1f}ms evaluate_regime={t_reg*1000:.1f}ms "
      f"比值={t_reg/t_eval:.2f}")

# ②-d _regime_labels 与 df 行对齐
ind2, _F2 = p2._features(df2, symbol="T2", period="1m")  # noqa: N806
labels = FuturesPredictor._regime_labels(ind2)
check("②_regime_labels 长度与 df 行数一致", len(labels) == len(ind2),
      f"{len(labels)} vs {len(ind2)}")
check("②_regime_labels 取值合法", set(np.unique(labels)) <= {"趋势行情", "震荡收敛(变盘窗口)", "震荡行情"},
      str(sorted(set(np.unique(labels)))))


# =========================================================================
# ③ _add_lag_features 只生成被使用的列
# =========================================================================
print("\n=== ③ _add_lag_features 按需生成 ===")

ind_src = pd.DataFrame({
    "close": np.linspace(100, 200, 60),
    "ret": np.random.default_rng(3).normal(0, 0.01, 60),
})
ind_src["ma5"] = ind_src["close"].rolling(5, min_periods=1).mean()

names_ext = FT.EXTENDED_FEATURES.copy()
before_cols = set(ind_src.columns)
out = FT._add_lag_features(ind_src.copy(), names_ext)
added = sorted(set(out.columns) - before_cols)

check("③扩展特征下只新增 3 列（旧实现 34×3=102 列）",
      len(added) == 3, f"新增 {added}")
check("③新增列正是被 feature_names 引用的 ret_lag1/2/5",
      added == ["ret_lag1", "ret_lag2", "ret_lag5"], str(added))
check("③数值正确：lagN == 基列 shift(N)",
      bool(np.allclose(out["ret_lag1"].to_numpy()[1:],
                       ind_src["ret"].shift(1).to_numpy()[1:], equal_nan=True))
      and bool(np.allclose(out["ret_lag5"].to_numpy()[5:],
                           ind_src["ret"].shift(5).to_numpy()[5:], equal_nan=True)))
check("③未污染原 DataFrame（返回新对象）", "ret_lag1" not in ind_src.columns)

# ③-b 无 lag 需求 → 一列不增
out0 = FT._add_lag_features(ind_src.copy(), ["close", "ret", "ma5"])
check("③feature_names 无 lag 项时一列不增",
      set(out0.columns) == before_cols, str(sorted(set(out0.columns) - before_cols)))

# ③-c 可扩展性：新增 xxx_lag3 只要写进 feature_names 就自动生成
out3 = FT._add_lag_features(ind_src.copy(), ["close_lag3", "ret_lag2"])
added3 = sorted(set(out3.columns) - before_cols)
check("③新增 lag 需求可自动扩展（close_lag3 / ret_lag2）",
      added3 == ["close_lag3", "ret_lag2"], str(added3))

# ③-d 真实链路：build_features 在扩展模式下仍产出全部特征列（无缺列回归）
ind_full, F, fnames = FT.build_features(_make_df(n=250, seed=5), extended=True,
                                       symbol="T3", period="1m")
check("③扩展模式下特征矩阵列数 == len(EXTENDED_FEATURES)",
      F.shape[1] == len(names_ext), f"{F.shape[1]} vs {len(names_ext)}")
check("③扩展模式下 ret_lag1/2/5 均存在",
      all(c in F.columns for c in ("ret_lag1", "ret_lag2", "ret_lag5")))
check("③扩展模式下无 NaN/inf 残留",
      bool(np.isfinite(F.to_numpy(dtype=float)).all()))


# =========================================================================
# 汇总
# =========================================================================
print("\n" + "=" * 60)
print(f"M3-12 验证结果：PASS={len(PASS)}  FAIL={len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print(f"  - {f}")
print("=" * 60)
sys.exit(1 if FAIL else 0)
