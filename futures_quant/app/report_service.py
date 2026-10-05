"""M1.6 报告导出服务：把回测 / 研究结果导出为 PDF 与 Excel（离线、零 UI 依赖）。

设计（决策门 D1.6：PDF + Excel 双通道，缺库优雅降级）：
- ``ReportService`` 接收结构化 ``ReportBundle``（标题 / 指标表 / 交易明细 / 文本段），
  按需产出：
  - ``export_pdf(path)``：用 reportlab Platypus 排版（封面 + 指标表 + 交易明细 + 文本段）。
    reportlab 缺失时返回 ``{"ok": False, "reason": "reportlab 不可用"}``，绝不崩。
  - ``export_excel(path)``：用 openpyxl 写工作簿（指标 sheet + 交易 sheet + 说明 sheet）。
    openpyxl 缺失同样降级。
- 无未来函数：只导出已给定的指标与交易记录，不做预测。
- 风险提示语（护栏 7）：每份报告页脚固定「历史表现不代表未来，不构成任何投资建议」。

用法:
    svc = ReportService(bundle)
    r = svc.export_pdf("report.pdf")   # {"ok": True, "path": ..., "rows": N}
    e = svc.export_excel("report.xlsx") # {"ok": True, "path": ..., "sheets": [...]}
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "ReportBundle",
    "ReportService",
    "DISCLAIMER",
]

DISCLAIMER: str = "历史表现不代表未来，本输出不构成任何投资建议。"


@dataclass
class ReportBundle:
    """待导出的报告数据束。

    参数:
        title: 报告标题。
        subtitle: 副标题（合约 / 周期 / 日期等）。
        metrics: 指标 ``{名称: 值}``（有序 dict）。
        trades: 交易明细列表 ``[{列...}]``（每项含 ``cols`` 顺序或扁平 dict）。
        trade_columns: 交易表列顺序（可选）。
        sections: 文本段落 ``[(小节标题, 正文), ...]``。
        generated_at: 生成时间（默认 now）。
    """
    title: str = "量化研究报告"
    subtitle: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    trade_columns: Optional[List[str]] = None
    sections: List[tuple[str, str]] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self) -> None:
        """补齐默认生成时间。"""
        if not self.generated_at:
            self.generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.trade_columns is None:
            cols: List[str] = []
            for t in self.trades:
                for k in t.keys():
                    if k not in cols:
                        cols.append(k)
            self.trade_columns = cols or []


class ReportService:
    """报告导出服务（PDF + Excel，缺库降级）。

    参数:
        bundle: 待导出的报告数据束。
    """

    def __init__(self, bundle: Optional[ReportBundle] = None) -> None:
        """初始化服务。

        参数:
            bundle: 报告数据束（None 时给空束，方便测试后 set）。"""
        self._bundle = bundle or ReportBundle()

    def set_bundle(self, bundle: ReportBundle) -> None:
        """替换报告数据束。

        参数:
            bundle: 报告数据束。"""
        self._bundle = bundle

    # ---------------- 指标 / 交易标准化 ----------------
    def _metric_rows(self) -> List[List[str]]:
        """指标表 → 行 ``[[名称, 值], ...]``。"""
        return [[str(k), self._fmt(v)] for k, v in (self._bundle.metrics or {}).items()]

    def _trade_rows(self) -> List[List[str]]:
        """交易明细 → 行（按 trade_columns 顺序，缺失列取空）。"""
        cols = self._bundle.trade_columns or []
        rows = []
        for t in (self._bundle.trades or []):
            rows.append([self._fmt(t.get(c, "")) for c in cols])
        return rows

    @staticmethod
    def _fmt(v: Any) -> str:
        """统一数值格式化（浮点去尾零，其余原样转字符串）。"""
        if isinstance(v, float):
            return f"{v:,.2f}" if abs(v) >= 1e-4 else f"{v:.6g}"
        if isinstance(v, (int,)):
            return f"{v:,}"
        return str(v)

    # ---------------- PDF ----------------
    def export_pdf(self, path: str) -> Dict[str, Any]:
        """导出 PDF（reportlab Platypus）。缺库降级，不崩。

        参数:
            path: 目标文件路径。

        返回:
            dict: ``{"ok", "path", "metrics", "trades", "reason"}``。"""
        try:
            from reportlab.lib import colors, units
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            )
        except Exception as e:  # 缺 reportlab
            return {"ok": False, "path": path, "reason": f"reportlab 不可用: {e}"}

        b = self._bundle
        doc = SimpleDocTemplate(
            path, pagesize=A4,
            leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40,
            title=b.title,
        )
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("H1x", parent=styles["Title"], fontSize=20,
                            spaceAfter=4, alignment=1)
        h2 = ParagraphStyle("H2x", parent=styles["Heading2"], fontSize=13,
                            spaceBefore=10, spaceAfter=4)
        body = ParagraphStyle("Bodyx", parent=styles["BodyText"], fontSize=10)
        small = ParagraphStyle("Smal", parent=styles["BodyText"], fontSize=8,
                               textColor=colors.HexColor("#6b7280"))

        story: List[Any] = []
        story.append(Paragraph(b.title, h1))
        if b.subtitle:
            story.append(Paragraph(b.subtitle, small))
        story.append(Paragraph(f"生成时间：{b.generated_at}", small))
        story.append(Spacer(1, 8))

        # 指标表
        mrows = self._metric_rows()
        if mrows:
            story.append(Paragraph("一、核心指标", h2))
            mtable = Table([["指标", "值"]] + mrows, colWidths=[180, 180])
            mtable.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(mtable)

        # 交易明细
        trows = self._trade_rows()
        if trows:
            story.append(Paragraph("二、交易明细（前 200 条）", h2))
            head = ["列号" if False else c for c in (b.trade_columns or [])]
            data = [head] + trows[:200]
            ttable = Table(data, repeatRows=1)
            ttable.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(ttable)

        # 文本段落
        for i, (sec_title, sec_body) in enumerate(b.sections, start=3):
            story.append(Paragraph(f"{_cn_num(i)}、{sec_title}", h2))
            story.append(Paragraph(sec_body or "（无）", body))

        # 风险声明
        story.append(Spacer(1, 12))
        story.append(Paragraph(DISCLAIMER, small))

        try:
            doc.build(story)
            return {"ok": True, "path": path,
                    "metrics": len(mrows), "trades": min(len(trows), 200)}
        except Exception as e:
            return {"ok": False, "path": path, "reason": f"PDF 构建失败: {e}"}

    # ---------------- Excel ----------------
    def export_excel(self, path: str) -> Dict[str, Any]:
        """导出 Excel（openpyxl 工作簿）。缺库降级，不崩。

        参数:
            path: 目标 .xlsx 路径。

        返回:
            dict: ``{"ok", "path", "sheets", "reason"}``。"""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
        except Exception as e:
            return {"ok": False, "path": path, "reason": f"openpyxl 不可用: {e}"}

        b = self._bundle
        wb = Workbook()
        header_fill = PatternFill("solid", fgColor="1F2937")
        header_font = Font(bold=True, color="FFFFFF")
        center = Alignment(horizontal="center", vertical="center")

        # Sheet 1：指标
        ws = wb.active
        ws.title = "指标"
        ws.append(["指标", "值"])
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
        for k, v in (b.metrics or {}).items():
            ws.append([str(k), self._fmt(v)])
        ws.append([])
        ws.append(["生成时间", b.generated_at])
        ws.append(["风险声明", DISCLAIMER])

        # Sheet 2：交易明细
        if b.trades:
            ws2 = wb.create_sheet("交易明细")
            ws2.append(list(b.trade_columns or []))
            for cell in ws2[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = center
            for t in b.trades:
                ws2.append([self._fmt(t.get(c, "")) for c in (b.trade_columns or [])])

        # Sheet 3：说明（文本段）
        if b.sections:
            ws3 = wb.create_sheet("说明")
            ws3.append(["小节", "内容"])
            for cell in ws3[1]:
                cell.fill = header_fill
                cell.font = header_font
            for title, body in b.sections:
                ws3.append([title, body])

        try:
            wb.save(path)
            sheets = [s.title for s in wb.worksheets]
            return {"ok": True, "path": path, "sheets": sheets}
        except Exception as e:
            return {"ok": False, "path": path, "reason": f"Excel 保存失败: {e}"}

    # ---------------- 一键双通道 ----------------
    def export_all(self, base: str) -> Dict[str, Any]:
        """同时导出 PDF + Excel（``base`` 不带扩展名）。

        参数:
            base: 目标基础路径（如 ``report`` → ``report.pdf`` / ``report.xlsx``）。

        返回:
            dict: ``{"pdf": {...}, "excel": {...}}``。"""
        return {"pdf": self.export_pdf(base + ".pdf"),
                "excel": self.export_excel(base + ".xlsx")}


def _cn_num(n: int) -> str:
    """1~99 转中文序数（一、二、三…）。"""
    digits = "零一二三四五六七八九十"
    if n <= 10:
        return digits[n]
    tens, ones = divmod(n, 10)
    s = ""
    if tens > 1:
        s += digits[tens]
    s += "十" if tens >= 1 else ""
    if ones:
        s += digits[ones]
    return s or str(n)


__all__.append("_cn_num")
