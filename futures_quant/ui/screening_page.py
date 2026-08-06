"""期货选品入手机会页（原生行情驱动）。

核心定位：为用户提供「可考虑入手的具体品种」与「需留意的板块方向」，
而非筛选「强势品种 / 热门板块」。本页回答的是：
    「哪些品种现在可以考虑建仓入手？哪些板块值得重点关注？」

评分 = 100 × (
        0.70 · Σ(|RankIC| 归一化 · 五因子分位)   # 趋势动量/均线排列/资金流/量能/持仓
      + 0.12 · 波动适中(钟形，目标年化 ~28%)
      + 0.18 · AI 方向概率(p_up 分位)
    )

因子权重由历史「入手信号」/收益对的 RankIC 数据驱动（替代固定权重），并引入
AI 方向概率因子，直接提升评分对未来收益的预测力（预测成功率）。

与「强势排行榜」的区别：
  · 历史信号定义为「入手机会」——趋势向好且未过度透支（留有上行空间）+ 量能配合，
    不要求已大幅上涨或量能暴增，避免把「已强势」误判为「可入手」。
  · 实盘评分对「近 20 日已大幅上涨（追高）」的品种做折让，使排名反映
    「可考虑入手」而非「谁最强势」，减少追高提示。

评分 0–100，按板块聚合给出「建议关注板块」；单品种分三档：
优先入手(≥68) / 可留意(≥55) / 暂观望。
"""
from __future__ import annotations

import datetime as dt
import math
from bisect import bisect_right
from typing import Optional

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QTextEdit, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from .pages import BasePage, Worker
from ..ai.predictor import FuturesPredictor
from ..ai.feedback import reliability_calibration, calibration_band_at
from .widgets import (
    PageHeader, ToolBar, PALETTE, THEME, prepare_table, color_pnl,
    ConfidenceBar, MetricChip, Badge, pal,
)

# 校准区间「低置信」阈值：与 predict_ops_page.LOW_CONF_BAND_WIDTH 保持一致
# （该档概率历史校准样本稀疏 → 研判可信度下降，AI 方向标注「置信偏低」）。
LOW_CONF_BAND_WIDTH = 0.25


