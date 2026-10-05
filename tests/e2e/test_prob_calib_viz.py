"""概率校准可视化回归测试（offscreen，不显示窗口）。

验证「🎯 概率校准」页把 ①校准可靠度图 ②预测价格概率带 正确画进 GUI：
  1. 预测页构造后新增第 3 个 Tab，且 reliability_chart / prob_band 组件就位；
  2. 注入足量已结算样本后，reliability_calibration 产出的 bins 能灌进
     ReliabilityChart（_bins 非空、本次预测落点 _mark 已设），且 paint 不崩；
  3. 预测结果（forecast/upper/lower）能灌进 PriceChart 形成 中枢线 + ±1σ 带
     （_series / _bands 均非空），paint 不崩；
  4. 样本不足（仅 5 条）时，图表显示「样本不足」提示且 paint 仍不崩；
  5. 深/浅主题切换均不崩。

不依赖真实行情网络、不触碰回测引擎；合成数据 + 临时库。
"""
from __future__ import annotations

import os
import sys
import tempfile
import math
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPaintEvent

from futures_quant.ai import feedback as fb


def _tmp_store(tag: str):
    p = os.path.join(tempfile.gettempdir(), f"qv_probcalib_{tag}_{os.getpid()}.db")
    return p


def _inject(store, n: int) -> None:
    """过度自信模式：真实命中率 = 0.5 + (p-0.5)*0.4 < p。"""
    random.seed(11)
    for _ in range(n):
        p = round(random.uniform(0.05, 0.95), 4)
        rate = max(0.02, min(0.98, 0.5 + (p - 0.5) * 0.4))
        hit = 1 if random.random() < rate else 0
        rg = random.choice(["趋势行情", "震荡行情"])
        store.save_prediction({
            "ts": "2026-01-01", "symbol": "rb.SHFE", "period": "D", "horizon": 10,
            "last_close": 3500.0, "expected_return_pct": (p - 0.5) * 10,
            "p_up": p, "p_down": 1 - p, "risk_score": 40, "risk_label": "中",
            "model": "ensemble", "regime": rg,
            "verdict": "看多" if p >= 0.5 else "看空",
            "score": hit, "forecast": "", "confidence": p,
            "status": "closed", "config": "enhanced",
        })


def _make_res() -> dict:
    last, horizon = 3500.0, 12
    fc, up, lo = [last], [last], [last]
    for h in range(1, horizon + 1):
        cum = 0.005 * h
        price = last * math.exp(cum)
        sigma = 0.01 * math.sqrt(h)
        fc.append(price)
        up.append(last * math.exp(cum + sigma))
        lo.append(last * math.exp(cum - sigma))
    return {"forecast": fc, "upper": up, "lower": lo,
            "p_up": 0.8, "regime": "趋势行情", "horizon": horizon}


