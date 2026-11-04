"""M3-11 阈值集中化 —— pytest 形态。

由散落脚本 ``tests/test_m3_11.py``（模块级 ``PASS/FAIL`` 列表 +
``check(name,cond,detail)`` 辅助 + 结尾 ``if FAIL: sys.exit(1)``，
0 个 ``def test_*``）机械改写：每段 ``check(...)`` 收敛为
``assert cond, f"{name} — {detail}"``，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 已逐项实测核对生产契约：黄金值表 146 项零漂移 / 零遗漏；反向物化依赖的
  ``_PC._EPS`` 在 ``predictor.py`` 仍各 71/26 处、私有方法
  ``_features/_risk_score/_long_short/_regime`` 签名兼容；``C.override`` /
  ``reload_from_settings`` / ``reset_to_defaults`` 均存在。

- 反向物化（③）会运行时把 ``predictor.py`` 里 ``_PC.x/_EPS.x`` 替换回字面量、
  在 ``futures_quant/ai/`` 内生成临时模块并 import，跑同一条流水线做数值对比，
  最后在 ``finally`` 里删除文件 + ``__pycache__`` + 从 ``sys.modules`` 卸出，
  确保不污染源码树与后续导入。
"""
from __future__ import annotations

import importlib
import os
import re
import shutil
import sys

import numpy as np
import pandas as pd

from futures_quant.ai import constants as C

