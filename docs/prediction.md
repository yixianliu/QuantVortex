# 市场预测模块使用说明

路径：`futures_quant/analytics/predictor.py`（统计引擎） + `api/futures_ai_predict.py`（AI 辅助分析模块） + UI「预测」页。

## 一、AI 辅助预测模块（api 文件夹，新增）

文件：`api/futures_ai_predict.py`，与同目录 `agnes-2.0-flash.py`、千帆 `function call` 示例**同风格**（requests 调用 Chat Completions，带 `Authorization: Bearer` 与 `stream:false` 请求体）。

`FuturesAIAnalyst.analyze(symbol, bars, horizon, lookback, provider)` 对**指定期货品种**的历史行情做 AI 辅助分析：

- `provider="auto"`（默认）：若已配置 API Key 且安装 `requests`，调用大模型（百度千帆 `deepseek-v3.1-250821` 或 Agnes，接口/模型可经环境变量 `FUTURES_AI_API_URL` / `FUTURES_AI_API_KEY` / `FUTURES_AI_MODEL` 覆盖），否则自动降级到本地统计引擎；
- `provider="llm"`：强制调用大模型；`provider="local"`：强制本地统计引擎（无需联网）；
- 无论哪种来源，数值预测路径（forecast / upper / lower）统一由本地 `Predictor` 给出，保证可视化一致与可离线运行；
- 返回固定结构 `AIAnalysisResult`：`symbol / direction(看多·看空·中性) / confidence / last_price / target_price / support / resistance / forecast / upper / lower / dates / key_indicators / narrative / source`，UI 与回测报告可直接消费。

独立运行（自校验 + 多品种演示）：

```bash
python api/futures_ai_predict.py
```

> 说明：本环境未安装 `requests` 且无 API Key，默认走本地统计引擎，模块仍可完整跑通与验证；接入真实大模型只需 `pip install requests` 并设置 `FUTURES_AI_API_KEY`。

## 二、统计预测引擎（analytics）

对一段历史 K 线做**趋势分析**与**统计外推预测**，输出：

- **方向研判**：看多 / 看空 / 中性（由趋势强度阈值决定）
- **趋势强度**：-1 ~ +1，综合「对数收盘回归斜率」与「均线排列（快/慢 MA 差 / ATR）」
- **预测路径**：按回归漂移率外推的逐期中枢价
- **情景区间**：随预测步数 √i 放大的上下沿（随机游走式置信带）
- **关键指标**：快/慢 MA、MA 排列、RSI、ATR、波动率、回归拟合优度 R²
- **支撑 / 阻力**：回看窗口内的最低价 / 最高价
- **预测表**：逐期（T+1…T+N）的日期、中枢价、情景区间

UI「预测」页（已升级为「AI 辅助分析」）提供：品种选择（螺纹钢/白银/沪铜/黄金/当前行情）、行情模式、回看根数、预测期数；点击「运行 KP分析」后展示：AI 文本结论 + 方向/置信度/支撑阻力 + 关键指标 + 预测图（历史收盘 + 预测中枢虚线 + 阴影置信带，三档 X 轴标注「历史 / 现在 / 预测」）+ 逐期预测表。

## 三、K 线图（chart_widget.KLineChart，新增）

行情页的实时图升级为**蜡烛图**，纯 QPainter、零额外依赖、主题感知：

- 蜡烛实体 + 影线，**红涨绿跌**（中国期货惯例，可切换）；
- 底部**成交量副图**，颜色与涨跌一致；
- 多均线叠加（MA5/MA10/MA20），左上角图例 + 实时数值；
- 价格 / 成交量 / 时间三轴标注，右侧价格刻度；
- 最新价虚线 + 标签；
- 鼠标**悬浮十字光标 + 信息框**（开高低收 / 涨跌 / 量 / 各均线值）；
- **滚轮缩放**可见根数（20~全部），提升信息密度与可读性。

## 方法（透明、可复现）

1. 取回看窗口内的对数收盘价，用最小二乘线性回归得到每期漂移率 `slope` 与拟合优度 `R²`；
2. 计算快/慢均线、RSI、ATR、对数收益波动率 `σ`；
3. 趋势强度 `ts = 0.5·tanh(slope·500) + 0.5·tanh((MA快−MA慢)/ATR)`，裁剪到 [-1,1]；
4. 方向：`ts>0.15` 看涨，`ts<-0.15` 看跌，否则震荡；
5. 预测中枢 `forecast[i] = 最近收盘 · exp(slope·i)`；
6. 情景带 `band = forecast · exp(±k·σ·√i)`，`k` 默认 1.96；
7. 置信度 `= clamp(0.35 + 0.4·max(R²,0) + 0.25·|ts|, 0, 1)`（启发式，非统计显著水平）。

所有计算在 `predictor.py` 内，纯 numpy，无第三方绘图依赖；UI 图表由 `ui/chart_widget.py`（QPainter）绘制。

## ⚠️ 重要声明

- 本模块所有「预测」均为**统计模型外推**，使用历史价格特征给出情景区间与方向概率，**绝非确定性预测**；
- 不构成任何投资建议或个股推荐；实盘决策须结合自身判断与风险管理；
- 示例数据来自 `data/synthetic.py`（合成行情），仅用于验证功能链路，**不代表真实市场表现**。

## 在代码中使用

```python
from futures_quant.analytics import Predictor
from futures_quant.data.synthetic import generate_bars

df = generate_bars(symbol="PRED.SHFE", mode="trend", n=300, seed=7)
res = Predictor().predict(
    df["close"].tolist(), df["high"].tolist(), df["low"].tolist(),
    df["datetime"].tolist(), horizon=20, lookback=120, freq="1min")
print(res.direction, res.target_price, res.summary)
```

自校验：`python docs/examples/predictor_demo.py`（对关键不变量做断言）。

## 在代码中调用 AI 模块

```python
import importlib.util, os
# 加载 api/futures_ai_predict.py（与 api 文件夹脚本保持一致）
path = os.path.join("api", "futures_ai_predict.py")
spec = importlib.util.spec_from_file_location("futures_ai_predict", path)
mod = importlib.util.module_from_spec(spec); import sys; sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

from futures_quant.data.synthetic import generate_bars
df = generate_bars(symbol="rb.SHFE", mode="trend", n=300, seed=7)
res = mod.FuturesAIAnalyst().analyze("rb.SHFE", df, horizon=20, lookback=120)
print(res.direction, res.target_price, res.source)
print(res.pretty())
```
