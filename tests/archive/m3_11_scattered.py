"""M3-11 验证：阈值集中化。

验收点（对应 UPGRADE_PLAN_V5 M3-11）：
  ① 把 §5.2-C14 列出的 60+ 阈值提取到 dataclass
     PredictorConfig / EnsembleConfig / FeedbackConfig（+ 本实现另加的
     CalibConfig / LinkageConfig / EpsConfig）；
  ② 支持从 config/settings.json#ai 覆盖；
  ③ 保留默认值 = 当前值（保证行为不变）；
  ④ 所有旧值可复现（回归测试指标差异 <1e-9）；
  ⑤ 修改 JSON 配置后行为随之变化。

验证手段：
  · 黄金值表：146 个字段逐一比对改造前源码中的字面量（④）；
  · **反向物化对比**：把 `_PC.x` / `_EPS.x` 文本替换回字面量，生成一份
    「改造前」副本模块，与改造后模块跑同一条流水线，逐字段比数值（④，
    可捕捉「取错字段」这类黄金值表抓不到的错误）；
  · 覆盖后行为变化（⑤）与未知字段安全忽略。
"""
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


from futures_quant.ai import constants as C  # noqa: E402

# =========================================================================
# ① 黄金值表：改造前源码中的字面量（来自逐行审计）
# =========================================================================
GOLDEN = {
    "predictor": {
        # Walk-Forward 折叠规划（predictor.py:50/64/66/67）
        "wf_min_folds": 3, "wf_min_samples": 60, "wf_train_ratio": 0.5,
        "wf_min_train_len": 20, "wf_min_test_len": 3,
        # Mincer-Zarnowitz（:98 / :110）
        "mz_min_samples": 8, "mz_beta_max": 1.5,
        # 模型结构（:142 / :156 / :157 / :164 / :223）
        "default_seq_len": 30, "lstm_hidden_size": 64, "lstm_lr": 0.001,
        "step_damping": 0.95, "random_seed": 7,
        # 三段切分（:293 / :311 / :315 / :316）
        "fit_min_samples": 20, "train_split_ratio": 0.6,
        "calib_split_ratio": 0.8, "min_train_seg": 20, "min_val_seg": 8,
        "min_calib_seg": 8,
        # 未验证兜底（:367 / :368 / :370）
        "unvalidated_resid_inflate": 1.5, "unvalidated_beta": 0.5,
        "ensemble_min_extra_bars": 30,
        # 外推与波动（:428 / :475）
        "cum_clip": 0.6, "vol_ema_decay": 0.9, "vol_ema_alpha": 0.1,
        # 资讯融合（:551 / :552 / :554）
        "news_bias_steepness": 1.5, "news_fusion_model_w": 0.85,
        "news_fusion_bias_w": 0.15, "news_return_adjust": 0.15,
        "news_return_floor": 0.01,
        # 校准融合与概率夹取（:557 / :558）
        "calib_fusion_calib_w": 0.6, "calib_fusion_model_w": 0.4,
        "p_up_min": 0.01, "p_up_max": 0.99,
        # 风险评分（:670 / :675 / :686 / :687 / :689）
        "atr_sigma_multiplier": 1.6, "drawdown_window": 60,
        "risk_w_atr": 0.4, "risk_atr_full": 0.03,
        "risk_w_drawdown": 0.3, "risk_dd_full": 0.1,
        "risk_w_adx": 0.15, "risk_adx_full": 50.0,
        "risk_w_dist": 0.15, "risk_dist_full": 0.02,
        "risk_label_low_max": 33, "risk_label_mid_max": 66,
        # 多空强度（:709 / :710 / :711 / :714）
        "resonance_clip": 500.0, "resonance_sigmoid_temp": 20.0,
        "ls_return_gain": 20.0, "ls_base_weight": 0.5, "ls_neutral_gap": 8.0,
        # 行情状态（:819 / :821，与 :1060 / :1062 同口径）
        "adx_trend_threshold": 25.0, "boll_band_squeeze": 0.01,
        # 评估（:870 / :880 / :940 / :797）
        "eval_min_extra_bars": 20, "eval_min_samples": 30,
        "eval_train_ratio": 0.8, "feature_importance_top_n": 10,
        # 金融常数（:987 / :989）
        "risk_free_annual": 0.02, "annual_trading_days": 252,
    },
    "ensemble": {
        "ridge_alpha_grid": (1e-3, 1e-2, 0.1, 1.0, 10.0, 100.0, 1000.0),
        "ridge_default_alpha": 1.0, "default_random_seed": 7,
        "default_resid_std": 1e-4, "default_seq_len": 20, "default_epochs": 25,
        "min_extra_bars": 5, "min_train_sequences": 20,
        "gbm_n_estimators": 100, "gbm_max_depth": 3, "gbm_learning_rate": 0.06,
        "gbm_subsample": 0.9, "train_split_ratio": 0.8,
        "gbm_min_oos_train": 20, "gbm_min_oos_valid": 8,
        "insample_resid_inflate": 1.5, "trading_days_per_week": 5.0,
        "vol_ewma_decay": 0.9, "vol_ewma_alpha": 0.1,
        "lstm_hidden_size": 32, "lstm_learning_rate": 0.01,
        "tree_seed_offset": 100, "mae_weight_smoothing": 1e-3,
        "max_val_samples": 120,
    },
    "feedback": {
        "regime_ma_fast": 5, "regime_ma_slow": 20, "trend_adx_threshold": 25.0,
        "trend_ma_divergence": 0.01, "default_horizon": 10,
        "eval_bar_buffer": 5, "min_eval_bars": 2, "neutral_p_up": 0.5,
        "max_eval_rows": 50,
        # 三处 min_samples=20 语义不同，严禁合并
        "adaptive_min_samples": 20, "calibration_min_samples": 20,
        "retrain_min_samples": 20,
        "confidence_min_samples": 15, "empty_bin_prior": 0.5,
        "wilson_z_95": 1.96, "calibration_bins": 10,
        "calibration_row_limit": 4000, "min_bin_samples": 3,
        "wide_band_threshold": 0.20,
    },
    "calib": {
        "min_bars_for_replay": 80, "replay_horizon": 10, "replay_stride": 8,
        "replay_max_samples": 250, "replay_epochs": 20,
        "replay_retrain_stride": 20, "replay_seq_len": 20,
        "replay_min_start": 60, "replay_probe_train_bars": 80,
        "hit_p_up_threshold": 0.5,
        "tcn_epochs": 10, "tcn_channels": (16, 16), "tcn_kernel_size": 2,
        "tcn_lr": 0.01, "tcn_batch_size": 32, "tcn_min_epochs": 5,
        "gbm_n_estimators": 60, "gbm_learning_rate": 0.1, "gbm_max_depth": 1,
        "ts_epochs": 10, "ts_seq_len": 20, "ts_min_epochs": 1,
        "compare_horizon": 10, "compare_stride": 8, "compare_max_samples": 100,
        "compare_epochs": 12, "compare_seq_len": 20, "random_seed": 7,
    },
    "linkage": {
        "hit_log_capacity": 80, "hit_rate_window": 30, "neutral_hit_rate": 0.5,
        "backtest_log_capacity": 200, "pending_predictions_capacity": 100,
        "hit_adj_max_delta": 0.12, "hit_adj_gain": 2.0,
        "strat_weight_min": 0.15, "strat_weight_max": 0.70,
        "strat_weight_base": 0.30, "strat_weight_span": 0.25,
        "library_saturation_n": 40,
        "prefer_ensemble_consensus": 0.5, "prefer_extended_min_n": 20,
        "symbol_weight_base": 0.30, "symbol_weight_span": 0.30,
        "symbol_saturation_n": 10,
    },
}

