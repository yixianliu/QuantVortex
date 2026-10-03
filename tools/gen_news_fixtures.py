# -*- coding: utf-8 -*-
"""M5-08：资讯源契约测试 fixture 生成器（可再生脚本）。

沙箱无外网 → 按各源**真实正则命中形态**构造代表性 HTML/JSON fixture，
冻结到 tests/fixtures/news_html/。解析改动须同步跑本脚本更新 fixture。

运行：
    /d/anaconda3/python.exe tools/gen_news_fixtures.py
"""
from __future__ import annotations
import json, os, sys

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_PROJ, "tests", "fixtures", "news_html")
os.makedirs(OUT, exist_ok=True)


def write(name: str, content: str, binary: bool = False) -> None:
    p = os.path.join(OUT, name)
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8"}
    with open(p, mode, **kwargs) as f:
        f.write(content)
    print(f"  generated {name} ({os.path.getsize(p)} B)")


def main() -> int:
    print(f"[gen_news_fixtures] target: {OUT}")

    # --- ① 东方财富期货 (EM_ART_RE: href="https://finance.eastmoney.com/a/{id}.html") ---
    em_html = """<html><body>
    <a href="https://finance.eastmoney.com/a/202609283500001.html">螺纹钢期货主力合约突破4000关口</a>
    <a href="https://finance.eastmoney.com/a/202609283500002.html">铁矿石进口量创新高 港口库存累积</a>
    <a href="https://finance.eastmoney.com/a/202609283500003.html">LME铜库存下降 金属需求回暖</a>
    <a href="https://finance.eastmoney.com/a/202609283500004.html">原油库存意外增加 OPEC讨论减产</a>
    <a href="https://finance.eastmoney.com/a/202609273500001.html">黄金期货站上2400美元 避险需求旺盛</a>
    </body></html>"""
    write("eastmoney.html", em_html)

    # --- ② 和讯期货 (HX_ART_RE: href="https://futures.hexun.com/YYYY-MM-DD/xxx.html") ---
    hx_html = """<html><body>
    <a href="https://futures.hexun.com/2026-09-28/hx001.html">焦煤期货大涨 钢厂复产预期升温</a>
    <a href="https://futures.hexun.com/2026-09-28/hx002.html">原油库存去化 供应端收缩</a>
    <a href="https://futures.hexun.com/2026-09-27/hx003.html">白银价格跟随黄金走强</a>
    </body></html>"""
    # 和讯 fetcher 用 .content 按 GBK 解码 → fixture 存 GBK 字节（忠实）
    write("hexun.html", hx_html.encode("gbk"), binary=True)

    # --- ③ 同花顺期货 (_THS_RE: href="...futures/detail/{id}...") ---
    ths_html = """<html><body>
    <a href="//www.10jqka.com.cn/futures/detail/1234567">螺纹钢期货持仓量增加 多头占优</a>
    <a href="//www.10jqka.com.cn/futures/detail/7654321">纯碱期货价格回落 库存压力增大</a>
    <a href="//www.10jqka.com.cn/futures/detail/1112223">豆粕期货震荡 美豆出口改善</a>
    </body></html>"""
    write("ths.html", ths_html)

    # --- ④ 金投网 (_CNGOLD_ART_RE: href="https://futures.cngold.org/..." title="...") ---
    cngold_html = """<html><body>
    <a href="https://futures.cngold.org/c/2026-09-28/00001.html" title="螺纹钢价格持稳 社会库存下降">螺纹钢价格持稳 社会库存下降</a>
    <a href="https://futures.cngold.org/c/2026-09-28/00002.html" title="原油市场消息面复杂 多空博弈加剧">原油市场消息面复杂 多空博弈加剧</a>
    <a href="https://futures.cngold.org/c/2026-09-27/00003.html" title="沪铜震荡整理 等待宏观指引">沪铜震荡整理 等待宏观指引</a>
    </body></html>"""
    write("cngold.html", cngold_html)

    # --- ⑤ 新浪财经滚动 (_SINA_ROLL_RE: href="https?://finance.sina.com.cn/...shtml") ---
    sina_roll_html = """<html><body>
    <a href="https://finance.sina.com.cn/money/future/2026-09-28/doc-abc123.shtml">螺纹钢期货主力合约涨超2% 突破4050元</a>
    <a href="https://finance.sina.com.cn/money/future/2026-09-28/doc-def456.shtml">原油期货跌1% 美能源信息局库存超预期</a>
    <a href="https://finance.sina.com.cn/money/future/2026-09-27/doc-ghi789.shtml">黄金价格再创历史新高 央行增持避险</a>
    </body></html>"""
    write("sina_roll.html", sina_roll_html)

    # --- ⑥ 中金在线 (_ZQ86_RE: href="https?://www.zq86.com/..." 标题在 <a> 内) ---
    zq86_html = """<html><body>
    <a href="https://www.zq86.com/news/20260928/news001.html">铁矿石期货大跌 需求预期走弱</a>
    <a href="https://www.zq86.com/news/20260928/news002.html">焦煤供应收紧 价格有望上行</a>
    <a href="https://www.zq86.com/news/20260927/news003.html">白银期货波动加大 关注美联储信号</a>
    </body></html>"""
    write("zq86.html", zq86_html)

    # --- ⑦ 华尔街见闻 (_WSJ_RE: href="https://wallstreetcn.com/articles/{id}") ---
    wsj_html = """<html><body>
    <a href="https://wallstreetcn.com/articles/3745601">美联储官员暗示暂停加息 黄金价格走强 避险需求升温</a>
    <a href="https://wallstreetcn.com/articles/3745602">原油期货大涨3% OPEC+延长减产协议至年底</a>
    <a href="https://wallstreetcn.com/articles/3745603">国际铜价回升 全球制造业PMI改善</a>
    </body></html>"""
    write("wsj.html", wsj_html)

    # --- ⑧ 金十数据 (_JIN10_FLASH_RE: flash-item div + flash-text div) ---
    jin10_html = """<html><body>
    <div class="flash-item">
      <div class="flash-text">螺纹钢期货主力合约日内涨超1.5% 报4062元/吨 黑色系集体走强</div>
    </div>
    <div class="flash-item">
      <div class="flash-text">原油期货价格大幅上涨 布伦特原油突破85美元 市场关注OPEC+增产节奏</div>
    </div>
    <div class="flash-item">
      <div class="flash-text">国际黄金价格维持高位 避险需求支撑金价 美联储加息预期降温</div>
    </div>
    </body></html>"""
    write("jin10.html", jin10_html)

    # --- ⑨ 新浪财经期货频道 (_SINA_RE: href="https?://finance.sina.com.cn/...shtml") ---
    sina_html = """<html><body>
    <a href="https://finance.sina.com.cn/futures/2026-09-28/doc-111.shtml">螺纹钢期货去库加速 钢厂利润回升</a>
    <a href="https://finance.sina.com.cn/futures/2026-09-28/doc-222.shtml">原油减产提振 布伦特原油震荡走高</a>
    <a href="https://finance.sina.com.cn/futures/2026-09-27/doc-333.shtml">LME铜库存下降 金属需求回暖</a>
    </body></html>"""
    write("sina.html", sina_html)

    # --- ⑩ 期货日报 (_QHRB_RE: href="http://www.qhrb.com.cn/...html") ---
    qhrb_html = """<html><body>
    <a href="http://www.qhrb.com.cn/2026/09/28/001.html">螺纹钢现货价格企稳 期现基差收窄</a>
    <a href="http://www.qhrb.com.cn/2026/09/28/002.html">原油供应端收紧 OPEC+减产协议延长</a>
    <a href="http://www.qhrb.com.cn/2026/09/27/003.html">沪金价格创新高 避险情绪升温</a>
    </body></html>"""
    # 期货日报是 GBK 编码——生成 GBK 字节文件
    write("qhrb.html", qhrb_html.encode("gbk"), binary=True)

    # --- ⑪ 中证网 (_CS_RE: href="https?://www.cs.com.cn/...html") ---
    cs_html = """<html><body>
    <a href="https://www.cs.com.cn/zhengquan/202609/28/art_100_001.html">证监会发布期货市场监管新规 强化风险管理</a>
    <a href="https://www.cs.com.cn/zhengquan/202609/28/art_100_002.html">原油期货市场保证金比例调整通知</a>
    <a href="https://www.cs.com.cn/zhengquan/202609/27/art_100_003.html">黄金储备数据公布 央行连续增持</a>
    </body></html>"""
    write("cs.html", cs_html)

    # --- ⑫ 证券时报 (_STCN_RE: href="https?://[a-z]+.stcn.com/...(html|shtml)") ---
    stcn_html = """<html><body>
    <a href="https://www.stcn.com/article/20260928/100001.html">螺纹钢期货持仓量创新高 多空博弈加剧</a>
    <a href="https://www.stcn.com/article/20260928/100002.html">原油期货价格回落 国际油价承压</a>
    <a href="https://www.stcn.com/article/20260927/100003.html">白银期货走强 光伏需求拉动</a>
    </body></html>"""
    write("stcn.html", stcn_html)

    # --- ⑬ 凤凰财经 (_IFENG_RE: href="https?://finance.ifeng.com/...shtml") ---
    ifeng_html = """<html><body>
    <a href="https://finance.ifeng.com/futures/20260928/5400001.shtml">螺纹钢期货突破4100 黑色系全线走强</a>
    <a href="https://finance.ifeng.com/futures/20260928/5400002.shtml">原油库存去化加速 供应缺口扩大</a>
    <a href="https://finance.ifeng.com/futures/20260927/5400003.shtml">沪金价格创新高 避险资产吸引力提升</a>
    </body></html>"""
    write("ifeng.html", ifeng_html)

    # --- 财联社（CLS_API JSON 接口 → fixture 为 JSON，非 HTML） ---
    cls_json = json.dumps({
        "data": {
            "roll_data": [
                {"id": 1001, "title": "螺纹钢期货主力合约日内涨超2% 黑色系集体走强",
                 "brief": "螺纹主力2601合约日内上涨2.1%报4085元 铁矿石和焦炭跟涨",
                 "content": "螺纹主力2601合约日内上涨2.1%报4085元 铁矿石和焦炭跟涨 市场关注钢厂复产节奏",
                 "ctime": 1727452800, "level": "A", "reading_num": 1520,
                 "stock_list": ""},
                {"id": 1002, "title": "原油期货大涨3% OPEC+延长减产协议至年底",
                 "brief": "布伦特原油收盘报85.6美元 日内涨3.2% 市场反应供应端收缩",
                 "content": "布伦特原油收盘报85.6美元 日内涨3.2% OPEC+声明减产协议延长至2027年Q1",
                 "ctime": 1727449200, "level": "B", "reading_num": 890,
                 "stock_list": ""},
                {"id": 1003, "title": "国际黄金价格维持高位 避险需求支撑金价",
                 "brief": "COMEX黄金主力合约站上2420美元 美联储加息预期降温利好贵金属",
                 "content": "COMEX黄金主力合约站上2420美元 美联储官员暗示暂停加息 央行连续增持",
                 "ctime": 1727445600, "level": "B", "reading_num": 670,
                 "stock_list": ""},
            ]
        }
    }, ensure_ascii=False, indent=2)
    write("cls_api.json", cls_json)

    print(f"[gen_news_fixtures] done: {len(os.listdir(OUT))} files in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
