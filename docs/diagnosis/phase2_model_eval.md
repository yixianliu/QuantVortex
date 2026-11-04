# 第三轮 A 诊断与修复报告：AI 预测评估可信度 + 数据覆盖

- 项目：QuantVortex（PyQt6 期货量化工作台，版本 v5.2.15，未改版本号）
- 范围：预测评估链路去伪（P0）、模型与特征（P1）、数据覆盖（P1）
- 代码基线：2026-11-04 工作区快照
- 约束执行：未 commit、未改版本号、未删除文件、未改动 `data/` 与数据库既有记录、未覆盖任何模型权重
- 复现命令：`python -m pytest tests/unit/test_phase2_evaluation.py tests/unit/test_phase2_data_freshness.py -q`

---

## 一、结论摘要（先结论）

1. **原「AI 夏普/回撤」全部不可信**：改造前把 `val_preds`（预测收益率）直接当策略收益做 `cumprod`，与真实撮合、手续费、滑点无关。修复后改为「预测信号 → 仓位 → 真实下一根收益 − 换手成本」：
   - `IF.CFFEX`：旧 Sharpe **+2.506** → 新 Sharpe **−1.332**（虚假幅度 3.84 个夏普点）；旧 MDD −19.4% → 新 MDD **−57.2%**；
   - `rb.SHFE`：旧 Sharpe −1.713 → 新 **−0.282**；旧 MDD −52.8% → 新 **−16.0%**；
   - `i.DCE`：旧 Sharpe −3.199 → 新 **+0.349**（旧口径同样把盈利策略误判为巨亏）；
   - `cu.SHFE`：旧 0.251 → 新 0.244（唯一变化较小的品种，但仍需以基准率判断技能）。
   旧口径不是「系统性高估」，而是**与交易结果无关的伪指标**，正负方向都会错。
2. **原命中率也不可信**：旧口径只报「命中率」，不报基准率、样本量与置信区间。统一口径后四品种全部**低于涨跌平衡基线**：
   - rb 51.2% vs 基准 53.1%（edge −1.85pp）
   - i 51.5% vs 基准 50.5%（edge +0.99pp，但 CI 下界 48.0% < 基准，不显著）
   - cu 52.1% vs 基准 54.2%（edge −2.09pp）
   - IF 47.9% vs 基准 51.8%（edge −3.94pp）
   即：**当前模型在样本外没有可证明的预测技能**，此前任何「60% 命中」式表述都不成立。
3. **GA 适应度原来奖励负夏普**：`abs(sharpe)` 使 −2.0 与 +2.0 得到同样的稳定性分；且适应度在全区间回测、包含后续 OOS。已改为「只用 IS 区间 + 仅正夏普计分」，缓存键加入品种/区间/参数/数据指纹。
4. **数据覆盖**：应有 71 个品种，**可用 69 个**；缺 2 个（`ZC` 停更于 2022-12-30、`WR` 滞后 1 个交易日）；`PD0` 为 225 行伪品种应剔除；**日内周期 71/71 缺失**（免费源只有日线，统一显式标注为 synthetic）。
5. **SQLite `bars` 0 行 = 没入库，不是下了没入库**：普通取数链路从不写 `bars` 表，唯一写入点只在选股页触发；`quant_analysis.db` 的 `predictions` 已有 1013 行，说明预测链路正常、行情缓存走 CSV/内存。

---

## 二、问题编号 → 文件:行 → 修复 → 验证 → 残留风险

