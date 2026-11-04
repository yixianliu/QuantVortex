# -*- coding: utf-8 -*-
"""M4-13 冒烟测试：图表交互补齐（offscreen）。

覆盖：
    ① PriceChart 十字光标 + Tooltip + 滚轮缩放（可视窗口锚定光标）
    ①' ReliabilityChart 十字 + 就近校准点 Tooltip（无缩放：[0,1] 固定域）
    ② hover 联动：predict_ops 副图(macd/kdj/rsi) hover → 主图十字同步；
       主图 hover → 副图回显；MultiPeriodSync.register_aux 通用绑定
    ③ 右键菜单数据导出：PriceChart/ReliabilityChart/KLineChart _export_rows
    ④ predict_ops 图表动态高度 min(260, avail/4)（768p 下 160px）
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

from PyQt6.QtCore import Qt, QPointF, QPoint, QEvent
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QPaintEvent
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def move(widget, x, y):
    """合成 mouseMove 直驱（offscreen 无真实光标）。"""
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y),
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    widget.mouseMoveEvent(ev)


def wheel(widget, dy):
    """合成 wheel 事件直驱。"""
    ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50),
                     QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.ScrollUpdate, False)
    widget.wheelEvent(ev)


def paint(widget):
    """直驱 paintEvent（offscreen 不保证真实绘制）。"""
    widget.paintEvent(QPaintEvent(widget.rect()))


# ---------- ① PriceChart：hover / tooltip / 缩放 / 导出 ----------
from futures_quant.ui.chart_widget import PriceChart, ReliabilityChart, KLineChart

pc = PriceChart()
pc.resize(400, 260)
vals = [float(i) for i in range(100)]
pc.set_data(series=[{"name": "收盘", "color": "#3b82f6", "y": vals}],
            title="测试")
pc.show()
app.processEvents()
paint(pc)
assert pc._last_rect is not None, "paintEvent 应记录绘图区几何"

got = []
pc.hover_fraction.connect(lambda f: got.append(f))
move(pc, 200, 100)
assert got and got[-1] is not None and 0.0 <= got[-1] <= 1.0, \
    f"hover 应广播占比: {got}"
paint(pc)   # hover 层（十字 + Tooltip）绘制不崩

assert pc._view_window() == (0, 99), "初始窗口应为全量"
wheel(pc, 120)   # 上滚放大
w = pc._view_window()
assert w[1] - w[0] < 99, f"滚轮放大应缩小窗口: {w}"
assert pc._view is not None
paint(pc)        # 缩放态绘制不崩
wheel(pc, -120)  # 下滚缩小
assert pc._view_window()[1] - pc._view_window()[0] > w[1] - w[0]

rows = pc._export_rows()
assert rows[0][:2] == ["样本", "收盘"], f"导出表头: {rows[0]}"
assert len(rows) == 101, f"导出行数: {len(rows)}"
pc.leaveEvent(None)

# ---------- ①' ReliabilityChart ----------
rc = ReliabilityChart()
rc.resize(400, 260)
rc.set_data(bins=[(0.2, 0.15, 10, 0.05, 0.3),
                  (0.5, 0.55, 20, 0.4, 0.7),
                  (0.8, 0.9, 5, 0.6, 0.95)])
rc.show()
app.processEvents()
paint(rc)
assert rc._last_rect is not None
info = rc._hover_info(0.2)
assert info is not None and "命中 15%" in info[2], f"就近 bin 读数: {info}"
move(rc, 200, 100)
paint(rc)
rrows = rc._export_rows()
assert len(rrows) == 4 and rrows[0] == ["预测概率", "经验命中", "样本", "下界", "上界"]

# ---------- KLineChart：联动入口 / 导出 ----------
kl = KLineChart()
kl.resize(600, 450)
bars = [{"datetime": f"2026-01-{(i % 28) + 1:02d}", "open": 100 + i,
         "high": 105 + i, "low": 95 + i, "close": 102 + i, "volume": 1000 + i}
        for i in range(80)]
kl.set_data(bars, ma={"MA5": [None] * 5 + [100.0 + i for i in range(75)]})
kl.show()
app.processEvents()
paint(kl)
kl.set_hover_fraction(0.5)
assert kl._hover == 40, f"0.5 应映射到可见窗口中点: {kl._hover}"
klf = []
kl.hover_fraction.connect(lambda f: klf.append(f))
move(kl, 8 + 0.25 * (600 - 8 - 64), 200)
assert klf and abs(klf[-1] - 0.25) < 0.02, f"主图应广播占比: {klf}"
krows = kl._export_rows()
assert krows[0] == ["时间", "开", "高", "低", "收", "量"] and len(krows) == 81
kl.set_hover_fraction(None)
assert kl._hover == -1

# ---------- ② 页面级联动 + ④ 动态高度 ----------
from futures_quant.data.market_data import MarketDataManager
from futures_quant.storage.analysis_store import AnalysisStore
from futures_quant.ui.predict_ops_page import PredictOpsPage

tmp_db = os.path.join(tempfile.gettempdir() if os.name != "nt"
                      else "D:/PythonProject/QuantVortex/.pytest_tmp",
                      "m4_13_smoke.db")
mdm = MarketDataManager(source="synthetic")
store = AnalysisStore(tmp_db)
page = PredictOpsPage(mdm, store, None, None)
page.resize(1200, 800)
page.show()
app.processEvents()

# ② 副图 hover → 主图十字
move(page.macd, 150, 60)
app.processEvents()
assert page.chart._hover != -1, "macd hover 应同步主图十字线"
# 主图 hover → 副图回显
move(page.chart, 300, 200)
app.processEvents()
assert page.macd._ext_frac is not None, "主图 hover 应回显到 macd"
assert page.kdj._ext_frac is not None and page.rsi._ext_frac is not None
# 各图 hover 层绘制不崩
for c in (page.chart, page.macd, page.kdj, page.rsi):
    paint(c)

# ④ 动态高度：avail = 屏幕高度（responsive_layout 单例）。
# 768p 屏 → 副图 192（<260 解除滚动条病根）；大屏 → 封顶 260。
from futures_quant.ui.responsive_layout import get_layout_manager

avail = max(480, int(get_layout_manager().height))
exp_sub = min(260, max(150, avail // 4))
assert page.macd.minimumHeight() == exp_sub, \
    f"副图动态高度应 {exp_sub}: {page.macd.minimumHeight()}"
assert page.kdj.minimumHeight() == exp_sub and page.rsi.minimumHeight() == exp_sub
assert page.chart.minimumHeight() <= 360
# resize 不改变 avail（屏幕同源），高度保持稳定且与大窗口一致
page.resize(1600, 1200)
app.processEvents()
assert page.macd.minimumHeight() == exp_sub

# ---------- ②' MultiPeriodSync.register_aux ----------
from futures_quant.ui.multi_period_widget import MultiPeriodSync

sync = MultiPeriodSync()
k2 = KLineChart()
k2.set_data(bars)
aux = PriceChart()
aux.set_data(series=[{"name": "a", "color": "#f59e0b", "y": [1, 2, 3]}])
sync.register(k2)
sync.register_aux(aux)
k2.hover_fraction.emit(0.3)
assert aux._ext_frac == 0.3, "K线 hover 应联动辅助图"
aux.hover_fraction.emit(0.7)
assert k2._hover != -1, "辅助图 hover 应联动 K 线十字"

page.close()
store.close()
print("M4-13 SMOKE OK")
