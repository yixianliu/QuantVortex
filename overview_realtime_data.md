# 交付概览 · 接入实盘数据（新浪公开期货接口）

## 本轮目标
在「期货智能分析预测系统」基础上**真正接入实盘数据**，并把数据源做成可插拔（合成 / 新浪实盘 / CTP 柜台），同时不伪造任何行情。

## 核心结论
- 沙箱 Python 运行时**可访问外网**；新浪期货公开日线接口**39/39 品种主力连续合约全部可用**（真实历史从上市日延续至 2026-07-20）。
- 新增 `SinaFeed` 后，系统默认即走**真实日线/周线**：AI 预测、指标、市场全景、回测验证全部基于真实行情运行。
- 实盘数据以**真实日线/周线**为主干；日内周期免费接口不提供历史分钟线，由 `MarketDataManager` 自动回退合成并明确标注，**绝不冒充实盘**。

## 交付内容
1. **`futures_quant/data/sina_feed.py`** — `SinaFeed(DataFeed)`：新浪公开 HTTP 接口拉真实日线；D 真实、W 由日线重采样；日内返回 None 交回退；磁盘+内存双缓存（默认 6h 新鲜度）；网络失败 stale 缓存兜底；符号映射 `rb.SHFE→rb0`。
2. **`futures_quant/data/market_data.py`**（改）— `MarketDataManager` 按 `config.data.source` 可插拔构建 feed；sina 探测失败自动回退 synthetic；新增 `_period_real()` 让 sina 模式下 quote/全景始终用真实日线；实时流在真实源下改为重放真实棒+刷新最新真实棒，不再随机游走伪造。
3. **`config/settings.json`**（改）— 默认 `data.source=sina` + `sina_cache_dir`。
4. **`examples/sina_demo.py`**（新）— 拉 rb/cu/au/IF/m/T 真实日线，跑指标+AI 预测，输出真实数值并保存 `output/sina_*_forecast.png`（图表标题/图例已英文化，无 CJK 豆腐警告）。
5. **文档** — README 第六章节改为「接入实盘行情」（三源表 + 实盘关键事实 + 健壮性/缓存说明）；`ctp_gateway.py` 注明 `SinaFeed` 为免密钥实盘路径；`docs/ui_design.md` 增加数据源说明。
6. **截图** — 重截 12 张六页深/浅截图（默认 sina 真实数据），直观展示真实 K 线与真实全景。

## 验证
- `python main.py --test` → 核心模块可导入 OK；`python -m py_compile` 全部 OK。
- `MarketDataManager()`（不传参）自动 `source=sina`，`connect()` → `已连接 · 新浪实盘日线`；`get_quote`/`compute_panorama` 用真实数据（全景 39 行，鸡蛋 +26.31% 领涨）。
- `examples/sina_demo.py` → 6 品种全部跑通真实数据 + LSTM 预测（如 rb 最新 3096、au 趋势行情空头共振、IF p_up 0.77 等）。
- `examples/test_core.py` → 在 sina 默认下仍 `ALL CORE LAYERS OK`（网络可用走真实，不可达自动回退合成，离线也不崩）。

## 实盘数据边界（诚实声明）
- 免费接口仅**日线/周线真实**；日内历史分钟线需接 CTP 柜台（tick 级）方可得。
- 实时为「最新真实日线棒」，非秒级推送；交易时段内若新浪追加当日棒会自然刷新。
- 新浪为公开行情服务，仅供学习与复盘，实盘交易请以期货公司授权数据为准。

> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
