# 期货智能分析预测系统（FuturesQuant Analyst）

一套基于 **Python + PyQt6 + pandas/numpy** 的期货**行情分析 / AI 趋势预测 / 量化回测 / 策略自进化 / 信号研判 / 数据复盘 / 风险分析**一体化桌面工具。

> **定位澄清（重要）**：本系统是**分析预测与回测工具，不做自动交易、不撮合、不连接实盘下单**（CTP 仅作只读监控）。它回答的是「这个品种现在处于什么状态、AI 怎么看未来 N 根、量价与指标共振如何、历史上这类信号表现怎样、某策略在历史数据上赚不赚钱」，而非「自动买卖」。所有结论均来自规则与模型，**不构成任何投资建议**。

---

## 一、重要说明（务必先读）

- 本沙箱环境**无法连接期货公司前置机**，也未安装 `vnpy / ctpbee / akshare` 等实时行情包，因此**无法获取真实交易所行情**。
- 为保证系统「可运行、可演示、逻辑可验证」，`data/synthetic.py` 提供了一个**统计特征贴近真实期货**的合成行情引擎（几何布朗运动 + 波动率聚集 + 量价正相关 + 可注入趋势/震荡/混合状态）。
- **合成行情仅用于验证程序逻辑与 UI 表现，不代表真实市场。** 生产环境请用 `data/ctp_gateway.py` 中预留的 `CTPFeed` 接入点接入实盘行情，或用 `SinaFeed` 拉取公开日线（详见「六、接入实盘行情」）。
- 投资有风险，本系统为技术框架，不构成任何投资建议。

---

## 二、七大功能模块

| # | 模块 | 对应页面 / 入口 | 核心能力 |
|---|------|----------------|----------|
| 一 | 系统基础 & 数据中心 | **行情全景** | 行情接口连接/重连、全市场 39 品种订阅筛选、实时盘口快照、多周期 K 线（1m~周线）、自动缓存 |
| 二 | 量化指标分析 | **指标分析** | MA/EMA/MACD/KDJ/RSI(6,14)/BOLL/ATR/DMI(ADX)/SAR/BIAS/MOM/CCI/OBV/VOL_MA；共振分析、背离检测、趋势强弱打分 |
| 三 | AI 智能预测核心 | **AI 预测** | 纯 numpy LSTM 短期趋势预测 + **Agnes AI 云端研判**、未来 N 根 K 线预测、涨跌概率、压力/支撑位、风险度打分、多空性价比 |
| 四 | 市场全景分析 | **市场全景** | 涨跌排行、强弱排序（动量 60% + 量能 40% 分位）、量能暴增/缩量预警、资金净流入/流出、多品种联动 |
| 五 | **回测中心**（策略回测 + 遗传算法自进化） | **回测验证** / 策略回测页 / 预测操作页 / CTP 监控页 / 绩效归因 | 任意品种/周期历史回测、预测准确率统计、胜率/最大回撤/趋势捕捉率、可视化报告、信号融合→模型→校准→实时降级闭环、品种/板块标注、阈值自适应 |
| 六 | 日志 / 预警 / 报告 | **日志预警** | 异动预警、预测/分析记录存档、导出报告（Excel/CSV） |
| 七 | 存储与配置 | 全局 | SQLite(WAL) 持久化、原子写 JSON 配置、会话状态恢复、密钥运行时脱敏 |

> UI 采用专业金融暗黑商务风（同时内置浅色主题）：左侧 SVG 图标导航 / 中间 K 线预测主区 / 右侧参数面板 / 底部状态栏；圆角控件、阴影分层、hover 高亮、**红涨绿跌**（中国期货惯例 `up=#ef4444 / down=#22c55e`），自适应布局。

---

## 三、项目结构

