"""外部资讯接入：财联社（cls.cn）资讯抓取与情感分析。

定位：把 cls.cn 的实时电报/快讯作为「分析输入」，结合现有模型/算法/策略
做综合分析，丰富预测的数据维度与时效性。

=== 关键修复（爬虫失效根因）===
cls.cn 是 Next.js 动态站点，原始 HTML 只是空壳，快讯内容由
XHR 接口 `/api/cache?name=telegraph` 异步下发（每条含 `brief`/`content`
正文、`ctime`、`level`、`reading_num`、`stock_list` 等）。旧实现用
`requests` 抓原始 HTML 再解析 `<a>` 标签，永远拿不到正文 → 资讯偏置
恒为 0 → 资讯情报功能形同虚设。本版本直接对接该 JSON 接口，
分页累积，提取真实正文用于情感与期货品种匹配。

设计原则（合规与稳健）：
    · 仅「用户主动点击」或预测运行时抓取，绝不自动高频轮询；
    · 本地缓存（data/cls_news_cache.json）＋最短间隔限频（默认 60s），
      避免对目标站点造成压力；
    · 设置浏览器级请求头（UA/Referer/X-Requested-With），仅读取公开快讯；
    · 任何抓取/解析失败均优雅降级（返回缓存或空结果），绝不拖垮主流程；
    · 情感得分采用「中性关键词词典」近似，仅作辅助维度，不构成投资建议。
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import math
import os
import re
import time

try:
    import requests
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    _HAVE_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    _HAVE_BS4 = True
except Exception:  # pragma: no cover
    _HAVE_BS4 = False

from ..runtime import get_data_dir

# —— 财联社真实数据接口（Next.js 电报流，经页面 JS 逆向确认）——
CLS_API = "https://www.cls.cn/api/cache"
CLS_DETAIL = "https://www.cls.cn/detail/{id}"
# 电报流每次最多返回 20 条，分页以最后一条 ctime 为游标向前翻
PAGE_SIZE = 20
CACHE_FILE = os.path.join(get_data_dir(), "cls_news_cache.json")
MIN_INTERVAL = 60.0  # 秒：最短抓取间隔，限频保护

# 请求头：模拟浏览器 XHR，cls.cn 对该接口要求 Referer 与 X-Requested-With
_API_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://www.cls.cn/telegraph",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}

# —— 情感词典（期货/宏观语境，可继续扩充）——
BULL_WORDS = ["利好", "上涨", "涨", "涨停", "攀升", "走高", "上行", "上扬", "拉升",
               "突破", "减产", "限产", "去库", "库存下降", "需求旺盛", "需求改善",
               "需求超预期", "多头", "利多", "上调", "复苏", "宽松", "增产不及预期",
               "出口大增", "供不应求", "企稳回升", "超预期", "收储", "旺季", "抢装",
               "囤货", "升水", "净多", "走强", "翻多", "创", "新高"]
BEAR_WORDS = ["利空", "下跌", "跌", "跌停", "跌破", "重挫", "大跌", "走低", "下行",
               "回落", "下挫", "跳水", "增产", "累库", "库存上升", "库存累库",
               "需求疲软", "需求走弱", "需求不及预期", "空头", "利淡", "下调", "衰退",
               "收紧", "出口下滑", "供过于求", "超预期下行", "承压", "腰斩", "抛储",
               "淡季", "累库", "贴水", "净空", "走弱", "翻空", "腰斩"]

# —— 品种别名（提升资讯召回）：快讯常以简称/品类词出现 ——
# key = universe 中的中文名；value = 额外可命中的关键词（均含核心商品字，避免跨品种误伤）
NAME_ALIASES = {
    "铁矿石": ["铁矿"],
    "螺纹钢": ["螺纹", "螺卷"],
    "热卷": ["热轧", "卷板"],
    "焦炭": ["焦炭"],
    "焦煤": ["焦煤"],
    "沪铜": ["铜", "阴极铜"],
    "沪铝": ["铝"],
    "沪锌": ["锌"],
    "沪镍": ["镍"],
    "沪锡": ["锡"],
    "黄金": ["金价", "黄金"],
    "白银": ["银价", "白银"],
    "原油": ["油价", "原油"],
    "燃料油": ["燃油", "船用油"],
    "低硫燃料油": ["低硫燃油"],
    "沥青": ["沥青"],
    "橡胶": ["天胶", "橡胶"],
    "PTA": ["PTA", "聚酯"],
    "甲醇": ["甲醇"],
    "乙二醇": ["乙二醇", "EG"],
    "聚乙烯": ["塑料", "PE"],
    "聚丙烯": ["PP", "拉丝"],
    "聚氯乙烯": ["PVC"],
    "豆粕": ["豆粕", "美豆", "大豆"],
    "菜粕": ["菜粕", "菜籽"],
    "棕榈油": ["棕榈", "棕油"],
    "豆油": ["豆油"],
    "菜油": ["菜油", "菜籽"],
    "玉米": ["玉米"],
    "鸡蛋": ["鸡蛋"],
    "生猪": ["生猪", "猪肉"],
    "棉花": ["棉花"],
    "白糖": ["白糖", "食糖"],
    "苹果": ["苹果"],
    "红枣": ["红枣"],
    "玻璃": ["玻璃"],
    "纯碱": ["纯碱", "轻质碱"],
    "锰硅": ["锰硅", "硅锰"],
    "硅铁": ["硅铁"],
    "不锈钢": ["不锈钢"],
    "碳酸锂": ["碳酸锂", "锂"],
    "工业硅": ["工业硅", "硅"],
}


# =========================== 缓存 ===========================
def _cache_read() -> dict | None:
    """读取本地缓存（不判断时效性）。"""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_fresh() -> bool:
    data = _cache_read()
    if not data:
        return False
    return (time.time() - float(data.get("ts", 0.0))) < MIN_INTERVAL


def _cache_put(items: list) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "items": items}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass


# =========================== 接口抓取 ===========================
def _normalize(raw: dict) -> dict | None:
    """把接口返回的单条原始快讯规整为统一结构。

    统一字段：id, title, content(正文), url, ts(可读时间), ctime,
    level(重要度 A/B/C), reading_num, stock_list(关联个股快照)。
    """
    cid = raw.get("id")
    if not cid:
        return None
    title = (raw.get("title") or "").strip()
    brief = (raw.get("brief") or raw.get("content") or "").strip()
    content = brief or title
    if not content:
        return None
    ctime = raw.get("ctime") or 0
    try:
        ts = dt.datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
    except Exception:
        ts = ""
    level = (raw.get("level") or "").strip()
    try:
        reading = int(raw.get("reading_num") or 0)
    except Exception:
        reading = 0
    return {
        "id": cid,
        "title": title or content[:40],
        "content": content,
        "url": CLS_DETAIL.format(id=cid),
        "ts": ts,
        "ctime": ctime,
        "level": level,
        "reading_num": reading,
        "stock_list": _parse_stock_list(raw.get("stock_list")),
    }


def _parse_stock_list(raw) -> list:
    """把关联个股字段（常为字符串化的列表）安全解析为 [{name, code, chg}]。"""
    if not raw:
        return []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s or s in ("[]", "null"):
            return []
        try:
            items = ast.literal_eval(s)
        except Exception:
            return []
    else:
        return []
    out = []
    for x in items[:6]:
        if isinstance(x, dict):
            out.append({
                "name": x.get("stock_name") or x.get("name") or "",
                "code": x.get("stock_code") or x.get("code") or "",
                "chg": x.get("rise_range_has_null") or x.get("chg") or 0,
            })
    return out


def _fetch_telegraph(limit: int = 40, timeout: int = 10) -> list:
    """调用财联社电报接口，分页累积到 limit 条（每页最多 20）。

    任何异常均返回已累积的部分（或空列表），由上层决定降级策略。
    """
    if not _HAVE_REQUESTS:
        return []
    out: list = []
    seen: set = set()
    last = None
    pages = min(math.ceil(max(1, limit) / PAGE_SIZE), 5)
    for _ in range(pages):
        params = {
            "rn": PAGE_SIZE,
            "lastTime": last if last is not None else int(time.time()),
            "name": "telegraph",
        }
        try:
            resp = requests.get(CLS_API, params=params,
                                headers=_API_HEADERS, timeout=timeout)
            if resp.status_code != 200:
                break
            data = resp.json().get("data", {})
            chunk = data.get("roll_data", []) or []
        except Exception:
            break
        if not chunk:
            break
        for it in chunk:
            cid = it.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            norm = _normalize(it)
            if norm:
                out.append(norm)
        if len(out) >= limit:
            break
        last = chunk[-1].get("ctime")
    return out[:limit]


# =========================== 对外主接口 ===========================
def fetch_cls_news(limit: int = 40, force: bool = False) -> dict:
    """抓取财联社电报快讯。返回 {ts, items:[...], source, cached}。

    source ∈ {"cls.cn"(实时抓取), "cache"(本地缓存), "none"(全失败)}。
    force=True 时忽略限频与缓存强制刷新；否则优先使用「未过期的」本地缓存。
    任何失败均降级：抓取失败回退缓存，缓存亦无则返回空 items。
    """
    cached = _cache_read()
    # 缓存有效且非强制 → 直接返回缓存
    if cached and not force and _cache_fresh():
        return {"ts": cached.get("ts"), "items": cached.get("items", [])[:limit],
                "source": "cache", "cached": True}
    # 实时抓取（分页累积）
    items = _fetch_telegraph(limit=limit)
    if items:
        _cache_put(items)
        return {"ts": time.time(), "items": items[:limit],
                "source": "cls.cn", "cached": False}
    # 抓取失败 → 回退缓存（若有）
    if cached:
        return {"ts": cached.get("ts"), "items": cached.get("items", [])[:limit],
                "source": "cache", "cached": True}
    return {"ts": None, "items": [], "source": "none", "cached": False}


# =========================== 情感分析 ===========================
def _sentiment_of(text: str) -> tuple:
    """返回 (score, matched)，score∈[-1,1]，matched 为命中的关键词列表。"""
    score = 0
    matched = []
    for w in BULL_WORDS:
        if w in text:
            score += 1
            matched.append(w)
    for w in BEAR_WORDS:
        if w in text:
            score -= 1
            matched.append(w)
    norm = max(1, len(matched))
    return (max(-1.0, min(1.0, score / norm)), matched)


def _text_of(it: dict) -> str:
    """取条目的可分析文本（优先正文 content，回退 title）。"""
    return it.get("content", "") or it.get("title", "")


def _level_weight(level: str) -> float:
    """重要度加权：A 最重要、C 最弱。"""
    return {"A": 1.0, "B": 0.8, "C": 0.6}.get((level or "").upper(), 0.7)


def _hit_view(it: dict, s: float) -> dict:
    """给命中条目构造展示用视图（含真实正文片段）。"""
    content = _text_of(it)
    return {
        "id": it.get("id"),
        "title": it.get("title") or content[:40],
        "content": content,
        "url": it.get("url", ""),
        "ts": it.get("ts", ""),
        "level": it.get("level", ""),
        "reading_num": it.get("reading_num", 0),
        "sentiment": round(s, 3),
        "snippet": content[:120],
    }


def news_bias_for_symbol(symbol: str, name: str, category: str = "",
                        news: dict | None = None) -> dict:
    """为某品种计算资讯情感偏置（bias∈[-0.6,0.6]）。

    用「品种名 / 板块 / 代码」在快讯 *正文/标题* 中做关键词匹配
    （旧版只看 title，而电报类快讯 title 多为空，导致永远命中不了）。
    命中条目的情感得分按重要度(level)加权取均值。无命中或抓取失败
    返回 bias=0（中性）。
    """
    if news is None:
        news = fetch_cls_news(limit=40)
    items = news.get("items", [])
    # 匹配键：中文品种名 + 别名 + 板块。
    # 注意：刻意【不】使用拉丁代码前缀（rb/cu/bu/MA …）做子串匹配，
    # 因其极易误命中英文文本（如 "SeCuRities"/"WeBUsh"/"BENCHMARK" 中的 cu/bu/MA），
    # 改为仅依赖中文商品名、品类别名与板块词，中文子串匹配足够特异且可靠。
    keys = [name, category] + NAME_ALIASES.get(name, [])
    keys = [k for k in keys if k]
    hits = []  # (item, score)
    for it in items:
        txt = _text_of(it)
        if not any(k and k in txt for k in keys):
            continue
        s, _ = _sentiment_of(txt)
        hits.append((it, s))
    if not hits:
        return {"bias": 0.0, "matched": 0, "samples": [], "items": []}
    wsum = 0.0
    wtotal = 0.0
    for it, s in hits:
        w = _level_weight(it.get("level"))
        wsum += s * w
        wtotal += w
    bias = (wsum / wtotal) if wtotal else 0.0
    bias = max(-0.6, min(0.6, bias))
    samples = [it.get("title") or _text_of(it)[:40] for it, _ in hits[:5]]
    items_view = [_hit_view(it, s) for it, s in hits[:10]]
    return {"bias": round(bias, 3), "matched": len(hits),
            "samples": samples, "items": items_view}


def analyze_symbol_news(symbol: str, name: str, category: str = "",
                        news: dict | None = None) -> dict:
    """对品种做「资讯深度解读」所需的完整结构化结果。

    返回 {bias, matched, bull, bear, items:[命中快讯视图]}，
    items 含真实正文片段、情感、重要度、时间，供预测解读面板直接渲染。
    """
    info = news_bias_for_symbol(symbol, name, category, news)
    items = info.get("items", [])
    bull = sum(1 for it in items if it["sentiment"] > 0)
    bear = sum(1 for it in items if it["sentiment"] < 0)
    return {"bias": info["bias"], "matched": info["matched"],
            "bull": bull, "bear": bear, "items": items}


def sentiment_summary(news: dict | None = None) -> dict:
    """全市场快讯情绪概览（用于预测页总览）。"""
    if news is None:
        news = fetch_cls_news(limit=40)
    items = news.get("items", [])
    pos = neg = 0
    for it in items:
        s, _ = _sentiment_of(_text_of(it))
        if s > 0:
            pos += 1
        elif s < 0:
            neg += 1
    total = len(items)
    if total == 0:
        return {"total": 0, "bull": 0, "bear": 0, "bias": 0.0}
    return {"total": total, "bull": pos, "bear": neg,
            "bias": round((pos - neg) / total, 3)}


# ============================================================================
# 多源期货资讯接入（东方财富期货 / 和讯期货）+ AI 多维研判
# ============================================================================
import html  # noqa: E402  （用于清洗文章正文 HTML）

# —— 东方财富期货 ——
EM_HOME = "https://futures.eastmoney.com/"
EM_ART_RE = re.compile(
    r'href="(https://finance\.eastmoney\.com/a/(\d+)\.html)"[^>]*>(.*?)</a>', re.S)
EM_DATE_RE = re.compile(r'/a/(\d{4})(\d{2})(\d{2})\d+\.html')
EM_BODY_RE = re.compile(r'<p[^>]*>(.*?)</p>', re.S)

# —— 和讯期货 ——
HX_HOME = "https://futures.hexun.com/"
HX_ART_RE = re.compile(
    r'href="(https://futures\.hexun\.com/(\d{4})-(\d{2})-(\d{2})/[^"]+\.html)"'
    r'[^>]*>(.*?)</a>', re.S)
HX_BODY_RE = re.compile(r'<p[^>]*>(.*?)</p>', re.S)

# 通用浏览器请求头（不绑定具体站点 Referer，降低被拦概率）
_BROWSER_HEADERS = {
    "User-Agent": _API_HEADERS["User-Agent"],
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/webp,*/*;q=0.8"),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _get(url: str, timeout: int = 10, referer: str = None):
    """带单次重试的 GET（0.3s 退避），吸收瞬时限频/抖动；失败抛异常由上层降级。"""
    last = None
    for _ in range(2):
        try:
            h = dict(_BROWSER_HEADERS)
            if referer:
                h["Referer"] = referer
            return requests.get(url, headers=h, timeout=timeout)
        except Exception as e:  # 瞬时失败：重试一次
            last = e
            time.sleep(0.3)
    raise last or RuntimeError("request failed")


def _clean_html(s: str) -> str:
    s = re.sub(r'<[^>]+>', '', s or '')
    return html.unescape(s).strip()


def _fetch_body(url: str, enc: str, timeout: int = 5,
                referer: str = None) -> str:
    """抓取文章正文（取前若干 <p> 段落拼接），失败返回空串。"""
    if not _HAVE_REQUESTS:
        return ""
    try:
        resp = _get(url, timeout, referer=referer)
        if resp.status_code != 200:
            return ""
        txt = resp.content.decode(enc, "ignore")
        paras = [_clean_html(p) for p in EM_BODY_RE.findall(txt)]
        paras = [p for p in paras if len(p) > 15][:6]
        return " ".join(paras)
    except Exception:
        return ""


def _enrich_bodies(items: list, enc: str, max_n: int = 6, timeout: int = 5,
                     referer: str = None) -> None:
    """并发抓取前 max_n 条正文，写回 item['content']（无正文则保留标题）。"""
    if not _HAVE_REQUESTS or not items:
        return
    cand = items[:max_n]
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(4, len(cand))) as ex:
            futs = {ex.submit(_fetch_body, it["url"], enc, timeout,
                                  referer): it for it in cand}
            for f in as_completed(futs, timeout=timeout * 2):
                it = futs[f]
                try:
                    body = f.result()
                    if body:
                        it["content"] = body
                except Exception:
                    pass
    except Exception:
        pass


def fetch_eastmoney_news(limit: int = 25, timeout: int = 10,
                         enrich: bool = True) -> list:
    """抓取东方财富期货首页的快讯/分析/研报链接并归一化。

    失败（无网络 / 被拦 / 接口变动）一律返回空列表，由上层优雅降级。
    """
    if not _HAVE_REQUESTS:
        return []
    out: list = []
    try:
        resp = _get(EM_HOME, timeout, referer=EM_HOME)
        if resp.status_code != 200:
            return []
        txt = resp.content.decode("utf-8", "ignore")
        seen: set = set()
        for url, datestr, title_html in EM_ART_RE.findall(txt):
            title = _clean_html(title_html)
            if not title or url in seen:
                continue
            seen.add(url)
            m = EM_DATE_RE.search(url)
            ctime = 0.0
            ts = ""
            if m:
                try:
                    d = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    ctime = d.timestamp()
                    ts = d.strftime("%Y-%m-%d")
                except Exception:
                    pass
            out.append({
                "id": "em_" + datestr,
                "title": title,
                "content": title,
                "url": url,
                "ts": ts,
                "ctime": ctime,
                "level": "B",
                "reading_num": 0,
                "source": "东方财富",
            })
            if len(out) >= limit:
                break
    except Exception:
        return out
        if enrich:
            _enrich_bodies(out, "utf-8", max_n=6, timeout=5,
                             referer=EM_HOME)
    return out[:limit]


def fetch_hexun_news(limit: int = 25, timeout: int = 10,
                      enrich: bool = True) -> list:
    """抓取和讯期货首页的行情动态/分析/研报链接并归一化（GBK 编码）。"""
    if not _HAVE_REQUESTS:
        return []
    out: list = []
    try:
        resp = _get(HX_HOME, timeout, referer=HX_HOME)
        if resp.status_code != 200:
            return []
        txt = resp.content.decode("gbk", "ignore")
        # 反爬挑战页（JS 校验、无真实正文）识别：直接按抓取失败降级，
        # 由上层（fetch_all_news 的 try/except）吸收，不影响其他源。
        if ("window." in txt and txt.count("<script") > 2
                and len(HX_ART_RE.findall(txt)) == 0):
            raise RuntimeError("hexun anti-bot challenge")
        seen: set = set()
        for url, y, mo, da, title_html in HX_ART_RE.findall(txt):
            title = _clean_html(title_html)
            if not title or url in seen:
                continue
            seen.add(url)
            try:
                d = dt.datetime(int(y), int(mo), int(da))
                ctime = d.timestamp()
                ts = d.strftime("%Y-%m-%d")
            except Exception:
                ctime, ts = 0.0, ""
            out.append({
                "id": "hx_" + url.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                "title": title,
                "content": title,
                "url": url,
                "ts": ts,
                "ctime": ctime,
                "level": "B",
                "reading_num": 0,
                "source": "和讯",
            })
            if len(out) >= limit:
                break
    except Exception:
        return out
        if enrich:
            _enrich_bodies(out, "gbk", max_n=6, timeout=5,
                             referer=HX_HOME)
    return out[:limit]


# —— 资讯分类（行情动态 / 市场分析 / 政策资讯 / 品种研报 / 其他）——
_CAT_POLICY = ["政策", "国务院", "央行", "证监会", "交易所", "发改委", "关税", "限产令",
                "收储", "抛储", "调控", "监管", "新规", "批复", "国常会", "财政部",
                "工信部", "商务部", "限产", "保供", "约谈", "处罚", "立案", "制裁"]
_CAT_REPORT = ["研报", "评级", "点评", "深度报告", "专题报告", "周报", "月报", "季报",
                "机构观点", "券商", "路演", "纪要", "研报称", "分析报告指出",
                "目标价", "策略报告", "晨会", "调研", "观点认为"]
_CAT_ANALYSIS = ["分析", "解读", "研判", "后市", "展望", "逻辑", "技术面", "基本面",
                  "行情", "策略", "看法", "认为", "预计", "提示", "观点"]
_CAT_DYNAMICS = ["收盘", "开盘", "主力", "持仓", "成交", "涨停", "跌停", "异动", "拉升",
                  "跳水", "突破", "新高", "新低", "合约", "盘", "上涨", "下跌", "涨幅", "跌幅"]


def _classify_category(text: str) -> str:
    t = text or ""
    if any(k in t for k in _CAT_POLICY):
        return "政策资讯"
    if any(k in t for k in _CAT_REPORT):
        return "品种研报"
    if any(k in t for k in _CAT_ANALYSIS):
        return "市场分析"
    if any(k in t for k in _CAT_DYNAMICS):
        return "行情动态"
    return "其他"


def fetch_all_news(limit: int = 60, force: bool = False,
                    use_cls: bool = True, use_em: bool = True,
                    use_hx: bool = True) -> dict:
    """合并多源期货资讯：财联社 + 东方财富 + 和讯。

    返回 {ts, items:[...], sources:{源名:抓取条数}, by_source:{...},
           by_category:{分类:条数}}。
    每条 item 含统一字段 + source + category + sentiment（合并时补全）。
    任何单源失败均不影响其余来源（优雅降级）。
    """
    parts: list = []
    if use_cls:
        try:
            c = fetch_cls_news(limit=limit, force=force)
            parts.append(("财联社", c.get("items", [])))
        except Exception:
            pass
    if use_em:
        try:
            parts.append(("东方财富", fetch_eastmoney_news(limit=limit)))
        except Exception:
            pass
    if use_hx:
        try:
            parts.append(("和讯", fetch_hexun_news(limit=limit)))
        except Exception:
            pass

    result = {"ts": time.time(), "items": [], "sources": {},
              "by_source": {}, "by_category": {}}
    seen: set = set()
    for src_name, items in parts:
        result["sources"][src_name] = len(items)
        for it in items:
            key = (it.get("title") or "")[:40] + "|" + (it.get("url") or "")
            if key in seen:
                continue
            seen.add(key)
            txt = _text_of(it)
            if "sentiment" not in it:
                s, _ = _sentiment_of(txt)
                it["sentiment"] = round(s, 3)
            if "category" not in it:
                it["category"] = _classify_category(txt)
            it.setdefault("source", src_name)
            result["items"].append(it)
            result["by_source"][src_name] = result["by_source"].get(src_name, 0) + 1
            cat = it.get("category", "其他")
            result["by_category"][cat] = result["by_category"].get(cat, 0) + 1
    result["items"].sort(key=lambda x: x.get("ctime", 0) or 0, reverse=True)
    result["items"] = result["items"][:limit]
    return result


# ============================================================================
# AI 多维研判（LLM 可选 + 规则兜底）
# ============================================================================
# LLM 接入：兼容 OpenAI / 百度千帆（千帆提供 OpenAI 兼容端点）等。
# 通过环境变量配置（不写死密钥）：
#   QV_LLM_BASE  = "https://xxx/v1"      （chat/completions 所在 base）
#   QV_LLM_KEY   = "sk-..."             （Bearer Token）
#   QV_LLM_MODEL = "ernie-4.0-8k"      （模型名，默认回退值）
# 未配置时自动使用规则合成（始终可用、零额外依赖）。

def _llm_chat(system: str, user: str, *, max_tokens: int = 900,
               temperature: float = 0.3) -> str | None:
    base = os.environ.get("QV_LLM_BASE")
    key = os.environ.get("QV_LLM_KEY")
    if not (base and key) or not _HAVE_REQUESTS:
        return None
    model = os.environ.get("QV_LLM_MODEL", "ernie-4.0-8k")
    try:
        resp = requests.post(
            base.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                  "temperature": temperature, "max_tokens": max_tokens},
            timeout=20)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def _symbol_mentions(items: list) -> dict:
    """统计各品种在资讯中被提及次数（用于「品种关注建议」）。"""
    cnt: dict = {}
    for name_, aliases in NAME_ALIASES.items():
        keys = [name_] + aliases
        n = 0
        for it in items:
            txt = _text_of(it)
            if any(k and k in txt for k in keys):
                n += 1
        if n:
            cnt[name_] = n
    return dict(sorted(cnt.items(), key=lambda x: -x[1])[:8])


def _heuristic_report(all_news: dict, res: dict, name: str,
                      category: str) -> dict:
    """规则合成多维度研判（无 LLM 时的兜底，保证始终有结论）。"""
    items = all_news.get("items", [])
    total = len(items)
    bull = sum(1 for it in items if float(it.get("sentiment", 0)) > 0)
    bear = sum(1 for it in items if float(it.get("sentiment", 0)) < 0)
    bias = (bull - bear) / total if total else 0.0
    by_cat = all_news.get("by_category", {})
    pol = [it for it in items if it.get("category") == "政策资讯"]
    pol_bull = sum(1 for it in pol if float(it.get("sentiment", 0)) > 0)
    pol_bear = sum(1 for it in pol if float(it.get("sentiment", 0)) < 0)
    rep = [it for it in items if it.get("category") == "品种研报"]
    rep_bull = sum(1 for it in rep if float(it.get("sentiment", 0)) > 0)
    p_up = float(res.get("p_up", 0.5))
    model_dir = "偏多" if p_up >= 0.55 else "偏空" if p_up <= 0.45 else "中性"
    exp = float(res.get("expected_return_pct", 0.0))
    risk_label = (res.get("risk") or {}).get("label", "中")

    tone_word = ("偏多" if bias > 0.05 else "偏空" if bias < -0.05 else "中性")
    consistent = ((tone_word == "偏多" and model_dir == "偏多") or
                  (tone_word == "偏空" and model_dir == "偏空"))
    trend = (f"综合 {total} 条多源资讯（东方财富/和讯/财联社），整体情绪"
              f"「{tone_word}」（偏置 {bias:+.2f}）：偏多 {bull} 条 / 偏空 {bear} 条。"
              f"其中政策面 {len(pol)} 条（偏多 {pol_bull} / 偏空 {pol_bear}），"
              f"品种研报 {len(rep)} 条（偏多 {rep_bull}）。\n"
              f"结合模型看{'涨' if p_up >= 0.55 else '跌' if p_up <= 0.45 else '震荡'}"
              f"概率 {p_up * 100:.0f}%、预期 {exp:+.2f}%，「{name}」中期趋势研判为"
              f"【{('震荡偏多' if tone_word == '偏多' else '震荡偏空' if tone_word == '偏空' else '区间震荡')}】，"
              f"与模型方向{'一致' if consistent else '互为参考'}。")
    risks = []
    if pol_bear:
        risks.append(f"政策面出现 {pol_bear} 条偏空信号（限产/调控/监管等），"
                     f"需警惕政策逆风；")
    if bias < -0.05:
        risks.append(f"资讯整体偏空（偏置 {bias:+.2f}），消息端暂不支持强势做多；")
    if risk_label in ("高", "中高"):
        risks.append(f"模型风险度「{risk_label}」，波动放大，逆势单易触发止损；")
    if bull and bear and abs(bull - bear) <= max(2, total * 0.2):
        risks.append("多空资讯数量接近、观点分歧明显，方向确认前宜控仓；")
    if not risks:
        risks.append("当前未识别到显著风险信号，但仍须设好止损、控制单笔仓位。")
    risk = " ".join(risks)
    mentions = _symbol_mentions(items)
    top = [k for k in mentions if k != name][:3]
    sugg = (f"资讯覆盖 {len(mentions)} 个品种，其中「{name}」被提及 "
            f"{mentions.get(name, 0)} 次；可重点跟踪 "
            f"{('、'.join([name] + top) if top else name)} 的供需与政策变化。")
    if rep:
        sugg += f"机构研报共 {len(rep)} 篇，建议优先阅读研报观点以校准方向预期。"
    return {"model": "heuristic", "trend": trend, "risk": risk,
            "suggestion": sugg, "by_category": by_cat}


def ai_analyze_news(all_news: dict, res: dict, name: str,
                    category: str, mdm=None) -> dict:
    """对多源资讯做 AI 多维研判，返回 {model, trend, risk, suggestion, by_category}。

    - 若配置了 LLM（QV_LLM_*），调用模型生成结构化 JSON；
    - 否则用规则合成兜底；任何异常均回退规则，保证始终有结论。
    """
    if not all_news or not all_news.get("items"):
        return {"model": "heuristic",
                "trend": "暂无可用的多源资讯，趋势研判以技术模型为主。",
                "risk": "资讯缺失，注意单独依赖技术信号的局限，严格止损。",
                "suggestion": "建议补充资讯源或手动关注品种基本面。",
                "by_category": {}}
    items = all_news["items"][:40]
    ctx = []
    for it in items:
        s = float(it.get("sentiment", 0))
        tone = "偏多" if s > 0 else "偏空" if s < 0 else "中性"
        ctx.append(f"[{it.get('source', '')}/{it.get('category', '')}] "
                   f"(情绪{tone}) {it.get('title', '')}")
    p_up = float(res.get("p_up", 0.5))
    ctx_block = "\n".join(ctx)
    system = ("你是期货量化研究的资深分析师。基于给定的多源期货资讯与模型预测，"
              "输出严格 JSON：{\"trend\":趋势研判(含方向与理由),"
              "\"risk\":风险提示(具体风险点),\"suggestion\":品种关注建议(跟踪哪些品种/逻辑)}。"
              "不要多余解释，只输出 JSON。")
    user = (f"品种：{name}（{category}）。模型看涨概率 {p_up * 100:.0f}%，"
             f"预期涨跌 {float(res.get('expected_return_pct', 0)):+.2f}%，"
             f"风险度「{(res.get('risk') or {}).get('label', '中')}」。\n"
             f"多源资讯（{len(items)} 条）：\n{ctx_block}")
    raw = _llm_chat(system, user)
    if raw:
        try:
            s = raw.strip()
            if s.startswith("```"):
                s = s.strip("`")
                if s.lower().startswith("json"):
                    s = s[4:]
            d = json.loads(s)
            return {"model": os.environ.get("QV_LLM_MODEL", "llm"),
                    "trend": str(d.get("trend", "")),
                    "risk": str(d.get("risk", "")),
                    "suggestion": str(d.get("suggestion", "")),
                    "by_category": all_news.get("by_category", {})}
        except Exception:
            pass
    return _heuristic_report(all_news, res, name, category)