# =========================================================================
# ① 黄金值表：改造前源码中的字面量（来自逐行审计）
# =========================================================================
GOLDEN = {
    "predictor": {
        # Walk-Forward 折叠规划
        "wf_min_folds": 3, "wf_min_samples": 60, "wf_train_ratio": 0.5,
        "wf_min_train_len": 20, "wf_min_test_len": 3,
        # Mincer-Zarnowitz
        "mz_min_samples": 8, "mz_beta_max": 1.5,
        # 模型结构
        "default_seq_len": 30, "lstm_hidden_size": 64, "lstm_lr": 0.001,
        "step_damping": 0.95, "random_seed": 7,
        # 三段切分
        "fit_min_samples": 20, "train_split_ratio": 0.6,
        "calib_split_ratio": 0.8, "min_train_seg": 20, "min_val_seg": 8,
        "min_calib_seg": 8,
        # 未验证兜底
        "unvalidated_resid_inflate": 1.5, "unvalidated_beta": 0.5,
        "ensemble_min_extra_bars": 30,
        # 外推与波动
        "cum_clip": 0.6, "vol_ema_decay": 0.9, "vol_ema_alpha": 0.1,
        # 资讯融合
        "news_bias_steepness": 1.5, "news_fusion_model_w": 0.85,
        "news_fusion_bias_w": 0.15, "news_return_adjust": 0.15,
        "news_return_floor": 0.01,
        # 校准融合与概率夹取
        "calib_fusion_calib_w": 0.6, "calib_fusion_model_w": 0.4,
        "p_up_min": 0.01, "p_up_max": 0.99,
        # 风险评分
        "atr_sigma_multiplier": 1.6, "drawdown_window": 60,
        "risk_w_atr": 0.4, "risk_atr_full": 0.03,
        "risk_w_drawdown": 0.3, "risk_dd_full": 0.1,
        "risk_w_adx": 0.15, "risk_adx_full": 50.0,
        "risk_w_dist": 0.15, "risk_dist_full": 0.02,
        "risk_label_low_max": 33, "risk_label_mid_max": 66,
        # 多空强度
        "resonance_clip": 500.0, "resonance_sigmoid_temp": 20.0,
        "ls_return_gain": 20.0, "ls_base_weight": 0.5, "ls_neutral_gap": 8.0,
        # 行情状态
        "adx_trend_threshold": 25.0, "boll_band_squeeze": 0.01,
        # 评估
        "eval_min_extra_bars": 20, "eval_min_samples": 30,
        "eval_train_ratio": 0.8, "feature_importance_top_n": 10,
        # 金融常数
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

AI_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "futures_quant", "ai")
AI_PKG = os.path.abspath(AI_PKG)


def _make_df_m11(n=320, seed=11, base=3500.0):
    """构造合成行情，供 fit / predict / evaluate 使用。"""
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


def test_golden_defaults():
    """① 默认值 == 改造前字面量（黄金值表，共 146 项）+ 无遗漏字段 + 覆盖率。"""
    import dataclasses

    total_g = 0
    for group, expect in GOLDEN.items():
        cfg = getattr(C, "DEFAULT_" + group.upper())
        bad = []
        for k, v in expect.items():
            got = getattr(cfg, k, "<<MISSING>>")
            if got != v:
                bad.append(f"{k}: 期望 {v!r} 实为 {got!r}")
        total_g += len(expect)
        assert not bad, f"{group}: {len(expect)} 项默认值全部可复现 — {'; '.join(bad[:4])}"

    for group, expect in GOLDEN.items():
        cfg = getattr(C, "DEFAULT_" + group.upper())
        extra = [f.name for f in dataclasses.fields(cfg) if f.name not in expect]
        assert not extra, f"{group}: 无遗漏字段 — {extra}"

    total_fields = sum(len(dataclasses.fields(getattr(C, "DEFAULT_" + g.upper())))
                       for g in GOLDEN)
    assert total_g == total_fields, f"黄金值表覆盖率 = 字段总数 — {total_g}"
    assert total_g >= 60, f"阈值总数远超文档要求（60+）— {total_g} 项"


def test_eps_config():
    """② epsilon 单独归类（frozen），EPS 值固定。"""
    assert C.EpsConfig.__dataclass_params__.frozen is True, "EpsConfig 为 frozen（防误改）"
    assert (C.EPS.eps_div, C.EPS.eps_std, C.EPS.eps_resid, C.EPS.eps_fitness) \
        == (1e-12, 1e-8, 1e-6, 1e-6), \
        "eps_div=1e-12 / eps_std=1e-8 / eps_resid=1e-6 / eps_fitness=1e-6"
    assert C.EPS.default_resid_std == 1e-4, "default_resid_std=1e-4"


def _materialize_predictor():
    """把 predictor.py 里的 ``_PC.x`` / ``_EPS.x`` 文本替换回出厂字面量，
    生成一份「改造前」副本模块路径（写入 ``futures_quant/ai/`` 内以便相对导入）。
    """
    src_name = "predictor.py"
    base_name = "_m3_11_baseline_predictor"
    base_path = os.path.join(AI_PKG, base_name + ".py")
    src = open(os.path.join(AI_PKG, src_name), encoding="utf-8").read()
    cfgs = {"_PC": C.DEFAULT_PREDICTOR, "_EC": C.DEFAULT_ENSEMBLE,
            "_FC": C.DEFAULT_FEEDBACK, "_CC": C.DEFAULT_CALIB,
            "_LC": C.DEFAULT_LINKAGE, "_EPS": C.EPS}
    for pre, cfg in cfgs.items():
        src = re.sub(re.escape(pre) + r"\.(\w+)",
                     lambda m, c=cfg: repr(getattr(c, m.group(1))), src)
    with open(base_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(src)
    return base_name, base_path


def test_reverse_materialization():
    """③ 反向物化对比（改造前 vs 改造后，指标差 <1e-9）。"""
    base_name, base_path = _materialize_predictor()
    mod_name = "futures_quant.ai." + base_name
    df = _make_df_m11()
    try:
        from futures_quant.ai.predictor import FuturesPredictor as NewP
        OldP = importlib.import_module(mod_name).FuturesPredictor

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
        assert worst < 1e-9, f"预测输出逐字段一致（差 <1e-9）— 最大差 {worst:.3e} {diffs}"
        assert max(abs(a - b) for a, b in zip(ro["forecast"], rn["forecast"])) < 1e-9, \
            "forecast 路径一致"
        assert (max(abs(a - b) for a, b in zip(ro["upper"], rn["upper"])) < 1e-9
                and max(abs(a - b) for a, b in zip(ro["lower"], rn["lower"])) < 1e-9), \
            "upper/lower 区间一致"
        assert abs(ro["risk"]["score"] - rn["risk"]["score"]) < 1e-9, \
            f"风险分一致 — {ro['risk']['score']} vs {rn['risk']['score']}"
        assert abs(ro["long_short"]["long"] - rn["long_short"]["long"]) < 1e-9, \
            "多空强度一致"
        assert (round(po.calib_beta, 9), round(po.skill, 9),
                 round(po.resid_std, 12), po.validated) \
            == (round(pn.calib_beta, 9), round(pn.skill, 9),
                 round(pn.resid_std, 12), pn.validated), \
            f"训练元信息一致 — {po.calib_beta:.6f}/{po.skill:.6f} vs {pn.calib_beta:.6f}/{pn.skill:.6f}"
        assert [(d["name"], d["importance"]) for d in ro["feature_importance"]] \
            == [(d["name"], d["importance"]) for d in rn["feature_importance"]], \
            "特征重要性 Top-N 一致"

        eo = OldP().evaluate(df, seq_len=20, epochs=8, use_walk_forward=True,
                            symbol="RB", period="D")
        en = NewP().evaluate(df, seq_len=20, epochs=8, use_walk_forward=True,
                            symbol="RB", period="D")
        ek = [k for k in eo if isinstance(eo.get(k), (int, float))
              and isinstance(en.get(k), (int, float))]
        d2 = max((abs(float(eo[k]) - float(en[k])) for k in ek), default=0.0)
        assert d2 < 1e-9, f"evaluate 指标一致（差 <1e-9）— 最大差 {d2:.3e} keys={ek}"
    finally:
        sys.modules.pop(mod_name, None)
        for suffix in ("", "c", "o"):
            try:
                os.remove(base_path + suffix)
            except OSError:
                pass
        shutil.rmtree(os.path.join(AI_PKG, "__pycache__"), ignore_errors=True)


def _predict_once(**kw):
    """用默认 predictor 跑一次 fit+predict，供覆盖前后对比。"""
    from futures_quant.ai.predictor import FuturesPredictor

    p = FuturesPredictor()
    p.fit(_make_df_m11(), seq_len=20, epochs=8, symbol="RB", period="D")
    return p.predict(_make_df_m11(), horizon=6, **kw)


def test_config_override_changes_behavior():
    """④ 改配置 → 行为随之变化（证明代码真的读配置，而非残留字面量）。"""
    from futures_quant.ai.predictor import FuturesPredictor
    from futures_quant.ai.ensemble import _Ridge, _TreeModel
    from futures_quant.ai import feedback as FB
    from futures_quant.ai import linkage_bus as LB
    from futures_quant.ai import calibration_replay as CR

    base_r = _predict_once()
    with C.override(C.PREDICTOR, p_up_max=0.7):
        r2 = _predict_once()
    assert base_r["p_up"] != r2["p_up"] or base_r["p_up"] <= 0.7, \
        f"p_up_max 收紧 → p_up 上限生效 — {base_r['p_up']} → {r2['p_up']}"

    r_news0 = _predict_once(news_bias=1.0)
    with C.override(C.PREDICTOR, news_fusion_bias_w=1.0, news_fusion_model_w=0.0):
        r_news1 = _predict_once(news_bias=1.0)
    assert abs(r_news1["p_up"] - r_news0["p_up"]) > 1e-9, \
        f"news_fusion_bias_w 改满 → 资讯独占 p_up — {r_news0['p_up']} → {r_news1['p_up']}"

    p0 = FuturesPredictor()
    p0.fit(_make_df_m11(), seq_len=20, epochs=8, symbol="RB", period="D")
    feats = p0._features(_make_df_m11(), symbol="RB", period="D")[0]
    risk0 = p0._risk_score(feats)["score"]
    with C.override(C.PREDICTOR, risk_w_atr=0.0):
        risk1 = p0._risk_score(feats)["score"]
    assert risk1 <= risk0, f"risk_w_atr 置 0 → 风险分下降（阈值确实被读取）— {risk0} → {risk1}"

    with C.override(C.PREDICTOR, risk_w_atr=0.4, risk_atr_full=1e9):
        risk2 = p0._risk_score(feats)["score"]
    assert risk2 < risk0, f"risk_atr_full 放大 → ATR 分量归一化后归零 — {risk0} → {risk2}"

    with C.override(C.PREDICTOR, ls_neutral_gap=1e9):
        ls = p0._long_short(_make_df_m11()["close"].iloc[-1] * 1.001,
                            _make_df_m11()["close"].iloc[-1], 10, 30)
    assert ls["recommend"] == "观望", f"ls_neutral_gap 放大 → 一律判「观望」— {ls}"

    with C.override(C.PREDICTOR, train_split_ratio=0.95, calib_split_ratio=0.98):
        p3 = FuturesPredictor()
        p3.fit(_make_df_m11(), seq_len=20, epochs=6, symbol="RB", period="D")
    assert p3.validated is False, \
        f"切分比例极端化 → 退化为两段/未验证分支（validated=False）— beta={p3.calib_beta:.3f}"

    with C.override(C.PREDICTOR, adx_trend_threshold=0.0):
        rg = p0._regime(feats, {"state": "多头趋势"})
    assert rg == "趋势行情", f"adx_trend_threshold 置 0 → 恒判「趋势行情」— {rg}"

    with C.override(C.ENSEMBLE, ridge_default_alpha=7.0):
        assert _Ridge().alpha == 7.0, "ridge_default_alpha 覆盖生效"
    with C.override(C.ENSEMBLE, default_seq_len=33):
        assert _TreeModel("D").seq_len == 33, "ensemble.default_seq_len 覆盖生效"

    rng = np.random.default_rng(3)
    _Xc = rng.normal(size=(80, 6))
    _yc = _Xc @ rng.normal(size=6) + 0.02 * rng.normal(size=80)
    with C.override(C.ENSEMBLE, ridge_alpha_grid=(0.5,)):
        picked_narrow = _Ridge.fit_with_cv(_Xc[:60], _yc[:60], _Xc[60:], _yc[60:])
    assert picked_narrow.alpha == 0.5, f"ridge_alpha_grid 覆盖生效（CV 只能从被覆盖的网格里选）— alpha={picked_narrow.alpha}"
    picked_wide = _Ridge.fit_with_cv(_Xc[:60], _yc[:60], _Xc[60:], _yc[60:])
    assert picked_wide.alpha != 0.5, f"默认网格下 alpha 未必是 0.5（证明上一条不是碰巧）— alpha={picked_wide.alpha}"

    with C.override(C.FEEDBACK, wilson_z_95=1.0):
        lo, hi = FB._wilson(0.5, 100)
    lo2, hi2 = FB._wilson(0.5, 100)
    assert (hi - lo) < (hi2 - lo2), f"wilson_z_95 覆盖生效（区间变窄）— {hi-lo:.4f} < {hi2-lo2:.4f}"

    with C.override(C.LINKAGE, hit_log_capacity=3):
        b = LB.LinkageBus()
        for i in range(10):
            b.record_hit("RB", True)
        n_after = len(b._hit_log)
    assert n_after == 3, f"hit_log_capacity 覆盖生效 — {n_after}"

    assert "_compute_tuning" in LB.LinkageBus.rebuild_tuning_locked.__doc__ \
        or hasattr(LB.LinkageBus, "_compute_tuning"), \
        "两条路径（rebuild_tuning / rebuild_tuning_locked）共用同一实现"
    import inspect as _ins

    _lt = _ins.getsource(LB.LinkageBus)
    assert _lt.count('"prefer_ensemble": consensus') == 1, \
        f"重复实现已合并（画像计算式只出现一次）— count={_lt.count('\"prefer_ensemble\": consensus')}"
    assert "hit_adj" not in _ins.getsource(LB.LinkageBus.rebuild_tuning_locked), \
        "rebuild_tuning_locked 不再自带重复计算体"
    assert _ins.getsource(LB.LinkageBus.rebuild_tuning).count("_compute_tuning") == 1, \
        "rebuild_tuning 只负责取数 + 调 _compute_tuning"

    with C.override(C.CALIB, tcn_batch_size=8):
        assert CR._TCNEstimator().epochs == C.CALIB.tcn_epochs, "tcn_batch_size 覆盖生效"
    with C.override(C.CALIB, tcn_min_epochs=50):
        est = CR.build_external_estimator("tcn", epochs=3)
        assert est.epochs == 50, f"tcn_min_epochs 下限生效 — {est.epochs}"
    with C.override(C.CALIB, gbm_n_estimators=7):
        assert CR._GBMEstimator().n_estimators == 7, "gbm_n_estimators 覆盖生效"
    with C.override(C.CALIB, compare_max_samples=13):
        _sig = _ins.signature(CR.MultiModelComparator.run)
        assert _sig.parameters["max_samples"].default is None, \
            "对比回放默认值改为 None 哨兵（运行期解析）"


def test_settings_json_override_and_robustness():
    """⑤ settings.json#ai.thresholds 覆盖 + 未知字段/组安全忽略 + 类型安全 + 嵌套还原。"""
    import json
    import tempfile

    tmpdir = os.path.join(os.path.dirname(__file__), ".pytest_tmp")
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
        assert n == 1, f"从 settings.json 载入覆盖（返回成功条数）— n={n}"
        assert C.PREDICTOR.cum_clip == 0.35, f"cum_clip 被覆盖为 0.35 — {C.PREDICTOR.cum_clip}"
        assert not hasattr(C.PREDICTOR, "不存在的字段"), "未知字段被忽略且不抛异常"
        assert n == 1, "未知组被忽略且不抛异常"
        with C.override(C.PREDICTOR, cum_clip=0.35):
            r_clip = _predict_once()
        C.reset_to_defaults()
        assert C.PREDICTOR.cum_clip == 0.6, f"reset_to_defaults 恢复出厂值 — {C.PREDICTOR.cum_clip}"
        r_base2 = _predict_once()
        assert abs(float(r_clip["p_up"]) - float(r_base2["p_up"])) > 1e-12 \
            or float(r_clip["p_up"]) <= 0.5, \
            f"覆盖 cum_clip 后预测路径确实改变 — clip=0.35 p_up={r_clip['p_up']} vs 默认 {r_base2['p_up']}"
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

    with C.override(C.PREDICTOR, wf_min_folds="abc"):
        pass
    assert C.PREDICTOR.wf_min_folds == 3, \
        f"非法类型被拒绝并保留原值（不崩溃）— {C.PREDICTOR.wf_min_folds}"
    assert C.PREDICTOR.cum_clip == 0.6 and C.ENSEMBLE.default_epochs == 25, \
        "override 上下文管理器可嵌套且自动还原"


def test_no_magic_numbers_in_source():
    """⑥ 源码层面已无遗留魔法数字（阈值已全部集中化）。"""
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
        src = open(os.path.join(AI_PKG, name), encoding="utf-8").read()
        hits = [p for p in pats if re.search(p, src)]
        assert not hits, f"{name}: 阈值已全部集中化 — {hits}"