def main() -> int:
    app = QApplication(sys.argv)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.predict_ops_page import PredictOpsPage

    mdm = MarketDataManager(source="synthetic")
    db_path = _tmp_store("main")
    store = AnalysisStore(path=db_path)
    _inject(store, 500)

    # 1) 构造预测页 + 校验新 Tab 与组件
    page = PredictOpsPage(mdm, store, config=None, session=None)
    # left_tab 是 QTabWidget，取它的 tab 数
    from PyQt6.QtWidgets import QTabWidget
    tab = page.findChild(QTabWidget)
    assert tab is not None, "预测页缺少 QTabWidget"
    assert tab.count() == 3, f"预期 3 个 Tab（含概率校准），实际 {tab.count()}"
    assert page.reliability_chart is not None, "缺少 reliability_chart"
    assert page.prob_band is not None, "缺少 prob_band"
    print("PASS: 预测页含「🎯 概率校准」Tab 与两图表组件")

    # 1.0) GUI 打磨组件就位：校准速览卡片 / 空状态提示 / 回放可配置控件
    for k in ("n", "err", "grade"):
        assert k in page.calib_stats, f"缺少校准速览卡片 '{k}'"
    assert page.calib_hint is not None, "缺少校准空状态提示"
    assert page.replay_hor is not None and page.replay_cur is not None, \
        "缺少回放步长/范围控件"
    # 右侧区块标题已升级为 SectionHeader（与全应用一致）
    from futures_quant.ui.widgets import SectionHeader
    secs = page.findChildren(SectionHeader)
    assert len(secs) >= 3, f"预期 ≥3 个 SectionHeader（选品/板块/解读），实际 {len(secs)}"
    print(f"PASS: GUI 打磨组件就位（{len(secs)} 个 SectionHeader + 校准速览 + 回放控件）")

    # 1.1) 历史回放校准接线：按钮存在 + _refresh_reliability 同步刷新不崩
    assert hasattr(page, "replay_btn") and page.replay_btn is not None, "缺少回放按钮"
    assert hasattr(page, "_refresh_reliability"), "缺少 _refresh_reliability"
    try:
        page._refresh_reliability()  # 同步刷新（无训练），不应抛异常
    except Exception as e:
        raise AssertionError(f"_refresh_reliability 崩溃: {e}")
    print("PASS: 历史回放校准按钮与 _refresh_reliability 接线正常")

    # 2) 真实校准 bins 灌入可靠度图
    _, calib_info = fb.reliability_calibration(store, regime=None, min_samples=20)
    res = _make_res()
    conf = 0.62
    page._update_calibration_tab(res, conf, calib_info)
    bins = page.reliability_chart._bins
    assert len(bins) == 10, f"校准分箱应为 10 个，实际 {len(bins)}"
    # 2.0) 区间置信带：bins 为 5 元组，且含 Wilson 区间（lo/hi 非空）
    assert all(len(b) == 5 for b in bins), "分箱应为 5 元组 (center,smoothed,n,lo,hi)"
    with_band = [b for b in bins if b[3] is not None and b[4] is not None]
    assert len(with_band) >= 2, f"应至少 2 个分箱含 Wilson 区间，实际 {len(with_band)}"
    assert page.reliability_chart._mark is not None, "本次预测落点未设置"
    # 落点应带校准区间（4 元组：p_up, conf, lo, hi）
    assert len(page.reliability_chart._mark) == 4, \
        f"落点应带校准区间(4元组)，实际 {page.reliability_chart._mark}"
    print(f"PASS: 可靠度图接收 {len(bins)} 个 5 元组分箱（含 {len(with_band)} 个 Wilson 区间），"
          f"落点={page.reliability_chart._mark}")

    # 2.1) 校准速览卡片在足量样本下被正确填充
    assert page.calib_stats["n"]._val.text() == "500", \
        f"校准样本数应显示 500，实际 {page.calib_stats['n']._val.text()}"
    assert page.calib_stats["err"]._val.text() != "--", "平均偏差未计算"
    assert page.calib_stats["grade"]._val.text() not in ("", "--", "样本不足"), \
        f"校准评级未设置: {page.calib_stats['grade']._val.text()}"
    assert page.calib_stats["band"]._val.text() != "--", "校准区间±未计算"
    print(f"PASS: 校准速览卡片=样本{page.calib_stats['n']._val.text()}/"
          f"偏差{page.calib_stats['err']._val.text()}/"
          f"评级{page.calib_stats['grade']._val.text()}/"
          f"区间{page.calib_stats['band']._val.text()}")

    # 3) 预测概率带灌入 PriceChart
    assert len(page.prob_band._series) >= 1, "概率带缺少中枢序列"
    assert len(page.prob_band._bands) >= 1, "概率带缺少 ±1σ 置信带"
    print(f"PASS: 概率带含中枢线 + {len(page.prob_band._bands)} 条置信带")

    # 4) 直接驱动 paint（offscreen 安全写法），两种主题均不崩
    for theme in ("dark", "light"):
        page.set_theme(theme)
        rc = page.reliability_chart
        pb = page.prob_band
        rc.paintEvent(QPaintEvent(rc.rect()))
        pb.paintEvent(QPaintEvent(pb.rect()))
    print("PASS: 深/浅主题下两图表 paintEvent 均不崩溃")

    # 5) 样本不足路径：空 bins + 落点，paint 不崩
    page.reliability_chart.set_data([], status="insufficient", coverage=5,
                                    mark=(0.7, 0.7))
    page.reliability_chart.paintEvent(
        QPaintEvent(page.reliability_chart.rect()))
    print("PASS: 样本不足时可靠度图 paint 不崩（显示提示）")

    # 5.1) 样本不足时校准速览卡片进入「样本不足」态（offscreen 下 isVisible
    #      不可靠，仅校验文本与 setVisible 调用不抛异常）
    page._update_calib_stats([], "insufficient", 5)
    assert page.calib_stats["grade"]._val.text() == "样本不足", \
        f"不足样本应显示「样本不足」，实际 {page.calib_stats['grade']._val.text()}"
    assert page.calib_stats["err"]._val.text() == "--", "不足样本偏差应为 --"
    print("PASS: 样本不足时校准速览=「样本不足」且引导提示就绪")

    # 清理
    try:
        page.close()
    except Exception:
        pass
    try:
        store.close()
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + s)
            except OSError:
                pass
    except Exception:
        pass

    print("=" * 60)
    print("概率校准可视化：全部断言通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
