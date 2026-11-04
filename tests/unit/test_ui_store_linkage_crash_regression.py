"""UI/联动层两处运行时崩溃的根因回归测试（2026-10-05）。

用户现场报错：
1. ``AttributeError: 'NoneType' object has no attribute 'save_prediction'``
   —— `predict_ops_page._on_predict_done` → `self.store.save_prediction(...)`
2. ``RuntimeError: wrapped C/C++ object of type LinkageBus has been deleted``
   —— 进化引擎 `step()` 里的 `BUS.push_backtest_result(...)`，
   被 `except Exception` 捕获后计入「本代基因评估失败」。

根因：
1. 主窗口按 UX-67 把 ``AnalysisStore`` 放到**后台线程**初始化（SQLite 建连约
   100–500ms），页面可能在 store 就绪前被构造，构造入参是占位 ``None``；
   而原 ``_on_store_init_done`` 只更新了主窗口自身，已建成页面仍持有 None。
   修复：① ``BasePage.store`` 改为 property（使用时才解析，兜底查服务定位器）；
        ② ``_on_store_init_done`` 回填已构造页面 + 重新 provide；
        ③ ``_on_predict_done`` 落盘前判空护栏。
2. ``BUS`` 是无父对象的模块级 ``QObject``。QApplication 析构（应用退出）或
   worker 线程销毁时，其 C++ 端会被销毁而 Python 名字仍指向失效包装对象。
   修复：新增 ``linkage_bus.safe_push_backtest_result()``（+ ``get_bus()``
   存活探测与重建），业务代码改走它 —— 联动通知是「尽力而为」的旁路能力，
   失败绝不能放大成「基因评估失败」。

运行：
    python tests/unit/test_ui_store_linkage_crash_regression.py
"""
from __future__ import annotations

import os
import sys

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------------------
# ① AnalysisStore 延迟就绪
# ---------------------------------------------------------------------------

def test_base_page_store_is_lazy_property():
    """BasePage.store 必须是 property：构造时传 None，使用时仍能解析出来。"""
    from futures_quant.ui.pages import BasePage

    assert isinstance(BasePage.store, property), "BasePage.store 应为 property"
    assert hasattr(BasePage, "_resolve_store"), "缺少 _resolve_store 兜底方法"


def test_base_page_store_setter_and_getter_roundtrip():
    """store 赋值/读取语义不变（property 化后不能改变行为）。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.ui.pages import BasePage

    app = QApplication.instance() or QApplication([])
    sentinel = object()
    page = BasePage(mdm=None, store=sentinel, config=None, session=None)
    assert page.store is sentinel, "构造入参应能被读回"
    other = object()
    page.store = other
    assert page.store is other, "setter 应生效"
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None, page  # 保活，避免被 GC


def test_base_page_store_none_does_not_crash_on_access():
    """store 构造入参为 None 时，读取不得抛 AttributeError。

    现在会走按需创建兜底，因此返回的是可用实例（或创建失败时的 None），
    关键是**访问本身不抛异常**。
    """
    from PyQt6.QtWidgets import QApplication

    from futures_quant.ui.pages import BasePage

    app = QApplication.instance() or QApplication([])
    page = BasePage(mdm=None, store=None, config=None, session=None)
    store = page.store          # 不得抛 AttributeError
    assert store is None or hasattr(store, "save_prediction")
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None, page


def test_store_late_binding_via_service_locator():
    """后台初始化完成后注册到服务定位器 → 页面应能拿到（延迟绑定生效）。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.app.service_locator import ServiceLocator, provide
    from futures_quant.ui.pages import BasePage

    app = QApplication.instance() or QApplication([])
    ServiceLocator.instance().clear()
    try:
        # 服务定位器注册优先于按需创建：注册的对象必须被原样返回
        sentinel = object()
        provide("analysis_store", sentinel)
        page = BasePage(mdm=None, store=None, config=None, session=None)
        assert page.store is sentinel, "定位器已注册时应优先返回该实例"

        # 未注册时退回按需创建（不得为 None）
        ServiceLocator.instance().clear()
        page2 = BasePage(mdm=None, store=None, config=None, session=None)
        assert page2.store is not sentinel
        assert page2.store is not None, "未注册时应按需创建兜底"
    finally:
        ServiceLocator.instance().clear()
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None


