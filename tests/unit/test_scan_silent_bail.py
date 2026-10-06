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


# ---------------------------------------------------------------- iter_py_files：文件实参
# 回归 pre-commit 钩子：钩子把「暂存的 .py 文件列表」直接喂给 --dir。
# 若 iter_py_files 只认目录、把文件实参整个跳过（base.is_dir() 为 False 即 continue），
# 则钩子的静默失效关会静默退化成「扫 0 个文件、恒 rc=0」的 no-op —— 曾踩过。
_SILENT_CHAIN = '''
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


def test_iter_py_files_accepts_single_file(tmp_path):
    """单个 .py 文件作为 --dir 实参必须被纳入（钩子正是这么调的）。"""
    f = tmp_path / "probe_mod.py"
    f.write_text(_SILENT_CHAIN, encoding="utf-8")
    files = scanner.iter_py_files([str(f)])
    assert files == [f], "单个 .py 文件实参必须被命中，否则钩子 no-op"
    # 串起「文件实参 + 检出链路」两条：既被收集，又能检出未留痕 CHAIN
    rows = scanner.scan_source(f.read_text(encoding="utf-8"), str(f))
    silent = [r for r in rows if r["rule"] == "CHAIN" and r["silent"]]
    assert silent, "文件实参链路必须能检出未留痕 CHAIN（rc=1 的门禁判据）"


def test_iter_py_files_accepts_dir_and_file_together(tmp_path):
    """目录（rglob）与文件实参可混用；文件实参不会被目录逻辑吞掉。"""
    f = tmp_path / "solo.py"
    f.write_text(_SILENT_CHAIN, encoding="utf-8")
    files = scanner.iter_py_files(["futures_quant", str(f)])
    assert f in files, "文件实参必须在结果里，与目录 rglob 并列"


def test_iter_py_files_skips_underscore_file_arg(tmp_path):
    """下划线开头的文件即便显式传入也过滤（与目录 rglob 口径一致）。"""
    f = tmp_path / "_private.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert scanner.iter_py_files([str(f)]) == []


def test_iter_py_files_ignores_non_py_file_arg(tmp_path):
    """非 .py 实参直接忽略（钩子已用 grep 只挑 .py，双保险）。"""
    f = tmp_path / "notes.txt"
    f.write_text("x = 1\n", encoding="utf-8")
    assert scanner.iter_py_files([str(f)]) == []
