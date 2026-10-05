#!/usr/bin/env python3
"""M7-05 冒烟测试：诊断页（第四分段）。

验证项：
    1. 诊断信息 8 项齐全且已填充（SDK 版本 / requests 可用性 / 端点 /
       生效参数 / 密钥来源 / 密钥指纹 / 环境变量注入 / 降级状态）
    2. 密钥指纹只显示末 4 位，任何标签/剪贴板 grep 不到密钥明文（验收①）
    3. 无密钥 → 降级状态显示「未配置 → AI 功能将降级为本地规则」（验收②）
    4. 复制诊断信息 → 剪贴板含全部字段名、不含密钥明文
    5. key_source()：memory / env / none 三态
    6. 打开日志目录 → QDesktopServices.openUrl 收到 logs/ 绝对路径且目录已建
    7. 系统诊断 → 无接收者时就地弹环境信息（QMessageBox mock），有接收者时
       只发信号不弹框
    8. requests 缺失场景（monkeypatch 模块级 requests=None）→ 显示 ✗ 不可用

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m7_05.py > tests/e2e/m7_05.log 2>&1; echo rc=$?
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import futures_quant.ui.ai_settings_dialog as ais  # noqa: E402
from futures_quant.ai.config import AIConfig  # noqa: E402
from futures_quant.ui.ai_settings_dialog import AIConfigDialog  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


TEST_KEY = "sk-live-1234567890abcdefgh"

dlg = AIConfigDialog(config=None)
dlg.show()
app.processEvents()
dlg._apply_current_index(3)
app.processEvents()

# ------------------------------------------------- 1. 八项齐全且已填充
EXPECTED = ("SDK 版本", "requests 可用性", "端点", "生效参数",
            "密钥来源", "密钥指纹", "环境变量注入", "降级状态")
check("diag-labels-8", set(dlg._diag_labels) == set(EXPECTED),
      f"got={sorted(dlg._diag_labels)}")
filled = all(dlg._diag_labels[n].text() not in ("", "…")
             for n in EXPECTED)
check("diag-filled", filled,
      f"vals={ {k: v.text() for k, v in dlg._diag_labels.items()} }")
check("sdk-version-shown",
      "requests" in dlg._diag_labels["SDK 版本"].text()
      and dlg._diag_labels["SDK 版本"].text() != "requests 不可用")
check("requests-usability-ok",
      "✓" in dlg._diag_labels["requests 可用性"].text())
check("endpoint-shown",
      "api.agnes-ai.cn" in dlg._diag_labels["端点"].text())

# --------------------------------------- 3. 无密钥 → 降级文案（验收②）
check("no-key-degrade-text",
      "降级为本地规则" in dlg._diag_labels["降级状态"].text()
      and "未配置" in dlg._diag_labels["降级状态"].text(),
      f"degrade={dlg._diag_labels['降级状态'].text()}")
check("no-key-fingerprint", dlg._diag_labels["密钥指纹"].text() == "未配置")

# ------------------------------- 2. 有密钥 → 指纹末4位，全文不出现（验收①）
dlg._api_key_edit.setText(TEST_KEY)
dlg._fields["api_key"]["widget"].setFocus()  # no-op，仅保持结构
from futures_quant.ai.config import get_ai_config  # noqa: E402
get_ai_config(None).set_api_key(TEST_KEY)
dlg._refresh_diag_info()
app.processEvents()
fp = dlg._diag_labels["密钥指纹"].text()
check("fingerprint-last4", fp == "…efgh", f"fp={fp}")
leaked_labels = [n for n, lbl in dlg._diag_labels.items()
                 if TEST_KEY in lbl.text()]
check("no-full-key-in-labels", not leaked_labels,
      f"leaked={leaked_labels}")

# -------------------------------------------- 4. 复制诊断（验收① grep）
dlg._on_copy_diag()
app.processEvents()
clip = QApplication.clipboard().text()
check("copy-contains-fields",
      all(k in clip for k in ("端点", "密钥指纹", "降级状态")),
      f"clip_len={len(clip)}")
check("copy-no-full-key", TEST_KEY not in clip)

# ------------------------------------------------------- 5. key_source
check("key-source-memory", get_ai_config(None).key_source() == "memory")
os.environ["QV_AGNES_API_KEY"] = "sk-env-aaaabbbbccccdddd"
try:
    fresh = AIConfig(None)  # 内存无密钥的新实例 → 回落 env
    check("key-source-env", fresh.key_source() == "env")
    fresh._api_key = None
    check("key-source-none-after-clear", fresh.key_source() == "env")
    del os.environ["QV_AGNES_API_KEY"]
    fresh2 = AIConfig(None)
    check("key-source-none", fresh2.key_source() == "none")
finally:
    os.environ.pop("QV_AGNES_API_KEY", None)
get_ai_config(None).set_api_key(None)  # 清理，回未配置态
dlg._refresh_diag_info()

# ------------------------------------------- 6. 打开日志目录（mock openUrl）
opened = []
_orig_open = ais.QDesktopServices.openUrl
ais.QDesktopServices.openUrl = staticmethod(
    lambda url: opened.append(url))
try:
    dlg._on_open_log_dir()
finally:
    ais.QDesktopServices.openUrl = _orig_open
log_dir = os.path.join(os.getcwd(), "logs")
check("open-log-dir-called", len(opened) == 1
      and isinstance(opened[0], QUrl)
      and os.path.normcase(os.path.normpath(opened[0].toLocalFile()))
      == os.path.normcase(os.path.normpath(log_dir)),
      f"url={opened[0].toLocalFile() if opened else '-'}")
check("log-dir-created", os.path.isdir(log_dir))

# ------------------------------------------------------- 7. 系统诊断联动
got = []
dlg.system_diag_requested.connect(lambda: got.append(1))
shown = []
_orig_box = QMessageBox.information
QMessageBox.information = staticmethod(
    lambda *a, **kw: shown.append(a))
try:
    dlg._on_system_diag()  # 有接收者 → 只发信号，不弹框
    check("sysdiag-signal-emitted", got == [1])
    check("sysdiag-no-dialog-when-connected", not shown)
    dlg.system_diag_requested.disconnect()
    dlg._on_system_diag()  # 无接收者 → 就地显示（mock）
finally:
    QMessageBox.information = _orig_box
check("sysdiag-fallback-dialog", len(shown) == 1
      and any("Python" in str(arg) for arg in shown[0]),
      f"args={[str(x)[:40] for x in shown[0]] if shown else '-'}")

# ----------------------------------- 8. requests 缺失 → ✗ 不可用
_orig_requests = ais.requests
ais.requests = None
try:
    dlg._refresh_diag_info()
    check("requests-missing-unusable",
          "✗" in dlg._diag_labels["requests 可用性"].text()
          and "不可用" in dlg._diag_labels["SDK 版本"].text())
finally:
    ais.requests = _orig_requests
dlg._refresh_diag_info()

# ------------------------------------------------------------ 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M7-05 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
