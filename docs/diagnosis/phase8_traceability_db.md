# 阶段8：回测/进化结果可追溯 + 历史库治理

> 范围：`futures_quant/storage/`、`futures_quant/strategy/auto_evolve.py`（缓存与快照元数据部分）、`tests/unit/`、`docs/diagnosis/`。
> 未改动 `futures_quant/ui/`、`futures_quant/data/`、`futures_quant/backtest/`，未执行任何 git 写操作（不 add / commit / stash / checkout / reset）。

---

## 一、结论先行（实测数字）

### 1. P0-1 缓存命中不再被误判（核心）

修复前：`_evaluate()` 命中缓存时返回 `metrics={}`、`profitable=False`、`trades=[]`，同一基因第二次评估被系统性判为「不赚钱」，精英选择与进化结果被污染；`step()` 命中分支还会再全量重跑一次且用 `fitness(m)`（丢失树深惩罚），同一基因两次评分不同。

修复后（`rb.SHFE` 日线，合成行情 504 根 bar，seed=42）：

| 指标 | 首次评估（未命中） | 第二次评估（缓存命中） | 是否一致 |
|---|---|---|---|
| fitness | 56.430000 | 56.430000 | ✅ 完全相等 |
| metrics（含 sharpe/收益/回撤等 14 项） | `{"sharpe": 1.448, "total_return": 0.0117, ...}` | 同左，整字典相等 | ✅ |
| profitable | False | False | ✅ |
| trades 条数 | 26 | 26 | ✅ |
| equity_curve 点数 | 504 | 504 | ✅ |
| 单次耗时 | **183.0 ms** | **0.0 ms（<0.1ms）** | 节省 100% |

同一份实测脚本还验证了同一个 `step()` 内出现两条完全相同的签名（`6890dfb5` 重复出现两次、fitness 均为 33.02）——修复前第二条必然被误判为不赚钱。

### 2. P0-2 结果可追溯字段（新增 8 列）

`evolve_history` 新增：`run_id`、`data_fingerprint`、`seed`、`params_json`、`data_source`、`created_at`、`is_synthetic`、`as_of`
（任务要求的 6 个 + 数据来源可信化所需的 `is_synthetic`/`as_of`，均为可空列，向后兼容）。

写入端由进化快照提供（`run_id` 由 `started_at+seed+区间+周期+git_rev` 派生，同一运行内稳定）；读取端对迁移前的老行一律返回 `None` 并标注：

```
trace_status = "legacy_missing"
trace_note   = "老记录无指纹（阶段8 迁移前写入，无法追溯数据来源/种子）"
```

实测：迁移后读取最新 3 条历史均为 `legacy_missing`、`data_fingerprint=None`、`seed=None`，未用任何默认值填充。

### 3. P0-4 可复现验证（同参数 + 同种子 + 同指纹 ⇒ 同结果）

两次独立构造的引擎（`seed=2024`、同一品种区间周期、`POP_SIZE=3`）各跑一代：

| 项目 | 结果 |
|---|---|
| 数据指纹 | 两次均为 `2024592ab308` ✅ |
| 参数快照 | 两次完全相等 ✅ |
| run_id | `run_45de6e97d3b4`（同运行稳定，不随代数变化） |
| ranked（签名 + fitness 序列） | 逐项完全一致 ✅ |

回归用例：`test_same_seed_params_and_fingerprint_reproduce_same_results`。

### 4. P0-3 库治理（体积 / 行数前后）

| 项目 | 治理前 | 治理后 | 变化 |
|---|---|---|---|
| 库文件体积 | 214,790,144 B（204.84 MiB） | 171,192,320 B（163.26 MiB） | **-43,597,824 B（-20.3%）** |
| `evolve_history` 行数 | 1001 | 986 | -15（空行，先归档后删除） |
| `evolve_history_archive` 行数 | 0 | 15 | +15（可回滚） |
| freelist 空闲页 | 10,642 页（约 41.6 MiB） | 0 页 | 已回收 |
| 迁移耗时 | — | 0.067 s（补列 + 归档空行） | — |
| `prune()` 耗时（含 VACUUM） | — | 6.588 s（205MB 库整库重写，仅触发一次） | — |

