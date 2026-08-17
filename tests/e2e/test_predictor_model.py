"""模型层深化回归：特征增维 + 树模型基学习器集成。

锁定：
  * build_features(extended=True) 产出 26 维且无残余 NaN；
  * FuturesPredictor 在 extended+ensemble 模式下集成含 sklearn 树模型成员；
  * 集成权重和为 1、树成员获得有效（>0）权重；
  * predict() 返回有限的价格路径，且 ±1σ 带满足 lower <= forecast <= upper。
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai.features import build_features, EXTENDED_FEATURES
from futures_quant.ai.predictor import FuturesPredictor
from futures_quant.ai.ensemble import MultiPeriodEnsemble


def _load_sample(n=700):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "data", "real_samples", "rb_SHFE_D.csv")
    df = pd.read_csv(base)
    return df.head(n).reset_index(drop=True)


def test_features_extended_dim():
    df = _load_sample()
    ind, F, names = build_features(df, extended=True)
    assert F.shape[1] == len(EXTENDED_FEATURES)
    assert names == EXTENDED_FEATURES
    assert not F.isna().any().any(), "扩展特征不得含残余 NaN"
    for c in ["ret_z", "vol_ratio_lr", "rsi_dev", "macd_dif", "atr_chg", "roll_skew", "gap_open"]:
        assert c in F.columns


def test_ensemble_has_tree_member_and_weights():
    df = _load_sample()
    P = FuturesPredictor()
    info = P.fit(df, seq_len=20, epochs=15, extended_features=True, use_ensemble=True)
    assert info.get("trained") is True
    ens: MultiPeriodEnsemble = P.ensemble
    assert ens is not None and ens.fitted is True
    # 至少含一个树模型成员
    tree_count = sum(1 for m in ens.models if type(m).__name__ == "_TreeModel")
    assert tree_count >= 1, "集成须含 sklearn 树模型基学习器"
    # 权重和=1 且树成员获得有效权重
    assert abs(sum(ens.weights) - 1.0) < 1e-6
    tree_w = [w for m, w in zip(ens.models, ens.weights) if type(m).__name__ == "_TreeModel"]
    assert all(w > 0 for w in tree_w), "树成员权重须 > 0"


def test_predict_curve_finite_and_bounded():
    df = _load_sample()
    P = FuturesPredictor()
    P.fit(df, seq_len=20, epochs=15, extended_features=True, use_ensemble=True)
    r = P.predict(df, horizon=12, news_bias=0.0)
    assert len(r["forecast"]) == 13
    assert np.all(np.isfinite(r["forecast"]))
    assert np.all(np.isfinite(r["upper"])) and np.all(np.isfinite(r["lower"]))
    # ±1σ 带满足 lower <= forecast <= upper（逐点）
    lo, fc, up = np.array(r["lower"]), np.array(r["forecast"]), np.array(r["upper"])
    assert np.all(lo <= fc + 1e-6) and np.all(fc <= up + 1e-6)


if __name__ == "__main__":
    test_features_extended_dim()
    test_ensemble_has_tree_member_and_weights()
    test_predict_curve_finite_and_bounded()
    print("OK: test_predictor_model 全部通过")
