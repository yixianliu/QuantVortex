# 阶段 3 · e2e 测试网修稳 + GUI 交互打磨

> 项目：QuantVortex v5.2.15（PyQt6 期货量化桌面工作台）
> 范围：只做测试网修复与交互体验打磨，未改版本号、未 commit、未删文件、未触碰 `data/` 与生产库。
> 前置基线：`full_chain_diagnosis.md`、`phase0_data_risk.md`、`phase1_rules_matching.md`、`outputs/baseline_snapshot.md`。

---

## 一、e2e 一次性跑通命令与结果

### 1.1 一次性命令（单进程跑完全部 e2e）

在仓库根目录执行：

```powershell
python -m pytest tests/e2e -q --tb=short -rf --junitxml=.pytest_tmp/e2e_junit.xml
```

> 若在 PowerShell 里需要同时落盘日志，请用 `Start-Process -RedirectStandardOutput/-RedirectStandardError`，
> **不要**用 `*>` 重定向——Python 启动时的 `[DLL固定] ...` 是写 stderr 的，`*>` 会被 PowerShell 当作
> `NativeCommandError`，导致进程孤儿化、日志截断（这正是此前"只能分段拼接"的表象之一）。

### 1.2 结果数字（单次完整跑到底）

| 指标 | 结果 |
| --- | --- |
| 收集用例数 | **221** |
| 通过 | **221** |
| 失败 | **0** |
| 错误 | **0** |
| 跳过 | **0** |
| 总耗时 | **625.44 s（约 10 分 25 秒）** |
| 原生崩溃 | **无**（进程自然退出到 100%，无 `0xC0000409` fail-fast） |

进度输出已跑到 `[100%]`（`................................................................ [ 97%]` → `..... [100%]`），无 `F`/`E` 标记：
即 **e2e 已能单次完整跑到底**，不再需要分段拼接。

耗时最长的 4 个用例（用于判断长尾是否正常）：

| 用例 | 耗时 |
| --- | --- |
| `test_calibration_replay::test_m6_multi_model_replay` | 299.5 s |
| `test_predictor_model::test_predict_curve_finite_and_bounded` | 91.3 s |
| `test_predictor_model::test_ensemble_has_tree_member_and_weights` | 88.2 s |
| `test_calibration_replay::test_replay_symbol_builds_calibration` | 62.9 s |

### 1.3 基线 6 项失败的逐条定性

| # | 用例 | 定性 | 处理 |
| --- | --- | --- | --- |
| 1 | `test_backtest_real_akshare::test_specs` | **用例问题（过期）**：合约 key 已统一大写 | 断言改 `RB` |
| 2 | `test_backtest_real_akshare::test_real_backtest` | **产品缺陷**：日线 `00:00` 时间戳被误判非交易时段 → 零成交 | 修复 `RiskManager` |
| 3 | `test_backtest_real_akshare::test_multi_symbol_real_backtest` | **产品缺陷**：同上 | 同上 |
| 4 | `test_drift`（no_data 分支） | **产品缺陷**：无数据返回 `correlation=0.0` 语义错误 | 改 `None` + `Optional[float]` |
| 5 | `test_market_overview_tech_predict::test_market_overview_tech_expansion` | **用例问题（过期）**：文案「综合技术结论」→「综合结论」 | 更新 marker |
| 6 | 顺序依赖类：`test_events::test_eventbus_wiring` / `test_market_overview_news::test_fetch_list_source_parsing` | **测试基建/用例缺陷**：QApplication 生命周期（C++ 单例被 GC）导致订阅链失效；全局 http 单例被永久改写 | session `qapp` fixture + `monkeypatch` |

> 结论：6 项 = **3 项真实产品缺陷**（已修并补回归测试）+ **2 项过期用例（文案/字段约定）** + **1 项顺序依赖（测试基建缺陷）**。修复后全部通过，无残留失败。
> 说明：第 6 项在分段拼接时会在不同分段各自暴露一次（`test_events` 与 `test_fetch_list_source_parsing`），根因同源，合并为一条。

---

## 二、e2e 修复清单

### 2.1 原生崩溃 `0xC0000409`（P0，产品/测试基建缺陷）

**现象**：单独运行 `tests/e2e/test_market_overview_news.py` 时进程直接 fail-fast 退出（`0xC0000409`，Windows `__fastfail`），无 Python traceback，pytest 无法汇总。

**根因**：Qt 的 `QApplication` 是 **C++ 侧单例**，Python 包装对象只是临时句柄。

- 多个用例函数内部写 `app = QApplication.instance() or QApplication([])`，该引用是**函数局部变量**；
- 函数返回后引用计数归零，Python GC 销毁包装对象，而 PyQt 的析构会连带销毁 C++ 的 `QApplication` 实例；
- 于是会话中途 `QApplication.instance()` 变成 `None`，后续任何用例构造 `QWidget`（`QWidget` 构造必须先有 QApplication）时 Qt 调用 `qFatal()` → 进程 fail-fast。