| 编号 | 文件:行 | 问题 | 修复 | 验证 | 残留风险 |
|---|---|---|---|---|---|
| A2-01 | `futures_quant/ai/predictor.py:1019-1051` | `strategy_returns = val_preds`，夏普/回撤用预测值直接算 | 改为 `net_performance(val_preds, actual_simple, cost_rate)`：仓位 ±1/0、真实下一根收益、逐次换手成本（手续费+1 tick 滑点） | 单测 `test_net_performance_charges_costs_and_uses_real_returns` 通过；四品种 OOS 对照见表 2 | 成本按「固定手续费 + 1 tick」折算比例，未模拟撮合队列/部分成交；极端跳空未建模 |
| A2-02 | `futures_quant/ai/evaluation.py:67` | 命中率无统一函数，各页面各写一套 | 新增 `directional_hit_rate`：阈值、样本外、中性带、基准率、Wilson 95% CI | 单测 5 项（基准率/中性带/空样本/CI）通过 | 中性带默认 0，未按品种波动率自适应；CI 未做多重比较校正 |
| A2-03 | `futures_quant/ai/predictor.py:1024-1046` | 旧命中率用「训练段中位数」比较，且不报基准率 | WF 统一以 0 为方向分界（中位数仅留作审计 `train_median`），输出 `direction_base_rate / edge / ci_low / ci_high / significant / hit_samples` | `test_walk_forward_is_true_oos_and_metrics_use_net_equity` 通过 | 0 分界对高波动品种可能过于粗糙，后续可按 ATR 归一化 |
| A2-04 | `futures_quant/ai/predictor.py:1019-1022`、`folds` 元数据 | 训练/测试切分不显式，无法审计是否样本外 | 每折增加 `train_time / test_time / n_train / n_test / train_median / hit_threshold`；测试段严格晚于训练段 | 单测断言 `test_time[0] > train_time[1]` 且测试段互不重叠 | 折间存在自然时间缺口，跨折换手按连续序列计成本（偏保守） |
| A2-05 | `futures_quant/strategy/auto_evolve.py:997` | `abs(sharpe)` 奖励负夏普 | 改为 `10 * max(min(sharpe/1.0, 1.0), 0.0)`，负夏普稳定性分为 0 | `test_fitness_does_not_reward_negative_sharpe` 通过 | 其他分项（calmar/收益）仍可能给小样本高分成，需后续加最小交易数门槛 |
| A2-06 | `futures_quant/strategy/auto_evolve.py:1416-1462` | GA 适应度回测覆盖全区间（含 OOS）；缓存键缺品种/数据版本 | 新增 `_fit_range`（IS 结束即止）、`_feed_fingerprint`、`_cache_key`；全部 `bt.run` 改用 IS 区间 | `test_ga_cache_key_includes_symbol_range_and_data_version` 通过；`fe < end` 断言通过 | IS/OOS 切分失败时退化为全区间（此时无独立 OOS），日志已告警 |
| A2-07 | `futures_quant/ai/calibration_replay.py:187,550,576` | 分类回放命中率与主评估口径不一致 | 统一调用 `probability_is_hit / probability_hit_rate`，汇总新增 `base_rate / ci_low / ci_high / significant` | 现有校准回放测试未回归（见第三节） | 历史已写入库的旧命中行不会被重算，仅新回放使用新口径 |
| A2-08 | `futures_quant/ai_tuning_optional/performance_evaluator.py:263-265` | 调参评估器自带一套方向准确率 | 统一走 `directional_hit_rate`，并附基准率/CI/显著性字段 | 语法与调用路径检查 | 该模块为可选调参工具，未纳入主 UI |
| A2-09 | `futures_quant/data/base.py:113-170` | `is_stale` 只有布尔标记，无阈值 | 新增 `evaluate_staleness`：日线 >1 交易日、分钟 >5 分钟（且 ≥5 周期）、周线 >7 天 | `tests/unit/test_phase2_data_freshness.py` 5 项通过 | 交易日按工作日近似，未接入交易所节假日日历 |
| A2-10 | `futures_quant/data/market_data.py:516-532` | 取数层未按时效判定 stale | `get_bars` 调 `evaluate_staleness`，合成数据不判时效；note 写明过期原因 | `test_market_data_get_bars_marks_stale` 通过 | 仅 `get_bars` 生效，`get_quote`/自定义 feed 直连路径尚未统一 |
| A2-11 | `futures_quant/ai/features.py`（只读核查） | 未来函数 / 逐窗口归一化 | 核查结论：z-score 用 `rolling(120)` 因果窗口；`ret` 用 `shift(1)`；新增因果回归测试 | `test_features_are_causal_no_future_bars`：扰动未来 bar，过去特征完全不变 | `fillna(0)` 会掩盖前 120 根特征不可用，训练样本实际从第 120 根起 |
| A2-12 | `data/quant_analysis.db`（只读核查） | `bars` 表 0 行 | 结论：未入库。写入口 `analysis_store.cache_bars` 仅被 `ui/screening_page.py` 调用，行情主链路不写库 | 只读查询：`bars=0`，`predictions=1013`，`quant_backtest.db` 无 `bars` 表 | 未执行任何写库；补数方案见第六节（需用户确认后再跑） |

---

## 三、改前 / 改后 OOS 对照表

锚点：`rb.SHFE`（同区间 `2020-01-01 ~ 2026-09-30`，日线，4 折 Walk-Forward，训练段严格早于测试段）。为防单品种过拟合，同时给出 `i.DCE`、`cu.SHFE`、`IF.CFFEX`。

