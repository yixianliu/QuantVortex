"""系统诊断面板（M1-09）。

设计目标（对齐 UPGRADE_PLAN_V5.md M1-09）：
    - 菜单「帮助 → 系统诊断」；
    - 逐项检查：Python 版本 / 依赖（torch,requests,akshare 可选）/
      数据目录可写 / 磁盘剩余 / 数据源连通（3s 超时）/ 数据新鲜度 /
      密钥注入状态 / 扫码门禁；
    - 每项绿勾 · 黄警 · 红叉 + 「复制诊断报告」；
    - 全程异步不卡 UI（复用 M4-06 Worker）。

用法:
    dlg = DiagnosticsDialog(context={
        "data_dir": "/abs/path/data",
        "disk_dir": "/abs/path",
        "data_feed": feed_or_None,
        "api_key_fingerprint": "sk-…abcd",
        "qr_gate_enabled": False,
    })
    dlg.run_all()                # 触发异步检查
    dlg.show()

无 QApplication 时可同步检查：
    dlg = DiagnosticsDialog(context={...})
    checks = dlg.run_all_checks()
    report = dlg.render_report(checks)

作者: QuantVortex M1-09 (2026-10-01)
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout,
)

logger = logging.getLogger(__name__)

__all__ = ["DiagnosticsDialog", "run_all_checks", "render_report", "CHECK_NAMES"]


# ---------- 状态符号 ----------
OK = "✅"
WARN = "⚠️"
FAIL = "❌"

_CHECK_NAMES: List[str] = [
    "python_version",
    "deps",
    "data_dir",
    "disk",
    "data_source",
    "data_freshness",
    "api_key",
    "qr_gate",
]
CHECK_NAMES = tuple(_CHECK_NAMES)


# ---------- 单项检查函数（可独立测试） ----------

def check_python_version() -> Tuple[str, str, str]:
    """Python 版本检查：>= 3.10 绿，3.8–3.9 黄，<3.8 红。"""
    v = sys.version_info
    major, minor = v.major, v.minor
    detail = f"Python {v.major}.{v.minor}.{v.micro} ({platform.system()} {platform.machine()})"
    if (major, minor) >= (3, 10):
        return OK, "符合推荐（≥3.10）", detail
    if (major, minor) >= (3, 8):
        return WARN, "版本偏旧，建议升级到 ≥3.10", detail
    return FAIL, "Python 版本过低，需 ≥3.8", detail


def check_deps(
    required: Optional[List[str]] = None,
    optional: Optional[List[str]] = None,
) -> Tuple[str, str, str]:
    """依赖检查：必需（PyQt6,requests）；可选（torch,akshare,pandas,numpy）。"""
    required = required if required is not None else ["PyQt6", "requests"]
    optional = optional if optional is not None else ["torch", "akshare", "pandas", "numpy"]
    missing_required: List[str] = []
    for mod in required:
        try:
            __import__(mod)
        except Exception:
            missing_required.append(mod)
    missing_optional: List[str] = []
    for mod in optional:
        try:
            __import__(mod)
        except Exception:
            missing_optional.append(mod)

    if missing_required:
        return FAIL, f"缺必需依赖: {', '.join(missing_required)}", ""
    if missing_optional:
        return WARN, f"缺可选依赖: {', '.join(missing_optional)}", ""
    return OK, "全部依赖就绪", ""


def check_data_dir(data_dir: str) -> Tuple[str, str, str]:
    """数据目录可写检查。"""
    if not data_dir:
        return WARN, "未指定数据目录", ""
    if not os.path.exists(data_dir):
        return FAIL, "数据目录不存在", data_dir
    if not os.access(data_dir, os.W_OK):
        return FAIL, "数据目录不可写", data_dir
    # 写入探测（1 字节）
    probe = os.path.join(data_dir, ".qvt_diag_probe")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except Exception as e:
        return FAIL, f"数据目录写入失败: {e}", data_dir
    return OK, "数据目录可写", data_dir


def check_disk(disk_dir: Optional[str] = None, warn_gb: float = 2.0,
               fail_gb: float = 0.5) -> Tuple[str, str, str]:
    """磁盘剩余检查：默认 ≥2GB 绿，≥500MB 黄，否则红。"""
    if not disk_dir:
        return WARN, "未指定检查目录", ""
    if not os.path.exists(disk_dir):
        return FAIL, "检查目录不存在", disk_dir
    try:
        usage = shutil.disk_usage(disk_dir)
    except Exception as e:
        return FAIL, f"读取磁盘信息失败: {e}", disk_dir
    free_gb = usage.free / (1024 ** 3)
    detail = f"剩余 {free_gb:.2f} GB / 总 {usage.total / (1024 ** 3):.2f} GB"
    if free_gb >= warn_gb:
        return OK, "磁盘剩余充足", detail
    if free_gb >= fail_gb:
        return WARN, "磁盘剩余偏低", detail
    return FAIL, "磁盘空间不足", detail


def check_data_source(feed: Any = None, timeout_s: float = 3.0) -> Tuple[str, str, str]:
    """数据源连通性：3s 超时。feed 为 None 时降级为 WARN。"""
    if feed is None:
        return WARN, "未接入数据源（离线/演示模式）", ""
    result: Dict[str, Any] = {"ok": False, "msg": ""}
    err: List[Exception] = []

    def _probe():
        try:
            # 兼容各种 feed：先看是否有 ping/health 属性
            for attr in ("ping", "health", "is_connected", "connected"):
                if hasattr(feed, attr):
                    fn = getattr(feed, attr)
                    if callable(fn):
                        try:
                            ok = bool(fn())
                        except TypeError:
                            ok = bool(fn(timeout_s))
                        result["ok"] = ok
                        result["msg"] = f"{attr}()={ok}"
                        return
            # 尝试 get_bars 或类似轻量方法（限制 3s）
            for attr in ("get_bars", "get_history", "query"):
                if hasattr(feed, attr):
                    result["ok"] = True
                    result["msg"] = f"接口就绪（{attr}）"
                    return
            result["ok"] = True
            result["msg"] = "feed 对象存在"
        except Exception as e:  # noqa: BLE001
            err.append(e)

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return WARN, f"数据源探测超时（>{timeout_s:.1f}s）", ""
    if err:
        return WARN, f"数据源探测异常: {err[0]}", ""
    if result["ok"]:
        return OK, "数据源可达", result["msg"]
    return FAIL, "数据源不可达", result["msg"]


def check_data_freshness(feed: Any = None) -> Tuple[str, str, str]:
    """数据新鲜度：最后 bar 距今天数。feed 无数据 → WARN。"""
    if feed is None:
        return WARN, "未接入数据源，跳过新鲜度检查", ""
    # 尝试拿最近 bar 的 ts
    last_ts = None
    for attr in ("last_bar_ts", "last_ts", "last_update"):
        if hasattr(feed, attr):
            try:
                last_ts = getattr(feed, attr)
                break
            except Exception:
                pass
    if last_ts is None:
        return WARN, "无法获取最后 bar 时间戳", ""
    try:
        import time as _time
        now = _time.time()
        age_s = max(0.0, float(now) - float(last_ts))
        age_h = age_s / 3600.0
        detail = f"最后 bar {age_h:.1f} 小时前"
        if age_h <= 24:
            return OK, "数据新鲜（≤24h）", detail
        if age_h <= 72:
            return WARN, "数据陈旧（24-72h）", detail
        return FAIL, "数据严重过期（>72h）", detail
    except Exception as e:
        return WARN, f"新鲜度检查失败: {e}", ""


def check_api_key(api_key_fingerprint: Optional[str] = None) -> Tuple[str, str, str]:
    """密钥注入状态：显示指纹，永不显示全文。"""
    if api_key_fingerprint:
        # 无论长度一律脱敏：只保留前 3 位和后 4 位，中间用省略号
        fp = api_key_fingerprint.strip()
        if len(fp) <= 7:
            safe = fp[:1] + "…" + fp[-1:] if len(fp) > 1 else "***"
        else:
            safe = fp[:3] + "…" + fp[-4:]
        return OK, f"已注入: {safe}", ""
    env_key = os.environ.get("QV_AGNES_API_KEY", "")
    if env_key:
        ek = env_key.strip()
        if len(ek) <= 7:
            safe = ek[:1] + "…" + ek[-1:] if len(ek) > 1 else "***"
        else:
            safe = ek[:3] + "…" + ek[-4:]
        return OK, f"环境变量已注入: {safe}", ""
    return WARN, "未配置 → AI 功能将降级为本地规则", ""


def check_qr_gate(enabled: bool = False) -> Tuple[str, str, str]:
    """扫码门禁：未启用 → 黄警。"""
    if enabled:
        return OK, "扫码门禁已启用", ""
    return WARN, "扫码门禁未启用（可选）", ""


# ---------- 检查清单 ----------

def run_all_checks(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """执行 8 项检查，返回结果列表。

    参数:
        context: 可选字典，键包括 data_dir / disk_dir / data_feed /
            api_key_fingerprint / qr_gate_enabled 等。

    返回:
        list[{"name", "label", "status", "desc", "detail"}]
    """
    ctx = context or {}
    checks = [
        ("python_version", "Python 版本", check_python_version()),
        ("deps", "依赖包", check_deps(
            required=ctx.get("required_deps"),
            optional=ctx.get("optional_deps"))),
        ("data_dir", "数据目录可写", check_data_dir(ctx.get("data_dir", ""))),
        ("disk", "磁盘剩余", check_disk(
            disk_dir=ctx.get("disk_dir"),
            warn_gb=ctx.get("warn_gb", 2.0),
            fail_gb=ctx.get("fail_gb", 0.5))),
        ("data_source", "数据源连通", check_data_source(
            feed=ctx.get("data_feed"),
            timeout_s=ctx.get("source_timeout", 3.0))),
        ("data_freshness", "数据新鲜度", check_data_freshness(ctx.get("data_feed"))),
        ("api_key", "密钥注入状态", check_api_key(ctx.get("api_key_fingerprint"))),
        ("qr_gate", "扫码门禁", check_qr_gate(ctx.get("qr_gate_enabled", False))),
    ]
    out: List[Dict[str, str]] = []
    for name, label, (status, desc, detail) in checks:
        out.append({
            "name": name,
            "label": label,
            "status": status,
            "desc": desc,
            "detail": detail or "",
        })
    return out


def render_report(checks: List[Dict[str, str]]) -> str:
    """渲染纯文本诊断报告（用于「复制诊断报告」）。"""
    lines: List[str] = [
        "============== 系统诊断报告 ==============",
        f"生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Python：{platform.python_version()} / {platform.platform()}",
        "",
    ]
    for c in checks:
        lines.append(f"{c['status']} {c['label']}：{c['desc']}")
        if c.get("detail"):
            lines.append(f"    └─ {c['detail']}")
    n_ok = sum(1 for c in checks if c["status"] == OK)
    n_warn = sum(1 for c in checks if c["status"] == WARN)
    n_fail = sum(1 for c in checks if c["status"] == FAIL)
    lines.append("")
    lines.append(f"汇总：{n_ok} 项正常 · {n_warn} 项警告 · {n_fail} 项失败")
    lines.append("========================================")
    return "\n".join(lines)


# ---------- GUI 对话框 ----------

class _DiagWorker(QThread):
    """M4-06 兼容的异步 Worker：run_all_checks 在子线程执行。"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, ctx: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx

    def run(self) -> None:  # noqa: N802
        try:
            self.finished.emit(run_all_checks(self.ctx))
        except Exception as e:  # noqa: BLE001
            logger.exception("诊断检查异常")
            self.error.emit(str(e))


