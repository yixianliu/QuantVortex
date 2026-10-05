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

import json
import logging
import os
import threading
import time
from typing import Any, Optional

try:
    import requests
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAVE_REQUESTS = False

try:  # 脱敏工具不可用时退化为「不记录响应体」，绝不裸写日志
    from ..utils.redact import redact as _redact
except Exception:  # pragma: no cover
    def _redact(value: Any) -> str:
        return "<脱敏模块不可用，内容已丢弃>"

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.agnes-ai.cn/v1/chat/completions"

# 环境变量中的 API 密钥（与 config.py 保持同步）
_ENV_KEY = "QV_AGNES_API_KEY"

# ---------------- M3-08：重试与熔断参数（集中于此，便于调参与测试） ----------------
# 【文档口径说明】M3-08 写的是「重试 3 次，0.5s→2s」，验收又写「mock 连续 3 次
# Timeout → 第 4 次成功」。二者只有在「首发 1 次 + 重试 3 次 = 共 4 次尝试」下
# 同时成立，故 MAX_ATTEMPTS=4；退避序列 0.5s → 1.0s → 2.0s（上限 2s）。
MAX_ATTEMPTS = 4          # 总尝试次数（首发 1 + 重试 3）
BACKOFF_BASE = 0.5        # 退避基数
BACKOFF_CAP = 2.0         # 单次退避上限
CB_FAIL_THRESHOLD = 5     # 连续失败多少次后打开熔断器
CB_COOLDOWN_SEC = 60.0    # 熔断后多久内直接快速失败


class CircuitBreaker:
    """极简熔断器：连续失败达阈值后，冷却期内直接快速失败（不再发请求）。

    仅保护**出口**：避免上游整体不可用时，UI 每次刷新都卡满 timeout。
    冷却期结束后进入半开（允许一次尝试），成功即清零计数。
    """

    def __init__(self, threshold: int = CB_FAIL_THRESHOLD,
                 cooldown: float = CB_COOLDOWN_SEC) -> None:
        self.threshold = int(threshold)
        self.cooldown = float(cooldown)
        self._fail_count = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """是否允许发起请求（熔断未打开或已过冷却期）。"""
        with self._lock:
            if self._opened_at and (time.monotonic() - self._opened_at) < self.cooldown:
                return False
            return True

    def record_success(self) -> None:
        """记录成功（清零连续失败并关闭熔断）。"""
        with self._lock:
            self._fail_count = 0
            self._opened_at = 0.0

    def record_failure(self) -> None:
        """记录失败（达阈值则打开熔断）。"""
        with self._lock:
            self._fail_count += 1
            if self._fail_count >= self.threshold and not self._opened_at:
                self._opened_at = time.monotonic()
                logger.warning("LLM 客户端熔断打开：连续失败 %d 次，%.0fs 内快速失败",
                               self._fail_count, self.cooldown)

    # ---- 观测/测试用 ----
    def snapshot(self) -> dict:
        """返回熔断状态快照。"""
        with self._lock:
            return {"fail_count": self._fail_count,
                    "open": bool(self._opened_at),
                    "opened_at": self._opened_at,
                    "threshold": self.threshold,
                    "cooldown": self.cooldown}

    def reset(self) -> None:
        """重置（测试用）。"""
        with self._lock:
            self._fail_count = 0
            self._opened_at = 0.0