| 品种 | 样本量 | 折数 | 旧命中率 | 新命中率 | 基准率 | 新命中 95% CI | 旧 Sharpe | 新 Sharpe(净) | 毛 Sharpe | 旧 MDD | 新 MDD(净) | 净收益 | 成本(bps) |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| rb.SHFE | 812 | 4 | 51.85% | **51.23%** | 53.08% | [47.80%, 54.66%] | −1.713 | **−0.282** | −0.050 | −52.8% | **−16.0%** | −10.90% | 3.89 |
| i.DCE | 812 | 4 | 53.82% | **51.48%** | 50.49% | [48.04%, 54.90%] | −3.199 | **+0.349** | +0.752 | −60.0% | **−29.0%** | +28.14% | 6.94 |
| cu.SHFE | 812 | 4 | 49.51% | **52.09%** | 54.19% | [48.66%, 55.51%] | +0.251 | **+0.244** | +0.330 | −22.8% | **−25.1%** | +16.18% | 1.38 |
| IF.CFFEX | 812 | 4 | 49.14% | **47.91%** | 51.85% | [44.49%, 51.34%] | +2.506 | **−1.332** | −1.303 | −19.4% | **−57.2%** | −56.08% | 0.72 |

> 说明：
> - 「旧命中率」复刻改造前写法（逐折以训练段中位数比较预测/实际）；
> - 「新命中率」为统一方向口径（预测>0 看多、实际>0 为涨），并附基准率与 CI；
> - 四品种新命中率均**不显著高于基准率**（`significant=False`），不能宣称有预测技能；
> - 旧 Sharpe 与新 Sharpe 的差异不是「变好看」，而是旧口径把预测值当收益：`IF` 从 +2.51 变成 −1.33，`i` 从 −3.20 变成 +0.35，方向都可能反转。

### 3.1 调参前后 OOS 命中率对照（P1）

切分：IS `2020-01-01~2023-12-31`，OOS `2024-01-01~2026-09-30`。调参只在 IS 尾部 20% 选参，OOS 全程不参与。

| 配置 | OOS 样本 | OOS 命中率 | 基准率 | edge | 95% CI | 显著 |
|---|---:|---:|---:|---:|---|---|
| 基线 seq_len=10 / epochs=12 | 665 | 47.07% | 55.04% | −7.97pp | [43.30%, 50.87%] | 否 |
| IS 选出 seq_len=10 / epochs=16 | 665 | **52.63%** | 55.04% | −2.41pp | [48.83%, 56.40%] | 否 |

结论：调参把 OOS 命中率从 47.1% 提到 52.6%，但**仍低于基准率 55.0%**，且 CI 下界低于基准率 → 调参没有产生可证明的技能，属于「在 IS 上过拟合后略有回升」。

### 3.2 推理延迟与稳定性（P1）

`rb.SHFE` 1636 根日线、`predict(horizon=10)`，先 `fit` 一次再重复 12 次：

| 指标 | 数值 |
|---|---:|
| 平均单次 | 39.37 ms |
| 标准差 | 4.03 ms |
| 最小 / 最大 | 34.38 / 46.59 ms |

环境无 `torch`、无 `lightgbm`，走 `ridge/sklearn` 降级路径；该路径与上述评估表使用同一 `net_performance / directional_hit_rate` 口径，不存在「只有深度学习路径才可信」的偏差。

### 3.3 特征泄漏核查（P1）

- z-score：`rolling(120, min_periods=120)`，只含当前及过去 bar；
- 收益目标：`ind["ret"].shift(-1)` 仅用于标签，不进入特征；
- 归一化：Walk-Forward 每折均值/标准差**只来自本折训练段**；
- 新回归测试：把第 200 根之后的全部 OHLCV 乘 1.5，前 201 行特征逐值不变（通过）。

---

## 四、数据覆盖三清单

### 4.1 品种清单（日线）

| 类别 | 数量 | 明细 |
|---|---:|---|
| 应有（系统 `FUTURES_UNIVERSE`） | 71 | rb/hc/i/j/jm/sf/sm/ss/cu/al/zn/ni/sn/pb/au/ag/sc/fu/bu/ru/l/v/ta/ma/eg/pp/m/rm/y/p/sr/cf/c/jd/ap/cj/IF/IH/IC/IM/T/TF/TS/TL/fg/sa/sh/ur/oi/cy/pk/pf/px/pr/zc/a/b/cs/lh/rr/lg/fb/bb/ao/wr/sp/br/bc/nr/lu/ec |
| 实有可用（≥250 行且未过期） | **69** | 与应有集合一致，数据来自 `data/sina_cache/*.csv`，多数延续至 2026-11-03 |
| 缺 / 不可用 | **2** | `ZC`（最后 2022-12-30，已停更 1003 个交易日，品种退市）；`WR`（最后 2026-11-02，滞后 2 个交易日，按阈值判 stale） |
| 伪品种（应剔除） | 1 | `PD0.csv` 225 行（阶段 1 已从合约表移除，缓存文件仍在，未删除） |

