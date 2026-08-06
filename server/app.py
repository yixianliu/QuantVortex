"""QuantVortex AI 代理服务。

职责：桌面客户端与上游 AI 服务商之间的唯一通道。
    客户端  --(短期令牌)-->  本服务  --(真实密钥)-->  上游 AI

对外接口：
    GET  /healthz               健康检查（无需鉴权）
    POST /v1/auth/device        设备注册，换取短期令牌
    POST /v1/ai/chat            AI 对话（需 Bearer 令牌）
    GET  /v1/admin/keystate     密钥轮换状态（需管理员令牌）
    POST /v1/admin/ban          封禁设备（需管理员令牌）

启动：
    python -m server.run_dev            # 本地开发
    uvicorn server.app:app --port 8787  # 生产（配合进程管理器）
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from futures_quant.utils.logger import get_logger          # noqa: E402
from futures_quant.utils.redact import (                    # noqa: E402
    install_global_redaction, redact,
)

from .auth import (                                          # noqa: E402
    AuthError, ban_device, banned_list, check_release_key,
    issue_device_token, normalize_device_id, verify_bearer,
)
from .config import ConfigError, ServerConfig, load_config   # noqa: E402
from .ratelimit import TokenBucket                           # noqa: E402
from .upstream import UpstreamClient, UpstreamError          # noqa: E402

log = get_logger("qv_proxy", level=logging.INFO)
install_global_redaction()


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------
class DeviceRegisterIn(BaseModel):
    device_id: str | None = Field(
        default=None, description="客户端本地生成的设备标识；留空则由服务端分配")


class ChatIn(BaseModel):
    system: str = Field(default="You are a helpful assistant.", max_length=4000)
    user: str = Field(..., min_length=1)
    model: str | None = None
    max_tokens: int = Field(default=900, ge=1, le=8192)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class BanIn(BaseModel):
    device_id: str


# ---------------------------------------------------------------------------
# 应用状态
# ---------------------------------------------------------------------------
class _State:
    cfg: ServerConfig | None = None
    upstream: UpstreamClient | None = None
    limiter: TokenBucket | None = None


state = _State()


def _init_state(cfg: ServerConfig) -> None:
    state.cfg = cfg
    state.upstream = UpstreamClient(cfg=cfg)
    state.limiter = TokenBucket(cfg.rate_per_minute, cfg.rate_burst)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if state.cfg is None:
        try:
            _init_state(load_config())
        except ConfigError as exc:
            # 配置错误必须让服务起不来，而不是带病运行
            log.error("配置错误，服务无法启动：\n%s", exc)
            raise
    log.info("代理服务已启动，配置摘要：%s", state.cfg.public_summary())
    yield
    log.info("代理服务已停止")


app = FastAPI(title="QuantVortex AI Proxy", version="1.0.0",
              lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


# ---------------------------------------------------------------------------
# 统一错误处理：任何异常都必须消毒后再回传
# ---------------------------------------------------------------------------
@app.exception_handler(AuthError)
async def _on_auth_error(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.message})


@app.exception_handler(UpstreamError)
async def _on_upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
    log.warning("上游调用失败：%s", exc.message)
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.message})


@app.exception_handler(Exception)
async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # 绝不把原始异常回传客户端：它可能带着 URL、请求头甚至密钥
    log.error("未预期异常 %s：%s", type(exc).__name__, redact(str(exc)))
    return JSONResponse(status_code=500,
                        content={"error": "服务内部错误"})


# ---------------------------------------------------------------------------
# 依赖
# ---------------------------------------------------------------------------
def _require_cfg() -> ServerConfig:
    if state.cfg is None:
        raise UpstreamError("服务尚未完成初始化", status_code=503)
    return state.cfg


def _check_rate(device_id: str) -> None:
    assert state.limiter is not None
    ok, retry_after = state.limiter.allow(device_id)
    if not ok:
        raise AuthError(f"请求过于频繁，请 {retry_after} 秒后重试",
                        status_code=429)


def _require_admin(token: str | None, cfg: ServerConfig) -> None:
    import hmac
    if not cfg.admin_token:
        raise AuthError("未配置管理员令牌，管理接口不可用", status_code=404)
    if not token or not hmac.compare_digest(token, cfg.admin_token):
        raise AuthError("管理员令牌无效", status_code=403)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """健康检查：只暴露存活状态，不泄露任何配置细节。"""
    return {"status": "ok"}


@app.post("/v1/auth/device")
async def register_device(
    body: DeviceRegisterIn = Body(default=DeviceRegisterIn()),
    x_release_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """设备注册，换取短期令牌。"""
    cfg = _require_cfg()
    check_release_key(x_release_key, cfg)
    device_id = normalize_device_id(body.device_id)
    _check_rate(f"reg:{device_id}")
    result = issue_device_token(device_id, cfg)
    log.info("设备注册成功 device=%s", device_id)
    return result


@app.post("/v1/ai/chat")
async def ai_chat(
    body: ChatIn,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """AI 对话代理。真实密钥在服务端注入，客户端永远看不到。"""
    cfg = _require_cfg()
    claims = verify_bearer(authorization, cfg)
    device_id = str(claims["sub"])
    _check_rate(device_id)

    total = len(body.system) + len(body.user)
    if total > cfg.max_prompt_chars:
        raise AuthError(
            f"请求内容过长（{total} 字符，上限 {cfg.max_prompt_chars}）",
            status_code=413)

    assert state.upstream is not None
    result = state.upstream.chat(
        body.system, body.user, model=body.model,
        max_tokens=body.max_tokens, temperature=body.temperature)

    log.info("AI 调用成功 device=%s served_by=%s chars=%d",
             device_id, result["served_by"], total)
    # served_by 只回传给管理接口，普通客户端无需知晓服务端密钥拓扑
    return {"content": result["content"]}


@app.get("/v1/admin/keystate")
async def admin_keystate(
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """密钥轮换状态：判断旧密钥能否安全吊销。"""
    cfg = _require_cfg()
    _require_admin(x_admin_token, cfg)
    assert state.upstream is not None
    out = state.upstream.key_state()
    out["rate_limiter"] = state.limiter.stats() if state.limiter else {}
    out["banned_devices"] = banned_list()
    return out


@app.post("/v1/admin/ban")
async def admin_ban(
    body: BanIn,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """封禁设备：其已签发的令牌会在下次请求时被拒。"""
    cfg = _require_cfg()
    _require_admin(x_admin_token, cfg)
    ban_device(body.device_id)
    log.warning("已封禁设备 device=%s", body.device_id)
    return {"banned": body.device_id, "total_banned": len(banned_list())}
