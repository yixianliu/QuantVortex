"""密钥泄露扫描器（构建门禁 + 产物验证）。

两种用途：
    1. 构建前扫描源码树，发现硬编码密钥立即阻断打包；
    2. 构建后扫描 dist/ 产物（exe / pyc / dll 等二进制），
       证明打包结果中不含任何上游密钥。

设计要点：
    * 文本文件按行扫描并给出行号；二进制文件按字节扫描并给出偏移量。
    * `.pyc` 一律按二进制处理 —— 编译不是加密，字符串常量原样保留，
      历史上本项目正是在 `__pycache__` 里泄露过真实密钥。
    * 输出中的命中内容一律掩码，避免扫描报告本身成为新的泄露源。
    * 支持 `--literal` 精确查找已知的历史泄露密钥，用于确认清除干净。

命令行：
    python build_tools/secret_scan.py                      # 扫描项目源码
    python build_tools/secret_scan.py dist --binary-only   # 扫描打包产物
    python build_tools/secret_scan.py --literal sk-abc123  # 追查特定密钥

退出码：
    0 = 未发现问题；1 = 发现疑似密钥；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---------------------------------------------------------------------------
# 规则定义
# ---------------------------------------------------------------------------
# high=True 的规则误报率极低，会同时用于二进制扫描；
# high=False 的规则（通用赋值）仅用于文本扫描，并额外做熵值过滤。
_RULES: list[tuple[str, str, bool]] = [
    # openai_key：sk- 开头，主体是一段**连续的**字母数字（≥20 位），
    # 可带 proj- / ant- 厂商前缀。
    #
    # 为什么用「连续主体长度」而不是负向预查排除关键词：
    # 打包产物里已核实的第三方误报全都是「连字符拼接的英文单词」——
    #     libssh2.dll   sk-ecdsa-sha2-nistp256-cert-v01（SSH 密钥类型名）
    #     babel/*.dat   sk-Kamchatski-standaardtyd（Petropavlovsk-Kamchatski 时区名）
    #     examples.json sk-definition-1470764550877（示例数据 task-definition-<ts>）
    # 这些串里最长的连续字母数字段都 <20 位，而真实密钥的主体必然是
    # 一整段高熵连续字符。用这条本质差异判别，比逐个拉黑关键词稳健得多
    # —— 关键词黑名单每遇到一个新库就要补一次，且极易顺手排除掉真密钥
    # （曾用 (?![A-Z]) 排除城市名，结果把所有大写开头的真密钥一并放过）。
    ("openai_key",    r"sk-(?:proj-|ant-)?[A-Za-z0-9_]{20,}",       True),
    # Anthropic 的 sk-ant-api03-… 主体是 base64url，可能内嵌 - 和 _；
    # 用 40 位以上的长度约束保证不会误伤单词拼接。
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_\-]{40,}",                True),
    ("bearer_token",  r"Bearer\s+[A-Za-z0-9._\-]{20,}",             True),
    ("aws_akid",      r"AKIA[0-9A-Z]{16}",                          True),
    ("github_token",  r"gh[pousr]_[A-Za-z0-9]{30,}",                True),
    ("google_key",    r"AIza[0-9A-Za-z_\-]{35}",                    True),
    ("slack_token",   r"xox[baprs]-[A-Za-z0-9\-]{10,}",             True),
    # private_key：要求头部与 -----END 之间存在 ≥100 字符的 base64 密钥体。
    # 否则会误伤第三方库里「仅列类型名、无密钥体」的字符串——
    #   * libssh2 的 "-----BEGIN OPENSSH PRIVATE KEY-----\n-----END ..."（紧邻、无体）
    #   * Qt6Network 的 "-----BEGIN RSA/DSA/EC PRIVATE KEY-----" 枚举常量表
    # 真正的私钥 PEM 必有数百字符的 base64 体，故该约束不会放过真实私钥。
    ("private_key",   r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=\r\n]{100,}", True),
    ("generic_assign",
     r"(?i)(api[_-]?key|secret|token|passwd|password|pwd)"
     r"\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']",                        False),
]

_TEXT_RULES = [(n, re.compile(p), h) for n, p, h in _RULES]
_BIN_RULES = [(n, re.compile(p.encode()), h) for n, p, h in _RULES if h]

# 占位符 / 示例值白名单：命中这些词的一律不算泄露。
# 注意：这里只放「人类明显意图表达为示例」的强标记。
# 曾经把 "abcdef" / "1234" 之类的通用片段放进来，导致真密钥只要碰巧
# 含有该子串就被静默放过 —— 白名单过宽等同于没有扫描，切勿再加回去。
_PLACEHOLDER_HINTS = (
    "xxx", "your", "example", "placeholder", "dummy", "changeme", "sample",
    "<", ">", "...", "redacted", "masked", "fake", "todo",
    "insert-", "replace-me", "my-key", "mykey", "test-key", "testkey",
)

# 行内抑制标记：确属误报或测试夹具时，在同一行加注释即可放行
_SUPPRESS_MARKERS = (
    "secret-scan: allow",
    "pragma: allowlist secret",
    "nosecret",
)

_DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
    "logs", "screenshots", ".workbuddy",
}

# 纯数据/文档类扩展名：跳过以降噪（不含代码与配置）
_SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
             ".csv", ".log", ".zip", ".gz", ".7z", ".mp4", ".woff",
             ".woff2", ".ttf", ".otf"}

# 按二进制处理的扩展名
_BIN_EXT = {".pyc", ".pyo", ".exe", ".dll", ".pyd", ".so", ".dylib",
            ".bin", ".dat", ".pkg", ".toc"}


@dataclass
class Finding:
    """一条疑似密钥命中记录。"""

    path: str
    rule: str
    locator: str      # 文本为 "line N"，二进制为 "offset N"
    masked: str

    def __str__(self) -> str:
        rel = os.path.relpath(self.path, ROOT)
        return f"  {rel}: {self.locator}  [{self.rule}]  {self.masked}"


def _mask(value: str) -> str:
    """掩码命中内容，只保留可辨识的前缀与长度。"""
    value = value.strip()
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:6]}***(len={len(value)})"


def _shannon(text: str) -> float:
    """计算字符串的香农熵，用于过滤通用赋值规则的误报。"""
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _is_placeholder(value: str) -> bool:
    """判断命中值是否为明显的占位符 / 示例值。"""
    low = value.lower()
    if any(h in low for h in _PLACEHOLDER_HINTS):
        return True
    # 单一字符重复（如 "aaaaaaaaaaaaaaaa"）
    stripped = low.strip("-_")
    return len(set(stripped)) <= 2


def _iter_files(roots: Sequence[str], skip_dirs: set[str]) -> Iterator[str]:
    """递归遍历待扫描文件。"""
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext in _SKIP_EXT:
                    continue
                yield os.path.join(dirpath, name)


def _scan_text(path: str, data: bytes, literals: Sequence[str]) -> list[Finding]:
    """按行扫描文本文件。"""
    out: list[Finding] = []
    text = data.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        # 行内抑制：测试夹具 / 文档示例可显式放行
        if any(mk in line for mk in _SUPPRESS_MARKERS):
            continue
        for name, rx, high in _TEXT_RULES:
            for m in rx.finditer(line):
                # 通用赋值规则取第 2 组作为真实值，其余取整体命中
                value = m.group(2) if (not high and m.lastindex and
                                       m.lastindex >= 2) else m.group(0)
                if _is_placeholder(value):
                    continue
                if not high and _shannon(value) < 3.0:
                    continue  # 熵太低，多半是普通字符串
                out.append(Finding(path, name, f"line {lineno}", _mask(value)))
        for lit in literals:
            if lit and lit in line:
                out.append(Finding(path, "known_literal",
                                   f"line {lineno}", _mask(lit)))
    return out


def _scan_binary(path: str, data: bytes, literals: Sequence[str]) -> list[Finding]:
    """按字节扫描二进制文件（只用高置信规则）。"""
    out: list[Finding] = []
    for name, rx, _ in _BIN_RULES:
        for m in rx.finditer(data):
            value = m.group(0).decode("utf-8", errors="replace")
            if _is_placeholder(value):
                continue
            out.append(Finding(path, name, f"offset {m.start()}", _mask(value)))
    for lit in literals:
        if not lit:
            continue
        idx = data.find(lit.encode())
        if idx >= 0:
            out.append(Finding(path, "known_literal",
                               f"offset {idx}", _mask(lit)))
    return out


def scan_paths(roots: Sequence[str], *, literals: Sequence[str] = (),
               binary_only: bool = False,
               skip_dirs: Iterable[str] | None = None) -> list[Finding]:
    """扫描给定路径，返回所有命中。

    Args:
        roots:       待扫描的文件或目录列表。
        literals:    已知的历史泄露密钥原文，用于精确追查。
        binary_only: 只扫描二进制类文件（用于验证打包产物）。
        skip_dirs:   额外跳过的目录名。

    Returns:
        Finding 列表；为空表示未发现问题。
    """
    skip = set(_DEFAULT_SKIP_DIRS)
    if skip_dirs:
        skip |= set(skip_dirs)

    findings: list[Finding] = []
    for path in _iter_files(roots, skip):
        ext = os.path.splitext(path)[1].lower()
        is_bin = ext in _BIN_EXT
        if binary_only and not is_bin:
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except (OSError, PermissionError):
            continue
        if is_bin or b"\x00" in data[:4096]:
            findings.extend(_scan_binary(path, data, literals))
        else:
            findings.extend(_scan_text(path, data, literals))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="扫描源码或打包产物中的硬编码密钥")
    ap.add_argument("paths", nargs="*", default=None,
                    help="待扫描路径，默认为项目根目录")
    ap.add_argument("--literal", action="append", default=[],
                    help="已知泄露密钥原文，可重复指定")
    ap.add_argument("--binary-only", action="store_true",
                    help="只扫描二进制文件（用于验证 dist/ 产物）")
    ap.add_argument("--skip", action="append", default=[],
                    help="额外跳过的目录名，可重复指定")
    args = ap.parse_args(argv)

    roots = args.paths or [ROOT]
    roots = [r if os.path.isabs(r) else os.path.join(ROOT, r) for r in roots]
    for r in roots:
        if not os.path.exists(r):
            print(f"[错误] 路径不存在：{r}", file=sys.stderr)
            return 2

    findings = scan_paths(roots, literals=args.literal,
                          binary_only=args.binary_only, skip_dirs=args.skip)

    scope = "二进制产物" if args.binary_only else "源码树"
    if not findings:
        print(f"[通过] {scope}扫描完成，未发现硬编码密钥。")
        return 0

    print(f"[阻断] {scope}中发现 {len(findings)} 处疑似密钥：\n",
          file=sys.stderr)
    for f in findings:
        print(str(f), file=sys.stderr)
    print("\n请改用环境变量或后端代理，不要把密钥写入源码或产物。",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
