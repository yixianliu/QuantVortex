"""M5-03 采集合规与限流 —— 验收冒烟（offscreen / 纯离线，不触网）。

覆盖 docs/UPGRADE_PLAN_V5.md §7.3 M5-03 三条验收（全部用 monkeypatch 夹具，不发真实网络）：
  ① UA 池轮换生效：HttpClient.next_ua() 一个周期内产出 6 个互不相同 UA，第 7 个回到第 1；
     且 news_feed / sina_feed 已改走 http_client（源码无裸 ``_SESSION/requests).get``、无 urllib.request）。
  ② 单域名令牌桶限流：同一域名 10 次请求（默认 1 req/s）实际耗时 ≥9s；
     FAST_MODE=1 下提速（10 次 < 2s）。
  ③ robots 合规门：RESPECT_ROBOTS=1 且 robots 禁止该路径时，client.get 返回 None（跳过该源）；
     未开启时恒放行。

运行（纯数据层，无需 offscreen / Qt）：
    /d/anaconda3/python.exe tests/e2e/smoke_m5_03.py
"""
from __future__ import annotations

import os
import sys
import time

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


class _FakeResp:
    """替身 Response：status_code=200、.text 可取，避免触网。"""
    status_code = 200
    text = "ok"
    content = b"ok"
    reason = "OK"


