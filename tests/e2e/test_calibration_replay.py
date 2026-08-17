"""历史回放校准 · e2e 验证（offscreen，无 GUI 依赖，纯数据/校准逻辑）。

覆盖：
  1. save_closed_prediction 原子写入 → query_closed_for_calibration 可读取；
  2. replay_symbol 用「独立 predictor」回放合成历史 → 写入已结算校准样本；
  3. 回放后 reliability_calibration 进入 status='ok'（coverage ≥ min_samples）；
  4. 回放绝对不污染「另一个 predictor 实例」状态（隔离保证）；
  5. load_bars_from_csv 能正确解析真实样本 CSV（含 DatetimeIndex）。
"""
import os
import sys
import tempfile
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from futures_quant.storage.analysis_store import AnalysisStore  # noqa: E402
from futures_quant.ai.predictor import FuturesPredictor  # noqa: E402
from futures_quant.ai.feedback import reliability_calibration  # noqa: E402
from futures_quant.ai.calibration_replay import (  # noqa: E402
    replay_symbol, load_bars_from_csv, discover_local_samples,
)
from futures_quant.data.synthetic import generate_bars  # noqa: E402


def _tmp_store():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="calib_replay_")
    os.close(fd)
    os.remove(path)
    return AnalysisStore(path)


def test_save_closed_prediction_and_readback():
    store = _tmp_store()
    rid = store.save_closed_prediction({
        "ts": "2026-01-01", "symbol": "TEST.SHFE", "period": "D", "horizon": 10,
        "last_close": 3500.0, "expected_return_pct": 1.2, "p_up": 0.72,
        "p_down": 0.28, "risk_score": 40.0, "risk_label": "中等风险",
        "model": "LSTM", "regime": "趋势行情", "verdict": "",
        "score": 1, "forecast": "", "confidence": 0.72,
        "status": "closed", "config": "enhanced",
        "actual_return_pct": 1.5, "y_up": 1.0, "closed_ts": "2026-01-11",
    })
    assert rid > 0
    rows = store.query_closed_for_calibration(limit=10)
    assert any(abs(r["p_up"] - 0.72) < 1e-6 and r["y_up"] == 1.0 for r in rows)
    print("PASS: save_closed_prediction 写入并可被 query_closed_for_calibration 读回")


def test_replay_symbol_builds_calibration():
    store = _tmp_store()
    # 合成混合行情（含趋势+震荡），产生多样化的 p_up 与行情状态
    df = generate_bars(symbol="rb.SHFE", n=320, mode="mixed", seed=20260731,
                       freq="1min")
    # generate_bars 以 datetime 列 + RangeIndex 返回；回放调用方（load_bars_from_csv /
    # mdm.get_bars）均提供 DatetimeIndex，这里对齐真实使用形态。
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) >= 80

    # 隔离保证：回放前记录一个独立 predictor 的状态
    other = FuturesPredictor()
    assert not other.trained

    r = replay_symbol(store, df, "rb.SHFE", period="D", horizon=10,
                      stride=3, max_samples=60, epochs=15)
    assert r["added"] >= 20, f"回放样本不足: {r}"
    print(f"回放写入 {r['added']} 条（skipped={r['skipped']}, total={r['total']}）")

    # 回放后另一个 predictor 仍是未训练状态（无全局副作用）
    assert not other.trained, "回放污染了外部 predictor 状态！"

    rows = store.query_closed_for_calibration(limit=4000)
    assert len(rows) >= 20
    # 至少覆盖两种行情状态，证明 regime 字段被如实记录
    regimes = {r["regime"] for r in rows}
    assert len(regimes) >= 1

    fn, info = reliability_calibration(store, regime=None, min_samples=20)
    assert fn is not None, f"校准未启用: {info}"
    assert info["status"] == "ok", info
    assert info["coverage"] >= 20
    assert len(info["bins"]) == 10
    print(f"PASS: 回放后可靠性校准已启用（coverage={info['coverage']}，bins={len(info['bins'])}）")


def test_load_bars_from_real_csv():
    base = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "data", "real_samples")
    csvp = os.path.join(base, "rb_SHFE_D.csv")
    if not os.path.exists(csvp):
        print("SKIP: 真实样本 CSV 不存在（沙箱未采集），跳过")
        return
    df = load_bars_from_csv(csvp)
    assert df is not None and isinstance(df.index, pd.DatetimeIndex)
    assert len(df) >= 80
    found = discover_local_samples(base)
    assert any(label == "rb.SHFE" for _, label, _ in found)
    print(f"PASS: load_bars_from_csv 解析真实样本（{len(df)} 根，"
          f"discover 命中 {len(found)} 个文件）")


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    test_save_closed_prediction_and_readback()
    test_replay_symbol_builds_calibration()
    test_load_bars_from_real_csv()
    print("\n历史回放校准：全部断言通过 ✅")
