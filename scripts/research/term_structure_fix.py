"""第五轮第 1 步：零成本数据质量修复后重跑（流动性过滤 + 换月复权）。

对同一批已缓存合约做 6 组对照，回答「rb 的 carry_ann 负相关是否还存在」：

    none   / main    修复前基线（最早到期即近月；标签用本地主力连续）
    loose  / main    仅加松流动性过滤（日成交≥1000 手 或 持仓≥1 万手）
    strict / main    仅加严流动性过滤（日成交≥2000 手 且 持仓≥2 万手）
    none   / rolled  仅换月复权（近月链比例复权后算标签）
    loose  / rolled  松过滤 + 复权
    strict / rolled  严过滤 + 复权

约束：不联网（全部命中第 4 轮缓存）、不装包、不改版本号、不动 ui/ 与数据库。
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PROJ_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import term_structure_research as ts  # noqa: E402

OUT_JSON = os.path.join(ts.OUT_DIR, "phase5_term_fix_results.json")

CONFIGS = [
    ("none", "main"), ("loose", "main"), ("strict", "main"),
    ("none", "rolled"), ("loose", "rolled"), ("strict", "rolled"),
]


def _eval_config(liq: str, label_mode: str) -> dict:
    """单组配置的完整样本外评估：IC + 横截面 IC + 组合毛/净。"""
    panel, coverage, _ = ts._assemble(liq=liq, label_mode=label_mode)
    if panel.empty:
        return {"config": f"{liq}/{label_mode}", "ok": False}
    te = panel[(panel.index >= ts.TEST_START) & (panel.index <= ts.TEST_END)]
    va = panel[(panel.index >= ts.VAL_START) & (panel.index <= ts.VAL_END)]

    # 方向与变体只在验证段选：方向按「验证段横截面 IC(fwd5)」定，因为组合交易的是
    # 同日横截面相对强弱（carry_z 的秩），不是单品种时序方向
    val_ics = {s: ts._ic_series(g, "carry_z", "fwd5") for s, g in va.groupby("symbol")}
    finite = [v for v in val_ics.values() if np.isfinite(v)]
    mean_val_ic = float(np.nanmean(finite)) if finite else 0.0
    val_cs = ts._cross_section_ic(va, "carry_z")["fwd5"]["mean_ic"]
    direction = 1.0 if (np.isfinite(val_cs) and val_cs >= 0) else -1.0
    variants = {
        "raw": {"direction": direction, "smooth": 1, "thr": 0.0, "hold": 1},
        "smooth5": {"direction": direction, "smooth": 5, "thr": 0.0, "hold": 1},
        "thresh03": {"direction": direction, "smooth": 1, "thr": 0.3, "hold": 1},
        "hold5": {"direction": direction, "smooth": 1, "thr": 0.0, "hold": 5},
        "hold10": {"direction": direction, "smooth": 1, "thr": 0.0, "hold": 10},
        "dem_hold5": {"direction": direction, "smooth": 1, "thr": 0.0, "hold": 5,
                      "demean": True},
        "dem_raw": {"direction": direction, "smooth": 1, "thr": 0.0, "hold": 1,
                    "demean": True},
    }
    val_scores = {k: ts._portfolio(va, "carry_z", **cfg) for k, cfg in variants.items()}
    best = max(val_scores, key=lambda k: val_scores[k]["sharpe_net"])
    pf = ts._portfolio(te, "carry_z", **variants[best])
    per_sym = ts._per_symbol_net(te, "carry_z", **variants[best])

    return {
        "config": f"{liq}/{label_mode}",
        "liq": liq,
        "label_mode": label_mode,
        "ok": True,
        "coverage": coverage,
        "split_rows": {
            "train": int(((panel.index >= ts.TRAIN_START) & (panel.index <= ts.TRAIN_END)).sum()),
            "validation": int(len(va)),
            "test": int(len(te)),
            "test_dates": int(te.index.nunique()),
        },
        "ic_time_series": ts._per_symbol_ics(te, "carry_ann"),
        "cross_section_ic": ts._cross_section_ic(te, "carry_z"),
        "selection": {"val_mean_ic_fwd1": round(mean_val_ic, 4), "direction": direction,
                      "chosen_variant": best,
                      "val_net_sharpe": {k: v["sharpe_net"] for k, v in val_scores.items()}},
        "portfolio": pf,
        "per_symbol_net": {k: v.get("sharpe") for k, v in per_sym.items()},
        "yearly_ic_fwd5": {y: {s: round(ts._ic_series(g, "carry_ann", "fwd5"), 4)
                               for s, g in gg.groupby("symbol")}
                           for y, gg in te.groupby(te.index.year)},
    }


def main() -> int:
    t0 = time.time()
    out = {"meta": {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "seed": ts.SEED,
                    "data_version": ts._fingerprint()["data_version"],
                    "configs": [f"{a}/{b}" for a, b in CONFIGS],
                    "liq_thresholds": ts.LIQ_MODES,
                    "label_mode_note": "rolled=近月链比例复权（新合约当日收盘/旧合约前日收盘链接收益）"},
           "results": []}
    for liq, label_mode in CONFIGS:
        r = _eval_config(liq, label_mode)
        out["results"].append(r)
        if not r.get("ok"):
            print(f"[{liq}/{label_mode}] 无数据")
            continue
        ic = r["ic_time_series"]
        cs = r["cross_section_ic"]["fwd5"]
        print(f"[{liq}/{label_mode}] 样本 {r['split_rows']['test']}，"
              f"IC(fwd5) rb={ic['rb']['ic_fwd5']} i={ic['i']['ic_fwd5']} cu={ic['cu']['ic_fwd5']}，"
              f"横截面 IC={cs['mean_ic']} p={cs['p_value']}，"
              f"毛夏普 {r['portfolio']['sharpe_gross']} 净夏普 {r['portfolio']['sharpe_net']}")

    # 停用标记：修复后符号是否仍翻转
    flipped = {}
    for r in out["results"]:
        if not r.get("ok"):
            continue
        signs = [r["ic_time_series"][s]["ic_fwd5"] for s in ("rb", "i", "cu")]
        signs = [s for s in signs if np.isfinite(s)]
        flipped[r["config"]] = len({1 if s > 0 else -1 for s in signs}) > 1
    out["conclusion"] = {
        "sign_flip_by_config": flipped,
        "any_config_without_flip": any(not v for v in flipped.values()),
    }
    os.makedirs(ts.OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, default=str)
    print(f"\n结论: 符号仍翻转的配置 {[k for k, v in flipped.items() if v]}")
    print(f"耗时 {time.time() - t0:.1f}s -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