```
futures_quant/
├── data/                 # 数据层
│   ├── synthetic.py      # 合成行情引擎（默认离线数据源）：generate_bars / resample_bars / SyntheticFeed(周期感知)
│   ├── sina_feed.py      # SinaFeed：新浪公开期货日线（免密钥、无需柜台）
│   ├── ctp_gateway.py    # CTPFeed 可插拔适配器（占位实现，需用户机器装 CTP 动态库 + 柜台凭据）
│   ├── market_data.py    # MarketDataManager：缓存 + 盘口快照 + 全市场全景 + 模拟实时流
│   ├── akshare_feed.py   # AkShareFeed：备用真实数据源
│   ├── csv_feed.py       # CSVFeed：从本地 CSV 读取真实行情回放（封闭、可复现）
│   └── base.py           # DataFeed 抽象基类
├── indicators/           # 指标层（纯 numpy/pandas 向量化）
│   └── tech.py           # sma/ema/boll/macd/dmi/sar/rsi/kdj/cci/roc/bias/momentum/obv/vol_ma + add_indicators
├── ai/                   # AI 预测层
│   ├── lstm.py           # 批量化纯 numpy LSTM（BPTT + Adam + 梯度裁剪）
│   ├── predictor.py      # FuturesPredictor：特征工程 + 训练(LSTM/岭回归回退) + 多步递归预测 + 研判
│   ├── llm_client.py     # 直接调用 Agnes AI API（云端研判）；双模式密钥管理
│   ├── config.py         # AIConfig：密钥仅内存持有；双模式（调试/打包）逻辑
│   ├── ensemble.py       # 多周期模型集成
│   ├── features.py       # 特征工程
│   ├── news_feed.py      # 新闻/舆情抓取与情绪打分
│   ├── calibration_replay.py  # 预测校准离线回放（Wilson/PAVA）
│   └── feedback.py       # 预测反馈闭环
├── analysis/             # 分析研判层
│   ├── signals.py        # resonance() 多空共振打分 / trend_score() 趋势强弱 / divergence() 背离
│   └── support_resistance.py  # compute_levels() 压力/支撑（pivot/swing/volume-cluster）
├── backtest/             # 回测引擎（回测中心核心）
│   └── backtester.py     # Backtester：串联行情源/交易引擎/经纪商，按 K 线逐根驱动，产出指标与 SVG 报告
├── broker/               # 经纪商撮合层
│   ├── base.py           # BrokerBase 抽象基类（submit/match 契约）
│   ├── backtest_broker.py# BacktestBroker：下一根 bar 开盘撮合（防未来函数）
│   └── paper.py          # PaperBroker：仿真/实盘即时撮合（含滑点）
├── strategy/             # 策略层
│   ├── base.py           # StrategyBase：on_bar 信号回调 + 持仓辅助
│   ├── auto_evolve.py    # 遗传算法策略自进化（变异/交叉/选择/适应度）
│   ├── breakout.py / grid.py / martingale.py / mean_reversion.py / trend_following.py  # 内置策略
├── risk/                 # 风控层
│   └── risk_manager.py   # RiskManager：下单前校验仓位/回撤/品种约束
├── core/                 # 引擎核心
│   ├── engine.py         # TradingEngine：逐根 K 线驱动策略、撮合、维护账户与成交日志（无未来函数）
│   ├── portfolio.py      # Portfolio：保证金/持仓/盈亏
│   └── types.py          # Order/Trade/Bar/Direction 等核心类型
├── storage/              # 存储层（持久化方案，见「八、数据持久化方案」）
│   ├── json_store.py     # AtomicJSON：原子写 + .bak 备份 + 损坏自愈 + 版本迁移
│   ├── config_manager.py # ConfigManager（用户配置）+ SessionState（运行时状态）
│   ├── analysis_store.py # AnalysisStore：SQLite(WAL) 缓存 bars / 预测 / 分析 / 预警 / 日志
│   ├── sqlite_backend.py / postgres_backend.py / base.py  # 存储后端（SQLite / Postgres / 抽象）
│   └── data_transfer.py  # SQLite <-> MySQL 数据迁移
├── alerts/               # 预警规则引擎（scan / RULE_KINDS / rule_label）
├── ui/                   # UI 层（PyQt6，零图表依赖，原生 QPainter 绘制）
│   ├── main_window.py    # 主窗口外壳：左导航 + 多页堆叠 + 状态栏 + 深/浅主题切换
│   ├── pages.py          # 六大页（MarketPage/IndicatorPage/PredictPage/PanoramaPage/ValidatePage/LogPage）
│   ├── backtest_page.py / simple_backtest_page.py / predict_ops_page.py / ctp_monitor_page.py  # 回测中心页
│   ├── attribution_dialog.py  # R6 绩效归因对话框
│   ├── chart_widget.py   # KLineChart：蜡烛图 + 成交量 + 均线 + 预测曲线/置信带 + 压力支撑 + 十字光标
│   ├── widgets.py        # 复用组件：PageHeader/Badge/MetricChip/ConfidenceBar/表格配色工具
│   └── ai_settings_dialog.py  # AI 设置对话框（仅 API 密钥输入）
├── utils/                # 工具层：分级日志、运行时脱敏（redact）
└── runtime.py            # 运行时辅助
main.py                   # 统一入口：python main.py [--theme dark|light] [--test]
config/settings.json      # 分析向配置（ui.theme / data.source / analysis.default_*）
requirements.txt          # 运行依赖（pandas / numpy / PyQt6；CTP / PyInstaller 标注可选）
examples/
├── run_backtest.py       # 回测中心独立演示
├── capture_ui.py         # offscreen 渲染各页 UI，输出深/浅两套 PNG
├── sina_demo.py          # 实盘(Sina)数据拉取 + 指标 + AI 预测演示
├── smoke_ai_kline.py / storage_demo.py / backtest/  # 各模块独立演示
```

