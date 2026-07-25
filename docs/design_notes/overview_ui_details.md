# UI 细节打磨 round · 2 交付概览

## 已完成内容

针对「继续打磨界面 UI 细节」的需求，对 QuantVortex 期货量化系统 PyQt6 界面做新一轮细节打磨与视觉一致性修复。

### 1. 修复风控页 Badge 垂直拉伸
- 文件：`futures_quant/ui/widgets.py`
- 改动：`Badge` 组件增加 `setFixedHeight(24)` + `AlignCenter`，确保在水平布局中保持胶囊形状，不被纵向撑开。
- 验证：截图 `ui_risk_dark.png` 中「正常」徽章为正常大小的绿色圆角标签，不再出现纵向绿色长条。

### 2. 表格视觉净化
- 文件：`futures_quant/ui/widgets.py`、`futures_quant/ui/main_window.py`
- 改动：
  - 新增 `prepare_table()` 工具：隐藏左侧行号表头、统一默认行高 28px、应用隔行底色。
  - 主窗口所有表格改用 `W.prepare_table()` 刷新。
  - QSS 增加 `QTableWidget::item:hover` 行悬停反馈（深色 `#232838`，浅色 `#eff6ff`）。
- 验证：行情页/持仓页截图中表格左侧无行号列，更干净。

### 3. 策略页参数面板扁平化
- 文件：`futures_quant/ui/main_window.py`
- 改动：将原来嵌套的「参数」`QGroupBox` 改为透明 `QWidget` + `QFormLayout`，置于「策略参数」卡片内，减少一层边框叠加。
- 验证：`ui_strategy_dark.png` 中参数表单直接显示，无双重边框。

### 4. K 线图细节优化
- 文件：`futures_quant/ui/chart_widget.py`
- 改动：
  - 最新价虚线颜色随当前 bar 涨跌切换（红涨绿跌）。
  - 移除十字光标悬浮框中重复设置画笔颜色的冗余代码。
  - 成交量透明度由 180 降至 150，降低视觉干扰。
- 验证：K 线截图中最新价虚线颜色与最后 bar 方向一致；成交量副图更柔和。

### 5. 全局 QSS 收尾
- 文件：`futures_quant/ui/main_window.py`
- 改动：
  - 表头 `font-weight: bold`。
  - `QStatusBar` 顶部增加 1px 分隔线。
  - `QComboBox::down-arrow` 使用 CSS 三角形指示器，深/浅主题分别配色。
- 验证：截图中下拉框箭头可见，状态栏与主内容区分隔更清晰。

## 验证结果

- `python -m py_compile` 通过（`widgets.py`、`main_window.py`、`chart_widget.py`、`capture_ui.py`）。
- `QT_QPA_PLATFORM=offscreen python examples/capture_ui.py` 成功生成 7 张深/浅主题截图。
- `QT_QPA_PLATFORM=offscreen python examples/smoke_ai_kline.py` 全部通过（K 线、AI 分析、39 品种、板块筛选、导航图标、双击切换等）。

## 交付文件

- 代码：`futures_quant/ui/main_window.py`、`futures_quant/ui/widgets.py`、`futures_quant/ui/chart_widget.py`
- 文档：`docs/ui_design.md`（新增「近期 UI 打磨要点」章节）
- 截图：`examples/output/ui_*.png`

## 备注

沙箱环境缺少中文字体，截图中中文显示为 tofu；在真实 Windows 环境（Microsoft YaHei）下显示正常。
