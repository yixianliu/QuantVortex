"""自进化回测引擎纯逻辑冒烟测试（无 Qt 依赖）。

验证：随机基因/变异/交叉合法性、单基因回测评估、一代进化 step()、
盈利判定与落盘、latest_signal_for 对 KP预测的信号输出。
运行：
    python tests/e2e/test_auto_evolve_engine.py
"""
from __future__ import annotations

import os
import sys

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


def main() -> None:
    import random
    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.strategy import auto_evolve as ae

    print("=" * 70)
    print("自进化引擎冒烟测试")
    print("=" * 70)

    rng = random.Random(7)

    # 1) 基因操作
    genes = [ae.random_gene(rng) for _ in range(20)]
    for g in genes:
        assert g["entry"] in ae.ENTRY_FACTORS
        if g["entry"] == "ma_cross":
            assert g["params"]["fast"] < g["params"]["slow"]
        d = ae.describe_gene(g)
        assert d and isinstance(d, str)
        sig = ae.gene_signature(g)
        assert len(sig) == 12
    child = ae.crossover(genes[0], genes[1], rng)
    mut = ae.mutate(genes[0], rng)
    assert child["entry"] in ae.ENTRY_FACTORS and mut["entry"] in ae.ENTRY_FACTORS
    print("[1] 基因生成/变异/交叉 OK")

    # 2) 引擎一代进化（缩小种群与区间提速）
    mdm = MarketDataManager(source="synthetic")
    eng = ae.EvolutionEngine(mdm.feed, mdm.universe, period="D", seed=7)
    eng.POP_SIZE = 6
    snap = eng.step()
    assert snap["generation"] == 1
    assert len(snap["ranked"]) >= 4, f"评估结果过少: {len(snap['ranked'])}"
    top = snap["ranked"][0]
    print(f"[2] 第1代进化 OK：{snap['symbol']} 评估 {len(snap['ranked'])} 个，"
          f"最优适应度 {top['fitness']}（{top['desc'][:30]}…）")
    assert snap["best_overall"] is not None
    assert isinstance(snap["profitable_total"], int)

    # 3) 第2代（应继承精英）
    snap2 = eng.step()
    assert snap2["generation"] == 2
    print(f"[3] 第2代进化 OK：最优适应度 {snap2['ranked'][0]['fitness']}")

    # 4) 盈利判定与库
    ok, reasons = ae.is_profitable({"total_return": 0.2, "sharpe": 1.5,
                                    "max_drawdown": 0.1, "win_rate": 0.5,
                                    "num_closing_trades": 20})
    assert ok and not reasons
    ok2, reasons2 = ae.is_profitable({"total_return": -0.1, "sharpe": 0.1,
                                      "max_drawdown": 0.5, "win_rate": 0.2,
                                      "num_closing_trades": 2})
    assert not ok2 and len(reasons2) == 5
    print("[4] 盈利判定 OK")

    # 5) 强制落盘一条并验证 KP预测侧读取
    sym = eng.symbol()
    g = genes[0]
    entry = ae.make_entry(sym, eng.symbol_name(), "D", g,
                          {"total_return": 0.3, "sharpe": 1.2,
                           "max_drawdown": 0.15, "win_rate": 0.45,
                           "num_closing_trades": 15}, 55.0)
    n = ae.save_profitable([entry])
    assert n >= 1
    lib = ae.load_profitable()
    assert any(e["symbol"] == sym for e in lib)
    df = mdm.get_bars(sym, "D", 200)
    sig = ae.latest_signal_for(sym, df)
    assert sig["n"] >= 1 and -1.0 <= sig["bias"] <= 1.0
    print(f"[5] 盈利库落盘+信号读取 OK：库 {n} 条，{sym} 信号偏置 {sig['bias']}")

    print("=" * 70)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()
