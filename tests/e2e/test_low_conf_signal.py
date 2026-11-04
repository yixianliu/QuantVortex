"""实时研判降级信号回归测试（offscreen，不显示窗口）。

验证 ⑬「校准区间 → 实时研判降级」闭环：
  1. _calib_conf_flag 决策函数：窄区间→可信(False) / 宽区间→低置信(True) /
     无 bins(None)→不误报(False)，三态判定正确且确定性；
  2. 研判徽章渲染 _render_verdict_badge：low_conf=False 维持原 verdict 文本，
     low_conf=True 追加「⚠低置信」并转琥珀色，不崩溃；
  3. 解读文本 _detail_html 在 calib_band 下渲染校准区间说明
     （低置信→区间警示 / 窄区间→「校准较可信」）。

不依赖真实行情网络、不触碰回测引擎；合成数据 + 临时库。
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from PyQt6.QtWidgets import QApplication


def _tmp_store(tag: str):
    return os.path.join(tempfile.gettempdir(), f"qv_lowconf_{tag}_{os.getpid()}.db")


def _centers():
    return [round(i / 10.0 + 0.05, 2) for i in range(10)]


def _make_bins(width: float, n_per: int):
    """构造均匀 bins：每个分箱经验命中率=中心、样本=n_per、Wilson 区间 ±width。"""
    out = []
    for c in _centers():
        lo = max(0.0, round(c - width, 3))
        hi = min(1.0, round(c + width, 3))
        # 严格按给定半宽重建（避免 round 截断掩盖阈值判定）
        width_lo = max(0.0, round(c - width, 3))
        width_hi = min(1.0, round(c + width, 3))
        out.append((c, round(c, 3), n_per, width_lo, width_hi))
    return out


def _full_res():
    return {
        "p_up": 0.8, "p_down": 0.2, "last_close": 3500.0,
        "forecast": [3500.0, 3600.0], "expected_return_pct": 2.8,
        "horizon": 12, "risk": {"score": 40, "label": "中"},
        "resonance": {"verdict": "看多", "score": 30},
        "regime": "趋势行情", "model": "ensemble",
        "news_bias": 0.0, "symbol": "rb.SHFE", "period": "D",
    }


def main() -> int:
    app = QApplication(sys.argv)
    from futures_quant.ui.predict_ops_page import PredictOpsPage

    # ------------------------------------------------------------------
    # 1) 决策函数（静态、确定性）
    # ------------------------------------------------------------------
    narrow_info = {"bins": _make_bins(0.03, 200), "status": "ok", "coverage": 2000}
    wide_info = {"bins": _make_bins(0.40, 5), "status": "ok", "coverage": 50}

    lc_n, *_ = PredictOpsPage._calib_conf_flag(narrow_info, 0.5)
    assert lc_n is False, f"窄区间(±0.03)应判为可信，实际 low_conf={lc_n}"
    lc_w, *_ = PredictOpsPage._calib_conf_flag(wide_info, 0.5)
    assert lc_w is True, f"宽区间(±0.40)应判为低置信，实际 low_conf={lc_w}"
    # 落点落在插值带内（非分箱中心）也应正确判定
    lc_w2, *_ = PredictOpsPage._calib_conf_flag(wide_info, 0.73)
    assert lc_w2 is True, f"非中心落点(0.73)宽区间仍应判低置信，实际 {lc_w2}"
    # 无 bins / None → 不误报（避免空样本误触降级）
    lc_none, *_ = PredictOpsPage._calib_conf_flag(None, 0.8)
    assert lc_none is False, "无校准信息时不应判低置信"
    lc_empty, *_ = PredictOpsPage._calib_conf_flag({"bins": [], "status": "insufficient"}, 0.8)
    assert lc_empty is False, "空 bins 不应判低置信"
    print("PASS: _calib_conf_flag 窄/宽/插值/无bins 四态判定正确")

    # 返回值结构：(low_conf, lo, hi, width) 且宽区间 width 与构造一致
    _, lo, hi, w = PredictOpsPage._calib_conf_flag(wide_info, 0.5)
    assert lo is not None and hi is not None and w is not None, "应返回有效区间"
    assert abs(w - 0.80) < 0.02, f"宽区间宽度应≈0.80，实际 {w}"
    print(f"PASS: 区间返回值结构正确（lo={lo}, hi={hi}, width={w:.3f}）")

    # ------------------------------------------------------------------
    # 2) 研判徽章降级渲染（需真实页面实例，verdict_badge 在 _build 中创建）
    # ------------------------------------------------------------------
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path=_tmp_store("page"))
    page = PredictOpsPage(mdm, store, config=None, session=None)

    page._render_verdict_badge({"verdict": "看多", "score": 40}, low_conf=False)
    assert page.verdict_badge.text() == "看多", \
        f"正常态应维持『看多』，实际 {page.verdict_badge.text()!r}"
    page._render_verdict_badge({"verdict": "看多", "score": 40}, low_conf=True)
    assert "⚠低置信" in page.verdict_badge.text(), \
        f"低置信应含『⚠低置信』，实际 {page.verdict_badge.text()!r}"
    # 信号不明 + 低置信 组合
    page._render_verdict_badge({"verdict": "信号不明", "score": 0}, low_conf=True)
    assert "⚠低置信" in page.verdict_badge.text(), \
        f"信号不明+低置信应含『⚠低置信』，实际 {page.verdict_badge.text()!r}"
    print(f"PASS: 研判徽章降级渲染：正常『看多』/ 降级『{page.verdict_badge.text()}』")

    # ------------------------------------------------------------------
    # 3) 解读文本带校准区间说明（两态）
    # ------------------------------------------------------------------
    low_band = (0.60, 0.95, 0.35, True)
    ok_band = (0.60, 0.95, 0.06, False)
    res = _full_res()
    html_low = PredictOpsPage._detail_html(
        res, {}, {"bias": 0.0, "matched": 0}, 0.7, {}, "RB", "金属",
        ind_info={"verdict": "看多", "score": 30, "state": "上涨"},
        settle={}, calib_band=low_band)
    assert "⚠" in html_low and "校准区间" in html_low, \
        "低置信解读应含区间警示"
    assert "研判可信度下降" in html_low, "低置信解读应提示可信度下降"
    # 低置信时，激进「可以入手（偏多）」结论应被软降级为「谨慎观望（置信偏低）」
    assert "谨慎观望（置信偏低）" in html_low, \
        "低置信应把激进『可以入手』软降级为『谨慎观望（置信偏低）』"
    html_ok = PredictOpsPage._detail_html(
        res, {}, {"bias": 0.0, "matched": 0}, 0.7, {}, "RB", "金属",
        ind_info={"verdict": "看多", "score": 30, "state": "上涨"},
        settle={}, calib_band=ok_band)
    assert "校准较可信" in html_ok, "窄区间解读应标『校准较可信』"
    assert "可以入手（偏多）" in html_ok, \
        "窄区间（可信）应维持原激进结论『可以入手（偏多）』"
    # 不传 calib_band 时不崩溃、不出现区间说明
    html_none = PredictOpsPage._detail_html(
        res, {}, {"bias": 0.0, "matched": 0}, 0.7, {}, "RB", "金属",
        ind_info={"verdict": "看多", "score": 30, "state": "上涨"},
        settle={})
    assert "校准较可信" not in html_none and "研判可信度下降" not in html_none, \
        "无 calib_band 时不应出现区间说明"
    print("PASS: 解读文本带校准区间说明（低置信/可信/无band 三态）")

    # ------------------------------------------------------------------
    # 4) 结论软降级（两个 helper 确定性单测）
    # ------------------------------------------------------------------
    # _soft_degrade_enter：激进「可以入手」+ 低置信 → 谨慎观望（置信偏低）
    e1, c1 = PredictOpsPage._soft_degrade_enter("可以入手（偏多）", "#22c55e", True)
    assert e1 == "谨慎观望（置信偏低）" and c1 == "#f59e0b", \
        f"enter 降级失败: {e1}/{c1}"
    # 偏空 / 观望结论不被降级（本身已保守）
    e2, _ = PredictOpsPage._soft_degrade_enter("暂不建议入手（偏空）", "#ef4444", True)
    assert e2.startswith("暂不建议入手"), "偏空结论不应被降级"
    e3, _ = PredictOpsPage._soft_degrade_enter("谨慎观望（方向不明）", "#f59e0b", True)
    assert e3.startswith("谨慎观望（方向不明）"), "观望结论不应被降级"
    # low_conf=False 时零副作用
    e4, c4 = PredictOpsPage._soft_degrade_enter("可以入手（偏多）", "#22c55e", False)
    assert e4 == "可以入手（偏多）" and c4 == "#22c55e", \
        "low_conf=False 应零副作用"
    print("PASS: _soft_degrade_enter 激进入手降级 / 偏空观望不改 / 无副作用")

    # _soft_degrade_recommend：偏多 + 低置信 → 观望（置信偏低），与结论一致
    r1 = PredictOpsPage._soft_degrade_recommend("偏多", True)
    assert r1 == "观望（置信偏低）", f"recommend 降级失败: {r1}"
    r2 = PredictOpsPage._soft_degrade_recommend("偏空", True)
    assert r2 == "偏空", "偏空不应降级"
    r3 = PredictOpsPage._soft_degrade_recommend("观望", True)
    assert r3 == "观望", "观望不应降级"
    r4 = PredictOpsPage._soft_degrade_recommend("偏多", False)
    assert r4 == "偏多", "low_conf=False 应零副作用"
    print("PASS: _soft_degrade_recommend 偏多降级 / 偏空观望不改 / 无副作用")

    # 清理
    try:
        page.close()
    except Exception:
        pass
    try:
        store.close()
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(_tmp_store("page") + s)
            except OSError:
                pass
    except Exception:
        pass

    print("=" * 60)
    print("实时研判降级信号：全部断言通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
