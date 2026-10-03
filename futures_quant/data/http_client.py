"""统一 HTTP 采集客户端（M5-03 · 采集合规与限流）。

设计目标（对应 docs/UPGRADE_PLAN_V5.md §7.3 M5-03）：
    · **单一 Session**：全部资讯源经本模块发请求，删除分散的裸 ``session.get``，
      统一连接池 + 自动重试（``urllib3.Retry`` 吸收 429/5xx 瞬时限频）。
    · **UA 池轮换**：6 个桌面浏览器 User-Agent 轮转，降低被单 UA 拉黑概率。
    · **单域名令牌桶限流**：默认 1 req/s/域名（可经 ``FAST_MODE=1`` 放宽），
      同一域名高频抓取时串行等待，避免触发目标站反爬。
    · **robots.txt 缓存检查**：``RESPECT_ROBOTS=1`` 时对已知域名抓取一次
      robots.txt 并缓存；被禁止的路径直接跳过（返回 None，不计入成功）。

合规与边界：
    · 仅读取公开资讯，不绕登录墙、不注入凭据；
    · 任何单源失败均返回 None / 空，由上层优雅降级，绝不拖垮主流程；
    · 本模块无副作用：不写盘、不发无关请求，robots 检查仅在开启时触发一次/域。

环境变量：
    ``RESPECT_ROBOTS=1``   启用 robots 合规门（默认关闭，保持既有抓取行为）。
    ``FAST_MODE=1``        放宽限流（令牌桶 rate 提至 5 req/s），用于本地高并发测试。
    ``VERIFY_SSL=0``       禁用 SSL 校验（默认 True；仅调试时用，会打 WARNING）。
                          M5-10 提供此逃生开关，避免生产静默关闭校验。
"""
from __future__ import annotations

import logging
import os
import random
import threading
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    _HAVE_REQUESTS = False


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
#: 6 个桌面浏览器 UA 池（轮换使用，降低单 UA 被拉黑概率）
UA_POOL: tuple = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

#: 默认单域名限流（req/s）。``FAST_MODE=1`` 时提至 5。
_DEFAULT_RATE = 1.0
_FAST_RATE = 5.0
_ROBOTS_CACHE_TTL = 3600.0  # robots.txt 缓存 1h

# M5-10①：SSL 校验开关（VERIFY_SSL=0 → 禁用，仅调试逃生）
def _verify_ssl() -> bool:
    """SSL 校验开关：默认 True；VERIFY_SSL=0 → False（打一次 WARNING）。"""
    if _verify_ssl._warned is None:
        env = os.environ.get("VERIFY_SSL", "1").strip().lower()
        disabled = env in ("0", "false", "no", "off")
        if disabled:
            logger.warning(
                "[M5-10] VERIFY_SSL=0 SSL 校验已禁用（仅调试逃生），"
                "生产环境强烈建议保持默认 True")
        _verify_ssl._warned = disabled
    return not _verify_ssl._warned
_verify_ssl._warned = None  # 首次调用时读取 env 并打 warning


def _respect_robots() -> bool:
    """是否启用 robots 合规门（默认关闭）。"""
    return os.environ.get("RESPECT_ROBOTS", "0") in ("1", "true", "True", "yes")


def _bucket_rate() -> float:
    """当前限流速率（req/s/域名）。FAST_MODE 下放宽。"""
    fast = os.environ.get("FAST_MODE", "0") in ("1", "true", "True", "yes")
    return _FAST_RATE if fast else _DEFAULT_RATE


