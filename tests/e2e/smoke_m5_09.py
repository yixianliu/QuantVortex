# -*- coding: utf-8 -*-
"""M5-09 解析健壮性升级冒烟测试（纯数据层，无头跑，不建 QApplication）。

覆盖：
- ① 反爬多特征打分（CF markers / WAF / captcha / script-heavy）
- ② BS4 结构化解析兜底（regex 0 条时启用）
- ③ 编码探测（chardet / charset-normalizer / fallback）
- ④ _GENERIC_BODY_RE 不再贪婪匹配 div
- ⑤ 阈值可配（CHALLENGE_THRESHOLD env）
- ⑥ 集成：反爬 fixture → _fetch_list_source 返 [] 且不计入成功

DoD：喂入反爬挑战页 fixture → 正确识别且不计入成功；
     正常页 → 解析条数不下降。

运行：
    /d/anaconda3/python.exe tests/e2e/smoke_m5_09.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from futures_quant.ai import news_feed as nf

_FIXTURES = os.path.join(ROOT, "tests", "fixtures", "news_html")


def _load(name: str, binary: bool = False):
    p = os.path.join(_FIXTURES, name)
    mode = "rb" if binary else "r"
    kw = {} if binary else {"encoding": "utf-8"}
    with open(p, mode, **kw) as f:
        return f.read()


class _FakeResp:
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
    """按 URL 子串路由到 fixture（含挑战页 fixture）。"""

    _ROUTES = [
        ("challenge_cf", "challenge_cf.html", False),
        ("challenge_waf", "challenge_waf.html", False),
        ("normal_paras", "normal_with_paragraphs.html", False),
        # 既有源 fixture（回归用）
        ("eastmoney.com", "eastmoney.html", False),
        ("hexun.com", "hexun.html", True),
        ("10jqka.com.cn", "ths.html", False),
        ("cngold.org", "cngold.html", False),
        ("finance.sina.com.cn", "sina.html", False),
        ("zq86.com", "zq86.html", False),
        ("wallstreetcn.com", "wsj.html", False),
        ("jin10.com", "jin10.html", False),
        ("sina_roll", "sina_roll.html", False),
        ("qhrb.com.cn", "qhrb.html", True),
        ("cs.com.cn", "cs.html", False),
        ("stcn.com", "stcn.html", False),
        ("ifeng.com", "ifeng.html", False),
        ("cls.cn/api/cache", "cls_api.json", False),
    ]

    def get(self, url: str, **kwargs):
        for sub, fix, binary in self._ROUTES:
            if sub in url:
                raw = _load(fix, binary=binary)
                if binary:
                    content = raw if isinstance(raw, bytes) else raw.encode("gbk")
                    text = raw.decode("gbk", "ignore") if isinstance(raw, bytes) else raw
                else:
                    text = raw if isinstance(raw, str) else raw.decode("utf-8")
                    content = text.encode("utf-8")
                return _FakeResp(content=content, text=text)
        return _FakeResp(content=b"", text="", status_code=404)


def _patch_client(monkeypatch):
    fake = _FakeHttpClient()
    monkeypatch.setattr(nf, "_get_http_client", lambda: fake)


# ============================================================================
# ① 反爬多特征打分
# ============================================================================

def test_detect_challenge_cloudflare():
    """CF 挑战页（Just a moment / __cf_chl / cf-browser-verification）→ 识别。"""
    txt = _load("challenge_cf.html")
    is_chal, score, reasons = nf._detect_challenge(txt)
    assert is_chal, f"应识别为反爬，实际 score={score}, reasons={reasons}"
    assert score >= 2.0, f"score={score} 应 ≥2.0（CF markers 加分）"
    # 至少命中 cf-browser-verification / __cf_chl / Just a moment 之一
    assert any("cf" in r.lower() or "just a moment" in r.lower() for r in reasons), \
        f"应包含 CF 标记 reasons={reasons}"


def test_detect_challenge_waf_captcha():
    """国内 WAF/captcha 挑战页 → 识别（中文标记 + captcha）。"""
    txt = _load("challenge_waf.html")
    is_chal, score, reasons = nf._detect_challenge(txt)
    assert is_chal, f"应识别为反爬，实际 score={score}, reasons={reasons}"
    assert score >= 2.0


def test_detect_challenge_normal_page_passes():
    """正常页（东财/和讯等 fixture）→ 不误报。"""
    txt = _load("eastmoney.html")
    is_chal, score, _ = nf._detect_challenge(txt)
    assert not is_chal, f"正常东财页不应被识别为反爬，实际 score={score}"


def test_detect_challenge_threshold_configurable():
    """高阈值（>实际得分）→ 不再识别为反爬（验证阈值可配）。"""
    txt = _load("challenge_cf.html")
    is_chal_lo, _, _ = nf._detect_challenge(txt, threshold=1.0)
    is_chal_hi, _, _ = nf._detect_challenge(txt, threshold=10.0)
    assert is_chal_lo, "低阈值应识别"
    assert not is_chal_hi, f"极高阈值（10.0）应放行，但被判反爬"


# ============================================================================
# ② BS4 结构化解析兜底
# ============================================================================

def test_extract_with_bs4_normal_article():
    """含 <article> 容器 + <a> 的 BS4 友好页面 → 解析出条目。"""
    # 临时构造个 BS4 友好页面（用现有东财 fixture 验证）
    txt = _load("eastmoney.html")
    items = nf._extract_with_bs4(txt, "东方财富", limit=10)
    assert len(items) >= 1, f"BS4 应能从东财 fixture 提取条目，实际 {len(items)}"
    url, title = items[0]
    assert url.startswith("http"), f"URL 应为绝对路径: {url}"
    assert len(title) >= 4


# ============================================================================
# ③ 编码探测
# ============================================================================

def test_decode_content_gbk_via_hint():
    """GBK hint 正确解码。"""
    gbk_text = "螺纹钢期货主力合约突破4000关口".encode("gbk")
    text, enc = nf._decode_content(gbk_text, enc_hint="gbk")
    assert text == "螺纹钢期货主力合约突破4000关口", f"GBK 解码错: {text!r}"
    assert enc == "gbk"


def test_decode_content_fallback_utf8_warns(monkeypatch, caplog):
    """hint/探测全失败 → 强制 utf-8 ignore + logger.warning。"""
    import logging
    # 禁用 chardet/charset-normalizer，逼 _decode_content 走 fallback utf-8
    monkeypatch.setattr(nf, "_HAVE_CHARDET", False)
    monkeypatch.setattr(nf, "_HAVE_CHARSET_NORMALIZER", False)
    caplog.set_level(logging.WARNING, logger=nf.logger.name)
    # big5 编码的字节（hint=invalid-enc 必失败，探测又被禁用）
    bad = "期貨突破4000".encode("big5")
    text, enc = nf._decode_content(bad, enc_hint="invalid-enc")
    assert isinstance(text, str)
    assert enc == "utf-8", f"全失败应 fallback utf-8，实际 {enc}"
    # 至少有一条 M5-09 warning
    assert any("M5-09" in rec.message for rec in caplog), \
        f"应记录 M5-09 warning，实际 messages={[getattr(r, 'message', '') for r in caplog]}"


# ============================================================================
# ④ _GENERIC_BODY_RE 不再匹配 div
# ============================================================================

def test_generic_body_re_no_div_greedy():
    """M5-09④：_GENERIC_BODY_RE 只匹配 <p>/<article>，不再匹配 <div>。"""
    pat = nf._GENERIC_BODY_RE
    # 含 <div> 的 HTML 不应被 _GENERIC_BODY_RE 捕获
    html = '<div class="content">被 div 包裹的内容</div><p>段落一</p>'
    matches = pat.findall(html)
    assert len(matches) == 1, f"<div> 不应被匹配，实际匹配 {len(matches)} 段"
    assert "段落一" in matches[0]


# ============================================================================
# ⑤ 集成：反爬 fixture 经 _fetch_list_source → 返 [] 不计入成功
# ============================================================================

def test_fetch_list_source_challenge_blocked(monkeypatch):
    """挑战页 fixture → _fetch_list_source 返 []（不计成功）。"""
    _patch_client(monkeypatch)
    # URL 子串含 "challenge_cf"，路由命中 CF challenge fixture
    art_re = re.compile(r'href="(https?://[^"]+\.html)"[^>]*>(.*?)</a>', re.S)
    items = nf._fetch_list_source(
        home="https://example.com/challenge_cf.html",
        art_re=art_re, source="cf_test", limit=10, enrich=False,
    )
    assert items == [], f"挑战页应返空，实际 {len(items)} 条: {items[:2]}"


def test_fetch_list_source_normal_no_regression(monkeypatch):
    """正常页（东财 fixture）经 M5-09 改造后条数不下降。"""
    _patch_client(monkeypatch)
    items = nf.fetch_eastmoney_news(limit=10, enrich=False)
    assert len(items) >= 3, f"东财正常页条数下降，实际 {len(items)}（M5-08 基线 ≥3）"


# ============================================================================
# ⑥ 全部 13 源契约在 M5-09 改造后仍 ≥ 历史基线
# ============================================================================

CONTRACT_BASELINE = {
    "eastmoney": ("fetch_eastmoney_news", 3),
    "hexun": ("fetch_hexun_news", 2),
    "ths": ("fetch_ths_news", 2),
    "cngold": ("fetch_cngold_news", 2),
    "sina_roll": ("fetch_sina_roll_news", 2),
    "zq86": ("fetch_zq86_news", 2),
    "wsj": ("fetch_wsj_news", 2),
    "jin10": ("fetch_jin10_news", 2),
    "sina": ("fetch_sina_news", 2),
    "qhrb": ("fetch_qhrb_news", 2),
    "cs": ("fetch_cs_news", 2),
    "stcn": ("fetch_stcn_news", 2),
    "ifeng": ("fetch_ifeng_news", 2),
}


def test_all_13_sources_no_regression(monkeypatch):
    """M5-09 改造后 13 源条数 ≥ 历史基线。"""
    _patch_client(monkeypatch)
    for name, (fn_name, baseline) in CONTRACT_BASELINE.items():
        fn = getattr(nf, fn_name)
        items = fn(limit=10, enrich=False)
        assert len(items) >= baseline, \
            f"{name} 条数 {len(items)} < 基线 {baseline}（M5-09 引入回归）"


# ============================================================================
# main
# ============================================================================

def _run():
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    passed = failed = 0
    fns = [v for k, v in globals().items() if k.startswith("test_")]

    class _Monkey:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

        def set_level(self, level, logger=None):
            import logging
            if logger is not None:
                logging.getLogger(logger).setLevel(level)

    class _Caplog(list):
        """极简 caplog 替代：作为 list 容器收集 logging.LogRecord。"""
        def set_level(self, level, logger=None):
            import logging
            target = logging.getLogger(logger) if logger else logging.getLogger()
            target.setLevel(level)
            # 挂 handler 把后续 record 加进 self
            handler = logging.Handler()
            handler.setLevel(level)
            handler.emit = lambda rec: self.append(rec)
            target.addHandler(handler)
            self._handler = handler
            self._logger = target

    def _build_args(fn):
        import inspect
        try:
            sig = inspect.signature(fn)
        except Exception:
            return ()
        args = []
        for name in sig.parameters:
            if name == "monkeypatch":
                args.append(_Monkey())
            elif name == "caplog":
                args.append(_Caplog())
        return tuple(args)

    for fn in fns:
        name = fn.__name__
        try:
            fn(*_build_args(fn))
            print(f"[PASS] {name}")
            passed += 1
        except Exception as exc:
            print(f"[FAIL] {name}  ({type(exc).__name__}: {exc})")
            failed += 1
    print("-" * 60)
    print(f"结果：{passed}/{passed + failed} 通过，{failed}/{passed + failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run())