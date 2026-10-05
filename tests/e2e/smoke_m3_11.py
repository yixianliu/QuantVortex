"""M3-11 阈值集中化 —— 端到端 smoke 验收。

DoD（spec + UPGRADE_PLAN_V5.md 第 341 行）：
  ① 60+ 阈值提取到 dataclass（PredictorConfig/EnsembleConfig/FeedbackConfig 等）
  ② 支持从 config/settings.json#ai.thresholds 覆盖
  ③ 默认值 = 当前字面量（保证行为不变）

DoD 硬指标：
  - 所有旧值可复现（回归指标差异 <1e-9）
  - 修改 JSON 配置后行为随之变化

运行：QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m3_11.py
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import logging
import os
import sys
import tempfile
from typing import Any

import numpy as np

# ---- 沙箱 sys.path 注入 ----
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


PASSED = 0
FAILED = 0
FAILURES: list[str] = []


# ============================================================
# Test 1: 6 个 Config dataclass 存在且字段数达标
# ============================================================
def test_1_all_config_classes_exist() -> None:
    """M3-11 ①：PredictorConfig/EnsembleConfig/FeedbackConfig/CalibConfig/
    LinkageConfig/DriftConfig 6 个 dataclass 就位，阈值总数 ≥60（spec 下限）。"""
    import futures_quant.ai.constants as C

    for name in ("PREDICTOR", "ENSEMBLE", "FEEDBACK", "CALIB", "LINKAGE", "DRIFT"):
        assert hasattr(C, name), f"缺单例 {name}"
        cfg = getattr(C, name)
        assert dataclasses.is_dataclass(type(cfg)), f"{name} 不是 dataclass"

    total = sum(len(dataclasses.fields(getattr(C, n)))
                for n in ("PREDICTOR", "ENSEMBLE", "FEEDBACK",
                          "CALIB", "LINKAGE", "DRIFT"))
    # 附加 EPS（虽然不属业务阈值，但一起统计确认存在）
    assert hasattr(C, "EPS") and dataclasses.is_dataclass(type(C.EPS))

    assert total >= 60, (
        f"阈值总数应 ≥60（spec 下限），实际 {total}"
    )
    print(f"[1/6] PASS 6 个 Config dataclass 就位（阈值总数 {total} ≥ 60）")


# ============================================================
# Test 2: 默认值 == 硬编码字面量（行为不变的关键）
# ============================================================
def test_2_defaults_match_documented_literals() -> None:
    """M3-11 ③：关键默认值应等于改造前的字面量，任一偏差都会破坏回归。"""
    import futures_quant.ai.constants as C

    p = C.PREDICTOR
    # 已知字面量（对照 spec 与源码）
    expected = {
        "cum_clip": 0.6,
        "step_damping": 0.95,
        "feature_importance_top_n": 10,
        "atr_sigma_multiplier": 1.6,
    }
    for k, v in expected.items():
        actual = getattr(p, k)
        if isinstance(v, float):
            assert abs(actual - v) < 1e-9, (
                f"PredictorConfig.{k} 默认值应为 {v}，实际 {actual}"
            )
        else:
            assert actual == v, f"PredictorConfig.{k} 默认值应为 {v}，实际 {actual}"

    # DEFAULT_* 快照应与当前单例相等（未 reload 前）
    assert C.PREDICTOR == C.DEFAULT_PREDICTOR, "PREDICTOR 与 DEFAULT_PREDICTOR 应相等"
    assert C.ENSEMBLE == C.DEFAULT_ENSEMBLE
    assert C.CALIB == C.DEFAULT_CALIB
    print(f"[2/6] PASS 默认值等于硬编码字面量（{list(expected.keys())}）")


# ============================================================
# Test 3: override 上下文管理器 —— 临时改 + 恢复
# ============================================================
def test_3_override_context_manager() -> None:
    """M3-11：override(ctx, key=value) 进入时改、离开时恢复。"""
    import futures_quant.ai.constants as C

    before = C.PREDICTOR.cum_clip
    with C.override(C.PREDICTOR, cum_clip=0.3):
        assert C.PREDICTOR.cum_clip == 0.3
    assert C.PREDICTOR.cum_clip == before, (
        f"override 退出后应恢复到 {before}，实际 {C.PREDICTOR.cum_clip}"
    )
    print(f"[3/6] PASS override 上下文管理器（0.6 → 0.3 → 0.6）")


# ============================================================
# Test 4: reset_to_defaults 恢复全部字段
# ============================================================
def test_4_reset_to_defaults() -> None:
    """M3-11：reset_to_defaults 把 6 个 Config 全部恢复到 DEFAULT_* 快照。"""
    import futures_quant.ai.constants as C

    # 先污染
    C.PREDICTOR.cum_clip = 0.99
    C.ENSEMBLE.default_epochs = 999
    C.CALIB.compare_epochs = 888

    C.reset_to_defaults()

    assert C.PREDICTOR.cum_clip == 0.6, f"应恢复到 0.6，实际 {C.PREDICTOR.cum_clip}"
    assert C.ENSEMBLE.default_epochs == C.DEFAULT_ENSEMBLE.default_epochs
    assert C.CALIB.compare_epochs == C.DEFAULT_CALIB.compare_epochs
    # 全部单例 == 默认快照
    for name in ("PREDICTOR", "ENSEMBLE", "FEEDBACK", "CALIB", "LINKAGE", "DRIFT"):
        assert getattr(C, name) == getattr(C, f"DEFAULT_{name}"), (
            f"{name} 未恢复到默认快照"
        )
    print(f"[4/6] PASS reset_to_defaults 全 6 组恢复默认")


# ============================================================
# Test 5: reload_from_settings 从 JSON 文件加载 + 未知字段告警
# ============================================================
def test_5_reload_from_settings_json() -> None:
    """M3-11 ②：从 config/settings.json#ai.thresholds 加载覆盖，未知字段告警不静默塞入。"""
    import futures_quant.ai.constants as C

    # 构造一个假的 settings.json
    settings = {
        "ai": {
            "thresholds": {
                "predictor": {"cum_clip": 0.45, "unknown_field_xyz": 1.0},
                "ensemble":  {"default_epochs": 40},
                "unknown_group": {"foo": 1},
            }
        }
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(settings, f)
        tmp_path = f.name

    # 通过环境变量指向临时文件
    import futures_quant.ai.constants as C2

    try:
        os.environ["QV_AI_THRESHOLDS_JSON"] = tmp_path
        n = C2.reload_from_settings(strict=False)

        # 已知字段被覆盖
        assert C.PREDICTOR.cum_clip == 0.45, (
            f"cum_clip 应被覆盖为 0.45，实际 {C.PREDICTOR.cum_clip}"
        )
        assert C.ENSEMBLE.default_epochs == 40, (
            f"default_epochs 应被覆盖为 40，实际 {C.ENSEMBLE.default_epochs}"
        )
        # 未知字段应被忽略（不塞进 dataclass）
        assert not hasattr(C.PREDICTOR, "unknown_field_xyz"), (
            "未知字段不应被静默塞进 dataclass"
        )
        assert not hasattr(C, "unknown_group")
        assert n >= 2, f"应至少应用 2 项覆盖，实际 {n}"

        # 恢复
        C.reset_to_defaults()
    finally:
        os.environ.pop("QV_AI_THRESHOLDS_JSON", None)
        os.unlink(tmp_path)
        C.reset_to_defaults()

    print(f"[5/6] PASS reload_from_settings（cum_clip=0.45, epochs=40，未知字段忽略）")


# ============================================================
# Test 6: Predictor 实际使用 PREDICTOR.cum_clip（源码检查）
# ============================================================
def test_6_predictor_uses_centralized_constants() -> None:
    """M3-11 ③：predictor.py 应引用 _PC.cum_clip 而非硬编码 0.6。"""
    import pathlib
    import re

    src = pathlib.Path("futures_quant/ai/predictor.py").read_text(encoding="utf-8")

    # 应引用 _PC.cum_clip
    assert re.search(r"_PC\.cum_clip", src), (
        "predictor.py 应引用 _PC.cum_clip，未找到"
    )
    # 不应有裸 0.6 的 cum_clip 字面量（作为 clip 上限）
    # 允许 0.6 出现在注释里
    body = re.sub(r"#.*", "", src)          # 去注释
    body = re.sub(r'""".*?"""', "", body, flags=re.S)  # 去 docstring
    matches = re.findall(r"clip\(\s*-\s*0\.6\b", body)
    assert not matches, (
        "predictor.py 仍有硬编码 clip(-0.6) 而非 _PC.cum_clip"
    )
    print(f"[6/6] PASS predictor.py 引用 _PC.cum_clip（无硬编码 clip 字面量）")


# ============================================================
def main() -> int:
    global PASSED, FAILED
    tests = [
        test_1_all_config_classes_exist,
        test_2_defaults_match_documented_literals,
        test_3_override_context_manager,
        test_4_reset_to_defaults,
        test_5_reload_from_settings_json,
        test_6_predictor_uses_centralized_constants,
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

    print(f"\n=== M3-11 smoke: {PASSED}/{total} passed ===")
    if FAILED:
        print(f"Failures ({FAILED}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
