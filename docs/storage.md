# 存储层选型与接入说明

## 一、结论先行

期货量化系统的存储采用**分层可插拔架构**，通过统一接口 `StorageBackend` 屏蔽底层数据库差异：

- **默认 SQLite**：零配置、单文件、可随 exe 桌面程序分发，覆盖仿真盘 / 回测落地 / 单机轻量实盘。
- **生产升级 PostgreSQL + TimescaleDB**：实盘多账户并发、海量历史 K 线、跨机器访问时切换，K 线用超表按时间分块。

切换只需改 `config/settings.json` 里的 `storage.backend`，**上层引擎 / 回测 / UI 代码无需改动**。

## 二、为什么是 SQLite 作默认

原需求明确要求"本地轻量化 SQLite""可打包 exe 免配置"。SQLite 完美契合：

- 单文件数据库，无需服务进程，桌面程序双击即用；
- 委托 / 成交 / 参数 / 日志量级小，单写者足够；
- 行情 K 线按 `(symbol, datetime)` 建索引，区间回测查询足够快（数万根级别）。

## 三、什么时候该上 PostgreSQL + TimescaleDB

| 信号 | 说明 |
|---|---|
| 实盘多账户并发写入 | SQLite 单写者，高并发会锁；Postgres 支持多连接 |
| 历史 K 线累积到千万级以上 | TimescaleDB 超表按时间分块，区间查询 / 压缩远优于行表 |
| CTP 实盘机与策略研究机分离 | 网络数据库，研究机直接连库做复盘 |
| 需要 SQL 级分析 / 报表 | Postgres 生态（窗口函数、物化视图）更强 |

## 四、接口与实现位置

| 文件 | 内容 |
|---|---|
| `futures_quant/storage/base.py` | `StorageBackend` 抽象接口（params / orders / trades / bars / logs / equity） |
| `futures_quant/storage/sqlite_backend.py` | `SQLiteBackend`（默认） |
| `futures_quant/storage/postgres_backend.py` | `PostgresBackend`（TimescaleDB 超表，psycopg 懒加载） |
| `futures_quant/storage/factory.py` | `get_storage(config)` 工厂 |
| `futures_quant/config/settings.py` | `StorageConfig`（backend / sqlite_path / pg_*） |

## 五、配置示例

`config/settings.json`：

```json
{
  "storage": {
    "backend": "sqlite",
    "sqlite_path": "data/futures_quant.db",
    "pg_host": "127.0.0.1",
    "pg_port": 5432,
    "pg_db": "futures",
    "pg_user": "postgres",
    "pg_password": "",
    "pg_timescale": true
  }
}
```

切到生产：

```json
{ "storage": { "backend": "postgres", "pg_host": "10.0.0.5", "pg_db": "futures", "pg_user": "quant", "pg_password": "***" } }
```

## 六、PostgreSQL + TimescaleDB 部署（实盘前）

```bash
# 1. 安装 PostgreSQL 15+ 与 TimescaleDB 扩展
#    Ubuntu: sudo apt install postgresql; 然后 CREATE EXTENSION timescaledb;
# 2. 建库与用户
createdb futures
psql -d futures -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
# 3. 安装驱动（沙箱默认未装，仅生产机需要）
pip install psycopg        # 或 psycopg2
```

后端首次运行会自动建表；若检测到 TimescaleDB 扩展，则把 `bars` / `equity` 建为超表，否则退回普通表（仍可用）。

## 七、代码接入

```python
from futures_quant.config.settings import Config
from futures_quant.storage import get_storage

cfg = Config.load("config/settings.json")
db = get_storage(cfg)          # 按配置返回 SQLite 或 Postgres 后端

# 行情落地
db.insert_bars(bars)
bars = db.query_bars("rb.SHFE", start="2024-01-01", end="2024-06-30", limit=5000)

# 成交 / 委托（引擎自动写入，也可手动查）
trades = db.query_trades("rb.SHFE")

# 策略参数 KV
db.save_param("trend_rb", "fast=10,slow=30")
db.load_param("trend_rb")

# 资金曲线（复盘用）
db.save_equity_point(dt, equity, available, drawdown)
db.query_equity()

db.close()
```

引擎在 **live / 仿真模式**下会自动把每根 K 线、每笔委托 / 成交、每个权益采样点落库；**回测模式**为性能跳过逐笔写库（已有 CSV / JSON / HTML 报告导出）。

## 八、关于 DuckDB（可选进阶）

若回测主要在本地做大规模历史 K 线的分析查询（而非交易落地），可额外引入 **DuckDB** 作为行情分析专用库——它列式存储、对 Parquet / CSV 极快，适合"读多写少"的回测数据层。当前架构已通过 `StorageBackend` 接口预留扩展位，新增 `DuckDBBackend` 不改动任何上层代码。如需要，可在 `storage/` 下追加实现并在工厂注册。
