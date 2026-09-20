"""M1.3 交互画线工具：水平/垂直线、斐波那契回撤、趋势线、矩形、文本标注，支持持久化。

设计（离线、零额外依赖、可序列化）：
- 几何模型与 Qt 解耦：每个 ``DrawTool`` 是纯数据（坐标归一化到图表 0~1 域），
  序列化/反序列化用 JSON，便于云持久化到 ``data/session_state.json``。
- 图表坐标系：以「可见 K 线窗口」为归一化基准（x: 0=最左可见根, 1=最右；
  y: 0=最低价, 1=最高价），重启后按当前数据重新定位即可还原。
- 持久化：``DrawToolList.save(path)`` / ``DrawToolList.load(path)``，复用
  ``storage.json_store.AtomicJSON`` 的原子写 + .bak 回退。

工具类型（``tool`` 字段）：
- hline   水平线（单 y）
- vline   垂直线（单 x）
- trend   趋势线（两点）
- fib     斐波那契回撤（两点锚定，自动生成分数水平线）
- rect    矩形（两对角点）
- text    文本标注（点 + 文本）
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

__all__ = [
    "DrawTool",
    "TOOL_TYPES",
    "FIB_RATIOS",
    "new_tool",
    "fib_levels",
    "serialize_tools",
    "deserialize_tools",
    "DrawToolList",
]

TOOL_TYPES: List[str] = ["hline", "vline", "trend", "fib", "rect", "text"]

# 斐波那契回撤标准分数（0~1，含 0 与 1 端点）
FIB_RATIOS: List[float] = [0.0, 0.236, 0.382, 0.5, 0.618, 0.809, 1.0]


class DrawTool:
    """单个画线工具（纯几何，可序列化）。"""

    def __init__(self, tool: str, params: Optional[Dict[str, Any]] = None,
                 color: str = "#3b82f6", label: str = "") -> None:
        if tool not in TOOL_TYPES:
            raise ValueError(f"未知工具类型：{tool!r}（可选 {TOOL_TYPES}）")
        self.tool = tool
        self.params: Dict[str, Any] = dict(params or {})
        self.color = color
        self.label = label

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, DrawTool):
            return False
        return (self.tool == other.tool and self.params == other.params
                and self.color == other.color and self.label == other.label)

    def to_dict(self) -> Dict[str, Any]:
        return {"tool": self.tool, "params": self.params,
                "color": self.color, "label": self.label}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DrawTool":
        return cls(d.get("tool", ""), d.get("params") or {},
                   d.get("color", "#3b82f6"), d.get("label", ""))


def new_tool(tool: str, x: float = 0.5, y: float = 0.5,
             x2: float = 0.5, y2: float = 0.5,
             text: str = "", color: str = "#3b82f6") -> DrawTool:
    """构造一个工具（参数按类型自动归位到 params）。"""
    p: Dict[str, Any] = {}
    if tool in ("hline", "text"):
        p["y"] = _clamp01(y)
    elif tool == "vline":
        p["x"] = _clamp01(x)
    elif tool in ("trend", "fib", "rect"):
        p["x"], p["y"] = _clamp01(x), _clamp01(y)
        p["x2"], p["y2"] = _clamp01(x2), _clamp01(y2)
    if tool == "text":
        p["text"] = text
    return DrawTool(tool, p, color=color)


def _clamp01(v: float) -> float:
    try:
        return min(max(float(v), 0.0), 1.0)
    except Exception:
        return 0.5


def fib_levels(anchor_y: float, anchor_y2: float) -> List[Dict[str, float]]:
    """由两个锚点 y 坐标生成斐波那契回撤水平线（归一化 y 坐标 + 分数）。"""
    a, b = _clamp01(anchor_y), _clamp01(anchor_y2)
    span = b - a
    out = []
    for r in FIB_RATIOS:
        y = a + r * span
        out.append({"ratio": r, "y": _clamp01(y)})
    return out


def serialize_tools(tools: List[DrawTool]) -> str:
    """工具列表 → JSON 字符串（云持久化用）。"""
    return json.dumps([t.to_dict() for t in tools], ensure_ascii=False)


def deserialize_tools(raw: str) -> List[DrawTool]:
    """JSON 字符串 → 工具列表。空/损坏返回 []。"""
    if not raw:
        return []
    try:
        arr = json.loads(raw)
        if not isinstance(arr, list):
            return []
        return [DrawTool.from_dict(d) for d in arr if isinstance(d, dict) and d.get("tool") in TOOL_TYPES]
    except Exception:
        return []


class DrawToolList:
    """可持久化的画线工具集合。

    用法：
        lst = DrawToolList()
        lst.add(new_tool("trend", 0.1, 0.2, 0.9, 0.8))
        lst.save(path)      # 云持久化
        lst2 = DrawToolList().load(path)  # 重启后还原
    """

    def __init__(self, tools: Optional[List[DrawTool]] = None) -> None:
        self.tools: List[DrawTool] = list(tools or [])

    def add(self, tool: DrawTool) -> "DrawToolList":
        if not isinstance(tool, DrawTool):
            raise TypeError("必须传 DrawTool 实例")
        self.tools.append(tool)
        return self

    def remove(self, idx: int) -> None:
        if 0 <= idx < len(self.tools):
            del self.tools[idx]

    def by_type(self, tool_type: str) -> List[DrawTool]:
        return [t for t in self.tools if t.tool == tool_type]

    def __len__(self) -> int:
        return len(self.tools)

    # ---------------- 序列化 ----------------
    def to_json(self) -> str:
        return serialize_tools(self.tools)

    @classmethod
    def from_json(cls, raw: str) -> "DrawToolList":
        return cls(deserialize_tools(raw))

    # ---------------- 持久化（原子写 + 回退） ----------------
    def save(self, path: str) -> bool:
        try:
            from ..storage.json_store import AtomicJSON
            store = AtomicJSON(path, default={"draw_tools": []})
            store.set("draw_tools", [t.to_dict() for t in self.tools])
            return store.save()
        except Exception:
            # 兜底：直接原子写 JSON
            return _atomic_write(path, self.to_json())

    @classmethod
    def load(cls, path: str) -> "DrawToolList":
        """加载画线工具；主文件损坏时自动回退 .bak（与 json_store 一致）。

        注意：回退仅在**整文件损坏**时发生（.bak 是上一次成功保存的整份）。
        """
        # 优先读主文件（可能已是旧版 schema 或缺失 .bak）
        raw = None
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    raw = f.read()
                # 主文件是合法 JSON 且能解析出工具 → 直接用
                data = json.loads(raw)
                arr = data.get("draw_tools") if isinstance(data, dict) else data
                if isinstance(arr, list):
                    return cls([DrawTool.from_dict(d) for d in arr
                                if isinstance(d, dict) and d.get("tool") in TOOL_TYPES])
        except Exception:
            raw = None  # 主文件损坏 → 落 .bak
        # 回退 .bak
        try:
            if os.path.exists(path + ".bak"):
                with open(path + ".bak", "r", encoding="utf-8") as f:
                    data = json.load(f)
                arr = data.get("draw_tools") if isinstance(data, dict) else data
                if isinstance(arr, list):
                    return cls([DrawTool.from_dict(d) for d in arr
                                if isinstance(d, dict) and d.get("tool") in TOOL_TYPES])
        except Exception:
            pass
        return cls()


def _atomic_write(path: str, content: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        if os.path.exists(path):
            os.replace(path, path + ".bak")
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _atomic_read(path: str) -> Optional[str]:
    for p in (path, path + ".bak"):
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            continue
    return None
