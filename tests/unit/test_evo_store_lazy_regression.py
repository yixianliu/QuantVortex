"""v5.2.4 回归：进化档案（EvolutionStore）「静默失效」根治。

根因（与 v5.2.3 修复的 AnalysisStore 为同一反模式的第二次复发）：
    ``BacktestCenterPage.__init__`` 在**构造期** ``try: EvolutionStore() except:
    self._evo_store = None``，一旦一次创建失败就把 None 钉死、永不重试。
    后果分两级且都不可观测：
      - ``_save_evo_run`` 里 ``if self._evo_store is None: return`` —— 静默 return、
        零日志，进化档案整条落盘能力失效而用户毫不知情；
      - ``_on_archive_selected`` 里 ``self._evo_store.convergence(rid)`` 无判空，
        None 时抛 AttributeError，被外层吞成误导性的「读取进化档案失败」。

修复：``evo_store`` 改 property 惰性解析（对齐 ``BasePage.store``）+ 单例
``get_evolution_store()`` + 失败路径强制记 error 日志。
"""
from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------- 环境准备
from PyQt6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

app = QApplication.instance() or QApplication([])

from futures_quant.storage import evolution_store as evo_mod  # noqa: E402
from futures_quant.storage.evolution_store import (  # noqa: E402
    get_evolution_store,
    reset_evolution_store_for_test,
)
from futures_quant.ui.backtest_page import BacktestCenterPage  # noqa: E402


# ---------------------------------------------------------------- 夹具
def _mock_mdm() -> types.SimpleNamespace:
    """最小 MarketDataManager 替身：只需支撑页面初始化期用到的 universe 索引。"""
    return types.SimpleNamespace(
        universe=[("RB", "SHFE", "rb", "SHFE", 10, 1)],
        get_history=lambda *a, **k: None,
        get_quote=lambda *a, **k: {},
    )


@pytest.fixture(scope="module")
def page():
    """模块级页面夹具：多个用例共享一个页面，避免反复构造_widgets 导致 Qt teardown 崩溃。"""
    reset_evolution_store_for_test()
    p = BacktestCenterPage(_mock_mdm(), store=None, config=None)
    yield p
    reset_evolution_store_for_test()


# -------------------------------------------------- ① EvolutionStore 单例
def test_get_evolution_store_is_singleton():
    """两次无参调用返回同一实例（避免每次构造页面都新建 store 重复 makedirs）。"""
    reset_evolution_store_for_test()
    try:
        a = get_evolution_store()
        b = get_evolution_store()
        assert a is b, "get_evolution_store() 应返回进程内单例"
    finally:
        reset_evolution_store_for_test()


def test_get_evolution_store_explicit_path_not_shared():
    """显式传 path 时不复用单例（临时区 / 测试隔离场景）。"""
    reset_evolution_store_for_test()
    try:
        a = get_evolution_store()
        b = get_evolution_store("/tmp/qv_evo_probe_sub")
        assert a is not b, "显式 path 应绕过单例另建实例"
    finally:
        reset_evolution_store_for_test()


def test_reset_evolution_store_for_test_discards_singleton():
    reset_evolution_store_for_test()
    try:
        a = get_evolution_store()
        reset_evolution_store_for_test()
        b = get_evolution_store()
        assert a is not b, "reset 后应重建"
    finally:
        reset_evolution_store_for_test()


# -------------------------------------------------- ② 页面惰性解析
def test_evo_store_is_lazy_not_solidified_at_construction(page):
    """构造期不固化 None：evo_store 未被访问前 _evo_store 保持 None，访问时才解析。"""
    assert page._evo_store is None, "构造期不得固化 None（否则永不重试）"
    s = page.evo_store
    assert s is not None, "档案目录可写时 evo_store 应能按需创建"
    assert page._evo_store is s, "property 应回填 _evo_store 避免重复解析"


def test_evo_store_reuses_singleton(page):
    """页面 property 复用全局单例，而非每次新建。"""
    reset_evolution_store_for_test()
    page._evo_store = None
    try:
        s = page.evo_store
        assert s is get_evolution_store(), "应复用 get_evolution_store 单例"
    finally:
        reset_evolution_store_for_test()
        page._evo_store = None


def test_resolve_evo_store_returns_instance(page):
    s = page._resolve_evo_store()
    assert s is not None and hasattr(s, "list_runs")


def test_resolve_evo_store_failure_returns_none_and_logs(page, caplog):
    """创建失败时返回 None，**必须**留下 error 日志（原实现零痕迹）。"""
    def _boom(path=None):
        raise OSError("simulated data/evolution unwritable")

    orig = evo_mod.get_evolution_store
    evo_mod.get_evolution_store = _boom
    try:
        with caplog.at_level("ERROR", logger="futures_quant.ui.backtest_page"):
            result = page._resolve_evo_store()
            assert result is None, "失败应返回 None"
            assert "EvolutionStore 创建失败" in caplog.text, \
                "档案不可用必须记 error 日志，否则能力静默失效"
    finally:
        evo_mod.get_evolution_store = orig


# -------------------------------------------------- ③ 不再静默丢弃
def _patch_store_unavailable(page, monkeypatch, *, raise_it: bool = False):
    """把 _resolve_evo_store 的最终来源（get_evolution_store）改成不可用。

    property ``evo_store`` 是只读的，因此不能靠「替换 property」来注入不可用状态；
    改为直接打桩它内部依赖的 ``get_evolution_store`` —— 这也更贴近真实故障
    （档案目录真的建不出来时，property 拿到的就是 None）。
    返回 (orig, monkeypatch) 以便 finally 还原。
    """

    def _unavailable(path=None):
        if raise_it:
            raise OSError("simulated data/evolution unwritable")
        return None

    monkeypatch.setattr(evo_mod, "get_evolution_store", _unavailable)
    page._evo_store = None          # 清掉缓存，强制走一次解析
    page._evo_store_warned = False
    return _unavailable


