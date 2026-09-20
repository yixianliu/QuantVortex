# QuantVortex v4.0 系统性升级实施方案

> 版本基线：`futures_quant.__version__ == "3.1.0"`（2026-09-09）
> 目标版本：`4.0.0`
> 编制时间：2026-09-19
> 定位：面向 AI 编码代理（LLM-Coder）可解析、可执行、可回归验证的工程化任务书。
> 免责：**历史表现不代表未来，不构成任何投资建议，期货交易有杠杆风险**。

---

## 0. 文档结构（AI 消费指引）

```
docs/
├── UPGRADE_PLAN.md      # 本文件：总纲 + 模块级任务书
├── upgrade/tasks.yaml   # 结构化任务清单（机器可读，任务图与依赖）
├── upgrade/modules.json # 模块 schema（接口/依赖/风险）
└── upgrade/competitors.md # 同类产品对标分析
```

**AI 代理消费顺序建议**：
1. 读 `tasks.yaml` 拿任务 DAG（拓扑排序后逐个执行）；
2. 执行任务前读对应 `modules.json#modules.<id>` 拿接口契约；
3. 遇到产品决策点回查 `UPGRADE_PLAN.md#§决策门`；
4. 竞品对标仅在 §UI / §策略 / §AI 章节按需查 `competitors.md`。

---

## 1. 项目当前状态快照（Baseline）

### 1.1 架构与规模
| 维度 | 现状 | 备注 |
|---|---|---|
| 版本 | 3.1.0 | 单一数据源 `futures_quant/__init__.py` |
| 源码 | ~85 个 .py，~15,000 行 | `futures_quant/` 主包 |
| 测试 | 45 个测试文件 | `tests/e2e/` 全 offscreen GUI 回归 |
| UI 框架 | PyQt6 + 自绘 QPainter | 零图表第三方依赖 |
| 数据源 | akshare(主) / sina(实时) / csv(兜底) / CTP(仿真) | 日线真实，日内合成 |
| AI 层 | 纯 numpy LSTM + Ridge + MultiPeriodEnsemble | torch 可选 |
| 风控 | ATR 自适应 / 凯利 / 回撤止损 | 无平今仓/涨跌停扩板 |
| 存储 | SQLite 主 + PostgreSQL 扩展 | 单文件 DB |

### 1.2 关键设计约束（不可破坏）
1. **五层解耦**：data → core/indicator → backtest/strategy → ai → ui，`app/service_locator.py` 做依赖注入。
2. **零未来函数**：所有指标、模型训练、样本生成、标签对齐均以「当前及之前」为准。
3. **密钥零落盘**：`AIConfig` 内存持有，构建门禁 `build_tools/secret_scan.py` 双扫。
4. **离线优先**：AI 未配密钥自动降级本地规则；无 torch 自动降级 numpy 单隐层。
5. **绿便分发**：PyInstaller 单 exe + `_internal/`，`futures_qt.spec` 注入版本资源。

### 1.3 已知短板（诊断结论，来自 `docs/old/规划与路线图/optimization_plan.md`）
- UI：QPainter 逐像素、无硬件加速、无画线工具、无多周期同列。
- 回测：Python `for` 循环热点、无 Polars 加速、无平今仓差异化费率。
- 策略：仅 5+1 种经典模板、无跨期/跨品种/期现套利、无期权。
- AI：仅 LSTM/Ridge/GBM，无 TCN/TS-Transformer/GARCH/PPO。
- 数据：无 Tick/Level2、无主力合约动态识别、无仓单/基差/持仓结构。
- 风控：无单日最大亏损、无保证金风险度实时预警、无涨跌停熔断。

---

## 2. 升级目标（North Star）

**一句话定位**：把 QuantVortex 从「单机期货分析/预测工具」升级为「**本地主权 + 智能自进化 + 多数据融合**的期货智能工作台」。

