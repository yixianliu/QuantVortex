# CTP 接入 - 10分钟快速操作清单

> ✅ 按照以下步骤操作，10 分钟内完成 CTP 仿真连接配置

---

## 📋 操作清单（逐条核对）

### □ 第 1 步：注册 SimNow 账号（5 分钟）
- [ ] 访问 http://www.simnow.com.cn
- [ ] 点击"开户"或"注册"
- [ ] 填写手机号、邮箱、设置密码
- [ ] 接收短信验证码并完成验证
- [ ] 注册成功 ✓

### □ 第 2 步：查询账号信息（2 分钟）
- [ ] 登录 SimNow 官网
- [ ] 找到"我的账号"或"账户信息"
- [ ] 记录 **用户名**（资金账号，9位数字）
- [ ] 记录 **密码**（您设置的登录密码）

### □ 第 3 步：编辑配置文件（1 分钟）
用记事本打开 `D:\PythonProject\QuantVortex\config\ctp_settings.json`

找到第 18-21 行：
```json
"account": {
    "user_id": "你的SimNow用户名",
    "password": "你的SimNow密码"
},
```

将 `"你的SimNow用户名"` 替换为您的实际用户名  
将 `"你的SimNow密码"` 替换为您的实际密码

**示例**（假设您的用户名是 `123456789`, 密码是 `MyPass123`）：
```json
"account": {
    "user_id": "123456789",
    "password": "MyPass123"
},
```

保存文件 (Ctrl + S) ✓

### □ 第 4 步：测试连接（1 分钟）
打开命令行（CMD 或 PowerShell），运行：

```cmd
cd D:\PythonProject\QuantVortex
D:\anaconda3\python.exe -c "from futures_quant.data.ctp_gateway import CTPCredentials, CTPFeed; creds = CTPCredentials.load(); feed = CTPFeed(creds); print('✓ 连接成功' if feed.connect() else '✗ 连接失败')"
```

如果显示 `✓ 连接成功` → 恭喜！配置完成 ✓  
如果显示 `✗ 连接失败` → 检查错误信息并联系技术支持

### □ 第 5 步：使用实时行情（可选）
修改 `config/settings.json` 中 `"source": "sina"` 为 `"source": "ctp"`

启动程序后，导航到"实盘监控"页面查看实时数据

---

## 🔍 验证清单

完成后检查以下项目是否全部通过：

- [x] CTP 库已安装（`ctpbee 1.7.5`）
- [ ] SimNow 账号已注册
- [ ] 配置文件已更新
- [ ] 连接测试成功
- [ ] 程序能正常显示实时行情

---

## ❗ 常见问题速查

| 问题 | 解决方法 |
|------|---------|
| 收不到短信验证码 | 检查手机号是否正确，等待1分钟后重试 |
| 用户名/密码错误 | 确认大小写，尝试"忘记密码"重置 |
| 连接超时 | 检查网络，确认SimNow服务器可访问 |
| JSON格式错误 | 确保引号完整，不要删除逗号 |

---

## 🆘 需要帮助？

- 详细注册教程：`SimNow注册完全指南.md`
- 完整接入文档：`CTP_本地接入完整步骤.md`
- 技术对接文档：`ctp_wiring.md`

---

> ⏱️ 预计耗时：10-15分钟  
> 🔐 安全提示：配置文件不会被提交到代码仓库
