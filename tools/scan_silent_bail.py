"""全量静态扫描「静默失效」链式反模式 —— 兜底把崩溃挡住了，但能力整条静默丢掉。

背景（v5.2.3 / v5.2.4 两次根治同一根因）：
    初始化期 `try: make() / except: self._x = None` 把 None 钉死；
    之后调用方 `if self._x is None: return` —— 崩溃没炸，但整条能力静默失效，
    用户看不到提示、日志里一个字都没有。

只扫 `_test_*.py` / 弃用文件之外的正式代码；测试目录不计入。

判定模型（**链式**，这才是真正的数据丢失信号）：

    CHAIN         同一 class / 同一函数内，名字 A 先在 except 里被钉成 None，
                  之后又在 `if A is None: return` 处被静默放弃   ← 高危
    BAIL_STANDAL  函数里有 `if x is None: return` 但该名字未被钉 None
                  （多半是可选参数守卫，可接受）                ← 提示
    PIN_STANDAL   名字被钉成 None 却从未被判空（写了但没人看）   ← 提示

「静默」= 该分支所在函数内**无任何 log/warn/error/toast 调用**。
已留痕的同样报出来但标 LOGGED，不等于缺陷。

用法：
    python tools/scan_silent_bail.py                      # 全量
    python tools/scan_silent_bail.py --min-severity high  # 只看高危 CHAIN
    python tools/scan_silent_bail.py --format json
退出码：存在「未留痕的 CHAIN」返回 1（可直接当 CI 门禁）。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIRS = ["futures_quant"]
SKIP_PARTS = {"__pycache__", ".git", "build", "dist", "node_modules"}

# 命中即视为「已留痕」的调用名（**按词元精确匹配**，不能用子串：
# 否则 `blockSignals` 里的 "log" 会让整个函数被误判成「已留痕」）
TRACE_HINTS = frozenset({
    "log", "logger", "logging", "syslog", "loglevel",
    "warn", "warning", "error", "exception_log",
    "toast", "msg", "msgbox", "msg_box", "notice",
})


# ---------------------------------------------------------------- 小工具
def _is_none_compare(test: ast.AST) -> bool:
    """test 是否为 `X is None` / `X == None`。"""
    if not isinstance(test, ast.Compare):
        return False
    if not any(isinstance(op, (ast.Is, ast.Eq)) for op in test.ops):
        return False
    return (bool(test.comparators)
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is None)


def _returns_none(node: ast.AST) -> bool:
    """裸 return / return None。"""
    if not isinstance(node, ast.Return):
        return False
    return node.value is None or (
        isinstance(node.value, ast.Constant) and node.value.value is None)


def _returns_value(node: ast.AST) -> bool:
    """return 带值（例如 `return -1`）→ 不算「放弃能力」。"""
    return isinstance(node, ast.Return) and node.value is not None \
        and not (isinstance(node.value, ast.Constant) and node.value.value is None)


def _target_names(node: ast.AST) -> list[str]:
    """取出赋值/比较涉及的「状态名」。

    关键：``self._x = None`` 必须归到 ``_x`` 而不是 ``self`` ——
    否则跨方法链式匹配（__init__ 里钉死、_save() 里判空）永远对不上。
    """
    if isinstance(node, ast.Attribute):
        return [node.attr]                 # self._x / obj._x → _x
    if isinstance(node, ast.Name):
        return [node.id]
    return []


def _call_names(node: ast.AST, acc: list[str]) -> None:
    """收集表达式里出现的所有可调用名（含间接 Call）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            acc.append(sub.attr)
        elif isinstance(sub, ast.Name):
            acc.append(sub.id)


def _token_hits(name: str) -> bool:
    """标识符里是否存在「日志/提示」词元（blockSignals 不算，_log 算）。"""
    for t in re.split(r"[_\W]+", name.lower()):
        if t in TRACE_HINTS or any(t.startswith(h + "_") for h in TRACE_HINTS):
            return True
    return False