| 维度 | v3.1 现状 | v4.0 目标 |
|---|---|---|
| 品种覆盖 | 39 品种日线 | 39+ 品种 × 4 周期（D/W/60min/1min）+ Tick |
| 策略数 | 5+1（GA 进化） | 20+（含套利/波动率/CTA 组合） |
| AI 模型 | 3 类（LSTM/Ridge/GBM） | 8+ 类（+TCN/TS-Trans/GARCH/PPO/集成） |
| 风控 | 5 项 | 12 项（+平今仓/扩板/熔断/风险度） |
| UI 页 | 7 页 | 12+ 页（+持仓模拟/组合/信号回放） |
| 报告 | CSV/JSON/HTML | PDF + Excel + PDF(带图表) |
| 数据 | 3 源 | 6 源（+TqSdk、仓单、持仓结构、消息面） |

---

## 3. 模块级任务书

> 每个模块给出：**M<n> = 任务 ID 前缀**；每条任务给出：`id / goal / files / interface / acceptance / risk / dep`。
> AI 代理执行前必须逐条读 `files` 与 `interface`；执行后必须自证 `acceptance`。

### M1 · 界面 UI 优化与重构

**总目标**：从「QPainter 单线程自绘」升级为「**多页面 + 交互画线 + 硬件加速图表 + 现代金融设计语言**」，保持零关键第三方图表依赖的可选原则（默认仍 QPainter，但可选 `pyqtgraph`/`QtCharts` 加速路径）。

| id | goal | files | acceptance |
|---|---|---|---|
| M1.1 | 引入 `ui/chart_engine.py` 图表引擎抽象层，把 `chart_widget.KLineChart` 拆成「渲染后端（Painter/PyQtGraph）+ 数据层 + 交互层」 | `ui/chart_engine.py`（新增）、`ui/chart_widget.py`（瘦身） | `QT_QPA_PLATFORM=offscreen python tests/e2e/test_all_pages.py` 通过；渲染后端可切换 |
| M1.2 | 引入专业设计系统：主背景 `#1e1e2e`、文本 `#dcdcdc`、上涨 `#ff4757`、下跌 `#2ed573`，统一 `widgets.PALETTE` | `ui/widgets.py`、`ui/main_window.py` | 深/浅主题切一次即全量刷新，`test_responsive_layout.py` 绿 |
| M1.3 | 新增交互画线工具：水平/垂直线、斐波那契回撤、趋势线、矩形、文本标注，支持云持久化到 `session_state.json` | `ui/draw_tools.py`（新增） | 保存→重启后画线还原；`test_draw_persistence.py` 绿 |
| M1.4 | 多周期同列（4 图并列，Ctrl+滚轮联动）+ 多合约对比（同图叠加价格归一化） | `ui/multi_period_widget.py`（新增） | 4 图同步缩放/十字光标对齐；`test_multi_period.py` 绿 |
| M1.5 | 新增「持仓模拟」页：模拟账户资金、保证金占用率、风险度仪表盘（>80% 红色告警） | `ui/paper_trading_page.py`（新增）、`broker/paper.py` 扩展 | 风险度实时刷新；`test_paper_trading.py` 绿 |
| M1.6 | 报告导出升级：PDF（`reportlab` 或 Qt 内置）+ Excel（`openpyxl`，含资金曲线图） | `app/report_service.py`（新增） | 一次导出 4 类文件；`test_report_export.py` 绿 |

**决策门 D1.1**：图表后端默认 `Painter`（保证打包轻）；用户可选 `pyqtgraph` 走硬件加速。若选加速则 `pyqtgraph` 进 `requirements-optional.txt`。

**风险**：QPainter 是既有测试护栏的核心（`test_all_pages`/`test_perf_chart_ux` 依赖），M1.1 必须先兼容旧 `KLineChart` API。

---

### M2 · 核心算法改进

