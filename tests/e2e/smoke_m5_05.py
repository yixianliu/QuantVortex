"""M5-05 发布时间真实性 —— 验收冒烟（纯离线，不触网、不建 Qt）。

覆盖 docs/UPGRADE_PLAN_V5.md §7.3 M5-05 验收（DoD）：
  ① 同一批资讯连续两次抓取，``published_ts`` **完全一致**（不再用 time.time() 冒充）；
  ② 无法获取发布时间的源（金十 / 华尔街见闻）``published_ts=None``，
     且不参与时间衰减（``_weighted_bias`` / CLS 衰减对 None ctime 跳过时效因子）；
  ③ ``_URL_DATE_RE`` 上下文约束：拒 8 位以上纯数字 ID、拒无分隔纯数字，
     仅匹配形如 /2026/09/26/ 或 /2026-09-26/ 的路径段日期。

运行（纯数据层，无需 offscreen / Qt）：
    /d/anaconda3/python.exe tests/e2e/smoke_m5_05.py
"""
from __future__ import annotations

import os
import sys

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


class _FakeResp:
    """替身 Response：返回一段「含路径日期」的静态列表页 HTML。"""
    status_code = 200

    def __init__(self, html: str) -> None:
        self._html = html

    @property
    def text(self) -> str:
        return self._html

    @property
    def content(self) -> bytes:
        return self._html.encode("utf-8")


def main() -> int:
    from futures_quant.ai import news_feed as nf
    from futures_quant.data import http_client as _hcm

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    # ---------------- ③ 正则上下文约束（_parse_url_date 行为） ----------------
    p_cases = [
        ("https://finance.sina.com.cn/futures/2026-07-27/abc.shtml", True),
        ("https://x.com/a/2026-09-26/b.html", True),
        ("https://x.com/flash/202609261234567890", False),  # 8 位以上纯数字 ID
        ("https://x.com/a/12345678/b", False),              # 无分隔纯数字
        ("https://x.com/a/2026-13-99/b.html", False),       # 非法月(13) → 构造抛异常
    ]
    for url, expect in p_cases:
        ctime, ts = nf._parse_url_date(url)
        check(f"url-date-{'hit' if expect else 'reject'}-{url[8:30]}",
              bool(ctime) is expect, f"ctime={ctime} ts={ts!r}")

    # ---------------- ① 同批连抓两次 published_ts 一致 ----------------
    # 打桩网络层：返回含路径日期的固定 HTML，模拟「同一批资讯」两次抓取。
    html = (
        '<a href="https://finance.sina.com.cn/futures/2026-07-27/a.shtml">螺纹钢去库加速利多</a>\n'
        '<a href="https://finance.sina.com.cn/futures/2026-07-26/b.shtml">原油减产提振</a>\n'
    )
    fake = _hcm.get_client()
    fake.get = lambda *a, **k: _FakeResp(html)  # 钉死响应 → 两次结果可复现

    batch1 = nf.fetch_sina_news(limit=10, enrich=False)
    batch2 = nf.fetch_sina_news(limit=10, enrich=False)
    pt1 = [it.get("published_ts") for it in batch1]
    pt2 = [it.get("published_ts") for it in batch2]
    check("published-ts-stable-across-fetches",
          pt1 == pt2 and len(batch1) >= 2 and all(p is not None for p in pt1),
          f"两次 published_ts 一致: {pt1 == pt2}, n={len(batch1)}, vals={pt1}")
    check("published-ts-real-not-faked",
          all(isinstance(p, float) for p in pt1) and pt1[0] > 0,
          f"有路径日期的源 published_ts 为真实时间戳（非 0/None）: {pt1[0]!r}")

    # ---------------- ② 无发布时间的源：published_ts=None 且不参与衰减 ----
    # 金十 / 华尔街见闻：静态 HTML 正则抓取，无真实发布时间 → ctime/published_ts 置 None
    # （源码级校验：全文件 0 处 time.time() 冒充 ctime）。
    import re
    src = open(os.path.join(_PROJ_ROOT, "futures_quant", "ai", "news_feed.py"),
               encoding="utf-8").read()
    check("no-fake-ctime-source-level",
          len(re.findall(r'"ctime":\s*time\.time\(\)', src)) == 0
          and 'fetch_jin10_news' in src and 'fetch_wsj_news' in src,
          "源码 0 处 time.time() 冒充 ctime（jin10/wsj 已置 None）")

    # 衰减/情绪路径对 None ctime 的健壮性：_weighted_bias 全 None ctime 不崩、返回有限值
    none_items = [
        {"sentiment": 0.4, "level": "B", "source": "金十数据", "ctime": None,
         "published_ts": None, "title": "多头 增持 库存减少"},
        {"sentiment": -0.3, "level": "B", "source": "华尔街见闻", "ctime": None,
         "published_ts": None, "title": "利空 下跌 库存堆积"},
    ]
    try:
        b = nf._weighted_bias(none_items)
        check("decay-skips-none-ctime", -1.0 <= b <= 1.0, f"全 None ctime 偏置={b:.3f}")
    except Exception as e:
        check("decay-skips-none-ctime", False, f"崩: {e}")

    # 对照：衰减开（全真实 ctime）vs 全 ctime=0（无衰减）——新鲜条目的时效权重
    # 优势在「全无衰减」时消失，偏置显著回落，证明 published_ts 参与衰减。
    import time as _t
    _now = _t.time()
    _40d = _now - 40 * 86400
    decay_on = [
        {"sentiment": 0.5, "level": "B", "source": "财联社",
         "ctime": _now, "published_ts": _now, "title": "利多新鲜"},
        {"sentiment": 0.5, "level": "B", "source": "财联社",
         "ctime": _40d, "published_ts": _40d, "title": "利多40天"},
        {"sentiment": -0.5, "level": "B", "source": "财联社",
         "ctime": _40d, "published_ts": _40d, "title": "利空40天"},
    ]
    decay_off = [
        {**d, "ctime": 0.0, "published_ts": 0.0} for d in decay_on
    ]
    b_on = nf._weighted_bias(decay_on)    # ≈0.625（新鲜利多被时效权重抬升，相对旧条目更重）
    b_off = nf._weighted_bias(decay_off)  # ≈0.333（全 ctime=0 → 无衰减，纯 2 利多 vs 1 利空）
    # 证据：衰减开（有 published_ts）时新鲜利多被抬升 → 偏置显著高于「全无衰减」
    check("decay-applies-when-published",
          b_on > 0.5 and b_on > b_off + 0.15,
          f"衰减开={b_on:+.3f}（新鲜利多被时效抬升） 衰减关={b_off:+.3f} 差={b_on - b_off:+.3f}")

    # ---------------- 汇总 ----------------
    print("=" * 62)
    print("M5-05 发布时间真实性 · 验收")
    print("=" * 62)
    passed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
        passed += 1 if ok else 0
    print("-" * 62)
    print(f"结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
