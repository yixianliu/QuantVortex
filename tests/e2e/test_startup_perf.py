"""Startup performance test."""
import os, sys, time
os.environ['QV_THEME'] = 'dark'
sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from futures_quant.ui.main_window import MainWindow

app = QApplication([])
t0 = time.time()
win = MainWindow()
t1 = time.time()
win.show()

results = []
def check():
    t = time.time()
    results.append({
        'init': round(t1 - t0, 2),
        'show_to_check': round(t - t1, 3),
        'status': win.mdm.status,
        'deferred_active': win._connect_deferred.isActive(),
    })
QTimer.singleShot(500, check)
app.exec()
print(f"init={results[0]['init']}s, status={results[0]['status']}, deferred_active={results[0]['deferred_active']}")
