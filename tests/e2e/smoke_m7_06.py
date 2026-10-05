#!/usr/bin/env python3
"""M7-06 冒烟测试：配置导入 / 导出 / 重置。

验证项：
    A. _validate_import 校验（P1 验收②：非法给出明确错误）：
       A1 非 dict / A2 schema 不匹配 / A3 版本不支持 / A4 缺 config /
       A5 类型错误（temperature 字符串）/ A6 范围越界（timeout 999）/
       A7 bool 字段传 int / A8 model 空 / A9 未知键忽略 / A10 合法通过
    B. 导出（验收①）：
       B1 文件生成且 schema/version/exported_at 齐全
       B2 config 值与 UI 一致（10 个键）
       B3 grep 不到任何密钥特征串（sk-）
       B4 导出成功弹窗提示（QMessageBox mock）
    C. 导入：
       C1 合法文件 → 控件更新 + dirty 标记 + 跳高级页
       C2 非法文件 → Toast 错误、控件不变
    D. 恢复默认（验收③）：
       D1 二次确认 Yes → 4 参数回 30/agnes-3.0-flash/1024/0.3，
          高级参数回 ADVANCED_DEFAULTS，密钥清空，dirty 清除
       D2 二次确认 No → 什么都不变
    E. 底部栏「恢复默认」按钮存在且连到 _on_reset

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m7_06.py > tests/e2e/m7_06.log 2>&1; echo rc=$?
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from futures_quant.ui.ai_settings_dialog import AIConfigDialog  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


dlg = AIConfigDialog(config=None)
dlg.show()
app.processEvents()

GOOD_CFG = {
    "model": "agnes-3.0-pro", "timeout": 60, "max_tokens": 2048,
    "temperature": 0.7, "retry": 4, "backoff_base": 2.0,
    "concurrency": 3, "proxy": "http://127.0.0.1:7890",
    "redact_log": False, "watchdog": False,
}

# ------------------------------------------------------------ A: 校验
v = dlg._validate_import
check("A1-not-dict", v([1, 2]) is not None)
check("A2-schema", v({"schema": "other", "version": 1,
                      "config": {}}) is not None)
check("A3-version", v({"schema": "quantvortex.ai-config",
                       "version": 99, "config": {}}) is not None)
check("A4-no-config", v({"schema": "quantvortex.ai-config",
                         "version": 1}) is not None)
check("A5-type-error",
      v({"schema": "quantvortex.ai-config", "version": 1,
         "config": {"temperature": "0.7"}}) is not None)
check("A6-range", v({"schema": "quantvortex.ai-config", "version": 1,
                     "config": {"timeout": 999}}) is not None)
check("A7-bool-as-int",
      v({"schema": "quantvortex.ai-config", "version": 1,
         "config": {"watchdog": 1}}) is not None)
check("A8-model-empty",
      v({"schema": "quantvortex.ai-config", "version": 1,
         "config": {"model": "  "}}) is not None)
check("A9-unknown-key-ignored",
      v({"schema": "quantvortex.ai-config", "version": 1,
         "config": {"future_key": 123}}) is None)
check("A10-valid", v({"schema": "quantvortex.ai-config", "version": 1,
                      "config": dict(GOOD_CFG)}) is None)
err_detail = v({"schema": "quantvortex.ai-config", "version": 1,
                "config": {"timeout": 999}})
check("A11-error-mentions-field", "timeout" in (err_detail or ""),
      f"err={err_detail}")

# ------------------------------------------------------------ B: 导出
TEST_KEY = "sk-test-export-9999zzzz"
dlg._api_key_edit.setText(TEST_KEY)  # UI 层面模拟已填密钥
tmpdir = tempfile.mkdtemp(dir=ROOT) if os.path.isdir(ROOT) \
    else tempfile.mkdtemp()
export_path = os.path.join(tmpdir, "export.json")
boxes = []
_orig_box = QMessageBox.information
QMessageBox.information = staticmethod(
    lambda *a, **kw: boxes.append(a))
_orig_save = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **kw: (export_path, "JSON (*.json)"))
try:
    dlg._on_export_config()
finally:
    QFileDialog.getSaveFileName = _orig_save
    QMessageBox.information = _orig_box
check("B1-file-written", os.path.isfile(export_path)
      and bool(boxes and boxes[0][1] == "导出成功"),
      f"boxes={len(boxes)}")
with open(export_path, encoding="utf-8") as f:
    raw = f.read()
    data = json.loads(raw)
check("B1-schema-fields", data.get("schema") == "quantvortex.ai-config"
      and data.get("version") == 1 and "exported_at" in data)
cfg = data.get("config", {})
check("B2-config-matches-ui",
      cfg["model"] == dlg._model_combo.currentText().strip()
      and cfg["timeout"] == dlg._timeout_spin.value()
      and cfg["max_tokens"] == dlg._max_tokens_spin.value()
      and abs(cfg["temperature"] - dlg._temperature_spin.value()) < 1e-9
      and cfg["retry"] == dlg._retry_spin.value()
      and abs(cfg["backoff_base"] - dlg._backoff_spin.value()) < 1e-9
      and cfg["concurrency"] == dlg._concurrency_spin.value()
      and cfg["proxy"] == dlg._proxy_edit.text().strip()
      and cfg["redact_log"] == dlg._redact_check.isChecked()
      and cfg["watchdog"] == dlg._watchdog_check.isChecked(),
      f"cfg={cfg}")
check("B3-no-key-in-export", "sk-" not in raw and TEST_KEY not in raw)
check("B3b-api-key-field-absent", "api_key" not in cfg)

# ------------------------------------------------------------ C: 导入
dlg._apply_current_index(1)  # 回模型页，验证导入后跳高级页
app.processEvents()
import_path = os.path.join(tmpdir, "import.json")
with open(import_path, "w", encoding="utf-8") as f:
    json.dump({"schema": "quantvortex.ai-config", "version": 1,
               "config": dict(GOOD_CFG)}, f)
_orig_open = QFileDialog.getOpenFileName
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **kw: (import_path, "JSON (*.json)"))
try:
    dlg._on_import_config()
finally:
    QFileDialog.getOpenFileName = _orig_open
app.processEvents()
check("C1-imported-values",
      dlg._model_combo.currentText() == "agnes-3.0-pro"
      and dlg._timeout_spin.value() == 60
      and dlg._max_tokens_spin.value() == 2048
      and abs(dlg._temperature_spin.value() - 0.7) < 1e-9
      and dlg._retry_spin.value() == 4
      and dlg._proxy_edit.text() == "http://127.0.0.1:7890"
      and not dlg._redact_check.isChecked(),
      f"model={dlg._model_combo.currentText()}, "
      f"timeout={dlg._timeout_spin.value()}")
check("C1b-dirty-marked", dlg._dirty is True)
check("C1c-jump-advanced", dlg._stack.currentIndex() == 2)

bad_path = os.path.join(tmpdir, "bad.json")
with open(bad_path, "w", encoding="utf-8") as f:
    json.dump({"schema": "nope", "version": 1, "config": {}}, f)
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **kw: (bad_path, "JSON (*.json)"))
before = (dlg._timeout_spin.value(), dlg._model_combo.currentText())
try:
    dlg._on_import_config()
finally:
    QFileDialog.getOpenFileName = _orig_open
app.processEvents()
check("C2-invalid-unchanged",
      (dlg._timeout_spin.value(), dlg._model_combo.currentText()) == before)

# ------------------------------------------------------------ D: 恢复默认
answers = {"ret": QMessageBox.StandardButton.Yes}
_orig_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **kw: answers["ret"])
try:
    dlg._on_reset()
finally:
    pass
app.processEvents()
check("D1-defaults-4-params",
      dlg._timeout_spin.value() == 30
      and dlg._model_combo.currentText() == "agnes-3.0-flash"
      and dlg._max_tokens_spin.value() == 1024
      and abs(dlg._temperature_spin.value() - 0.3) < 1e-9,
      f"timeout={dlg._timeout_spin.value()}, "
      f"model={dlg._model_combo.currentText()}, "
      f"tokens={dlg._max_tokens_spin.value()}, "
      f"temp={dlg._temperature_spin.value()}")
check("D1b-advanced-defaults",
      dlg._retry_spin.value() == 2
      and abs(dlg._backoff_spin.value() - 1.0) < 1e-9
      and dlg._concurrency_spin.value() == 2
      and dlg._redact_check.isChecked()
      and dlg._watchdog_check.isChecked())
check("D1c-key-cleared", dlg._api_key_edit.text() == "")
check("D1d-dirty-cleared", dlg._dirty is False
      and not dlg._dirty_badge.isVisible())

answers["ret"] = QMessageBox.StandardButton.No
dlg._timeout_spin.setValue(120)
dlg._mark_dirty()
try:
    dlg._on_reset()
finally:
    QMessageBox.question = _orig_q
app.processEvents()
check("D2-no-keeps-values", dlg._timeout_spin.value() == 120
      and dlg._dirty is True)

# ------------------------------------------------------------ E: 按钮接线
check("E-reset-btn-exists", dlg._reset_btn.text() == "恢复默认"
      and not dlg._reset_btn.isHidden())
check("E-reset-btn-connected",
      dlg._reset_btn.receivers(dlg._reset_btn.clicked) > 0,
      f"receivers={dlg._reset_btn.receivers(dlg._reset_btn.clicked)}")
check("E-io-buttons-exist",
      dlg._export_btn.text() == "导出配置 JSON"
      and dlg._import_btn.text() == "导入配置…")

# 清理临时目录
for f_ in (export_path, import_path, bad_path):
    try:
        os.remove(f_)
    except OSError:
        pass
try:
    os.rmdir(tmpdir)
except OSError:
    pass

# ------------------------------------------------------------ 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M7-06 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
