report = r'''# 行情全景面板：财经资讯 + AI 智能解读 模块研究报告

> 只读调研报告（Plan Mode）。目标：定位并分析「行情全景」右侧「财经资讯 + AI 智能解读」的
> (a) 资讯抓取/返回结构，(b) AI 综合研判 / 技术面解读的 prompt 构建与融合逻辑，(c) AI 输出文本的展示方式。
> 所有行号均来自 2026-08-13 实际读取，代码片段为真实源码。

## 0. 关键文件清单

| 文件 | 角色 | 规模 |
|---|---|---|
| `D:/PythonProject/QuantVortex/futures_quant/ai/news_feed.py` | 多源资讯抓取 + AI 研判 / 规则兜底 | ~1970 行 |
| `D:/PythonProject/QuantVortex/futures_quant/ai/llm_client.py` | Agnes AI 直连客户端 | ~160 行 |
| `D:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py` | 行情全景 UI | ~1742 行 |
| `D:/PythonProject/QuantVortex/futures_quant/ai/predictor.py` | 预测模块（news_bias 融合） | ~29000 B |
| `D:/PythonProject/QuantVortex/futures_quant/indicators/tech.py` | `add_indicators`（指标计算，被 `_compute_technical` 调用） | — |

## 1. 数据流总览

页面类 `MarketOverviewPage(BasePage)`（`market_overview_page.py:96`），右侧常驻「财经资讯 + AI 智能解读」面板。

- 自动加载：`showEvent`（`market_overview_page.py:798`）→ `QTimer.singleShot(600, self._run_news)`（L812）。
- 手动刷新：`news_btn.clicked.connect(self._run_news)`（L170）。
- 核心流程 `_run_news`（L1046）`work()`（L1056）：
  1. `news = news_feed.fetch_all_news(limit=60)`
  2. `bias = _news_overall_bias(news)` —— 全市场情绪偏置（L74）
  3. 构造模型概率壳 `res = {"p_up", "expected_return_pct", "risk"}`（L1064）
  4. `analysis = news_feed.ai_analyze_news(news, res, "期货市场", "全市场", mdm=self.mdm)` ← **综合研判**
  5. `tech = self._compute_technical(self.cur_symbol, self.cur_period, news_bias=bias)` ← **技术面解读**
  6. `sd_rows = news_feed.news_bias_for_symbol(...)` —— 板块供需信号（L1070）
- `done(payload)`（L1076）→ `_fill_news`（L1132）→ 渲染 `news_list` 与 `_render_ai(analysis, tech)`（L1267）。

布局：`_build`（L135）建立 `QSplitter`，左栏 stretch 3、右栏 stretch 2（`market_overview_page.py:212-213`）；右栏为 `QScrollArea` + `_build_news()`（L199-209）。

## 2. (a) 资讯抓取模块：fetch / 返回结构

### 2.1 `fetch_all_news`（`news_feed.py:924`）

```python
def fetch_all_news(limit: int = 60, force: bool = False,
                    use_cls: bool = True, use_em: bool = True,
                    use_hx: bool = True) -> dict:
```

- 任务表（L939-957）共 **13 个源**（含备用）：财联社 / 东方财富 / 和讯 / 同花顺 / 华尔街见闻 / 金十数据 / 新浪财经 / 金投网 / 中金在线 / 中证网 / 证券时报 / 凤凰财经 / 期货日报。
- 并发：`ThreadPoolExecutor(max_workers=min(6, len(tasks)))`（L961），单源失败 `logger.warning` 后继续（L970-971），优雅降级。
- 返回结构（L973-1003）：
```python
result = {"ts": time.time(), "items": [], "sources": {},
          "by_source": {}, "by_category": {}}
# 去重 key = title[:40] + "|" + url
# 合并时补全 sentiment(_sentiment_of) 与 category(_classify_category)，setdefault("source", src)
# 排序 by ctime desc，截断 limit
# source_coverage = {total_sources, active_sources, active:[源名...]}
```

### 2.2 单条 item 的统一结构

`_normalize`（L280）定义统一字段：
```python
{"id", "title", "content", "url", "ts", "ctime", "level", "reading_num", "stock_list"}
```
`fetch_all_news` 额外追加：`source`、`category`、`sentiment`。

**UI 实际使用的 item 字段**：`id, title, content, url, ts, ctime, level, reading_num, stock_list, source, category, sentiment`。

### 2.3 各源抓取函数（均返回 item 列表或 `{"items":[...]}`）

- `fetch_cls_news(limit=40, force=False)` L392 → `{"ts","items","source","cached"}`，source∈`cls.cn`/`cache`/`none`
- `fetch_eastmoney_news` L794、`fetch_hexun_news` L842、`fetch_ths_news` L1492、`fetch_wsj_news` L1661、`fetch_jin10_news` L1722、`fetch_sina_news` L1789、`fetch_qhrb_news` L1803、`fetch_cs_news` L1817、`fetch_stcn_news` L1831、`fetch_ifeng_news` L1845、`fetch_cngold_news`、`fetch_zq86_news`

### 2.4 情感分析

`_sentiment_of(text)`（L460）→ `(score∈[-1,1], matched)`：长词优先匹配 + 否定词窗口极性反转 + 程度副词加权。

### 2.5 源可信度权重

`SOURCE_CREDIBILITY`（L1054）：财联社 1.00、华尔街见闻 0.95、金十 0.95、中证网 0.95、期货日报 0.92、东方财富 0.90、同花顺 0.90、和讯 0.80、凤凰 0.85 等。`_weighted_bias`（L1073）按 重要度×可信度×时间衰减 计算加权偏置。

## 3. (b) AI 解读 / 分析逻辑

### 3.1 综合研判（Tab1「🧠 AI 综合研判」）—— **有 LLM prompt**

入口 `ai_analyze_news(all_news, res, name, category, mdm=None)`（`news_feed.py:1303`）。

无论走 LLM 还是规则兜底，都先共用一套量化指标（L1335-1341）：
```python
coverage  = _compute_coverage(all_news)                       # L1124
consensus = _cross_source_consensus(items, [name, category] + NAME_ALIASES.get(name, []))  # L1092
wbias     = _weighted_bias(items)                             # L1073
confidence = _analysis_confidence(coverage, consensus, wbias) # L1136 -> 0.40*覆盖 + 0.35*一致 + 0.25*偏置强度
```
`ctx_block` 由前 50 条 item 拼接（L1323-1331），形如 `[来源/类别] (情绪偏多/偏空/中性) 标题`。

**LLM prompt 构建（L1350-1363）—— 这是综合研判的 prompt：**
```python
system = ("你是期货量化研究的资深分析师。基于给定的多源期货资讯与模型预测，"
          "输出严格 JSON：{\"trend\":趋势研判(含方向与理由,60-120字,须结合信源覆盖与一致性),"
          "\"risk\":风险提示(具体风险点,30-60字),"
          "\"suggestion\":品种关注建议(跟踪哪些品种/逻辑,30-60字),"
          "\"key_events\":[关键事件列表(每个含事件描述和影响判断)],"
          "\"actionable_insights\":可操作洞察(基于资讯的综合判断,20-50字)}。"
          "不要多余解释，只输出 JSON。")
user = (f"品种：{name}（{category}）。模型看涨概率 {p_up * 100:.0f}%，"
         f"预期涨跌 {float(res.get('expected_return_pct', 0)):+.2f}%，"
         f"风险度「{(res.get('risk') or {}).get('label', '中')}」。\n"
         f"资讯覆盖：{cov_desc}。综合置信度 {confidence*100:.0f}%。{con_desc}。\n"
        f"多源资讯（{len(items)} 条，来自财联社/东方财富/华尔街见闻/金十数据/"
        f"和讯/同花顺/新浪财经/金投网/中证网/证券时报/凤凰财经/中金在线）：\n{ctx_block}")
raw = _llm_chat(system, user)
```

**调用链 → Agnes AI 直连客户端：**
- `_llm_chat`（L1022）→ `from .llm_client import chat as _proxy_chat` → `_proxy_chat(...)`
- `llm_client.chat`（L124）→ `get_client().chat(...)` → `AgnesLLMClient.chat`（L59）
- `AgnesLLMClient.chat` POST 到 `DEFAULT_BASE = "https://api.agnes-ai.cn/v1/chat/completions"`（L28），Bearer `QV_AGNES_API_KEY`（L31），返回 `data["choices"][0]["message"]["content"]`，任何失败返回 `None`。

**LLM 成功解析（L1364-1383）：** 剥离 ```json 围栏 → `json.loads` → 返回：
```python
{"model": "llm(proxy)", "trend", "risk", "suggestion",
 "by_category", "sentiment_breakdown", "key_events", "hot_symbols",
 "actionable_insights", **meta}          # meta = source_coverage/consensus/weighted_bias/confidence
```
**失败 / 无 LLM → 规则兜底** `_heuristic_report`（L1146，回退于 L1386-1395），补充 `sentiment_breakdown / key_events / hot_symbols / actionable_insights`。`_heuristic_report` 的 `trend/risk/suggestion/brief/sector_rotation/actionable_insights` 由关键词密度 + 偏置 + 置信度规则拼接（示例见 L1240-1300）。

> ⚠️ **安全模型注释冲突（重要，改造前必读）：**
> - `news_feed.py` L1006-1020 注释写「经自建代理调用 LLM；未配置代理时自动降级到规则合成」「需要联调真实上游时，请在本地起一份代理服务，而不是让客户端持钥」。
> - 但 `llm_client.py` 实际是 **直接** 用 `QV_AGNES_API_KEY` POST 到 `api.agnes-ai.cn`（L28-98），单例 `get_client()` 无代理中转。
> 两处安全约定不一致。

### 3.2 技术面解读（Tab2「📐 技术面解读」）—— **没有独立 LLM prompt**

技术面解读**完全本地计算**，不经过 LLM。由 `_compute_technical` + `_render_tech` 产出纯 HTML。

`_compute_technical(symbol, period, news_bias=0.0)`（`market_overview_page.py:1498`）：
- `df = self.mdm.get_bars(symbol, period, 260)`，要求 ≥30 根（L1507）
- `ind = add_indicators(df)` 计算 MA5/10/20/60、MACD(DIF/DEA/MACD)、BOLL(up/mid/low)、KDJ(K/D/J)、RSI6/14、OBV
- 多空评分（L1557-1564）：
```python
score = 0.0
score += 28 if bull_align else (-28 if bear_align else 0)
score += 22 if macd_bull else -22
score += 15 if obv_bull else -15
score += (8 if rsi14 > 55 else -8 if rsi14 < 45 else 0)
score += (7 if above_mid else -7)
score = max(-100.0, min(100.0, score))
force = max(-100.0, min(100.0, 0.62 * score + 0.38 * news_bias * 100))
```
- 返回 dict：`last, ma, bull_align, bear_align, dif, dea, hist, golden, death, macd_bull, bup/bmid/blow, kdj_*, rsi*, obv*, supports, resist, score, force, news_bias`

`_render_tech(tech)`（L1583）：8 段 HTML（均线系统 / MACD / 布林 / KDJ-RSI / OBV / 支撑阻力 / 综合技术结论 / 全局研判思路），引用 `tech['force']` 与 `tech['score']`。**无模型调用。**

### 3.3 融合点：资讯面 + 技术面 → AI 叙述

融合发生在三层：

1. **`_outlook_html(a, tech)`（L1447）—— Tab1「🔮 趋势预测与综合研判」：**
```python
tone = (a.get("trend") or "")
if "偏多" in tone or "看多" in tone or "利多" in tone: news_dir = "偏多"
elif "偏空" in tone or "看空" in tone or "利空" in tone: news_dir = "偏空"
else: news_dir = "中性"
tech_dir = "—"
if tech:
    f = tech.get("force", 0.0)
    tech_dir = "偏多" if f > 15 else "偏空" if f < -15 else "中性"
if tech_dir == news_dir or tech_dir == "—":
    synth = "技术面与资讯面方向一致，信号共振，研判可靠性较高"
elif news_dir == "—":
    synth = "资讯面暂无明确倾向，以技术面形态为主要参考"
else:
    synth = "技术面与资讯面出现分歧，建议等待方向确认、控制仓位"
```
并拼接 KDJ/RSI/BOLL/MACD 形态风险提示（L1473-1486）。

2. **`_bullbear_html(tech, consensus, wbias)`（L1404）：** 多空力量条以 `tech["force"]`（缺技术时退化为 `wbias*100`）渲染，标注资讯偏置与看多/看空源数。

3. **`force = 0.62*score + 0.38*news_bias*100`（L1564）：** 技术评分与资讯偏置的加权融合，是「资讯+技术」数值融合核心公式。

## 4. (c) AI 输出文本如何展示

### 4.1 布局构建 `_build_news`（L687）
- `self.news_list = QListWidget()`（maxHeight 280）—— 资讯列表
- `self.ai_tabs = QTabWidget()` 含：
  - `self.ai_view = QTextEdit()`（Tab1「🧠 AI 综合研判」，readOnly，minHeight 420）
  - `self.tech_view = QTextEdit()`（Tab2「📐 技术面解读」，readOnly，minHeight 420）

### 4.2 渲染入口 `_render_ai(a, tech=None)`（L1267）
- 读取 `a["trend"/"risk"/"suggestion"/"key_events"/"hot_symbols"/"actionable_insights"/"model"/"source_coverage"/"consensus"/"confidence"/"weighted_bias"/"brief"/"sector_rotation"]`
- 组装 HTML parts（模型 banner、情报摘要、板块轮动、`_bullbear_html`、`_global_framework_html`、`_outlook_html`、风险提示、关注建议、关键事件、活跃品种、可操作洞察）
- 末尾：`self.ai_view.setHtml("<div ...>" + "".join(parts) + "</div>")`（L1352-1353）
- Tab2：`self.tech_view.setHtml(self._render_tech(tech))`（L1356）

### 4.3 资讯列表行 `_add_news_row(it, p)`（L1215）
- 自定义 `QFrame` 行：顶行 时间 + 来源徽标 + 类别徽标 + 情绪标签（利好/利空/中性，按 `sentiment` 着色）
- 标题（bold）+ 核心含义（`_news_core(it)`，取 `content[:72]` 或 `title+类别+情绪`）
- 通过 `QListWidgetItem` + `setItemWidget` 注入（L1261-1264）

### 4.4 触发与刷新
- 自动：`showEvent` → `QTimer.singleShot(600, self._run_news)`（L812）
- 手动：`news_btn` → `_run_news`（L170）
- 切换合约/周期：`_refresh_tech`（L1703）仅重算技术面（`_compute_technical` + `_render_ai(self._ai_analysis, tech)`），**不重复抓取资讯**

## 5. 预测模块（predictor.py）—— 与资讯的融合

`Predictor.predict(df, horizon=10, news_bias=0.0, news_samples=None, calibrate_p_up=None)`（L348）：
- `news_bias∈[-1,1]` 由 `news_feed` 计算（市场级 `_news_overall_bias` 或板块级 `news_bias_for_symbol`）
- 融合（L391-397）：
```python
if news_bias:
    bias_p = 1.0 / (1.0 + math.exp(-news_bias * 1.5))    # sigmoid 转概率偏置
    p_up = 0.85 * p_up + 0.15 * bias_p                   # 温和融合，单资讯最多撬动 ~±12%
    mean_cum = mean_cum + 0.15 * news_bias * abs(mean_cum if mean_cum else 0.01)
```
注意：`market_overview_page._run_news` 目前**仅把 news_bias 传给 `_compute_technical` 与 `res` 壳**，并未直接调用 `Predictor.predict`；predictor 的 news_bias 融合主要在预测/回测链路中使用。

## 6. 结论与备注

1. **综合研判文本**：来自 LLM（`ai_analyze_news`/`_llm_chat`→`llm_client.chat` 直连 Agnes AI）或 `_heuristic_report` 规则兜底；prompt 在 `news_feed.py:1350-1363`。
2. **技术面解读文本**：无 LLM prompt，纯本地 `add_indicators` → `_compute_technical` → `_render_tech` 的 HTML。
3. **资讯+技术融合**：数值层 `force = 0.62*score + 0.38*news_bias*100`（L1564）；叙事层 `_outlook_html`（L1447）；预测层 `predict` 的 sigmoid 融合（L391）。
4. **展示**：双 `QTextEdit`（`ai_view`/`tech_view`）经 `setHtml`；资讯列表为 `QListWidget` 自定义 `QLabel` 行。
5. **安全注释冲突**：`news_feed.py` L1006-1020「代理」 与 `llm_client.py` 直连不一致，改造时需统一。
'''
path = r'C:/Users/Administrator/.workbuddy/plans/electric-nebula-tesla.md'
with open(path, 'w', encoding='utf-8') as f:
    f.write(report)
print("written", len(report), "chars ->", path)
