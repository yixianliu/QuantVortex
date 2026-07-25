# -*- coding: utf-8 -*-
"""
半导体ETF(512480) 回调分批买入 + 止盈/移动止损 策略回测

数据来源：westock-data（腾讯自选股接口）拉取的 512480 日线前复权(qfq)数据，
        已落盘为 512480_daily_qfq.csv（本脚本仅读取，不硬编码价格）。

策略逻辑（自然语言）：
- 空仓时，若收盘价较「前 20 个交易日收盘价最高点」回落 >= 10%，视为回调，
  于次日开盘买入一整批仓位（简化版「回调分批」：每轮回调只建一次仓，
  分批建仓作为后续优化项，见仪表盘说明）。
- 持仓期间退出条件（任一触发，于次日开盘执行）：
    * 止盈：盘中最高价 >= 入场价 * 1.20（+20%）
    * 移动止损：盘中最低价 <= 持仓期以来收盘价峰值 * 0.88（自峰值回落 -12%）
    * 时间止损：持仓交易日数 >= 60
  - 同一根 K 线同时触及止盈与止损时，优先按止损处理。
- A 股 T+1：买入最早次日才可卖；本脚本买入在 bar i+1 开盘、退出最早在
  bar i+2，自然满足。
- ETF 交易：100 份整数倍，佣金双边 3bps，免印花税。
- 样本末日若仍持仓，按末日收盘强制平仓并计入交易。

防前视核心：
- 信号在 bar i 用「截至 i-1 的历史」生成 -> pending 挂单；
- 实际成交价用 bar i+1 的开盘价。
- 20 日高点用 df['close'].rolling(20).max().shift(1)（严格不含当前 bar）。

基准：同标的「买入持有」（用前复权收盘价折算净值），用于对照。

运行：python semiconductor_dipbuy_backtest.py
依赖：同目录下的 export_results.py / render_dashboard.py / dashboard_locales.py /
      dashboard_template.html（由 quant-backtest-lab 技能复制而来）。
"""
from __future__ import annotations

import csv
import os
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
SYMBOL = "512480.SH"
SYMBOL_NAME = "半导体ETF"
INITIAL_CASH = 1_000_000.0
BUY_COMMISSION = 0.0003      # 3 bps 买入佣金
SELL_COMMISSION = 0.0003     # 3 bps 卖出佣金
SELL_TAX = 0.0               # ETF 免印花税
LOT_SIZE = 100               # ETF 100 份/手
WARMUP_BARS = 20             # 20 日高点所需前视窗口
DIP_PCT = 0.10               # 较 20 日高点回落 >=10% 触发回调买入
TAKE_PROFIT_PCT = 0.20       # +20% 止盈
TRAILING_STOP_PCT = 0.12     # 自持仓峰值回落 -12% 移动止损
MAX_HOLD_BARS = 60           # 持仓超 60 交易日时间止损
PREFIX = "semiconductor_dipbuy"

DATA_FILE = HERE / "512480_daily_qfq.csv"


def load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str)
    for col in ("open", "close", "high", "low", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "open", "high", "low"]).reset_index(drop=True)
    # 不含当前 bar 的 20 日收盘最高点（严格前视）
    df["high20"] = df["close"].rolling(WARMUP_BARS).max().shift(1)
    return df


