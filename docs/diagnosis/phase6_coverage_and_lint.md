# Phase 6：预测区间真实覆盖率落库 + pre-commit 告警核查

> 范围：只做数据层/评估接口与工具告警修复；未改 UI 展示逻辑、指标与回测内核，未 commit、未改版本号。
> 数据库只执行「新增列」；迁移前已完成全库备份。

---

## 一、问题

### 1.1 覆盖率口径不是真的

- 预测页「历史实际覆盖率」由 [`_band_coverage`](../../futures_quant/ui/predict_ops_page.py) 现算：
  用当前模型残差 `resid_std` 生成 `±σ√h` 的累计对数收益带，再回看最近 ≤240 个 h 步窗口。
  它衡量的是「历史涨跌幅有没有落进当前 σ 的带子」，**不是**「预测当时落库的区间命中了没有」。
- `predictions` 表迁移前没有 `lower / upper / band_sigma / model_version / data_fingerprint`，
  已结算记录无法回溯核算，只能在页面上用近似值展示。
- 79.7% 的来源见 [`phase3_e2e_gui.md` §5.1](phase3_e2e_gui.md)：那是 offscreen 冒烟**注入合成预测结果**后
  断言的界面文本，并非真实行情回放结论。

### 1.2 三处 pre-commit 告警

`tools/hooks/pre-commit` 调用 `tools/scan_silent_bail.py`，规则 `CHAIN`：

1. 某变量在 `except` 分支被显式钉成 `None`；
2. 之后出现「判空 return」，把该能力悄悄跳过；
3. 若 return 之前没有可见日志/显式豁免，才算 `silent=True`，`high + silent` 才阻断提交。

对 `backtest_page.py:2511`、`splash.py:108/122` 的扫描结果是 `CHAIN=3 / silent=0 / rc=0`，
说明**不是真静默失效**；问题在工具把「已留痕/已豁免」的非阻断项也按「能力静默失效」文案和 ⚠️ 打印，造成误读。

---

## 二、改动文件与位置

| 文件 | 位置 | 改动 |
| --- | --- | --- |
| `futures_quant/storage/analysis_store.py` | L167-L173 | `_migrate_predictions` 新增 5 列，`PRAGMA table_info` 幂等检查，老数据保持 NULL |
| 同上 | L216-L247 | `save_prediction` 落库 `lower/upper/band_sigma/model_version/data_fingerprint`（缺省写 NULL） |
| 同上 | L248-L307 | `save_closed_prediction` 同步落库，回放/结算路径共用 |
| 同上 | L308-L329 | 新增 `query_closed_with_bands(limit)`，返回覆盖率回溯所需字段（含 NULL 老数据） |
| `futures_quant/ai/predictor.py` | L424-L458 | 新增 `_model_version()` 与 `data_fingerprint()`（sha256 前 16 位，覆盖品种/周期/样本量/首尾时间/尾部 5 收盘） |
| 同上 | L652-L655 | 正常预测结果增加 `band_sigma/model_version/data_fingerprint` |
| 同上 | L739-L742 | 降级结果 `band_sigma=0.0` 并带元信息，便于覆盖率核算时明确剔除 |
| `futures_quant/ai/evaluation.py` | L330-L712 | 新增真实覆盖率接口、分组统计、训练/测试校准建议 |
| `futures_quant/ai/calibration_replay.py` | L202-L211 | walk-forward 回放写入区间字段（供真实覆盖率回溯，不写生产库） |
| `futures_quant/ui/predict_ops_page.py` | L2332-L2342 | **只补落库字段**，未改任何展示逻辑 |
| `futures_quant/ui/pages.py` | L1948-L1958 | 同上（旧预测页保存路径） |
| `tools/scan_silent_bail.py` | L305-L312、L400-L405 | 非 silent 的 CHAIN 改为 ✅ +「已留痕/已豁免，不阻断」，摘要明确区分；门禁语义未变 |
| `tests/unit/test_phase6_interval_coverage.py` | 全文 11 个用例 | 覆盖率、None+原因、NULL 老数据、分组、校准、迁移幂等/回滚兼容 |
| `scripts/research/phase6_coverage_audit.py` | 全文 | 真实行情 walk-forward 覆盖率审计（临时库，不碰生产数据） |

### 2.1 评估接口（供 UI 会话直接调用）

