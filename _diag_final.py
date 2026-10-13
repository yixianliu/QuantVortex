"""诊断支付宝卡片重叠 + 主窗口未最大化。"""
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt

app = QApplication(sys.argv if hasattr(sys, "argv") else ["test"])
sys.path.insert(0, r"d:\PythonProject\QuantVortex")

from futures_quant.ui.about_page import AboutDialog

# 完整 AboutDialog
print("=== AboutDialog 完整截图 ===")
dlg = AboutDialog()
dlg.show()
app.processEvents()
app.processEvents()

print(f"dlg.size: {dlg.size()}")
print(f"dlg.contentsRect: {dlg.contentsRect()}")

pix = dlg.grab()
pix.save(r"d:\PythonProject\QuantVortex\_about_full.png")
print(f"截图: {pix.width()}x{pix.height()}")

# 扫描所有 QRCard 的几何
from futures_quant.ui.qr_card import QRCard
cards = dlg.findChildren(QRCard)
print(f"\n=== 所有 QRCard 几何 ===")
for i, c in enumerate(cards):
    print(f"\n  Card #{i}:")
    print(f"    rect: {c.rect()}")
    print(f"    sizeHint: {c.sizeHint()}")
    host = getattr(c, '_img_host', None)
    print(f"    host.geometry: {host.geometry() if host else 'N/A'}")
    if c._title_lbl:
        print(f"    title: '{c._title_lbl.text()}' geo={c._title_lbl.geometry()}")
    if c._sub_lbl:
        print(f"    sub: '{c._sub_lbl.text()[:20]}' geo={c._sub_lbl.geometry()}")
    if c._cap_lbl:
        print(f"    caption: '{c._cap_lbl.text()[:30]}...' geo={c._cap_lbl.geometry()}")
        print(f"    caption.sizeHint: {c._cap_lbl.sizeHint()}")
        # 判断是否和 host 重叠
        if host:
            cap_geo = c._cap_lbl.geometry()
            host_geo = host.geometry()
            overlap_y = cap_geo.y() < host_geo.y() + host_geo.height()
            print(f"    caption.y={cap_geo.y()} host.bottom={host_geo.y()+host_geo.height()} 重叠={overlap_y}")

# 也扫 _QRCard（about_page 的包装器）
from futures_quant.ui.about_page import _QRCard
wrappers = dlg.findChildren(_QRCard)
print(f"\n=== _QRCard 包装器 ===")
for i, w in enumerate(wrappers):
    print(f"  Wrapper #{i}: rect={w.rect()}, sizeHint={w.sizeHint()}")
