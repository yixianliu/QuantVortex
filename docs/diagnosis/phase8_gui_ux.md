# 第 8 期（最后一期）：GUI 重构与体验升级

> 范围：`futures_quant/ui/`、`tests/unit/`、`tests/e2e/`、`docs/diagnosis/`、`outputs/phase8_ux/`。
> 未触碰 `backtest/`、`core/`、`data/`、`storage/`、`ai/`、`strategy/`；无 git 写操作、无联网、无生产库写入。

## 1. 结论

本期做的是**降低学习成本**而不是削功能：7 个主页面、全部入口保持原样，信息密度不降。

四类目标全部落地：

| 目标 | 结果 | 硬证据 |
|---|---|---|
| A 视觉统一 | 建立 token/样式工具层；实际改动的 3 个页面完成迁移，其余页面列为「未迁移」，不做全仓格式大改 | token 解析值断言 + QSS 兜底断言（单测） |
| B 主线压缩 | 主线尾部「看结果 → 预测」由 **3 次点击 → 1 次点击**（省 2 次）；跨页上下文自动带品种/周期并自动预测 | `MAINLINE_CLICK_JSON` 实跑 |
| C 失败可行动 | AI 研判前置禁用 + 原因 tooltip；静默 `except: pass` 改为状态栏/Toast/日志；副标题与真实功能对齐；独立回测 KPI 6→10 且接真实导出 | 单测 + 代码列表 |
| D 开关与标识 | 真实主力换月开关（两处页面、默认关、日线门控）；`legacy_missing` 老记录标识；覆盖率口径复查；`pages.py` 只标注不删除 | 单测 + 实跑 |

同时修掉两个**此前一直存在但被误判为「偶发」**的跳转缺陷（详见 3.2）：
`navigate_requested` 的页面 key 错写为 `"predict"`（真实 key 是 `"predict_ops"`）；
首页延迟构造时无条件 `setCurrentWidget(首页)`，会把用户在首帧 100ms 内的跳转打回行情页。

**实测通过 / 未验证（一句话）**：7 页 offscreen 构建与主线点击脚本、27 项单测、运行历史/复跑/网格弹窗的构造与预览均已实跑通过；
**未验证**的是真实联网行情下的网格全量扫描耗时、真实 `backtest_runs` 库里的老记录复跑（本测试无生产数据），
以及导出/复跑在真实磁盘权限与大数据量下的表现。

## 2. 主线点击路径对照（实跑）