**总目标**：核心指标/撮合/绩效三块做到「性能 3–5x、规则严谨、可单元测试」，全面杜绝未来函数。

| id | goal | files | acceptance |
|---|---|---|---|
| M2.1 | 用 TA-Lib 或 `numba.njit` 重写 20+ 指标，缓存键 `(symbol, period, indicator, params, hash(close[:n]))`，LRU 1000 | `indicators/tech.py`、`indicators/cache.py` | 单指标计算 <5ms（1000 根）；`test_indicator_forecast.py` 绿；新增 `test_indicator_cache.py` |
| M2.2 | 补齐标准指标：DMI(ADX)、SAR、CCI、OBV、ATR-TRIX、VWAP、历史波动率 HV、GARCH(1,1)（可选 `arch`） | `indicators/tech.py` | 与 Wikipedia/官方公式逐值对拍；`test_indicator_accuracy.py` 绿 |
| M2.3 | 撮合引擎差异化：开仓/平昨/平今三种费率 + 比例滑点 + 波动率自适应滑点（`slip = k * ATR / price`）+ 涨跌停扩板识别 | `broker/backtest_broker.py` | 平今费×2、平昨费×1、开仓×1；涨跌停日禁止反向单；`test_broker_rules.py` 绿 |
| M2.4 | 保证金动态：按 `contract_specs.margin_rate × price × multiplier`，逐日盯市，风险度 = 占用/权益 | `core/portfolio.py`、`data/contract_specs.py` | 权益变动后风险度实时算；风险度>1.0 触发强平信号；`test_margin_calc.py` 绿 |
| M2.5 | 绩效指标 Schema 扩展：Calmar、Sortino、VaR(95)、CVaR、最大连续盈利/亏损次数、月度收益热力图 | `core/metric_schema.py` | 全指标可从 `equity_curve` 一函数算出；`test_metric_schema.py` 绿 |
| M2.6 | 向量化回测路径（`Backtester.vectorized()`）与事件驱动路径并行：小样本走事件驱动（正确性），大数据走向量化（性能），结果一致 | `backtest/backtester.py` | 同一策略两条路径 metrics 差异 <0.5%；`test_backtest_consistency.py` 绿 |

**决策门 D2.1**：`arch`（GARCH）与 `TA-Lib` 均放 optional；缺失时回退纯 numpy 实现。
**防未来函数**：所有 `indicator(n, i)` 计算中，参数 i 只能访问 `close[:i]`；单元测试必须覆盖 `i=window` 与 `i=window-1` 两个边界。

---

### M3 · 业务逻辑增强

**总目标**：契约数据、合约生命周期、事件总线三块补齐「期货规则严谨性」。

| id | goal | files | acceptance |
|---|---|---|---|
| M3.1 | 主力合约动态识别：按成交量 + 持仓量综合权重（`0.4 * vol_rank + 0.6 * oi_rank`），输出 `主力映射表`（date→contract） | `data/dominant.py`（新增） | 与 akshare 官方主力表逐日对齐率 >95%；`test_dominant_contract.py` 绿 |
| M3.2 | 连续合约拼接：三种复权模式（无复权/后复权/比例复权），支持「跳空修正」 | `data/continuous.py`（新增） | 拼接后无跳空；`test_continuous_join.py` 绿 |
| M3.3 | 移仓换月成本模拟：按交割日 T-7 自动换月，价差 × 保证金 × 手续费计入回测 | `backtest/backtester.py`、`data/contract_specs.py` | 主连回测含移仓成本；`test_roll_cost.py` 绿 |
| M3.4 | 涨跌停扩板规则：正常 4%、扩板第 1 天 6%、第 2 天 8%、第 3 天封停，日限仓自动更新 | `data/contract_specs.py`、`broker/backtest_broker.py` | 扩板日正确拒绝反向单；`test_price_limit.py` 绿 |
| M3.5 | 事件总线（替代 `linkage_bus`）：`events.publish("backtest.completed", payload)`；预测↔回测↔UI 全部通过订阅 | `core/events.py`（新增） | 消除 `ai/linkage_bus.py`；`test_events.py` 绿 |
| M3.6 | 期货时段识别：夜盘（21:00–02:30）跨日归属当日交易日；节假日表 `contract_specs.trading_calendar` 静态注入 | `data/trading_calendar.py`（新增） | 21:00 那根归当日；跨年/春节正确剔除；`test_trading_calendar.py` 绿 |

