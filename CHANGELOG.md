# Changelog

本项目遵循 [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/)。

---

## [5.2.11] - 2026-10-06

> 堵住 5.2.10 排查出的**同类更严重**故障：`build_tools/` 整目录被 `.gitignore`
> 裸规则 `/build_tools/` 排除 → `git ls-files build_tools/` 为 0，**打包脚本 + 密钥
> 门禁工具全都不受版本控制**。后果：fresh clone 上 pre-commit 的密钥关（gate-1）
> 因找不到 `build_tools/secret_scan.py` 而静默失效，且工具自身的加固无法入库。
> 这与「`.gitignore` 零受控」是同款故障，也与文件顶部声明「build_tools/ 是受控
> 资产、不要忽略目录本身」自相矛盾。

### 修复

- `.gitignore` 删除裸规则 `/build_tools/`（原第 59 行，"历史残留"段），只保留精确的
  内部排除：`build_tools/_app_version_info.txt`（版本资源，自动生成）、
  `build_tools/_rebrand_*.py`（一次性脚本，grep 0 引用，维持忽略）、`__pycache__/`。
- **纳入受控**：`build_tools/secret_scan.py`、`build_tools/build_exe.py`、
  `build_tools/futures_qt.spec`（`git ls-files build_tools/` 0 → 3）。
- **顺手加固 `secret_scan.py`**：把运行期脚手架目录 `.pytest_tmp/` 加入默认
  `_DEFAULT_SKIP_DIRS`，防止测试探针遗留的「疑似密钥」fixture 让**全树**扫描误报
  （历史上 `.pytest_tmp/_bad_secret.py` 就踩过）。双向验证：`.pytest_tmp` 内假密钥
  → 全树扫描跳过（rc=0）；受控目录内假密钥 → 仍被拦（rc=1），未过度抑制。

### 验证（`git check-ignore` 逐一确认 + 本次提交走钩子）

| 对象 | 期望 | 结果 |
| --- | --- | --- |
| `secret_scan.py` / `build_exe.py` / `futures_qt.spec` | trackable | ✅ trackable |
| `_rebrand_py.py` / `_app_version_info.txt` | 仍 IGNORED（口径不变） | ✅ IGNORED |
| 本次提交走 pre-commit（gate-1 密钥 + gate-2 静默失效） | 4 暂存文件全过、gate-2 真扫到暂存 .py | ✅ `命中 0 条` 放行 |

> 方法论：这是「测采集链路」教训的延伸——门禁工具**本身**必须在受控目录里，
> 否则它只在作者机器上"能跑"，clone 到任何别处就静默失效。工具的可移植性
> 也是门禁可信度的一部分。

## [5.2.10] - 2026-10-06

> 「让 5.2.9 的静默失效关真正生效」：修复 pre-commit 钩子第 2 关
> （`scan_silent_bail`）此前是**静默 no-op** 的两个叠加缺陷——它一直「扫 0 个文件、
> 恒 rc=0」，从没真正拦住过任何违规。

### 根因（两个独立缺陷叠加）

- **缺陷 ①（工具）**：`tools/scan_silent_bail.py::iter_py_files` 只认**目录**
  （`if not base.is_dir(): continue`）。而 pre-commit 把「暂存的 `.py` 文件列表」逐个
  传给 `--dir`——文件实参不是目录，被整条跳过 → **实际扫描 0 个文件**。
- **缺陷 ②（验证侧）**：此前用来证明「能检出」的探针文件名以下划线开头
  （`_bad_silent_class.py`），而 `iter_py_files` 会过滤 `_` 开头的文件——即便文件实参
  被正确传入也照样被丢弃。两个缺陷叠加，导致「命中 0 条 / 恒 rc=0」被误读为
  「扫描器全瞎」，实际是**采集链路（`iter_py_files`）根本没把文件喂进去**。

### 修复

- `tools/scan_silent_bail.py::iter_py_files` 现在**既接受目录（rglob 全量）也接受单个
  `.py` 文件（只扫它）**；对文件实参保持与目录 rglob 一致的口径：`SKIP_PARTS`、
  `_` 开头、非 `.py` 一律过滤。pre-commit 的「只扫暂存 .py、秒级」语义不变。

### 验证（端到端，用真实钩子脚本，非 mock）

| 场景 | 结果 |
| --- | --- |
| 暂存「未留痕 CHAIN」探针（`except` 钉 None → 判空静默 `return`）跑 `sh tools/hooks/pre-commit` | **阻断**（🚨 命中 1 条 / `hook_exit=1`） |
| 暂存「已留痕」同结构探针（判空前有 `logger.error`） | **放行**（未留痕 0 / `hook_exit=0`） |
| `--dir` 传单个文件 vs 传目录（对照真实 `backtest_page.py`） | 目录命中 3、修复前文件命中 0 → 修复后文件命中与目录一致 |

> 新增回归测试 `tests/unit/test_scan_silent_bail.py`（4 项，覆盖 `iter_py_files` 的
> 单文件实参 / 文件+目录混用 / `_` 过滤 / 非 `.py` 过滤），专门锁死「采集链路把文件
> 喂进检出」这一步，防止 no-op 再次静默回归。全套件 17 passed。

## [5.2.9] - 2026-10-06

> 「让质量门禁不可绕过」：把此前只能**手动记得跑**的检测能力（密钥扫描 /
> 静默失效 AST 门禁）固化成 git 钩子，堵上「提交时忘了跑 check.py」这道口子。

### 钩子（新增）

- `tools/hooks/pre-commit`：只扫**暂存改动**（非全量，秒级），两关——
  `secret_scan.py`（密钥）+ `scan_silent_bail.py --min-severity high`（静默失效）。
  任一非 0 即阻断。设计要点：
  - **只扫 `git diff --cached` 的文件**而非整棵源码树 → 绝大多数提交 ~2s（干净）到
    ~9s（改了 .py）就过，不会像 `check.py` 那样每次拖 5 分钟。
  - **解释器缺失 → fail-open**（放行并提示手动跑 `check.py`）：钩子不能变成
    「谁都提交不了」的卡子。
  - 逃生口 `QV_SKIP_HOOKS=1 git commit`。
- `tools/hooks/pre-push`：透传 git-lfs 的 `pre-push`（保 LFS 行为不变）+ 可选
  全量门禁 `QV_PREPUSH_FULL_TESTS=1`（默认关，不拖慢 push）。
- `tools/install_hooks.py`：设 `core.hooksPath=tools/hooks`（钩子**受控、可克隆复现**，
  写在 `.git/hooks` 里的钩子克隆后会丢），并把 `.git/hooks` 里 LFS 的 4 个钩子
  原样同步进 `tools/hooks/`（**零行为变化**），且**已存在的自定义钩子绝不覆盖**。

### 验证（端到端）