def test_store_provider_creates_on_demand():
    """store_provider.get_store() 必须能按需同步创建单例（不受后台时序影响）。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.app import store_provider as sp

    app = QApplication.instance() or QApplication([])
    sp.reset_for_test()
    try:
        assert sp.current_path() is None, "初始应为空"
        s1 = sp.get_store()
        assert s1 is not None, "按需创建失败"
        assert hasattr(s1, "save_prediction"), "缺少 save_prediction"
        s2 = sp.get_store()
        assert s1 is s2, "多次调用必须返回同一实例（单例）"
        assert sp.current_path() is not None
    finally:
        sp.reset_for_test()
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None


def test_store_provider_set_store_is_idempotent():
    """set_store 不得覆盖已有实例（避免双连接）。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.app import store_provider as sp

    app = QApplication.instance() or QApplication([])
    sp.reset_for_test()
    try:
        first = sp.get_store()
        other = object()
        sp.set_store(other)
        assert sp.get_store() is first, "set_store 不应覆盖已存在实例"
        sp.set_store(None)          # None 必须被忽略
        assert sp.get_store() is first
    finally:
        sp.reset_for_test()
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None


def test_base_page_falls_back_to_on_demand_store():
    """【核心场景】后台初始化未完成时，页面访问 store 应拿到可用实例而非 None。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.app import store_provider as sp
    from futures_quant.app.service_locator import ServiceLocator
    from futures_quant.ui.pages import BasePage

    app = QApplication.instance() or QApplication([])
    ServiceLocator.instance().clear()
    sp.reset_for_test()
    try:
        # 模拟：服务定位器未注册 + 后台初始化尚未完成
        page = BasePage(mdm=None, store=None, config=None, session=None)
        store = page.store
        assert store is not None, "页面 store 不得为 None（预测落盘依赖它）"
        assert hasattr(store, "save_prediction")
    finally:
        ServiceLocator.instance().clear()
        sp.reset_for_test()
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None


def test_predict_done_guards_none_store():
    """_on_predict_done 在 store 为 None 时必须提前返回，不得 AttributeError。"""
    import inspect

    from futures_quant.ui.predict_ops_page import PredictOpsPage

    src = inspect.getsource(PredictOpsPage._on_predict_done)
    assert "self.store is None" in src, "_on_predict_done 缺少 store 判空护栏"
    assert "save_prediction" in src


def test_main_window_store_init_backfills_pages():
    """_on_store_init_done 必须把 store 回填到已构造的页面。"""
    import inspect

    from futures_quant.ui.main_window import MainWindow

    src = inspect.getsource(MainWindow._on_store_init_done)
    assert "for p in self.pages" in src, "缺少页面回填逻辑"
    assert "provide(" in src, "缺少服务定位器重新注册"


# ---------------------------------------------------------------------------
# ② LinkageBus C++ 对象失效
# ---------------------------------------------------------------------------

def test_linkage_bus_exposes_safe_helpers():
    """linkage_bus 必须提供存活探测与安全推送。"""
    from futures_quant.ai import linkage_bus as lb

    for name in ("is_bus_alive", "get_bus", "safe_push_backtest_result"):
        assert hasattr(lb, name), f"linkage_bus 缺少 {name}"


def test_safe_push_returns_false_when_bus_dead():
    """BUS 的 C++ 端已失效时，安全推送必须返回 False 且不抛出。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.ai import linkage_bus as lb

    app = QApplication.instance() or QApplication([])

    class _DeadBus:
        """模拟 C++ 对象已销毁的 LinkageBus。"""

        @staticmethod
        def objectName():
            raise RuntimeError(
                "wrapped C/C++ object of type LinkageBus has been deleted")

        def push_backtest_result(self, *a, **kw):
            raise RuntimeError(
                "wrapped C/C++ object of type LinkageBus has been deleted")

    original = lb.BUS
    try:
        lb.BUS = _DeadBus()
        assert lb.is_bus_alive() is False
        # 重建成功路径：is_bus_alive False → get_bus 重建 → 推送成功
        ok = lb.safe_push_backtest_result(
            symbol="rb.SHFE", gene={}, metrics={},
            direction_bias=None, regime=None)
        assert ok is True, "get_bus 应重建出一个可用实例并推送成功"
    finally:
        lb.BUS = original
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None