**决策门 D3.1**：主力合约识别优先 akshare 官方 `futures_main_sina`；备用自算权重。

---

### M4 · 策略系统升级

**总目标**：从 5+1 种扩展至 20+，覆盖 CTA 趋势 / 统计套利 / 日内短线 / 波动率 四大品类。

| id | goal | files | acceptance |
|---|---|---|---|
| M4.1 | CTA 趋势扩充：Dual Thrust、Keltner、Ichimoku、Trailing-ATR、Vortix；均基于 `StrategyBase` | `strategy/ctA/*.py`（新增子包） | 5 策略回测在 rb/au/i/IF 上夏普 >0.6；`test_strategies_cta.py` 绿 |
| M4.2 | 统计套利：跨期（近月/远月价差 Z-score）、跨品种（如 RB-I 螺纹铁矿）、期现套利（基差 = 期货-现货，现货来自 sina 或 akshare） | `strategy/arbitrage/*.py`（新增） | 协整检验 coint.pvalues <0.05；套利区间 [σ_lo, σ_hi] 触发；`test_arbitrage.py` 绿 |
| M4.3 | 日内短线：开盘突破（30min）、成交量异动（放量 2σ）、改良网格（动态间距 = ATR×k） | `strategy/intraday/*.py`（新增） | 日内信号严格收盘产生、次日开盘撮合；`test_intraday.py` 绿 |
| M4.4 | 波动率交易：Bollinger-带内做空/带外做多、HV 分位突破、GARCH 波动率择时 | `strategy/volatility/*.py`（新增） | HV 分位与 GARCH 输出一致；`test_volatility.py` 绿 |
| M4.5 | `strategy/combo.py`：多策略组合（权重可优化），子策略共享风险预算 | `strategy/combo.py`（新增） | 组合夏普 > max(单策略夏普)；`test_combo.py` 绿 |
| M4.6 | 遗传算法升级：从 8 因子扩展至 20+ 因子，加入树结构基因（多因子组合）；适应度引入 **Calmar + 稳定性系数（跨品种）** | `strategy/auto_evolve.py` | 200 代进化收敛；输出盈利策略在留一岁验证集夏普 >0.5；`test_auto_evolve_engine.py` 扩展绿 |

**决策门 D4.1**：`scipy.stats.pearsonr`/`adfuller`/`coint` 依赖 `statsmodels`（可选，缺失则禁用套利类）。

---

### M5 · AI 模型辅助功能集成

**总目标**：模型矩阵从 3 类扩展至 8 类，全部遵守 Walk-Forward 与滚动 z-score；预测输出含点值 + 95% 置信带 + 特征贡献度。

