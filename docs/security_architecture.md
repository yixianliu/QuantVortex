# 客户端密钥安全架构与运维手册

> 面向公众分发的桌面程序，如何做到「AI 能力可用」且「上游密钥不泄露」。

---

## 一、为什么不能把密钥硬编码进 exe

最初的方案是「把 API 密钥、端点、参数全部硬编码在源码里，再做代码混淆和反调试」。
这个方案在**面向公众分发**的前提下是无法成立的，原因不是实现不够好，而是威胁模型不成立：

| 防护手段 | 攻击者的破解成本 |
|---|---|
| 编译成 exe | `pyinstxtractor` 解包 → `strings` 直接搜出密钥，约 2 分钟 |
| 代码混淆 | 字符串常量最终必须以明文进入内存才能发请求，内存转储即得 |
| 反调试 | Python 运行时本身就是调试器；`sitecustomize.py` / 环境变量即可绕过 |
| HTTPS/TLS | 攻击者控制自己的机器，装一张自签 CA 用 mitmproxy 就能读 `Authorization` 头 |

**根本矛盾**：程序必须能用密钥，就必须能读到密钥；程序运行在用户的机器上，用户就能读到程序能读到的一切。
这不是工程问题，是信息论问题。

一旦泄露，后果是**你的计费账户**被人拿走，而你唯一的止损手段是吊销密钥 —— 这会让所有已发布的客户端同时失效。

---

## 二、采用的架构：后端代理

```
桌面客户端  --(短期令牌, 1小时)-->  自建代理服务  --(真实密钥)-->  上游 AI
   可被逆向                          你的服务器                    计费账户
```

客户端里能被挖出来的东西，只有三样：

1. 代理地址（`QV_PROXY_BASE`）
2. release key（一道低强度门槛，可随版本轮换）
3. 一个 1 小时有效期的设备令牌

**这三样你都能随时轮换、限流、按设备封禁，且都不涉及计费账户。**
上游真实密钥从未离开过服务器。

### 目录结构

| 路径 | 职责 |
|---|---|
| `server/config.py` | 配置加载；上游密钥只存在于本进程内存 |
| `server/auth.py` | 设备注册、短期令牌签发与校验、封禁名单 |
| `server/ratelimit.py` | 按设备令牌桶限流，防额度被刷穿 |
| `server/upstream.py` | **唯一持有真实密钥的模块**；双密钥轮换 + 错误消毒 |
| `server/app.py` | FastAPI 路由与统一异常处理 |
| `futures_quant/ai/llm_client.py` | 客户端唯一大模型出口，不持有任何上游密钥 |
| `futures_quant/utils/redact.py` | 日志/异常/traceback 全链路脱敏 |
| `build_tools/secret_scan.py` | 构建门禁：源码 + 二进制产物密钥扫描 |

---

## 三、部署代理服务

```bash
pip install -r server/requirements.txt

# 必填
export QV_UPSTREAM_BASE="https://apihub.example.com/v1"
export QV_UPSTREAM_KEY="<上游真实密钥>"
export QV_JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"

# 建议填
export QV_APP_RELEASE_KEY="<随客户端分发的应用级 key>"
export QV_ADMIN_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
export QV_RATE_PER_MIN=20
export QV_ALLOWED_MODELS="agnes-2.0-flash"

uvicorn server.app:app --host 0.0.0.0 --port 8787
```

生产环境请置于 Nginx/Caddy 之后并启用 HTTPS，用 systemd / supervisor 守护进程。
**密钥只放在进程环境变量或密钥管理服务里，永远不要写进仓库、镜像层或配置文件。**

配置缺失时服务会**拒绝启动**并列出全部缺失项 —— 宁可起不来，也不要带病运行。

### 客户端配置

```bash
QV_PROXY_BASE=https://ai.yourdomain.com
QV_APP_RELEASE_KEY=<与服务端一致>
```

未配置时客户端自动降级为本地规则合成，**功能不中断**，只是没有大模型润色。

---

## 四、密钥轮换手册（生产在用、不能停）

现有那把已泄露的密钥正在生产中使用，不能直接吊销。用双密钥做平滑切换：

### 第 1 步：申请新密钥
在上游服务商后台新建一把密钥，**先不要吊销旧的**。