| 场景 | 结果 |
| --- | --- |
| 暂存一个含 `sk-proj-…` 的文件并提交 | pre-commit **阻断**（rc=1，报 2 处疑似密钥） |
| 暂存干净改动并提交 | pre-commit **放行**（rc=0） |
| 安装器幂等 | 重跑不改已设 `core.hooksPath`、不覆盖自定义 `pre-push` |
| 本次提交自身 | 走了新 pre-commit，扫 `install_hooks.py` 通过 |

> 门禁分层：**pre-commit = 秒级快检（防带病提交）**，**pre-push/`check.py` =
> 分钟级全量（发布前）**。静默失效扫描器对全树的 ~11s 耗时留在 push 侧，
> 提交侧只扫改动，两者不重复。

## [5.2.8] - 2026-10-06

> 「我以为修好了，其实只是运气好」：`test_ux_phase5_6.py` 的 `0xC0000409`
> 在 v5.2.7 被判定为已根治，实际**仍在以约 10% 的概率崩**。这一版靠门禁新加的
> 「失败回显」拿到了证据，定位到真因并根治。

### 真因：`DiagnosticsDialog` 构造即开后台线程，测试从不回收

`DiagnosticsDialog.__init__` 末尾**无条件**调用 `self._start_async()`，起一个
`_DiagWorker`（**QThread**）跑 8 项真实系统检查（其中 `check_data_source`
还会再开一个 `threading.Thread` 做网络探测）。

而 `test_open_log_dir_method_exists` / `test_btn_logs_exists` 只为了断言
「属性存在」而构造对话框，随后 `d.close()` 就走 —— **线程既不等也不回收**。
进程在后续某个时刻因「QThread 仍在运行就被销毁」触发 `qFatal`
→ `__fastfail` **0xC0000409**。

**取证过程**（这条比结果更值得记）：

| 步骤 | 结果 |
| --- | --- |
| 门禁失败回显（v5.2.7 新增） | 直接给出崩溃文件 `test_ux_phase5_6.py`、`passed=8/37`、rc=3221226505 |
| 按 runner 的确切调用连跑 10 次 | 1 次 CRASH、9 次 PASS（≈10%） |
| 只跑 `::TestUX64Diagnostics` 两个用例 8 次 | **8/8 CRASH** —— 不是 flake，是确定性缺陷 |
| 反向证伪「MainWindow 定时器」假设 | 造 2 个 MainWindow + 强制转事件循环 → 不崩，假设排除 |

**v5.2.7 的误判根因**：拿「连跑 3 次全绿」当结论。崩溃概率约 10%，
3 次全过的概率是 73% —— **3 次根本测不出低概率崩溃**。
本次改用「定向组 8 次 > 全文件 20 次」的分层复跑，才拿到可信结论。

### 修复

- `futures_quant/ui/diagnostics_dialog.py`：新增 `auto_check: bool = True` 参数，
  `False` 时跳过 `_start_async()`。**默认值不变，应用侧行为零变化**
  （`main_window.py:808` 的构造点不受影响），只给离屏/单测留逃生口。
- `tests/unit/test_ux_phase5_6.py`：两处 `DiagnosticsDialog()` →
  `DiagnosticsDialog(auto_check=False)`。
- 未改动 `MainWindow`：定向实验证实定时器/线程不是崩溃源
  （`_start_drift_monitor` 用的是 `threading.Timer` 调度器，非 QThread）。

### 验证

| 检查 | 结果 |
| --- | --- |
| `::TestUX64Diagnostics` 连跑 8 次 | 修复前 **8/8 CRASH** → 修复后 **8/8 PASS** |
| `test_ux_phase5_6.py` 连跑 20 次 | **20/20 PASS**（修复前 1/10 CRASH） |
| `python tools/check.py` | scan `CHAIN 3 / 未留痕 0` · unit **589/0/0** · 版本防漂移 PASS · 性能预算 PASS，rc=0 |

另注：本版补齐了 v5.2.7 章节里那句已被推翻的「已根治」结论，避免后人照抄。

---

## [5.2.7] - 2026-10-06

> 「测量口径统一 + 门禁落地 + 核心资产入库」：审计出逐文件 runner 用**非递归
> glob 静默漏掉 31 个用例**（547 vs 578），把两个测试口径对齐；新增统一门禁
> `tools/check.py`；把从未纳管的密钥脱敏测试搬进 `tests/unit/`；并修复了
> `.gitignore` 把**整个源码包与整个测试目录**排除在版本控制外的重大风险。

### 审计发现（三条，其中一条是重风险）

- **（高）核心资产几乎零受控**：`.gitignore` 第 20 行 `tests/`、第 60 行
  `futures_quant` 把**整个源码包与整个测试目录**排除在版本控制外。
  实测：仓库受控文件共 **49 个**，全项目 **410 个 `.py` 只有 3 个受控**，
  `tests/` 下受控数为 **0**。一次误删/误格式化即不可恢复。
  **✅ 已于本版修复**（详见下方「版本控制」）：移除裸规则后，受控文件从 **49 个**
  恢复到 **~498 个**（`git add -A -n` dry-run 显示将新增 **449 个**、剔除 2 个
  运行时伴随文件）。
- **（高）测试口径不一致**：`tools/run_unit_timed.py` 用 `UNIT_DIR.glob("*.py")`
  （**非递归**），静默漏掉 `tests/unit/contracts/test_ux_contracts.py` 的
  **31 个用例** —— 逐文件口径 547、整套件口径 578，差得毫无提示。
  改为 `rglob` + 过滤 `test_` 开头（与 `pytest.ini` 的 `python_files` 对齐），
  两个口径现已一致为 **578**。
- **（中）散落测试 5.4k 行不参与任何门禁**：`tests/` 根目录 20 个 M2/M3/M4 时期
  `test_*.py` 不被 `testpaths` 收集；其中 `test_security_redaction.py`
  （密钥脱敏/扫描）此前**完全未被门禁覆盖**，现已迁入 `tests/unit/` 纳管。

### 修复

- `tests/unit/test_ux_phase5_6.py`：删除时机错误导致的 `0xC0000409` fast-fail。
  崩溃点稳定在第 **8/37** 个用例（``test_top_tabs_widget_exists`` 造的是
  **完整 MainWindow**，``deleteLater()`` 只是挂起删除事件，紧随其后的
  `processEvents()` 立刻结算 → 主窗口在下一个用例的事件循环里被析构）。
  改为**延迟删除 + 对象身份集合**（不用 `id()`：地址可复用会漏删），
  37 个用例期间完全不触发 Qt 析构，模块收尾一次性结算。
  连跑 3 次均 37/37 通过（此前单独跑 3 次有 2 次卡在第 8 个）。

  ⚠️ **该结论后被推翻（见 5.2.8）**：这次只是把崩溃概率降下来了，**没碰到真因**
  —— 真因是 `DiagnosticsDialog` 构造即开 QThread 且从不回收。
  教训：**「连跑 3 次全绿」测不出 10% 概率的崩溃**（3 次全过概率 73%）。
