"""回测引擎（驱动历史行情，产出绩效报告）。

流程：
    1) 从 DataFeed 取历史 K 线；
    2) 逐根 bar 送入 TradingEngine.process_bar（信号当日收盘产生，次日开盘撮合）；
    3) 统计绩效指标，导出 equity.csv / trades.csv / summary.json 与 HTML 报告。

注意：本文件用于「已加载真实/合成行情」后的回测。示例用合成数据验证引擎逻辑，
请勿把合成结果当作真实市场结论。
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import Optional

import pandas as pd

from ..config.settings import Config
from ..core.engine import TradingEngine
from ..core.types import Offset, Direction


def compute_metrics(equity_curve: list, trades: list) -> dict:
    """从资金曲线与成交记录计算绩效指标。"""
    if not equity_curve:
        return {}
    eq = pd.Series([e[1] for e in equity_curve], dtype=float)
    start = float(eq.iloc[0])
    end = float(eq.iloc[-1])
    total_return = (end / start - 1) if start else 0.0

    # 最大回撤
    run_max = eq.cummax()
    dd = (run_max - eq) / run_max.replace(0, float("nan"))
    max_dd = float(dd.max())

    # 年化（按日重采样）
    sharpe = None
    annual_return = None
    try:
        idx = pd.to_datetime([e[0] for e in equity_curve])
        eqd = pd.Series(eq.values, index=idx).resample("D").last().dropna()
        if len(eqd) > 1:
            daily_ret = eqd.pct_change().dropna()
            if daily_ret.std() > 0:
                sharpe = float(daily_ret.mean() / daily_ret.std() * (252 ** 0.5))
            annual_return = float((eqd.iloc[-1] / eqd.iloc[0]) ** (252 / len(eqd)) - 1)
    except Exception:
        pass

    # 平仓交易统计
    close_trades = [t for t in trades if t.offset in (Offset.CLOSE, Offset.CLOSE_TODAY, Offset.CLOSE_YESTERDAY)]
    wins = [t.pnl for t in close_trades if t.pnl > 0]
    losses = [t.pnl for t in close_trades if t.pnl < 0]
    win_rate = (len(wins) / len(close_trades)) if close_trades else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (-gross_loss / len(losses)) if losses else 0.0

    # 开仓方向分布（持仓分布图用）
    long_opens = sum(1 for t in trades if t.offset == Offset.OPEN and t.direction == Direction.LONG)
    short_opens = sum(1 for t in trades if t.offset == Offset.OPEN and t.direction == Direction.SHORT)

    return {
        "start_equity": round(start, 2),
        "end_equity": round(end, 2),
        "total_return": round(total_return, 4),
        "annual_return": None if annual_return is None else round(annual_return, 4),
        "sharpe": None if sharpe is None else round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": None if profit_factor == float("inf") else round(profit_factor, 3),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "num_fills": len(trades),
        "num_closing_trades": len(close_trades),
        "long_opens": long_opens,
        "short_opens": short_opens,
    }


class Backtester:
    def __init__(self, config: Config, feed, logger=None, db=None) -> None:
        self.config = config
        self.feed = feed
        self.logger = logger
        self.db = db
        self.engine = TradingEngine(config, logger=logger, mode="backtest", db=db)

    def add_contract(self, contract) -> None:
        self.engine.add_contract(contract)

    def add_strategy(self, strategy) -> None:
        self.engine.register_strategy(strategy)

    def run(self, symbol: str, start: str, end: str, period: str = "1m", warmup: int = 0) -> dict:
        df = self.feed.get_history(symbol, start, end, period)
        if df.empty:
            raise ValueError(f"未取到 {symbol} 的行情数据。")
        self.engine.start()

        records = df.to_dict("records")
        for i, r in enumerate(records):
            if i < warmup:
                # 预热：仅更新价格，不跑策略，避免指标 NaN 误触发
                self.engine._current_dt = r["datetime"]
                self.engine.portfolio.update_price(symbol, r["close"])
                self.engine.equity_curve.append((r["datetime"], self.engine.portfolio.equity(), self.engine.portfolio.available()))
                continue
            from ..core.types import Bar
            bar = Bar(
                symbol=symbol, datetime=r["datetime"], open=float(r["open"]),
                high=float(r["high"]), low=float(r["low"]), close=float(r["close"]),
                volume=float(r["volume"]), open_interest=float(r["open_interest"]),
            )
            self.engine.process_bar(bar)

        metrics = compute_metrics(self.engine.equity_curve, self.engine.trades_log)
        return {"metrics": metrics, "equity_curve": self.engine.equity_curve,
                "trades": self.engine.trades_log}

    # ---------- 导出 ----------
    def export(self, outdir: str = ".", prefix: str = "backtest") -> dict:
        os.makedirs(outdir, exist_ok=True)
        eq_path = os.path.join(outdir, f"{prefix}_equity.csv")
        tr_path = os.path.join(outdir, f"{prefix}_trades.csv")
        sum_path = os.path.join(outdir, f"{prefix}_summary.json")
        html_path = os.path.join(outdir, f"{prefix}_report.html")

        # 资金曲线
        eq_df = pd.DataFrame(self.engine.equity_curve, columns=["datetime", "equity", "available"])
        eq_df.to_csv(eq_path, index=False)

        # 成交
        rows = [{
            "datetime": str(t.datetime), "symbol": t.symbol, "direction": t.direction.value,
            "offset": t.offset.value, "quantity": t.quantity, "price": t.price,
            "commission": t.commission, "pnl": t.pnl, "order_id": t.order_id,
        } for t in self.engine.trades_log]
        tr_df = pd.DataFrame(rows)
        tr_df.to_csv(tr_path, index=False)

        # 概要
        metrics = compute_metrics(self.engine.equity_curve, self.engine.trades_log)
        summary = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "metrics": metrics,
            "params": self.config.to_dict(),
        }
        with open(sum_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # HTML 报告（内嵌 SVG 资金曲线，无第三方依赖）
        self._write_html(html_path, metrics)

        return {"equity": eq_path, "trades": tr_path, "summary": sum_path, "html": html_path}

    def _write_html(self, path: str, metrics: dict) -> None:
        curve = self.engine.equity_curve
        svg_equity = self._equity_svg(curve)
        svg_pnl = self._pnl_bars_svg(self.engine.trades_log)
        daily = self._daily_pnl(curve)
        svg_daily = self._daily_pnl_svg(daily)
        svg_dist = self._pos_dist_svg(metrics.get("long_opens", 0), metrics.get("short_opens", 0))
        daily_summary = self._daily_summary_html(daily)

        rows = "".join(
            f"<tr><td>{t.datetime}</td><td>{t.symbol}</td><td>{t.direction.value}</td>"
            f"<td>{t.offset.value}</td><td>{t.quantity}</td><td>{t.price:.2f}</td>"
            f"<td>{t.commission:.2f}</td><td>{t.pnl:.2f}</td></tr>"
            for t in self.engine.trades_log[:200]
        )
        m = metrics or {}
        cards = "".join(
            f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>'
            for k, v in m.items()
        )
        html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>回测报告</title><style>
body{{font-family:-apple-system,'Segoe UI',sans-serif;background:#0f1116;color:#e6e6e6;margin:0;padding:24px}}
h1{{font-size:20px}} h3{{font-size:15px;color:#8b93a7;margin:22px 0 8px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.card{{background:#1a1d27;border:1px solid #2a2e3a;border-radius:10px;padding:12px 16px;min-width:110px}}
.k{{color:#8b93a7;font-size:12px}} .v{{font-size:18px;margin-top:4px;color:#7ee787}}
.chart-grid{{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start}}
table{{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}}
th,td{{border:1px solid #2a2e3a;padding:6px 8px;text-align:left}}
th{{background:#1a1d27;color:#8b93a7}} .warn{{color:#ff7b72}}
.dstat{{font-size:12px;color:#cbd5e1;line-height:1.8}}
.dstat b{{color:#e6e6e6}}
</style></head><body>
<h1>期货策略回测报告</h1>
<div class="cards">{cards}</div>
<h3>资金曲线</h3>{svg_equity}
<div class="chart-grid">
  <div style="flex:1;min-width:360px">
    <h3>逐笔盈亏</h3>{svg_pnl}
  </div>
  <div style="width:200px">
    <h3>多空持仓分布</h3>{svg_dist}
  </div>
</div>
<h3>每日盈亏</h3>{svg_daily}
<h3>每日交易统计</h3><div class="dstat">{daily_summary}</div>
<h3>成交明细（前200条）</h3>
<table><tr><th>时间</th><th>合约</th><th>方向</th><th>开平</th><th>数量</th><th>价格</th><th>手续费</th><th>盈亏</th></tr>
{rows}</table>
<p class="warn">⚠️ 以上由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。</p>
</body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    # ---------- 图表辅助（内联 SVG，无第三方依赖） ----------
    @staticmethod
    def _pnl_bars_svg(trades, w: int = 600, h: int = 220, max_bars: int = 150) -> str:
        closes = [t for t in trades
                  if t.offset in (Offset.CLOSE, Offset.CLOSE_TODAY, Offset.CLOSE_YESTERDAY) and t.pnl != 0]
        if not closes:
            return "<p style='color:#8b93a7'>无平仓交易</p>"
        if len(closes) > max_bars:
            closes = closes[-max_bars:]
        vals = [t.pnl for t in closes]
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1.0
        pad = 16
        n = len(vals)
        bw = (w - 2 * pad) / n
        zero_y = pad + hi / rng * (h - 2 * pad)
        bars = []
        for i, v in enumerate(vals):
            x = pad + i * bw
            y = pad + (hi - v) / rng * (h - 2 * pad)
            color = "#22c55e" if v >= 0 else "#ef4444"
            bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bw*0.7,0.5):.1f}" '
                        f'height="{abs(y-zero_y):.1f}" fill="{color}"/>')
        line = (f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{w-pad}" y2="{zero_y:.1f}" '
                f'stroke="#475569" stroke-width="1"/>')
        return (f'<svg viewBox="0 0 {w} {h}" width="100%" '
                f'style="background:#11141c;border-radius:8px">{line}{"".join(bars)}</svg>')

    @staticmethod
    def _daily_pnl(curve: list) -> list:
        if not curve:
            return []
        s = pd.Series([e[1] for e in curve], index=pd.to_datetime([e[0] for e in curve]))
        s = s.resample("D").last().dropna()
        diffs = s.diff().dropna()
        return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in diffs.items()]

    @staticmethod
    def _daily_pnl_svg(daily, w: int = 900, h: int = 200, max_bars: int = 250) -> str:
        if not daily:
            return "<p style='color:#8b93a7'>无每日数据</p>"
        if len(daily) > max_bars:
            daily = daily[-max_bars:]
        vals = [v for _, v in daily]
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1.0
        pad = 16
        n = len(vals)
        bw = (w - 2 * pad) / n
        zero_y = pad + hi / rng * (h - 2 * pad)
        bars = []
        for i, v in enumerate(vals):
            x = pad + i * bw
            y = pad + (hi - v) / rng * (h - 2 * pad)
            color = "#22c55e" if v >= 0 else "#ef4444"
            bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bw*0.7,0.5):.1f}" '
                        f'height="{abs(y-zero_y):.1f}" fill="{color}"/>')
        line = (f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{w-pad}" y2="{zero_y:.1f}" '
                f'stroke="#475569" stroke-width="1"/>')
        return (f'<svg viewBox="0 0 {w} {h}" width="100%" '
                f'style="background:#11141c;border-radius:8px">{line}{"".join(bars)}</svg>')

    @staticmethod
    def _pos_dist_svg(long_n: int, short_n: int, size: int = 180) -> str:
        total = long_n + short_n
        if total == 0:
            return "<p style='color:#8b93a7'>无开仓</p>"
        cx = cy = size / 2
        r = size / 2 - 12
        lw = 26

        def arc(frac_start: float, frac_end: float, color: str) -> str:
            a0 = frac_start * 2 * math.pi - math.pi / 2
            a1 = frac_end * 2 * math.pi - math.pi / 2
            x0 = cx + r * math.cos(a0)
            y0 = cy + r * math.sin(a0)
            x1 = cx + r * math.cos(a1)
            y1 = cy + r * math.sin(a1)
            large = 1 if (frac_end - frac_start) > 0.5 else 0
            return (f'<path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 {large} 1 {x1:.1f} {y1:.1f}" '
                    f'fill="none" stroke="{color}" stroke-width="{lw}"/>')

        svg = f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        if long_n > 0:
            svg += arc(0, long_n / total, "#22c55e")
        if short_n > 0:
            svg += arc(long_n / total, 1.0, "#ef4444")
        svg += (f'<text x="{cx}" y="{cy-4}" fill="#e6e6e6" font-size="13" '
                f'text-anchor="middle">多 {long_n}</text>')
        svg += (f'<text x="{cx}" y="{cy+14}" fill="#e6e6e6" font-size="13" '
                f'text-anchor="middle">空 {short_n}</text>')
        svg += "</svg>"
        return svg

    @staticmethod
    def _daily_summary_html(daily: list) -> str:
        if not daily:
            return "无每日数据"
        pnls = [v for _, v in daily]
        win_days = sum(1 for v in pnls if v > 0)
        loss_days = sum(1 for v in pnls if v < 0)
        flat_days = len(pnls) - win_days - loss_days
        best = max(daily, key=lambda x: x[1])
        worst = min(daily, key=lambda x: x[1])
        return (f"交易日数：<b>{len(pnls)}</b> ｜ 盈利日：<b style='color:#22c55e'>{win_days}</b> ｜ "
                f"亏损日：<b style='color:#ef4444'>{loss_days}</b> ｜ 持平日：<b>{flat_days}</b><br>"
                f"最佳单日：<b style='color:#22c55e'>{best[0]} +{best[1]:,.2f}</b> ｜ "
                f"最差单日：<b style='color:#ef4444'>{worst[0]} {worst[1]:,.2f}</b>")

    @staticmethod
    def _equity_svg(curve: list, w: int = 900, h: int = 280) -> str:
        if not curve:
            return "<p>无数据</p>"
        ys = [e[1] for e in curve]
        lo, hi = min(ys), max(ys)
        n = len(ys)
        pad = 10
        def x(i): return pad + i * (w - 2 * pad) / max(1, n - 1)
        def y(v): return pad + (hi - v) / (hi - lo or 1) * (h - 2 * pad)
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(ys))
        area = f"{pad},{h-pad} " + pts + f" {w-pad},{h-pad}"
        return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="background:#11141c;border-radius:8px">'
                f'<polygon points="{area}" fill="#7ee78722"/>'
                f'<polyline points="{pts}" fill="none" stroke="#7ee787" stroke-width="1.5"/></svg>')
