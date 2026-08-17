# 本轮交付：GUI 最大化 / 自适应布局 / 视觉风格重构

## 完成内容

1. **启动默认最大化**
   - `main()` 改为 `win.showMaximized()`。
   - `MainWindow` 增加最小尺寸约束 `1100×680`，避免窗口过小导致组件挤压/遮挡。

2. **新增顶部菜单栏**
   - `视图`：切换主题（Ctrl+T）
   - `数据`：重连数据源
   - `帮助`：关于
   - QSS 统一样式，与整体配色一致。

3. **工具栏卡片化 + 控制条分组**
   - 新增 `widgets.ToolBar`（`#toolbar`）圆角卡片容器。
   - 行情全景 / 指标分析 / KP预测 / 市场全景 / 回测验证 / 日志预警 六个页面的控制条统一包进工具栏卡片。

4. **指标卡等比缩放**
   - `MarketPage`、`PredictPage` 的指标卡由 `addStretch(1)` 改为 `addWidget(chip, 1)`，随窗口宽度等分缩放。

5. **QSS 视觉系统重构**
   - 统一字号层级（正文 13px、标题 18px、副标题 12px）。
   - 统一圆角层级（卡片/按钮/输入 8–10px）。
   - 按钮 hover/pressed/disabled/focus 四态分明。
   - 输入控件 focus 高光环 + hover 边框反馈。
   - 表格、标签页、滚动条、复选框、菜单、状态栏、Tooltip 风格一致。
   - 深色/浅色两套 QSS 同步。

6. **主题切换传播修复**
   - `BasePage.set_theme()` 递归向子组件下发主题，修复 `MetricChip / Badge / ConfidenceBar` 等带内联样式的组件在切主题时不更新的问题。

7. **PageHeader 层级细化**
   - 标题 18px / 副标题 12px；底部增加 1px 分隔线。

8. **图表 NaN 守卫**
   - `PriceChart._y_range()` 过滤 NaN，避免 RSI 等含 warmup 空值的副图 Y 轴刻度显示成 `nan`。

## 验证结果

- `py_compile` 全部通过；`python main.py --test` → 核心模块导入 OK。
- `examples/capture_ui.py` 重新生成 12 张六页深/浅截图，真实数据 + KP预测渲染正常。
- 视觉检查：菜单栏、工具栏卡片、等比指标卡、K 线图、预测置信带、状态栏均正常；RSI 副图刻度已修复。

## 已知限制

- 免费数据源仅支持日线/周线真实行情；日内周期在 `sina` 模式下回退合成并明确标注。
- 截图偶发 `QPainterPath::arcTo: NaN` 警告，不影响渲染与数据。