class AgnesLLMClient:
    """直接调用 Agnes AI API 的客户端（线程安全）。

    Args:
        api_key: API 密钥（不从磁盘持久化）
        timeout: 单次请求超时（秒）
    """

    def __init__(self, api_key: str | None = None,
                 timeout: int = 30,
                 model: str = "agnes-3.0-flash",
                 max_tokens: int = 1024,
                 temperature: float = 0.3) -> None:
        """初始化相关对象。
        
            参数:
                api_key: str | None
                timeout: int
                model: str
                max_tokens: int
                temperature: float"""
        self.api_key = api_key
        self.base = DEFAULT_BASE
        self.timeout = timeout
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # M3-08 ③：熔断器（每实例独立，避免单例全局互相牵连）
        self.circuit = CircuitBreaker()
        # 便于测试注入：默认走 requests.post
        self._post = None

    # ------------------------------------------------------------------
    def available(self) -> bool:
        """是否具备调用条件（配置了 API 密钥且 requests 可用）。"""
        return bool(self.api_key) and _HAVE_REQUESTS

    # ------------------------------------------------------------------
    def chat(self, system: str, user: str, *, model: Optional[str] = None,
             max_tokens: Optional[int] = None,
             temperature: Optional[float] = None) -> str | None:
        """调用 Agnes AI API。

        M3-08 ①：`max_tokens` / `temperature` 的哨兵值（900 / 0.3）改为
        ``Optional[...] = None`` —— 旧实现靠「实参是否恰好等于哨兵值」判断是否
        回落到实例配置，于是**调用方真的想传 900 或 0.3 时反而拿不到自己要的值**。

        Returns:
            模型回复文本；任何环节失败均返回 None（由调用方降级）。
        """
        if not self.available():
            return None

        # M3-08 ③：熔断打开 → 快速失败，不再消耗 timeout
        if not self.circuit.allow():
            logger.warning("LLM 请求被熔断跳过（连续失败已达阈值）")
            return None

        actual_model = model if model is not None else (self.model or "agnes-3.0-flash")
        actual_max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        actual_temperature = (temperature if temperature is not None
                              else self.temperature)

        payload: dict[str, Any] = {
            "model": actual_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": actual_max_tokens,
            "temperature": actual_temperature,
        }

        post = self._post or requests.post
        last_reason = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            # ---- 单次尝试 ----
            try:
                resp = post(
                    self.base,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    timeout=self.timeout,
                )
            except Exception as e:  # noqa: BLE001
                # M3-08 ④：print → logging，异常信息经脱敏后再落日志
                last_reason = f"{type(e).__name__}: {_redact(e)}"
                retryable = isinstance(e, (TimeoutError, ConnectionError)) or \
                    type(e).__name__ in ("Timeout", "ConnectTimeout", "ReadTimeout",
                                         "ConnectionError", "SSLError")
                if not retryable or attempt >= MAX_ATTEMPTS:
                    logger.warning("LLM 请求异常（第 %d/%d 次）：%s",
                                   attempt, MAX_ATTEMPTS, last_reason)
                    self.circuit.record_failure()
                    return None
                self._sleep_backoff(attempt)
                continue

            status = int(getattr(resp, "status_code", 0) or 0)
            if status == 200:
                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                except Exception as e:  # noqa: BLE001
                    logger.warning("LLM 响应解析失败：%s", _redact(e))
                    self.circuit.record_failure()
                    return None
                self.circuit.record_success()
                return content

            # 关键：将 HTTP 503 model_not_found 视为可降级错误，
            # 而不是抛出异常，让调用方回退到本地规则合成
            if status == 503:
                try:
                    err_data = resp.json()
                    if err_data.get("error", {}).get("code") == "model_not_found":
                        logger.info("LLM 模型不可用（model_not_found），回退本地统计引擎")
                        self.circuit.record_failure()
                        return None
                except Exception:  # noqa: BLE001
                    pass  # 非 JSON 响应，按普通错误处理
            # M3-08 ②：5xx 才重试；4xx（密钥错/参数错）重试无意义
            last_reason = f"HTTP {status}"
            if status >= 500 and attempt < MAX_ATTEMPTS:
                logger.warning("LLM 服务端错误（第 %d/%d 次）：%s",
                               attempt, MAX_ATTEMPTS, last_reason)
                self._sleep_backoff(attempt)
                continue
            body = ""
            try:
                body = _redact(str(resp.text)[:200])      # M3-08 ④：响应体脱敏
            except Exception:  # noqa: BLE001
                body = "<响应体不可用>"
            logger.warning("LLM 请求失败：%s | %s", last_reason, body)
            self.circuit.record_failure()
            return None

        self.circuit.record_failure()
        logger.warning("LLM 请求在 %d 次尝试后仍未成功：%s", MAX_ATTEMPTS, last_reason)
        return None

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        """指数退避：0.5s → 1.0s → 2.0s（上限 BACKOFF_CAP）。"""
        delay = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** (attempt - 1)))
        time.sleep(delay)

    # ------------------------------------------------------------------
    def probe(self, should_abort=None) -> dict[str, Any]:
        """连通性探测（M7-04）：轻量请求返回结构化结果，复用重试与熔断。

        与 :meth:`chat` 的区别：不解析回复内容，而是返回状态码 / 耗时 /
        响应体（脱敏）等原始信息，供设置页结果卡展示；失败同样计入
        熔断器（record_failure），与真实调用共享熔断状态。

        参数:
            should_abort: 无参回调，返回 True 时在重试间隙中止（M7-04 ⑥）。

        Returns:
            dict: ok / status / elapsed_ms / model / time / reason / body /
            attempts / cancelled / breaker_open。
            reason 取值：``no_key`` / ``no_requests`` / ``circuit_open`` /
            异常类名（Timeout 等）/ ``HTTP <code>`` / ``""``（成功）。
        """
        result: dict[str, Any] = {
            "ok": False, "status": 0, "elapsed_ms": 0,
            "model": self.model or "agnes-3.0-flash",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": "", "body": "", "attempts": 0,
            "cancelled": False, "breaker_open": False,
        }
        if not self.api_key:
            result["reason"] = "no_key"
            return result
        if not _HAVE_REQUESTS:
            result["reason"] = "no_requests"
            return result
        if not self.circuit.allow():
            result["breaker_open"] = True
            result["reason"] = "circuit_open"
            return result

        payload: dict[str, Any] = {
            "model": result["model"],
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
            "temperature": self.temperature,
        }
        post = self._post or requests.post
        start = time.perf_counter()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if should_abort is not None and should_abort():
                result["cancelled"] = True
                result["attempts"] = attempt - 1
                return result
            result["attempts"] = attempt
            try:
                resp = post(
                    self.base,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    timeout=self.timeout,
                )
            except Exception as e:  # noqa: BLE001
                retryable = isinstance(e, (TimeoutError, ConnectionError)) or \
                    type(e).__name__ in ("Timeout", "ConnectTimeout",
                                         "ReadTimeout", "ConnectionError",
                                         "SSLError")
                result["reason"] = type(e).__name__
                if retryable and attempt < MAX_ATTEMPTS:
                    if should_abort is not None and should_abort():
                        result["cancelled"] = True
                        return result
                    self._sleep_backoff(attempt)
                    continue
                result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
                self.circuit.record_failure()
                return result

            status = int(getattr(resp, "status_code", 0) or 0)
            result["status"] = status
            try:
                result["body"] = _redact(str(resp.text)[:500])
            except Exception:  # noqa: BLE001
                result["body"] = "<响应体不可用>"
            if status == 200:
                result["ok"] = True
                result["reason"] = ""
                try:
                    result["model"] = resp.json().get("model") or result["model"]
                except Exception:  # noqa: BLE001
                    pass  # 响应非 JSON 时保留请求侧模型名
                result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
                self.circuit.record_success()
                return result
            result["reason"] = f"HTTP {status}"
            if status >= 500 and attempt < MAX_ATTEMPTS:
                if should_abort is not None and should_abort():
                    result["cancelled"] = True
                    return result
                self._sleep_backoff(attempt)
                continue
            result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
            self.circuit.record_failure()
            return result

        result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
        result["reason"] = result["reason"] or "exhausted"
        self.circuit.record_failure()
        return result


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
        # M3-08 ③：熔断状态外露，便于设置页解释「为什么 AI 一直没响应」
        "circuit": c.circuit.snapshot(),
    }