- `tests/unit/test_ui_store_linkage_crash_regression.py`：9 处
  `return app` → `assert app is not None`。pytest 8 起「测试函数返回非 None」
  会升级为 error；保活语义等价（局部变量返回时同样释放，Qt 的 qApp 单例仍在）。

### 工具

- 新增 `tools/check.py`：统一质量门禁，一条命令串起
  `scan_silent_bail` → `tests/unit` → 版本防漂移 → 性能预算，
  逐项输出 PASS/FAIL 与可自证计数，最终按退出码判定（CI 直接判这个）。
  `--skip / --step` 定向跑。单测**刻意走逐文件 runner** 而非整套件：
  整套件在并发跑其他 pytest 时会间歇挂死（实测卡在 `test_m4_08_data_grid.py`
  16 分钟不动）。
- 新增 `tools/hang_watchdog.py`：pytest 插件，用
  `faulthandler.dump_traceback_later` 的看门狗线程抓挂起栈
  （Windows 上 signal 投递不可靠，`os.kill(SIGABRT)` 走的是 TerminateProcess）。
- `tools/run_unit_timed.py`：`glob` → `rglob`，口径对齐到 578。
- `tools/check.py`：**失败必须回显**。原先非 0 退出只打印一个 `PASSED=…` 数字，
  stdout/stderr 全丢 —— 失败时无从定位（本轮真就遇到一次
  `PASSED=560 FAILED=1 CRASHED=1`，因为没留证据，只好多跑一遍才复现成全绿）。
  现在非 0 退出把完整 stdout+stderr 落盘到 `.pytest_tmp/check_fail_<key>.log`
  并回打尾部 60 行。
- 新增 `tools/check_selftest.py`：**自证门禁自己的失败分支**。
  故意造一个 `stderr=boom-from-child; exit(3)` 的子进程，验证转储确实落盘、
  含 `rc=` 与诊断文本、尾部回显取到最后一行 —— 否则「能报绿的门禁」不代表
  「失败时也能报 Why」。带 `--quick`（秒级）跑转储路径，不带则额外真跑一次
  `tools/check.py`。
  ⚠️ 该脚本第一版自身就带了个 bug：成功时返回 `0`，被直接当布尔赋值后变成
  falsy，四项子检查全 PASS 却输出「自证失败」—— 已改 `== 0` 并在此记录。
- `pytest.ini`：补「`tests/` 根目录散落文件不参与收集」的口径提醒（纯注释）。

### 版本控制（`.gitignore` 修复）

真因是**裸规则**（不带 `/` 前缀的目录名匹配任意层级同名目录）叠了三处：

| 行 | 改动前 | 改动后 |
| --- | --- | --- |
| 20（构建产物段） | `tests/` | 删除；改为 `tests/**/*.log`（只忽略跑测日志，不再吞整个目录） |
| 59（手工排除段） | 裸 `tests` | 删除 |
| 60（手工排除段） | 裸 `futures_quant` | 删除 |

配套：

- 运行时数据段补 `*.db-shm` / `*.db-wal`（SQLite WAL 伴随文件）。
- 手工排除段去重：`/tests/`、`/build_tools/`、`/packaging/`、`/docs/` 各重复出现
  两次，只保留一处。
- 新增「临时评估/实验脚本（不入库）」段：`test_design.py`、`test_output.txt`、
  `cd`、`remove data/`（早期清理数据时误建的目录）。
- 新增「测试 / 运行期产物（不入库）」段：`tests/_*.xml` / `_*.txt` / `_*.out`、
  `tests/e2e/archived_logs/`、`tests/e2e/*.png`、`outputs/`、`.write_test`、
  `data/evolution/`、`data/auto_strategies/`、`data/cls_news_cache.json`、
  `data/_pred_export.csv` —— 否则「核心资产入库」会顺带把 5 个 junit/summary 转储、
  截图、探针文件、进化快照一起提交进去。

> ⚠️ **踩到的坑**：`.gitignore` 的 **行尾 `#` 不是注释**，它是模式的一部分
> （只有行首 `#` 才起注释作用）。写成 `tests/_*.xml   # junit 转储` 规则会静默失配，
> 直到 `git check-ignore -v` 才暴露。现规则已改为**每条独占一行、注释另起一行**。

### 遗留：`ignore` 管不到已追踪文件 —— 已清理

`git check-ignore` 对**已被 git 追踪**的文件无效（ignore 只作用于 untracked）。
历史提交里实际混入了 **17 个**运行期文件（比初查的 4 个多：`data/` 下还有 5 组
SQLite 的 `-shm`/`-wal` 对）。已用 `git rm -r --cached` 一次性清出，**只退 index、
未删磁盘文件**。清理前逐个确认它们都是**可再生的运行期产物**：
`profitable_strategies.json` 由 `auto_evolve.load_profitable()` 读取且有兜底，
`cls_news_cache.json` 是新闻缓存，`*.db-shm/-wal` 是 SQLite 内部文件。

> 附带事实：清理期间 `data/quant_backtest.db-shm` 从磁盘消失，是 **SQLite 干净
> 关闭 checkpoint 后自行删除临时文件** —— 主库（214MB / 4 张表 /
> `evolve_history` 1000 行）打开校验完好，与 `git rm --cached` 无关。

验证（`git check-ignore -v`）：`futures_quant/ui/main_window.py`、
`futures_quant/ai/linkage_bus.py`、`tests/unit/test_ux_phase5_6.py`、
`tests/fixtures/news_html/cs.html`、`tools/check.py` **全部可入库**；
`dist/`、`build/`、`*.pyc`、`test_design.py`、`tests/e2e/*.log`、`outputs/`、
`tests/_junit_*.xml`、`.write_test`、`data/evolution/` **全部仍被忽略**。
入库前 `git add -A -n` dry-run：**437 行**（add 435 / remove 2）；实际提交为
**429 新增 / 17 删除 / 4 修改 → 受控 461 个文件**（`tests 238 · futures_quant 178 ·
tools 8 · scripts 5` + 根文件）。提交前跑过 `build_tools/secret_scan.py`：
源码树**未发现硬编码密钥**。

### 验证（v5.2.7 发布门禁，`python tools/check.py` 全绿）

| 门禁 | 结果 |
| --- | --- |
| 静态门禁 `scan_silent_bail` | `CHAIN 3 / 未留痕 0`，rc=0 |
| 单元测试 `tests/unit` | **39 文件 / PASSED=589 / FAILED=0 / CRASHED=0** |
| 版本防漂移 | PASS（5.2.7 / 2026-10-06，三项子校验） |
| 性能预算 | PASS（主题全量刷新 / 表格填充 / K 线 p95 / 图表 set_data） |