`prune()` 本次删除 2 行 `evolve_log`（history 986 < 1000 上限，未删历史行）；治理后再次 `prune()` 因空闲页为 0 不会重复 VACUUM。

### 5. 测试实跑结果

```
tests/unit/test_phase8_traceability_db.py + test_m2_12_evolve_failure_regression.py
  → 28 passed, 0 failed, 0 skipped, 14.640 s

关联回归（phase2_evaluation / m2_06 / m2_08 / m2_09 / ui_store_linkage / gene_operators）
  → 51 passed, 0 failed, 0 skipped, 10.186 s
```

合计 **79 项通过、0 失败**，仅跑单元测试，未跑全量 e2e。

---

## 二、改动清单（文件:行 → 问题 → 改法 → 验证）

### 2.1 进化缓存（`futures_quant/strategy/auto_evolve.py`）

| 文件:行 | 问题 | 改法 | 验证 |
|---|---|---|---|
| `auto_evolve.py:1237` | 缓存值只有 `(gene, fitness)`，缺完整结果 | 结构升级为 `{"gene", "fitness", "result"}`；`result` 为一次完整评估产物；新增 `_fit_cache_max=200` 与 provenance 缓存 | `test_cache_hit_scores_identical_to_first_evaluation` |
| `auto_evolve.py:1547` (`_cache_get`) | 老二元组无法复用却被当作命中 | 读到 tuple 直接清除（结构升级，不做兼容转换）；命中时刷新 LRU 顺序 | `test_legacy_tuple_cache_is_invalidated_and_upgraded` |
| `auto_evolve.py:1561` (`_cache_put`) | 缓存无上限，完整结果长跑会累积数百 MB | 按 LRU 淘汰，容量上限 200 条（约最近 20 代，覆盖每代 2 个精英） | `test_cache_lru_bounds_entries` |
| `auto_evolve.py:1571` (`_cache_hit_result`) | 命中只回填「无利」占位 | 命中返回完整结果副本（metrics/profitable/trades/curve 原样复用），打 `_cache_hit` 标记 | 同上；`test_cache_hit_preserves_profitable_and_metrics` |
| `auto_evolve.py:1585` (`_evaluate_fitness_only`) | 只存 fitness 的邻域条目会被主评估误当完整命中 | 只写 `{"gene","fitness","result":None}`，主评估命中此条目时补全完整评估并升级 | `test_fitness_only_entry_triggers_full_evaluation` |
| `auto_evolve.py:1613-1670` (`_evaluate`) | 命中缓存返回空指标 → 误判不赚钱 | 命中直接返回完整结果；miss 后完整评估并写入完整结果；新键回写（老键仅兼容查询） | 实测表 1；两个缓存用例 |
| `auto_evolve.py:1750-1870`（并行/顺序 `step()`） | 命中后仍全量重跑一次，且用 `fitness(m)` 丢树深惩罚 → 两次评分不一致 | 删除两处「命中后重跑」分支，直接使用缓存完整结果；并行子进程评分统一为 `fitness(m, gene=gene)`，缓存由父进程写入（子进程写缓存不会回传） | `test_m2_12_*` 18 项全通过；实测 fitness 两次相等 |
| `auto_evolve.py:1498-1535`（`_run_id/_params_snapshot/_trace_meta`） | 快照无任何「用什么数据/参数/种子跑的」信息 | 新增三个只读派生方法（不改变实验语义），`run_id` 由实验元数据哈希派生 | `test_step_snapshot_carries_traceability_fields` |
| `auto_evolve.py:1525`、`auto_evolve.py:1959-1987` | 快照缺可追溯字段 | 快照新增 `run_id/created_at/seed/data_fingerprint/data_source/is_synthetic/as_of/params_snapshot` | 同上 + 迁移/写入用例 |
| `auto_evolve.py` `_feed_fingerprint` | 指纹只算哈希，未留来源元数据 | 同一次取数顺带缓存 provenance（来源/合成/时效/as_of）；取数失败显式留空（不编造） | 指纹格式与 `data_source= synthetic` 断言 |

