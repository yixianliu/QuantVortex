# QuantVortex 全链路代码与架构诊断报告

- 项目：QuantVortex（PyQt6 期货量化桌面工作台，版本 v5.2.15）
- 诊断阶段：第一阶段（只读梳理）
- 代码基线：当前工作区快照（2026-11-04），未修改任何业务代码
- 行号说明：所有 `文件:行号` 均对应当前工作区文件，可直接跳转核对

---

## 一、结论摘要

### 1.1 五个最关键的根因

1. **“真实行情”与“合成行情”在运行时无法区分，且回退是静默的。**
   真实源对不支持周期/不支持品种/网络失败时，`MarketDataManager` 与 `Backtester` 会悄悄回退到 `SyntheticFeed`，但返回值里没有 `data_source` 标记（[market_data.py:392-401](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L392-L401)、[backtester.py:177-184](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L177-L184)）。CTP 适配层更彻底：`get_history/get_recent` 恒返回合成数据（[ctp_gateway.py:448-473](file:///d:/PythonProject/QuantVortex/futures_quant/data/ctp_gateway.py#L448-L473)），但连接成功后 `is_real=True`，界面仍显示“实盘已连接”。

2. **行情口径错误，不是“小数点误差”，而是量级/窗口错误。**
   全市场速览的“涨跌幅”取 61 根窗口的首根收盘为基准（≈60 个交易日累计），OI 变化取半窗口、资金流取 30 根累计（[market_data.py:445](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L445)、[market_data.py:451-461](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L451-L461)）。

3. **合约元数据用字符串前缀匹配，IF/IH/IC/IM 全部命中铁矿石 I。**
   `symbol.startswith(row[0])` 让 `IF.SHFE` 命中 `("I", …)`，乘数从 300 变成 100、合成基准价从 3600 变成 850（[market_data.py:420-424](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L420-L424)、[synthetic.py:119-126](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L119-L126)）。同一 bug 会污染资金流、保证金、盈亏。

4. **记账与风控的“分母/乘数”口径不一致。**
   手续费只扣 `cash`，而 `equity()` 用 `初始资金 + 已实现 + 浮盈`，完全不含手续费（[portfolio.py:118-120](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L118-L120)、[portfolio.py:158-164](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L158-L164)）；`RiskManager.check_order` 估算保证金时漏乘合约乘数（[risk_manager.py:118-121](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L118-L121)），而 `Portfolio.used_margin` 是乘了乘数的（[portfolio.py:141-143](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L141-L143)）。结果是回测收益高估 + 风控实际放宽 10~30 倍。

5. **撮合引擎存在未来函数，且涨跌停规则整体失效。**
   引擎用**当根 K 线收盘**相对开盘的涨跌幅来决定**当根开盘挂单**是否触发涨跌停（[engine.py:211-223](file:///d:/PythonProject/QuantVortex/futures_quant/core/engine.py#L211-L223)）；涨跌停状态机按“day_key 变化”重置，日线每根都重置，连续停板/扩板永远累计不起来（[price_limit.py:94-97](file:///d:/PythonProject/QuantVortex/futures_quant/data/price_limit.py#L94-L97)）。

6. **评估层指标自欺：AI 夏普用预测值当收益，GA 用含样本外的全区间做适应度。**
   [predictor.py:1033](file:///d:/PythonProject/QuantVortex/futures_quant/ai/predictor.py#L1033) 把 `val_preds` 直接当策略收益算夏普/回撤；[auto_evolve.py:1427-1429](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1427-L1429) 的适应度来自全区间回测（其中包含后续所谓的 OOS 段），[auto_evolve.py:1493-1494](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1493-L1494) 的“盈利”判定还未传 OOS 指标。

7. **“实时行情”没有真正刷新。** `LiveDataWorker` 把新数据写进自己的字典（[market_data.py:101-114](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L101-L114)），既不回传管理器，`finished` 信号也要等线程退出才发（[market_data.py:513-519](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L513-L519)），最终只是重复发旧的最后一根 K 线。

8. **主线程串行 43 个品种 HTTP。** 切换周期/分类时 `_on_period → _refresh_pano → _ensure_panorama → compute_panorama` 全在主线程执行（[market_overview_page.py:624-633](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L624-L633)、[market_overview_page.py:924-932](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L924-L932)），首次/缓存过期时最长可冻结数十秒。

### 1.2 最优先动作（按性价比排序）

| 优先级 | 动作 | 对应问题 |
|---|---|---|
| 1 | 给所有行情/回测结果加 `data_source / is_synthetic / is_stale` 元数据，禁止静默回退；UI 顶部常驻数据源水印 | P0-1 |
| 2 | 修正 `equity()` 计入手续费；`check_order` 保证金乘上 `contract.multiplier` | P0-5、P0-6 |
| 3 | 涨跌停改用“上一交易日结算价”并禁止用当根 close 决策当根 open；暂停扩板逻辑直到状态机可验证 | P0-7 |
| 4 | 乘数/基准价改为精确代码匹配；补齐品种清单并移除伪品种 | P0-3、P0-4 |
| 5 | 全市场速览与资金流改为“当日口径”，并补一条与交易所数据的对照测试 | P0-2 |

### 1.3 问题统计

| 等级 | 数量 | 说明 |
|---|---|---|
| P0 | 10 | 直接导致数据错误、回测失真、资金/风控错误、界面卡死 |
| P1 | 14 | 显著影响可信度/稳定性，但有明确绕行或影响面较局部 |
| P2 | 9 | 代码质量、死代码、交互细节、性能优化 |
| 合计 | 33 | — |

---

## 二、模块地图与职责

### 2.1 目录与职责

| 位置 | 职责 | 关键文件 | 现状判断 |
|---|---|---|---|
| `main.py` / `main.spec` | 启动入口、PyInstaller 打包 | `main.py`、`main.spec` | 正常 |
| `futures_quant/runtime.py` | 运行时装配（配置、日志、数据管理器） | `runtime.py` | 正常 |
| `futures_quant/config` | 配置模型与默认值 | `settings.py`、`../../config/settings.json` | 基本正常；默认 `source=sina`、`default_symbol=RB.SHFE` |
| `futures_quant/data` | 数据源、清洗、缓存、合约元数据、涨跌停、CTP | `market_data.py`、`sina_feed.py`、`akshare_feed.py`、`ctp_gateway.py`、`synthetic.py`、`contract_specs.py`、`continuous.py`、`dominant.py`、`price_limit.py`、`universe_validator.py` | 绝大多数问题集中在此；`continuous/dominant` 未接线 |
| `futures_quant/core` | 撮合引擎、组合账户、订单/持仓类型 | `engine.py`、`portfolio.py`、`types.py` | 撮合/记账存在 P0 |
| `futures_quant/broker` | 回测经纪商、模拟经纪商 | `backtest_broker.py`、`paper.py` | 手续费/涨跌停逻辑有缺陷 |
| `futures_quant/backtest` | 回测主流程、绩效、报告 | `backtester.py`、`roll_cost.py` | 指标可算；`roll_cost` 未接线 |
| `futures_quant/risk` | 风控与仓位 | `risk_manager.py`、`position_sizing.py` | 保证金口径错误 |
| `futures_quant/strategy` | 策略、验证、遗传进化 | `base.py`、`trend_following.py`、`martingale.py`、`volatility/garch_timing.py`、`evolver.py`、`auto_evolve.py`、`validate.py` | 信号本身因果；GA 选择/OOS 有污染 |
| `futures_quant/indicators` | 技术指标与 LRU 缓存 | `tech.py`、`cache.py` | 多为因果实现；GARCH 参数用全样本（待接线确认） |
| `futures_quant/ai` | 特征、LSTM/岭回归预测、评估、集成 | `features.py`、`predictor.py`、`validation.py` | 训练/WF 因果；评估指标失真 |
| `futures_quant/analysis` | 支撑阻力、评分卡、信号 | `support_resistance.py`、`scorecard.py` | 摆动点已限制 `n-window`，无未来确认 |
| `futures_quant/storage` | SQLite 行情/分析缓存 | `sqlite_backend.py` | 共享连接无锁 |
| `futures_quant/alerts` | 预警规则/通知 | `alerts` 包 | 未见阻塞问题 |
| `futures_quant/ui` | 主窗口、7 个业务页、图表、Web/移动端 | `main_window.py`、`market_overview_page.py`、`backtest_page.py`、`pages.py`、`chart_widget.py` | `pages.py` 含大量未接入的历史页面；主线程 IO |
| `tests/` | 单测/E2E | `tests/unit/*.py`、`tests/e2e/*.py` | 151 单测（junit 快照 0 fail / 1 error），但存在“伪覆盖”（见 P1-13） |
| `scripts/`、`tools/`、`build_tools/` | 打包、巡检、静默异常扫描 | `check.py`、`scan_silent_bail.py` 等 | 工具存在，但未纳入 CI 门禁 |

### 2.2 实际接入情况（重要）

- 主窗口导航只有 7 个页面：行情全景、预测操作、回测中心、简易回测、CTP 监控、日志、数据中心（`main_window.py`）。
- `pages.py` 中的 `MarketPage / IndicatorPage / PredictPage / PanoramaPage / ValidatePage` 没有被主窗口引用，属于历史双实现（约 1800 行死代码）。
- `data/continuous.py`、`data/dominant.py`、`backtest/roll_cost.py` 在 `futures_quant/`、`tests/` 中无任何调用方；回测直接使用新浪 `rb0` 连续合约，换月成本从未进入撮合。

---

## 三、关键数据流（文本流程图）

### 3.1 行情展示链路

```
main.py
  -> runtime 装配 Config / SQLite / MarketDataManager
  -> MarketOverviewPage
       -> MarketDataManager.connect()
            -> _build_feed(source=sina|akshare|csv|ctp|synthetic)
                 -> probe 失败或未安装依赖 => SyntheticFeed（有状态栏提示）
       -> get_bars(symbol, period)
            -> _full 缓存命中？ => 直接返回（本会话内永不过期）
            -> SinaFeed.get_history
                 period 不在 D/W => None（上层静默转合成）
                 磁盘 CSV 缓存（6h TTL）-> 失败读旧缓存（无 stale 标记）
                 内存 _mem 命中 => 直接返回（无 TTL）
            -> 空表 => _ensure_full 静默 SyntheticFeed
       -> compute_panorama(period)
            -> 43 个品种串行 get_bars
            -> ref = df.close.iloc[0]（约 60 日前）
            -> chg_pct / oi_chg / fund_flow 全部是“窗口累计”而非“当日”
       -> get_quote(symbol)
            -> mult 由 FUTURES_UNIVERSE.startswith 前缀匹配（IF 命中 I）
       -> LiveDataWorker（真实源）
            -> 每 2s 抓一次 get_recent
            -> 只写 worker 本地 self._live
            -> 线程退出时才 emit finished（期间图表不更新）
```

### 3.2 回测链路

```
BacktestCenterPage._run_backtest
  -> 构造 RiskConfig（单笔/日亏/回撤上限被改成 1e12 / 0.99，风控实质关闭）
  -> Backtester.run(symbol, start, end, period, warmup)
       -> feed.get_history
            失败/周期不支持 => SyntheticFeed（仅 logger.warning）
       -> 逐 bar：
            engine.process_bar(bar)
              1) price_limit_mgr.update(pct=(close-open)/open)   ← 用当根 close
              2) broker.match(bar, pending)                      ← 用当根 open 成交
              3) 策略 on_bar -> send_order -> risk.check_order(保证金漏乘)
              4) portfolio.update_price(close) / equity_curve
       -> flatten_all() 只是提交平仓单，循环已结束，最后一根不会成交
       -> compute_metrics(equity_curve)
            equity = 初始资金 + 已实现 + 浮盈（不含手续费）
            Sharpe/年化/回撤基于该权益序列
```

### 3.3 AI 预测链路

```
fit(symbol, period)
  -> get_bars -> IndicatorCache -> build_features
       滚动 z-score（窗口 120，因果）
  -> y = ret.shift(-1)（下一根收益，无泄漏）
  -> 60% 训练 / 20% 校准 / 20% 验证（WF 折内单独归一化）
  -> 全量重训用于线上推理
evaluate
  -> Walk-Forward（正确因果）
  -> strategy_returns = val_preds（把预测收益当真实收益）
  -> 夏普/最大回撤/胜率均由该“虚拟收益”计算
```

### 3.4 遗传进化链路

```
auto_evolve
  -> 基因 -> 全区间回测（start~end，包含后续 OOS 段）-> fitness
  -> fitness = 收益 + 夏普 + 胜率 + abs(夏普)稳定性 + 交易充足度
  -> fitness 缓存键 = (基因, 数据版本)，不含 symbol/period
  -> 选出后再 validate_strategy 做 IS/OOS 分段，但选择阶段已经看过 OOS
```

---

## 四、问题清单（P0 / P1 / P2）

> 每条格式：`文件:行号` → 证据 → 根因 → 影响 → 修复方向与验收标准。

### 4.1 P0（10 项）

#### P0-1 真实源失败静默回退合成，UI 无法识别

- 证据：
  - [market_data.py:392-401](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L392-L401)：`_ensure_full` 在真实源返回空表时直接调用 `SyntheticFeed.wrap`，仅 `logger.warning`，返回值无来源标记。
  - [backtester.py:177-184](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L177-L184)：`feed.get_history` 为 `None`（分钟线）时立刻构造 `SyntheticFeed`，回测结果不带 `data_source` 字段。
  - [ctp_gateway.py:448-473](file:///d:/PythonProject/QuantVortex/futures_quant/data/ctp_gateway.py#L448-L473)：`get_history/get_recent` 无论是否连接都返回 `self._fallback`（合成）。
- 根因：把“数据源可用”与“本品种/本周期数据可用”混为一谈；降级路径只写日志，不进入返回值/状态机。
- 影响：
  - 图形界面在断网、限流、非 D/W 周期下显示随机游走价格，但状态栏仍可能显示真实源。
  - 回测/GA 在合成数据上产出“策略业绩”，用户无法复核。
- 修复方向：
  1. 定义 `MarketFrame(df, source, is_synthetic, is_stale, as_of)`，贯穿 feed → manager → backtester → UI。
  2. 删除静默回退：真实源失败时抛 `DataUnavailable`，由 UI 明确展示“该品种暂无真实数据，是否使用演示数据？”。
  3. 回测报告页固定显示数据源徽标与覆盖率（真实/合成/缺失各多少根）。
- 验收标准：
  - 断网启动：所有图表出现“演示数据”水印；回测结果 JSON 含 `data_source=synthetic`。
  - 单元测试：mock 真实源返回空表时，`_ensure_full` 不再返回“看似真实”的 df。

#### P0-2 全市场速览的涨跌幅/OI/资金流口径错误

- 证据：[market_data.py:445](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L445) `limit = win + 60`；[market_data.py:451](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L451) `ref = df["close"].iloc[0]`；[market_data.py:458-461](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L458-L461) `oi_prev = iloc[half]`、`fund = tail(half).sum()`。
- 根因：复用了“取 61 根做指标”的窗口，却把窗口首尾差当作“当日涨跌幅”；OI/资金流同样是半窗口累计。
- 影响：全市场榜单整页失真（rb 的“涨跌幅”可能是过去 60 个交易日的累计），排序与筛选全部不可信。
- 修复方向：`chg_pct = close[-1]/close[-2]-1`；`oi_chg = oi[-1]-oi[-2]`；`fund_flow = close[-1]*vol[-1]*mult`（如需“净流入”则明确口径与单位）。
- 验收标准：与交易所/新浪当日行情对照，误差 ≤1 个最小变动价位；新增对照测试固定 3 个品种。

#### P0-3 品种清单硬编码、不完整且含非境内品种

- 证据：[synthetic.py:32-75](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L32-L75) 硬编码 43 条；包含 `PD`（钯金，境内无此期货合约，SHFE 仅有 AU/AG）；缺少约 25 个在交易品种（如 SA、UR、OI、CY、PK、PF、SH、PX、PR、CS、LH、RR、LG、FB、BB、A、B、AO、WR、SP、BR、BC、NR、LU、EC、ZC、TF、TS、TL）。
- 根因：没有从交易所合约列表/元数据服务同步品种与合约生命周期；`universe_validator.py` 只校验本地清单自洽，不校验“是否真实可交易”。
- 影响：品种选择器缺项；选中缺失品种会静默落入合成数据；非真实品种会生成“可回测”的假标的。
- 修复方向：
  1. 以交易所品种表为唯一事实源（离线 JSON + 可选在线更新），含交易所、代码、乘数、最小变动价位、上市/退市日、保证金/手续费。
  2. `universe_validator` 增加“存在性 + 生命周期 + 交易所归属”校验并接入启动自检。
  3. 删除 PD 等非境内品种。
- 验收标准：清单条数与交易所官网一致；每个品种有 `list_date/delist_date`；启动自检发现缺失/伪品种时阻断并给出清单。

#### P0-4 前缀匹配导致乘数与基准价错误（IF/IH/IC/IM 命中 I）

- 证据：
  - [market_data.py:420-424](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L420-L424)：`for row in FUTURES_UNIVERSE: if symbol.startswith(row[0])`。
  - [synthetic.py:119-126](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L119-L126)：同样用 `startswith` 取 `typical_price`，`IF` 先命中 `I`（850）。
  - 对照正确实现：[contract_specs.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/contract_specs.py) 使用精确 `_norm` 映射。
- 根因：用“前缀包含”代替“代码等值匹配”，且未按 `.` 切分交易所后缀。
- 影响：IF/IH/IC/IM 的乘数被当作 100（真实 300/300/200/200），基准价被当作 850（真实约 3600+）；资金流、保证金、盈亏、合成行情全部错位；JM 命中 J、部分品种同理。
- 修复方向：`code = symbol.split(".")[0]` 后精确查表；找不到就拒绝该品种，不得回落默认乘数（默认值只能用于明确标注的“未知合约”）。
- 验收标准：单测断言 `IF.SHFE→mult=300, 基准价量级>3000`、`IM→200`、`JM→60`；未知代码必须抛错而非静默取 10。

#### P0-5 手续费未计入权益，回测收益系统性高估

- 证据：[portfolio.py:118-120](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L118-L120) 只做 `self.cash -= commission`；[portfolio.py:158-160](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L158-L160) `equity = initial_capital + realized_pnl + unrealized_pnl`，`cash` 与 `total_commission` 均不参与。
- 根因：权益定义漏项；`realized_pnl` 按“价差×乘数”计算，本身不含费。
- 影响：所有绩效指标（收益、夏普、回撤、日亏）都没有扣费；高频/平今策略可能由盈转亏；风控 `max_daily_loss` 以未扣费权益判断，阈值失效。
- 修复方向：`equity = initial + realized + unrealized - total_commission`；`available = equity - used_margin`；或在 `process_trade` 时把手续费并入 `realized_pnl`（二选一，但必须唯一口径）。
- 验收标准：手工核算一笔“开+平（含平今）”后，`equity` 减少额 = 价差盈亏 + 双边手续费；单测锁定该等式。

#### P0-6 风控保证金漏乘合约乘数，实际放宽 10~30 倍

- 证据：[risk_manager.py:118-121](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L118-L121) `add_margin = quantity * price * margin_rate`；对照 [portfolio.py:141-143](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L141-L143) 的 `used_margin` 已乘 `mult`。
- 根因：两处保证金公式各自实现，未抽公共函数。
- 影响：rb（乘数 10）保证金被低估 10 倍，IF（300）低估 300 倍；`max_position`/可用资金校验形同虚设，回测/模拟盘可开出远超资金的仓位。
- 修复方向：抽 `margin_for(symbol, qty, price)` 单一实现（含乘数与保证金率），风控、组合、下单预估全部调用它。
- 验收标准：`rb3500×1 手×10%` 两处均返回 3500；随机 200 组品种/价格/手数的两函数输出完全一致。

#### P0-7 涨跌停判定是未来函数，且扩板状态机失效

- 证据：
  - [engine.py:211-223](file:///d:/PythonProject/QuantVortex/futures_quant/core/engine.py#L211-L223)：`pct = (bar.close - bar.open)/bar.open` → `price_limit_mgr.update(...)` → 同一次 `process_bar` 里用该 `level` 计算 `eff_up/eff_down`，然后撮合**当根开盘**挂单。
  - [price_limit.py:94-97](file:///d:/PythonProject/QuantVortex/futures_quant/data/price_limit.py#L94-L97)：跨 `day_key` 重置 `consec_days` 与 `level`。
  - [engine.py:196-202](file:///d:/PythonProject/QuantVortex/futures_quant/core/engine.py#L196-L202)：`SEALING_LEVEL=99` 时仍用 `0.04+0.02*min(level,2)=0.08`，并非“停板禁止成交”。
- 根因：把“事后才能知道的当日涨跌”用于“开盘前就应确定的限价带”；扩板本应基于**连续交易日**的停板记录，却被日线每根重置；封停只改阈值、不做方向拦截。
- 影响：涨跌停日仍可能成交（回测偏乐观）；真实连续停板/扩板永远不触发；停板日价格穿越被当成正常成交。
- 修复方向：
  1. 维护 `prev_settlement`，用 `(price - prev_settle)/prev_settle` 判断停板；
  2. 限价带只允许使用“上一交易日收盘后已知”的 level；
  3. `SEALING_LEVEL` 时同向开仓直接拒绝，反向平仓按排队规则处理；
  4. 状态机按“交易日序列”而非 `day_key` 重置，并补单测。
- 验收标准：构造“昨日结算 3500、今日开盘 3630（+3.7%）、收盘 3640（+4%）”的日线，开盘挂单不得因收盘涨幅被拒/被放行；连续 2 日停板后第 3 日限价带正确扩大。

#### P0-8 AI 指标与 GA 选择存在“伪样本外”

- 证据：
  - [predictor.py:1029-1036](file:///d:/PythonProject/QuantVortex/futures_quant/ai/predictor.py#L1029-L1036)：`strategy_returns = val_preds`，随后以此算 `sharpe/max_drawdown/hit_rate`。
  - [auto_evolve.py:1427-1429](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1427-L1429)：适应度来自 `start..end` 全区间回测。
  - [auto_evolve.py:1418-1419](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1418-L1419)：缓存键不含 `symbol/period`。
  - [auto_evolve.py:1493-1494](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1493-L1494)：`is_profitable(m)` 未传 `oos_metrics`。
- 根因：把“预测值序列”误当“撮合后的策略净值”；把“全区间绩效”当作选择依据，再在同一区间尾部报告 OOS；缓存键缺少维度导致跨品种污染。
- 影响：AI 面板的夏普/回撤/胜率不可信；GA 选出的“OOS 为正”只是选择偏差；换品种可能命中他人缓存。
- 修复方向：
  1. 评估改为“预测→建仓→按真实 bar 撮合（含费/滑点）→净值”；
  2. GA 适应度只用 IS 段（如 0~60%），OOS 段只做 gate 与报告，且记录选择次数用于多重检验校正；
  3. 缓存键加入 `symbol/period/start/end/数据版本`；
  4. 移除 `abs(sharpe)` 项（负夏普不应被奖励）。
- 验收标准：同一基因换品种不再复用缓存；报告明确“选择区间/报告区间”；AI 夏普与同参数回测夏普差异 <10%。

#### P0-9 “实时行情”链路假刷新（含 CTP 恒合成）

- 证据：
  - [market_data.py:101-114](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L101-L114)：`self._live[...]` 是 worker 自己的字典，管理器 `_live` 从未被更新；TTL 判断 `fresh_ts = time.time()-TTL; fresh_ts < 0` 恒为假。
  - [market_data.py:513-519](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L513-L519)：启动时同步 `_refresh_once()`（主线程 HTTP），且只连 `finished`（线程退出才触发）。
  - [market_data.py:538-553](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L538-L553)：回调重新发 `df.iloc[-1]` 旧数据；错误回调也发旧数据，静默降级。
  - [market_data.py:322-345](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L322-L345)：CTP tick 直接 append 成 bar，未按周期聚合，且每个 tick 都 `bar_arrived.emit`。
  - [ctp_gateway.py:448-473](file:///d:/PythonProject/QuantVortex/futures_quant/data/ctp_gateway.py#L448-L473)：历史/最新数据恒为合成。
  - [market_overview_page.py:662-668](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L662-L668)：`_on_live` 只调用 `_refresh_quote()`，即使收到新 bar 也不更新图表/K 线。
- 根因：QThread 只做“轮询”，没有“数据回传 + 增量合并 + 周期聚合”三件套；`is_real` 只代表“连接成功”。
- 影响：真实源模式下图表永远不动；CTP 模式显示“实盘已连接”但价格是随机的；tick 频率会触发主线程重绘风暴。
- 修复方向：
  1. worker 通过 `Signal(df_delta)` 回传，由管理器在锁内合并到 `_live[symbol]` 并落库；
  2. tick→1m/5m 聚合后再 emit；
  3. 未接入真实历史数据前，CTP 的 `is_real` 必须为 False，并在 UI 明确标注“仅行情连接，历史为演示”。
- 验收标准：真实源运行 5 分钟，图表新增 K 线数与实际分钟数一致；关闭网络后 10s 内 UI 出现“数据中断”提示，且不再发旧 bar。

#### P0-10 主线程串行 43 品种 HTTP / 重计算

- 证据：[market_overview_page.py:624-633](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L624-L633) `_on_period` 直接调 `_refresh_pano`（不在 Worker）；[market_overview_page.py:882-900](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L882-L900) 缓存 5s 过期后由 [market_overview_page.py:924-932](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L924-L932) 在主线程调用 `compute_panorama`；[market_data.py:445](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L445) 单次为 43 个品种串行取数。
- 根因：把“初始化预取”的 Worker 方案只用在 `_lazy_refresh_all`，交互路径遗漏。
- 影响：切换周期/分类、刷新按钮会冻结 UI，新浪限流时可达数十秒；用户会误以为程序崩溃。
- 修复方向：所有 `compute_panorama/get_quote/get_bars` 走 `run_job`；先渲染旧缓存并显示“更新中”；对 43 个品种做并发限流（3~5 并发）+ 分页渲染。
- 验收标准：点击刷新后 <100ms 内界面可交互；43 品种全量完成 <3s（本地缓存）/ <8s（网络）；无 `Application Not Responding`。

### 4.2 P1（14 项）

#### P1-1 连续合约/主力映射/移仓成本链路未接通

- 证据：[continuous.py:31-56](file:///d:/PythonProject/QuantVortex/futures_quant/data/continuous.py#L31-L56)：按日期对多合约 `groupby.mean()` 求“均价”，`back` 模式 `pass`，并把 >10% 的变动置 NaN 后 `ffill`；`join_continuous`/`identify_dominant`/`roll_cost` 在仓库内无调用方。
- 根因：连续合约功能停留在占位实现，回测直接依赖新浪 `rb0`。
- 影响：回测没有换月成本；若启用 `continuous`，价格是“多合约均价”（无经济含义），且真实涨跌停/大幅跳空会被删除。
- 修复方向：以“主力映射表 + 后复权因子”生成连续序列；换月日计入移仓成本（价差 + 双边手续费）；保留原始跳空，仅对复权因子做调整。
- 验收标准：换月日前后价差 = 新旧合约价差 × 复权因子，且可列出每次换月日期/成本；禁止出现 NaN 填充替换真实涨跌。

#### P1-2 合约代码转换对“以 0 结尾/含数字”的代码误判

- 证据：[sina_feed.py:63-74](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L63-L74)：`if len(s) >= 2 and s.endswith("0"): return s`；[akshare_feed.py:34-38](file:///d:/PythonProject/QuantVortex/futures_quant/data/akshare_feed.py#L34-L38) 的 `_to_ak_symbol` 对“末位是数字”的代码直接返回。
- 根因：用字符特征猜测“连续合约”，而非按合约规则解析月份。
- 影响：`rb2410`、`TA410` 等月合约不会被映射到连续代码，真实源查询失败 → 静默合成（与 P0-1 联动）。
- 修复方向：写 `parse_contract(symbol) -> (variety, yymm, exchange)`，只有显式 `x0` 才是连续；月合约按交易所规则（CZCE 3 位、其他 4 位）转换。
- 验收标准：`rb2410→rb2410`（按新浪月合约规则）或明确拒绝；`RB0→RB0`；`TA410→TA410`；表驱动单测覆盖 5 个交易所。

#### P1-3 结算价缺失，且未剔除“未收盘 K 线”

- 证据：`sina_feed`/`akshare_feed` 的列只保留 OHLCV+持仓，未见 `settle`；[backtest_broker.py:232-241](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtest_broker.py#L232-L241) 用 `bar.o/c` 判断与成交；持仓盯市用 `close`。
- 根因：免费源缺少结算价；代码未提供 `settlement` 字段与“交易日是否收盘”的状态。
- 影响：保证金/涨跌停/当日盈亏应按结算价，却用收盘价；盘中运行时最后一根是未完成 bar，信号会“提前”触发。
- 修复方向：数据模型增加 `settle`（缺失时显式 `settle=close` 并标注）；`get_bars` 增加 `closed_only` 参数，实时信号只用已收盘 bar。
- 验收标准：盘中最后一根标记 `is_closed=False` 且不参与信号；回测报告注明“结算价缺失，按收盘替代”。

#### P1-4 内存缓存永不失效（同一会话永久 stale）

- 证据：[sina_feed.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py) 的 `_fetch_daily` 命中 `self._mem` 直接返回；[market_data.py:242-252](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L242-L252) `_full` 只增不减且无 TTL；[akshare_feed.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/akshare_feed.py) 有 `is_stale`，新浪没有。
- 根因：磁盘缓存有 6h TTL，但内存缓存与 `_full` 没有时间戳。
- 影响：程序开着过夜后，日线永远停在启动时；盘中看不到新 bar；`is_stale` 无法告知用户。
- 修复方向：统一 `CacheEntry(df, fetched_at, ttl)`；D 级 TTL=收盘后至次日开盘、分钟级 TTL=1 分钟；缓存命中返回 `is_stale`。
- 验收标准：模拟 8 小时后再次取数会重新请求；UI 显示“数据时间”。

#### P1-5 限价挂单永不过期 + 跨品种用错 bar

- 证据：[backtest_broker.py:232-241](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L232-L241) 未校验 `order.symbol == bar.symbol`；[backtest_broker.py:244-250](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L244-L250) 未成交则 `still_pending`，无 Day 单失效。
- 根因：撮合循环按“所有 pending”遍历，未做品种过滤与订单生命周期管理。
- 影响：多品种回测时 A 品种订单可能用 B 品种价格成交；单品种回测里，一周前的限价单会在任意未来 bar 成交，回测偏乐观。
- 修复方向：`match` 先按 `order.symbol` 过滤；订单带 `valid_until`（默认当日/下一根），到期撤单并记录。
- 验收标准：构造跨品种两标的回测，A 的订单成交价必须来自 A 的 bar；限价单未成交 1 日后自动撤单。

#### P1-6 马丁格尔层数封顶失效

- 证据：[martingale.py:84](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/martingale.py#L84) 判断 `_layer <= max_layers`，而 `_layer` 已被 `min(max_layers, layer+1)` 封顶。
- 根因：边界条件用 `<=`，封顶层仍可继续开仓。
- 影响：止损后在第 4 层（base×2^4）无限重复开仓，单次回撤可击穿资金；与文档“封顶后不再开新仓”不符。
- 修复方向：改为 `_layer < max_layers`；增加“连续亏损次数/日内亏损”熔断。
- 验收标准：连续 6 次止损后，第 5 次起不再开新仓；单测断言手数序列 `1,2,4,8,16` 后停止。

#### P1-7 Worker 超时直接 `terminate()`，可能损坏状态

- 证据：[pages.py:249-255](file:///d:/PythonProject/QuantVortex/futures_quant/ui/pages.py#L249-L255) `_on_timeout` 调用 `self.terminate()`；Worker 内可能正在写 SQLite/HTTP。
- 根因：用强制杀线程替代取消协议。
- 影响：偶发数据库锁、半写文件、Qt 崩溃（terminate 不释放资源）。
- 修复方向：任务内检查 `cancelled` 标志；I/O 设超时；仅在线程已退出后清理，不调用 `terminate`。
- 验收标准：所有 `run_job` 任务都能在 100ms 内响应取消；连续取消 50 次无崩溃/锁。

#### P1-8 102 处静默吞异常，数据问题不可观测

- 证据：仓库内 `except ...:` 后紧跟 `pass/continue/return` 共 102 处（`tools/scan_silent_bail.py` 即为此巡检工具）。
- 根因：以“不要让界面崩”为理由吞掉异常，缺少错误码/提示通道。
- 影响：数据源失败、解析失败、绘图失败都表现为“没数据/没反应”，用户无法判断是网络问题还是逻辑问题。
- 修复方向：统一 `AppError(code, message, recoverable)`；UI 只捕获可恢复错误并提示；不可恢复错误写入日志并上报。
- 验收标准：静默 `pass` 数量降至 <20；断网、限流、非法合约三种场景均有明确提示。

#### P1-9 回测中心把风控参数调到“等于关闭”

- 证据：[backtest_page.py:578-580](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L578-L580)、[backtest_page.py:2637-2639](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2637-L2639)：`max_single_loss=1e12`、`max_daily_loss=1e12`、`max_drawdown=0.99`。
- 根因：为了“展示策略原始表现”绕开风控，但没有“风控开/关”显式开关与结果标识。
- 影响：回测净值与实盘（受风控约束）不可比；用户以为策略可承受该回撤。
- 修复方向：默认开启风控；提供“关闭风控（仅研究）”开关并在报告上打标；同时输出“有风控/无风控”两套指标。
- 验收标准：报告首屏显示风控状态；同一策略两套净值的差异可解释。

#### P1-10 AI 固定分割路径的命中率阈值与 WF 口径不一致

- 证据：[predictor.py:960](file:///d:/PythonProject/QuantVortex/futures_quant/ai/predictor.py#L960) 使用训练段收益中位数；[predictor.py:1008-1009](file:///d:/PythonProject/QuantVortex/futures_quant/ai/predictor.py#L1008-L1009) 固定分割路径阈值取 0。
- 根因：两套评估代码各自实现方向判定。
- 影响：同一模型在 WF 与固定分割下“命中率”不可比；报告里的“方向准确率”含义漂移（中位数平衡 vs 涨跌平衡）。
- 修复方向：抽出 `direction_metrics(pred, y, threshold_mode)`，报告注明阈值来源。
- 验收标准：同一数据两种模式产生一致的阈值与命中率定义说明。

#### P1-11 SQLite 共享连接无写锁，worker 并发写有风险

- 证据：[sqlite_backend.py:32-36](file:///d:/PythonProject/QuantVortex/futures_quant/storage/sqlite_backend.py#L32-L36) `check_same_thread=False` + WAL，但文件内未见 `threading.Lock`。
- 根因：多线程复用同一 `sqlite3.Connection`，未串行化写事务。
- 影响：并发保存行情/分析结果时出现 `database is locked` 或半事务。
- 修复方向：每线程独立连接（`threading.local`）或全局写锁 + 单写者队列。
- 验收标准：8 线程并发写 1000 条无异常；WAL 文件可正常 checkpoint。

#### P1-12 GA 适应度 `stability_score = abs(sharpe)` 奖励负夏普

- 证据：[auto_evolve.py:996](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L996)：`stability_score = 10.0 * max(min(abs(sharpe) / 1.0, 1.0), 0.0)`。
- 根因：把“绝对值大”误当“稳定”。
- 影响：稳定亏损的策略也能获得稳定性加分，诱导 GA 选择高波动负收益基因。
- 修复方向：改为 `min(0, sharpe)` 或“IS/OOS 夏普一致性（同号且差距小）”。
- 验收标准：负夏普基因的稳定性得分不得为正；单测覆盖。

#### P1-13 测试“伪覆盖”，关键缺陷无护栏

- 证据：
  - [test_backtest_consistency.py:34-53](file:///d:/PythonProject/QuantVortex/tests/e2e/test_backtest_consistency.py#L34-L53) 比较 `vectorized` 与 `event` 指标，但 [backtester.py:217-231](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L217-L231) 的“向量化”只是计算一个 `signal_shifted` 后调用事件驱动 → 测试恒真。
  - `test_continuous_join.py` 只在已单调、无缺口的数据上断言“拼接后无 >1% 跳空”，未覆盖换月/复权/涨跌停。
  - `test_roll_cost.py` 测试的模块从未被回测调用。
- 根因：测试围绕“当前实现能通过”编写，而非围绕“业务不变量”。
- 影响：151 个单测 0 失败，但 P0 缺陷全部漏网，CI 给出虚假安全感。
- 修复方向：
  1. 增加“对账型”测试：交易所样例数据、含费净值手算、涨跌停日撮合、IF 乘数。
  2. 删除/重写恒真测试；对“未接线模块”要么接线要么删。
  3. 在 CI 中运行 `tools/scan_silent_bail.py` 与覆盖率阈值（核心模块 ≥80%）。
- 验收标准：新增至少 10 条能复现本报告 P0 的失败用例（修复后转绿）。

#### P1-14 实时切换品种不重启 worker，且信号连接时序错误

- 证据：[market_overview_page.py:614-620](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L614-L620) 的 `_on_symbol` 只更新 `cur_symbol`；[market_overview_page.py:643-655](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L643-L655) 的 `_toggle_live` 先 `start_live` 再 `bar_arrived.connect`。
- 根因：实时会话与“当前品种”没有绑定生命周期。
- 影响：切换品种后图表不再更新（worker 仍在拉旧品种，回调被 `cur_symbol` 过滤丢弃）。
- 修复方向：`set_symbol` 时先 `stop_live()`，再启动并连接信号；用 `symbol` 作为 live 会话 id。
- 验收标准：连续切换 5 个品种，每个都能在 2s 内收到新 bar；旧 worker 数量不增长。

### 4.3 P2（9 项）

| 编号 | 位置 | 证据与问题 | 修复方向 |
|---|---|---|---|
| P2-1 | [portfolio.py:186](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L186) | `self.realized_pnl()` 把 float 当方法调用，`summary()` 必抛 `TypeError`；且缺 `cash/initial_cash/alert/level` 等字段。`PaperTradingPage` 未接入 NAV，暂未触发 | 改属性访问并补齐字段；纳入单测 |
| P2-2 | [backtester.py:127-145](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L127-L145) | `__init__` 对同一批成员重复初始化/重复赋值 | 删除重复块 |
| P2-3 | `ui/pages.py` | 5 个页面类未被主窗口引用（约 1800 行），与 `market_overview_page/backtest_page` 双实现 | 标注 legacy 或删除；统一到一套页面 |
| P2-4 | [price_limit.py:64](file:///d:/PythonProject/QuantVortex/futures_quant/data/price_limit.py#L64)、[price_limit.py:118-126](file:///d:/PythonProject/QuantVortex/futures_quant/data/price_limit.py#L118-L126) | `SEALING_LEVEL=99` 时 `threshold` 返回 `0.04+0.02*99=2.02`（202%），且 `detect_limit_level` 无调用方 | 删除死代码；封停用显式枚举 |
| P2-5 | [backtest_broker.py:111-130](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L111-L130) | 平今/平昨仅比较“订单日期的日历日”，未按交易日历（夜盘归属下一交易日） | 引入交易日历，使用 trading_day |
| P2-6 | [auto_evolve.py:1411-1500](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L1411-L1500) | 先全区间评估、再 `validate` 内部又跑 IS/OOS 两次回测，重复计算 | 复用一次全区间结果切分，或 IS 回测复用 |
| P2-7 | [garch_timing.py](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/volatility/garch_timing.py) | 仅开仓无平仓/退出条件，方向参数固定（不做空波动率的经济映射）；反复开仓直到仓位上限 | 增加退出/反手规则；把“波动率”与“方向”解耦 |
| P2-8 | [market_overview_page.py:882-900](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L882-L900) | 缓存键含 `category`，切换分类会重新计算全部 43 品种 | 缓存只按 `period`，分类在本地过滤 |
| P2-9 | 仓库根目录 | `nul`、`cd`、`test_design.py`、`_diag_final.py`、`test_output.txt`、各类覆盖率/日志文件残留 | 清理或移入 `tools/`，加 `.gitignore` |

---

## 五、分阶段落地计划

### 阶段 0：止血（优先 1~2 周）

- 改动范围：
  - P0-1（数据来源元数据 + 禁静默回退 + UI 水印）
  - P0-5（手续费入权益）
  - P0-6（保证金统一函数）
  - P0-7（涨跌停先“关闭错误逻辑”而非“修好错误逻辑”：停用扩板、改用昨日结算价、封停禁止同向开仓）
  - P0-9（实时 worker 回传 + 周期聚合 + CTP is_real=False）
  - P0-10（交互路径全部 Worker 化）
- 风险：
  - 回测历史结果会变化（应视为“纠错”，需在报告页标注版本差异）。
  - 禁用合成回退会导致部分品种/周期“无数据”，需要 UI 明确引导。
- 回归测试点：
  - 断网、限流、空数据三种场景的 UI 提示；
  - 手算手续费/保证金对账；
  - 涨跌停日构造用例；
  - 43 品种刷新耗时与 UI 响应性（手动 + 计时断言）。

### 阶段 1：数据底座（2~3 周）

- 改动范围：P0-2、P0-3、P0-4；P1-1~P1-5；新增“交易所品种/合约元数据”离线表与校验器。
- 风险：
  - 品种清单变更会影响自选/缓存键，需要迁移；
  - 引入连续合约与复权因子会改变回测基准，需保留“原始 rb0”模式对照。
- 回归测试点：
  - 品种数量/交易所归属/生命周期与官网一致；
  - IF/IH/IC/IM/JM 乘数与基准价；
  - 全景当日口径与交易所对照；
  - 换月日期、复权因子、移仓成本可回溯。

### 阶段 2：算法可信度（2~3 周）

- 改动范围：P0-8、P1-6、P1-9、P1-10、P1-12、P1-13。
- 风险：
  - 现有很多“优秀”策略指标会显著下降（这是预期内的去偏）；
  - GA 运行时间可能上升（需要做 IS 缓存与并行）。
- 回归测试点：
  - AI 指标 vs 撮合回测一致性；
  - 同一基因不同品种缓存隔离；
  - GA 选择区间与报告区间严格分离；
  - 新增 10 条失败用例（修复前红、修复后绿）。

### 阶段 3：工程化与交互（2 周）

- 改动范围：P1-7、P1-8、P1-11、P1-14；P2 全量清理；CI 门禁（静默异常扫描、覆盖率、性能基准）。
- 风险：
  - 错误提示变多会改变用户习惯，需要分级（阻断/警告/信息）。
  - 删除 legacy 页面需确认无外部调用。
- 回归测试点：
  - 取消任务 50 次无崩溃；
  - 8 线程并发写库；
  - 连续切换 5 个品种的实时刷新；
  - 页面导航与 7 个主页面冒烟。

---

## 六、待验证项与验证方法

| 编号 | 待验证内容 | 验证方法 |
|---|---|---|
| V-1 | 新浪日线字段 `p` 是否确为持仓量、是否存在结算价字段 | 抓取原始 JSON 对照官方文档；用同一交易日与交易所结算价比对 |
| V-2 | 新浪 `rb0` 的换月规则与覆盖品种范围 | 对 43+ 个品种逐一 probe；记录空表/异常品种，形成“真实源覆盖矩阵” |
| V-3 | 境内品种完整数量与代码（用于 P0-3 验收基线） | 以上期所/大商所/郑商所/中金所/广期所官网合约列表为准，生成基线 JSON |
| V-4 | 股指期货平今手续费率与 `_CLOSE_TODAY_FREE` 是否成立 | 对照交易所手续费公告；用真实成交回单核对 |
| V-5 | CTP 历史数据是否可通过柜台/行情接口获取 | 在仿真环境调用 Trade/History 接口验证；否则必须把 `is_real` 置 False |
| V-6 | 夜盘成交归属交易日（P2-5） | 用交易所交易日历与结算单核对 21:00 后的成交日期 |
| V-7 | GARCH 指标全样本拟合是否被策略使用 | 全局搜索 `garch(` 调用；若使用则改为滚动窗口重估 |

---

## 七、诊断方法说明（可复核）

- 全程只读：未修改任何业务代码、未删除文件、未执行 git 破坏性命令。
- 检索：`Select-String` + 文件逐段阅读；对关键函数逐一打印带行号的源码，避免凭印象引用。
- 静态可判定项（如 `summary()` 的 float 调用、乘数缺少 `mult`）已通过源码直接确认；未通过运行期复现的项已在正文标注“待验证”并给出方法。
- 测试基线：`tests/_junit_unit.xml` 快照显示 151 个单测、0 failures、1 error；`tests/_junit_full.xml` 显示 293 个测试、1 error。测试“绿”与本报告 P0 结论的冲突，本身即为 P1-13 的证据。
