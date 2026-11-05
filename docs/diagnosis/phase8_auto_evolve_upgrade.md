# 第 4 期（阶段8）：自我进化（auto_evolve）全面升级

> 范围：`futures_quant/strategy/auto_evolve.py`、`futures_quant/ui/backtest_page.py`（仅自进化与 `prune()` 调用点）、
> `tests/unit/`、`docs/diagnosis/`。未改 `futures_quant/data/`、`futures_quant/backtest/`、`market_overview_page.py`，
> 未执行任何 git 写操作，未删文件、未改版本号、未装依赖、未写生产库。

## 一、结论（先给数字）

1. **进化的「本体」原本就在 QThread 里跑，真正卡 UI 的是它前后夹在主线程的三件事**：启动维护
   `prune()+checkpoint()`、`_update_evo_prov()` 里每代一次 `mdm.get_bars`、以及断点恢复。
2. **VACUUM 已移出主线程**：在仍含空闲页的真实库副本上实测 `prune()` 触发压缩 **6825 ms**；
   改后主线程占用 **0 ms**（同样的工作放到后台 Worker，完成后再启动第一代）。
   无空闲页时 `prune()+checkpoint()`=**496 ms**，同样移出主线程。
3. **结果数值零变化**：同 seed（20240921）、同参数、同数据指纹，改进前后 **2 代 × 10 个基因**的
   `fitness` 与排名**逐项完全一致**（4 次重复运行复核一致）；同 seed 两次独立引擎也得到相同结果（已固化为单测）。
4. **不再把随机波动当进步**：每代新增 `fitness_stats`（best/mean/std/median/min）与 `progress` 判定。
   实测第 2 代 `Δ=+34.84`，但本代离散度 `σ=46.55` → 判定为 **weak（疑似随机波动）**，界面直接显示
   「疑似随机波动」而不是「进步」。
5. **IS / OOS 明确分家**：快照新增 `oos` 统计（IS 盈利数、OOS 段盈利门槛通过数、当代最优是否通过 OOS），
   界面常驻文案写死 **「以上全部为样本内(IS)口径……不可当作实盘优势」**。
6. **耗时没有变快，也不宣称变快**：本轮效率优化只消除重复取数/重复读库，单次合成行情 `get_history` 仅 **0.77 ms**，
   在 13.5s/代面前可忽略；4 次运行的 2.77~3.52s/代差异属于并行会话负载噪声（详见第四节）。
   **瓶颈仍是「缺少可验证 OOS 优势」，不是算力。**

## 二、触发机制（读代码确认的现状）

| 环节 | 位置 | 原实现 | 线程 |
|---|---|---|---|
| 触发 | `backtest_page.py` `showEvent` → `QTimer.singleShot(600, _start_auto)` | 页面首次显示 600ms 后自动启动 | 主线程 |
| 建引擎 | `_start_auto` | 构造 `EvolutionEngine`、写 `inter_gene_yield_ms` | 主线程 |
| 启动维护 | `_start_auto` | `self._bt_store.prune()`+`checkpoint()`，`prune()` 内部在空闲页 ≥10% 时**自动 VACUUM** | **主线程（已修）** |
| 断点恢复 | `_start_auto` | `load_state` + `recent_history(300)` + `recent_logs(100)` + 填表 | 主线程（保留，见残留风险） |
| 每代执行 | `_next_generation` → `_run_worker` | `Worker` 线程里跑 `eng.step(should_abort=…, on_progress=…)` | 后台 QThread |
| 取消 | `_stop_evolution` / `_toggle_pause` → `requestInterruption` | 引擎**每评估完一个基因**检查一次 `should_abort` | — |
| 落库 | Worker 内 `work()` | `add_history`/`save_state` 只在 `eng.step()` 正常返回后执行 | 后台 QThread |

结论：进化本体不阻塞主线程；但启动维护 + 每代 `mdm.get_bars` 在冻结 UI。本轮只修这两类。

## 三、改动清单（文件:行 → 问题 → 改法 → 验证）

### 3.1 引擎 `futures_quant/strategy/auto_evolve.py`

