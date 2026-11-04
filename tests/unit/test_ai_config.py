# -*- coding: utf-8 -*-
"""M3-09：ai/config.py 单元测试。

锁定：
  * 密钥优先级：内存 > 环境变量 > None；
  * 打包（frozen）模式启动清除持久化的 ai.api_key；
  * 无 ConfigManager 时 set 不污染模块级 DEFAULTS；
  * 前缀判断用 "ai."（ai_foo 必须被补全）；
  * api_key 永不持久化。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai import config as AC  # noqa: E402


class _CfgM:
    """最小 ConfigManager 替身。"""

    def __init__(self, data=None):
        self.d = dict(data or {})
        self.saved = 0
        self.set_calls = []

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.set_calls.append((k, v))
        self.d[k] = v

    def save(self):
        self.saved += 1

    def as_dict(self):
        out = {}
        for k, v in self.d.items():
            if "." in k:
                sec, sub = k.split(".", 1)
                out.setdefault(sec, {})[sub] = v
        return out


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(AC._ENV_KEY, raising=False)
    yield
    monkeypatch.delenv(AC._ENV_KEY, raising=False)


def test_key_priority_memory_over_env(monkeypatch):
    monkeypatch.setenv(AC._ENV_KEY, "from-env")
    c = AC.AIConfig(_CfgM())
    assert c.get_api_key() == "from-env"      # 初始化时由 env 填充内存
    c.set_api_key("from-memory")
    assert c.get_api_key() == "from-memory"   # 内存优先


def test_key_priority_env_when_memory_empty(monkeypatch):
    monkeypatch.setenv(AC._ENV_KEY, "env-only")
    c = AC.AIConfig(_CfgM())
    assert c.get_api_key() == "env-only"


def test_key_priority_none_when_missing():
    c = AC.AIConfig(_CfgM())
    assert c.get_api_key() is None


def test_set_api_key_never_persisted():
    cm = _CfgM()
    c = AC.AIConfig(cm)
    c.set("api_key", "secret-value")
    assert c.get_api_key() == "secret-value"
    assert not any("api_key" in k for k, _ in cm.set_calls), \
        "api_key 绝不能进入 ConfigManager"
    assert cm.saved == 0


def test_frozen_mode_purges_persisted_api_key(monkeypatch):
    monkeypatch.setattr(AC, "is_frozen", lambda: True)
    cm = _CfgM({"ai.api_key": "leaked", "ai.timeout": 30})
    c = AC.AIConfig(cm)
    assert c._frozen is True
    assert "ai.api_key" in [k for k, _ in cm.set_calls], \
        "打包模式必须清除持久化的 ai.api_key"
    assert cm.d.get("ai.api_key") is None


def test_debug_mode_keeps_config_untouched(monkeypatch):
    monkeypatch.setattr(AC, "is_frozen", lambda: False)
    cm = _CfgM({"ai.api_key": "x"})
    AC.AIConfig(cm)
    assert not any("api_key" in k for k, _ in cm.set_calls)


def test_set_without_config_manager_does_not_pollute_defaults():
    before = dict(AC.DEFAULTS)
    a = AC.AIConfig(None)
    a.set("timeout", 123)
    assert AC.DEFAULTS == before, "模块级 DEFAULTS 被污染了"
    assert a.get("timeout") == 123
    # 新实例不受影响
    assert AC.AIConfig(None).get("timeout") == before["ai.timeout"]


def test_prefix_normalization_for_non_prefixed_keys():
    cm = _CfgM()
    a = AC.AIConfig(cm)
    a.set("ai_foo", 1)
    a.set("timeout", 9)
    assert "ai.ai_foo" in cm.d, f"ai_foo 应补全为 ai.ai_foo，实际 {list(cm.d)}"
    assert "ai.timeout" in cm.d


def test_get_uses_ai_prefixed_lookup():
    cm = _CfgM({"ai.timeout": 42, "ai.model": "m"})
    a = AC.AIConfig(cm)
    assert a.get("timeout") == 42
    assert a.get("ai.timeout") == 42
    assert a.get("model") == "m"


def test_get_all_marks_defaults_as_none():
    cm = _CfgM({"ai.timeout": 42})          # model/max_tokens/temperature 均为默认
    a = AC.AIConfig(cm)
    out = a.get_all()
    assert set(out) == set(AC.DEFAULTS)
    assert out["ai.timeout"] == 42
    assert out["ai.model"] is None          # 与默认值相同 → None


def test_get_all_without_config_manager():
    a = AC.AIConfig(None)
    out = a.get_all()
    assert set(out) == set(AC.DEFAULTS)
    assert out == dict(AC.DEFAULTS)


def test_reset_to_defaults_clears_key(monkeypatch):
    monkeypatch.setenv(AC._ENV_KEY, "env-key")
    cm = _CfgM({"ai.timeout": 5})
    a = AC.AIConfig(cm)
    assert a.get_api_key() == "env-key"
    a.reset_to_defaults()
    assert a.get_api_key() is None or a.get_api_key() == "env-key"  # env 仍可读
    assert a._api_key is None


def test_status_contains_no_secret(monkeypatch):
    monkeypatch.setenv(AC._ENV_KEY, "super-secret")
    a = AC.AIConfig(_CfgM())
    st = a.status()
    assert st["api_key_set"] is True
    blob = str(st)
    assert "super-secret" not in blob