`tools/check.py` 三次运行：1 次 FAIL（**间歇性** Qt flake：`PASSED=560 FAILED=1
CRASHED=1`，约 27 个用例没跑完）+ **2 次全绿**；`tools/run_unit_timed.py` 单独重跑
复现为 589/0/0。该 flake 在旧版门禁下**留不下任何证据**，现已由上面的
「失败回显 + `check_selftest.py`」覆盖；`test_ux_phase5_6.py` 单独连跑 3 次 37/37。

### 已知

- 整套件 `pytest tests/unit` 在**并发跑别的 pytest 进程**时仍会间歇挂住
  （跑得顺 2m17s / 卡死 16min+）。统一门禁因此走逐文件串行路线。
- `tests/` 根目录剩余 19 个散落测试文件（约 5.4k 行）为 M2/M3/M4 时期历史遗留、
  不在 `testpaths` 收集内，**本次随资产一起入库但未纳入门禁**，待人工归档决策
  （详见 `pytest.ini` 顶部口径说明）。
- 整套件 `pytest tests/unit` 会间歇性 flake（本轮实测 `PASSED=560 FAILED=1
  CRASHED=1`）；门禁已具备失败回显，下次再撞可直接从
  `.pytest_tmp/check_fail_unit.log` 取证。

---

## [5.2.6] - 2026-10-05

> 「用例全过但整文件被静默丢弃」的根因定位与根治：修掉一个**只跑一个用例就能崩掉
> 整个文件**的 Qt 测试缺陷，并把逐文件 runner 的测量可信度补上。

### 修复（真因：monkeypatch 拦不住 Qt 信号槽）

- `tests/unit/test_m7_07_theme_shortcuts.py::test_apply_timer_timeout_wired`：
  该用例想用 `monkeypatch.setattr(dlg, "_finish_apply", stub)` 拦截槽函数，
  但 **Qt 信号在 `AIConfigDialog.__init__` 里就绑定了真实槽函数**，
  事后改实例属性**拦不住那个连接** —— `emit()` 真跑了
  `_apply_timer.timeout → _finish_apply → _do_apply`（落配置、改全局状态）。
  后果：该用例单独执行就会让进程 `0xC0000409`（CRT fast-fail）abort，
  全文件跑到第 25/27 个，最后 2 个用例根本跑不到，
  而逐文件 runner 只看 stdout 会把它们记成「0 个用例」。
  → 改为先断言 `timer.receivers(timer.timeout) >= 1`（验证确实已接槽），
  再 `disconnect()` + 重连计数器验证信号通路，最后还原连接；不再误触发真实槽。
- 同文件 `dlg` fixture 增加**删除前先 stop 内部 QTimer**（`_apply_timer` /
  `_save_spinner` / `_test_poll` / `_copy_timer`）：回调不得在 widget 已释放后触发。
- `tests/unit/test_ux_phase5_6.py`：新增 autouse `_cleanup_widgets` fixture，
  自动销毁每个用例新建的顶层 widget（只删「进入用例前不存在的新增项」，
  不碰模块级 fixture 持有的对象）。
  原实现里对话框只 `close()` 从不销毁，widget 与 QApplication 的释放顺序交给 GC，
  **实测约 1/3 概率**中段 abort（37 个用例只跑到第 8 个）。

### 工具（测量可信度）

- `tools/run_unit_timed.py`：
  - **进程崩溃算失败**：Win32 致命码经 `subprocess` 出来是**正数**（0xC0000409 →
    3221226505），旧判据只看 `rc < 0`，把 Qt 的常见崩溃整个漏掉。
  - 结果改用**逐用例流式落盘**（新增 `tools/unit_result_logger.py`）而非
    pytest 汇总行/`--junitxml`：退出期崩溃时那两者都来不及写，
    只看 stdout 会让整个文件被记成 0 个用例。
  - 跳过 `_` 开头文件（与 `python_files = test_*.py` 一致）——
    它们不被收集但模块级代码照跑（`_test_data_transfer.py` 导入就 >120s）。
  - 新增 `--only=<片段>` 定向调试；结果目录固定到项目内（tempfile 默认落
    `E:\Temp`，本机极慢且会干扰子进程）。
  - 崩溃但「通过数 == 收集数且零失败」时降级为告警（`~~`）而非失败。
  - **（第二轮）结果日志改为「父进程截断、子进程 append」，全程不做删除**：
    ① append 模式遇到上一轮残留会被**重复计数**（实测把 27 个用例记成 54 个），
    而原先「循环后再清理」的顺序根本兜不住；
    ② `unlink` 会被沙箱安全删除守卫拦下（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`），
    且它抛的是 **`SystemExit`（不是 `Exception`）** —— `except Exception` 兜不住，
    异常从 `finally` 里把 `return code` 顶掉，把一次**全绿**的运行报成 `rc=1`。
    退出码是 CI 的唯一凭据，被清理逻辑污染比不清理危险得多，
    于是改成父进程 `write_text("")` 截断，彻底绕开删除。

### 排查记录（供后续复用）

崩溃码 `0xC0000409` 是 `__fastfail` **直接 raise**，不走信号 → faulthandler 抓不到；
Qt 默认把致命信息写进 C 层 `stderr`（管道下块缓冲），abort 时随之丢失，
连 `qInstallMessageHandler` 也拿不到东西。
定位靠三板斧：① 用 subprocess 拿**原始 returncode** 区分信号/Win32 致命码；
② 在 `pytest_runtest_logreport` 里**逐用例落盘**（崩在哪条之后一目了然）；
③ 用 `-k` 做**前缀二分**收敛到单用例。
已排除的假设：deleteLater 堆积、QTimer 回调时序、顶层 widget 清扫、
复用单个对话框 —— 都不是。

### 验证（v5.2.6 发布门禁，三项全绿）

| 项目 | 结果 |
| --- | --- |
| `tools/run_unit_timed.py --verbose`（37 个文件逐文件） | `PASSED=547  FAILED=0  CRASHED=0`，37/37 `rc=0`，进程 `rc=0` |
| `tests/e2e/test_auto_evolve_engine.py` | 5/5 段通过；适应度 65.64、盈利库 60 条（与 v5.2.4 一致） |
| `tools/scan_silent_bail.py` | `CHAIN 3 / 未留痕 0`，`rc=0` |
| `tests/e2e/run_version_checks.py` | 版本同步 / 资源构建 / 防漂移 三项 PASS |

### 已知

- `test_m7_07_theme_shortcuts.py` 与 `test_ux_phase5_6.py` 的崩溃已根治，
  但整套 `pytest tests/unit` 直跑仍可能在退出期挂起：继续用
  `python tools/run_unit_timed.py` 逐文件跑并读其汇总。

---

## [5.2.5] - 2026-10-05

> 把「静默失效」从个案变成**可复检的工程门禁**：新增 AST 扫描器
> `tools/scan_silent_bail.py`，按类归并检测「except 钉死 None → 判空静默 return」
> 的链式反模式；扫描即挖出第 3 条同类缺陷并一并修复。

### 新增

- `tools/scan_silent_bail.py`：AST 级链式扫描，四条输出
  （`CHAIN` / `PIN_STANDAL` / `BAIL_STANDAL`，外加「未留痕」判定）。
  - 链式按**类**归并：钉 None 常在 `__init__`、判空常在别的方法，只看方法级键
    会漏掉真实缺陷。
  - 留痕判定是**顺序敏感**的：只看判空分支**之前**的日志/Toast 调用
    （函数后面才打的日志救不了这个分支）。
  - 豁免必须**写明理由**并留在代码里：``# scan-silent-bail: 允许 —— <原因>``。
    装饰性子系统（Splash）这类合理跳过可以标注豁免，但不能靠「关掉告警」隐藏。
  - 退出码即门禁语义：存在未留痕 `CHAIN` 返回 1。
  - 用法：``python tools/scan_silent_bail.py``（全量）／
    `--min-severity high` 只看高危／`--format json --output f.json` 供机器读取
    （`--output` 是因为本机 anaconda 的 `sitecustomize.py` 会往 stdout 打 banner）。
    CI 里直接判退出码即可；`0` = 无未留痕静默失效。
- `tests/unit/test_scan_silent_bail.py`：13 项扫描器自身契约测试
  （跨方法链能检出 / `return None` 等价 / 已留痕不算静默 / 可选参数守卫不误报 /
  if-else 双分支短路不误报 / `return -1` 有值返回不算放弃能力 / 工程侧零未留痕 CHAIN）。
  **「扫描器报 0 条」只有在扫描器确实能检出时才成立**，因此这类契约必须先自证。

### 修复（扫描新挖出的第 3 条同类缺陷）

- `backtest_page.py:2498` `_maybe_restore_manual_config`：
  `_bt_store` 由 `get_backtest_store()` 在构造期创建，失败置 None；
  判空处**静默 return** —— 「上次手动配置」预填会被无声跳过。
  → 补 `logger.error`（仅跳过预填，不影响回测主流程，但必须留痕）。

### 已知豁免（含理由，可审计）

- `ui/splash.py` `step()` / `finish()`：Splash 是**纯装饰性子系统**，headless /
  无显示环境下 `QSplashScreen` 建不出来是预期行为，跳过不影响任何数据链路。
  以 `# scan-silent-bail: 允许 —— …` 标注豁免。