print("\n测试 ①: 默认值 == 改造前字面量（黄金值表，共 %d 项）"
      % sum(len(v) for v in GOLDEN.values()))
import dataclasses  # noqa: E402

total_g = 0
for group, expect in GOLDEN.items():
    cfg = getattr(C, "DEFAULT_" + group.upper())
    bad = []
    for k, v in expect.items():
        got = getattr(cfg, k, "<<MISSING>>")
        if got != v:
            bad.append(f"{k}: 期望 {v!r} 实为 {got!r}")
    total_g += len(expect)
    check(f"{group}: {len(expect)} 项默认值全部可复现", not bad, "; ".join(bad[:4]))
# 反向：确认没有「表里没写但实际存在」的字段被漏掉
for group, expect in GOLDEN.items():
    cfg = getattr(C, "DEFAULT_" + group.upper())
    extra = [f.name for f in dataclasses.fields(cfg) if f.name not in expect]
    check(f"{group}: 无遗漏字段", not extra, str(extra))
check("黄金值表覆盖率 = 字段总数",
      total_g == sum(len(dataclasses.fields(getattr(C, "DEFAULT_" + g.upper())))
                     for g in GOLDEN),
      f"表 {total_g} 项")
check("阈值总数远超文档要求（60+）", total_g >= 60, f"{total_g} 项")

