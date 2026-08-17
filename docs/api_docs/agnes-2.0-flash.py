"""Agnes Chat Completions 最小调用示例。

安全声明：
    本脚本**不含任何密钥**。密钥一律从环境变量读取，缺失时直接退出。
    历史版本曾在此处硬编码 Bearer Token，该密钥已作废，禁止再以任何形式
    把密钥写回源码（构建流程有 build_tools/secret_scan.py 门禁拦截）。

用法：
    set AGNES_API_KEY=sk-xxxx          # Windows
    export AGNES_API_KEY=sk-xxxx       # Linux / macOS
    python api_docs/agnes-2.0-flash.py
"""
import json
import os
import sys

import requests

DEFAULT_URL = os.environ.get(
    "AGNES_API_URL", "https://apihub.agnes-ai.com/v1/chat/completions")
DEFAULT_MODEL = os.environ.get("AGNES_MODEL", "agnes-2.0-flash")


def main() -> int:
    api_key = os.environ.get("AGNES_API_KEY", "").strip()
    if not api_key:
        print("[错误] 未设置环境变量 AGNES_API_KEY，已终止。", file=sys.stderr)
        print("       本示例不内置任何密钥，请自行提供。", file=sys.stderr)
        return 2

    payload = json.dumps({
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "你好"},
        ],
    })
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        response = requests.post(DEFAULT_URL, headers=headers,
                                 data=payload, timeout=30)
    except Exception as exc:
        # 注意：不要把 headers 带进异常输出，否则密钥会进日志
        print(f"[错误] 请求失败：{type(exc).__name__}", file=sys.stderr)
        return 1

    if response.status_code != 200:
        print(f"[错误] HTTP {response.status_code}", file=sys.stderr)
        return 1
    print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
