# 回测后阶段 · 下一阶段深化计划（R5+）

> 依据：回测中心深度调优 + R1~R4（绩效图交互 / 手动回测 / 联动 / 真实数据）已全部收官。系统现在跑在「真实合约规格 + 真实历史行情」基线上。下一步不再围绕「回测做对」展开，而是围绕「回测后系统的价值深化」与「交付与对接」。
>
> 本计划基于 `docs/roadmap_next_three_directions.md`（方向一已由 R1~R4 覆盖，方向二三未动）+ 自然衍生方向，给出 5 个候选任务的优先级、依赖、风险与决策选项。

---

## 一、回顾与候选清单

| 编号 | 方向 | 候选任务 | 来源 | 价值 | 依赖 | 复杂度 |
|------|------|----------|------|------|------|--------|
| **R5** | 真实数据扩列 | 多品种真实样本（金属/能化/农产品/金融）覆盖 | R4 自然延伸 | 中 | akshare 已装 | 低 |
| **R6** | 分析能力深化 | 绩效归因（分笔/月度/持仓时长） | R1 图表承接 + roadmap 方向一 | 高 | R4 已落 | 中 |
| **R7** | 体验闭环 | 回测/进化状态持久化 + 重启恢复 | roadmap 方向一部分 | 中 | backtest_store 已存在 | 中 |
| **R8** | 交付 | Inno Setup 安装包 + 代码签名 | roadmap 方向三 | 中 | PyInstaller 已产出 EXE | 中 |
| **R9** | 对接 | CTP 仿真环境接入（只读监控） | roadmap 方向二 | 高 | 需期货账号前置 | 高 |

---

## 二、每条任务的具体内容

### R5 · 真实样本多品种扩列（✅ 已完成，2026-07-28）
- **5.1** 用 `collect_real_samples.py` 批量拉取：au.SHFE / i.DCE / IF.CFFEX 主力连续日线（连同既有 rb.SHFE），落 `data/real_samples/`。✅ 4/4 全部成功（rb 4208 / au 4272 / i 3105 / IF 2310 根）。
- **5.2** `test_backtest_real_akshare.py` 增 F 段（多品种真实回测），4 板块均跑通真实规格+真实回测：末权益均 > 0、资金曲线均随行情波动、成交数 287~374 笔。✅ 4/4 末权益 > 0。
- **5.3** `BacktestCenterPage._populate_manual_symbols` 扫描 `data/real_samples/` 给已落盘品种 label 末尾加「📦真实」尾标；其余 35 个品种不带标。✅ 视觉对比清晰。
- **R5 完成标准**：4 品种真实样本落盘 + 多品种 e2e 全绿 + UI 视觉标记 e2e 全绿。回归 6/6 套件（test_all_pages / test_backtest_manual / test_backtest_linkage / test_perf_chart_ux / test_backtest_futures / test_backtest_real_akshare）全 rc=0；新增 `test_real_sample_badge` 第 7 套件全绿。

### R6 · 绩效归因/分笔分析 ✅ 已完成（2026-07-29）
- **6.1** 历史表行加 "📊 详情" 按钮（第 12 列）→ 弹 `AttributionDialog`（`futures_quant/ui/attribution_dialog.py`）：
  - **分笔成交表**（7 列）：开/平时间、方向（多/空）、手数、持仓时长、盈亏(元)、手续费。
  - **月度收益柱状图**（正绿负红，QPainter 渲染，复用 `chart_widget.PriceChart`，**零 matplotlib 依赖**）。
  - **持仓时长分布**（5 桶直方图，按累计盈亏着色）。
  - **顶部摘要卡**：品种/代数/收益/回撤/胜率/夏普/成交数。
