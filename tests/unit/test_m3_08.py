"""M3-08 LLM 客户端加固 —— pytest 形态。

由散落脚本 ``tests/test_m3_08.py``（模块级 ``PASS/FAIL`` 列表 +
``check(name,cond,detail)`` 辅助 + 结尾 ``if FAIL: sys.exit(1)``，
0 个 ``def test_*``）机械改写：每段 ``check(...)`` 收敛为
``assert cond, f"{name} — {detail}"``，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 保留 ``_Resp`` / ``_TimeoutErr`` / ``_ValueErr`` / ``_Cap`` / ``_Cfg`` /
  ``_CfgM`` 辅助；脱敏注册用 ``clear_registered_secrets`` 回收。
- 退避加速用 autouse fixture 在模块级别 patch ``_sleep_backoff``。
"""
from __future__ import annotations

import inspect
import json
import logging
import pytest

from futures_quant.ai import llm_client as L
from futures_quant.ai.config import AIConfig, DEFAULTS, AI_SECTION


# ---------------------------------------------------------------------------
# 辅助类（与散落脚本保持一致）
# ---------------------------------------------------------------------------
class _Resp:
    """模拟 requests.Response。"""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload


class _TimeoutErr(Exception):
    """模拟 requests ConnectTimeout（让客户端识别为可重试）。"""


_TimeoutErr.__name__ = "ConnectTimeout"  # 让客户端识别为可重试


class _ValueErr(Exception):
    """模拟不可重试的 ValueError。"""


_ValueErr.__name__ = "ValueError"  # 不可重试


def _ok_resp(content=" Hello "):
    """构造 200 响应。"""
    return _Resp(200, {"choices": [{"message": {"content": content}}]})


def _flaky_then_ok(fail_times, calls, exc=_TimeoutErr):
    """前 fail_times 次抛 exc，之后返回成功响应；通过外部 calls 计数。

    计数复用调用方传入的 ``calls`` 字典（与散落脚本一致：脚本里 ``calls``
    是模块级共享变量，``_flaky_then_ok`` 通过闭包改动它，断言据此校验尝试次数）。
    """

    def _post(base, headers=None, data=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc("boom")
        return _ok_resp("recovered")

    return _post


class _Cap(logging.Handler):
    """捕获 ``futures_quant.ai.llm_client`` 日志到内存。"""

    def __init__(self, sink):
        super().__init__()
        self._sink = sink

    def emit(self, record):
        self._sink.append(record.getMessage())


class _Cfg:
    """模拟 ConfigManager（仅 get）。"""

    def __init__(self, d):
        self._d = d

    def get(self, k, default=None):
        return self._d.get(k, default)


class _CfgM:
    """模拟带 ai. 前缀补全的 ConfigManager。"""

    def __init__(self):
        self.d = {"ai.timeout": 7, "ai_foo": 123}
        self.saved = 0

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v

    def save(self):
        self.saved += 1

    def as_dict(self):
        return {"ai": {"timeout": 7}}


# 测试夹具密钥：显式标注允许扫描，避免 secret-scan 误报阻断 CI。
SECRET = "sk-TEST-SECRET-ABCD1234"  # secret-scan: allow（测试夹具）


@pytest.fixture(autouse=True)
def _accelerate_backoff(monkeypatch):
    """把指数退避加速为 no-op，避免测试被真实 sleep 拖慢。"""
    monkeypatch.setattr(
        L.AgnesLLMClient,
        "_sleep_backoff",
        staticmethod(lambda attempt: None),
    )
    yield


def test_sentinel_optional():
    """① 哨兵值 900 / 0.3 → Optional；显式传参真正生效，不传回落实例配置。"""
    c = L.AgnesLLMClient(api_key="k", timeout=5)
    c.max_tokens = 1024
    c.temperature = 0.3
    seen = {}

    def _capture_post(base, headers=None, data=None, timeout=None):
        seen.update(json.loads(data.decode("utf-8")))
        return _ok_resp("ok")

    c._post = _capture_post
    c.chat("s", "u", max_tokens=900)
    assert seen.get("max_tokens") == 900, (
        f"显式传 max_tokens=900 应真正生效（旧实现会替换成 1024）— payload={seen.get('max_tokens')}"
    )
    c.chat("s", "u", temperature=0.3)
    assert abs(float(seen.get("temperature", -1)) - 0.3) < 1e-12, (
        f"显式传 temperature=0.3 应真正生效 — payload={seen.get('temperature')}"
    )
    c.chat("s", "u")
    assert seen.get("max_tokens") == 1024 and abs(seen.get("temperature") - 0.3) < 1e-12, (
        f"不传时回落实例配置（1024 / 0.3）— {seen.get('max_tokens')} / {seen.get('temperature')}"
    )
    sig = inspect.signature(L.AgnesLLMClient.chat)
    assert sig.parameters["max_tokens"].default is None and \
        sig.parameters["temperature"].default is None, \
        "签名中 max_tokens / temperature 默认值应为 None"


def test_retry_and_backoff():
    """② 重试仅对 Timeout/ConnectionError/5xx；非网络异常/4xx 不重试；退避 0.5→1→2。"""
    calls = {"n": 0}

    c2 = L.AgnesLLMClient(api_key="k", timeout=5)
    c2._post = _flaky_then_ok(3, calls)
    out = c2.chat("s", "u")
    assert out == "recovered" and calls["n"] == 4, (
        f"连续 3 次 Timeout → 第 4 次成功（共 4 次尝试）— n={calls['n']}, out={out!r}"
    )

    # 5xx 重试，4xx 不重试
    calls["n"] = 0
    c3 = L.AgnesLLMClient(api_key="k", timeout=5)
    c3._post = (lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), _Resp(500, {}, "err"))[1])
    assert c3.chat("s", "u") is None and calls["n"] == 4, (
        f"5xx 会重试至 4 次后返回 None — n={calls['n']}"
    )
    calls["n"] = 0
    c4 = L.AgnesLLMClient(api_key="k", timeout=5)
    c4._post = (lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), _Resp(401, {}, "unauth"))[1])
    assert c4.chat("s", "u") is None and calls["n"] == 1, (
        f"4xx 不重试（只发 1 次）— n={calls['n']}"
    )

    calls["n"] = 0
    c5 = L.AgnesLLMClient(api_key="k", timeout=5)
    c5._post = _flaky_then_ok(99, calls, exc=_ValueErr)
    assert c5.chat("s", "u") is None and calls["n"] == 1, (
        f"非网络异常（ValueError）不重试 — n={calls['n']}"
    )

    # 退避时长序列
    seq = []
    L.AgnesLLMClient._sleep_backoff = staticmethod(lambda attempt: seq.append(attempt))
    calls["n"] = 0
    c6 = L.AgnesLLMClient(api_key="k", timeout=5)
    c6._post = _flaky_then_ok(3, calls)
    c6.chat("s", "u")
    assert seq == [1, 2, 3], f"退避发生在第 1/2/3 次尝试后（共 3 次 sleep）— {seq}"
    delays = [min(L.BACKOFF_CAP, L.BACKOFF_BASE * (2 ** (a - 1))) for a in [1, 2, 3]]
    assert delays == [0.5, 1.0, 2.0], f"退避时长 0.5s → 1.0s → 2.0s — {delays}"
    L.AgnesLLMClient._sleep_backoff = staticmethod(lambda attempt: None)


