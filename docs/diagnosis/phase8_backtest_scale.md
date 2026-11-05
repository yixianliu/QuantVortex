# 第 3 期：回测规模化 + 参数维度 + 可追溯

> 范围：仅内核与服务层（`futures_quant/backtest/`、`futures_quant/core/` 未改、
> `futures_quant/app/backtest_service.py`、`futures_quant/storage/backtest_store.py`、
> `scripts/`、`tests/unit/`、`docs/diagnosis/`）。**未改 `ui/`、未改版本号、未执行任何 git 写操作。**
> 并行会话正在修改的 `futures_quant/strategy/auto_evolve.py` 与 `ui/backtest_page.py` 未触碰。

---

## 0. 结论与实测数字

**工程层面三项改善，数值口径逐位不变：**

| 项目 | 改造前 | 改造后 | 变化 |
|---|---|---|---|
| 锚点成交笔数（`perf_probe.py --section anchor`） | rb 全窗 **231** / rb 锚点 **225** / i.DCE **235** | 同左，`verdict.all_ok: true` | **逐位不变** |
| 锚点逐笔成交 sha1 | 41b790bf… / d262b8a4… / fba77d75… | 同左（旧路径 vs 新路径一致） | **逐位不变** |
| 峰值内存（N=3 品种 × M=12 组合 × K=800，36 次） | 11.272 MB（tracemalloc 峰值），RSS Δ +8.746 MB | 6.502 MB，RSS Δ −0.227 MB | 峰值 **−42.3%** |
| 峰值内存（N=3 × M=12 × K=1600，36 次） | 20.056 MB，RSS Δ +8.910 MB | 9.829 MB，RSS Δ +0.008 MB | 峰值 **−51.0%** |
| 紧预算（摘要上限 10 条 / 50KB） | — | 6.038 MB（K=800）/ 9.172 MB（K=1600），26 条摘要落盘 JSONL | 内存不随组合数线性增长 |
| 引擎内耗时（36 次回测求和） | K=800：1894.9 ms；K=1600：3732.6 ms | K=800：1879.7 ms；K=1600：3839.1 ms | −0.8% / +2.9%，在测量噪声内 |
| 墙钟耗时（含 Python 汇总/摘要） | 2123.9 / 4177.1 ms | 2113.4 / 4328.0 ms | −0.5% / +3.6%，见 §2.1 噪声说明 |
| 单条组合摘要占用 | 0.18 MB/组合（完整结果驻留） | ≈1.2 KB/组合（43.8 KB/36 条） | 约 **150×** 缩减 |
| 按 run_id 复跑校验 | 无 | 7 项检查全部 `ok=True`（参数哈希/数据指纹/run_id/结果哈希/成交摘要/曲线摘要/KPI） | 新增能力 |

**一句话结论：撮合算力不是瓶颈（第 7 期已证实 66.9 µs/bar、无 O(N²)）；本期把
「结果对象与存储层」的内存增长从 O(组合数 × 单次结果) 降为 O(摘要上限 + Top-K)，
并补齐参数快照、数据指纹、run_id、落库与一键复跑。数值结果没有变，也没有声称变准。**

---

## 1. 改动清单（文件:行 → 问题 → 改法 → 验证）

