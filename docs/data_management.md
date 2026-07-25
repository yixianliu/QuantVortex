# 数据管理 · 导出 / 备份 / 恢复 / MySQL 迁移

> v2 新增模块，统一解决「开箱即用 + 数据可控 + 跨机器迁移」三类需求。

## 模块布局

GUI 在侧边栏新增第 8 项「数据管理」入口（含顶部菜单 `数据 → 数据导出…/备份 恢复…` 快捷跳转），页面内分三大卡片：

```
① 数据导出       ── 勾选表 → 导出到文件夹 / 打包 ZIP（CSV / JSON）
② 本地备份/恢复  ── 一键 .db 备份 / 从 .db 覆盖恢复（带安全快照）
③ 远程 MySQL     ── 备份到 MySQL / 从 MySQL 迁移或恢复到本地
```

## 底层模块 `futures_quant/storage/data_transfer.py`

| 函数 | 用途 |
|------|------|
| `migrate_mysql_to_sqlite` | MySQL → SQLite 全量迁移（结构+数据），逐表行数核对 |
| `export_tables` | 指定表 → CSV（utf-8-sig，Excel 直接打开）或 JSON |
| `export_all_zip` | 全部核心表打包成 `quantvortex_export_<时间戳>.zip` |
| `backup_to_file` | SQLite Online Backup API，一致性快照 |
| `restore_from_file` | 从 .db 覆盖恢复，恢复前自动 `*.pre_restore.db` |
| `backup_to_mysql` | SQLite → 远端 MySQL（全量覆盖），按表 drop & 重建 |
| `restore_from_mysql` | 远端 MySQL → 本地，覆盖前自动 `*.pre_restore.db` |

## 数据库现状说明

程序默认本地库就是 SQLite（`data/quant_analysis.db`），用户**无需任何数据库服务器**即可使用全部功能。
远程备份 / 迁移功能是为了支持以下两类老用户：

1. **老版用 MySQL 存数据**：用 `从 MySQL 迁移到本地` 把历史数据一次性搬过来，之后无需再开 MySQL；
2. **多机协同 / 异地容灾**：用 `备份到 MySQL` 同步到团队的 MySQL 服务器做异地灾备。

## MySQL 类型映射

| SQLite 类型 | MySQL 类型 |
|-------------|------------|
| INTEGER (PK) | BIGINT PRIMARY KEY |
| INTEGER | BIGINT |
| REAL | DOUBLE |
| TEXT | TEXT / VARCHAR(191) (主键时) |
| BLOB | LONGBLOB |

日期 / 时间 / bytes / timedelta 在迁移前自动归一化为字符串 / 字节，避免 Python 类型问题。

## 恢复操作的自动安全机制

- 任何「整库覆盖」类操作（从 .db 恢复、从 MySQL 恢复）都会**先备份现库**为 `<原文件名>.pre_restore.db`；
- 备份文件若 `PRAGMA integrity_check` 不为 `ok`，**直接拒绝恢复**；
- 完成弹窗明确提示「本地数据已被覆盖，建议重启程序以刷新各页面显示」。

## 安装可选依赖

```bash
pip install pymysql
```

`requirements.txt` 已声明可选依赖；未安装时 MySQL 相关按钮会弹出友好指引。

## 回归测试

- `_test_data_transfer.py`  — CSV/JSON/ZIP 导出、本地备份恢复、损坏文件拒绝
- `_test_data_page.py`      — DataPage 离屏实例化、控件齐全、主题切换、信号链路
- `_test_mysql_roundtrip.py`— 真实本地 MySQL 闭环（需要本机有 MySQL & 凭据 root/root）

```
ALL DATA-TRANSFER TESTS PASSED
ALL GUI TESTS PASSED
MYSQL ROUND-TRIP TEST PASSED
```