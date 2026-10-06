# -*- coding: utf-8 -*-
"""M4-02 验收（pytest 版）：修复 MarketPage 必崩 + 孤儿页面处置。

对照原始散落脚本 tests/test_m4_02.py 改写：
  · main() + sys.exit(main()) → pytest 函数；
  · check(cond,msg) → assert；行为契约不变；
  · 页面构造副作用（AnalysisStore 落盘）重定向到 TMP（conftest 已设），
    不污染真实数据目录。

验收点：
  1. pages.py 全部页面类可构造（offscreen 冒烟 rc=0）；
  2. main_window.py 死导入 ValidatePage 已移除；LogPage 仍被导入；
  3. MarketPage._build_alert_center 签名接受 margin 形参（修复 NameError 根因）；
  4. 孤儿页 MarketPage/PredictPage/PanoramaPage 标注 @deprecated；
     IndicatorPage/ValidatePage/LogPage 不标注（M4-11 / 仍在使用）；
  5. BasePage._page_margin 已新增；pages._deprecated 装饰器已定义。
"""
import os

os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

import inspect
import re

import pytest
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication

PAGE_CLASSES = [
    "MarketPage", "IndicatorPage", "PredictPage",
    "PanoramaPage", "ValidatePage", "LogPage",
]
# 预期 @deprecated 标记：孤儿页 True，活跃页 False
DEPRECATED_EXPECT = {
    "MarketPage": True, "PredictPage": True, "PanoramaPage": True,
    "IndicatorPage": False, "ValidatePage": False, "LogPage": False,
}


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture(scope="module")
def pages_env(app):
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    import futures_quant.ui.pages as P

    mdm = MarketDataManager(source="synthetic")
    db_path = os.path.join(os.environ.get("TMP", "/tmp"), "m4_02_pages.db")
    db_path = os.path.abspath(db_path)
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass
    store = AnalysisStore(path=db_path)
    yield P, mdm, store
    store.close()
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except OSError:
        pass


@pytest.mark.parametrize("cls_name", PAGE_CLASSES)
def test_page_class_constructs(pages_env, cls_name):
    P, mdm, store = pages_env
    Cls = getattr(P, cls_name)
    page = Cls(mdm, store, config=None, session=None)
    page.set_theme("dark")
    page.set_theme("light")
    page.set_theme("dark")
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    page.closeEvent(QCloseEvent())
    # 构造/主题/关闭均未抛异常即视为通过
    assert page is not None


def test_build_alert_center_has_margin_param(pages_env):
    P, _m, _s = pages_env
    sig = inspect.signature(P.MarketPage._build_alert_center)
    assert "margin" in sig.parameters, \
        "MarketPage._build_alert_center 应接受 margin 形参（修复 NameError 根因）"
    assert sig.parameters["margin"].default is None, \
        "_build_alert_center(margin=None) 默认值应为 None"


@pytest.mark.parametrize("cls_name", PAGE_CLASSES)
def test_deprecated_marker(pages_env, cls_name):
    P, _m, _s = pages_env
    Cls = getattr(P, cls_name)
    actual = getattr(Cls, "__deprecated__", False)
    expected = DEPRECATED_EXPECT[cls_name]
    assert actual is expected, \
        f"{cls_name}.__deprecated__ 应为 {expected}，实测 {actual}"


def test_main_window_no_validatepage_death_import():
    mw_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "futures_quant", "ui", "main_window.py",
    )
    with open(mw_path, "r", encoding="utf-8") as fh:
        mw_src = fh.read()
    bad = re.search(r"from\s+\.pages\s+import[^\n]*ValidatePage", mw_src)
    assert bad is None, "main_window.py 仍从 .pages 导入 ValidatePage（死导入未移除）"
    ok = re.search(r"from\s+\.pages\s+import[^\n]*LogPage", mw_src)
    assert ok is not None, "main_window.py 未导入 LogPage（活跃页面不应被移除）"


def test_basepage_has_page_margin(pages_env):
    P, _m, _s = pages_env
    assert hasattr(P.BasePage, "_page_margin"), "BasePage._page_margin 应已新增"


def test_pages_deprecated_decorator_callable(pages_env):
    P, _m, _s = pages_env
    assert callable(getattr(P, "_deprecated", None)), "pages._deprecated 装饰器应已定义"