# ---------------------------------------------------------------------------
# 令牌桶（单域名限流）
# ---------------------------------------------------------------------------
class _TokenBucket:
    """极简线程安全令牌桶。

    容量 = rate（即最多缓冲 rate 个立即放行），以 rate/s 补充。
    同一域名的连续请求会被串行等待至 ``1/rate`` 间隔，从而实现单域名限流。
    """

    __slots__ = ("rate", "capacity", "tokens", "last", "_lock")

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = float(rate)
        self.capacity = float(capacity if capacity is not None else rate)
        self.tokens = self.capacity
        self.last = time.monotonic()
        self._lock = threading.Lock()

    # 单次 acquire 最长等待秒数（防御性上限）。
    # 原实现为无限 ``while True`` + 持锁 ``time.sleep``：一旦令牌耗尽或
    # 多线程串行排队，调用方（尤其主线程）会被无限期挂起 —— 主线程挂起会
    # 令 Qt 事件循环无法重绘窗口，表现为「启动后白屏」。加此上限后，
    # 超时即放行，限流语义保留但绝不死锁。
    _ACQUIRE_MAX_WAIT = 5.0

    def acquire(self, n: int = 1, timeout: float | None = None) -> float:
        """阻塞获取 n 个令牌，返回实际等待秒数（便于测试断言）。

        参数:
            n: 需要的令牌数。
            timeout: 最长等待秒数；None 时取 ``_ACQUIRE_MAX_WAIT``。
                超时后直接放行（返回已等待时长），绝不无限阻塞。

        返回:
            float: 实际等待秒数。
        """
        if timeout is None:
            timeout = self._ACQUIRE_MAX_WAIT
        wait_total = 0.0
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            # 仅在「计算/扣减令牌」时持锁；sleep 必须在锁外，
            # 否则持锁睡觉会让其他线程的 acquire 全部串行堵死。
            with self._lock:
                now = time.monotonic()
                # 按经过时间补充令牌
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= n:
                    self.tokens -= n
                    return wait_total
                # 需要等待的时间
                needed = (n - self.tokens) / self.rate
                self.tokens = 0.0
                self.last = now
            # 超时保护：剩余预算不足则直接放行
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return wait_total
                needed = min(needed, remaining)
            if needed <= 0:
                return wait_total
            time.sleep(needed)
            wait_total += needed


# ---------------------------------------------------------------------------
# robots.txt 极简解析（仅 User-agent / Disallow，无需第三方依赖）
# ---------------------------------------------------------------------------
def _fetch_robots(session: "requests.Session", domain: str,
                  timeout: float = 5.0) -> "tuple[list, float]":
    """抓取并解析某域名 robots.txt，返回 (disallow_paths, ts)。

    抓取失败 / 404 / 无 robots → 返回 ([""], ts)（空列表表示允许全部）。
    """
    robots_url = f"https://{domain}/robots.txt"
    disallows: list = []
    try:
        resp = session.get(robots_url, timeout=timeout,
                           headers={"User-Agent": UA_POOL[0]})
        if resp.status_code == 200:
            ua_block_active = False
            for line in resp.text.splitlines():
                s = line.split("#", 1)[0].strip()
                if not s or ":" not in s:
                    continue
                key, val = s.split(":", 1)
                key, val = key.strip().lower(), val.strip()
                if key == "user-agent":
                    ua_block_active = (val == "*" or val.lower() in
                                        (u.lower() for u in UA_POOL))
                elif key == "disallow" and ua_block_active:
                    if val:  # Disallow: 空 = 无限制
                        disallows.append(val)
        # 404/403/其他：无 robots → 允许全部
    except Exception as e:  # pragma: no cover
        logger.debug("robots fetch %s failed: %s", domain, e)
    return disallows, time.time()


