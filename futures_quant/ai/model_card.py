"""模型卡片（Model Card）与状态透明化（M3-10）。

目标：让使用者**一眼知道当前到底在跑哪个模型、是否降级、是不是占位实现**。

背景：项目里同时存在 numpy 自实现、第三方库实现与若干"接口齐全但没真训练"的
占位模型（TCN 只训练读出层、TS-Transformer 无 torch 时恒返回 0、PPO 无 torch 时是
玩具策略、GARCH 无 arch 时是固定系数 EWMA）。旧代码对此完全没有显式表达，
UI 上所有模型看起来都一样可用 —— 这是典型的「能力幻觉」。

设计：
    ModelCard{name, enabled, is_stub, train_range, n_samples, metrics, known_limits}
    + 两个扩展字段：backend（实际后端）/ trained（本会话是否已训练）

- `is_stub=True` 表示**实现不完整**（非端到端训练 / 恒值输出 / 玩具实现），
  UI 必须标灰并注明「占位实现」；
- 可用性探测**每次实时执行**（`probe_module`），装/卸 torch、arch 后状态即时变化，
  而不是沿用 import 期缓存的开关。

用法：
    from futures_quant.ai.model_card import collect_model_cards, format_cards_text
    cards = collect_model_cards(predictor=P, df=df)
"""
from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["ModelCard", "probe_module", "collect_model_cards",
           "format_cards_text", "cards_to_rows"]