> **已清理模块（历史遗留，已从仓库移除）**：早期 `server/`（代理层）、`analytics/`（与 `ai/` 重复的轻量预测器）、`core/event.py`、`ai/evaluate.py`、`screening_eval.py` 等零引用死代码已在整理阶段删除；`analytics` 的轻量预测器已迁至 `api_docs/local_predictor.py` 供示例自包含使用。`futures_quant/` 内所有源文件已补齐中文 docstring（函数功能 / 参数 / 返回值），覆盖率 100%。

---

## 四、快速开始

```bash
# 1. 准备虚拟环境（推荐 Python 3.9+，项目实测 3.13）
python -m venv venv && venv/Scripts/activate        # Windows
pip install -r requirements.txt                      # 仅需 pandas / numpy / PyQt6

# 2. 启动桌面端（默认深色主题，内置合成行情）
python main.py
python main.py --theme light                         # 浅色主题
python main.py --test                                # 仅校验核心模块可导入（无 UI，CI 友好）

# 3. 核心层自检 / 回测演示（无 UI）
python examples/run_backtest.py

# 4. 离线渲染各页 UI 截图（交付/视觉确认用）
QT_QPA_PLATFORM=offscreen python examples/capture_ui.py
```

桌面端包含行情全景 / 指标分析 / AI 预测 / 市场全景 / 回测验证 / 日志预警六大页，以及回测中心子页（策略回测、预测操作、CTP 只读监控、绩效归因）。支持深色/浅色主题、左侧 SVG 图标导航、实时 K 线蜡烛图、AI 分析结论卡片、39 品种自选行情（双击切换主图）、预测曲线与压力/支撑标注。

### 在自己的数据上做分析 / 预测 / 回测

```python
from futures_quant.data.synthetic import SyntheticFeed
from futures_quant.indicators.tech import add_indicators
from futures_quant.ai.predictor import FuturesPredictor
from futures_quant.backtest.backtester import Backtester

feed = SyntheticFeed()
df = feed.get_recent("rb.SHFE", "D", limit=600)      # 日线最近 600 根
ind = add_indicators(df)                             # 注入全部技术指标

# AI 预测
pred = FuturesPredictor()
pred.fit(df, seq_len=20, epochs=30)                  # 训练（LSTM，异常时自动回退岭回归）
res = pred.predict(df, horizon=12)                   # 预测未来 12 根
print(res["model"], "p_up:", res["p_up"], "风险:", res["risk"]["label"])

# 回测（防未来函数：信号在下一根 bar 开盘撮合）
bt = Backtester(feed, strategy=my_strategy)
out = bt.run("rb.SHFE", "2023-01-01", "2023-12-31", period="D")
print(out["metrics"])
```

---

## 五、各模块说明