| id | goal | files | acceptance |
|---|---|---|---|
| M5.1 | 特征工程重构：`features.build_features(df)` 输出纯 2D numpy，**滚动 z-score**（window=120，仅用当前及之前），标签 = 未来 N 根方向 | `ai/features.py` | 与全量归一化差异显著；`test_features_no_lookahead.py` 单测通过（对比 t 时点前后特征一致性） |
| M5.2 | 新增 XGBoost / LightGBM 集成：`ai/boosting.py`（可选依赖，缺失降级 numpy GBDT 玩具实现） | `ai/boosting.py`（新增） | 与 Ridge 对比验证集 MAE 降低 >10%；`test_boosting.py` 绿 |
| M5.3 | TCN（时间卷积网络，纯 numpy）：1D 因果卷积 + 膨胀卷积堆叠，`ai/tcn.py` | `ai/tcn.py`（新增） | 单序列 100 根样本训练 <1s；预测 MAE 与 LSTM 相当；`test_tcn.py` 绿 |
| M5.4 | TS-Transformer（可选 torch）：多头自注意力 + 位置编码 + 时间戳嵌入 | `ai/ts_transformer.py`（新增） | 有 torch 训练；无 torch 自动跳过并 log warn；`test_ts_transformer.py`（`skipif no torch`） |
| M5.5 | GARCH(1,1) 波动率：`ai/garch.py`，输出条件波动率 + 置信带（`forecast ± z * sigma_t`） | `ai/garch.py`（新增，用 `arch` 可选） | σ_t 与实证波动率相关 >0.7；`test_garch.py` 绿 |
| M5.6 | PPO 强化学习（可选 torch）：`ai/ppo.py`，状态 = 特征向量，动作 = {-2,-1,0,+1,+2}（仓位） | `ai/ppo.py`（新增） | 训练 10k steps 后夏普 > 随机基线；`test_ppo.py`（`skipif no torch`） |
| M5.7 | Walk-Forward 滚动验证：`ai/validation.py`，窗口 252 天滚动，验证 63 天，扩展步 63 天，禁随机划分 | `ai/validation.py`（新增） | 输出每折 metrics + OOS 汇总；`test_walk_forward.py` 绿 |
| M5.8 | 特征贡献度：`ai/attribution.py`（基于 `shap` 可选 or 朴素重要性），输出前 10 特征 bar chart 到预测页 | `ai/attribution.py`（新增） | 特征重要性排序稳定；`test_attribution.py` 绿 |

**决策门 D5.1**：`torch` / `arch` / `shap` 均为可选；缺失时全部自动降级到 numpy 版本，UI 上明确标注「轻量模式」。
**防未来函数硬约束**：
- `features.build_features(X, i)` 只能读 `X[:i]`；
- 训练集标签 `y[t] = sign(close[t+N] - close[t])` 使用 `t+N` 未来收益作为监督，训练时**只在 t 处 fit**，预测时**仅当 t 的 y 已知**（即历史），未来样本的 y 通过滚动生成；
- 单元测试 `test_features_no_lookahead.py` 用「截断到 i 的 df」两次调用特征函数应完全相同。

---

### M6 · 数据分析与预测功能开发

**总目标**：把「预测」从「单品种单模型」升级为「**多品种横截面 + 多周期 + 概率化 + 校准闭环**」。

| id | goal | files | acceptance |
|---|---|---|---|
| M6.1 | 横截面筛选：全市场 39 品种同时算 `趋势分 / 波动分 / 动量分 / 反转分`，输出热力图 + 排序 | `ai/cross_section.py`（新增） | 每次运行 <2s；`test_cross_section.py` 绿 |
| M6.2 | 板块联动：黑色系/有色/贵金属/能化/农产品/金融 6 大板块的板块因子（等权平均收益）+ 板块内 rank | `analysis/sector.py`（新增） | 板块因子与子成分相关 >0.6；`test_sector.py` 绿 |
| M6.3 | 多因子打分卡：把技术面、量能、AI 概率、板块因子加权成 0–100 综合分 | `analysis/scorecard.py`（新增） | 分数可复现；`test_scorecard.py` 绿 |
| M6.4 | 预测回放器（`calibration_replay` 升级）：支持多模型对比（Ridge/LSTM/TCN/GBM）在同一回放集上跑 MAE/命中率 | `ai/calibration_replay.py` | 输出对比表 CSV；`test_calibration_replay.py` 扩展绿 |
| M6.5 | 蒙特卡洛风险：对历史收益做 bootstrap 抽样 1000 次，输出未来 N 日权益分布 P5/P50/P95 | `risk/monte_carlo.py`（新增） | P5 < 实际值 < P95；`test_monte_carlo.py` 绿 |
| M6.6 | 归因分析：Brinson-style 品种归因（配置/选择/交互）+ 策略归因（趋势 vs 反转） | `analysis/attribution.py`（新增） | 归因之和 ≈ 总收益（±0.1%）；`test_attribution.py` 绿 |

