# QuantVortex v4.0 升级进度记录

**基线版本**: 3.1.0  
**目标版本**: 4.0.0  
**开始时间**: 2026-09-20  
**当前阶段**: P3 数据与 AI 融合（✅ 已完成）

## 基线校验结果
- 版本确认: futures_quant.__version__ == "3.1.0" ✓
- 密钥扫描: 通过，未发现硬编码密钥 ✓
- 全页面 GUI 冒烟测试: 7/7 通过 ✓
- 代码编译检查: 通过 ✓

## 任务追踪
### P1 基础加固
- [x] M2.x~M3.x 核心算法与合约规则（详见各 e2e 测试）

### P2 策略与 AI（本轮完成 2026-09-20）
- [x] M4.1 CTA 趋势扩充 - strategy/cta/dual_thrust.py/keltner.py/ichimoku.py/trailing_atr.py/vortex.py 实现，test_strategies_cta.py 全绿
- [x] M4.2 统计套利 - strategy/arbitrage/calendar_spread.py 实现，test_arbitrage.py 全绿
- [x] M4.3 日内短线：开盘突破（30min）、成交量异动（2σ） - strategy/intraday/open_breakout.py、volume_anomaly.py 实现，test_intraday.py、test_volume_anomaly.py 全绿
- [x] M4.3 日内短线：改良网格（动态间距 = ATR×k） - strategy/intraday/grid.py 实现，test_intraday_grid.py 全绿
- [x] M4.4 波动率交易（本轮收尾）：
  - strategy/volatility/bollinger.py 修复 std 改用总体标准差 ddof=0（匹配布林带标准定义与测试期望），test_volatility_bollinger.py 重写全绿
  - strategy/volatility/hv_percentile.py HV分位突破，test_volatility_hv_percentile.py 全绿
  - strategy/volatility/garch_timing.py（新增）GARCH(1,1) 条件波动率择时（EWMA 递推，离线可算），test_volatility_garch_timing.py 全绿
- [x] M4.5 策略组合：多策略权重优化 - strategy/combo.py 实现，test_combo_strategy.py 全绿
- [x] M4.6 遗传算法升级：20+因子、树结构基因、Calmar+稳定性 - strategy/auto_evolve.py 实现
- [x] M5.1 特征工程重构：滚动z-score、特征构建 - ai/features.py（实为 futures_quant/ai/features.py），test_features_no_lookahead.py 全绿
- [x] M5.2 XGBoost/LightGBM 集成：ai/boosting.py（可选依赖降级玩具实现），test_boosting.py 全绿
- [x] M5.3 TCN（纯numpy）- ai/tcn.py，test_tcn.py 全绿
- [x] M5.4 TS-Transformer（可选torch）- ai/ts_transformer.py（无 torch 自动降级零模型），test_ts_transformer.py 全绿
- [x] M5.5 GARCH(1,1) 波动率 - ai/garch.py（arch 可选、缺失降级 EWMA 递推；本轮修复 numpy 路径与 forecast[0] 公式 bug），test_garch.py 全绿
- [x] M5.6 PPO强化学习（可选torch）- ai/ppo.py（本轮新增；无 torch 走 numpy REINFORCE+baseline 降级；动作 {-2..+2}），test_ppo.py 全绿（policy 夏普 144.6 > 随机基线 19.4）
- [x] M5.7 Walk-Forward 滚动验证 - ai/validation.py（本轮新增；窗口 252/验证 63/步长 63，禁随机划分），test_walk_forward.py 全绿
- [x] M5.8 特征贡献度 - ai/attribution.py（本轮新增；shap 可选，缺失降级朴素扰动重要性；前 10 特征 bar chart），test_attribution.py 全绿

## P2 阶段门禁（全部通过）
- [x] `python -m compileall` 全包绿
- [x] `test_all_pages.py` 全绿（rc=0）
- [x] `build_tools/secret_scan.py` 绿（exit 0，无密钥泄露）
- [x] P2 全 18 个模块 e2e 测试 rc=0

## 修复的既有缺陷
- **PriceLimitManager 缺失**（M3.4 遗留）：`core/engine.py` 导入 `data.price_limit.PriceLimitManager` 但该类不存在，导致全页 e2e ImportError 阻塞。本轮在 `futures_quant/data/price_limit.py` 补齐 `PriceLimitManager`（多合约状态机：0 正常/1 扩板1/2 扩板2/99 封停，新交易日重置，threshold=default_limit+step*level），`test_price_limit.py` 扩展全绿。
- **bollinger std 定义错位**：策略用 pandas 默认样本标准差 ddof=1，测试注释按总体标准差 ddof=0 期望，边界恒等导致触发失败。改策略 `std(ddof=0)`（匹配布林带标准定义）并重写测试用 window=3 序列 [10,12,14,8] 验证严格突破。