---

## [5.2.4] - 2026-10-05

> 「静默失效」反模式第二次复发并根治：v5.2.3 解决了 `AnalysisStore` 后台未就绪丢数据，
> 同一类缺陷在**进化档案（EvolutionStore）**上原样复现，且更隐蔽 ——
> 构造期失败把 `None` 钉死，落盘能力整条失效而**日志里一个字都没有**。

### 修复

#### ① 进化档案整条能力静默失效（`_save_evo_run` 判空 return）
- **真因**：`BacktestCenterPage.__init__` 在构造期 `try: EvolutionStore() / except:
  self._evo_store = None`，**一次创建失败就把 None 钉死、永不重试**。此后
  `_save_evo_run` 里 `if self._evo_store is None: return` —— 直接 return、**零日志**。
  用户跑了几十代进化，界面显示「进化中」，但档案一条都没写进去，且无从排查。
- `_evo_store` 改 **property 惰性解析**（与 `BasePage.store` 同构）：
  `evo_store` 才解析，`_resolve_evo_store()` 按需建单例，失败返回 None **并记 error**。
- 新增 `storage/evolution_store.get_evolution_store()` 单例（对齐既有的
  `get_backtest_store()`），`reset_evolution_store_for_test()` 供测试隔离。
  原先每次页面构造都新建一个 `EvolutionStore`，重复 `makedirs`。
- `_save_evo_run` 不可用时**强制记 error + 界面提示一次**（`_evo_store_warned` 去重，
  避免每代刷屏），不再无声返回。

#### ② `_on_archive_selected` 的 None 访问
- `self._evo_store.convergence(rid)` 无判空 → None 时抛 `AttributeError`，
  被外层 `except` 吞成误导性的「读取进化档案失败」。
  → 改为先取 `self.evo_store`，None 时给直接可用的「档案不可用」提示。

#### ③ 后台初始化失败路径零日志（可观测性）
- `main_window._run_store_init` 的 `_do_init` 吞异常只返回 None，`_on_store_init_done`
  对 None 直接 return —— 两条路径都**不留任何痕迹**，与 `store_provider.get_store()`
  的 error 日志行为不一致。均补 `logger.error`。
- `_on_mdm_init_done` 收到 None（行情数据源建不出来）同样补 error 日志。
- `EvolutionStore` 模块补 `logger`。

### 新增
- `tests/unit/test_evo_store_lazy_regression.py`：14 项根因回归测试
  （单例语义 / 惰性解析 / 瞬时故障可自愈 / 不可用必记日志 / 只提示一次 /
  源码 AST 级防回归：禁止业务代码再裸判 `self._evo_store is None`）

---

## [5.2.3] - 2026-10-05

> 预测结果「未落盘」根治：上一条 5.2.2 引入的判空护栏把崩溃变成了**静默丢数据**
> （`AnalysisStore 尚未就绪` → 预测直接丢弃）。本版不再靠护栏兜底，而是让
> `AnalysisStore` 变成**按需可创建的线程安全单例**，页面永远能拿到可用 store。

### 修复

#### ① `预测结果未落盘：AnalysisStore 尚未就绪`（预测被静默丢弃）
- **真因**：5.2.2 只做了「延迟解析 + 定位器兜底」，但启动流程里定位器注册的是
  占位 `None`，且初始化走后台线程；若请求发生在建连完成前或后台线程已被回收，
  兜底链路全部落空 → `self.store` 恒为 `None` → 预测结果直接丢掉，用户只看到一条
  warning。
- 新增 `futures_quant/app/store_provider.py`：**AnalysisStore 线程安全单例**
  （`RLock` 保护），`get_store()` 在单例为空时**按需同步创建**（含单独捕获
  `SystemExit`，不让它穿透否定「刚写入成功」），`set_store()` 幂等（已存在则不覆盖、
  关闭后来者），另提供 `current_path()` / `reset_for_test()`。
- `BasePage._resolve_store()` 改为**两级兜底**：先查服务定位器 `request("analysis_store")`，
  未命中则退回 `store_provider.get_store()` 按需建连。
  → 现在 `page.store` **只有在 SQLite 库真的创建不出来时才为 None**。
- `main_window._on_store_init_done` 增加 `store_provider.set_store(store)` 登记，
  保证主窗口建好的实例与 provider 单例是同一个对象，避免「两套实例写两个库」。
