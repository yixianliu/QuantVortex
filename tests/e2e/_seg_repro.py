# -*- coding: utf-8 -*-
"""分段复现：定位 test_backtest_manual rc=127 崩溃点。"""
import os, sys, time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from futures_quant.data.market_data import MarketDataManager
from futures_quant.ui.backtest_page import BacktestCenterPage
mdm = MarketDataManager(source='synthetic')
page = BacktestCenterPage(mdm)
page.show()
app.processEvents()
t0 = time.time()
while page._engine is None and (time.time() - t0) * 1000 < 8000:
    app.processEvents(); time.sleep(0.02)
page._rb_manual.setChecked(True)
app.processEvents()
idx = page._manual_sym_cb.findData('rb.SHFE')
page._manual_sym_cb.setCurrentIndex(idx if idx >= 0 else 0)
page._manual_strat_cb.setCurrentIndex(0)
app.processEvents()
t0 = time.time()
while page._gen_running and (time.time() - t0) * 1000 < 15000:
    app.processEvents(); time.sleep(0.02)
page._run_manual()
t0 = time.time()
while page._manual_running and (time.time() - t0) * 1000 < 30000:
    app.processEvents(); time.sleep(0.02)
print('A: first manual done:', page._last_manual is not None, flush=True)
page._futures_params['delivery_date'] = '2020-01-10'
mi = page._manual_strat_cb.findData('momentum')
print('B: momentum idx:', mi, flush=True)
page._manual_strat_cb.setCurrentIndex(mi if mi >= 0 else 0)
app.processEvents()
t0 = time.time()
while page._gen_running and (time.time() - t0) * 1000 < 15000:
    app.processEvents(); time.sleep(0.02)
print('C: pre-run done', flush=True)
page._run_manual()
print('D: run_manual returned', flush=True)
t0 = time.time()
while page._manual_running and (time.time() - t0) * 1000 < 30000:
    app.processEvents(); time.sleep(0.02)
print('E: delivery manual done:', not page._manual_running, flush=True)
logger = page._last_manual_logger
print('F: logger:', logger is not None, flush=True)
trades = page._last_manual['res']['trades'] if page._last_manual else []
print('G: trades:', len(trades), flush=True)
page._rb_auto.setChecked(True)
app.processEvents()
print('H: switch back ok', flush=True)
page.close()
print('I: closed ok', flush=True)
