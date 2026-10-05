"""M1.6 e2e：报告导出服务（PDF + Excel），离线验证。

验证点：
- ReportBundle 默认列推导、生成时间补齐。
- export_pdf 产出文件且 ok（reportlab 可用），缺指标/交易时仍 ok。
- export_excel 产出工作簿含 指标 sheet，有交易时含 交易明细 sheet。
- export_all 双通道。
- 数值格式化 _fmt（int 千分位、float 小数、str 原样）。
"""
from __future__ import annotations

import os
import tempfile
import unittest

import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from futures_quant.app.report_service import (
    ReportBundle,
    ReportService,
    DISCLAIMER,
)


class TestBundle(unittest.TestCase):
    def test_trade_columns_inferred(self) -> None:
        b = ReportBundle(trades=[{"t": "1", "p": 1.0}, {"p": 2.0, "t": "2"}])
        self.assertEqual(b.trade_columns, ["t", "p"])

    def test_generated_at_default(self) -> None:
        b = ReportBundle()
        self.assertTrue(b.generated_at)
        self.assertIn(":", b.generated_at)

    def test_empty_bundle_defaults(self) -> None:
        b = ReportBundle()
        self.assertEqual(b.trade_columns, [])
        self.assertEqual(b.metrics, {})


class TestFmts(unittest.TestCase):
    def test_fmt_int_thousands(self) -> None:
        self.assertEqual(ReportService._fmt(1000000), "1,000,000")

    def test_fmt_float(self) -> None:
        self.assertEqual(ReportService._fmt(1234.5678), "1,234.57")

    def test_fmt_str(self) -> None:
        self.assertEqual(ReportService._fmt("abc"), "abc")


class TestExport(unittest.TestCase):
    def _bundle(self) -> ReportBundle:
        return ReportBundle(
            title="回测报告",
            subtitle="rb · D",
            metrics={"夏普": 1.2345, "最大回撤": -8.5, "总收益": 210000},
            trades=[{"开": "2026-01-02", "平": "2026-01-05", "盈亏": 1234.56}],
            sections=[("结论", "整体趋势向上，胜率 62%。")],
        )

    def test_export_pdf_ok(self) -> None:
        svc = ReportService(self._bundle())
        d = tempfile.mkdtemp()
        p = os.path.join(d, "r.pdf")
        r = svc.export_pdf(p)
        self.assertTrue(r["ok"], r.get("reason"))
        self.assertTrue(os.path.exists(p))
        self.assertGreater(os.path.getsize(p), 200)
        self.assertEqual(r["metrics"], 3)
        self.assertEqual(r["trades"], 1)

    def test_export_excel_ok(self) -> None:
        svc = ReportService(self._bundle())
        d = tempfile.mkdtemp()
        p = os.path.join(d, "r.xlsx")
        r = svc.export_excel(p)
        self.assertTrue(r["ok"], r.get("reason"))
        self.assertTrue(os.path.exists(p))
        self.assertIn("指标", r["sheets"])
        self.assertIn("交易明细", r["sheets"])

    def test_export_all(self) -> None:
        svc = ReportService(self._bundle())
        d = tempfile.mkdtemp()
        base = os.path.join(d, "both")
        out = svc.export_all(base)
        self.assertTrue(out["pdf"]["ok"], out["pdf"].get("reason"))
        self.assertTrue(out["excel"]["ok"], out["excel"].get("reason"))
        self.assertTrue(os.path.exists(base + ".pdf"))
        self.assertTrue(os.path.exists(base + ".xlsx"))

    def test_empty_bundle_exports(self) -> None:
        svc = ReportService(ReportBundle(title="空"))
        d = tempfile.mkdtemp()
        r = svc.export_pdf(os.path.join(d, "e.pdf"))
        self.assertTrue(r["ok"], r.get("reason"))
        r2 = svc.export_excel(os.path.join(d, "e.xlsx"))
        self.assertTrue(r2["ok"], r2.get("reason"))
        # 空 bundle：无交易/无 sections → 仅「指标」sheet
        self.assertEqual(r2["sheets"], ["指标"])

    def test_disclaimer_present(self) -> None:
        self.assertIn("不构成任何投资建议", DISCLAIMER)


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