### 数据层（数据中心）
- `SyntheticFeed` 为**周期感知**数据源：日内周期（1m/5m/15m/30m/1h/4h）以 1 分钟基准序列按需重采样；日线/周线（D/W）直接以该周期生成（日线约 720 根、周线约 320 根），避免「从 1 分钟重采样日线只剩几根」的陷阱，保证指标与预测有足够样本。
- `MarketDataManager` 负责缓存、盘口快照（`get_quote`）、全市场全景（`compute_panorama`，强弱分 = 动量 60% + 量能 40% 分位）、以及基于 `QTimer` 的模拟实时流（`start_live`）。
- 全市场覆盖 **39 个期货品种**，横跨黑色系 / 有色金属 / 贵金属 / 能源化工 / 农产品 / 金融 六大板块（`FUTURES_UNIVERSE`）。

### 指标层（量化指标分析）
- `add_indicators(df)` 一次性注入：MA5/10/20/60、EMA20、BOLL(中/上/下轨)、MACD(DIF/DEA/MACD)、KDJ(K/D/J)、RSI6/14、DMI(含 ADX)、SAR、BIAS6、MOM10、CCI14、OBV、VOL_MA5、ROC12。
- 研判函数：`resonance()` 多空共振打分（±100）、`trend_score()` 趋势强弱（0~100，基于 ADX）、`divergence()` RSI 背离检测；`compute_levels()` 压力/支撑位（pivot + swing + 量能聚类）。

### AI 预测层（AI 智能预测核心）
- **本地零依赖 LSTM**：`ai/lstm.py` 为纯 numpy 实现（批量前向 + BPTT 反向 + Adam + 梯度裁剪 clip=5.0），无 torch / sklearn 依赖，可在沙箱离线训练。
- `FuturesPredictor` 流程：特征工程（对数收益、滚动波动、RSI/MACD/KDJ/BOLL%/CCI）→ 训练「下一根对数收益」LSTM（数值异常自动回退岭回归）→ 以最近窗口**递归外推**未来 N 根收盘价路径并给出 ±1σ 预测带 → 研判（涨跌概率正态近似、压力/支撑、风险度、多空性价比、行情状态：趋势/震荡/震荡收敛变盘）。
- **Agnes AI 云端研判（可选）**：`ai/llm_client.py` 直接调用 `https://api.agnes-ai.cn/v1/chat/completions`，为预测结论补充自然语言解读。**密钥安全见「九、安全架构」**。当云端不可用时自动降级为本地规则合成文本，不影响主流程。

### 回测中心（策略回测 + 遗传算法自进化）
- `Backtester` 串联行情源、`TradingEngine` 与 `BrokerBase` 子类，**按 K 线逐根驱动**策略信号；`BacktestBroker` 保证**下一根 bar 开盘价撮合**（防未来函数），`PaperBroker` 用于仿真/实盘即时撮合（含滑点）。
- `RiskManager` 在下单前校验仓位、回撤与品种约束，拦截超限委托。
- `strategy/auto_evolve.py` 提供**遗传算法策略自进化**：以变异/交叉/选择迭代优化策略参数，适应度基于历史回测绩效（胜率、收益、回撤等）。
- 回测产出指标（收益/胜率/最大回撤/趋势捕捉率/夏普）与 SVG 可视化报告，支撑「信号→预测→回测→归因」闭环验证。

### 存储层（日志 / 预警 / 报告）
- `AnalysisStore`（SQLite，WAL 模式）持久化：K 线缓存、预测记录、分析结论、异动预警、系统日志；启动做 `integrity_check()` 完整性校验，退出前 `checkpoint()` 合并 WAL，`prune()` 限容防止无限膨胀；`export_csv()` 支持将预测/分析表导出为 CSV/Excel 可读取格式。
- 配置与运行时状态见「八、数据持久化方案」。

