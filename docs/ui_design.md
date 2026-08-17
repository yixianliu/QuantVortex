# PyQt6 界面视觉设计说明（期货智能分析预测系统）

本文档说明 `futures_quant/ui/main_window.py`、`futures_quant/ui/widgets.py`、`futures_quant/ui/icons.py` 与 `futures_quant/ui/pages.py`、`futures_quant/ui/chart_widget.py` 的视觉与交互设计，便于后续维护、扩展与主题二次开发。

> **本系统为分析/预测工具，不含持仓、下单、风控平仓等交易界面。** 页面为：行情全景 / 指标分析 / KP预测 / 市场全景 / 回测验证 / 日志预警。

---

## 一、整体布局

- **顶部菜单栏 + 左侧导航 + 右侧堆叠页面**：QMenuBar 提供 视图（切换主题 Ctrl+T）/ 数据（重连数据源）/ 帮助（关于）；左侧 168px 导航面板；右侧 `QStackedWidget` 切换 6 个业务页面。主窗口默认最大化，并设最小尺寸 `1100×680`。
- **数据源（实盘接入）**：`MarketDataManager` 按 `config/settings.json` 的 `data.source` 选择 `SinaFeed`（**新浪公开接口，真实日线，免密钥**）/ `SyntheticFeed`（合成）/ `CTPFeed`（柜台）。默认 `sina`，外网不可达时自动回退合成，状态栏实时显示当前源。日线/周线为真实数据，日内周期回退合成并明确标注。
- **全局字体**：显式加载 `C:/Windows/Fonts/simhei.ttf`（黑体）并注册为应用字体，QSS `font-family` 依次为 `'SimHei','Noto Sans SC','Microsoft YaHei'`；offscreen 截图环境下也通过 `docs/examples/capture_ui.py` 的 `setup_fonts()` 显式注册，避免中文 tofu。
- **圆角卡片化**：统一圆角 10px、卡片底色，与 `QSS` 保持一致。
- **页头 `PageHeader`**：每个页面顶部固定高度标题区，左侧 4px 强调色竖条 + 大标题 + 副标题，建立清晰层级。

---

## 二、主题系统

支持 **深色（dark）** 与 **浅色（light）** 两套配色，通过底部状态栏「切换浅色/深色」按钮（`_toggle_theme`）实时切换。

| 语义 | 深色 `#` | 浅色 `#` | 用途 |
|------|----------|----------|------|
| 背景 | `0f1116` | `f5f7fa` | 窗口主背景 |
| 面板 | `11141c` | `eef2f7` | 导航、表头 |
| 卡片 | `161a24` | `ffffff` | GroupBox、MetricChip |
| 边框 | `2a2e3a` | `d1d5db` | 卡片边框、输入框 |
| 主文字 | `e6e6e6` | `1f2937` | 正文、标题 |
| 次要文字 | `8b93a7` | `6b7280` | 副标题、表头 |
| 强调色 | `2563eb` | `2563eb` | 按钮、选中态、强调条 |
| 辅助蓝 | `3b82f6` | `3b82f6` | 图表、高亮 |
| 涨/红 | `ef4444` | `dc2626` | 上涨/看多（中国期货惯例） |
| 跌/绿 | `22c55e` | `16a34a` | 下跌/看空（中国期货惯例） |

主题切换时，QSS 全局重载，图表、卡片、徽章、表格、指标卡、**导航/按钮图标**统一刷新（`main_window._apply_theme` 遍历页面与各图表 `set_theme`），避免「旧主题残留」。

---

## 三、可复用美化组件（`widgets.py`）

| 组件 | 用途 | 关键接口 |
|------|------|----------|
| `PageHeader` | 页面标题区 | `set_theme(theme)` |
| `Badge` | 圆角标签（方向、状态） | `set_text(str)`, `set_color(bg, fg)`, `set_theme(theme)` |
| `MetricChip` | 指标卡（标题+大数值） | `set_value(str, color)`, `set_theme(theme)` |
| `ConfidenceBar` | 水平置信度条 | `set_pct(0..1)`, `set_theme(theme)` |
| `make_dot_icon` | 生成彩色圆点图标（旧导航占位） | `make_dot_icon(color, size=10) -> QIcon` |
| `stripe_table` | 表格隔行底色 | `stripe_table(QTableWidget)` |
| `prepare_table` | 表格统一预处理：隐藏左侧行号、设置默认行高、应用隔行底色 | `prepare_table(QTableWidget)` |
| `color_pnl` | 表格盈亏列红绿配色 | `color_pnl(QTableWidgetItem, value)` |