| 文件:行 | 问题 | 改法 | 验证 |
|---|---|---|---|
| `futures_quant/backtest/run_config.py:57` | 回测入参散落在 account/backtest/risk 三个 dataclass，调用方各自构造，无法回答「这份结果用了什么参数」 | 新增 `BacktestConfig`：策略、数据窗口、账户、成本、风控、换月、种子、备注全部显式化；`params_snapshot()` 保留三段**完整**字典 | `test_snapshot_contains_every_field_and_is_json_serializable`；参数化 10 个维度逐一改值，`params_hash` 必须变化 |
| `run_config.py:94` | 通过 `vars()` 复制后缺少字段过滤，配置字段漂移时重建会崩 | `from_settings` 按目标 dataclass 字段名过滤捕获，`to_settings` 再按字段名过滤重建，老快照兼容新版本 | `test_to_settings_roundtrip_keeps_values`、`test_from_snapshot_roundtrip` |
| `run_config.py:220-243` | 参数快照无稳定序列化，无法做幂等比对 | `params_json()` 键排序 + 紧凑分隔；`params_hash()` = sha1 前 16 位 | 同上；`result_hash` 一致性测试 |
| `futures_quant/backtest/trace.py:35` | 「复跑拿到的还是同一段数据吗」无法判断 | `fingerprint_frame()`：行数 + 首末时间 + 数值缓冲区（OHLCV/OI，float64）sha1 | `test_fingerprint_changes_with_data_window`；同窗口重复读取必须同指纹 |
| `trace.py:73-107` | 成交/曲线无摘要，无法逐笔校验 | `trades_digest` / `equity_digest`：字段固定、数值 6 位小数、规范 JSON sha1 | 锚点旧/新路径摘要一致；复跑 7 项检查 |
| `trace.py:120` | 代码版本未记录 | `code_version()` 只读调用 `git rev-parse --short HEAD` + `git status --porcelain`（带缓存、超时、失败回退 `unavailable`），不写 git | `test_code_version_is_read_only_and_recorded` |
| `trace.py:141` | run_id 非确定性，无法「按 id 复跑」 | `run_id = bt_ + sha1(参数哈希 + 数据指纹 + commit + 包版本)[:12]`；同输入必然同 id | `test_run_id_and_result_hash_are_deterministic` |
| `futures_quant/backtest/backtester.py:29,239-246` | 执行层不知道本次实际用的行情窗口，指纹只能二次取数（可能不一致） | 在 `run()` 内对**实际读取的 df** 计算指纹并附到结果（纯追加字段，不参与撮合/指标） | 锚点 metrics/逐笔哈希不变；`data_fingerprint` 新旧路径相同 |
| `futures_quant/backtest/runner.py:53` | 服务层/扫描/复跑可能形成多套执行口径 | 统一执行器 `execute(cfg, feed)`：按快照重建 Config/合约/策略 → 调既有 `Backtester.run` → 附加追溯字段 | `test_runner_matches_legacy_backtester_exactly`（指标、逐笔 sha1、曲线逐点一致） |
| `runner.py:26-40` | 真实主力换月逻辑在服务层重复实现 | 迁移为 `resolve_roll_schedule()`：仅日线、失败显式抛 `DominantChainError`，不静默退回自然月近似 | 既有 `test_phase8_dominant_roll.py` 全通过 |
| `runner.py:162` | 无复跑校验能力 | `replay_run()`：按 `params_json` 还原配置 → 重跑 → 7 项逐项比对；数据指纹不一致直接判失败 | `test_store_save_get_and_replay`（含反向用例：数据窗口不一致必须 `ok=False`） |
| `runner.py:79-83` | 快照只记调用方传入参数，策略类默认值（fast/slow/atr/止损/手数）在快照里不可见，形成「隐式默认值」 | 执行前把策略实例的**生效参数**写回 `strategy_params`（`gene` 除外，其参数整体在 `gene` 串中）；只影响快照/哈希，不参与撮合 | `test_runner_matches_legacy_backtester_exactly`（断言结果 `params_hash` 即生效参数哈希）；锚点数值/逐笔 sha1 不变 |
| `futures_quant/backtest/sweep.py:43` | 参数扫描若保留完整结果，内存随组合数线性增长 | `SweepLimits`：摘要条数 + 字节双阈值 + Top-K + 可选 JSONL 落盘；超限即 `spill` 或计数丢弃 | `test_sweep_summary_matches_single_run_and_respects_caps`、`test_sweep_drops_when_no_sink` |
| `sweep.py:110` | 每个组合的完整曲线/成交无压缩方式 | `_summarize()`：KPI + 曲线摘要（点数/首末/极值）+ 摘要哈希，随后释放完整结果 | 保留/落盘摘要与单跑 `result_hash`、`trades_digest` 一致 |
| `sweep.py:155` | 多品种 × 多组合无统一入口 | `run_sweep()` 支持 `symbols`、网格/已展开组合、固定参数、进度回调、明细落盘、协作式中断 | `test_sweep_multi_symbol_and_detail_sink`（4 次运行全部可追溯） |
| `futures_quant/backtest/export.py:38` | 结果无法交给 UI/外部核对 | `export_result()` 输出 `_kpi.csv`、`_trades.csv`、`_equity.csv`、`_run.json`（含参数快照 + 数据指纹 + 成交） | `test_export_result_and_stored_run` |
| `futures_quant/storage/backtest_store.py:203` | 无单次回测运行表；升级老库无备份 | 新增 `backtest_runs`（26 列，`run_id` UNIQUE）+ 幂等 `ALTER TABLE` 补列 | `test_run_table_migration_is_idempotent` |
| `backtest_store.py:248` | 「动库前先备份」未落地 | 老库升级前用 sqlite3 `backup()` 写到同目录 `backups/<库名>_phase9_<时间戳>.db`；备份失败则中止建表 | 生产库实测生成 `data/backups/quant_backtest_phase9_20261104_222016.db`（171,192,320 字节） |
| `backtest_store.py:274` | 同参数同数据重复执行会插重复行 | `save_run()` 按 `run_id` upsert，`attempts + 1` | `test_store_save_get_and_replay`（写两次 → 1 行 / attempts=2） |
| `backtest_store.py:340` | 无法按 run_id 读取参数/摘要 | `get_run()` 解析 `params_json` / `metrics_json`，标注 `trace_status` | 复跑 CLI 实测 7 项全部一致 |
| `futures_quant/app/backtest_service.py:66` | 服务层无统一配置构造 | `build_config()` 全部入口共用 | `test_service_config_entry_persists_and_replays` |
| `backtest_service.py:91` | 原 `run_backtest` 与扫描/复跑走不同路径 | 改走 `runner.execute`，返回键集合保持不变（追溯字段纯追加） | `test_service_legacy_signature_still_works`（指标/逐笔摘要与直跑一致） |
| `backtest_service.py:223-263` | 无配置化运行/落库/复跑/导出接口 | 新增 `run_backtest_with_config` / `persist_result` / `replay` / `export_result` | 同上 + CLI 实测 |
| `scripts/replay_run.py` | 无法一条命令复跑 | `python scripts/replay_run.py --run-id <id> [--db ...] [--feed local|synthetic|market]`，校验失败退出码 1 | 实测 `replay_ok=True`（见 §4.3） |
| `scripts/research/phase9_backtest_scale.py` | 缺「改造前后」对照数据 | A 锚点等价 / B N×M×K 内存与耗时 / C 落库复跑 | 本报告 §2、§4 |
| `tests/unit/test_phase9_backtest_scale.py` | 缺回归 | 27 条用例（快照、等价、扫描上限、任意参数维度、落库、导出、迁移备份） | 27 passed |

