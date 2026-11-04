#!/usr/bin/env python3
"""M7-04 冒烟测试：连通性测试体验升级。

验证项：
    A. probe()（复用 M3-08 重试与熔断，_post 注入无真实网络）：
       A1 200 → ok + 状态码 + 耗时 + 模型名
       A2 401 → 不重试（attempts=1）+ reason HTTP 401 + 计入熔断
       A3 503×2 → 200 → 自动重试成功（attempts=3）
       A4 Timeout×4 → 耗尽（attempts=4）+ reason Timeout + 熔断计数
       A5 should_abort → cancelled，不计历史
       A6 连续失败 5 次 → 熔断打开 → reason circuit_open 且不发请求
       A7 无密钥 → reason no_key
    B. 对话框（FakeClient 注入）：
       B1 成功结果卡四元组：HTTP 200 ✓ / 143 ms / 模型 / 时间
       B2 原始响应折叠区：默认收起 → 展开 → 收起
       B3 失败 503 → 建议文案「服务不可用」
       B4 历史列表：最新在前、最多 5 条
       B5 取消：测试中再点 → cancelled 路径不记历史
       B6 未配置密钥 → 就地建议（无 QMessageBox）

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m7_04.py > tests/e2e/m7_04.log 2>&1; echo rc=$?
"""
import sys
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import futures_quant.ai.llm_client as llm  # noqa: E402
from futures_quant.ai.llm_client import AgnesLLMClient  # noqa: E402
from futures_quant.ui.ai_settings_dialog import AIConfigDialog  # noqa: E402

app = QApplication.instance() or QApplication([])

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


# 重试退避置零（否则 503/Timeout 用例要真睡 0.5~2s）
AgnesLLMClient._sleep_backoff = staticmethod(lambda attempt: None)


class _FakeResp:
    def __init__(self, status, text='{"model": "agnes-3.0-flash"}'):
        self.status_code = status
        self.text = text

    def json(self):
        import json as _j
        return _j.loads(self.text)


def _mk_client(post_calls):
    c = AgnesLLMClient(api_key="sk-test-1234567890")  # secret-scan: allow（测试夹具）
    outcomes = []

    def post(url, **kwargs):
        post_calls.append(1)
        return outcomes.pop(0)

    c._post = post
    return c, outcomes


# ------------------------------------------------------------ A1: 200
calls = []
c, outcomes = _mk_client(calls)
outcomes.append(_FakeResp(200))
r = c.probe()
check("A1-200-ok", r["ok"] and r["status"] == 200 and r["attempts"] == 1,
      f"r={ {k: r[k] for k in ('ok', 'status', 'attempts')} }")
check("A1-elapsed-ms", isinstance(r["elapsed_ms"], int) and r["elapsed_ms"] >= 0,
      f"ms={r['elapsed_ms']}")
check("A1-model", "agnes" in r["model"], f"model={r['model']}")
check("A1-time-format", len(r["time"]) == 19, f"time={r['time']}")

# ------------------------------------------------------------ A2: 401 不重试
calls = []
c, outcomes = _mk_client(calls)
outcomes.append(_FakeResp(401, '{"error": "unauthorized"}'))
r = c.probe()
check("A2-401-no-retry",
      not r["ok"] and r["status"] == 401 and r["attempts"] == 1
      and r["reason"] == "HTTP 401",
      f"attempts={r['attempts']}, reason={r['reason']}")
check("A2-body-redacted-present", bool(r["body"]) and "unauthorized" in r["body"])

# ------------------------------------------------------------ A3: 503×2→200 重试
calls = []
c, outcomes = _mk_client(calls)
outcomes.extend([_FakeResp(503, "svc down"), _FakeResp(503, "svc down"),
                 _FakeResp(200)])
r = c.probe()
check("A3-503-retry-then-200",
      r["ok"] and r["attempts"] == 3,
      f"attempts={r['attempts']}, ok={r['ok']}")

# ------------------------------------------------------------ A4: Timeout 耗尽
calls = []
c, outcomes = _mk_client(calls)


def raise_timeout(url, **kwargs):
    calls.append(1)
    raise TimeoutError("timed out")


c._post = raise_timeout
r = c.probe()
check("A4-timeout-exhausted",
      not r["ok"] and r["reason"] == "TimeoutError" and r["attempts"] == 4,
      f"attempts={r['attempts']}, reason={r['reason']}")

# ------------------------------------------------------------ A5: 取消
calls = []
c, outcomes = _mk_client(calls)
outcomes.extend([_FakeResp(503)] * 4)
r = c.probe(should_abort=lambda: True)
check("A5-cancelled", r["cancelled"] and not r["ok"] and r["attempts"] == 0,
      f"cancelled={r['cancelled']}, attempts={r['attempts']}")

# ------------------------------------------------------------ A6: 熔断
c = AgnesLLMClient(api_key="sk-test-1234567890")  # secret-scan: allow（测试夹具）
c._post = lambda url, **kw: (_ for _ in ()).throw(AssertionError("不应发请求"))
for _ in range(5):
    c.circuit.record_failure()
r = c.probe()
check("A6-circuit-open",
      r["breaker_open"] and r["reason"] == "circuit_open" and not r["ok"],
      f"reason={r['reason']}")

# ------------------------------------------------------------ A7: 无密钥
c = AgnesLLMClient(api_key=None)
r = c.probe()
check("A7-no-key", r["reason"] == "no_key" and not r["ok"])

# ============================================================ 对话框部分
dlg = AIConfigDialog(config=None)
dlg.show()
app.processEvents()
dlg._apply_current_index(3)  # 诊断页
app.processEvents()