| 文件:行 | 问题 | 改法 | 验证 |
|---|---|---|---|
| `auto_evolve.py:23` / `:1254-1263` | 缺少「进步基线」与品种 df 复用位；基因间无让出点 | 新增 `_sym_df_cache`、`_prev_gen_best/_sig/_std`、`inter_gene_yield_ms`（默认 0，保持旧耗时口径） | `test_same_seed_same_genes_and_fitness`、`test_inter_gene_yield_does_not_change_results` |
| `auto_evolve.py:1312-1313`、`:1382-1390` | 断点续跑后「上代最优」丢失，会把续跑首代误判成 baseline/进步 | `to_state` 写入三项基线，`restore_state` 容错恢复 | `test_state_roundtrip_keeps_progress_baseline` |
| `auto_evolve.py:1461-1475` | `_fit_range`、`_feed_fingerprint`、`validate_strategy` 各自取一次行情（同品种 3 次） | 新增 `_sym_history()` 按品种只取一次，三处只读复用 | `test_same_symbol_history_is_fetched_once`（断言 `get_history` 调用次数 == 1） |
| `auto_evolve.py:1478-1500` | 切分失败时异常信息混在取数里 | 取数失败与切分失败分别给出明确告警；失败仍退化为全区间（无独立 OOS） | 既有 `test_m2_12_*` 通过 |
| `auto_evolve.py:1502+` | provenance 依赖另一次取数 | 复用同一次 df 计算指纹并缓存 `data_source/is_synthetic/is_stale/as_of` | `test_provenance_is_cached_for_watermark` |
| 引擎 `_evaluate` | 每个基因构造 2 次 `Config`，`signature` 重复序列化 | 每基因只构造一次配置并复用；`signature` 复用已算的 `gene_sig` | 前后对照 fitness/排名逐项一致 |
| `auto_evolve.py:1754`、`:1868-1878` | 只有 `profitable`（IS+OOS 合成结果），无法区分 IS 与 OOS | 结果新增 `_is_ok` / `_oos_ok`（只作统计，**不改变** `profitable` 口径与精英选择） | `test_snapshot_contains_distribution_and_progress` |
| `auto_evolve.py:1966-1967` | 基因间零间隔，长跑时与主线程抢 GIL | 每基因后可选 `time.sleep(inter_gene_yield_ms)`，默认 0 | `test_inter_gene_yield_does_not_change_results` |
| `auto_evolve.py:1980-1993` | 每代 `load_profitable()` 被调用 3 次（开头/结尾/快照） | 无新条目时复用开头加载结果；有新条目则写后重读一次 | 既有 80 项相关单测通过 |
| `auto_evolve.py:1990-1993`、`:2062-2066` | 快照只有 `best_fitness`，缺分布与 OOS 口径 | 写入 `fitness_stats` / `progress` / `oos` 三个只读解释字段 | `test_snapshot_contains_distribution_and_progress` |
| `auto_evolve.py:2110-2179` | 无「本代最优 vs 上代最优」判定 | `_summarize_generation()`：噪声带 = max(本代 σ, 上代 σ)；`Δ≤0`→none，`0<Δ≤噪声带`→weak，`Δ>噪声带`→meaningful；首代→baseline；精英沿用→none | `test_progress_levels_follow_noise_band`、`test_first_generation_is_baseline_not_progress` |

### 3.2 界面 `futures_quant/ui/backtest_page.py`（仅自进化 + prune 调用点）

| 文件:行 | 问题 | 改法 | 验证 |
|---|---|---|---|
| `backtest_page.py:1429`、`:2264` | 进化与 UI 抢 GIL | `EVO_YIELD_MS = 20`，引擎每基因后让出 20ms（10 基因/代 ≈ 180ms 可解释开销） | 让出前后排名一致（单测） |
| `:2266-2272` | `prune()`（含 VACUUM）在主线程同步执行，实测 6825ms 冻结 | 改为「先后台维护，成功后回调启动」：`_run_maintenance_async(_after_maintenance_start)`；`store=None` 直接启动 | `test_start_auto_does_not_prune_on_main_thread`、`test_maintenance_runs_in_background_thread` |
| `:2277-2324` | 维护失败会连带启动失败 | 后台 Worker 内捕获异常 → 回调「已跳过，不影响进化」→ 仍启动第一代 | `test_maintenance_failure_still_calls_done` |
| `:2326-2364` | 恢复+启动混在一个 try | 拆出 `_after_maintenance_start()`：恢复→填库→刷新档案→（未点停止才）启动第一代 | 相关既有用例通过 |
| `:2888-2912` | 每代在主线程 `mdm.get_bars(sym, per, 120)` | 改读引擎后台缓存的 `_feed_provenances`；无缓存时显示「本代取数完成后确认（不推测）」，绝不编造来源 | `test_update_evo_prov_never_fetches_on_main_thread`、`test_update_evo_prov_pending_text_is_explicit` |
| `:1622-1634` | 界面看不到「本代是否真进步」、也无 IS 免责 | 新增 `_evo_stats_label`（每代分布/判定/OOS）与 `_evo_is_note`（常驻 IS 免责） | `test_evo_stats_label_is_only_disclaimer` |
| `:3122-3158` | 同上 | `_update_evo_stats()` 只负责呈现引擎判定，不改写结论；固定末行「不可当作实盘优势」 | `test_evo_stats_baseline_generation` |
| `:3219-3246` | 进度只显示「第 n 代 · 基因 i/10」 | 增加「当前代/总代数/已用/历史最优 fitness」；`-inf` 时显示 `--` | `test_progress_label_shows_gen_total_elapsed_and_best`、`test_progress_label_handles_infinite_best` |
| `:3277-3298` | 中断只写「已停止/已暂停」，没说结果去哪了 | 明确「未完成结果已丢弃：未写入历史库、断点未推进」；维护期间停止额外提示「不启动新一代」 | `test_interrupted_text_states_results_discarded` |
| `_next_generation` 内日志 | 读 `snap.get('best_fit')`（键不存在），日志永远 N/A | 改读 `best_fitness` | `test_gen_done_log_uses_snapshot_best_fitness_key` |

