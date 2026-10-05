"""M3-08 验证：LLM 客户端加固。

验收点（对应 UPGRADE_PLAN_V5 M3-08）：
  ① 哨兵值 900 / 0.3 → Optional[int]/Optional[float] = None；
  ② 重试：手写退避（首发 + 3 次重试，0.5s→2s），仅对 Timeout/ConnectionError/5xx；
  ③ 熔断：连续 5 次失败后 60s 内快速失败（不发请求）；
  ④ print() → logging，响应体经 utils/redact 脱敏（日志无密钥明文）；
  ⑤ reload_from_config 的 int/float 包 try；
  ⑥ config.py：改 dict(DEFAULTS) 再改、删死循环、startswith("ai.")。
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


# ---------------- 假 requests / 假响应 ----------------
class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload


class _TimeoutErr(Exception):
    pass


_TimeoutErr.__name__ = "ConnectTimeout"     # 让客户端识别为可重试


class _ValueErr(Exception):
    pass


_ValueErr.__name__ = "ValueError"           # 不可重试


def _ok_resp(content=" Hello "):
    return _Resp(200, {"choices": [{"message": {"content": content}}]})


from futures_quant.ai import llm_client as L  # noqa: E402

print("\n测试 ①: 哨兵值改为 Optional（900 / 0.3 不再被吞掉）")
c = L.AgnesLLMClient(api_key="k", timeout=5)
c.max_tokens = 1024
c.temperature = 0.3
seen = {}


def _capture_post(base, headers=None, data=None, timeout=None):
    """处理capturepost。"""
    import json as _json
    seen.update(_json.loads(data.decode("utf-8")))
    return _ok_resp("ok")


c._post = _capture_post
c.chat("s", "u", max_tokens=900)
check("显式传 max_tokens=900 时真正生效（旧实现会被替换成 1024）",
      seen.get("max_tokens") == 900, f"payload={seen.get('max_tokens')}")
c.chat("s", "u", temperature=0.3)
check("显式传 temperature=0.3 时真正生效",
      abs(float(seen.get("temperature", -1)) - 0.3) < 1e-12,
      f"payload={seen.get('temperature')}")
c.chat("s", "u")
check("不传时回落实例配置（1024 / 0.3）",
      seen.get("max_tokens") == 1024 and abs(seen.get("temperature") - 0.3) < 1e-12,
      f"{seen.get('max_tokens')} / {seen.get('temperature')}")
import inspect  # noqa: E402

sig = inspect.signature(L.AgnesLLMClient.chat)
check("签名中 max_tokens / temperature 默认值为 None",
      sig.parameters["max_tokens"].default is None
      and sig.parameters["temperature"].default is None)

print("\n测试 ②: 重试与退避（仅对 Timeout/ConnectionError/5xx）")
calls = {"n": 0}

L.AgnesLLMClient._sleep_backoff = staticmethod(lambda attempt: None)   # 加速


def _flaky_then_ok(fail_times, exc=_TimeoutErr):
    """处理flakythenok。"""
    def _post(base, headers=None, data=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc("boom")
        return _ok_resp("recovered")
    return _post


c2 = L.AgnesLLMClient(api_key="k", timeout=5)
c2._post = _flaky_then_ok(3)
out = c2.chat("s", "u")
check("连续 3 次 Timeout → 第 4 次成功（共 4 次尝试）",
      out == "recovered" and calls["n"] == 4, f"n={calls['n']}, out={out!r}")

# 5xx 重试，4xx 不重试
calls["n"] = 0
c3 = L.AgnesLLMClient(api_key="k", timeout=5)
c3._post = (lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), _Resp(500, {}, "err"))[1])
check("5xx 会重试至 4 次后返回 None", c3.chat("s", "u") is None and calls["n"] == 4,
      f"n={calls['n']}")
calls["n"] = 0
c4 = L.AgnesLLMClient(api_key="k", timeout=5)
c4._post = (lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), _Resp(401, {}, "unauth"))[1])
check("4xx 不重试（只发 1 次）", c4.chat("s", "u") is None and calls["n"] == 1,
      f"n={calls['n']}")

calls["n"] = 0
c5 = L.AgnesLLMClient(api_key="k", timeout=5)
c5._post = _flaky_then_ok(99, exc=_ValueErr)
check("非网络异常（ValueError）不重试", c5.chat("s", "u") is None and calls["n"] == 1,
      f"n={calls['n']}")

# 退避时长序列
seq = []
L.AgnesLLMClient._sleep_backoff = staticmethod(lambda attempt: seq.append(attempt))
calls["n"] = 0
c6 = L.AgnesLLMClient(api_key="k", timeout=5)
c6._post = _flaky_then_ok(3)
c6.chat("s", "u")
check("退避发生在第 1/2/3 次尝试后（共 3 次 sleep）", seq == [1, 2, 3], str(seq))
delays = [min(L.BACKOFF_CAP, L.BACKOFF_BASE * (2 ** (a - 1))) for a in [1, 2, 3]]
check("退避时长 0.5s → 1.0s → 2.0s", delays == [0.5, 1.0, 2.0], str(delays))
L.AgnesLLMClient._sleep_backoff = staticmethod(lambda attempt: None)

print("\n测试 ③: 熔断（连续 5 次失败后快速失败且不发请求）")
calls["n"] = 0
cb = L.CircuitBreaker(threshold=5, cooldown=60.0)
c7 = L.AgnesLLMClient(api_key="k", timeout=5)
c7.circuit = cb
c7._post = _flaky_then_ok(10_000)
for i in range(5):
    c7.chat("s", "u")
check("5 次调用后熔断打开", cb.snapshot()["open"] is True, str(cb.snapshot()))
before = calls["n"]
out7 = c7.chat("s", "u")
check("第 6 次调用被快速失败（返回 None）", out7 is None)
check("第 6 次调用**没有发出请求**", calls["n"] == before,
      f"{before} → {calls['n']}")
# 成功后清零
c7._post = lambda *a, **k: _ok_resp("ok")
cb.reset()
check("reset 后熔断关闭", cb.snapshot()["open"] is False)
check("成功后可正常返回", c7.chat("s", "u") == "ok")
# 计数达到阈值前不熔断
cb2 = L.CircuitBreaker(threshold=5, cooldown=60.0)
c8 = L.AgnesLLMClient(api_key="k", timeout=5)
c8.circuit = cb2
c8._post = _flaky_then_ok(10_000)
for i in range(4):
    c8.chat("s", "u")
check("失败 4 次时熔断仍未打开（阈值 5）", cb2.snapshot()["open"] is False,
      str(cb2.snapshot()))

print("\n测试 ④: 日志脱敏（日志中不出现密钥明文）")
import logging  # noqa: E402

records = []


class _Cap(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self._sink = sink

    def emit(self, record):
        self._sink.append(record.getMessage())


SECRET = "sk-TEST-SECRET-ABCD1234"  # secret-scan: allow（测试夹具）
lg = logging.getLogger("futures_quant.ai.llm_client")
cap = _Cap(records)
lg.addHandler(cap)
try:
    from futures_quant.utils.redact import register_secret  # noqa: E402

    register_secret(SECRET)
    c9 = L.AgnesLLMClient(api_key=SECRET, timeout=5)
    # 响应体里回显密钥（模拟上游把请求内容原样返回）
    c9._post = lambda *a, **k: _Resp(400, {}, f'{{"error":"bad key {SECRET}"}}')
    c9.chat("s", "u")
finally:
    lg.removeHandler(cap)
check("日志已记录失败", len(records) > 0, str(records[:1]))
check("日志中不含密钥明文", all(SECRET not in m for m in records),
      "; ".join(records)[:160])
check("审计：脱敏函数确实能抹掉该密钥",
      SECRET not in L._redact(f"x {SECRET} y"), L._redact(f"x {SECRET} y"))
# 模块中不再有 print(
src = inspect.getsource(L)
check("llm_client 源码中不再有裸 print(", "print(" not in src)

print("\n测试 ⑤: reload_from_config 的 int/float 包 try（脏配置不抛异常）")


class _Cfg:
    def __init__(self, d):
        self._d = d

    def get(self, k, default=None):
        return self._d.get(k, default)


L.reset_client()
L.reload_from_config(_Cfg({"ai.timeout": "abc", "ai.model": None,
                           "ai.max_tokens": "12x", "ai.temperature": "oops"}))
cc = L.get_client()
check("脏配置不抛异常且落到默认值",
      cc.timeout == 30 and cc.model == "agnes-3.0-flash"
      and cc.max_tokens == 1024 and abs(cc.temperature - 0.3) < 1e-12,
      f"{cc.timeout}/{cc.model}/{cc.max_tokens}/{cc.temperature}")
L.reload_from_config(_Cfg({"ai.timeout": 45, "ai.model": "m2",
                           "ai.max_tokens": 512, "ai.temperature": 0.9}))
check("正常配置生效",
      cc.timeout == 45 and cc.model == "m2" and cc.max_tokens == 512
      and abs(cc.temperature - 0.9) < 1e-12,
      f"{cc.timeout}/{cc.model}/{cc.max_tokens}/{cc.temperature}")
L.reload_from_config(None)
check("config=None 回落到默认值", cc.timeout == 30 and cc.max_tokens == 1024)

print("\n测试 ⑥: AIConfig —— 默认值不再被污染 / 前缀判断 / 无死循环")
from futures_quant.ai.config import AIConfig, DEFAULTS, AI_SECTION  # noqa: E402

before_defaults = dict(DEFAULTS)
a1 = AIConfig(None)
a1.set("timeout", 99)
check("无 ConfigManager 时 set 不污染模块级 DEFAULTS",
      DEFAULTS == before_defaults, f"DEFAULTS={DEFAULTS}")
check("实例内可读到自己设的值", a1.get("timeout") == 99, str(a1.get("timeout")))
a2 = AIConfig(None)
check("新实例不受前一个实例影响（读到默认 30）", a2.get("timeout") == 30,
      str(a2.get("timeout")))

# 前缀判断：ai_ 开头的键不应被误判为已带 ai. 前缀
class _CfgM:
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


cm = _CfgM()
a3 = AIConfig(cm)
check("get('timeout') 走 ai.timeout", a3.get("timeout") == 7, str(a3.get("timeout")))
check("get('ai.timeout') 也正确", a3.get("ai.timeout") == 7)
try:
    a3.set("ai_foo", 1)
    saved_key = "ai.ai_foo" in cm.d
except Exception as e:  # noqa: BLE001
    saved_key = False
check("'ai_foo' 被正确补全为 'ai.ai_foo'（旧实现会原样存成 ai_foo）", saved_key,
      str([k for k in cm.d if "foo" in k]))

al = a3.get_all()
check("get_all 覆盖全部默认键", set(al.keys()) == set(DEFAULTS.keys()), str(al))
check("get_all 中与默认值相同的项返回 None（docstring 语义）",
      al.get("ai.model") is None, str(al))
csrc = inspect.getsource(AIConfig)
check("get_all 中不再有重复的第二个 for 循环（死代码已删）",
      csrc.count("for key, default in DEFAULTS.items()") == 1,
      f"count={csrc.count('for key, default in DEFAULTS.items()')}")

print("\n测试 ⑦: 未配置密钥 / 无 requests 时安全降级为 None")
c10 = L.AgnesLLMClient(api_key=None)
check("无密钥 → chat 返回 None", c10.chat("s", "u") is None)
c11 = L.AgnesLLMClient(api_key="k")
c11._post = lambda *a, **k: _ok_resp("ok")
check("有密钥 → 正常返回", c11.chat("s", "u") == "ok")
st = L.api_status()
check("api_status 含 circuit 字段", "circuit" in st, str(st))

print(f"\n{'=' * 60}")
print(f"M3-08 验证结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("test_m3_08.py 全绿")