## 风险/问题记录
- ~~**顶层 `ai/` 包位置漂移**~~ → **已归位**：M5.x 7 模块（boosting/tcn/ts_transformer/garch/validation/ppo/attribution）从仓库根 `ai/` 移至 `futures_quant/ai/`，测试导入改 `from futures_quant.ai.X import`，根 `ai/` 包删除。符合方案 §8 文件结构约定。
- PPO 归位后夏普骤降（-199）→ 改进 `train` 为多轮 REINFORCE + 逐轮学习率衰减 + 独立评估环境重放，policy 夏普 144.6 > 随机 20.5，稳定通过。
- 工作区存在大量未提交改动，建议阶段性打 tag baseline-v4.0-P2。

## 下一步
P4 UI 与进化（M1.1~M1.6 UI/交互 + M7.1~M7.6 进化/自学习）。P3 已完场，可直接开 P4。

## P3 数据与 AI 融合（本轮完成 2026-09-20）
### M6 横截面 / 多模型 / 风险
- [x] M6.1 横截面打分 - `ai/cross_section.py`（compute_scores/rank_symbols/heatmap，39 品种 <2s），test_cross_section.py 全绿
- [x] M6.2 板块因子 - `analysis/sector.py`（SectorFactor：6 板块映射、因子收益、板块内 rank、成员相关度），test_sector.py 全绿
- [x] M6.3 多因子打分卡 - `analysis/scorecard.py`（技术面/量能/AI概率/板块 4 项，缺失→0.5 中性），test_scorecard.py 全绿
- [x] M6.4 多模型回放 - `ai/calibration_replay.py` 追加 MultiModelComparator（ridge/lstm/tcn/gbm 4 模型对比 + CSV 落盘），test_calibration_replay.py 全绿
- [x] M6.5 蒙特卡洛 - `risk/monte_carlo.py`（mc_equity：bootstrap 1000 次、P5/P50/P95），test_monte_carlo.py 全绿
- [x] M6.6 Brinson 归因 - `analysis/brinson_attribution.py`（配置/选股/交互 + 策略归因），test_brinson_attribution.py 全绿

### M8 市场信息
- [x] M8.1 新闻聚合 - `ai/news_feed.py` 追加 NewsAggregator（4 源并发 + 去重 + tfidf_sentiment∈[0,1]），test_news_feed.py 全绿
- [x] M8.2 持仓排行 - `data/position_rank.py`（多空 Top-N 占比、集中度、多空比），test_position_rank.py 全绿
- [x] M8.3 基差 / 权证 - `data/basis.py`（basis/basis_chg/basis_rank）+ `data/warrant.py`（warrant_factor：chg/supply_signal/z_score），test_basis.py 全绿
- [x] M8.4 宏观日历 - `data/macro_calendar.py`（MacroCalendar 30 事件/年 + mark_vol_amplification 事件窗口波动放大标记），test_macro_calendar.py 全绿
- [x] M8.5 综合信号面板 - `analysis/scorecard.py` 扩展 FULL_WEIGHTS 8 项（+news/position/basis/event），include_full=True 启用，test_scorecard_full.py 全绿
- [x] M8.6 政策事件预警 - `alerts/engine.py` 新增 event 规则类型 + scan_events（事件→阈值→通知，接 M8.4 MacroCalendar，冷却去重，单事件一次推送），test_alerts.py 全绿

### P3 阶段门禁（全部通过）
- [x] `python -m py_compile` 全 P3 文件绿
- [x] `test_all_pages.py` 全绿（rc=0）
- [x] `build_tools/secret_scan.py` 绿（exit 0，无密钥泄露）
- [x] P3 全 12 个模块 e2e 测试 rc=0（cross_section/sector/scorecard/calibration_replay/monte_carlo/brinson_attribution/news_feed/position_rank/basis/macro_calendar/scorecard_full/alerts）

### 修复的既有缺陷
- **build_features 契约错位（M5.1 遗留）**：`ai/features.py::build_features` 曾返回 2 元组 `(F, names)`，但 `predictor._features` / `ensemble` 按 3 元组 `(ind, F, names)` 解包，致 test_calibration_replay / test_features_no_lookahead / test_predictor_model ImportError。统一为 3 元组并同步 3 个测试。