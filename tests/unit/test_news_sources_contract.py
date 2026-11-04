# -*- coding: utf-8 -*-
"""M5-08 资讯源契约测试（录制回放）。

13 源 × fixture → 断言「该源能解析出 ≥N 条且 title/url/ts 三字段齐全」。
注入方式：patch ``news_feed._get_http_client`` 返回 fake client（按 URL 路由 fixture），
全部离线，不触网。

变异守护：若某源解析正则被改坏 → 该源契约 Fail。

运行：
    /d/anaconda3/python.exe -m pytest tests/unit/test_news_sources_contract.py -v
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from futures_quant.ai import news_feed as nf

_FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "news_html")


def _load(name: str, binary: bool = False):
    p = os.path.join(_FIXTURES, name)
    mode = "rb" if binary else "r"
    kw = {} if binary else {"encoding": "utf-8"}
    with open(p, mode, **kw) as f:
        return f.read()


class _FakeResp:
    """模拟 requests.Response：content(bytes) / text(str) / json()。"""

    def __init__(self, content: bytes, text: str, status_code: int = 200):
        self.content = content
        self._text = text
        self.status_code = status_code

    @property
    def text(self) -> str:
        return self._text

    def json(self):
        return json.loads(self._text)

    @property
    def reason(self) -> str:
        return "OK"


class _FakeHttpClient:
    """按 URL 路由到对应 fixture 的 fake http_client。"""

    # URL 路由表：(url_substring, fixture_name, binary)
    # 注意：substring 必须同时覆盖「首页（如 futures.eastmoney.com）」
    # 与「文章 URL（如 finance.eastmoney.com/a/...html）」
    _ROUTES = [
        ("eastmoney.com", "eastmoney.html", False),
        ("futures.hexun.com", "hexun.html", True),
        ("10jqka.com.cn", "ths.html", False),
        ("futures.cngold.org", "cngold.html", False),
        ("finance.sina.com.cn", "sina.html", False),
        ("zq86.com", "zq86.html", False),
        ("wallstreetcn.com", "wsj.html", False),
        ("jin10.com", "jin10.html", False),
        ("qhrb.com.cn", "qhrb.html", True),
        ("cs.com.cn", "cs.html", False),
        ("stcn.com", "stcn.html", False),
        ("ifeng.com", "ifeng.html", False),
        ("cls.cn/api/cache", "cls_api.json", False),
    ]

    def get(self, url: str, **kwargs):
        for url_sub, fixture, binary in self._ROUTES:
            if url_sub in url:
                raw = _load(fixture, binary=binary)
                if binary:
                    content = raw if isinstance(raw, bytes) else raw.encode("gbk")
                    text = raw.decode("gbk", "ignore") if isinstance(raw, bytes) else raw
                else:
                    text = raw if isinstance(raw, str) else raw.decode("utf-8")
                    content = text.encode("utf-8")
                return _FakeResp(content=content, text=text)
        # 未匹配 → 模拟 404（上层降级返 []）
        return _FakeResp(content=b"", text="", status_code=404)


def _patch_client(monkeypatch):
    """将 nf._get_http_client 替换为返回 _FakeHttpClient。"""
    fake = _FakeHttpClient()
    monkeypatch.setattr(nf, "_get_http_client", lambda: fake)


# ============================================================================
# 各源契约（每源：≥N 条 + title/url/ts 三字段非空）
# ============================================================================

def test_eastmoney_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_eastmoney_news(limit=10, enrich=False)
    assert len(items) >= 3, f"eastmoney 解析 {len(items)} 条（应≥3）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it, f"字段缺失: {it}"


def test_hexun_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_hexun_news(limit=10, enrich=False)
    assert len(items) >= 2, f"hexun 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it


def test_ths_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_ths_news(limit=10, enrich=False)
    assert len(items) >= 2, f"ths 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and it.get("source") == "同花顺"


def test_cngold_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_cngold_news(limit=10, enrich=False)
    assert len(items) >= 2, f"cngold 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it and "ctime" in it


def test_sina_roll_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_sina_roll_news(limit=10, enrich=False)
    assert len(items) >= 2, f"sina_roll 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"]


def test_zq86_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_zq86_news(limit=10, enrich=False)
    assert len(items) >= 2, f"zq86 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it


def test_wsj_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_wsj_news(limit=10, enrich=False)
    assert len(items) >= 2, f"wsj 解析 {len(items)} 条（应≥2，关键词过滤后）"
    for it in items:
        assert it["title"] and it["url"]
        # M5-05：WSJ 无真实发布时间 → ctime=None
        assert it.get("ctime") is None, "WSJ ctime 应为 None（M5-05）"


def test_jin10_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_jin10_news(limit=10, enrich=False)
    assert len(items) >= 2, f"jin10 解析 {len(items)} 条（应≥2，关键词过滤后）"
    for it in items:
        assert it["title"] and it["url"]
        # M5-05：JIN10 无真实发布时间 → ctime=None
        assert it.get("ctime") is None, "JIN10 ctime 应为 None（M5-05）"


def test_sina_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_sina_news(limit=10, enrich=False)
    assert len(items) >= 2, f"sina 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it and "published_ts" in it


def test_qhrb_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_qhrb_news(limit=10, enrich=False)
    assert len(items) >= 2, f"qhrb 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it


def test_cs_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_cs_news(limit=10, enrich=False)
    assert len(items) >= 2, f"cs 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it


def test_stcn_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_stcn_news(limit=10, enrich=False)
    assert len(items) >= 2, f"stcn 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it


def test_ifeng_contract(monkeypatch):
    _patch_client(monkeypatch)
    items = nf.fetch_ifeng_news(limit=10, enrich=False)
    assert len(items) >= 2, f"ifeng 解析 {len(items)} 条（应≥2）"
    for it in items:
        assert it["title"] and it["url"] and "ts" in it


def test_cls_contract(monkeypatch):
    _patch_client(monkeypatch)
    res = nf.fetch_cls_news(limit=10, force=True)
    items = res.get("items", [])
    assert len(items) >= 3, f"cls 解析 {len(items)} 条（应≥3）"
    for it in items:
        assert it["title"] and it["url"] and "ctime" in it
        # CLS 有真实 ctime（API 返回）→ 非 None
        assert it["ctime"], "CLS ctime 应非空（API 返回真实时间）"


# ============================================================================
# 变异守护：故意改坏某源正则 → 契约 Fail
# ============================================================================

def test_mutation_guard_eastmoney(monkeypatch):
    """把 EM_ART_RE 改错（域名不匹配）→ eastmoney 解析 0 条。
    M5-09 注：BS4 兜底可能从 fixture 提 N 条，故同时屏蔽 BS4 隔离正则效应。
    """
    _patch_client(monkeypatch)
    import re
    orig = nf.EM_ART_RE
    monkeypatch.setattr(nf, "EM_ART_RE",
                        re.compile(r'href="(https://finance\.WRONG\.com/a/(\d+)\.html)"[^>]*>(.*?)</a>', re.S))
    monkeypatch.setattr(nf, "_extract_with_bs4", lambda *a, **k: [])
    items = nf.fetch_eastmoney_news(limit=10, enrich=False)
    assert len(items) == 0, f"变异守护：改坏正则+屏蔽 BS4 后应 0 条，实际 {len(items)}"


def test_mutation_guard_sina(monkeypatch):
    """把 _SINA_RE 改错（扩展名改 .shtml→.xxx）→ sina 解析 0 条。
    M5-09 注：BS4 兜底会从 fixture 提 3 条，故同时屏蔽 BS4，仅验证正则破坏的解析失败路径。
    """
    _patch_client(monkeypatch)
    import re
    monkeypatch.setattr(nf, "_SINA_RE",
                        re.compile(r'href="(https?://finance\.sina\.com\.cn/[^"]+\.xxx)"[^>]*>(.*?)</a>', re.S))
    # M5-09①：BS4 结构化兜底会让改坏正则不再"零条"，故隔离 BS4 再断言
    monkeypatch.setattr(nf, "_extract_with_bs4", lambda *a, **k: [])
    items = nf.fetch_sina_news(limit=10, enrich=False)
    assert len(items) == 0, f"变异守护：改坏正则+屏蔽 BS4 后应 0 条，实际 {len(items)}"