def _traced(func: ast.AST, before_line: int = 0) -> bool:
    """函数内在 ``before_line`` **之前**是否存在「留痕」调用。

    顺序必须算：判空分支之后才打的日志，救不了这个分支的静默。
    （曾踩坑：``_maybe_restore_manual_config`` 里 2496 行判空 return，
    2531 行才 ``self._log(...)``，不加顺序判定会被误判为「已留痕」。）
    """
    acc: list[tuple[int, str]] = []
    for sub in ast.walk(func):
        ln = getattr(sub, "lineno", 0)
        if not isinstance(ln, int):
            continue
        if isinstance(sub, ast.Attribute):
            acc.append((ln, sub.attr))
        elif isinstance(sub, ast.Name):
            acc.append((ln, sub.id))
    # 注意必须按「名字自己那一行」过滤：沿节点递归会把后面行的名字一起带进来
    return any(_token_hits(n) for ln, n in acc if ln <= before_line)


ALLOW_TAG = "scan-silent-bail:"
_ALLOW_RE = re.compile(r"scan-silent-bail:\s*(allow|豁免)?\s*[：:]?\s*(.*)")


def _allow_reason(text: str, lineno: int, span: int = 3) -> str:
    """在被判空分支附近（前后各 span 行）找 `# scan-silent-bail: <理由>` 标注。

    豁免必须**写明理由**并留在代码里，这样门禁可审计；
    不能只是「让它不报错」—— 那等于把缺陷藏起来。
    """
    try:
        lines = text.splitlines()
    except Exception:  # noqa: BLE001
        return ""
    lo = max(0, lineno - 1 - span)
    hi = min(len(lines), lineno + span)
    for ln in lines[lo:hi]:
        if ALLOW_TAG in ln:
            m = _ALLOW_RE.search(ln)
            if m and (m.group(1) or m.group(2).strip()):
                return (m.group(1) or "").strip() or m.group(2).strip()
    return ""


def _snippet_from(text: str, lineno: int, span: int = 1) -> str:
    try:
        lines = text.splitlines()
        return " / ".join(lines[lineno - 1: lineno - 1 + span])[:150].strip()
    except Exception:  # noqa: BLE001
        return ""


def _snippet(path: Path, lineno: int, span: int = 1) -> str:
    try:
        return _snippet_from(path.read_text(encoding="utf-8"), lineno, span)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- 扫描
class _Scope:
    """把每个节点归属到最近的顶层 class / 模块级函数，作为链式判定作用域。"""

    def __init__(self) -> None:
        self.owner: dict[int, str] = {}     # node id -> 方法级 scope key
        self._groups: dict[str, str] = {}   # scope key -> 类级/函数级「组」

    def run(self, tree: ast.AST) -> None:
        def _mark(node: ast.AST, key: str, group: str) -> None:
            for sub in ast.walk(node):
                self.owner[id(sub)] = key
                self._groups.setdefault(key, group)
        for top in tree.body:
            if isinstance(top, ast.ClassDef):
                key = f"class {top.name}"
                _mark(top, key, key)         # 类级自带成组：跨方法链式匹配
                for item in top.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        k = f"{key}.{item.name}"
                        self.owner[id(item)] = k
                        _mark(item, k, key)
            elif isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = f"def {top.name}()"
                _mark(top, key, key)
            else:
                _mark(top, "<module>", "<module>")

    def group_of(self, key: str) -> str:
        return self._groups.get(key, "<module>")


