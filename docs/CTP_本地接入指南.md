# CTP 本地接入完整操作指南

> 📌 本指南帮助用户在**本机**完成 CTP 行情接入的完整流程：安装依赖 → 配置凭据 → 启动测试 → 诊断验证。

---

## 一、前置准备

### 1.1 环境要求
- Windows 系统（或 Linux/Mac，本指南以 Windows 为主）
- Python 3.8+（推荐使用项目已有的 anaconda 环境）
- 期货公司账号 或 SimNow 仿真账号

### 1.2 获取 SimNow 仿真账号（免费）
1. 访问 [SimNow 官网](http://www.simnow.com.cn)
2. 注册仿真账号（需手机号验证）
3. 登录查询你的：
   - **用户名**（资金账号）
   - **密码**
   - **经纪商代码**：`9999`（SimNow 默认）
   - **AppID**：`simnow_client_test`
   - **AuthCode**：`0000000000000000`（SimNow 仿真专用）

---

## 二、安装 CTP 库

本项目支持 `vnpy_ctp` 和 `ctpbee` 两种 CTP 适配器，推荐优先使用 **ctpbee**（API 更简洁）。

### 2.1 安装 ctpbee（推荐）

```bash
# 进入项目根目录
cd D:\PythonProject\QuantVortex

# 使用项目已有的 anaconda python
D:/anaconda3/python.exe -m pip install ctpbee pandas numpy PyQt6
```

如果安装失败，尝试指定国内镜像源：
```bash
D:/anaconda3/python.exe -m pip install ctpbee pandas numpy PyQt6 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2.2 或使用 vnpy_ctp（备选）

```bash
D:/anaconda3/python.exe -m pip install vnpy vnpy_ctp
```

---

## 三、配置凭据

### 3.1 复制模板文件

```cmd
cd D:\PythonProject\QuantVortex\config
copy ctp_settings.example.json ctp_settings.json
```

### 3.2 编辑配置文件

用记事本或 VS Code 打开 `config/ctp_settings.json`，填入你的信息：

```json
{
  "mode": "simnow",
  "simnow": {
    "md_front": "tcp://180.168.146.187:10211",
    "td_front": "tcp://180.168.146.187:10201",
    "broker_id": "9999",
    "app_id": "simnow_client_test",
    "auth_code": "0000000000000000"
  },
  "live": {
    "md_front": "",
    "td_front": "",
    "broker_id": "",
    "app_id": "",
    "auth_code": ""
  },
  "account": {
    "user_id": "你的SimNow用户名",
    "password": "你的SimNow密码"
  },
  "subscribe": ["rb.SHFE", "cu.SHFE", "IF.CFFEX"]
}
```

**注意**：
- `mode` 设为 `"simnow"`（仿真）或 `"live"`（实盘）
- `subscribe` 列表为你想订阅的合约代码
- `ctp_settings.json` 已被 `.gitignore` 忽略，**安全不入库**

---

## 四、切换数据源并启动

### 4.1 修改 settings.json

编辑 `config/settings.json`，将数据源设为 `"ctp"`：

```json
{
  "data": {
    "source": "ctp",
    "sqlite_path": "data/quant_analysis.db"
  },
  "ui": {
    "theme": "dark"
  }
}
```

### 4.2 启动程序

```bash
cd D:\PythonProject\QuantVortex
D:/anaconda3/python.exe main.py
```

或在 EXE 直接运行：
```cmd
dist\FuturesQuant\FuturesQuant.exe
```

---

## 五、验证与诊断

### 5.1 查看「实盘监控」页

在主窗口左侧导航点击 **「实盘监控」** 页面，查看：

1. **连接状态卡**：显示当前数据源模式、连接状态
2. **CTP 诊断面板**：
   - `lib_available`: 是否检测到 CTP 库
   - `creds_complete`: 凭据是否完整
   - `mode`: 当前模式（SimNow/实盘）
   - `subscribe`: 订阅合约列表

### 5.2 常见问题排查

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| "未安装 CTP 库" | `ctpbee` 或 `vnpy_ctp` 未安装 | 执行第二步安装 CTP 库 |
| "凭据不完整" | `ctp_settings.json` 缺失或未填 | 检查配置文件格式和用户信息 |
| "连接超时" | 网络问题或前置机地址错误 | 确认 SimNow 地址可用，检查防火墙 |
| "鉴权失败" | AuthCode 或 AppID 错误 | 确认使用 SimNow 仿真专用凭据 |

### 5.3 命令行诊断

运行以下命令快速诊断：

```bash
cd D:\PythonProject\QuantVortex
D:/anaconda3/python.exe -c "
from futures_quant.data.ctp_gateway import ctp_diagnose, CTPCredentials
d = ctp_diagnose()
print('诊断结果:', d)
c = CTPCredentials.load()
print('凭据完整:', c.complete)
print('模式:', c.mode)
"
```

---

## 六、从仿真过渡到实盘

当 SimNow 仿真稳定运行后，切换到实盘：

1. 联系你的期货公司，获取：
   - 行情前置地址 (`md_front`)
   - 交易前置地址 (`td_front`)
   - 经纪商代码 (`broker_id`)
   - AppID 和 AuthCode

2. 编辑 `ctp_settings.json`：
   ```json
   {
     "mode": "live",
     "live": {
       "md_front": "tcp://xxx.xxx.xxx.xxx:xxxx",
       "td_front": "tcp://xxx.xxx.xxx.xxx:xxxx",
       "broker_id": "你的经纪商代码",
       "app_id": "xxx",
       "auth_code": "xxx"
     },
     ...
   }
   ```

3. **先用小资金试运行**，观察滑点、拒单、断连重连等情况。

---

## 七、安全提醒

- ✅ `ctp_settings.json` 已被 `.gitignore` 忽略，不会提交到代码仓库
- ✅ 如需分享配置，请使用 `ctp_settings.example.json` 模板
- ❌ 绝对不要将 `ctp_settings.json` 上传到任何公开仓库
- ⚠️ 实盘交易有风险，请严格遵守第七条的上线建议

---

## 八、技术支持

如遇问题，请按以下步骤收集信息：

1. 运行诊断脚本，保存输出
2. 检查 `logs/` 目录下的日志文件
3. 截图「实盘监控」页面的诊断面板
4. 提供 Python 版本：`python --version`

> 本系统定位为「行情分析 / KP预测 / 量化研判」工具，不做自动交易。
> 下单、持仓、委托功能需用户明确确认后另行开发。

---

> 以上内容基于项目现状整理，仅供参考。投资有风险，决策需谨慎。
