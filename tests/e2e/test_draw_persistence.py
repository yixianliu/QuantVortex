"""M1.3 e2e：交互画线工具（几何 + 持久化往返 + 损坏恢复），离线验证。

验证点：
- new_tool 各类型参数归位正确，非法类型报错。
- fib_levels 生成 7 条标准回撤线（含 0/1 端点），y 坐标单调。
- DrawToolList.save → load 往返完全一致（云持久化→重启还原）。
- 序列化/反序列化 JSON 往返；损坏 JSON 降级空列表。
- 损坏主文件后 load 回退 .bak。
- 按类型过滤 / 删除 / 计数。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from futures_quant.ui.draw_tools import (
    DrawTool,
    DrawToolList,
    FIB_RATIOS,
    TOOL_TYPES,
    deserialize_tools,
    fib_levels,
    new_tool,
    serialize_tools,
)


def _full_list() -> DrawToolList:
    lst = DrawToolList()
    lst.add(new_tool("hline", y=0.7, color="#ef4444"))
    lst.add(new_tool("vline", x=0.3, color="#22c55e"))
    lst.add(new_tool("trend", 0.1, 0.2, 0.9, 0.8))
    lst.add(new_tool("fib", 0.2, 0.8))
    lst.add(new_tool("rect", 0.1, 0.1, 0.9, 0.9))
    lst.add(new_tool("text", 0.5, 0.5, text="顶部", color="#f59e0b"))
    return lst


class TestNewTool(unittest.TestCase):
    def test_types(self) -> None:
        for t in TOOL_TYPES:
            tool = new_tool(t, 0.2, 0.3, 0.4, 0.5, text="x")
            self.assertIsInstance(tool, DrawTool)
            self.assertEqual(tool.tool, t)

    def test_invalid_type(self) -> None:
        with self.assertRaises(ValueError):
            new_tool("magic")

    def test_params_placement(self) -> None:
        self.assertEqual(new_tool("hline", y=0.7).params["y"], 0.7)
        self.assertEqual(new_tool("vline", x=0.2).params["x"], 0.2)
        r = new_tool("rect", 0.1, 0.1, 0.9, 0.9).params
        self.assertEqual(r["x"], 0.1)
        self.assertEqual(r["y2"], 0.9)

    def test_clamp(self) -> None:
        self.assertEqual(new_tool("hline", y=5.0).params["y"], 1.0)
        self.assertEqual(new_tool("hline", y=-1.0).params["y"], 0.0)


class TestFib(unittest.TestCase):
    def test_levels(self) -> None:
        lv = fib_levels(0.2, 0.8)
        self.assertEqual(len(lv), len(FIB_RATIOS))
        self.assertEqual([x["ratio"] for x in lv], FIB_RATIOS)
        ys = [x["y"] for x in lv]
        self.assertEqual(ys, sorted(ys))  # 单调（a=0.2<b=0.8）
        self.assertAlmostEqual(ys[0], 0.2, places=6)
        self.assertAlmostEqual(ys[-1], 0.8, places=6)

    def test_reversed_anchors(self) -> None:
        lv = fib_levels(0.8, 0.2)  # 倒序锚点
        ys = [x["y"] for x in lv]
        self.assertEqual(ys, sorted(ys, reverse=True))


class TestSerialize(unittest.TestCase):
    def test_roundtrip(self) -> None:
        lst = _full_list()
        raw = serialize_tools(lst.tools)
        back = deserialize_tools(raw)
        self.assertEqual(back, lst.tools)

    def test_corrupted_returns_empty(self) -> None:
        self.assertEqual(deserialize_tools("{not json"), [])
        self.assertEqual(deserialize_tools(""), [])
        self.assertEqual(deserialize_tools("[1,2,3]"), [])  # 非工具字典


class TestPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="draw_tools_")
        self.path = os.path.join(self.tmp, "session_state.json")

    def test_save_load_roundtrip(self) -> None:
        lst = _full_list()
        ok = lst.save(self.path)
        self.assertTrue(ok)
        restored = DrawToolList.load(self.path)
        self.assertEqual(restored.tools, lst.tools)
        self.assertEqual(len(restored), 6)

    def test_crash_fallback_bak(self) -> None:
        lst = _full_list()
        lst.save(self.path)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{broken")
        restored = DrawToolList.load(self.path)
        self.assertEqual(restored.tools, lst.tools)  # 来自 .bak

    def test_missing_returns_empty(self) -> None:
        self.assertEqual(DrawToolList.load(self.path).tools, [])

    def test_by_type_and_remove(self) -> None:
        lst = _full_list()
        self.assertEqual(len(lst.by_type("trend")), 1)
        lst.remove(0)
        self.assertEqual(len(lst), 5)
        self.assertNotIn("hline", [t.tool for t in lst.tools])


if __name__ == "__main__":
    unittest.main(verbosity=2)