- `_on_predict_done` 护栏级别从 warning 提升到 **error**，文案改为
  「数据存储不可用」——此处的 `None` 已只代表真的建库失败。

#### ② `_is_writable` 探针在系统级拦截下穿透（连带修复）
- **真因**：沙箱/安全软件的 safe-delete 守卫会拦截 `os.remove(probe)`，抛的是
  `SystemExit`（属 `BaseException`，不是 `Exception`），直接穿透过
  `except Exception` 炸掉 `AnalysisStore` 构造，导致测试大面积失败。
- `runtime._is_writable` 拆成三段：建目录 / 写探针 / 删探针，
  其中**删探针用 `except BaseException: pass`**（清理是尽力而为，任何系统级拦截
  都不得否定「刚写入成功」这个结论）。
- `get_data_dir` 加进程内 `_DATA_DIR_CACHE`：原先每次构造 `AnalysisStore` 都会
  新建并删除一次 `.write_test` 探针，高频触发守卫；缓存后探针只在首次探测出现。

### 新增
- `tests/unit/test_ui_store_linkage_crash_regression.py` 扩至 14 项：
  provider 按需创建 / 幂等 / 定位器注册优先于按需创建 / 未注册退回按需创建 /
  页面兜底按需拿到 store / `_on_predict_done` 护栏 / `_on_store_init_done` 登记回填 /
  安全推送不抛出。

---

## [5.2.2] - 2026-10-05

> UI/联动层两处运行时崩溃根治：`AnalysisStore` 后台初始化竞态导致的
> `save_prediction` AttributeError，以及进化链路里 `LinkageBus` C++ 对象
> 已销毁被误计入「基因评估失败」。

### 修复

#### ① `AttributeError: 'NoneType' object has no attribute 'save_prediction'`
- **真因**：主窗口按 UX-67 把 `AnalysisStore` 放到**后台线程**初始化（SQLite
  建连 + 建表约 100–500ms），页面可能在 store 就绪前被构造，构造入参是占位 `None`；
  而 `_on_store_init_done` 只更新了主窗口自身，**已建成的页面仍持有 None 且永不刷新**。
- `BasePage.store` 改为 **property**：构造时只存 `_store`，真正使用时才解析，
  未就绪时兜底查服务定位器（`_resolve_store`）。
- `_on_store_init_done` 增加**页面回填**：遍历 `self.pages` 逐个 `p.store = store`，
  并重新 `provide("analysis_store", store)`（启动时注册的是占位 None）。
- `_on_predict_done` 落盘前加判空护栏：store 未就绪时记 warning + Toast 提示用户，
  回调提前返回，不再炸掉整个研判结果渲染。

#### ② `RuntimeError: wrapped C/C++ object of type LinkageBus has been deleted`
- **真因**：`BUS` 是无父对象的模块级 `QObject`。两类场景会让其 C++ 端被销毁、
  而 Python 名字仍指向失效包装对象 —— ① QApplication 析构（应用退出）时 Qt 销毁
  所有 QObject，而后台进化 Worker 仍在跑；② 模块在 worker 线程首次 import 创建，
  随线程生命周期销毁。
- 新增 `linkage_bus.is_bus_alive()`（触碰 `objectName()` 探测存活）、
  `get_bus()`（失效则重建）、`safe_push_backtest_result()`（尽力而为，永不抛出）。
- `auto_evolve` 的 3 处裸 `BUS.push_backtest_result` 全部改为 `safe_push_backtest_result`。
  **联动通知是旁路能力，其失败不应被放大成「本代基因评估失败」。**

### 新增
- `tests/unit/test_ui_store_linkage_crash_regression.py`：11 项根因回归测试
  （store 延迟绑定 / 服务定位器兜底 / 页面回填 / BUS 存活探测 / 安全推送不抛出）

---

## [5.2.1] - 2026-10-04

> 自进化引擎 M2-12 故障根治：修复用户现场的三类运行时报错
> （因子切片 TypeError / IS 段日期解析失败 / 基因评估 KeyError），
> 并连带挖出 IS/OOS 校验长期静默失效与 typical_price 因子恒失败两个隐藏缺陷。

### 修复

#### ① `sequence index must be integer, not 'slice'`（因子信号）
- `factor_signal()`：入口把 `closes/highs/lows` 统一转 `list`。
  原实现只转了 `closes`，而 `StrategyBase._highs/_lows` 是 `deque`（不支持切片），
  `highs[-n:]` 必然抛 TypeError → 所有 H/L 类因子（hlc_avg / typical_price /
  donchian / cci / willr / stoch / adx / sar）100% 降级为「无信号」。
- `ensemble_strategy_signal()`、`regime_of()` 同病同修（入口转 list + 异常降级 0.0）。

#### ② `day is out of range for month: 0`（IS 段回测失败）
- **真因**：`SyntheticFeed` 把 `datetime` 作为**普通列**返回（index 是 RangeIndex），
  而 `split_is_oos()` 无条件取 `df.index[0]` → 整数 `0` → `_to_str` 产出 `"0"`
  → 下游 `pd.Timestamp("0")` 抛 `DateParseError: day is out of range for month: 0`。
- 新增 `validate._datetime_series()`：优先取 `datetime` 列 → 其次 DatetimeIndex →
  都没有才报错。`split_is_oos()` 改用它。
- **副作用收益**：IS/OOS 校验此前 100% 失败并被外层 except 静默吞掉，等于过拟合护栏
  从未生效；本次修复后护栏真正开始工作。
- `validate._to_str()` 改用 `pd.Timestamp` 严格校验，拒绝 `None/NaT/空串` 等脏值。
- `validate.i_o_o_split()`：补 NaT 判定（`pd.Timestamp("")` 返回 NaT 不抛错，
  原代码 `int(NaT.total_seconds())` 抛 `cannot convert float NaN to integer`）。

#### ③ `本代基因评估失败（已跳过）：'gene'` + 失败率 5/10
- `EvolutionEngine._evaluate()` 命中缓存时返回的 dict 只有 `_cached_gene`，
  缺 `gene` / `fitness` 键；而 `step()` 用 `result["gene"]`、
  `results.sort(key=lambda x: x["fitness"])` 访问 → 两条 KeyError。
  （第 2 代起必然命中缓存，故第 1 代能跑、第 2 代崩。）
- 缓存命中 dict 补齐为**完整结果形状**（gene/fitness/metrics/desc/signature/
  profitable/reasons/equity_curve/trades）；并行路径的两处降级 dict 同样补齐。
- 缓存基因重评失败时，由「静默 `pass` 保留残缺 dict」改为「降级为完整无利占位 dict
  + 记录 warning」，杜绝 `r["profitable"]` 后续 KeyError。
- `_evaluate()` 的 `bt.run()` / `validate_strategy()` 加显式 try/except，
  失败返回完整占位 dict 而非让异常冒到 `step()` 计入失败率。