def scan_source(text: str, rel: str) -> list[dict]:
    """扫描一段源码（抽出以便单测直接喂 fixture）。"""
    try:
        tree = ast.parse(text)
    except Exception:  # noqa: BLE001
        return []
    scope = _Scope()
    scope.run(tree)
    lines = text.splitlines()

    pins: dict[str, list[tuple[int, str, bool]]] = {}
    bails: dict[str, list[tuple[int, str, bool]]] = {}

    for node in ast.walk(tree):
        owner = scope.owner.get(id(node), "<module>")

        # ① 钉死 None：except 里 `x = None` / `x: T = None`
        if isinstance(node, ast.ExceptHandler):
            for s in node.body:
                if isinstance(s, ast.Assign):
                    for t in s.targets:
                        names = _target_names(t)
                        val = s.value
                        pinned = (isinstance(val, ast.Constant) and val.value is None)
                        if names and pinned:
                            pins.setdefault(owner, []).append(
                                (s.lineno, names[0], False))
                if isinstance(s, ast.AnnAssign) and s.value is not None:
                    names = _target_names(s.target)
                    if names and isinstance(s.value, ast.Constant) \
                            and s.value.value is None:
                        pins.setdefault(owner, []).append(
                            (s.lineno, names[0], False))

        # ② 判空 return
        if isinstance(node, ast.If) and _is_none_compare(node.test):
            body = node.body
            # 分支里可能先打日志再 return（`if x is None: log(); return`），
            # 因此不能要求 body 只有一条语句，只要「无值返回」且至少一条 return None。
            if body and any(_returns_none(s) for s in body) \
                    and not any(_returns_value(s) for s in body):
                # 取比较的左操作数（_x is None → 名为 _x），不能把 Compare 本身
                # 当目标，否则 names 恒为空、所有判空分支都漏检。
                left = node.test.left if isinstance(node.test, ast.Compare) else node.test
                names = _target_names(left)
                if not names:
                    continue
                # 只认 `if x is None: return`；双分支都 return 属正常短路
                orelse = node.orelse
                if orelse and _returns_none(orelse[0]) and len(orelse) == 1:
                    continue
                fn_owner = scope.owner.get(
                    id(node), owner) if id(node) in scope.owner else owner
                bails.setdefault(fn_owner, []).append(
                    (body[0].lineno, names[0], False, fn_owner))

    # 「是否已留痕」：取 bail 所在函数
    func_nodes: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for key in {owner for owner in scope.owner.values()
                        if owner.endswith(f".{node.name}") or owner == f"def {node.name}()"}:
                func_nodes[key] = node

    findings: list[dict] = []

    def _is_silent(fn_key: str, before_line: int = 0) -> bool:
        """「留痕」只看**判空所在那个方法**、且发生在判空之前。"""
        return not _traced(func_nodes.get(fn_key)
                           or ast.Module(body=[], type_ignores=[]), before_line)

    # 链式匹配按「类」归并：钉 None 常在 __init__，判空常在别的方法里，
    # 只看方法级键会把真实的跨方法链漏掉（splash.py 那类就是）。
    groups: dict[str, dict] = {}
    for key in set(pins) | set(bails):
        gk = scope.group_of(key)
        slot = groups.setdefault(gk, {"pins": [], "bails": []})
        # 必须**合并**不能赋值：同一个类下多个方法各有判空分支，
        # 直接赋值只会留下最后遍历到的那一条（会漏报真实缺陷）。
        if key in pins:
            slot["pins"].extend(pins[key])
        if key in bails:
            slot["bails"].extend(bails[key])

    for gkey, gdata in groups.items():
        pin_names = {n for _, n, _ in gdata["pins"]}
        bail_names = {n for _, n, *_ in gdata["bails"]}
        # 「留痕」取**判空所在方法**判定：__init__ 打了日志不代表 _save 也打了
        bail_keys = {k for k in bails if scope.group_of(k) == gkey}
        for ln, name, *_ in gdata["pins"]:
            if name in bail_names:
                continue                       # 由 CHAIN 统一出报
            findings.append({
                "rule": "PIN_STANDAL", "severity": "info",
                "silent": _is_silent(key, ln),
                "scope": gkey, "file": rel, "line": ln,
                    "snippet": _snippet_from(text, ln),
                    "msg": f"“{name}” 在 except 里被置 None，但本作用域从未判空",
            })
        for ln, name, *_rest, owner_of_bail in gdata["bails"]:
            # 逐分支判定（方法与豁免理由都要各自成立）：
            # 同组里一个已标注分支不能把同组未标注的分支一起洗白。
            reason = _allow_reason(text, ln)
            silent = _is_silent(owner_of_bail, ln) and not reason
            if name in pin_names:
                findings.append({
                    "rule": "CHAIN", "severity": "high", "silent": silent,
                    "allow_reason": reason,
                    "scope": gkey, "file": rel, "line": ln,
                    "snippet": _snippet_from(text, ln),
                    "msg": f"“{name}” 先被 except 钉成 None，此处又静默 return "
                           f"（能力静默失效）",
                })
            else:
                findings.append({
                    "rule": "BAIL_STANDAL", "severity": "info", "silent": silent,
                    "scope": gkey, "file": rel, "line": ln,
                    "snippet": _snippet_from(text, ln),
                    "msg": f"“{name}” 判空后 return（未见 except 钉 None，"
                           f"多半是可选参数守卫）",
                })
    return findings