---

### M7 · 系统自我进化机制构建

**总目标**：把 GA 单策略进化升级为**「策略+模型+风控」三轨协同进化**，且每次进化产出可回溯报告。

| id | goal | files | acceptance |
|---|---|---|---|
| M7.1 | 进化控制器：`strategy/evolver.py`，把现有 `auto_evolve` 抽为「策略基因进化」；新增「模型超参进化」与「风控参数进化」 | `strategy/evolver.py`（新增，抽象 `Genome`） | 三轨可独立/联合进化；`test_evolver.py` 绿 |
| M7.2 | 适应度函数升级：`fitness = 0.4*sharpe + 0.3*calmar - 0.2*max_dd - 0.1*drawdown_duration` + 跨品种稳定性惩罚 | `strategy/evolver.py` | 与旧适应度对比：跨品种 OOS 夏普 >0.5；`test_fitness.py` 绿 |
| M7.3 | 进化档案：每代基因 + metrics + 收敛曲线 落 `data/evolution/<run_id>.json`；支持回看历史进化 | `storage/evolution_store.py`（新增） | 100 次进化数据 <10MB；`test_evolution_store.py` 绿 |
| M7.4 | 用户反馈闭环：`feedback.py` 扩展，实盘/回测交易结果写回 → 触发每周再训练（可选定时任务） | `ai/feedback.py`、`app/scheduler.py`（新增） | 触发一次手动反馈重训；`test_feedback_loop.py` 绿 |
| M7.5 | 模型漂移检测：监控过去 60 天预测命中率 vs 训练期命中率，漂移 >20% 触发重训警告 | `ai/drift.py`（新增） | 模拟漂移数据集触发告警；`test_drift.py` 绿 |
| M7.6 | 知识蒸馏：把最强策略压缩为规则集，导出到 `data/auto_strategies/rules.json`，UI 可读 | `strategy/distill.py`（新增） | 蒸馏后策略在回测中夏普下降 <10%；`test_distill.py` 绿 |

---

### M8 · 期货市场信息整合与应用

**总目标**：把消息面、持仓、基差、政策四大外部信号纳入系统，作为**辅助研判因子**（不作为单一决策依据）。

| id | goal | files | acceptance |
|---|---|---|---|
| M8.1 | 消息聚合器：`news_feed.py` 扩展，接入财联社/东方财富/同花顺/交易所公告 4 源，去重 + 情绪打分（TF-IDF + 词典） | `ai/news_feed.py` | 30 天数据 <1s 拉取；情绪分与人工标注相关 >0.5；`test_news_feed.py` 绿 |
| M8.2 | 持仓结构：交易所每日持仓排名 Top20，计算 **多单集中度 / 空单集中度 / 多空比** | `data/position_rank.py`（新增） | 与上期所官网数据一致；`test_position_rank.py` 绿 |
| M8.3 | 基差与仓单：期货价 - 现货价 = 基差；仓单数变化率 → 供给因子 | `data/basis.py`、`data/warrant.py`（新增） | 基差数据每日更新；`test_basis.py` 绿 |
| M8.4 | 宏观日历：CPI/PMI/美联储议息/国内政策发布日历，事件发生前后 3 日波动率放大标记 | `data/macro_calendar.py`（新增） | 日历与官方发布日一致；`test_macro_calendar.py` 绿 |
| M8.5 | 综合信号面板：把 M8.1–M8.4 因子汇入 `analysis/scorecard.py`，作为 0–100 分的**消息面/持仓/基差/事件**四子项 | `analysis/scorecard.py` 扩展 | 因子缺失时降级为 50 中性；`test_scorecard_full.py` 绿 |
| M8.6 | 政策事件预警：`alerts/engine.py` 扩展规则引擎，支持「事件 → 阈值 → 通知」链路 | `alerts/engine.py` | 事件触发一次推送；`test_alerts.py` 扩展绿 |

