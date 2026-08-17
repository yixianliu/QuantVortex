"""离屏渲染 KLineChart 验证视觉打磨效果（深色/浅色/悬浮）。"""
import math, random
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt

import futures_quant.ui.chart_widget as cw

random.seed(7)
N = 240
bars = []
price = 3200.0
for i in range(N):
    drift = math.sin(i / 18.0) * 6 + random.uniform(-9, 9)
    op = price
    cl = max(1.0, op + drift)
    hi = max(op, cl) + random.uniform(0, 8)
    lo = min(op, cl) - random.uniform(0, 8)
    vol = abs(random.gauss(0, 1)) * 80000 + 40000
    yy = f"2025-{1 + (i // 20) % 12:02d}"
    mm = f"{(i % 28) + 1:02d}"
    bars.append({
        "datetime": f"{yy}-{mm} 00:00:00",
        "open": round(op, 2), "high": round(hi, 2), "low": round(lo, 2),
        "close": round(cl, 2), "volume": round(vol, 0),
    })
    price = cl

def sma(arr, n):
    out = []
    for i in range(len(arr)):
        if i < n - 1:
            out.append(None); continue
        out.append(sum(arr[i - n + 1:i + 1]) / n)
    return out

closes = [b["close"] for b in bars]
ma = {"MA10": sma(closes, 10), "MA20": sma(closes, 20), "MA30": sma(closes, 30)}

def render(theme, hover, fname):
    app = QApplication.instance() or QApplication([])
    w = cw.KLineChart()
    w.setFixedSize(960, 520)
    w.set_data(bars, ma=ma)
    w.set_watermark("rb.SHFE · 日线")
    w.set_theme(theme)
    w._hover = hover
    w.update()
    pix = QPixmap(w.width(), w.height())
    pix.fill(QColor(15, 17, 22) if theme == "dark" else QColor(255, 255, 255))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w.render(p)
    p.end()
    pix.save(fname)
    print("saved", fname)

render("dark", -1, "examples/kline_dark.png")
render("dark", 150, "examples/kline_dark_hover.png")
render("light", -1, "examples/kline_light.png")
print("done")
