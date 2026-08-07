"""数据迁移 / 导出 / 备份统一模块。

功能总览（全部围绕本地 SQLite 主库 quant_analysis.db）：

1. MySQL → SQLite 迁移（migrate_mysql_to_sqlite）
   - 面向旧版本（数据存 MySQL）的用户：把 MySQL 库中所有表结构 + 数据
     完整迁入本地 SQLite，之后程序开箱即用、无需再部署数据库服务器；
   - 自动做 MySQL → SQLite 类型映射，迁移完成后逐表核对行数，保证完整性。

2. 数据导出（export_tables）
   - 将本地库全部核心业务表导出为 CSV（Excel 可直接打开）或 JSON；
   - 支持整库一键导出，返回逐表导出行数报告。

3. 备份 / 恢复
   - backup_to_file / restore_from_file：基于 SQLite Online Backup API 的
     单文件全量备份，运行中也能得到一致性快照；恢复前自动做安全备份。
   - backup_to_mysql / restore_from_mysql：把本地库整体推送到远程 MySQL
     （或从 MySQL 拉回覆盖本地），用于异地容灾 / 多机同步。

依赖说明：MySQL 相关功能需要 PyMySQL（纯 Python，pip install pymysql），
未安装时其余功能不受影响，调用 MySQL 功能会抛出带安装指引的异常。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import shutil
import sqlite3
from typing import Any, Callable, Optional

ProgressFn = Optional[Callable[[str], None]]

# 本地主库中的核心业务表（导出 / 备份到 MySQL 时的白名单顺序）
CORE_TABLES = [
    "bars", "predictions", "analysis", "alerts", "alert_rules",
    "logs", "judgments", "screening_samples",
]

# 各表中文名（GUI 展示用）
TABLE_LABELS = {
    "bars": "K线缓存",
    "predictions": "AI预测记录",
    "analysis": "研判记录",
    "alerts": "预警日志",
    "alert_rules": "预警规则",
    "logs": "系统日志",
    "judgments": "选品判断",
    "screening_samples": "选品样本",
}


# ============================================================================
# 内部工具
# ============================================================================
def _require_pymysql():
    """处理requirepymysql。"""
    try:
        import pymysql  # noqa: PLC0415
        return pymysql
    except ImportError as e:
        raise RuntimeError(
            "该功能需要 PyMySQL 库（纯 Python，无需编译）。\n"
            "请先安装：pip install pymysql") from e


def _mysql_connect(host: str, port: int, db: str, user: str, password: str,
                   create_db: bool = False):
    """处理mysqlconnect。
    
        参数:
            host: str
            port: int
            db: str
            user: str
            password: str
            create_db: bool"""
    pymysql = _require_pymysql()
    if create_db:
        conn = pymysql.connect(host=host, port=int(port), user=user,
                               password=password, charset="utf8mb4",
                               connect_timeout=8)
        with conn.cursor() as c:
            c.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.select_db(db)
        return conn
    return pymysql.connect(host=host, port=int(port), user=user,
                           password=password, database=db,
                           charset="utf8mb4", connect_timeout=8)


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    """处理sqlitetables。
    
        参数:
            conn: sqlite3.Connection
    
        返回:
            list[str]"""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'").fetchall()
    return [r[0] for r in rows]


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> list[dict]:
    """返回 [{name, type, pk}]。"""
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [{"name": r[1], "type": (r[2] or "TEXT").upper(), "pk": r[5]}
            for r in rows]


def _map_sqlite_to_mysql(sqlite_type: str) -> str:
    """处理mapsqlitetomysql。
    
        参数:
            sqlite_type: str
    
        返回:
            str"""
    t = sqlite_type.upper()
    if "INT" in t:
        return "BIGINT"
    if any(k in t for k in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE"
    if any(k in t for k in ("BLOB",)):
        return "LONGBLOB"
    return "TEXT"


def _map_mysql_to_sqlite(mysql_type: str) -> str:
    """处理mapmysqltosqlite。
    
        参数:
            mysql_type: str
    
        返回:
            str"""
    t = mysql_type.upper()
    if any(k in t for k in ("INT", "BIT", "BOOL")):
        return "INTEGER"
    if any(k in t for k in ("FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL")):
        return "REAL"
    if any(k in t for k in ("BLOB", "BINARY")):
        return "BLOB"
    return "TEXT"


# ============================================================================
# 1. MySQL → SQLite 迁移（旧版本用户一次性迁移入口）
# ============================================================================
def migrate_mysql_to_sqlite(host: str, port: int, db: str, user: str,
                            password: str, sqlite_conn: sqlite3.Connection,
                            progress: ProgressFn = None) -> dict:
    """把 MySQL 库中所有表（结构 + 数据）迁移进本地 SQLite。

    - 同名表：先清空本地数据再导入（保证与 MySQL 一致）；
    - 新表：按 MySQL 列定义映射建表；
    - 返回 {table: {"rows": n, "verified": bool}} 逐表迁移报告。
    """
    say = progress or (lambda _m: None)
    my = _mysql_connect(host, port, db, user, password)
    report: dict[str, dict] = {}
    try:
        with my.cursor() as c:
            c.execute("SHOW TABLES")
            tables = [r[0] for r in c.fetchall()]
        if not tables:
            raise RuntimeError(f"MySQL 库 {db} 中没有任何表")

        for table in tables:
            say(f"迁移表 {table} …")
            with my.cursor() as c:
                c.execute(f"SHOW COLUMNS FROM `{table}`")
                cols = c.fetchall()          # (Field, Type, Null, Key, Default, Extra)
            col_names = [r[0] for r in cols]

            # -- 本地无此表则按映射建表 --
            local_tables = set(_sqlite_tables(sqlite_conn))
            if table not in local_tables:
                defs = []
                for field, ftype, _null, key, _default, extra in cols:
                    st = _map_mysql_to_sqlite(ftype)
                    if key == "PRI" and "auto_increment" in (extra or "").lower():
                        defs.append(f'"{field}" INTEGER PRIMARY KEY AUTOINCREMENT')
                    elif key == "PRI":
                        defs.append(f'"{field}" {st} PRIMARY KEY')
                    else:
                        defs.append(f'"{field}" {st}')
                sqlite_conn.execute(
                    f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(defs)})')
            else:
                # 同名表：只迁移两边都存在的列，先清空本地数据
                local_cols = {c_["name"] for c_ in _sqlite_columns(sqlite_conn, table)}
                col_names = [c_ for c_ in col_names if c_ in local_cols]
                if not col_names:
                    report[table] = {"rows": 0, "verified": False,
                                     "note": "无可映射列，已跳过"}
                    continue
                sqlite_conn.execute(f'DELETE FROM "{table}"')

            # -- 分批搬数据 --
            quoted = ", ".join(f"`{c_}`" for c_ in col_names)
            placeholders = ", ".join("?" for _ in col_names)
            q_cols = ", ".join(f'"{c_}"' for c_ in col_names)
            total = 0
            with my.cursor() as c:
                c.execute(f"SELECT {quoted} FROM `{table}`")
                while True:
                    rows = c.fetchmany(2000)
                    if not rows:
                        break
                    norm = [tuple(_norm_value(v) for v in r) for r in rows]
                    sqlite_conn.executemany(
                        f'INSERT INTO "{table}" ({q_cols}) VALUES ({placeholders})',
                        norm)
                    total += len(rows)
            sqlite_conn.commit()

            # -- 行数核对 --
            with my.cursor() as c:
                c.execute(f"SELECT COUNT(*) FROM `{table}`")
                mysql_count = c.fetchone()[0]
            local_count = sqlite_conn.execute(
                f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            report[table] = {"rows": total,
                             "verified": (mysql_count == local_count)}
            say(f"表 {table}：{total} 行，核对{'通过' if mysql_count == local_count else '不一致'}")
    finally:
        my.close()
    return report


def _norm_value(v: Any) -> Any:
    """MySQL 值归一化为 SQLite 可存储类型。"""
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return str(v)
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v)
    return v


# ============================================================================
# 2. 数据导出（CSV / JSON）
# ============================================================================
def export_tables(sqlite_conn: sqlite3.Connection, out_dir: str,
                  tables: Optional[list[str]] = None, fmt: str = "csv",
                  progress: ProgressFn = None) -> dict:
    """把本地库的核心业务表导出到 out_dir。

    :param tables: None = 全部核心表（存在的才导）
    :param fmt: "csv"（utf-8-sig，Excel 直接打开）或 "json"
    :return: {table: 导出行数}
    """
    say = progress or (lambda _m: None)
    os.makedirs(out_dir, exist_ok=True)
    existing = set(_sqlite_tables(sqlite_conn))
    wanted = [t for t in (tables or CORE_TABLES) if t in existing]
    report: dict[str, int] = {}
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    for table in wanted:
        say(f"导出 {TABLE_LABELS.get(table, table)} …")
        cols = [c["name"] for c in _sqlite_columns(sqlite_conn, table)]
        cur = sqlite_conn.execute(f'SELECT * FROM "{table}"')
        rows = cur.fetchall()
        path = os.path.join(out_dir, f"{table}_{stamp}.{fmt}")
        if fmt == "json":
            data = [dict(zip(cols, tuple(r))) for r in rows]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        else:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)
        report[table] = len(rows)
    return report


# ============================================================================
# 3a. 本地文件备份 / 恢复（SQLite Online Backup API）
# ============================================================================
def backup_to_file(sqlite_conn: sqlite3.Connection, dest_path: str,
                   progress: ProgressFn = None) -> str:
    """把当前打开的库在线备份为独立 .db 文件（运行中亦可得到一致快照）。"""
    say = progress or (lambda _m: None)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    say("正在生成一致性快照 …")
    dst = sqlite3.connect(dest_path)
    try:
        sqlite_conn.backup(dst)
    finally:
        dst.close()
    say(f"备份完成：{dest_path}")
    return dest_path


def restore_from_file(sqlite_conn: sqlite3.Connection, src_path: str,
                      live_db_path: str, progress: ProgressFn = None) -> str:
    """从备份文件恢复到当前打开的库（覆盖式）。

    恢复前会把现有库先安全备份为 <live>.pre_restore.db，失败可回退。
    """
    say = progress or (lambda _m: None)
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"备份文件不存在：{src_path}")

    # 校验备份文件是本合法 SQLite 库
    probe = sqlite3.connect(src_path)
    try:
        ok = probe.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        if not ok:
            raise RuntimeError("备份文件完整性校验失败，已取消恢复")
    finally:
        probe.close()

    # 现库安全快照
    safety = live_db_path + ".pre_restore.db"
    say("为当前数据做安全备份 …")
    backup_to_file(sqlite_conn, safety)

    say("正在恢复数据 …")
    src = sqlite3.connect(src_path)
    try:
        src.backup(sqlite_conn)   # 反向：备份文件 → 当前连接（整库覆盖）
    finally:
        src.close()
    sqlite_conn.commit()
    say("恢复完成")
    return safety


# ============================================================================
# 3b. 备份到远程 MySQL / 从 MySQL 恢复
# ============================================================================
def backup_to_mysql(sqlite_conn: sqlite3.Connection, host: str, port: int,
                    db: str, user: str, password: str,
                    progress: ProgressFn = None) -> dict:
    """把本地库全部核心表推送到远程 MySQL（drop & 重建，全量覆盖）。"""
    say = progress or (lambda _m: None)
    say("连接远程 MySQL …")
    my = _mysql_connect(host, port, db, user, password, create_db=True)
    report: dict[str, int] = {}
    try:
        existing = set(_sqlite_tables(sqlite_conn))
        for table in [t for t in CORE_TABLES if t in existing]:
            say(f"上传 {TABLE_LABELS.get(table, table)} …")
            cols = _sqlite_columns(sqlite_conn, table)
            defs = []
            for c_ in cols:
                mt = _map_sqlite_to_mysql(c_["type"])
                if c_["pk"] and "INT" in c_["type"]:
                    defs.append(f"`{c_['name']}` BIGINT PRIMARY KEY")
                elif c_["pk"]:
                    # MySQL TEXT 不能直接做主键，退化为带长度的 VARCHAR
                    mt2 = "VARCHAR(191)" if mt == "TEXT" else mt
                    defs.append(f"`{c_['name']}` {mt2} PRIMARY KEY")
                else:
                    defs.append(f"`{c_['name']}` {mt}")
            with my.cursor() as c:
                c.execute(f"DROP TABLE IF EXISTS `{table}`")
                c.execute(
                    f"CREATE TABLE `{table}` ({', '.join(defs)}) "
                    "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")

            names = [c_["name"] for c_ in cols]
            quoted = ", ".join(f"`{n}`" for n in names)
            ph = ", ".join("%s" for _ in names)
            cur = sqlite_conn.execute(f'SELECT * FROM "{table}"')
            total = 0
            while True:
                rows = cur.fetchmany(2000)
                if not rows:
                    break
                with my.cursor() as c:
                    c.executemany(
                        f"INSERT INTO `{table}` ({quoted}) VALUES ({ph})",
                        [tuple(r) for r in rows])
                total += len(rows)
            my.commit()

            # 行数核对
            with my.cursor() as c:
                c.execute(f"SELECT COUNT(*) FROM `{table}`")
                if c.fetchone()[0] != total:
                    raise RuntimeError(f"表 {table} 上传后行数不一致")
            report[table] = total
        say("备份到 MySQL 完成")
    finally:
        my.close()
    return report


def restore_from_mysql(sqlite_conn: sqlite3.Connection, host: str, port: int,
                       db: str, user: str, password: str,
                       live_db_path: str, progress: ProgressFn = None) -> dict:
    """从远程 MySQL 拉回数据覆盖本地库（恢复前自动做本地安全备份）。"""
    say = progress or (lambda _m: None)
    safety = live_db_path + ".pre_restore.db"
    say("为当前数据做安全备份 …")
    backup_to_file(sqlite_conn, safety)
    report = migrate_mysql_to_sqlite(host, port, db, user, password,
                                     sqlite_conn, progress=progress)
    say("从 MySQL 恢复完成")
    return report


# ============================================================================
# 便捷：整目录打包导出
# ============================================================================
def export_all_zip(sqlite_conn: sqlite3.Connection, out_dir: str,
                   fmt: str = "csv", progress: ProgressFn = None) -> str:
    """全部核心表导出后打成一个 zip，返回 zip 路径。"""
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = os.path.join(out_dir, f"_export_{stamp}")
    export_tables(sqlite_conn, tmp, fmt=fmt, progress=progress)
    zip_base = os.path.join(out_dir, f"quantvortex_export_{stamp}")
    path = shutil.make_archive(zip_base, "zip", tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return path
