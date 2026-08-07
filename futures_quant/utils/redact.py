"""敏感信息脱敏（日志 / 异常 / 界面提示统一出口）。

威胁模型：
    即便密钥本身不落盘，它仍可能通过以下路径泄露给终端用户或客服渠道：
        * logger.info(f"请求头 {headers}")          —— 日志文件
        * requests 抛异常时 URL 带 ?token=xxx        —— traceback
        * 未捕获异常直接打印到控制台 / 崩溃弹窗       —— 用户截图外发
    本模块在「输出侧」统一拦截，无论上游代码是否小心，密钥都不会成文。

使用：
    from futures_quant.utils.redact import redact, install_global_redaction
    install_global_redaction()          # 程序启动时调用一次
    log.info(redact(some_text))         # 手动脱敏（logger 已自动接入）

设计原则：
    宁可过度脱敏，也不可漏掉。日志的可读性让位于密钥安全。
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import traceback
from typing import Any, Callable, Iterable

MASK = "***REDACTED***"

# ---------------------------------------------------------------------------
# 规则表：(正则, 替换)
# 替换为 callable 时可保留键名、只抹掉值，便于排障时仍看得出「哪个字段」被抹。
# ---------------------------------------------------------------------------


def _keep_prefix(match: "re.Match[str]") -> str:
    """保留键名与分隔符，仅替换值部分。"""
    return f"{match.group(1)}{MASK}"


_RULES: list[tuple[re.Pattern[str], Any]] = [
    # 各家云厂商的强特征密钥
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), MASK),
    (re.compile(r"AKIA[0-9A-Z]{16}"), MASK),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), MASK),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), MASK),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), MASK),
    # Authorization 头（Bearer / Basic）
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-+/=]{8,}"), _keep_prefix),
    (re.compile(r"(?i)(Basic\s+)[A-Za-z0-9+/=]{8,}"), _keep_prefix),
    # JWT：三段 base64
    (re.compile(r"eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"),
     MASK),
    # 私钥块
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?"
                r"-----END [A-Z ]*PRIVATE KEY-----"), MASK),
    # URL 中的凭据：https://user:pass@host
    (re.compile(r"(https?://[^:/\s]+:)[^@/\s]+(@)"),
     lambda m: f"{m.group(1)}{MASK}{m.group(2)}"),
    # 查询参数中的密钥
    (re.compile(r"(?i)([?&](?:api[_-]?key|token|access[_-]?token|"
                r"secret|password|sig|signature)=)[^&\s\"']+"), _keep_prefix),
    # 字典 / 赋值形式：key="value" 或 'key': 'value'
    (re.compile(r"(?i)([\"']?(?:api[_-]?key|apikey|secret|token|password|passwd|"
                r"pwd|authorization|auth[_-]?token|access[_-]?token|"
                r"client[_-]?secret)[\"']?\s*[:=]\s*[\"']?)"
                r"[^\s,;}\)\"']{6,}"), _keep_prefix),
]

# 运行时登记的精确密钥（例如内存中真实存在的令牌），永远抹掉
_exact_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """登记一个运行时已知的密钥，后续任何输出都会将其抹除。

    适用于「密钥从服务端下发、只存在于内存」的场景：即便它不匹配任何
    通用规则，也能保证不会被打印出来。
    """
    if not value or len(value) < 6:
        return
    with _lock:
        _exact_secrets.add(value)


def clear_registered_secrets() -> None:
    """清空运行时登记的密钥（主要供测试使用）。"""
    with _lock:
        _exact_secrets.clear()


def redact(value: Any) -> str:
    """对任意对象做脱敏，返回安全可输出的字符串。

    本函数保证不抛异常：脱敏失败时退化为通用占位符，
    绝不因为脱敏逻辑本身的问题而把原文泄露出去。
    """
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return "<不可转换为字符串的对象>"

    try:
        # 先抹精确登记的密钥（最高优先级）
        with _lock:
            secrets = tuple(_exact_secrets)
        for s in secrets:
            if s in text:
                text = text.replace(s, MASK)
        # 再套用通用规则
        for rx, repl in _RULES:
            text = rx.sub(repl, text)
        return text
    except Exception:
        # 脱敏过程异常时宁可丢信息，也不能原样返回
        return "<脱敏失败，内容已丢弃>"


def redact_mapping(mapping: dict) -> dict:
    """脱敏字典（常用于 HTTP headers / params 的调试输出）。"""
    out = {}
    for k, v in mapping.items():
        key_l = str(k).lower()
        if any(t in key_l for t in ("authorization", "key", "token", "secret",
                                    "password", "cookie", "auth")):
            out[k] = MASK
        else:
            out[k] = redact(v)
    return out


# ---------------------------------------------------------------------------
# logging 接入
# ---------------------------------------------------------------------------
class RedactingFilter(logging.Filter):
    """在记录进入 handler 前脱敏消息与参数。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """过滤相关对象。
        
            参数:
                record: logging.LogRecord
        
            返回:
                bool"""
        try:
            if record.args:
                # 提前把参数渲染进消息，避免 args 里的密钥绕过脱敏
                record.msg = redact(record.getMessage())
                record.args = ()
            else:
                record.msg = redact(record.msg)
        except Exception:
            record.msg = "<日志脱敏失败，内容已丢弃>"
            record.args = ()
        return True


