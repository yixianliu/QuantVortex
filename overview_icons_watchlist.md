# UI 图标重设计 + 自选品种扩充 + 面板再打磨 — 交付概览

## 完成内容

1. **全新 SVG 矢量图标库** `futures_quant/ui/icons.py`
   - 23 个图标，覆盖 7 个导航项、主要操作按钮、工具图标。
   - 基于 `PyQt6.QtSvg` 2x 超采样渲染，主题感知（深/浅），高分屏清晰。
   - 调用接口：`icon(name, theme, color_override, size)`，带缓存。

2. **导航与按钮图标升级**
   - 左侧导航改用统一 SVG 图标，选中态白色、未选中态灰色，hover 背景反馈。
   - 主题按钮随深/浅显示太阳/月亮图标。
   - 启动/暂停/清仓/手动下单/锁仓/运行回测/运行 AI 分析按钮均带图标。

3. **自选品种从 1 行扩充到 39 品种、6 大板块**
   - 黑色系 8 / 有色金属 6 / 贵金属 2 / 能源化工 10 / 农产品 10 / 金融 3。
   - 行情页「自选合约」新增板块筛选下拉；表格展示合约/名称/最新价/涨跌幅/持仓量，涨跌红绿配色。
   - 双击任意品种行可切换主图行情（仿真盘引擎重启）。

4. **面板细节打磨**
   - QSS 微调：表格加边框/圆角、导航按钮统一对齐、hover/pressed 更明显。
   - 各页面卡片化、PageHeader、指标卡保持一致；深浅主题统一刷新无残留。

## 验证结果

- `examples/smoke_ai_kline.py`：19 项 OK（新增：39 品种、板块筛选、导航图标、双击切换主图）。
- `examples/capture_ui.py`：生成 7 张深/浅主题截图，布局与图标均正常。
- `python -m compileall -q futures_quant api examples`：通过。
- `examples/predictor_demo.py`：通过。

## 主要新增/修改文件

| 文件 | 说明 |
|------|------|
| `futures_quant/ui/icons.py` | 新增：SVG 矢量图标库 |
| `futures_quant/ui/main_window.py` | 图标接入、自选品种 WATCHLIST、板块筛选、双击切换主图、QSS 打磨 |
| `examples/smoke_ai_kline.py` | 补充自选/图标/切换主图校验 |
| `examples/capture_ui.py` | 补充 strategy_dark 截图 |
| `docs/ui_design.md` | 更新图标库、导航、自选品种、截图列表说明 |
| `README.md` | 更新结构树与入口描述 |

## 已知边界

- 沙箱无中文字体，截图中文显示为 tofu；真实 Windows 环境使用 Microsoft YaHei 正常显示，图标已清晰呈现。
- 双击切换主图会重置仿真引擎与持仓，符合仿真盘「验证逻辑」定位，非实盘状态迁移。
