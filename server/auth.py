"""客户端鉴权：设备注册 + 短期令牌。

诚实的安全边界说明（重要，不要误读）：
    面向公众发布的桌面程序**不存在真正的客户端身份认证**。任何随程序
    下发的凭据（包括下面的 release key）都可以被提取。本模块的目标不是
    「阻止提取」，而是把泄露的后果压到可承受、可恢复：

        * 泄露的是短期令牌（默认 1 小时），不是上游真实密钥；
        * 每台设备独立限流，刷不动你的额度；
        * 你可以按 device_id 封禁，也可以整体轮换 JWT 密钥令全部令牌失效；
        * 上游密钥全程留在服务器，永不进入客户端。

    对比「把上游密钥打进 exe」：那种方案一旦泄露，攻击者直接拿到你的
    计费账户，且你只能吊销密钥、让所有已发布客户端集体失效。
"""
from __future__ import annotations

import hmac
import threading
import time
import uuid
from typing import Any

import jwt  # PyJWT

from .config import ServerConfig

_ALGO = "HS256"


class AuthError(Exception):
    """鉴权失败。"""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# 设备封禁名单（内存版；生产可换 Redis / DB）
# ---------------------------------------------------------------------------
_banned: set[str] = set()
_ban_lock = threading.Lock()


def ban_device(device_id: str) -> None:
    with _ban_lock:
        _banned.add(device_id)


def unban_device(device_id: str) -> None:
    with _ban_lock:
        _banned.discard(device_id)


def is_banned(device_id: str) -> bool:
    with _ban_lock:
        return device_id in _banned


def banned_list() -> list[str]:
    with _ban_lock:
        return sorted(_banned)


# ---------------------------------------------------------------------------
# 令牌签发与校验
# ---------------------------------------------------------------------------
def check_release_key(provided: str | None, cfg: ServerConfig) -> None:
    """校验应用级 release key（可选的第一道门槛）。

    这把 key 会随客户端分发，因此**可被提取**，它的作用只是挡掉
    顺手的脚本滥用；真正的防线是限流 + 短期令牌 + 服务端持钥。
    用 hmac.compare_digest 做常数时间比较，避免计时侧信道。
    """
    if not cfg.app_release_key:
        return
    if not provided or not hmac.compare_digest(provided, cfg.app_release_key):
        raise AuthError("release key 无效", status_code=403)


def normalize_device_id(raw: str | None) -> str:
    """规整设备号：缺失或异常时生成一个新的，避免空串成为共用限流键。"""
    if not raw:
        return uuid.uuid4().hex
    raw = raw.strip()
    if not (8 <= len(raw) <= 128) or not raw.replace("-", "").isalnum():
        return uuid.uuid4().hex
    return raw


def issue_device_token(device_id: str, cfg: ServerConfig) -> dict[str, Any]:
    """为设备签发短期令牌。

    Returns:
        {"access_token", "token_type", "expires_in", "device_id"}
    """
    if is_banned(device_id):
        raise AuthError("该设备已被封禁", status_code=403)

    now = int(time.time())
    payload = {
        "sub": device_id,
        "iat": now,
        "exp": now + cfg.jwt_ttl_seconds,
        "scope": "ai.chat",
    }
    token = jwt.encode(payload, cfg.jwt_secret, algorithm=_ALGO)
    # PyJWT 2.x 返回 str；1.x 返回 bytes，做一次兼容
    if isinstance(token, bytes):  # pragma: no cover
        token = token.decode()
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": cfg.jwt_ttl_seconds,
        "device_id": device_id,
    }


def verify_bearer(authorization: str | None, cfg: ServerConfig) -> dict[str, Any]:
    """校验 Authorization 头中的 Bearer 令牌，返回 claims。

    Raises:
        AuthError: 缺失 / 格式错误 / 过期 / 签名不符 / 设备被封禁。
    """
    if not authorization:
        raise AuthError("缺少 Authorization 头")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Authorization 头格式应为 'Bearer <token>'")

    try:
        claims = jwt.decode(parts[1], cfg.jwt_secret, algorithms=[_ALGO])
    except jwt.ExpiredSignatureError:
        raise AuthError("令牌已过期，请重新获取")
    except jwt.InvalidTokenError:
        # 不回显具体原因，避免给攻击者提供调试信息
        raise AuthError("令牌无效")

    device_id = str(claims.get("sub", ""))
    if not device_id:
        raise AuthError("令牌缺少设备标识")
    if is_banned(device_id):
        raise AuthError("该设备已被封禁", status_code=403)
    if claims.get("scope") != "ai.chat":
        raise AuthError("令牌权限不足", status_code=403)
    return claims