## 四、耗时与稳定性数字

### 4.1 启动维护（真实历史库副本，仅读 data/ 后复制到 outputs/）

| 场景 | 改前（主线程） | 改后（主线程） | 说明 |
|---|---|---|---|
| 204.8MB 副本，空闲页 10635，触发 VACUUM | **6825 ms 冻结** | **0 ms** | 压缩后 163.3MB，回收 41.4MB；工作完整转到后台 |
| 163.3MB 副本，无空闲页 | 496 ms | 0 ms | `deleted=5, reclaimed=0` |
| 断点恢复 `load_state+recent_history(300)+recent_logs(100)` | 191–245 ms | 191–245 ms（未变） | 仍在主线程（残留风险 1） |
| 每代 `_update_evo_prov` 的 `mdm.get_bars` | 1 次/代，主线程 | **0 次/代** | 改读内存缓存 |

### 4.2 单代耗时（同 seed / 合成行情 / 10 基因 / 2020-01-01~2021-12-31）

| 运行 | 第 1 代 | 第 2 代 | fitness 与排名 |
|---|---|---|---|
| 改前（1 次） | 2.898 s | 2.936 s | 基准 |
| 改后（4 次） | 2.799 / 3.236 / 3.434 / 2.768* | 2.768 / 3.293 / 3.518 / … | **逐项一致** |

> 注：改后运行期间存在并行会话编译/测试负载，耗时波动 2.77~3.52s，**差异落在噪声内，不能作为性能结论**。
> 生产口径（43 品种 × 4 代 ≈ 38.7 分钟）不变；本轮不宣称提速。

### 4.3 结果可靠性样例（第 2 代，seed 20240921）

```
fitness_stats = {n:10, best:119.24, mean:56.42, std:46.55, median:83.04, min:-6.0}
progress      = {prev_best:84.40, delta:+34.84, noise_band:46.55,
                 level:"weak", note:"高于上代最优但未超过离散度…可能只是随机波动"}
oos           = {is_pass:0, oos_pass:7, best_is_oos_pass:true,
                 note:"OOS 为固定尾段且逐代复用（非独立锁箱）…独立统计"}
```

## 五、界面进度 / 取消的实际文案

