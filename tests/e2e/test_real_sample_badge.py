# -*- coding: utf-8 -*-
"""R5.3 真实样本视觉标记 e2e：手动模式下品种下拉给已具真实样本的品种加「📦真实」后缀。

运行：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/test_real_sample_badge.py \
        > tests/e2e/test_real_sample_badge.log 2>&1; echo rc=$?
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from futures_quant.data.market_data import MarketDataManager  # noqa: E402
from futures_quant.ui.backtest_page import BacktestCenterPage  # noqa: E402
from futures_quant.runtime import get_data_dir  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    status = "✅" if cond else "❌"
    print(f"{status} {msg}")
    if not cond:
        fails += 1


# 准备：确认 data/real_samples/ 至少有这 4 个品种
sample_dir = os.path.join(get_data_dir(), "real_samples")
R5_SYMS = ["rb.SHFE", "au.SHFE", "i.DCE", "IF.CFFEX"]
have_real = [s for s in R5_SYMS
             if os.path.exists(os.path.join(sample_dir, f"{s.replace('.', '_')}_D.csv"))]
print(f"[fixture] 真实样本落盘 {len(have_real)}/4: {have_real}")
assert len(have_real) >= 3, "前置：至少 3 个品种真实样本已落盘"

# 构造页面 → 切到手动回测模式（触发 _populate_manual_symbols）
mdm = MarketDataManager(source="synthetic")
page = BacktestCenterPage(mdm)
page.show()  # offscreen 下需上屏，isVisible 才能反映真实状态
app.processEvents()

# 通过手动模式 RB 触发 _on_mode_toggle → _build_manual_panel → _populate_manual_symbols
assert page._rb_manual is not None, "手动模式 radio 应已实例化"
page._rb_manual.setChecked(True)
app.processEvents()

cb = page._manual_sym_cb
assert cb is not None, "手动品种下拉应已实例化"

# 收集所有 label + userData
labels = [cb.itemText(i) for i in range(cb.count())]
datas = [cb.itemData(i) for i in range(cb.count())]
print(f"[fixture] 手动品种下拉共 {cb.count()} 项")
for lab, d in zip(labels, datas):
    print(f"   {d!s:<14} {lab}")

# 检查 1：每个有真实样本的品种 label 末尾都含「📦真实」
for sym in have_real:
    idx = datas.index(sym) if sym in datas else -1
    check(idx >= 0, f"{sym} 应出现在下拉中")
    if idx >= 0:
        check(labels[idx].endswith("📦真实"), f"{sym} label 应带「📦真实」尾标：{labels[idx]!r}")

# 检查 2：未落盘真实样本的品种（如果有）label 不含「📦真实」
no_real = [s for s in [d for d in datas if d]
           if s not in have_real and s.startswith(("rb.", "au.", "i.", "IF.", "cu.", "m.", "ZC.", "al."))]
# 实际只断言"非这 4 个品种的代码"不带真实尾标（容错：universe 可能就这 4 个）
for sym in [d for d in datas if d and d not in have_real]:
    idx = datas.index(sym)
    check("📦真实" not in labels[idx], f"{sym} 不应带「📦真实」尾标：{labels[idx]!r}")

# 检查 3：手动模式面板已渲染
check(page._manual_group is not None and page._manual_group.isVisible(),
      "手动模式 QGroupBox 应可见")

print()
if fails == 0:
    print("=== R5.3 真实样本视觉标记 e2e 全部通过 ===")
    sys.exit(0)
print(f"=== 失败 {fails} 项 ===")
sys.exit(1)