### UI 层（各页面）
- **行情全景**：6 个指标卡（最新价/涨跌/最高/最低/成交量/持仓量）+ K 线主图（蜡烛+成交量+均线+十字光标+滚轮缩放）+ 39 品种自选表（板块筛选、双击切主图）。
- **指标分析**：多指标同屏（主图叠加均线/BOLL、副图 MACD/KDJ/RSI），共振/背离/趋势强弱结论卡。
- **AI 预测**：参数卡（品种/周期/回看根数/预测期数）+ 结论卡（方向徽章+置信度条+最新价/预测中枢/支撑/阻力）+ 预测图（历史+预测中枢虚线+阴影置信带）+ 逐期预测表 + AI 文本摘要。
- **市场全景**：涨跌排行、强弱排序、量能暴增/缩量预警、资金净流入/流出、多品种联动。
- **回测验证 / 回测中心**：任意品种/周期历史回测，统计预测准确率、胜率、最大回撤、趋势捕捉率，输出可视化报告；支持策略自进化与 CTP 只读监控。
- **日志预警**：异动预警、预测/分析记录存档、导出报告。

---

## 六、接入实盘行情

数据源通过 `DataFeed` 接口注入，`MarketDataManager` 按 `config/settings.json` 的 `data.source` 选择，**上层（UI / 分析 / 预测 / 回测）零改动**。三种源：

| `data.source` | 数据源 | 说明 |
|---------------|--------|------|
| `sina`（**默认**） | `SinaFeed` | **新浪财经公开期货接口，免密钥、无需期货公司柜台**，只要有外网即可拉取全市场真实日线；覆盖本系统 39 个品种主力连续合约 |
| `synthetic` | `SyntheticFeed` | 统计特征贴近真实期货的合成行情，离线可跑、用于演示与单元测试 |
| `ctp` | `CTPFeed` | 期货公司柜台（vnpy/ctpbee）适配占位，生产环境填入前置地址/账号后接入（仅作只读监控） |

**实盘数据（Sina）关键事实**
- **周期**：日线 `D` 与周线 `W` 为**真实数据**（W 由真实日线重采样）；日内周期（1m/5m/…/4h）免费接口不提供历史分钟线，`MarketDataManager` 自动回退 `SyntheticFeed` 并明确标注为模拟，**绝不冒充实盘**。
- **实时**：免费接口无可靠实时推送；「最新价」取真实日线最后一根（最近交易日收盘）。如需真正 tick 级实时，请切换到 `ctp` 源接入柜台。
- **健壮性**：`MarketDataManager` 启动时做一次轻量探测，若外网不可达自动回退 `synthetic`，状态栏会显示「合成行情(模拟, 实盘获取失败)」，保证任何环境都能启动。
- **缓存**：真实日线按品种缓存到 `data/sina_cache/*.csv`（默认 6 小时新鲜度），重复运行不重复拉取。

切换方式（任选其一）：
- 改 `config/settings.json`：`"data": { "source": "sina" }`（当前默认）；
- 或在代码中 `MarketDataManager(source="sina" | "synthetic" | "ctp")`。

实盘接入验证脚本：

```bash
python examples/sina_demo.py
#  -> 拉取 rb/cu/au/IF/m/T 等真实日线，跑指标+AI预测，输出真实数值
```

> 注意：新浪为公开行情服务，仅供学习与复盘；实盘交易请以期货公司授权数据为准，并遵守相关法规。

---

## 七、数据持久化方案

系统把「持久化」拆成三类数据、三种载体，分别满足**格式清晰 / 读写高效 / 崩溃可恢复**：

| 类别 | 载体 | 文件 | 内容 | 写时机 |
| --- | --- | --- | --- | --- |
| 用户配置 | JSON | `config/settings.json`（默认）+ `data/user_settings.json`（用户覆盖，原子写） | 主题、数据源、默认合约/周期等「很少变」的偏好 | 用户显式操作（如切换主题） |
| 运行时状态 | JSON | `data/session_state.json`（原子写 + .bak 回退） | 窗口几何/最大化、最后停留页、各页当前合约/周期 | 组合框变更 / 窗口缩放 / 页面切换（防抖 600ms） |
| 历史记录 | SQLite | `data/quant_analysis.db`（WAL） | K 线缓存、预测、分析结论、异动预警、系统日志 | 每次分析/预测/日志产生时 |

