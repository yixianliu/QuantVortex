# Changelog

本项目遵循 [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/)。

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
