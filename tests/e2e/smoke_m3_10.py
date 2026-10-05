"""M3-10 模型卡片（Model Card）与状态透明化 —— 端到端 smoke 验收。

DoD（spec + UPGRADE_PLAN_V5.md 第 340 行）：
  ① 定义 ModelCard{name, enabled, is_stub, train_range, n_samples, metrics, known_limits}
  ② 为每个模型生成卡片（lstm_numpy / ridge / ensemble / tcn / transformer / garch / ppo）
  ③ 预测页新增「模型状态」小面板

DoD 硬指标：
  - 面板正确显示「TCN：占位实现（未训练）」
  - 装上/卸下 torch 时状态实时更新

运行：QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_10.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

# ---- 沙箱 sys.path 注入 ----
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd


PASSED = 0
FAILED = 0
FAILURES: list[str] = []


# ============================================================
# Test 1: ModelCard dataclass 契约 —— 字段齐全 + status_text 语义
# ============================================================
def test_1_model_card_dataclass_contract() -> None:
    """M3-10 ①：ModelCard 包含 spec 要求的 7 字段 + 2 扩展字段（backend/trained）。"""
    from futures_quant.ai.model_card import ModelCard

    c = ModelCard(
        name="foo",
        enabled=True,
        is_stub=True,
        train_range="2024-01-01 ~ 2024-12-31",
        n_samples=100,
        metrics={"mae": 0.01},
        known_limits=["限制 1"],
    )
    # spec 要求字段全部存在
    for attr in ("name", "enabled", "is_stub", "train_range",
                 "n_samples", "metrics", "known_limits"):
        assert hasattr(c, attr), f"ModelCard 缺字段 {attr}"
    # 扩展字段
    assert hasattr(c, "backend") and c.backend == "none"
    assert hasattr(c, "trained") and c.trained is False
    # display 未给时应 fallback 到 name
    assert c.display == ""
    assert c.label == "foo"
    # is_stub + 未训练 → 状态为「占位实现（未训练）」
    assert c.status_text() == "占位实现（未训练）", f"实际 {c.status_text()!r}"
    # to_dict 应包含全部关键字段
    d = c.to_dict()
    for k in ("name", "display", "enabled", "is_stub", "trained",
              "backend", "train_range", "n_samples", "metrics",
              "known_limits", "status"):
        assert k in d, f"to_dict 缺字段 {k}"
    print(f"[1/6] PASS ModelCard 契约（字段 7+2、is_stub → 占位实现（未训练））")


# ============================================================
# Test 2: collect_model_cards 返回 8 张卡片（spec 7 + 扩展 gbm）
# ============================================================
def test_2_collect_returns_8_cards() -> None:
    """M3-10 ②：collect_model_cards 覆盖 lstm_numpy/ridge/ensemble/tcn/transformer/garch/ppo + gbm。"""
    from futures_quant.ai.model_card import collect_model_cards

    cards = collect_model_cards()
    names = {c.name for c in cards}
    expected = {"lstm_numpy", "ridge", "ensemble", "tcn", "gbm",
                "transformer", "garch", "ppo"}
    missing = expected - names
    assert not missing, f"缺卡片 {missing}，实际 {names}"
    assert len(cards) == 8, f"应返回 8 张卡片（spec 7 + gbm），实际 {len(cards)}"
    print(f"[2/6] PASS collect 返回 8 张卡片（{sorted(names)}）")


# ============================================================
# Test 3: TCN 显示「占位实现（未训练）」 —— DoD 硬指标
# ============================================================
def test_3_tcn_shows_placeholder() -> None:
    """M3-10 DoD：TCN 应显示「占位实现（未训练）」—— 因为 M3-06 只训练读出层，
    卷积权重是随机固定的，非端到端训练。"""
    from futures_quant.ai.model_card import collect_model_cards

    cards = collect_model_cards()
    tcn = next(c for c in cards if c.name == "tcn")

    # is_stub 必须是 True（非端到端训练）
    assert tcn.is_stub is True, (
        f"TCN 应标 is_stub=True（卷积权重随机固定），实际 {tcn.is_stub}"
    )
    # 未启用未训练时，status_text 应为「占位实现（未训练）」
    assert tcn.enabled is False, f"未传 external_model 时 TCN 应未启用，实际 {tcn.enabled}"
    assert tcn.trained is False
    status = tcn.status_text()
    assert status == "占位实现（未训练）", (
        f"TCN status 应为「占位实现（未训练）」，实际 {status!r}"
    )
    # known_limits 应提到非端到端 / 随机特征
    limits = " ".join(tcn.known_limits)
    assert ("非端到端" in limits) or ("随机" in limits), (
        f"TCN known_limits 应提非端到端/随机特征，实际 {tcn.known_limits}"
    )
    print(f"[3/6] PASS TCN：{tcn.label} → {status}（is_stub=True）")


# ============================================================
# Test 4: probe_module 实时探测 torch —— 装上/卸下状态实时更新
# ============================================================
def test_4_probe_module_realtime() -> None:
    """M3-10 DoD：装上/卸下 torch 时状态实时更新（probe_module 每次重新探测）。"""
    import futures_quant.ai.model_card as mc

    # monkeypatch probe_module，第一次返回 False，第二次返回 True
    orig = mc.probe_module
    state = {"value": False}

    def fake_probe(name):
        return state["value"]

    mc.probe_module = fake_probe
    try:
        # 无 torch 场景
        state["value"] = False
        cards_no_torch = mc.collect_model_cards()
        transformer_no_torch = next(c for c in cards_no_torch if c.name == "transformer")
        ppo_no_torch = next(c for c in cards_no_torch if c.name == "ppo")
        assert transformer_no_torch.is_stub is True, "无 torch 时 transformer 应 is_stub"
        assert ppo_no_torch.is_stub is True, "无 torch 时 ppo 应 is_stub"
        assert transformer_no_torch.backend == "none"

        # 「装上 torch」后重新采集，应实时反映
        state["value"] = True
        cards_torch = mc.collect_model_cards()
        transformer_torch = next(c for c in cards_torch if c.name == "transformer")
        ppo_torch = next(c for c in cards_torch if c.name == "ppo")
        assert transformer_torch.is_stub is False, "有 torch 时 transformer 不应 is_stub"
        assert ppo_torch.is_stub is False, "有 torch 时 ppo 不应 is_stub"
        assert transformer_torch.backend == "torch"
    finally:
        mc.probe_module = orig

    # 真实 probe_module 对不存在模块返回 False
    assert orig("totally_nonexistent_package_xyz") is False
    # 真实 probe_module 对 numpy 返回 True
    assert orig("numpy") is True
    print(f"[4/6] PASS probe_module 实时探测（无 torch → stub / 有 torch → 正常）")


# ============================================================
# Test 5: predictor + df 传入后 train_range/n_samples/metrics 正确填充
# ============================================================
def test_5_predictor_and_df_fill_metadata() -> None:
    """M3-10 ③：传入 predictor 与 df 后，卡片反映真实训练区间、样本量与指标。"""
    from futures_quant.ai.model_card import collect_model_cards

    # 构造一个模拟 FuturesPredictor（用 SimpleNamespace 避免真训练）
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    import numpy as np
    df = pd.DataFrame({"close": 100.0 + np.arange(50)}, index=idx)

    predictor = SimpleNamespace(
        trained=True,
        use_lstm=True,
        use_ensemble=False,
        ensemble=None,
        resid_std=0.05,
        calib_beta=0.95,
        skill=0.3,
        validated=True,
    )

    cards = collect_model_cards(predictor=predictor, df=df)
    lstm = next(c for c in cards if c.name == "lstm_numpy")

    assert lstm.train_range is not None, "应填充 train_range"
    assert lstm.n_samples == 50, f"n_samples 应=50，实际 {lstm.n_samples}"
    assert lstm.trained is True
    # metrics 应包含 resid_std / calib_beta / skill / validated
    for k in ("resid_std", "calib_beta", "skill", "validated"):
        assert k in lstm.metrics, f"metrics 缺 {k}：{lstm.metrics}"
    print(f"[5/6] PASS predictor/df 元信息填充（train_range={lstm.train_range}, "
          f"n={lstm.n_samples}, metrics={lstm.metrics}）")


# ============================================================
# Test 6: format_cards_text + cards_to_rows 渲染正确
# ============================================================
def test_6_format_and_rows() -> None:
    """M3-10 ③：format_cards_text / cards_to_rows 产出可读的文本与表格。"""
    from futures_quant.ai.model_card import (collect_model_cards,
                                              format_cards_text, cards_to_rows,
                                              COLUMNS)

    cards = collect_model_cards()
    text = format_cards_text(cards)
    assert "占位实现（未训练）" in text, "文本渲染应含 TCN 占位状态"
    assert "LSTM" in text, "文本渲染应含 LSTM 模型名"
    assert "TCN" in text, "文本渲染应含 TCN 模型名"
    # 表格列
    rows = cards_to_rows(cards)
    assert len(rows) == len(cards), f"行数应等于卡片数：{len(rows)} vs {len(cards)}"
    for r in rows:
        assert len(r) == len(COLUMNS), f"每行 {len(r)} 列，应等于 {len(COLUMNS)}"
    # COLUMNS 列序
    assert COLUMNS == ["模型", "状态", "启用", "后端", "训练区间", "样本量", "已知局限"], (
        f"COLUMNS 列序不符：{COLUMNS}"
    )
    print(f"[6/6] PASS 渲染（文本含占位状态、{len(rows)} 行 × {len(COLUMNS)} 列）")


# ============================================================
def main() -> int:
    global PASSED, FAILED
    tests = [
        test_1_model_card_dataclass_contract,
        test_2_collect_returns_8_cards,
        test_3_tcn_shows_placeholder,
        test_4_probe_module_realtime,
        test_5_predictor_and_df_fill_metadata,
        test_6_format_and_rows,
    ]
    total = len(tests)
    for t in tests:
        try:
            t()
            PASSED += 1
        except Exception as e:
            FAILED += 1
            FAILURES.append(f"{t.__name__}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")

    print(f"\n=== M3-10 smoke: {PASSED}/{total} passed ===")
    if FAILED:
        print(f"Failures ({FAILED}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