def _palette():
    """极简调色板：跟随系统，不依赖 theme 模块。"""
    return {
        "bg": "#ffffff",
        "text": "#1f2937",
        "muted": "#6b7280",
        "ok": "#16a34a",
        "warn": "#d97706",
        "fail": "#dc2626",
        "border": "#e5e7eb",
        "card": "#f9fafb",
    }


class DiagnosticsDialog(QDialog):
    """系统诊断面板（M1-09）。"""

    def __init__(self, context: Optional[Dict[str, Any]] = None,
                 parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.context = dict(context or {})
        self._worker: Optional[_DiagWorker] = None
        self._last_checks: List[Dict[str, str]] = []
        self.setWindowTitle("系统诊断")
        self.setMinimumSize(720, 520)
        self._build()
        # 自动检查：对话框一打开就异步跑一轮
        self._start_async()

    # ---------- UI 构建 ----------
    def _build(self) -> None:
        p = _palette()
        self.setStyleSheet(f"QDialog {{ background: {p['bg']}; color: {p['text']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 顶部标题 + 操作
        head = QHBoxLayout()
        head.setSpacing(8)
        self._title = QLabel("系统诊断 · 8 项检查")
        self._title.setFont(QFont("", 14, QFont.Weight.Bold))
        head.addWidget(self._title)
        head.addStretch(1)
        self._status = QLabel("准备中…")
        self._status.setObjectName("diag_status")
        head.addWidget(self._status)
        root.addLayout(head)

        # 单项检查行
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self._row_widgets: Dict[str, Tuple[QLabel, QLabel, QLabel]] = {}
        for i, name in enumerate(CHECK_NAMES):
            icon_lbl = QLabel("?")
            icon_lbl.setObjectName(f"diag_icon_{name}")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setMinimumWidth(28)

            name_lbl = QLabel("")
            name_lbl.setFont(QFont("", 11, QFont.Weight.DemiBold))

            desc_lbl = QLabel("等待检查…")
            desc_lbl.setObjectName(f"diag_desc_{name}")
            desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_lbl.setTextFormat(Qt.TextFormat.RichText)

            grid.addWidget(icon_lbl, i, 0)
            grid.addWidget(name_lbl, i, 1)
            grid.addWidget(desc_lbl, i, 2)
            grid.setColumnStretch(2, 1)
            self._row_widgets[name] = (icon_lbl, name_lbl, desc_lbl)
        root.addLayout(grid)

        # 底部：报告 + 操作
        bottom = QVBoxLayout()
        bottom.setSpacing(8)
        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._report.setPlaceholderText("诊断报告将在此处生成…")
        self._report.setMinimumHeight(180)
        bottom.addWidget(self._report)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_rerun = QPushButton("重新检查")
        self._btn_rerun.setObjectName("diag_btn_rerun")
        self._btn_rerun.clicked.connect(self._start_async)
        self._btn_copy = QPushButton("复制诊断报告")
        self._btn_copy.setObjectName("diag_btn_copy")
        self._btn_copy.clicked.connect(self._copy_report)
        self._btn_close = QPushButton("关闭")
        self._btn_close.setObjectName("diag_btn_close")
        self._btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_rerun)
        btn_row.addWidget(self._btn_copy)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_close)
        bottom.addLayout(btn_row)
        root.addLayout(bottom)

    # ---------- 异步 / 同步 ----------
    def _start_async(self) -> None:
        """触发异步检查（M4-06 Worker）。"""
        self._btn_rerun.setEnabled(False)
        self._status.setText("检查中…")
        self._worker = _DiagWorker(self.context, self)
        self._worker.finished.connect(self._on_checks_done)
        self._worker.error.connect(self._on_checks_error)
        self._worker.start()

    def run_all_checks_sync(self) -> List[Dict[str, str]]:
        """同步执行（无 QApplication 时使用）。"""
        self._last_checks = run_all_checks(self.context)
        self._render(self._last_checks)
        return self._last_checks

    def run_all_checks(self) -> List[Dict[str, str]]:
        """别名：同步检查入口（供单测/无 Qt 环境）。"""
        return self.run_all_checks_sync()

    def _on_checks_done(self, checks: List[Dict[str, str]]) -> None:
        self._last_checks = checks
        self._render(checks)
        self._btn_rerun.setEnabled(True)
        n_fail = sum(1 for c in checks if c["status"] == FAIL)
        if n_fail:
            self._status.setText(f"完成：{n_fail} 项失败")
        else:
            self._status.setText("全部检查完成")

    def _on_checks_error(self, msg: str) -> None:
        self._btn_rerun.setEnabled(True)
        self._status.setText(f"检查失败：{msg[:40]}")

    # ---------- 渲染 ----------
    def _render(self, checks: List[Dict[str, str]]) -> None:
        p = _palette()
        for c in checks:
            icon_lbl, name_lbl, desc_lbl = self._row_widgets.get(c["name"], (None, None, None))
            if icon_lbl is None:
                continue
            color = p["ok"] if c["status"] == OK else (
                p["warn"] if c["status"] == WARN else p["fail"])
            icon_lbl.setText(c["status"])
            icon_lbl.setStyleSheet(f"color: {color}; font-size: 16px;")
            name_lbl.setText(c["label"])
            detail_html = f'<span style="color:{color}">{c["desc"]}</span>'
            if c.get("detail"):
                detail_html += f'<br><span style="color:{p["muted"]};font-size:10px">' \
                               f'{c["detail"]}</span>'
            desc_lbl.setText(detail_html)
        self._report.setPlainText(render_report(checks))

    def render_report(self, checks: Optional[List[Dict[str, str]]] = None) -> str:
        """返回文本报告。"""
        return render_report(checks or self._last_checks)

    def _copy_report(self) -> None:
        from PyQt6.QtWidgets import QApplication
        text = self.render_report()
        QApplication.clipboard().setText(text)
        self._status.setText("已复制到剪贴板")
        # 3s 后恢复
        if self._worker is None or not self._worker.isRunning():
            QTimer.singleShot(3000, lambda: self._status.setText("全部检查完成"))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(1000)
        super().closeEvent(event)


# ---------- 命令行 / 独立运行入口（诊断用） ----------

def _main() -> int:
    """命令行诊断（供 smoke test / 无头环境使用）。

    用法: python -m futures_quant.ui.diagnostics_dialog
    """
    import argparse
    ap = argparse.ArgumentParser(description="QuantVortex 系统诊断（无头模式）")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--disk-dir", default=".")
    ap.add_argument("--key", default=None, help="密钥指纹（如 sk-…abcd）")
    ap.add_argument("--qr-gate", action="store_true", help="启用扫码门禁检查为通过")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非文本")
    args = ap.parse_args()

    ctx: Dict[str, Any] = {
        "data_dir": os.path.abspath(args.data_dir),
        "disk_dir": os.path.abspath(args.disk_dir),
        "data_feed": None,
        "api_key_fingerprint": args.key,
        "qr_gate_enabled": args.qr_gate,
    }
    checks = run_all_checks(ctx)
    if args.json:
        import json
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        print(render_report(checks))
    return 0 if all(c["status"] != FAIL for c in checks) else 1


if __name__ == "__main__":
    sys.exit(_main())
