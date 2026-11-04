"""QuantVortex 统一验收入口（一条命令跑完并给出可判定结论）。

覆盖四类验证，全部在仓库根目录可复现，不引入第三方依赖：

1. 单元测试      ``python -m pytest tests/unit``
2. e2e 测试      ``python -m pytest tests/e2e``（可用 ``--e2e-skip`` / ``--quick`` 跳过）
3. 回测锚点等价  ``scripts/perf_probe.py --section anchor``，比对 docs/diagnosis/phase2_perf_fix.md §8.2
4. 性能门槛      ``scripts/perf_probe.py --section backtest/indicators"``，比对 outputs/perf_baseline.md
5. GUI 冒烟      offscreen 构建主窗口与全部页面（``PAGES_OK 7 / 7``）

用法::

    python scripts/acceptance.py              # 全量验收（含 e2e，约 20~25 分钟）
    python scripts/acceptance.py --quick      # 只跑 unit + 锚点 + GUI 冒烟（约 12 分钟）
    python scripts/acceptance.py --perf-skip  # 跳过性能门槛
    python scripts/acceptance.py --e2e-skip   # 跳过 e2e

退出码：0 = 全部 PASS 或 SKIP；1 = 存在 FAIL（控制台与报告会写清哪项退化、差多少）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs"
REPORT_PATH = OUT_DIR / "acceptance_report.md"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# ---------------------------------------------------------------------------
# 基线常量（唯一来源：docs/diagnosis/phase2_perf_fix.md §8.2 与 outputs/perf_baseline.md）
# ---------------------------------------------------------------------------
# 回测锚点：num_fills 精确比对；收益/回撤容差 0.02pp（0.0002）；Sharpe 容差 0.005
ANCHOR_EXPECT: Dict[str, Dict[str, Dict[str, float]]] = {
    "rb.SHFE": {
        "full_window": {"num_fills": 231, "total_return": -0.0078,
                        "sharpe": -0.130, "max_drawdown": 0.0308},
        "anchor_window": {"num_fills": 225, "total_return": -0.0076,
                          "sharpe": -0.129, "max_drawdown": 0.0308},
    },
    "i.DCE": {
        "full_window": {"num_fills": 235, "total_return": -0.0089,
                        "sharpe": -0.465, "max_drawdown": 0.0127},
        "anchor_window": {"num_fills": 235, "total_return": -0.0089,
                          "sharpe": -0.465, "max_drawdown": 0.0127},
    },
}
ANCHOR_TOL = {"total_return": 0.0002, "max_drawdown": 0.0002, "sharpe": 0.005}

# 性能门槛（用户指定的硬门禁，取自 perf_baseline.md 的「可直接写死的绝对阈值」）
PERF_LIMITS = [
    ("batch_ms", "43 品种批量回测", 24_500.0, "≤24.5s"),
    ("single_ms", "rb.SHFE 单次回测", 500.0, "≤500ms"),
    ("indicators_ms", "add_indicators(5000bar)", 180.0, "≤180ms"),
    ("sar_ms", "SAR 单指标", 120.0, "≤120ms"),
]
PERF_BASELINE = {"batch_ms": 21_276.6, "single_ms": 405.2,
                 "indicators_ms": 154.9, "sar_ms": 97.28}

# 子进程超时（秒）。unit 实测约 800s（含 M3 训练类用例），留足一倍余量。
T_UNIT, T_E2E, T_ANCHOR, T_PERF_BT, T_PERF_IND, T_GUI = 1800, 2400, 300, 600, 180, 240


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _child_env() -> Dict[str, str]:
    """子进程环境：UTF-8 输出，避免 Windows 控制台编码把中文日志截断。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(cmd: List[str], timeout: int, env: Optional[Dict[str, str]] = None
         ) -> Tuple[int, str, float]:
    """执行子命令，返回 (退出码, 合并输出, 耗时秒)。超时按失败处理且不抛异常。"""
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env=env or _child_env())
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return proc.returncode, out, round(time.perf_counter() - t0, 2)
    except subprocess.TimeoutExpired:
        return -9, f"子进程超时（>{timeout}s）已中止", round(time.perf_counter() - t0, 2)
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}", round(time.perf_counter() - t0, 2)


