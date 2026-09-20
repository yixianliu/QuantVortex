"""M7.1 进化控制器：把「策略 + 模型 + 风控」三轨基因统一抽象为 Genome，可独立 / 联合进化。

设计（决策门 D7.1：进化由手动 + 反馈闭环触发，不强制定时）：
- ``Genome`` 统一封装三轨基因字典，支持部分轨缺失（独立进化时其余轨用默认值）。
- 三轨：
  1. strategy：复用 ``auto_evolve`` 的策略因子基因（可经 ``auto_evolve.random_gene`` 生成，
     也接受外部传入的 dict）。
  2. model：AI 模型超参（模型类型 / 学习率 / seq_len / 正则 / ensemble 开关）。
  3. risk：风控参数（ATR 止损倍数 / 凯利分数 / 单日最大亏损阈值 / 回撤熔断）。
- ``EvolutionController`` 提供：
  - ``mutate(genome, track)``：按轨变异（未指定则全轨）。
  - ``crossover(a, b, track)``：按轨交叉。
  - ``evaluate(genome)``：调用户注入的 fitness_fn(genome)->float（解耦真实回测/AI 训练，
    便于离线单测；真实场景把 auto_evolve / predictor 的指标打包传入）。
  - ``run(generations, ...)``：精英 + 锦标赛的简易 GA 循环，返回收敛曲线（供 M7.3 落盘）。
- 防未来函数：本模块不读行情，纯基因运算；行情评估全部委托 fitness_fn。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

__all__ = [
    "Genome",
    "EvolutionController",
    "DEFAULT_MODEL_SPACE",
    "DEFAULT_RISK_SPACE",
    "TRACKS",
    "compute_fitness",
]

TRACKS: tuple[str, ...] = ("strategy", "model", "risk")

# ---------------- 模型超参基因空间（M7.1 模型轨） ----------------
DEFAULT_MODEL_SPACE: Dict[str, List[Any]] = {
    "model_type": ["ridge", "lstm", "tcn", "gbm"],
    "lr": [0.001, 0.005, 0.01, 0.02, 0.05],
    "seq_len": [8, 12, 20, 30],
    "epochs": [10, 20, 40],
    "l2_reg": [0.0, 0.01, 0.1, 1.0],
    "use_ensemble": [False, True],
}

# ---------------- 风控参数基因空间（M7.1 风控轨） ----------------
DEFAULT_RISK_SPACE: Dict[str, List[Any]] = {
    "stop_atr_mult": [1.0, 1.5, 2.0, 3.0, 4.0],
    "kelly_fraction": [0.1, 0.25, 0.5, 0.75, 1.0],
    "max_daily_loss_pct": [0.02, 0.03, 0.05, 0.08, 0.10],
    "drawdown_circuit_pct": [0.10, 0.15, 0.20, 0.30, 0.40],
}


@dataclass
class Genome:
    """三轨统一基因。

    各轨为可独立进化的子字典；某轨缺失（None）时独立进化会先注入该轨的默认随机基因。
    """
    strategy: Optional[Dict[str, Any]] = None
    model: Optional[Dict[str, Any]] = None
    risk: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Optional[Dict[str, Any]]]:
        return {"strategy": self.strategy, "model": self.model, "risk": self.risk}

    def active_tracks(self) -> List[str]:
        return [t for t in TRACKS if getattr(self, t) is not None]

    def clone(self) -> "Genome":
        import copy
        return copy.deepcopy(self)


def _random_model_gene(rng: random.Random, space: Dict[str, List[Any]] = None) -> Dict[str, Any]:
    space = space or DEFAULT_MODEL_SPACE
    return {k: rng.choice(v) for k, v in space.items()}


def _random_risk_gene(rng: random.Random, space: Dict[str, List[Any]] = None) -> Dict[str, Any]:
    space = space or DEFAULT_RISK_SPACE
    return {k: rng.choice(v) for k, v in space.items()}


class EvolutionController:
    """三轨协同进化控制器。

    参数:
        fitness_fn: 必填，``fn(genome: Genome) -> float``。把真实回测 / 模型验证交给
            外部注入（返回越高越好），本控制器只做基因运算与 GA 循环，保持可离线测试。
        strategy_generator: 可选，``fn(rng) -> dict`` 生成策略基因；默认用
            ``auto_evolve.random_gene``，未传则惰性导入。
        model_space / risk_space: 可选，自定义基因空间。
        pop_size / elites / tournament: GA 超参。
        seed: 随机种子（可复现）。
    """

    def __init__(
        self,
        fitness_fn: Callable[[Genome], float],
        strategy_generator: Optional[Callable[[random.Random], Dict[str, Any]]] = None,
        model_space: Optional[Dict[str, List[Any]]] = None,
        risk_space: Optional[Dict[str, List[Any]]] = None,
        pop_size: int = 8,
        elites: int = 2,
        tournament_k: int = 3,
        seed: Optional[int] = None,
    ) -> None:
        if fitness_fn is None:
            raise ValueError("fitness_fn 必填")
        if pop_size < 2:
            raise ValueError("pop_size 至少为 2")
        self.fitness_fn = fitness_fn
        self._strategy_generator = strategy_generator or _default_strategy_generator
        self.model_space = model_space or DEFAULT_MODEL_SPACE
        self.risk_space = risk_space or DEFAULT_RISK_SPACE
        self.pop_size = pop_size
        self.elites = max(1, min(elites, pop_size - 1))
        self.tournament_k = max(2, tournament_k)
        self.rng = random.Random(seed)
        self.last_convergence: List[Dict[str, float]] = []

    # ---------------- 基因运算 ----------------
    def random_genome(self, tracks: Sequence[str] = TRACKS) -> Genome:
        g = Genome()
        for t in tracks:
            if t == "strategy":
                g.strategy = self._strategy_generator(self.rng)
            elif t == "model":
                g.model = _random_model_gene(self.rng, self.model_space)
            elif t == "risk":
                g.risk = _random_risk_gene(self.rng, self.risk_space)
        return g

    def _mutate_track(self, track: str, gene: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
        g = dict(gene)
        if track == "strategy":
            try:
                from .auto_evolve import mutate as _amut
                # auto_evolve.mutate 接受 (gene, rng)
                return dict(_amut(g, rng))
            except Exception:
                # 降级：随机替换一个键的取值（保持结构不变）
                keys = [k for k in g if isinstance(g[k], (int, float, str, bool))]
                if keys:
                    k = rng.choice(keys)
                    if isinstance(g[k], (int, float)):
                        g[k] = g[k] * (1.0 + rng.uniform(-0.3, 0.3))
                return g
        if track == "model":
            keys = [k for k in self.model_space if k in g]
            if keys:
                k = rng.choice(keys)
                g[k] = rng.choice(self.model_space[k])
            return g
        if track == "risk":
            keys = [k for k in self.risk_space if k in g]
            if keys:
                k = rng.choice(keys)
                g[k] = rng.choice(self.risk_space[k])
            return g
        return g

    def mutate(self, genome: Genome, tracks: Sequence[str] = TRACKS) -> Genome:
        out = genome.clone()
        for t in tracks:
            if getattr(out, t) is None:
                # 缺失轨注入默认随机基因后变异
                if t == "strategy":
                    out.strategy = self._strategy_generator(self.rng)
                elif t == "model":
                    out.model = _random_model_gene(self.rng, self.model_space)
                elif t == "risk":
                    out.risk = _random_risk_gene(self.rng, self.risk_space)
            out = Genome(
                strategy=self._mutate_track("strategy", out.strategy or {}, self.rng) if "strategy" in tracks and out.strategy is not None else out.strategy,
                model=self._mutate_track("model", out.model or {}, self.rng) if "model" in tracks and out.model is not None else out.model,
                risk=self._mutate_track("risk", out.risk or {}, self.rng) if "risk" in tracks and out.risk is not None else out.risk,
            )
        return out

    def crossover(self, a: Genome, b: Genome, tracks: Sequence[str] = TRACKS) -> Genome:
        """逐轨按 key 随机混合 a/b 基因。"""
        out = a.clone()
        for t in tracks:
            ga, gb = getattr(a, t), getattr(b, t)
            if ga is None and gb is None:
                continue
            ga = ga or {}
            gb = gb or {}
            merged: Dict[str, Any] = {}
            for k in set(ga.keys()) | set(gb.keys()):
                merged[k] = gb.get(k, ga.get(k)) if self.rng.random() < 0.5 else ga.get(k, gb.get(k))
            setattr(out, t, merged)
        return out

    # ---------------- 评估与 GA ----------------
    def evaluate(self, genome: Genome) -> float:
        try:
            return float(self.fitness_fn(genome))
        except Exception:
            return -1e9

    def run(self, generations: int = 10, tracks: Sequence[str] = TRACKS) -> Dict[str, Any]:
        """执行 generations 代进化。

        返回：
            ``{best_genome, best_fitness, convergence: [ {generation, best, mean} ]}``。
        """
        if generations < 0:
            raise ValueError("generations 不能为负")
        pop = [self.random_genome(tracks) for _ in range(self.pop_size)]
        scores = [self.evaluate(g) for g in pop]
        convergence: List[Dict[str, float]] = []

        for gen in range(generations):
            # 依分数排序
            order = sorted(range(len(pop)), key=lambda i: -scores[i])
            best_i = order[0]
            mean = sum(scores) / len(scores) if scores else -1e9
            convergence.append({"generation": gen, "best": scores[best_i], "mean": mean})

            # 精英保留
            elites = [pop[order[j]].clone() for j in range(self.elites)]
            # 锦标赛填充其余
            next_pop: List[Genome] = list(elites)
            while len(next_pop) < self.pop_size:
                pa, pb = self._two_parents(pop, scores)
                if self.rng.random() < 0.5:
                    child = self.crossover(pa, pb, tracks)
                else:
                    child = pa.clone()
                next_pop.append(self.mutate(child, tracks))
            pop = next_pop
            scores = [self.evaluate(g) for g in pop]

        self.last_convergence = convergence
        final_order = sorted(range(len(pop)), key=lambda i: -scores[i])
        best = pop[final_order[0]]
        return {"best_genome": best, "best_fitness": scores[final_order[0]], "convergence": convergence}

    def _two_parents(self, pop: List[Genome], scores: List[float]) -> "tuple[Genome, Genome]":
        """锦标赛取 2 个父代。"""
        k = self.tournament_k
        n = len(pop)
        if n < 2:
            return pop[0], pop[0]
        i1 = max(self.rng.sample(range(n), min(k, n)), key=lambda i: scores[i])
        rest = [i for i in range(n) if i != i1]
        i2 = max(self.rng.sample(rest, min(k, len(rest))), key=lambda i: scores[i]) if rest else i1
        return pop[i1], pop[i2]


# ---------------- 适应度函数（M7.2 升级版） ----------------
def compute_fitness(
    metrics: Dict[str, float],
    cross_symbol_sharpes: Optional[Sequence[float]] = None,
) -> float:
    """M7.2 升级适应度（方案公式 + 跨品种稳定性惩罚）。

    公式（主项）：
        fitness = 0.4*sharpe + 0.3*calmar - 0.2*max_dd - 0.1*drawdown_duration
    其中：
        - sharpe / calmar：越大越好（正向贡献）；
        - max_dd：最大回撤（0~1，越大越差 → 负向惩罚）；
        - drawdown_duration：最大回撤持续时长（占样本比例，0~1 → 负向惩罚）。
    稳定性惩罚（可选）：
        - 当传入跨品种 sharpe 列表时，按其离散度（cv = std/|mean|）施加惩罚，
          品种越多越一致越不罚；全为 0 或单品种不罚。

    参数:
        metrics: 至少含 ``sharpe``；可选 ``calmar`` / ``max_drawdown`` / ``max_dd`` /
            ``drawdown_duration``。缺失字段取 0。
        cross_symbol_sharpes: 可选，跨品种夏普序列（用于稳定性惩罚）。

    返回:
        float。无数据（全空）返回 -100.0。
    """
    if not metrics:
        return -100.0
    sharpe = float(metrics.get("sharpe") or 0.0)
    calmar = float(metrics.get("calmar") or metrics.get("calmar_ratio") or 0.0)
    # 最大回撤：兼容 max_drawdown / max_dd，统一取 [0,1]（若已是百分制则除 100）
    mdd = metrics.get("max_drawdown", metrics.get("max_dd"))
    if mdd is None:
        mdd = 0.0
    mdd = abs(float(mdd))
    if mdd > 1.0:  # 百分制 → 0~1
        mdd = min(mdd, 100.0) / 100.0
    dd_dur = metrics.get("drawdown_duration")
    if dd_dur is None:
        dd_dur = 0.0
    dd_dur = min(max(abs(float(dd_dur)), 0.0), 1.0)

    main = 0.4 * sharpe + 0.3 * calmar - 0.2 * mdd - 0.1 * dd_dur

    # 稳定性惩罚：跨品种夏普离散度越大罚越多（最多 -0.5）
    penalty = 0.0
    if cross_symbol_sharpes:
        arr = np.asarray([float(x) for x in cross_symbol_sharpes], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size >= 2:
            mean = float(arr.mean())
            if abs(mean) > 1e-6:
                cv = float(arr.std(ddof=0) / abs(mean))
            else:
                cv = float(arr.std(ddof=0))
            # cv=0（完全一致）→ 不罚；cv 越大罚越多，封顶 0.5
            penalty = min(0.5, 0.5 * cv)

    return round(main - penalty, 6)


# ---------------- 惰性策略基因生成器 ----------------
def _default_strategy_generator(rng: random.Random) -> Dict[str, Any]:
    try:
        from .auto_evolve import random_gene
        return random_gene(rng)
    except Exception:
        # 极简兜底策略基因（不依赖 auto_evolve 的完整空间）
        return {
            "factor": "ma_cross",
            "ma_fast": rng.choice([3, 5, 10]),
            "ma_slow": rng.choice([20, 30, 60]),
            "stop_mult": round(rng.choice([1.0, 1.5, 2.0, 3.0]), 2),
            "tp_mult": round(rng.choice([0.0, 1.5, 2.0, 3.0]), 2),
            "lots": 1,
            "allow_long": True,
            "allow_short": True,
        }


__all__ = [
    "Genome",
    "EvolutionController",
    "DEFAULT_MODEL_SPACE",
    "DEFAULT_RISK_SPACE",
    "TRACKS",
    "_default_strategy_generator",
]