---

## 2. 规模实测

### 2.1 测量条件（必须连同数字一起读）

- 行情：`LocalDailyFeed`（本地 akshare 日线缓存，**离线**，无联网）。
- 品种：`rb.SHFE`、`i.DCE`、`cu.SHFE`；组合：`fast ∈ {5,10,20}` × `slow ∈ {30,60}` × `stop_mult ∈ {1.5,2.5}` = **12 组**；每次运行 36 次回测。
- K：800 / 1600 根；起始日 2023-06-15 / 2020-03-02，结束 2026-09-30。
- 内存：`tracemalloc` 峰值（Python 对象；numpy 缓冲区不计入）+ `psutil` RSS 前后差。
  每次测量前 `gc.collect()`；RSS 受系统缓存/GC 影响，仅作量级参考，**以 tracemalloc 峰值为准**。
- 耗时：`tracemalloc` 关闭后单独计时；**「改造前/改造后交替各跑 3 轮，取各自最小值」**，
  同时记录每轮 `Backtester.run` 的 `duration_ms` 求和（「引擎内耗时」，不含 Python 汇总噪声）。
  交替是为了避免前后两次测量落在不同负载区间（早期串行测量曾出现 ±30% 级的假差异）。
- 机器负载未隔离（开发机同时有其他会话/IDE 活动）；交替 + 取最小值后，两条路径的
  引擎内耗时差异收敛到 ±3%，仍应视为「基本持平」，不要当成加速或退化。

