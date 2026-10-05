"""选品排行 AI 方向「置信偏低」标注回归测试（offscreen，不显示窗口）。

验证 ⑮「校准不确定度 → 选品排行 AI 方向标注」闭环：
  1. _calib_low_conf 决策函数：落点 Wilson 区间宽 > 阈值 → 低置信(True) /
     窄区间 → False / 无校准信息(None) → 不误报(False)；
  2. 排行表「AI方向」列：低置信品种追加「·置信偏低」并转琥珀色，
     正常品种维持原方向（偏多/偏空/中性）不动；
  3. 入手详情「③ KP预测信号」：低置信品种标注「置信偏低」+ 可信度警示段落，
     正常品种不出现该标注。

不依赖真实行情网络、不跑回放；手工注入宽/窄校准分箱，确定性。
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
    return os.path.join(tempfile.gettempdir(), f"qv_scr_lowconf_{tag}_{os.getpid()}.db")


def _centers():
    return [round(i / 10.0 + 0.05, 2) for i in range(10)]


def _make_bins(width: float, n_per: int):
    """构造均匀 bins：每个分箱经验命中率=中心、样本=n_per、Wilson 区间 ±width。"""
    out = []
    for c in _centers():
        lo = max(0.0, round(c - width, 3))
        hi = min(1.0, round(c + width, 3))
        out.append((c, round(c, 3), n_per, lo, hi))
    return out


def _wide_info():
    # 高概率档(≈0.9)样本稀疏 → 区间宽(±0.40)，低概率/中概率档窄(±0.03)
    bins = []
    for c in _centers():
        w = 0.40 if c >= 0.85 else 0.03
        lo = max(0.0, round(c - w, 3))
        hi = min(1.0, round(c + w, 3))
        n = 5 if c >= 0.85 else 200
        bins.append((c, round(c, 3), n, lo, hi))
    return {"bins": bins, "status": "ok", "coverage": 2000}


def _narrow_info():
    return {"bins": _make_bins(0.03, 200), "status": "ok", "coverage": 2000}


def _one_result(pu: float, tier: str = "可留意"):
    return {
        "sym": "rb.SHFE", "name": "螺纹钢", "category": "金属",
        "last": 3500.0, "ret_20": 1.2, "ma_gap": 0.5, "bull": True,
        "vol_20": 20.0, "fund": 0.5, "vr": 1.1, "oi": 0.5,
        "score": 60.0, "tier": tier, "pu": pu, "ai_exp": 2.0,
        "ai_conf": 0.7,
        "hist": {"wins": 30, "total": 50, "rate": 0.6, "examples": [],
                 "fac": {}, "fwd": []},
    }


def main() -> int:
    app = QApplication(sys.argv)
    from futures_quant.ui.screening_page import ScreeningPage
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore

    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path=_tmp_store("page"))
    # 阻止 __init__ 的后台筛选计算（纯单元验证，避免重跑 KP预测）
    ScreeningPage._run = lambda self: None
    page = ScreeningPage(mdm, store, config=None, session=None)

    # ------------------------------------------------------------------
    # 1) 决策函数
    # ------------------------------------------------------------------
    page._calib_info = _wide_info()
    # 高概率档(0.9)区间宽 → 低置信
    assert page._calib_low_conf(0.9) is True, "高概率档(0.9)应判低置信"
    # 中概率档(0.5)区间窄 → 不可信度不触发
    assert page._calib_low_conf(0.5) is False, "中概率档(0.5)应判可信"
    # 无校准信息 → 不误报
    page._calib_info = None
    assert page._calib_low_conf(0.9) is False, "无校准信息时不应判低置信"
    page._calib_info = {"bins": [], "status": "insufficient"}
    assert page._calib_low_conf(0.9) is False, "空 bins 不应判低置信"
    print("PASS: _calib_low_conf 宽档/窄档/无信息 三态判定正确")

    # ------------------------------------------------------------------
    # 2) 排行表「AI方向」列标注
    # ------------------------------------------------------------------
    page._calib_info = _wide_info()
    page._results = [_one_result(0.9, "优先入手"), _one_result(0.5, "可留意")]
    page._cats = []
    page._filtered = list(page._results)  # _render_table 遍历 _filtered
    page._render_table()

    item_lo = page.tbl.item(0, 10)  # 高概率(0.9) → 低置信
    item_ok = page.tbl.item(1, 10)  # 中概率(0.5) → 正常
    assert item_lo is not None and "置信偏低" in item_lo.text(), \
        f"低置信品种 AI方向应含『置信偏低』，实际 {item_lo.text()!r}"
    assert item_ok is not None and "置信偏低" not in item_ok.text(), \
        f"正常品种 AI方向不应含『置信偏低』，实际 {item_ok.text()!r}"
    # 颜色为琥珀（低置信）
    lo_color = item_lo.foreground().color().name().lower()
    assert lo_color in ("#f59e0b", "#f59e0b".upper()), \
        f"低置信 AI方向应转琥珀色，实际 {lo_color}"
    print(f"PASS: 排行表 AI方向列：低置信『{item_lo.text()}』/ 正常『{item_ok.text()}』")

    # ------------------------------------------------------------------
    # 3) 入手详情「③ KP预测信号」标注
    # ------------------------------------------------------------------
    html_lo = page._logic_html(_one_result(0.9, "优先入手"))
    assert "置信偏低" in html_lo, "低置信品种详情应标注『置信偏低』"
    assert "历史校准样本稀疏" in html_lo, "低置信品种详情应附可信度警示段落"
    html_ok = page._logic_html(_one_result(0.5, "可留意"))
    assert "置信偏低" not in html_ok, "正常品种详情不应标注『置信偏低』"
    assert "历史校准样本稀疏" not in html_ok, "正常品种详情不应附可信度警示"
    print("PASS: 入手详情 KP预测信号：低置信标注 / 正常不标注")

    # ------------------------------------------------------------------
    # 4) 板块关注方向「置信偏低」标注（⑱）
    # ------------------------------------------------------------------
    # 构造两个板块：金属（avg_pu=0.9 → 低置信）/ 能化（avg_pu=0.5 → 正常）
    page._calib_info = _wide_info()  # 高概率档区间宽 → 0.9 判低置信
    page._results = [
        _one_result(0.9, "优先入手"),  # 金属
        _one_result(0.88, "可留意"),
        _one_result(0.5, "可留意"),    # 能化
    ]
    page._cats = [
        dict(category="金属", avg=65.0, count=2, rec=2, top_name="螺纹钢", top_score=70.0,
             success_rate=0.6, wins=30, total=50, examples=[], avg_pu=0.89),
        dict(category="能化", avg=58.0, count=1, rec=1, top_name="PTA", top_score=58.0,
             success_rate=0.5, wins=20, total=40, examples=[], avg_pu=0.50),
    ]
    page._filtered = list(page._results)
    page._render_cats()

    # 金属板块 avg_pu=0.89，高概率档区间宽(±0.40) → 低置信
    item_metal = page.ctbl.item(0, 5)  # 关注方向列
    assert item_metal is not None and "置信偏低" in item_metal.text(), \
        f"低置信板块应含『置信偏低』，实际 {item_metal.text()!r}"
    # 能化板块 avg_pu=0.50，区间窄 → 不标注
    item_chem = page.ctbl.item(1, 5)
    assert item_chem is not None and "置信偏低" not in item_chem.text(), \
        f"正常板块不应含『置信偏低』，实际 {item_chem.text()!r}"
    print(f"PASS: 板块关注方向：金属『{item_metal.text()}』/ 能化『{item_chem.text()}』")

    # 低置信为空的板块（avg_pu=0.5，宽区间）→ 不误报
    page._calib_info = _wide_info()
    page._cats = [
        dict(category="金融", avg=52.0, count=1, rec=0, top_name="股指", top_score=52.0,
             success_rate=None, wins=0, total=0, examples=[], avg_pu=0.50),
    ]
    page._render_cats()
    item_fin = page.ctbl.item(0, 5)
    assert item_fin is not None and "置信偏低" not in item_fin.text(), \
        f"中概率档不应标注『置信偏低』，实际 {item_fin.text()!r}"
    print(f"PASS: 中概率板块『{item_fin.text()}』不误报")

    # 无校准信息 → 零副作用
    page._calib_info = None
    page._render_cats()
    item_no = page.ctbl.item(0, 5)
    assert item_no is not None and "置信偏低" not in item_no.text(), \
        f"无校准信息不应误报，实际 {item_no.text()!r}"
    print(f"PASS: 无校准信息板块『{item_no.text()}』零副作用")

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
    print("选品排行 AI方向 置信偏低标注：全部断言通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