这也是「无法一次跑完、只能分段拼接」以及 `test_events.py` 顺序依赖失败（`LINKAGE_BUS` 等 QObject 的 C++ 对象随应用销毁而失效）的同一个根因。

**修复**：

| 文件 | 位置 | 改法 |
| --- | --- | --- |
| `tests/e2e/conftest.py` | [conftest.py](file:///d:/PythonProject/QuantVortex/tests/e2e/conftest.py#L31) | 新增 `session` 级 `autouse` fixture `qapp`：全会话只创建一次 `QApplication` 并由 fixture 强引用持有到会话结束；不在 fixture 内 `quit()`/析构 |
| `tests/e2e/test_market_overview_news.py` | [test_market_overview_news.py](file:///d:/PythonProject/QuantVortex/tests/e2e/test_market_overview_news.py) `test_market_overview_layout_and_render` | 函数开头显式 `app = QApplication.instance() or QApplication([])`，兼容单独调试该函数的场景 |

**验证**：修复前单跑该文件必崩；修复后单跑通过，且全量 e2e 进程能跑到 100%（见第一节结果）。

### 2.2 顺序依赖不稳定用例

| 用例 | 文件:行 | 定性 | 根因 | 修复 |
| --- | --- | --- | --- | --- |
| `test_events.py::test_eventbus_wiring` | 无改动 | 测试基建缺陷 | 根因同上：前序用例销毁 QApplication 后 `LINKAGE_BUS` 的 C++ 对象失效，`push_backtest_result` 抛 `RuntimeError` 打断订阅链 | 由 §2.1 的 session `qapp` fixture 解决 |
| `test_market_overview_news.py::test_fetch_list_source_parsing` | [test_market_overview_news.py](file:///d:/PythonProject/QuantVortex/tests/e2e/test_market_overview_news.py#L88) | 用例缺陷（污染全局） | 原实现直接改写全局 http 客户端单例（`data/http_client.py` 的 `_CLIENT`）的 `.get`，且**从不恢复**，污染后续所有依赖网络的用例 | 改为 `monkeypatch.setattr(nf, "_get_http_client", lambda: FakeClient())`，用例结束自动还原，且不受其它用例 `reset_client()` 影响 |

### 2.3 过期用例（文案 / 字段约定变动）

| 用例 | 文件:行 | 过期原因 | 改法 |
| --- | --- | --- | --- |
| `test_backtest_real_akshare.py::test_specs` | [test_backtest_real_akshare.py](file:///d:/PythonProject/QuantVortex/tests/e2e/test_backtest_real_akshare.py#L64-L65) | 合约规格表 key 已统一为大写品种代码（`rb.SHFE` → `RB`），小写仅由 `_norm` 兜底解析 | 断言改为 `assert "RB" in CONTRACT_SPECS` |
| `test_market_overview_tech_predict.py::test_market_overview_tech_expansion` | [test_market_overview_tech_predict.py](file:///d:/PythonProject/QuantVortex/tests/e2e/test_market_overview_tech_predict.py#L55-L56) | 技术面小节标题已改为「七、趋势强度与综合结论」，旧断言写死「综合技术结论」 | marker 改为「综合结论」 |

### 2.4 真实产品缺陷（保留失败 + 修复，非用例问题）

#### 缺陷 A：真实日线回测零成交（资金曲线恒平直）

- **文件**：[risk_manager.py](file:///d:/PythonProject/QuantVortex/futures_quant/risk/risk_manager.py#L107-L115)
- **现象**：`test_backtest_real_akshare.py::test_real_backtest` / `test_multi_symbol_real_backtest` 用真实 AKShare 日线跑回测，成交数恒为 0，资金曲线一条直线。
- **根因**：日线（周期 `D`/`W`）K 线时间戳约定为 `00:00:00`，本身不含日内时段信息；`RiskManager` 在 `non_trading_hours_block=True` 时对所有委托做交易时段校验，`00:00:00` 必然落在非交易时段 → **全部委托被判「非交易时段禁止下单」**，回测零成交。
- **影响面**：所有日线/周线级回测（含 GUI 简单回测页、回测中心）。属于口径级缺陷，影响结论可信度。
- **修复**：仅当 bar 带具体时钟（非 `00:00`）时才做时段校验；`00:00` 视为日线时间戳直接放行。日内周期行为不变。
- **回归**：[test_phase3_e2e_regressions.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_phase3_e2e_regressions.py#L47) `test_daily_bar_not_blocked_by_trading_hours`（00:00 通过 / 09:15 通过 / 12:00 被拦截）。

#### 缺陷 B：`DriftMonitor` 无数据时 `correlation=0.0` 语义错误

- **文件**：[drift.py](file:///d:/PythonProject/QuantVortex/futures_quant/ai/drift.py#L53)、[drift.py](file:///d:/PythonProject/QuantVortex/futures_quant/ai/drift.py#L130)
- **现象**：`test_drift.py` 期望 `no_data` 场景 `correlation is None`，实际返回 `0.0`。
- **根因**：「无数据」与「零相关」是不同语义；返回 `0.0` 会让上层把样本不足误判为「相关性确认为零」。
- **修复**：类型改为 `Optional[float]`，`no_data` 分支返回 `None`。
- **回归**：[test_phase3_e2e_regressions.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_phase3_e2e_regressions.py#L68) `test_drift_no_data_correlation_is_none`。

---

## 三、GUI 现状审计问题清单（按严重度）

审计维度：布局与信息层级、主流程操作断点、状态可见性、异常反馈、长任务阻塞、大数据量渲染。

### P0（主流程阻断 / 界面假死）

| # | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| P0-1 | 行情全景「刷新」「切周期」「切板块」在**主线程**串行抓取全市场行情并计算全景 | 原 `_on_period`/`_on_cat` 直接调 `_refresh_pano()`；`refresh_btn` 绑定 `_refresh_all` | 数据源慢时窗口无响应（假死），用户误以为崩溃 |
| P0-2 | 「选品种 → 看盘 → 预测」跨页上下文断裂：主窗口会调 `apply_context`，但预测页**未实现**该方法 | 行情全景双击品种行后，预测页仍需手动重选品种+周期 | 主流程每次多 2~3 次点击 |

### P1（关键体验缺陷）

| # | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| P1-1 | 数据来源/时效水印只在行情全景与 CTP 页存在；预测页、独立回测页缺失 | `predict_ops_page.py` 无来源展示；`simple_backtest_page.py` 无来源展示 | 用户无法判断结果基于真实/合成/陈旧数据，易误当实盘结论 |
| P1-2 | 回测结果 provenance 在服务层被丢弃 | `app/backtest_service.py` 返回 dict 未透传 `data_source/is_synthetic/is_stale/as_of` | 即使页面想显示也无数据可用 |
| P1-3 | 预测失败只 `print` 到 stdout，界面仅显示「失败」 | `predict_ops_page.py` 异常分支 | 用户不知道该改什么、下一步做什么 |
| P1-4 | 大表逐格 `setItem` 无批量更新 | `attribution_dialog.py` 分笔表、`backtest_page.py` 成交表 | 2000+ 行时分笔/成交表填充卡顿、闪烁 |

### P2（可接受，本次记录未改）

| # | 问题 | 说明 |
| --- | --- | --- |
| P2-1 | 预测页 `_base_refresh` 同步取 600 根 bar | 真实数据源首屏可能卡顿数百毫秒；改造成本涉及线程模型，先记录方案不动 |
| P2-2 | 独立回测页无「取消」按钮 | 只显示进度条，长回测无法中止 |
| P2-3 | 回测中心自动进化页无数据来源水印 | 同 P1-1 的推广未覆盖该页 |
| P2-4 | 主窗口状态栏无全局数据源汇总 | 需跨页聚合，改动面较大 |

---

## 四、GUI 改动明细（文件:行 → 痛点 → 改法 → 验证）

### 4.1 长任务不阻塞主线程（P0-1）

- **文件**：[market_overview_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L685)
- **痛点**：全景刷新/切周期/切板块在主线程抓全市场行情，数据源慢时窗口假死。
- **改法**：
  - 新增 `_refresh_all_async()`：用 Worker 线程执行 `mdm.compute_panorama(period)`，完成后回主线程 `_put_panorama()` 再 `_refresh_all()`；
  - `_pano_loading` / `_pano_pending` 做防重入与「加载期间用户又切了周期/板块 → 完成后补刷最后一次选择」，避免并发重复计算；
  - 失败时把来源水印置为 `unknown / stale` 并提示「全景刷新失败：<原因>」，而不是静默保留旧数据；
  - 刷新按钮（[L175](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L175)）、`_on_period`（[L641](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L641)）、`_on_cat`（[L650](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L650)）、`_on_period_changed`（[L2210](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L2210)）统一改走异步入口。
- **验证**：offscreen 冒烟构建主窗口 7/7 页 OK；e2e `test_market_overview_news.py` / `test_market_overview_tech_predict.py` 通过。

### 4.2 主流程少点击：双击品种直达预测（P0-2）

- **文件**：[market_overview_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/market_overview_page.py#L2179)、[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L902)
- **痛点**：双击全市场速览表某行后，只切换了本页合约，切到预测页还要再选一次品种和周期。
- **改法**：
  - `_on_pick` 双击后 `navigate_requested.emit("predict", {"symbol": code, "period": cur_period})`；
  - 预测页实现 `apply_context(context)`：读取 `symbol`/`period`，定位 `sym_cb`/`per_cb`，并在状态栏提示「已从行情全景带入：XXX · 周期，点击「开始预测」」；上下文失败只记 warning，不影响页面切换。
- **验证**：offscreen 冒烟中主窗口页面跳转正常；`apply_context` 未抛异常（异常被捕获并降级）。

### 4.3 状态可见：数据来源水印推广（P1-1 / P1-2）

- **新增组件**：[widgets.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/widgets.py#L327) `ProvenanceBadge`（以及辅助函数 `get_provenance_obj`）
  - 统一渲染 `provenance_text(data_source, is_synthetic, is_stale, as_of, note)`；
  - 合成或陈旧数据用警示色，正常数据用次要色，避免「看起来一样」。
- **预测页**：[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L363-L364) 控制条挂载水印；[L932](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L932) `_base_refresh`、[L2039](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2039) 预测结果渲染时用 `df.attrs` 更新。
- **独立回测页**：[simple_backtest_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L160-L161) 挂载水印；[L415](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L415) fallback 返回补充 `data_source/is_synthetic/is_stale/as_of/data_note`；[L470](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L470) 结果渲染时更新。
- **服务层透传**：[backtest_service.py](file:///d:/PythonProject/QuantVortex/futures_quant/app/backtest_service.py#L93-L99) 返回 dict 增加上述 5 个字段（此前被丢弃，页面无数据可显示）。
- **痛点**：用户无法分辨结果基于真实行情还是合成/陈旧数据，存在把演示数据当实盘结论的风险。
- **验证**：offscreen 冒烟断言预测页与独立回测页 `prov_badge` 存在且可 `set_provenance`；e2e 相关页面用例通过。

### 4.4 错误提示可行动（P1-3）

- **文件**：[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L891) `_actionable_hint`
- **痛点**：预测失败只显示「失败」，用户不知道下一步做什么。
- **改法**：按异常类型翻译成可执行下一步（样本不足 → 去数据管理确认行情长度；超时 → 缩短训练轮数/序列长度；模型依赖 → 检查 AI 依赖或切换 NumPy 模型；默认 → 检查数据源与系统日志）。状态栏显示 `预测失败：<原因>｜下一步：<建议>` 并同时 toast（[L1604](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L1604)）。
- **验证**：offscreen 冒烟无异常；预测失败路径不吞异常（保留原始消息）。

### 4.5 大数据量表格性能（P1-4）

- **文件**：[attribution_dialog.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/attribution_dialog.py#L406-L440)、[backtest_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L1320-L1342)
- **痛点**：2000+ 行分笔/成交表逐格 `setItem` 触发逐次重绘与信号，填充卡顿、界面闪烁。
- **改法**：填充循环外包 `setUpdatesEnabled(False)` + `blockSignals(True)`，`pal()` 等主题查找提到循环外，`finally` 中恢复并 `viewport().update()` 一次性重绘。
- **验证**：e2e 回测与归因相关用例通过；表格行数与内容断言不变。

### 4.6 新增回归测试

- [test_phase3_e2e_regressions.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_phase3_e2e_regressions.py)：覆盖缺陷 A（日线时段校验）与缺陷 B（drift 无数据语义）。

---

## 五、第二批：预测结论的诚实呈现 + 遗留补齐

> 约束：**未修改 `futures_quant/ai/` 任何文件**（另有会话在改评估逻辑），只调用既有
> `ai.evaluation.probability_hit_rate` 与 `Predictor.evaluate` 的既有字段；未改指标与回测内核。
> 回测内核原本就有 `should_abort` 协作式中断参数（M4-06），本批只在服务层透传。

### 5.1 预测页：结果区拆成三层（点预测 / 概率区间 / 置信水平）

- **文件**：[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L393-L411)（控件）、[L2300-L2366](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2300-L2366)（覆盖率/样本外统计）、[L2368-L2436](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2368-L2436)（三层刷新）、[L2210-L2211](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2210-L2211)（预测完成回调）
- **痛点**：原结果区把「目标价、涨跌概率、置信度」混在散点指标里，用户无法区分
  什么是点估计、什么是区间、什么是置信水平；也无法判断这些数字是否可信。
- **改法**：在结果 chips 下方新增固定三层文本（一行一层，主题色不变）：
  - `① 点预测：目标价 X（±Y%），方向「上涨/下跌」概率 Z%，预期收益 E%（h 根K线）`
  - `② 概率区间：[下界, 上界]（区间宽度 ±w%），名义覆盖 ≈68%（±1σ），历史实际覆盖率 R%`
  - `③ 置信水平：校准置信度 C%（校准区间过宽时明示降低信任度）；已结算样本外 n=…：命中率 H% vs 随机基准率 B%，95% CI [lo, hi] → 显著/无显著`
- **区间实际覆盖率口径**（[`_band_coverage`](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2300)）：
  用当前模型残差 `resid_std` 生成 ±σ√h 的累计对数收益带，对最近 ≤240 个 h 步窗口做历史回测，
  覆盖比例即实测覆盖率；**有效窗口 <30 时返回 `None`，界面显示「样本不足」，不编造数字**。
- **验证**：offscreen 冒烟注入合成预测结果后断言三行均存在，且区间行含「历史实际覆盖率」；
  回归测试 `test_band_coverage_helper_uses_residual_sigma`（σ 非法/窗口不足 → None）。

### 5.2 统计不显著时的醒目告警（措辞明确，不使用模棱两可表述）

- **文件**：[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2437-L2480) `_update_sig_banner`
- **痛点**：模型可能只是「看起来能猜」，原界面没有任何统计检验结论，用户容易把 51% 命中率
  当成有效优势。
- **触发条件**：`significant=False` **或** `hit_rate <= base_rate`（`significant` 来自既有
  `probability_hit_rate`，规则为 Wilson 95% CI 下界 > 基准率）。
- **实际文案**：
  - 不显著 / 不优于基准（琥珀色底+边框）：
    **「⚠ 当前模型无统计显著优势，仅作参考」**，同行附
    `（样本外命中率 48.0% ≤ 随机基准率 52.0%，95% CI [39.0%, 57.0%]，n=120）`。
  - 显著优于基准（绿色底+边框）：
    **「✔ 样本外检验通过：命中率显著高于随机基准」**，附命中率、基准率、CI 下界。
  - 样本不足（灰色）：
    **「样本不足（已结算 n=0），暂不做统计显著性判定；当前模型结果仅作参考。」**
- **验证**：offscreen 冒烟注入 `significant=False` 的样本外统计，断言告警条包含
  「无统计显著优势」原文。

### 5.3 历史验证区：样本外命中率 vs 随机基准率 + 95% CI

- **文件**：[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L1860)（Walk-Forward 结果行）、[L2745](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L2745)（预测解读「样本外检验」段）
- **痛点**：验证区原来只给「方向准确率 x%」，没有随机基准率、没有置信区间，用户无法判断
  x% 是「比抛硬币好」还是「在噪声范围内」。
- **改法**：
  - Walk-Forward 结果改为
    `✅ 真·滚动：5 折 · 样本外命中率 52.1% vs 随机基准率 50.0%，95% CI [47.9%, 56.3%] → 无统计显著优势，仅作参考 · MAE …`
    （读既有 `direction_base_rate / direction_acc_ci_low / direction_acc_ci_high / direction_significant`，
    不新增字段）；不显著时整行转琥珀色。
  - 预测解读「历史预测回测」下新增一行「样本外检验（已结算 n=…）：命中率 H% vs 随机基准率 B%，
    95% CI [lo, hi] → 显著优于随机基准 / 无统计显著优势，仅作参考」。
- **验证**：offscreen 冒烟通过；页面 e2e `test_predictor_model` 相关用例通过。

### 5.4 固定免责声明位

- **文件**：[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L780)
- **改法**：页面底部固定一行浅色文本：`本页预测、回测与验证结果仅供研究参考，不构成投资建议。`
  不新增卡片、不改信息架构。
- **验证**：冒烟断言 `disclaimer.text()` 以「本页预测」开头。

### 5.5 主窗口状态栏：全局数据源 / 时效汇总

- **文件**：[main_window.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L1342)
- **痛点**：状态栏原来只显示「数据源：新浪实盘日线」，看不到**当前品种**的数据时间与是否陈旧，
  与页面内的来源水印割裂。
- **改法**：新增 `_update_data_prov()`：从当前页取 `cur_symbol / cur_period`，读取 `mdm.get_bars`
  的来源元数据，显示
  `数据源：新浪日线 · 命中磁盘缓存 · 2026-11-03 00:00:00｜当前品种 RB.SHFE · D`；
  合成/陈旧数据用琥珀色并加 tooltip 提示。仅在页面切换与品种/周期变更时触发，**不新增网络请求**
  （`get_bars` 走内存缓存）。
- **验证**：冒烟输出
  `STATUS_BAR_OK 数据源：新浪日线 · 命中磁盘缓存 · 2026-11-03 00:00:00｜当前品种 RB.SHFE · D`。

### 5.6 回测中心「策略自进化」页来源水印

- **文件**：[backtest_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L1582)（挂载）、[L2793](file:///d:/PythonProject/QuantVortex/futures_quant/ui/backtest_page.py#L2793)（刷新）
- **痛点**：自进化默认可能跑在合成行情的 feed 上，却没有任何来源提示，用户容易把进化结果
  当作真实行情结论。
- **改法**：在进化控制条末端挂 `ProvenanceBadge`；每代切换品种时调用 `_update_evo_prov()`，
  用 `mdm.get_bars(sym, period, 120)` 的来源元数据刷新；取不到行情时明确标注
  「合成行情（模拟）· 非真实数据」，不隐去来源。
- **验证**：冒烟输出 `EVO_BADGE 数据来源：新浪日线 · 命中磁盘缓存 · 2026-11-03 00:00:00`。

### 5.7 独立回测页：运行中可取消（真取消，不是隐藏）

- **文件**：[simple_backtest_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L217)（按钮）、[L291](file:///d:/PythonProject/QuantVortex/futures_quant/ui/simple_backtest_page.py#L291)（取消逻辑）、[backtest_service.py](file:///d:/PythonProject/QuantVortex/futures_quant/app/backtest_service.py#L55-L82)（透传）
- **可行性结论**：**线程模型允许**。回测内核 `Backtester.run(..., should_abort=...)` 已有协作式
  中断检查点（M4-06），本批**未改内核**，只在 `BacktestService.run_backtest()` 增加可选参数
  `should_abort=None` 并原样透传（默认 None 时行为完全不变）。
- **改法**：新增「⏹ 取消」按钮（空闲禁用、运行中启用）；点击调 `worker.requestInterruption()`，
  Worker 以 `worker.isInterruptionRequested` 作为 `should_abort` 传给内核；中断后走
  `on_interrupted` 回调恢复按钮并提示「回测已取消（未生成结果）」，不渲染半截结果。
- **验证**：冒烟断言按钮存在、空闲禁用、运行中运行按钮禁用；回归测试
  `test_backtest_service_accepts_should_abort`。

### 5.8 回归测试与 offscreen 冒烟

- 新增回归（[test_phase3_e2e_regressions.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_phase3_e2e_regressions.py#L79-L133)）：
  - `test_band_coverage_helper_uses_residual_sigma`
  - `test_oos_stats_calls_existing_hit_rate_api`
  - `test_backtest_service_accepts_should_abort`
- 结果：`5 passed`（含第一批 2 项）。
- offscreen 冒烟（临时库 + `QUANTVORTEX_NO_PERSIST=1`）：
  - `PAGES_OK 7 / 7`（主窗口 + 7 页全部构建成功）
  - `SIG_BANNER_OK ... 当前模型无统计显著优势，仅作参考`
  - `LAYERS_OK ... 历史实际覆盖率 79.7%`
  - `STATUS_BAR_OK 数据源：…｜当前品种 RB.SHFE · D`
  - `CANCEL_BTN_OK ⏹ 取消`、`EVO_BADGE 数据来源：新浪日线…`
  - `SMOKE_DONE`

### 5.9 遗留 P2-1：预测页首屏 600 bar 同步取数（本轮只给方案，不动线程模型）

**现状**：[predict_ops_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L962) `_base_refresh()` 在主线程串行执行
`mdm.get_bars(sym, per, 600)` + `cached_add_indicators()` + 图表渲染；调用点：页面构建
（[L786](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L786)）与品种/周期切换（[L876](file:///d:/PythonProject/QuantVortex/futures_quant/ui/predict_ops_page.py#L876)）。
真实数据源冷启动时，主线程会阻塞数百毫秒到数秒（网络 + 指标计算 + 图表重建）。

**方案（建议分两小步，避免一次性重构线程模型）**：

1. **只把取数与指标计算搬到 Worker**（图表更新仍回主线程）：
   - 新增 `_base_loading / _base_pending / _base_seq` 状态（照搬行情全景 `_refresh_all_async` 的模式）；
   - `_base_refresh()` 改为提交 Worker：任务内只做 `df = mdm.get_bars(...)`、`ind = cached_add_indicators(...)`，
     把 `(seq, sym, per, df, ind)` 回传；
   - 主线程 `_on_base_ready`：若 `seq != self._base_seq`（用户已切品种/周期）则直接丢弃；
     否则执行现有 `chart.set_data / set_forecast / _render_indicators`，并更新 `prov_badge`；
   - 加载期间状态栏显示「K线加载中…」，图表保留上一帧或空态，不阻塞点击。
2. **确认线程安全后再推广**：
   - `mdm.get_bars` 内部会访问 feed 缓存与 `last_provenance`，需确认单写者/加锁；
     若不确定，第一步只异步化 `cached_add_indicators`（纯计算），`get_bars` 暂留主线程。
   - `cached_add_indicators` 的 LRU 缓存需确认线程安全；必要时在 Worker 内改用无缓存版本。

**影响面**：`_base_refresh` 的两个调用点、`prov_badge` 更新时机、`chart` 空态显示、
`_render_indicators` 依赖 `_last_ind` 的时序；不影响预测主流程（`_run_prediction` 已是 Worker）。
**风险**：低—中。渲染仍在主线程，最坏情况只是首屏晚 1 帧出现；主要风险是行情层并发读取。
**本轮未实施**，仅记录方案。

### 5.10 接口需求记录（本轮未实施，不擅自改 `ai/`）

为把「区间实际覆盖率」从**残差 σ 近似**升级为**真实结算覆盖率**，需要（任选其一，需与 ai/ 会话协同）：

- 存储层：预测记录落库时保存 `upper / lower`（或 `sigma` 与 `horizon`）；
- 结算时：用实际收盘价判断是否落入区间，累计「命中区间数 / 已结算数」；
- 评估 API（`ai/evaluation.py`）：新增/扩展一个返回 `interval_coverage` 的函数（本轮不新增，避免与
  另一会话冲突）。

当前实现只依赖既有 `resid_std` 做历史窗口近似，并在界面明确标注口径，不冒充真实结算覆盖率。

---

## 六、剩余项

| 项 | 原因 | 建议后续 |
| --- | --- | --- |
| 预测页首屏 600 bar 同步取数 | 涉及行情层线程安全确认，本轮只给方案（见 5.9） | 先异步化指标计算，再逐步迁移取数 |
| 真实区间覆盖率 | 需存储层保存 upper/lower 或结算比对（见 5.10） | 与 ai/ 会话协同新增接口后再接 UI |
| 样本外统计按品种/配置过滤 | 现有 `query_closed_for_calibration` 无品种字段，当前展示为全库样本并已标注 | 存储层加 symbol/config 过滤参数 |
| 回测中心其它子页来源水印 | 仅补齐「策略自进化」页，其余页避免扩大改动面 | 复用 `ProvenanceBadge` |

## 七、约束遵守情况

- 未 commit、未改版本号、未删文件；
- **未修改 `futures_quant/ai/` 任何文件**，只调用既有 API（`probability_hit_rate`、`Predictor.evaluate`
  既有返回字段）；未改指标与回测内核（内核 `should_abort` 为既有能力，仅在服务层透传）；
- 未触碰生产数据库；新增回归测试为纯逻辑测试；GUI offscreen 冒烟使用临时库并设置
  `QUANTVORTEX_NO_PERSIST=1`；
  （注：`tests/e2e` 中既有用例历史上会在 `data/` 下建 `*_test.db` 并在用例结束时自行删除，属既有测试设计，本次未改动其数据路径。）
- 第一批中唯一涉及口径的改动是缺陷 A 的日线时段判定（修复既有错误口径，有回归测试保护）。

---

## 八、第三批：统一验收入口 `scripts/acceptance.py`

> 目的：把散落的 unit / e2e / 回测锚点 / 性能门槛 / GUI 冒烟合成一条命令，输出**可判定**结论，
> 作为后续「全功能回归、无退化」验收的基础设施。未改 `futures_quant/ai/`、未改指标与回测内核，
> 未引入新第三方包，未 commit / 改版本号 / 删文件 / 动生产数据。

### 8.1 一条命令（仓库根目录直接可跑）

```powershell
python scripts/acceptance.py              # 全量：unit + e2e + 锚点 + 性能 + GUI 冒烟（约 20~25 分钟）
python scripts/acceptance.py --quick      # 快速：unit + 锚点 + GUI 冒烟（约 12 分钟，跳过 e2e/性能）
python scripts/acceptance.py --e2e-skip   # 只跳过 e2e
python scripts/acceptance.py --perf-skip  # 只跳过性能门槛
```

- **退出码**：全部 PASS 或 SKIP → `0`；任一项 FAIL → `1`（可直接接入 CI / 批处理判定）。
- **报告**：`outputs/acceptance_report.md`——结论总览表 + 失败/跳过详情 + 判定口径 + 复现命令。
- **临时产物**：`outputs/.acceptance_*.json|xml`（锚点、性能分节、pytest junit），
  不覆盖既有 `outputs/.perf_*.json`，也不写生产库。

### 8.2 五项验收：数据来源与判定

| # | 验收项 | 执行方式 | 判定依据 | SKIP 条件 |
| --- | --- | --- | --- | --- |
| 1 | 单元测试 | `pytest tests/unit -q --tb=line -rf --junitxml=outputs/.acceptance_junit_unit.xml` | 0 失败 0 错误（不看用例总数，避免新增用例被误判退化） | pytest 未安装 |
| 2 | e2e 测试 | 同上，目标 `tests/e2e` | 同 #1（基线 221 项全通过） | `--quick` / `--e2e-skip` |
| 3 | 回测锚点等价 | `perf_probe.py --section anchor --child --json-out outputs/.acceptance_anchor.json --runs 1` | `verdict.all_ok == true`，且与 §8.2 基线逐项比对 | 本地无离线日线缓存 |
| 4 | 性能门槛 | `perf_probe.py --section backtest / indicators --child --runs 1` | 批量 ≤24.5s、rb 单次 ≤500ms、add_indicators ≤180ms、SAR ≤120ms | `--quick` / `--perf-skip`；分节跑不起来 |
| 5 | GUI 冒烟 | 子进程 `QT_QPA_PLATFORM=offscreen` 构建 `MainWindow` 并逐页 `_show_page` | `PAGES_OK 7 / 7` | PyQt6 未安装 |

关键实现位置：[acceptance.py](file:///d:/PythonProject/QuantVortex/scripts/acceptance.py#L183)（pytest 判定）、
[L234](file:///d:/PythonProject/QuantVortex/scripts/acceptance.py#L234)（锚点比对）、
[L339](file:///d:/PythonProject/QuantVortex/scripts/acceptance.py#L339)（性能门槛）、
[L454](file:///d:/PythonProject/QuantVortex/scripts/acceptance.py#L454)（GUI 冒烟）、
[L498](file:///d:/PythonProject/QuantVortex/scripts/acceptance.py#L498)（报告生成）。

### 8.3 判定细节（几个必须说清的坑）

1. **pytest 计数不能只看控制台尾行**：本仓库有用例会重定向 stdout，实测 821 项跑完后
   `1 failed, 820 passed ... in 802.70s` 这行会缺失（第一版只解析尾行 → 误报「未能正常收集」）。
   现改为**优先解析 `--junitxml`**（`_parse_junit`），控制台解析仅兜底；失败用例名也从 junit 里取，
   形如 `tests/unit/x.py::test_y — <断言消息>`。
2. **锚点容差**（数值为浮点舍入后落盘）：成交笔数**精确**比对；`total_return / max_drawdown`
   容差 `0.02pp`（0.0002）；`sharpe` 容差 `0.005`。超差时报告写明「哪一窗口、哪个字段、
   实测值 vs 基线、差多少」，例如 `rb.SHFE anchor_window num_fills 224 ≠ 基线 225（差 -1 笔）`。
3. **性能分节不污染历史基线**：用 `--child --json-out outputs/.acceptance_perf_*.json` 现跑，
   不写 `outputs/.perf_backtest.json` 等既有文件；现跑失败才回退读取既有 JSON，并在详情里标注「缓存值」。
   `unit` 超时设为 1800s（实测约 708~803s，M3 训练类用例占大头），避免误杀。
4. **GUI 冒烟放子进程**：Qt 在父进程内构建后难以彻底回收（历史上有 `0xC0000409` 先例），
   子进程崩溃只判该项 FAIL，不影响其余验收项；`QUANTVORTEX_NO_PERSIST=1` + 预置 data 目录缓存，
   不写真实会话文件。

### 8.4 `--quick` 实跑样例（本次真实输出）

```text
==============================================================================
QuantVortex 统一验收 · --quick（跳过 e2e 与性能）
==============================================================================
[1/5] 单元测试       PASS 通过 821 / 失败 0 / 错误 0 / 跳过 0 · 707.66s
[2/5] e2e 测试     SKIP 已跳过
        由 --quick / --e2e-skip 跳过（基线 221 项通过）
[3/5] 回测锚点等价     PASS rb 全窗口 231 笔 · rb 锚点 225 笔 · i.DCE 235 笔 · all_ok=True
[4/5] 性能门槛       SKIP 已跳过
        由 --quick / --perf-skip 跳过
[5/5] GUI 冒烟     PASS PAGES_OK 7 / 7 · 8.93s
------------------------------------------------------------------------------
结论：PASS · 失败 0 / 跳过 2 · 总耗时 732.1s
报告：D:\PythonProject\QuantVortex\outputs\acceptance_report.md
退出码：0
```

性能门槛路径另行单独验证（不走 `--quick`，直接调用判定函数）：

```text
性能门槛 PASS
  43 品种批量回测 3874.7ms ≤ 24.5s
  rb.SHFE 单次回测 82.6ms ≤ 500ms
  add_indicators(5000bar) 61.1ms ≤ 180ms
  SAR 单指标 3.8ms ≤ 120ms
```

> 注：当前机器上批量回测/指标耗时显著低于 `perf_baseline.md` 基线（基线环境有其它会话 Heavy 负载），
> 阈值判定只看「是否超过绝对上限」，不要求与基线逐值一致，避免把机器差异误判为退化。

### 8.5 哪些项会因环境缺失而 SKIP（而不是 FAIL）

| 场景 | 结果 | 报告里的说明 |
| --- | --- | --- |
| 未安装 pytest | unit / e2e → SKIP | 「环境缺失 pytest」 |
| 未安装 PyQt6 | GUI 冒烟 → SKIP | 「环境缺少 PyQt6，无法执行 offscreen 冒烟」 |
| 无离线日线缓存（`data/akshare_cache` 等） | 锚点 / 性能 → SKIP | 「本地缺少离线日线缓存，分节无法运行；未用历史值判定，避免假绿」 |
| 主动跳过 | 对应项 → SKIP | 「由 --quick / --e2e-skip / --perf-skip 跳过」 |

> 口径：**SKIP 不等于通过**——控制台与报告里明确列出跳过项及原因；全量验收（不带任何 skip）时
> 只允许 0 SKIP。

### 8.6 本轮顺带修的过期用例（unit 首跑唯一失败项）

- 用例：[test_m4_11_window_nav.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_m4_11_window_nav.py#L119)
  原 `test_restore_geometry_respects_maximized_false`
- 现象：源码级断言要求 `main_window.py` 中存在 `bool(w.get("maximized", True))`。
- 定性：**用例过期**。当前产品口径是「启动默认最大化」（
  [main_window.py:951-956](file:///d:/PythonProject/QuantVortex/futures_quant/ui/main_window.py#L951-L956) `self._want_max = True`，
  注释写明用户明确要求默认最大化），会话里的 `maximized` 仅作保存参考。
- 改法：用例改名为 `test_restore_geometry_defaults_to_maximized`，断言新契约
  （`_want_max = True` 存在、不再按会话值分支、且函数体内无 `or True` 历史缺陷），
  并修正原先脆弱的切片（旧写法命中的是调用点而非函数体）。
- 验证：该文件单独跑通过；全量 unit 由 `820 passed / 1 failed` 变为 `821 passed / 0 failed`。

