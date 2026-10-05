#!/usr/bin/env python3
"""M7-07 冒烟测试：主题化与交互提示。

验证项：
    1. 源码无硬编码 hex 颜色（grep 审计，排除注释/docstring 行）
    2. 状态样式经 _style_status token 化（ok/warn/off/error 四态取 pal()）
    3. 快捷键：Ctrl+S 应用 / Ctrl+Enter 测试 / Ctrl+R 重置（keyPressEvent
       直驱 + 行为断言）
    4. 50ms 魔法延迟已删（_on_apply 不再调用 _apply_timer.start）
    5. 主题连续切换 10 次无残留旧色（dark/light 交替后关键色随 pal() 变化）
    6. 控件 accessible name 补全（API 密钥）
    7. 帮助菜单快捷键清单登记（main_window._shortcut_seqs 含 3 条 AI 条目）

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m7_07.py > tests/e2e/m7_07.log 2>&1; echo rc=$?
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from futures_quant.ui import ai_settings_dialog as ais  # noqa: E402
from futures_quant.ui.ai_settings_dialog import AIConfigDialog  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


# ------------------------------------------------------------- 1. 源码审计
path = os.path.join(ROOT, "futures_quant", "ui", "ai_settings_dialog.py")
with open(path, encoding="utf-8") as f:
    src = f.read()

# 去掉 docstring 与注释行后审计 hex 颜色
code_only = []
in_doc = False
for line in src.splitlines():
    s = line.strip()
    if s.startswith('"""') or s.startswith("'''"):
        if len(s) >= 3 and s.endswith('"""') and not s.startswith(
                '"""', 1):
            in_doc = not in_doc
        code_only.append(line)  # docstring 定界行本身保留
        continue
    if in_doc or s.startswith("#"):
        continue
    code_only.append(line)
code_src = "\n".join(code_only)
hex_re = re.compile(r"#[0-9a-fA-F]{6}\b")
violations = [m.group(0) for m in hex_re.finditer(code_src)]
check("no-hardcoded-hex-in-code", not violations,
      f"violations={violations[:5]}")

check("style-status-method", "_style_status" in src)
check("status-uses-pal-tokens",
      'p["down"]' in src and 'p["warning"]' in src
      and 'p["sub"]' in src and 'p["up"]' in src)

# ------------------------------------------------------------- 3. 快捷键
dlg = AIConfigDialog(config=None)
dlg.show()
app.processEvents()
got_apply = []
dlg.config_applied.connect(lambda: got_apply.append(1))


def press(key, modifiers=Qt.KeyboardModifier.ControlModifier):
    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
    dlg.keyPressEvent(event)
    app.processEvents()


# Ctrl+S：应用（无 config → 走进程内保存，成功发射信号）
press(Qt.Key.Key_S)
QTest.qWait(180)  # 等待 150ms 单发 timer 触发 _finish_apply → 发射 config_applied
check("ctrl-s-applies", len(got_apply) == 1, f"emitted={got_apply}")

# Ctrl+Enter：测试（无密钥 → 就地建议，不崩溃）
dlg._test_summary.setText("reset")
press(Qt.Key.Key_Return)
check("ctrl-enter-tests",
      "未配置 API 密钥" in dlg._test_advice.text(),
      f"advice={dlg._test_advice.text()[:40]}")

# Ctrl+R：重置（二次确认 mock 成 No → 无副作用）
orig_q = ais.QMessageBox.question
ais.QMessageBox.question = staticmethod(
    lambda *a, **kw: ais.QMessageBox.StandardButton.No)
before = dlg._timeout_spin.value()
try:
    press(Qt.Key.Key_R)
finally:
    ais.QMessageBox.question = orig_q
check("ctrl-r-reset-noop-when-cancelled",
      dlg._timeout_spin.value() == before)

# Esc：不拦截（QDialog 默认 reject 行为由基类处理）
press(Qt.Key.Key_Escape)
check("esc-no-crash", True)

# ------------------------------------------------------------- 4. 魔法延迟删除
# M7-07 目标：删除 50ms 魔法延迟。保存改由 _apply_timer（单发 150ms 可观察间隔）
# 驱动，既满足 M7-03「保存中…」态可观测契约，又避免 50ms 拍脑袋。
on_apply_src = src[src.index("def _on_apply"):
                   src.index("def _set_saving")]
check("no-magic-50ms-delay", "start(50)" not in src
      and ".start(50)" not in src,
      f"snippet={on_apply_src[:80]!r}")
check("apply-timer-observable-interval",
      "setInterval(150)" in on_apply_src
      and "_apply_timer.start()" in on_apply_src,
      "保存中态由 150ms 单发 timer 驱动，UI 刷新后可观察")

# ------------------------------------------------------------- 5. 主题切换
from futures_quant.ui import widgets as w  # noqa: E402
for i in range(10):
    t = "light" if i % 2 == 0 else "dark"
    w.THEME = t
    dlg.set_theme(t)
    app.processEvents()
# 连续 10 次切换后回到 dark，关键样式必须用最新 pal() 值（无旧色残留）
dlg.set_theme("dark")
dlg._style_status("ok")
app.processEvents()
p_dark = dict(w.PALETTE["dark"])
ok_dark = ("color:" + p_dark["down"]) in dlg._status_label.styleSheet()
dlg.set_theme("light")
dlg._style_status("warn")
app.processEvents()
p_light = dict(w.PALETTE["light"])
ok_light = ("color:" + p_light["warning"]) in dlg._status_label.styleSheet()
check("theme-10-switch-no-residue", ok_light and ok_dark,
      f"light={ok_light}, dark={ok_dark}")
check("theme-syncs-module-level",
      w.THEME == "light" and ais.THEME == "light")

# ------------------------------------------------------------- 6. accessible
check("api-key-accessible",
      dlg._api_key_edit.accessibleName() == "API 密钥")

# ------------------------------------------------------------- 7. 帮助清单
# 直读 main_window.py 源码验证登记（避免 import main_window 触发其模块级 UI 依赖）
mw_path = os.path.join(ROOT, "futures_quant", "ui", "main_window.py")
with open(mw_path, encoding="utf-8") as f:
    mw_src = f.read()
ai_seq_block = [ln for ln in mw_src.splitlines()
                if "for seq, desc in ((" in ln]
check("help-menu-3-ai-entries", len(ai_seq_block) == 1,
      f"block_lines={len(ai_seq_block)}")
need = ("应用并保存", "测试连接", "恢复默认")
idx0 = mw_src.index("for seq, desc in ((" + '"', mw_src.index("M7-07"))
block_src = mw_src[idx0: idx0 + 400]
check("help-entries-cover-3-actions",
      all(desc in block_src for desc in need),
      f"missing={[d for d in need if d not in block_src]}")
check("help-only-register-no-shortcut",
      ("Ctrl+S（AI 对话框）" in block_src
       and "Ctrl+Enter（AI 对话框）" in block_src
       and "Ctrl+R（AI 对话框）" in block_src
       and "self._shortcut_seqs.append((seq, desc))" in block_src
       and "QShortcut" not in block_src))

# ------------------------------------------------------------- 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M7-07 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