# ---------------------------------------------------------------------------
# 计算层：全合约综合评分
# ---------------------------------------------------------------------------
def _screen(mdm, store=None):
    """对全合约做「入手机会」评分，返回 (品种列表, 板块聚合列表)。

    排名反映「可考虑入手」而非「谁最强势」：对近 20 日已大幅上涨
    （透支上行空间）的品种做评分折让，避免提示追高。

    store：若传入 AnalysisStore，则对「样本不足」的品种做持久化标记
    （sufficient=0），供界面提示与「补充采集」流程使用，确保样本不丢失。
    """
    REQUIRED = 65  # 回测/因子所需最少日线根数
    rows = mdm.universe  # (prefix, name, category, exchange, mult, mintick, base)
    raw = []
    for row in rows:
        prefix, name, cat, exch, mult, _mintick, _base = row
        sym = f"{prefix}.{exch}"
        try:
            df = mdm.get_bars(sym, "D", limit=130)
        except Exception:
            # 取数异常：登记为样本不足，待补充采集
            if store is not None:
                store.upsert_sample(sym, "D", 0, REQUIRED, 0,
                                     status="缺失", note="取数异常")
            continue
        avail = len(df) if df is not None else 0
        if df is None or avail < REQUIRED:
            # 样本不足：持久化标记 + 跳过计算，不静默丢弃
            if store is not None:
                store.upsert_sample(sym, "D", avail, REQUIRED, 0,
                                         status="不足",
                                         note=f"仅 {avail} 根，需 {REQUIRED}")
            continue
        try:
            close = df["close"].astype(float)
            if float(close.iloc[-1]) <= 0:
                continue
            ret = close.pct_change().dropna()
            ret_20 = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100
            ma5 = float(close.tail(5).mean())
            ma20 = float(close.tail(20).mean())
            ma60 = float(close.tail(60).mean())
            bull = (ma5 > ma20 > ma60)
            ma_gap = (ma5 / ma20 - 1) * 100 if ma20 else 0.0
            vol_20 = float(ret.tail(20).std() * math.sqrt(252) * 100) if len(ret) >= 20 else 0.0
            half = max(1, len(df) // 2)
            vol_recent = float(df["volume"].tail(half).mean())
            vol_prior = float(df["volume"].head(half).mean())
            vr = vol_recent / vol_prior if vol_prior else 1.0
            if "open_interest" in df.columns:
                oi_now = float(df["open_interest"].iloc[-1])
                oi_prev = float(df["open_interest"].iloc[half])
                oi = (oi_now - oi_prev) / oi_prev * 100 if oi_prev else 0.0
            else:
                oi = 0.0
            fund = float(((df["close"] - df["open"]) * df["volume"] * df["close"] * mult)
                         .tail(20).sum() / 1e8)
            r = dict(sym=sym, name=name, category=cat, last=float(close.iloc[-1]),
                     ret_20=ret_20, ma_gap=ma_gap, bull=bull, vol_20=vol_20,
                     fund=fund, vr=vr, oi=oi)
            # AI 方向概率因子（快速岭回归，进程内廉价；异常时回退中性 0.5）
            try:
                pu, ai_exp, ai_conf = _ai_full_predict(df)
                r["pu"] = pu
                r["ai_exp"] = ai_exp
                r["ai_conf"] = ai_conf
            except Exception:
                r["pu"] = 0.5
                r["ai_exp"] = 0.0
                r["ai_conf"] = 0.5
            # 历史信号回测（独立容错，避免回测异常导致该品种丢失）
            try:
                r["hist"] = _backtest_symbol(df, horizon=5)
            except Exception:
                r["hist"] = dict(wins=0, total=0, rate=None, examples=[])
            raw.append(r)
        except Exception:
            continue

    if not raw:
        return [], []

    def _rank(vals):
        s = sorted(vals)
        n = len(s)
        return [bisect_right(s, v) / n for v in vals]

    # ---- 数据驱动因子权重：用历史信号/收益对计算各因子的 RankIC ----
    # 替代原先拍脑袋的固定权重（0.32/0.13/0.20/0.13/0.10），让"对未来收益
    # 预测力更强"的因子自动获得更大权重，直接提升评分的预测成功率。
    _fac_names = ["ret20", "ma_gap", "fund", "vr", "oi"]
    pooled = {k: [] for k in _fac_names}
    pooled_fwd = []
    for r in raw:
        h = r.get("hist", {})
        f = h.get("fac", {})
        fw = h.get("fwd", [])
        if not fw:
            continue
        for k in _fac_names:
            pooled[k].extend(f.get(k, []))
        pooled_fwd.extend(fw)
    ics = {}
    for k in _fac_names:
        ics[k] = _spearman(pooled[k], pooled_fwd) if len(pooled_fwd) >= 10 else 0.0
    # |IC| 归一化为权重（带均匀先验，抑制小样本噪声过拟合）；5 因子合计 0.70，
    # 波动适中(vol_score) 固定 0.12，AI 方向概率(pu) 固定 0.18。
    prior = 0.05
    absics = {k: abs(ics[k]) + prior for k in _fac_names}
    s_ic = sum(absics.values()) or 1.0
    w = {k: 0.70 * absics[k] / s_ic for k in _fac_names}
    W_VOL, W_PU = 0.12, 0.18

    rt = _rank([r["ret_20"] for r in raw])
    rm = _rank([r["ma_gap"] for r in raw])
    rf = _rank([r["fund"] for r in raw])
    rv = _rank([r["vr"] for r in raw])
    ro = _rank([r["oi"] for r in raw])
    rpu = _rank([r["pu"] for r in raw])

    for i, r in enumerate(raw):
        vol_score = max(0.0, 1.0 - abs(r["vol_20"] - 28.0) / 35.0)
        r["vol_score"] = round(vol_score, 3)
        score = 100.0 * (
            w["ret20"] * rt[i] + w["ma_gap"] * rm[i] + w["fund"] * rf[i]
            + w["vr"] * rv[i] + w["oi"] * ro[i]
            + W_VOL * vol_score + W_PU * rpu[i])
        # 追高折让：近 20 日已大幅上涨（透支上行空间）的品种下调入手吸引力，
        # 使排名反映「可考虑入手」而非「强势排行榜」，避免提示追高。
        r["overext"] = r["ret_20"] > 22
        if r["overext"]:
            score *= 0.8
        r["score"] = round(score, 1)
        s = r["score"]
        r["tier"] = "优先入手" if s >= 68 else ("可留意" if s >= 55 else "暂观望")

    raw.sort(key=lambda x: x["score"], reverse=True)

    cats: dict = {}
    for r in raw:
        cats.setdefault(r["category"], []).append(r)
    cat_rows = []
    for cat, members in cats.items():
        avg = sum(m["score"] for m in members) / len(members)
        rec = sum(1 for m in members if m["tier"] != "暂观望")
        top = max(members, key=lambda x: x["score"])
        # 同类历史信号胜率聚合 + 样例收集（过往类似选品判断结果）
        hw = sum(m["hist"]["wins"] for m in members)
        ht = sum(m["hist"]["total"] for m in members)
        rate = (hw / ht) if ht else None
        examples = []
        for m in members:
            for e in m["hist"]["examples"]:
                examples.append(dict(name=m["name"], **e))
        examples.sort(key=lambda x: (x.get("date") or ""), reverse=True)
        # 板块平均 AI 方向概率（用于「置信偏低」标注）
        avg_pu = sum(m.get("pu", 0.5) for m in members) / len(members)
        cat_rows.append(dict(category=cat, avg=round(avg, 1), count=len(members),
                             rec=rec, top_name=top["name"], top_score=top["score"],
                             success_rate=rate, wins=hw, total=ht,
                             examples=examples[:8], avg_pu=avg_pu))
    cat_rows.sort(key=lambda x: x["avg"], reverse=True)
    return raw, cat_rows


# ---------------------------------------------------------------------------
# 历史信号回测：为每个选品机会计算「历史上同类信号」的胜率与样例
# ---------------------------------------------------------------------------
def _backtest_symbol(df, horizon: int = 5, cost_pct: float = 0.0006) -> dict:
    """对单合约历史日线做「入手机会信号」回测，返回胜率、样例与因子/收益对（供 IC 加权）。

    信号定义（与选品评分同源，体现「入手机会」而非「强势/热门」）：
        趋势向好(多头排列 MA5>MA20>MA60) 且 未过度透支(近20日涨幅<22%，留有
        上行空间) 且 量能配合(量比≥0.9，未缩量塌陷)。
    区别于「强势排行榜」：不要求已大幅上涨或量能暴增(≥1.05)，避免把「已强势」
    误判为「可入手」、提示用户追高。每当信号出现，记录其后 horizon 日收益，
    并收集该时刻的因子值与前瞻收益，用于跨合约汇总计算 RankIC（数据驱动因子权重）。

    胜率标签已改为「净成本」：fwd > cost 才算成功，更贴近真实交易。
    """
    try:
        close = df["close"].astype(float).to_numpy(dtype=float)
        volume = df["volume"].astype(float).to_numpy(dtype=float)
        openp = df["open"].astype(float).to_numpy(dtype=float) if "open" in df.columns else close
    except Exception:
        return dict(wins=0, total=0, rate=None, examples=[], fac={}, fwd=[])
    oi = None
    if "open_interest" in df.columns:
        try:
            oi = df["open_interest"].astype(float).to_numpy(dtype=float)
        except Exception:
            oi = None
    n = len(close)
    if n < 72:                      # 需足够历史支撑 MA60 与 horizon 日前瞻
        return dict(wins=0, total=0, rate=None, examples=[], fac={}, fwd=[])
    dates = None
    if "datetime" in df.columns:
        try:
            dates = df["datetime"].astype(str).to_numpy(dtype=str)
        except Exception:
            dates = None
    wins = total = 0
    examples = []
    fac = dict(ret20=[], ma_gap=[], fund=[], vr=[], oi=[], vol=[])
    fwd_list = []
    for t in range(60, n - horizon):
        ma5 = float(close[t - 4:t + 1].mean())
        ma20 = float(close[t - 19:t + 1].mean())
        ma60 = float(close[t - 59:t + 1].mean())
        bull = ma5 > ma20 > ma60
        c0 = close[t - 20]
        ret20 = (float(close[t]) / c0 - 1.0) if c0 else 0.0
        if t - 60 >= 0:
            vr = float(volume[t - 30:t].mean()) / (float(volume[t - 60:t - 30].mean()) or 1.0)
        else:
            vr = 1.0
        # 入手机会信号：趋势向好（多头排列）且未过度透支（留有上行空间）
        # + 量能配合；不要求已大幅上涨或量能暴增，避免把「已强势」误判为「可入手」。
        if bull and ret20 < 22 and vr >= 0.9:
            fwd = float(close[t + horizon]) / float(close[t]) - 1.0
            win = fwd > cost_pct
            total += 1
            wins += int(win)
            d = str(dates[t])[:10] if dates is not None else None
            examples.append(dict(date=d, fwd=round(float(fwd) * 100, 2), win=bool(win)))
            # 收集该信号时刻的因子值（与 _screen 当前快照同口径），供 RankIC 计算
            ma_gap = (ma5 / ma20 - 1.0) * 100.0 if ma20 else 0.0
            rets = np.diff(np.log(close[t - 19:t + 1]))
            vol = float(np.std(rets) * math.sqrt(252) * 100) if len(rets) >= 2 else 0.0
            fund = float(((close[t - 19:t + 1] - openp[t - 19:t + 1]) * volume[t - 19:t + 1]
                          * close[t - 19:t + 1]).sum() / 1e8)
            oi_v = 0.0
            if oi is not None and t - 30 >= 0:
                oi_v = (float(oi[t]) - float(oi[t - 30])) / (float(oi[t - 30]) or 1.0) * 100.0
            fac["ret20"].append(ret20)
            fac["ma_gap"].append(ma_gap)
            fac["fund"].append(fund)
            fac["vr"].append(vr)
            fac["oi"].append(oi_v)
            fac["vol"].append(vol)
            fwd_list.append(fwd)
    rate = (wins / total) if total else None
    return dict(wins=wins, total=total, rate=rate, examples=examples[-6:],
                fac=fac, fwd=fwd_list)


def _spearman(x, y) -> float:
    """Spearman 秩相关（因子值 vs 前瞻收益），衡量因子的预测力（IC）。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 5:
        return 0.0
    rx = x.argsort().argsort().astype(float)
    ry = y.argsort().argsort().astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    denom = math.sqrt((rx ** 2).sum()) * math.sqrt((ry ** 2).sum())
    return float(np.dot(rx, ry) / denom) if denom > 0 else 0.0


def _ai_p_up(df) -> float:
    """用快速岭回归给出「未来上涨概率」方向因子（进程内廉价，秒级）。
    
    复用 FuturesPredictor 的 7 特征 + 正态近似涨跌概率；失败回退中性 0.5。
    仅作选品排序的第 7 个因子，不阻塞主流程。
    """
    try:
        pr = FuturesPredictor()
        pr.fit(df, seq_len=20, epochs=15, force_ridge=True)
        res = pr.predict(df, horizon=5)
        return float(np.clip(res.get("p_up", 0.5), 0.01, 0.99))
    except Exception:
        return 0.5


def _ai_full_predict(df) -> tuple:
    """完整 AI 预测，返回 (p_up, expected_return, confidence)。
    
    用于选品页面展示 AI 预期收益和置信度，与预测页联动。
    """
    try:
        pr = FuturesPredictor()
        pr.fit(df, seq_len=20, epochs=15, force_ridge=True)
        res = pr.predict(df, horizon=5)
        p_up = float(np.clip(res.get("p_up", 0.5), 0.01, 0.99))
        exp = float(res.get("expected_return_pct", 0.0))
        # 置信度：基于模型信号强度计算
        risk = res.get("risk", {})
        resonance = res.get("resonance", {})
        conf = 0.5 + 0.3 * abs(p_up - 0.5) + 0.2 * min(abs(exp) / 10, 0.5)
        conf = min(0.95, max(0.1, conf))
        return p_up, exp, conf
    except Exception:
        return 0.5, 0.0, 0.5


def _history_kpi(raw: list) -> Optional[float]:
    """全市场信号历史胜率（按样本加权）。"""
    tw = sum(r["hist"]["wins"] for r in raw)
    tt = sum(r["hist"]["total"] for r in raw)
    return (tw / tt) if tt else None



def _logic_text(r: dict, cat_examples: Optional[list] = None) -> str:
    """根据指标生成「入手逻辑 / 风险提示 / 历史回测」文本。

    定位为「入手机会」：强调是否可考虑建仓，并对已大幅上涨（追高）的品种
    给出明确风险提示，避免把「强势」误读为「可入手」。

    cat_examples：同类（同板块）其他品种的历史信号样例，用于展示
    「过往类似选品的入手结果」。
    """
    logic, risk = [], []
    if r["ret_20"] > 0:
        logic.append(f"近20日涨幅 {r['ret_20']:.1f}%，趋势向上")
    else:
        logic.append(f"近20日下跌 {abs(r['ret_20']):.1f}%，整体偏弱")
    if r["bull"]:
        logic.append("均线多头排列（MA5 > MA20 > MA60）")
    elif r["ma_gap"] < 0:
        logic.append("均线空头压制（MA5 < MA20）")
    if r["fund"] > 0:
        logic.append(f"资金净流入约 {r['fund']:.2f} 亿")
    elif r["fund"] < 0:
        logic.append(f"资金净流出约 {abs(r['fund']):.2f} 亿")
    if r["vr"] > 1.15:
        logic.append(f"量能放大（{r['vr']:.1f}倍），趋势有量配合")
    elif r["vr"] < 0.85:
        logic.append(f"量能萎缩（{r['vr']:.1f}倍）")
    if r["oi"] > 1:
        logic.append(f"持仓增加 {r['oi']:.1f}%，多头增仓")
    elif r["oi"] < -1:
        logic.append(f"持仓减少 {abs(r['oi']):.1f}%，资金离场")

    if r["vol_20"] > 35:
        risk.append(f"年化波动 {r['vol_20']:.0f}% 偏高，务必严格止损")
    if r["ret_20"] < 0 and not r["bull"]:
        risk.append("趋势尚未扭转，逆势抄底风险大")
    if r["fund"] < 0:
        risk.append("资金净流出，短期或继续承压")
    if r["vr"] < 0.8:
        risk.append("量能不足，趋势持续性存疑")
    # 追高提示：近 20 日已大幅上涨、透支上行空间时，明确提示谨慎，
    # 把「强势」与「可入手」区分开，避免用户追高。
    if r.get("overext"):
        risk.append(f"近20日已涨 {r['ret_20']:.1f}%，处相对高位，追高需谨慎；"
                    f"等回踩支撑、确认不破位再入手更稳")
    if not risk:
        risk.append("信号相对健康，但仍需结合止损与仓位管理")

    head = (f"【{r['name']} {r['sym']}】 评分 {r['score']} · {r['tier']}\n"
            f"最新价 {r['last']:,.1f} ｜ 20日 {r['ret_20']:+.1f}% ｜ "
            f"资金流 {r['fund']:+.2f}亿 ｜ 年化波动 {r['vol_20']:.1f}%\n\n")
    head += "▍入手逻辑\n" + "\n".join(f"• {x}" for x in logic) + "\n\n"
    head += "▍风险提示\n" + "\n".join(f"• {x}" for x in risk)

    # 历史信号回测（成功率 + 过往类似选品判断结果）
    hist = r.get("hist", {})
    rate = hist.get("rate")
    total = hist.get("total", 0)
    head += "\n\n▍历史信号回测（成功率）\n"
    if rate is None or total == 0:
        head += "• 历史样本不足，暂无成功率统计\n"
    else:
        verdict = ("高" if rate >= 0.6 else "中" if rate >= 0.45 else "偏低")
        head += (f"• 同类入手信号历史胜率 {rate*100:.0f}%（{verdict}），"
                 f"基于近 {total} 次历史信号\n")
        ex = hist.get("examples", [])
        if ex:
            head += "• 本品种近期类似信号后续表现：\n"
            for e in ex[-4:]:
                tag = "盈利" if e["win"] else "亏损"
                d = e.get("date") or "—"
                head += f"   - {d} 信号后 {e['fwd']:+.1f}%（{tag}）\n"
    # 同类（同板块）其他品种的历史信号样例
    if cat_examples:
        head += "\n▍过往类似选品（同板块）入手结果\n"
        shown = 0
        for e in cat_examples:
            if e.get("name") == r["name"]:
                continue
            tag = "盈利" if e["win"] else "亏损"
            d = e.get("date") or "—"
            head += f"• {e['name']} {d} 信号后 {e['fwd']:+.1f}%（{tag}）\n"
            shown += 1
            if shown >= 5:
                break
        if shown == 0:
            head += "• （暂无其他同板块品种的历史信号样例）\n"
    return head


def _tier_color(tier: str) -> QColor:
    if tier == "优先入手":
        return QColor(PALETTE[THEME]["up"])       # 红（期货涨色）
    if tier == "可留意":
        return QColor("#3b82f6")
    return QColor(PALETTE[THEME]["text"])


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
class ScreeningPage(BasePage):
    navig_to_predict = pyqtSignal(str, str)  # symbol, period → 切换到 AI 预测并自动运行

    def __init__(self, mdm, store, config=None, session=None):
        super().__init__(mdm, store, config, session)
        self.PAGE_KEY = "screening"
        self._results: list = []
        self._cats: list = []
        self._filtered: list = []
        self._kpi_cards: list = []
        self._kpi_vals: dict = {}
        self._calib_info: Optional[dict] = None  # 校准分箱（_on_done 时读一次）
        self._build()
        self._run_lazy = True      # 首次 showEvent 时延迟加载筛选

    # ---- 构建 ----
    def _build(self):
        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)
        root.addWidget(PageHeader(
            "选品入手机会 · AI 决策辅助",
            "全合约入手机会评分 · 趋势 / 资金流 / 量能 / 持仓 / 波动 五维综合 + AI预测辅助 · "
            "直接回答「哪些品种可考虑入手 · 哪些板块值得关注 · AI预测信号如何」"))

        # 样本状态横幅
        self.banner = QFrame()
        self.banner.setObjectName("warn-banner")
        b_layout = QHBoxLayout(self.banner)
        b_layout.setContentsMargins(10, 6, 10, 6)
        self.banner_lbl = QLabel("")
        self.banner_lbl.setWordWrap(True)
        b_layout.addWidget(self.banner_lbl, 1)
        self.collect_btn = QPushButton("补充采集")
        self.collect_btn.setObjectName("warn")
        self.collect_btn.clicked.connect(self._on_collect)
        self.collect_btn.setVisible(False)
        b_layout.addWidget(self.collect_btn)
        self.banner.setVisible(False)
        self.banner.setStyleSheet(
            "QFrame{background:#fff7ed;border:1px solid #f59e0b;"
            "border-radius:8px;}")
        p = pal()
        self.banner_lbl.setStyleSheet(f"color:{p['accent']};font-weight:bold;")
        self.collect_btn.setStyleSheet(
            "QPushButton{background:#f59e0b;color:#ffffff;border:none;"
            "border-radius:6px;padding:5px 14px;font-weight:bold;}"
            "QPushButton:hover{background:#d97706;}"
            "QPushButton:disabled{background:#d6d3d1;}")
        root.addWidget(self.banner)

        # 工具条
        ctl = QHBoxLayout()
        self.sort_cb = QComboBox()
        for k, t in [("score", "按评分"), ("fund", "按资金流"),
                      ("rate", "按成功率"), ("ret", "按20日涨跌"),
                      ("ai_dir", "按AI方向")]:
            self.sort_cb.addItem(t, k)
        self.sort_cb.currentIndexChanged.connect(lambda _: self._apply_filter())
        self.cat_cb = QComboBox()
        for c in ["全部"] + sorted({r[2] for r in self.mdm.universe}):
            self.cat_cb.addItem(c)
        self.cat_cb.currentIndexChanged.connect(lambda _: self._apply_filter())
        self.run_btn = QPushButton("开始筛选")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        self.src_lbl = QLabel("")
        self.src_lbl.setObjectName("sub")
        ctl.addWidget(QLabel("排序")); ctl.addWidget(self.sort_cb)
        ctl.addWidget(QLabel("板块")); ctl.addWidget(self.cat_cb)
        ctl.addWidget(self.run_btn)
        ctl.addStretch(1)
        ctl.addWidget(self.src_lbl)
        root.addWidget(ToolBar(ctl))

        # KPI 卡片
        self._kpi_box = QHBoxLayout()
        self._kpi_box.setSpacing(8)
        for key, label in [("rec", "可考虑入手"), ("hot", "建议关注板块"),
                           ("top", "优先入手品种"), ("rate", "机会历史成功率"),
                           ("src", "数据源")]:
            card = QFrame()
            cv = QVBoxLayout(card)
            cv.setContentsMargins(10, 6, 10, 6)
            cv.setSpacing(2)
            v = QLabel("—")
            v.setObjectName("kpi-val")
            l = QLabel(label)
            l.setObjectName("kpi-lbl")
            cv.addWidget(v)
            cv.addWidget(l)
            self._kpi_cards.append(card)
            self._kpi_vals[key] = v
            self._kpi_box.addWidget(card)
        root.addLayout(self._kpi_box)
        self._style_kpi()

        # 主区：排行表 + 板块关注方向
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("全合约入手机会排行（单击查看入手逻辑 / 风险 / 历史成功率 / AI预测信号）"))
        self.tbl = QTableWidget(0, 13)
        self.tbl.setHorizontalHeaderLabels(
            ["合约", "板块", "评分", "历史成功率", "20日%", "资金流(亿)",
             "量比", "持仓变%", "波动%", "信号", "AI方向", "AI预期%", "AI置信度"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.setColumnWidth(10, 65)
        self.tbl.setColumnWidth(11, 70)
        self.tbl.setColumnWidth(12, 70)
        self.tbl.itemSelectionChanged.connect(self._on_select)
        lv.addWidget(self.tbl)
        # 评分档位图例（提升可读性）
        legend = QLabel(
            "<span style='color:#ef4444;font-weight:600;'>■</span> 优先入手 (评分≥68)　"
            "<span style='color:#3b82f6;font-weight:600;'>■</span> 可留意 (评分≥55)　"
            "<span style='color:#64748b;font-weight:600;'>■</span> 暂观望 (评分&lt;55)"
        )
        legend.setObjectName("legend-lbl")
        legend.setStyleSheet(f"font-size:12px;padding:4px 2px;color:{p['sub']};")
        lv.addWidget(legend)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("板块机会地图（颜色越红=平均入手机会越强）"))
        self.heat = QLabel("—")
        self.heat.setWordWrap(True)
        self.heat.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        rv.addWidget(self.heat)
        rv.addWidget(QLabel("板块关注方向（平均评分 / 入手数 / 历史成功率）"))
        self.ctbl = QTableWidget(0, 6)
        self.ctbl.setHorizontalHeaderLabels(
            ["板块", "平均评分", "品种数", "入手数", "成功率", "关注方向"])
        self.ctbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        rv.addWidget(self.ctbl)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        # 决策摘要卡（关键数据突出：评分 + 历史成功率 + 同类成功率 + 样本）
        root.addWidget(QLabel("决策摘要"))
        self._build_summary()

        # 入手逻辑与风险提示 + 历史回测
        root.addWidget(QLabel("入手逻辑 · 风险提示 · 历史信号回测"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(220)
        self.detail.setHtml(
            "<p style='color:#94a3b8'>点击上方任意品种，这里会给出该品种的"
            "<b>一句话结论 · 入手逻辑 · 风险提示 · 历史信号回测</b> 白话解读，"
            "帮助判断是否值得入手、何时入手。</p>")
        root.addWidget(self.detail)

        # 联动按钮：「在 AI 预测中分析」和「查看K线图」
        btn_row = QHBoxLayout()
        self.predict_btn = QPushButton("在 AI 预测中分析 →")
        self.predict_btn.setObjectName("primary")
        self.predict_btn.setVisible(False)
        self.predict_btn.clicked.connect(self._on_navigate_to_predict)
        btn_row.addWidget(self.predict_btn)
        
        self.chart_btn = QPushButton("查看K线图")
        self.chart_btn.setObjectName("secondary")
        self.chart_btn.setVisible(False)
        self.chart_btn.clicked.connect(self._on_show_chart)
        btn_row.addWidget(self.chart_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

    def _style_kpi(self):
        pal = PALETTE[THEME]
        for card in self._kpi_cards:
            card.setStyleSheet(
                f"QFrame{{background:{pal['card']};border:1px solid {pal['border']};"
                f"border-radius:8px;}}"
                f"QLabel#kpi-val{{color:{pal['text']};font-weight:bold;background:transparent;}}"
                f"QLabel#kpi-lbl{{color:{pal['sub']};background:transparent;}}")
        self._kpi_vals["src"].setText(self.mdm.source_label)

    # ---- 决策摘要卡 ----
    def _build_summary(self) -> None:
        pal = PALETTE[THEME]
        box = QHBoxLayout()
        box.setSpacing(8)
        self.sum_score = MetricChip("进场评分", "--", pal["text"])
        box.addWidget(self.sum_score)

        # 历史成功率卡（含 ConfidenceBar，关键数据突出）
        self.rate_card = QFrame()
        self.rate_card.setObjectName("chip")
        rcl = QVBoxLayout(self.rate_card)
        rcl.setContentsMargins(12, 8, 12, 8)
        rcl.setSpacing(4)
        rl = QLabel("历史成功率")
        rl.setObjectName("kpi-lbl")
        self.rate_bar = ConfidenceBar(0.0)
        self.rate_bar.setMinimumWidth(160)
        self.rate_val = QLabel("—")
        self.rate_val.setStyleSheet(
            f"color:{pal['text']};font-size:16px;font-weight:bold;")
        rcl.addWidget(rl)
        rcl.addWidget(self.rate_bar)
        rcl.addWidget(self.rate_val)
        box.addWidget(self.rate_card)

        self.sum_cat = MetricChip("同类成功率", "--", pal["text"])
        box.addWidget(self.sum_cat)
        self.sum_sample = MetricChip("历史样本", "--", pal["sub"])
        box.addWidget(self.sum_sample)
        self.sum_badge = Badge("", bg=pal["badge_bg"], fg=pal["text"])
        box.addWidget(self.sum_badge)
        box.addStretch(1)
        self._root.addLayout(box)

    def _apply_summary_theme(self) -> None:
        pal = PALETTE[THEME]
        self.rate_val.setStyleSheet(
            f"color:{pal['text']};font-size:16px;font-weight:bold;")
        self._style_rate_card()

    def _style_rate_card(self) -> None:
        pal = PALETTE[THEME]
        self.rate_card.setStyleSheet(
            f"#chip{{background:{pal['chip_bg']};border:1px solid {pal['border']};"
            f"border-radius:10px;}}")
        for w in (self.sum_score, self.sum_cat, self.sum_sample):
            w.set_theme(THEME)
        self.sum_badge.set_theme(THEME)

    def _update_summary(self, r: dict) -> None:
        """选中某选品时刷新决策摘要卡。"""
        pal = PALETTE[THEME]
        self.sum_score.set_value(f"{r['score']:.1f}", _tier_color(r["tier"]).name())
        hist = r.get("hist", {})
        rate = hist.get("rate")
        total = hist.get("total", 0)
        if rate is None or total == 0:
            self.rate_bar.set_pct(0.0)
            self.rate_val.setText("样本不足")
            self.rate_val.setStyleSheet(
                f"color:{pal['sub']};font-size:16px;font-weight:bold;")
        else:
            self.rate_bar.set_pct(rate)
            col = ("#22c55e" if rate >= 0.6 else "#f59e0b" if rate >= 0.45 else "#ef4444")
            self.rate_val.setText(f"{rate*100:.0f}% · {total}次")
            self.rate_val.setStyleSheet(
                f"color:{col};font-size:16px;font-weight:bold;")
        # 同类成功率
        if self._cats:
            mine = next((c for c in self._cats if c["category"] == r["category"]), None)
            if mine and mine.get("success_rate") is not None:
                self.sum_cat.set_value(f"{mine['success_rate']*100:.0f}%")
            else:
                self.sum_cat.set_value("--")
        else:
            self.sum_cat.set_value("--")
        self.sum_sample.set_value(str(total) if total else "--")
        self.sum_badge.set_text(r["tier"])
        self.sum_badge.set_color(
            _tier_color(r["tier"]).name(), "#ffffff")

    # ---- 懒加载：首次可见时启动筛选后台任务 ----
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_run_lazy", False):
            self._run_lazy = False
            QTimer.singleShot(100, self._run)

    # ---- 运行 ----
    def _run(self):
        self.run_btn.setEnabled(False)
        self.run_btn.setText("筛选中…")
        self.src_lbl.setText(f"数据源：{self.mdm.source_label}")
        # 传入 store：样本不足时自动持久化标记（不静默丢弃，T1）
        self._run_worker(lambda: _screen(self.mdm, self.store),
                         self._on_done, self._on_err)

    def _on_done(self, payload):
        self._results, self._cats = payload
        self._calib_info = self._load_calib()
        self.run_btn.setEnabled(True)
        self.run_btn.setText("开始筛选")
        self._render()
        self._refresh_sample_banner()

    def _load_calib(self) -> Optional[dict]:
        """筛选完成后读一次全局校准分箱（status='closed' 样本），供 AI 方向标注「置信偏低」。

        失败 / 无样本时返回 None，_calib_low_conf 安全回退 False（不误报）。
        """
        try:
            info = reliability_calibration(self.store)
            if isinstance(info, dict) and (info.get("bins") or []):
                return info
        except Exception:
            pass
        return None

    def _calib_low_conf(self, pu: float) -> bool:
        """品种 AI 方向概率 pu 是否落在校准区间过宽档（该档历史样本稀疏）。

        与 ⑬/⑭ 同一判定口径：落点 Wilson 区间宽 > 阈值 或 该档样本 < 50 即判低置信。
        无校准信息 / 空 bins / 异常 → False（零副作用）。
        """
        info = getattr(self, "_calib_info", None)
        if not isinstance(info, dict):
            return False
        bins = info.get("bins", []) or []
        if not bins:
            return False
        try:
            lo, hi = calibration_band_at(bins, float(pu))
        except Exception:
            return False
        if lo is None or hi is None:
            return False
        # 用最近中心值匹配该落点所在分箱（避免 Wilson 区间边界截断导致误匹配）
        n_at_bin = min(bins, key=lambda b: abs(b[0] - float(pu)))[2]
        if n_at_bin < 50:
            return True
        return (hi - lo) > LOW_CONF_BAND_WIDTH

    def _refresh_sample_banner(self) -> None:
        """样本不足时显示醒目横幅 + 补充采集入口（T1）。"""
        bad = self.store.query_insufficient_samples()
        if not bad:
            self.banner.setVisible(False)
            self.collect_btn.setVisible(False)
            return
        syms = "、".join(b["symbol"] for b in bad[:8])
        more = f" 等 {len(bad)} 个" if len(bad) > 8 else ""
        self.banner_lbl.setText(
            f"⚠ 样本不足：{syms}{more} 历史日线不足，已本地留痕（不丢失）。"
            f"点击「补充采集」重新拉取并补齐后再筛。")
        self.banner.setVisible(True)
        self.collect_btn.setVisible(True)

    def _on_collect(self) -> None:
        """补充采集：对样本不足品种重新拉取更多日线并落库，随后自动重筛（T1）。"""
        bad = self.store.query_insufficient_samples()
        if not bad:
            return
        self.collect_btn.setEnabled(False)
        self.collect_btn.setText("采集中…")
        syms = [b["symbol"] for b in bad]

        def work():
            collected = []
            for sym in syms:
                try:
                    df = self.mdm.get_bars(sym, "D", limit=600)
                except Exception:
                    continue
                avail = len(df) if df is not None else 0
                if df is not None and avail >= 65:
                    try:
                        self.store.cache_bars(sym, "D", df)
                    except Exception:
                        pass
                    self.store.mark_sample_collected(sym, avail)
                    collected.append(sym)
                else:
                    self.store.upsert_sample(
                        sym, "D", avail, 65, 0,
                        status="不足", note=f"仅 {avail} 根，需 65")
            return collected

        def done(collected):
            self.collect_btn.setEnabled(True)
            self.collect_btn.setText("补充采集")
            if collected:
                self._run()           # 补齐后自动重筛
            else:
                self._refresh_sample_banner()

        self._run_worker(work, done, lambda e: (
            self.collect_btn.setEnabled(True),
            self.collect_btn.setText("补充采集"),
            self._refresh_sample_banner()))

    def _on_err(self, msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("开始筛选")
        self.detail.setPlainText(f"筛选失败：{msg}（请检查行情源是否可取）")

    # ---- 渲染 ----
    @staticmethod
    def _sort_key(r: dict, key: str):
        if key == "fund":
            return float(r.get("fund", 0.0))
        if key == "rate":
            h = r.get("hist", {}) or {}
            rt = h.get("rate")
            return rt if rt is not None else -1.0
        if key == "ret":
            return float(r.get("ret_20", 0.0))
        if key == "ai_dir":
            return float(r.get("pu", 0.5))
        return float(r.get("score", 0.0))

    @staticmethod
    def _heat_color(avg: float) -> str:
        if avg >= 68:
            return "#ef4444"      # 红：机会强
        if avg >= 60:
            return "#f59e0b"      # 橙：偏强
        if avg >= 50:
            return "#3b82f6"      # 蓝：中性
        return "#64748b"            # 灰：偏弱

    def _apply_filter(self):
        if not self._results:
            return
        cat = self.cat_cb.currentText()
        self._filtered = (self._results if cat == "全部"
                          else [r for r in self._results if r["category"] == cat])
        key = self.sort_cb.currentData()
        self._filtered.sort(key=lambda r: self._sort_key(r, key), reverse=True)
        self._render_table()
        self._render_cats()
        self._auto_select()

    def _render(self):
        self._style_kpi()
        # KPI
        rec = [r for r in self._results if r["tier"] != "暂观望"]
        top = self._results[0] if self._results else None
        hottest = self._cats[0] if self._cats else None
        rate = _history_kpi(self._results)
        self._kpi_vals["rec"].setText(str(len(rec)))
        self._kpi_vals["hot"].setText(hottest["category"] if hottest else "—")
        self._kpi_vals["top"].setText(f"{top['name']} {top['score']:.0f}" if top else "—")
        self._kpi_vals["rate"].setText(
            f"{rate*100:.0f}%" if rate is not None else "—")
        self._apply_filter()

    def _render_table(self):
        res = self._filtered
        self.tbl.setRowCount(len(res))
        for i, r in enumerate(res):
            self.tbl.setRowHeight(i, 36)
            self._set(self.tbl, i, 0, r["name"])
            self._set(self.tbl, i, 1, r["category"])
            tc = _tier_color(r["tier"])
            sc = self._set(self.tbl, i, 2, f"{r['score']:.1f}", "#ffffff")
            sc.setBackground(QColor(tc.name()))
            f = sc.font(); f.setBold(True); f.setPointSize(11); sc.setFont(f)
            # 历史成功率（关键指标，按阈值着色突出）
            hist = r.get("hist", {})
            rate = hist.get("rate")
            total = hist.get("total", 0)
            if rate is None or total == 0:
                self._set(self.tbl, i, 3, "—", QColor(PALETTE[THEME]["sub"]))
            else:
                col = ("#22c55e" if rate >= 0.6 else "#f59e0b" if rate >= 0.45
                       else "#ef4444")
                self._set(self.tbl, i, 3, f"{rate*100:.0f}%", QColor(col))
            a = self._set(self.tbl, i, 4, f"{r['ret_20']:+.1f}")
            color_pnl(a, r["ret_20"])
            b = self._set(self.tbl, i, 5, f"{r['fund']:+.2f}")
            color_pnl(b, r["fund"])
            self._set(self.tbl, i, 6, f"{r['vr']:.2f}")
            c = self._set(self.tbl, i, 7, f"{r['oi']:+.1f}")
            color_pnl(c, r["oi"])
            self._set(self.tbl, i, 8, f"{r['vol_20']:.1f}")
            self._set(self.tbl, i, 9, r["tier"], _tier_color(r["tier"]))
            # AI 方向概率因子（秒级岭回归，复用 predictor）
            pu = r.get("pu", 0.5)
            # 校准不确定度 → AI 方向标注「置信偏低」：落点处 Wilson 区间过宽
            # （该档概率历史校准样本稀疏）时，提示该方向研判可信度下降。
            low_conf = self._calib_low_conf(pu)
            ai_dir = "偏多" if pu >= 0.55 else ("偏空" if pu <= 0.45 else "中性")
            if low_conf:
                ai_dir += "·置信偏低"
            pal = PALETTE[THEME]
            ai_col = ("#f59e0b" if low_conf else
                      pal["up"] if pu >= 0.55 else
                      (pal["down"] if pu <= 0.45 else pal["sub"]))
            it_ai = self._set(self.tbl, i, 10, ai_dir, QColor(ai_col))
            font = it_ai.font()
            font.setPointSize(9); font.setBold(True)
            it_ai.setFont(font)
            
            # AI 预测预期收益（新增列）
            ai_exp = r.get("ai_exp", 0.0)
            exp_col = pal["up"] if ai_exp >= 0 else (pal["down"] if ai_exp < 0 else pal["sub"])
            it_exp = self._set(self.tbl, i, 11, f"{ai_exp:+.1f}%", QColor(exp_col))
            it_exp.setFont(font)
            
            # AI 置信度（新增列）
            ai_conf = r.get("ai_conf", 0.5)
            conf_col = "#22c55e" if ai_conf >= 0.65 else "#f59e0b" if ai_conf >= 0.5 else "#ef4444"
            it_conf = self._set(self.tbl, i, 12, f"{ai_conf*100:.0f}%", QColor(conf_col))
            it_conf.setFont(font)
        prepare_table(self.tbl)

    def _render_cats(self):
        self.ctbl.setRowCount(len(self._cats))
        for i, c in enumerate(self._cats):
            self._set(self.ctbl, i, 0, c["category"])
            self._set(self.ctbl, i, 1, f"{c['avg']:.1f}")
            self._set(self.ctbl, i, 2, str(c["count"]))
            self._set(self.ctbl, i, 3, str(c["rec"]))
            sr = c.get("success_rate")
            if sr is None:
                self._set(self.ctbl, i, 4, "—", QColor(PALETTE[THEME]["sub"]))
            else:
                col = ("#22c55e" if sr >= 0.6 else "#f59e0b" if sr >= 0.45
                       else "#ef4444")
                self._set(self.ctbl, i, 4, f"{sr*100:.0f}%", QColor(col))
            # 关注方向：有入手品种且平均评分较高 → 重点留意；仅有入手品种 → 可留意；无 → 暂观望
            direction = ("重点留意" if (c["rec"] > 0 and c["avg"] >= 60)
                         else ("可留意" if c["rec"] > 0 else "暂观望"))
            # 校准不确定度 → 板块关注方向「置信偏低」标注（与品种表同一口径）
            low_conf = self._calib_low_conf(c.get("avg_pu", 0.5))
            if low_conf:
                direction += " ·置信偏低"
            self._set(self.ctbl, i, 5, direction)
        prepare_table(self.ctbl)
        # 板块机会地图（彩色热力格）
        cells = []
        for c in self._cats:
            col = self._heat_color(c["avg"])
            cells.append(
                f"<span style='display:inline-block;min-width:104px;margin:4px;"
                f"padding:8px 10px;border-radius:10px;background:{col};color:#ffffff;"
                f"text-align:center;font-weight:bold'>"
                f"{c['category']}<br>"
                f"<span style='font-size:11px;font-weight:normal'>"
                f"评分 {c['avg']:.0f} · {c['rec']} 品种</span></span>")
        self.heat.setText("<div style='line-height:1.9'>" + "".join(cells) + "</div>")

    def _auto_select(self):
        if self._filtered:
            self.tbl.selectRow(0)
        else:
            self.detail.setPlainText("当前筛选条件下无品种。")

    def _on_select(self):
        row = self.tbl.currentRow()
        if row < 0 or row >= len(self._filtered):
            return
        r = self._filtered[row]
        cat = next((c for c in self._cats if c["category"] == r["category"]), None)
        cat_ex = cat["examples"] if cat else []
        self.detail.setHtml(self._logic_html(r, cat_ex))
        self._update_summary(r)
        # 显示联动按钮
        sym = r["sym"].replace(".", ".")
        self.predict_btn.setVisible(True)
        self.predict_btn._current_sym = sym
        self.predict_btn._current_per = "D"  # 默认日线周期
        # K线图按钮
        self.chart_btn.setVisible(True)
        self.chart_btn._current_sym = sym
        self.chart_btn._current_name = r["name"]

    def _on_navigate_to_predict(self):
        """将选中的品种联动到 AI 预测页。"""
        sym = getattr(self.predict_btn, "_current_sym", None)
        per = getattr(self.predict_btn, "_current_per", "D")
        if sym:
            self.navig_to_predict.emit(sym, per)
    
    def _on_show_chart(self):
        """显示选中品种的 K 线图弹出窗口。"""
        sym = getattr(self.chart_btn, "_current_sym", None)
        name = getattr(self.chart_btn, "_current_name", "")
        if not sym:
            return
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout
            from .chart_widget import KLineChart
            from ..indicators.tech import add_indicators
            from ..ui.pages import df_to_bars
            
            dlg = QDialog(self)
            dlg.setWindowTitle(f"{name} {sym} - K线图预览")
            dlg.resize(800, 500)
            layout = QVBoxLayout(dlg)
            chart = KLineChart()
            chart.set_theme(THEME)
            layout.addWidget(chart)
            
            df = self.mdm.get_bars(sym, "D", 120)
            if df is not None and not df.empty:
                ind = add_indicators(df)
                bars = df_to_bars(df)
                chart.set_data(bars, ma={"MA10": ind["MA10"].tolist(), 
                                          "MA20": ind["MA20"].tolist(),
                                          "MA60": ind["MA60"].tolist()})
                chart.set_watermark(f"{sym} · D")
            dlg.exec()
        except Exception:
            pass

    def _set(self, table, r, c, text, color=None):
        it = QTableWidgetItem(str(text))
        fg = (QColor(color) if isinstance(color, str) else color) if color is not None \
            else QColor(PALETTE[THEME]["text"])
        it.setForeground(fg)
        table.setItem(r, c, it)
        return it

    # ---- 入手详情：结构化 HTML（比纯文本更易读） ----
    def _logic_html(self, r: dict, cat_examples: Optional[list] = None) -> str:
        """把「入手逻辑 / 风险提示 / 历史信号回测 / AI预测」渲染为结构化 HTML，更直观易读。"""
        p = PALETTE[THEME]
        tcol = _tier_color(r["tier"]).name()
        logic, risk = [], []
        if r["ret_20"] > 0:
            logic.append(f"近20日涨幅 <b>{r['ret_20']:.1f}%</b>，趋势向上")
        else:
            logic.append(f"近20日下跌 <b>{abs(r['ret_20']):.1f}%</b>，整体偏弱")
        if r["bull"]:
            logic.append("均线多头排列（<b>MA5 &gt; MA20 &gt; MA60</b>）")
        elif r["ma_gap"] < 0:
            logic.append("均线空头压制（MA5 &lt; MA20）")
        if r["fund"] > 0:
            logic.append(f"资金净流入约 <b>{r['fund']:.2f} 亿</b>")
        elif r["fund"] < 0:
            logic.append(f"资金净流出约 <b>{abs(r['fund']):.2f} 亿</b>")
        if r["vr"] > 1.15:
            logic.append(f"量能放大（{r['vr']:.1f} 倍），趋势有量配合")
        elif r["vr"] < 0.85:
            logic.append(f"量能萎缩（{r['vr']:.1f} 倍）")
        if r["oi"] > 1:
            logic.append(f"持仓增加 {r['oi']:.1f}%，多头增仓")
        elif r["oi"] < -1:
            logic.append(f"持仓减少 {abs(r['oi']):.1f}%，资金离场")
        if r["vol_20"] > 35:
            risk.append(f"年化波动 {r['vol_20']:.0f}% 偏高，<b>务必严格止损</b>")
        if r["ret_20"] < 0 and not r["bull"]:
            risk.append("趋势尚未扭转，逆势抄底风险大")
        if r["fund"] < 0:
            risk.append("资金净流出，短期或继续承压")
        if r["vr"] < 0.8:
            risk.append("量能不足，趋势持续性存疑")
        if r.get("overext"):
            risk.append(f"近20日已涨 {r['ret_20']:.1f}%，处相对高位，"
                        f"<b>追高需谨慎</b>；等回踩支撑、确认不破位再入手更稳")
        if not risk:
            risk.append("信号相对健康，但仍需结合止损与仓位管理")
        li = lambda items: "".join(f"<li style='margin:3px 0'>{x}</li>" for x in items)

        if r["tier"] == "优先入手":
            verdict = (f"综合评分 <b>{r['score']:.1f}</b>，"
                       f"<b style='color:{tcol}'>优先入手</b>：趋势与资金配合，"
                       f"可考虑分批建仓、回踩支撑加仓。")
        elif r["tier"] == "可留意":
            verdict = (f"综合评分 <b>{r['score']:.1f}</b>，"
                       f"<b style='color:{tcol}'>可留意</b>：具备一定机会，"
                       f"建议结合回踩支撑与严格止损再动手。")
        else:
            verdict = (f"综合评分 <b>{r['score']:.1f}</b>，"
                       f"<b style='color:{tcol}'>暂观望</b>：当前信号偏弱，"
                       f"不建议贸然入手，等信号转强。")
        html = (
            f"<div style='font-size:13px;color:{p['text']}'>"
            f"<p style='margin:0 0 8px;font-size:14px;font-weight:bold;color:{tcol}'>{verdict}</p>"
            f"<p style='margin:0 0 6px'><b style='font-size:14px'>{r['name']} "
            f"<span style='color:{p['sub']};font-size:12px'>{r['sym']}</span></b> "
            f"<span style='background:{tcol};color:#fff;padding:1px 8px;"
            f"border-radius:10px;font-size:12px'>{r['tier']}</span> "
            f"<span style='color:{p['sub']}'>评分 {r['score']:.1f}</span></p>"
            f"<p style='margin:0 0 8px;color:{p['sub']};font-size:12px'>"
            f"最新价 {r['last']:,.1f} ｜ 20日 {r['ret_20']:+.1f}% ｜ "
            f"资金流 {r['fund']:+.2f}亿 ｜ 年化波动 {r['vol_20']:.1f}%</p>"
            f"<p style='font-weight:bold;margin:8px 0 2px'>① 入手逻辑</p>"
            f"<ul style='margin:2px 0 0 16px'>{li(logic)}</ul>"
            f"<p style='font-weight:bold;margin:10px 0 2px'>② 风险提示</p>"
            f"<ul style='margin:2px 0 0 16px'>"
            f"{li([f'<span style=\"color:{p['down']}\">{x}</span>' if ('追高' in x or '止损' in x) else x for x in risk])}</ul>"
        )
        # ③ AI 预测信号（新增板块，整合 AI 预测数据）
        pu = r.get("pu", 0.5)
        ai_exp = r.get("ai_exp", 0.0)
        ai_conf = r.get("ai_conf", 0.5)
        # 校准不确定度 → AI 方向标注「置信偏低」（与排行榜 AI方向列口径一致）
        low_conf = self._calib_low_conf(pu)
        ai_dir = "偏多" if pu >= 0.55 else ("偏空" if pu <= 0.45 else "中性")
        ai_dir_color = ("#f59e0b" if low_conf else
                        "#22c55e" if pu >= 0.55 else
                        ("#ef4444" if pu <= 0.45 else "#f59e0b"))
        exp_color = "#22c55e" if ai_exp >= 0 else "#ef4444"
        conf_color = "#22c55e" if ai_conf >= 0.65 else "#f59e0b" if ai_conf >= 0.5 else "#ef4444"
        ai_dir_suffix = (" <span style='color:#f59e0b'>·置信偏低</span>"
                         if low_conf else "")
        html += (f"<p style='font-weight:bold;margin:10px 0 2px'>③ AI 预测信号</p>"
                 f"<p style='margin:2px 0'>AI 方向判断：<b style='color:{ai_dir_color}'>{ai_dir}</b>{ai_dir_suffix} "
                 f"（上涨概率 {pu*100:.0f}%）</p>"
                 f"<p style='margin:2px 0'>AI 预期收益：<b style='color:{exp_color}'>{ai_exp:+.1f}%</b></p>"
                 f"<p style='margin:2px 0'>AI 置信度：<b style='color:{conf_color}'>{ai_conf*100:.0f}%</b></p>"
                 f"{('<p style=\'margin:2px 0;color:#f59e0b\'>⚠ 该档概率历史校准样本稀疏，'
                    'AI 方向研判可信度下降，建议结合其他维度谨慎参考。</p>') if low_conf else ''}")
        hist = r.get("hist", {})
        rate = hist.get("rate"); total = hist.get("total", 0)
        html += "<p style='font-weight:bold;margin:10px 0 2px'>④ 历史信号回测（成功率）</p>"
        if rate is None or total == 0:
            html += f"<p style='color:{p['sub']};margin:2px 0'>历史样本不足，暂无成功率统计。</p>"
        else:
            v = ("高" if rate >= 0.6 else "中" if rate >= 0.45 else "偏低")
            vcol = "#22c55e" if rate >= 0.6 else ("#f59e0b" if rate >= 0.45 else "#ef4444")
            html += (f"<p style='margin:2px 0'>同类入手信号历史胜率 "
                     f"<b style='color:{vcol}'>{rate*100:.0f}%（{v}）</b>，"
                     f"基于近 {total} 次历史信号。</p>")
            ex = hist.get("examples", [])
            if ex:
                rows = ""
                for e in ex[-4:]:
                    tag = "盈利" if e["win"] else "亏损"
                    c3 = "#22c55e" if e["win"] else "#ef4444"
                    d = e.get("date") or "—"
                    rows += (f"<tr><td style='padding:2px 8px 2px 0;color:{p['sub']}'>{d}</td>"
                             f"<td style='padding:2px 8px;color:{c3}'>{tag}</td>"
                             f"<td style='padding:2px 8px;color:{c3}'>{e['fwd']:+.1f}%</td></tr>")
                html += (f"<table style='border-collapse:collapse;font-size:12px;margin:2px 0'>"
                         f"<tr style='color:{p['sub']};font-size:11px'>"
                         f"<td style='padding:2px 8px'>日期</td><td style='padding:2px 8px'>结果</td>"
                         f"<td style='padding:2px 8px'>信号后</td></tr>{rows}</table>")
        if cat_examples:
            shown = 0; parts = []
            for e in cat_examples:
                if e.get("name") == r["name"]:
                    continue
                tag = "盈利" if e["win"] else "亏损"
                c3 = "#22c55e" if e["win"] else "#ef4444"
                d = e.get("date") or "—"
                parts.append(f"<li style='margin:2px 0'><span style='color:{p['sub']}'>{e['name']} {d}</span> "
                                  f"<span style='color:{c3}'>{e['fwd']:+.1f}%（{tag}）</span></li>")
                shown += 1
                if shown >= 5:
                    break
            if parts:
                html += (f"<p style='font-weight:bold;margin:10px 0 2px'>⑤ 过往类似选品（同板块）入手结果</p>"
                         f"<ul style='margin:2px 0 0 16px;font-size:12px'>{"".join(parts)}</ul>")
        html += (f"<p style='margin:10px 0 0;color:{p['sub']};font-size:11px'>"
                 f"本页为量化筛选工具，结果均不构成投资建议。</p></div>")
        return html

    # ---- 主题 ----
    def set_theme(self, t: str) -> None:
        super().set_theme(t)
        self._style_kpi()
        self._apply_summary_theme()
        if self._results:
            self._render_table()
            self._render_cats()
            # 重新渲染当前选中项的摘要配色
            row = self.tbl.currentRow()
            if 0 <= row < len(self._filtered):
                self._update_summary(self._filtered[row])