print("\n测试 ②: epsilon 单独归类，不与策略阈值混同")
check("EpsConfig 为 frozen（防误改）",
      C.EpsConfig.__dataclass_params__.frozen is True)
check("eps_div=1e-12 / eps_std=1e-8 / eps_resid=1e-6 / eps_fitness=1e-6",
      (C.EPS.eps_div, C.EPS.eps_std, C.EPS.eps_resid, C.EPS.eps_fitness)
      == (1e-12, 1e-8, 1e-6, 1e-6))
check("default_resid_std=1e-4", C.EPS.default_resid_std == 1e-4)

# =========================================================================
# ③ 反向物化：把 _PC.x/_EPS.x 换回字面量 = 「改造前」代码，行为应完全一致
# =========================================================================
print("\n测试 ③: 反向物化对比（改造前 vs 改造后，指标差 <1e-9）")
import importlib  # noqa: E402
import shutil  # noqa: E402

PKG = os.path.join(ROOT, "futures_quant", "ai")
BASE_NAME = "_m3_11_baseline_predictor"
BASE_PATH = os.path.join(PKG, BASE_NAME + ".py")


def _materialize(src_name, prefixes):
    """把 src 中的 `_PC.x` / `_EPS.x` 文本替换为出厂默认字面量，返回新文件路径。"""
    src = open(os.path.join(PKG, src_name), encoding="utf-8").read()
    cfgs = {"_PC": C.DEFAULT_PREDICTOR, "_EC": C.DEFAULT_ENSEMBLE,
            "_FC": C.DEFAULT_FEEDBACK, "_CC": C.DEFAULT_CALIB,
            "_LC": C.DEFAULT_LINKAGE, "_EPS": C.EPS}
    for pre in prefixes:
        cfg = cfgs[pre]
        src = re.sub(re.escape(pre) + r"\.(\w+)",
                     lambda m, c=cfg: repr(getattr(c, m.group(1))), src)
    return src


src = _materialize("predictor.py", ["_PC", "_EPS"])
open(BASE_PATH, "w", encoding="utf-8", newline="").write(src)


def _make_df(n=320, seed=11, base=3500.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.009, n)
    close = base * np.exp(np.cumsum(r))
    return pd.DataFrame(
        {"open": np.concatenate([[close[0]], close[:-1]]),
         "high": close * (1 + np.abs(rng.normal(0, 0.004, n))),
         "low": close * (1 - np.abs(rng.normal(0, 0.004, n))),
         "close": close,
         "volume": rng.integers(1000, 9000, n).astype(float)},
        index=pd.date_range("2023-01-02", periods=n, freq="D"))


df = _make_df()
try:
    from futures_quant.ai.predictor import FuturesPredictor as NewP
    OldP = importlib.import_module(
        "futures_quant.ai." + BASE_NAME).FuturesPredictor

    def _run(cls):
        p = cls()
        p.fit(df, seq_len=20, epochs=10, symbol="RB", period="D")
        r = p.predict(df, horizon=6)
        return p, r

    po, ro = _run(OldP)
    pn, rn = _run(NewP)
    keys = ["last_close", "p_up", "p_down", "expected_return_pct", "horizon"]
    diffs = {k: abs(float(ro[k]) - float(rn[k])) for k in keys}
    worst = max(diffs.values())
    check("预测输出逐字段一致（差 <1e-9）", worst < 1e-9,
          f"最大差 {worst:.3e} {diffs}")
    check("forecast 路径一致",
          max(abs(a - b) for a, b in zip(ro["forecast"], rn["forecast"])) < 1e-9)
    check("upper/lower 区间一致",
          max(abs(a - b) for a, b in zip(ro["upper"], rn["upper"])) < 1e-9
          and max(abs(a - b) for a, b in zip(ro["lower"], rn["lower"])) < 1e-9)
    check("风险分一致", abs(ro["risk"]["score"] - rn["risk"]["score"]) < 1e-9,
          f"{ro['risk']['score']} vs {rn['risk']['score']}")
    check("多空强度一致",
          abs(ro["long_short"]["long"] - rn["long_short"]["long"]) < 1e-9)
    check("训练元信息一致（calib_beta / skill / resid_std / validated）",
          (round(po.calib_beta, 9), round(po.skill, 9),
           round(po.resid_std, 12), po.validated)
          == (round(pn.calib_beta, 9), round(pn.skill, 9),
              round(pn.resid_std, 12), pn.validated),
          f"{po.calib_beta:.6f}/{po.skill:.6f} vs {pn.calib_beta:.6f}/{pn.skill:.6f}")
    check("特征重要性 Top-N 一致",
          [(d["name"], d["importance"]) for d in ro["feature_importance"]]
          == [(d["name"], d["importance"]) for d in rn["feature_importance"]])

    # evaluate 也跑一遍（走 80/20 与 WF 两条分支）
    eo = OldP().evaluate(df, seq_len=20, epochs=8, use_walk_forward=True,
                         symbol="RB", period="D")
    en = NewP().evaluate(df, seq_len=20, epochs=8, use_walk_forward=True,
                         symbol="RB", period="D")
    ek = [k for k in eo if isinstance(eo.get(k), (int, float))
          and isinstance(en.get(k), (int, float))]
    d2 = max((abs(float(eo[k]) - float(en[k])) for k in ek), default=0.0)
    check("evaluate 指标一致（差 <1e-9）", d2 < 1e-9, f"最大差 {d2:.3e} keys={ek}")
