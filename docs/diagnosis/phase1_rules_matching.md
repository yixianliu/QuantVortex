# 第二轮：规则与撮合正确性修复报告

- 范围：涨跌停与撮合（P0）、乘数与基准价精确匹配（P0）、速览/资金流当日口径（P1）、换月成本接入（P1）
- 约束遵守：未 commit、未改版本号、未删除文件、未改动 `data/` 数据与数据库；API 均保留向后兼容默认值
- 基线：`rb.SHFE` 日线 2020-01-01 ~ 2026-09-30，TrendFollowing，warmup=60，初始资金 100 万

---

## 1. 涨跌停与撮合规则（P0-7 / P1-5）

### 问题
| 编号 | 问题 | 旧位置 |
|---|---|---|
| P0-7 | 涨跌停用「当根 `(close-open)/open`」决定当根开盘能否成交，属未来函数 | `futures_quant/broker/backtest_broker.py` `match()` |
| P0-7 | 涨停/跌停时买卖方向语义写反：涨停拒绝了「平多（卖出）」，却放行「平空（买入）」 | 同上 |
| P1-5 | 挂单永不过期，陈旧限价单长期滞留 | 同上 |
| P1-5 | 撮合遍历全部 pending，未按品种过滤，可跨品种串单成交 | 同上 |
| P0-7 | 扩板状态机按当日涨跌幅累计，无法用交易所规则核对，且接在当根撮合中 | `futures_quant/core/engine.py` `process_bar()` |

### 修复
1. **昨结算价基准**：涨跌停价 = `上一交易日结算价 × (1 ± 幅度)`，仅比较**当根开盘价**：
   - 开盘 ≥ 涨停价 → 买入方向（开多 / 平空）拒单；
   - 开盘 ≤ 跌停价 → 卖出方向（开空 / 平多）拒单。
   - 位置：[backtest_broker.py:225-238](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L225-L238)、[backtest_broker.py:267-279](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L267-L279)