### 第 2 步：新旧并存，重启服务
```bash
export QV_UPSTREAM_KEY="<新密钥>"        # 主：承载全部正常流量
export QV_UPSTREAM_KEY_OLD="<旧密钥>"    # 备：仅在主密钥鉴权失败时兜底
```
重启代理。此时：
- 新密钥没问题 → 全部流量走主密钥，备用密钥一次都不会被用到；
- 新密钥配错了 → 自动落到旧密钥，**业务零中断**，同时状态接口报警提示你去修。

### 第 3 步：观察，确认可以收尾
```bash
curl -H "X-Admin-Token: $QV_ADMIN_TOKEN" https://ai.yourdomain.com/v1/admin/keystate
```
```json
{
  "primary":   {"success": 1284, "auth_fail": 0},
  "secondary": {"success": 0,    "auth_fail": 0},
  "safe_to_revoke_old_key": true,
  "hint": "secondary 未承载任何成功请求，可去服务商后台吊销旧密钥"
}
```
判定口径：`secondary.success == 0` 且 `primary.success > 0` → 旧密钥已完全没有流量。
建议观察至少一个完整业务周期（含日终、周末等低峰时段）。

### 第 4 步：吊销
1. 到服务商后台**吊销旧密钥**；
2. 清空 `QV_UPSTREAM_KEY_OLD`，重启代理；
3. 再查一次 `keystate`，确认 `has_secondary_key: false`。

全程业务无中断。

### 紧急情况
- **发现有人在刷额度** → `POST /v1/admin/ban {"device_id": "..."}` 封禁单台设备。
- **令牌被批量盗用** → 换一个 `QV_JWT_SECRET` 并重启，**所有已签发令牌立即全部失效**，客户端会自动重新注册。这个操作不影响上游密钥，代价极小。

---

## 五、纵深防御的其余几层

### 1. 运行时脱敏（输出侧拦截）
`futures_quant/utils/redact.py` 在**输出侧**统一拦截，无论上游代码是否小心，密钥都不会成文：
- 覆盖 `sk-` / `AKIA` / `ghp_` / `AIza` / `xox?-` / `Bearer` / `Basic` / JWT / 私钥块 / URL 内凭据 / 查询参数 / 字典赋值；
- 已接入 logger 的 filter 与 formatter（formatter 会连 traceback 一起洗）；
- `sys.excepthook` 与 `threading.excepthook` 均已替换，未捕获异常打到控制台前也会脱敏；
- `register_secret()` 可登记运行时才知道的精确值（如服务端下发的令牌），即便它不匹配任何通用规则也必被抹除。

设计取向：**宁可过度脱敏，也不能漏**。日志可读性让位于密钥安全。

### 2. 构建门禁（强制，无法用环境变量关闭）
`build_tools/build_exe.py` 在打包前后各扫一遍：
- **构建前**：扫源码树，命中即 `exit 3`，不产出任何东西；
- **构建后**：对 `dist/` 做**字节级**扫描（exe / dll / pyd / pyc 全覆盖），命中即 `exit 4`；
- **构建后**：查产物里有没有混入**本地凭据文件**，命中即 `exit 7`。

`.pyc` 一律按二进制扫描 —— **编译不是加密**，字符串常量原样保留。
本项目历史上正是在 `api_docs/__pycache__/` 里泄露过真实密钥。

误报的唯一逃生口是在该行加 `# secret-scan: allow`。这个标记会留在代码里被 review 看到 ——
**不要给扫描器加宽泛白名单，白名单过宽等同于关掉扫描。**

#### 关于第三方库造成的 `sk-` 误报

打包产物里会捆绑大量第三方二进制，其中有些字符串长得像密钥：

| 来源 | 字符串 | 实际含义 |
|---|---|---|
| `libssh2.dll` | `sk-ecdsa-sha2-nistp256-cert-v01@openssh.com` | OpenSSH FIDO 密钥**类型名** |
| `babel/*.dat` | `sk-Kamchatski-standaardtyd` | 时区名 Petropavlovsk-Kamchatski |
| 示例 JSON | `sk-definition-1470764550877` | `task-definition-<时间戳>` |
| `Qt6Network.dll` | `-----BEGIN RSA PRIVATE KEY-----` | PEM 类型枚举常量（无密钥体） |