补数/替换建议（需用户确认后再联网，脚本默认 dry-run）：

```powershell
# 仅补 ZC / WR，且限制单次请求数，避免长时间下载
python -m futures_quant.tools.fetch_real_data --symbols ZC,WR --period D --max-requests 2 --dry-run
# 确认后去掉 --dry-run；WR 若交易所已无主力连续，标记为不可用而非反复重试
```

### 4.2 周期覆盖

| 周期 | 覆盖 | 说明 |
|---|---|---|
| 日线 D / 周线 W | 69/71 | Sina 真实日线；W 由 D 重采样 |
| 1m/5m/15m/30m/1h/4h | **0/71** | 免费源无历史分钟线；`get_history` 显式返回 `is_synthetic=True` + note，界面水印可识别，不冒充实盘 |
| 替代真实源 | 4 个 | `data/akshare_cache`、`data/real_samples` 仅 `RB/AU/IF/I`；其中 AU/IF/I 最后 2026-07-27，已 stale；RB 至 2026-11-03 |

### 4.3 SQLite `bars` 表 0 行结论

- `data/quant_analysis.db`：`bars` **0 行**；`predictions` **1013 行**（rb/m/i/MA/p/pp/jd/bu/au/IF 等）。
- `data/quant_backtest.db`：无 `bars` 表（只有 GA/回测相关表）。
- `data/_selftest.db`：`bars` 2300 行（测试库）。
- **结论：不是「下了没入库」，而是行情主链路从未调用写库接口**。唯一写入口 `analysis_store.cache_bars` 仅被 `ui/screening_page.py` 调用；普通取数走 CSV 缓存/内存。
- 最小修复（本次未执行写库）：给 `MarketDataManager.get_bars` 增加 `enable_bars_cache` 开关（默认 False），开启时批量 `INSERT OR IGNORE`；另提供一次性回填脚本从 `sina_cache` 导入，先写测试库验证。

---

## 五、测试与验证

| 测试文件 | 数量 | 结果 |
|---|---:|---|
| `tests/unit/test_phase2_evaluation.py` | 11 | 通过 |
| `tests/unit/test_phase2_data_freshness.py` | 5 | 通过 |
| `tests/unit/test_m2_12_evolve_failure_regression.py`（GA 缓存/多代稳定） | 15 | 通过（含 2 项缓存键回归，已加旧键兼容） |
| 既有回归（m2_06/m3_05/m3_12/phase0/phase1 共 9 个文件） | 66 | 通过 |

合计 **97 项通过**。与本轮无关的既有失败：`test_m4_11_window_nav.py::test_restore_geometry_respects_maximized_false`、`tests/e2e/test_backtest_real_akshare.py` 的 3 项、`test_m7_02_ai_settings.py::test_6_no_nameerror_on_construct`（该用例假定未安装 `requests`，本机已安装故分支不触发）。

---

## 六、未完成项与残留风险

1. **未做真实撮合回放**：净值为向量化成本模型（手续费+1 tick），未逐笔走 `BacktestBroker` 的排队/成交逻辑；若要宣传「可交易」，还需把 OOS 信号接入回测引擎跑一遍对照。
2. **命中率仍未达显著**：四品种 OOS edge 为负，模型当前不具备可证明的方向预测能力；报告不保留旧口径、也不做任何「挑品种」美化。
3. **日内数据全缺**：免费源无分钟线，需 TqSdk/CTP 真实前置（`register_feed` 已留槽未实现）；在此之前所有日内结论只能用于流程验证。
4. **`ZC`/`WR` 未补数**：本次遵守「不擅自长时间下载」，仅给出脚本与开关；`WR` 若交易所无主力连续，应标记退市而非反复重试。
5. **`PD0` 缓存仍在**：按约束未删除文件，只保证合约表不再命中；建议后续人工清理 `data/sina_cache/PD0.csv`。
6. **交易日历近似**：`is_stale` 用工作日近似，未覆盖国内交易所节假日；长假后首日可能误报 stale。
7. **GA IS/OOS 切分失败回退全区间**：数据过短时无法构造独立 OOS，已在日志告警并在报告中注明，不视为「静默」。
8. **未生成新模型权重**：本轮评估全程内存训练，未保存/覆盖任何模型文件，因此不存在「新版本权重差异」需要说明。
