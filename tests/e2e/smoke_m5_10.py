# -*- coding: utf-8 -*-
"""M5-10 安全与合规冒烟测试（纯数据层，无头跑，不建 QApplication）。

覆盖：
- ① VERIFY_SSL env 开关（默认 True；VERIFY_SSL=0 → False + warning）
- ② QHRB_HOME https 化（http:// → https://）
- ③ SOURCES 配置表收敛（news_feed 各 fetch_xxx 的 URL 来自 source_config）
- ③ settings.json#news_sources 覆盖
- ③ env 覆盖（QV_NEWS_<NAME>_URL / _DISABLED）
- ③ source_enabled 启停
- ③ 全库 URL 硬编码 ≤2 处（配置表内）

运行：
    /d/anaconda3/python.exe tests/e2e/smoke_m5_10.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import json  # noqa: F401  (settings.json 加载场景的示例导入)
import re

from futures_quant.ai import source_config as sc
from futures_quant.ai import news_feed as nf
from futures_quant.data import http_client


def _load_fixture(name: str) -> str:
    p = os.path.join(ROOT, "tests", "fixtures", "news_html", name)
    with open(p, encoding="utf-8") as f:
        return f.read()


# ============================================================================
# ① VERIFY_SSL env 开关
# ============================================================================

def test_verify_ssl_default_true():
    """默认 SSL 校验开启（True）。"""
    os.environ.pop("VERIFY_SSL", None)
    http_client._verify_ssl._warned = None  # 重置 warning 缓存
    assert http_client._verify_ssl() is True, "VERIFY_SSL 默认应为 True"


def test_verify_ssl_env_disabled(monkeypatch, caplog):
    """VERIFY_SSL=0 → SSL 校验关闭，且 logger.warning 打一次。"""
    import logging
    caplog.set_level(logging.WARNING, "futures_quant.data.http_client")
    os.environ["VERIFY_SSL"] = "0"
    http_client._verify_ssl._warned = None  # 重置 warning 缓存
    try:
        result = http_client._verify_ssl()
        assert result is False, f"VERIFY_SSL=0 应返 False，实际 {result}"
    finally:
        os.environ.pop("VERIFY_SSL", None)
        http_client._verify_ssl._warned = None
    # 验证 warning 打出（含 [M5-10] 标识）
    assert any("M5-10" in getattr(r, "message", "") for r in caplog), \
        f"应记录 M5-10 warning，实际={[getattr(r, 'message', '') for r in caplog]}"


def test_verify_ssl_false_values(monkeypatch):
    """VERIFY_SSL 的 false 等价值（false/no/off）都触发禁用。"""
    for v in ("0", "false", "no", "off"):
        os.environ["VERIFY_SSL"] = v
        http_client._verify_ssl._warned = None
        assert http_client._verify_ssl() is False, f"VERIFY_SSL={v} 应返 False"
    os.environ.pop("VERIFY_SSL", None)
    http_client._verify_ssl._warned = None


def test_verify_ssl_true_values():
    """VERIFY_SSL 未设置或 =1 都为启用。"""
    for v in ("1", "true", "yes", "on"):
        os.environ["VERIFY_SSL"] = v
        http_client._verify_ssl._warned = None
        assert http_client._verify_ssl() is True, f"VERIFY_SSL={v} 应返 True"
    os.environ.pop("VERIFY_SSL", None)
    http_client._verify_ssl._warned = None


# ============================================================================
# ② QHRB_HOME https 化
# ============================================================================

def test_qhrb_https():
    """M5-10②：QHRB_HOME 已从 http:// 改为 https://。"""
    assert nf.QHRB_HOME.startswith("https://"), \
        f"QHRB_HOME 应 https，实际 {nf.QHRB_HOME}"
    spec = sc.get_source("qhrb")
    assert spec is not None and spec.url.startswith("https://"), \
        f"source_config.qhrb 应 https，实际 {spec.url if spec else None}"


# ============================================================================
# ③ SOURCES 配置表收敛
# ============================================================================

def test_source_config_all_news_sources_registered():
    """全部 13 个资讯源都在 SOURCES 表内注册。"""
    urls = sc.all_urls()
    expected = {"cls", "cls_detail", "eastmoney", "hexun", "ths", "cngold",
                "sina_roll", "wsj", "sina", "qhrb", "cs", "stcn", "ifeng",
                "zq86", "jin10"}
    missing = expected - set(urls.keys())
    assert not missing, f"缺失源注册：{missing}"


def test_source_config_news_feed_uses_config():
    """news_feed 各 HOME 常量来自 source_config（值一致）。"""
    pairs = [
        ("eastmoney", nf.EM_HOME),
        ("hexun", nf.HX_HOME),
        ("ths", nf.THS_HOME),
        ("cngold", nf.CNGOLD_FUTURES_HOME),
        ("sina_roll", nf.SINA_ROLL_HOME),
        ("wsj", nf.WSJ_FUTURES_HOME),
        ("sina", nf.SINA_HOME),
        ("qhrb", nf.QHRB_HOME),
        ("cs", nf.CS_HOME),
        ("stcn", nf.STCN_HOME),
        ("ifeng", nf.IFENG_HOME),
        ("zq86", nf.ZQ86_HOME),
        ("jin10", nf.JIN10_HOME),
    ]
    for name, actual in pairs:
        expected = sc.get_source_url(name)
        assert actual == expected, f"{name}: news_feed={actual} != config={expected}"