- **6.2** 数据链路：`Backtester.run` 输出 `trades` → `auto_evolve._evaluate`/`_step` 透传 `snap.gen_best_trades` → `backtest_store.add_history` 序列化进 `evolve_history.trades_json`/`equity_curve_json`（并 `return lastrowid`）→ `get_history_detail(id)` 取回 → 对话框渲染。`_prepend_history_row` 把 `snap._history_id` 带进内存行，保证「新鲜完成」与「DB 重载」两种来源行都能按 id 打开详情。
- **6.3** `tests/e2e/test_backtest_attribution.py`：真实回测（rb.SHFE 真实样本+真实规格）→ 落库 → `get_history_detail` 还原 → 构造对话框 → 断言分笔表非空(13 配对回合)、月度/持仓图已渲染、摘要卡填充。
- **完成标准**：详情对话框 e2e 全绿 + 全套 8 个 e2e 套件回归全绿。
- 实现偏差修正：原方案「matplotlib 嵌入 QLabel」改为「复用 `PriceChart` QPainter」，避免 matplotlib 打包体积与 offscreen 中文方框问题，与项目现有图表栈一致。

### R7 · 回测/进化状态自动持久化与恢复（✅ 已完成，2026-07-29）
- **7.1** 进化引擎状态（种群/最优基因/代数）→ 每代 `save_state("engine")` 落库，启动 `_restore_from_db` 恢复继续进化，`closeEvent` 触发 WAL checkpoint。`test_backtest_persistence.py` 覆盖「kill+restart 断点续跑」完成标准，rc=0。（前序会话已落地）
- **7.2** 用户最后手动配置（品种/参数/策略基因）→ `_run_manual` 落 `last_manual_config`，首切手动模式 `_maybe_restore_manual_config()` 预填品种下拉 + 精确基因；重启不丢。
- **7.3** 历史表第 12 列「🔁复跑」按钮 → `_rerun_history(id)` 按 id 取回完整配置（品种+精确基因）→ 切手动模式重跑。
- **顺手修的真 bug**：① `backtest_store` 老库缺 R6 的 `trades_json/equity_curve_json` 列（`CREATE TABLE IF NOT EXISTS` 不改旧表）→ `add_history` 静默失败；新增 `_migrate_schema()` ALTER TABLE 幂等补齐。② 互斥单选切换触发两次 toggled 把预填重置回首行 → `entering_manual` 守卫。
- **完成标准**：offscreen 模拟 kill+restart 状态可恢复（test_backtest_persistence rc=0）+ 复跑生成基因一致的 Manual 行（test_backtest_restore rc=0）。全套 e2e 现 **9 个全绿**。

### R8 · 安装包（Inno Setup）+ 代码签名（✅ 已完成，2026-07-29）
- **8.1** Inno Setup 脚本：`build_tools/installer.iss`（`futures_qt.spec` + `build_exe.py` 为 PyInstaller 构建侧）—— 桌面/开始菜单快捷方式、提权回退、卸载保留用户 `data/`。
- **8.2** 实测编译+安装/运行/卸载（offscreen 静默）：
  - 沙箱装 Inno Setup 6.7.3 → `C:/InnoSetup/ISCC.exe`；`ISCC installer.iss` 编出 `installer_out/FuturesQuant_Setup_1.0.0.exe`（lzma2，368MB）。
  - 静默安装到临时目录 rc=0；exe 落盘 12276 文件；offscreen 下进程可启动存活；静默卸载 rc=0；**卸载后非 data 文件 = 0（程序清理干净），仅保留用户 `data/`**，符合设计。
  - 修复：原 `futures_qt.spec` 把 Analysis 源路径按 `build_tools/` 解析（缺 main.py/config/futures_quant），`build_exe.py` 从 build_tools 跑必失败 → 改 spec 用项目根相对路径、build_exe cwd 改项目根，重建含 R7 的 dist（92.9MB）。
  - 中文向导：官方发布版不含 `ChineseSimplified.isl`，临时回退 `Default.isl`（英文向导）；中文向导可作 drop-in 后续替换。
- **8.3** 代码签名：留 stub（`QV_SIGN` 环境变量触发 signtool），待用户决策证书后做。
- **完成标准**：ISCC 编译产物可正常安装/运行/卸载，且卸载清理干净。✅

