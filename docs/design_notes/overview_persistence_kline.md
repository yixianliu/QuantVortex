# 本轮交付概览：数据持久化方案 + K 线图视觉/性能重构

## 一、数据持久化存储方案（已落地并验证）

### 1.1 三层存储模型

| 类别 | 载体 | 文件 | 关键设计 | 异常恢复机制 |
| --- | --- | --- | --- | --- |
| 用户配置 | JSON | `config/settings.json`（默认）+ `data/user_settings.json`（用户覆盖） | 仅保存用户差异覆盖，原子写 | `*.bak` 回退 + 损坏自愈 + 版本迁移 |
| 运行时状态 | JSON | `data/session_state.json` | 窗口几何/最大化/最后页/各页合约周期 | `*.bak` 回退 + 损坏自愈 |
| 历史记录 | SQLite | `data/quant_analysis.db` | WAL 模式、索引、启动校验、退出 checkpoint | WAL 崩溃安全 + 完整性校验 + 容量限制 |

### 1.2 新增 / 修改文件
- `futures_quant/storage/json_store.py` — `AtomicJSON`：原子写、`.bak` 备份、损坏回退、版本迁移、点分路径。
- `futures_quant/storage/config_manager.py` — `ConfigManager` + `SessionState`。
- `futures_quant/storage/analysis_store.py` — 增强 `busy_timeout/synchronous/WAL/integrity_check/checkpoint/prune/close`。
- `futures_quant/ui/main_window.py` — 接入配置与状态、恢复窗口/主题/最后页、防抖落盘、全局崩溃兜底。
- `futures_quant/ui/pages.py` — `BasePage` 新增 `selection_changed` 信号；各页从 session 恢复 symbol/period 并在变更时 emit。
- `config/settings.json` — 增加 `"version": 2`。
- `README.md` / `docs/ui_design.md` — 新增持久化与 K 线重构说明。

### 1.3 验证结果
- `python main.py --test` → 核心模块全部可导入 OK。
- `python examples/test_core.py` → ALL CORE LAYERS OK。
- `python examples/_persist_check.py` → 原子写/损坏回退(`a.b=99`)/版本迁移/配置持久化/会话恢复 全部 PASS。
- 截图脚本已加 `QUANTVORTEX_NO_PERSIST=1`，不污染用户真实 session。

---

## 二、K 线图视觉与性能重构

### 2.1 视觉优化点
- **蜡烛体/影线比例**：随可视根数自适应宽度（1~16px），影线 1px 清晰；最小实体高度 1px，避免十字星消失。
- **配色与可读性**：红涨绿跌保持；绘图区添加微底色 + 细边框；成交量透明度 150，不喧宾夺主。
- **坐标轴/网格/刻度**：右侧价格刻度按价格量级自适应小数位；时间轴自动识别日线/分钟并显示 `YYYY-MM-DD` 或 `MM-DD HH:mm`。
- **交互提示**：鼠标悬停显示圆角信息框（O/H/L/C、涨跌、成交量、均线），并在右轴、时间轴显示跟随光标的价签与日期。
- **最新价与关键价位**：最新价虚线 + 右侧圆角价签；压力/支撑水平虚线，标签做简单防重叠。

### 2.2 性能优化点
- **密集模式**：可视根数极多、单根像素 < 3px 时，每根蜡烛用单根影线绘制，避免 body+wick 双绘制开销。
- **零拷贝索引**：`paintEvent` 中不再切片 `self._bars`，而是使用全局索引 `gi` 直接访问，降低大容量数据下的内存拷贝与 GC 压力。
- **局部重绘**：仅当悬停目标蜡烛变化时才 `update()`，鼠标在相邻像素内滑动不触发重绘。

### 2.3 修改文件
- `futures_quant/ui/chart_widget.py` — 重写 `KLineChart.paintEvent` 与交互辅助函数；保留 `set_data / set_forecast / set_levels / set_theme` 等公开接口不变。

### 2.4 视觉验证
- `examples/capture_ui.py` 生成 12 张深/浅六页截图，文件大小 59–188KB，K 线、预测曲线、成交量、悬浮提示均正常渲染。

---

## 三、诚实边界
- 免费新浪接口仅提供日线/周线真实数据；分钟/小时历史线未提供，在 `sina` 模式下会明确回退合成行情。
- AI 多步预测为概率性点预测，远端步长误差随 horizon 放大；置信带按残差标准差 √h 扩张。
- 程序**不做自动交易**，所有结果仅供学习研究。

> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
