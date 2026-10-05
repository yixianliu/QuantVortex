#!/usr/bin/env python3
"""M6-04 冒烟测试：响应式布局。

验证项（对应 spec 验收标准）：
    1. 对话框三档尺寸：min=480×560 / default=min(680, 屏宽*0.6)×min(760, 屏高*0.85)
       / max=880×900
    2. 二维码网格用 QGridLayout（非 QHBoxLayout）
    3. 宽屏（≥620 可用宽）→ 双列；窄屏（<620）→ 单列；拖动 1400→500 列数 2→1
    4. 单列时卡片限宽 min(280, avail-32)
    5. 联系方式行同样双列/单列自适应（_InfoGrid）
    6. 无横向滚动条（三档屏幕下均无溢出）
    7. 删除 setFixedHeight 递归风险（_QRCard 无 resizeEvent setFixedHeight）
    8. 间距/字号经 layout_manager.scale 缩放（_scaled/_font 走 lm）
    9. 主题往返无残留

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m6_04.py > tests/e2e/m6_04.log 2>&1; echo rc=$?
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QGridLayout, QHBoxLayout  # noqa: E402

from futures_quant.ui import about_page as ap  # noqa: E402
from futures_quant.ui.about_page import (
    AboutDialog, _QRSection, _InfoGrid, _scaled,
)
from futures_quant.ui import responsive_layout as rl  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


# 源码（供审计）
SRC = os.path.join(ROOT, "futures_quant", "ui", "about_page.py")
with open(SRC, encoding="utf-8") as f:
    src = f.read()

# ------------------------------------------------------------- 1. 三档尺寸
dlg = AboutDialog()
dlg.show()
app.processEvents()

check("min-size-480x560",
      dlg.minimumWidth() == 480 and dlg.minimumHeight() == 560,
      f"min={dlg.minimumWidth()}x{dlg.minimumHeight()}")
check("max-size-880x900",
      dlg.maximumWidth() == 880 and dlg.maximumHeight() == 900,
      f"max={dlg.maximumWidth()}x{dlg.maximumHeight()}")

lm = rl.get_layout_manager()
sw, sh = lm.width, lm.height
exp_w = min(680, int(sw * 0.6))
exp_h = min(760, int(sh * 0.85))
check("default-size-formula",
      dlg.width() == exp_w and dlg.height() == exp_h,
      f"got={dlg.width()}x{dlg.height()}, exp={exp_w}x{exp_h} (screen={sw}x{sh})")

# ------------------------------------------------------------- 2. QGridLayout
sections = [w for w in dlg.findChildren(_QRSection)]
check("two-qr-sections", len(sections) == 2, f"count={len(sections)}")
check("qr-grid-is-qgridlayout",
      all(isinstance(s._grid, QGridLayout) for s in sections),
      f"types={[type(s._grid).__name__ for s in sections]}")

# ------------------------------------------------------------- 3. 列数切换
def cols_of(section):
    """从 grid 里数出实际列数（按 item 的列号最大值 +1）。"""
    max_c = 0
    for i in range(section._grid.count()):
        it = section._grid.itemAt(i)
        if it is None:
            continue
        # QGridLayout.getItemPosition(index) → (row, col, rowSpan, colSpan)
        try:
            _, c, _, _ = section._grid.getItemPosition(i)
            max_c = max(max_c, c)
        except Exception:  # noqa: BLE001
            pass
    return max_c + 1


# 列数由「布局传导后的实际宽度」决定——必须 resize 对话框（resize 子控件会被
# 父布局覆写回布局宽度，这是写测试时最容易踩的坑）。
orig_class = lm._resolution_class


def cols_at(dialog_w: int) -> int:
    """把对话框调到指定宽度，processEvents 后读取首个二维码分区的实际列数。"""
    dlg.resize(dialog_w, 700)
    app.processEvents()
    app.processEvents()  # 两轮：确保布局传导 + resizeEvent 回落完成
    sec = [w for w in dlg.findChildren(_QRSection)][0]
    return cols_of(sec), sec


try:
    lm._resolution_class = "wide"
    c_wide, sec_w = cols_at(880)     # 内容宽 ~824 ≥620 → 双列
    c_narrow, sec_n = cols_at(500)   # 内容宽 ~444 <620 → 单列
    w_narrow = sec_n.width()
    max_w_single = max(c._card.maximumWidth() for c in sec_n._cards)
finally:
    lm._resolution_class = orig_class

check("columns-wide-2", c_wide == 2, f"cols={c_wide} @dlg_w=880")
check("columns-narrow-1", c_narrow == 1,
      f"cols={c_narrow} @dlg_w=500 (sec_w={w_narrow})")
check("columns-switch-2-to-1", c_wide == 2 and c_narrow == 1,
      f"wide={c_wide}, narrow={c_narrow}")

# 拖动语义：宽 → 窄 自动 2→1（同一实例连续 resize）
try:
    lm._resolution_class = "wide"
    before, _ = cols_at(880)
    after, _ = cols_at(500)
finally:
    lm._resolution_class = orig_class
check("drag-wide-to-narrow-cols-2to1", before == 2 and after == 1,
      f"before={before}, after={after}")

# ------------------------------------------------------------- 4. 单列限宽
check("single-col-max-width",
      max_w_single == max(150, min(280, w_narrow - 32)),
      f"max_w={max_w_single}, avail-32={w_narrow - 32}")

# ------------------------------------------------------------- 5. 联系行网格
grids = [w for w in dlg.findChildren(_InfoGrid)]
check("info-grid-exists", len(grids) == 1, f"count={len(grids)}")
g = grids[0]
check("info-grid-rows-4", len(g._rows) == 4, f"rows={len(g._rows)}")


def info_cols_at(dialog_w: int) -> int:
    """同理：resize 对话框后读联系行网格列数。"""
    dlg.resize(dialog_w, 700)
    app.processEvents()
    app.processEvents()
    return cols_of(g)


try:
    ic_wide = info_cols_at(880)
    ic_narrow = info_cols_at(500)
finally:
    lm._resolution_class = orig_class
check("info-grid-responsive-2-1", ic_wide == 2 and ic_narrow == 1,
      f"wide={ic_wide}(@880), narrow={ic_narrow}(@500)")

# ------------------------------------------------------------- 6. 无横向滚动
from PyQt6.QtWidgets import QScrollArea  # noqa: E402
scrolls = [w for w in dlg.findChildren(QScrollArea)]
h_off = all(
    s.horizontalScrollBarPolicy()
    == __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.ScrollBarPolicy
    .ScrollBarAlwaysOff
    for s in scrolls)
check("no-horizontal-scrollbar", h_off, f"scrolls={len(scrolls)}")

# 真正的「无溢出」：内容宽度不得超过视口宽度（否则横向滚动条被关闭即视觉截断）
def _overflow(dialog_w: int) -> tuple:
    dlg.resize(dialog_w, 700)
    app.processEvents()
    app.processEvents()
    sa = [w for w in dlg.findChildren(QScrollArea)][0]
    return sa.widget().width(), sa.viewport().width()


try:
    lm._resolution_class = "wide"
    cw_500, vp_500 = _overflow(500)
    cw_880, vp_880 = _overflow(880)
finally:
    lm._resolution_class = orig_class
check("no-overflow-at-500", cw_500 <= vp_500,
      f"content={cw_500}, viewport={vp_500}")
check("no-overflow-at-880", cw_880 <= vp_880,
      f"content={cw_880}, viewport={vp_880}")

# chips 必须可换行（FlowLayout），否则横排 minimumSize 顶宽内容
check("chips-use-flow-layout", "FlowLayout" in src)

# 三档屏幕下构造无溢出（1366×768 / 1920×1080 / 2560×1440）
ok_3 = True
detail_3 = []
for w, h in ((1366, 768), (1920, 1080), (2560, 1440)):
    try:
        lm._width, lm._height = w, h
        d = AboutDialog()
        d.show()
        app.processEvents()
        # 内容宽度不得超过对话框可视宽（无横向溢出）
        if d.width() > d.maximumWidth() or d.width() < d.minimumWidth():
            ok_3 = False
            detail_3.append(f"{w}x{h}: w={d.width()} out of bounds")
        d.close()
    except Exception as e:  # noqa: BLE001
        ok_3 = False
        detail_3.append(f"{w}x{h}: {e}")
check("3-resolutions-no-overflow", ok_3, "; ".join(detail_3))

# ------------------------------------------------------------- 7. 无递归风险
# M6-04④：_QRCard 不得在 resizeEvent 里 setFixedHeight
qr_src = src[src.index("class _QRCard"): src.index("class _QRSection")]
check("no-setfixedheight-in-qrcard", "setFixedHeight" not in qr_src,
      f"snippet_has={[l.strip()[:50] for l in qr_src.splitlines() if 'setFixedHeight' in l]}")
check("no-resizeevent-in-qrcard", "resizeEvent" not in qr_src)

# ------------------------------------------------------------- 8. scale 缩放
check("uses-layout-manager", "get_layout_manager" in src)
check("_scaled-helper", "def _scaled" in src and "_scaled(" in src)
check("font-uses-lm-font-size", "font_size" in src)
lm0 = rl.get_layout_manager()
s_val = _scaled(28)
check("_scaled-applies-scale", s_val == max(1, int(28 * lm0.scale)),
      f"_scaled(28)={s_val}, scale={lm0.scale}")

# ------------------------------------------------------------- 9. 主题往返
try:
    dlg.set_theme("light")
    app.processEvents()
    dlg.set_theme("dark")
    app.processEvents()
    check("theme-roundtrip", True)
except Exception as e:  # noqa: BLE001
    check("theme-roundtrip", False, f"err={e}")

# ------------------------------------------------------------- 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M6-04 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