def test_source_config_template_detail_url():
    """CLS_DETAIL 是 {id} 模板，可格式化。"""
    spec = sc.get_source("cls_detail")
    assert spec.template is True
    assert spec.detail_url(id="12345") == "https://www.cls.cn/detail/12345"


def test_source_config_env_url_override(monkeypatch):
    """QV_NEWS_<NAME>_URL 可覆盖 URL。"""
    monkeypatch.setenv("QV_NEWS_EASTMONEY_URL", "https://my.custom.host/")
    sc.clear_settings_cache()
    try:
        url = sc.get_source_url("eastmoney")
        assert url == "https://my.custom.host/", f"env 覆盖失效：{url}"
    finally:
        os.environ.pop("QV_NEWS_EASTMONEY_URL", None)
        sc.clear_settings_cache()


def test_source_config_env_disabled(monkeypatch):
    """QV_NEWS_<NAME>_DISABLED=1 可禁用源。"""
    monkeypatch.setenv("QV_NEWS_EASTMONEY_DISABLED", "1")
    sc.clear_settings_cache()
    try:
        assert sc.source_enabled("eastmoney") is False, "env disabled 未生效"
    finally:
        os.environ.pop("QV_NEWS_EASTMONEY_DISABLED", None)
        sc.clear_settings_cache()


def test_source_config_settings_json_override():
    """settings.json#news_sources 可覆盖 URL/enabled（直接注入 _settings_cache 模拟）。"""
    # 写入临时 settings.json 内容（内存 dict 模拟读取结果）
    cfg = {
        "eastmoney": {"url": "https://override.example.com/", "enabled": False},
        "qhrb": {"url": "https://qhrb.override.com/"},
    }
    # 让 source_config 读取该 settings（模拟读取成功）
    sc._settings_cache = cfg
    try:
        url = sc.get_source_url("eastmoney")
        assert url == "https://override.example.com/", f"settings 覆盖失效：{url}"
        assert sc.source_enabled("eastmoney") is False, "settings enabled=False 未生效"

        url2 = sc.get_source_url("qhrb")
        assert url2 == "https://qhrb.override.com/", f"qhrb settings 覆盖失效：{url2}"
        # qhrb 未被 enabled=False 覆盖，仍启用
        assert sc.source_enabled("qhrb") is True
    finally:
        sc._settings_cache = None


def test_source_config_env_overrides_settings():
    """env 覆盖优先级 > settings.json（env 最后生效）。"""
    # settings 设 override 1
    sc._settings_cache = {"eastmoney": {"url": "https://settings.host/"}}
    os.environ["QV_NEWS_EASTMONEY_URL"] = "https://env.host/"
    try:
        url = sc.get_source_url("eastmoney")
        assert url == "https://env.host/", f"env 应优先于 settings，实际 {url}"
    finally:
        os.environ.pop("QV_NEWS_EASTMONEY_URL", None)
        sc._settings_cache = None


# ============================================================================
# ④ 全库 URL 硬编码审计
# ============================================================================

def test_no_hardcoded_news_urls_outside_config():
    """全库 URL 硬编码：除 source_config.py + settings.json 外 ≤0 处（news 相关）。

    AGNES API 与 SVG xmlns 属于不同领域（LLM 配置 / XML schema），不计入。
    """
    import os
    hard_urls = []
    url_pat = re.compile(r'["\']https?://[a-zA-Z0-9]')
    for root, dirs, files in os.walk("futures_quant"):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            with open(p, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    if not url_pat.search(line):
                        continue
                    stripped = line.lstrip()
                    if stripped.startswith("#") or stripped.startswith('"""'):
                        continue
                    # 白名单：source_config 本身、Referer header、LLM base、SVG xmlns
                    if "source_config.py" in p:
                        continue
                    if "Referer" in line or "agnes" in line or "xmlns" in line:
                        continue
                    hard_urls.append((p, i, line.rstrip()))

    assert not hard_urls, \
        f"news 源 URL 硬编码未收敛到 source_config.py：\n" + "\n".join(
            f"  {p}:{i}: {l[:100]}" for p, i, l in hard_urls)


# ============================================================================
# ⑤ 集成：13 源契约在 M5-10 改造后仍 ≥ 历史基线
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


def test_all_13_sources_still_work(monkeypatch):
    """M5-10 改造后 13 源契约无回归。"""
    from smoke_m5_09 import _FakeHttpClient  # 复用 M5-09 的 fake client
    monkeypatch.setattr(nf, "_get_http_client", lambda: _FakeHttpClient())
    for name, (fn_name, baseline) in CONTRACT_BASELINE.items():
        fn = getattr(nf, fn_name)
        items = fn(limit=10, enrich=False)
        assert len(items) >= baseline, \
            f"{name} 条数 {len(items)} < 基线 {baseline}（M5-10 引入回归）"


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
        def setenv(self, name, value):
            os.environ[name] = value

    class _Caplog(list):
        def set_level(self, level, logger=None):
            import logging
            target = logging.getLogger(logger) if logger else logging.getLogger()
            target.setLevel(level)
            handler = logging.Handler()
            handler.setLevel(level)
            handler.emit = lambda rec: self.append(rec)
            target.addHandler(handler)

    def _build_args(fn):
        import inspect
        import tempfile
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
            elif name == "tmp_path":
                args.append(tempfile.mkdtemp(prefix="smoke_m5_10_"))
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