### 2.2 前后对照表

| K | 路径 | 运行数 | 引擎内耗时 | 墙钟（3 轮最小） | tracemalloc 峰值 | RSS Δ | 保留的完整结果 / 摘要 |
|---|---|---|---|---|---|---|---|
| 800 | 改造前（全量保留） | 36 | 1894.9 ms | 2123.9 ms | **11.272 MB** | +8.746 MB | 36 份完整结果 |
| 800 | 改造后（边算边汇总，上限 50 条 / 8MB，Top-5） | 36 | 1879.7 ms | 2113.4 ms | **6.502 MB** | −0.227 MB（GC 噪声） | 36 条摘要 / Top-5 明细 |
| 800 | 改造后（紧预算 10 条 / 50KB，落盘） | 36 | — | — | **6.038 MB** | — | 10 条摘要 + **26 条落盘** |
| 1600 | 改造前（全量保留） | 36 | 3732.6 ms | 4177.1 ms | **20.056 MB** | +8.910 MB | 36 份完整结果 |
| 1600 | 改造后（边算边汇总，上限 50 条 / 8MB，Top-5） | 36 | 3839.1 ms | 4328.0 ms | **9.829 MB** | +0.008 MB | 36 条摘要 / Top-5 明细 |
| 1600 | 改造后（紧预算 10 条 / 50KB，落盘） | 36 | — | — | **9.172 MB** | — | 10 条摘要 + **26 条落盘** |

补充：36 条摘要合计峰值 43.8~44.0 KB（约 1.2 KB/条），而改造前每组合保留完整
成交/曲线（第 7 期基线 0.18 MB/组合）。因此当组合数从 36 扩到 1000 时：

- 改造前预计额外增长 ≈ `0.18 MB × (1000 − 36) ≈ 174 MB`；
- 改造后摘要总量 ≈ `1.2 KB × 1000 ≈ 1.2 MB`，且上限触发后不再增长（只落盘）。

### 2.3 结论

1. **数值不变**：新旧路径 231/225/235 笔、逐笔 sha1、逐点曲线一致（§4.1）。
2. **内存与组合数解耦**：峰值只与「单次结果 + 摘要上限 + Top-K」有关，不随 M 线性增长。
3. **耗时不是改善项**：36 次回测的引擎内耗时 `1879.7 vs 1894.9 ms`（K=800）、
   `3839.1 vs 3732.6 ms`（K=1600），差异 −0.8%~+2.9%，在交替测量的噪声范围内；
   摘要/哈希开销约 1 ms/次，未改变量级。
4. **超限不 OOM**：紧预算下 26 条摘要自动落盘到 `outputs/phase9_sweep_spool.jsonl`，
   内存峰值反而更低（6.04~9.17 MB）。

---

## 3. `BacktestConfig` 字段表（全部进参数快照）

`params_snapshot()` 结构：`schema_version / notes / strategy / data / account / backtest / risk / seed`。
`account`、`backtest`、`risk` 三段由全局 `Config.asdict` **完整展开**，不是只挑几个字段。

### 3.1 策略与数据

| 字段 | 来源 | 说明 |
|---|---|---|
| `strategy.name` | 调用方 / 策略注册表 | `trend_following`、`gene` 等 |
| `strategy.params` | 调用方 / 网格 | 策略参数；gene 时为 `{gene: {...}}` |
| `data.symbol` | 调用方 | 合约代码，如 `rb.SHFE` |
| `data.start` / `data.end` | 调用方 | 日期区间 |
| `data.period` | 调用方 | `D` / `5m` / `15m` / `30m` 等 |
| `data.warmup` | 调用方 | 预热根数 |

### 3.2 账户（`account` 段）

| 字段 | 说明 |
|---|---|
| `initial_capital` | 初始资金（显式覆盖入口 `initial_capital=`） |
| `margin_rate` | 保证金率 |
| `multiplier` | 默认合约乘数（合约规格缺失时的回退值） |
| `commission_per_lot` | 每手手续费（元） |
| `close_today_ratio` | 平今手续费折扣/系数 |
| 其余 `AccountConfig` 字段 | 由 `asdict` 全量记录，新增字段自动进入快照 |

