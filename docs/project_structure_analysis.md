# QuantVortex 项目文件结构分析

> 生成日期：2026-07-25  
> 最后整理：2026-07-25（文件归类迁移完成）  
> 项目路径：`D:\PythonProject\QuantVortex`  
> 语言版本：Python 3.13  
> 核心依赖：PyQt6 / pandas / numpy

---

## 一、项目概览

```
QuantVortex/                     # 项目根目录
├── futures_quant/               # [核心库] 期货智能分析预测系统主包
│   ├── ai/                      #     KP预测模型（LSTM、集成学习、新闻推送）
│   ├── alerts/                  #     预警引擎（规则扫描、触发通知）
│   ├── analysis/                #     技术分析引擎（支撑阻力、共振信号）
│   ├── analytics/               #     分析评估工具（预测结果评估）
│   ├── backtest/                #     回测引擎
│   ├── broker/                  #     交易代理（回测/模拟）
│   ├── config/                  #     系统配置加载
│   ├── core/                    #     核心运行时（引擎/事件/组合/类型）
│   ├── data/                    #     数据源（新浪/CTP/合成行情）
│   ├── indicators/              #     技术指标库（MA/BOLL/RSI/KDJ/MACD...）
│   ├── risk/                    #     风险管理模块
│   ├── storage/                 #     存储层（SQLite/PostgreSQL/JSON配置）
│   ├── strategy/                #     策略库（趋势/均值回归/网格/马丁/突破）
│   ├── ui/                      #     GUI 界面（主窗口/页面/图表/图标）
│   ├── utils/                   #     工具模块（日志等）
│   └── runtime.py               #     运行时路径管理
├── config/                      # [配置文件] 系统全局配置
├── data/                        # [数据目录] 运行时数据持久化
├── docs/                        # [文档目录] 项目文档与指南
├── examples/                    # [示例目录] 演示脚本 + UI截图
├── logs/                        # [日志目录] 程序运行日志
├── packaging/                   # [打包目录] EXE 安装包构建
├── api/                         # [API目录] 外部接口脚本
├── main.py                      # [入口文件] 程序启动入口
├── requirements.txt             # [依赖文件] Python 依赖清单
├── futures_qt.spec              # [构建文件] PyInstaller 打包配置
├── build_*.py / *.log           # [构建文件] 构建脚本与日志
├── _test_*.py                   # [测试文件] 模块自测脚本
├── overview_*.md                # [概览文件] 项目各模块概述笔记
├── market_sector_screening_report.html  # [输出文件] 选品报告（HTML）
└── .gitignore                   # [Git配置] Git忽略规则
```

---

## 二、文件分类清单

### 1. 源代码文件 — 87 个 Python 文件

#### A. 核心业务库 `futures_quant/`（68 个文件，~12,000 行）

