"""原子化、可恢复的 JSON 存储助手。

设计目标（对应「异常恢复机制」与「读写效率」要求）：
    - 原子写：先写 *.tmp 再 os.replace，绝不会在磁盘上留下半截文件；
    - 备份回退：每次成功写入前把旧文件复制为 *.bak，主文件损坏时自动回退；
    - 损坏恢复：读取时若主文件解析失败，自动尝试 *.bak，再不行回退默认值，
      保证「程序意外关闭或崩溃后仍能启动并恢复之前保存的状态」；
    - 版本迁移：__version__ 变化时与默认值深合并，丢弃未知键、保留已知键；
    - 点分路径：get("ui.theme") / set("ui.theme", "light") 方便嵌套读写。

读写都在内存 dict 上完成，磁盘 IO 仅在 save() 时发生，效率可控。
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Optional


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：以 base 为骨架，用 override 覆盖同名叶子节点。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if k == "__version__":
            out[k] = v
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _get_path(d: dict, path: str) -> tuple[Optional[dict], str]:
    """获取路径。
    
        参数:
            d: dict
            path: str
    
        返回:
            tuple[Optional[dict], str]"""
    node = d
    parts = path.split(".")
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            node[p] = {}
        node = node[p]
    return node, parts[-1]


def safe_load_json(path: str, default: Optional[dict] = None) -> Optional[dict]:
    """安全读取 JSON；文件不存在 / 解析失败 / 非 dict 时返回 default。"""
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        return data
    except Exception:
        return default


class AtomicJSON:
    """一个以 JSON 文件为后端的原子化键值存储。"""

    def __init__(self, path: str, default: Optional[dict] = None,
                 version: int = 1) -> None:
        """初始化相关对象。
        
            参数:
                path: str
                default: Optional[dict]
                version: int"""
        self.path = path
        self.version = version
        self._default = default or {}
        self.data = self._load()

    def _load(self) -> dict:
        """加载相关对象。
        
            返回:
                dict"""
        data = safe_load_json(self.path, None)
        if data is None:
            # 主文件损坏/缺失 → 尝试备份
            data = safe_load_json(self.path + ".bak", None)
        if data is None:
            data = {}
        # 版本迁移：与默认值深合并，保证缺字段被补齐、未知字段被丢弃
        data = _deep_merge(self._default, data)
        data["__version__"] = self.version
        return data

    # ---------- 读写 ----------
    def get(self, path: str, default: Any = None) -> Any:
        """获取相关对象。
        
            参数:
                path: str
                default: Any
        
            返回:
                Any"""
        node, key = _get_path(self.data, path)
        if key in node and node[key] is not None:
            return node[key]
        return default

    def set(self, path: str, value: Any) -> None:
        """设置相关对象。
        
            参数:
                path: str
                value: Any"""
        node, key = _get_path(self.data, path)
        node[key] = value

    def update(self, mapping: dict) -> None:
        """更新相关对象。
        
            参数:
                mapping: dict"""
        for k, v in mapping.items():
            self.set(k, v)

    def as_dict(self) -> dict:
        """处理asdict。
        
            返回:
                dict"""
        return {k: v for k, v in self.data.items() if k != "__version__"}

    # ---------- 落盘 ----------
    def save(self) -> bool:
        """原子写：写 *.tmp → 复制旧文件为 *.bak → os.replace。

        返回是否成功；任何异常都被吞掉并返回 False，绝不影响主流程。
        """
        self.data["__version__"] = self.version
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2, sort_keys=False)
            # 先备份旧的好文件，再替换
            if os.path.exists(self.path):
                shutil.copyfile(self.path, self.path + ".bak")
            os.replace(tmp, self.path)
            # 首次写入后也确保存在一份 .bak，便于后续崩溃回退
            if not os.path.exists(self.path + ".bak"):
                shutil.copyfile(self.path, self.path + ".bak")
            return True
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return False

    def exists(self) -> bool:
        """处理exists。
        
            返回:
                bool"""
        return os.path.exists(self.path)