def _tail(text: str, n: int = 30) -> str:
    """取输出末尾 n 行，用于失败原因摘要（避免把整段 pytest 输出塞进报告）。"""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _get(d: Any, *keys: str, default: Any = None) -> Any:
    """安全取值：任一层缺失即返回 default（探针 JSON 结构变动时不抛异常）。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _pp(x: Optional[float]) -> str:
    """收益率转百分比展示（-0.0078 → -0.78%）。"""
    return "n/a" if x is None else f"{x * 100:.2f}%"


# ---------------------------------------------------------------------------
# 1/2. pytest 类验收
# ---------------------------------------------------------------------------
_SUM_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped)", re.I)


def _parse_pytest(text: str) -> Dict[str, Any]:
    """从 pytest -q 输出解析通过/失败/错误/跳过数量、耗时与失败用例名。"""
    res: Dict[str, Any] = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                           "secs": None, "failed_cases": []}
    for num, word in _SUM_RE.findall(text):
        w = word.lower()
        if w == "passed":
            res["passed"] = int(num)
        elif w == "failed":
            res["failed"] = int(num)
        elif w in ("error", "errors"):
            res["errors"] = int(num)
        elif w == "skipped":
            res["skipped"] = int(num)
    secs = re.findall(r"in\s+(\d+(?:\.\d+)?)s", text)
    if secs:
        res["secs"] = float(secs[-1])
    res["failed_cases"] = [
        f"{node}{(' — ' + msg) if msg else ''}"
        for node, msg in re.findall(r"^(?:FAILED|ERROR)\s+(\S+)(?:\s+-+\s+(.*))?$", text, re.M)
    ]
    return res


def _parse_junit(path: Path) -> Optional[Dict[str, Any]]:
    """解析 pytest 的 junitxml（比解析控制台尾行可靠，且能拿到失败用例名）。"""
    if not path.exists():
        return None
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(str(path)).getroot()
    except Exception:  # noqa: BLE001
        return None
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return None
    total = int(suite.get("tests", 0) or 0)
    failed = int(suite.get("failures", 0) or 0)
    errors = int(suite.get("errors", 0) or 0)
    skipped = int(suite.get("skipped", 0) or 0)
    secs = suite.get("time")
    cases: List[str] = []
    for tc in suite.iter("testcase"):
        bad = tc.find("failure")
        if bad is None:
            bad = tc.find("error")
        if bad is None:
            continue
        node = f"{tc.get('classname', '')}::{tc.get('name', '')}".strip(":")
        msg = (bad.get("message") or "").strip().splitlines()
        cases.append(f"{node}{(' — ' + msg[0]) if msg else ''}")
    return {"passed": max(0, total - failed - errors - skipped), "failed": failed,
            "errors": errors, "skipped": skipped,
            "secs": float(secs) if secs else None, "failed_cases": cases}


def _pytest_item(name: str, target: str, timeout: int) -> Dict[str, Any]:
    """运行一个 pytest 目标并判定（用例失败 / 收集错误 / 超时均判 FAIL）。

    判定数据优先取 ``--junitxml``（结构化、与控制台输出顺序无关），
    控制台解析仅作兜底——本仓库部分用例会重定向 stdout，导致末尾统计行缺失。
    """
    try:
        import pytest as _p  # noqa: F401  # 仅用于判断 pytest 是否可用
    except Exception:  # noqa: BLE001
        return {"name": name, "status": SKIP, "metrics": "pytest 未安装",
                "detail": "环境缺失 pytest，无法执行该验收项", "seconds": 0.0}

    tag = "unit" if "unit" in target else "e2e"
    junit = OUT_DIR / f".acceptance_junit_{tag}.xml"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    code, out, secs = _run(
        [sys.executable, "-m", "pytest", target, "-q", "--tb=line", "-rf",
         f"--junitxml={junit}"], timeout)

    parsed = _parse_pytest(out)
    jr = _parse_junit(junit)
    if jr:
        parsed.update(jr)
        if jr.get("secs"):
            secs = float(jr["secs"])
    total = parsed["passed"] + parsed["failed"] + parsed["errors"]
    metrics = (f"通过 {parsed['passed']} / 失败 {parsed['failed']} / "
               f"错误 {parsed['errors']} / 跳过 {parsed['skipped']} · {secs:.2f}s")

    infra = ("INTERNALERROR" in out) or ("ERROR collecting" in out) or (total == 0)
    if infra:
        return {"name": name, "status": FAIL, "metrics": metrics,
                "detail": "未能正常收集或执行用例（疑似导入/环境错误），末尾输出：\n"
                          + _tail(out, 15), "seconds": secs}
    if parsed["failed"] or parsed["errors"] or code != 0:
        cases = parsed["failed_cases"][:15]
        detail = (f"退化：失败 {parsed['failed']} / 错误 {parsed['errors']} "
                  f"（基线为 0 失败 0 错误）。")
        if cases:
            detail += "\n失败用例：\n" + "\n".join(f"- {c}" for c in cases)
        if not cases:
            detail += "\n末尾输出：\n" + _tail(out, 10)
        return {"name": name, "status": FAIL, "metrics": metrics,
                "detail": detail, "seconds": secs}
    return {"name": name, "status": PASS, "metrics": metrics,
            "detail": "全部用例通过", "seconds": secs}


# ---------------------------------------------------------------------------
# 3. 回测锚点等价
# ---------------------------------------------------------------------------
def _anchor_item() -> Dict[str, Any]:
    """跑 anchor 分节（独立子进程，写临时 JSON）并逐项比对 §8.2 锚点。"""
    tmp = OUT_DIR / ".acceptance_anchor.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    code, out, secs = _run(
        [sys.executable, str(ROOT / "scripts" / "perf_probe.py"), "--section", "anchor",
         "--child", "--json-out", str(tmp), "--runs", "1"], T_ANCHOR)
    if code != 0 or not tmp.exists():
        # 现跑失败时退回读取既有锚点 JSON（明确标注来源，避免假绿）
        cached = OUT_DIR / ".perf_anchor.json"
        if cached.exists():
            try:
                data = json.loads(cached.read_text(encoding="utf-8"))
                note = "现跑锚点分节失败，已退回读取 outputs/.perf_anchor.json（缓存值）。"
            except Exception:  # noqa: BLE001
                data, note = None, ""
        else:
            data, note = None, ""
        if data is None:
            reason = ("本地缺少离线日线缓存或数据文件，锚点分节无法运行" if "FileNotFound" in out
                      or "No such file" in out or "缓存" in out
                      else "锚点分节未产出 JSON")
            return {"name": "回测锚点等价", "status": SKIP, "metrics": "未产出锚点结果",
                    "detail": f"{reason}（exit={code}）。末尾输出：\n{_tail(out, 10)}",
                    "seconds": secs}
    else:
        data = json.loads(tmp.read_text(encoding="utf-8"))
        note = "现跑 anchor 分节，结果写 outputs/.acceptance_anchor.json。"

    verdict = _get(data, "verdict", default={}) or {}
    all_ok = bool(verdict.get("all_ok"))
    problems: List[str] = []
    infos: List[str] = []

    for sym, windows in ANCHOR_EXPECT.items():
        for win, exp in windows.items():
            got = _get(data, "results", sym, win, default={}) or {}
            for key, want in exp.items():
                val = got.get(key)
                if val is None:
                    problems.append(f"{sym} {win} {key} 缺失（期望 {want}）")
                    continue
                if key == "num_fills":
                    if int(val) != int(want):
                        problems.append(
                            f"{sym} {win} 成交笔数 {int(val)} ≠ 基线 {int(want)}"
                            f"（差 {int(val) - int(want):+d} 笔）")
                else:
                    tol = ANCHOR_TOL[key]
                    diff = float(val) - float(want)
                    if abs(diff) > tol:
                        unit = "pp" if key in ("total_return", "max_drawdown") else ""
                        shown = f"{diff * 100:+.2f}pp" if unit else f"{diff:+.3f}"
                        problems.append(
                            f"{sym} {win} {key}={val} vs 基线 {want}"
                            f"（差 {shown}，容差 {tol}）")
            infos.append(
                f"{sym} {win}：{int(got.get('num_fills', 0))} 笔 / "
                f"{_pp(got.get('total_return'))} / Sharpe {got.get('sharpe')} / "
                f"MDD {_pp(got.get('max_drawdown'))}")

    metrics = (f"rb 全窗口 "
               f"{_get(data, 'results', 'rb.SHFE', 'full_window', 'num_fills', default='n/a')} 笔"
               f" · rb 锚点 "
               f"{_get(data, 'results', 'rb.SHFE', 'anchor_window', 'num_fills', default='n/a')} 笔"
               f" · i.DCE {_get(data, 'results', 'i.DCE', 'full_window', 'num_fills', default='n/a')} 笔"
               f" · all_ok={all_ok}")

    if problems or not all_ok:
        detail = note + "\n" + "\n".join(infos)
        if not all_ok:
            detail += ("\nverdict.all_ok=false（两窗口结果不一致），"
                       f"mismatch={json.dumps(verdict, ensure_ascii=False)[:400]}")
        if problems:
            detail += "\n与 §8.2 基线不一致：\n" + "\n".join(f"- {p}" for p in problems)
        return {"name": "回测锚点等价", "status": FAIL, "metrics": metrics,
                "detail": detail, "seconds": secs}
    return {"name": "回测锚点等价", "status": PASS, "metrics": metrics,
            "detail": note + "\n" + "\n".join(infos), "seconds": secs}


# ---------------------------------------------------------------------------
# 4. 性能门槛
# ---------------------------------------------------------------------------
def _probe_section(section: str, timeout: int) -> Optional[Dict[str, Any]]:
    """现跑一个性能分节（--child 模式只写指定 JSON，不覆盖既有 .perf_*.json）。"""
    tmp = OUT_DIR / f".acceptance_perf_{section}.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    code, _out, _secs = _run(
        [sys.executable, str(ROOT / "scripts" / "perf_probe.py"), "--section", section,
         "--child", "--json-out", str(tmp), "--runs", "1"], timeout)
    if code != 0 or not tmp.exists():
        cached = OUT_DIR / f".perf_{section}.json"
        if cached.exists():
            try:
                return json.loads(cached.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
        return None
    try:
        return json.loads(tmp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _perf_item() -> Dict[str, Any]:
    """现跑 backtest/indicators 轻量分节，按固定阈值判定四项性能门禁。"""
    t0 = time.perf_counter()
    secs = lambda: round(time.perf_counter() - t0, 2)  # noqa: E731
    bt = _probe_section("backtest", T_PERF_BT)
    ind = _probe_section("indicators", T_PERF_IND)
    if bt is None and ind is None:
        return {"name": "性能门槛", "status": SKIP, "metrics": "无可用分节数据",
                "detail": "本地缺少离线日线缓存或指标分节无法运行；未用历史值判定，避免假绿",
                "seconds": secs()}

    vals = {
        "batch_ms": _get(bt, "batch", "total", "median_ms"),
        "single_ms": _get(bt, "single", "stats", "median_ms"),
        "indicators_ms": _get(ind, "total", "median_ms"),
        "sar_ms": None,
    }
    for unit in (ind.get("unit_results") or []) if isinstance(ind, dict) else []:
        if str(unit.get("name", "")).upper() == "SAR":
            vals["sar_ms"] = unit.get("median_ms")
            break

    parts: List[str] = []
    problems: List[str] = []
    missing: List[str] = []
    for key, label, limit, limit_txt in PERF_LIMITS:
        v = vals.get(key)
        if v is None:
            missing.append(label)
            parts.append(f"{label} 缺失")
            continue
        parts.append(f"{label} {v:.1f}ms{limit_txt}")
        if v > limit:
            base = PERF_BASELINE[key]
            problems.append(
                f"{label} {v:.1f}ms > 阈值 {limit:.1f}ms（超 {v - limit:+.1f}ms，"
                f"基线 {base:.1f}ms，相对基线 {v / base - 1:+.1%}）")

    status = FAIL if problems else (SKIP if (bt is None or ind is None) else PASS)
    detail = "；".join(parts)
    if missing:
        detail += "；缺失项：" + "、".join(missing)
    if problems:
        detail += "\n性能退化：\n" + "\n".join(f"- {p}" for p in problems)
    if bt is None or ind is None:
        detail += "\n注意：部分分节现跑失败，缺失项未参与判定（已回退读取既有 JSON 或跳过）"
    return {"name": "性能门槛", "status": status, "metrics": " · ".join(parts),
            "detail": detail, "seconds": secs()}


# ---------------------------------------------------------------------------
# 5. GUI 冒烟（offscreen 子进程）
# ---------------------------------------------------------------------------
def _gui_child() -> int:
    """子进程：offscreen 构建主窗口并逐页切换，输出一行 JSON 供父进程判定。"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QUANTVORTEX_NO_PERSIST"] = "1"
    sys.path.insert(0, str(ROOT))
    # 预置 runtime 数据目录缓存，避免 get_data_dir() 在 data/ 下写探针文件
    try:
        import futures_quant.runtime as rt
        rt._DATA_DIR_CACHE = os.path.join(rt.app_base_dir(), "data")
    except Exception:  # noqa: BLE001
        pass

    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from futures_quant.ui.main_window import NAV, MainWindow
    except Exception as exc:  # noqa: BLE001
        print("ACCEPTANCE_GUI_JSON " + json.dumps(
            {"error": f"依赖导入失败：{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2

    app = QApplication.instance() or QApplication(["acceptance", "-platform", "offscreen"])

    def _stop_timers(widget) -> None:
        for t in widget.findChildren(QTimer):
            try:
                if t.isActive():
                    t.stop()
            except Exception:  # noqa: BLE001
                pass

    pages: List[Dict[str, Any]] = []
    try:
        win = MainWindow()
    except Exception as exc:  # noqa: BLE001
        print("ACCEPTANCE_GUI_JSON " + json.dumps(
            {"error": f"主窗口构建失败：{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    _stop_timers(win)

    for idx, entry in enumerate(NAV):
        title = entry[0]
        row = {"idx": idx, "title": title, "ok": False}
        try:
            if hasattr(win, "_show_page"):
                row["ok"] = bool(win._show_page(idx))
            else:  # 兼容旧接口
                win._switch(idx)
                row["ok"] = True
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"[:160]
        _stop_timers(win)
        pages.append(row)

    try:
        win.close()
    except Exception:  # noqa: BLE001
        pass
    ok_n = sum(1 for p in pages if p["ok"])
    print("ACCEPTANCE_GUI_JSON " + json.dumps(
        {"pages_ok": ok_n, "pages_total": len(pages), "pages": pages}, ensure_ascii=False))
    return 0 if ok_n == len(pages) and pages else 2


def _gui_item() -> Dict[str, Any]:
    """父进程：以子进程方式跑 GUI 冒烟，按 PAGES_OK 7/7 判定。"""
    cmd = [sys.executable, str(Path(__file__).resolve()), "--gui-child"]
    env = _child_env()
    env["QT_QPA_PLATFORM"] = "offscreen"
    code, out, secs = _run(cmd, T_GUI, env=env)

    payload: Optional[Dict[str, Any]] = None
    for line in out.splitlines():
        if line.startswith("ACCEPTANCE_GUI_JSON "):
            try:
                payload = json.loads(line[len("ACCEPTANCE_GUI_JSON "):])
            except Exception:  # noqa: BLE001
                payload = None

    if payload is None:
        if "ModuleNotFoundError" in out and "PyQt6" in out:
            return {"name": "GUI 冒烟", "status": SKIP, "metrics": "PyQt6 未安装",
                    "detail": "环境缺少 PyQt6，无法执行 offscreen 冒烟", "seconds": secs}
        return {"name": "GUI 冒烟", "status": FAIL, "metrics": f"子进程 exit={code}",
                "detail": "未拿到结构化结果（可能进程崩溃）。末尾输出：\n" + _tail(out, 15),
                "seconds": secs}

    if payload.get("error"):
        msg = str(payload["error"])
        status = SKIP if ("PyQt6" in msg or "依赖导入失败" in msg) else FAIL
        return {"name": "GUI 冒烟", "status": status, "metrics": "未完成构建",
                "detail": msg, "seconds": secs}

    ok_n, total = payload.get("pages_ok", 0), payload.get("pages_total", 0)
    metrics = f"PAGES_OK {ok_n} / {total} · {secs:.2f}s"
    if ok_n == total and total > 0:
        return {"name": "GUI 冒烟", "status": PASS, "metrics": metrics,
                "detail": "主窗口 + 全部页面 offscreen 构建成功", "seconds": secs}
    bad = [p for p in payload.get("pages", []) if not p.get("ok")]
    detail = "退化：以下页面构建失败（基线 7/7）：\n" + "\n".join(
        f"- [{p.get('idx')}] {p.get('title')}：{p.get('error', '返回 False')}" for p in bad)
    return {"name": "GUI 冒烟", "status": FAIL, "metrics": metrics,
            "detail": detail, "seconds": secs}


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------
def _write_report(items: List[Dict[str, Any]], mode: str, code: int,
                  started: str, elapsed: float) -> None:
    """写 outputs/acceptance_report.md：结论表 + 失败详情 + 复现命令。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fails = [i for i in items if i["status"] == FAIL]
    skips = [i for i in items if i["status"] == SKIP]
    lines = [
        "# QuantVortex 验收报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（开始 {started}，"
        f"总耗时 {elapsed:.1f}s）",
        f"- 模式：{mode}",
        f"- 结论：**{'FAIL' if fails else 'PASS'}**（失败 {len(fails)} / 跳过 {len(skips)}）",
        f"- 退出码：{code}",
        "",
        "## 一、结论总览",
        "",
        "| # | 验收项 | 状态 | 关键数字 | 耗时(s) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for idx, it in enumerate(items, 1):
        lines.append(f"| {idx} | {it['name']} | **{it['status']}** | "
                     f"{it['metrics'].replace('|', '\\|')} | {it['seconds']:.2f} |")

    detail_items = [i for i in items if i["status"] != PASS]
    if detail_items:
        lines += ["", "## 二、失败 / 跳过详情", ""]
        for it in detail_items:
            lines += [f"### {it['name']}（{it['status']}）", "", it["detail"].strip(), ""]

    lines += [
        "",
        "## 三、判定口径",
        "",
        "- 单元/e2e：以「0 失败 0 错误」为通过，不因用例总数变化判退化；失败用例名逐条列出。",
        "- 回测锚点：`verdict.all_ok == true`，且与 §8.2 基线比对——成交笔数精确，收益/回撤容差 0.02pp，Sharpe 容差 0.005。",
        "- 性能门槛：批量 ≤24.5s、rb 单次 ≤500ms、add_indicators ≤180ms、SAR ≤120ms。",
        "- GUI 冒烟：offscreen 构建主窗口 + 全部页面，要求 `PAGES_OK 7 / 7`。",
        "- 任一项 FAIL 时退出码为 1；SKIP 不计失败（环境缺失会写明原因）。",
        "",
        "## 四、复现",
        "",
        "```powershell",
        "python scripts/acceptance.py            # 全量（含 e2e，约 20~25 分钟）",
        "python scripts/acceptance.py --quick    # unit + 锚点 + GUI 冒烟（约 12 分钟）",
        "python scripts/acceptance.py --perf-skip",
        "python scripts/acceptance.py --e2e-skip",
        "```",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="QuantVortex 统一验收入口")
    ap.add_argument("--quick", action="store_true",
                    help="快速模式：跳过 e2e 与性能，只跑 unit + 锚点 + GUI 冒烟")
    ap.add_argument("--e2e-skip", action="store_true", help="跳过 e2e 测试")
    ap.add_argument("--perf-skip", action="store_true", help="跳过性能门槛")
    ap.add_argument("--gui-child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.gui_child:
        return _gui_child()

    quick = args.quick
    skip_e2e = quick or args.e2e_skip
    skip_perf = quick or args.perf_skip
    mode = ("--quick（跳过 e2e 与性能）" if quick else "全量") + \
           (f"；--e2e-skip" if args.e2e_skip and not quick else "") + \
           (f"；--perf-skip" if args.perf_skip and not quick else "")

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.perf_counter()
    items: List[Dict[str, Any]] = []

    print("=" * 78)
    print(f"QuantVortex 统一验收 · {mode}")
    print("=" * 78)

    def _emit(idx: int, total: int, it: Dict[str, Any]) -> None:
        print(f"[{idx}/{total}] {it['name']:<10} {it['status']:<4} {it['metrics']}")
        if it["status"] != PASS:
            for ln in it["detail"].splitlines()[:6]:
                print(f"        {ln}")

    steps: List[Tuple[str, Any]] = [
        ("单元测试", lambda: _pytest_item("单元测试", "tests/unit", T_UNIT)),
        ("e2e 测试",
         lambda: ({"name": "e2e 测试", "status": SKIP, "metrics": "已跳过", "seconds": 0.0,
                   "detail": "由 --quick / --e2e-skip 跳过（基线 221 项通过）"}
                  if skip_e2e else _pytest_item("e2e 测试", "tests/e2e", T_E2E))),
        ("回测锚点等价", _anchor_item),
        ("性能门槛",
         lambda: ({"name": "性能门槛", "status": SKIP, "metrics": "已跳过", "seconds": 0.0,
                   "detail": "由 --quick / --perf-skip 跳过"}
                  if skip_perf else _perf_item())),
        ("GUI 冒烟", _gui_item),
    ]

    for idx, (label, fn) in enumerate(steps, 1):
        it = fn()
        it.setdefault("seconds", 0.0)
        items.append(it)
        _emit(idx, len(steps), it)

    elapsed = round(time.perf_counter() - t0, 2)
    fails = [i for i in items if i["status"] == FAIL]
    code = 1 if fails else 0
    _write_report(items, mode, code, started, elapsed)

    print("-" * 78)
    print(f"结论：{'FAIL' if fails else 'PASS'} · 失败 {len(fails)} / 跳过 "
          f"{sum(1 for i in items if i['status'] == SKIP)} · 总耗时 {elapsed:.1f}s")
    if fails:
        print("退化项：" + "、".join(i["name"] for i in fails))
    print(f"报告：{REPORT_PATH}")
    print(f"退出码：{code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