---

## 4. 同类产品对标（详见 `competitors.md`）

| 产品 | 定位 | 可借鉴点 |
|---|---|---|
| 文华财经 WH6/WT8 | 国内期货头部交易软件 | 云端条件单、主连链回测、39 个头寸管理函数、算法分批下单（TWAP/冰山/幽灵） |
| VeighNa（vnpy） | Python 开源量化框架 | 事件驱动架构、多 Gateway 抽象、CTA/套利/期权策略 App、DataRecorder、RiskManager |
| Backtrader | Python 回测库 | 0-based 索引防未来函数、事件 + 向量化双模、122 指标、Sizers、Analyzers、Plotly 报告 |
| QLib | 微软 AI 量化平台 | 数据/工作流/接口三层解耦、qrun 一键工作流、公式化 Alpha、RD-Agent LLM 自主进化 |
| TradingView | Web 金融图表 | Pine Script、Volume Profile/Market Profile、12 项 alert、AI 洞察、社交分享 |

**QuantVortex 差异化定位**（避免正面竞争）：
- ✅ 单机/离线（对比 TV/Qlib 云依赖）；
- ✅ 中文期货规则严谨（对比 Backtrader 通用性但弱国内规则）；
- ✅ AI + 策略自进化同框（对比 WH6 需付费、Qlib 学习曲线陡）；
- ⚠️ 短板：无社交/无实盘交易/无 Tick 高频。

---

## 5. 执行路线图（4 个 Phase）

| Phase | 覆盖任务 | 里程碑 | 关键护栏 |
|---|---|---|---|
| **P1 基础加固** | M2.1–M2.6、M3.1–M3.6 | v3.2：算法严谨、合约规则合规 | 全部单测绿；无未来函数 |
| **P2 策略与AI** | M4.1–M4.6、M5.1–M5.8 | v3.3：策略 20+、模型 8 类 | 无 torch/optional 时降级路径全绿 |
| **P3 数据与AI融合** | M6.1–M6.6、M8.1–M8.6 | v3.4：横截面 + 消息面 | 数据源失败自动降级 |
| **P4 UI 与自进化** | M1.1–M1.6、M7.1–M7.6 | v4.0：完整工作台 | 全页面 e2e 绿 + 打包无密钥 |

**每 Phase 完成标准**：
- `python -m py_compile` 全包绿；
- `QT_QPA_PLATFORM=offscreen python tests/e2e/test_all_pages.py` 绿；
- `python build_tools/secret_scan.py` 绿（无密钥泄露）；
- `tests/e2e/` 覆盖新增模块，回归不劣化。

---

## 6. 决策门（Decision Gates）

| Gate | 问题 | 推荐 | 备选 |
|---|---|---|---|
| D1.1 | 图表后端 | 默认 QPainter，可选 pyqtgraph | 直接 pyqtgraph（重，弃用） |
| D2.1 | TA-Lib/arch | 可选，缺失降级 numpy | 强制依赖（重） |
| D3.1 | 主力合约识别 | akshare 官方优先，自算兜底 | 自算权重（延迟高） |
| D4.1 | statsmodels | 可选 | 自实现（工作量翻倍） |
| D5.1 | torch/shap | 可选，UI 标注「轻量模式」 | 强制（体积 +200MB） |
| D7.1 | 进化触发 | 手动 + 反馈闭环触发 | 定时（复杂度高） |
| D8.1 | 新闻源 | 财联社+东财为主，同花顺兜底 | 交易所公告（数据量小） |

---

