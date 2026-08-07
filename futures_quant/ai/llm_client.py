"""Agnes AI 直接客户端（桌面端大模型出口）。

安全模型：
    本模块直接调用 Agnes AI API（https://api.agnes-ai.cn/v1/chat/completions），
    客户端仅持有用户填写的 API 密钥，密钥不持久化到磁盘。

双模式：
    - 调试模式（python main.py）：密钥可从 UI 或环境变量注入
    - 打包模式（FuturesQuant.exe）：密钥只能从环境变量 QV_AGNES_API_KEY 注入

降级策略：
    未配置密钥、网络不通、API 故障 —— 一律返回 None，
    由调用方回退到本地规则合成，保证功能永远可用。
"""
from __future__ import annotations

import os
import threading
from typing import Any

try:
    import requests
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAVE_REQUESTS = False

DEFAULT_BASE = "https://api.agnes-ai.cn/v1/chat/completions"

# 环境变量中的 API 密钥（与 config.py 保持同步）
_ENV_KEY = "QV_AGNES_API_KEY"


class AgnesLLMClient:
    """直接调用 Agnes AI API 的客户端（线程安全）。

    Args:
        api_key: API 密钥（不从磁盘持久化）
        timeout: 单次请求超时（秒）
    """

    def __init__(self, api_key: str | None = None,
                 timeout: int = 30) -> None:
        """初始化相关对象。
        
            参数:
                api_key: str | None
                timeout: int"""
        self.api_key = api_key
        self.base = DEFAULT_BASE
        self.timeout = timeout

    # ------------------------------------------------------------------
    def available(self) -> bool:
        """是否具备调用条件（配置了 API 密钥且 requests 可用）。"""
        return bool(self.api_key) and _HAVE_REQUESTS

    # ------------------------------------------------------------------
    def chat(self, system: str, user: str, *, model: str | None = None,
             max_tokens: int = 900, temperature: float = 0.3) -> str | None:
        """调用 Agnes AI API。

        Returns:
            模型回复文本；任何环节失败均返回 None（由调用方降级）。
        """
        if not self.available():
            return None

        payload: dict[str, Any] = {
            "model": model or "agnes-flash",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            resp = requests.post(
                self.base,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except Exception:
            return None

        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return None


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------
_client: AgnesLLMClient | None = None
_client_lock = threading.Lock()


def get_client() -> AgnesLLMClient:
    """获取全局客户端单例。"""
    global _client
    with _client_lock:
        if _client is None:
            _client = AgnesLLMClient()
        return _client


def reset_client() -> None:
    """重置单例（配置变更或测试时使用）。"""
    global _client
    with _client_lock:
        _client = None


def chat(system: str, user: str, **kwargs) -> str | None:
    """便捷函数：调用 Agnes AI，失败返回 None。"""
    return get_client().chat(system, user, **kwargs)


def api_status() -> dict[str, Any]:
    """API 可用性摘要（供设置页展示；不含密钥）。"""
    c = get_client()
    return {
        "configured": bool(c.api_key),
        "base": c.base,
        "requests_available": _HAVE_REQUESTS,
        "usable": c.available(),
    }


def reload_from_config(config) -> None:
    """从 ConfigManager 热加载 API 密钥配置（不重建单例，仅更新属性）。

    Args:
        config: ConfigManager 实例（或 None，退化为环境变量）
    """
    c = get_client()
    if config is not None:
        api_key = config.get("ai.api_key", "")
        timeout = config.get("ai.timeout", 30)
    else:
        # 优先从环境变量读取（双模式统一入口）
        api_key = os.environ.get(_ENV_KEY, "")
        timeout = 30
    c.api_key = api_key.strip() if api_key else None
    c.timeout = int(timeout) if timeout else 30


def enforce_security_mode(frozen: bool) -> None:
    """在启动时强制应用安全模式。

    Args:
        frozen: True 表示当前是打包模式，需清除持久化密钥
    """
    if not frozen:
        return

    # 清除已加载的单例，强制重新初始化
    reset_client()

    # 从环境变量注入密钥（如果有的话）
    env_key = os.environ.get(_ENV_KEY, "").strip()
    if env_key:
        client = get_client()
        client.api_key = env_key
        print(f"[安全] 打包模式：已从环境变量 QV_AGNES_API_KEY 注入密钥")
    else:
        print("[安全] 打包模式：未检测到 QV_AGNES_API_KEY，AI 功能将降级为本地规则合成")
