"""配置管理器 与 运行时状态。

两类持久化数据，分开存储以保证「读写效率」与「异常恢复」互不干扰：

1. ConfigManager（用户配置 / 稳定偏好）
   - 默认值来自 config/settings.json；
   - 用户修改写入 data/user_settings.json（仅存差异覆盖，原子写）；
   - 典型内容：主题、数据源、默认合约/周期等「很少变」的设置。

2. SessionState（运行状态 / 高频变化）
   - 写入 data/session_state.json（原子写 + .bak 回退）；
   - 典型内容：窗口几何/最大化、最后停留页、各页当前合约/周期；
   - 在组合框变化、窗口缩放、页面切换时落盘，保证崩溃/关闭后可恢复。

两者都基于 json_store.AtomicJSON，具备：原子写、备份回退、损坏自愈、
版本迁移、点分路径读写。SQLite 历史记录见 analysis_store.AnalysisStore。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from .json_store import AtomicJSON
from ..runtime import get_data_dir, get_config_dir

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_json(path: str) -> dict:
    """读取json。
    
        参数:
            path: str
    
        返回:
            dict"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


class ConfigManager:
    """配置：defaults(settings.json) + 用户覆盖(user_settings.json)。"""

    def __init__(self, defaults_path: Optional[str] = None,
                 user_path: Optional[str] = None, version: int = 2) -> None:
        """初始化相关对象。
        
            参数:
                defaults_path: Optional[str]
                user_path: Optional[str]
                version: int"""
        self.defaults_path = defaults_path or os.path.join(get_config_dir(), "settings.json")
        self.user_path = user_path or os.path.join(get_data_dir(), "user_settings.json")
        self._defaults = _read_json(self.defaults_path)
        self._user = AtomicJSON(self.user_path, default=self._defaults, version=version)

    # ---------- 点分路径读写 ----------
    def get(self, path: str, default: Any = None) -> Any:
        """获取相关对象。
        
            参数:
                path: str
                default: Any
        
            返回:
                Any"""
        return self._user.get(path, default)

    def set(self, path: str, value: Any) -> None:
        """设置相关对象。
        
            参数:
                path: str
                value: Any"""
        self._user.set(path, value)

    def as_dict(self) -> dict:
        """处理asdict。
        
            返回:
                dict"""
        return self._user.as_dict()

    def save(self) -> bool:
        """保存相关对象。
        
            返回:
                bool"""
        return self._user.save()

    def reset_user(self) -> bool:
        """清空用户覆盖，回退到 settings.json 默认值。"""
        try:
            if os.path.exists(self.user_path):
                os.remove(self.user_path)
            if os.path.exists(self.user_path + ".bak"):
                os.remove(self.user_path + ".bak")
        except Exception:
            pass
        self._user = AtomicJSON(self.user_path, default=self._defaults,
                                version=self._user.version)
        return True


class SessionState:
    """运行时状态：窗口几何、最后页、各页合约/周期等高频变化数据。"""

    _DEFAULTS = {
        "window": {"x": None, "y": None, "w": 1360, "h": 860, "maximized": True},
        "last_page": 0,
        "pages": {},   # page_key -> {"symbol":..., "period":...}
    }

    def __init__(self, path: Optional[str] = None, version: int = 1) -> None:
        """初始化相关对象。
        
            参数:
                path: Optional[str]
                version: int"""
        self.path = path or os.path.join(get_data_dir(), "session_state.json")
        self._state = AtomicJSON(self.path, default=self._DEFAULTS, version=version)
        self._dirty = False

    def get(self, path: str, default: Any = None) -> Any:
        """获取相关对象。
        
            参数:
                path: str
                default: Any
        
            返回:
                Any"""
        return self._state.get(path, default)

    def set(self, path: str, value: Any) -> None:
        """设置相关对象。
        
            参数:
                path: str
                value: Any"""
        self._state.set(path, value)
        self._dirty = True

    def mark_dirty(self) -> None:
        """处理markdirty。"""
        self._dirty = True

    @property
    def is_dirty(self) -> bool:
        """处理isdirty。
        
            返回:
                bool"""
        return self._dirty

    def flush(self) -> bool:
        """刷新相关对象。
        
            返回:
                bool"""
        ok = self._state.save()
        self._dirty = not ok
        return ok

    def set_page_selection(self, page_key: str, symbol: str, period: str) -> None:
        """设置页面selection。
        
            参数:
                page_key: str
                symbol: str
                period: str"""
        pages = self._state.data.setdefault("pages", {})
        pages[page_key] = {"symbol": symbol, "period": period}
        self._dirty = True

    def get_page_selection(self, page_key: str,
                           default_symbol: str = "rb.SHFE",
                           default_period: str = "D") -> tuple[str, str]:
        """获取页面selection。
        
            参数:
                page_key: str
                default_symbol: str
                default_period: str
        
            返回:
                tuple[str, str]"""
        p = self._state.data.get("pages", {}).get(page_key, {})
        return (p.get("symbol") or default_symbol,
                p.get("period") or default_period)