## 7. 强制护栏（Guardrails，不可破坏）

1. **未来函数禁令**：所有指标、特征、样本、模型训练只能读 `t` 及之前；单元测试 `test_no_lookahead.py` 强制覆盖。
2. **风险提示语**：所有回测/AI 结果 UI 顶部固定提示语「历史表现不代表未来，不构成任何投资建议，期货交易有杠杆风险」。
3. **密钥零落盘**：任何新增第三方 API 走 `AIConfig` 内存持有；构建门禁扫描。
4. **无明确买卖点位**：AI 输出仅给概率 + 区间 + 置信度，不给出「买入价 X」「卖出价 Y」。
5. **离线优先**：任何联网功能失败必须降级为本地或空态，不阻塞 UI。
6. **PEP 8 + 类型注解**：所有新增 .py 文件加 docstring，函数签名带类型注解。
7. **不承诺收益**：任何文档/UI 禁用「稳赚」「保证」「必涨」等词。

---

## 8. 附录 A · 文件结构变更总览

```
futures_quant/
├── ai/
│   ├── boosting.py         # M5.2
│   ├── tcn.py              # M5.3
│   ├── ts_transformer.py   # M5.4
│   ├── garch.py            # M5.5
│   ├── ppo.py              # M5.6
│   ├── validation.py       # M5.7
│   ├── attribution.py      # M5.8
│   ├── cross_section.py    # M6.1
│   ├── drift.py            # M7.5
│   └── ...
├── analysis/
│   ├── sector.py           # M6.2
│   ├── scorecard.py        # M6.3, M8.5
│   └── attribution.py      # M6.6
├── data/
│   ├── dominant.py         # M3.1
│   ├── continuous.py       # M3.2
│   ├── trading_calendar.py # M3.6
│   ├── position_rank.py    # M8.2
│   ├── basis.py            # M8.3
│   ├── warrant.py          # M8.3
│   └── macro_calendar.py   # M8.4
├── core/
│   └── events.py           # M3.5
├── risk/
│   └── monte_carlo.py      # M6.5
├── storage/
│   └── evolution_store.py  # M7.3
├── strategy/
│   ├── cta/                # M4.1
│   ├── arbitrage/          # M4.2
│   ├── intraday/           # M4.3
│   ├── volatility/         # M4.4
│   ├── combo.py            # M4.5
│   ├── evolver.py          # M7.1
│   └── distill.py          # M7.6
├── app/
│   ├── report_service.py   # M1.6
│   └── scheduler.py        # M7.4
└── ui/
    ├── chart_engine.py     # M1.1
    ├── draw_tools.py       # M1.3
    ├── multi_period_widget.py  # M1.4
    ├── paper_trading_page.py   # M1.5
    └── ...
```

---

## 9. 附录 B · AI 代理执行协议

**Agent 执行前必读**：
1. 读 `docs/upgrade/tasks.yaml` 拿当前任务；
2. 执行前 `git status` 确认干净；
3. 生成/修改代码前先读 `modules.json#modules.<id>`；
4. 生成代码后必须：
   - `python -m py_compile <文件>`；
   - 跑对应 `tests/e2e/test_*.py`；
   - 若新增护栏测试则同步更新 `UPGRADE_PLAN.md#§7`。
5. 完成任务后写 commit：`M<N>.<M>: <goal 摘要>`。

**Agent 执行禁止**：
- 禁用 `git push --force`；
- 禁用 `rm -rf`；
- 禁在 `.gitignore` 之外硬编码任何密钥；
- 禁用 `eval()`/`exec()` 处理外部数据；
- 禁用 SQL 字符串拼接（必须参数化）；
- 禁在无用户确认下改动生产配置。

---

> **文档版本**：v1.0（2026-09-19）
> **维护者**：AI 代理 / 项目维护者
> **下次修订触发**：任一模块任务完成、任一决策门关闭、任一竞品出现重大更新。