统计脚本：[tests/e2e/test_phase8_mainline.py](file:///d:/PythonProject/QuantVortex/tests/e2e/test_phase8_mainline.py)
离屏真实控件 `click()`；预测/回测耗时动作打桩，只统计「触发等待」次数。

实测输出（`python -m pytest tests/e2e/test_phase8_mainline.py -s -q`）：

```json
MAINLINE_CLICK_JSON {
  "legacy_tail": {"clicks": 3, "page_switches": 1, "waits": 1},
  "new_tail":    {"clicks": 1, "page_switches": 1, "waits": 1},
  "reduction":   {"clicks": 2, "page_switches": 0, "waits": 0},
  "mainline_before_tail": {"clicks": 3, "page_switches": 2, "waits": 2}
}
```

| 环节 | 改造前 | 改造后 |
|---|---|---|
| 看行情 → 预测（双击品种） | 跳转**从未生效**（信号未连接 + key 错），必须侧栏切页（+1 点击 +1 切页） | **1 次点击 / 1 次切页**，品种+周期随上下文带入 |
| 预测（开始预测） | 1 点击 / 1 等待 | 1 点击 / 1 等待 |
| 调策略 → 回测（回测此策略） | 1 点击 / 1 切页 / 1 等待 | 1 点击 / 1 切页 / 1 等待 |
| 看结果 | 0 点击（KPI 自动刷新） | 0 点击 |
| 结果 → 预测（尾部） | **3 点击**（切页 + 手选品种 + 点开始）/ 1 切页 / 1 等待 | **1 点击**（🔮 去预测）/ 1 切页 / 1 等待，自动开跑 |
| **完整主线合计** | **6 点击**（跳转不可用则 7）/ 3 切页 / 3 等待 | **4 点击 / 3 切页 / 3 等待** |

> 口径说明：`mainline_before_tail` 的 3 点击 / 2 切页 / 2 等待是主线前半段（行情→预测→回测→看结果）；尾部两条路径从同一基线出发，因此可直接相减。

## 3. 改动清单（文件:行 → 痛点 → 改法 → 验证）

### 3.1 A 视觉统一（先立骨架，不做全仓重写）

| 位置 | 痛点 | 改法 | 验证 |
|---|---|---|---|
| [design_system.py:43-77](file:///d:/PythonProject/QuantVortex/futures_quant/ui/design_system.py#L43-L77) | 无状态色语义，各页各自写 `#ef4444` 之类 | 双主题新增 `success/danger/info`，并加别名映射（ok/error/weak/up/down） | `test_status_tokens_exist_and_map` |
| [design_system.py:120-170](file:///d:/PythonProject/QuantVortex/futures_quant/ui/design_system.py#L120-L170) | 字号/间距/圆角只能翻大字典，易写错 key | 新增 `token/status_color/font_size/space/radius/status_qss` 读取工具，未知 key 回退默认值不抛异常 | `test_font_space_radius_tokens`、`test_status_qss_contains_color_and_size` |
| design_system QSS 模板（`#breadcrumb` / `#breadcrumb-sep` / `#page-subtitle`） | 页头靠 3 处内联 `setStyleSheet` 维持字号/字重，主题刷新与字号缩放下易漏 | 下沉 QSS，并补 `font-size:$font_body$` 保证删除内联后视觉等价 | `test_migrated_pages_no_inline_header_style` |
| [main_window.py:317-324](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L317-L324) | 同上 | 控件只设 `objectName`，样式交给 QSS | 同上 + offscreen 截图 |
| [data_page.py:26,89,100-109,200,239,262](file:///d:/PythonProject/QuantVortex/futures_quant/ui/data_page.py#L89-L109) | 5 处卡片主色硬编码（含 `#0ea5e9` 与全局蓝不一致） | 改用 `status_color("success/info/warning")` 与 `token("chart_series_5")`；`#0ea5e9`→`#3b82f6`（有意统一，见风险 R2） | 页面 offscreen 构建 + 截图 |
| [simple_backtest_page.py:109-119,665-681](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L109-L119) | 3 处校验提示用裸 `color:#ef4444` | 改 `status_qss("danger", ...)`；换月开关开启/关闭用 `status_color("warning"/"sub")` | 单测 + 截图 |

**已迁移 / 未迁移清单（grep 计数，当前工作树）**

| 文件 | hex | font-size | setStyleSheet | 状态 |
|---|---|---|---|---|
| `main_window.py` | 1 | 4 | 4 | **已迁移**（页头 3 处内联已移除；余量为图标/局部） |
| `data_page.py` | 0 | 0 | 0 | **已迁移**（全部走 token） |
| `simple_backtest_page.py` | 0 | 0 | 8 | **已迁移**（8 处均为 `status_qss`/主题重绘，无裸色值） |
| `backtest_runs_dialog.py`（新增） | 0 | 0 | 19 | **已迁移**（状态条/标题全部走 `status_qss`/`status_color`，0 裸色值） |
| `attribution_dialog.py` | 7 | 0 | 3 | **部分**：仅新增 legacy 提示条走 `status_qss`，既有色值未迁 |
| `predict_ops_page.py` | 72 | 29 | 21 | **未迁移**：本期只改禁用态与失败文案 |
| `backtest_page.py` | 32 | 6 | 19 | **未迁移**：本期只新增控件与 legacy 标识 |
| `market_overview_page.py` | 33 | 52 | 30 | **未迁移**：本期只修跳转 key |
| `states.py` / `widgets.py` | 22 / 9 | 12 / 17 | 27 / 27 | **未迁移**（共享基件，改动面大，留后续） |
| `pages.py`（死代码） | 83 | 18 | 9 | **不迁移、不删除**（用户未拍板） |

全局 grep 对照：phase7 调查记录为 397 hex / 131 font-size / 190 `setStyleSheet`；当前为 **434 / 181 / 207**。
差异说明：`+6 hex` 正是本期新增的 `success/danger/info` 双主题 token 定义本身；其余增量来自本仓库中其它并行阶段的 UI 新增与既有代码，**不是本期新增的裸色值**。
本期效果的可验证口径是「实际改动页面新增裸色值 = 0」，而非全仓计数下降——全仓重写会把 diff 变成不可审查的几千行，明确不做。

### 3.2 B 主线压缩 + 跳转可靠性（真实缺陷修复）

| 位置 | 痛点 | 改法 | 验证 |
|---|---|---|---|
| [market_overview_page.py:2363](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L2363) | 双击品种发出 `key="predict"`，而 `NAV` 里是 `"predict_ops"` → `_goto_page` 报「未找到页面 key=predict」，双击**永久无效** | key 改为 `"predict_ops"`，并携带 `{symbol, period}` | 主线 e2e：`switch→PredictOpsPage` |
| [main_window.py:470-473](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L470-L473) | 首页由 `_init_first_page` 单独构造，只连了 `selection_changed`，**没连 `navigate_requested`** → 行情页发出的跳转无人接收 | 补连 `navigate_requested`（与 `_switch` 内延迟页面一致） | 同上 |
| [main_window.py:455-505](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L455-L505) | 首页 100ms 延迟构造结束时无条件 `setCurrentWidget(首页)` + 重置侧栏高亮/面包屑 → 用户在首帧内的跳转被打回，表现为「跳转一会儿又回去」 | 先判断占位符是否仍为当前页（`placeholder_was_current`），只在是的时候才切首页；否则保持用户所在页面 | 主线 e2e 稳定通过（此前必失败） |
| [backtest_page.py:2527-2533](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2527-L2533) | 回测完成→再预测必须侧栏切页 + 手选品种 + 点开始（3 点击） | 新增「🔮 去预测」，带品种/周期并 `auto_run=True` | 主线 e2e 尾部 3→1 |
| [simple_backtest_page.py:265-277,684-710](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L265-L277) | 独立回测结果无法带走，也无导出 | 新增「📤 导出结果」「🔮 用该品种去预测」，结果渲染后启用 | 单测 + 截图 |
| [predict_ops_page.py:967+](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L967) | 跨页上下文只定位品种，用户仍需再点一次 | `apply_context` 支持 `auto_run`：`QTimer.singleShot(0, _run_prediction)`，状态栏提示「正在自动预测…」 | `test_apply_context_auto_run_triggers_prediction` |

### 3.3 C 失败必须可行动（诚实性）

| 位置 | 痛点 | 改法 | 验证 |
|---|---|---|---|
| [predict_ops_page.py:222-224,483,1270-1288,1348,1358,2211](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L222-L224) | 未预测时「AI 指标研判」可点，提示词却没有预测上下文，结论无依据 | 构建期 `setEnabled(False)` + 禁用态 tooltip「请先点击「开始预测」…」；`_run_ai_indicator` 增加无结果守卫（状态栏 + warning toast）；有结果才启用 | `test_ai_indicator_disabled_before_prediction` / `..._enabled_after_result` |
| [predict_ops_page.py:885-887](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L885-L887) | 切换品种/周期后旧结果仍可被 AI 研判复用（跨品种污染） | 切换即 `_last_res=None` + 禁用 AI 按钮，并刷新回测联动按钮 tooltip | `test_ai_indicator_reset_on_selection_change` |
| [predict_ops_page.py:901-927](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L901-L927) | `except Exception: pass` 吞掉联动失败，用户只看到「没反应」 | 改为状态栏可行动文案 + warning toast：已跳到回测中心但自动运行失败，请手动点「运行手动回测」 | 代码核对 + 主线 e2e |
| [backtest_page.py:4237-4240](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L4237-L4240) | 历史详情读取失败静默 | logger + 状态行 + toast 三处给出「读取失败：…（可稍后重试）」 | 代码核对 |
| [main_window.py:93](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L93) | 数据管理页副标题写「行情下载」，但该页无下载功能 | 改为「数据导出、备份恢复、数据源管理、系统设置」（与真实卡片一致） | `test_main_window_subtitle_matches_real_features` |
| [simple_backtest_page.py:286,622-640,684-702](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L286) | 独立回测仅 6 个 KPI、无导出 | KPI 6→**10**（新增交易笔数/95%VaR/最大连亏/多空开仓，不替换旧指标）；导出接 `backtest/export.py::export_result`（第 3 期 API **已存在**，非占位） | 单测 `len(page.kpis)==10` |

### 3.4 D 开关与标识补齐

| 位置 | 内容 | 验证 |
|---|---|---|
| [simple_backtest_page.py:109-119,251-256,665-681](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L251-L256) | 「真实主力换月」开关：默认取 `backtest.enable_dominant_roll`（缺省 False）；开启提示「需联网取合约链、耗时较长」；**非日线自动取消勾选并禁用**（tooltip 说明原因）；运行前再次拦截 | `test_default_dom_roll_*`、`test_dom_roll_disabled_on_non_daily`、`test_simple_backtest_passes_use_dominant_roll` |
| [backtest_page.py:2520-2526,2751-2756](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2520-L2526) | 回测中心手动面板同样接入换月（`build_roll_schedule` → `roll_schedule=`），非日线给可行动提示 | 单测 + 代码核对 |
| [backtest_page.py:4131-4133,4148-4162](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L4131-L4133) | `trace_status="legacy_missing"` 记录：代数列显示「老记录无指纹」，tooltip「老记录无指纹（无法追溯数据来源/种子）」 | `test_legacy_history_row_marker` / `test_new_history_row_has_no_legacy_marker` |
| [attribution_dialog.py:256-260](file:///d:/PythonProject/QuantVortex/futures_quant/ui/attribution_dialog.py#L256-L260) | 历史详情弹窗（归因）同样加老记录提示条 | 代码核对 |
| [predict_ops_page.py:2441-2456](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2441-L2456) | 区间覆盖率口径复查：`coverage=None` → 「实测覆盖率：样本不足（原因）」；有值 → 实测覆盖率 + 已结算样本 n + 95%CI；**不回退残差 σ 近似** | `test_interval_coverage_sample_short_text_and_real_api` |
| [pages.py:1-6,64-77,608,1339,2386](file:///d:/PythonProject/QuantVortex/futures_quant/ui/pages.py#L1-L6) | 死代码只加「⚠️ 未启用 / 待移除」模块级标注 + `_deprecated` 装饰器，**不删除** | 代码核对 |

### 3.5 第 3 期能力接线（原「依赖其它期」已落地，本期全部接上）

模块：[backtest_runs_dialog.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_runs_dialog.py)（新增，约 700 行；`futures_quant/ui/` 内，未碰内核）

| 入口 | 位置 | 接线方式 | 失败/边界处理 |
|---|---|---|---|
| 📚 运行历史 | [simple_backtest_page.py:284-289](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L284-L289) → `RunHistoryDialog` | `store.recent_runs(limit=200)` / `count_runs()` / `db_stats().run_rows`，标题显示「最近 N 条 / 库内共 M 条」 | 库打不开/读失败 → 状态条写原因并禁用导出/复跑；无记录 → 「先跑一次回测」引导 |
| 📤 导出所选 | `RunHistoryDialog._export_selected` | `export.export_stored_run(store, run_id, outdir)`（目录选择，落 CSV/JSON） | 目录不可写/老记录缺快照 → 红字写明原因；成功显示文件数 |
| 🔁 复跑校验 | [simple_backtest_page.py:269-274](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L269-L274) → `ReplayCheckDialog` | 优先 `BacktestService.replay(run_id, store, feed)`，服务未注册回退 `runner.replay_run`；7 项逐项填充「期望 vs 实际」 | 不一致项在结论里**点名**（如「数据指纹（行情窗口）、KPI 全量比对」）；异常 → 「复跑失败 + 可行动建议」并可重试 |
| 🧪 参数网格 | `GridSweepDialog` | `sweep.expand_grid` 预展开组合数 + `sweep.run_sweep(feed, cfg, grid, fixed_params, limits, should_abort, on_progress)`；`page._run_worker` 后台线程；`worker.emit_progress` 推进度；取消走 `worker.isInterruptionRequested` | 套利策略 → 「未在策略注册表注册，仅支持单腿策略」；格式错 → 带行号；组合数 >300 → 拒绝并要求缩小网格；失败/取消都写状态，不渲染半截 Top-N |

关键口径：
- 网格 UI **只拿摘要与 Top-N**：`run_sweep` 返回的 `top` 最多 `top_k` 条，其余组合结果不会进入 UI；
  内存上限 `max_summaries_in_memory=2000` 由内核控制，UI 不遍历完整集合。
- `is_stale=1` 的记录：状态列显示「参数口径已变更，仅审计用途」；复跑弹窗即使在 7 项全一致时，
  结论也固定为「仅审计…（不作为一致性通过）」，**任何路径都不会出现绿色“通过”**。
- 换月开关旁新增常驻代价说明（两处页面）：「需联网取合约链 · 耗时显著增加 · 链不完整直接报错（不回退近似）」。

## 4. 验证实跑输出

```
python -m pytest tests/unit/test_phase8_gui_ux.py -q
...........................                                              [100%]
27 passed

python -m pytest tests/e2e/test_phase8_gui_smoke.py -s -q
PAGES_OK 7/7
1 passed

python -m pytest tests/e2e/test_phase8_mainline.py -s -q
MAINLINE_CLICK_JSON {"legacy_tail": {"clicks": 3, "page_switches": 1, "waits": 1},
                     "new_tail": {"clicks": 1, "page_switches": 1, "waits": 1},
                     "reduction": {"clicks": 2, "page_switches": 0, "waits": 0},
                     "mainline_before_tail": {"clicks": 3, "page_switches": 2, "waits": 2}}
1 passed
```

补充：offscreen 用假 store 构造 `RunHistoryDialog` 实跑（2 条记录）：
`HISTORY_ROWS 2 | 老记录无指纹（…） | 参数口径已变更，仅审计用途`；
`GridSweepDialog` 预览实跑：`将运行 9 个组合`（`fast=5,10,20 × slow=30,60,120`），
`SweepLimits / run_sweep` 签名与调用一致（已用 `inspect.signature` 核对）。

> 口径说明：offscreen 下行情表为空，主线脚本用「同一 `navigate_requested` 信号」代替真实双击；
> 双击路径的 key/信号连接已由 `test_market_double_click_context_is_handled` 与代码修复覆盖。

## 5. 未做项与依赖

| 项 | 状态 | 原因 / 依赖 |
|---|---|---|
| `predict_ops_page.py` / `backtest_page.py` / `market_overview_page.py` / `states.py` / `widgets.py` 的存量硬编码色值 token 化 | 未做 | 单文件 20~80 处，全量替换会产生数千行不可审查 diff；本期只保证「改动处不新增裸色值」，后续按页推进 |
| 设计 token 门禁脚本（新增裸 hex 即 CI 失败） | 未做 | 属 `scripts/`，不在本期允许改动范围；建议第 9 期落地，白名单从本期 3 个已迁移页面开始 |
| `ui/pages.py`（约 2000 行）删除 | 未做（按指示） | 用户未拍板，只标注 |
| 回测结果的 PDF/图形报告导出 | 未做 | 本期接的是真实 `export_result` / `export_stored_run`（CSV×3 + JSON 参数快照/指纹/清单）；PDF 需内核侧提供渲染入口，属依赖其它期 |
| 运行历史分页/筛选（>200 条） | 未做 | 当前只取 `recent_runs(limit=200)`；`count_runs` 已在标题展示总数，超过 200 条时需后续加分页或按品种筛选 |
| 参数网格结果落盘（detail_sink / summary_sink） | 未做 | 内核支持，但会写用户目录；本期先在 UI 展示摘要与 Top-N，落盘入口留待产品确认格式 |
| 独立回测页曲线与回测中心结果的可视化统一 | 未做 | 涉及 `chart_widget` 双图型合并，收益低于风险 |
| 主线「调策略」环节的参数面板前置 | 未做 | 当前策略参数在回测中心已可预设；再前置会挤压 K 线区，信息密度反而下降（明确取舍） |

## 6. 截图说明（offscreen 导出，`outputs/phase8_ux/`）

冒烟测试逐页 `win.grab().save(...)`，共 7 张：

| 文件 | 页面 |
|---|---|
| `page_0_market.png` | 行情全景 |
| `page_1_predict.png` | 预测操作（含 AI 研判按钮禁用态可见） |
| `page_2_backtest.png` | 回测中心（手动面板含「真实主力换月」「🔮 去预测」） |
| `page_3_simple_backtest.png` | 独立回测（10 KPI + 导出/去预测按钮） |
| `page_4_ctp.png` | 实盘监控 |
| `page_5_log.png` | 日志预警 |
| `page_6_data.png` | 数据管理（副标题已与真实功能对齐） |

> 目录内另有 `page_0_42455476.png`、`page_5_67318222.png` 为早期命名遗留（内容相同）。按「不删文件」约束保留，新截图以 `page_<idx>_<slug>.png` 为准。

## 7. 残留风险

- **R1 首帧延迟构造**：已改为「不抢占用户已切换的页面」。若未来把首帧延迟调大，仍需保证 `placeholder_was_current` 判断先于任何 `setCurrentWidget`。
- **R2 颜色统一**：`data_page` 的 `#0ea5e9`→`#3b82f6` 是**有意**的颜色归并（与全局 info 蓝一致），视觉上有轻微变化；若设计侧要求保留青色，应改回并新增独立 token，而不是回退成裸色值。
- **R3 换月开关门控**：只允许日线，是内核 `build_roll_schedule` 的现有能力边界；若后续支持分钟级合约链，需同步放开前端门控与提示文案。
- **R4 主线统计口径**：`page_switches` 统计的是 `QStackedWidget.currentChanged`，包含延迟构造页面时的首次入栈；脚本已用「尾部基线相减」消除该影响，跨版本对比时请沿用同一口径。
- **R5 并行会话**：本仓库同时存在其它期对 `backtest/`、`core/`、`app/`、`storage/` 的未提交改动；本期未 revert、未格式化这些文件，接口以当前工作树实际签名为准（`export_result` / `export_stored_run` / `replay` / `expand_grid` / `run_sweep` 均已核对签名）。
- **R6 运行历史库为只读访问**：UI 只调用 `recent_runs / count_runs / db_stats / get_run`，不写库；但打开 store 会创建/连接 SQLite（WAL），这是应用既有行为，不是本期新增写操作。
- **R7 run_id 缺失**：独立回测走内核回退路径（未注册服务）时，结果可能没有 `run_id`；此时点「复跑校验」会引导到「运行历史」并说明原因，不会给出假的校验结论。
- **R8 进度回调线程**：网格进度通过 `worker.emit_progress` → `Worker.progress` 信号回主线程（`on_progress` 绑定对话框对象），UI 更新不在后台线程执行。
