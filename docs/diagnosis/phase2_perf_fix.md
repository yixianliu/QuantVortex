# 阶段二性能修复：指标与回测内核（`atr_last` / 其他 `_last` / `tech.sar`）

> 范围：只改指标层与回测内核，未触碰 `futures_quant/ui/` 下任何文件。
> 未 commit、未改版本号、未删文件、未动 `data/` 与数据库。
> 基准数据：`rb.SHFE` 日线 1636 根 + `hc.SHFE` 1636 根 + `i.DCE` 1590 根，
> 另以 `rb` 三段拼接构造 5000 根序列（`rb5000`），覆盖 100 / 1000 / 全区间 / 5000 根。

---

## 1. 结论速览

| 场景 | 改前中位数 | 改后中位数 | 变化 | 参考阈值 | 达标 |
|---|---:|---:|---:|---:|:--:|
| `rb.SHFE` 单策略回测（1636 根） | 405.19 ms | **172.79 ms** | 2.35× 提速 | ≤ 500 ms | ✅ |
| 43 品种批量回测 | 21276.59 ms | **5260.00 ms** | 4.05× 提速 | ≤ 24500 ms | ✅ |
| 单品种平均 | 494.81 ms | **122.33 ms** | 4.05× 提速 | — | ✅ |
| `add_indicators`（5000 根 / 36 列） | 154.88 ms | **65.52 ms** | 2.36× 提速 | ≤ 180 ms | ✅ |
| `tech.sar`（5000 根） | 97.29 ms | **5.24 ms** | 18.57× 提速 | ≤ 120 ms | ✅ |
| `core.atr_last`（5000 根单次） | 2.835 ms | **0.008 ms** | 354× 提速 | — | ✅ |