def reload_from_config(config) -> None:
    """从 ConfigManager 热加载非密钥配置（超时、模型名、max_tokens、temperature）。
    
    注意：API 密钥由 AIConfig.apply() 统一管理（优先级：环境变量 > 内存 > None），
    此处不再处理 api_key，避免重复设置与竞态。
    
    Args:
        config: ConfigManager 实例（或 None，使用默认值）
    """
    c = get_client()
    if config is not None:
        timeout = config.get("ai.timeout", 30)
        model = config.get("ai.model", "agnes-3.0-flash")
        max_tokens = config.get("ai.max_tokens", 1024)
        temperature = config.get("ai.temperature", 0.3)
    else:
        timeout = 30
        model = "agnes-3.0-flash"
        max_tokens = 1024
        temperature = 0.3
    # M3-08 ⑤：int() / float() 转换包 try —— 配置里若被写入非数字（UI 误填、
    # 旧版本残留），旧实现会让整个热加载抛异常，AI 功能静默失效。
    def _as_int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _as_float(v, default):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    c.timeout = _as_int(timeout, 30) or 30
    c.model = model or "agnes-3.0-flash"
    c.max_tokens = _as_int(max_tokens, 1024) or 1024
    c.temperature = _as_float(temperature, 0.3)
    if not (c.temperature == c.temperature):      # NaN 防御
        c.temperature = 0.3


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
        # M3-08 ④：只记录「已注入」这一事实，绝不打印密钥本体
        logger.info("[安全] 打包模式：已从环境变量 %s 注入密钥", _ENV_KEY)
    else:
        logger.info("[安全] 打包模式：未检测到 %s，AI 功能将降级为本地规则合成",
                    _ENV_KEY)