```python
from futures_quant.ai.evaluation import evaluate_interval_coverage

result = evaluate_interval_coverage(store=analysis_store)  # 或 rows=[...]
# 有样本：result["coverage"] / ci / verdict（over/under/aligned/insufficient）
# 无样本：result["coverage"] is None 且 result["reason"] 明确
```

- `coverage is None` 时**不得**回退成 `_band_coverage` 近似值；接口本身不会返回近似数字。
- 分组：`by_symbol`、`by_horizon`、`by_volatility`（相对区间半宽三分位 low/mid/high）。
- 每组样本 <30 一律 `coverage=None + reason`。
- 校准：`recommend_band_multiplier(rows, target=...)` 只用训练段取 `z` 的 `target` 分位数，
  测试段仅验证；`rule` 字段写明「测试段不参与定参」。

---

## 三、迁移 SQL 与备份

### 3.1 备份（已实际执行）

```powershell
# Python sqlite 在线备份（已执行）
python -c "import sqlite3; s=sqlite3.connect('data/quant_analysis.db'); d=sqlite3.connect('data/backups/quant_analysis_phase6_20261104_154259.db'); s.backup(d); d.close(); s.close()"
```

| 项 | 值 |
| --- | --- |
| 备份路径 | `data/backups/quant_analysis_phase6_20261104_154259.db` |
| 大小 | 286,720 bytes |
| 备份校验 | `PRAGMA integrity_check = ok` |
| 备份内行数 | `predictions = 1013`，与迁移前一致 |

### 3.2 迁移 SQL（向前兼容，只加列）

```sql
ALTER TABLE predictions ADD COLUMN lower REAL;
ALTER TABLE predictions ADD COLUMN upper REAL;
ALTER TABLE predictions ADD COLUMN band_sigma REAL;
ALTER TABLE predictions ADD COLUMN model_version TEXT;
ALTER TABLE predictions ADD COLUMN data_fingerprint TEXT;
```

- `horizon` 自 v1 已存在，不重复新增；迁移只补区间与元信息列。
- 代码中的 `_migrate_predictions` 先读 `PRAGMA table_info(predictions)`，已存在则跳过 → 可重复执行。
- 所有 `INSERT` 对缺失字段写 `NULL`，旧调用方无需同步改造。

### 3.3 回滚

优先直接恢复备份（最安全，包含数据与 schema）：

```powershell
Copy-Item data/backups/quant_analysis_phase6_20261104_154259.db data/quant_analysis.db -Force
```

若只需回退 schema（SQLite ≥ 3.35）：

```sql
ALTER TABLE predictions DROP COLUMN data_fingerprint;
ALTER TABLE predictions DROP COLUMN model_version;
ALTER TABLE predictions DROP COLUMN band_sigma;
ALTER TABLE predictions DROP COLUMN upper;
ALTER TABLE predictions DROP COLUMN lower;
```

### 3.4 迁移后校验（生产库）

```text
integrity = ok
predictions total = 1013
closed_with_actual = 1013
lower/upper 非空 = 0        # 老数据 NULL，符合预期
新增 5 列均存在
```

迁移**没有修改或删除任何既有记录**；1013 条老记录保持原值。

---

## 四、真实覆盖率结果

### 4.1 生产库接口现状

```text
evaluate_interval_coverage(store=analysis_store)
total_rows = 1013, usable_rows = 0, coverage = None
reason = 无可用区间样本（lower/upper 为空；迁移前老数据需新预测落库后才有真实覆盖率）
calibration = False（样本数 0 < 训练 30 + 测试 30）
```

结论：迁移后接口按约定返回 `None + 原因`，**没有**用 79.7% 之类的近似值冒充真实值。
新预测落库并结算 ≥30 条后，同一接口自动给出真实覆盖率。

### 4.2 真实行情 walk-forward 审计（rb / i / IF）

方法：`replay_symbol` 严格只用 t 时刻以前的数据训练，预测 h=10，按 `ts` 时序结算；
写入 **tempfile 临时库**，再调用 `evaluate_interval_coverage`。参数固定种子 `20261104`，
`stride=40`、`max_samples=100`、`retrain_stride=768`，输出明细见
`scripts/research/phase6_coverage_audit.json`。

| 品种 | n | 真实覆盖率 | 名义(±1σ) | 95% CI | 判定 | 与 79.7% 差 |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| rb.SHFE | 100 | **69.00%** | 68.27% | [59.37%, 77.22%] | 与名义一致 | **-10.70pp** |
| i.DCE | 76 | **56.58%** | 68.27% | [45.39%, 67.14%] | **覆盖不足** | **-23.12pp** |
| IF.CFFEX | 56 | **73.21%** | 68.27% | [60.41%, 83.04%] | 与名义一致 | **-6.49pp** |
| 合并 | 232 | **65.95%** | 68.27% | [59.63%, 71.74%] | 与名义一致 | **-13.75pp** |