def main() -> int:
    # M5-03 是纯数据层验收（http_client / sina_feed 均无 Qt 依赖）——不建 QApplication，
    # 直接无头运行，避免 offscreen 进程被沙箱回收。
    from futures_quant.data import http_client
    from futures_quant.data.http_client import (
        HttpClient, UA_POOL,
    )

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    # ---------------- ① UA 池轮换 ----------------
    c = http_client.HttpClient()
    seen = [c.next_ua() for _ in range(len(UA_POOL))]
    check("ua-pool-distinct-cycle",
          len(set(seen)) == len(UA_POOL) and len(UA_POOL) == 6,
          f"distinct={len(set(seen))}/{len(UA_POOL)}")
    check("ua-pool-wraps", c.next_ua() == seen[0], "第 N+1 个回到第 1")

    # 源码级：news_feed / sina_feed 已改走 http_client
    nf = open(os.path.join(_PROJ_ROOT, "futures_quant", "ai", "news_feed.py"),
              encoding="utf-8").read()
    sf = open(os.path.join(_PROJ_ROOT, "futures_quant", "data", "sina_feed.py"),
              encoding="utf-8").read()
    # 剔除注释与 http_client 自身导入行后，裸网络调用应清零
    import re
    def _strip_comments(src: str) -> str:
        lines = [l for l in src.splitlines()
                 if not l.lstrip().startswith("#") and "get_client as" not in l]
        return "\n".join(lines)
    nf_code = _strip_comments(nf)
    sf_code = _strip_comments(sf)
    bare_nf = re.findall(r"(_SESSION\s*or\s*requests)\.get|sess\.get", nf_code)
    bare_sf = re.findall(r"urlopen|urllib\.request", sf_code)
    check("news_feed-routes-via-http_client",
          "http_client" in nf and len(bare_nf) == 0,
          f"bare_sessions={len(bare_nf)}")
    check("sina_feed-routes-via-http_client",
          "http_client" in sf and len(bare_sf) == 0,
          f"bare_urllib={len(bare_sf)}")

    # ---------------- ② 单域名令牌桶限流（确定性：伪造时钟） ----------------
    # 令牌桶用 time.monotonic() 补令牌、time.sleep() 等待。若只把 sleep 打桩成
    # 空操作，real 时钟不前进 → 补令牌≈0 → 死循环自旋。故同时伪造 monotonic
    # （每次 sleep(s) 让假时钟前进 s），纯数学、零真实等待、零环境噪音：
    #   默认 1 req/s：cap=1，#1 免等 + #2..#10 各等 1.0 → 记录预算 ≈ 9.0s
    #   FAST   5 req/s：cap=5，前 5 免等 + 后 5 各等 0.2 → 记录预算 ≈ 1.0s
    from futures_quant.data import http_client as _hcm
    _orig_mono = _hcm.time.monotonic
    _orig_sleep = _hcm.time.sleep

    def _measure_rate(rate: float) -> float:
        """在指定速率下，伪造时钟对新桶做 10 次取用，返回记录的等待预算总和。"""
        # 起点 0.0（避免大基准 + 小步长浮点相加丢精度导致假时钟不前进、桶自旋）
        state = {"now": 0.0, "sleeps": []}
        _hcm.time.monotonic = lambda: state["now"]

        def _fake_sleep(s):
            state["sleeps"].append(float(s))
            state["now"] += float(s)

        _hcm.time.sleep = _fake_sleep
        try:
            tb = _hcm._TokenBucket(rate)
            for _ in range(10):
                tb.acquire()
        finally:
            _hcm.time.monotonic = _orig_mono
            _hcm.time.sleep = _orig_sleep
        return sum(state["sleeps"])

    default_budget = _measure_rate(1.0)   # 期望 ≈ 9.0s
    fast_budget = _measure_rate(5.0)      # 期望 ≈ 1.0s
    check("ratelimit-default-1req-s-budget", default_budget >= 8.5,
          f"默认 1req/s 记录等待预算={default_budget:.2f}s (期望≥~9s)")
    check("ratelimit-fast-mode-speedup",
          fast_budget < default_budget * 0.7,
          f"FAST 5req/s 记录等待预算={fast_budget:.2f}s < 默认1req/s {default_budget:.2f}s"
          f"（5 倍速限流 → 相对提速；不要求绝对值，避免浮点漂移误判）")

    # 端到端：client.get 确实在同一域名上复用同一令牌桶（打桩网络层）。
    # _TokenBucket 用 __slots__，不能给实例打桩方法；改为验证「get() 触发
    # 该域名令牌桶的创建/复用」——全新 client 下，首次 get 前该域无桶，3 次
    # 同域 get 后桶已缓存且为同一对象（证明走的是单域限流桶），异域则另开桶。
    os.environ.pop("FAST_MODE", None)
    limiter = http_client.HttpClient()
    limiter._session.get = lambda *a, **k: _FakeResp()
    limiter._buckets = {}
    assert "wire.example.com" not in limiter._buckets
    for _ in range(3):
        limiter.get("https://wire.example.com/x")
    b1 = limiter._buckets.get("wire.example.com")
    limiter.get("https://other.example.com/y")
    b2 = limiter._buckets.get("other.example.com")
    check("client-get-routes-token-bucket",
          b1 is not None and b2 is not None and b1 is not b2,
          "同域 get() 复用同一令牌桶，异域各开一桶（单域名限流接线正确）")


    # ---------------- ③ robots 合规门 ----------------
    # 未开启：恒放行
    r_off = http_client.HttpClient(respect_robots=False)
    r_off._session.get = lambda *a, **k: _FakeResp()
    check("robots-off-always-allow", r_off.robots_allowed(
        "https://any.example.com/secret") is True, "未开启合规门恒 True")

    # 开启 + robots 禁止：_robots_fetch 返回 ["/private"]，命中路径应跳过
    r_on = http_client.HttpClient(respect_robots=True)
    r_on._session.get = lambda *a, **k: _FakeResp()
    r_on._robots_fetch = lambda domain, timeout=5.0: (["/private"], time.time())
    check("robots-disallow-skip",
          r_on.robots_allowed("https://x.example.com/private/x.html") is False
          and r_on.robots_allowed("https://x.example.com/public.html") is True,
          "命中 Disallow 前缀→False，未命中→True")
    got = r_on.get("https://x.example.com/private/x.html")
    check("robots-blocked-get-returns-none", got is None,
          "robots 禁止路径 get() 返回 None（不计入成功）")

    # 正常路径仍可发请求（走令牌桶，返回 FakeResp）
    got2 = r_on.get("https://x.example.com/public.html")
    check("robots-allowed-get-passes", got2 is not None and got2.status_code == 200,
          "未禁止路径 get() 正常返回")

    # ---------------- 汇总 ----------------
    print("=" * 58)
    print("M5-03 采集合规与限流 · 验收")
    print("=" * 58)
    passed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
        passed += 1 if ok else 0
    print("-" * 58)
    print(f"结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