def test_circuit_breaker():
    """③ 连续 5 次失败后熔断打开；冷却期内快速失败且不发请求；reset 后恢复。"""
    calls = {"n": 0}
    cb = L.CircuitBreaker(threshold=5, cooldown=60.0)
    c7 = L.AgnesLLMClient(api_key="k", timeout=5)
    c7.circuit = cb
    c7._post = _flaky_then_ok(10_000, calls)
    for _ in range(5):
        c7.chat("s", "u")
    assert cb.snapshot()["open"] is True, f"5 次调用后熔断打开 — {cb.snapshot()}"

    before = calls["n"]
    out7 = c7.chat("s", "u")
    assert out7 is None, "第 6 次调用被快速失败（返回 None）"
    assert calls["n"] == before, f"第 6 次调用没有发出请求 — {before} → {calls['n']}"

    # 成功后清零
    c7._post = lambda *a, **k: _ok_resp("ok")
    cb.reset()
    assert cb.snapshot()["open"] is False, "reset 后熔断关闭"
    assert c7.chat("s", "u") == "ok", "成功后可正常返回"

    # 计数达到阈值前不熔断
    cb2 = L.CircuitBreaker(threshold=5, cooldown=60.0)
    c8 = L.AgnesLLMClient(api_key="k", timeout=5)
    c8.circuit = cb2
    c8._post = _flaky_then_ok(10_000, calls)
    for _ in range(4):
        c8.chat("s", "u")
    assert cb2.snapshot()["open"] is False, (
        f"失败 4 次时熔断仍未打开（阈值 5）— {cb2.snapshot()}"
    )