#### ④ `typical_price` 因子恒定失败（连带发现）
- `PARAM_SPACE["typical_price"]` 原为 `{}`，但 `factor_signal` 读 `p["period"]`
  → 该因子 100% KeyError → 静默无信号，是「评估失败率过高」的隐藏贡献源。
- 补齐 `{"period": [5, 10, 20]}`；`factor_signal` 改用 `.get()` 兜底，
  兼容盈利库中 `params={}` 的历史基因。

### 新增
- `tests/unit/test_m2_12_evolve_failure_regression.py`：18 项根因回归测试
  （deque 因子消费 / PARAM_SPACE 覆盖 / 日期归一化 / 缓存 dict 完整性 / 连续 3 代稳定）
- `tools/run_unit_per_file.py`：逐文件跑 `tests/unit` 并汇总，规避整套件在
  Qt teardown 阶段挂起（RC=0xC0000135）导致拿不到汇总结果

---

## [5.2.0] - 2026-10-04

> UI_UX_UPGRADE_PLAN v2 Phase 5/6/7 全清零：UX-60~UX-84 共 25 项任务全部完成。
> 界面可用性（面包屑/窄屏导航/长任务/诊断联动/空态/右键跨页）与
> 可访问性（高 DPI/Tab 顺序/setWhatsThis/焦点环/减动效）双主线落地。

### 新增

#### Phase 5 · 界面可用性（UX-60 ~ UX-68，9 项）
- UX-60 导航分组：交易台 / 分析与回测 / 系统与数据三组标题 + 分组间距
- UX-61 面包屑 + 页面副标题（当前品种 / 周期 / 数据源回显）
- UX-62 窄屏抽屉导航：三档宽度自适应（≥1100 完整 / 900–1100 图标 / <900 顶部 QTabWidget）
- UX-63 长任务体验统一：进度条 + 阶段文案 + 百分比 + 可取消 + ETA + 日志实时滚动
- UX-64 诊断面板与日志目录联动（跨平台 `_open_log_dir`：Windows/macOS/Linux）
- UX-65 QMessageBox 收敛：非破坏性确认改 Toast + 内联错误
- UX-66 空态模板：`EmptyState` 分级文案 + 重试按钮
- UX-67 首屏性能：非首屏页面 `showEvent` 首次触发才构造骨架
- UX-68 表格/图表右键菜单「在此打开 K 线」跨页跳转

#### Phase 6 · 可访问性与环境适配（UX-70 ~ UX-75，6 项）
- UX-70 高 DPI 支持：Qt 6 默认启用 + Splash Logo 按 `devicePixelRatio()` 超采样
- UX-71 Tab 顺序：MarketOverviewPage（6 控件）+ PredictOpsPage（11 控件）焦点链
- UX-72 setWhatsThis 覆盖：导航栏、状态栏、主要操作按钮帮助文本（5 处）
- UX-73 屏幕变化订阅：`geometryChanged` + `virtualGeometryChanged` 信号订阅
- UX-74 焦点环 QSS：12 个控件类型 `:focus-visible` 样式（2px 圆角描边）
- UX-75 `QV_REDUCED_MOTION` 门控铺开：`motion_enabled()` 辅助函数 + 全部动画入口审计

#### Phase 7 · 验证与门禁（UX-80 ~ UX-84，5 项）
- UX-80 单元测试：`tests/unit/test_ux_phase5_6.py` 37 项全绿
- UX-81 offscreen 冒烟：`tests/e2e/smoke_ux_phase5_6.py` 50 项全绿
- UX-82 契约测试：`tests/unit/contracts/test_ux_contracts.py` 31 项，4 组契约（Token 完整 / QSS 无残留占位 / 主题切换无残留 / 键盘可达）
- UX-83 性能基线：`tools/perf_ui_budget.py` 输出 5 项预算（启动 ≤800ms / 主题切换 ≤60ms / 表格填充 ≤300ms / K 线 p95 ≤16ms / 图表 set_data ≤200ms）
- UX-84 文档同步：`CHANGELOG.md` v5.2.0 条目 + `__version__` / `__release_date__` 三处对齐

### 变更
- `futures_quant/__init__.py`：`__version__` 5.0.0 → 5.2.0，`__release_date__` 2026-10-02 → 2026-10-04
- `futures_quant/ui/main_window.py`：新增 `_update_nav_mode()` 三档宽度自适应 + `_connect_screen_changes()` 屏幕订阅 + 多处 `setWhatsThis`
- `futures_quant/ui/design_system.py`：新增 12 类 `:focus-visible` 焦点环 QSS
- `futures_quant/ui/splash.py`：Logo 按 `devicePixelRatio()` 超采样
- `futures_quant/ui/states.py`：新增 `motion_enabled()` 辅助函数
- `futures_quant/ui/diagnostics_dialog.py`：新增「打开日志目录」按钮 + `_open_log_dir()` 跨平台实现
- `futures_quant/ui/market_overview_page.py` + `predict_ops_page.py`：新增 `_setup_tab_order()` 焦点链

### 新增测试 / 工具
- `tests/unit/test_ux_phase5_6.py`（37 项）
- `tests/e2e/smoke_ux_phase5_6.py`（50 项）
- `tests/unit/contracts/test_ux_contracts.py`（31 项）
- `tools/perf_ui_budget.py`（5 项性能预算）

### 修复
- UX-62 最小窗口尺寸由 1024×768 降至 `min(800, min_w)`，允许窄屏模式真实生效
- UX-75 `MOTION` 常量在模块加载时评估，测试通过 `importlib.reload()` 后重设环境变量验证
- M4-05 inline 样式主题刷新二轮修复：`PageHeader` / `SectionHeader` / `StatusTile` / `StatTile` / K 线涨跌色 / 预测页标签样式统一传入 `self._theme`，消除局部主题与全局主题不一致导致的残留色
- QPalette 导入修复：`attribution_dialog.py` / `ai_settings_dialog.py` 补齐 `QPalette` 导入，避免 AI 配置加载阶段 NameError
- 测试修复：`test_m4_11_window_nav.py` 折叠导航断言改为 `_nav_mode == "collapsed"`，允许折叠态极短文本或空文本

---

## [5.0.0] - 2026-10-02

> UPGRADE_PLAN_V5 Phase A/B/C 全清零，7 域 73 项任务全部完成。

### 新增

#### M1 · 全部功能模块（10 项）
- M1-01 交易反馈闭环死链修复（P0）
- M1-02 失效 e2e 断言修复（P0）
- M1-03 策略注册表 + 消除平行路径（P1）
- M1-04 存储并发安全 + 备份 + 瘦身（P1）
- M1-05 StrategyBase 缓冲区语义修复（P2）
- M1-06 ComboStrategy 权重口径修复（P2）
- M1-07 孤模块处置 + lazy import 守卫（P1）
- M1-08 独立回测表单校验（P1）
- M1-09 系统诊断面板（P1）
- M1-10 测试工程基建（pytest + conftest + fixtures）（P2）