### 3.3 成本 / 撮合（`backtest` 段）

| 字段 | 说明 |
|---|---|
| `fill_mode` | 成交模式（如 `next_open`） |
| `slippage` | 滑点（跳） |
| `slip_mode` / `slip_ratio` / `slip_atr_k` / `atr_window` | 百分比/ATR 滑点口径 |
| `limit_up_pct` / `limit_down_pct` | 涨跌停幅度（基于上一交易日结算价） |
| `pending_expire_bars` | 挂单过期根数 |
| `enable_roll_cost` | 换月成本开关 |
| `roll_spread_mode` | 换月价差口径（`none` / `charge` 等） |
| `enable_dominant_roll` | 真实主力换月（第 2 期，默认关） |
| 其余 `BacktestConfig` 字段 | 由 `asdict` 全量记录 |

### 3.4 风控（`risk` 段）

`RiskConfig` 全量记录，包括但不限于 `non_trading_hours_block`、`max_position_per_symbol`、
`margin_halt_ratio` 等。这样「非交易时段是否阻断」这类会改变 225/231 笔结果的开关，
不可能出现「没记进快照却影响了结果」。

### 3.5 可复现

| 字段 | 说明 |
|---|---|
| `seed` | 随机种子；`from_settings` 默认取 `cfg.evolution.seed` |
| `notes` | 调用方备注（不参与哈希） |

> 说明：`runner.execute()` 会把**策略实例的生效参数**（含类默认值）写回快照
> （`strategy_params`），因此快照里不会出现「参数为空、实际却用了默认值」的隐式情况；
> `gene` 策略除外（参数由基因串决定，已整体记录在 `strategy.params.gene`）。
> 该写回只影响快照/哈希，不参与撮合，锚点数值不变；代价是 `params_hash` 语义
> 从「调用方传入参数」变为「实际生效参数」，改造前落库的旧记录因此不可复跑（§4.2）。

---

## 4. 追溯字段与复跑

### 4.1 结果新增字段（纯追加，不改旧字段语义）

| 字段 | 示例 | 用途 |
|---|---|---|
| `run_id` | `bt_4a8cf17d6f5d` | 按 id 复跑/查库；同输入同 id |
| `params_json` | 规范化 JSON（含策略生效参数） | 完整参数快照（落库/导出） |
| `params_hash` | `5efc9a34ab984e7a` | 参数变更检测 |
| `seed` | `20240921` | 随机性复现 |
| `data_fingerprint` | `e38af91e97e8…`（40 位 sha1） | 行情窗口指纹 |
| `data_rows` / `data_first` / `data_last` | `1600` / 时间 | 指纹摘要的可读补充 |
| `data_source` / `is_synthetic` / `is_stale` / `as_of` | 沿用现有 provenance | 数据可信度 |
| `code_version` / `code_dirty` / `package_version` | git commit | 代码版本 |
| `trades_digest` / `equity_digest` / `result_hash` | sha1 | 逐笔/曲线/整体一致性 |
| `duration_ms` | 引擎内耗时 | 性能观测 |
| `roll_mode` / `roll_schedule_stats` | `dominant` / `monthly_approx` | 换月口径可追溯 |

### 4.2 `backtest_runs` 表（`data/quant_backtest.db`）

26 列：`run_id`(UNIQUE)、`created_at`、`symbol/start/end/period`、`strategy_name`、`seed`、
`params_hash`、`params_json`、`data_fingerprint`、`data_rows/data_first/data_last`、
`data_source/is_synthetic/is_stale/as_of`、`code_version`、`metrics_json`、
`trades_digest/equity_digest/result_hash`、`duration_ms`、`attempts`、`note`。

- 只存 KPI + 参数 + 指纹，**不存完整成交/曲线**（规模化设计的一部分）；
- 完整明细按需 `replay_run` 重跑或 `export_result` 落盘；
- 升级老库前自动备份到同级 `backups/`，文件名带时间戳不覆盖；
- 本次实测已在生产库创建该表并写入 2 条记录：