def test_log_redaction():
    """④ 日志脱敏（日志中不出现密钥明文，脱敏函数确实生效，源码无裸 print）。"""
    from futures_quant.utils.redact import clear_registered_secrets, register_secret

    records = []
    lg = logging.getLogger("futures_quant.ai.llm_client")
    cap = _Cap(records)
    lg.addHandler(cap)
    try:
        register_secret(SECRET)
        c9 = L.AgnesLLMClient(api_key=SECRET, timeout=5)
        # 响应体里回显密钥（模拟上游把请求内容原样返回）
        c9._post = lambda *a, **k: _Resp(400, {}, f'{{"error":"bad key {SECRET}"}}')
        c9.chat("s", "u")
    finally:
        lg.removeHandler(cap)
        clear_registered_secrets()

    assert len(records) > 0, f"日志已记录失败 — {records[:1]}"
    assert all(SECRET not in m for m in records), "; ".join(records)[:160]
    assert SECRET not in L._redact(f"x {SECRET} y"), L._redact(f"x {SECRET} y")
    src = inspect.getsource(L)
    assert "print(" not in src, "llm_client 源码中不再有裸 print("


def test_reload_from_config():
    """⑤ reload_from_config 的 int/float 包 try：脏配置不抛异常落到默认值。"""
    L.reset_client()
    L.reload_from_config(_Cfg({"ai.timeout": "abc", "ai.model": None,
                               "ai.max_tokens": "12x", "ai.temperature": "oops"}))
    cc = L.get_client()
    assert cc.timeout == 30 and cc.model == "agnes-3.0-flash" \
        and cc.max_tokens == 1024 and abs(cc.temperature - 0.3) < 1e-12, (
        f"脏配置不抛异常且落到默认值 — {cc.timeout}/{cc.model}/{cc.max_tokens}/{cc.temperature}"
    )
    L.reload_from_config(_Cfg({"ai.timeout": 45, "ai.model": "m2",
                               "ai.max_tokens": 512, "ai.temperature": 0.9}))
    assert cc.timeout == 45 and cc.model == "m2" and cc.max_tokens == 512 \
        and abs(cc.temperature - 0.9) < 1e-12, (
        f"正常配置生效 — {cc.timeout}/{cc.model}/{cc.max_tokens}/{cc.temperature}"
    )
    L.reload_from_config(None)
    assert cc.timeout == 30 and cc.max_tokens == 1024, "config=None 回落到默认值"


def test_aiconfig_no_pollution():
    """⑥-1 AIConfig：set 不污染模块级 DEFAULTS；实例读到自己设的值；新实例不受影响。"""
    before_defaults = dict(DEFAULTS)
    a1 = AIConfig(None)
    a1.set("timeout", 99)
    assert DEFAULTS == before_defaults, f"无 ConfigManager 时 set 不污染模块级 DEFAULTS — {DEFAULTS}"
    assert a1.get("timeout") == 99, f"实例内可读到自己设的值 — {a1.get('timeout')}"
    a2 = AIConfig(None)
    assert a2.get("timeout") == 30, f"新实例不受前一个实例影响（读到默认 30）— {a2.get('timeout')}"


def test_aiconfig_prefix_and_get_all():
    """⑥-2 AIConfig：前缀补全、get_all 覆盖默认键、与默认相同项返回 None、无死循环。"""
    cm = _CfgM()
    a3 = AIConfig(cm)
    assert a3.get("timeout") == 7, f"get('timeout') 走 ai.timeout — {a3.get('timeout')}"
    assert a3.get("ai.timeout") == 7, "get('ai.timeout') 也正确"
    try:
        a3.set("ai_foo", 1)
        saved_key = "ai.ai_foo" in cm.d
    except Exception:  # noqa: BLE001
        saved_key = False
    assert saved_key, f"'ai_foo' 应被补全为 'ai.ai_foo'（旧实现原样存成 ai_foo）— {[k for k in cm.d if 'foo' in k]}"

    al = a3.get_all()
    assert set(al.keys()) == set(DEFAULTS.keys()), f"get_all 覆盖全部默认键 — {al}"
    assert al.get("ai.model") is None, f"get_all 中与默认值相同的项返回 None — {al}"
    csrc = inspect.getsource(AIConfig)
    assert csrc.count("for key, default in DEFAULTS.items()") == 1, (
        f"get_all 中不再有重复的第二个 for 循环（死代码已删）— "
        f"count={csrc.count('for key, default in DEFAULTS.items()')}"
    )


def test_no_key_degrade():
    """⑦ 未配置密钥 / 无 requests 时安全降级为 None；api_status 含 circuit 字段。"""
    c10 = L.AgnesLLMClient(api_key=None)
    assert c10.chat("s", "u") is None, "无密钥 → chat 返回 None"
    c11 = L.AgnesLLMClient(api_key="k")
    c11._post = lambda *a, **k: _ok_resp("ok")
    assert c11.chat("s", "u") == "ok", "有密钥 → 正常返回"
    st = L.api_status()
    assert "circuit" in st, f"api_status 含 circuit 字段 — {st}"