def _path_disallowed(disallows: list, path: str) -> bool:
    """path 是否命中任一 Disallow 前缀。``*`` 通配做简化的前缀匹配。"""
    for d in disallows:
        # 处理末尾 ``*`` 通配：取 ``*`` 前部分做前缀匹配（保守：命中即禁）
        rule = d.split("*")[0]
        if rule and path.startswith(rule):
            return True
        if d and path == d:
            return True
    return False


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
class HttpClient:
    """统一 HTTP 采集客户端：连接池 + 自动重试 + UA 轮换 + 单域限流 + robots 门。"""

    def __init__(self, respect_robots: bool | None = None) -> None:
        self._session = self._build_session() if _HAVE_REQUESTS else None
        self._ua_idx = 0
        self._ua_lock = threading.Lock()
        self._buckets: dict = {}
        self._buckets_lock = threading.Lock()
        self._robots: dict = {}
        self._robots_lock = threading.Lock()
        self._respect_robots = (
            _respect_robots() if respect_robots is None else respect_robots
        )
        # 是否真的会发网络请求（无 requests 时全走降级）
        self.enabled = bool(self._session)

    @staticmethod
    def _build_session() -> "requests.Session":
        """构建带连接池 + 自动重试的会话。"""
        s = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
            respect_retry_after_header=False,
        )
        adapter = HTTPAdapter(max_retries=retry,
                              pool_connections=16, pool_maxsize=16)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

    # -- UA 轮换 -----------------------------------------------------------
    def next_ua(self) -> str:
        """轮转取下一个 UA（线程安全）。"""
        with self._ua_lock:
            ua = UA_POOL[self._ua_idx % len(UA_POOL)]
            self._ua_idx += 1
            return ua

    # -- 限流 -------------------------------------------------------------
    def _bucket_for(self, domain: str) -> _TokenBucket:
        with self._buckets_lock:
            b = self._buckets.get(domain)
            if b is None:
                b = _TokenBucket(_bucket_rate())
                self._buckets[domain] = b
            return b

    # -- robots 门 ---------------------------------------------------------
    def _robots_fetch(self, domain: str) -> "tuple[list, float]":
        """抓取并缓存某域名 robots（实例方法，便于测试打桩）。"""
        return _fetch_robots(self._session, domain)

    def robots_allowed(self, url: str) -> bool:
        """robots 是否允许抓取 url（未开启合规门时恒为 True）。"""
        if not self._respect_robots:
            return True
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return True
        domain = parsed.netloc
        with self._robots_lock:
            hit = self._robots.get(domain)
            if hit is None or (time.time() - hit[1]) > _ROBOTS_CACHE_TTL:
                disallows, ts = self._robots_fetch(domain)
                self._robots[domain] = (disallows, ts)
                hit = (disallows, ts)
            disallows = hit[0]
        return not _path_disallowed(disallows, parsed.path or "/")

    # -- 主入口 ------------------------------------------------------------
    def get(self, url: str, headers: dict | None = None,
            timeout: float = 10.0, params: dict | None = None,
            verify: bool | None = None):
        """统一 GET：robots 门 → 单域限流 → UA 轮换 → 发请求。

        返回 ``requests.Response``；无 requests / robots 禁止 / 网络异常
        时返回 ``None``（调用方据此优雅降级，绝不抛到主流程）。

        verify: M5-10 显式覆盖 SSL 校验；None 时走模块级 _verify_ssl()
                （默认 True，VERIFY_SSL=0 可全局禁用）。
        """
        if not self.enabled:
            return None
        # robots 合规门（仅开启时校验）
        if not self.robots_allowed(url):
            logger.debug("robots disallow, skip %s", url)
            return None
        domain = urlparse(url).netloc
        if domain:
            self._bucket_for(domain).acquire()
        hdrs = dict(headers or {})
        # 若调用方未显式指定 UA，则用轮换 UA（避免覆盖源特定的 UA 需求）
        hdrs.setdefault("User-Agent", self.next_ua())
        if verify is None:
            verify = _verify_ssl()
        try:
            return self._session.get(url, headers=hdrs,
                                     timeout=timeout, params=params,
                                     verify=verify)
        except Exception as e:  # 网络/超时：交由上层降级，不拖垮主流程
            logger.debug("http get %s failed: %s", url, e)
            return None


# 全局单例 + 便捷入口
_CLIENT: HttpClient | None = None
_CLIENT_LOCK = threading.Lock()


def get_client() -> HttpClient:
    """获取全局 HttpClient 单例（惰性创建，线程安全）。"""
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = HttpClient()
    return _CLIENT


def http_get(url: str, headers: dict | None = None, timeout: float = 10.0,
             params: dict | None = None, verify: bool | None = None):
    """模块级便捷 GET（走全局单例）。失败/被禁/无 requests 返回 None。"""
    return get_client().get(url, headers=headers, timeout=timeout,
                            params=params, verify=verify)
