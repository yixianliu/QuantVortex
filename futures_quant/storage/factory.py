"""存储后端工厂。

根据 Config.storage.backend 返回对应后端实例：
    - "sqlite"  （默认）：SQLiteBackend，零配置单文件；
    - "postgres"：PostgresBackend（PostgreSQL + TimescaleDB 超表）。

上层只需 `db = get_storage(config)`，无需关心具体数据库。
"""
from __future__ import annotations

from .base import StorageBackend
from .sqlite_backend import SQLiteBackend


def get_storage(config) -> StorageBackend:
    """获取storage。
    
        参数:
            config
    
        返回:
            StorageBackend"""
    sc = getattr(config, "storage", None)
    if sc is None:
        return SQLiteBackend()
    if sc.backend == "postgres":
        from .postgres_backend import PostgresBackend
        return PostgresBackend(
            host=sc.pg_host, port=sc.pg_port, dbname=sc.pg_db,
            user=sc.pg_user, password=sc.pg_password, timescale=sc.pg_timescale,
        )
    return SQLiteBackend(sc.sqlite_path)
