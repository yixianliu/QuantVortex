# R4 真实行情 / 合约规格接入 — 完成总结

> 回测中心深化计划（R1 绩效图表 → R2 手动/交割 → R3 双向联动 → **R4 真实数据**）收官项。
> 完成日期：2026-07-28。任务 #51~#55。

## 做了什么
把回测引擎从「合成 universe + 全品种统一 10% 保证金 / 3 元手续费」升级为「**真实合约规格 + 真实历史行情**」。回测中心现在能跑在真实螺纹钢主力日线上，并按品种真实保证金率、手续费、乘数、杠杆结算。

## 关键决策：决策节点 C 裁决（偏离原计划 C1）
原计划建议 C1(Neodata) 优先。实测沙箱环境后改采 **C2(akshare) + C3(csv 离线兜底)**：
- ✅ **akshare 1.18.64 已装、免费、零认证**，沙箱实测可联网拉真实期货日线（`futures_zh_daily_sina('rb0')` 返回 4208 根真实螺纹钢主力日线 2009–2023）。
- ❌ **Neodata connector 当前 `disconnected`** 且涉及额度/计费 → 不采用。
- ✅ **CsvFeed 离线回放**作为兜底，保证测试封闭可复现。

## 新增 / 改动文件
| 文件 | 作用 |
|------|------|
| `futures_quant/data/contract_specs.py` | 品种级真实规格注册表（乘数/最小变动价位/保证金率/按手手续费/杠杆/平今优惠/交割日）；`get_contract_spec(sym)` / `build_contract(sym, **overrides)` |
| `futures_quant/data/akshare_feed.py` | `AkshareFeed(DataFeed)` 真实源（日线/周线）；列映射 `date→datetime`、`hold→open_interest`、丢弃 `settle`；非日线周期回退合成；按 (symbol,period) 缓存到 `data/akshare_cache/` |
| `futures_quant/data/csv_feed.py` | `CsvFeed(DataFeed)` 本地 CSV 离线回放（封闭可复现） |
| `futures_quant/data/collect_real_samples.py` | 采集团队脚本，akshare → 落盘 `data/real_samples/` |
| `futures_quant/data/market_data.py` | `_build_feed` 新增 `source="akshare"/"csv"`；`connect()`/`_period_real()` 视 akshare 为真实日线源（同 sina） |
| `futures_quant/ui/backtest_page.py` | 自动/手动两处 `Contract` 构造 + 账户级 `cfg.account.margin_rate/commission_per_lot/multiplier/leverage` 接入真实值 |

## 关键技术点
- **真实规格生效点**：`Portfolio` 用**账户级** `cfg.account.margin_rate/commission_per_lot/multiplier/leverage`，**不是** `Contract` 上的同名字段（后者在回测链里没被读）。两处回测路径都已设为品种真实值。
- **自动模式**：`build_contract(sym)` 构造合约 + 账户级取 spec。
- **手动模式**：保留 UI 覆盖（杠杆/保证金/乘数/交割日），仅手续费/tick 取真实规格（UI 无该字段）。

## 验证结果
- 新增 `tests/e2e/test_backtest_real_akshare.py`：**全部通过**
  - A 规格注册表（含平今免品种识别、未知品种兜底）
  - B `CsvFeed` 离线回放（rb.SHFE 真实样本 2432 根，列齐全、日期过滤正确）
  - C/D 真实回测：资金曲线 2432 点、**339 笔成交**、末权益 1,001,090、总收益 0.1%、最大回撤 3.0%、胜率 45%、盈亏比 1.01
  - E `AkshareFeed` 直连可达（best-effort，联网失败不报错）
- 回归：`test_all_pages`(6/6) / `test_backtest_futures` / `test_backtest_linkage` 全部 `rc=0`
- `py_compile`：COMPILE_OK

## 真实样本
- `data/real_samples/rb_SHFE_D.csv`（akshare 拉取，4208 根真实螺纹钢主力日线，列已规范为 DataFeed 标准）

## 可选下一步
- 采集更多品种真实样本（`i.DCE` / `au.SHFE` / `IF.CFFEX` 等，采集脚本已支持）
- 单月合约交割日规格（当前主力连续 `delivery_date=None`）
- 分钟线真实源（需扩展 akshare 接口，当前仅日线/周线真实）
