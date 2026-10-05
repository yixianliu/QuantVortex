# -*- coding: utf-8 -*-
"""M5-10③ 资讯源 URL 集中配置表。

所有资讯源 URL 硬编码收敛到本模块 ``SOURCES`` 字典，避免散落在
``news_feed.py`` 各 fetch_xxx 里难以审计/替换。

结构：
    SOURCES: Dict[str, SourceSpec]
    - name: str         唯一源标识（与 news_feed.fetch_xxx 命名一致）
    - url: str          首页/API URL
    - enabled: bool     默认启用；False 时 fetch_xxx 直接返 []
    - desc: str         中文描述（供 UI/日志展示）
    - template: bool    URL 是否含 {id} 模板占位（如 CLS_DETAIL）
    - extra: dict       附加元数据（例如 keywords、charset、detail_re 等）

覆盖：
    1) settings.json#news_sources 覆盖 URL/enabled
    2) 环境变量 ``QV_NEWS_<NAME>_URL`` / ``QV_NEWS_<NAME>_DISABLED=1``
       （<NAME> 大写）
    3) 兜底：SOURCES 字典中的默认值

DoD（M5-10）：全库 URL 硬编码收敛到「本模块 + settings.json」两处。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceSpec:
    """单个资讯源的元数据与配置。"""
    name: str
    url: str
    desc: str = ""
    enabled: bool = True
    template: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def detail_url(self, **kwargs: Any) -> str:
        """若本 spec 的 url 含 {id} 模板，用 kwargs 格式化。"""
        try:
            return self.url.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return self.url


# ---------------------------------------------------------------------------
# 默认 SOURCES 表（全部资讯源；URL 集中管理）
# ---------------------------------------------------------------------------

SOURCES: Dict[str, SourceSpec] = {
    "cls": SourceSpec(
        name="cls",
        url="https://www.cls.cn/api/cache",
        desc="财联社 7x24 快讯 API",
        template=False,
    ),
    "cls_detail": SourceSpec(
        name="cls_detail",
        url="https://www.cls.cn/detail/{id}",
        desc="财联社文章详情",
        template=True,
    ),
    "eastmoney": SourceSpec(
        name="eastmoney",
        url="https://futures.eastmoney.com/",
        desc="东方财富期货首页",
    ),
    "hexun": SourceSpec(
        name="hexun",
        url="https://futures.hexun.com/",
        desc="和讯期货首页",
        extra={"encoding": "gbk"},
    ),
    "ths": SourceSpec(
        name="ths",
        url="https://www.10jqka.com.cn/futures/",
        desc="同花顺期货首页",
    ),
    "cngold": SourceSpec(
        name="cngold",
        url="https://futures.cngold.org/",
        desc="金投网期货首页",
    ),
    "sina_roll": SourceSpec(
        name="sina_roll",
        url="https://finance.sina.com.cn/",
        desc="新浪财经滚动新闻",
    ),
    "wsj": SourceSpec(
        name="wsj",
        url="https://wallstreetcn.com/live/global",
        desc="华尔街见闻全球实时",
    ),
    "sina": SourceSpec(
        name="sina",
        url="https://finance.sina.com.cn/futures/",
        desc="新浪财经期货频道",
    ),
    # M5-10②：qhrb http:// → https://（若 https 抓不到自动下线）
    "qhrb": SourceSpec(
        name="qhrb",
        url="https://www.qhrb.com.cn/",
        desc="期货日报首页（M5-10 https 化）",
        extra={"encoding": "gbk"},
    ),
    "cs": SourceSpec(
        name="cs",
        url="https://www.cs.com.cn/",
        desc="中证网首页",
    ),
    "stcn": SourceSpec(
        name="stcn",
        url="https://www.stcn.com/",
        desc="证券时报网首页",
    ),
    "ifeng": SourceSpec(
        name="ifeng",
        url="https://finance.ifeng.com/futures/",
        desc="凤凰财经期货频道",
    ),
    "zq86": SourceSpec(
        name="zq86",
        url="https://www.zq86.com/",
        desc="中国期货网首页",
    ),
    "jin10": SourceSpec(
        name="jin10",
        url="https://www.jin10.com/",
        desc="金十数据首页",
    ),
}

# 行情源（非资讯，仅 URL 集中管理）
SINA_KLINE_URL = "https://stock2.finance.sina.com.cn/futures/api/json.php/" \
                 "InnerFuturesNewService.getDailyKLine"


# ---------------------------------------------------------------------------
# settings.json#news_sources 覆盖加载
# ---------------------------------------------------------------------------

_settings_cache: Optional[Dict[str, Any]] = None


def _load_settings_sources() -> Dict[str, Any]:
    """读取 settings.json#news_sources；不存在/解析失败返空 dict。"""
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache
    # 项目根 config/settings.json
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    p = os.path.join(root, "config", "settings.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    raw = cfg.get("news_sources") or {}
    _settings_cache = raw if isinstance(raw, dict) else {}
    return _settings_cache


def _env_override(name: str) -> tuple:
    """读 QV_NEWS_<NAME>_URL / QV_NEWS_<NAME>_DISABLED 环境变量。"""
    up = f"QV_NEWS_{name.upper()}_"
    url = os.environ.get(up + "URL")
    disabled = os.environ.get(up + "DISABLED", "").strip().lower() in (
        "1", "true", "yes", "on")
    return url, disabled


def clear_settings_cache() -> None:
    """测试用：清空 settings 缓存。"""
    global _settings_cache
    _settings_cache = None


# ---------------------------------------------------------------------------
# 对外查询接口
# ---------------------------------------------------------------------------

def get_source(name: str) -> Optional[SourceSpec]:
    """按 name 取源配置；合并 settings.json 与 env 覆盖。

    优先级：env > settings.json > SOURCES 默认值。
    """
    spec = SOURCES.get(name)
    if spec is None:
        return None

    # settings.json 覆盖
    override = _load_settings_sources().get(name, {}) or {}
    # env 覆盖
    env_url, env_disabled = _env_override(name)

    new_url = spec.url
    if env_url:
        new_url = env_url
    elif override.get("url"):
        new_url = override["url"]

    new_enabled = spec.enabled
    if env_disabled:
        new_enabled = False
    elif override.get("enabled") is False:
        new_enabled = False

    if new_url == spec.url and new_enabled == spec.enabled and not override:
        return spec

    return SourceSpec(
        name=spec.name, url=new_url, desc=spec.desc,
        enabled=new_enabled, template=spec.template,
        extra=dict(spec.extra),
    )


def get_source_url(name: str, **kwargs: Any) -> str:
    """取源 URL（含 {id} 模板格式化）。"""
    spec = get_source(name)
    if spec is None:
        return ""
    if spec.template:
        return spec.detail_url(**kwargs)
    return spec.url


def source_enabled(name: str) -> bool:
    """该源是否启用（False 时 fetch_xxx 应直接返 []）。"""
    spec = get_source(name)
    if spec is None:
        return True  # 未知源默认放行，避免误伤
    return spec.enabled


def list_sources() -> List[SourceSpec]:
    """列出所有已注册源（供 UI 数据源健康卡展示）。"""
    return list(SOURCES.values())


def all_urls() -> Dict[str, str]:
    """所有源 name->url 快照（用于合规审计 / smoke 断言）。"""
    return {n: s.url for n, s in SOURCES.items()}