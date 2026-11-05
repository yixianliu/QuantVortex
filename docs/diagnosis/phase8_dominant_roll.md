# 第 2 期改造：主力合约真正接进回测 + 目标品种主力合约模块

> 范围：`docs/diagnosis/phase7_full_survey.md` B 节 / P0-2「主力合约模块」。
> 约束遵守：未执行任何 git 写操作，未改版本号，未删既有文件，未改 `futures_quant/storage/`
> 与 `strategy/auto_evolve.py`，未写生产库；`ui/` 仅改动 `futures_quant/ui/market_overview_page.py`。
> 联网均为有界（单品种单次 ≤ 175s，超时即停并显式报错）。

## 一、结论（先看数字）

1. **「自然月近似」确实在系统性虚增换月成本**：2024-01-01~2026-09-30 同品种同区间，
   rb 计费换月 26 次 / 156.00 元，真实主力换月仅 6 次 / 36.00 元；i 为 23 次 / 230.00 元
   vs 6 次 / 60.00 元。成本被高估 3.8~4.3 倍。
2. **成交笔数完全不变**（rb 87 / i 93）：换月成本只影响权益，不影响撮合，说明这是
   「成本口径修正」而不是「策略结果美化」。
3. **策略本身仍是负收益**（rb 净收益 -0.30% → -0.29%，i -0.57% → -0.56%），修完换月后
   结论没有改变：本区间双均线在该两品种上不具备可交易边际。修正只是让亏损数字更真实。
4. **真实换月日与自然月首日差距 1~3 周**（例：rb 2024-08-30 而非 2024-09-02、
   i 2024-07-26 而非 2024-08-01），因此"在错误日期按错误手数扣费"是真实存在的偏差来源。
5. **当前主力合约已可在界面真实展示**：实测 `rb2701`（2027-01 交割，最新 3008、持仓 185.5 万手），
   近月 `rb2611`、次近月 `rb2612`，最近换月日 2026-08-28（2026-11-04 已持有 48 个交易日），
   来源=新浪、非合成、非陈旧。

## 二、改动清单（文件:行 → 问题 → 改法 → 验证）

