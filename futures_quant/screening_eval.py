"""选品机会模块「预测成功率」量化验证（方向一·1.3 延伸 / 任务2）。

目标：用可复现的合成多合约数据，walk-forward 对比
    - baseline ：固定权重(0.32/0.13/0.20/0.13/0.10/0.12) 启发式打分，无 AI 因子
    - enhanced ：|RankIC| 数据驱动加权 + AI 方向概率(p_up) 第 7 因子
在同一测试集上的预测力差异，给出可量化指标与验证方法。

数据构造：每个合约的前瞻 10 日收益由「动量(ret20)」与「隐藏 AI 信号」共同驱动，
其余因子(均线偏离/资金流/量比/持仓)仅含噪声——用于验证 IC 加权能自动给有预测力
的因子更高权重、并抑制噪声因子；p_up 由 AI 信号加噪得到，代表模型输出。
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1) 合成多合约数据（含可预测结构）
# ---------------------------------------------------------------------------
def make_contracts(n_contracts: int = 30, n_bars: int = 400,
                   seed: int = 0) -> List[pd.DataFrame]:
    rng = np.random.default_rng(seed)
    out = []
    for c in range(n_contracts):
        # 慢变隐藏因子（AI 信号来源），随机游走=>高度持久，
        # 当前水平可预测近期未来（使 p_up 真实具备信息）。
        hidden = np.cumsum(rng.normal(0, 0.004, n_bars))
        ret = np.zeros(n_bars)
        for t in range(2, n_bars):
            # 动量(可被 ret20 捕捉) + 持久 hidden 水平(AI 可学) + 噪声
            ret[t] = (0.25 * ret[t - 1]
                      + 0.30 * hidden[t]
                      + rng.normal(0, 0.016))
        price = 100.0 * np.exp(np.cumsum(ret))
        high = price * (1 + np.abs(rng.normal(0, 0.006, n_bars)))
        low = price * (1 - np.abs(rng.normal(0, 0.006, n_bars)))
        open_ = price * (1 + rng.normal(0, 0.003, n_bars))
        vol = 1e4 * np.exp(np.abs(rng.normal(0, 0.4, n_bars)))
        # 隐藏信号归一化（供"AI 模型输出"p_up 参考）
        ai = (hidden - hidden.mean()) / (hidden.std() + 1e-9)
        df = pd.DataFrame({"open": open_, "high": high, "low": low,
                           "close": price, "volume": vol})
        df["_ai"] = ai
        out.append(df)
    return out


# ---------------------------------------------------------------------------
# 2) 因子计算（与 screening_page._screen 同口径）
# ---------------------------------------------------------------------------
def factors_last(df: pd.DataFrame, mult: float = 1.0) -> Dict[str, float]:
    close = df["close"].astype(float).to_numpy()
    openp = df["open"].astype(float).to_numpy()
    volume = df["volume"].astype(float).to_numpy()
    n = len(close)
    ret20 = (close[-1] / close[-21] - 1.0) * 100 if n > 21 else 0.0
    ma5 = close[-5:].mean()
    ma20 = close[-20:].mean()
    ma60 = close[-60:].mean() if n >= 60 else ma20
    ma_gap = (ma5 / ma20 - 1.0) * 100 if ma20 else 0.0
    ret = np.diff(np.log(close))
    vol_20 = float(np.std(ret[-20:]) * math.sqrt(252) * 100) if len(ret) >= 20 else 0.0
    fund = float(((close[-20:] - openp[-20:]) * volume[-20:] * close[-20:]
                  * mult).sum() / 1e8)
    half = max(1, n // 2)
    vr = (volume[-half:].mean() / (volume[:half].mean() or 1.0))
    oi = 0.0  # 合成数据无持仓，保持 0
    vol_score = max(0.0, 1.0 - abs(vol_20 - 28.0) / 35.0)
    return dict(ret20=ret20, ma_gap=ma_gap, fund=fund, vr=float(vr),
                oi=oi, vol_score=vol_score)


def ai_p_up(df: pd.DataFrame) -> float:
    """模拟 AI 模型输出：由隐藏信号加噪得到方向概率（代表 FuturesPredictor.p_up）。"""
    ai = df["_ai"].to_numpy()
    raw = 0.5 + 0.45 * ai[-1]
    noise = np.random.default_rng(int(ai[-1] * 1e6) & 0xFFFF).normal(0, 0.03)
    return float(np.clip(raw + noise, 0.01, 0.99))


# ---------------------------------------------------------------------------
# 3) 历史信号/收益对（供 IC 计算，与 _backtest_symbol 同口径）
# ---------------------------------------------------------------------------
def backtest_pairs(df: pd.DataFrame, horizon: int = 10,
                   signal_only: bool = False) -> Tuple[Dict[str, list], list]:
    """因子→收益样本对，供 RankIC 估计。

    signal_only=False（默认）：在「全部历史切面」采样，反映因子在一般条件下的
    预测力（避免只在牛市切片采样导致均值回归假象，错误估计 IC）。
    signal_only=True：仅信号触发切面，用于真实信号的历史胜率展示。
    """
    close = df["close"].astype(float).to_numpy()
    volume = df["volume"].astype(float).to_numpy()
    openp = df["open"].astype(float).to_numpy()
    n = len(close)
    if n < 72:
        return {}, []
    fac = dict(ret20=[], ma_gap=[], fund=[], vr=[], oi=[], vol=[])
    fwd_list = []
    for t in range(60, n - horizon):
        ma5 = close[t - 4:t + 1].mean()
        ma20 = close[t - 19:t + 1].mean()
        ma60 = close[t - 59:t + 1].mean()
        bull = ma5 > ma20 > ma60
        c0 = close[t - 20]
        ret20 = (close[t] / c0 - 1.0) if c0 else 0.0
        vr = (volume[t - 30:t].mean() / (volume[t - 60:t - 30].mean() or 1.0))
        if signal_only and not (ret20 > 0 and bull and vr >= 1.05):
            continue
        fwd = close[t + horizon] / close[t] - 1.0
        fwd_list.append(fwd)
        ma_gap = (ma5 / ma20 - 1.0) * 100 if ma20 else 0.0
        rets = np.diff(np.log(close[t - 19:t + 1]))
        vol = float(np.std(rets) * math.sqrt(252) * 100) if len(rets) >= 2 else 0.0
        fund = float(((close[t - 19:t + 1] - openp[t - 19:t + 1])
                      * volume[t - 19:t + 1] * close[t - 19:t + 1]).sum() / 1e8)
        fac["ret20"].append(ret20)
        fac["ma_gap"].append(ma_gap)
        fac["fund"].append(fund)
        fac["vr"].append(float(vr))
        fac["oi"].append(0.0)
        fac["vol"].append(vol)
    return fac, fwd_list


# ---------------------------------------------------------------------------
# 4) 打分（use_ic / use_pu 开关，复刻 screening_page 权重逻辑）
# ---------------------------------------------------------------------------
def _spearman(x, y) -> float:
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y); x, y = x[m], y[m]
    if len(x) < 5:
        return 0.0
    rx = x.argsort().argsort().astype(float) - (len(x) - 1) / 2
    ry = y.argsort().argsort().astype(float) - (len(y) - 1) / 2
    d = math.sqrt((rx ** 2).sum()) * math.sqrt((ry ** 2).sum())
    return float(np.dot(rx, ry) / d) if d > 0 else 0.0


def _rank(vals):
    s = sorted(vals); n = len(s)
    return [__import__("bisect").bisect_right(s, v) / n for v in vals]


def score_contracts(contracts: List[pd.DataFrame], use_ic: bool, use_pu: bool
                    ) -> List[float]:
    facs = [factors_last(df) for df in contracts]
    pus = [ai_p_up(df) for df in contracts]
    # 历史信号对（供 IC）
    pooled = {k: [] for k in ("ret20", "ma_gap", "fund", "vr", "oi")}
    pfwd = []
    for df in contracts:
        f, fw = backtest_pairs(df, horizon=10)
        if fw:
            for k in pooled:
                pooled[k].extend(f.get(k, []))
            pfwd.extend(fw)
    if use_ic and len(pfwd) >= 10:
        ics = {k: _spearman(pooled[k], pfwd) for k in pooled}
        absics = {k: abs(ics[k]) + 0.05 for k in pooled}
        s_ic = sum(absics.values()) or 1.0
        w = {k: 0.70 * absics[k] / s_ic for k in pooled}
    else:
        w = {"ret20": 0.32, "ma_gap": 0.13, "fund": 0.20, "vr": 0.13, "oi": 0.10}
    rt = _rank([f["ret20"] for f in facs])
    rm = _rank([f["ma_gap"] for f in facs])
    rf = _rank([f["fund"] for f in facs])
    rv = _rank([f["vr"] for f in facs])
    ro = _rank([f["oi"] for f in facs])
    rpu = _rank(pus)
    scores = []
    for i in range(len(contracts)):
        base = (w["ret20"] * rt[i] + w["ma_gap"] * rm[i] + w["fund"] * rf[i]
                + w["vr"] * rv[i] + w["oi"] * ro[i])
        if use_pu:
            # 固定权重合计 1.0：pu 占 0.18，五因子占 0.82
            s = 0.82 * base / (sum(w.values()) or 1.0) + 0.18 * rpu[i]
        else:
            s = base  # 固定权重本就合计≈1.0（0.88，vol 另计）
            s = s + 0.12 * facs[i]["vol_score"]
        scores.append(100.0 * s)
    return scores


# ---------------------------------------------------------------------------
# 5) Walk-forward 指标
# ---------------------------------------------------------------------------
def walk_forward(contracts: List[pd.DataFrame], use_ic: bool, use_pu: bool,
                 top_n: int = 5, hold: int = 10) -> Dict[str, float]:
    """在多个时间切点上：用截至切点的数据打分，再用之后 hold 日收益评估。"""
    n_bars = min(len(df) for df in contracts)
    cutoffs = range(150, n_bars - hold - 5, 40)
    rankics, sharpes, dir_acc, win_rates = [], [], [], []
    pu_pred, fwd_sign = [], []
    for cut in cutoffs:
        sub = [df.iloc[:cut + 1].copy() for df in contracts]
        scores = score_contracts(sub, use_ic, use_pu)
        # 前瞻收益（切点 -> 切点+hold）
        fwds = []
        for df in contracts:
            c = df["close"].astype(float).to_numpy()
            fwds.append(c[cut + hold] / c[cut] - 1.0)
        fwds = np.array(fwds)
        # RankIC：评分与前瞻收益的秩相关（越高=评分越能预测收益）
        rankics.append(_spearman(scores, fwds))
        # 策略 Sharpe：做多得分前 top_n
        order = np.argsort(scores)[::-1][:top_n]
        strat = fwds[order].mean()
        resid = fwds[order] - strat
        sd = resid.std() + 1e-9
        sharpes.append(strat / sd * math.sqrt(252 / hold))
        # 方向准确率：得分高于中位数 -> 前瞻收益为正的命中率
        med = float(np.median(scores))
        for sc, f in zip(scores, fwds):
            pu_pred.append(sc > med)
            fwd_sign.append(f > 0)
        # 胜率：得分前 top_n 多头中，净成本后为正的占比
        wr = sum(1 for f in fwds[order] if f > 0.0006) / len(order)
        win_rates.append(wr)
    dir_acc = float(np.mean([a == b for a, b in zip(pu_pred, fwd_sign)])) if pu_pred else 0.0
    return dict(rankic=float(np.mean(rankics)),
                sharpe=float(np.mean(sharpes)),
                dir_acc=dir_acc,
                win_rate=float(np.mean(win_rates)))


def compare(seeds: int = 6, n_contracts: int = 30) -> Dict:
    base, enh = [], []
    for s in range(seeds):
        contracts = make_contracts(n_contracts=n_contracts, n_bars=400, seed=s)
        base.append(walk_forward(contracts, use_ic=False, use_pu=False))
        enh.append(walk_forward(contracts, use_ic=True, use_pu=True))
    out = {"baseline": _avg(base), "enhanced": _avg(enh), "n": seeds}
    out["delta"] = {k: out["enhanced"][k] - out["baseline"][k] for k in out["baseline"]}
    return out


def _avg(rows: List[Dict]) -> Dict[str, float]:
    keys = rows[0].keys()
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}


if __name__ == "__main__":
    r = compare(seeds=6)
    print("指标                baseline     enhanced      Δ")
    for k in r["baseline"]:
        b, e, d = r["baseline"][k], r["enhanced"][k], r["delta"][k]
        print(f"{k:18s} {b:+.4f}      {e:+.4f}      {d:+.4f}")
    print(f"\n（walk-forward 平均，{r['n']} 随机种子；"
          "RankIC/方向准确率/胜率/Sharpe 越高越好）")