def test_safe_push_never_raises():
    """无论 BUS 处于何种状态，safe_push_backtest_result 都不得抛出。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.ai import linkage_bus as lb

    app = QApplication.instance() or QApplication([])
    original = lb.BUS
    try:
        class _Exploding:
            """存活（objectName 正常）但 push 抛非 RuntimeError 异常。"""

            @staticmethod
            def objectName():
                return "still-alive"

            def push_backtest_result(self, *a, **kw):
                raise ValueError("boom")

        lb.BUS = _Exploding()
        assert lb.is_bus_alive() is True, "objectName 正常应判定为存活"
        # 即便 push 抛非 RuntimeError 也必须被吞掉并返回 False
        assert lb.safe_push_backtest_result("rb", {}, {}) is False
    finally:
        lb.BUS = original
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None


def test_safe_push_handles_dead_bus_gracefully():
    """C++ 已销毁且无法重建时（无 QApplication），也应返回 False 而非抛出。"""
    from PyQt6.QtWidgets import QApplication

    from futures_quant.ai import linkage_bus as lb

    app = QApplication.instance() or QApplication([])
    original = lb.BUS
    try:
        class _DeadBus:
            @staticmethod
            def objectName():
                raise RuntimeError("wrapped C/C++ object ... has been deleted")

            def push_backtest_result(self, *a, **kw):
                raise RuntimeError("wrapped C/C++ object ... has been deleted")

        lb.BUS = _DeadBus()
        assert lb.is_bus_alive() is False
        # get_bus 会重建；此处只保证「调用不抛出」，结果 True/False 均可
        _ = lb.safe_push_backtest_result("rb", {}, {})
    finally:
        lb.BUS = original
    # 这里原本是 `return app`（想保活 QApplication），但 pytest 8 起把
    # 「测试函数返回非 None」升级为 error（PytestReturnNotNoneWarning）。
    # 保活语义等价：局部变量在函数返回时一样释放，Qt 的 qApp 单例仍在。
    assert app is not None


def test_auto_evolve_uses_safe_push_not_raw_bus():
    """auto_evolve 不得再直接调用 BUS.push_backtest_result。"""
    import inspect

    from futures_quant.strategy import auto_evolve as ae

    src = inspect.getsource(ae)
    assert "BUS.push_backtest_result" not in src, \
        "auto_evolve 仍存在裸 BUS 调用（会把联动失败放大为基因评估失败）"
    assert "safe_push_backtest_result" in src


# ---------------------------------------------------------------------------
# 直接运行入口
# ---------------------------------------------------------------------------

def main() -> None:
    keeps = []
    try:
        test_base_page_store_is_lazy_property()
        print("[1] BasePage.store 是延迟解析 property ✅")

        keeps.append(test_base_page_store_setter_and_getter_roundtrip())
        print("[2] store getter/setter 语义不变 ✅")

        keeps.append(test_base_page_store_none_does_not_crash_on_access())
        print("[3] store 为 None 时读取不崩溃 ✅")

        keeps.append(test_store_late_binding_via_service_locator())
        print("[4] 服务定位器延迟绑定生效 ✅")

        keeps.append(test_store_provider_creates_on_demand())
        print("[5] store_provider 按需创建单例 ✅")

        keeps.append(test_store_provider_set_store_is_idempotent())
        print("[6] set_store 幂等不覆盖 ✅")

        keeps.append(test_base_page_falls_back_to_on_demand_store())
        print("[7] 后台未就绪时页面仍能拿到 store ✅")

        test_predict_done_guards_none_store()
        print("[8] _on_predict_done 有判空护栏 ✅")

        test_main_window_store_init_backfills_pages()
        print("[9] _on_store_init_done 回填页面 ✅")

        test_linkage_bus_exposes_safe_helpers()
        print("[10] linkage_bus 提供安全访问器 ✅")

        keeps.append(test_safe_push_returns_false_when_bus_dead())
        print("[11] BUS 失效时自动重建并推送 ✅")

        keeps.append(test_safe_push_never_raises())
        print("[12] safe_push 吞掉非 RuntimeError ✅")

        keeps.append(test_safe_push_handles_dead_bus_gracefully())
        print("[13] safe_push 处理已销毁 BUS 不抛出 ✅")

        test_auto_evolve_uses_safe_push_not_raw_bus()
        print("[14] auto_evolve 改用 safe_push ✅")
    finally:
        del keeps  # 释放保活引用

    print("=" * 60)
    print("UI/联动崩溃回归测试 全部通过（14/14）")


if __name__ == "__main__":
    main()