| 子模块 | 文件数 | 功能说明 | 关键文件 |
|--------|--------|----------|----------|
| **core/** | 6 | 核心运行时：事件总线、类型定义、投资组合、交易引擎 | `engine.py`, `types.py`, `portfolio.py`, `event.py`, `indicators.py` |
| **strategy/** | 6 | 策略库：趋势跟踪、均值回归、网格、马丁格尔、突破 | `base.py`, `trend_following.py`, `mean_reversion.py`, `grid.py`, `martingale.py`, `breakout.py` |
| **data/** | 6 | 数据源层：新浪实时行情、CTP柜台行情、合成模拟行情 | `sina_feed.py`, `ctp_gateway.py`, `synthetic.py`, `market_data.py`, `base.py` |
| **storage/** | 8 | 存储后端：SQLite 单文件、PostgreSQL ���产级、JSON 配置、迁移导出 | `analysis_store.py`, `sqlite_backend.py`, `postgres_backend.py`, `factory.py`, `config_manager.py`, `json_store.py`, `base.py`, `data_transfer.py` |
| **ui/** | 10 | GUI 界面：主窗口、7 个功能页、K线图组件、图标系统 | `main_window.py`, `pages.py`, `chart_widget.py`, `data_page.py`, `icons.py`, `widgets.py`, `backtest_page.py`, `screening_page.py`, `ctp_monitor_page.py`, `__main__.py` |
| **ai/** | 7 | KP预测：LSTM 序列预测、特征工程、集成学习、反馈评估、新闻流 | `predictor.py`, `lstm.py`, `ensemble.py`, `features.py`, `evaluate.py`, `feedback.py`, `news_feed.py` |
| **analysis/** | 2 | 技术分析：共振信号检测、趋势打分、支撑阻力线计算 | `signals.py`, `support_resistance.py` |
| **alerts/** | 2 | 预警引擎：规则定义、周期扫描、阈值触发 | `__init__.py`（含常量定义）, `engine.py`（扫描器） |
| **analytics/** | 2 | 分析评估：预测准确度评估 | `__init__.py`, `predictor.py` |
| **backtest/** | 2 | 回测框架：回测执行器 | `__init__.py`, `backtester.py` |
| **broker/** | 4 | 交易代理：回测撮合、模拟下单 | `base.py`, `backtest_broker.py`, `paper.py` |
| **config/** | 2 | 配置数据类：账户/风控/回测/UI/存储配置 | `settings.py`, `__init__.py` |
| **indicators/** | 1 | 技术指标函数集 | `tech.py` |
| **risk/** | 2 | 风险管理：仓位控制、回撤限制、单笔亏损上限 | `__init__.py`, `risk_manager.py` |
| **utils/** | 2 | 工具：日志记录 | `__init__.py`, `logger.py` |
| **顶层** | 2 | 包初始化、运行时路径管理、选品评估器 | `__init__.py`, `runtime.py`, `screening_eval.py` |

#### B. 程序入口

| 文件 | 功能 |
|------|------|
| `main.py` (55 行) | 程序启动入口，创建 QApplication 并启动 MainWindow |

#### C. API 接口

| 文件 | 功能 |
|------|------|
| `api/futures_ai_predict.py` | KP预测 API 接口 |
| `api/agnes-2.0-flash.py` | 第三方模型调用适配 |

### 2. 配置文件 — 3 个 JSON + 1 个 spec

| 文件 | 路径 | 内容 |
|------|------|------|
| `settings.json` | `config/` | 全局默认配置：主题、数据源、SQL路径、预测参数、默认合约/周期 |
| `ctp_settings.json` | `config/` | CTP 实盘行情接入凭据 |
| `ctp_settings.example.json` | `config/` | CTP 配置模板（无真实凭据） |
| `futures_qt.spec` | 根目录 | PyInstaller EXE 打包配置文件 |

### 3. 数据持久化文件 — 4 个 DB + 2 个 JSON 状态

| 文件 | 路径 | 用途 |
|------|------|------|
| `quant_analysis.db` | `data/` | **主库**：K线缓存、KP预测、研判、预警、日志、判断、选品样本 |
| `_selftest.db` | `data/` | 功能自测 SQLite 库 |
| `integration_test.db` | `data/` | 集成测试 SQLite 库 |
| `smoke_test.db` (+ shm/wal) | `data/` | 冒烟测试 SQLite 库 |
| `user_settings.json` | `data/` | 用户个性化设置（从 settings.json 继承，仅存差异覆盖） |
| `session_state.json` (+ bak) | `data/` | 运行时状态：窗口几何、最后停留页、各页合约/周期 |
| `cls_news_cache.json` | `data/` | 新闻缓存 |
| `_pred_export.csv` | `data/` | 预测导出中间文件 |

### 4. 测试文件 — 5 个

| 文件 | 范围 | 说明 |
|------|------|------|
| `_test_data_transfer.py` | 数据模块 | CSV/JSON/ZIP 导出、备份恢复、损坏文件拒绝、MySQL 连通性提示 |
| `_test_data_page.py` | GUI 页面 | DataPage 离屏实例化、控件完整性、主题切换、信号链路 |
| `_test_mysql_roundtrip.py` | MySQL | 真实本地 MySQL 闭环：SQLite→MySQL→清空→恢复→行数/浮点/中文校验 |
| `examples/test_all_pages.py` | 页面 | 全页面功能测试 |
| `examples/test_core.py` | 核心 | 行情合成+指标计算+页面渲染端到端 |
| `examples/test_ctp_integration.py` | CTP | CTP 行情接入集成测试 |
| `examples/test_persistence.py` | 存储 | JSON原子写、配置管理、分析存储健壮性 |
| `examples/integration_test.py` | 整体 | 端到端集成测试 |
| `examples/predictor_demo.py` | AI | LSTM预测演示 |
| `examples/run_backtest.py` | 回测 | 回测执行演示 |
| `examples/sina_demo.py` | 数据 | 新浪数据源演示 |
| `examples/storage_demo.py` | 存储 | 存储层演示 |
| `examples/smoke_ai_kline.py` | UI | K线图冒烟测试 |

### 5. 文档文件 — 13 个 Markdown + 1 个 HTML

| 文件 | 类别 | 内容 |
|------|------|------|
| `README.md` | 项目 | 项目说明 |
| `docs/packaging.md` | 构建 | EXE 打包说明 |
| `docs/CTP_本地接入完整步骤.md` | 接入 | CTP 全栈接入指南 |
| `docs/CTP_本地接入指南.md` | 接入 | CTP 快速入门 |
| `docs/CTP接入_速查清单.md` | 接入 | CTP 操作速查 |
| `docs/CTP接入验证操作指南.md` | 接入 | CTP 验证步骤 |
| `docs/SimNow注册完全指南.md` | 接入 | SimNow 注册教程 |
| `docs/ctp_wiring.md` | 接入 | CTP 接线/连接说明 |
| `docs/storage.md` | 架构 | 存储层设计说明 |
| `docs/prediction.md` | 架构 | KP预测系统设计 |
| `docs/strategy_tuning.md` | 策略 | 策略参数调优指南 |
| `docs/ui_design.md` | UI | 界面设计规范 |
| `docs/ui_alternative.md` | UI | 备选 UI 方案 |
| `docs/data_management.md` | 模块 | 数据管理模块说明 |
| `docs/roadmap_next_three_directions.md` | 规划 | 路线图 |
| `market_sector_screening_report.html` | 输出 | 板块选品报告 |

### 6. 资源文件 — 22 个 PNG + 其他

| 文件 | 路径 | 说明 |
|------|------|------|
| `kline_dark.png` ... `kline_light_hover.png` | `examples/` | K线图样式截图 |
| `output/ui_*_dark.png` / `*_light.png` | `examples/output/` | 各页面深/浅主题截图（共 22 张） |
| `screening_page_preview.png` | `examples/` | 选品页预览 |

### 7. 构建文件 — 2 个脚本 + 6 个日志

| 文件 | 说明 |
|------|------|
| `build_exe.py` | PyInstaller 构建脚本 |
| `packaging/build_installer.bat` | Windows 安装包构建批处理 |
| `packaging/installer.iss` | Inno Setup 安装脚本 |
| `build_*.log` (×6) | 历次构建日志 |

### 8. 日志文件 — 5 个

| 文件 | 路径 | 说明 |
|------|------|------|
| `cli.log` | `logs/` | CLI 模式日志 |
| `backtest_example.log` | `logs/` | 回测示例日志 |
| `probe.log` | `logs/` | 探测日志 |
| `storage_demo.log` | `logs/` | 存储演示日志 |
| `ui.log` | `logs/` | GUI 日志 |

---

## 三、文件依赖关系图

### A. 模块间导入拓扑

```
main.py
  └─> futures_quant.ui.main_window
        ├─> futures_quant.storage.analysis_store  ──→ sqlite3 (std lib)
        ├─> futures_quant.storage.config_manager  ──→ futures_quant.runtime
        ├─> futures_quant.ui.pages                ──> 所有页面组件
        │     ├─> futures_quant.data.market_data  ──> sina_feed / ctp_gateway / synthetic
        │     ├─> futures_quant.ai.predictor      ──> lstm / features / ensemble
        │     ├─> futures_quant.analysis.signals  ──> indicators.tech
        │     ├─> futures_quant.indicators.tech   ──> numpy / pandas
        │     ├─> futures_quant.strategy.*        ──> core.indicators / core.types
        │     └─> futures_quant.alerts.engine
        ├─> futures_quant.ui.backtest_page         ──> futures_quant.strategy.*
        ├─> futures_quant.ui.screening_page        ──> futures_quant.ai.predictor
        ├─> futures_quant.ui.ctp_monitor_page      ──> futures_quant.data.ctp_gateway
        ├─> futures_quant.ui.data_page             ──> futures_quant.storage.data_transfer
        └─> futures_quant.ui.chart_widget           ──> PyQt6 (绘图)
              └─> PyQt6.QtWidgets / QtGui / QtCore

futures_quant.core.engine           ──→ futures_quant.broker.*
                                       futures_quant.risk.risk_manager
                                       futures_quant.config.settings
                                       futures_quant.storage.base (工厂)

futures_quant.storage.factory       ──→ sqlite_backend / postgres_backend
futures_quant.storage.data_transfer ──→ pymysql (optional)

examples/*                          ──→ 以上各模块的子集（演示/测试用）
```

### B. 数据流向

```
[数据源层]                               [AI层]                              [存储层]
SinaFeed ──┐                            predictor.py ──→ prediction records ──→ quant_analysis.db
SyntheticFeed ──┤                                                      (bars/predictions/analysis/alerts...)
CTPFeed ────┘                                                              ↑
         │                                                                 │
         ▼                                                                 │
MarketDataManager ──► indicator.py ──► signals.py ──► alert engine ────────┘
         │                                                            │
         ▼                                                            ▼
    K线图(chart_widget)                                    predictions表(feedback闭环)
    页面展示(pages.*)
```

### C. 策略执行流

```
Config (settings.json)
    │
    ▼
TradingEngine ──► Portfolio ──► Position tracking
    │
    ├─► Broker (BacktestBroker / PaperBroker) ──► Order → Trade
    │
    ├─► RiskManager ──► max_drawdown, max_position, non_trading_hours_block
    │
    └─► Strategy (TrendFollowing / Grid / Martingale / MeanReversion / Breakout)
              │
              ▼
       Signal → Order → Execution → Record(storage)
```

---

## 四、目录结构建议

### 当前状况

✅ **做得好的方面：**
- `futures_quant/` 包内部按职责分层清晰（core / strategy / data / storage / ui）
- GUI 页面与业务逻辑解耦，每个页面独立文件
- 存储后端通过 `factory.py` 统一抽象，上层不关心底层
- `config/settings.py` 使用 dataclass 集中管理配置

⚠️ **可改进之处：**

| 问题 | 位置 | 建议 |
|------|------|------|
| 测试脚本散落在根目录 | `root/_test_*.py` | 统一移入 `tests/` 目录，命名规范为 `test_<module>.py` |
| 示例脚本与测试边界模糊 | `examples/` | 细分为 `examples/demo/`（演示）和 `tests/e2e/`（端到端） |
| 构建产物堆积根目录 | `build_*.log`, `build_*.py`, `nul` | 移入 `build_tools/` 目录 |
| API 文件夹语义不清 | `api/` | 内含功能说明文档而非代码，可改名为 `api_docs/` 或直接移入 `docs/` |
| 概览笔记散落根目录 | `overview_*.md` | 移入 `docs/design_notes/` 或直接写入对应模块文档 |
| `data/sina_cache/` 近 50 个文件 | `data/` | 排除在版本控制外（已在 .gitignore？），或在 `data/cache/` 下组织 |
| 编译缓存污染 | `*/__pycache__/` | 确认 `.gitignore` 已忽略 |

### 推荐目标结构

```
QuantVortex/
├── futures_quant/                 # [核心库] 68 个 Python 文件
│   ├── __init__.py
│   ├── runtime.py
│   ├── screening_eval.py
│   ├── ai/                        # KP预测
│   ├── alerts/                    # 预警引擎
│   ├── analysis/                  # 技术分析
│   ├── analytics/                 # 分析评估
│   ├── backtest/                  # 回测框架
│   ├── broker/                    # 交易代理
│   ├── config/                    # 配置管理
│   ├── core/                      # 核心运行时 ⭐ 最内层依赖
│   ├── data/                      # 数据源
│   ├── indicators/                # 技术指标
│   ├── risk/                      # 风险管理
│   ├── storage/                   # 存储层 ⭐
│   ├── strategy/                  # 策略库
│   ├── ui/                        # GUI 界面
│   └── utils/                     # 工具
│
├── config/                        # [配置文件] (不变)
│   ├── settings.json
│   ���── ctp_settings.json
│   └── ctp_settings.example.json
│
├── data/                          # [运行时数据] (git-ignored)
│   ├── quant_analysis.db          # 主库
│   ├── user_settings.json
│   ├── session_state.json
│   └── sina_cache/                # K线缓存
│
├── tests/                         # ← 新建（统一存放所有测试）
│   ├── unit/                      #     单元测试（原 _test_*.py）
│   ├── e2e/                       #     端到端测试（原 examples/test_*.py）
│   ├── fixtures/                  #     测试数据集
│   └── conftest.py                #     pytest 配置
│
├── examples/                      # [示例目录] (保持，仅含演示脚本)
│   ├── demo_ai.py                 #     只保留演示性质
│   ├── demo_backtest.py
│   └── demo_storage.py
│
├── docs/                          # [文档目录] (保持 + 扩展)
│   ├── architecture.md            #     架构总览（新增）
│   ├── modules/                   #     模块文档（新增）
│   │   ├── core.md
│   │   ├── ai.md
│   │   ├── ui.md
│   │   └── storage.md
│   ├── guides/                    #     用户指南（新增）
│   │   ├── ctp_setup.md
│   │   ├── packaging.md
│   │   └── data_management.md
│   └── design_notes/              #     设计笔记（原 overview_*.md 迁入）
│
├── build_tools/                   # ← 新建（原 build_*.py / build_*.log）
│   ├── build_exe.py
│   ├── spec/
│   │   └── futures_qt.spec
│   └── log/                       #     构建日志归档
│
├── api_docs/                      # ← 新建（原 api/ 改名）
│   ├── futures_ai_predict.py
│   ├── agnes-2.0-flash.py
│   └── function_call_1.txt
│
├── packaging/                     # [打包目录] (不变)
├── logs/                          # [日志目录] (可选 git-ignored)
├── screenshots/                   # ← 新建（原 examples/*.png 迁入）
│   ├── kline_dark.png
│   └── ...                        #     所有 UI 截图
│
├── main.py                        # [入口] (不变)
├── README.md                      # [说明] (不变)
├── requirements.txt               # [依赖] (不变)
├── requirements-dev.txt           # [开发依赖] (不变)
├── .gitignore                     # [Git配置] (不变)
└── CHANGELOG.md                   # ← 建议新增（版本变更日志）
```

---

## 五、文件大小统计

| 类别 | 文件数 | 估计大小 |
|------|--------|----------|
| 核心源代码（futures_quant/） | 68 | ~12,000 行 |
| GUI 页面（ui/） | 10 | ~4,300 行 |
| 示例 + 测试 | 15+ | ~1,500 行 |
| 配置 + 文档 | 18 | - |
| 运行时数据（DB + cache） | 50+ | ~10-50 MB |
| UI 截图（PNG） | 22 | ~2-5 MB |

---

## 六、关键设计模式总结

| 模式 | 应用位置 | 说明 |
|------|----------|------|
| **工厂模式** | `storage/factory.py` | 根据配置返回 SQLite 或 PostgreSQL 后端 |
| **策略模式** | `strategy/base.py + *` | 多策略共享统一基类接口 |
| **观察者模式** | UI 信号/槽（pyqtSignal） | 页面间通信、Worker 线程 → UI 更新 |
| **适配器模式** | `data/sina_feed.py / ctp_gateway.py / synthetic.py` | 统一行情接口（MarketDataManager） |
| **命令模式** | `alerts/engine.py` | 预警规则作为可执行的命令对象 |
| **组件组合** | `ui/main_window.py` | 左侧导航 + QStackedWidget 页堆叠 + 底部状态栏 |

---

## 七、文件归类迁移记录（2026-07-25）

### 已完成的重构操作

| 源位置 | 目标位置 | 移动文件数 | 说明 |
|--------|----------|-----------|------|
| `root/_test_*.py` (3) | `tests/unit/` | 3 | 单元测试：数据迁移、GUI 页面、MySQL 闭环 |
| `examples/test_*.py` (4) | `tests/e2e/` | 4 | 端到端测试：全页面、核心功能、CTP、持久化 |
| `examples/backtest/*.py` (5) | `tests/e2e/` | 5 | 回测脚本：红利定投、半导体回调、导出/渲染 |
| `examples/backtest/*.csv` (8) | `tests/fixtures/` | 8 | 回测数据：ETF 日线、equity/trades CSV |
| `examples/backtest/*.json` (3) | `tests/fixtures/` | 3 | 回测摘要 JSON |
| `build_*.py` (1) + `futures_qt.spec` (1) | `build_tools/` | 2 | 构建脚本和 spec 配置 |
| `packaging/*.bat` + `*.iss` (2) | `build_tools/` | 2 | Windows 安装器 + Inno Setup 脚本 |
| `build_*.log` (6) | `build_tools/log/` | 6 | 构建日志归档 |
| `api/*` (4) | `api_docs/` | 4 | API 接口文档和适配脚本 |
| `overview_*.md` (7) | `docs/design_notes/` | 7 | 设计笔记：K线/图标/持久化/UI 概述等 |
| `market_sector_screening_report.html` | `docs/reports/` | 1 | 板块选品报告 |
| `examples/*.png` + `output/*_*.png` (22) | `screenshots/` | 22 | UI 截图：K线图/各页面深/浅主题 |
| `packaging/` 目录 | `build_tools/` | 合并 | 目录合并，原 packaging 删除 |

### 修正的引用路径

| 文件 | 修改内容 |
|------|----------|
| `tests/unit/_test_data_page.py` | `sys.path` → 从 tests/unit/ 到根目录 |
| `tests/unit/_test_data_transfer.py` | 同上 |
| `tests/unit/_test_mysql_roundtrip.py` | 同上 |
| `tests/e2e/dividend_dca_backtest.py` | DATA_FILE/SEMI_* 路径 → `../../fixtures/` |
| `tests/e2e/semiconductor_dipbuy_backtest.py` | DATA_FILE 路径 → `../../fixtures/` |
| `.gitignore` | 细化 data/ 忽略规则（只忽略 sina_cache 和 backtest_reports） |

### 验证结果

- ✅ 所有 Python 文件编译通过（py_compile）
- ✅ `_test_data_transfer.py` — ALL DATA-TRANSFER TESTS PASSED
- ✅ GUI 页面实例化测试 — ALL GUI TESTS PASSED
- ✅ MySQL 闭环测试无需重复运行（上轮已验证）