### 2.2 历史库（`futures_quant/storage/backtest_store.py`）

| 文件:行 | 问题 | 改法 | 验证 |
|---|---|---|---|
| `backtest_store.py:40` (`_TRACE_COLUMNS`) | 表结构无审计字段 | 新增 8 个可空列（`run_id/data_fingerprint/seed/params_json/data_source/created_at/is_synthetic/as_of`） | `test_migration_is_idempotent_and_archives_empty_rows` |
| `backtest_store.py:52` (`_EMPTY_ROW_WHERE`) | 库内 15 行全空（无指标/成交/曲线/签名） | 定义统一空行判定，仅迁移/清理时使用 | 同上 |
| `backtest_store.py:127` (`_migrate_schema`) | 老库缺列 → `add_history` 静默失败；迁移不清理脏行 | 幂等补 R6 + 阶段8 列；补完后归档清理空行；写 `schema_version=8` 到 `evolve_state` | 迁移幂等用例（打开两次行数/归档数不变） |
| `backtest_store.py:166` (`purge_empty_history`) | 空行直接删会丢证据 | 先整行 JSON 写入 `evolve_history_archive(reason='empty_row')` 再删除；失败整体回滚 | 归档内容断言 `metrics_json='{}'` 且 `src_id` 保留 |
| `backtest_store.py:200` (`db_stats`) | 治理前后无对照口径 | 返回主库/WAL 体积、page/freelist、行数、归档数 | 库治理实测表 |
| `backtest_store.py:227` (`vacuum`) | 无压缩能力，删除的页永远停在 freelist | `commit → wal_checkpoint(TRUNCATE) → VACUUM → checkpoint`，返回压缩前后体积与回收字节 | `test_prune_triggers_vacuum_and_shrinks_db`；生产实测 -20.3% |
| `backtest_store.py:295-410` (`add_history`) | 空行写入无防护；可追溯字段未落库 | 无 `symbol` 或无 `ranked` 直接拒写并告警；写入 8 个追溯列（缺失保持 NULL，种子非整数也置 NULL，绝不编造）；`as_of` 截断到秒 | `test_add_history_writes_trace_fields_and_rejects_empty_rows` |
| `backtest_store.py:411-446` (`recent_history` / `_annotate_trace`) | 老行与有指纹行无法区分 | 每行补 `trace_status`(`ok`/`legacy_missing`) 与 `trace_note`，字段值保持 SQL 原值 | 老库用例断言 `None` + 中文说明 |
| `backtest_store.py:447-520` (`get_history_detail`) | 参数快照读不出来 | 解析 `params_json → params`（老行为 `None`）；同样标注 `trace_status` | 老库 + 新写入用例 |
| `backtest_store.py:522` (`prune`) | 只删不压，205MB 长期不降 | 删除后按「freelist ≥ max(200 页, 全库 10%)」自动 VACUUM；`vacuum=True/False` 可强制/跳过；返回删除数与体积对照（兼容原无返回值调用） | 测试 + 生产实测 |

### 2.3 测试

| 文件 | 内容 |
|---|---|
| `tests/unit/test_phase8_traceability_db.py`（新增，10 项） | 缓存一致性、盈利标记保留、老结构失效、fitness-only 补全、LRU 上限、快照追溯字段、可复现、迁移幂等 + 空行归档、写入追溯 + 空行防护、prune+VACUUM 缩容 |
| `tests/unit/test_m2_12_evolve_failure_regression.py`（修改 3 处） | 原用例直接塞 `(gene, fitness)` 老结构、期望命中返回空指标的语义已废弃；改为写入新结构（`_seed_cache_entry` 辅助函数），其余断言保持不变 |

