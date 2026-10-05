# -*- coding: utf-8 -*-
"""M3-09：llm_client 单元测试（M3-08 加固项的回归门禁）。

锁定：
  * 端点构造（base / headers / payload 字段）；
  * timeout 透传到 requests.post；
  * 503 model_not_found 降级为 None 而非抛异常；
  * 哨兵值移除：显式的 900 / 0.3 不会被替换；
  * 重试只对 Timeout/5xx；熔断达阈值后不发请求；
  * 日志不含密钥明文。
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai import llm_client as L  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload


class _TimeoutErr(Exception):
    pass


_TimeoutErr.__name__ = "ConnectTimeout"


class _ValueErr(Exception):
    pass


_ValueErr.__name__ = "ValueError"


def _ok(content="hi"):
    return _Resp(200, {"choices": [{"message": {"content": content}}]})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """加速：退避不真的 sleep。"""
    monkeypatch.setattr(L.AgnesLLMClient, "_sleep_backoff",
                        staticmethod(lambda attempt: None))


def _client(post=None, **kw):
    c = L.AgnesLLMClient(api_key="k", **kw)
    if post is not None:
        c._post = post
    return c


def test_endpoint_and_payload_construction():
    seen = {}

    def post(base, headers=None, data=None, timeout=None):
        import json as _json
        seen.update({"base": base, "headers": headers,
                     "payload": _json.loads(data.decode("utf-8")),
                     "timeout": timeout})
        return _ok()

    c = _client(post, timeout=13)
    c.chat("sys", "usr")
    assert seen["base"] == L.DEFAULT_BASE
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert "application/json" in seen["headers"]["Content-Type"]
    assert seen["payload"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert seen["payload"]["model"] == "agnes-3.0-flash"
    assert set(seen["payload"]) == {"model", "messages", "max_tokens", "temperature"}


def test_timeout_is_passed_through():
    seen = {}

    def post(base, headers=None, data=None, timeout=None):
        seen["timeout"] = timeout
        return _ok()

    c = _client(post, timeout=7)
    c.chat("s", "u")
    assert seen["timeout"] == 7


def test_503_model_not_found_degrades_to_none():
    def post(*a, **k):
        return _Resp(503, {"error": {"code": "model_not_found"}}, '{"error":...}')

    c = _client(post)
    assert c.chat("s", "u") is None


def test_503_other_code_still_none_without_retry():
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        return _Resp(503, {"error": {"code": "upstream_busy"}}, "busy")

    c = _client(post)
    # 非 model_not_found 的 503 属 5xx → 会重试至 MAX_ATTEMPTS
    assert c.chat("s", "u") is None
    assert calls["n"] == L.MAX_ATTEMPTS


def test_sentinel_values_removed():
    seen = {}

    def post(base, headers=None, data=None, timeout=None):
        import json as _json
        seen.update(_json.loads(data.decode("utf-8")))
        return _ok()

    c = _client(post)
    c.max_tokens = 1024
    c.chat("s", "u", max_tokens=900)
    assert seen["max_tokens"] == 900          # 旧实现会被换成 1024
    c.chat("s", "u", temperature=0.3)
    assert abs(seen["temperature"] - 0.3) < 1e-12


def test_retry_then_success():
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise _TimeoutErr("timeout")
        return _ok("recovered")

    c = _client(post)
    assert c.chat("s", "u") == "recovered"
    assert calls["n"] == 4                     # 首发 + 3 次重试


def test_no_retry_on_4xx_or_value_error():
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        return _Resp(401, {}, "unauthorized")

    assert _client(post).chat("s", "u") is None
    assert calls["n"] == 1

    calls["n"] = 0

    def post2(*a, **k):
        calls["n"] += 1
        raise _ValueErr("bad")

    assert _client(post2).chat("s", "u") is None
    assert calls["n"] == 1


def test_circuit_breaker_blocks_requests():
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        raise _TimeoutErr("down")

    c = _client(post)
    for _ in range(L.CB_FAIL_THRESHOLD):
        assert c.chat("s", "u") is None
    before = calls["n"]
    assert c.circuit.snapshot()["open"] is True
    # 熔断打开后：不发请求
    assert c.chat("s", "u") is None
    assert calls["n"] == before


def test_success_resets_circuit():
    c = _client(lambda *a, **k: _ok("ok"))
    c.circuit.record_failure()
    c.circuit.record_failure()
    assert c.circuit.snapshot()["fail_count"] == 2
    assert c.chat("s", "u") == "ok"
    assert c.circuit.snapshot()["fail_count"] == 0
    assert c.circuit.snapshot()["open"] is False


def test_unavailable_without_key():
    assert L.AgnesLLMClient(api_key=None).chat("s", "u") is None
    assert L.AgnesLLMClient(api_key="").chat("s", "u") is None


def test_log_has_no_secret(monkeypatch, caplog):
    """响应体回显密钥时，日志里不得出现明文。"""
    from futures_quant.utils.redact import register_secret

    secret = "sk-UNIT-SECRET-9999"  # secret-scan: allow（测试夹具）
    register_secret(secret)
    c = _client(lambda *a, **k: _Resp(400, {}, f'{{"e":"key {secret}"}}'))
    c.api_key = secret
    with caplog.at_level("WARNING", logger="futures_quant.ai.llm_client"):
        c.chat("s", "u")
    assert caplog.records
    assert all(secret not in r.getMessage() for r in caplog.records)


def test_api_status_exposes_circuit():
    st = L.api_status()
    assert "circuit" in st and "usable" in st and "requests_available" in st
    assert set(st["circuit"]) >= {"fail_count", "open", "threshold"}


def test_backoff_schedule():
    assert [min(L.BACKOFF_CAP, L.BACKOFF_BASE * 2 ** i) for i in range(3)] == [0.5, 1.0, 2.0]


def test_reload_from_config_tolerates_dirty_values():
    class _Cfg:
        def get(self, k, default=None):
            return {"ai.timeout": "abc", "ai.model": None,
                    "ai.max_tokens": "xx", "ai.temperature": "yy"}.get(k, default)

    L.reset_client()
    L.reload_from_config(_Cfg())
    c = L.get_client()
    assert c.timeout == 30 and c.max_tokens == 1024
    assert abs(c.temperature - 0.3) < 1e-12
    assert np.isfinite(c.temperature)
