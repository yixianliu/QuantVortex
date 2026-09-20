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
        .run(X, y) -> {model: [fold_metrics...], 'oos': {model: agg}}

trainer / predictor 为可调用对象：
    trainer(X_train, y_train) -> fitted_model
    predictor(fitted_model, X_test) -> np.ndarray  (预测值)

y 为二分类方向标签（0/1）或回归值；MAE 始终计算，命中率仅当 y ∈ {0,1} 时给出。
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
    hit_rate: Optional[float]  # None 表示回归目标（无命中率概念）
    n_test: int


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
        return plan

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
        for p in plan:
            x_tr, y_tr = X[p["train_start"]:p["train_end"]], y[p["train_start"]:p["train_end"]]
            x_te, y_te = X[p["test_start"]:p["test_end"]], y[p["test_start"]:p["test_end"]]
            for name, (trainer, predictor) in self._models.items():
                model = trainer(x_tr, y_tr)
                pred = np.asarray(predictor(model, x_te), dtype=float)
                mae = float(np.mean(np.abs(pred - y_te))) if len(y_te) else 0.0
                if is_binary:
                    yb = (y_te > 0.5).astype(int)
                    pb = (pred > 0.5).astype(int)
                    hit = float((pb == yb).mean()) if len(pb) else None
                else:
                    hit = None
                folds_out[name].append(Fold(
                    fold=p["fold"], train_start=p["train_start"],
                    train_end=p["train_end"], test_start=p["test_start"],
                    test_end=p["test_end"], mae=mae, hit_rate=hit,
                    n_test=int(len(y_te)),
                ))

        # OOS 汇总：把各折 OOS 段拼接后统一统计
        oos: Dict[str, Dict[str, float]] = {}
        for name, fl in folds_out.items():
            all_pred = np.concatenate([
                # 重新预测以拼接 OOS 段（因果：只用该折训练）
                np.asarray(self._models[name][1](
                    self._models[name][0](
                        X[f.train_start:f.train_end],
                        y[f.train_start:f.train_end]),
                        X[f.test_start:f.test_end]), dtype=float)
                for f in fl
            ])
            all_true = np.concatenate([
                y[f.test_start:f.test_end] for f in fl
            ])
            mae = float(np.mean(np.abs(all_pred - all_true))) if len(all_true) else 0.0
            if is_binary:
                yb = (all_true > 0.5).astype(int)
                pb = (all_pred > 0.5).astype(int)
                hit = float((pb == yb).mean()) if len(pb) else None
            else:
                hit = None
            oos[name] = {"mae": mae, "hit_rate": hit, "n": int(len(all_true))}

        return WalkForwardResult(folds=[f for fl in folds_out.values() for f in fl],
                                 oos=oos, models=folds_out)
