#!/usr/bin/env python3
"""M7-01 冒烟测试：AI 模型配置对话框向导式分组重构。

验证项：
    1. 容器：min 560x600 / default 680x680 / max 900x820
    2. 分段导航：QListWidget 4 项 + QStackedWidget 4 页，宽屏侧栏模式
    3. 分段切换状态保持：编辑控件值 → 切走再切回，值不丢
    4. 控件类型：模型名 QComboBox 可编辑 / 令牌数 QSpinBox /
       温度 QDoubleSpinBox / 超时 QSpinBox
    5. SpinBox 越界钳制：99999→8192、1→256、0→5、999→300、9.9→2.0
    6. 密钥 👁 显隐切换：Password ↔ Normal
    7. 端点只读 + 复制到剪贴板
    8. 温度预设按钮（精确 0.1 / 均衡 0.3 / 创意 0.7）
    9. 窄屏（<620px）自动折叠为顶部 QTabWidget，状态保持
   10. config_applied 信号存在且可连接
   11. _save_to_config（无 ConfigManager 时进程内生效）

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m7_01.py > tests/e2e/m7_01.log 2>&1; echo rc=$?
"""
import sys

from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox,
)

ROOT = None
import os

if ROOT is None:  # 三级 dirname 自注入 sys.path（项目 e2e 规范 #12）
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from futures_quant.ui.ai_settings_dialog import (  # noqa: E402
    AGNES_API_BASE, COMPACT_BREAKPOINT, DIALOG_DEFAULT, DIALOG_MAX,
    DIALOG_MIN, NAV_ITEMS, AIConfigDialog,
)

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


# ---------------------------------------------------------------- 容器与骨架
dlg = AIConfigDialog(config=None)
dlg.show()
app.processEvents()

check("min-size-560x600",
      (dlg.minimumSize().width(), dlg.minimumSize().height()) == DIALOG_MIN,
      f"min={dlg.minimumSize().width()}x{dlg.minimumSize().height()}")
check("max-size-900x820",
      (dlg.maximumSize().width(), dlg.maximumSize().height()) == DIALOG_MAX,
      f"max={dlg.maximumSize().width()}x{dlg.maximumSize().height()}")
check("default-size-680x680",
      (dlg.width(), dlg.height()) == DIALOG_DEFAULT,
      f"size={dlg.width()}x{dlg.height()}")
check("nav-4-items", dlg._nav.count() == 4,
      f"items={[dlg._nav.item(i).text() for i in range(dlg._nav.count())]}")
check("nav-titles-match",
      [dlg._nav.item(i).text() for i in range(dlg._nav.count())]
      == list(NAV_ITEMS))
check("stack-4-pages", dlg._stack.count() == 4)
check("wide-mode-default", dlg._compact is False and dlg._stack.currentIndex() == 0)
check("breakpoint-constant", COMPACT_BREAKPOINT == 620)

# ------------------------------------------------------------ 切换 + 状态保持
dlg._nav.setCurrentRow(1)
app.processEvents()
check("nav-switch-model", dlg._stack.currentIndex() == 1)

dlg._temperature_spin.setValue(1.25)
dlg._model_combo.setCurrentText("my-custom-model")
dlg._retry_spin.setValue(4)
dlg._nav.setCurrentRow(3)
app.processEvents()
dlg._nav.setCurrentRow(1)
app.processEvents()
check("state-preserved-temp", abs(dlg._temperature_spin.value() - 1.25) < 1e-9,
      f"temp={dlg._temperature_spin.value()}")
check("state-preserved-model",
      dlg._model_combo.currentText() == "my-custom-model",
      f"model={dlg._model_combo.currentText()}")
check("state-preserved-retry", dlg._retry_spin.value() == 4,
      f"retry={dlg._retry_spin.value()}")

# ---------------------------------------------------------------- 控件类型
check("model-combo-editable",
      isinstance(dlg._model_combo, QComboBox) and dlg._model_combo.isEditable())
check("max-tokens-is-spinbox", isinstance(dlg._max_tokens_spin, QSpinBox))
check("temperature-is-doublespin",
      isinstance(dlg._temperature_spin, QDoubleSpinBox))
check("timeout-is-spinbox", isinstance(dlg._timeout_spin, QSpinBox))
check("max-tokens-range-step",
      (dlg._max_tokens_spin.minimum(), dlg._max_tokens_spin.maximum(),
       dlg._max_tokens_spin.singleStep()) == (256, 8192, 256))
check("temperature-range-step",
      (dlg._temperature_spin.minimum(), dlg._temperature_spin.maximum(),
       round(dlg._temperature_spin.singleStep(), 3)) == (0.0, 2.0, 0.05))
check("timeout-range", (dlg._timeout_spin.minimum(),
                        dlg._timeout_spin.maximum()) == (5, 300))