### R9 · CTP 仿真环境接入（只读监控）（✅ 已完成，2026-07-29；真实账号接入留接口）
- **9.2** `data/ctp_gateway.py` 已有完整 `CTPFeed` 适配器：懒加载 `vnpy_ctp`/`ctpbee`、SimNow/实盘 front 预设、`connect()`/`subscribe()`/行情回报转换/自动重连退避/`ctp_diagnose()`；两库均缺或凭据不完整时 `connect()` 返回 False 并给诊断，**绝不冒充实盘**。已接入 `MarketDataManager` 的 `ctp` 分支。
- **9.3** `ui/ctp_monitor_page.py`（`CTPMonitorPage`）已接入 `main_window.NAV` 页签「实盘监控（只读）」：连接状态卡 + 诊断面板（还差什么才能连上）+ 订阅合约实时盘口表 + 持仓/委托只读占位（明确标注交易侧未启用）。
- **9.4** 无账号/无 CTP 库时 **合成兜底**：`MarketDataManager.connect()` 在 `synthetic` 源下 `is_real=False`、盘口取自合成行情；`CTPMonitorPage` 显示诊断（未安装/凭据不完整）+ 合成盘口，不崩。
- **完成标准（可达部分）**：新增 `tests/e2e/test_ctp_monitor.py` 全绿（合成兜底 e2e：诊断非空 / 盘口表填充 / 连接柜台不冒充实盘 / 诊断刷新 / 主题切换 / 关闭事件不崩）。**真实 SimNow 账号接入留接口**：填 `ctp_settings.json` + `config/settings.json` 的 `data.source="ctp"` 即可切真账号；此部分需用户机器装 CTP 动态库 + 凭据，沙箱无法实测（与原计划风险表一致）。

---

## 三、风险与应对

| 风险 | 所属 | 应对 |
|------|------|------|
| akshare 限流/品种缺失（IF.CFFEX/AU） | R5 | 失败品种降级到 sina；测试断言"至少 3/4 成功" |
| matplotlib offscreen 中文方框 | R6 | 复用 `capture_ui.py` 字体注入；归因图用 PNG 嵌入避免文字重叠 |
| 持久化并发写（进化后台线程 vs UI 线程） | R7 | 复用 `BacktestCenterPage._save_*` 现有互斥；状态写入走 SQLite（已有 backend） |
| Inno Setup 仅 Windows | R8 | 标注 Windows-only；Mac/Linux 用 PyInstaller 单文件 |
| SimNow 账号需前置申请（不能纯代码做） | R9 | 提供 MockGateway 兜底；用户可在 docs/CTP_本地接入指南.md 流程跑通后切真账号 |
| 代码签名证书采购/吊销 | R8 | stub 留位，先做安装包；签名待用户决策 |

---

## 四、阶段时间表

| 阶段 | 内容 | 估时 |
|------|------|------|
| Phase 1 | R5（真实样本多品种） | 0.5 周 |
| Phase 2 | R6（绩效归因） | 1.5 周 |
| Phase 3 | R7（状态持久化） | 1.5 周 |
| Phase 4（并行可选） | R8（安装包） | 1 周 |
| Phase 5（外部依赖） | R9（CTP 仿真） | 2–3 周 |

---

## 五、决策节点

### 决策节点 D — 起点选哪条？
- **方案 D1（推荐）**：R5 → R6 → R7（留在回测价值链上，不引入外部依赖）
  - 优点：连续深化、零外部阻塞、全部封闭可复现。
  - 缺点：不直接产生新用户价值。
- **方案 D2**：R6 直接起步（跳过 R5）
  - 优点：直接做最有用户感的功能。
  - 缺点：归因图暂只跑在 rb.SHFE 一个真实品种上；视觉验证偏弱。
- **方案 D3**：R8 安装包先做（交付增强）
  - 优点：交付物立等可取；用户可分发。
  - 缺点：与回测价值深化脱钩；pyinstaller 已建好。
- **方案 D4**：R9 CTP 直接做
  - 优点：真正接实盘；价值最高。
  - 缺点：外部账号前置、限流、Mock 兜底工作量大。

---

## 六、立即行动建议

按方案 D1 推进：**从 R5 起步**（多品种真实样本扩列），因为它纯增量、低风险，且 R6 的归因分析需要在多个真实品种上做视觉验证时才能体现价值。R5 完成后即启动 R6。

确认后我即开干 R5.1–R5.3 + 新增 `tests/e2e/test_backtest_real_akshare.py` 多品种段。