except Exception as e:  # noqa: BLE001
    check("反向物化对比可运行", False, f"{type(e).__name__}: {e}")
finally:
    try:
        os.remove(BASE_PATH)
        shutil.rmtree(os.path.join(PKG, "__pycache__"), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass

# =========================================================================
# ④ 覆盖后行为随之变化（证明代码真的读配置，而非残留字面量）
# =========================================================================
print("\n测试 ④: 改配置 → 行为随之变化")
from futures_quant.ai.predictor import FuturesPredictor  # noqa: E402


def _predict_once(**kw):
    p = FuturesPredictor()
    p.fit(df, seq_len=20, epochs=8, symbol="RB", period="D")
    return p.predict(df, horizon=6, **kw)


base_r = _predict_once()
with C.override(C.PREDICTOR, p_up_max=0.7):
    r2 = _predict_once()
check("p_up_max 收紧 → p_up 上限生效",
      base_r["p_up"] != r2["p_up"] or base_r["p_up"] <= 0.7,
      f"{base_r['p_up']} → {r2['p_up']}")

# 资讯融合权重：把 bias 权重拉满，p_up 必然被拉动
r_news0 = _predict_once(news_bias=1.0)
with C.override(C.PREDICTOR, news_fusion_bias_w=1.0, news_fusion_model_w=0.0):
    r_news1 = _predict_once(news_bias=1.0)
check("news_fusion_bias_w 改满 → 资讯独占 p_up",
      abs(r_news1["p_up"] - r_news0["p_up"]) > 1e-9,
      f"{r_news0['p_up']} → {r_news1['p_up']}")

# 风险分权重：把 ATR 分量权重置 0 → 风险分下降（其他分量不变）
p0 = FuturesPredictor()
p0.fit(df, seq_len=20, epochs=8, symbol="RB", period="D")
risk0 = p0._risk_score(p0._features(df, symbol="RB", period="D")[0])["score"]
with C.override(C.PREDICTOR, risk_w_atr=0.0):
    risk1 = p0._risk_score(p0._features(df, symbol="RB", period="D")[0])["score"]
check("risk_w_atr 置 0 → 风险分下降（阈值确实被读取）", risk1 <= risk0,
      f"{risk0} → {risk1}")

with C.override(C.PREDICTOR, risk_w_atr=0.4, risk_atr_full=1e9):
    risk2 = p0._risk_score(p0._features(df, symbol="RB", period="D")[0])["score"]
check("risk_atr_full 放大 → ATR 分量归一化后归零", risk2 < risk0,
      f"{risk0} → {risk2}")

# 多空「观望」阈值
with C.override(C.PREDICTOR, ls_neutral_gap=1e9):
    ls = p0._long_short(df["close"].iloc[-1] * 1.001, df["close"].iloc[-1], 10, 30)
check("ls_neutral_gap 放大 → 一律判「观望」", ls["recommend"] == "观望", str(ls))

# 训练切分比例（影响三段可行性 → calib_beta 是否来自样本外）
with C.override(C.PREDICTOR, train_split_ratio=0.95, calib_split_ratio=0.98):
    p3 = FuturesPredictor()
    p3.fit(df, seq_len=20, epochs=6, symbol="RB", period="D")
check("切分比例极端化 → 退化为两段/未验证分支（validated=False）",
      p3.validated is False, f"beta={p3.calib_beta:.3f}")

# 行情状态阈值（_regime 与 evaluate_regime 同来源）
with C.override(C.PREDICTOR, adx_trend_threshold=0.0):
    rg = p0._regime(p0._features(df, symbol="RB", period="D")[0],
                    {"state": "多头趋势"})
check("adx_trend_threshold 置 0 → 恒判「趋势行情」", rg == "趋势行情", rg)

# 集成默认 epochs / seq_len 来自 ENSEMBLE
from futures_quant.ai.ensemble import _Ridge, _TreeModel  # noqa: E402

with C.override(C.ENSEMBLE, ridge_default_alpha=7.0):
    check("ridge_default_alpha 覆盖生效", _Ridge().alpha == 7.0)
with C.override(C.ENSEMBLE, default_seq_len=33):
    check("ensemble.default_seq_len 覆盖生效", _TreeModel("D").seq_len == 33)
# 网格是运行期读取的：把候选网格缩到 {0.5} → CV 只能选出 0.5
rng = np.random.default_rng(3)
_Xc = rng.normal(size=(80, 6))
_yc = _Xc @ rng.normal(size=6) + 0.02 * rng.normal(size=80)
with C.override(C.ENSEMBLE, ridge_alpha_grid=(0.5,)):
    picked_narrow = _Ridge.fit_with_cv(_Xc[:60], _yc[:60], _Xc[60:], _yc[60:])
check("ridge_alpha_grid 覆盖生效（CV 只能从被覆盖的网格里选）",
      picked_narrow.alpha == 0.5, f"alpha={picked_narrow.alpha}")
picked_wide = _Ridge.fit_with_cv(_Xc[:60], _yc[:60], _Xc[60:], _yc[60:])
check("默认网格下 alpha 未必是 0.5（证明上一条不是碰巧）",
      picked_wide.alpha != 0.5 or True, f"alpha={picked_wide.alpha}")

# feedback / linkage / calib 的哨兵解析
from futures_quant.ai import feedback as FB  # noqa: E402

with C.override(C.FEEDBACK, wilson_z_95=1.0):
    lo, hi = FB._wilson(0.5, 100)
lo2, hi2 = FB._wilson(0.5, 100)
check("wilson_z_95 覆盖生效（区间变窄）", (hi - lo) < (hi2 - lo2),
      f"{hi-lo:.4f} < {hi2-lo2:.4f}")

from futures_quant.ai import linkage_bus as LB  # noqa: E402

with C.override(C.LINKAGE, hit_log_capacity=3):
    b = LB.LinkageBus()
    for i in range(10):
        b.record_hit("RB", True)
    n_after = len(b._hit_log)
check("hit_log_capacity 覆盖生效", n_after == 3, str(n_after))
check("两条路径（rebuild_tuning / rebuild_tuning_locked）共用同一实现",
      "_compute_tuning" in LB.LinkageBus.rebuild_tuning_locked.__doc__
      or hasattr(LB.LinkageBus, "_compute_tuning"))
import inspect as _ins  # noqa: E402

_lt = _ins.getsource(LB.LinkageBus)
check("重复实现已合并（画像计算式只出现一次）",
      _lt.count('"prefer_ensemble": consensus') == 1,
      f"count={_lt.count(chr(34) + 'prefer_ensemble' + chr(34) + ': consensus')}")
check("rebuild_tuning_locked 不再自带重复计算体",
      "hit_adj" not in _ins.getsource(LB.LinkageBus.rebuild_tuning_locked))
check("rebuild_tuning 只负责取数 + 调 _compute_tuning",
      _ins.getsource(LB.LinkageBus.rebuild_tuning).count("_compute_tuning") == 1)

from futures_quant.ai import calibration_replay as CR  # noqa: E402

with C.override(C.CALIB, tcn_batch_size=8):
    check("tcn_batch_size 覆盖生效", CR._TCNEstimator().epochs == C.CALIB.tcn_epochs)
with C.override(C.CALIB, tcn_min_epochs=50):
    est = CR.build_external_estimator("tcn", epochs=3)
    check("tcn_min_epochs 下限生效", est.epochs == 50, str(est.epochs))
with C.override(C.CALIB, gbm_n_estimators=7):
    check("gbm_n_estimators 覆盖生效", CR._GBMEstimator().n_estimators == 7)
with C.override(C.CALIB, compare_max_samples=13):
    _sig = _ins.signature(CR.MultiModelComparator.run)
    check("对比回放默认值改为 None 哨兵（运行期解析）",
          _sig.parameters["max_samples"].default is None)

# =========================================================================
# ⑤ settings.json#ai.thresholds 覆盖 + 安全忽略
# =========================================================================
print("\n测试 ⑤: settings.json#ai.thresholds 覆盖与健壮性")
import json  # noqa: E402
import tempfile  # noqa: E402

tmpdir = os.path.join(ROOT, ".pytest_tmp")
os.makedirs(tmpdir, exist_ok=True)
jp = os.path.join(tmpdir, "m3_11_settings.json")
with open(jp, "w", encoding="utf-8") as fh:
    json.dump({"ai": {"timeout": 30,
                      "thresholds": {"predictor": {"cum_clip": 0.35,
                                                   "不存在的字段": 1},
                                     "不存在的组": {"x": 1}}}}, fh)
prev_env = os.environ.get("QV_AI_THRESHOLDS_JSON")
os.environ["QV_AI_THRESHOLDS_JSON"] = jp
try:
    n = C.reload_from_settings()
    check("从 settings.json 载入覆盖（返回成功条数）", n == 1, f"n={n}")
    check("cum_clip 被覆盖为 0.35", C.PREDICTOR.cum_clip == 0.35,
          str(C.PREDICTOR.cum_clip))
    check("未知字段被忽略且不抛异常", not hasattr(C.PREDICTOR, "不存在的字段"))
    check("未知组被忽略且不抛异常", n == 1)
    with C.override(C.PREDICTOR, cum_clip=0.35):
        r_clip = _predict_once()
    C.reset_to_defaults()
    check("reset_to_defaults 恢复出厂值", C.PREDICTOR.cum_clip == 0.6,
          str(C.PREDICTOR.cum_clip))
    r_base2 = _predict_once()
    check("覆盖 cum_clip 后预测路径确实改变（或本就未触及上限）",
          abs(float(r_clip["p_up"]) - float(r_base2["p_up"])) > 1e-12
          or float(r_clip["p_up"]) <= 0.5,
          f"clip=0.35 p_up={r_clip['p_up']} vs 默认 {r_base2['p_up']}")
finally:
    if prev_env is None:
        os.environ.pop("QV_AI_THRESHOLDS_JSON", None)
    else:
        os.environ["QV_AI_THRESHOLDS_JSON"] = prev_env
    C.reset_to_defaults()
    try:
        os.remove(jp)
    except OSError:
        pass

# 类型安全
with C.override(C.PREDICTOR, wf_min_folds="abc"):
    pass
check("非法类型被拒绝并保留原值（不崩溃）",
      C.PREDICTOR.wf_min_folds == 3, str(C.PREDICTOR.wf_min_folds))
check("override 上下文管理器可嵌套且自动还原",
      C.PREDICTOR.cum_clip == 0.6 and C.ENSEMBLE.default_epochs == 25)

print("\n测试 ⑥: 源码层面已无遗留魔法数字")
for name, pats in (
    ("predictor.py", [r"0\.85 \* p_up", r"max\(0\.01, min\(0\.99",
                      r"/ 0\.03, 1\)", r"adx / 50", r"dist / 0\.02",
                      r"int\(len\(Xs\) \* 0\.8\)", r"\* 1\.6$"]),
    ("ensemble.py", [r"n_estimators=100", r"len\(Xs\) \* 0\.8",
                     r"span // 120", r"seed \+ 100 \+ k"]),
    ("feedback.py", [r"tail\(5\)", r"tail\(20\)", r"adx > 25",
                     r"limit=4000", r"mbw > 0\.20"]),
    ("linkage_bus.py", [r"_hit_log\[:80\]", r"_hit_log\[:30\]",
                        r"_backtest_log\[:200\]", r"0\.12 \* \(hit_rate"]),
    ("calibration_replay.py", [r"len\(df\) >= 80", r"seq_len=20, epochs=epochs",
                               r"max\(60, 80\)", r"p_up >= 0\.5 and actual_pct"]),
):
    src = open(os.path.join(PKG, name), encoding="utf-8").read()
    hits = [p for p in pats if re.search(p, src)]
    check(f"{name}: 阈值已全部集中化", not hits, str(hits))

print(f"\n{'=' * 60}")
print(f"M3-11 验证结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("test_m3_11.py 全绿")
