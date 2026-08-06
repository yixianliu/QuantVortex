"""代理服务配置（全部来自环境变量，服务端专用）。

关键约束：
    上游真实密钥 **只存在于这个进程的内存里**，永不下发给桌面客户端，
    也永不写入任何返回体、日志或错误信息。

密钥轮换（双密钥设计）：
    QV_UPSTREAM_KEY      —— 主密钥，正常流量都走它
    QV_UPSTREAM_KEY_OLD  —— 备用密钥，仅在主密钥鉴权失败时兜底

    这组设计是为了「生产在用、不能停」的平滑轮换：
        1. 在服务商后台申请新密钥；
        2. 把新密钥填 QV_UPSTREAM_KEY，旧密钥填 QV_UPSTREAM_KEY_OLD，重启；
        3. 观察 /v1/admin/keystate，确认 primary 正常承载流量；
        4. 去服务商后台吊销旧密钥，清空 QV_UPSTREAM_KEY_OLD，再重启。
    全程业务无中断。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

# 复用桌面端的脱敏模块（纯标准库实现，可独立部署时一并拷贝）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from futures_quant.utils.redact import register_secret
except Exception:  # pragma: no cover - 独立部署且未拷贝时降级
    def register_secret(value):  # type: ignore
        return None


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip()
    return v or default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"环境变量 {name} 必须是整数，当前值非法")


@dataclass
class ServerConfig:
    """代理服务运行配置。"""

    upstream_base: str
    upstream_model: str
    key_primary: str
    key_secondary: str | None
    jwt_secret: str
    jwt_ttl_seconds: int
    app_release_key: str | None
    rate_per_minute: int
    rate_burst: int
    admin_token: str | None
    upstream_timeout: int
    max_prompt_chars: int
    allowed_models: tuple[str, ...] = field(default_factory=tuple)

    def public_summary(self) -> dict:
        """可安全对外暴露的配置摘要（绝不含密钥）。"""
        return {
            "upstream_base": self.upstream_base,
            "upstream_model": self.upstream_model,
            "has_secondary_key": bool(self.key_secondary),
            "jwt_ttl_seconds": self.jwt_ttl_seconds,
            "rate_per_minute": self.rate_per_minute,
            "rate_burst": self.rate_burst,
            "max_prompt_chars": self.max_prompt_chars,
            "release_key_required": bool(self.app_release_key),
        }


def load_config() -> ServerConfig:
    """从环境变量加载配置；缺少必填项时抛出 ConfigError 并列出全部缺失。"""
    missing: list[str] = []

    upstream_base = _env("QV_UPSTREAM_BASE")
    if not upstream_base:
        missing.append("QV_UPSTREAM_BASE（上游 chat/completions 的 base，"
                       "如 https://apihub.agnes-ai.com/v1）")

    key_primary = _env("QV_UPSTREAM_KEY")
    if not key_primary:
        missing.append("QV_UPSTREAM_KEY（上游真实密钥，仅服务端持有）")

    jwt_secret = _env("QV_JWT_SECRET")
    if not jwt_secret:
        missing.append("QV_JWT_SECRET（签发客户端令牌用的服务端密钥，"
                       "请用随机长字符串）")
    elif len(jwt_secret) < 16:
        raise ConfigError("QV_JWT_SECRET 过短，至少 16 字符。"
                          "可用 python -c \"import secrets;"
                          "print(secrets.token_urlsafe(48))\" 生成。")

    if missing:
        raise ConfigError(
            "缺少必要的环境变量：\n  - " + "\n  - ".join(missing))

    key_secondary = _env("QV_UPSTREAM_KEY_OLD")

    # 把两把上游密钥登记进脱敏器：即便某处代码不小心打印，也不会成文
    register_secret(key_primary)
    register_secret(key_secondary)

    models_raw = _env("QV_ALLOWED_MODELS", "") or ""
    allowed = tuple(m.strip() for m in models_raw.split(",") if m.strip())

    cfg = ServerConfig(
        upstream_base=upstream_base.rstrip("/"),      # type: ignore[union-attr]
        upstream_model=_env("QV_UPSTREAM_MODEL", "agnes-2.0-flash"),  # type: ignore[arg-type]
        key_primary=key_primary,                       # type: ignore[arg-type]
        key_secondary=key_secondary,
        jwt_secret=jwt_secret,                         # type: ignore[arg-type]
        jwt_ttl_seconds=_env_int("QV_JWT_TTL", 3600),
        app_release_key=_env("QV_APP_RELEASE_KEY"),
        rate_per_minute=_env_int("QV_RATE_PER_MIN", 20),
        rate_burst=_env_int("QV_RATE_BURST", 5),
        admin_token=_env("QV_ADMIN_TOKEN"),
        upstream_timeout=_env_int("QV_UPSTREAM_TIMEOUT", 30),
        max_prompt_chars=_env_int("QV_MAX_PROMPT_CHARS", 12000),
        allowed_models=allowed,
    )
    return cfg
