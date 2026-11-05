# Phase 7 全量排查报告（只读）

> 项目：`d:\PythonProject\QuantVortex` · v5.2.15（2026-10-07）
> 排查日期：2026-11-04
> 方式：只读静态审查 + 轻量探针（cProfile、import/构造计时、Sina 单合约探针、DB 只读统计）
> 边界：**未改任何代码 / .gitignore / 数据文件 / 数据库；未执行任何 git 写操作；未删除文件；未跑全量测试与 e2e**。
> 既有诊断：`docs/diagnosis/phase0~phase6` 已解决的问题不再重复；本报告只记录仍然存在的缺口、未验证项与新发现。

**证据等级约定**

| 标记 | 含义 |
|---|---|
| 实测 | 本轮探针或命令实际跑出的数字，附录写测量条件 |
| 静态确认 | 通过代码路径 / grep / DB 只读查询确认，未运行动态实验 |
| 待验证 | 有合理推测但缺证据，第 8 节给验证方法 |

---

## 0. 结论先行

### 0.1 最该先做的 3 件事

1. **P0：结果可追溯 + 历史库治理（D 节）**
   `evolve_history` 只存指标与曲线，不存数据指纹、随机种子、参数快照、数据源；同一份历史无法证明“用什么数据、什么参数、什么种子”跑出来的。同时库已 204.84MB、1001 行中 15 行全空、`prune()` 保留 1000 行却不 `VACUUM`。这件事改动小、直接恢复“结果可信”，应排第一。
   证据：[backtest_store.py:58-71](file:///d:/PythonProject/QuantVortex/futures_quant/storage/backtest_store.py#L58-L71)、[backtest_store.py:196-220](file:///d:/PythonProject/QuantVortex/futures_quant/storage/backtest_store.py#L196-L220)、[backtest_store.py:309-322](file:///d:/PythonProject/QuantVortex/futures_quant/storage/backtest_store.py#L309-L322)。

2. **P0：把主力合约/换月真正接进回测（B 节）**
   现有回测从未收到 `roll_schedule`，默认按“每自然月首个交易日”近似换月，只收手续费下限；`dominant.py` / `continuous.py` 无生产调用方。数据可行性已实测：新浪单月合约可取（rb2701 192 根、rb2501 242 根、rb2001 243 根、TA2701 191 根、i2501 241 根）。先做“数据链 → 主力识别 → roll_schedule → 回测成本”只读纵切，暂不做独立 UI。
   证据：[backtester.py:169-182](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L169-L182)、[backtester.py:259-280](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L259-L280)、[backtester.py:328-335](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L328-L335)、[dominant.py:11-54](file:///d:/PythonProject/QuantVortex/futures_quant/data/dominant.py#L11-L54)。

3. **P1：GUI 诚实性与主线压缩（A 节）**
   AI 指标研判在未预测时仍可点、会发“无上下文”的泛化提示词；多处 `except Exception: pass` 让失败静默；`数据管理` 页没有行情下载按钮但主窗口副标题写着“行情下载”；`独立回测` 只有 6 个 KPI、无导出；两个回测页职责重叠。这些都是“点得到但不可信/没反馈”，修复成本低于新增功能。
   证据：[predict_ops_page.py:1241-1250](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L1241-L1250)、[predict_ops_page.py:1319-1345](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L1319-L1345)、[predict_ops_page.py:886-905](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L886-L905)、[main_window.py:86-94](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L86-L94)、[data_page.py:192-229](file:///d:/PythonProject/QuantVortex/futures_quant/ui/data_page.py#L192-L229)、[simple_backtest_page.py:229-231](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L229-L231)。

### 0.2 最不值得做的 2 件事

1. **继续给 GA 加算力（更大种群 / 更多代 / 并行 / GPU）**
   已有结论：方向模型样本外不显著高于随机基准，日线免费数据不存在可交易的非方向性边际。当前单基因热缓存 1.35s、单代约 13.5s，瓶颈不在“算得慢”，而在“算出来的东西没有可验证的样本外优势”。在没有锁箱 OOS 与交易成本证据前，扩大搜索只会更快地过拟合。
   证据：[auto_evolve.py:1205-1207](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1205-L1207)、[auto_evolve.py:1465-1489](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1465-L1489)、本轮实测 1.35s/基因。

2. **复活 `pages.py` 旧页面 / `screening_page` / `paper_trading_page`，或自建免费分钟数据管线**
   这些页面无生产引用（旧 `BacktestPage` 也被测试注释明确标为“已死类”）；免费新浪接口不提供历史分钟线，强行做只能用合成数据冒充，违反项目“不得静默降级”的原则。清理与归档比复活更有价值。
   证据：[test_datagrid_rollout.py:85](file:///d:/PythonProject/QuantVortex/tests/e2e/test_datagrid_rollout.py#L85)、[sina_feed.py:14-23](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L14-L23)、[main_window.py:68-76](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L68-L76)。

### 0.3 优先级速览

| 级别 | 数量 | 内容 |
|---|---|---|
| P0 | 3 | 可追溯性、历史库治理、主力换月接线 |
| P1 | 5 | 进化缓存/适应度一致性、GUI 静默失败、主线与导出、热点性能、视觉 token |
| P2 | 4 | 死代码归档、主力合约独立 UI、TqSdk 实时、规模化流式/落库 |

---

## 1. 模块地图

### 1.1 分层与职责

| 层 | 关键文件 | 现状 |
|---|---|---|
| 入口/UI | [ui/main_window.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py)（1618 行）、7 个 NAV 页面、对话框 | 7 页可达；另有约 2.0k 行旧页面不可达 |
| 数据 | [data/market_data.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py)（827 行）、`sina_feed` / `akshare_feed` / `tqsdk_feed` / `synthetic` / `csv_feed`、`contract_specs`、`price_limit`、`dominant`、`continuous` | 日线可信化已完成；单月合约可取；主力/连续未接线 |
| 核心 | `core/engine.py`、`core/portfolio.py`、`core/indicators.py`、`core/metric_schema.py`、`core/events.py` | 事件驱动撮合；`atr_last` 每根全窗口重算 |
| 风控 | `risk/risk_manager.py`、`risk/position_sizing.py` | 每 bar 风控开销约 10.4% |
| 策略 | `strategy/trend_following|breakout|grid|martingale|mean_reversion`、`arbitrage`、`cta`、`intraday`、`volatility`、`auto_evolve`、`validate` | 进化引擎 2070 行；OOS 复用同一尾段 |
| 回测 | [backtest/backtester.py](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py)（645 行）、`roll_cost.py` | 支持 `roll_schedule`，但无调用方传入 |
| 存储 | `storage/backtest_store.py`、`analysis_store.py`、`evolution_store.py`、`sqlite_backend.py`、`postgres_backend.py` | 历史表无指纹/种子；205MB 未 VACUUM |
| AI | `ai/predictor.py`、`llm_client.py`、`features.py`、`lstm/tcn/transformer`、`calibration_replay`、`linkage_bus` | 预测链路可用；AI 指标研判可无上下文调用 |
| 应用 | `app/backtest_service.py`、`scheduler.py`、`report_service.py` | 统一回测构造入口；定时器不触发进化 |
| 脚本 | `scripts/acceptance.py`、`perf_probe.py`、`validate_qss_mapping.py` | 验收与性能基线入口 |

### 1.2 实际接线（live vs dead）

```text
MainWindow
├─ NAV[0] 行情全景  → MarketOverviewPage      live
├─ NAV[1] 预测操作  → PredictOpsPage          live
├─ NAV[2] 回测中心  → BacktestCenterPage      live（backtest_page.py:1426）
├─ NAV[3] 独立回测  → SimpleBacktestPage      live
├─ NAV[4] 实盘监控  → CTPMonitorPage          live（无账号时不可用）
├─ NAV[5] 日志预警  → LogPage (pages.py:2838) live
└─ NAV[6] 数据管理  → DataPage                live（无行情下载）

未接线：
- backtest_page.py:246 BacktestPage       测试注释明确“已死类”
- pages.py MarketPage / IndicatorPage / PredictPage / PanoramaPage / ValidatePage
- screening_page.py ScreeningPage（1329 行，不在 NAV）
- paper_trading_page.py PaperTradingPage（197 行，不在 NAV）
- data/continuous.py join_continuous（均价拼接，非真实连续合约）
- data/dominant.py 仅被单测/e2e 引用，生产零调用
```

### 1.3 关键数据事实

- 新浪日线：主力连续 `rb0` 实测 4274 根、2009-03-27 至 2026-11-04，耗时 3.51s；单月合约 0.15~0.21s。
- 新浪/akshare 免费源**无历史分钟线**；`SinaFeed.get_history` 对分钟周期返回 None，由 `MarketDataManager` 回退合成并标注 `is_synthetic`。
- TqSdk 适配器支持 `D / 1 / 5 / 15 / 30m`、`KQ.m@SHFE.rb` 与显式月份合约，但真实连通性未验证（无账号）。
- 品种乘数/涨跌停/保证金已按精确匹配落地（`contract_specs`、`price_limit`、`find_universe_row`）。

---

## 2. A. GUI 全量盘点

### A-1 入口清单

| 入口 | 文件:行 | 可达 | 依赖数据源 | 需等待网络 | 反馈/备注 |
|---|---|---|---|---|---|
| 行情全景 | [main_window.py:68-76](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L68-L76) → [market_overview_page.py:90](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L90) | 是 | `mdm.feed`（Sina/AkShare/synthetic）+ 新闻 | 是（首次/刷新逐品种；实测 rb0 3.51s） | 有来源水印；刷新异步 |
| 预测操作 | [predict_ops_page.py:212](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L212) | 是 | `mdm.feed` + 本地模型 + 可选 LLM | 预测本地；AI 按钮联网 | 主按钮“开始预测”；AI 指标无前置校验 |
| 回测中心 | [backtest_page.py:1426](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L1426) | 是 | `mdm.feed` | 首次取数；进化本地 | 页面显示即自动进化，无需点击 |
| 独立回测 | [simple_backtest_page.py:107](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L107) | 是 | `mdm.feed` | 首次取数 | 仅 6 KPI，无导出 |
| 实盘监控 | [ctp_monitor_page.py:34](file:///d:/PythonProject/QuantVortex/futures_quant/ui/ctp_monitor_page.py#L34) | 是 | CTP 柜台 | 是（需账号/前置） | 未连接时下单类入口被禁用 |
| 日志预警 | [pages.py:2838](file:///d:/PythonProject/QuantVortex/futures_quant/ui/pages.py#L2838) | 是 | 本地日志/DB | 否 | 可用 |
| 数据管理 | [data_page.py:40](file:///d:/PythonProject/QuantVortex/futures_quant/ui/data_page.py#L40) | 是 | SQLite；可选 MySQL | 仅 MySQL | **无行情下载/更新按钮** |
| 视图/切换主题 | [main_window.py:683-686](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L683-L686) | 是 | 本地 config | 否 | 有快捷键 Ctrl+T |
| 视图/字号缩放 | [main_window.py:688-696](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L688-L696) | 是 | 本地 config | 否 | 90/100/110/125% |
| 数据/重连数据源 | [main_window.py:699-700](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L699-L700) → [1308-1324](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L1308-L1324) | 是 | `mdm` | 是 | Worker 线程，15s 超时 |
| 数据/数据导出… | [main_window.py:702-703](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L702-L703) | 是 | 本地 DB | 否 | **只跳转数据页，不直接导出** |
| 数据/备份恢复… | [main_window.py:704-705](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L704-L705) | 是 | 本地 DB | 否 | 同上，只跳转 |
| AI/模型配置… | [main_window.py:707-709](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L707-L709) → [ai_settings_dialog.py:152](file:///d:/PythonProject/QuantVortex/futures_quant/ui/ai_settings_dialog.py#L152) | 是 | LLM API | 测试连接时是 | 有应用/测试 |
| AI/API状态 | [main_window.py:710-711](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L710-L711) | 是 | 本地状态 | 否 | 只读 |
| 帮助/快捷键… | [main_window.py:714-716](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L714-L716) | 是 | 本地 | 否 | Ctrl+/ |
| 帮助/系统诊断… | [main_window.py:719-721](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L719-L721) → [diagnostics_dialog.py:347](file:///d:/PythonProject/QuantVortex/futures_quant/ui/diagnostics_dialog.py#L347) | 是 | 本地 | 否 | Ctrl+Shift+D |
| 帮助/关于 | [main_window.py:723-724](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L723-L724) → [about_page.py:479](file:///d:/PythonProject/QuantVortex/futures_quant/ui/about_page.py#L479) | 是 | 本地 | 否 | — |
| 命令面板（导出/备份） | [main_window.py:607-608](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L607-L608) | 是 | 本地 DB | 否 | 同样只跳转 |
| 行情行双击→预测 | [market_overview_page.py:2177-2180](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L2177-L2180) → [main_window.py:843-863](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L843-L863) | 是 | `mdm` | 否（已加载） | 自动带品种/周期跳预测 |
| 预测→回测此策略 | [predict_ops_page.py:886-905](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L886-L905) | 是 | 回测库 | 否 | 失败静默（见 A-2） |
| 旧 `BacktestPage` | [backtest_page.py:246](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L246) | **否** | — | — | 测试注释明确“已死类” |
| 旧 Market/Indicator/Predict/Panorama/Validate | [pages.py:609](file:///d:/PythonProject/QuantVortex/futures_quant/ui/pages.py#L609) 起 | **否** | — | — | 仅测试引用 |
| ScreeningPage | [screening_page.py:509](file:///d:/PythonProject/QuantVortex/futures_quant/ui/screening_page.py#L509) | **否** | — | — | 1329 行孤儿 |
| PaperTradingPage | [paper_trading_page.py:46](file:///d:/PythonProject/QuantVortex/futures_quant/ui/paper_trading_page.py#L46) | **否** | — | — | 197 行孤儿，且依赖第二套账务 |

**实测补充**：静态扫描 `QPushButton` 未连接 `clicked` 的只有 `_eye_btn`（通过 `toggled` 连接），**不存在“按钮完全无响应”的入口**；问题集中在“有响应但静默/误导”。

### A-2 静默失败、无提示、点了没反应（按严重度）

| 问题 | 证据 | 影响 | 建议 | 验收 |
|---|---|---|---|---|
| AI 指标研判可在未预测时点击，提示词无 `res` 上下文，返回泛化研判 | [predict_ops_page.py:1241-1250](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L1241-L1250)、[1319-1345](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L1319-L1345) | 用户以为“AI 看过我的预测”，实际没有 | 未生成 `_last_res` 时禁用按钮并 tooltip 说明；提示词显式写“无预测结果”或要求先预测 | 未预测时按钮 disabled；有预测后提示词含 `res` 摘要 |
| 跳转回测失败被 `pass` 吞掉 | [predict_ops_page.py:896-905](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L896-L905) | 页面跳了但回测没跑，无任何提示 | 捕获后 toast/状态栏“回测启动失败：原因”；目标页缺 `run_manual_for` 时提示 | 人为注入异常，UI 必须出现可行动文案 |
| 每代历史落库失败静默 | [backtest_page.py:2876-2884](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2876-L2884) | 历史缺口，用户无法追溯 | 记录 WARN + 状态栏/toast + 继续进化不中断 | DB 写失败模拟：界面有提示，进化不崩 |
| 启动恢复失败静默 | [backtest_page.py:2297-2303](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2297-L2303) | 断点丢失但显示“新启动” | 区分“无断点”与“恢复失败”；失败时提示并保留库 | 损坏 state 时显示“恢复失败”而非静默 |
| 进化失败 6s 自动重试，可能无限循环 | [backtest_page.py:2262-2265](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2262-L2265)、[3017-3035](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L3017-L3035) | 用户只看到反复重试，难定位根因 | 连续 N 次失败后停止并给“查看日志/重试/忽略”三选一 | 失败 3 次停止自动重试 |
| DB 有 15 条全空历史行 | 只读查询：1001 行中 15 行 `symbol=NULL`、`metrics_json={}` | 历史表污染，用户看到空记录 | 写入前校验 `symbol + ranked`；启动时清理/标记空行 | 新库 0 空行；旧库迁移后空行被归档 |
| “数据导出/备份恢复”菜单只跳页，不执行动作 | [main_window.py:702-705](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L702-L705) | 菜单语义与行为不符 | 改为“打开数据管理”或直接弹对应流程 | 菜单文案与行为一致 |
| 数据管理页无行情下载，但主窗口副标题写“行情下载” | [main_window.py:86-94](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L86-L94) vs [data_page.py:192-229](file:///d:/PythonProject/QuantVortex/futures_quant/ui/data_page.py#L192-L229) | 用户找不到“下载行情” | 要么加“更新行情/清缓存”按钮，要么改副标题 | 文案与按钮二者一致 |
| 独立回测无导出，指标仅 6 个 | [simple_backtest_page.py:229-231](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L229-L231) | 结果无法交付/复盘 | 复用回测中心的 HTML/CSV 导出；补成交笔数/Calmar/手续费合计 | 导出文件含数据指纹与参数快照 |

### A-3 主线交互成本

静态路径（不是真人计时，见第 8 节“待验证”）：

| 场景 | 动作数 | 跨页 | 等待 | 说明 |
|---|---|---|---|---|
| 看行情 → 直接预测 → 回测此策略 | **3 次操作**（行情行双击、开始预测、回测此策略） | 2 次（行情→预测→回测） | 2 次（预测、回测） | 双击已自动带品种/周期（[market_overview_page.py:2177-2180](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L2177-L2180)）；回测按钮见 [predict_ops_page.py:364](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L364) |
| 看行情 → 改策略参数 → 回测 → 看结果 → 预测 | **约 8~12 次**（选品种/周期/策略 + N 个参数编辑 + 开始回测 + 切预测 + 开始预测） | 2~3 次 | 2 次以上 | 参数编辑次数取决于策略（`SEARCH_SCHEMA` 每策略 2~4 个数值参数） |
| 手动回测（回测中心） | 1 次切“手动回测” + N 次参数 + 1 次运行 | 0（同页） | 1 次 | [backtest_page.py:2396-2398](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2396-L2398) |

**可合并/可跳转点**

1. 在“预测操作”页内嵌“参数编辑 → 回测 → 结果”三步，避免跳到回测中心后再回来。
2. 回测结果卡增加“用此结果跑预测”，复用 `set_symbol(symbol, period, gene)`（[predict_ops_page.py:907-917](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L907-L917)）。
3. 把“独立回测”和“回测中心”合并为一个页面的两个 Tab；`BacktestPage` 死类直接移除。
4. 全局保留“当前品种/周期”上下文（已有 session `get_page_selection`），减少重复选择。
5. 历史记录行支持“重跑此配置”，用参数快照填充表单（依赖 P0-1 快照落库）。

### A-4 视觉一致性

静态统计（grep 计数，含死代码；口径：`#RRGGBB` 字面量、`font-size: Npx`、`setStyleSheet(`、`setFixed/Minimum*`）：

| 指标 | 数量 | 备注 |
|---|---|---|
| 硬编码十六进制色值 | **397 处 / 19 个 UI 文件** | live 页面：predict 67、backtest 32、overview 30、states 21；死代码 screening 49 |
| 内联 `font-size` | **131 处** | 与字号缩放（90~125%）存在冲突风险 |
| 固定/最小尺寸 | **128 处** | 响应式布局受限 |
| `setStyleSheet(` | **190 处** | 与 `design_system` token 部分重复 |
| `setObjectName("primary")` | **15 处** | 主按钮规范仅少量覆盖 |

结论：已有 `PALETTE` / `design_tokens` / `scripts/validate_qss_mapping.py`，但**采纳不完整**。建议先只治理 4 个 live 页（predict/backtest/overview/states），死代码不投入；用脚本做 allowlist 门禁，新增硬编码色值即失败。

### A-5 `ui/pages.py` 死代码处置方案（只给方案）

现状：[pages.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/pages.py) 2969 行；生产只使用 `BasePage`、`Worker`、`LogPage` 与若干 helper（`symbol_code/symbol_label/PERIODS/df_to_bars`）。`MarketPage/IndicatorPage/PredictPage/PanoramaPage/ValidatePage` 仅测试引用，估算约 **2.0k 行**历史双实现。

| 方案 | 做法 | 优点 | 风险 | 建议 |
|---|---|---|---|---|
| A. 保留现状 | 不动 | 零风险 | 继续误导搜索、增加维护成本 | 不推荐 |
| B. 拆分 + 归档（推荐） | 把 `BasePage/Worker/helpers/LogPage` 拆到 `ui/base.py`、`ui/log_page.py`；旧 5 页移到 `ui/legacy/pages_legacy.py`，不导入、标 deprecated；测试改为直接导入 legacy | 主路径变清晰；可逆；不删历史 | 需改测试导入；一次较大 rename | **先做 B** |
| C. 直接删除 | 删除 5 页与相关测试 | 最干净 | 丢失参考实现；测试覆盖下降 | 待 B 稳定后再评估 |

同批处理：`backtest_page.py` 的 `BacktestPage`（死类）删除；`screening_page.py`、`paper_trading_page.py` 归档；`continuous.py`（均价拼接假实现）归档并明确禁止生产使用。

### A 节汇总表

| 问题 | 证据 | 影响 | 建议方案 | 验收标准 |
|---|---|---|---|---|
| AI 研判可无上下文调用 | 文件:行见 A-2 | 误导性结论 | 前置校验 + 提示词分支 | 未预测时 disabled；提示词含结果摘要 |
| 3 处以上静默失败 | 文件:行见 A-2 | 用户无法定位失败 | 统一 `toast/status` 错误出口 | 注入异常必出可行动文案 |
| 主线跨页多、重复页面 | A-3 | 操作成本高 | 内嵌三步 + 合并回测页 | 快乐路径 ≤3 动作；参数主线 ≤8 动作 |
| 视觉 token 未统一 | A-4 统计 | 主题/缩放不一致 | 4 个 live 页 token 化 + 脚本门禁 | 新增硬编码色值 0；字号缩放无截断 |
| 死代码约 2.0k 行 | A-5 | 维护/搜索成本 | 拆分归档 | `pages.py` ≤950 行或拆分完成；acceptance 通过 |

---

## 3. B. 主力合约模块现状

### B-1 能力边界

| 能力 | 现状 | 证据 |
|---|---|---|
| 主力识别 | `identify_dominant` 需要**调用方提供多合约宽表** `['date','contract','volume','open_interest']`；按日对成交量/持仓量排名，`0.4*vol_score + 0.6*oi_score` 取最大 | [dominant.py:11-38](file:///d:/PythonProject/QuantVortex/futures_quant/data/dominant.py#L11-L38) |
| 换月识别 | `roll_transitions` 只做事后检测：相邻交易日主力代码变化即换月 | [dominant.py:41-54](file:///d:/PythonProject/QuantVortex/futures_quant/data/dominant.py#L41-L54) |
| 换月规则 | **没有**“交割月前 N 日/流动性阈值/交易所规则”的前瞻规则；不能预测未来换月日 | 静态确认，`dominant.py` 无日历/规则参数 |
| 近月/次近月选择 | **没有**；只从已有合约里选分数最高者 | 同上 |
| 连续合约 | `continuous_symbol_map` 只做日期→代码映射；`continuous.join_continuous` 是均价拼接，且把 >10% 变动置 NaN 后 ffill，**不可用于真实回测** | [continuous.py:15-56](file:///d:/PythonProject/QuantVortex/futures_quant/data/continuous.py#L15-L56) |
| 回测接线 | `Backtester.run(..., roll_schedule=None)` 支持真实换月日集合；但所有 UI/服务调用均未传，实际走“每自然月首个交易日”近似 | [backtester.py:169-182](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L169-L182)、[259-280](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L259-L280) |

### B-2 调用穷举（grep 全仓库，排除 docs）

`identify_dominant` / `roll_transitions` / `continuous_symbol_map` / `join_continuous` 的引用只有：

- 自身定义；
- `tests/unit/test_phase1_roll_cost.py`；
- `tests/e2e/test_dominant_contract.py`、`tests/e2e/test_continuous_join.py`；
- `roll_cost.py` 注释提到 `dominant.roll_transitions`。

**生产代码零调用**（与 `full_chain_diagnosis.md` 的既有结论一致，本轮复核未发现新增调用）。

### B-3 数据可行性实测

探针：`outputs/_probe_b_contract.py`，结果 `outputs/_probe_b_result.txt`。条件：Windows / Python 3.13.5 / 与验收并行（CPU≈49%）；直接调 `DataFeed.get_history` 底层，日线，未写缓存目录。

| 合约 | 根数 | 首日 | 末日 | 耗时 |
|---|---:|---|---|---:|
| `rb0`（主力连续） | 4274 | 2009-03-27 | 2026-11-04 | 3.51s |
| `rb2701` | 192 | 2026-01-16 | 2026-11-04 | 0.21s |
| `rb2501` | 242 | 2024-01-16 | 2025-01-15 | 0.20s |
| `rb2001` | 243 | 2019-01-16 | 2020-01-15 | 0.20s |
| `rb1901` | 0 | — | — | 0.19s |
| `TA2701` | 191 | 2026-01-19 | 2026-11-04 | 0.20s |
| `i2501` | 241 | 2024-01-16 | 2025-01-15 | 0.21s |
| `i1901` | 0 | — | — | 0.15s |

字段包含 `v`（成交量）、`p`（持仓量）、`s`（结算价），可用于主力评分与结算价基准。已到期合约保留约 2019 年以后；更早的 `rb1901/i1901` 为空（**待验证**：是接口保留窗口还是合约代码规则问题）。

数据层参数格式：

- `SinaFeed._to_sina`：纯字母品种补 `0` 变连续；月份合约原样返回（[sina_feed.py:74-79](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L74-L79)）。因此 `rb2701` 可直接取。
- `AkshareFeed._to_ak_symbol`：末位为数字的原样返回，月份合约可透传（[akshare_feed.py:34-40](file:///d:/PythonProject/QuantVortex/futures_quant/data/akshare_feed.py#L34-L40)）；但底层 `futures_zh_daily_sina` 对月份合约的支持**未单独验证**（待验证）。
- `TqSdkFeed`：支持 `KQ.m@SHFE.rb`、`SHFE.rb2611`、简写 `rb2611`；周期 `D/1/5/15/30m`（[tqsdk_feed.py:10-31](file:///d:/PythonProject/QuantVortex/futures_quant/data/tqsdk_feed.py#L10-L31)）。
- `MarketDataManager.get_bars` 接受任意 symbol（[market_data.py:581-598](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L581-L598)）；但 `get_quote` 的乘数走 `find_universe_row`（[market_data.py:601-611](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L601-L611)），月份合约不在 universe 时回退 10.0 乘数，**存在乘数错误风险**。

### B-4 “目标品种主力合约单模块”缺口清单（只列落点，不实现）

| # | 缺口 | 落点（文件:行） | 说明 | 依赖 |
|---|---|---|---|---|
| 1 | 多合约链抓取 | 新模块或在 [dominant.py:11](file:///d:/PythonProject/QuantVortex/futures_quant/data/dominant.py#L11) 外围加 `fetch_chain(product, start, end)`；复用 `SinaFeed.get_history` | 枚举品种当年/次年月份合约，逐合约取日线，合并为 `identify_dominant` 所需宽表 | 无 |
| 2 | 主力识别输入构造 | 同上，产出 `['date','contract','volume','open_interest']` | 当前 `identify_dominant` 只吃现成宽表 | #1 |
| 3 | 换月调度接入回测 | [backtester.py:169](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L169)、[backtest_service.py:143-170](file:///d:/PythonProject/QuantVortex/futures_quant/app/backtest_service.py#L143-L170)、UI 调用点 | 把 `roll_transitions` 结果转成 `roll_schedule` 传入；默认关闭以保锚点 | #1/#2 |
| 4 | 真实换月成本 | [backtester.py:328-335](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L328-L335)、[roll_cost.py](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/roll_cost.py) | 现行仅手续费下限；需按真实换月日计双边成本，并可与滑点合并 | #3 |
| 5 | 连续价格口径 | 不要使用 [continuous.py:15-56](file:///d:/PythonProject/QuantVortex/futures_quant/data/continuous.py#L15-L56) | 建议“按合约回测 + 换月事件”而非均价拼接；若需连续图，用换月日价差复权并明确标注 | #3 |
| 6 | 前瞻换月规则 | 新配置 `roll_rule`（交割月前 N 日/流动性阈值/交易所差异） | `dominant` 只能事后识别，不能提前决定换月 | #1 |
| 7 | 单合约乘数 | [market_data.py:609-611](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L609-L611) | 月份合约不在 universe 时乘数回退 10.0，必须改为按品种前缀精确查表 | #1 |
| 8 | 链缓存/刷新 | `data/sina_cache` 目前只有 `x0.csv`（只读统计） | 需要 per-contract 缓存 + 链级 TTL + 手动刷新；避免每页重建链 | #1 |
| 9 | UI 展示 | 无页面；可在 [market_overview_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py) 增加“主力合约”卡片或新页 | 展示当前主力、次主力、成交量/OI、距换月天数、来源/时间 | #1/#2 |
| 10 | 实时刷新 | `SinaFeed` 只有日线；`TqSdkFeed` 可分钟但无账号 | 实时只能 TqSdk/CTP；不可用时应显示“不可用”，禁止合成冒充 | TqSdk 账号 |
| 11 | 分钟历史 | 免费源无分钟；`SinaFeed` 分钟返回 None | 单合约分钟只能 TqSdk 或 CTP；日线模块先落地 | TqSdk |
| 12 | 验收锚点 | `docs/diagnosis/phase2_perf_fix.md §8`：rb 231 / 锚点 225 / i.DCE 235 | 新换月路径必须单独锚点，不改变默认口径 | #3 |

**结论**：B 不是“写一个 UI”问题，而是“缺数据链 + 缺前瞻规则 + 缺回测接线 + 缺乘数保护”的四段缺口。建议按 #1→#2→#3→#7→#9 顺序做只读纵切，先让 rb 在 2024-2026 显示真实主力切换与换月成本，再考虑分钟/实时。

### B 节汇总表

| 问题 | 证据 | 影响 | 建议方案 | 验收标准 |
|---|---|---|---|---|
| 主力/连续无生产调用 | grep：仅 tests + `roll_cost` 注释；[dominant.py:11-54](file:///d:/PythonProject/QuantVortex/futures_quant/data/dominant.py#L11-L54) | 换月成本失真，连续图不可信 | 按 B-4 #1→#2→#3→#7→#9 只读纵切 | rb 2024-2026 识别 ≥1 次换月并进回测 |
| 回测默认月度近似换月 | [backtester.py:181-182](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L181-L182)、[259-280](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L259-L280) | 成本被系统性低估/错配 | 传真实 `roll_schedule`，默认开关关闭 | 开关打开时 `total_roll_cost` 可解释；关闭时锚点不变 |
| 月份合约乘数回退 10.0 | [market_data.py:609-611](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L609-L611) | 保证金/盈亏计算错误 | 按品种前缀精确查表，禁止回退 | 单月合约乘数等于品种规格 |
| 免费源无分钟历史 | [sina_feed.py:14-23](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L14-L23) | 分钟模块无法真实落地 | 日线先落地；分钟仅 TqSdk/CTP，不可用即报错 | 无账号时明确报错，不合成 |
| 无前瞻换月规则 | `dominant.py` 只事后识别 | 无法提前安排换月/展示倒计时 | 新增 `roll_rule` 配置（交割月前 N 日/流动性） | 规则可配置且单测覆盖 |

---

## 4. C. 自我进化（auto_evolve）

### C-1 流程与参数

| 项 | 现状 | 证据 |
|---|---|---|
| 触发 | **仅页面显示自动启动**：`showEvent` 延迟 600ms 调 `_start_auto`；`app/scheduler.py` 不触发进化 | [backtest_page.py:2204-2213](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2204-L2213)、[2215-2265](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2215-L2265) |
| 种群/代数 | `POP_SIZE=10`，每品种 `GENS_PER_SYMBOL=4`，最多 200 代，停滞 30 代停止；默认 seed 20240921 | [auto_evolve.py:1205-1207](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1205-L1207)、[config/settings.py:66-69](file:///d:/PythonProject/QuantVortex/futures_quant/config/settings.py#L66-L69) |
| 适应度 | 只用 IS 区间回测（`_fit_range`），`fitness(m, gene=gene)` 含树深惩罚；OOS 仅用于 `validate_strategy` 的盈利判定 | [auto_evolve.py:1533-1566](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1533-L1566) |
| 缓存 | `_fit_cache`，键 = 品种 + 区间 + 周期 + 数据指纹 + 基因签名 | [auto_evolve.py:1437-1463](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1437-L1463)、[1231-1235](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1231-L1235) |
| 结果落库 | 每代 `to_state` + `last_snapshot` + `evolve_history`（含 gene/metrics/trades/equity JSON） | [backtest_page.py:2864-2884](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2864-L2884)、[backtest_store.py:196-220](file:///d:/PythonProject/QuantVortex/futures_quant/storage/backtest_store.py#L196-L220) |
| UI 展示 | 状态灯、KPI、种群表、历史表、进化档案下拉；断点恢复 | [backtest_page.py:2895-2975](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2895-L2975)、[2270-2306](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2270-L2306) |

### C-2 适应度与 OOS 泄漏残留

1. **IS-only 已落地**：适应度回测只跑 `fit_start~fit_end`（[auto_evolve.py:1533-1539](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1533-L1539)）。但 `validate_strategy` 仍对**每个基因**跑固定 OOS 尾段，并把 `ok_valid` 作为盈利门槛（[auto_evolve.py:1559-1566](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1559-L1566)、[validate.py:477-495](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/validate.py#L477-L495)）。
2. **同一 OOS 尾段被每一代重复使用**：`split_is_oos` 按行数 70/30 切分（[validate.py:157-192](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/validate.py#L157-L192)）。这意味着 OOS 实际参与了“逐代筛选”，从统计上已不再是纯锁箱；泄漏程度待量化（见第 8 节）。
3. **OOS 一致性只做“二次确认”**：`is_profitable(m, ...)` 又对 IS 指标判一次，不改变上述复用问题（[auto_evolve.py:1571-1575](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1571-L1575)）。
4. **并行路径更弱**：`evaluate_gene_pair` 用 `fitness(m)`，不带 `gene` 惩罚；`validate_strategy` 不传 `_evaluator`（[auto_evolve.py:1679-1691](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1679-L1691)）。默认 `parallel=False`（[auto_evolve.py:1212](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1212)），属于潜在不一致而非当前默认路径。

### C-3 缓存语义与可复现性（已确认的实质问题）

| 问题 | 证据 | 影响 |
|---|---|---|
| 缓存命中返回 `metrics={}`、`profitable=False`、`trades=[]` | [auto_evolve.py:1501-1525](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1501-L1525) | 精英基因每代都要**完整重跑**才能恢复 metrics/曲线（[1866-1898](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1866-L1898)）；缓存基本只省“落选基因”的重复评估 |
| 首次评估 `fitness(m, gene=gene)`，缓存命中重评 `fitness(m)` | [auto_evolve.py:1552](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1552)、[1876](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1876)、[1679](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1679) | 同一基因在“首评”和“精英重评”得到不同 fitness，精英可能因丢掉树深惩罚而被高估，选择压力不一致 |
| `_fit_cache` 无上限 | [auto_evolve.py:1231](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1231) | 172 代 × 10 基因约 1720 条，当前规模可接受；不是主要风险 |
| 可复现性 | seed 与 `rng_state` 存在 `to_state`，历史行**不存 seed** | 引擎断点可复现；但单条历史结果无法独立复现（见 D） |
| 失败静默 | 基因评估异常只 `logger.warning`，UI 只显示“失败数” | 用户不知道哪些基因为什么失败；并行路径异常返回 None 直接丢失 |

### C-4 性能与稳定性实测

条件：与验收并行（CPU≈49%）、日线、约 1600 根、warmup 60、单进程；探针 `outputs/_probe_phase7_scale.py`。

| 指标 | 实测 | 说明 |
|---|---:|---|
| 单基因冷启动 `_evaluate` | **4.13s** | 含 IS 回测 + OOS/邻域验证 |
| 单基因热缓存中位数 | **1.35s** | 3 个基因，seed 10/11/12 |
| 单代（10 基因）估算 | **≈13.5s** | 10 × 1.35s，未计缓存命中节省 |
| 全 43 品种 × 4 代估算 | **≈38.7min** | 172 代；冷启动上限约 2h |
| 缓存命中 `_evaluate` | **≈0ms** | 但返回空 metrics，见 C-3 |
| UI 线程阻塞点 | 启动时 `prune()+checkpoint()` 在 UI 线程 | [backtest_page.py:2238-2243](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2238-L2243)；205MB 库上的实际停顿**待验证** |
| 进化主循环 | 后台 `Worker` 线程，支持暂停/停止/协作中断 | [2816-2893](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2816-L2893)；中断检查按基因粒度 |

**可量化目标建议**

| 目标 | 建议值 | 验收方法 |
|---|---|---|
| 单代耗时（热缓存，1600 根，POP=10） | ≤10s | 固定 seed 跑 5 代取中位数 |
| 单基因热评估 | ≤1.0s | 缓存 metrics 后避免精英全量重跑 |
| UI 主线程单次阻塞 | ≤100ms | 把 prune/checkpoint 移到后台；用 `QElapsedTimer` 采样 |
| 中断响应 | ≤1 个基因（当前已满足） | 点停止后 ≤2s 内停 |
| 可复现 | 同 seed + 同数据指纹 → best_signature/top3 完全一致 | 连续两次冷启动 + 断点恢复各一次 |
| 失败可见 | 每代失败基因数 + 首个原因显示在 UI | 注入异常验证 |

### C 节汇总表

| 问题 | 证据 | 影响 | 建议方案 | 验收标准 |
|---|---|---|---|---|
| 缓存命中返回空 metrics/`profitable=False` | [auto_evolve.py:1501-1525](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1501-L1525) | 精英每代全量重跑，缓存几乎不省 | 缓存完整结果或标记“需重评”；精英结果复用 | 精英重评次数 0；单代 ≤10s |
| 同一基因两次 fitness 口径不一致 | [1552](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1552) vs [1876](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1876) | 树深惩罚丢失，选择压力偏差 | 统一 `fitness(m, gene)`；并行路径同步 | 同基因首评/重评 fitness 差 <1e-9 |
| 固定 OOS 尾段逐代复用 | [validate.py:157-192](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/validate.py#L157-L192) | OOS 参与筛选，存在验证泄漏 | 锁箱 OOS 不参与选择；或 walk-forward 滚动 | A/B 报告：锁箱命中率与盈利库数量 |
| 并行路径无 `_evaluator`/无 gene 惩罚 | [auto_evolve.py:1679-1691](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1679-L1691) | 默认关闭，但开启后结果不可比 | 与串行路径统一评估函数；pickle 失败显式计数 | 并行/串行同 seed top3 一致 |
| 单代 13.5s、全周期 38.7min | 本轮实测/估算 | 长跑成本高，反馈慢 | 缓存 metrics + 热点降耗；不扩种群 | 单代 ≤10s；UI 阻塞 ≤100ms |
| 历史/失败不可追溯 | 历史行无 seed/指纹；异常只 WARNING | 结果不可复现、失败难定位 | 与 P0-1 合并；UI 显示失败原因 | 新行字段齐全；失败可见 |

---

## 5. D. 回测性能与规模上限

### D-1 耗时构成（cProfile）

条件：12 品种日线、默认区间（约 2020-01-01~2026-07-21）、warmup 60、单线程、与验收并行（CPU≈49%）。**cProfile 会放大绝对耗时，百分比用于定位热点，不代表生产绝对值。**

| 热点 | cumtime | 占 2.863s | 备注 |
|---|---:|---:|---|
| 总计 | 2.863s | 100% | 12 品种 |
| `_run_event_driven` | 2.448s | 85.5% | 撮合主循环 |
| `engine.process_bar` | 1.901s | 66.4% | 每 bar 处理 |
| `strategy.on_bar` | 1.125s | 39.3% | 策略信号 |
| `atr_last` | 0.646s | **22.6%** | 每根全窗口重算 |
| `risk.on_new_bar` | 0.297s | 10.4% | 风控 |
| `_tail` | 0.257s | 9.0% | 96,125 次调用 |
| `portfolio.equity` | 0.178s | 6.2% | 41,695 次 ≈2.13 次/bar |
| `match` | 0.179s | 6.2% | 撮合 |
| 数据加载 | 0.384s | 13.4% | 其中 `read_csv` 0.237s（8.3%） |

结论：主循环已无 O(N²)；剩余是“每 bar 常数级重复计算”（ATR 全窗口、equity 多次、`_tail` 切片）。

### D-2 规模与内存

| 场景 | 实测/估算 | 条件 |
|---|---:|---|
| 单次回测保留内存 | **0.77MB**，峰值 1.7MB | 1600 bars，`tracemalloc` |
| 参数扫描 8 组合（丢弃结果） | **+0.16MB** | 1600 bars |
| 参数扫描 8 组合（保留结果） | **+1.4MB**（≈0.18MB/组合） | 1600 bars |
| 1000 组合外推 | **≈175MB** | 0.18MB×1000，**外推估算** |
| 5000 bars × 1000 组合 | **≈500MB** | 0.5MB/组合，**外推估算** |

- 单 bar 成本：1636 bars 总耗时 109ms → **66.9µs/bar**；首段约 101µs/bar，末段/首段比值 0.66，说明固定开销占比高、**无 O(N²)**。
- `add_indicators`：5000 根实测 38~52ms（验收 51.9ms），已是线性，无 O(N²) 复现。
- **全量驻留风险**：`MarketDataManager._full` 是无上限 `(symbol, period)` 缓存（[market_data.py:356](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L356)、[541-579](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L541-L579)）。43 品种日线可接受；若为每个品种/周期加载完整分钟序列，会线性累积。**待验证**（未跑分钟全量）。
- **结果对象持有 bars**：回测结果只返回 `equity_curve/trades`，不持有原始 bars（[backtester.py:332-335](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L332-L335)）；但参数扫描若同时保留每股曲线，内存按组合数线性增长（上表）。

### D-3 大样本瓶颈与方案

| 瓶颈 | 证据 | 方案 | 可接受规模估算 |
|---|---|---|---|
| ATR 每 bar 全窗口重算 | [indicators.py:43](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L43)、cProfile 22.6% | 预计算 ATR 序列或增量缓存 last-N | rb 1600 bars 预计 -20%~25%，目标 ≤85ms |
| `portfolio.equity()` 每 bar 多次 | [portfolio.py:199](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L199)、41,695 次 | 每 bar 缓存一次权益，成交后再失效 | 预计 -3%~5% |
| `risk.on_new_bar` 10.4% | [risk_manager.py:141](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L141) | 只在持仓/价格阈值变化时做重算；预计算阈值 | 预计 -5% |
| `_tail` 9.0% / 96k 次 | 主循环内切片 | 用索引窗口而非每 bar `tail()` | 预计 -5% |
| 数据加载 13.4% | `read_csv` 8.3% | 落 Parquet/feather 或进程内共享 DataFrame | 批量 43 品种 4462ms → ≤3500ms |
| 参数扫描全量保留曲线 | `_compare_results`/优化结果 | 只保留 top-K 曲线，其余落库/丢弃 | 1000 组合 ≤80MB（1600 bars） |
| 结果全量写 DB | `equity_curve_json` 均值 129.6KB/行 | 只存降采样/关键点；全量写文件或对象存储 | 单行 ≤20KB，DB 增长可控 |

**分批/流式/落库建议**

1. 参数扫描改为生成器：`for combo in combos: run(); yield metrics`，只有 top-K 保留曲线。
2. 回测结果对象改为“轻量 metrics + 曲线引用”，曲线按需从 store 读。
3. 品种批量回测复用已加载 DataFrame（`_full` 加容量上限/LRU）。
4. 历史库按 id 分页读取，曲线降采样（如每 5 点取 1 点 + 首尾 + 最大回撤点）。
5. 大规模实验写独立 SQLite/Parquet，避免主库膨胀。

### D-4 结果可视化与可追溯性缺口

| 项 | 现状 | 证据 | 缺口 |
|---|---|---|---|
| 回测中心指标 | 有总收益/年化/夏普/回撤/胜率/盈亏比/Calmar/交易数等 | [backtest_page.py:2196-2199](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2196-L2199) | 无手续费/滑点合计展示 |
| 独立回测指标 | 仅 6 个 KPI | [simple_backtest_page.py:229-231](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L229-L231) | 缺交易数、Calmar、成本；无 CSV/HTML 导出 |
| 数据指纹 | 引擎缓存键有 `_feed_fingerprint` | [auto_evolve.py:1437-1463](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1437-L1463) | **不落历史行、不进报告** |
| 参数快照 | `_experiment` 有参数，但只在引擎状态/内存 | [auto_evolve.py:1245-1259](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1245-L1259) | `evolve_history` 无参数列；重跑用当前 `futures_params` |
| 随机种子 | `to_state` 有 seed/rng_state | [auto_evolve.py:1261-1285](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1261-L1285) | 历史行无 seed；报告无 seed |
| 数据源 | UI 有来源水印 | `_update_evo_prov` 调用点 | 历史行/报告无 `data_source/is_synthetic/as_of` |
| 复现同一结果 | 只能靠断点状态 | 静态确认 | 单条历史无法“用同数据同参数同种子”重跑 |
| 历史库健康 | 1001 行、986 非空、15 全空；204.84MB；`prune` 保留 1000 不 VACUUM | 只读查询 + [backtest_store.py:309-322](file:///d:/PythonProject/QuantVortex/futures_quant/storage/backtest_store.py#L309-L322) | 膨胀 + 空行污染 |

### D 节汇总表

| 问题 | 证据 | 影响 | 建议方案 | 验收标准 |
|---|---|---|---|---|
| ATR 每 bar 全窗口重算 | cProfile 22.6%；[indicators.py:43](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L43) | 单次回测 1/5 时间耗在此 | 预计算/增量 last-N | rb 1600 bars ≤85ms |
| `equity()` 每 bar 2.13 次 | 41,695 次；[portfolio.py:199](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L199) | 重复计算 | 每 bar 缓存，成交后失效 | 调用次数 ≤1/bar |
| 风控每 bar 重算 | 10.4%；[risk_manager.py:141](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L141) | 固定开销 | 阈值预计算/状态触发 | 43 品种批量 ≤3.5s |
| 参数扫描保留全曲线 | 0.18MB/组合@1600；1000 组合≈175MB | 大规模扫描 OOM 风险 | 生成器 + top-K 曲线 | 1000 组合 ≤80MB |
| 历史行无指纹/seed/参数/来源 | [backtest_store.py:58-71](file:///d:/PythonProject/QuantVortex/futures_quant/storage/backtest_store.py#L58-L71) | 结果不可复现 | P0-1 schema + 快照 | 同 seed+指纹可复现 |
| DB 204.84MB、15 空行、无 VACUUM | 只读查询 + [backtest_store.py:309-322](file:///d:/PythonProject/QuantVortex/futures_quant/storage/backtest_store.py#L309-L322) | 体积/查询退化、历史污染 | 空行防护 + prune/VACUUM + 降采样 | 体积 -50%；0 空行 |
| 独立回测无导出/指标少 | [simple_backtest_page.py:229-231](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L229-L231) | 结果不可交付 | 复用 HTML/CSV 导出 | 导出含指纹/参数/种子 |

---

## 6. 优先级表（P0/P1/P2）

| ID | 级别 | 事项 | 依赖 | 顺序 | 主要改动面 | 验收标准 |
|---|---|---|---|---|---|---|
| P0-1 | P0 | 结果可追溯：历史行/报告写入 `data_source`、`data_fingerprint`、`seed`、`params_json`、`engine_version` | 无 | 1 | `storage/backtest_store.py`（schema+migration）、`auto_evolve.py`（snapshot）、`backtest_page.py`（展示/导出） | 新行字段非空；同 seed+指纹重跑 top1 一致；导出含指纹 |
| P0-2 | P0 | 历史库治理：空行防护、`prune+VACUUM`、曲线降采样、持久化失败可见 | P0-1（同一次迁移） | 1 | `backtest_store.py`、`backtest_page.py` | 新库 0 空行；DB 体积下降 ≥50%；写失败有 UI 提示 |
| P0-3 | P0 | 主力合约链 → `roll_schedule` → 回测换月成本（默认关闭，保锚点） | B#1/#2 | 2 | 新链抓取模块、`dominant.py`、`backtest_service.py`、`backtester` 调用点 | rb 2024-2026 识别 ≥1 次换月；`total_roll_cost` 与月度近似有可解释差异；默认锚点不变 |
| P1-1 | P1 | 进化缓存/适应度一致性：缓存返回完整 metrics 或标记重评；统一 `fitness(m, gene)`；OOS 锁箱或滚动 | 无（与 P0-1 可并行） | 3 | `auto_evolve.py`、`validate.py` | 精英不再全量重跑；同基因 fitness 一致；锁箱 A/B 有报告 |
| P1-2 | P1 | GUI 静默失败治理：AI 前置校验、回测跳转/落库/恢复错误提示、空行过滤 | 无 | 3 | `predict_ops_page.py`、`backtest_page.py` | 注入异常可见；未预测时 AI 按钮 disabled |
| P1-3 | P1 | 主线压缩与导出：预测页内嵌参数→回测→结果；独立回测补指标/导出；数据页下载或改文案 | P1-2 | 4 | `predict_ops_page.py`、`simple_backtest_page.py`、`data_page.py`、`main_window.py` | 快乐路径 ≤3 动作；独立回测可导出 CSV/HTML |
| P1-4 | P1 | 热点性能：ATR 预计算、权益缓存、风控阈值、`_tail` 索引化 | P0-1（便于回归对照） | 4 | `indicators.py`、`portfolio.py`、`risk_manager.py`、`backtester.py` | rb 1600 bars ≤85ms；43 品种批量 ≤3.5s；锚点不变 |
| P1-5 | P1 | 视觉 token 化（仅 4 个 live 页）+ 脚本门禁 | 无 | 4 | predict/backtest/overview/states、`design_system.py`、`scripts/validate_qss_mapping.py` | 新增硬编码色值 0；字号缩放不截断 |
| P2-1 | P2 | 死代码归档：`pages.py` 拆分、`BacktestPage` 删除、screening/paper/continuous 归档 | P1-2/P1-3（先确认无遗漏入口） | 5 | `ui/pages.py`、`backtest_page.py`、测试 | `pages.py` ≤950 行；acceptance 通过；无导入错误 |
| P2-2 | P2 | 主力合约独立 UI（当前/次主力、OI/量、换月倒计时、刷新） | P0-3 | 5 | 新页面或 `market_overview_page.py` | 卡片显示来源/时间；刷新不阻塞 UI |
| P2-3 | P2 | TqSdk 实时/分钟连通性验证与接线 | 外部账号 | 6 | `tqsdk_feed.py`、`market_data.py` | 有账号时 D/5m 真实数据；无账号明确报错，不合成 |
| P2-4 | P2 | 规模化：参数扫描流式化、曲线 top-K/落库、`_full` 容量上限 | P0-1/P0-2 | 6 | `backtest_page.py`、`market_data.py`、`backtest_store.py` | 1000 组合 1600 bars ≤80MB；5000 bars 可跑不 OOM |

**依赖与实施顺序**：P0-1+P0-2 同一迁移先行 → P0-3 数据/回测接线 → P1-1/P1-2 并行 → P1-3/P1-4/P1-5 → P2 系列。P0-3 与 P1-1 互不依赖，可双线。

---

## 7. 分期落地计划

### 第 1 期：可信结果与库治理（P0-1 / P0-2）

- **目标**：任何一条历史结果都能回答“什么数据、什么参数、什么种子、什么版本”；历史库不再膨胀/空行。
- **改动面**：`backtest_store.py`（加列 + 幂等迁移 + prune/VACUUM + 空行防护）、`auto_evolve.py`（snapshot 增加指纹/seed/params/source）、`backtest_page.py`（展示/导出/失败提示）。
- **回归口径**：
  - `python scripts/acceptance.py --quick` 855 单测通过；
  - 旧库副本迁移两次幂等，无数据丢失；
  - 锚点 rb 231 / 锚点 225 / i.DCE 235 不变；
  - 新库跑 10 代后 0 空行；DB 体积下降 ≥50%（对比 204.84MB）。

### 第 2 期：主力合约纵切（P0-3）

- **目标**：rb 单品种、2024-2026，能取多合约链、识别主力、输出换月事件，并把 `roll_schedule` 传入回测（默认开关关闭）。
- **改动面**：新增链抓取（建议 `data/contract_chain.py`，不改 `dominant.py` 纯函数）、`market_data.py` 乘数保护、`backtest_service.py` 传参、`backtester` 已支持无需改核心。
- **回归口径**：
  - 新功能开关关闭时所有锚点/耗时不变；
  - 开关打开时 rb 换月成本与月度近似有差异，差异可解释；
  - 月份合约乘数按品种精确值，非 10.0 回退；
  - 无网络时明确报错/陈旧缓存标注，不合成。

### 第 3 期：GUI 诚实性与主线（P1-2 / P1-3 / P1-5）

- **目标**：所有失败可见；快乐路径 ≤3 动作；独立回测可交付；视觉一致。
- **改动面**：`predict_ops_page.py`、`backtest_page.py`、`simple_backtest_page.py`、`data_page.py`、`main_window.py`、4 个 live 页样式。
- **回归口径**：
  - e2e 7/7 GUI 冒烟通过（或 `--e2e-skip` 下不回归）；
  - 人为注入异常，UI 必出文案；
  - 未预测时 AI 按钮 disabled；
  - 导出文件含指纹/参数/种子；
  - `scripts/validate_qss_mapping.py` 通过。

### 第 4 期：进化正确性与性能（P1-1 / P1-4）

- **目标**：同一基因 fitness 一致；精英不重复全量回测；OOS 不再逐代复用；热点降耗。
- **改动面**：`auto_evolve.py`、`validate.py`、`indicators.py`、`portfolio.py`、`risk_manager.py`、`backtester.py`。
- **回归口径**：
  - 固定 seed 两次冷启动 + 一次断点恢复，best_signature/top3 一致；
  - 单代 ≤10s（1600 bars，POP 10）；
  - rb 1600 bars ≤85ms；43 品种 ≤3.5s；
  - 锚点不变。

### 第 5 期：清理与规模化（P2）

- **目标**：死代码归档；参数扫描内存可控；主力 UI 可选；TqSdk 真连通性明确。
- **改动面**：`pages.py` 拆分、死类删除、`screening/paper/continuous` 归档、`market_data._full` 上限、扫描流式化。
- **回归口径**：
  - `pages.py` ≤950 行或拆分；全仓无死导入；
  - 1000 组合 1600 bars ≤80MB（进程 RSS 实测）；
  - 5000 bars 扫描不 OOM；
  - TqSdk 无账号时明确 `MissingCredentials`，绝不回退合成。

---

## 8. 待验证清单（推测 → 验证方法）

| # | 待验证项 | 为什么是推测 | 验证方法（只读/输出到 outputs） |
|---|---|---|---|
| 1 | Akshare 月份合约支持 | 只看了 `_to_ak_symbol` 透传，未实际调 akshare | `outputs/` 探针调用 `futures_zh_daily_sina('rb2701')`，与新浪结果比对根数/首尾日 |
| 2 | TqSdk 真实连通性 | 无账号，未连 | 配 `TQ_USER/TQ_PASSWORD` 后取 `SHFE.rb2701` D/5m，验证 `is_synthetic=False` |
| 3 | 真实换月成本影响幅度 | 未接 `roll_schedule`，无对照 | 同一 rb 区间跑“月度近似 vs 真实换月”，比较 `total_roll_cost` 与收益/回撤差异 |
| 4 | `prune+checkpoint` 在 205MB 库的 UI 停顿 | 未计时；只在 UI 线程看到调用 | 复制 DB 到 `outputs/`，计时 `prune()+checkpoint()`（单次 ≤2 分钟） |
| 5 | OOS 逐代复用造成的选择偏差 | 代码确认复用，但未量化 | 当前策略 vs “OOS 锁箱不参与选择” A/B；比较盈利库数量与真正锁箱命中率 |
| 6 | 1000/5000 bars 扫描内存外推 | 由 8 组合线性外推 | 子进程跑 100/500/1000 组合，记录 RSS 峰值，拟合斜率 |
| 7 | 真实点击路径耗时 | A-3 是静态路径推断 | 离屏自动化记录每次点击到页面可交互的时间；或人工秒表 3 次取中位 |
| 8 | 视觉一致性实际渲染 | 只做 grep 计数 | 离屏渲染 4 个 live 页截图，检查主题/字号 90~125% 是否截断 |
| 9 | `dominant` 在真实链上的准确性 | 只用测试宽表，未用真实多合约 | 构造 rb 2025-2026 月份链，比较 `identify_dominant` 与 `rb0` 主连走势/换月日 |
| 10 | 新浪月份合约保留边界 | `rb1901/i1901` 为空，原因未知 | 逐年探测 `rbYY01`，记录首个可用年份与接口行为 |
| 11 | `_full` 缓存在分钟周期下的内存 | 未跑分钟全量 | 单品种 5m 全量加载后测 RSS，推算 43 品种 |
| 12 | 15 条空历史行的来源 | 只读看了时间戳，未追代码路径 | 按 ts 关联日志/旧版本行为；确认是旧 bug 还是迁移残留 |

---

## 9. 附录

### 9.1 测量条件

- 机器：AMD Ryzen 7 3700X（8C/16T），31.9GB RAM；探针期间空闲约 12.5GB；CPU 约 49%（**与另一会话的全量验收并行**，因此耗时数字偏保守/受争用影响）。
- Python 3.13.5 / Windows / PowerShell。
- 日线窗口：默认约 2020-01-01 ~ 2026-07-21；单合约探针按接口返回窗口（2019 年起）。
- 回测 warmup=60；单进程；cProfile 会放大绝对耗时，百分比有效。
- 单次探针均 ≤2 分钟；只写 `outputs/` 与 `docs/diagnosis/`；未写 `data/`、未写数据库、未 git 写。

### 9.2 本轮新增探针（均在 `outputs/`，不属于生产代码）

| 文件 | 用途 |
|---|---|
| `outputs/_probe_phase7_scale.py` | 回测随 bar 数缩放、指标耗时、tracemalloc、参数扫描内存、单基因/缓存计时 |
| `outputs/_probe_b_contract.py` | 新浪单月合约取数探针 |
| `outputs/_probe_b_result.txt` | 上一探针结果（rb0/rb2701/rb2501/rb2001/TA2701/i2501 等） |
| `outputs/_probe_a_unconnected.py` | 静态扫描按钮 `clicked` 未连接 |
| `outputs/_probe_gene_error*.py` | 误报排查脚本（见 9.3） |

### 9.3 误报说明（必须保留，避免后续误判）

`outputs/_probe_gene_error*.py` 早期探针出现 `IndexError: tuple index out of range`，一度怀疑 `_config()`/`_contract()` 在生产环境会崩。复核后确认是**探针构造的 universe 行只有 4 个元素**，而生产 `FUTURES_UNIVERSE` 行有 7 个元素；`_config()` 使用 `self._row()[4]`（[auto_evolve.py:1382-1391](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1382-L1391)）。改用 7 元素行（如 `("RB","螺纹钢","黑色系","SHFE",10,1.0,3500.0)`）后全部正常。

**结论：这不是生产 bug，是探针误报。** 后续任何人看到这些脚本的报错，不应据此改生产代码。

### 9.4 已有诊断的复用边界

本报告不重复以下已落地结论：数据源可信化与 provenance、账务/保证金、涨跌停/结算价、乘数精确匹配、指标 O(n²) 修复、`equity()` 重复调用修复、AI 伪指标修复、e2e 崩溃修复、区间覆盖率真实接口、TqSdk 适配器编写。仅在此基础上记录**剩余缺口**与**新发现**（缓存语义、OOS 复用、历史库可追溯性、主力链未接线、GUI 静默失败、死代码规模）。

### 9.5 验收基线引用

`outputs/acceptance_report.md`（2026-11-04 17:15:33 生成）：PASS；855 单测、221 e2e、锚点 5.51s、性能 20.31s、GUI 7/7 8.94s、总耗时 1308.9s；43 品种 4462ms、rb 112.7ms、add_indicators(5000) 51.9ms。

`outputs/perf_baseline.md` 的旧阈值（rb 405ms、43 品种 21.3s）已远高于当前值，**回归门禁偏松**；建议在第 1 期把阈值更新为当前值 +20% 上限，否则性能回退不会被发现。
