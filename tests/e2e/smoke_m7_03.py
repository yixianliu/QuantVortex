#!/usr/bin/env python3
"""M7-03 冒烟测试：模型配置对话框信息层级与状态反馈。

验证项：
    1. 字段三层结构：控件 + 灰色 Hint（11px）+ 隐藏 Error（红色 11px）
    2. Dirty 状态：任一字段变更 → 「● 未保存」角标 + 应用按钮 primary
    3. 就地错误：清空模型名 → Error 红字显示 + 应用按钮禁用，无弹窗
    4. 修正后：Error 隐藏 + 按钮恢复
    5. 软性提示：温度 > 1.2 → 橙色提示（不阻断保存）
    6. 代理格式校验：非 http(s) 前缀 → Error + 禁用
    7. 保存中：按钮「保存中…」+ 禁用 + 自绘 spinner；完成后恢复 + 角标消失
    8. 成功 Toast：非阻断出现并 2.5s 自动消失
    9. 打包模式：密钥输入框只读 + 👁 隐藏 + 环境变量说明
   10. config_applied 信号照常发射

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m7_03.py > tests/e2e/m7_03.log 2>&1; echo rc=$?
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from futures_quant.ui.ai_settings_dialog import AIConfigDialog  # noqa: E402
from futures_quant.ui.states import Toast  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


dlg = AIConfigDialog(config=None)
dlg.show()
app.processEvents()

WRAPPED = ("api_key", "model", "max_tokens", "temperature", "timeout",
           "retry", "backoff_base", "concurrency", "proxy")

# ---------------------------------------------------------------- ① 字段结构
check("fields-registered",
      all(k in dlg._fields for k in WRAPPED),
      f"got={sorted(dlg._fields)}")
hint_ok = all(dlg._fields[k]["hint"].objectName() == "ai-hint"
              and not dlg._fields[k]["hint"].isHidden() for k in WRAPPED)
check("hints-visible-11px", hint_ok)
err_hidden = all(dlg._fields[k]["error"].isHidden() for k in WRAPPED)
check("errors-hidden-default", err_hidden)
check("field-page-index-valid",
      all(0 <= dlg._fields[k]["page"] <= 3 for k in WRAPPED))

# ---------------------------------------------------------------- ② Dirty
dlg._temperature_spin.setValue(0.9)
app.processEvents()
check("dirty-flag-set", dlg._dirty is True)
check("dirty-badge-visible", dlg._dirty_badge.isVisible(),
      f"text={dlg._dirty_badge.text()}")
check("dirty-badge-text", dlg._dirty_badge.text() == "● 未保存")
check("save-btn-primary", dlg._save_btn.objectName() == "primary")

# ------------------------------------------------------- ③④ 就地错误（无弹窗）
dlg._model_combo.setCurrentText("")
app.processEvents()
m_err = dlg._fields["model"]["error"]
check("model-error-shown", not m_err.isHidden() and bool(m_err.text()),
      f"text={m_err.text()}")
check("model-widget-error-prop",
      dlg._model_combo.property("error") is True)
check("save-btn-disabled-on-error", not dlg._save_btn.isEnabled())
dlg._model_combo.setCurrentText("agnes-3.0-flash")
app.processEvents()
check("model-error-cleared", m_err.isHidden())
check("save-btn-re-enabled", dlg._save_btn.isEnabled())

# ---------------------------------------------------------------- ⑤ 温度软提示
dlg._temperature_spin.setValue(1.5)
app.processEvents()
t_err = dlg._fields["temperature"]["error"]
check("temp-warn-shown", not t_err.isHidden() and "偏高" in t_err.text(),
      f"text={t_err.text()}")
check("temp-warn-not-blocking", dlg._save_btn.isEnabled())
dlg._temperature_spin.setValue(0.3)
app.processEvents()
check("temp-warn-cleared", t_err.isHidden())

# ---------------------------------------------------------------- ⑥ 代理校验
dlg._proxy_edit.setText("127.0.0.1:7890")
app.processEvents()
p_err = dlg._fields["proxy"]["error"]
check("proxy-error-shown", not p_err.isHidden() and "http" in p_err.text(),
      f"text={p_err.text()}")
check("proxy-blocks-save", not dlg._save_btn.isEnabled())
dlg._proxy_edit.setText("")
app.processEvents()
check("proxy-error-cleared", p_err.isHidden()
      and dlg._save_btn.isEnabled())

# --------------------------------------------------- ⑦⑧ 保存中 / Toast / 信号
got = []
dlg.config_applied.connect(lambda: got.append(1))
dlg._on_apply()
app.processEvents()
check("saving-text", dlg._save_btn.text() == "保存中…",
      f"btn={dlg._save_btn.text()}")
check("saving-disabled", not dlg._save_btn.isEnabled())
check("spinner-visible", dlg._save_spinner.isVisible())

QTest.qWait(180)
app.processEvents()
check("saving-restored", dlg._save_btn.text() == "应用并保存"
      and dlg._save_btn.isEnabled(),
      f"btn={dlg._save_btn.text()}")
check("spinner-stopped", not dlg._save_spinner.isVisible())
check("dirty-cleared", dlg._dirty is False
      and not dlg._dirty_badge.isVisible())
check("save-btn-back-secondary", dlg._save_btn.objectName() == "secondary")
toasts = dlg.findChildren(Toast)
check("toast-present", len(toasts) == 1,
      f"msg={toasts[0]._lab.text() if toasts else '-'}")
check("toast-message", bool(toasts) and "已保存并生效" in toasts[0]._lab.text())
check("signal-emitted", got == [1], f"got={got}")

QTest.qWait(2800)
app.processEvents()
check("toast-auto-dismissed", len(dlg.findChildren(Toast)) == 0)

# ------------------------------------------------------- ⑨ 打包模式只读密钥
import futures_quant.ui.ai_settings_dialog as ais  # noqa: E402

_orig_frozen = ais.is_frozen
ais.is_frozen = lambda: True
try:
    dlg2 = AIConfigDialog(config=None)
    dlg2.show()
    app.processEvents()
    check("frozen-key-readonly", dlg2._api_key_edit.isReadOnly())
    check("frozen-eye-hidden", not dlg2._eye_btn.isVisible())
    check("frozen-hint-env",
          "QV_AGNES_API_KEY" in dlg2._fields["api_key"]["hint"].text())
    dlg2.setParent(None)
    dlg2.deleteLater()
finally:
    ais.is_frozen = _orig_frozen

# ---------------------------------------------------------------- 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M7-03 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