**异常恢复机制（核心）**
- **原子写**：所有 JSON 落盘均「写 `*.tmp` → 复制旧文件为 `*.bak` → `os.replace`」，磁盘上永不出现半截文件；
- **损坏自愈**：读取时主文件解析失败自动回退 `*.bak`，再不行回退默认值，保证「崩溃/关闭后程序仍能启动并恢复」；
- **版本迁移**：`__version__` 变化时与默认值深合并，补齐缺字段、丢弃未知键；
- **SQLite 崩溃安全**：WAL 日志 + `synchronous=NORMAL` + `busy_timeout=5000`；启动 `integrity_check()` 校验，退出/关闭前 `checkpoint()` 合并 WAL；`prune()` 限制各表容量（日志 3000 / 预测·分析·预警 2000）防止无限膨胀；
- **全局崩溃兜底**：`main()` 安装 `sys.excepthook`，未捕获异常时先 flush 会话状态、写入 `CRASH` 日志并落盘 SQLite，再向上抛出，便于事后复盘。

**启动恢复顺序**：`ConfigManager` 载入主题/数据源 → `MainWindow` 按 `session_state.json` 恢复窗口几何与最大化状态、跳到上次停留页、各页恢复上次合约/周期 → `MarketDataManager` 按配置选择数据源并探测 → `AnalysisStore` 校验完整性并 `maintenance()`。

---

## 八、已知边界与免责

- 本框架**不做自动交易**，下单/撮合/账户相关能力不在范围内（CTP 仅只读监控）；
- 合成行情仅验证逻辑，**不能**作为实盘依据；
- AI 多步预测为概率性研判，远端步长误差随 horizon 放大，置信带已按残差标准差 √h 扩张；
- 所有结果由模型/规则驱动，**不构成投资建议或个股推荐**。

---

## 九、安全架构（公开分发必读）

公开分发的客户端**不含任何上游密钥**，AI 能力由用户在运行时注入：

- **密钥仅内存持有**：`ai/config.py` 的 `AIConfig` 仅在运行时从环境变量读取 API 密钥，绝不写入 `user_settings.json` 等持久化文件。
- **双模式**：
  - **调试模式**（`python main.py`）：密钥可从 UI「AI 设置」输入，或从环境变量 `QV_AGNES_API_KEY` 注入；
  - **打包模式**（`FuturesQuant.exe`）：**强制**仅从环境变量 `QV_AGNES_API_KEY` 注入，启动时清除任何持久化的 `ai.api_key` 字段（`enforce_security_mode(is_frozen())`）。
- **运行时脱敏**：`utils/redact.py` 的 `install_global_redaction()` 在 `main.py` 入口最早调用，对日志/异常中的密钥与敏感参数做全局脱敏。
- **构建门禁**（`build_tools/build_exe.py` + `build_tools/secret_scan.py`）：
  - 源码扫描发现密钥 → `exit 3`；
  - 产物字节扫描发现密钥 → `exit 4`；
  - 凭据文件（如 `config/ctp_settings.json` 含实盘账号密码）被 `futures_qt.spec` 的 `CONFIG_DENY` 拒绝打入产物，复查发现 → `exit 7`；
  - 产物中 `user_settings.json` 含 `api_key` 字段 → `exit 8`；
  - 无 exe 产物 → `exit 5`；distpath 无法腾空 → `exit 6`。

> 诚实边界：公开客户端无真实身份认证，安全目标是**降低密钥泄露后果**而非阻止提取。详见 [`docs/security_architecture.md`](docs/security_architecture.md)。

---

## 十、打包与分发（exe）

桌面端可一键打包成免配置、双击即用的 Windows exe，分发**无需目标机安装 Python**。完整步骤、spec 要点、运行时数据落盘位置、中文字体策略见 **[`docs/packaging.md`](docs/packaging.md)**。

```bash
pip install pyinstaller
python build_tools/build_exe.py     # 产物：dist/FuturesQuant/（含 FuturesQuant.exe + config/）
```

要点：依赖仅 `PyQt6 + numpy + pandas`（AI 预测=原生 numpy，K 线=QPainter，无 torch/matplotlib）；运行时数据统一落到 `<exe 目录>/data/`，只读安装位置自动回退 `%APPDATA%/FuturesQuant/data`；中文显示优先注册内嵌/系统 SimHei 字体。

> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
