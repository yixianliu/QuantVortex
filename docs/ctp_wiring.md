# CTP 实盘 / 模拟盘接入指南

本系统的回测、仿真、风控、策略逻辑均已实现并验证。实盘 / 仿真行情接入通过
`futures_quant/data/ctp_gateway.py` 的**可插拔适配器**完成，上层（行情中枢
`MarketDataManager` 与「实盘监控」页）只依赖 `DataFeed` 接口，业务代码零改动。

> ⚠️ 本仓库**不含**任何券商私密信息。账号密码只存在于本地 `ctp_settings.json`
> （已被 `.gitignore` 忽略），绝不提交到代码仓库。

---

## 一、前置条件（必须由期货公司 / SimNow 提供）

| 项目 | 说明 |
|------|------|
| CTP 动态库 | `vnpy_ctp` 或 `ctpbee` + 对应期货公司 `.dll`/`.so` |
| 前置地址 | 行情前置 `md_front`、交易前置 `td_front`（生产 / 仿真不同） |
| 账号信息 | `user_id`、`password`、`broker_id`（经纪商代码） |
| 授权码 | `app_id`、`auth_code`（SimNow / 期货公司提供） |

仿真推荐走 **SimNow 7x24** 环境，地址已内置于 `ctp_gateway.py` 的 `SIMNOW_*` 常量。

---

## 二、配置填写（安全管理）

复制模板并填入真实凭据（**不要**直接改 example 文件，example 入库、real 不入库）：

```bash
cp config/ctp_settings.example.json config/ctp_settings.json
# 编辑 config/ctp_settings.json，填入你的账号 / 密码 / 前置机
```

`ctp_settings.json` 结构：

```json
{
  "mode": "simnow",
  "simnow":   { "md_front": "...", "td_front": "...", "broker_id": "9999",
                "app_id": "simnow_client_test", "auth_code": "..." },
  "live":     { "md_front": "...", "td_front": "...", "broker_id": "...",
                "app_id": "...", "auth_code": "..." },
  "account":  { "user_id": "你的资金账号", "password": "你的密码" },
  "subscribe": ["rb.SHFE", "cu.SHFE", "IF.CFFEX"]
}
```

程序按以下顺序查找（优先可写的 data 目录，便于打包后落盘）：
1. `<data_dir>/ctp_settings.json`
2. `<项目根>/config/ctp_settings.json`

> 凭据加载逻辑见 `ctp_gateway.CTPCredentials.load()`；缺失时返回空凭据，
> `connect()` 会明确报告「凭据不完整」，**绝不伪造已连接**。

---

## 三、适配器架构（`ctp_gateway.py`）

| 组件 | 作用 |
|------|------|
| `CTPCredentials` | 凭据数据类；`complete` 属性校验必填项；`load()` 安全读取本地文件 |
| `CTPFeed(DataFeed)` | 真实行情适配器；懒加载 `vnpy_ctp` / `ctpbee`，缺失不崩溃 |
| `ctp_diagnose()` | 返回 `{lib_available, lib_name, creds_complete, mode, subscribe}`，供 UI 诊断面板 |

`CTPFeed` 关键行为：
- `connect()`：凭据不完整 → 报「凭据不完整」；CTP 库缺失 → 报「未安装 CTP 库」；
  两者皆备 → 尝试真实连接（vnpy / ctpbee 二选一），成功置 `connected=True`。
- `subscribe(symbol)` / `on_bar`：行情回报（Tick）转换为系统 `Bar` 字典并回调，
  由 `MarketDataManager._on_ctp_bar` 累加到实时序列并广播给 UI。
- `maybe_reconnect()`：断线后按退避策略（最多 5 次）自动重连。
- `source_label`：已连接显示「CTP(SimNow)/实盘·已连接」，否则显示「CTP未连接·回退合成」。

---

## 四、行情中枢对接（`data/market_data.py`）

`MarketDataManager` 把 `ctp` 作为一等数据源：
- `connect()`：调用 `feed.connect()`；成功则 `is_real=True`、`allow_sim=False`，
  并启动 30s 重连看门狗；失败则回退合成并**清晰标注**，不冒充实盘。