check("retry-range", (dlg._retry_spin.minimum(),
                      dlg._retry_spin.maximum()) == (0, 5))

# ---------------------------------------------------------------- 越界钳制
dlg._max_tokens_spin.setValue(99999)
check("clamp-max-tokens-high", dlg._max_tokens_spin.value() == 8192,
      f"v={dlg._max_tokens_spin.value()}")
dlg._max_tokens_spin.setValue(1)
check("clamp-max-tokens-low", dlg._max_tokens_spin.value() == 256,
      f"v={dlg._max_tokens_spin.value()}")
dlg._timeout_spin.setValue(0)
check("clamp-timeout-low", dlg._timeout_spin.value() == 5,
      f"v={dlg._timeout_spin.value()}")
dlg._timeout_spin.setValue(999)
check("clamp-timeout-high", dlg._timeout_spin.value() == 300,
      f"v={dlg._timeout_spin.value()}")
dlg._temperature_spin.setValue(9.9)
check("clamp-temp-high", dlg._temperature_spin.value() == 2.0,
      f"v={dlg._temperature_spin.value()}")
dlg._temperature_spin.setValue(-3.0)
check("clamp-temp-low", dlg._temperature_spin.value() == 0.0,
      f"v={dlg._temperature_spin.value()}")

# ---------------------------------------------------------------- 温度预设
dlg._nav.setCurrentRow(1)
app.processEvents()
preset_btns = []
row = dlg._temperature_spin.parentWidget()
for b in row.findChildren(type(dlg._save_btn)):
    if b is not dlg._save_btn and b.text() in ("精确 0.1", "均衡 0.3", "创意 0.7"):
        preset_btns.append(b)
check("preset-buttons-3", len(preset_btns) == 3,
      f"found={[b.text() for b in preset_btns]}")
for b in preset_btns:
    if b.text() == "创意 0.7":
        b.click()
        app.processEvents()
check("preset-apply-0.7", abs(dlg._temperature_spin.value() - 0.7) < 1e-9,
      f"temp={dlg._temperature_spin.value()}")

# ------------------------------------------------------------ 密钥显隐 / 复制
dlg._nav.setCurrentRow(0)
app.processEvents()
check("key-echo-password",
      dlg._api_key_edit.echoMode() == QLineEdit.EchoMode.Password)
dlg._eye_btn.setChecked(True)
app.processEvents()
check("eye-show-normal",
      dlg._api_key_edit.echoMode() == QLineEdit.EchoMode.Normal)
dlg._eye_btn.setChecked(False)
app.processEvents()
check("eye-hide-password",
      dlg._api_key_edit.echoMode() == QLineEdit.EchoMode.Password)

check("endpoint-readonly", dlg._endpoint_edit.isReadOnly())
check("endpoint-text", dlg._endpoint_edit.text() == AGNES_API_BASE)
dlg._copy_btn.click()
app.processEvents()
check("copy-to-clipboard",
      QApplication.clipboard().text() == AGNES_API_BASE,
      f"clip={QApplication.clipboard().text()[:48]}...")
check("copy-feedback", dlg._copy_btn.text() == "已复制 ✓",
      f"btn={dlg._copy_btn.text()}")

# ---------------------------------------------------------------- 窄屏 Tab
dlg.resize(560, 620)
app.processEvents()
check("compact-mode-on", dlg._compact is True, f"w={dlg.width()}")
check("body-lay-narrow", dlg._body_lay.currentIndex() == 1)
check("tabs-4-pages", dlg._tabs.count() == 4)
check("stack-drained", dlg._stack.count() == 0)
dlg._tabs.setCurrentIndex(2)
app.processEvents()
check("tab-syncs-nav", dlg._nav.currentRow() == 2,
      f"nav_row={dlg._nav.currentRow()}")
check("compact-state-kept",
      dlg._model_combo.currentText() == "my-custom-model",
      f"model={dlg._model_combo.currentText()}")

dlg.resize(680, 680)
app.processEvents()
check("wide-mode-restored", dlg._compact is False, f"w={dlg.width()}")
check("stack-restored-4", dlg._stack.count() == 4)
check("tabs-drained", dlg._tabs.count() == 0)
check("current-index-kept",
      dlg._stack.currentIndex() == 2 and dlg._nav.currentRow() == 2,
      f"stack={dlg._stack.currentIndex()}, nav={dlg._nav.currentRow()}")

# ------------------------------------------------------- 信号 / 保存（无落盘）
got = []
dlg.config_applied.connect(lambda: got.append(1))
check("signal-config-applied", len(got) == 0)  # 未 apply 前不应发射
ok = dlg._save_to_config()
app.processEvents()
check("save-ok-no-configmanager", ok is True, f"ret={ok}")
check("save-does-not-emit-signal", len(got) == 0)

# ---------------------------------------------------------------- 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M7-01 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
