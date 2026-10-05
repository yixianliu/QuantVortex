"""Walk-Forward 滚动验证（M5.7）。

把「预测」从随机划分升级为**时间序列滚动扩展验证**：
- 训练窗口 train_len（默认 252 天）；
- 验证窗口 test_len（默认 63 天）；
- 扩展步长 step（默认 63 天，每次把 step 并入新训练集）；
- 禁止随机划分（时间序列乱序会引入未来函数，破坏因果性）。

输出每折 metrics（MAE / 命中率）与 OOS 汇总，供模型对比与漂移监控。

接口：
    class WalkForward(train_len=252, test_len=63, step=63, min_folds=3)
        .add_model(name, trainer, predictor)
        .run(X, y) -> WalkForwardResult

trainer / predictor 为可调用对象：
    trainer(X_train, y_train) -> fitted_model
    predictor(fitted_model, X_test) -> np.ndarray  (预测值)

y 为二分类方向标签（0/1）或回归值；MAE 始终计算。

M3-05 改动：
  ① 命中率阈值：`pred > 0.5` 只对二分类目标有意义。回归目标（本项目预测的是
     对数收益）改用**训练段收益中位数** `median(y_train)` 作为「看多/看空」分界，
     否则 0.5 永远判为「看空」，命中率会退化为「下跌样本占比」这个常数。
     每折的阈值记录在 `Fold.hit_threshold`，可审计。
  ② OOS 汇总**复用 fold 内已训模型**的预测结果：旧实现（:153-161）把每个 fold
     又重训一遍只为拼 OOS 段，训练成本翻倍且毫无收益（同 seed 下结果本应一致，
     但无 seed 约束的模型会给出**与 fold 指标不一致**的汇总值）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np


@dataclass
class Fold:
    """单折验证结果。"""
    fold: int
    train_start: int
    train_end: int      # 半开区间 [train_start, train_end)
    test_start: int
    test_end: int       # 半开区间 [test_start, test_end)
    mae: float
    hit_rate: Optional[float]
    n_test: int
    # M3-05：本折用于把预测值切成「看多/看空」的阈值。
    # 二分类 y 恒为 0.5；回归 y 为训练段收益中位数（见模块 docstring ①）。
    hit_threshold: Optional[float] = None


@dataclass
class WalkForwardResult:
    """一次 Walk-Forward 的完整结果。"""
    folds: List[Fold]
    oos: Dict[str, Dict[str, float]]  # model_name -> {mae, hit_rate, n}
    models: Dict[str, List[Fold]]

    def summary(self) -> str:
        lines = []
        for name, agg in self.oos.items():
            hit = f"{agg['hit_rate']:.3f}" if agg.get('hit_rate') is not None else "n/a"
            lines.append(f"{name}: MAE={agg['mae']:.4f} 命中率={hit} n={agg['n']}")
        return "\n".join(lines)


class WalkForward:
    """滚动扩展验证器。

    约束：
    - train_len / test_len / step 均为正整数；
    - 至少能跑出 min_folds 折才有效（否则抛 ValueError）；
    - 严格因果：第 k 折训练集只读 [0, test_start_k)，测试集只读 [test_start_k, test_end_k)。
    """

    def __init__(self, train_len: int = 252, test_len: int = 63, step: int = 63,
                 min_folds: int = 3) -> None:
        if train_len <= 0 or test_len <= 0 or step <= 0:
            raise ValueError("train_len / test_len / step 必须为正整数")
        if min_folds <= 0:
            raise ValueError("min_folds 必须为正")
        self.train_len = int(train_len)
        self.test_len = int(test_len)
        self.step = int(step)
        self.min_folds = int(min_folds)
        self._models: Dict[str, tuple[Callable, Callable]] = {}

    # ---- 模型注册 ----
    def add_model(self, name: str,
                  trainer: Callable[[np.ndarray, np.ndarray], object],
                  predictor: Callable[[object, np.ndarray], np.ndarray]) -> "WalkForward":
        """注册一个可训练 + 可预测的模型对。"""
        if not callable(trainer) or not callable(predictor):
            raise TypeError("trainer / predictor 必须可调用")
        self._models[name] = (trainer, predictor)
        return self

    # ---- 折叠生成（纯逻辑，可单独测试）----
    def folds_plan(self, n: int) -> List[Dict[str, int]]:
        """给定样本总数 n，返回每折的窗口索引（因果滚动）。

        第 k 折（k 从 0 起）：
            test 区间 [test_start, test_start + test_len)
            其中 test_start = train_len + k * step
            train 区间 [test_start - train_len, test_start)
        直到 test_start + test_len <= n。
        """
        plan: List[Dict[str, int]] = []
        k = 0
        test_start = self.train_len + k * self.step
        while test_start + self.test_len <= n:
            plan.append({
                "fold": k,
                "train_start": test_start - self.train_len,
                "train_end": test_start,
                "test_start": test_start,
                "test_end": test_start + self.test_len,
            })
            k += 1
            test_start = self.train_len + k * self.step
        if len(plan) < self.min_folds:
            raise ValueError(
                f"Walk-Forward 只能产出 {len(plan)} 折，少于 min_folds={self.min_folds}"
                f"；请增大样本量或缩短 train_len / test_len / step"
            )
        self.validate_plan(plan)
        return plan

    @staticmethod
    def validate_plan(plan: Sequence[Dict[str, int]]) -> bool:
        """M3-05：折叠方案的因果性自检（验收标准「train/test 严格不重叠」）。

        断言：
          - 每折 train 区间严格早于 test 区间（train_end <= test_start）；
          - 各折 test 区间两两**不相交**（step >= test_len 时成立；step < test_len
            会让相邻折的测试段重叠 -> 同一样本被重复计入 OOS，指标虚高）。
        违例直接 raise ValueError，绝不静默产出污染指标。
        """
        prev_test_end = None
        for p in plan:
            if not (p["train_start"] < p["train_end"] <= p["test_start"] < p["test_end"]):
                raise ValueError(f"折叠 {p['fold']} 区间不满足因果顺序：{p}")
            if prev_test_end is not None and p["test_start"] < prev_test_end:
                raise ValueError(
                    f"折叠 {p['fold']} 的测试段 [{p['test_start']}, {p['test_end']}) "
                    f"与上一折测试段重叠（止于 {prev_test_end}）：请令 step >= test_len")
            prev_test_end = p["test_end"]
        return True

    # ---- 主流程 ----
    def run(self, X: np.ndarray, y: np.ndarray) -> WalkForwardResult:
        X = np.asarray(X, dtype=float)
        y = np.asarray(y)
        n = X.shape[0]
        if y.shape[0] != n:
            raise ValueError("X 与 y 长度不一致")
        plan = self.folds_plan(n)
        is_binary = set(np.unique(y)) <= {0, 1} or set(np.unique(y)) <= {0.0, 1.0}

        folds_out: Dict[str, List[Fold]] = {m: [] for m in self._models}
        # M3-05 ②：OOS 段直接复用 fold 内已训模型的预测，不再重训一遍
        oos_segments: Dict[str, List[np.ndarray]] = {m: [] for m in self._models}
        oos_true_segments: List[np.ndarray] = []
        oos_hit_segments: Dict[str, List[np.ndarray]] = {m: [] for m in self._models}

        for p in plan:
            x_tr, y_tr = X[p["train_start"]:p["train_end"]], y[p["train_start"]:p["train_end"]]
            x_te, y_te = X[p["test_start"]:p["test_end"]], y[p["test_start"]:p["test_end"]]
            # M3-05 ①：回归目标用训练段中位数做多空分界，不再无脑 0.5
            thr = 0.5 if is_binary else float(np.median(y_tr)) if len(y_tr) else 0.0
            for name, (trainer, predictor) in self._models.items():
                model = trainer(x_tr, y_tr)
                pred = np.asarray(predictor(model, x_te), dtype=float)
                mae = float(np.mean(np.abs(pred - y_te))) if len(y_te) else 0.0
                if len(pred):
                    hit_mask = ((pred > thr).astype(int)
                                == (np.asarray(y_te, dtype=float) > thr).astype(int))
                    hit = float(hit_mask.mean())
                else:
                    hit_mask = np.empty(0, dtype=bool)
                    hit = None
                folds_out[name].append(Fold(
                    fold=p["fold"], train_start=p["train_start"],
                    train_end=p["train_end"], test_start=p["test_start"],
                    test_end=p["test_end"], mae=mae, hit_rate=hit,
                    n_test=int(len(y_te)), hit_threshold=thr,
                ))
                oos_segments[name].append(pred)
                oos_hit_segments[name].append(hit_mask.astype(float))
            oos_true_segments.append(np.asarray(y_te, dtype=float))

        # OOS 汇总：拼接各折 OOS 段（每折自带阈值，逐段判定后再汇总）
        oos: Dict[str, Dict[str, float]] = {}
        all_true = (np.concatenate(oos_true_segments)
                    if oos_true_segments else np.empty(0))
        for name in folds_out:
            segs = oos_segments[name]
            all_pred = np.concatenate(segs) if segs else np.empty(0)
            mae = float(np.mean(np.abs(all_pred - all_true))) if len(all_true) else 0.0
            hs = oos_hit_segments[name]
            hit = float(np.concatenate(hs).mean()) if hs and len(hs[0]) else None
            oos[name] = {"mae": mae, "hit_rate": hit, "n": int(len(all_true))}

        return WalkForwardResult(folds=[f for fl in folds_out.values() for f in fl],
                                 oos=oos, models=folds_out)
