# -*- coding: utf-8 -*-
"""
红利ETF(510880) 定投(DCA) 回测 + 与「半导体回调分批」横向对比

数据来源：westock-data 拉取的 510880 日线前复权(qfq)数据，已落盘为
        510880_daily_qfq.csv（本脚本仅读取，不硬编码价格）。
        上一轮半导体回测的三件套（semiconductor_dipbuy_*）也在此目录，直接复用做对比。

策略逻辑（自然语言）—— 红利ETF 定投（防御型主线）：
- 自评估窗口起，每月首个交易日触发一次定投信号（日历驱动，非价格信号），
  为严格防前视，实际成交价为触发后下一交易日开盘。
- 每次投入固定金额（默认 10,000 元），按 ETF 100 份整数倍买入并累加份额。
- 全程持有、不做止盈止损；样本末日按收盘一次性强制平仓，逐批次折算收益。

同窗口对照（用于隔离「资产选择」与「方法」）：
- 红利ETF 一次性买入持有（同窗口、同成本假设）：作为「资产本身」的基准。
- 半导体ETF 回调分批（上一轮结果，窗口对齐到 2019-07-10 ~ 2026-07-21）：成长型主线。

防前视核心：
- 定投信号在 bar i 以「日历」判定（无需看价格），挂单后于 bar i+1 开盘成交。
- ETF 交易：100 份整数倍，佣金双边 3bps，免印花税；A 股 T+1 自然满足。

交付：标准三件套（dividend_dca_* / dividend_bh_*）+ 对比仪表盘 index.html。

运行：python dividend_dca_backtest.py
依赖：同目录下的 export_results.py / render_dashboard.py / dashboard_locales.py /
      dashboard_template.html（由 quant-backtest-lab 技能复制而来）。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

# ---- 让脚本在 cwd 下找到复制过来的交付模块 ----
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from export_results import export_results  # noqa: E402
from render_dashboard import build_dashboard_data, render_dashboard  # noqa: E402

# ---------------------------------------------------------------------------
# 参数（用户未显式指定的，均在此集中说明）
# ---------------------------------------------------------------------------
SYMBOL = "510880.SH"
SYMBOL_NAME = "红利ETF"
WINDOW_START = "2019-07-10"   # 与半导体回测窗口对齐
WINDOW_END = "2026-07-21"
INITIAL_CASH = 1_000_000.0
MONTHLY_AMOUNT = 10_000.0     # 每月定投固定金额
BUY_COMMISSION = 0.0003       # 3 bps 买入佣金
SELL_COMMISSION = 0.0003      # 3 bps 卖出佣金
SELL_TAX = 0.0                # ETF 免印花税
LOT_SIZE = 100                # ETF 100 份/手
PREFIX_DCA = "dividend_dca"
PREFIX_BH = "dividend_bh"

DATA_FILE = HERE / "../../fixtures/510880_daily_qfq.csv"
SEMI_EQUITY = HERE / "../../fixtures/semiconductor_dipbuy_equity.csv"
SEMI_TRADES = HERE / "../../fixtures/semiconductor_dipbuy_trades.csv"
SEMI_SUMMARY = HERE / "../../fixtures/dividend_bh_summary.json"


def load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str)
    for col in ("open", "close", "high", "low", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "open", "high", "low"]).reset_index(drop=True)
    return df


def _first_window_index(df: pd.DataFrame) -> int:
    for i in range(len(df)):
        if str(df.iloc[i]["date"])[:10] >= WINDOW_START:
            return i
    return 0


def run_dca(df: pd.DataFrame):
    """红利ETF 定投：每月固定金额买入，全程持有，末日强制平仓（逐批次折算）。"""
    equity: list[dict] = []
    trade_history: list[dict] = []

    cash = INITIAL_CASH
    shares = 0
    lots: list[dict] = []        # 每批定投：{buy_date, buy_price, size, buy_idx}
    pending_buy = False
    prev_month = None

    n = len(df)
    for i in range(n):
        row = df.iloc[i]
        date = str(row["date"])[:10]
        close = float(row["close"])
        o = float(row["open"])
        in_window = date >= WINDOW_START

        # ---- 仅在评估窗口内产生交易副作用（防前视 / 防窗口外建仓）----
        if in_window:
            # 1) 执行上一根 bar 挂出的定投买单（下一交易日开盘成交）
            if pending_buy:
                price = o
                size = int(MONTHLY_AMOUNT / (price * (1 + BUY_COMMISSION)))
                size = (size // LOT_SIZE) * LOT_SIZE
                if size > 0:
                    cost = size * price * (1 + BUY_COMMISSION)
                    if cost <= cash:
                        cash -= cost
                        shares += size
                        lots.append({"buy_date": date, "buy_price": price,
                                     "size": size, "buy_idx": i})
                    pending_buy = False
                else:
                    pending_buy = False  # 金额不足以买 1 手，放弃本轮

            # 2) 日历信号：跨月即触发（下一交易日开盘执行）
            if prev_month is not None and date[:7] != prev_month:
                pending_buy = True
            prev_month = date[:7]

            # 3) 记录净值
            equity.append({"date": date, "value": round(cash + shares * close, 2)})

    # ---- 末日强制平仓：逐批次按末日收盘折算 ----
    if shares > 0 and lots:
        last = df.iloc[-1]
        end_date = str(last["date"])[:10]
        fprice = float(last["close"])
        total_proceeds = 0.0
        for lot in lots:
            if lot["buy_date"] >= end_date:   # T+1 守卫（本策略不会触发）
                continue
            proceeds = lot["size"] * fprice * (1 - SELL_COMMISSION - SELL_TAX)
            cost_basis = lot["size"] * lot["buy_price"] * (1 + BUY_COMMISSION)
            pnl = proceeds - cost_basis
            pnl_pct = ((fprice / lot["buy_price"] - 1) * 100.0
                       - (BUY_COMMISSION + SELL_COMMISSION + SELL_TAX) * 100.0)
            trade_history.append({
                "entry_date": lot["buy_date"],
                "exit_date": end_date,
                "side": "long",
                "size": lot["size"],
                "entry_price": round(lot["buy_price"], 4),
                "exit_price": round(fprice, 4),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "holding_bars": n - 1 - lot["buy_idx"],
                "symbol": SYMBOL,
                "symbol_name": SYMBOL_NAME,
                "display_symbol": SYMBOL_NAME,
                "label": f"定投 {lot['buy_date'][:7]}",
            })
            total_proceeds += proceeds
        cash += total_proceeds
        shares = 0
        if equity:
            equity[-1]["value"] = round(cash, 2)

    return equity, trade_history


def run_buyhold(df: pd.DataFrame):
    """红利ETF 一次性买入持有（同窗口、同成本假设）：资产本身的基准。"""
    equity: list[dict] = []
    trade_history: list[dict] = []

    start_i = _first_window_index(df)
    row0 = df.iloc[start_i]
    date0 = str(row0["date"])[:10]
    price0 = float(row0["open"])
    cash = INITIAL_CASH
    size = int(cash / (price0 * (1 + BUY_COMMISSION)))
    size = (size // LOT_SIZE) * LOT_SIZE
    shares = 0
    entry_price = 0.0
    entry_idx = start_i
    if size > 0:
        cash -= size * price0 * (1 + BUY_COMMISSION)
        shares = size
        entry_price = price0

    n = len(df)
    for i in range(start_i, n):
        row = df.iloc[i]
        date = str(row["date"])[:10]
        close = float(row["close"])
        equity.append({"date": date, "value": round(cash + shares * close, 2)})

    if shares > 0:
        last = df.iloc[-1]
        end_date = str(last["date"])[:10]
        fprice = float(last["close"])
        proceeds = shares * fprice * (1 - SELL_COMMISSION - SELL_TAX)
        pnl = proceeds - shares * entry_price * (1 + BUY_COMMISSION)
        pnl_pct = ((fprice / entry_price - 1) * 100.0
                   - (BUY_COMMISSION + SELL_COMMISSION + SELL_TAX) * 100.0)
        trade_history.append({
            "entry_date": date0,
            "exit_date": end_date,
            "side": "long",
            "size": shares,
            "entry_price": round(entry_price, 4),
            "exit_price": round(fprice, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "holding_bars": n - 1 - entry_idx,
            "symbol": SYMBOL,
            "symbol_name": SYMBOL_NAME,
            "display_symbol": SYMBOL_NAME,
            "label": "买入持有(基准)",
        })
        cash += proceeds
        shares = 0
        if equity:
            equity[-1]["value"] = round(cash, 2)

    return equity, trade_history


# ---------------------------------------------------------------------------
# 对比仪表盘构建
# ---------------------------------------------------------------------------
def _read_equity(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append({"date": row["date"], "value": float(row["value"])})
    return out


def _read_summary(path: Path) -> dict:
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _rebase(points: list[dict]) -> list[dict]:
    if not points:
        return []
    base = points[0]["value"]
    if base == 0:
        return points
    return [{"date": p["date"], "value": p["value"] / base * 100.0} for p in points]


def _kpi(label, value, raw=None):
    item = {"label": label, "value": value}
    if raw is not None:
        item["raw"] = raw
    return item


def _fmt_pct(x, d=2):
    return f"{x:.{d}f}%" if x is not None else "--"


def _fmt_pct_neg(x, d=2):
    """最大回撤以负数展示。"""
    return f"{x:.{d}f}%" if x is not None else "--"


def _build_comparison(dca_eq, bh_eq, semi_eq, dca_sum, bh_sum, semi_sum):
    # 折线对比（均归一化到 100）
    dca_re = _rebase(dca_eq)
    bh_re = _rebase(bh_eq)
    semi_re = _rebase(semi_eq)

    line_chart = {
        "type": "line_chart",
        "tab": "compare",
        "title": "净值增长对比（期初归一化 = 100）",
        "subtitle": "防御(红利) vs 成长(半导体) · 同一窗口 2019-07-10 ~ 2026-07-21",
        "series": [
            {"name": "红利ETF定投(DCA)", "points": dca_re},
            {"name": "红利ETF买入持有", "points": bh_re},
            {"name": "半导体回调分批", "points": semi_re},
        ],
    }

    cols = ["指标", "红利ETF定投(DCA)", "红利ETF买入持有", "半导体回调分批"]
    rows = [
        {"metric": "总收益率", "values": [
            {"main": _fmt_pct(dca_sum["summary"]["total_return_pct"]), "raw": dca_sum["summary"]["total_return_pct"]},
            {"main": _fmt_pct(bh_sum["summary"]["total_return_pct"]), "raw": bh_sum["summary"]["total_return_pct"]},
            {"main": _fmt_pct(semi_sum["summary"]["total_return_pct"]), "raw": semi_sum["summary"]["total_return_pct"]},
        ]},
        {"metric": "年化收益率", "values": [
            {"main": _fmt_pct(dca_sum["summary"]["annual_return_pct"]), "raw": dca_sum["summary"]["annual_return_pct"]},
            {"main": _fmt_pct(bh_sum["summary"]["annual_return_pct"]), "raw": bh_sum["summary"]["annual_return_pct"]},
            {"main": _fmt_pct(semi_sum["summary"]["annual_return_pct"]), "raw": semi_sum["summary"]["annual_return_pct"]},
        ]},
        {"metric": "最大回撤", "values": [
            {"main": _fmt_pct_neg(-abs(dca_sum["summary"]["max_drawdown_pct"] or 0)), "raw": -abs(dca_sum["summary"]["max_drawdown_pct"] or 0)},
            {"main": _fmt_pct_neg(-abs(bh_sum["summary"]["max_drawdown_pct"] or 0)), "raw": -abs(bh_sum["summary"]["max_drawdown_pct"] or 0)},
            {"main": _fmt_pct_neg(-abs(semi_sum["summary"]["max_drawdown_pct"] or 0)), "raw": -abs(semi_sum["summary"]["max_drawdown_pct"] or 0)},
        ]},
        {"metric": "夏普比率", "values": [
            {"main": f"{dca_sum['summary']['sharpe']:.3f}" if dca_sum['summary']['sharpe'] is not None else "--", "raw": dca_sum['summary']['sharpe']},
            {"main": f"{bh_sum['summary']['sharpe']:.3f}" if bh_sum['summary']['sharpe'] is not None else "--", "raw": bh_sum['summary']['sharpe']},
            {"main": f"{semi_sum['summary']['sharpe']:.3f}" if semi_sum['summary']['sharpe'] is not None else "--", "raw": semi_sum['summary']['sharpe']},
        ]},
        {"metric": "期末净值倍数", "values": [
            {"main": f"{1 + dca_sum['summary']['total_return_pct']/100:.2f}x", "raw": 1 + dca_sum['summary']['total_return_pct']/100},
            {"main": f"{1 + bh_sum['summary']['total_return_pct']/100:.2f}x", "raw": 1 + bh_sum['summary']['total_return_pct']/100},
            {"main": f"{1 + semi_sum['summary']['total_return_pct']/100:.2f}x", "raw": 1 + semi_sum['summary']['total_return_pct']/100},
        ]},
        {"metric": "交易/定投批次", "values": [
            {"main": str(dca_sum["summary"]["total_trades"])},
            {"main": str(bh_sum["summary"]["total_trades"])},
            {"main": str(semi_sum["summary"]["total_trades"])},
        ]},
        {"metric": "胜率", "values": [
            {"main": _fmt_pct(dca_sum["summary"]["win_rate_pct"]), "raw": dca_sum["summary"]["win_rate_pct"]},
            {"main": "— (1笔)", "raw": None},
            {"main": _fmt_pct(semi_sum["summary"]["win_rate_pct"]), "raw": semi_sum["summary"]["win_rate_pct"]},
        ]},
    ]
    metric_table = {
        "type": "metric_table",
        "tab": "compare",
        "title": "风险收益结构横向对比",
        "subtitle": "同一窗口、同一初始资金、同一成本假设下对照",
        "columns": cols,
        "rows": rows,
    }
    return line_chart, metric_table


def main():
    df = load_data(DATA_FILE)

    # ---- 红利ETF 定投 ----
    dca_equity, dca_trades = run_dca(df)
    export_results(
        equity_curve=dca_equity, trade_history=dca_trades, prefix=PREFIX_DCA,
        initial_cash=INITIAL_CASH, start=WINDOW_START, end=WINDOW_END,
        market="china_a", is_flat_at_end=True,
        strategy_name="红利ETF定投(DCA)", symbol=SYMBOL,
    )
    print(f"[ok] {PREFIX_DCA} 三件套已写入")

    # ---- 红利ETF 买入持有（基准）----
    bh_equity, bh_trades = run_buyhold(df)
    export_results(
        equity_curve=bh_equity, trade_history=bh_trades, prefix=PREFIX_BH,
        initial_cash=INITIAL_CASH, start=WINDOW_START, end=WINDOW_END,
        market="china_a", is_flat_at_end=True,
        strategy_name="红利ETF买入持有", symbol=SYMBOL,
    )
    print(f"[ok] {PREFIX_BH} 三件套已写入")

    # ---- 读取三套结果 ----
    dca_eq = _read_equity(HERE / f"{PREFIX_DCA}_equity.csv")
    bh_eq = _read_equity(HERE / f"{PREFIX_BH}_equity.csv")
    semi_eq = _read_equity(SEMI_EQUITY)
    dca_sum = _read_summary(HERE / f"{PREFIX_DCA}_summary.json")
    bh_sum = _read_summary(HERE / f"{PREFIX_BH}_summary.json")
    semi_sum = _read_summary(SEMI_SUMMARY)
    dca_trades_loaded = list(csv.DictReader(open(HERE / f"{PREFIX_DCA}_trades.csv", encoding="utf-8")))
    semi_trades_loaded = list(csv.DictReader(open(SEMI_TRADES, encoding="utf-8")))

    # ---- 构建对比仪表盘 ----
    line_chart, metric_table = _build_comparison(
        dca_eq, bh_eq, semi_eq, dca_sum, bh_sum, semi_sum)

    # 用 build_dashboard_data 生成两个单策略的 overview/trades 模块（已含正确点位与标记）
    rep_dca = build_dashboard_data(
        equity_csv=HERE / f"{PREFIX_DCA}_equity.csv",
        trades_csv=HERE / f"{PREFIX_DCA}_trades.csv",
        summary_json=HERE / f"{PREFIX_DCA}_summary.json",
        language="zh", market="china_a",
    )
    rep_semi = build_dashboard_data(
        equity_csv=SEMI_EQUITY, trades_csv=SEMI_TRADES, summary_json=SEMI_SUMMARY,
        language="zh", market="china_a",
    )

    dca_ov = next(m for m in rep_dca["modules"] if m["type"] == "overview_chart")
    semi_ov = next(m for m in rep_semi["modules"] if m["type"] == "overview_chart")
    dca_tt = next(m for m in rep_dca["modules"] if m["type"] == "trades_table")
    semi_tt = next(m for m in rep_semi["modules"] if m["type"] == "trades_table")

    # 红利定投页：仅保留「买入」标记（定投节奏），末日补一个「卖出」标记；叠加买入持有基准
    dca_markers = [m for m in dca_ov.get("markers", []) if m.get("action") == "buy"]
    if dca_trades_loaded:
        total_size = sum(int(float(t["size"])) for t in dca_trades_loaded)
        end_price = float(dca_trades_loaded[0]["exit_price"])
        dca_markers.append({
            "date": dca_trades_loaded[0]["exit_date"], "action": "sell",
            "price": end_price, "size": total_size, "symbol": SYMBOL_NAME,
            "label": "样本末日强制平仓",
        })
    dca_ov["markers"] = dca_markers
    dca_ov["tab"] = "dividend"
    dca_ov["overlay_series"] = [
        {"name": "红利ETF买入持有(基准)", "stroke": "#ff9800", "points": bh_eq}
    ]
    dca_tt["tab"] = "dividend"

    semi_ov["tab"] = "semi"
    semi_tt["tab"] = "semi"

    text_modules = [
        {"type": "text", "tab": "compare", "title": "结论速览",
         "text": (
            "在同一窗口（2019-07-10 ~ 2026-07-21）、同一初始资金 100 万、同一成本假设下：\n"
            "· 红利ETF 定投(DCA) 总收益约 +%.1f%%，年化约 %.1f%%，最大回撤约 -%.1f%%，夏普约 %.2f。\n"
            "· 红利ETF 一次性买入持有 总收益约 +%.1f%%，回撤约 -%.1f%%。\n"
            "· 半导体回调分批 总收益约 +%.1f%%（远高于红利），但最大回撤约 -%.1f%%，波动显著更大。\n"
            "一句话：红利定投是「低波动、低回撤、收益温和」的压舱石；半导体是「高弹性、高回撤」的"
            "成长进攻。两者风险收益结构差异明显，取决于风险偏好而非单纯收益高低。"
            % (dca_sum["summary"]["total_return_pct"], dca_sum["summary"]["annual_return_pct"],
               dca_sum["summary"]["max_drawdown_pct"], dca_sum["summary"]["sharpe"],
               bh_sum["summary"]["total_return_pct"], bh_sum["summary"]["max_drawdown_pct"],
               semi_sum["summary"]["total_return_pct"], semi_sum["summary"]["max_drawdown_pct"]))},
        {"type": "text", "tab": "compare", "title": "关键假设与方法",
         "text": (
            "· 数据：westock-data 拉取的 510880 / 512480 日线前复权(qfq)。\n"
            "· 窗口对齐：三者均取 2019-07-10 ~ 2026-07-21，保证曲线可比。\n"
            "· 红利定投：每月固定 1 万元，下一交易日开盘成交，100 份整数倍，全程持有。\n"
            "· 红利买入持有：窗口首交易日开盘一次性满仓，持有至末日。\n"
            "· 成本：双边佣金 3bps，ETF 免印花税；均做末日强制平仓。\n"
            "· 半导体（上一轮）：空仓时较 20 日高点回落≥10% 买入，+20%%止盈/自峰值-12%%移动止损/60日时间止损。"
         )},
        {"type": "text", "tab": "compare", "title": "局限与已知偏差",
         "text": (
            "· 现金拖累：定投前期大量资金以现金形式闲置，会系统性压低其回撤与波动，"
            "使「定投 vs 买入持有」的波动差异部分来自仓位而非资产本身。\n"
            "· 日线无法还原盘中委托顺序；未含滑点与冲击成本。\n"
            "· 参数（月定投额、10%%/20%%/12%%/60日）为合理默认，未做样本外优化。\n"
            "· 买入持有仅 1 笔，其「胜率」无参考意义，已在表中标注。"
         )},
        {"type": "text", "tab": "compare", "title": "优化方向",
         "text": (
            "· 红利定投可叠加「低估多投、高估少投」的估值择时，提升定投效率。\n"
            "· 用「定投 + 半导体战术仓」做核心-卫星组合，平衡压舱石与进攻性。\n"
            "· 把回测模块接入 PyQt6 桌面程序作为「策略回测」新页，实现交互式参数调优。"
         )},
    ]

    report = rep_dca
    report["meta"]["strategy_name"] = "防御vs成长：红利定投 与 半导体回调 横向对比"
    report["modules"] = [
        line_chart, metric_table, *text_modules,
        dca_ov, dca_tt, semi_ov, semi_tt,
    ]
    report["ui"]["tabs"] = [
        {"id": "compare", "label": "对比"},
        {"id": "dividend", "label": "红利定投"},
        {"id": "semi", "label": "半导体回调"},
    ]
    report["ui"]["active_tab"] = "compare"

    out_html = HERE / "index.html"
    render_dashboard(report, output_path=out_html)
    print(f"[ok] 对比仪表盘已渲染: {out_html}")

    # ---- 可选 PNG：净值增长对比（离线查看）----
    try:
        dca_re = _rebase(dca_eq)
        bh_re = _rebase(bh_eq)
        semi_re = _rebase(semi_eq)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure(figsize=(9, 5))
        plt.plot([p["date"] for p in dca_re], [p["value"] for p in dca_re], label="Dividend ETF DCA")
        plt.plot([p["date"] for p in bh_re], [p["value"] for p in bh_re], label="Dividend ETF Buy&Hold")
        plt.plot([p["date"] for p in semi_re], [p["value"] for p in semi_re], label="Semiconductor Dip-Buy")
        plt.axhline(100, color="#999", lw=0.8, ls="--")
        plt.title("Growth of 100 (same window 2019-07-10 ~ 2026-07-21)")
        plt.ylabel("归一化净值")
        plt.legend()
        plt.xticks(rotation=0)
        plt.tight_layout()
        png = HERE / "dividend_vs_semi_growth.png"
        plt.savefig(png, dpi=120)
        plt.close()
        print(f"[ok] 对比图已保存: {png}")
    except Exception as e:  # noqa
        print(f"[warn] PNG 生成跳过: {e}")


if __name__ == "__main__":
    main()
