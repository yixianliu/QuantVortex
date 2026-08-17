"""样本外可靠性校准回归测试（锁定 ⑨ 的下一层：概率分箱 → 真实命中率映射）。

验证：
  1. 充足样本下，reliability_calibration 返回区分性、单调的校准函数；
  2. 过度自信被压缩：fn(0.9) < 0.9 且 fn(0.1) > 0.1；
  3. regime 特异性子集可独立校准；
  4. 样本不足时回退 None（调用方沿用扁平命中率，旧行为零回归）。
纯函数 + 临时库，不依赖真实数据、不触碰回测引擎。
"""
from __future__ import annotations

import os
import sys
import tempfile
import random

_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from futures_quant.storage.analysis_store import AnalysisStore
import futures_quant.ai.feedback as fb


def _store(tag):
    p = os.path.join(tempfile.gettempdir(), f"qv_calib_e2e_{tag}.db")
    return AnalysisStore(p), p


def _inject(store, n, regime=None):
    """过度自信：真实命中率 = 0.5 + (p-0.5)*0.4 < p（模型偏高）。"""
    random.seed(7)
    for _ in range(n):
        p = round(random.uniform(0.05, 0.95), 4)
        rate = max(0.02, min(0.98, 0.5 + (p - 0.5) * 0.4))
        hit = 1 if random.random() < rate else 0
        rg = regime or random.choice(["趋势行情", "震荡行情"])
        store.save_prediction({
            "ts": "2026-01-01", "symbol": "rb.SHFE", "period": "D", "horizon": 10,
            "last_close": 3500.0, "expected_return_pct": (p - 0.5) * 10,
            "p_up": p, "p_down": 1 - p, "risk_score": 40, "risk_label": "中",
            "model": "ensemble", "regime": rg,
            "verdict": "看多" if p >= 0.5 else "看空",
            "score": hit, "forecast": "", "confidence": p,
            "status": "closed", "config": "enhanced",
        })


def _close(store, p):
    try:
        store.checkpoint(); store.conn.close()
    except Exception:
        pass
    for s in ("", "-wal", "-shm"):
        try:
            os.remove(p + s)
        except OSError:
            pass


def main() -> None:
    st, path = _store("main")
    _inject(st, 500)
    fn, info = fb.reliability_calibration(st, regime=None, min_samples=20)
    assert fn is not None, "充足样本应返回校准函数"
    lo, mid, hi = fn(0.1), fn(0.5), fn(0.9)
    assert hi < 0.9 - 0.05, f"高概率未被校准压缩: {hi}"
    assert lo > 0.1 + 0.02, f"低概率未被校准抬升: {lo}"
    assert lo <= mid <= hi, "校准映射非单调"
    assert abs(hi - lo) > 0.1, "校准未体现概率区分度（仍扁平）"
    print(f"PASS: 可靠性校准映射（coverage={info['coverage']}, "
          f"fn(0.1)={lo:.3f}, fn(0.5)={mid:.3f}, fn(0.9)={hi:.3f}）")

    fn_r, info_r = fb.reliability_calibration(st, regime="趋势行情", min_samples=20)
    assert fn_r is not None and isinstance(fn_r(0.9), float)
    print(f"PASS: regime 特异性子集校准（trend coverage={info_r['coverage']}）")
    _close(st, path)

    st2, path2 = _store("few")
    _inject(st2, 5)
    fn2, info2 = fb.reliability_calibration(st2, regime=None, min_samples=20)
    assert fn2 is None, "样本不足应回退 None"
    conf = fb.calibrated_confidence(st2, "趋势行情", "enhanced", 0.7)
    assert conf == 0.7, "样本不足时回退应原样返回 base_p_up"
    print(f"PASS: 样本不足正确回退（status={info2['status']}, 扁平命中率={conf}）")
    _close(st2, path2)


if __name__ == "__main__":
    main()
