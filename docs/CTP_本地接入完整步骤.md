# CTP 本地接入 - 完整操作步骤

## ✅ 已完成的部分

- [x] CTP 库安装 (`ctpbee 1.7.5`)
- [x] 配置文件模板创建 (`config/ctp_settings.json`)
- [x] 诊断验证通过：`lib_available=True`, `creds_complete=True`

## 📝 您需要做的 3 步操作

### 第 1 步：注册 SimNow 仿真账号（免费，约 5 分钟）

1. 访问 **http://www.simnow.com.cn**
2. 点击"注册"，填写：
   - 手机号（需短信验证）
   - 邮箱
   - 设置密码
3. 注册成功后，登录查询您的：
   - **用户名**（就是资金账号，通常是数字）
   - **密码**

> 💡 SimNow 是上期技术提供的免费仿真环境，用于测试 CTP 接入，无需真实资金

### 第 2 步：更新配置文件（约 2 分钟）

用记事本或 VS Code 打开这个文件：
```
D:\PythonProject\QuantVortex\config\ctp_settings.json
```

找到第 18-20 行，将占位符替换为您的实际信息：

**修改前：**
```json
"account": {
    "user_id": "你的SimNow用户名",
    "password": "你的SimNow密码"
},
```

**修改后（示例）：**
```json
"account": {
    "user_id": "12345678",
    "password": "mypassword123"
},
```

⚠️ **注意**：
- 只改 `user_id` 和 `password`，其他保持不动
- 不要删除引号
- 保存文件

### 第 3 步：测试连接

在命令行运行以下命令测试：

```cmd
cd D:\PythonProject\QuantVortex
D:\anaconda3\python.exe -c "
from futures_quant.data.ctp_gateway import CTPCredentials, CTPFeed
creds = CTPCredentials.load()
feed = CTPFeed(creds)
ok = feed.connect()
print('连接状态:', '✓ 成功' if ok else '✗ 失败')
"
```

**预期结果：**
- ✅ 如果显示 `✓ 成功` → 恭喜！CTP 接入完成，可以启动程序使用实时行情了
- ❌ 如果显示 `✗ 失败` → 请检查：
  1. 用户名和密码是否正确
  2. 网络是否能访问 SimNow 服务器（tcp://180.168.146.187:10211）
  3. SimNow 账号是否已激活（如需登录 SimNow 官网激活）

## 🚀 连接成功后

1. **修改数据源配置**：打开 `config/settings.json`，将 `"source": "sina"` 改为 `"source": "ctp"`
2. **启动程序**：运行 `D:\anaconda3\python.exe main.py` 或双击 EXE
3. **查看实时行情**：导航到"实盘监控"页面，应该能看到实时盘口数据

## 📊 各页面数据源变化

| 页面 | 使用 sina 时 | 使用 CTP 时 |
|------|-------------|------------|
| 行情全景 | 合成行情（模拟） | 实时 tick 数据 |
| 指标分析 | 合成行情 | 实时行情 |
| AI 预测 | 合成行情历史数据 | 实时数据预测 |
| 选品机会 | 合成日线数据 | 实时入手信号 |
| 预警中心 | 合成数据触发 | 实时异动推送 |

## ⚠️ 重要提醒

1. **这是仿真环境**：SimNow 提供的是仿真行情，不是真实交易
2. **不要在这里下单**：本系统定位为"行情分析/AI 预测"工具，未实现自动交易功能
3. **首次连接可能较慢**：CTP 建立连接需要几秒到几十秒
4. **保留凭据安全**：`ctp_settings.json` 已被 `.gitignore` 忽略，不会提交到代码仓库

## 🆘 常见问题

**Q: 连接一直超时怎么办？**
A: 检查网络防火墙是否阻止了对 `180.168.146.187` 的访问，尝试更换网络（手机热点）

**Q: 提示"鉴权失败"？**
A: 确认用户名密码正确，且 SimNow 账号已激活

**Q: 如何切换到期货公司实盘？**
A: 联系您的期货公司获取：
- 行情前置地址 (`md_front`)
- 交易前置地址 (`td_front`)
- 经纪商代码 (`broker_id`)
- AppID 和 AuthCode
然后编辑 `ctp_settings.json`，将 `mode` 改为 `"live"`，填入上述信息

---

> 本指南基于项目现状整理，仅供参考。投资有风险，决策需谨慎。