此外 `futures_quant/ui/icons.py` 提供 **SVG 矢量图标集**（基于 `PyQt6.QtSvg`）：

| 图标 | 名称 | 用途 |
|------|------|------|
| 导航 | `market`, `indicator`, `predict`, `panorama`, `validate`, `log` | 左侧导航 6 页 |
| 工具 | `sun`, `moon`, `filter`, `warning`, `check`, `bolt`, `gear`, `book`, `refresh` | 主题/筛选/预警/成功/闪电/设置/文档/刷新 |

调用：`icon(name, theme="dark", color_override=None, size=20) -> QIcon`。图标以 2x 超采样渲染，确保高分屏下清晰锐利。

组件使用模块级 `W.THEME` 全局（`dark`/`light`），`main_window._apply_theme` 写入该全局，无需逐个保存引用。

---

## 四、导航与状态栏

- 每个导航项左侧带 **SVG 矢量图标**（行情全景 / 指标分析 / KP预测 / 市场全景 / 回测验证 / 日志预警），激活态为白色，未激活态为次要文字色，hover 背景反馈。
- 底部状态栏（`QStatusBar`）：连接状态点（● 已连接/离线）+ 数据源标签 + 实时时钟 + 「重连」按钮 + 主题切换按钮（sun/moon 图标）。

---

## 五、各页面视觉要点

### 行情全景（MarketPage）
- 顶部 6 个 `MetricChip`：最新价、涨跌（红/绿）、最高、最低、成交量、持仓量。
- 中部 `KLineChart`：蜡烛图 + 成交量副图 + MA5/10/20 叠加 + 悬浮十字光标 + 滚轮缩放。
- 底部「自选合约」表：39 个期货品种，覆盖黑色系 / 有色金属 / 贵金属 / 能源化工 / 农产品 / 金融 六大板块；板块筛选下拉；列含合约、名称、最新价、涨跌幅、持仓量（涨跌红绿配色）；**双击任意行切换主图行情**。

### 指标分析（IndicatorPage）
- 主图 `KLineChart` 叠加均线 / BOLL；下方三个 `PriceChart` 副图：`MACD`（DIF/DEA/柱）、`KDJ`（K/D/J）、`RSI`（RSI6/RSI14），各 `setMinimumHeight(90)`。
- 结论卡：多空共振打分、趋势强弱（基于 ADX）、RSI 背离类型。

### KP预测（PredictPage）
- 参数卡：品种、周期、回看根数、预测期数、蓝色「运行预测」按钮（`run_btn`，`objectName=primary`）。
- 结论卡：方向徽章（看多/看空/中性）+ 置信度条 + 最新价 / 预测中枢 / 支撑 / 阻力指标卡。
- 预测图 `KLineChart`：历史收盘 + 预测中枢虚线（`set_forecast`）+ 阴影置信带（±1σ）+ 压力支撑水平虚线（`set_levels`）。
- 底部：AI 文本摘要 + 逐期预测表（隔行底色）。预测在 `Worker(QThread)` 后台线程执行，按钮在运行中禁用并显示「预测中…」。

### 市场全景（PanoramaPage）
- `PriceChart`（`bar`，`setMinimumHeight(260)`）展示全市场强弱/涨跌分布。
- 排行表：涨跌排行、强弱排序、量能暴增/缩量预警、资金净流入/流出，支持多空联动筛选。

### 回测验证（ValidatePage）
- 参数卡：品种、周期、预测期数、是否使用 LSTM，蓝色「开始验证」按钮（`run_btn`，`objectName=primary`）。
- 历史回测在 `Worker` 后台线程执行（验证页用 `force_ridge` 快速滚动评估，避免长时 LSTM 训练阻塞 UI）。
- `PriceChart`（`chart`，`setMinimumHeight(240)`）展示回测曲线；结果区统计预测准确率、胜率、最大偏差、趋势捕捉率，并可导出可视化报告。

### 日志预警（LogPage）
- 预警/预测/分析记录存档列表 + 系统日志文本区；支持导出报告（CSV/Excel 可读取）。

---

## 六、图表组件（`chart_widget.py`)

