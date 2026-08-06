"""本地开发启动脚本。

用法：
    # 先设置环境变量（PowerShell 示例）
    $env:QV_UPSTREAM_BASE = "https://apihub.agnes-ai.com/v1"
    $env:QV_UPSTREAM_KEY  = "<你的新上游密钥>"
    $env:QV_JWT_SECRET    = python -c "import secrets;print(secrets.token_urlsafe(48))"
    python -m server.run_dev

缺少配置时会打印清晰的缺失清单并退出，而不是带病启动。
"""
from __future__ import annotations

import os
import secrets
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from server.config import ConfigError, load_config  # noqa: E402


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print("[配置错误] 服务未启动：\n", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("\n可用下面这条命令生成一个 JWT 密钥：", file=sys.stderr)
        print('  python -c "import secrets;print(secrets.token_urlsafe(48))"',
              file=sys.stderr)
        print(f"\n示例值：{secrets.token_urlsafe(48)}", file=sys.stderr)
        return 2

    print("[配置就绪]", cfg.public_summary())
    import uvicorn
    host = os.environ.get("QV_HOST", "127.0.0.1")
    port = int(os.environ.get("QV_PORT", "8787"))
    print(f"[启动] http://{host}:{port}")
    uvicorn.run("server.app:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