| run_id | 说明 | 状态 |
|---|---|---|
| `bt_4a8cf17d6f5d` | rb 全窗口锚点配置，`params_hash=5efc9a34ab984e7a`、`result_hash=8712b43909b8c4c0` | 可复跑基线（7 项校验通过） |
| `bt_0fcc0c97a0e4` | 改造前保存的同配置记录，`params_hash` 为旧语义（未含生效参数） | **已标记 `is_stale=1`**，备注说明不可作为复跑基线，保留审计不删行 |

- 写库前手工备份：`data/backups/quant_backtest_phase9b_20261104_230728.db`（171,536,384 字节）；
  建表迁移自动备份：`data/backups/quant_backtest_phase9_20261104_222016.db`（171,192,320 字节）。

### 4.3 复跑命令

```bash
# 1) 按 run_id 复跑并校验（默认离线本地日线 Feed，不写库）
python scripts/replay_run.py --run-id bt_4a8cf17d6f5d --db data/quant_backtest.db

# 2) 换行情源（原始 run 用的是分钟/其他数据时）
python scripts/replay_run.py --run-id bt_4a8cf17d6f5d --feed market

# 3) 复跑后导出（KPI / 成交 / 曲线 / 完整 JSON）
python scripts/replay_run.py --run-id bt_4a8cf17d6f5d --db data/quant_backtest.db \
  --export-dir outputs/replay_demo
```

实测输出（生产库 `bt_4a8cf17d6f5d`，7 项全部 `ok=True`）：

```
run_id=bt_4a8cf17d6f5d
symbol=rb.SHFE window=2020-01-01~2026-09-30 period=D strategy=trend_following
params_hash=5efc9a34ab984e7a data_fp=e38af91e97e87ff1b0801d05d1d225874797f44e
[OK ] params_hash      [OK ] data_fingerprint  [OK ] run_id       [OK ] result_hash
[OK ] trades_digest    [OK ] equity_digest      [OK ] metrics
复跑结论：一致
```

校验规则：数据指纹不一致 → 直接失败（说明「同一 id 已经不是同一段数据」）；
参数/结果哈希不一致 → 说明代码或配置已变化，同样失败，不会「模糊通过」。

### 4.4 参数扫描（服务层/脚本入口）

```python
from futures_quant.backtest.sweep import SweepLimits, run_sweep
from futures_quant.app.backtest_service import BacktestService

svc = BacktestService(cfg, feed)
base = svc.build_config("rb.SHFE", "2020-01-01", "2026-09-30", period="D", warmup=60)
report = run_sweep(
    feed, base,
    {"fast": [5, 10, 20], "slow": [30, 60], "stop_mult": [1.5, 2.5]},
    symbols=["rb.SHFE", "i.DCE", "cu.SHFE"],
    limits=SweepLimits(max_summaries_in_memory=50, memory_budget_mb=8.0,
                       top_k=5, summary_sink="outputs/sweep_summaries.jsonl"),
    detail_sink="outputs/sweep_details.jsonl",   # 需要每条明细时开启
)
```

- `summaries`：KPI + 曲线摘要，条数/字节受 `SweepLimits` 约束；
- `top`：Top-K 完整明细（默认 5 条），其余组合需要明细时按需重跑或看 `detail_sink`；
- `aggregate.best/worst/mean_sharpe`：即使摘要被落盘/丢弃也基于全量运行统计。

---

## 5. 验证记录

