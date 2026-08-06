"""R6 绩效归因对话框。

由回测中心历史表的「📊 详情」按钮触发。基于 ``BacktestStore.get_history_detail``
取回的 trades/equity_curve，渲染三块：
    1. 顶部摘要卡（品种/代数/收益/回撤/胜率/夏普等关键指标）；
    2. 月度收益柱状图（净收益，正绿负红，按月聚合）；
    3. 分笔成交表 + 持仓时长直方图（QSplitter 左右布局）。

零外部依赖：柱状图/直方图复用 ``chart_widget.PriceChart``（QPainter 渲染），
分笔表用 QTableWidget；offscreen 可跑。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QWidget, QAbstractItemView,
    QSizePolicy,
)

from .chart_widget import PriceChart
from .widgets import pal

_FONT = None  # 延迟初始化，使用系统字体


def _get_font() -> str:
    """返回优先使用的字体名称。"""
    global _FONT
    if _FONT is not None:
        return _FONT
    import sys
    if sys.platform == "win32":
        _FONT = "Microsoft YaHei"
    elif sys.platform == "darwin":
        _FONT = "PingFang SC"
    else:
        _FONT = "Noto Sans CJK SC"
    return _FONT


def _fmt_pct(v) -> str:
    """百分比格式：None/NaN → '—'，否则 '±X.XX%'。"""
    if v is None or not isinstance(v, (int, float)) or math.isnan(float(v)):
        return "—"
    return f"{float(v) * 100:+.2f}%"


def _fmt_num(v, digits: int = 2) -> str:
    if v is None or not isinstance(v, (int, float)) or math.isnan(float(v)):
        return "—"
    return f"{float(v):,.{digits}f}"


def _pair_round_trips(trades: Sequence[dict]) -> List[dict]:
    """把一连串 Trade（OPEN/CLOSE）配对成回合，统计持仓时长与盈亏。

    按 symbol + 开仓时间配对：每次 OPEN 类开始一个新回合，遇到 CLOSE 类收尾。
    跳过平今/平昨细节——简化为「回合=开仓 + 任意平仓」。
    """
    open_pos: Dict[Tuple[str, str], dict] = {}
    rounds: List[dict] = []
    for t in trades:
        offset = str(t.get("offset", "")).lower()
        direction = str(t.get("direction", "")).lower()
        sym = t.get("symbol", "")
        tdt_raw = t.get("datetime", "")
        if not tdt_raw:
            continue
        try:
            tdt = dt.datetime.fromisoformat(str(tdt_raw))
        except Exception:  # noqa: BLE001
            continue
        key = (sym, "long" if "long" in direction else
               "short" if "short" in direction else "flat")
        if "open" in offset and "close" not in offset:
            # 新开仓
            open_pos.setdefault(key, {"side": key[1], "qty": 0,
                                      "open_dt": tdt, "open_price": 0.0,
                                      "commission_open": 0.0})
            p = open_pos[key]
            p["qty"] = int(t.get("quantity", 0))
            p["open_price"] = float(t.get("price", 0.0))
            p["commission_open"] += float(t.get("commission", 0.0))
            p["open_dt"] = tdt
        elif "close" in offset:
            p = open_pos.pop(key, None)
            if p is None:
                continue
            pnl = float(t.get("pnl", 0.0))
            comm_close = float(t.get("commission", 0.0))
            hold_seconds = max(0.0, (tdt - p["open_dt"]).total_seconds())
            rounds.append({
                "symbol": sym,
                "side": p["side"],
                "qty": p["qty"],
                "open_dt": p["open_dt"],
                "close_dt": tdt,
                "hold_hours": hold_seconds / 3600.0,
                "pnl": pnl - comm_close,  # 净盈亏（开仓佣金已在 pnl 里扣过一次，按惯例不再扣）
                "commission": p["commission_open"] + comm_close,
            })
    return rounds


def _monthly_returns(rounds: Sequence[dict]) -> List[Tuple[str, float]]:
    """按 close_dt 的 (YYYY-MM) 聚合 pnl，返回 [(ym, pnl), ...] 倒序前 24 个月。"""
    buckets: Dict[str, float] = {}
    for r in rounds:
        ym = r["close_dt"].strftime("%Y-%m")
        buckets[ym] = buckets.get(ym, 0.0) + r["pnl"]
    items = sorted(buckets.items(), key=lambda kv: kv[0], reverse=True)
    return items[:24][::-1]  # 旧→新，方便画图


def _hold_buckets(rounds: Sequence[dict]) -> List[Tuple[str, int, float]]:
    """把持仓时长按 1/4/24/72/168h 分桶，统计盈亏总和（用于直方图颜色）。"""
    edges = [(0, 4), (4, 24), (24, 72), (72, 168), (168, 24 * 365)]
    labels = ["<4h", "4-24h", "1-3d", "3-7d", ">7d"]
    counts = [0] * len(labels)
    pnl_sum = [0.0] * len(labels)
    for r in rounds:
        h = r["hold_hours"]
        for i, (lo, hi) in enumerate(edges):
            if lo <= h < hi:
                counts[i] += 1
                pnl_sum[i] += r["pnl"]
                break
        else:
            # 超过 1 年
            counts[-1] += 1
            pnl_sum[-1] += r["pnl"]
    return [(labels[i], counts[i], pnl_sum[i]) for i in range(len(labels))]


class _SummaryCard(QFrame):
    """顶部关键指标卡：等宽排列 6 个标签。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("AttributionSummaryCard")
        self.setStyleSheet(
            "QFrame#AttributionSummaryCard { background: rgba(255,255,255,0.04);"
            " border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(18)
        self._cells: Dict[str, QLabel] = {}
        p = pal()
        for key in ("symbol", "gen", "return", "drawdown",
                    "winrate", "sharpe", "trades"):
            box = QVBoxLayout()
            box.setSpacing(0)
            title = QLabel({"symbol": "品种", "gen": "代数", "return": "总收益",
                            "drawdown": "最大回撤", "winrate": "胜率",
                            "sharpe": "夏普", "trades": "成交数"}[key])
            title.setFont(QFont(_get_font(), 9))
            title.setStyleSheet(f"color: {p['sub']};")
            val = QLabel("—")
            val.setFont(QFont(_get_font(), 12, QFont.Weight.Bold))
            val.setStyleSheet(f"color: {p['text']};")
            box.addWidget(title)
            box.addWidget(val)
            layout.addLayout(box)
            self._cells[key] = val
        layout.addStretch(1)

    def set_metric(self, key: str, text: str, color: str = "#e5e7eb") -> None:
        if key not in self._cells:
            return
        self._cells[key].setText(text)
        self._cells[key].setStyleSheet(f"color: {color};")


class AttributionDialog(QDialog):
    """回测历史详情对话框（R6）。

    用法：``AttributionDialog(detail_record, parent).exec()``。
    ``detail_record`` 来自 ``BacktestStore.get_history_detail(id)``。
    """

    def __init__(self, detail: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._detail = detail
        self.setWindowTitle("回测详情 · 绩效归因")
        self.resize(960, 640)
        self.setMinimumSize(QSize(820, 540))
        self.setStyleSheet(
            "QDialog { background: #1a1d24; color: #e5e7eb; }"
            " QHeaderView::section { background: #232730; color: #e5e7eb;"
            " padding: 6px; border: 0px; }"
            " QTableWidget { background: #14171c; gridline-color: #232730;"
            " alternate-background-color: #181c22; selection-background-color: "
            " #2b6cb0; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # 摘要卡
        self._summary = _SummaryCard(self)
        root.addWidget(self._summary)
        self._fill_summary(detail)

        # Splitter：左月度柱状 + 持仓直方图；右分笔表
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # 左侧：两个图表纵向堆叠
        charts_box = QWidget(splitter)
        charts_layout = QVBoxLayout(charts_box)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(8)
        self._month_chart = PriceChart(charts_box)
        self._month_chart.set_minimum_height = lambda h: None  # noop, avoid attr error
        self._month_chart.setMinimumHeight(220)
        self._hold_chart = PriceChart(charts_box)
        self._hold_chart.setMinimumHeight(180)
        charts_layout.addWidget(self._month_chart, 3)
        charts_layout.addWidget(self._hold_chart, 2)

        # 右侧：分笔表
        self._trade_tbl = QTableWidget(0, 7, splitter)
        self._trade_tbl.setHorizontalHeaderLabels(
            ["开仓时间", "平仓时间", "方向", "手数", "持仓时长", "盈亏(元)", "手续费"])
        self._trade_tbl.verticalHeader().setVisible(False)
        self._trade_tbl.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._trade_tbl.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._trade_tbl.setAlternatingRowColors(True)
        self._trade_tbl.setShowGrid(False)
        h = self._trade_tbl.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        splitter.addWidget(charts_box)
        splitter.addWidget(self._trade_tbl)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([360, 480])

        self._populate(detail)

    # ------------------------------------------------------------------
    def _fill_summary(self, d: dict) -> None:
        m = d.get("metrics") or {}
        sym = d.get("symbol", "—")
        gen = d.get("generation", "—")
        if isinstance(gen, int) and gen < 0:
            gen_text = "手动"
        else:
            gen_text = f"#{gen}"
        ret = m.get("total_return")
        ret_color = "#22c55e" if (isinstance(ret, (int, float))
                                  and ret > 0) else "#ef4444" if (
            isinstance(ret, (int, float)) and ret < 0) else "#e5e7eb"
        dd = m.get("max_drawdown")
        wr = m.get("win_rate")
        sh = m.get("sharpe")
        trades_n = m.get("num_closing_trades")
        self._summary.set_metric("symbol", f"{sym}")
        self._summary.set_metric("gen", gen_text)
        self._summary.set_metric("return", _fmt_pct(ret), ret_color)
        self._summary.set_metric("drawdown", _fmt_pct(dd))
        self._summary.set_metric("winrate", _fmt_pct(wr))
        self._summary.set_metric("sharpe", _fmt_num(sh))
        self._summary.set_metric("trades", f"{int(trades_n) if trades_n else 0}")

    # ------------------------------------------------------------------
    def _populate(self, d: dict) -> None:
        trades = d.get("trades") or []
        rounds = _pair_round_trips(trades)

        # 月度柱状
        monthly = _monthly_returns(rounds)
        if monthly:
            xs = list(range(len(monthly)))
            ys = [v for _, v in monthly]
            # 颜色随正负
            series = [{
                "name": "月度净收益",
                "x": xs,
                "y": ys,
                "color": "#22c55e" if sum(ys) >= 0 else "#ef4444",
                "width": 2.0,
            }]
            # 叠加零轴折线便于读数
            series.append({
                "name": "0",
                "x": xs,
                "y": [0.0] * len(xs),
                "color": "#8b93a7",
                "width": 1.0,
                "dashed": True,
            })
            x_ticks = [(i, ym) for i, (ym, _) in enumerate(monthly)]
            self._month_chart.set_data(
                series=series, x_ticks=x_ticks,
                title=f"月度净收益（元） · 共 {len(monthly)} 月")
        else:
            self._month_chart.set_data(title="月度净收益（无成交数据）")

        # 持仓时长直方图（颜色按累计盈亏着色）
        buckets = _hold_buckets(rounds)
        if any(c for _, c, _ in buckets):
            xs = list(range(len(buckets)))
            ys = [c for _, c, _ in buckets]
            pnl = [p for _, _, p in buckets]
            colors = ["#22c55e" if p > 0 else "#ef4444" if p < 0 else
                      "#8b93a7" for p in pnl]
            self._hold_chart.set_data(
                series=[{"name": "回合数", "x": xs, "y": ys,
                         "color": colors[0], "width": 2.0}],
                x_ticks=[(i, label) for i, (label, _, _) in enumerate(buckets)],
                title="持仓时长分布（5 桶）")
        else:
            self._hold_chart.set_data(title="持仓时长分布（无成交数据）")

        # 分笔表
        rows = sorted(rounds, key=lambda r: r["close_dt"], reverse=True)
        self._trade_tbl.setRowCount(len(rows))
        for r, rd in enumerate(rows):
            self._set_cell(r, 0, rd["open_dt"].strftime("%Y-%m-%d %H:%M"))
            self._set_cell(r, 1, rd["close_dt"].strftime("%Y-%m-%d %H:%M"))
            side_color = "#22c55e" if rd["side"] == "long" else "#ef4444"
            side_lbl = QTableWidgetItem(
                "多" if rd["side"] == "long" else "空")
            side_lbl.setForeground(QColor(side_color))
            self._trade_tbl.setItem(r, 2, side_lbl)
            self._set_cell(r, 3, str(rd["qty"]))
            hold = rd["hold_hours"]
            if hold < 24:
                hold_str = f"{hold:.1f} 小时"
            elif hold < 24 * 7:
                hold_str = f"{hold / 24:.1f} 天"
            else:
                hold_str = f"{hold / (24 * 30):.1f} 月"
            self._set_cell(r, 4, hold_str)
            pnl = rd["pnl"]
            pnl_color = QColor("#22c55e") if pnl > 0 else (
                QColor("#ef4444") if pnl < 0 else QColor("#e5e7eb"))
            pnl_item = QTableWidgetItem(_fmt_num(pnl, 0))
            pnl_item.setForeground(pnl_color)
            self._trade_tbl.setItem(r, 5, pnl_item)
            self._set_cell(r, 6, _fmt_num(rd["commission"], 2))

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setForeground(QColor("#e5e7eb"))
        self._trade_tbl.setItem(row, col, item)