| 文件:行 | 问题 | 改法 | 验证 |
|---|---|---|---|
| `futures_quant/data/dominant_chain.py:1-536`（新增） | `dominant.py` 有能力但生产零调用：没有任何模块把同品种多个月份合约拼成主力识别所需的宽表，回测只能按自然月近似 | 新增「合约枚举 → 有界并发抓链 → 宽表 → 主力映射（3 日稳定化）→ 换月调度表」全链路；`ChainResult` 显式区分 `missing`（未挂牌，可容忍）与 `failed`（抓取异常，判为不完整）；合成源直接抛错；报价层提供进程内 300s 缓存与 `as_of/is_stale/data_source` | `tests/unit/test_phase8_dominant_roll.py` 20 项全通过；真实新浪调用实测 rb 返回 `rb2701` |
| `futures_quant/data/dominant_chain.py:139` `fetch_contract_chain` | 单次抓 40+ 合约若串行需 3 分钟以上，且失败会拖垮整链 | 4 路并发（仍受 `http_client` 单域令牌桶约束）+ `deadline_s` / `max_contracts` 双重封顶；超时 `truncated=True` 并上报原因，已取数据保留；单合约异常记入 `failed` | 对照实验 rb/i 各 8 个窗口内换月，链抓取耗时见 JSON `chain_elapsed_s`；单测覆盖超时/异常分支 |
| `futures_quant/data/dominant_chain.py:299` `roll_schedule_from_chain` | 换月事件没有新旧合约报价就无法算价差，容易被"假装算了" | 事件带 `from_close/to_close/price_basis`；缺报价回退「最近可得收盘价」，若完全无报价则 `price_basis=missing_quote` 并计入 `missing_quotes` 统计 | 单测 `test_roll_schedule_uses_real_roll_date_and_prices`、`test_roll_schedule_missing_quote_is_explicit` |
| `futures_quant/data/dominant_chain.py:343` `build_roll_schedule` | 链不完整时若静默返回，就会退回自然月近似 | 链不完整 / 无合约 / 无换月事件 → 一律抛 `DominantChainError`，由调用方显式呈现 | `test_missing_contracts_tolerated_but_fetch_failures_are_fatal`、`test_no_contract_data_raises_explicit_error` |
| `futures_quant/backtest/backtester.py:295-365` `_is_single_contract` / `_charge_roll_cost` | 旧实现只算双边手续费，`roll_cost.py` 的价差能力从未被使用；结果里也没有成本口径 | 新增价差口径 `auto/charge/report/off`；多头按 `(新价-旧价)`、空头取反；只扣正成本（负成本=换月收益只报告不回补，保持保守）；每次换月写 `roll_events`（日期/手数/手续费/价差/口径） | `test_commission_only_for_continuous_symbol`、`test_spread_charged_for_single_contract_symbol`、`test_spread_mode_switch`、`test_no_position_roll_event_is_not_charged` |
| `futures_quant/backtest/backtester.py:410-421` 事件循环 | 调度表只能是日期集合，无法携带报价 | `roll_schedule` 允许 `{date: {from,to,from_close,to_close}}`，按日取值透传给成本层；结果新增 `roll_events/roll_cost_basis/roll_spread_reported` | `test_run_passes_schedule_and_reports_basis` |
| `futures_quant/backtest/backtester.py:219` `run()` | 同一实例多品种回测会串账 | 每次 `run` 重置换月事件与价差统计 | 单测 + 对照脚本连续两次 run 结果独立 |
| `futures_quant/config/settings.py:60-62` | 没有开关，无法做"开/关"对照 | `enable_dominant_roll=False`（默认关，保证既有锚点逐位不变）、`roll_spread_mode="auto"` | `python scripts/perf_probe.py --section anchor` → `verdict.all_ok: true` |
| `futures_quant/app/backtest_service.py:56-131` | 生产回测入口不传 `roll_schedule`，永远自然月近似；结果也不透传成本明细 | 新增 `use_dominant_roll` 参数（默认读配置）；开启时调 `build_roll_schedule`，非日线周期/链不可用直接抛错；结果透传 `roll_mode/roll_schedule_stats/roll_events/...` | 对照实验 B 路即走该链路；锚点回归通过 |
| `futures_quant/ui/market_overview_page.py:390-419` | 首屏只有连续行情，用户不知道真实主力是哪个月份合约、何时换月 | 在行情全景页新增「主力合约」卡片（并入既有页面，不新造第八页）：合约代码、交割月、近/次近月、最新价/涨跌/成交量/持仓量/结算价、最近换月日与已持有交易日 | offscreen 构建主窗口通过；单测渲染断言 |
| `futures_quant/ui/market_overview_page.py:756-841` | 主力判定需抓 8~45 个合约，主线程执行会假死；切品种可能被慢请求覆盖 | 全部放 Worker 后台线程；递增 `_dom_seq` 丢弃过期结果；加载中/失败/不可用三态文案；同一品种 300s 命中缓存 | `test_market_page_dominant_async_load_and_error_path`（真实 Worker + 事件泵）；`test_market_page_dominant_card_renders_ok_and_unavailable` |
| `scripts/research/phase8_roll_compare.py`（新增） | 没有可复现的"自然月 vs 真实换月"对照工具 | 单品种单次运行，价格序列固定用本地日线缓存（离线确定），链走新浪并落 JSON | `outputs/phase8_rb_compare.json`、`outputs/phase8_i_compare.json`（本次产物，未入库） |
| `tests/unit/test_phase8_dominant_roll.py`（新增 417 行 / 20 项） | 无回归保护 | 覆盖枚举、换月日/价格、缺失数据、成本口径四种模式、零持仓、`run` 透传、报价正常/陈旧/不可用/合成源、UI 异步与异常路径 | `python -m pytest tests/unit/test_phase8_dominant_roll.py -q` → 20 passed |

### 关键设计取舍（避免"看起来更好"的改动）

- **默认不开真实换月**：`enable_dominant_roll` 默认 `False`。原因：锚点 `verdict.all_ok` 校验
  总收益/回撤/夏普，默认切换会让既有验收基线全部漂移。开启后才有真实换月，差异见下表。
- **价差默认只报告（auto）**：回测价格序列仍是主力连续 `rb0/i0`，该序列在换月日本身已有跳空，
  再扣一次价差等于重复计费。`auto` 对连续序列只报告价差、只扣手续费；对单月合约
  （`rb2601.SHFE` 这类）才把价差计入权益。需要强制计费可 `roll_spread_mode="charge"`。
- **负的换月收益不回补现金**：`max(0, signed_spread)` 只扣正成本，backwardation 下的换月收益
  记录在 `roll_spread_reported` 但不进权益——宁可低估收益，也不制造凭空利润。
- **换月抖动抑制 3 个交易日**：成交/持仓在换月窗口常互相超越，单日排名会造成来回换月；
  短于 3 天的区间并入前一段主力。这不是交易所规则，是工程上的降噪，已在残留风险中列出。

## 三、对照实验：自然月近似 vs 真实主力换月

### 3.1 实验口径

```
python scripts/research/phase8_roll_compare.py --product rb --start 2024-01-01 --end 2026-09-30 --save outputs/phase8_rb_compare.json
python scripts/research/phase8_roll_compare.py --product i  --start 2024-01-01 --end 2026-09-30 --save outputs/phase8_i_compare.json
```