- `cu.SHFE`：`data/real_samples/` 无本地 CSV，未纳入审计（不联网补抓）。
- **是否过度覆盖：否。** rb/IF/合并样本的 CI 都包含 68.27%；i 是覆盖不足（CI 上界 67.14% < 68.27%）。
  旧界面的 79.7% 高于名义水平，看起来像「过度覆盖」，但那是合成注入值，不具参考性。

### 4.3 真实 vs 近似对照

| 品种 | 真实覆盖 | 逐样本近似(±σ√h，无漂移) | UI 式全局近似(近 120 根) |
| --- | ---: | ---: | ---: |
| rb.SHFE | 69.00% | 70.00% | 100.00% |
| i.DCE | 56.58% | 55.27% | 96.36% |
| IF.CFFEX | 73.21% | 76.79% | 65.45% |

- 逐样本近似与真实值接近（差 1-3.6pp），说明真实区间的主要信息来自 σ 宽度；
- UI 式全局近似偏差最大（rb +31pp、i +39.8pp、IF -7.8pp）：它用单一中位 σ 扫最近窗口，
  既不含预测漂移，也不含当时逐样本 σ，**不能替代真实覆盖率**。

### 4.4 名义水平对比与校准建议

- rb：`k_old≈1.000`，训练段拟合 `k'=1.065`；测试段覆盖率在 k=1 与 k'=1.065 均为 80.0%，
  CI 包含 68.27% → 校准通过，但**没有实质增益**（样本仅 100，测试 30）。
- i：`k_old≈0.99999`，训练段 `k'=1.245`；测试段从 60.0% 提升到 63.3%，
  CI [45.51%, 78.13%] 包含 68.27% → 技术上通过，但提升不显著，属于「候选乘数」。
- IF：56 条 < 训练 30 + 测试 30，**拒绝给出 k'**（返回 `available=False + 原因`）。
- 纪律：`k'` 只由训练段 `z` 的分位数确定；测试段只验证，不参与定参。
  当前不建议自动套用 `k'`：单品种样本 56-100，乘数估计不稳定，容易过拟合。

波动分层（仅 rb 三组均 ≥30）：low 61.76%、mid 63.64%、high 81.82%——
高波动组在本样本内偏过度覆盖，`i/IF` 每组 <30，按要求返回 `None`。

---

## 五、pre-commit 三处告警核查与修复

### 5.1 核查结论：不是真静默失效

| 位置 | 代码事实 | 扫描结果 | 性质 |
| --- | --- | --- | --- |
| `backtest_page.py:2511` | `if self._bt_store is None:` → `logger.error("跳过上次手动配置预填…")` → `return` | `silent=False` | **已留痕**：跳过的是「上次手动配置预填」，不影响回测主流程；有可见 error 日志 |
| `splash.py:108` | `if self._splash is None: return`，上方有 `# scan-silent-bail: 允许 —— Splash 是纯装饰性子系统，headless 环境建不出来是预期行为` | `silent=False`（允许） | **显式豁免**：不落盘任何数据，非数据链路 |
| `splash.py:122` | `finish()` 同样的判空，上方有 `# scan-silent-bail: 允许 —— 同 step()：装饰性子系统` | `silent=False`（允许） | **显式豁免** |

所以三处都不满足 `high + silent` 的阻断条件，hook 的 `rc=0`。

### 5.2 真正的缺陷：工具文案把非阻断项说成「能力静默失效」

- 修复前：所有 `CHAIN` 无论 `silent` 与否，都打印 `⚠️/🚨` 且文案统一为
  「此处又静默 return（能力静默失效）」，导致 3 条合法项看起来像故障。
- 修复后（`tools/scan_silent_bail.py` L305-L312、L400-L405）：
  - `silent=True` → 🚨 +「能力静默失效」；
  - 已留痕 → ✅ +「判空分支前已有可见日志（已留痕，非静默失效，不阻断）」；
  - 已豁免 → ✅ +「判空分支已显式豁免：<原因>（非静默失效，不阻断）」；
  - 摘要改为 `CHAIN 3 / 其中未留痕 0；已留痕或已豁免 3 条不阻断`。
