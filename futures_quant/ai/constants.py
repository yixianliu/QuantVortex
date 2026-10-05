"""AI 层阈值集中化（M3-11）。

背景（UPGRADE_PLAN_V5 §5.2-C14）：原先有 60+ 个「策略阈值 / 权重 / 切分比例 /
归一化基准」以魔法数字形式散落在 `predictor.py`、`ensemble.py`、`feedback.py`、
`linkage_bus.py`、`calibration_replay.py` 五个文件里，且同一数值在不同位置
**语义常常不同**（例如 `0.8` 既是 fit 的三段切分点，又是 evaluate 的 80/20 切分；
`60` 既是 Walk-Forward 最小样本，也是回撤滚动窗口，还是回放起始下界）。
要调参就得翻源码、改一处漏一处，且无法做 A/B。

本模块把这些数值集中到几个 dataclass 里：

    PredictorConfig    预测器（训练切分 / 校准 / 融合 / 风险评分 / 多空）
    EnsembleConfig     多周期集成（岭回归 / GBM / LSTM 成员 / 加权）
    FeedbackConfig     反馈闭环（结算 / 校准 / 自适应配置 / 再训练触发）
    CalibConfig        离线回放与多模型对比
    LinkageConfig      预测↔回测联动画像
    DriftConfig        模型漂移检测（M3-13）
    EpsConfig + EPS_*  数值稳定性常数（**不是**策略阈值，单独归类）

设计约定：
1. **默认值 == 改造前的字面量**，逐一核对，保证行为完全不变（回归指标差 <1e-9）；
2. **同值不同义必须拆成不同字段**：`PredictorConfig.default_seq_len=30` 与
   `EnsembleConfig.default_seq_len=20` 刻意不统一；`risk_dist_full=0.02`（价位距离
   基准）与 `risk_free_annual=0.02`（无风险利率）也各自独立，禁止合并；
3. 运行期可在 `config/settings.json` 用 `ai.thresholds.<组>.<字段>` 覆盖，
   例如::

       {"ai": {"thresholds": {"predictor": {"cum_clip": 0.45},
                              "ensemble":  {"default_epochs": 40}}}}

   也可用环境变量 `QV_AI_THRESHOLDS_JSON` 指向一份 JSON 文件（便于 A/B 与测试）。
   未知字段会被**忽略并告警**，不会静默塞进 dataclass。

用法：
    from .constants import PREDICTOR, ENSEMBLE, reload_from_settings
    cum = max(-PREDICTOR.cum_clip, min(PREDICTOR.cum_clip, cum))

    # 单测 / A/B 场景
    with override(PREDICTOR, cum_clip=0.3):
        ...
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
import threading
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "EpsConfig", "PredictorConfig", "EnsembleConfig", "FeedbackConfig",
    "CalibConfig", "LinkageConfig", "DriftConfig",
    "EPS", "PREDICTOR", "ENSEMBLE", "FEEDBACK", "CALIB", "LINKAGE", "DRIFT",
    "DEFAULT_PREDICTOR", "DEFAULT_ENSEMBLE", "DEFAULT_FEEDBACK",
    "DEFAULT_CALIB", "DEFAULT_LINKAGE", "DEFAULT_DRIFT",
    "reload_from_settings", "reset_to_defaults", "override",
    "THRESHOLDS_SECTION",
]

# settings.json 中的路径：ai.thresholds.<组名>.<字段名>
THRESHOLDS_SECTION = "thresholds"

_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# 数值稳定性常数（与策略阈值严格分离：这些不该被业务调参）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EpsConfig:
    """除零保护与默认兜底值。

    这些量的量纲是「数值稳定性」，不是策略强度；单独放一个 frozen dataclass，
    避免被当成可调旋钮误改（改 `eps_div` 只会掩盖 bug，不会改进策略）。
    """

    eps_div: float = 1e-12            # 除法 / 指标分母的除零保护
    eps_std: float = 1e-8             # 标准化（z-score）分母下限
    eps_resid: float = 1e-6           # 残差标准差下限
    eps_fitness: float = 1e-6         # 联动 fitness 比值 / 加权的除零保护
    default_resid_std: float = 1e-4   # 未训练时残差 σ 的先验兜底


EPS = EpsConfig()


# ---------------------------------------------------------------------------
# 预测器
# ---------------------------------------------------------------------------
@dataclass
class PredictorConfig:
    """`FuturesPredictor` 的全部可调阈值。

    默认值逐项取自改造前的字面量，未做任何行为改动。
    """

    # ---- Walk-Forward 折叠规划（M3-05）----
    wf_min_folds: int = 3            # 达不到该折数就回退固定 80/20
    wf_min_samples: int = 60         # 启用 WF 的最小样本量
    wf_train_ratio: float = 0.5      # 训练段占比
    wf_min_train_len: int = 20       # 训练段最小长度
    wf_min_test_len: int = 3         # 单折测试段最小长度

    # ---- Mincer-Zarnowitz 校准 ----
    mz_min_samples: int = 8          # 校准回归所需最小样本
    mz_beta_max: float = 1.5         # beta 上限（负相关一律视作无技能）

    # ---- 模型结构 / 超参 ----
    default_seq_len: int = 30        # 实例默认窗口（与 ensemble 的 20 不同源，勿统一）
    lstm_hidden_size: int = 64
    lstm_lr: float = 0.001
    step_damping: float = 0.95       # 多步递归外推的逐步阻尼
    random_seed: int = 7

    # ---- 训练三段切分 ----
    fit_min_samples: int = 20        # 有效序列数下限
    train_split_ratio: float = 0.6   # 前 60% 训练
    calib_split_ratio: float = 0.8   # 末 20% 校准（切分点取 0.8）
    min_train_seg: int = 20
    min_val_seg: int = 8
    min_calib_seg: int = 8

    # ---- 未验证时的保守处理 ----
    unvalidated_resid_inflate: float = 1.5   # 样本内残差的经验放大
    unvalidated_beta: float = 0.5            # 预测幅度一律先收缩一半
    ensemble_min_extra_bars: int = 30        # 启用集成所需额外 K 线

    # ---- 外推与波动 ----
    cum_clip: float = 0.6            # 累计对数收益 / 收益率截断 ±60%
    vol_ema_decay: float = 0.9       # 波动 EMA 惯性权重
    vol_ema_alpha: float = 0.1       # 波动 EMA 新息权重（= 1 - decay）

    # ---- 资讯融合 ----
    news_bias_steepness: float = 1.5
    news_fusion_model_w: float = 0.85
    news_fusion_bias_w: float = 0.15
    news_return_adjust: float = 0.15
    news_return_floor: float = 0.01

    # ---- 历史校准融合 ----
    calib_fusion_calib_w: float = 0.6
    calib_fusion_model_w: float = 0.4
    p_up_min: float = 0.01
    p_up_max: float = 0.99

    # ---- 风险评分（四个归一化基准彼此独立，勿合并）----
    atr_sigma_multiplier: float = 1.6   # ATR 缺失时用 σ 换算真实波幅
    drawdown_window: int = 60
    risk_w_atr: float = 0.4
    risk_atr_full: float = 0.03         # 单根 3% 视为满格
    risk_w_drawdown: float = 0.3
    risk_dd_full: float = 0.1           # 回撤 10% 视为满格
    risk_w_adx: float = 0.15
    risk_adx_full: float = 50.0
    risk_w_dist: float = 0.15
    risk_dist_full: float = 0.02        # 距关键价位 2% 以内
    risk_label_low_max: float = 33
    risk_label_mid_max: float = 66

    # ---- 多空强度 ----
    resonance_clip: float = 500.0
    resonance_sigmoid_temp: float = 20.0
    ls_return_gain: float = 20.0
    ls_base_weight: float = 0.5
    ls_neutral_gap: float = 8.0         # 多空分差小于该值判「观望」

    # ---- 行情状态判定（`_regime` 与 `evaluate_regime` 必须同口径）----
    adx_trend_threshold: float = 25.0
    boll_band_squeeze: float = 0.01

    # ---- 评估 ----
    eval_min_extra_bars: int = 20
    eval_min_samples: int = 30
    eval_train_ratio: float = 0.8
    feature_importance_top_n: int = 10

    # ---- 金融常数（非策略阈值，仅集中放置便于一致引用）----
    risk_free_annual: float = 0.02
    annual_trading_days: int = 252


# ---------------------------------------------------------------------------
# 多周期集成
# ---------------------------------------------------------------------------
@dataclass
class EnsembleConfig:
    """`MultiPeriodEnsemble` / `PeriodModel` / `_TreeModel` 的阈值。"""

    ridge_alpha_grid: tuple = (1e-3, 1e-2, 0.1, 1.0, 10.0, 100.0, 1000.0)
    ridge_default_alpha: float = 1.0
    default_random_seed: int = 7
    default_resid_std: float = 1e-4
    default_seq_len: int = 20        # 与 PredictorConfig.default_seq_len 不同源
    default_epochs: int = 25
    min_extra_bars: int = 5          # len(df) >= seq_len + 5
    min_train_sequences: int = 20

    # GBM（sklearn 分支）
    gbm_n_estimators: int = 100
    gbm_max_depth: int = 3
    gbm_learning_rate: float = 0.06
    gbm_subsample: float = 0.9
    train_split_ratio: float = 0.8   # 成员内部 train/OOS 切分
    gbm_min_oos_train: int = 20
    gbm_min_oos_valid: int = 8
    insample_resid_inflate: float = 1.5   # 样本内残差的保守膨胀（无推导依据的旧值）

    # 周线 → 日线折算
    trading_days_per_week: float = 5.0

    # 波动率递推（EWMA）
    vol_ewma_decay: float = 0.9
    vol_ewma_alpha: float = 0.1

    # LSTM 成员
    lstm_hidden_size: int = 32
    lstm_learning_rate: float = 0.01

    # 集成加权
    tree_seed_offset: int = 100      # 树成员种子与 LSTM 成员隔离的偏移
    mae_weight_smoothing: float = 1e-3   # 1/(mae + x)：反比加权的平滑兼下限
    max_val_samples: int = 120       # 权重估计时验证集最多抽样点数


# ---------------------------------------------------------------------------
# 反馈闭环
# ---------------------------------------------------------------------------
@dataclass
class FeedbackConfig:
    """`feedback.py`：结算 / 校准 / 自适应配置 / 再训练触发。"""

    regime_ma_fast: int = 5
    regime_ma_slow: int = 20
    trend_adx_threshold: float = 25.0
    trend_ma_divergence: float = 0.01

    default_horizon: int = 10
    eval_bar_buffer: int = 5
    min_eval_bars: int = 2
    neutral_p_up: float = 0.5
    max_eval_rows: int = 50

    # 三处 min_samples=20 语义不同，**严禁合并**
    adaptive_min_samples: int = 20
    calibration_min_samples: int = 20
    retrain_min_samples: int = 20

    confidence_min_samples: int = 15
    empty_bin_prior: float = 0.5
    wilson_z_95: float = 1.96
    calibration_bins: int = 10
    calibration_row_limit: int = 4000
    min_bin_samples: int = 3
    wide_band_threshold: float = 0.20


# ---------------------------------------------------------------------------
# 离线回放与多模型对比
# ---------------------------------------------------------------------------
@dataclass
class CalibConfig:
    """`calibration_replay.py`：回放参数与外部模型超参。"""

    min_bars_for_replay: int = 80
    replay_horizon: int = 10
    replay_stride: int = 8
    replay_max_samples: int = 250
    replay_epochs: int = 20
    replay_retrain_stride: int = 20
    replay_seq_len: int = 20
    replay_min_start: int = 60
    replay_probe_train_bars: int = 80
    hit_p_up_threshold: float = 0.5

    # TCN
    tcn_epochs: int = 10
    tcn_channels: tuple = (16, 16)
    tcn_kernel_size: int = 2
    tcn_lr: float = 0.01
    tcn_batch_size: int = 32
    tcn_min_epochs: int = 5

    # GBM（玩具实现）
    gbm_n_estimators: int = 60
    gbm_learning_rate: float = 0.1
    gbm_max_depth: int = 1

    # TS-Transformer
    ts_epochs: int = 10
    ts_seq_len: int = 20
    ts_min_epochs: int = 1           # 结构性下限，保证至少跑一轮

    # 多模型对比（与 replay_* 部分同值但语义独立，不可共用常量）
    compare_horizon: int = 10
    compare_stride: int = 8
    compare_max_samples: int = 100
    compare_epochs: int = 12
    compare_seq_len: int = 20

    random_seed: int = 7


# ---------------------------------------------------------------------------
# 预测 ↔ 回测联动
# ---------------------------------------------------------------------------
@dataclass
class LinkageConfig:
    """`linkage_bus.py`：联动画像的权重与容量。"""

    hit_log_capacity: int = 80
    hit_rate_window: int = 30
    neutral_hit_rate: float = 0.5
    backtest_log_capacity: int = 200
    pending_predictions_capacity: int = 100

    hit_adj_max_delta: float = 0.12
    hit_adj_gain: float = 2.0

    strat_weight_min: float = 0.15
    strat_weight_max: float = 0.70
    strat_weight_base: float = 0.30
    strat_weight_span: float = 0.25
    library_saturation_n: int = 40

    prefer_ensemble_consensus: float = 0.5
    prefer_extended_min_n: int = 20

    # 单品种权重（span 与全局 span 数值不同，勿互换）
    symbol_weight_base: float = 0.30
    symbol_weight_span: float = 0.30
    symbol_saturation_n: int = 10


# ---------------------------------------------------------------------------
# 模型漂移检测（M3-13）
# ---------------------------------------------------------------------------
@dataclass
class DriftConfig:
    """`drift.py`：漂移检测的阈值与窗口。

    M3-13 新增。除 `threshold` / `min_days` / `window` 是改造前就有的字面量外，
    `dev_norm` / `noise_band` / `mag_norm` 是本次**恢复 corr_penalty 真实计算**
    新引入的归一化基准（见 `drift.detect_drift` 的注释）。
    """

    threshold: float = 0.20          # 漂移分阈值，超过即触发重训警告
    window: int = 60                 # rolling_hit_drift 的默认回看窗口（天）
    min_days: int = 10               # 判定所需的最小天数（**与 window 解耦**）

    # 均值偏移归一：|窗口均值 − 基准| / dev_norm，理论最大偏离即 dev_norm
    dev_norm: float = 0.5
    # 一致性判定的「噪声带」：单日偏离 |d| ≤ noise_band 视为噪声，不计方向，
    # 避免数值抖动被当成「每天都系统性偏离」
    noise_band: float = 0.02
    # 幅度归一：mean(|d|) / mag_norm
    mag_norm: float = 0.5

    # scheduler 定时漂移检测的默认间隔（分钟）。文档 M3-13 ④ 要求「默认 1h」
    scheduler_interval_min: int = 60
    # 单次检测最多扫多少个已预测品种（防止定时任务拖垮主线程）
    scheduler_max_symbols: int = 40


# ---------------------------------------------------------------------------
# 运行期实例与覆盖机制
# ---------------------------------------------------------------------------
PREDICTOR = PredictorConfig()
ENSEMBLE = EnsembleConfig()
FEEDBACK = FeedbackConfig()
CALIB = CalibConfig()
LINKAGE = LinkageConfig()
DRIFT = DriftConfig()

# 出厂默认值快照（reset_to_defaults / 单测基准用）
DEFAULT_PREDICTOR = PredictorConfig()
DEFAULT_ENSEMBLE = EnsembleConfig()
DEFAULT_FEEDBACK = FeedbackConfig()
DEFAULT_CALIB = CalibConfig()
DEFAULT_LINKAGE = LinkageConfig()
DEFAULT_DRIFT = DriftConfig()

_GROUPS: Dict[str, Any] = {
    "predictor": (PREDICTOR, DEFAULT_PREDICTOR),
    "ensemble": (ENSEMBLE, DEFAULT_ENSEMBLE),
    "feedback": (FEEDBACK, DEFAULT_FEEDBACK),
    "calib": (CALIB, DEFAULT_CALIB),
    "linkage": (LINKAGE, DEFAULT_LINKAGE),
    "drift": (DRIFT, DEFAULT_DRIFT),
}


def _coerce(cfg: Any, name: str, value: Any) -> bool:
    """把一个外部值写进 dataclass 字段（类型不符则拒绝并告警）。

    返回是否成功写入。
    """
    try:
        f = next(f for f in fields(cfg) if f.name == name)
    except StopIteration:
        logger.warning("忽略未知阈值 %s.%s=%r（无此字段）",
                       type(cfg).__name__, name, value)
        return False
    try:
        if f.type is tuple or f.type == "tuple":
            setattr(cfg, name, tuple(value))
        elif f.type is float or f.type == "float":
            setattr(cfg, name, float(value))
        elif f.type is int or f.type == "int":
            # 显式拒绝「该填 int 却给了 float」——多半是笔误
            if isinstance(value, float) and not float(value).is_integer():
                raise ValueError(f"{name} 需要整数，收到 {value!r}")
            setattr(cfg, name, int(value))
        else:
            setattr(cfg, name, value)
    except Exception as e:  # noqa: BLE001
        logger.warning("阈值 %s.%s=%r 无效，保留原值：%s",
                       type(cfg).__name__, name, value, e)
        return False
    return True


def apply_overrides(mapping: Dict[str, Dict[str, Any]],
                    strict: bool = False) -> int:
    """把 {组名: {字段名: 值}} 应用到运行期实例，返回成功写入的条数。"""
    n = 0
    with _LOCK:
        for group, kv in (mapping or {}).items():
            pair = _GROUPS.get(str(group).lower())
            if pair is None:
                msg = f"忽略未知阈值组 '{group}'"
                if strict:
                    raise KeyError(msg)
                logger.warning(msg)
                continue
            cfg = pair[0]
            for k, v in (kv or {}).items():
                if _coerce(cfg, k, v):
                    n += 1
    return n


def _settings_paths() -> list:
    """候选的 settings.json 路径（环境变量优先，便于 A/B 与测试）。"""
    out = []
    env = os.environ.get("QV_AI_THRESHOLDS_JSON")
    if env:
        out.append(env)
    try:
        from ..runtime import get_config_dir
        out.append(os.path.join(get_config_dir(), "settings.json"))
    except Exception:  # noqa: BLE001
        pass
    # 源码树兜底：<包>/../config/settings.json
    here = os.path.dirname(os.path.abspath(__file__))
    out.append(os.path.join(os.path.dirname(os.path.dirname(here)),
                            "config", "settings.json"))
    return out


def reload_from_settings(strict: bool = False) -> int:
    """从 `config/settings.json#ai.thresholds` 重新载入覆盖值。

    找不到文件或该段不存在时**静默保持默认值**（返回 0），不抛异常 ——
    本模块被 UI 启动路径依赖，任何加载失败都不该阻断启动。
    """
    for p in _settings_paths():
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        section = (data.get("ai") or {}).get(THRESHOLDS_SECTION) or {}
        if not isinstance(section, dict) or not section:
            continue
        n = apply_overrides(section, strict=strict)
        logger.info("已载入 %d 项 AI 阈值覆盖（%s）", n, p)
        return n
    return 0


def reset_to_defaults() -> None:
    """把所有运行期实例恢复为出厂默认值（单测 / 配置回滚用）。"""
    with _LOCK:
        for cfg, default in _GROUPS.values():
            for f in fields(default):
                setattr(cfg, f.name, getattr(default, f.name))


@contextlib.contextmanager
def override(cfg: Any, **kw: Any) -> Iterator[Any]:
    """临时改几个阈值，退出时自动还原（线程安全，可嵌套）。

        with override(PREDICTOR, cum_clip=0.3):
            ...
    """
    with _LOCK:
        saved = {k: getattr(cfg, k) for k in kw}
        for k, v in kw.items():
            setattr(cfg, k, v)
    try:
        yield cfg
    finally:
        with _LOCK:
            for k, v in saved.items():
                setattr(cfg, k, v)


# 首次导入即尝试载入一次；失败不影响默认值（全部字段已就地初始化）
reload_from_settings()