def scan_file(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    return scan_source(text, str(path.relative_to(ROOT)))


def iter_py_files(dirs: list[str]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        base = (ROOT / d) if not Path(d).is_absolute() else Path(d)
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if SKIP_PARTS & set(p.parts):
                continue
            if p.name.startswith("_"):
                continue
            out.append(p)
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描「静默失效」链式反模式")
    ap.add_argument("--dir", nargs="*", default=DEFAULT_DIRS)
    ap.add_argument("--min-severity", choices=["all", "high"], default="all")
    ap.add_argument("--rule", nargs="*", default=None)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    # 本机 anaconda 的 sitecustomize.py 会在 stdout 打 "[DLL固定]..." banner，
    # 机器读输出（--format json）会被那行污染 → 需要能落到文件，stdout 保持干净。
    ap.add_argument("--output", default=None, help="结果写入文件（默认写 stdout）")
    args = ap.parse_args()

    findings: list[dict] = []
    for p in iter_py_files(args.dir):
        findings.extend(scan_file(p))

    if args.rule:
        findings = [f for f in findings if f["rule"] in args.rule]
    if args.min_severity == "high":
        findings = [f for f in findings if f["severity"] == "high"]

    order = {"high": 0, "info": 1}
    findings.sort(key=lambda x: (order[x["severity"]], x["file"], x["line"]))

    if args.format == "json":
        payload = json.dumps(findings, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return 1 if any(f["severity"] == "high" and f["silent"] for f in findings) else 0

    chains = [f for f in findings if f["rule"] == "CHAIN"]
    silent_chains = [f for f in chains if f["silent"]]
    print("=" * 74)
    print(f"扫描：{', '.join(args.dir)}   命中 {len(findings)} 条 "
          f"（CHAIN {len(chains)} / 其中未留痕 {len(silent_chains)}）")
    print("=" * 74)
    for f in findings:
        if f["rule"] != "CHAIN":
            continue
        mark = "🚨" if f["silent"] else "⚠️"
        print(f"\n{mark} {f['file']}:{f['line']}  [{f['rule']}]  {f['scope']}")
        print(f"    {f['snippet']}")
        print(f"    → {f['msg']}")
    if chains:
        print("\n" + "-" * 74)
        print("未留痕 CHAIN 清单（作为 CI 门禁判据）：")
        for f in silent_chains:
            print(f"  - {f['file']}:{f['line']}  {f['scope']}")
    other = [f for f in findings if f["rule"] != "CHAIN"]
    if other:
        print("-" * 74)
        print(f"其它提示 {len(other)} 条（用 --rule PIN_STANDAL BAIL_STANDAL 查看）")
    return 1 if silent_chains else 0


if __name__ == "__main__":
    raise SystemExit(main())
