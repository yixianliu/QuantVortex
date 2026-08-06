"""上游 AI 服务调用（唯一持有真实密钥的地方）。

两个不可妥协的约束：
    1. 密钥只出现在本模块构造的请求头里，绝不进入返回体、日志或异常；
    2. 上游返回的错误必须「消毒」后再给客户端 —— 上游有可能把请求头
       原样回显在错误信息里，直接透传就等于自己泄露密钥。

双密钥轮换：
    正常走 primary。当且仅当 primary 遭遇 401/403（鉴权失败）时，
    才用 secondary 重试一次。这样在轮换窗口内：
        * 新密钥已生效  → primary 成功，secondary 永不被使用；
        * 新密钥没配好  → 自动落到 secondary，业务不中断，
                          同时 keystate 会显示告警，提示你去修。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import requests

from .config import ServerConfig

# 上游返回体里可能出现的敏感字段，回传客户端前一律剔除
_STRIP_FIELDS = ("headers", "request", "authorization", "api_key", "key")


class UpstreamError(Exception):
    """上游调用失败（已消毒，可安全回传客户端）。"""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class _KeyStats:
    """单把密钥的使用统计（用于判断轮换是否可以收尾）。"""

    success: int = 0
    auth_fail: int = 0
    other_fail: int = 0
    last_success_ts: float = 0.0


@dataclass
class UpstreamClient:
    """上游 Chat Completions 客户端。"""

    cfg: ServerConfig
    _stats: dict[str, _KeyStats] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._stats = {"primary": _KeyStats(), "secondary": _KeyStats()}
        self._session = requests.Session()

    # ------------------------------------------------------------------
    def chat(self, system: str, user: str, *, model: str | None = None,
             max_tokens: int = 900, temperature: float = 0.3) -> dict[str, Any]:
        """调用上游模型，返回 {"content": str, "served_by": "primary|secondary"}。

        Raises:
            UpstreamError: 已消毒的失败信息。
        """
        use_model = model or self.cfg.upstream_model
        if self.cfg.allowed_models and use_model not in self.cfg.allowed_models:
            raise UpstreamError(f"不支持的模型：{use_model}", status_code=400)

        payload = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        attempts: list[tuple[str, str]] = [("primary", self.cfg.key_primary)]
        if self.cfg.key_secondary:
            attempts.append(("secondary", self.cfg.key_secondary))

        last_err: UpstreamError | None = None
        for label, key in attempts:
            try:
                content = self._request_once(key, payload)
            except _AuthRejected as exc:
                # 该密钥被上游拒绝：记账后尝试下一把
                self._bump(label, "auth_fail")
                last_err = UpstreamError(
                    "上游拒绝了服务端凭据，请检查密钥配置", status_code=502)
                continue
            except UpstreamError as exc:
                self._bump(label, "other_fail")
                last_err = exc
                break     # 非鉴权类错误换密钥也没用，直接结束
            else:
                self._bump(label, "success")
                return {"content": content, "served_by": label}

        raise last_err or UpstreamError("上游调用失败")

    # ------------------------------------------------------------------
    def _request_once(self, key: str, payload: dict) -> str:
        """单次请求。密钥只在这里出现，不外泄到任何返回值。"""
        url = self.cfg.upstream_base + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        try:
            resp = self._session.post(
                url, headers=headers, json=payload,
                timeout=self.cfg.upstream_timeout)
        except requests.Timeout:
            raise UpstreamError("上游响应超时", status_code=504)
        except requests.RequestException as exc:
            # 只带类型名，不带 exc 内容 —— 它可能包含完整 URL 与请求头
            raise UpstreamError(
                f"上游网络异常（{type(exc).__name__}）", status_code=502)

        if resp.status_code in (401, 403):
            raise _AuthRejected()
        if resp.status_code == 429:
            raise UpstreamError("上游限流，请稍后重试", status_code=429)
        if resp.status_code >= 400:
            raise UpstreamError(
                f"上游返回错误状态 {resp.status_code}",
                status_code=502 if resp.status_code >= 500 else 400)

        try:
            data = resp.json()
        except ValueError:
            raise UpstreamError("上游返回了非 JSON 内容", status_code=502)

        content = self._extract_content(data)
        if content is None:
            raise UpstreamError("上游返回结构异常，未取到回复内容",
                                status_code=502)
        return content

    @staticmethod
    def _extract_content(data: Any) -> str | None:
        """从上游响应中稳健地取出回复文本。"""
        try:
            choices = data.get("choices") or []
            if not choices:
                return None
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            return content if isinstance(content, str) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _bump(self, label: str, field_name: str) -> None:
        import time
        with self._lock:
            st = self._stats.setdefault(label, _KeyStats())
            setattr(st, field_name, getattr(st, field_name) + 1)
            if field_name == "success":
                st.last_success_ts = time.time()

    def key_state(self) -> dict:
        """密钥使用状态，用于判断轮换能否收尾。

        判定口径：
            secondary.success == 0 且 primary.success > 0
            → 说明流量已全部由新密钥承载，可以安全吊销旧密钥。
        """
        with self._lock:
            primary = self._stats["primary"]
            secondary = self._stats["secondary"]
            has_secondary = bool(self.cfg.key_secondary)
            safe_to_revoke_old = (
                has_secondary and secondary.success == 0 and primary.success > 0)
            return {
                "has_secondary_key": has_secondary,
                "primary": {
                    "success": primary.success,
                    "auth_fail": primary.auth_fail,
                    "other_fail": primary.other_fail,
                },
                "secondary": {
                    "success": secondary.success,
                    "auth_fail": secondary.auth_fail,
                    "other_fail": secondary.other_fail,
                },
                "safe_to_revoke_old_key": safe_to_revoke_old,
                "hint": (
                    "secondary 未承载任何成功请求，可去服务商后台吊销旧密钥"
                    if safe_to_revoke_old else
                    "旧密钥仍在兜底或主密钥尚无成功记录，暂不要吊销"
                    if has_secondary else
                    "当前只配置了单把密钥"),
            }


class _AuthRejected(Exception):
    """内部信号：上游拒绝了当前密钥（401/403）。"""
