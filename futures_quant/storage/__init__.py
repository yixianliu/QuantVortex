"""存储层入口。

统一暴露抽象接口与各后端；原 `Database` 名称以 SQLiteBackend 向后兼容保留。
"""
from .base import StorageBackend
from .sqlite_backend import SQLiteBackend
from .postgres_backend import PostgresBackend
from .factory import get_storage

# 向后兼容：早期代码中的 `Database` 即 SQLiteBackend
Database = SQLiteBackend

__all__ = [
    "StorageBackend",
    "SQLiteBackend",
    "PostgresBackend",
    "get_storage",
    "Database",
]
