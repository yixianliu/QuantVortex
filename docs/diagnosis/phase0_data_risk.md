# 阶段 0（止血）实施记录：数据源可信化 + 风控账务

> 范围：仅两项 P0 —— **数据源可信化**、**风控账务一致**。
> 明确暂缓（本轮未改动）：涨跌停规则（P0-7）、乘数精确匹配（P0-3/P0-4）、速览当日口径（P0-2）、`roll_cost`/`dominant` 接入（P1-1）。
> 约束遵守：未 git commit、未改版本号、未删文件、未修改 `data/` 内数据与数据库。

---

## 一、改动前后回测对照（基线锚点）

**统一口径**：`rb.SHFE` · 日线 `D` · `2020-01-01 ~ 2026-09-30` · `TrendFollowing`（默认参数）· `warmup=60` · 初始资金 100 万 · 合约规格取 `build_contract("rb.SHFE")`（乘数 10 / 保证金率 10% / 手续费 3 元/手）· 风控按「不勾选风控」放松、`non_trading_hours_block=False`（日线 bar 时间为 00:00，否则全量拒单）。

| 指标 | 改动前（旧 equity 口径） | 改动后（新 equity 口径） | 变化 |
|---|---|---|---|
| 成交笔数 | 231 | **231** | 0 |
| 总收益 | -0.65% | **-0.72%** | -0.07pp |
| Sharpe | -0.107 | **-0.119** | -0.012 |
| 最大回撤 | 3.01% | **3.04%** | +0.03pp |
| 期末权益 | 993,530.00 | **992,837.00** | -693.00 |

- 成交笔数完全不变，说明差异**只来自手续费入账**：231 笔 × 3 元/手 = **693 元**，与期末权益差额精确一致。
- 数据来源：`data_source=sina`、`is_synthetic=False`、`is_stale=False`、`as_of=2026-09-30`、`note=命中磁盘缓存`（`data/sina_cache/rb0.csv`，1636 根）。
- 与用户给出的锚点（225 笔 / -0.63% / -0.106 / 3.01%）对照：**Sharpe 与 MDD 基本一致，收益差 0.02pp，成交多 6 笔**。该 6 笔差异在「改动前」复现时同样存在（231 笔），属锚点生成时的数据缓存/配置差异，**不是本次改动引入**。本次改动的净效应可从同环境「前→后」差值精确核对（-693 元手续费）。
- 复现方式：临时脚本（项目仓库外）分别以当前代码、以及运行时 monkeypatch 旧 `Portfolio.equity`（`initial_capital + realized_pnl + unrealized_pnl()`）跑同一区间，未改任何文件。

---

## 二、问题 → 改动 → 验证 → 残留风险

### P0-1 真实源失败静默回退合成，UI 无法识别

**改动文件:行**