- 价格序列：本地日线缓存（`scripts/perf_probe.py` 的 `LocalDailyFeed`，与锚点同一份数据），
  两路完全相同，离线、可复现。
- 策略：`TrendFollowing`（双均线），`warmup=60`，日线，`non_trading_hours_block=False`（与锚点一致）。
- A 路（自然月近似）：`roll_schedule=None`，内核按「每自然月首个交易日」换月。
- B 路（真实换月）：新浪单月合约链 → 成交量×持仓量排名 → 真实换月日/换出手数。
- `roll_spread_mode=auto`：连续价格已含跳空，价差只报告不扣权益。

### 3.2 rb（螺纹钢，SHFE）

| 指标 | 自然月近似 | 真实主力换月 | 差异 |
|---|---|---|---|
| 成交笔数 | 87 | 87 | 0 |
| 总收益 | -0.30% | -0.29% | +0.01 pct |
| 年化收益 | -0.12% | -0.11% | +0.01 pct |
| 最大回撤 | 0.80% | 0.79% | -0.01 pct |
| Sharpe | -0.261 | -0.250 | +0.011 |
| 计费换月次数（有持仓时） | 26 | 6 | **-20** |
| 累计换月成本（元） | 156.00 | 36.00 | **-120.00（高估 4.33 倍）** |
| 端口换月事件（窗口内，含空仓日） | —（按自然月 33 个候选） | 8 | — |
| 换月价差（只报告，元） | 0（无报价，不计算） | -2,240.00 | 全部为 backwardation，对多头是收益 |

真实换月日：`2024-03-29 / 2024-08-30 / 2024-12-04 / 2025-04-02 / 2025-08-28 / 2025-12-01 / 2026-04-02 / 2026-08-28`
（其中 2024-03-29、2026-08-28 当日空仓，不产生成本，因此计费 6 次）。

### 3.3 i（铁矿石，DCE）

| 指标 | 自然月近似 | 真实主力换月 | 差异 |
|---|---|---|---|
| 成交笔数 | 93 | 93 | 0 |
| 总收益 | -0.57% | -0.56% | +0.01 pct |
| 年化收益 | -0.23% | -0.23% | 0 |
| 最大回撤 | 0.64% | 0.63% | -0.01 pct |
| Sharpe | -1.465 | -1.419 | +0.046 |
| 计费换月次数（有持仓时） | 23 | 6 | **-17** |
| 累计换月成本（元） | 230.00 | 60.00 | **-170.00（高估 3.83 倍）** |
| 换月价差（只报告，元） | 0（无报价，不计算） | -2,400.00 | 同为 backwardation |

真实换月日：`2024-03-27 / 2024-07-26 / 2024-12-09 / 2025-04-01 / 2025-08-07 / 2025-12-03 / 2026-04-02 / 2026-08-07`
（2024-03-27、2024-07-26 当日空仓，计费 6 次）。

### 3.4 差异来源（逐项解释）

1. **次数差**：自然月近似把「每月都换月」当成事实（rb 实际一年只换 3 次：01/05/10 循环），
   26 次 vs 6 次，直接放大手续费。
2. **日期差 1~3 周**：真实换月发生在成交量/持仓量迁移当天（如 rb 2024-08-30），
   自然月近似固定在月初（2024-09-02）。同一策略在 8-30 与 9-02 的持仓手数可能不同，成本随之不同。
3. **收益差异极小但不是 0**：因为价差未计入（连续价格已含跳空），差异只来自「手续费扣款日期与手数」，
   对总收益的贡献是 +0.01 pct 级别——这正好说明自然月近似的主要危害是**成本虚高**，
   而不是凭空改变行情。
4. **Sharpe 略升**：权益曲线少了 20~17 次不必要的扣费，回撤尾部抬高，Sharpe 分母变小。
   数值仍然为负，不改变「本区间无可交易边际」的结论。

## 四、界面（`futures_quant/ui/market_overview_page.py`）

位置：行情全景页「实时行情」下方新增独立卡片，不新造页面。

真实数据渲染示例（实测 rb，2026-11-04）：

```
主力合约                                   [真实月份合约]
rb2701            交割 2027-01 · 近月 rb2611 · 次近月 rb2612
[最新价 3008] [涨跌 +17 (+0.57%)] [成交量 56.6万手] [持仓量 185.5万手] [结算价 源未提供]
换月：最近换月 2026-08-28（rb2610→rb2701，已持有 48 个交易日）；下一换月日由成交/持仓迁移决定，无法预先确定
数据来源：sina · 最新 2026-11-04 00:00 ｜ 链：11 个合约（缺 0 个，0.09s）｜ 数据源未提供结算价，界面显示为空
```

三态文案（全部为实测路径）：