```bash
# 新用例 + 相关回归（99 项）
python -m pytest tests/unit/test_phase9_backtest_scale.py \
  tests/unit/test_m1_03_strategy_registry.py tests/unit/test_phase3_e2e_regressions.py \
  tests/unit/test_phase8_traceability_db.py tests/unit/test_phase8_dominant_roll.py \
  tests/unit/test_phase8_auto_evolve_upgrade.py tests/unit/test_phase0_accounting.py \
  tests/unit/test_phase1_roll_cost.py tests/unit/test_phase2b_portfolio_perf.py \
  -q --junitxml=outputs/phase9_unit_tests.xml
# -> {'tests': 99, 'failures': 0, 'errors': 0, 'skipped': 0, 'time': 18.8}
#   （其中 test_phase9_backtest_scale.py 27 项）

# 锚点逐位校验（内核撮合未改）
python scripts/perf_probe.py --section anchor
# -> verdict.all_ok: true；rb 231/225、i.DCE 235；用时 1.03s

# 规模 / 复跑实测
python scripts/research/phase9_backtest_scale.py
# -> 总判定 PASS，产物 outputs/phase9_backtest_scale.json

# 按 run_id 复跑（生产库）
python scripts/replay_run.py --run-id bt_4a8cf17d6f5d --db data/quant_backtest.db
# -> 7 项 [OK]，复跑结论：一致
```

未跑全量 e2e（按要求）；未执行任何 git 写操作；未修改版本号与 `ui/`。

---

## 6. 残留风险与依赖 GUI 期

### 6.1 残留风险（工程层面，如实列出）

1. **并行度未实现**：`run_sweep` 目前是顺序执行，只提供「内存预算 + 分批落盘」，
   没有多进程/线程并行。任务中的「最大并行组合数」以「内存上限 + 顶部摘要条数」
   的形式落地；真正的并行可复用 `SweepLimits`，但需要额外处理 Feed 线程安全与
   进程启动开销，本轮未做。
2. **run_id 不含工作区代码内容**：`code_version` 只取 commit；未提交改动通过
   `code_dirty` 标记，但不参与哈希。若在两份不同的未提交代码上跑同一配置，
   run_id 可能相同；此时 `result_hash` 校验会失败并明确报错（不会静默通过）。
   彻底解决需要对源码做内容哈希，成本高，留待需要时再做。
3. **复跑 Feed 需显式指定**：CLI 默认离线日线。若原始 run 用的是分钟/其他数据源，
   需传 `--feed market` 或自定义 Feed；数据指纹不一致会直接判失败，这是有意设计。
4. **库里不存完整明细**：`backtest_runs` 只存 KPI + 指纹。需要逐笔明细时必须复跑
   或依赖 `detail_sink`/`export_result` 产物；这是内存/库体积取舍，不是缺陷。
5. **摘要字节估算**：`summary_bytes_peak` 用 JSON UTF-8 字节估算，和真实 Python
   对象内存有差异（约 1.2 KB/条 vs 实测峰值总量 43.8 KB）。上限策略以估算值为准，
   留有余量，不会因此超预算。
6. **生产库新增 2 条记录 / 1 条被标记 stale**：可复跑基线 `bt_4a8cf17d6f5d`；
   改造前写入的 `bt_0fcc0c97a0e4` 因 `params_hash` 语义变更已标记 `is_stale=1`
   （保留审计、不删行），按 id 复跑会在 `params_hash` 校验处失败——这是设计中的
   显式失败，不是模糊通过。写库前已备份，需要回退时用
   `data/backups/quant_backtest_phase9b_20261104_230728.db`。

### 6.2 依赖 GUI 期（本轮未改 `ui/`）

| GUI 需求 | 依赖的内核能力（已就绪） |
|---|---|
| 参数面板（网格 fast/slow/atr/止损/手数） | `BacktestConfig.with_overrides`、`expand_grid` |
| 运行历史列表 / 筛选品种 | `BacktestStore.recent_runs`、`count_runs`、`db_stats.run_rows` |
| 「导出」按钮（KPI/成交/参数/指纹） | `export_result` / `export_stored_run` |
| 「复跑校验」按钮 | `runner.replay_run` / `BacktestService.replay` |
| 真实主力换月开关 | `BacktestConfig` 的 `enable_dominant_roll` + 服务层 `use_dominant_roll=` |
| 运行页展示 run_id / 数据指纹 / 合成水印 | 结果字段已全部返回 |
| 长任务进度/取消 | `run_sweep` 的 `on_progress`、`should_abort` |

GUI 接入建议：扫描放后台线程（只做执行与汇总，UI 只接收摘要/Top-K），
表格只渲染 `summaries` 与 `top`，不要在界面上持有全部完整结果。