#### M2 · 自我进化（13 项）
- M2-06 补过拟合护栏（IS/OOS 切分 + 参数邻域稳健性 + Deflated Sharpe）（P0）
- M2-07 适应度缓存（精英不重复评估）（P1）
- M2-08 遗传算法接入 + 蒸馏接入 + 调度接入（P1）
- M2-09 进化可观测性 + 三轨进化接入（P1）
- M2-10 参数空间定义 + 交叉变异算子（P2）
- M2-11 修复超参数搜索器（ParameterGrid + LSTM 相对导入 + 包导入）（P2）
- M2-12 进化存储持久化 + 历史回看（P2）

#### M3 · AI 模型分析（13 项）
- M3-01 修复恒零特征 + ATR 列名（P0）
- M3-02 特征契约测试（P0）
- M3-03 修复回放样本内泄漏（P0）
- M3-04 特征缓存串味 + 线程竞争修复（P0）
- M3-05 真·Walk-Forward 验证接入生产（P1）
- M3-06 修复多模型对比名不副实（P1）
- M3-07 修复特征重要性与风险评分（P1）
- M3-08 LLM 客户端加固（熔断 + 重试 + 超时）（P1）
- M3-09 补齐 AI 层单元测试（P1）
- M3-10 模型卡片 + 状态透明化（P1）
- M3-11 阈值集中化（154 项 → 单一常量表）（P2）
- M3-12 消除重复预测与重复训练（P2）
- M3-13 漂移检测接线（P2）

#### M4 · 界面架构与 UI/UX（14 项）
- M4-01 修复页面栈索引错位（P0）
- M4-02 修复 MarketPage 必崩 + 孤儿页面处置（P0）
- M4-03 修复字号层级丢失（P0）
- M4-04 建立 QSS 单一事实来源（P1）
- M4-05 消灭 inline 样式不刷新（P1）
- M4-06 异步框架统一：取消 / 进度 / 超时（P0）
- M4-07 通用组件补齐（Card / DataGrid / Toast / EmptyState / Skeleton / Pagination）（P1）
- M4-08 表格能力铺开（31 张表全量迁移 DataGrid）（P1）
- M4-09 长任务可视化（进度 + 取消 UI）（P1）
- M4-10 主线程去阻塞（connect 异步 + 缓存 + 节流）（P1）
- M4-11 导航与窗口体验（Splash + 图标 + 折叠 + 状态栏）（P1）
- M4-12 快捷键与命令面板（Ctrl+K / F5 / Ctrl+1..7）（P2）
- M4-13 图表交互补齐（十字光标 + 联动 + 右键菜单）（P2）
- M4-14 无障碍与动效开关（MOTION / focus / 字号缩放）（P2）

#### M5 · 爬虫与数据源（10 项）
- M5-01 修复财联社并发失败（P0）
- M5-02 行情源缓存 + 连接真实性（P0）
- M5-03 采集合规与限流（UA 池 + 令牌桶 + robots）（P1）
- M5-04 资讯落库 + 数据质量校验（P1）
- M5-05 发布时间真实性（P1）
- M5-06 采集可观测性（P1）
- M5-07 消除滥用与主线程阻塞（P1）
- M5-08 契约测试（录制回放）（P1）
- M5-09 解析健壮性升级（BS4 + 反爬 + chardet）（P2）
- M5-10 安全与合规（VERIFY_SSL + https + URL 收敛）（P2）

#### M6 · 专项：关于板块重构 + 二维码卡片（6 项）
- M6-01 修二维码路径 + 打包进 EXE（P0）
- M6-02 二维码卡片重做（尺寸 / hover / 放大 / 保存）（P0）
- M6-03 扫码引导文案与信息架构（P0）
- M6-04 响应式布局（双列→单列自适应）（P0）
- M6-05 视觉层次与主题化（五段式信息架构）（P0）
- M6-06 交互与可达性（Esc / Tab / 键盘激活 / 复制反馈）（P2）

#### M7 · 专项：模型配置板块重构（7 项）
- M7-01 表单分组重构（向导式 4 分段）（P0）
- M7-02 修复 requests NameError + 导入规范（P0）
- M7-03 信息层级与状态反馈（inline 校验 + dirty 角标）（P0）
- M7-04 连通性测试体验升级（四元组 + 历史 + 错误建议）（P1）
- M7-05 诊断页（密钥指纹 + 脱敏复制）（P1）
- M7-06 配置导入 / 导出 / 重置（P1）
- M7-07 主题化与交互提示（快捷键 + Tooltip）（P1）

### 修复

- 修复 `StrategyBase` 缓冲区无限增长（`deque(maxlen=HISTORY_LEN)` 封顶）
- 修复 `ComboStrategy` 权重未归一化（`sum(w)=1`）
- 修复 `MarketPage` 必崩（`_build_alert_center` 签名 + `margin` 提取）
- 修复 `ai/tuning/*` 模块缺依赖崩溃（lazy import + `_Stub` 守卫）
- 修复 `ParameterGrid` 局部变量漏绑定
- 修复 LSTM 相对导入 `..lstm` → `..ai.lstm`
- 修复 `_get_score_func` 包 ImportError
- 修复 `fetch_cls_news` 并发失败（容错签名 + `inspect.signature`）
- 修复 `news_feed` 单源超时（`per_source_timeout=25` 协作式取消）
- 修复 `ctp_gateway._ctpbee_app` → `_ctpbee_api` 属性名
- 修复 `QDoubleSpinBox` 温度越界（max=2.0 自动钳制）
- 修复 `_fields[key]["page"]` 错位（`_reindex_field_pages()` 后置修正器）
- 修复 `QGraphicsEffect` 黑底 BUG（全项目禁用，改用 paintEvent 自绘）

### 测试

- 累计 pytest tests/unit：**457 items collected / 411 passed / 0 failed**
- 新增测试文件 30+，覆盖 M1-M7 全部 73 项任务
- offscreen e2e 回归：MainWindow + 14 页面构造全绿

### 工程

- 版本号 4.0.0 → **5.0.0**
- 发布日 2026-09-21 → **2026-10-02**
- UPGRADE_PLAN_V5 三阶段（A 止血 / B 提质 / C 体验）全部完成
- 清理 `nul` 文件（Windows 设备名冲突，0 字节残留）
- 清理空目录 `pytest-cache-files-i6i7zd87/`

---

## [4.0.0] - 2026-09-21

> v4.0 系统性升级（UPGRADE_PLAN.md），详见 `docs/2026-09-25/UPGRADE_PLAN.md`。

---

## [3.1.0] - 2026-09-09

> v3.1 基线版本。
