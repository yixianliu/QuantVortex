#!/usr/bin/env python3
"""M6-03 冒烟测试：扫码引导文案与信息架构（关于页）。

验收（对应 F6 缺陷修复：原卡片只有「QQ 群 / 微信群 / 支付宝 / 微信支付」
四个词，无「为什么扫 / 扫了有什么 / 备注什么」引导文案）：

    1. 四张二维码卡均含非空引导文案（caption）
    2. 每张 caption 显著长于原 4 词占位（含完整语义，而非仅名词）
    3. 每张 caption 含引导/动作语义词（扫码 / 复制 / 备注 / 加入 / 获取 /
      请 / 打赏 / 添加 / 私信 / 工作日 / 致谢 / 进阶 任一）
    4. QRCard 实际渲染出 caption 标签（_cap_lbl 非空、text 非空）
    5. 组尾声明存在且含合规文案「不构成任何服务承诺」
    6. 源码级守门：占位式 4 词（「QQ 群」「微信群」）已被替换

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m6_03.py > tests/e2e/m6_03.log 2>&1; echo rc=$?
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication  # noqa: E402
from futures_quant.ui.about_page import AboutDialog, _QRSection  # noqa: E402
from futures_quant.ui.qr_card import QRCard  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


# 引导语义词：命中任一即视为含「为什么扫 / 扫了有什么 / 备注什么」
GUIDE_WORDS = ["扫码", "复制", "备注", "加入", "获取", "请", "打赏",
               "添加", "私信", "工作日", "致谢", "进阶"]

dlg = AboutDialog()
dlg.show()
app.processEvents()

cards = []
for sec in dlg.findChildren(_QRSection):
    for c in sec._cards:
        cards.append(c._card)  # 内部 QRCard

check("qr-cards-count-4", len(cards) == 4, f"cards={len(cards)}")

captions = [c._caption for c in cards]
check("all-captions-nonempty", all(captions), f"captions={captions}")
check("captions-longer-than-placeholder",
      all(len(c) >= 12 for c in captions),
      f"lens={[len(c) for c in captions]}")


def has_guide(cap):
    return any(w in cap for w in GUIDE_WORDS)


check("each-caption-has-guide-semantics",
      all(has_guide(c) for c in captions),
      f"caps={captions}")

# 实际渲染出 caption 标签（_build 中 caption 非空才建 _cap_lbl）
check("caption-label-rendered",
      all(c._cap_lbl is not None and c._cap_lbl.text()
          for c in cards))

# 组尾声明（合规）
note = getattr(dlg, "_pay_note", None)
check("group-end-declaration-exists", note is not None)
check("group-end-has-compliance",
      note is not None and "不构成任何服务承诺" in note.text(),
      f"note={note.text() if note else None}")

# 信息架构验收：卡片 label 已从「名词占位」升级为「动作导向」
# （含 添加 / 打赏 等动词，而非原「QQ 群 / 微信群 / 支付宝 / 微信支付」裸名词）
ACTION_VERBS = ["添加", "打赏", "扫码", "好友"]
labels = [c._title for c in cards]
check("card-labels-action-oriented",
      len(labels) == 4 and all(any(v in lb for v in ACTION_VERBS)
                               for lb in labels),
      f"labels={labels}")

# 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M6-03 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