| 位置 | 修复内容 |
|---|---|
| [base.py:30-64](file:///d:/PythonProject/QuantVortex/futures_quant/data/base.py#L30-L64) | 新增统一来源元数据契约 `PROVENANCE_KEYS = (data_source, is_synthetic, is_stale, as_of, note)`；`attach_provenance()` 写入 `DataFrame.attrs`（失败不影响主流程）；`get_provenance()` 对未标注老数据返回安全默认值（`unknown / False / False / None / ""`），**保证向后兼容**。 |
| [base.py:67-97](file:///d:/PythonProject/QuantVortex/futures_quant/data/base.py#L67-L97) | `provenance_text()/provenance_label()` 生成统一中文说明（新浪日线 / AkShare / 合成行情(模拟) / CTP历史回退 / 来源未知），并附加「模拟数据」「过期缓存」「时间」。 |
| [base.py:110-125](file:///d:/PythonProject/QuantVortex/futures_quant/data/base.py#L110-L125) | 新增可插拔数据源注册表 `register_feed / get_feed_factory / registered_feeds`，为未来 TqSdk / 真实 CTP 留槽（本轮不实现）。 |
| [synthetic.py:26](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L26)、[320](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L320)、[336](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L336) | 合成行情返回前强制标注 `data_source=synthetic / is_synthetic=True / note=合成行情 / as_of=最后一根`。 |
| [sina_feed.py:55-56](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L55-L56)、[143-148](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L143-L148) | 新增每品种 `_stale/_note` 状态；`_ensure_prov_state()` 兼容测试/外部构造的极简实例。 |
| [sina_feed.py:160-200](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L160-L200) | 命中磁盘缓存 → `is_stale=False, note=命中磁盘缓存`；网络成功 → 清空 note；网络失败回退旧缓存 → `is_stale=True, note=网络失败，使用陈旧磁盘缓存`；无缓存 → `is_stale=True, note=网络失败且无可用缓存`（空表仍标注，不静默）。 |
| [sina_feed.py:215-231](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L215-L231) | `get_history` 返回前统一 `attach_provenance`（含空表分支），`as_of` 取实际最后一根日期。 |
| [akshare_feed.py:200-216](file:///d:/PythonProject/QuantVortex/futures_quant/data/akshare_feed.py#L200-L216)、[229-241](file:///d:/PythonProject/QuantVortex/futures_quant/data/akshare_feed.py#L229-L241) | 周期不支持时回退合成，但**显式**标注 `synthetic + is_synthetic=True + note="akshare 不支持周期 {period}，回退合成"`；真实数据标注 `akshare` 与 `is_stale`。 |
| [market_data.py:252](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L252)、[262](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L262)、[275](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L275) | 新增 `requested_source`、`feed_error`、`last_provenance`；连接失败原因对外可读。 |
| [market_data.py:425-441](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L425-L441) | 真实源空表 → 回退合成时显式 `attach_provenance(synthetic, is_synthetic=True, note="{源} 无 {周期} 周期数据，回退合成（{原因}）")`；自定义 feed 未标注则补标当前源。 |
| [market_data.py:445-454](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L445-L454) | `get_bars` 在 `tail().reset_index(drop=True)` 后**显式回写 attrs**（防切片丢元数据），并同步 `last_provenance`。 |
| [market_data.py:538-541](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L538-L541) | 全景结果附加来源统计 `synthetic_count/stale_count/sources` 与水印 note（如「3/43 个品种为合成数据」）。 |
| [backtester.py:26](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L26)、[147](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L147)、[181-213](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L181-L213) | 回测结果新增 `data_source/is_synthetic/is_stale/as_of/data_note`；真实源不支持该周期回退合成时显式标注。 |
| [market_overview_page.py:185-188](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L185-L188)、[854-869](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L854-L869)、[959](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L959) | 行情页工具栏新增常驻水印 `数据来源：—`；报价与全景刷新时更新；合成/陈旧用警示色加粗。 |

**验证方式与结果**

- 新增 `tests/unit/test_phase0_data_provenance.py`（5 条）：
  - `test_synthetic_frame_is_marked`：合成必带 `is_synthetic=True`；
  - `test_unmarked_frame_defaults_are_backward_compatible`：老 DataFrame 读取不抛异常；
  - `test_manager_marks_fallback_as_synthetic`：真实源返回 `None` → 回退结果 `is_synthetic=True` 且 note 含「回退合成」；
  - `test_manager_preserves_real_provenance_after_slicing`：切片后 attrs 不丢；
  - `test_ctp_label_does_not_claim_real_history`：CTP 已连接但历史为合成时，标签含「历史K线为合成」。
- 实跑：`34 passed`（新 9 条 + 相关既有 25 条，见第四节）。
- 回测端来源核对：`data_source=sina, is_synthetic=False, is_stale=False, as_of=2026-09-30`。

**已知残留风险**

1. `SinaFeed` 的**内存缓存**仍不失效（P1-4 未在本轮修复）：同一会话内 `_mem` 命中后不再联网，`note` 保留首次取数时的标记。
2. `get_quote` 的价格/资金流仍为旧口径（P0-2 暂缓），仅补充来源字段，不改数值。
3. 全景 `is_synthetic` 是聚合布尔值，未做逐品种标记；UI 只能看到「N/43 个品种为合成」的汇总。
4. 回测遇到**空 DataFrame（非 None）**时抛出 `ValueError("未取到行情数据")`，属「明确错误」路径，但错误信息未携带来源/时效。
5. 其他页面（K 线页、AI 页）尚未接入常驻水印；本轮只保证速览页有一处常驻提示。

---

### P0-9 CTP 返回合成数据却报告「实盘已连接」

**改动文件:行**

| 位置 | 修复内容 |
|---|---|
| [ctp_gateway.py:36](file:///d:/PythonProject/QuantVortex/futures_quant/data/ctp_gateway.py#L36)、[180](file:///d:/PythonProject/QuantVortex/futures_quant/data/ctp_gateway.py#L180) | 新增 `history_real=False`，显式区分「连接状态」与「历史数据真实性」。 |
| [ctp_gateway.py:465-484](file:///d:/PythonProject/QuantVortex/futures_quant/data/ctp_gateway.py#L465-L484) | `get_history/get_recent` 回退合成时标注 `data_source=ctp-fallback / is_synthetic=True / note=CTP历史K线未接入，回退合成`。 |
| [ctp_gateway.py:486-493](file:///d:/PythonProject/QuantVortex/futures_quant/data/ctp_gateway.py#L486-L493) | `source_label`：连接时返回 `CTP(SimNow/实盘)已连接 · 历史K线为合成`；未连接返回 `CTP未连接·回退合成`，不再单向宣称实盘。 |
| [market_data.py:333-336](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L333-L336) | 管理器层同步追加「· 历史K线为合成」并写 `feed_error="CTP 历史K线回退合成"`。 |

**验证方式与结果**

- `test_ctp_label_does_not_claim_real_history`（新增）通过：`connected=True` 时标签仍含「历史K线为合成」，历史结果 `is_synthetic=True / data_source=ctp-fallback`。
- 未实盘连接 CTP 柜台（无 SimNow 账号/前置），仅覆盖代码路径与标签语义。

**已知残留风险**

- **真实 CTP 历史 K 线仍未接入**，本轮只做「不冒充」：CTP 模式下的历史数据依旧是合成行情，实盘实时 Tick 链路未变。
- `CTPFeed.connect()` 真实握手未在本机验证，标签修复不代表连通性修复。

---

### P0-5 手续费未计入权益，回测收益系统性高估

**改动文件:行**

| 位置 | 修复内容 |
|---|---|
| [portfolio.py:59](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L59) | 新增 `total_commission` 累计字段。 |
| [portfolio.py:122](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L122) | 成交时 `cash += realized - commission`：**手续费在现金侧唯一入账**，不再出现「cash 扣了、equity 没扣」的双份真值。 |
| [portfolio.py:163-167](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L163-L167) | `equity()` 统一为 `cash + unrealized_pnl()`，即 `初始资金 + 已实现盈亏 - 累计手续费 + 浮动盈亏`。 |
| [portfolio.py:190-198](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L190-L198) | `summary()` 补 `total_commission / cash / initial_cash`，风险度仍按 `used_margin / equity`。 |
| [portfolio.py:195](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L195) | 顺带修复诊断 P2-1：`round(self.realized_pnl(), 2)`（把 float 当方法调用、必抛 `TypeError`）改为属性访问。 |

**验证方式与结果**

- 新增 `tests/unit/test_phase0_accounting.py`（4 条）：
  - 开仓后 `equity = 初始资金 - 手续费`；
  - 平仓后 `equity = 初始 + 已实现 - 双边手续费`，且 `equity == cash`；
  - `summary()` 各字段与属性一致、不抛异常；
  - `check_order` 保证金乘乘数（与 P0-6 共用）。
- 回测对照：期末权益 993,530 → 992,837（差额 693 = 231 笔 × 3 元），数值可手工复核。

**已知残留风险**

- 手续费模型仍是「按手固定元」，未改为「成交金额比例」；`close_today` 折扣依赖合约规格（RB 规格为 0，即平今免收）。
- `broker/paper_portfolio.py` 是另一套并行账务实现（模拟盘），本轮未统一到 `Portfolio`；两套账的口径仍可能漂移。
- 手续费只进 `cash`，`realized_pnl` 本身仍不含费；下游若直接读 `realized_pnl` 做收益展示，需改用 `equity`（本轮未逐一排查 UI 展示）。

---

### P0-6 风控保证金漏乘合约乘数

**改动文件:行**

| 位置 | 修复内容 |
|---|---|
| [risk_manager.py:118-128](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L118-L128) | `add_margin = quantity × price × contract.multiplier × margin_rate`；无合约时回落 `portfolio._multiplier(symbol)`，与 `Portfolio.used_margin()` 同口径。 |
| [portfolio.py:136-148](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L136-L148) | 复核：`used_margin` 已按 `手数 × 标记价 × 乘数 × 保证金率`，无需改动。 |
| [paper_portfolio.py:73](file:///d:/PythonProject/QuantVortex/futures_quant/broker/paper_portfolio.py#L73)、[149](file:///d:/PythonProject/QuantVortex/futures_quant/broker/paper_portfolio.py#L149)、[191](file:///d:/PythonProject/QuantVortex/futures_quant/broker/paper_portfolio.py#L191) | 复核：模拟盘保证金均乘乘数，无需改动。 |
| [backtest_broker.py:282-300](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L282-L300) | 复核：成交 `Trade.multiplier` 取自 `contract.multiplier`，无需改动。 |

**验证方式与结果**

- `test_risk_manager_margin_multiplies_contract_multiplier`（新增）通过：初始 1 万、RB 4000 元、5 手 → 保证金 20,000 元（旧实现仅 2,000 元），订单被「可用资金不足」拒绝。
- 蝴蝶效应检查：`on_new_bar` 的 `risk_degree = used_margin / equity` 使用同一 `equity` 新口径；`margin_warn_ratio=0.80`、`margin_halt_ratio=0.95` 阈值未改数值，但因分子分母同时校正而**实际收紧**，与真实保证金一致。

**已知残留风险**

- 保证金风险度/强平阈值仍用**标记价（收盘价）**而非结算价（P1-3 暂缓），日内与隔夜口径存在偏差。
- 风控没有统一的 `margin_for()` 公共函数，仍是「风控一处 + 组合一处 + 模拟盘一处」；本轮只保证三处都乘乘数，未抽象收敛（避免大改）。
- `check_order` 的价格来源为 `_current_prices` 或限价，市价单在首批成交前可能取到 0 → 保证金按 0 估算；该行为沿用旧逻辑，未在本轮改动。

---

## 三、附带修正（与本轮两项直接相关，已披露）

| 位置 | 内容 | 原因 |
|---|---|---|
| [sina_feed.py:65-79](file:///d:/PythonProject/QuantVortex/futures_quant/data/sina_feed.py#L65-L79) | `_to_sina` 仅对纯字母品种代码追加 `0`；月份合约（`rb2401`）原样返回 | 旧逻辑会把 `rb2401` 拼成 `rb24010`，真实源查不到 → 被误判为「空数据」→ 静默合成（与 P0-1 直接联动）。属数据源可信化前置修正。 |
| [akshare_feed.py:82-83](file:///d:/PythonProject/QuantVortex/futures_quant/data/akshare_feed.py#L82-L83) | 保留 `settle`（结算价）字段 | 为下一轮 P0-7「涨跌停改用上一交易日结算价」预留数据基础；本轮不改变涨跌停逻辑。 |

---

## 四、测试执行记录

命令：

```powershell
python -m pytest tests/unit/test_phase0_data_provenance.py tests/unit/test_phase0_accounting.py `
  tests/unit/test_market_data_feeds.py tests/e2e/test_margin_calc.py `
  tests/e2e/test_broker_rules.py tests/e2e/test_price_limit.py `
  tests/e2e/test_roll_cost.py tests/e2e/test_dominant_contract.py -q
```

结果：**34 passed**（0 failed）。其中：

| 测试文件 | 条数 | 说明 |
|---|---|---|
| `tests/unit/test_phase0_data_provenance.py` | 5 | 本轮新增，数据源可信化 |
| `tests/unit/test_phase0_accounting.py` | 4 | 本轮新增，账务与保证金 |
| `tests/unit/test_market_data_feeds.py` 等 6 个既有文件 | 25 | 相关回归，确认无破坏 |

未运行全量 `tests/` 的原因：仓库存在大量 e2e/smoke 脚本（部分依赖 GUI/网络/长耗时），与本轮改动无关；已覆盖直接受影响的行情、撮合、风控、组合、移仓成本模块。

---

## 五、影响面与向后兼容

1. `DataFrame.attrs` 新增 5 个键：读取方未适配时完全无感；`get_provenance()` 对缺失键返回默认值，不抛异常。
2. `Backtester.run()` 返回 dict **新增** 5 个键（`data_source/is_synthetic/is_stale/as_of/data_note`），原有键不变。
3. `MarketDataManager.get_quote()` 返回 dict **新增** 5 个键，原有价格/资金流字段不变。
4. `Portfolio` 新增属性 `total_commission`；`summary()` 新增 3 个字段，原有字段保留。
5. `CTPFeed.source_label` 文案变化（新增「· 历史K线为合成」），仅影响展示。
6. 所有改动均为「增量字段 + 默认值」，无签名破坏、无删除 API。

---

## 六、遗留问题（明确未做）

| 项 | 状态 | 原因 |
|---|---|---|
| P0-7 涨跌停未来函数 / 扩板状态机 | 未做 | 用户本轮要求暂缓 |
| P0-3 / P0-4 乘数精确匹配、品种表补齐、移除伪品种 `PD` | 未做 | 同上 |
| P0-2 速览/资金流当日口径 | 未做 | 同上（本轮只加来源水印，未改数值口径） |
| P1-1 `roll_cost` / `dominant` 接入 | 未做 | 同上 |
| CTP 真实历史 K 线 / 实时 Tick | 未做 | 仅修「不冒充实盘」标签，接入需真实柜台与账号 |
| P1-14 实时 worker 停旧线程 / 假刷新 | 未做 | 超出本轮两项范围 |
| P0-10 主线程串行 43 品种 | 未做 | 超出本轮两项范围 |
| P1-4 Sina 内存缓存不失效 | 未做 | 仅通过 `is_stale/note` 暴露风险，未改缓存策略 |