---

## 三、迁移与回滚步骤

### 迁移（已在生产库执行，自动且幂等）

1. 备份：`data/backups/quant_backtest_phase8_20261104_214545.db`（`sqlite3.Connection.backup` 在线备份，214,790,144 B，`integrity_check=ok`，1001 行）。
2. 打开 `BacktestStore` 即自动迁移：补 8 列 → 归档并删除 15 行空行 → 写 `evolve_state.schema_version=8`。
3. `prune()`（进化启动时 UI 本来就会调用）按空闲页自动 VACUUM，回收 41.6 MiB。

重复执行安全：补列有 `PRAGMA table_info` 存在性判断；空行归档后源行已删除，二次执行归档数不再增长（实测打开两次均为 986 行 / 15 归档）。

### 回滚

```python
# 方式 A：按归档 payload 原样回填（payload 是迁移后 SELECT * 的整行 JSON，
# 含新增列，可直接重建整行；如有主键冲突请先调整 id）
import json, sqlite3
conn = sqlite3.connect("data/quant_backtest.db")
for (payload,) in conn.execute(
        "SELECT payload_json FROM evolve_history_archive WHERE reason='empty_row'"):
    row = json.loads(payload)
    cols = ",".join(row.keys())
    marks = ",".join("?" * len(row))
    conn.execute(f"INSERT INTO evolve_history({cols}) VALUES({marks})",
                 list(row.values()))
conn.commit()
```

方式 B（彻底回滚）：关闭程序 → 用 `data/backups/quant_backtest_phase8_20261104_214545.db`
覆盖 `data/quant_backtest.db`，并删除同名 `-wal`/`-shm`。
新增列全部可空，旧代码即使保留新列也不受影响，无需 `ALTER TABLE DROP COLUMN`。

---

## 四、残留风险与未完成项

1. **VACUUM 在主线程执行**：`prune()` 由 `ui/backtest_page.py` 在进化启动时同步调用，实测 205MB 库压缩耗时 6.6s。已通过 10% 空闲页门槛把触发频率降到「约每 120 代一次」，但首次压缩仍可能造成一次可见卡顿；彻底方案需把维护任务移到后台线程（涉及 `ui/`，本轮不改）。
2. **完整结果缓存的内存占用**：单条结果含 504~1600 点曲线与成交明细，200 条上限最坏约几十 MB；若后续曲线点数增大，建议下调 `FIT_CACHE_MAX` 或只缓存最近若干代。
3. **老历史行不可追溯**：迁移只保证「新写入可追溯」，历史 986 行仍为 `legacy_missing`。UI 尚未展示 `trace_status/trace_note`（`ui/` 不在本轮范围），需后续一轮在历史表/详情对话框显式标注「老记录无指纹」。
4. **并行路径仍为实验性**：`ProcessPoolExecutor` 分支默认关闭，闭包 `evaluate_gene_pair` 引用 `self`，在 Windows spawn 下仍可能无法 pickle（历史遗留问题，本轮未改变其可用性，仅统一了评分与缓存写入语义）。
5. **run_id 碰撞**：由 `started_at + seed + 区间 + 周期 + git_rev` 哈希派生，同一秒内以完全相同参数启动两次会得到同一 `run_id`；如需强唯一，可改为额外混入 uuid（本轮未加，避免影响可复现性语义）。
6. **`as_of` 精度**：落库截断到秒（`YYYY-MM-DD HH:MM:SS`），丢失亚秒信息；对「日线数据时效」判断无影响。
7. **空行防护只覆盖 `add_history`**：`evolve_state` 快照仍可能保存空 `ranked`（属断点状态而非历史行），未纳入治理口径。