处理这类误报时**不要逐个拉黑关键词** —— 每换一个依赖就要补一次，而且极易顺手把真密钥排除掉。
这里踩过一次实实在在的坑：曾用 `(?![A-Z])` 排掉城市名，结果**所有大写字母开头的真密钥全部漏检**，
是 `.pyc` 取证用例先炸出来的。

正确做法是抓本质差异：上表的误报全都是**连字符拼接的英文单词**，最长连续字母数字段都 < 20 位；
而真实密钥的主体必然是一整段高熵连续字符。故规则按「连续主体长度 ≥ 20」判别，
私钥则要求 `-----BEGIN` 与 `-----END` 之间存在 ≥ 100 字符的 base64 体。

#### 本地凭据文件门禁（正则扫描抓不到的那一类）

密钥扫描靠 `sk-` / `-----BEGIN PRIVATE KEY-----` 这类**特征前缀**工作。
但期货账户凭据长这样：

```json
{ "broker_id": "9999", "user_id": "123456", "password": "..." }
```

没有任何可匹配的前缀 —— **字节级扫描对它完全无效**。

`config/ctp_settings.json` 按设计就是存放实盘账号密码的（所以它在 `.gitignore` 里），
而 spec 原本是整目录 `datas.append((config_dir, "config"))`，会把它一并打进
面向公众分发的 exe。当时机器上只有 SimNow 公开测试参数所以没出事，
但只要开发者哪天填了实盘账号再打包，凭据就随 exe 流出去了。

两道防线，源头 + 产物各一道：

| 位置 | 机制 |
|---|---|
| `futures_qt.spec` | 逐文件收集 `config/`，命中 `CONFIG_DENY` 名单的直接不收（构建日志会打印跳过了哪些） |
| `build_exe.py` | 产物侧复查文件名，命中即 `exit 7` —— 防的是将来换打包方式（改 spec / 加 `--add-data` / 加 hook）后重新漏出去 |

放行名单只有 `cacert.pem`（certifi 与 botocore 各带一份的公开 CA 信任链，只含公钥证书）。
**这个白名单必须保持极小**：它一放宽，门禁就开始天天误报，接着就会被人关掉。

最终用户自己在 exe 同级 `data/` 或 `config/` 放 `ctp_settings.json` 即可，运行时查找逻辑不变；
产物里只带 `ctp_settings.example.json` 模板。

`tests/test_security_redaction.py::test_scanner_precision` 把误报与漏检**两个方向同时钉死**：
良性串一个都不许命中，真密钥（含大写开头、全字母无数字、`sk-proj-`、`sk-ant-api03-` 各形态）一个都不许漏。
今后再调扫描规则，先跑这个用例。

### 3. 打包产物剔除字节码缓存
`futures_qt.spec` 逐文件收集 `futures_quant/`，显式跳过 `__pycache__` 与 `*.pyc`。
不要图省事改回 `datas.append((pkg_dir, "futures_quant"))` —— 那会把字节码缓存一起打进产物。

---

## 六、诚实的边界说明

**面向公众发布的桌面程序不存在真正的客户端身份认证。**
release key 会随程序分发，因此**可以被提取**。它的作用只是挡掉顺手的脚本滥用。

真正的防线是这四条，请不要误以为 release key 是安全的核心：

1. 上游密钥全程留在服务器，客户端从未持有；
2. 客户端只拿 1 小时短期令牌，且可被单独封禁；
3. 按设备限流，单点刷不动额度；
4. 轮换 `QV_JWT_SECRET` 可一键令全部令牌失效，代价极小。

目标不是「阻止提取」，而是**把泄露的后果压到可承受、可恢复**。

---

## 七、验证

```bash
python tests/test_security_redaction.py    # 脱敏与扫描门禁     37 项
python tests/test_proxy_server.py          # 代理服务全链路     85 项
python build_tools/secret_scan.py          # 源码树扫描
python build_tools/secret_scan.py dist --binary-only   # 产物扫描
```

追查特定的历史泄露密钥（不要写进脚本，只用环境变量或命令行）：
```bash
python build_tools/secret_scan.py --literal "<已泄露的密钥原文>"
```