_now = time.strftime("%Y-%m-%d %H:%M:%S")


class FakeClient:
    """probe 结果队列注入；wait_cancel 模式模拟长请求直至收到取消。"""

    def __init__(self, results=None, wait_cancel=False):
        self._results = list(results or [])
        self._wait_cancel = wait_cancel
        self.model = "agnes-3.0-flash"
        self.api_key = "sk-test"
        # api_status() 需要：避免 _refresh_status 里的噪音
        self.base = llm.DEFAULT_BASE
        self.timeout = 30
        self.max_tokens = 1024
        self.temperature = 0.3
        self.circuit = llm.CircuitBreaker()

    def available(self):
        return True

    def probe(self, should_abort=None):
        if self._wait_cancel:
            while should_abort is None or not should_abort():
                time.sleep(0.02)
            return {"ok": False, "status": 0, "elapsed_ms": 120,
                    "model": self.model, "time": _now, "reason": "",
                    "body": "", "attempts": 1, "cancelled": True,
                    "breaker_open": False}
        if not self._results:
            return {"ok": False, "status": 0, "elapsed_ms": 0,
                    "model": self.model, "time": _now, "reason": "no_key",
                    "body": "", "attempts": 0, "cancelled": False,
                    "breaker_open": False}
        return self._results.pop(0)


def _patch_client(client):
    llm.get_client = lambda: client


OK_RES = {"ok": True, "status": 200, "elapsed_ms": 143,
          "model": "agnes-3.0-flash", "time": _now, "reason": "",
          "body": '{"model": "agnes-3.0-flash", "choices": []}',
          "attempts": 1, "cancelled": False, "breaker_open": False}

# ------------------------------------------------------------ B1: 成功结果卡
fc = FakeClient([dict(OK_RES)])
_patch_client(fc)
dlg._on_test()
QTest.qWait(400)
app.processEvents()
summary = dlg._test_summary.text()
check("B1-summary-quadruple",
      "HTTP 200 ✓" in summary and "143 ms" in summary
      and "agnes-3.0-flash" in summary and _now in summary,
      f"summary={summary}")
check("B1-advice-ok", "连接正常" in dlg._test_advice.text())
check("B1-raw-toggle-shown", dlg._raw_toggle.isVisible()
      and not dlg._raw_view.isVisible())
check("B1-history-1", dlg._history_list.count() == 1)
check("B1-signal-refreshed", dlg._test_state == "idle")

# ------------------------------------------------------------ B2: 折叠区
dlg._raw_toggle.click()
app.processEvents()
check("B2-raw-expanded", dlg._raw_view.isVisible()
      and "agnes" in dlg._raw_view.toPlainText())
dlg._raw_toggle.click()
app.processEvents()
check("B2-raw-collapsed", not dlg._raw_view.isVisible())

# ------------------------------------------------------------ B3: 503 失败
fc = FakeClient([{**OK_RES, "ok": False, "status": 503, "elapsed_ms": 210,
                  "reason": "HTTP 503",
                  "body": '{"error": {"code": "model_not_found"}}'}])
_patch_client(fc)
dlg._on_test()
QTest.qWait(400)
app.processEvents()
summary = dlg._test_summary.text()
check("B3-503-summary", "HTTP 503 ✗" in summary, f"summary={summary}")
check("B3-503-advice", "服务不可用" in dlg._test_advice.text(),
      f"advice={dlg._test_advice.text()}")
check("B3-history-2-newest-first",
      dlg._history_list.count() == 2
      and "503" in dlg._history_list.item(0).text()
      and "200" in dlg._history_list.item(1).text(),
      f"item0={dlg._history_list.item(0).text()}")

# ------------------------------------------------------------ B4: 历史上限 5
for i in range(4):
    dlg._show_test_result({**OK_RES, "elapsed_ms": 100 + i})
app.processEvents()
check("B4-history-capped-5", dlg._history_list.count() == 5
      and len(dlg._test_history) == 5,
      f"count={dlg._history_list.count()}")
check("B4-newest-first",
      "103 ms" in dlg._history_list.item(0).text(),
      f"item0={dlg._history_list.item(0).text()}")

# ------------------------------------------------------------ B5: 取消流程
fc = FakeClient(wait_cancel=True)
_patch_client(fc)
dlg._on_test()
QTest.qWait(200)
app.processEvents()
check("B5-running-state", dlg._test_state == "running"
      and "取消" in dlg._test_btn.text()
      and dlg._test_spinner.isVisible(),
      f"btn={dlg._test_btn.text()}")
dlg._on_test()  # 再次点击 = 请求取消
QTest.qWait(600)
app.processEvents()
check("B5-cancelled-back-idle", dlg._test_state == "idle"
      and dlg._test_btn.text() == "测试连接",
      f"state={dlg._test_state}")
check("B5-cancel-summary", "取消" in dlg._test_summary.text(),
      f"summary={dlg._test_summary.text()}")
check("B5-cancel-not-in-history", len(dlg._test_history) == 5)

# ------------------------------------------------------------ B6: 无密钥
fc = FakeClient()
fc.available = lambda: False
_patch_client(fc)
dlg._on_test()
app.processEvents()
check("B6-nokey-inline-advice",
      "未配置 API 密钥" in dlg._test_advice.text()
      and dlg._test_state == "idle",
      f"advice={dlg._test_advice.text()}")
check("B6-jump-diag-page", dlg._stack.currentIndex() == 3)

# ------------------------------------------------------------ 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M7-04 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