- `KLineChart`：原生 `QPainter` 绘制，零图表依赖。
  - 蜡烛体宽随可视根数自适应（1~16px），影线清晰；大数据量自动进入「密集模式」（单根影线呈现），保证流畅渲染。
  - 右侧价格刻度按价格量级自适应小数位；底部时间轴根据数据是否含时间自动切换 `YYYY-MM-DD` / `MM-DD HH:mm`。
  - 最新价虚线 + 右侧圆角价签。
  - 鼠标悬浮十字光标 + 圆角信息框（开/高/低/收、涨跌、成交量、均线），并在右轴与时间轴显示跟随光标的价签与日期。
  - 支持预测曲线（`set_forecast(y, upper, lower)`）、压力支撑水平虚线（`set_levels(levels)`）且做了标签防重叠。
  - `total_n = view_n + horizon` 保证预测段完整可见。
- `PriceChart`：通用折线/面积图，用于 MACD/KDJ/RSI/全景分布/回测曲线。`set_theme` 统一配色。

---

## 七、二次开发建议

1. **新增页面**：在 `main_window.NAV` 注册 `(名称, PageClass, icon_name)`，复制现有 `BasePage` 子类模板；顶部加 `PageHeader`，内容放 `QGroupBox`；在 `icons.py` 增加对应图标名。
2. **新增指标卡**：用 `MetricChip(label, value)`，数值颜色按正负传入 `W.pal()["up"]` / `W.pal()["down"]`。
3. **新增主题**：在 `widgets.PALETTE` 新增第三套配色；在 `main_window` 的 `DARK_QSS` / `LIGHT_QSS` 旁新增第三套 `QSS`；在 `_apply_theme` 中切换对应 QSS 即可。
4. **替换图标**：在 `icons.py` 的图标表中新增条目，再通过 `icon(name, theme=self.theme, size=...)` 获取 `QIcon` 设置到按钮或导航。

---

## 八、视觉校验

本项目包含 `docs/examples/capture_ui.py` 用于离线渲染截图，生成位置 `docs/examples/output/`：

- `ui_market_dark.png` / `ui_market_light.png`
- `ui_indicator_dark.png` / `ui_indicator_light.png`
- `ui_predict_dark.png` / `ui_predict_light.png`
- `ui_panorama_dark.png` / `ui_panorama_light.png`
- `ui_validate_dark.png` / `ui_validate_light.png`
- `ui_log_dark.png` / `ui_log_light.png`

运行（会先触发一次 KP预测以填充预测页内容）：

```bash
QT_QPA_PLATFORM=offscreen python docs/examples/capture_ui.py
```

> 注意：在沙箱/offscreen 环境下，`capture_ui.py` 通过 `setup_fonts()` 显式注册 `simhei.ttf / NotoSansSC-VF.ttf / msyh.ttc` 并应用为应用字体，已解决中文 tofu 问题；真实 Windows 环境下由 `main_window.main()` 的 `QFontDatabase.addApplicationFont` 同样保证中文显示。

更全面的交互冒烟测试：

```bash
QT_QPA_PLATFORM=offscreen python docs/examples/smoke_ai_kline.py
```

---

## 九、近期 UI 打磨要点

1. **Badge 不再拉伸**：`Badge` 组件固定高度 `24px` 并内部居中对齐，在结论卡等水平布局中保持胶囊形状，不会被布局纵向撑开。
2. **表格去掉左侧行号**：所有表格通过 `prepare_table` 隐藏 `verticalHeader` 并统一行高，列表更干净；同时 QSS 增加 `QTableWidget::item:hover` 行悬停反馈。
3. **参数面板扁平化**：去掉嵌套 `QGroupBox` 边框，参数表单直接置于卡片内，减少视觉层级堆叠。
4. **K 线视觉重构**：蜡烛体/影线比例自适应、右侧圆角价签、按量级自适应价格刻度、时间轴智能格式、悬浮圆角信息框 + 光标价签/时间标签、压力支撑标签防重叠、大数据量密集模式保流畅。
5. **全局 QSS 收尾**：`QStatusBar` 顶部增加分隔线；`QComboBox` 三角形指示；表头加粗；导航按钮保持左对齐与圆角一致。
6. **持久化接入**：主题/窗口几何/最后停留页/各页合约周期自动保存；崩溃时通过 `sys.excepthook` 兜底 flush 状态并写 `CRASH` 日志，确保重启可恢复。