全部**数值逐位一致**（`max_abs = 0`、`max_rel = 0`、`not_bit_identical = 0`）。
回测结果的**唯一口径**见 [§8 回测数字唯一口径](#8-回测数字唯一口径锚点对齐)：
`rb.SHFE` 当前全窗口（1636 根）为 `231 笔 / -0.78% / Sharpe -0.130 / MDD 3.08%`；
裁到锚点截止日（1590 根）为 `225 笔 / -0.76% / -0.129 / 3.08%`，与文档锚点逐位吻合。

---

## 2. 问题清单（文件:行 → 问题 → 改法）

### 2.1 `core/indicators.py` — `atr_last` 的 O(n²)（主因）

| 项 | 内容 |
|---|---|
| 位置 | 改前 [indicators.py:22](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py)：`atr_last`；现为 [indicators.py:43](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py) |
| 问题 | 每次调用 `list(closes)` / `list(highs)` / `list(lows)` 全量拷贝后，`for i in range(1, len(c))` 重建**整段历史**的 TR，再取最后 `period` 个求和。回测主循环每根 bar 调一次 → 整体 O(n²)。`deque(maxlen=500)` 虽封顶了缓冲，但每次仍要转 list 并遍历全量，属于纯浪费。 |
| 证据 | 改前 cProfile：`atr_last` 1606 次调用、自身 887.09 ms、累计 1581.71 ms，占单次回测（profile 计 1957.88 ms）约 81%；连带 `abs` 调用 1 382 919 次、`max` 693 887 次、`list.append` 700 506 次。 |
| 改法 | 只取尾部 `period + 1` 根（新增 [`_tail`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L17)），计算 `period` 个 TR 后求和。**求和顺序保持「由旧到新」**，与原实现一致，因此浮点结果逐位相同；`len < period + 1` 仍返回 `nan`。复杂度 O(period)。 |

### 2.2 同类「每 bar 重算全历史」的其他 `_last`（一并修掉，低风险优先）

| 函数 | 改前位置 | 问题 | 改法 |
|---|---|---|---|
| [`sma_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L35) | indicators.py:38 | `list(seq)` 全量拷贝 | `_tail(seq, period)` |
| [`donchian_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L63) | indicators.py:46 | 全量 `list()` 后 `max/min` 全历史 | `_tail(..., period+1)` 后取 `[:-1]` |
| [`bollinger_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L79) | indicators.py:62 | 同上 | `_tail(closes, period)` |
| [`rsi_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L91) | indicators.py:74 | 同上 | `_tail(closes, period+1)` |
| [`cci_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L107) | indicators.py:90 | 同上 | `_tail(..., period)` |
| [`roc_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L147) | indicators.py:143 | 同上 | `_tail(closes, period+1)` |
| [`willr_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L155) | indicators.py:151 | 同上 | `_tail(..., period)` |
| [`stoch_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L169) | indicators.py:165 | 同上 | `_tail(..., k_period)` |
| [`sar_last`](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L197) | indicators.py:193 | `if not highs` 对 ndarray 会抛「歧义真值」 | 仅需 `lows[-1]`，判空改 `len()` |

`_tail` 对 `list/tuple/ndarray` 走切片（O(count)）；对 `deque`（回测真实容器）改走
右端负索引 `seq[i - count]`，代价 O(count²) 指针步进但 count ≤ 百级，
相对 `list(deque)` 的 O(500) 全量转换大幅降低（微基准 500 长 deque、count=15：
负索引 1.78 µs vs 全量转 list 3.89 µs；`islice(reversed(...))` 0.98 µs 但引入额外反转，未采用）。

**未改**：`macd_last`（[indicators.py:124](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L124)）
的 EMA 定义依赖完整历史，截断会改变数值，本轮保持 O(n)，已在模块 docstring 标注为例外。

### 2.3 `indicators/tech.py` — `SAR` 逐点 pandas 标量访问

| 项 | 内容 |
|---|---|
| 位置 | 改前 [tech.py:104](file:///d:/PythonProject/QuantVortex/futures_quant/indicators/tech.py#L104)（改后仍在 104 行），`sar()` |
| 问题 | 每根 bar 执行 `high.iloc[i]` / `low.iloc[i]`（pandas `iloc` 标量取值有显著的 Python 开销），并在循环内重复读 `sar[i-1]`；5000 根实测 97.29 ms，是 `add_indicators` 的第一热点（36 列总量 154.88 ms 的 63%）。 |
| 改法 | SAR 是顺序状态机（`trend/EP/AF` 依赖上一根结果），**无法整体向量化**；改为 `to_numpy(dtype=float64, copy=False)` 预取 `h/l` 数组、局部变量承接 `prev/ep/af`，用 `nxt_af if nxt_af <= maximum else maximum` 替代 `min()`（结果等价）。状态机分支与运算顺序逐行保持，**数值逐位一致**。5000 根降到 5.24 ms。 |

---

## 3. 数值一致性结果

方法：同一份真实数据上，改动前先把每个 bar 的指标值落盘（`.perf_parity_before.json`），
改动后再用同一探针重算并逐点对比；判定 `abs ≤ 1e-9 且 rel ≤ 1e-9`，否则记为 `bad_points`。
`tech.sar` 另用「改动前 `sar()` 逐行副本」作参考实现（参考实现仅存在于临时探针与单测中，不入库）。

### 3.1 `core/indicators.py` 全部改动函数

列：`sma20 / atr14 / don_up / don_lo / boll_mid / boll_up / boll_lo / rsi14 / cci20 / roc12 / willr14 / stoch_k / stoch_d / macd_dif（未改，作稳定性参照）`

| 数据集 | 长度 | 采样点数 | 不一致列 |
|---|---:|---:|---|
| rb.SHFE | 100 | 85 | 无 |
| rb.SHFE | 1000 | 985 | 无 |
| rb.SHFE | 1636 | 1621 | 无 |
| hc.SHFE | 100 | 85 | 无 |
| hc.SHFE | 1000 | 985 | 无 |
| hc.SHFE | 1636 | 1621 | 无 |
| i.DCE | 100 | 85 | 无 |
| i.DCE | 1000 | 985 | 无 |
| i.DCE | 1590 | 1575 | 无 |
| rb5000 | 100 | 85 | 无 |
| rb5000 | 1000 | 985 | 无 |
| rb5000 | 5000 | 526（每 10 点 + 末 30 点） | 无 |

全部 `max_abs = 0，max_rel = 0`（bit 级一致，非「误差极小」）。采样含数据不足周期的前段，
`nan` / 默认值（`rsi_last→50.0`、`cci_last→0.0`、`stoch→nan` 等）行为一致。

### 3.2 `tech.sar`

参考实现 = 改动前 `sar()` 的逐行副本（`.iloc` 逐点访问版本）。

| 数据集 | 长度 | max_abs | max_rel | 非 bit 一致点数 |
|---|---:|---:|---:|---:|
| rb.SHFE | 100 / 1000 / 1636 | 0.0 | 0.0 | 0 |
| hc.SHFE | 100 / 1000 / 1636 | 0.0 | 0.0 | 0 |
| i.DCE | 100 / 1000 / 1590 | 0.0 | 0.0 | 0 |
| rb5000 | 100 / 1000 / 5000 | 0.0 | 0.0 | 0 |
| rb.SHFE 参数变体 | accel=0.01/max=0.1、accel=0.03/max=0.3 | 0.0 | 0.0 | 0 |

边界：空序列 → 空 Series；单根 → 长度 1 且全 `nan`；索引（`DatetimeIndex`）原样保留。

### 3.3 端到端（回测结果不变）

> 口径说明：本节只用于**证明代码改动未改变结果**，因此改动前后都用同一套
> 「计时口径」（`warmup=0`、全 1636 根）。对外的回测数字请用 [§8](#8-回测数字唯一口径锚点对齐)
> 的唯一口径（`warmup=60`），两者相差的 10 笔成交纯粹来自 warmup 前 60 根是否允许开仓。

| 指标（计时口径：warmup=0，1636 根） | 改前 | 改后 |
|---|---:|---:|
| `num_fills` | 241 | 241 |
| `total_return` | -0.0093 | -0.0093 |
| `annual_return` | -0.0014 | -0.0014 |
| `max_drawdown` | 0.0308 | 0.0308 |
| `sharpe` | -0.155 | -0.155 |
| `win_rate` | 0.4167 | 0.4167 |

---

## 4. 性能前后对比（`scripts/perf_probe.py`，先 warm-up 再取 3 次中位数）

### 4.1 回测分节（`--section backtest --runs 3`）

| 场景 | 改前中位数 | 改后中位数 | 提速 | 阈值 | 达标 |
|---|---:|---:|---:|---:|:--:|
| rb.SHFE 单次（1636 根） | 405.19 ms | 172.79 ms | 2.35× | ≤ 500 ms | ✅ |
| 43 品种批量总耗时 | 21276.59 ms | 5260.00 ms | 4.05× | ≤ 24500 ms | ✅ |
| 单品种平均 | 494.81 ms | 122.33 ms | 4.05× | — | ✅ |
| 批量最后一次 | 25116.05 ms | 5361.96 ms | 4.68× | — | ✅ |

cProfile Top（累计时间）：

| 函数 | 改前 累计 / 自身 | 改后 累计 / 自身 |
|---|---:|---:|
| `backtester.run` | 1957.88 / 0.41 ms | 373.88 / 0.43 ms |
| `engine.process_bar` | 1843.60 / 16.66 ms | 295.16 / 13.44 ms |
| `trend_following.on_bar` | 1694.42 / 45.50 ms | 158.35 / 8.70 ms |
| `atr_last` | **1581.71 / 887.09 ms** | **88.62 / 42.40 ms** |
| `_tail`（新增） | — | 38.63 / 30.21 ms（8030 次） |
| `sma_last` | 未入 Top15 | 32.10 / 7.93 ms（3212 次） |

`atr_last` 已从「单点占 81%」降为 top-5 之末；剩余时间分布在 `risk_manager.on_new_bar`、
`portfolio.equity/unrealized_pnl`（每 bar 多次估值）等业务逻辑，不属于本轮指标范围。

### 4.2 指标分节（`--section indicators --runs 3`，5000 根 / 36 列）

| 项 | 改前中位数 | 改后中位数 | 提速 | 阈值 | 达标 |
|---|---:|---:|---:|---:|:--:|
| `add_indicators` 总量 | 154.88 ms | 65.52 ms | 2.36× | ≤ 180 ms | ✅ |
| `SAR` | 97.29 ms | 5.24 ms | 18.57× | ≤ 120 ms | ✅ |
| `GARCH` | 10.88 ms | 12.53 ms | ~1.0×（噪声） | — | — |
| `DMI(4列)` | 6.63 ms | 9.00 ms | ~1.0×（噪声） | — | — |
| `boll_pct` | 5.25 ms | 4.21 ms | ~1.0× | — | — |

> 说明：除 SAR 外其它单项未改动，前后差异属亚毫秒级调度噪声（GARCH 走 NumPy 降级路径，
> 本身波动 ±2 ms）。`slowest5` 改前为 `SAR/GARCH/dir_di/DMI/boll_pct`，改后 `SAR` 退居第 4。

### 4.3 单函数微基准（5000 根，300 次中位数）

| 函数 | 改前 | 改后 | 提速 |
|---|---:|---:|---:|
| `atr_last` | 2.835 ms | 0.008 ms | 354× |
| `rsi_last` | 1.956 ms | 0.006 ms | 326× |
| `cci_last` | 1.184 ms | 0.014 ms | 85× |
| `willr_last` | 0.054 ms | 0.003 ms | 18× |
| `tech.sar` | 111.62 ms | 5.21 ms | 21× |

> `tech.sar` 在探针里单测 111.62 ms、在指标分节里 97.29 ms，差异来自是否复用同一份
> `Series` 及测量上下文；两个口径的改后值都在 5 ms 量级。

---

## 5. 回归测试

新增 [tests/unit/test_phase2_indicator_perf.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_phase2_indicator_perf.py)（10 个用例，全绿）：

1. `test_tail_boundaries`：`_tail` 的 `count<=0` / `count>=n` / list / deque 分支。
2. `test_atr_last_matches_naive_reference`：800 根上**逐根**与朴素全历史参考实现对比（含 `< period+1` 的 `nan`）。
3. `test_last_series_match_naive_reference`：sma / donchian / bollinger / rsi / cci / roc / willr / stoch / sar_last 与朴素参考逐点一致（覆盖前段数据不足区间）。
4. `test_container_equivalence`：`list / tuple / deque / deque(maxlen=500) / ndarray` 五种容器结果一致。
5. `test_atr_last_cost_does_not_grow_with_history`：同一尾窗、历史 500 vs 5000，耗时比 **≤ 4.0**（相对阈值，不依赖绝对耗时）。
6. `test_sar_scales_linearly_and_under_loose_cap`：5000 根宽松上限 2000 ms（仅首次 >50 ms 时才二次确认，抗抖动）。
7. `test_sar_matches_reference[3 参数变体]`：与改动前逐行副本**逐点 bit 级一致**。
8. `test_sar_edge_cases`：空序列 / 单根 / 索引保留。

既有相关测试回归：`tests/unit/test_feature_contract.py`、`tests/unit/test_m3_01.py`、
`tests/e2e/test_indicator_accuracy.py`、`tests/e2e/test_core.py`、`tests/e2e/test_indicator_cache.py`
共 20 个用例全部通过。

---

## 6. 残留风险与未修项

| 项 | 位置 | 说明 | 处理 |
|---|---|---|---|
| `macd_last` 仍 O(n) | [indicators.py:124](file:///d:/PythonProject/QuantVortex/futures_quant/core/indicators.py#L124) | EMA 需完整历史（首值取前 `period` 均值再递推），截断会改变数值 | **不修**，模块 docstring 已标注例外；策略缓冲 `deque(maxlen=500)` 实际限制在 500 根 |
| 策略层每 bar `list(deque)` | [auto_evolve.py:572-580](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L572)、[auto_evolve.py:750-752](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L750)、[auto_evolve.py:806](file:///d:/PythonProject/QuantVortex/futures_quant/strategy/auto_evolve.py#L806) | 因子/集成/regime 各自把同一 deque 转 list，属于「每 bar 3×O(500)」而非 O(n²) | **本轮不修**（策略层，且次数有界）；若后续要优化，可在 `on_bar` 转一次 list 后透传 |
| `adx_last` / `obv_last` / `vwap_last` 为占位实现 | indicators.py:189/207/213 | 恒返回常量，不耗时 | 保持现状（改动会改变策略信号） |
| `_tail` 的 deque 分支 | indicators.py:17 | 右端负索引为 O(count²) 指针步进（count ≤ 百级，实测 1.8 µs） | 可接受；若未来 window 上百，改 `islice(reversed(...))` |
| `GARCH` 走降级路径 | tech.py:310 | `arch` 未安装 → EWMA，波动 ±2 ms，是改后 `add_indicators` 的最大单项（约 12.5 ms） | 与本轮无关，未动 |
| 剩余回测开销 | `risk_manager.on_new_bar`、`portfolio.equity(8668 次)` | 指标不再是瓶颈后，估值/风控成为主要开销 | 第二轮已处理 P0+P1，见 §10；P2 快照缓存/P3 策略层透传未做 |

---

## 7. 复现方式

```powershell
# 0) 回测数字唯一口径（任何对照前先跑这一条，verdict.all_ok 必须为 true）
python scripts/perf_probe.py --section anchor

# 1) 指标分节 / 回测分节（改后）
python scripts/perf_probe.py --section indicators --runs 3
python scripts/perf_probe.py --section backtest --runs 3

# 2) 回归测试
python -m pytest tests/unit/test_phase2_indicator_perf.py tests/unit/test_phase2b_portfolio_perf.py -q

# 3) 改前基线（已保存在 outputs/，勿覆盖）
#    .perf_backtest_before.json / .perf_indicators_before.json / .perf_parity_before.json
```

产物：`outputs/.perf_backtest.json`、`outputs/.perf_indicators.json`、
`outputs/.perf_parity_before.json`（改前逐点值）、`outputs/.perf_sar_parity.json`（SAR 一致性报告）、
`outputs/.perf_anchor.json`（回测数字唯一口径）。

---

## 8. 回测数字唯一口径（锚点对齐）

### 8.1 问题

探针给出 `rb.SHFE` `241 笔 / -0.93%`，文档锚点记录 `225 笔 / -0.76% / Sharpe -0.129 / MDD 3.08%`。
同品种同区间出现两套数字，必须查清到底是代码、配置还是数据版本造成的。

### 8.2 唯一口径（已固化）

> **命令**：`python scripts/perf_probe.py --section anchor`（产物 `outputs/.perf_anchor.json`，`verdict.all_ok = true`）

口径 = **同策略同参数 + `warmup=60` + 非交易时段不阻断 + 含移仓成本 + `Config()` 默认账户/费率**，
数据窗口 `2020-01-01 ~ 2026-09-30`，缓存文件由 `LocalDailyFeed` 自动选中（并打印 sha1）。

| 配置项 | 值 |
|---|---|
| 策略 | `TrendFollowing` |
| 参数 | `fast=10, slow=30, atr_period=14, stop_mult=2.0, lots=1` |
| 预热 | `warmup=60`（前 60 根只喂数据，不下单） |
| 风控开关 | `risk.non_trading_hours_block=False` |
| 移仓成本 | `backtest.enable_roll_cost=True` |
| 初始资金 | `initial_capital=start_cash=1,000,000` |
| 手续费 | `commission_per_lot=3.0`，`close_today_ratio=0.5` |
| 滑点 | `slippage=1.0`（`slip_mode=fixed`，1 个最小变动价位） |
| 保证金 | `margin_rate=0.1`，`multiplier=10` |
| 撮合 | `fill_mode=next_open`，`pending_expire_bars=5`，涨跌停 `±4%` 起、每档扩 2%、最多 2 档 |
| 数据（rb） | `data/akshare_cache/rb_SHFE_D.csv`，sha1 `ff8ed028ba343703`，窗口 1636 根（2020-01-02 ~ 2026-09-30），重复日期 0 |
| 数据（i） | `data/akshare_cache/i_DCE_D.csv`，sha1 `f5d32448db5cb5ed`，窗口 1590 根（2020-01-02 ~ 2026-07-27），重复日期 0 |

### 8.3 数字是怎么差出来的（三段归因）

| 口径 | 数据窗口 | bar 数 | warmup | fills | total_return | Sharpe | MDD |
|---|---|---:|---:|---:|---:|---:|---:|
| ① 探针旧口径（`_run_once`） | 2020-01-01~2026-09-30 | 1636 | **0** | **241** | -0.93% | -0.155 | 3.08% |
| ② 锚点开关 + 当前缓存 | 2020-01-01~2026-09-30 | 1636 | 60 | **231** | -0.78% | -0.130 | 3.08% |
| ③ 锚点开关 + 锚点截止日 | 2020-01-01~**2026-07-27** | **1590** | 60 | **225** | **-0.76%** | **-0.129** | **3.08%** |
| 文档锚点（phase1） | — | — | — | 225 | -0.76% | -0.129 | 3.08% |

- **①→②（-10 笔）**：纯 `warmup=0` 造成。预热 60 根被放开后，`fast=10/slow=30/atr=14`
  在数据不足时仍按默认值下单，多出 5 组开平仓（10 笔），并把总收益从 -0.78% 拉到 -0.93%。
  **这是探针写法的问题，与指标优化无关**（改前改后同为 241，见 §3.3）。
- **②→③（-6 笔）**：纯数据版本。`real_samples/rb_SHFE_D.csv` 止于 **2026-07-27**（窗口 1590 根），
  而 `akshare_cache/rb_SHFE_D.csv` 已更新到 **2026-09-30**（多 46 个交易日），多出的行情产生 6 笔成交、
  收益从 -0.76% 到 -0.78%（Sharpe -0.129 → -0.130）。MDD 不变（3.08%）。
- **③ 与锚点逐位吻合**：`225 / -0.76% / -0.129 / 3.08%`，`verdict.anchor_window_matches = true`，
  `mismatch = {}`。另用 `akshare_cache` 截到 07-27 跑同一配置，同样得到 225 笔，
  证明两个缓存文件在重叠区间上**结果等价**（sha1 不同只是行数/尾部不同）。

> 更正 phase1 文档中的一处表述：`data/real_samples/rb_SHFE_D.csv` 与
> `data/akshare_cache/rb_SHFE_D.csv` **并非同数据**（前者 4208 行止于 07-27，后者 4273 行止于 09-30），
> 只是重叠区间逐笔复现一致。

第二品种 `i.DCE`（缓存自然止于 07-27，两窗口同长）：`235 / -0.89% / -0.465 / 1.27%`，
与锚点一致，`all_ok = true`。

### 8.4 后续引用规则

- **对外/报告的回测数字**：只引用 `--section anchor` 的输出（②为当前全窗口，③为锚点对齐值）；
- **改前/改后性能对比**：`--section backtest` 保持 `warmup=0`（跑满全窗口），其 `metrics`
  仅用于「代码改动未改结果」的健全性核对，JSON 中已带 `metrics_note` 标注；
- 任何新对照先跑 §8.2 命令，`verdict.all_ok` 必须为 `true` 才允许下结论。
- 第二轮（P0+P1）已按本规则复核完毕，实施记录与证据见 [§10](#10-第二轮性能优化p0--p1)。

---

## 9. 下一轮优化：剖析与候选方案（仅分析，未改代码）

剖析条件：`rb.SHFE` 1636 根、`warmup=0`、cProfile，总耗时 373.88 ms（cProfile 计）。

| # | 函数 | 调用次数 | 累计 / 自身 (ms) | 观察 |
|---|---:|---:|---:|---|
| 1 | `backtester._run_event_driven` | 1 | 370.13 / 18.64 | 主循环本身 |
| 2 | `engine.process_bar` | 1636 | 295.16 / 13.44 | 每 bar 风控 + 撮合 + 估值 |
| 3 | `risk_manager.on_new_bar` | 1636 | 62.33 / 13.19 | **每 bar 调 2 次 `portfolio.equity()`** |
| 4 | `portfolio.equity` | 8668 | 45.42 / 5.77 | 5.3 次/bar |
| 5 | `portfolio.unrealized_pnl` | 8668 | 39.65 / 23.02 | 逐持仓查 `_multiplier/_margin_rate` |
| 6 | `portfolio.used_margin` | 3758 | 26.31 / 16.84 | 2.3 次/bar |
| 7 | `portfolio.risk_degree` | 1636 | 26.35 / 3.03 | 内部又算一次 `equity()` |
| 8 | `portfolio.available` | 1879 | 18.76 / 1.73 | 内部又算一次 `equity()` |
| 9 | `backtester._trading_day_key` | 4908 | 19.29 / 14.56 | 3 次/bar 的日期化简 |
| 10 | `backtest_broker.match` | 1636 | 29.51 / 20.60 | 单次 12.6 µs |
| 11 | `core.indicators._tail` | 8030 | 38.63 / 30.21 | 5 次/bar，deque 右端取尾 |

调用来源（`warmup=60` 口径）：`equity` 共 8468 次，其中 `on_new_bar` 3152、`available` 1869、
`process_bar` 1576、`risk_degree` 1576、`check_order` 233 —— **同一条 bar 内被重复估值 5～6 次**。

候选方案（按风险从低到高，均未实施）：

| 优先级 | 方案 | 预期收益 | 风险 | 备注 |
|---|---|---|---|---|
| P0 | `portfolio.risk_degree(eq=None)` / `available(eq=None)` 增加可选预计算参数；`on_new_bar` 复用同一 `eq` | 每 bar 少 2 次 `equity`（约 -2500 次/run），≈ -10~14 ms | 低 | 不新增缓存、无失效点，数值完全等价 |
| P0 | `engine.process_bar` 先算一次 `eq`，`available()` 传 `eq`；`backtester` 里 `equity()+available()` 合并 | 每 bar 再少 2 次 `equity`，≈ -8~10 ms | 低 | 同上 |
| P1 | `Portfolio` 内缓存 `symbol → (multiplier, margin_rate, commission)`（注册合约时填充） | `unrealized_pnl` 自身 23 ms → 估计 15 ms | 低 | 仅缓存静态合约属性 |
| P1 | `_trading_day_key` 按 `date` 对象做 dict 缓存（4908 → 1636 次） | 自身 14.56 ms → ~6 ms | 低 | 纯字符串/日期运算 |
| P2 | `Portfolio` 增加「同 bar 快照」(equity, used_margin)，由 `mark_price/apply_trade/on_bar` 失效 | `equity` 5.3→1 次/bar，≈ -25 ms | 中 | 失效点必须覆盖成交、结算、换月，需单测守护 |
| P2 | `_tail` 的 deque 分支改 `list(islice(reversed(seq), count))[::-1]` | `_tail` 30 ms → 估计 18 ms | 中 | 微基准 1.78→0.98 µs；已有逐位一致性测试兜底 |
| P3 | 策略 `on_bar` 入口把 deque 转一次 list 并透传给所有 `_last` | `atr_last+sma_last+_tail` 共 ~130 ms → 估计 -60 ms | 中高 | 改 `StrategyBase` 调用约定，需全策略回归 |

合计低风险项（P0+P1）预期 373 ms → 约 335 ms（-10%），且不改任何数值。
下一轮验收方式：仍以 §8.2 命令核对 `225 / -0.76% / -0.129 / 3.08%` 与 `231 / -0.78% / -0.130 / 3.08%`
必须逐位不变，再比较 `--section backtest` 的中位数。

> **状态更新**：上表 **P0 两条 + P1 两条已实施并通过复核**（记录见 §10）；
> P2（同 bar 快照缓存）与 P3（策略层 deque 透传）按约定本轮不做。

---

## 10. 第二轮性能优化（P0 + P1）

> 范围：`core/portfolio.py`、`core/engine.py`、`risk/risk_manager.py`、`backtest/backtester.py`。
> **未触碰** `futures_quant/ui/` 与 `futures_quant/ai/`（另有会话在改）。
> 未 commit、未改版本号、未删文件、未动 `data/` 与数据库。

### 10.1 改动清单（文件:行 → 改法）

| 编号 | 文件:位置 | 改法 | 为什么数值不变 |
|---|---|---|---|
| P0-1a | [portfolio.py:208](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L208) `available()`、[portfolio.py:217](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L217) `risk_degree()` | 增加可选参数 `equity=None`：`eq = self.equity() if equity is None else float(equity)`，其余公式不变 | 调用方传入的 `eq` 就是同一时刻 `self.equity()` 的返回值；`equity()` 是纯函数（`cash + unrealized_pnl()`），两次调用之间无状态变更，故 `eq - used` / `used / eq` 的运算数与运算顺序完全一致 |
| P0-1b | [risk_manager.py:141](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L141) `on_new_bar` | 把 `eq = portfolio.equity()` 提到日切判断**之前**，`daily_start_equity = eq`；末尾改 `portfolio.risk_degree(eq)`（保留 `hasattr` 分支，并对无参鸭子类型 `TypeError` 回落 `risk_degree()`） | 原实现日切时算一次、随后再算一次，两次值相同；`risk_degree(eq)` 与 `risk_degree()` 内部同一表达式 |
| P0-2a | [engine.py:230-232](file:///d:/PythonProject/QuantVortex/futures_quant/core/engine.py#L230) `process_bar` | `avail = eq - self.portfolio.used_margin()`，不再调 `available()` | `available()` 定义即 `equity() - used_margin()`；此处 `eq` 正是刚算出的 `equity()` |
| P0-2b | [backtester.py:301-307](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L301) warmup 分支 | 先 `eq = p.equity()`，再 `(datetime, eq, eq - p.used_margin())` | 同上 |
| P0-2c | [risk_manager.py:123-136](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L123) `check_order` 资金校验 | `used = portfolio.used_margin()` 只取一次；`new_used = used + add_margin`；可用资金判定改 `eq - used < add_margin` | 原 `available()` 内部再算一次 `equity()`；改后仍用同一次 `used`/`eq` |
| P1-1 | [portfolio.py:69](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L69)、[portfolio.py:72](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L72) `_spec()` | 新增 `_spec_cache: {symbol: (contract, mult, margin_rate, commission, close_today_ratio, 账户默认值快照)}`；4 个参数 Getter 与 `used_margin`/`unrealized_pnl` 全部走 `_spec()` | 缓存命中时直接返回「按原分支算出的同一组 float」；守卫为 `contract is 原对象 且 账户默认值元组未变`，替换合约/改默认值即重建 |
| P1-2 | [backtester.py:225-237](file:///d:/PythonProject/QuantVortex/futures_quant/backtest/backtester.py#L225) `_trading_day_key` | `@staticmethod` + `@lru_cache(maxsize=8192)` | 纯函数（只依赖时间戳），缓存只省重复计算，返回值不变 |

### 10.2 数值等价证据（逐位，非「误差极小」）

1) **唯一口径探针** `python scripts/perf_probe.py --section anchor` → `verdict.all_ok = true`，`mismatch = {}`：

| 对象 | 窗口 | bar 数 | fills | total_return | Sharpe | MDD | 与改前 |
|---|---:|---:|---:|---:|---:|---:|:--:|
| rb.SHFE | 全窗口 | 1636 | **231** | **-0.78%** | **-0.130** | **3.08%** | 逐位一致 |
| rb.SHFE | 锚点窗口（至 2026-07-27） | 1590 | **225** | **-0.76%** | **-0.129** | **3.08%** | 逐位一致 |
| i.DCE | 全窗口 | 1590 | **235** | **-0.89%** | **-0.465** | **1.27%** | 逐位一致 |

数据侧未变：`rb_SHFE_D.csv` sha1 `ff8ed028ba343703`（4273 行 / 窗口 1636 / 锚点窗口 1590）、
`i_DCE_D.csv` sha1 `f5d32448db5cb5ed`（3105 行 / 窗口 1590），`dup_dates = 0`。

2) **成交明细逐笔对比**（改前快照 `.fills_before.json` vs 改后 `.fills_after.json`，
字段 `datetime / symbol / direction / offset / quantity / price / commission / pnl`）：

| 场景 | 笔数（前→后） | 成交字段差异 | 资金曲线点数（前→后） | 资金曲线哈希 |
|---|---:|---:|---:|---|
| rb.SHFE 全窗口 | 231 → 231 | **0** | 1636 → 1636 | `f9effe95519f04bf`（前后相同） |
| rb.SHFE 锚点窗口 | 225 → 225 | **0** | 1590 → 1590 | `f828fb4f4aca31be`（前后相同） |
| i.DCE 全窗口 | 235 → 235 | **0** | 1590 → 1590 | `5cb514e719c845c8`（前后相同） |

> 资金曲线逐点 `(datetime, equity, available)` 也是 0 差异——说明 `available` 由 `eq - used_margin()`
> 推导后与旧 `available()` 的浮点结果完全一致。

3) **单测**：新增 [tests/unit/test_phase2b_portfolio_perf.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_phase2b_portfolio_perf.py)（6 用例全绿）：
`available(eq) == available()`、`risk_degree(eq) == risk_degree()`（`==` 即逐位）；
持仓加仓 + 价格上移后 `risk_degree(新 eq)` 仍等于 `used/eq`；
合约对象被替换后乘数翻倍立即生效；账户默认保证金率变更后缓存重建；
多品种乘数/保证金率互不串味；`_trading_day_key` 的 lru 结果与参考实现一致且实例/类调用等价。
既有回归：`test_phase3_e2e_regressions.py`、`test_phase2_indicator_perf.py`、`test_margin_calc.py`、
`test_core.py` 共 15 用例全绿。

### 10.3 耗时对比（`--section backtest --runs 3`，先 warm-up 再取中位数）

| 场景 | 本轮改前 | 改后·复测1 | 改后·复测2 | 提速（相对改前） | 预估 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| rb.SHFE 单次（1636 根） | 172.79 ms | 106.71 ms | **100.51 ms** | -38.2% / **-41.8%** | ~-10% | 超过预估 |
| 43 品种批量总耗时 | 5260.00 ms | **4632.60 ms** | 4767.93 ms | **-11.9%** / -9.4% | ~-10% | 达到预估 |
| 单品种平均 | 122.33 ms | 107.74 ms | 110.88 ms | -11.9% / -9.4% | — | — |

> 单次场景波动较大（复测1 样本 96.9 / 106.7 / 124.9 ms），批量更稳定（两次 4632~4809 ms）。
> 两次独立复测都优于改前，故不取单次极值下结论；批量口径是本轮的主要验收对象。

cProfile（含剖析开销，仅比比例）：

| 函数 | 本轮改前 调用 / 累计 | 本轮改后 调用 / 累计 |
|---|---:|---:|
| `backtester.run` | 1 / 373.88 ms | 1 / **255.42 ms** |
| `engine.process_bar` | 1636 / 295.16 ms | 1636 / 192.94 ms |
| `risk_manager.on_new_bar` | 1636 / 62.33 ms | 1636 / **31.92 ms** |
| `portfolio.equity` | **8668** / 45.42 ms | **3517** / 18.55 ms |
| `portfolio.unrealized_pnl` | 8668 / 39.65 ms | 3517 / 16.50 ms |
| `portfolio.used_margin` | 3758 / 26.31 ms | 3515 / 14.43 ms |
| `portfolio.risk_degree` | 1636 / 26.35 ms | 已退出 Top15（复用 eq 后仅剩除法） |
| `portfolio.available` | 1879 / 18.76 ms | 已退出 Top15（调用点改内联） |
| `backtester._trading_day_key` | **4908** / 19.29 ms | 已退出 Top15（lru 命中） |
| `portfolio._spec`（新增） | — | 7145 次 / 11.28 ms（含缓存命中判断） |

`equity` 调用从 8668 → 3517（-59.4%），与「同 bar 估值 5~6 次 → 2 次」的预期一致；
剩余 3517 次 ≈ 2.15 次/bar：`on_new_bar` 1 次 + `process_bar` 1 次 + `check_order` 233 次。
再往下压需要 P2 同 bar 快照缓存（本轮不做）。

### 10.4 复现

```powershell
python scripts/perf_probe.py --section anchor            # verdict.all_ok 必须 true
python scripts/perf_probe.py --section backtest --runs 3  # 耗时中位数
python -m pytest tests/unit/test_phase2b_portfolio_perf.py -q
```

产物：`outputs/.perf_anchor.json`、`outputs/.perf_backtest.json`、
`outputs/.fills_before.json`（本轮改前快照）、`outputs/.fills_after.json`（改后快照）。

### 10.5 残留风险

| 项 | 说明 | 影响 | 处理 |
|---|---|---|---|
| `_spec` 守卫是「合约对象身份 + 默认值快照」 | 若有人**原地**修改已注册 Contract 的 `multiplier/margin_rate` 等字段（同一对象），缓存不会失效 | 保证金/盈亏用了旧参数 | 仓库内目前没有原地修改 Contract 的代码（`add_contract` 是 dict 替换，会触发重建；`Config.account` 变更由默认值快照覆盖）；如未来需要原地改，应先替换合约对象或新增显式 `invalidate_spec_cache()` |
| `risk_degree(eq)` 的鸭子类型兼容 | `on_new_bar` 里对无参签名 `risk_degree` 做 `TypeError` 回落；外部若直接传 `eq` 给自定义账户类需自行保证签名 | 仅影响非 `Portfolio` 的自定义账户 | 已用嵌套 `try` 兜底；`_PortfolioStub`（无 `risk_degree`）走 else 分支，测试全绿 |
| `_trading_day_key` 的 lru 容量 8192 | 单次运行时间戳超过 8192 根（如 1 分钟级长序列）时早期键被淘汰，后续调用会重算 | **只影响命中率，不影响结果** | 8192 ≈ 4.5 个日线品种全历史；如需日内长序列可调大或按 run 清理 |
| 跨实例共享 lru | 缓存挂在类上，多个 `Backtester` 实例共用 | 键是时间戳、值是 `date`，无实例状态，不会串味 | 无需处理 |
| lru 要求时间戳可哈希 | `pd.NaT` 不可哈希，若 bar 时间戳为 NaT 会抛 `TypeError` | 极低：日线/缓存 feed 都会按 `start~end` 掩码过滤，NaT 比较为 False 已被剔除（`csv_feed.py:87`、`akshare_feed.py:208`） | 若未来接入未清洗的数据源，先 `dropna(subset=["datetime"])` |
| `summary()` 仍重复估值 | [portfolio.py:231](file:///d:/PythonProject/QuantVortex/futures_quant/core/portfolio.py#L231) 各自再算 `equity/used_margin/available` | 非回测热点（UI 摘要才调用） | 本轮不动，避免影响 GUI 会话 |
| risk_manager 非交易时段逻辑 | [risk_manager.py:111-114](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L111) 未改动 | — | 已由 `test_phase3_e2e_regressions.py` 覆盖并通过 |