| 状态 | 文案 | 说明 |
|---|---|---|
| 加载中 | `正在后台加载 rb 真实主力合约（多合约链约需数秒）` + `换月：加载中…` | Worker 线程执行，UI 不阻塞 |
| 不可用 | `⚠ {原因}（不合成、不用自然月近似替代）`，数值全部置 `--` | 无数据/抓取异常/超时/合成源 |
| 陈旧 | 来源行追加 `· 陈旧数据`，并给出 `warnings` 明细 | `as_of` 超过 1 个交易日即判定 |
| 结算价缺失 | 卡片显示 `源未提供`，不填 0、不用收盘价冒充 | 新浪日线不返回结算价 |

刷新策略：切品种、`_refresh_all`（全景刷新/首屏懒加载）时触发；同一品种 300s 内命中进程内缓存；
切品种时用递增 seq 丢弃过期结果，晚到的慢请求不会覆盖新品种。

## 五、验证记录

| 验证项 | 命令 | 结果 |
|---|---|---|
| 新增单测 | `python -m pytest tests/unit/test_phase8_dominant_roll.py -q` | `20 passed`（含真实 Worker 异步加载与异常路径） |
| 既有换月/回测回归 | `python -m pytest tests/unit/test_phase1_roll_cost.py tests/unit/test_phase3_e2e_regressions.py -q` | `10 passed` |
| 回测锚点 | `python scripts/perf_probe.py --section anchor` | `verdict.all_ok: true`（rb 全窗口 231 笔 / 锚点 225 笔 / i 235 笔均未变） |
| GUI 冒烟 | offscreen 构造 `MainWindow` 并 `show/processEvents` | 通过，无 Qt 警告/崩溃 |
| 真实数据 | `dominant_quote('rb', SinaFeed(), now='2026-11-04')` | `ok=True`，`rb2701`，`data_source=sina`，`is_synthetic=False` |
| 对照实验 | 两个 JSON 见 `outputs/phase8_*_compare.json` | 数字见第三节 |

## 六、残留风险与未接入项

### 残留风险

1. **价差未计入连续序列的权益（auto 口径）**：这是刻意的防重复计费，但会让"真实成本"偏乐观，
   尤其是 backwardation 下的换月收益（rb -2240 元、i -2400 元）完全没进权益。真实落地需要
   **逐合约价格序列回测**（下一期），否则 auto 只能算"现实主义下限"。
2. **换月判定不是交易所规则**：本模块用「成交量×持仓量排名 + 3 日稳定化」推断主力，
   与行业常用的「持仓量最大」或「成交量最大」口径可能相差 1~3 个交易日，极端行情下
   `_stabilize_mapping` 还会把 2 天的短区间并入前一段，可能延迟换月 1~2 天。
3. **长窗口的链抓取受令牌桶限制**：单域 1 req/s，窗口越长所需合约越多；2.75 年窗口需 46 个合约，
   在慢网络下接近 3 分钟上限。超过 `deadline_s` 会显式失败（不会静默降级），但可用性受网络影响。
4. **新浪单月合约历史约 1 年**：更早年份的单月合约可能取不到，导致长回测链缺口；
   目前按 `missing` 计数并在界面显示，不影响已取到区间的判定，但早期区间的主力求取会失败。
5. **结算价/保证金口径未升级**：新浪日线无结算价，界面如实显示"源未提供"；
   `RiskManager` 仍按收盘价估保证金，未改成结算价（属另一条 P1，未在本期触碰）。
6. **近月判定阈值 7 天**：`active` 定义为「最后一根 K 线不早于链内最新交易日的 7 天内」，
   若某合约已在交割月停止交易但缓存仍有旧数据，可能被误列为近月。
7. **报价缓存不持久**：进程内 300s，重启后首屏需重新抓 8~11 个合约（实测冷启动 5~15s，全程后台）。
8. **`_roll_spread_reported` 为负数时不抵扣**：保守口径，会让含 backwardation 区间的回测收益偏低。

### 未接入项（明确未启用，不留半成品）

1. **回测界面的主力换月开关**：`enable_dominant_roll` 只到服务层参数，UI 未暴露勾选框
   （受"只允许改一个 ui 文件"约束，回测页未动）。因此默认 UI 回测仍是自然月近似。
2. **逐合约价格序列回测**：本期只做「连续价格 + 真实换月成本」，未做按合约拼接复权价；
   `continuous.py` 的比例复权/价差复权仍未接入回测。
3. **交易所结算价、限仓与交割月强平**：未接入，界面/回测均未使用。
4. **TqSdk/SimNow 合约链**：`tqsdk_feed` 已具备单合约能力，但链抓取仍默认新浪；
   真实账号连通性仍待 SimNow 验证。
5. **换月成本进入绩效归因**：`roll_events` 已回传，但报告模板未单列"换月成本"科目。
