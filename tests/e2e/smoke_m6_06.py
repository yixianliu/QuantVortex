#!/usr/bin/env python3
"""M6-06 冒烟测试：交互与可达性（关于页）。

验证项（对应 spec 验收标准）：
    1. Esc 关闭对话框（QTest.keyClick）
    2. Tab 焦点顺序：信息行复制按钮 → 二维码卡 → 页脚按钮（setTabOrder）
    3. 二维码卡可键盘激活（Enter / 空格 → 放大灯箱）
    4. 复制按钮 accessibleName 形如「复制QQ号」
    5. 复制成功：剪贴板正确 + 文案「已复制 ✓」 + QToolTip 提示
    6. 页脚「复制版本信息」按钮：文案含 QuantVortex / Python / PyQt6
    7. 无横向溢出（页脚按钮改 FlowLayout 后仍是 content ≤ viewport）

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m6_06.py > tests/e2e/m6_06.log 2>&1; echo rc=$?
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import Qt, QEvent  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QScrollArea, QPushButton, QToolTip,
)

from futures_quant.ui import about_page as ap  # noqa: E402
from futures_quant.ui.about_page import AboutDialog, _InfoGrid, _QRSection  # noqa: E402
from futures_quant.ui.qr_card import QRCard  # noqa: E402
from futures_quant.ui import responsive_layout as rl  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


SRC = os.path.join(ROOT, "futures_quant", "ui", "about_page.py")
with open(SRC, encoding="utf-8") as f:
    src = f.read()
QR_SRC = os.path.join(ROOT, "futures_quant", "ui", "qr_card.py")
with open(QR_SRC, encoding="utf-8") as f:
    qr_src = f.read()


def press(widget, key, mod=Qt.KeyboardModifier.NoModifier):
    """直驱 keyPressEvent（offscreen 下比 QTest.keyClick 更可控）。"""
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mod)
    widget.keyPressEvent(ev)
    app.processEvents()


# ============================================================ ① Esc 关闭
dlg = AboutDialog()
dlg.show()
app.processEvents()
check("dialog-visible-before-esc", dlg.isVisible())
press(dlg, Qt.Key.Key_Escape)
app.processEvents()
check("esc-closes-dialog", not dlg.isVisible(),
      f"visible={dlg.isVisible()}")

# ============================================================ ② Tab 顺序（真实键盘导航）
# 注意：不验证 ``nextInFocusChain()`` 邻接——焦点链会潜入 QRCard 内部的
# NoFocus 子控件/包装层，导致 ``qr0.nextInFocusChain()`` 指向子控件而非 qr1，
# 属假阴性。正确做法是驱动真实 Tab 导航并断言焦点顺序（可达性的本质）。
dlg2 = AboutDialog()
dlg2.show()
app.processEvents()
# 显式重设一次，保证响应式重排后顺序稳定（确定性）
dlg2._setup_tab_order()
app.processEvents()

grid = dlg2.findChildren(_InfoGrid)[0]
copy_btns = [r._copy_btn for r in grid._rows]
qr_cards = []
for sec in dlg2.findChildren(_QRSection):
    qr_cards.extend(c._card for c in sec._cards)
footer = [dlg2._diag_btn, dlg2._update_btn, dlg2._copy_ver_btn]

check("chain-non-empty",
      bool(copy_btns) and bool(qr_cards) and bool(footer),
      f"copy={len(copy_btns)}, qr={len(qr_cards)}, footer={len(footer)}")

# 真实 Tab 导航：从首个复制按钮出发，焦点应依次经过 复制按钮→二维码卡→页脚
def tab_seq(start, steps):
    start.setFocus()
    app.processEvents()
    seq = [QApplication.focusWidget()]
    for _ in range(steps):
        fw = QApplication.focusWidget()
        if fw is None:
            break
        QTest.keyClick(fw, Qt.Key.Key_Tab)
        app.processEvents()
        seq.append(QApplication.focusWidget())
    return seq

def classify(w):
    if w in copy_btns:
        return ("copy", copy_btns.index(w))
    if w in qr_cards:
        return ("qr", qr_cards.index(w))
    if w in footer:
        return ("footer", footer.index(w))
    return ("other", type(w).__name__)

expected_order = ([("copy", i) for i in range(len(copy_btns))]
                  + [("qr", i) for i in range(len(qr_cards))]
                  + [("footer", i) for i in range(len(footer))])

seq = tab_seq(copy_btns[0], len(expected_order) + 2)
classified = [classify(w) for w in seq]
seen = []
for c in classified:
    if c not in seen:
        seen.append(c)

check("tab-starts-at-copy0", classified[0] == ("copy", 0),
      f"first={classified[0]}")
check("tab-order-copy-qr-footer",
      seen[:len(expected_order)] == expected_order,
      f"seen_prefix={seen[:len(expected_order)]}")
check("tab-reaches-all-targets",
      all(("copy", i) in seen for i in range(len(copy_btns)))
      and all(("qr", i) in seen for i in range(len(qr_cards)))
      and all(("footer", i) in seen for i in range(len(footer))),
      f"seen={seen}")
check("uses-settaborder", "setTabOrder" in src)

# ============================================================ ③ 键盘激活二维码
card = qr_cards[0]
check("qr-card-focusable",
      card.focusPolicy() == Qt.FocusPolicy.StrongFocus,
      f"policy={card.focusPolicy()}")
# 拦截 _open_lightbox 验证被触发（不真弹模态）
calls = []
orig_open = card._open_lightbox
card._open_lightbox = lambda: calls.append(1)
try:
    press(card, Qt.Key.Key_Return)
    press(card, Qt.Key.Key_Space)
    press(card, Qt.Key.Key_Enter)
finally:
    card._open_lightbox = orig_open
check("qr-card-enter-space-activates", len(calls) == 3,
      f"calls={calls}")
check("qr-card-has-keypressevent", "def keyPressEvent" in qr_src)

# ============================================================ ④ accessibleName
names = [b.accessibleName() for b in copy_btns]
check("copy-btn-accessible-names", names == ["复制QQ号", "复制微信号",
                                             "复制手机号", "复制工作室号"],
      f"names={names}")
check("copy-btn-focusable",
      all(b.focusPolicy() == Qt.FocusPolicy.StrongFocus for b in copy_btns))
check("copy-ver-btn-accessible",
      dlg2._copy_ver_btn.accessibleName() == "复制版本信息")

# ============================================================ ⑤ 复制反馈
btn = copy_btns[0]
app.clipboard().setText("__before__")
press(btn, Qt.Key.Key_Return)   # 键盘激活复制
check("copy-writes-clipboard",
      app.clipboard().text() == "1153602036",
      f"clip={app.clipboard().text()!r}")
check("copy-shows-checkmark", btn.text() == "已复制 ✓", f"text={btn.text()}")
check("copy-tooltip-shown", QToolTip.isVisible(),
      "QToolTip 已弹出")
# 1.2s 后复原
QTest.qWait(1400)
app.processEvents()
check("copy-restores-after-1200ms", btn.text() == "复制",
      f"text={btn.text()}")

# ============================================================ ⑥ 复制版本信息
ver = dlg2.version_info_text()
check("version-info-content",
      "QuantVortex v" in ver and "Python" in ver and "PyQt6" in ver,
      f"ver={ver!r}")
app.clipboard().setText("__before__")
dlg2._copy_version_info()
app.processEvents()
check("copy-ver-writes-clipboard",
      app.clipboard().text() == ver,
      f"clip={app.clipboard().text()!r}")
check("copy-ver-btn-feedback",
      dlg2._copy_ver_btn.text() == "已复制 ✓",
      f"text={dlg2._copy_ver_btn.text()}")
QTest.qWait(1400)
app.processEvents()
check("copy-ver-restores",
      dlg2._copy_ver_btn.text() == "复制版本信息",
      f"text={dlg2._copy_ver_btn.text()}")

# ============================================================ ⑦ 无溢出（三按钮）
lm = rl.get_layout_manager()
orig_cls = lm._resolution_class


def overflow_at(w):
    dlg2.resize(w, 700)
    app.processEvents()
    app.processEvents()
    sa = dlg2.findChildren(QScrollArea)[0]
    return sa.widget().width(), sa.viewport().width()


try:
    lm._resolution_class = "wide"
    cw, vp = overflow_at(500)
finally:
    lm._resolution_class = orig_cls
check("no-overflow-with-3-buttons", cw <= vp, f"content={cw}, viewport={vp}")
check("footer-buttons-3", len(dlg2.findChildren(QPushButton)) >= 3,
      f"btns={len(dlg2.findChildren(QPushButton))}")

# ============================================================ 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M6-06 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
