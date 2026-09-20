"""M1.2 e2e：设计系统（规范色板 + 一键全量刷新 + 回归护栏），离线验证。

验证点：
- DESIGN 含规范四色（dark bg #1e1e2e / text #dcdcdc / up #ff4757 / down #2ed573）。
- apply_design 注入 widgets.PALETTE，THEME 切换。
- reset_design 恢复原 PALETTE（回归护栏，保证旧 e2e 不被设计覆盖污染）。
- design_tokens 返回拷贝（改原表不影响）。
- 无崩溃。
"""
from __future__ import annotations

import unittest

from futures_quant.ui.design_system import (
    DESIGN,
    design_tokens,
    apply_design,
    reset_design,
)


class TestDesignTokens(unittest.TestCase):
    def test_spec_colors_present(self) -> None:
        d = DESIGN["dark"]
        self.assertEqual(d["bg"], "#1e1e2e")
        self.assertEqual(d["text"], "#dcdcdc")
        self.assertEqual(d["up"], "#ff4757")
        self.assertEqual(d["down"], "#2ed573")

    def test_light_theme_present(self) -> None:
        self.assertIn("light", DESIGN)
        self.assertEqual(DESIGN["light"]["up"], "#ff4757")

    def test_design_tokens_returns_copy(self) -> None:
        snap = dict(DESIGN["dark"])
        t = design_tokens("dark")
        t["bg"] = "changed"
        self.assertEqual(DESIGN["dark"]["bg"], snap["bg"])
        # 回退主题
        self.assertEqual(design_tokens("bogus")["bg"], snap["bg"])


class TestApplyReset(unittest.TestCase):
    def test_apply_injects_palette(self) -> None:
        from futures_quant.ui import widgets as W
        before = dict(W.PALETTE["dark"])
        try:
            out = apply_design("dark", refresh_widgets=False)
            self.assertEqual(out["bg"], "#1e1e2e")
            self.assertEqual(W.PALETTE["dark"]["bg"], "#1e1e2e")
            self.assertEqual(W.THEME, "dark")
        finally:
            reset_design()
            # 恢复后 PALETTE 的 dark.bg 应回到原值（非规范色）
            self.assertEqual(W.PALETTE["dark"]["bg"], before["bg"])

    def test_apply_light(self) -> None:
        from futures_quant.ui import widgets as W
        try:
            apply_design("light", refresh_widgets=False)
            self.assertEqual(W.PALETTE["light"]["up"], "#ff4757")
        finally:
            reset_design()


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
