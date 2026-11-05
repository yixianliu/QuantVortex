# -*- coding: utf-8 -*-
"""第 8 期 GUI 重构与体验升级：单元测试。

覆盖范围：
1) 主题 token / 状态色 / 样式工具解析值（视觉统一的单一事实来源）；
2) 真实主力换月开关：默认关、配置读取、参数透传；
3) 老记录（trace_status=legacy_missing）标识文案；
4) 失败可行动：AI 研判禁用态与提示、回测联动禁用态 tooltip；
5) 主线压缩：跨页上下文 auto_run；
6) 独立回测新增 KPI 与导出入口。

约束：全部使用 MagicMock 数据层，不联网、不读写生产数据库、不触发真实回测。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _proj_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _src(name: str) -> str:
    with open(os.path.join(_proj_root(), "futures_quant", "ui", name),
              "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# 1. 主题 token 与样式工具
# ─────────────────────────────────────────────────────────────

def test_status_tokens_exist_and_map():
    """状态色 token 必须解析到预期色值（成功绿/危险红/信息蓝/警告琥珀）。"""
    from futures_quant.ui.design_system import status_color

    assert status_color("success", "dark") == "#10b981"
    assert status_color("ok", "dark") == "#10b981"
    assert status_color("danger", "dark") == "#ef4444"
    assert status_color("error", "dark") == "#ef4444"
    assert status_color("info", "dark") == "#3b82f6"
    assert status_color("warning", "dark") == "#f59e0b"
    # 弱文本回退到 sub（未知 kind 不抛异常，避免打断 UI）
    assert status_color("unknown-kind", "dark") == "#8b93a7"


def test_status_qss_contains_color_and_size():
    """status_qss 生成的样式串包含主题色与字号，供内联状态文本使用。"""
    from futures_quant.ui.design_system import status_qss

    qss = status_qss("danger", "dark", size="font_body")
    assert "color:#ef4444" in qss
    assert "font-size:12px" in qss
    qss2 = status_qss("weak", "light", extra="padding:2px 4px;")
    assert "padding:2px 4px;" in qss2


def test_font_space_radius_tokens():
    """字号/间距/圆角档位读取稳定（未知档位回退默认值）。"""
    from futures_quant.ui.design_system import font_size, space, radius

    assert font_size("dark", "font_body") == 12
    assert font_size("dark", "font_caption") == 11
    assert font_size("dark", "not-exist") == 12
    assert space("dark", "space_sm") == 8
    assert radius("dark", "radius_md") == 8


def test_main_window_subtitle_matches_real_features():
    """数据管理页副标题必须描述真实功能，不得写“行情下载”（该页无下载功能）。"""
    from futures_quant.ui.main_window import PAGE_SUBTITLES

    subtitle = PAGE_SUBTITLES[6]
    assert "行情下载" not in subtitle, "副标题承诺了不存在的下载功能"
    for word in ("数据导出", "备份恢复", "数据源"):
        assert word in subtitle


def test_migrated_pages_no_inline_header_style():
    """主窗口页头内联样式已下沉 QSS（视觉统一的最小验证点）。"""
    src = _src("main_window.py")
    assert 'setStyleSheet("font-size: 13px; font-weight: 600' not in src
    assert "#breadcrumb" in _src("design_system.py")


# ─────────────────────────────────────────────────────────────
# 2. 真实主力换月开关
# ─────────────────────────────────────────────────────────────

def test_default_dom_roll_is_false_without_config():
    """无配置时真实主力换月必须默认关闭（硬约束）。"""
    from futures_quant.ui.simple_backtest_page import _default_dom_roll

    assert _default_dom_roll(None) is False
    assert _default_dom_roll(SimpleNamespace()) is False


def test_default_dom_roll_reads_config_manager_path():
    """能从 ConfigManager 风格的点分路径读取开关，异常回落 False。"""
    from futures_quant.ui.simple_backtest_page import _default_dom_roll

    class _Cfg:
        def get(self, path, default=None):
            if path == "backtest.enable_dominant_roll":
                return True
            return default

    assert _default_dom_roll(_Cfg()) is True

    class _Broken:
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    assert _default_dom_roll(_Broken()) is False


def test_simple_backtest_dom_roll_and_kpi_defaults(qapp, monkeypatch):
    """独立回测页：开关默认关、10 个 KPI、导出/去预测按钮初始禁用。"""
    from unittest.mock import MagicMock
    from futures_quant.ui.simple_backtest_page import SimpleBacktestPage

    mdm = MagicMock()
    mdm.universe = [("rb", "螺纹钢", 1, "SHFE", 1000, 1.0)]
    mdm.load_bars = MagicMock(return_value=None)
    page = SimpleBacktestPage(mdm, None, None, None)
    try:
        assert page.dom_roll_chk.isChecked() is False
        assert len(page.kpis) == 10
        for label in ("交易笔数", "95%VaR", "最大连亏", "多/空开仓"):
            assert label in page.kpis
        assert page.export_btn.isEnabled() is False
        assert page.goto_predict_btn.isEnabled() is False
        # 默认周期为 1 分钟，换月开关应禁用并说明“仅支持日线”
        assert page.dom_roll_chk.isEnabled() is False
        assert "仅支持日线" in page.dom_roll_chk.toolTip()
        idx_d = page.per_cb.findData("D")
        page.per_cb.setCurrentIndex(idx_d)
        assert "需联网" in page.dom_roll_chk.toolTip()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_simple_backtest_passes_use_dominant_roll(qapp, monkeypatch):
    """勾选开关后必须把 use_dominant_roll 传给 BacktestService。"""
    from unittest.mock import MagicMock
    from futures_quant.ui import simple_backtest_page as SBP

    mdm = MagicMock()
    mdm.universe = [("rb", "螺纹钢", 1, "SHFE", 1000, 1.0)]
    page = SBP.SimpleBacktestPage(mdm, None, None, None)
    captured = {}

    class _Svc:
        def run_backtest(self, sym, start, end, per, warmup=60, strategy=None,
                         use_dominant_roll=False, should_abort=None):
            captured["use_dominant_roll"] = use_dominant_roll
            return {"metrics": {"total_return": 0.1, "win_rate": 0.5},
                    "equity_curve": [], "trades": [],
                    "data_source": "synthetic", "is_synthetic": True,
                    "is_stale": False, "as_of": None, "data_note": ""}

    monkeypatch.setattr(SBP, "request", lambda _k: _Svc())

    def fake_run_worker(fn, on_done, on_err=None, **_kw):
        """同步执行工作函数，避免测试里开线程。"""
        fn(SimpleNamespace(isInterruptionRequested=lambda: False))
        on_done({"metrics": {"total_return": 0.1, "win_rate": 0.5},
                 "equity_curve": [], "trades": [],
                 "data_source": "synthetic", "is_synthetic": True,
                 "is_stale": False, "as_of": None, "data_note": ""})
        return SimpleNamespace()

    page._run_worker = fake_run_worker
    idx_d = page.per_cb.findData("D")
    assert idx_d >= 0
    page.per_cb.setCurrentIndex(idx_d)
    page.dom_roll_chk.setChecked(True)
    try:
        page._run_backtest()
        assert captured.get("use_dominant_roll") is True
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_dom_roll_disabled_on_non_daily(qapp):
    """非日线周期时换月开关必须禁用并说明原因（避免勾了跑不起来）。"""
    from unittest.mock import MagicMock
    from futures_quant.ui.simple_backtest_page import SimpleBacktestPage

    mdm = MagicMock()
    mdm.universe = [("rb", "螺纹钢", 1, "SHFE", 1000, 1.0)]
    page = SimpleBacktestPage(mdm, None, None, None)
    try:
        idx_1m = page.per_cb.findData("1m")
        assert idx_1m >= 0
        page.per_cb.setCurrentIndex(idx_1m)
        assert page.dom_roll_chk.isEnabled() is False
        assert "仅支持日线" in page.dom_roll_chk.toolTip()
        idx_d = page.per_cb.findData("D")
        page.per_cb.setCurrentIndex(idx_d)
        assert page.dom_roll_chk.isEnabled() is True
    finally:
        page.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# 3. 老记录标识
# ─────────────────────────────────────────────────────────────

def test_legacy_history_row_marker():
    """trace_status=legacy_missing 的历史行显示“老记录无指纹”。"""
    from futures_quant.ui.backtest_page import BacktestCenterPage

    rec = {"ts": "2025-01-01T10:00:00", "symbol_name": "螺纹钢",
           "generation": 3, "best_desc": "trend", "total_return": 0.1,
           "sharpe": 1.2, "max_drawdown": 0.05, "win_rate": 0.5,
           "trades": 10, "fitness": 55.0, "total_profitable": 3,
           "trace_status": "legacy_missing"}
    vals = BacktestCenterPage._hist_row_values(SimpleNamespace(), rec)
    assert "老记录无指纹" in vals[2]


def test_new_history_row_has_no_legacy_marker():
    """正常记录不得被误标“无指纹”。"""
    from futures_quant.ui.backtest_page import BacktestCenterPage

    rec = {"ts": "2025-01-01T10:00:00", "symbol_name": "螺纹钢",
           "generation": 3, "best_desc": "trend", "trace_status": "ok"}
    vals = BacktestCenterPage._hist_row_values(SimpleNamespace(), rec)
    assert "老记录无指纹" not in vals[2]


# ─────────────────────────────────────────────────────────────
# 4. 失败可行动
# ─────────────────────────────────────────────────────────────

def _build_predict_page(qapp, monkeypatch):
    """构造预测页并禁用后台刷新，保证断言确定性。"""
    from unittest.mock import MagicMock
    from futures_quant.ui.predict_ops_page import PredictOpsPage

    monkeypatch.setattr(PredictOpsPage, "_base_refresh", lambda *a, **k: None)
    mdm = MagicMock()
    mdm.universe = [("rb", "螺纹钢", 1, "SHFE", 1000, 1.0)]
    page = PredictOpsPage(mdm, MagicMock(), None, None)
    return page


def test_ai_indicator_disabled_before_prediction(qapp, monkeypatch):
    """未预测时 AI 研判按钮必须禁用，并说明先做预测。"""
    page = _build_predict_page(qapp, monkeypatch)
    try:
        assert page.ai_ind_btn.isEnabled() is False
        assert "请先点击「开始预测」" in page.ai_ind_btn.toolTip()
        page._run_ai_indicator()
        assert "请先" in page.status_lbl.text()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_ai_indicator_enabled_after_result(qapp, monkeypatch):
    """拿到本次预测结果后按钮恢复可用，提示词说明依据。"""
    page = _build_predict_page(qapp, monkeypatch)
    try:
        page._last_res = {"symbol": "rb.SHFE", "period": "D"}
        page._set_ai_ind_enabled(True)
        assert page.ai_ind_btn.isEnabled() is True
        assert "本次预测结果" in page.ai_ind_btn.toolTip()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_ai_indicator_reset_on_selection_change(qapp, monkeypatch):
    """切换品种会作废旧预测上下文，AI 按钮重新禁用。"""
    page = _build_predict_page(qapp, monkeypatch)
    try:
        page._last_res = {"symbol": "rb.SHFE", "period": "D"}
        page._set_ai_ind_enabled(True)
        page._on_sel()
        assert page._last_res is None
        assert page.ai_ind_btn.isEnabled() is False
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_backtest_link_disabled_has_actionable_tooltip(qapp, monkeypatch):
    """无回测沉淀时联动按钮禁用，tooltip 必须给出下一步（不再只是灰按钮）。"""
    page = _build_predict_page(qapp, monkeypatch)
    try:
        assert page.backtest_link_btn.isEnabled() is False
        tip = page.backtest_link_btn.toolTip()
        assert "暂无回测沉淀" in tip
        assert "回测中心" in tip
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_market_double_click_context_is_handled():
    """行情全景双击必须带正确页面 key 发出跨页上下文（主线入口不缺失）。"""
    src = _src("market_overview_page.py")
    assert 'navigate_requested.emit("predict_ops"' in src
    assert '"symbol": code' in src


# ─────────────────────────────────────────────────────────────
# 5. 主线压缩：auto_run
# ─────────────────────────────────────────────────────────────

def test_apply_context_auto_run_triggers_prediction(qapp, monkeypatch):
    """跨页上下文带 auto_run 时应自动开始预测，省去再点一次按钮。"""
    page = _build_predict_page(qapp, monkeypatch)
    calls = []
    monkeypatch.setattr(page, "_run_prediction", lambda: calls.append(1))
    try:
        page.apply_context({"symbol": "rb.SHFE", "period": "D", "auto_run": True})
        qapp.processEvents()
        assert calls, "auto_run 未触发预测"
        assert "正在自动预测" in page.status_lbl.text()
    finally:
        page.deleteLater()
        qapp.processEvents()


# ─────────────────────────────────────────────────────────────
# 6. 第 3 期能力接线：运行历史 / 复跑校验 / 参数网格
# ─────────────────────────────────────────────────────────────

def test_registry_key_and_grid_preset():
    """只有已注册的单腿策略支持参数网格；套利策略显式不支持。"""
    from futures_quant.ui.backtest_runs_dialog import grid_preset, registry_key

    assert registry_key("TrendFollowing") == "trend_following"
    assert registry_key("MeanReversion") == "mean_reversion"
    assert registry_key("CalendarSpread") is None
    assert registry_key(None) is None
    assert "fast=" in grid_preset("TrendFollowing")
    assert grid_preset("CalendarSpread") == ""


def test_parse_grid_text_valid_and_errors():
    """网格文本解析：支持 =/: 两种写法、跳过注释；错误必须带行号。"""
    from futures_quant.ui.backtest_runs_dialog import parse_grid_text

    grid = parse_grid_text("# 注释\nfast=5,10\nslow: 30, 60\nnum_std=1.5,2.0\n")
    assert grid["fast"] == [5, 10]
    assert grid["slow"] == [30, 60]
    assert grid["num_std"] == [1.5, 2.0]

    with pytest.raises(ValueError, match="第 1 行格式错误"):
        parse_grid_text("fast 5,10")
    with pytest.raises(ValueError, match="重复"):
        parse_grid_text("fast=5\nfast=10")
    with pytest.raises(ValueError, match="为空"):
        parse_grid_text("  \n# 只有注释\n")


def test_run_status_text_stale_and_legacy():
    """状态列：is_stale 优先；缺数据指纹标老记录；两者都正常才叫追溯完整。"""
    from futures_quant.ui.backtest_runs_dialog import run_status_text

    assert run_status_text({"is_stale": 1, "data_fingerprint": "fp"}) == \
        "参数口径已变更，仅审计用途"
    assert run_status_text({"is_stale": 0, "data_fingerprint": ""}) == \
        "老记录无指纹（无法追溯数据来源/种子）"
    assert run_status_text({"is_stale": 0, "data_fingerprint": "fp"}) == "追溯完整"


def test_replay_conclusion_never_passes_stale_record():
    """stale 记录即使 7 项一致也只能是“仅审计”，不能显示为通过。"""
    from futures_quant.ui.backtest_runs_dialog import replay_conclusion

    all_ok = {"ok": True, "checks": [
        {"name": n, "ok": True} for n in
        ("params_hash", "data_fingerprint", "run_id", "result_hash",
         "trades_digest", "equity_digest", "metrics")]}
    text, kind = replay_conclusion(all_ok, stale=False)
    assert "通过" in text or "一致" in text
    assert kind == "success"

    text2, kind2 = replay_conclusion(all_ok, stale=True)
    assert "仅审计" in text2
    assert "不作为一致性通过" in text2
    assert kind2 == "warning"
    assert kind2 != "success"


def test_replay_conclusion_names_mismatch_items():
    """失败时必须说清“哪一项不一致”，不是一句笼统失败。"""
    from futures_quant.ui.backtest_runs_dialog import replay_conclusion

    report = {"ok": False, "checks": [
        {"name": "params_hash", "ok": True},
        {"name": "data_fingerprint", "ok": False},
        {"name": "metrics", "ok": False},
    ]}
    text, kind = replay_conclusion(report, stale=False)
    assert "数据指纹（行情窗口）" in text
    assert "KPI 全量比对" in text
    assert kind == "danger"


def test_simple_page_exposes_history_replay_and_grid_entries(qapp):
    """独立回测页必须出现运行历史/复跑校验/参数网格三个入口，且初始可用。"""
    from unittest.mock import MagicMock
    from futures_quant.ui.simple_backtest_page import SimpleBacktestPage

    mdm = MagicMock()
    mdm.universe = [("rb", "螺纹钢", 1, "SHFE", 1000, 1.0)]
    page = SimpleBacktestPage(mdm, None, None, None)
    try:
        for name in ("replay_btn", "history_btn", "grid_btn"):
            btn = getattr(page, name)
            assert btn.isEnabled() is True, f"{name} 不应被禁用（至少可打开弹窗）"
            assert btn.toolTip(), f"{name} 必须有说明"
        # 换月开关旁必须有常驻代价说明（不能只靠 tooltip）
        assert "需联网取合约链" in page.dom_roll_cost_lbl.text()
        assert "链不完整直接报错" in page.dom_roll_cost_lbl.text()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_grid_dialog_rejects_unregistered_strategy(qapp):
    """套利策略打开参数网格必须给出可行动文案，而不是空白面板。"""
    from unittest.mock import MagicMock
    from futures_quant.ui import simple_backtest_page as SBP
    from futures_quant.ui.backtest_runs_dialog import GridSweepDialog

    mdm = MagicMock()
    mdm.universe = [("rb", "螺纹钢", 1, "SHFE", 1000, 1.0)]
    page = SBP.SimpleBacktestPage(mdm, None, None, None)
    idx = next(i for i in range(page.strat_cb.count())
               if page.strat_cb.itemData(i) == "CalendarSpread")
    page.strat_cb.setCurrentIndex(idx)
    dlg = GridSweepDialog(page=page, theme="dark")
    try:
        inputs = dlg._validated_inputs()
        assert inputs is None
        assert "未在策略注册表注册" in dlg.status_lbl.text()
        assert "单腿策略" in dlg.status_lbl.text()
    finally:
        dlg.deleteLater()
        page.deleteLater()
        qapp.processEvents()


def test_replay_error_is_actionable(qapp):
    """复跑失败必须写明原因 + 可行动建议，并允许重试。"""
    from types import SimpleNamespace
    from futures_quant.ui.backtest_runs_dialog import ReplayCheckDialog

    page = SimpleNamespace(_run_worker=None)
    dlg = ReplayCheckDialog(page=page, run_id="run-x", rec={"run_id": "run-x"},
                            store=None, theme="dark")
    try:
        dlg._finish_err("数据源不可用")
        assert "复跑失败" in dlg.conclusion.text()
        assert "可行动建议" in dlg.conclusion.text()
        assert dlg.retry_btn.isEnabled() is True
        assert dlg.progress.isVisible() is False
    finally:
        dlg.deleteLater()
        qapp.processEvents()



# ─────────────────────────────────────────────────────────────
# 6. 区间覆盖率口径（D3 复查）
# ─────────────────────────────────────────────────────────────

def test_interval_coverage_sample_short_text_and_real_api():
    """覆盖率展示必须调用真实接口，并在 None 时给出“样本不足（原因）”。"""
    src = _src("predict_ops_page.py")
    assert "evaluate_interval_coverage" in src
    assert "样本不足" in src
    assert "实测覆盖率" in src
    assert "已结算预测" in src
