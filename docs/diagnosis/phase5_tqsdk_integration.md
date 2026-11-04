# 阶段 5：TqSdk / SimNow 数据源适配器（方案 A）

> 目标：把「真实账号行情」接入既有 `DataFeed` 契约与 provenance 体系，先用 mock 打通链路并验收；
> 不依赖真实账号、不静默降级、不把合成行情伪装成真实行情。

## 1. 改动文件 → 行

| 文件 | 位置 | 改动 |
|---|---|---|
| [tqsdk_feed.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/tqsdk_feed.py) | 全文件（新增 577 行） | `TqSdkFeed` 适配器、错误分类、合约/周期规范化、凭据读取、`tqsdk_diagnose()`、`register_feed("tqsdk", ...)` |
| 同上 | [L56-L148](file:///d:/PythonProject/QuantVortex/futures_quant/data/tqsdk_feed.py#L56-L148) | 错误类：`TqSdkFeedError` 基类 + 5 类具名错误（另含 `InvalidSymbolError`） |
| 同上 | [L184-L248](file:///d:/PythonProject/QuantVortex/futures_quant/data/tqsdk_feed.py#L184-L248) | `to_tq_symbol` / `normalize_period`（主力连续与单合约、D/1m/5m/15m/30m） |
| 同上 | [L253-L345](file:///d:/PythonProject/QuantVortex/futures_quant/data/tqsdk_feed.py#L253-L345) | `TqSdkCredentials.load`（env → 本地未跟踪文件）+ 只读诊断 |
| 同上 | [L348-L366](file:///d:/PythonProject/QuantVortex/futures_quant/data/tqsdk_feed.py#L348-L366) | TqSdk 纳秒时间戳 → 北京时间 naive datetime（+8h） |
| 同上 | [L369-L577](file:///d:/PythonProject/QuantVortex/futures_quant/data/tqsdk_feed.py#L369-L577) | `TqSdkFeed`：懒连接、`get_history/get_recent`、`close()` 幂等、字段规范化、区间过滤、provenance |
| [base.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/base.py) | [L70-L79](file:///d:/PythonProject/QuantVortex/futures_quant/data/base.py#L70-L79) | provenance 名称映射补 `tqsdk → TqSdk 实盘行情` |
| [data/__init__.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/__init__.py) | 全文件 | 导入即注册 `tqsdk` 工厂（不导入 tqsdk 本体，未安装不阻塞启动） |
| [market_data.py](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py) | [L35](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L35) | `REAL_SOURCES` 增加 `tqsdk`（禁止对真实源伪造随机 tick） |
| 同上 | [L285-L299](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L285-L299) | `_build_feed` 增加 tqsdk 分支：只构建、不探测、不回退合成 |
| 同上 | [L430-L443](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L430-L443) | `connect()` 增加 tqsdk 探测：失败保留具名错误，禁止模拟 tick |
| 同上 | [L500-L505](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L500-L505) | `disconnect()` 调用 `feed.close()`，避免 TqApi 连接线程残留 |
| 同上 | [L519-L560](file:///d:/PythonProject/QuantVortex/futures_quant/data/market_data.py#L519-L560) | `_ensure_full`：TqSdk 失败返回空表 + 错误 provenance，**不做合成回退** |
| [config/settings.json](file:///d:/PythonProject/QuantVortex/config/settings.json) | [L4-L13](file:///d:/PythonProject/QuantVortex/config/settings.json#L4-L13) | `data.tqsdk` 占位配置（env 名 / 本地凭据路径），无真实凭据；`data.source` 默认仍为 `sina` |
| [.gitignore](file:///d:/PythonProject/QuantVortex/.gitignore) | [L4-L5](file:///d:/PythonProject/QuantVortex/.gitignore#L4-L5) | 忽略 `config/tqsdk_settings.json` |
| [data_page.py](file:///d:/PythonProject/QuantVortex/futures_quant/ui/data_page.py) | [L29-L37](file:///d:/PythonProject/QuantVortex/futures_quant/ui/data_page.py#L29-L37)、[L117-L189](file:///d:/PythonProject/QuantVortex/futures_quant/ui/data_page.py#L117-L189) | 数据管理页新增「行情数据源」选择卡 + TqSdk 安装/凭据提示（不弹窗索取密码） |
| [test_phase5_tqsdk_feed.py](file:///d:/PythonProject/QuantVortex/tests/unit/test_phase5_tqsdk_feed.py) | 全文件 | 23 条离线单测 |

未改动：`data/`、生产数据库、指标与回测内核、版本号；未 commit。

## 2. 能力边界

- **周期**：日线（`D`/`1D`）、`1m`、`5m`、`15m`、`30m`；其它周期（`1h`、`W`、`M`）明确拒绝。
- **合约**：
  - 主力连续：`KQ.m@SHFE.rb`；可简写 `rb` / `rb0` / `rb.SHFE`；
  - 单合约：`SHFE.rb2611`；可简写 `rb2611` / `rb2611.SHFE`；
  - 郑商所按 TqSdk 约定大写（`CZCE.MA609`）。
- **字段**：统一为 `[datetime, open, high, low, close, volume, open_interest]`；上游若带 `settle`/`settlement` 则保留为 `settle`；成交量/持仓量缺失补 0。
- **时间口径**：TqSdk `datetime` 是「以北京时间为基准的纳秒计数」，按 ns 解析后 **+8 小时**，得到与项目其它源一致的北京时间 naive 时间；`as_of` = 最后一根 bar 时间。
- **provenance**：成功返回 `data_source="tqsdk"`、`is_synthetic=False`、`is_stale=False`、`as_of=最后一根 bar`、`note=""`。
- **连接管理**：构造不联网；首次取数才 `TqApi(...)`；`close()` 幂等，`MarketDataManager.disconnect()` 已接线；支持 `with TqSdkFeed(...)`。
- **不做的事**：不缓存回放、不生成合成 K 线、不在失败时假装「已连接」。

## 3. 错误分类与下一步

所有错误继承 `TqSdkFeedError`，`kind` 稳定可用于 UI/日志分类，`user_message` 自带可执行下一步。

| 异常 | `kind` | 触发条件 | 界面文案（示例） | 下一步 |
|---|---|---|---|---|
| `NotInstalledError` | `NotInstalled` | `import tqsdk` 失败 | 未安装 tqsdk（ModuleNotFoundError） | `pip install tqsdk` 后重启 |
| `MissingCredentialsError` | `MissingCredentials` | env 与本地文件都没有账号 | 未找到 TqSdk / SimNow 账号… | 设 `TQ_USER`/`TQ_PASSWORD`，或写 `config/tqsdk_settings.json`（不入库） |
| `ConnectFailedError` | `ConnectFailed` | `TqApi` 初始化或取数调用抛异常 | TqSdk 取数失败（SHFE.rb…，周期 300s）：TimeoutError… | 检查网络/账号权限/交易时段；必要时换模拟账号 |
| `NoDataError` | `NoData` | 请求区间返回空表 | 未返回 … 的 … K 线 | 核对合约/周期/区间；非交易时段扩大区间 |
| `UnsupportedPeriodError` | `UnsupportedPeriod` | 周期不在白名单 | 不支持周期 '1h'（仅支持 D/1m/5m/15m/30m） | 改用受支持周期或切换数据源 |
| `InvalidSymbolError` | `InvalidSymbol` | 代码无法解析/未知品种 | 未识别品种 'zzz' | 用 `SHFE.rb2611` / `KQ.m@SHFE.rb` |

**禁止静默降级**的两道闸：
1. `TqSdkFeed` 任何失败都抛具名异常，绝不返回合成 DataFrame；
2. `MarketDataManager` 的 tqsdk 分支不再走「空数据 → 合成回退」路径：`_ensure_full` 捕获后返回 **空表 + `data_source=tqsdk` + `note=错误原因`**，`connect()` 状态显示「TqSdk 不可用 · …」，且 `allow_sim=False`（不伪造随机 tick）。

## 4. 配置与凭据

`config/settings.json`（仅占位，无真实凭据）：

```json
"data": {
  "source": "sina",
  "tqsdk": {
    "user_env": "TQ_USER",
    "password_env": "TQ_PASSWORD",
    "creds_path": "config/tqsdk_settings.json"
  }
}
```

凭据读取顺序：
1. 构造参数 `user/password`（测试/上层注入）；
2. 环境变量 `TQ_USER` / `TQ_PASSWORD`（兼容 `TQSDK_*`、`QV_TQ_*`）；
3. 本地未跟踪文件 `tqsdk_settings.json`，支持两种结构：
   ```json
   {"user": "账号", "password": "密码"}
   ```
   ```json
   {"account": {"user": "账号", "password": "密码"}}
   ```
   候选路径：`<data>/tqsdk_settings.json` → `<config>/tqsdk_settings.json`；`config/tqsdk_settings.json` 已被 `.gitignore` 忽略。

UI 仅在数据管理页展示「是否已安装 / 是否检测到凭据 / 如何设置」，**不弹窗索要密码**，输入框也不收集密码。

## 5. 测试覆盖（全部离线）

命令：

```bash
python -m pytest tests/unit/test_phase5_tqsdk_feed.py -q
```

结果：**23 passed**（本机 `tqsdk` 未安装，全部使用 `api_factory` 桩与 `sys.modules` 注入）。

| # | 场景 | 断言 |
|---|---|---|
| 1 | 正常区间取数（5m） | 列结构、行数、北京时间 09:00→09:20、`data_source=tqsdk`、`is_synthetic=False`、`as_of=最后一根`、symbol 规范为 `KQ.m@SHFE.rb`、duration=300 |
| 2 | 日线 + settle | `settle` 保留；volume/OI 缺失补 0 |
| 3 | `get_recent` | 走 `get_kline_serial`、`data_length=limit`、升序、非合成 |
| 4 | 缺库 | `NotInstalledError`，提示含 `pip install tqsdk` |
| 5 | 缺凭据 | `MissingCredentialsError`，且**不创建 TqApi** |
| 6 | 连接失败 | `ConnectFailedError`，`kind=ConnectFailed` |
| 7 | 空数据 | `NoDataError`，不返回任何行情 |
| 8 | 周期不支持 | `UnsupportedPeriodError`，且工厂调用次数为 0（懒加载） |
| 9 | `close()` 幂等 | 连续两次 `close()` 底层只关闭一次；之后可重新懒建连接 |
| 10 | 合约规范化（10 组） | `rb0/rb/rb.SHFE/SHFE.rb2611/rb2611/MA609/i2409/KQ.m@...` |
| 11 | 非法合约 | `InvalidSymbolError`（不猜测） |
| 12 | 凭据 env/文件 | env 优先；文件可读且来源可追溯 |
| 13 | 注册表 + 诊断 | `registered_feeds()` 含 `tqsdk`；诊断不联网 |
| 14 | 管理器层失败 | 空表、`data_source=tqsdk`、`is_synthetic=False`、note 含错误；`connect()` 状态「TqSdk 不可用」，`allow_sim=False`，状态不含「合成」 |

## 6. 真实连通性结果

**未测试（环境不具备条件）**：

```
$ python -c "import tqsdk"
ModuleNotFoundError: No module named 'tqsdk'
```

按约束未擅自联网安装。因此本轮只验证了「适配逻辑 + 错误分类 + 管理器接线」，
真实 TqApi 握手/行情权限仍需在有账号的机器上确认。

## 7. 拿到 SimNow / TqSdk 账号后的三步验证

### 第 1 步：安装与凭据（不写入仓库）

```bash
pip install tqsdk
```

PowerShell（当前会话）：

```powershell
$env:TQ_USER = "你的账号"
$env:TQ_PASSWORD = "你的密码"
```

或写本地文件 `config/tqsdk_settings.json`（已被 gitignore）：

```json
{"user": "你的账号", "password": "你的密码"}
```

自检（不联网）：

```bash
python -c "from futures_quant.data.tqsdk_feed import tqsdk_diagnose; print(tqsdk_diagnose())"
# 期望 installed=True, creds_complete=True, creds_origin in ('env','file:...')
```

### 第 2 步：最小只读连通性（≤3 合约，建议 60s 内完成）

```bash
python - <<'PY'
import os, time
from tqsdk import TqApi, TqAuth
t0 = time.time()
api = TqApi(auth=TqAuth(os.environ["TQ_USER"], os.environ["TQ_PASSWORD"]), web_gui=False)
try:
    for sym in ("KQ.m@SHFE.rb", "SHFE.rb2611", "KQ.m@DCE.i"):
        kl = api.get_kline_serial(sym, 86400, data_length=5)
        print(sym, len(kl), float(kl.iloc[-1]["close"]), int(kl.iloc[-1]["volume"]))
    print("elapsed", round(time.time() - t0, 1), "s")
finally:
    api.close()
PY
```

Windows PowerShell 下若 `<<'PY'` 不适用，可保存为临时文件（如 `%TEMP%\tq_check.py`）后执行；
若超过 60s 未返回，直接 `Ctrl+C` 中止并记录为「连接失败」，不得继续跑批量取数。

### 第 3 步：切源并验收

1. 优先在「数据管理 → 行情数据源」选择 `TqSdk / SimNow` 并保存，重启程序；
   或直接把 `config/settings.json` 的 `data.source` 改为 `tqsdk`（或写 `data/user_settings.json` 覆盖）。
2. 观察状态栏：
   - 成功：`已连接 · TqSdk 实盘行情`；
   - 失败：`TqSdk 不可用 · [NotInstalled]/[MissingCredentials]/[ConnectFailed] …`，**不会显示合成行情**。
3. 回归单测与数据验收：

```bash
python -m pytest tests/unit/test_phase5_tqsdk_feed.py -q
python -c "from futures_quant.data.tqsdk_feed import TqSdkFeed; from futures_quant.data.base import get_provenance; \
f=TqSdkFeed(); d=f.get_history('rb.SHFE','2024-01-01','2024-12-31','D'); print(d.tail(3)); print(get_provenance(d)); f.close()"
```

期望：`data_source=tqsdk`、`is_synthetic=False`、`as_of` 等于最后一根日线时间、`note=""`。
若出现 `NoData/ConnectFailed`，按第 3 节表格的「下一步」逐项处理，不要切回合成源掩盖问题。

## 8. 已知限制 / 后续可拓展

- `TqApi` 无同步超时参数：真实环境若网络卡住，只能由外层进程/脚本限时中止；适配器本身不做伪超时。
- 未做本地 K 线缓存（与 akshare 的陈旧缓存不同）：TqSdk 失败时直接报错，避免「旧数据当新数据」。
- 主力连续未做换月复权（本阶段只保证「取到真实行情」）；复权应在研究/回测层按既定口径处理。
- 若未来需要 1h/周线，可在 `_PERIOD_MAP` 增加映射，但需先确认 TqSdk 服务端支持的时长上限。