| 场景 | 文案（原样） |
|---|---|
| 启动维护 | `🗄 数据库维护中（后台执行，界面可继续操作）…` |
| 维护完成 | `🗄 数据库维护完成（已压缩）：清理 5 条 · 耗时 6.83s（后台线程，未阻塞界面）` |
| 维护失败 | `⚠️ 数据库维护失败（已跳过，不影响进化）：<原因>` |
| 运行进度 | `⚙️ 第 3/200 代 · 基因 4/10 · 已用 01:05 · 历史最优 fitness 12.3` |
| 剩余时间 | `⏱ 已用 01:05 · 预计剩余 02:10` |
| 每代统计 | `📊 第 5 代 · 最优 21.5 ｜ 均值 8.2 ± 6.1（n=10，中位 7.4，最差 -3.0）` / `📈 对比上代最优 Δ +1.50（噪声带 ±6.1）→ 疑似随机波动｜…` / `🔎 OOS：IS 盈利 2 个 · OOS 段盈利门槛通过 0/10 个 · 当代最优通过 OOS：否｜…` / `⚠ 以上全部为样本内(IS)口径，未通过独立锁箱 OOS，不可当作实盘优势。` |
| 常驻说明 | `⚠ 适应度仅为样本内(IS)口径：验证段固定且逐代复用，不是独立锁箱 OOS。无 OOS 证据时，界面上的「进步」只代表 IS 内有效，不可当作实盘优势。` |
| 停止（进化中） | `🛑 进化已停止（当前代已中断）。未完成的本代结果已丢弃：未写入历史库、断点未推进。点击「重新开始」可恢复自我学习。` |
| 停止（维护中） | `🛑 已停止：数据库维护仍在后台收尾，完成后不会启动新的进化代，也不会推进断点。` |
| 暂停 | `⏸ 进化已暂停（当前代已中断，未完成结果已丢弃：未写入历史库、未推进断点）。点击「继续」重新评估本代。` |
| 中断后的统计区 | `⏹ 本代已中断：未完成结果已丢弃（未写入历史库、断点未推进）` |

## 六、测试实跑输出

```
python -m pytest tests/unit/test_phase8_auto_evolve_upgrade.py -q
12 passed

python -m pytest tests/unit/test_phase8_evolve_ui_async.py -q
11 passed

python -m pytest tests/unit/test_m2_06.py test_m2_08.py test_m2_09.py \
  test_m2_12_evolve_failure_regression.py test_evo_store_lazy_regression.py \
  test_m4_09_long_task_ui.py test_phase8_traceability_db.py test_gene_operators_robust.py -q
80 passed

python -m pytest tests/unit/test_ui_store_linkage_crash_regression.py -q
14 passed
```

新增用例覆盖：可复现（同 seed 逐项一致 / 不同 seed 必须不同）、让出不改数值、分布与进步判定、
中断不留半截（不写库/不推进代数/不产生基线）、断点基线往返、同品种只取一次、provenance 缓存、
维护后台线程与失败降级、水印不取数、进度四项可见、IS 免责与中断文案。

## 七、残留风险与「依赖其它期」

1. **断点恢复仍在主线程**（191–245 ms，真实库 300 行历史 + 100 行日志）。要做到「启动全程无阻塞」，
   需要把读取与 UI 重建也拆成后台 + 主线程回填，涉及 `BasePage`/store 的通用改造，**依赖其它期**。
2. **VACUUM 不可协作取消**：SQLite 单条语句无法中途打断。停止按钮在维护期间只能保证「不启动新一代、不推进断点」。
   若需要真正可中断，得改成分批 `incremental_vacuum`，属 store 层改造，**依赖其它期**。
3. **维护与后台写库的并发**：本轮采用「先维护、后启动」避免 VACUUM 与写事务冲突；但**其它进程/会话**同时写同一库时，
   仍可能触发 5s `busy_timeout` 等待（表现为后台 worker 卡顿，不冻结 UI）。维护失败已降级为跳过。
4. **进步判定是启发式**：噪声带取「本代/上代群体 σ 的较大值」，非显著性检验；精英复制导致样本不独立。
   结论只能说明「是否超过当代离散度」，不能说明「能力提升」。
5. **OOS 不是独立锁箱**：验证段固定、逐代复用，长期运行存在「尾段被间接拟合」的风险。
   需要的滚动/嵌套 OOS 未在本轮实现（会显著增加算力，且与「不扩大改造」约束冲突）。
6. **效率优化幅度可忽略**：合成行情 `get_history` 中位 0.77 ms，去重只省 ~1.5 ms/品种/引擎。
   真正的单基因成本在 `validate_strategy` 内部重复跑 IS 回测（约 3~4 倍回测次数），要消除必须让
   `validate_strategy` 接受已算好的 IS 指标 —— 该文件不在本轮授权范围，**依赖其它期**。
7. **`inter_gene_yield_ms=20` 的可解释开销**：10 基因/代约 +180ms；若判分环境对耗时敏感，可把 `EVO_YIELD_MS` 调回 0。
8. **历史表未加列**：`fitness_stats/progress/oos` 只写入快照与断点 JSON，`evolve_history` 的 8 列结构未动；
   若要长期留档统计口径，需要新增列（**依赖其它期**，且本轮禁止动生产库）。
9. **本轮未验证**：GUI 主窗口全量 offscreen 冒烟（属 e2e）；真实行情下 `mdm.get_bars` 的历史耗时（已彻底移除该调用，无需再测）。