def probe_module(name: str) -> bool:
    """实时探测某个可选依赖是否可用（不真正导入，避免拉起重型依赖）。

    与模块级 `try: import xxx` 的区别：后者在 import 期一次性固化，装/卸依赖后
    不会变化；这里每次调用都重新探测，满足「装上/卸下 torch 时状态实时更新」。
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@dataclass
class ModelCard:
    """单个模型的「身份证」。

    Attributes:
        name: 模型标识（如 "lstm_numpy"）。
        enabled: 当前是否参与预测（False = 存在但未启用）。
        is_stub: 实现是否**不完整**（占位/恒值/玩具/非端到端）。
        train_range: 训练区间文本（"起 ~ 止"），未训练为 None。
        n_samples: 训练样本量。
        metrics: 关键指标（MAE / 技能度 / 校准系数 …）。
        known_limits: 已知局限的人类可读列表。
        backend: 实际后端（"numpy" / "torch" / "sklearn" / "arch" / "none"）。
        trained: 本会话中该模型实例是否已被训练过。
        display: 中文显示名。
    """

    name: str
    enabled: bool = False
    is_stub: bool = False
    train_range: Optional[str] = None
    n_samples: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)
    known_limits: List[str] = field(default_factory=list)
    backend: str = "none"
    trained: bool = False
    display: str = ""

    @property
    def label(self) -> str:
        """处理label。"""
        return self.display or self.name

    def status_text(self) -> str:
        """面板上显示的「状态」文本。

        占位实现（is_stub）优先暴露「占位」属性 —— 无论是否启用，都不该让它
        看起来像个正常模型（对应验收：TCN 显示为「占位实现（未训练）」）。
        """
        if self.is_stub:
            return "占位实现（未训练）" if not self.trained else "占位实现（部分已训练）"
        if not self.enabled:
            return "未启用"
        return "已训练" if self.trained else "未训练"

    def to_dict(self) -> Dict[str, Any]:
        """处理todict。"""
        return {
            "name": self.name,
            "display": self.label,
            "enabled": self.enabled,
            "is_stub": self.is_stub,
            "trained": self.trained,
            "backend": self.backend,
            "train_range": self.train_range,
            "n_samples": self.n_samples,
            "metrics": dict(self.metrics),
            "known_limits": list(self.known_limits),
            "status": self.status_text(),
        }


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------

def _range_of(df: Optional[pd.DataFrame]) -> Optional[str]:
    if df is None or len(df) == 0:
        return None
    try:
        return f"{df.index[0]} ~ {df.index[-1]}"
    except Exception:  # noqa: BLE001
        return None


def _metrics_of(predictor: Any) -> Dict[str, Any]:
    if predictor is None:
        return {}
    out: Dict[str, Any] = {}
    for key in ("resid_std", "calib_beta", "skill", "validated"):
        v = getattr(predictor, key, None)
        if v is None:
            continue
        try:
            out[key] = round(float(v), 6) if isinstance(v, (int, float, np.floating)) else v
        except Exception:  # noqa: BLE001
            continue
    return out


def collect_model_cards(predictor: Any = None,
                        df: Optional[pd.DataFrame] = None,
                        external_model: Any = None) -> List[ModelCard]:
    """采集全部模型的卡片。

    【文档偏差 · 已注明假设】UPGRADE_PLAN_V5 M3-10 列出的模型为 7 个
    （lstm_numpy / ridge / ensemble / tcn / transformer / garch / ppo）。
    本实现**额外生成一张 `gbm` 卡片**，理由：M3-06 已把 GBM 实装为可用的外部
    主模型通道（`calibration_replay.build_external_estimator` 可选 "gbm"），
    若不给它卡片，UI 会出现「能选但没有状态」的盲区 —— 与本节「状态透明化」
    目标相悖。此处按「宁可多列、不可漏列」处理，如需严格对齐 7 个请删除
    `gbm` 段落。

    参数:
        predictor: 可选的 `FuturesPredictor` 实例（用于 enabled / metrics）。
        df: 训练用数据（用于 train_range / n_samples）。
        external_model: 当前生效的外部主模型（TCN / GBM / Transformer 适配器）。
    """
    have_torch = probe_module("torch")
    have_sklearn = probe_module("sklearn")
    have_arch = probe_module("arch")

    rng = _range_of(df)
    n = int(len(df)) if df is not None else 0
    mets = _metrics_of(predictor)
    trained = bool(getattr(predictor, "trained", False))
    use_lstm = bool(getattr(predictor, "use_lstm", True))
    use_ens = bool(getattr(predictor, "use_ensemble", False))
    ens = getattr(predictor, "ensemble", None)
    ens_fitted = bool(ens is not None and getattr(ens, "fitted", False))
    ext_name = type(external_model).__name__ if external_model is not None else None

    cards: List[ModelCard] = []

    # ---- 主模型：numpy / torch LSTM ----
    cards.append(ModelCard(
        name="lstm_numpy",
        display="LSTM（时序主模型）",
        enabled=bool(trained and use_lstm and ext_name is None),
        is_stub=False,
        train_range=rng,
        n_samples=n,
        metrics=mets,
        known_limits=(
            ["无 torch 时走纯 numpy 实现，训练速度较慢、容量较小"]
            if not have_torch else
            ["torch 版本需与打包环境 ABI 一致，否则会自动回退 numpy"]
        ),
        backend="torch" if have_torch else "numpy",
        trained=trained and use_lstm,
    ))

    # ---- 回退模型：岭回归 ----
    cards.append(ModelCard(
        name="ridge",
        display="岭回归（LSTM 回退）",
        enabled=bool(trained and not use_lstm),
        is_stub=False,
        train_range=rng,
        n_samples=n,
        metrics={},
        known_limits=["线性模型，无法刻画特征间非线性交互",
                      "输入为展平时间窗口，序列位置信息被弱化"],
        backend="numpy",
        trained=bool(trained and not use_lstm),
    ))

    # ---- 多周期集成 ----
    ens_limits: List[str] = ["每周期两套特征（基础 7 + 扩展）按验证 MAE 反比加权"]
    if not have_sklearn:
        ens_limits.append("未装 sklearn：树模型基学习器缺失，集成退化为 LSTM 成员")
    cards.append(ModelCard(
        name="ensemble",
        display="多周期集成",
        enabled=bool(use_ens and ens_fitted),
        is_stub=False,
        train_range=rng,
        n_samples=n,
        metrics={"ensemble_resid": round(float(getattr(ens, "ensemble_resid", 0.0) or 0.0), 6)}
        if ens is not None else {},
        known_limits=ens_limits,
        backend="sklearn+numpy" if have_sklearn else "numpy",
        trained=ens_fitted,
    ))

    # ---- TCN（M3-06：只训练读出层，卷积为随机固定特征）----
    tcn_enabled = ext_name == "_TCNEstimator"
    tcn_trained = bool(tcn_enabled and getattr(external_model, "net", None) is not None
                       and getattr(getattr(external_model, "net"), "fitted", False))
    cards.append(ModelCard(
        name="tcn",
        display="TCN（因果膨胀卷积）",
        enabled=tcn_enabled,
        is_stub=True,          # 卷积权重随机固定，仅训练线性读出层
        train_range=rng if tcn_trained else None,
        n_samples=n if tcn_trained else 0,
        metrics={},
        known_limits=[
            "非端到端训练：因果膨胀卷积权重为随机固定特征，只训练线性读出层",
            "随机特征的表达上限取决于通道数与随机种子",
        ],
        backend="numpy",
        trained=tcn_trained,
    ))

    # ---- GBM / 提升树 ----
    gbm_enabled = ext_name == "_GBMEstimator"
    cards.append(ModelCard(
        name="gbm",
        display="GBM（梯度提升树）",
        enabled=gbm_enabled,
        is_stub=not have_sklearn,
        train_range=rng if gbm_enabled else None,
        n_samples=n if gbm_enabled else 0,
        metrics={},
        known_limits=(["未装 xgboost / lightgbm：走玩具实现，仅 1 层阈值分裂"]
                      if not (probe_module("xgboost") or probe_module("lightgbm"))
                      else ["树模型不吃时序结构，输入按窗口展平"]),
        backend="xgboost/lightgbm" if (probe_module("xgboost")
                                       or probe_module("lightgbm")) else "numpy(玩具)",
        trained=gbm_enabled,
    ))

    # ---- TS-Transformer ----
    transformer_enabled = ext_name == "_TSTransformerEstimator"
    cards.append(ModelCard(
        name="transformer",
        display="TS-Transformer",
        enabled=transformer_enabled and have_torch,
        is_stub=not have_torch,     # 无 torch 时 predict 恒返回 0
        train_range=rng if transformer_enabled else None,
        n_samples=n if transformer_enabled else 0,
        metrics={},
        known_limits=(["未安装 torch：前向直接返回 0，**不参与任何预测**"]
                      if not have_torch else
                      ["训练成本显著高于 LSTM，小样本易过拟合"]),
        backend="torch" if have_torch else "none",
        trained=transformer_enabled and have_torch,
    ))

    # ---- GARCH（波动率）----
    cards.append(ModelCard(
        name="garch",
        display="GARCH(1,1)（波动率）",
        enabled=False,               # 尚未接入预测主链路，仅作波动率工具
        is_stub=not have_arch,
        train_range=None,
        n_samples=0,
        metrics={},
        known_limits=(["未安装 arch：用固定系数 (α=0.1, β=0.8) 的 EWMA 近似，非 MLE 拟合"]
                      if not have_arch else
                      ["未接入预测主链路，当前仅作波动率估计工具"]),
        backend="arch" if have_arch else "numpy(EWMA)",
        trained=False,
    ))

    # ---- PPO（强化学习）----
    cards.append(ModelCard(
        name="ppo",
        display="PPO（强化学习仓位）",
        enabled=False,
        is_stub=not have_torch,
        train_range=None,
        n_samples=0,
        metrics={},
        known_limits=(["未安装 torch：退化为 numpy 玩具策略（REINFORCE + 基线）"]
                      if not have_torch else
                      ["需 1 万步以上训练才有意义，且未接入预测主链路"]),
        backend="torch" if have_torch else "numpy(玩具)",
        trained=False,
    ))

    return cards


def format_cards_text(cards: List[ModelCard]) -> str:
    """把卡片渲染成纯文本（日志 / 只读文本框 / 测试断言用）。"""
    lines: List[str] = []
    for c in cards:
        lines.append(f"{c.label}：{c.status_text()}　[{c.backend}]")
        if c.train_range:
            lines.append(f"    训练区间：{c.train_range}　样本量：{c.n_samples}")
        if c.metrics:
            mets = "，".join(f"{k}={v}" for k, v in c.metrics.items())
            lines.append(f"    指标：{mets}")
        for lim in c.known_limits:
            lines.append(f"    局限：{lim}")
    return "\n".join(lines)


COLUMNS = ["模型", "状态", "启用", "后端", "训练区间", "样本量", "已知局限"]


def cards_to_rows(cards: List[ModelCard]) -> List[List[str]]:
    """渲染成表格行（列序见 `COLUMNS`）。"""
    rows: List[List[str]] = []
    for c in cards:
        rows.append([
            c.label,
            c.status_text(),
            "是" if c.enabled else "否",
            c.backend,
            c.train_range or "—",
            str(c.n_samples) if c.n_samples else "—",
            "；".join(c.known_limits) or "—",
        ])
    return rows