def test_evo_store_property_returns_none_when_unavailable(page, monkeypatch):
    """档案目录不可建时 evo_store 返回 None，不是抛异常也不是钉死旧值。"""
    _patch_store_unavailable(page, monkeypatch)
    assert page.evo_store is None, "不可用应返回 None（已由 _resolve_evo_store 记日志）"
    assert page._evo_store is None, "失败不得回填，保证下次还能重试"


def test_evo_store_property_recovers_after_transient_failure(page, monkeypatch):
    """瞬时故障可自愈：先失败一次，再恢复，property 应能重新拿到实例。"""
    _patch_store_unavailable(page, monkeypatch, raise_it=True)
    assert page.evo_store is None
    monkeypatch.undo()
    reset_evolution_store_for_test()
    page._evo_store = None
    assert page.evo_store is not None, "瞬时故障后应能重建（原实现永久钉死 None）"


def test_save_evo_run_unavailable_logs_error_not_silent(page, monkeypatch, caplog):
    """store 不可用 → 记 error + 界面提示，绝不再「判空 return 什么都不说」。"""
    _patch_store_unavailable(page, monkeypatch)
    page._engine = object()   # 越过 `_engine is None` 这道前置守卫，覆盖到 store 分支
    try:
        with caplog.at_level("ERROR", logger="futures_quant.ui.backtest_page"):
            page._save_evo_run({"generation": 1, "ranked": [], "symbol": "RB"})
    finally:
        page._engine = None
    assert "EvolutionStore 不可用" in caplog.text, \
        "档案未落盘必须有 error 级留痕（原实现静默 return）"
    assert page._evo_store_warned is True, "界面提示应已触发（且只触发一次）"


def test_save_evo_run_warns_only_once(page, monkeypatch, caplog):
    """同一次不可用只提示一次，避免每代刷屏；但日志每次都留（供排查）。"""
    _patch_store_unavailable(page, monkeypatch)
    with caplog.at_level("ERROR", logger="futures_quant.ui.backtest_page"):
        page._warn_evo_store_unavailable()
        page._warn_evo_store_unavailable()
    assert page._evo_store_warned is True
    assert caplog.text.count("进化档案未落盘") == 2, \
        "日志须每次都记，界面提示才去重"


def test_on_archive_selected_no_attribute_error_when_store_unavailable(
        page, monkeypatch, caplog):
    """store 为 None 时选档案必须走「不可用」提示，而不是 AttributeError。"""
    _patch_store_unavailable(page, monkeypatch)
    # 让 currentData() 返回一个非空 run_id，否则会在 `if not rid` 处提前返回、
    # 测不到 store 分支
    page.archive_combo.blockSignals(True)
    page.archive_combo.addItem("probe", "qv_evo_probe_run")
    page.archive_combo.blockSignals(False)
    try:
        with caplog.at_level("ERROR", logger="futures_quant.ui.backtest_page"):
            # 不应抛 AttributeError；异常只应转成用户可见提示
            page._on_archive_selected(0)
    finally:
        page.archive_combo.blockSignals(True)
        page.archive_combo.removeItem(page.archive_combo.count() - 1)
        page.archive_combo.blockSignals(False)
    assert "进化档案存储不可用" in caplog.text, \
        "档案不可用必须留 error 日志，而不是被吞成一句界面提示"


# -------------------------------------------------- ④ 源码级防回归
def test_no_direct_none_check_on_private_evo_store():
    """防回归：业务代码不得再裸判 `self._evo_store is None`（应统一走 property）。

    用 AST 而不是字符串匹配 —— 注释/文档字符串里出现这句是允许的（本文件自己
    就在解释这个缺陷），只有真正的比较表达式才算违规。
    """
    tree = ast.parse((ROOT / "futures_quant" / "ui" / "backtest_page.py").read_text(
        encoding="utf-8"))

    def _hits(node: ast.AST) -> bool:
        if not isinstance(node, ast.Compare):
            return False
        if not any(isinstance(op, ast.Is) for op in node.ops):
            return False
        return (isinstance(node.left, ast.Attribute)
                and node.left.attr == "_evo_store"
                and node.comparators
                and isinstance(node.comparators[0], ast.Constant)
                and node.comparators[0].value is None)

    # 手动递归而非 ast.walk：walk 不认「子树豁免」，会把 evo_store property 内部
    # 那句「必须判 None 才知道要不要解析」也当成违规。
    _EXEMPT = {"evo_store", "_resolve_evo_store"}
    offenders: list = []

    def _walk(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name in _EXEMPT:
            return                       # 整棵子树豁免，不再下钻
        if _hits(node):
            offenders.append(getattr(node, "lineno", "?"))
            return
        for child in ast.iter_child_nodes(node):
            _walk(child)

    _walk(tree)
    assert not offenders, \
        f"禁止裸判 self._evo_store is None（行 {offenders}）；" \
        f"应统一用 evo_store 惰性解析（失败即记日志）"


def test_constructor_does_not_swallow_evo_store_creation():
    """防回归：构造期不得再 `except: self._evo_store = None` 固化 None。"""
    src = (ROOT / "futures_quant" / "ui" / "backtest_page.py").read_text(
        encoding="utf-8")
    idx = src.find("self._evo_run_gens = []")
    assert idx > 0, "未找到构造期初始化段"
    segment = src[idx:idx + 400]
    assert "EvolutionStore" not in segment, \
        "构造期不应再 try 创建 EvolutionStore（应交给 property 惰性解析）"