- 门禁语义不变：仍只在 `high + silent` 时 `return 1`。不改变任何扫描判定逻辑，仅改呈现与文案。

### 5.3 本地 hook 实跑

```text
$ python tools/scan_silent_bail.py --dir futures_quant/ui/backtest_page.py futures_quant/ui/splash.py --min-severity high
扫描：... 命中 3 条（CHAIN 3 / 其中未留痕 0；已留痕或已豁免 3 条不阻断）
RC=0

$ git add <本轮 8 个文件> && bash tools/hooks/pre-commit
（secret scan + silent-bail scan 全部通过）
HOOK_RC=0
```

- 未使用 `--no-verify`，未 commit；验证后已 `git reset` 取消暂存。
- 说明：`tools/` 被 `.gitignore` 忽略，扫描器文案修复仅存在于本地工作区，
  由统一提交流程决定是否纳入；hook 本身仍会读取本地文件。

---

## 六、测试结果

```text
python -m pytest tests/unit/test_phase6_interval_coverage.py -q
........... [100%]    # 11 passed

python -m pytest tests/unit/test_phase2_evaluation.py \
  tests/unit/test_scan_silent_bail.py \
  tests/unit/test_ui_store_linkage_crash_regression.py \
  tests/unit/test_phase6_interval_coverage.py -q
..................................................... [100%]   # 53 passed
```

新增用例覆盖：

1. 全命中 → 过度覆盖；全落外 → 覆盖不足；
2. 样本 <30 → `coverage=None + reason`，同时保留 `observed_rate` 供排查；
3. 老数据 `lower/upper=NULL` 必须剔除，40 新 + 20 老 → `usable_rows=40`；
4. 无可用样本 → `None + reason`，校准返回不可用；
5. 按品种 / horizon / 波动三分位分组，小组 <30 → `None + reason`；
6. z 标准化回归：价格量级 3000 时 `k'<2`（防止把 `ln(price)` 当漂移）；
7. 校准只用训练段：训练 z≈0.5-1.0、测试 z≈3-6，`k'<1.5`，测试段未参与定参；
8. 迁移：旧表 → 新增列存在、老记录保留且为 NULL、新记录可写入、二次打开幂等；
9. 纯老库查询 → `total_rows=1 / usable_rows=0 / coverage=None + reason`。

审计过程序中发现并修复了一个真实缺陷：早期 `z` 用绝对价格 `log(lower/upper)` 计算中心，
导致价格量级直接进入标准化残差（rb 上 `k'` 被抬到数百）。已改为相对起点价的 log 收益，
并新增 `test_interval_z_is_relative_to_start_price` 防回归。

---

## 七、残留风险

1. **生产库暂时没有区间数据**：1013 条老记录 `lower/upper=NULL`，在新区间预测结算到 30 条前，
   接口只会返回 `None + 原因`。UI 会话需要把展示改为调用 `evaluate_interval_coverage`，
   并正确处理 `None`（显示「真实覆盖率暂不可用」），不得回退到近似值。
2. **审计口径与生产不完全一致**：审计用 `extended_features=False / use_ensemble=False`
   （当前环境无可用 LSTM，强制 Ridge），且 `retrain_stride=768` 为提速做了稀疏重训；
   结论对「区间宽度/漂移」有效，但不等价于线上完整模型。
3. **样本量小**：单品种 56-100 条，波动分层多数组 <30；`k'` 估计不稳定，禁止自动上线，
   建议累积到每品种 ≥200 条再定参。
4. **79.7% 不可比**：来自 offscreen 合成注入，和真实行情回放不是同一口径；
   本文的对照仅用于说明「近似值偏高」，不能据此判断历史模型质量。
5. **回放 `closed_ts` 是写库时间**：校准切分已改用 `ts`（预测时间），但若未来 UI 展示
   `closed_ts`，其语义仍是「写库时间」而非「结算 K 线时间」，需要单独评估。
6. **`cu.SHFE` 未覆盖**：本地无 CSV；未联网补抓，扩品种验证需另行安排。
7. **工具目录被 gitignore**：`tools/scan_silent_bail.py` 的文案修复不会随本轮提交进入仓库；
   若统一提交需要该修复，请单独确认 `tools/` 的纳管策略。
8. **数据库备份文件在 `data/backups/`**：属于运维产物，是否入库/清理由用户决定；
   回滚时优先整库恢复，避免只 DROP 列造成列顺序差异。