class RedactingFormatter(logging.Formatter):
    """对最终格式化结果（含 traceback）再做一次脱敏。

    这是最后一道闸门：`exc_info` 渲染出的调用栈里可能带有局部变量、
    URL、请求头等内容，只有在 format() 之后才能完整覆盖。
    """

    def format(self, record: logging.LogRecord) -> str:
        """格式化相关对象。
        
            参数:
                record: logging.LogRecord
        
            返回:
                str"""
        return redact(super().format(record))


# ---------------------------------------------------------------------------
# 全局未捕获异常钩子
# ---------------------------------------------------------------------------
_original_excepthook: Callable | None = None
_installed = False


def _redacting_excepthook(exc_type, exc_value, exc_tb) -> None:
    """未捕获异常：脱敏后再输出到 stderr。"""
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(redact(text))
    except Exception:
        sys.stderr.write(f"未捕获异常：{exc_type.__name__}（详情已脱敏丢弃）\n")


def _redacting_threading_excepthook(args) -> None:
    """子线程未捕获异常：同样脱敏。"""
    _redacting_excepthook(args.exc_type, args.exc_value, args.exc_traceback)


def install_global_redaction(*, patch_root_logger: bool = True) -> None:
    """安装全局脱敏钩子（幂等，可重复调用）。

    Args:
        patch_root_logger: 是否给 root logger 的现有 handler 也挂上脱敏过滤器，
                           以覆盖第三方库（requests / urllib3 等）的日志输出。
    """
    global _installed, _original_excepthook
    if _installed:
        return

    _original_excepthook = sys.excepthook
    sys.excepthook = _redacting_excepthook
    try:
        threading.excepthook = _redacting_threading_excepthook
    except Exception:
        pass

    if patch_root_logger:
        root = logging.getLogger()
        flt = RedactingFilter()
        for h in root.handlers:
            h.addFilter(flt)
        root.addFilter(flt)

    _installed = True


def attach_to_logger(logger: logging.Logger) -> logging.Logger:
    """给指定 logger 的所有 handler 挂上脱敏过滤器与格式化器。"""
    flt = RedactingFilter()
    logger.addFilter(flt)
    for h in logger.handlers:
        h.addFilter(flt)
        existing = h.formatter
        if existing is not None and not isinstance(existing, RedactingFormatter):
            h.setFormatter(RedactingFormatter(
                fmt=existing._fmt, datefmt=existing.datefmt))
    return logger


def iter_rules() -> Iterable[str]:
    """返回当前生效的规则说明（供测试与文档使用）。"""
    return (rx.pattern for rx, _ in _RULES)