- `_period_real(period)`：仅当 `is_real` 为真时返回真实（sina 仅 D/W；
  ctp 全周期真实）。
- `_on_ctp_bar`：CTP 实时棒 → 累加到 live 游标 → 广播 `bar_arrived` / `quote_updated`。

切换数据源：在 `config/settings.json` 把 `data.source` 设为 `"ctp"`（默认 `"sina"`）。
程序启动时按该值装配；也可在「实盘监控」页点「连接柜台」手动触发。

---

## 五、实盘监控页（只读）

「实盘监控」页（`ui/ctp_monitor_page.py`，导航第 8 项）提供：
- 柜台连接状态卡：数据源 / 模式（SimNow / 实盘 / 合成回退）/ 连接状态；
- 连接诊断面板：展示「CTP 库是否安装 / 凭据是否完整 / 模式 / 订阅列表」及下一步指引；
- 订阅合约实时盘口表：由行情中枢回报驱动刷新（最新价 / 涨跌幅 / 量 / 持仓 / 资金流）；
- 持仓 / 委托只读占位：明确标注「交易侧未启用」。

> 本沙箱默认源为 sina（真实日线），CTP 未配置时盘口取自当前源；配置并连接 CTP 后
> 自动切换为实时盘口（需本机装有 CTP 库）。

---

## 六、真实连接代码骨架

### vnpy_ctp（需 vnpy 主引擎 / 事件引擎上下文）
```python
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy_ctp.gateway import CtpGateway
from vnpy.trader.object import SubscribeRequest
from vnpy.trader.constant import Exchange
from vnpy.trader.event import EVENT_TICK

ee = EventEngine(); me = MainEngine(ee); me.add_gateway(CtpGateway)
me.connect({"用户名": user_id, "密码": password, "经纪商代码": broker_id,
            "交易服务器": td_front, "行情服务器": md_front,
            "产品名称": app_id, "授权编码": auth_code}, "CTP")
ee.register(EVENT_TICK, on_tick)          # on_tick 累积成 Bar → feed.on_bar
for sym in subscribe:
    code, exch = sym.split(".")
    me.subscribe(SubscribeRequest(symbol=code,
                                  exchange=getattr(Exchange, exch, Exchange.SHFE)), "CTP")
```

### ctpbee（API 简洁，推荐）
```python
from ctpbee import CtpbeeApi
app = CtpbeeApi("futures_quant")
app.config.update(MD_ADDRESS=md_front, TD_ADDRESS=td_front, USER=user_id,
                  PASSWORD=password, BROKER=broker_id, APPID=app_id, AUTHCODE=auth_code)
app.on_tick = lambda tick: feed.on_bar(_tick_to_bar(tick))   # 转系统 Bar
app.start()
for sym in subscribe: app.subscribe(sym.split(".")[0])
```

---

## 七、上线建议（务必遵守）

1. **先用 SimNow / 期货公司模拟盘**充分验证行情接入与策略（至少 1~2 周）；
2. 小资金实盘试运行，观察滑点、拒单、断连重连；
3. 风控四道防线（单笔 / 单日 / 回撤 / 仓位）**默认开启**；
4. 任何异常触发 `RiskManager.halt()`，引擎自动停止开仓并平仓锁仓；
5. **交易侧默认不启用**：本系统定位为「行情分析 / KP预测 / 量化研判」，下单、
   持仓、委托功能需用户明确确认后另行开发（见 `core/engine.py` 的 `TradingEngine`）。

---

## 八、本沙箱的已知边界

本开发环境**未安装** `vnpy_ctp` / `ctpbee`，且**无法连接**期货公司前置机，因此：
- `ctp_diagnose()` 将报告 `lib_available=false`；
- 点击「连接柜台」会返回「未安装 CTP 库」并回退合成行情，界面如实标注；
- 真实登录需在**用户本机**装好 CTP 库 + 填入 `ctp_settings.json` 后验证。

> 以上由 AI 基于项目现状整理，仅供参考，不构成投资建议。投资有风险，决策需谨慎。