2. **昨结算价注入**：`Bar` 新增可选字段 `settle / prev_settle`（默认 `None`，向后兼容）；`Backtester._prev_settle_by_index()` 按交易日分组，取上一交易日最后一根 `settle`（缺失回退 `close`）。夜盘（18:00 后）归属下一交易日。
   - 位置：[types.py](file:///d:/PythonProject/QuantVortex/futures_quant/core/types.py)、[backtester.py:229-250](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L229-L250)
   - 未注入 `prev_settle` 时**不判涨跌停（fail-open）**，避免用上一根分钟收盘冒充结算价而错杀正常委托。
3. **挂单过期**：`Order.bars_alive` 默认 0；同品种每根 K 线未成交累加，达到 `pending_expire_bars`（配置默认 5）即置 `CANCELLED`。
   - 位置：[backtest_broker.py:255-265](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L255-L265)、[settings.py:56](file:///d:/PythonProject/QuantVortex/futures_quant/config/settings.py#L56)
4. **品种过滤**：`order.symbol != bar.symbol` 的委托原样保留，不参与本根撮合。
   - 位置：[backtest_broker.py:241-245](file:///d:/PythonProject/QuantVortex/futures_quant/broker/backtest_broker.py#L241-L245)
5. **扩板状态机停用**：`engine.process_bar()` 不再调用 `PriceLimitManager.update()`，撮合只用基准幅度；`limit_level` 入参仅为 API 兼容保留。`price_limit.py` 模块与类均加「⚠️ 未启用」标注。
   - 位置：[engine.py:212-216](file:///d:/PythonProject/QuantVortex/futures_quant/core/engine.py#L212-L216)、[price_limit.py:1-10](file:///d:/PythonProject/QuantVortex/futures_quant/data/price_limit.py#L1-L10)

### 验证
- 新增 `tests/unit/test_phase1_price_limit_matching.py`（5 项，全通过）：
  - 昨结算 100、开盘 104、收盘 90 → 买入必须拒单（旧实现会放行）；
  - 开盘 100、收盘 104 → 买入必须成交（旧实现会误拒，证明消除未来函数）；
  - 跌停仅买入方向成交；
  - A 的委托不会被 B 的 K 线撮合；
  - 限价单 2 根未触发即撤单；
  - 夜盘 21:00 的昨结算取上一交易日日盘结算价，而非夜盘自身。
- 既有 `tests/e2e/test_broker_rules.py::test_limit_reject` 已按新语义重写（旧断言本身固化了错误行为），通过。
- `tests/e2e/test_price_limit.py`、`test_arbitrage_linkage.py`、`test_core.py` 通过。

### 残留风险
- 分钟线回测的「交易日」按 `18:00` 切分，遇到长假前夜盘/临时休市可能与交易所交易日历不完全一致；日线回测不受影响。
- 停板判定只看开盘价，未模拟盘中封板/排队成交；这是回归「无未来函数」后的保守下限。
- `PriceLimitManager` 仍保留代码，禁止在完成交易所规则核对前重新接线。

---

## 2. 乘数与基准价精确匹配（P0-3 / P0-4）

### 问题
| 编号 | 问题 | 旧位置 |
|---|---|---|
| P0-4 | `startswith(row[0])` 前缀匹配：`IF/IH/IC/IM` 命中 `I`（铁矿），`JM` 命中 `J` | `data/market_data.py` `get_quote()`、`data/synthetic.py` 生成器 |
| P0-4 | `contract_specs._norm()` 仅剥离末尾 `0`，`IF2601` 等具体合约无法归一化 | `data/contract_specs.py` |
| P0-3 | 品种清单混入伪品种 `PD`（钯金，境内无此期货） | `synthetic.FUTURES_UNIVERSE`、`contract_specs._SPEC_TUNING` |
| P0-3 | 多个真实在交易品种缺失（SA/UR/OI/CS/LH/AO/BC/NR/LU/EC/TF/TS/TL 等） | 同上 |

### 修复
1. 新增精确匹配工具 `universe_code()` / `find_universe_row()`：取字母段（`rb2410`→`RB`、`IF2601`→`IF`），建立 `代码→行` 字典，**彻底移除 `startswith`**。
   - 位置：[synthetic.py:111-140](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L111-L140)
2. `get_quote()` 与合成行情生成器、`_mode_for()` 全部改用精确匹配。
   - 位置：[market_data.py:534-538](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L534-L538)、[synthetic.py:304](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L304)
3. `contract_specs._norm()` 改为字母段精确归一化，`IF/IH/IC/IM` 不再命中 `I`。
   - 位置：[contract_specs.py:139-152](file:///d:/PythonProject/QuantVortex/futures_quant/data/contract_specs.py#L139-L152)
4. 品种表补齐 30 个真实品种（郑商所 UR/OI/CY/PK/PF/PX/PR/ZC、大商所 A/B/CS/LH/RR/LG/FB/BB、上期所 AO/WR/SP/BR、上期能源 BC/NR/LU/EC、中金所 TF/TS/TL、郑商所 SA/SH），并移除伪品种 `PD`。
   - 位置：[synthetic.py:70-110](file:///d:/PythonProject/QuantVortex/futures_quant/data/synthetic.py#L70-L110)、[contract_specs.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/contract_specs.py)

### 验证
- 新增 `tests/unit/test_phase1_contract_specs.py`（5 项，全通过）：
  - 表驱动 27 个品种的「乘数 / 最小变动价位」对照交易所公开合约细则；
  - 基准价量级表（IF 2800-4800、I 500-1300、JM 900-3000、CU 40000-90000、AU 300-900、EC 800-3000）；
  - 回归用例：`IF/IH/IC/IM` 乘数分别为 300/300/200/200，`I` 为 100，`JM` 为 60、`J` 为 100；`IF2601`、`i2409`、`rb2410` 精确命中；
  - `PD.SHFE` 返回显式 `UNKNOWN`（不再命中任何品种）。

### 残留风险
- 新增品种的 `typical_price` 是公开行情量级参考值，不是交易所合约细则字段；已用区间断言而非精确值。
- 未知代码仍返回 `symbol="UNKNOWN"` + 默认乘数 10，而非直接抛错（为保持既有调用方兼容）；若后续要严格执行「未知即拒绝」，需单独评估影响面。
- 部分新上市品种（PX/PR/SH/LG 等）保证金率与手续费沿用分类默认值，未逐合约核对。

---

## 3. 速览与资金流当日口径（P0-2）

### 问题
| 编号 | 问题 | 旧位置 |
|---|---|---|
| P0-2 | 全景涨跌幅基准 = 窗口首根；OI 变化 = 半窗口；资金流 = 半窗口累计 | `market_data.compute_panorama()` |
| P0-2 | 速览资金流 = 近 20 根累计；且全景误用请求周期而非真实周期，可能回退合成数据 | `market_data.get_quote()` / `compute_panorama()` |

### 修复
1. 新增 `trading_day_key()`：夜盘（≥18:00）及凌晨时段归属下一交易日。
2. 新增 `daily_snapshot(df, mult)`：统一输出
   - 当日涨跌幅 = 当日最后价 / **上一交易日收盘** - 1；
   - 当日 OI 变化 = 当日最后 OI - **上一交易日最后 OI**；
   - 当日资金流 = Σ(当日每根 `(close-open) × volume × 乘数`) / 1e8；
   - 当日成交量；`has_prev_day` 标记无上一交易日的情况。
   - 位置：[market_data.py:137-207](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L137-L207)
3. `get_quote()` 与 `compute_panorama()` 全面改用 `daily_snapshot()`；全景取数修正为真实周期 `eff`，并按周期放大取数窗口以覆盖上一交易日。
   - 位置：[market_data.py:520-552](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L520-L552)、[market_data.py:564-606](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L564-L606)
4. 新增返回字段：`oi_prev / oi_chg / oi_chg_pct / has_prev_day / trading_day / oi_chg_abs`（新增字段，旧字段全部保留）。

### 验证
- 新增 `tests/unit/test_phase1_daily_snapshot.py`（6 项，全通过）：
  - 窗口首根 90、昨收 105、当日 108 → 涨跌幅取 108/105-1，而非 108/90-1；
  - OI 取当日最后 vs 上一交易日最后，资金流只累计当日；
  - 夜盘 21:00 归属下一交易日，涨跌幅对比上一交易日收盘，不产生假涨跌；
  - 跨周末/休市仍以最后可用交易日为基准；
  - 仅一日数据时 `has_prev_day=False`、涨跌幅 0。
- 合成行情冒烟：`get_quote('rb.SHFE','D')` 与 `compute_panorama('D')`（71 个品种）正常返回。

### 残留风险
- `vol_ratio` 仍是半窗口量比（不在本次三项口径内），未改为「当日量 / 历史均量」。
- 全景 `strength` 综合评分公式未调整，仍可能受量比口径影响。
- 交易日归属按 18:00 切分，长假前后夜盘需依赖数据本身的日期，未接交易所日历。

---

## 4. 换月成本接入（P1-1）

### 问题
| 编号 | 问题 | 旧位置 |
|---|---|---|
| P1-1 | `roll_cost.py` / `dominant.py` 未被回测、撮合链路引用，换月成本为 0 | 全仓库无调用 |
| P1-1 | 无主力→连续映射输出，无法定位换月事件 | `data/dominant.py` |
| P1-1 | `continuous.py` 与 `ui/pages.py` 历史页面未标记状态 | 同上 |

### 修复
1. `dominant` 新增 `roll_transitions(mapping)`（输出 `(换月日, 旧合约, 新合约)`）与 `continuous_symbol_map(mapping)`（日期→连续合约代码）。
   - 位置：[dominant.py:41-64](file:///d:/PythonProject/QuantVortex/futures_quant/data/dominant.py#L41-L64)
2. `roll_cost` 新增 `roll_cost_commission()`（平旧+开新双边手续费下限）与 `build_roll_schedule()`（无多合约数据时的月度近似）。
   - 位置：[roll_cost.py:35-62](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/roll_cost.py#L35-L62)
3. `Portfolio` 新增 `total_roll_cost` 与 `apply_roll_cost()`，成本直接扣现金，权益同步下降，`summary()` 输出累加值。
   - 位置：[portfolio.py:132-144](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L132-L144)
4. `Backtester` 新增 `roll_schedule` 入参（默认 `None`）与 `_charge_roll_cost()`：在换月日对持仓收取双边手续费；`config.backtest.enable_roll_cost` 默认开启，可关闭做对照。
   - 位置：[backtester.py:150](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L150)、[backtester.py:252-288](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L252-L288)、[settings.py:55](file:///d:/PythonProject/QuantVortex/futures_quant/config/settings.py#L55)
5. `continuous.py` 模块头、`ui/pages.py` 模块头加「⚠️ 未启用 / 待移除」标注，未删除、未改行为。

### 验证
- 新增 `tests/unit/test_phase1_roll_cost.py`（5 项，全通过）：
  - `roll_transitions` 仅输出实际切换事件；
  - `roll_cost_commission(2, 3.0)` = 12 元（双边）；
  - `Portfolio.apply_roll_cost(10)` 使现金/权益同步减 10、累计成本 10；
  - `enable_roll_cost=False` 时换月日集合为空；显式 `roll_schedule` 优先于月度近似。
- 锚点回测：同一代码、同一区间，开关前后数字见下表。

### 残留风险
- **未计入价差成本**：单合约连续序列没有新旧合约双边报价，只收双边手续费下限；真实换月价差需接入多合约行情后启用。
- 默认换月日为「每自然月首个有行情交易日」的近似，不是真实主力迁移日；生产使用应传入 `dominant.roll_transitions()` 输出。
- 持仓成本目前只覆盖手续费，未对移仓前后的保证金占用变化建模。

---

## 5. 回测前后对照

配置：`rb.SHFE` 日线，2020-01-01 ~ 2026-09-30，TrendFollowing 默认参数，warmup=60，初始 100 万，手续费 3 元/手，默认风控 + `non_trading_hours_block=False`，数据源 `data/real_samples/rb_SHFE_D.csv`（与 `data/akshare_cache/rb_SHFE_D.csv` 同数据）。
该配置可复现出与用户基线一致的 **225 笔**，因此作为本轮主对照口径。

| 版本 | 笔数 | 收益 | Sharpe | MDD | 期末权益 | 换月成本 |
|---|---:|---:|---:|---:|---:|---:|
| 用户基线（历史记录） | 225 | -0.63% | -0.106 | 3.01% | — | 0 |
| **本轮改动后（`enable_roll_cost=False`）** | 225 | -0.72% | -0.121 | 3.06% | 992,805 | 0 |
| **本轮改动后（`enable_roll_cost=True`，默认）** | 225 | -0.76% | -0.129 | 3.08% | 992,385 | 420 |

第二品种 `i.DCE`（同区间、同策略、同配置，排除单一品种过拟合）：

| 版本 | 笔数 | 收益 | Sharpe | MDD | 期末权益 | 换月成本 |
|---|---:|---:|---:|---:|---:|---:|
| `roll_cost=False` | 235 | -0.82% | -0.428 | 1.21% | 991,825 | 0 |
| `roll_cost=True` | 235 | -0.89% | -0.465 | 1.27% | 991,145 | 680 |

补充：上一轮记录的「宽松风控」配置（max_total_position_ratio=0.98 等）下，笔数为 231，
本轮 `roll off → on` 为 `231/-0.74%/-0.123/3.06% → 231/-0.78%/-0.130/3.08%`，
与主对照方向一致，可作为第二组交叉验证。

### 归因
- 笔数 225/235 未变：本轮改动没有新增/吞掉信号，只改变个别成交价格与成本。
- `-0.72% → -0.76%`（roll off → on）：换月双边手续费 420 元，约 -0.042 个百分点。
- `-0.63%`（用户基线）→ `-0.72%`（本轮 roll off）：**不可复现的历史配置差异**（约 -0.09pp），
  主要来自手续费/风控参数历史口径，与本轮四项改动无关。计数已对齐到 225，说明策略信号未变。
- Sharpe -0.106 → -0.121（历史口径差）+ → -0.129（换月成本）；MDD 3.01% → 3.06% → 3.08%。
- 所有数字方向一致：成本增加、收益与风险指标小幅走差，未出现「改完变好看」。
- 本轮所有对照均使用同一份 CSV 与同一配置（除 `enable_roll_cost`），保证内部可比。

---

## 6. 测试汇总

| 测试文件 | 项数 | 结果 |
|---|---:|---|
| `tests/unit/test_phase1_price_limit_matching.py` | 5 | 通过 |
| `tests/unit/test_phase1_contract_specs.py` | 5 | 通过 |
| `tests/unit/test_phase1_daily_snapshot.py` | 6 | 通过 |
| `tests/unit/test_phase1_roll_cost.py` | 5 | 通过 |
| 既有 phase0 / broker / price_limit / roll_cost / arbitrage / core | 20 | 通过 |

合计本轮定向回归 **41 项全部通过**（另 `test_backtest_attribution.py` 单独运行通过）。

- `tests/unit/test_m4_11_window_nav.py::test_restore_geometry_respects_maximized_false` 为**既有失败**（断言 `main_window.py` 源码字符串，本轮未改动该文件），与本轮无关。
- `tests/e2e/test_backtest_real_akshare.py` 的 3 项为**既有失败**，已核实与本轮无关：
  - `test_specs` 直接断言小写键 `'rb' in CONTRACT_SPECS`，而品种表键一直为大写；
  - `test_real_backtest` 未设置 `non_trading_hours_block=False`，日线时间戳为 00:00，
    被风控全部拦截 → 0 成交；同一配置手动关闭该开关后 rb 可成交 337 笔。

---

## 7. 未完成 / 明确未启用

1. **换月价差成本未接入**：缺少多合约双边报价，当前只计手续费下限；需要行情侧提供新旧合约价格后才能启用价差项。
2. **扩板状态机未启用**：无法用交易所公开规则核对连续停板判定、扩板阈值与封停排队，按约束停用并标注。
3. **速览 `vol_ratio` / `strength` 未改**：不在本次三项当日口径范围内，保留原逻辑。
4. **225 基线未复现**：已用同数据同配置的阶段 0 末结果作为可比基线，并在报告中说明差异来源。