def run_backtest(df: pd.DataFrame):
    equity_curve: list[dict] = []
    trade_history: list[dict] = []

    cash = INITIAL_CASH
    position = 0          # 持有份数
    entry_price = 0.0     # 入场均价（含费成本基准）
    entry_bar = -1        # 入场 bar 索引
    peak_close = 0.0      # 持仓期收盘价峰值
    pending_buy = False
    pending_sell = False
    sell_reason = ""

    n = len(df)
    eval_start_idx = WARMUP_BARS  # 指标就绪后的首个可交易 bar

    for i in range(n):
        row = df.iloc[i]
        date = str(row["date"])[:10]
        close = float(row["close"])
        o = float(row["open"])
        h = float(row["high"])
        lo = float(row["low"])

        # ---- 1) 先执行上一根 bar 的挂单（次日开盘成交）----
        # 末根 K 线不执行买入：避免在样本最后一天买入又于强制平仓时同日卖出，
        # 那将违反 A 股 T+1（当日不可买卖同一标的）。
        if pending_buy and position == 0 and i < n - 1:
            price = o
            size = int(cash / (price * (1 + BUY_COMMISSION)))
            size = (size // LOT_SIZE) * LOT_SIZE
            if size > 0:
                cost = size * price * (1 + BUY_COMMISSION)
                cash -= cost
                position = size
                entry_price = price
                entry_bar = i
                peak_close = close  # 以成交日收盘初始化峰值
                pending_buy = False
            else:
                pending_buy = False  # 资金不足，放弃本轮

        if pending_sell and position > 0:
            # T+1：必须晚于入场 bar 才能卖
            if i > entry_bar:
                price = o
                proceeds = position * price * (1 - SELL_COMMISSION - SELL_TAX)
                pnl = proceeds - position * entry_price * (1 + BUY_COMMISSION)
                pnl_pct = (price / entry_price - 1) * 100.0 - (BUY_COMMISSION + SELL_COMMISSION + SELL_TAX) * 100.0
                trade_history.append({
                    "entry_date": str(df.iloc[entry_bar]["date"])[:10],
                    "exit_date": date,
                    "side": "long",
                    "size": position,
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(price, 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "holding_bars": i - entry_bar,
                    "symbol": SYMBOL,
                    "symbol_name": SYMBOL_NAME,
                    "display_symbol": SYMBOL_NAME,
                    "label": sell_reason,
                })
                cash += proceeds
                position = 0
                entry_price = 0.0
                peak_close = 0.0
                pending_sell = False
                sell_reason = ""

        # ---- 2) 生成本根 bar 的信号（供下一根执行）----
        if i >= eval_start_idx:
            high20 = row["high20"]
            # 更新持仓期峰值（必须在止损检查之后；本处在信号生成段，
            # 峰值更新放到下面专用位置，避免同日误抬止损线）
            if position > 0:
                # 退出信号（用当日 high/low 判触发，次日开盘执行）
                # 优先级：移动止损 > 时间止损 > 止盈
                # 注意：止损检查须用「截至上一根」的峰值，故 peak_close 的更新
                # 放在检查之后，避免同日新高抬高止损线导致漏触发。
                stop_line = peak_close * (1 - TRAILING_STOP_PCT)
                if lo <= stop_line:
                    pending_sell = True
                    sell_reason = "移动止损(-%.0f%%)" % (TRAILING_STOP_PCT * 100)
                elif (i - entry_bar) >= MAX_HOLD_BARS:
                    pending_sell = True
                    sell_reason = "时间止损(%d日)" % MAX_HOLD_BARS
                elif h >= entry_price * (1 + TAKE_PROFIT_PCT):
                    pending_sell = True
                    sell_reason = "止盈(+%.0f%%)" % (TAKE_PROFIT_PCT * 100)
                # 止损/止盈检查之后再更新持仓期收盘价峰值
                if close > peak_close:
                    peak_close = close

                # 若已挂卖，不再考虑买入
            else:
                # 空仓：回调买入信号
                if pd.notna(high20) and high20 > 0 and close <= high20 * (1 - DIP_PCT):
                    pending_buy = True

        # ---- 3) 记录净值（仅评估窗口内）----
        if i >= eval_start_idx:
            value = cash + position * close
            equity_curve.append({"date": date, "value": round(value, 2)})

    # ---- 末日强制平仓 ----
    if position > 0:
        last = df.iloc[-1]
        date = str(last["date"])[:10]
        price = float(last["close"])
        proceeds = position * price * (1 - SELL_COMMISSION - SELL_TAX)
        pnl = proceeds - position * entry_price * (1 + BUY_COMMISSION)
        pnl_pct = (price / entry_price - 1) * 100.0 - (BUY_COMMISSION + SELL_COMMISSION + SELL_TAX) * 100.0
        trade_history.append({
            "entry_date": str(df.iloc[entry_bar]["date"])[:10],
            "exit_date": date,
            "side": "long",
            "size": position,
            "entry_price": round(entry_price, 4),
            "exit_price": round(price, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "holding_bars": n - 1 - entry_bar,
            "symbol": SYMBOL,
            "symbol_name": SYMBOL_NAME,
            "display_symbol": SYMBOL_NAME,
            "label": "样本末日强制平仓",
        })
        cash += proceeds
        position = 0
        # 用末日市值刷新最后一点净值
        if equity_curve:
            equity_curve[-1]["value"] = round(cash, 2)

    return equity_curve, trade_history


def build_benchmark(df: pd.DataFrame, start_idx: int) -> list[dict]:
    """同标的买入持有基准（前复权净值）。"""
    base = float(df.iloc[start_idx]["close"])
    bench = []
    for i in range(start_idx, len(df)):
        c = float(df.iloc[i]["close"])
        bench.append({
            "date": str(df.iloc[i]["date"])[:10],
            "value": round(INITIAL_CASH * c / base, 2),
        })
    return bench


def main():
    df = load_data(DATA_FILE)
    equity_curve, trade_history = run_backtest(df)

    start_idx = WARMUP_BARS
    start_date = str(df.iloc[start_idx]["date"])[:10]
    end_date = str(df.iloc[-1]["date"])[:10]

    export_results(
        equity_curve=equity_curve,
        trade_history=trade_history,
        prefix=PREFIX,
        initial_cash=INITIAL_CASH,
        start=start_date,
        end=end_date,
        market="china_a",
        is_flat_at_end=True,
        strategy_name="半导体ETF回调分批+止盈止损",
        symbol=SYMBOL,
    )
    print(f"[ok] 标准三件套已写入 {HERE} (prefix={PREFIX})")

    # ---- 基准曲线 + 渲染仪表盘 ----
    benchmark = build_benchmark(df, start_idx)
    # 对齐到评估窗口的 overlay 点
    bench_map = {p["date"]: p["value"] for p in benchmark}
    overlay_points = [
        {"date": p["date"], "value": bench_map.get(p["date"])}
        for p in equity_curve if p["date"] in bench_map
    ]

    report = build_dashboard_data(
        equity_csv=HERE / f"{PREFIX}_equity.csv",
        trades_csv=HERE / f"{PREFIX}_trades.csv",
        summary_json=HERE / f"{PREFIX}_summary.json",
        language="zh",
        market="china_a",
        extra_modules=[
            {
                "type": "text", "tab": "overview", "title": "结论速览",
                "text": (
                    "本回测将上一轮板块筛选中「科技成长（半导体）属超跌反弹、适合回调分批、严格止损」的"
                    "操作建议落成可运行策略：空仓时价格较 20 日高点回落 ≥10% 买入，+20% 止盈 / 自峰值"
                    "回落 -12% 移动止损 / 60 日时间止损。\n"
                    "结论以 summary.json 与下方指标表为准；若策略收益显著落后于「买入持有」基准，"
                    "说明在半导体的长期上行趋势中，频繁离场会带来踏空成本——这是回调策略在牛市中的典型短板。"
                ),
            },
            {
                "type": "text", "tab": "overview", "title": "关键假设与方法",
                "text": (
                    "· 数据：westock-data 拉取的 512480 日线前复权(qfq)，2019-06-12 至 2026-07-21，共 1724 根。\n"
                    "· 执行：信号在 bar i 用历史数据生成，次日开盘成交（防前视）；T+1 自然满足。\n"
                    "· 仓位：每轮回调一次性建满仓（简化的「分批」实现；真正的分批建仓为后续优化）。\n"
                    "· 成本：双边佣金 3bps，ETF 免印花税；100 份整数倍。\n"
                    "· 末日若持仓，按收盘强制平仓并计入交易。"
                ),
            },
            {
                "type": "text", "tab": "overview", "title": "局限与已知偏差",
                "text": (
                    "· 日线无法还原盘中委托顺序：止损/止盈以当日 high/low 近似触发，未建模开盘跳空后的精确价位。\n"
                    "· 未含滑点与冲击成本；真实大单滑点会侵蚀收益。\n"
                    "· 参数（10%/20%/12%/60 日）为合理默认值，未做样本外优化，存在一定过拟合风险。\n"
                    "· 前复权绝对价位偏低属正常（相对最新价调整），不影响收益率比率。"
                ),
            },
            {
                "type": "text", "tab": "overview", "title": "优化方向",
                "text": (
                    "· 改为分 2~3 批在更深处加仓，降低单次择时错误。\n"
                    "· 加入趋势/波动率过滤（如仅在 20 日均线向上时参与），规避下跌通道中的连续止损。\n"
                    "· 对照「红利ETF 定投」防御主线，做风险收益结构的横向比较。"
                ),
            },
        ],
    )
    # 把基准曲线叠加到主图
    for mod in report.get("modules", []):
        if mod.get("type") == "overview_chart":
            mod["overlay_series"] = [
                {"name": "买入持有(基准)", "stroke": "#9e9e9e", "points": overlay_points}
            ]

    out_html = HERE / "index.html"
    render_dashboard(report, output_path=out_html)
    print(f"[ok] 仪表盘已渲染: {out_html}")


if __name__ == "__main__":
    main()
