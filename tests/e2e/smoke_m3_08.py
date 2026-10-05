"""M3-08 LLM 客户端加固 —— 端到端 smoke 验收。

DoD（spec + UPGRADE_PLAN_V5.md 第 338 行）：
  ① 哨兵值 900/0.3 → Optional[int]=None / Optional[float]=None
  ② 重试：3 次退避 0.5→1.0→2.0s，仅对 Timeout/ConnectionError/5xx
  ③ 熔断：连续 5 次失败后 60s 内快速失败
  ④ print → logging，响应体经 redact 脱敏后再记
  ⑤ reload_from_config 的 int/float 包 try
  ⑥ config.py: dict(DEFAULTS) 副本 + 删除 get_all 死循环 + startswith("ai.")

DoD 硬指标：
  - mock 连续 3 次 Timeout → 第 4 次成功
  - mock 6 次失败 → 第 6 次快速失败且不发请求
  - 日志无密钥明文

运行：QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_08.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
from types import SimpleNamespace

# ---- 沙箱 sys.path 注入 ----
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


PASSED = 0
FAILED = 0
FAILURES: list[str] = []


# 假 post 返回对象
class _FakeResp:
    def __init__(self, status_code=200, text="", json_body=None):
        self.status_code = status_code
        self.text = text
        self._json_body = json_body or {}

    def json(self):
        if isinstance(self._json_body, Exception):
            raise self._json_body
        return self._json_body


# ============================================================
# Test 1: 重试 —— 前 3 次 Timeout，第 4 次成功
# ============================================================
def test_1_retry_3_timeouts_then_success() -> None:
    """M3-08 ② 硬指标：mock 连续 3 次 Timeout → 第 4 次成功。"""
    from futures_quant.ai import llm_client as L

    calls = {"n": 0}

    def fake_post(url, headers=None, data=None, timeout=None, **kw):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise TimeoutError("read timed out")
        # 第 4 次成功
        return _FakeResp(200, "", {"choices": [{"message": {"content": "hello"}}]})

    c = L.AgnesLLMClient(api_key="sk-test-abc", timeout=1)
    c._post = fake_post
    # 消除真实退避等待
    c._sleep_backoff = lambda attempt: None  # noqa: SLF001

    result = c.chat("sys", "hi")

    assert result == "hello", f"第 4 次应成功返回 hello，实际 {result!r}"
    assert calls["n"] == 4, f"应调用 4 次（3 失败 + 1 成功），实际 {calls['n']}"
    assert c.circuit.snapshot()["open"] is False, "熔断未打开"
    print(f"[1/7] PASS 3×Timeout 后第 4 次成功（calls={calls['n']}, result={result!r}）")


# ============================================================
# Test 2: 熔断 —— 6 次失败后第 6 次快速失败且不发请求
# ============================================================
def test_2_circuit_breaker_fast_fails_after_5() -> None:
    """M3-08 ③ 硬指标：mock 连续 6 次失败 → 第 6 次快速失败且不发请求。"""
    from futures_quant.ai import llm_client as L

    calls = {"n": 0}

    def fake_post(url, headers=None, data=None, timeout=None, **kw):
        calls["n"] += 1
        raise TimeoutError("always timeout")

    # 使用低阈值的独立熔断器实例（避免污染模块默认）
    c = L.AgnesLLMClient(api_key="sk-test-abc", timeout=1)
    c._post = fake_post
    c._sleep_backoff = lambda attempt: None  # noqa: SLF001

    # 前 5 次触发：每次都会走 MAX_ATTEMPTS=4 次尝试（1 成功 + 3 重试）
    # 但注意：连续 5 次 chat() 调用，每次内部 4 次重试都会 record_failure
    # 我们希望累计失败次数达到 5 就打开熔断
    results = []
    for i in range(5):
        r = c.chat("sys", "hi")
        results.append(r)
    # 此时熔断器已打开（fail_count >= threshold=5）
    assert c.circuit.snapshot()["open"] is True, (
        f"连续失败后熔断应打开，实际 open={c.circuit.snapshot()}"
    )
    post_calls_before = calls["n"]
    # 第 6 次应被熔断拦截，不再发请求
    r6 = c.chat("sys", "hi")
    assert r6 is None, f"熔断打开后应返回 None，实际 {r6!r}"
    assert calls["n"] == post_calls_before, (
        f"熔断打开后不应再调 post（前 {post_calls_before} → 后 {calls['n']}）"
    )
    print(f"[2/7] PASS 熔断后快速失败（前 {post_calls_before} 次 post 调用，第 6 次未发）")


# ============================================================
# Test 3: 哨兵值修正 —— 传 max_tokens=900 和 temperature=0.3 时应被采纳
# ============================================================
def test_3_no_sentinel_value_confusion() -> None:
    """M3-08 ①：调用方真的想传 900 或 0.3 时，payload 里就是 900/0.3。"""
    from futures_quant.ai import llm_client as L

    captured_payload = {}

    def fake_post(url, headers=None, data=None, timeout=None, **kw):
        captured_payload["payload"] = json.loads(data)
        return _FakeResp(200, "", {"choices": [{"message": {"content": "ok"}}]})

    c = L.AgnesLLMClient(api_key="sk-test-abc", timeout=1)
    c.max_tokens = 1024
    c.temperature = 0.7  # 故意设为非 0.3，验证传入值生效
    c._post = fake_post
    c._sleep_backoff = lambda attempt: None  # noqa: SLF001

    c.chat("sys", "hi", max_tokens=900, temperature=0.3)

    p = captured_payload["payload"]
    assert p["max_tokens"] == 900, (
        f"传入 max_tokens=900 应被采纳，实际 payload max_tokens={p.get('max_tokens')}"
    )
    assert abs(p["temperature"] - 0.3) < 1e-9, (
        f"传入 temperature=0.3 应被采纳，实际 payload temperature={p.get('temperature')}"
    )
    print(f"[3/7] PASS 哨兵值不冲突（max_tokens=900, temperature=0.3 都被采纳）")


# ============================================================
# Test 4: 日志无密钥明文
# ============================================================
def test_4_no_api_key_in_logs() -> None:
    """M3-08 ④ 硬指标：日志输出中不含 API 密钥明文。"""
    import logging as _logging
    from futures_quant.ai import llm_client as L

    # 用一个明显可辨的密钥，测试中不会真实发送
    secret = "sk-TEST-FIXTURE-NOT-REAL-000000"  # secret-scan: allow

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    L.logger.addHandler(handler)
    L.logger.setLevel(logging.DEBUG)
    L.logger.propagate = False

    try:
        c = L.AgnesLLMClient(api_key=secret, timeout=1)

        def fake_post(url, headers=None, data=None, timeout=None, **kw):
            return _FakeResp(500, "server error", {"error": {"message": "internal"}})

        c._post = fake_post
        c._sleep_backoff = lambda attempt: None  # noqa: SLF001
        c.chat("sys", "hi")
    finally:
        L.logger.removeHandler(handler)
        L.logger.propagate = True

    log_text = buf.getvalue()
    assert secret not in log_text, (
        f"日志含密钥明文！泄漏片段:\n{log_text}"
    )
    print(f"[4/7] PASS 日志无密钥明文（{len(log_text)} 字符日志中不含 {secret[:12]}...）")


# ============================================================
# Test 5: reload_from_config 对非法值不崩溃
# ============================================================
def test_5_reload_from_config_nonnumeric_safe() -> None:
    """M3-08 ⑤：配置里被写入非数字时不抛异常，回落到默认值。"""
    from futures_quant.ai.llm_client import reload_from_config, reset_client, get_client

    class _FakeConfig:
        def __init__(self, mapping):
            self._m = mapping

        def get(self, key, default=None):
            return self._m.get(key, default)

    # 用垃圾值模拟 UI 误填 / 旧版本残留
    bad_cfg = _FakeConfig({
        "ai.timeout": "abc",
        "ai.model": "",
        "ai.max_tokens": "1024abc",
        "ai.temperature": "not-a-number",
    })

    # 先重置单例避免测试间污染
    reset_client()
    get_client().api_key = "sk-test"  # 确保有密钥

    # 关键：不抛异常即可
    reload_from_config(bad_cfg)

    c = get_client()
    assert c.timeout == 30, f"timeout 应回落 30，实际 {c.timeout}"
    assert c.max_tokens == 1024, f"max_tokens 应回落 1024，实际 {c.max_tokens}"
    assert c.temperature == 0.3, f"temperature 应回落 0.3，实际 {c.temperature}"
    assert c.model == "agnes-3.0-flash", f"空 model 应回落默认，实际 {c.model!r}"
    print(f"[5/7] PASS reload_from_config 非法值回落默认（timeout=30, temp=0.3）")


# ============================================================
# Test 6: AIConfig — startswith("ai.") 判前缀，不污染 DEFAULTS
# ============================================================
def test_6_ai_config_prefix_and_no_global_pollution() -> None:
    """M3-08 ⑥：`ai_` 前缀不应被误认为带 `ai.` 前缀；DEFAULTS 不被 set 污染。"""
    from futures_quant.ai.config import AIConfig, DEFAULTS
    from copy import deepcopy

    # 快照 DEFAULTS，验证 set 不改它
    defaults_snapshot = deepcopy(DEFAULTS)

    cfg = AIConfig(config=None)
    # 用 "ai_foo" 这样的键，不应被拼成 "ai.ai_foo"
    cfg.set("ai_foo", 123)
    # get 相同键应能取回
    got = cfg.get("ai_foo")
    assert got == 123, (
        f"`ai_foo` 键应被正确存储/取回，实际 get('ai_foo')={got}"
        f"（旧 startswith('ai') 会把 'ai_foo' 误判成已带前缀，再拼成 'ai.ai_foo'）"
    )
    # DEFAULTS 未被污染
    assert DEFAULTS == defaults_snapshot, (
        f"AIConfig.set 污染了模块级 DEFAULTS！diff={dict(DEFAULTS)}"
    )
    print(f"[6/7] PASS AIConfig 前缀修正 + DEFAULTS 不污染（ai_foo={got}, DEFAULTS={DEFAULTS}")


# ============================================================
# Test 7: AIConfig.get_all 无死循环
# ============================================================
def test_7_get_all_no_dead_loop() -> None:
    """M3-08 ⑥：get_all 只跑一遍，非默认值返回原值、默认值返回 None。"""
    from futures_quant.ai.config import AIConfig

    class _FakeConfigMgr:
        def __init__(self, mapping):
            self._m = mapping

        def get(self, key, default=None):
            return self._m.get(key, default)

        def set(self, key, value):
            if value is None:
                self._m.pop(key, None)
            else:
                self._m[key] = value

        def save(self):
            return True

    # 一个自定义 timeout=45（非默认），其他默认
    cfg_mgr = _FakeConfigMgr({
        "ai.timeout": 45,
        "ai.model": "agnes-3.0-flash",       # 与默认同 → 应返回 None
        "ai.max_tokens": 1024,                # 与默认同 → 应返回 None
        "ai.temperature": 0.3,                # 与默认同 → 应返回 None
    })
    ai = AIConfig(config=cfg_mgr)
    result = ai.get_all()

    assert result["ai.timeout"] == 45, (
        f"非默认值应返回原值，实际 ai.timeout={result.get('ai.timeout')}"
    )
    assert result["ai.model"] is None, (
        f"与默认相同应返回 None，实际 ai.model={result.get('ai.model')}"
    )
    assert result["ai.max_tokens"] is None
    assert result["ai.temperature"] is None
    print(f"[7/7] PASS get_all 非默认=值/默认=None（{result}）")


# ============================================================
def main() -> int:
    global PASSED, FAILED
    tests = [
        test_1_retry_3_timeouts_then_success,
        test_2_circuit_breaker_fast_fails_after_5,
        test_3_no_sentinel_value_confusion,
        test_4_no_api_key_in_logs,
        test_5_reload_from_config_nonnumeric_safe,
        test_6_ai_config_prefix_and_no_global_pollution,
        test_7_get_all_no_dead_loop,
    ]
    total = len(tests)
    for t in tests:
        try:
            t()
            PASSED += 1
        except Exception as e:
            FAILED += 1
            FAILURES.append(f"{t.__name__}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")

    print(f"\n=== M3-08 smoke: {PASSED}/{total} passed ===")
    if FAILED:
        print(f"Failures ({FAILED}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
