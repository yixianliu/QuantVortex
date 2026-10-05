"""扫描器自身的正确性契约（用 fixture 源码喂 AST，不依赖真实工程文件）。

存在意义：``tools/scan_silent_bail.py`` 报「0 条 CHAIN」只有在扫描器**确实能
检出**时才成立。若哪天把匹配逻辑改坏（例如又退化成把 ``self._x`` 归到
``self``），这里必须红，而不是让「全绿」掩盖「扫描器全瞎」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import scan_silent_bail as scanner  # noqa: E402


def hits(src: str, rule: str | None = None) -> list[dict]:
    rows = scanner.scan_source(src, "fixture.py")
    return [r for r in rows if rule is None or r["rule"] == rule]


# ---------------------------------------------------------------- 能检出
def test_detects_cross_method_chain():
    """__init__ 钉死 self._store，之后 _save 判空 return —— 必须报 CHAIN。"""
    src = '''
class P:
    def __init__(self):
        try:
            self._store = make()
        except Exception:
            self._store = None

    def _save(self):
        if self._store is None:
            return
        self._store.write()
'''
    chains = hits(src, "CHAIN")
    assert len(chains) == 1, chains
    assert chains[0]["scope"] == "class P", "链式按类归并（钉 None 与判空可能跨方法）"
    assert chains[0]["silent"] is True, "没有任何日志 → 判定为静默"
    assert "_store" in chains[0]["msg"]


def test_chain_same_function():
    src = '''
def load():
    try:
        cfg = read()
    except Exception:
        cfg = None
    if cfg is None:
        return
    return cfg
'''
    chains = hits(src, "CHAIN")
    assert len(chains) == 1
    assert chains[0]["scope"] == "def load()"


def test_explicit_return_none_counts():
    """`return None` 与裸 `return` 等价。"""
    src = '''
def f():
    try:
        m = build()
    except Exception:
        m = None
    if m is None:
        return None
    return m
'''
    assert len(hits(src, "CHAIN")) == 1


def test_chain_within_attribute_not_name():
    """self 之外的属性（obj._x）同样要归到 _x。"""
    src = '''
class A:
    def go(self):
        try:
            self._cash = 0
            raise RuntimeError
        except Exception:
            obj._cash = None
        if obj._cash is None:
            return
'''
    assert len(hits(src, "CHAIN")) == 1


# ---------------------------------------------------------------- 留痕降级
def test_chain_is_marked_logged_when_traced():
    """分支前打了 error 日志 → CHAIN 仍报，但 silent=False（不算缺陷）。"""
    src = '''
import logging
logger = logging.getLogger(__name__)

class P:
    def __init__(self):
        try:
            self._store = make()
        except Exception:
            self._store = None

    def _save(self):
        if self._store is None:
            logger.error("store 不可用")
            return
'''
    chains = hits(src, "CHAIN")
    assert len(chains) == 1
    assert chains[0]["silent"] is False, "已留痕不应判定为静默"


def test_chain_marked_logged_via_toast_helper():
    src = '''
class P:
    def __init__(self):
        try:
            self._store = make()
        except Exception:
            self._store = None

    def _save(self):
        if self._store is None:
            self.toast("不可用")
            return
'''
    chains = hits(src, "CHAIN")
    assert chains and chains[0]["silent"] is False


# ---------------------------------------------------------------- 不误报
def test_no_false_positive_on_optional_arg_bail():
    """可选参数守卫（没钉过 None）只报 BAIL_STANDAL，不是 CHAIN。"""
    src = '''
def render(x=None):
    if x is None:
        return None
    draw(x)
'''
    assert not hits(src, "CHAIN")
    assert len(hits(src, "BAIL_STANDAL")) == 1


def test_no_false_positive_on_value_return():
    """`if x is None: return x` 有值返回，不是丢弃能力。"""
    src = '''
def get(d, k):
    v = d.get(k)
    if v is None:
        return v
    return v
'''
    assert not hits(src, "CHAIN")


def test_no_false_positive_on_else_both_return():
    """if/else 双分支都 return 属正常短路。"""
    src = '''
def pick(v):
    try:
        s = make()
    except Exception:
        s = None
    if s is None:
        return 0
    else:
        return 1
'''
    assert not hits(src, "CHAIN")


def test_no_false_positive_on_truthiness_guard():
    """`if not x: return` 不在本反模式射程内。"""
    src = '''
def run(items):
    if not items:
        return None
    for i in items:
        pass
'''
    assert not hits(src, "CHAIN")


def test_no_false_positive_on_real_exception_reraise():
    """真正重抛/返回别的值的异常处理器不算 swallow。"""
    src = '''
def load():
    try:
        return read()
    except FileNotFoundError as e:
        raise RuntimeError("x") from e
'''
    assert not hits(src, "CHAIN")


# ---------------------------------------------------------------- PIN 提示
def test_pinned_never_tested_is_pin_standal():
    src = '''
class P:
    def __init__(self):
        try:
            import requests
        except Exception:
            requests = None
'''
    pins = hits(src, "PIN_STANDAL")
    assert len(pins) == 1
    assert "requests" in pins[0]["msg"]


# ---------------------------------------------------------------- 工程自洽
def test_scanner_finds_no_silent_chain_in_product_code():
    """工程全量扫描：不应存在**未留痕**的 CHAIN（CI 门禁语义）。

    这里刻意不断言「条数为 0」—— 扫描器能力本身由上面 fixture 用例保证。
    若这里红了，说明工程里真的还有静默丢能力的写法。
    """
    rows = []
    for p in scanner.iter_py_files(["futures_quant"]):
        rows.extend(scanner.scan_file(p))
    silent_chains = [r for r in rows if r["rule"] == "CHAIN" and r["silent"]]
    assert silent_chains == [], \
        "存在未留痕的静默失效链式写法：" + ", ".join(
            f"{r['file']}:{r['line']}" for r in silent_chains)
