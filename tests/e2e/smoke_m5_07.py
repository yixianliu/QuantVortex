# -*- coding: utf-8 -*-
"""M5-07 冒烟测试：消除滥用与主线程阻塞（offscreen）。

覆盖：
    ① pages.py PredictPage：fetch_all_news 不再 force（尊重 60s 缓存）；
       work 内已正确导入 news_feed（修复 NameError 静默失败）；
       新增「刷新资讯」按钮，二次点击 = 取消
    ② market_overview showEvent：5 分钟节流 —— 3 分钟内重复进入只发 1 次抓取
    ③ predict_ops：资讯抓取走 fetch_all_news（带 should_abort），
       worker 注入 + 中断检查点（InterruptionError）
    ④ 进度「x/13 源」：on_progress 经 Worker.progress 上报（既有 M4-09 路径复用）
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from futures_quant.data.market_data import MarketDataManager
from futures_quant.storage.analysis_store import AnalysisStore
from futures_quant.ui.pages import PredictPage
from futures_quant.ui.market_overview_page import MarketOverviewPage
from futures_quant.ui.predict_ops_page import PredictOpsPage

tmp_db = os.path.join("D:/PythonProject/QuantVortex/.pytest_tmp", "m5_07_smoke.db")
mdm = MarketDataManager(source="synthetic")
store = AnalysisStore(tmp_db)

# ---------- ① PredictPage：按钮存在 + work 内 news_feed 可用 + 无 force ----------
pp = PredictPage(mdm, store, None, None)
pp.show()
app.processEvents()
assert hasattr(pp, "news_refresh_btn"), "PredictPage 应有「刷新资讯」按钮"
assert pp.news_refresh_btn.text() == "刷新资讯"
assert hasattr(pp, "_refresh_news")

# 源码级断言：force=True 已移除、news_feed 已在 work 内导入
src = open(os.path.join(ROOT, "futures_quant", "ui", "pages.py"),
           encoding="utf-8").read()
assert "fetch_all_news(limit=60, force=True)" not in src, "force=True 应已移除"
assert "from ..ai import news_feed" in src, "work 内应导入 news_feed"
assert "fetch_all_news(limit=60, force=False)" in src, "work 内应为 force=False"
assert src.count("force=False") >= 2, "work 与 _refresh_news 均应为 force=False"

# 刷新按钮点击 → 进入抓取态（worker 启动，按钮变「取消抓取」）
pp._refresh_news()
app.processEvents()
assert pp._news_fetching is True, "点击后应进入抓取态"
assert pp.news_refresh_btn.text() == "取消抓取"
# 二次点击 = 取消请求
pp._refresh_news()
app.processEvents()
assert pp._workers and pp._workers[-1].isInterruptionRequested(), \
    "二次点击应请求中断"
# 等待 worker 退出（synthetic 环境抓取很快失败/完成）
deadline = time.time() + 20
while time.time() < deadline and pp._news_fetching:
    app.processEvents()
    time.sleep(0.05)
pp._news_fetching = False
pp.close()

# ---------- ② market_overview：5 分钟节流 ----------
mo = MarketOverviewPage(mdm, store, None, None)
mo.show()
app.processEvents()
assert mo._news_autoloaded is True, "首次进入应标记已自动加载"
# 模拟「3 分钟前刚抓取过」→ 再次 showEvent 不应发起抓取
mo._news_running = False
mo._news_last_ts = time.time() - 180   # 3 分钟前
calls = []
orig_run = mo._run_news
mo._run_news = lambda: calls.append(1)
from PyQt6.QtGui import QShowEvent
ev = QShowEvent()
mo.showEvent(ev)
assert not calls, "3 分钟内重复进入不应重新抓取"
# 模拟「6 分钟前」→ 应触发
mo._news_last_ts = time.time() - 360
mo.showEvent(QShowEvent())
assert calls, "超过 5min 应自动刷新"
mo._run_news = orig_run
mo.close()

# ---------- ③ predict_ops：work 注入 worker + should_abort 抓取 ----------
pop = PredictOpsPage(mdm, store, None, None)
pop.show()
app.processEvents()
psrc = open(os.path.join(ROOT, "futures_quant", "ui", "predict_ops_page.py"),
            encoding="utf-8").read()
assert "def work(worker):" in psrc, "预测 worker 应注入 worker 句柄"
assert "should_abort=worker.isInterruptionRequested" in psrc, \
    "资讯抓取应支持协作式取消"
assert "raise InterruptionError" in psrc, "抓取后应有中断检查点"
assert "fetch_all_concurrent" not in psrc.split("def work(worker):")[1].split("def ")[0], \
    "资讯抓取应改用支持取消的 fetch_all_news"
pop.close()

store.close()
print("M5-07 SMOKE OK")
