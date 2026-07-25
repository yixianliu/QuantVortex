# CTP 接入验证操作指南

## 前置条件 (已完成)

- ✅ ctpbee 1.7.5 已安装 (`D:\anaconda3\Lib\site-packages\ctpbee\`)
- ✅ `config/ctp_settings.json` 已配置 SimNow 凭据
  - USER_ID: yixianliu
  - PASSWORD: fanchen2011!
  - MD_FRONT: tcp://180.168.146.187:10211
  - TD_FRONT: tcp://180.168.146.187:10201
  - BROKER: 9999 (SimNow)
- ✅ CTP 连接测试通过 (耗时 0.2s, 无报错)
- ✅ 9/9 GUI 页面冒烟测试通过

---

## 操作步骤

### 步骤 1: 启动 GUI 主程序

```bash
cd D:\PythonProject\QuantVortex
python main.py --theme light
```

### 步骤 2: 导航到 "实盘监控" 页面

在左侧导航栏点击 **"实盘监控"** (或 "CTPMonitorPage")

### 步骤 3: 查看诊断面板

页面应显示:
- **CTP 库检测**: ✅ ctpbee 1.7.5
- **凭据状态**: ✅ 完整
- **模式**: SimNow 仿真
- **已订阅合约**: rb.SHFE, cu.SHFE, IF.CFFEX, au.SHFE

### 步骤 4: 测试连接 (非交易时段)

当前时间 (周四上午): 非交易时段
- SimNow 7x24 仿真仅在 **夜间交易时段 (21:00-02:30)** 有实时行情
- 白天的 "连接" 按钮会显示: "已连接 · CTP仿真(库: ctpbee)"
- 但不接收实时 tick/bar 数据 (正常现象)

### 步骤 5: 交易时段验证实时数据

**今晚 21:00-02:30** (或任何交易日交易时段):
1. 再次运行 GUI: `python main.py`
2. 进入 "实盘监控" 页面
3. 点击 "连接" 按钮
4. 观察是否收到实时 tick/Bar 数据
5. 数据流应在 K线图、市场监控等页面同步显示

---

## 故障排查

### 问题 1: 连接失败 "没有发现登录信息"

**原因**: ctpbee `CONNECT_INFO` 配置格式错误  
**解决**: 已修复 — 确保使用最新代码 (`futures_quant/data/ctp_gateway.py`)

### 问题 2: refresh_query 线程报错

**错误信息**: `AttributeError: 'NoneType' object has no attribute 'query_account'`  
**原因**: TD_FUNC=False 时不应启动 refresh_query 线程  
**解决**: 已修复 — 在 `start()` 前设置 `r_flag = False`

### 问题 3: 非交易时段无数据

**正常现象**: SimNow 7x24 仅在 **21:00-02:30** 提供实时行情  
**解决方案**: 
- 白天测试: 连接成功即可,不期待收到 tick
- 夜晚测试: 21:00后重新连接,应能收到实时数据

---

## 技术细节

### SimNow 7x24 仿真环境

| 项目 | 值 |
|------|-----|
| MD Front | tcp://180.168.146.187:10211 |
| TD Front | tcp://180.168.146.187:10201 |
| Broker ID | 9999 |
| App ID | simnow_client_test |
| Auth Code | 0000000000000000 |

### 已订阅合约

- rb.SHFE (螺纹钢)
- cu.SHFE (铜)
- IF.CFFEX (沪深300股指期货)
- au.SHFE (黄金)

### CTP 工作流程

```
CTPCredentials.load() → CTPFeed.connect() → ctpbee start() → init_interface()
    ↓
CONNECT_INFO dict {userid, password, brokerid, md_address}
    ↓
BeeMdApi.connect(info) → registerFront(md_address) → init()
    ↓
on_tick(tick) → _on_ctpbee_tick() → feed.on_bar(bar) → UI 更新
```

---

## 后续计划

1. ✅ **已完成**: CTP 接入框架搭建 + 凭据管理
2. ✅ **已完成**: SimNow 连接测试 (非交易时段验证)
3. ⏳ **待验证**: 交易时段实时行情接收 (今晚21:00后)
4. 📋 **下一步**: 重新构建 EXE 安装包 (包含最新CTP修复代码)
5. 📋 **可选**: 申请证书签名 EXE 安装包

---

## 相关文档

- `docs/CTP_本地接入完整步骤.md` — 10分钟快速操作清单
- `docs/SimNow注册完全指南.md` — 手把手注册教程
- `futures_quant/data/ctp_gateway.py` — CTP 行情适配器源码
