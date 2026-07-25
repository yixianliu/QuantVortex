# 期货 AI 预测模块 + K 线图增强

针对 QuantVortex 期货量化系统的三项需求，完成以下交付（全部在沙箱验证通过）：

## 1. AI 辅助预测模块（`api/futures_ai_predict.py`，新增）
- 与 `api/agnes-2.0-flash.py`、千帆 `function call` 示例**同风格**（requests 调 Chat Completions，`Authorization: Bearer` + `stream:false`）。
- `FuturesAIAnalyst.analyze(symbol, bars, horizon, lookback, provider)`：
  - `auto`（默认）：有 API Key + `requests` 则调大模型，否则自动降级本地统计引擎；
  - `llm` / `local` 可强制；
  - 数值预测路径统一由 `futures_quant.analytics.Predictor` 给出，保证离线可跑、可视化一致。
- 返回固定结构 `AIAnalysisResult`（含 `direction/confidence/target/support/resistance/forecast/upper/lower/key_indicators/narrative/source`）+ `to_dict/pretty`。

## 2. K 线图增强（`chart_widget.py` → 新增 `KLineChart`）
- 蜡烛实体+影线（红涨绿跌）、成交量副图、MA5/10/20 叠加+实时图例、价格/量/时间三轴、最新价虚线标签；
- 鼠标**悬浮十字光标 + 信息框**（开高低收/涨跌/量/各均线）、**滚轮缩放**可见根数；
- 纯 QPainter、零额外依赖、深色/浅色主题感知。行情页实时图已由折线升级为蜡烛图。

## 3. UI「预测」页升级为「AI 辅助分析」
- 品种下拉（螺纹钢/白银/沪铜/黄金/当前行情）+ 行情模式/回看根数/预测期数；
- 一键运行：经 importlib 加载 `api` 模块，展示 AI 结论文本、方向/置信度/支撑阻力、关键指标、预测图（历史收盘+预测中枢虚线+置信带）、逐期预测表。

## 验证结果
- `python api/futures_ai_predict.py` → 本地引擎自校验 PASS（多品种）；
- `examples/smoke_ai_kline.py`（offscreen PyQt6）→ 8 项 OK（K 线数据/渲染/AI 分析/主题/悬浮）；
- `examples/predictor_demo.py` → PASS；`compileall` 全过。
- 文档：README 结构树 + `docs/prediction.md` 增补 AI 模块与 K 线说明。

## 边界（如实说明）
- 沙箱未装 `requests` 且无 API Key，AI 模块默认走本地统计引擎；接入真实大模型只需 `pip install requests` + 设置 `FUTURES_AI_API_KEY`。
- 行情仍为合成数据，仅验证逻辑；实盘需替换数据源与券商授权。
- 所有预测为模型输出，**非确定性预测，不构成投资建议**。
