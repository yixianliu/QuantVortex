"""预测操作板块 ⇄ 回测中心 双向联动总线（深度协同基石）。

设计目标
--------
让「回测中心」与「预测操作板块」形成**实时双向数据闭环**：

1. 回测 → 预测（反哺调参 / 自我调整）
   - 回测中心每产出一条经验证的盈利策略，就通过 :meth:`push_backtest_result`
     推送到总线；总线聚合**全市场盈利回测库**（`load_profitable()`），
     计算出「预测调参画像」：
       * 全市场方向一致性（consensus）—— 盈利策略多空方向越一致，回测信号
         在预测融合中的权重越高；
       * 策略信号基础权重（strat_weight_base，0.30~0.55，随库容量×一致性自增）；
       * 是否偏好扩展特征 / 集成模型（库足够大时自动开启）。
   - 预测页在每次预测时读取该画像，把回测沉淀的高质量方向**自我调整**地
     融合进研判，使预测贴合「当前期货实盘行情」而非孤立建模。

2. 预测 → 回测（信号待验证 / 自我训练）
   - 预测页每次产出研判，通过 :meth:`push_prediction` 把「预测信号」推送到总线；
   - 回测中心在自动进化 / 手动回测完成时消费这些待验证信号，提示用户「用回测
     验证该预测」，形成「预测 → 回测验证 → 反哺预测」的自我训练闭环。

总线为模块级单例 :data:`BUS`，两个页面各自 import 同一实例，零侵入接入，
不破坏现有页面构造签名。所有读写加锁，可在多线程 worker 安全调用。
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal


class LinkageBus(QObject):
    """双向联动总线（QObject 信号 + 调参画像缓存）。"""

    # 回测中心 → 预测：盈利策略产出
    backtest_updated = pyqtSignal(dict)
    # 预测 → 回测中心：研判信号产出（待回测验证）
    prediction_updated = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._tuning: dict = {"global": self._default_global(), "by_symbol": {}}
        self._backtest_log: list = []
        self._pending_predictions: list = []
        self._hit_log: list = []        # 最近命中记录 [{symbol, hit, ts}]
        self._built = False

    def record_hit(self, symbol: str, hit: bool) -> None:
        """预测结果落盘后的命中回执：hit=True 表示后续实际走势符合判断。"""
        with self._lock:
            self._hit_log.insert(0, {"symbol": symbol, "hit": hit,
                                     "ts": __import__("time").time()})
            self._hit_log = self._hit_log[:80]

    def _recalc_hit_rate(self) -> float:
        """最近 30 次命中率；无记录则 0.5（中性先验）。"""
        recs = self._hit_log[:30]
        if not recs:
            return 0.5
        return sum(1 for r in recs if r["hit"]) / len(recs)

    # ------------------------------------------------------------------
    # 回测中心 → 预测（反哺调参画像）
    # ------------------------------------------------------------------
    def push_backtest_result(self, symbol: str, gene: Optional[dict],
                             metrics: dict, direction_bias: Optional[float] = None,
                             regime: Optional[str] = None) -> None:
        """回测中心产出（盈利或非盈利）策略时调用，触发画像重建并发射信号。"""
        with self._lock:
            self._backtest_log.insert(0, {
                "symbol": symbol,
                "gene": dict(gene) if gene else None,
                "metrics": metrics if metrics is not None else {},
                "direction_bias": direction_bias,
                "regime": regime,
            })
            self._backtest_log = self._backtest_log[:200]
        self.rebuild_tuning()
        self.backtest_updated.emit({
            "symbol": symbol, "gene": gene, "metrics": metrics,
            "direction_bias": direction_bias, "regime": regime,
        })

    def rebuild_tuning(self) -> None:
        """聚合全市场盈利回测库 → 预测调参画像（自我调整依据）。"""
        try:
            from ..strategy.auto_evolve import load_profitable, latest_signal_for
            entries = load_profitable()
        except Exception:  # noqa: BLE001
            entries = []
        with self._lock:
            self._built = True
            out: dict = {"global": self._default_global(), "by_symbol": {}}
            if not entries:
                self._tuning = out
                return
            biases: list = []
            fit_sum = 0.0
            by_sym: dict = {}
            for e in entries:
                sym = e.get("symbol", "")
                try:
                    sig = latest_signal_for(sym, None)
                    b = float(sig.get("bias", 0.0) or 0.0)
                except Exception:  # noqa: BLE001
                    b = 0.0
                f = float(e.get("fitness") or 0.0)
                biases.append((b, f))
                fit_sum += f
                d = by_sym.setdefault(sym, {"db": 0.0, "fs": 0.0, "n": 0})
                d["db"] += b * (f + 1e-6)
                d["fs"] += (f + 1e-6)
                d["n"] += 1
            n = len(entries)
            # 全市场加权方向偏置
            g_bias = (sum(b * (f + 1e-6) for b, f in biases) / (fit_sum + 1e-6)
                      if fit_sum else 0.0)
            # 方向一致性：|加权方向| / 平均|方向|，越接近 1 多空越一致
            mean_abs = (sum(abs(b) for b, _ in biases) / n) if biases else 0.0
            consensus = (abs(g_bias) / mean_abs) if mean_abs > 1e-6 else 0.0
            consensus = max(0.0, min(1.0, consensus))
            avg_fit = fit_sum / n if n else 0.0
            # 命中率调节：命中率低→降低依赖（hit_adj 为负）；命中率高→提高依赖
            hit_rate = self._recalc_hit_rate()
            hit_adj = 0.12 * (hit_rate - 0.5) * 2.0  # 范围 −0.12 ~ +0.12
            base = max(0.15, min(0.70,
                0.30 + 0.25 * min(1.0, n / 40.0) * consensus + hit_adj))
            out["global"] = {
                "n": n,
                "avg_fitness": round(avg_fit, 2),
                "direction_bias": round(g_bias, 4),
                "consensus": round(consensus, 3),
                "strat_weight_base": round(base, 3),
                "prefer_ensemble": consensus >= 0.5,
                "prefer_extended": n >= 20,
                "hit_rate": round(hit_rate, 3),
            }
            for sym, d in by_sym.items():
                db = d["db"] / (d["fs"] or 1e-6)
                out["by_symbol"][sym] = {
                    "direction_bias": round(db, 4),
                    "n": d["n"],
                    # 单品种权重：库内样本越多、方向越偏 → 越高（0.30~0.60）
                    "weight": round(0.30 + 0.30 * min(1.0, d["n"] / 10.0)
                                    * min(1.0, abs(db)), 3),
                }
            self._tuning = out

    @staticmethod
    def _default_global() -> dict:
        return {"n": 0, "avg_fitness": 0.0, "direction_bias": 0.0,
                "consensus": 0.0, "strat_weight_base": 0.30,
                "prefer_ensemble": False, "prefer_extended": False,
                "hit_rate": 0.5}

    def get_tuning(self, symbol: Optional[str] = None) -> dict:
        """返回当前调参画像（按需惰性构建）。"""
        with self._lock:
            if not self._built:
                # 首次访问时已在锁内，直接重建
                self._built = True
                try:
                    from ..strategy.auto_evolve import load_profitable
                    if load_profitable():
                        self.rebuild_tuning_locked()
                except Exception:  # noqa: BLE001
                    pass
            g = self._tuning.get("global", self._default_global())
            sym = (self._tuning.get("by_symbol", {}).get(symbol)
                   if symbol else None)
        return {"global": g, "symbol": sym}

    def rebuild_tuning_locked(self) -> None:
        """锁内版本（get_tuning 已持锁时调用）。"""
        try:
            from ..strategy.auto_evolve import load_profitable, latest_signal_for
            entries = load_profitable()
        except Exception:  # noqa: BLE001
            entries = []
        out: dict = {"global": self._default_global(), "by_symbol": {}}
        if not entries:
            self._tuning = out
            return
        biases: list = []
        fit_sum = 0.0
        by_sym: dict = {}
        for e in entries:
            sym = e.get("symbol", "")
            try:
                sig = latest_signal_for(sym, None)
                b = float(sig.get("bias", 0.0) or 0.0)
            except Exception:  # noqa: BLE001
                b = 0.0
            f = float(e.get("fitness") or 0.0)
            biases.append((b, f))
            fit_sum += f
            d = by_sym.setdefault(sym, {"db": 0.0, "fs": 0.0, "n": 0})
            d["db"] += b * (f + 1e-6)
            d["fs"] += (f + 1e-6)
            d["n"] += 1
        n = len(entries)
        g_bias = (sum(b * (f + 1e-6) for b, f in biases) / (fit_sum + 1e-6)
                  if fit_sum else 0.0)
        mean_abs = (sum(abs(b) for b, _ in biases) / n) if biases else 0.0
        consensus = (abs(g_bias) / mean_abs) if mean_abs > 1e-6 else 0.0
        consensus = max(0.0, min(1.0, consensus))
        avg_fit = fit_sum / n if n else 0.0
        hit_rate = self._recalc_hit_rate()
        hit_adj = 0.12 * (hit_rate - 0.5) * 2.0
        base = max(0.15, min(0.70,
             0.30 + 0.25 * min(1.0, n / 40.0) * consensus + hit_adj))
        out["global"] = {
            "n": n, "avg_fitness": round(avg_fit, 2),
            "direction_bias": round(g_bias, 4), "consensus": round(consensus, 3),
            "strat_weight_base": round(base, 3),
            "prefer_ensemble": consensus >= 0.5, "prefer_extended": n >= 20,
            "hit_rate": round(hit_rate, 3),
        }
        for sym, d in by_sym.items():
            db = d["db"] / (d["fs"] or 1e-6)
            out["by_symbol"][sym] = {
                "direction_bias": round(db, 4), "n": d["n"],
                "weight": round(0.30 + 0.30 * min(1.0, d["n"] / 10.0)
                                * min(1.0, abs(db)), 3),
            }
        self._tuning = out

    def last_backtest(self) -> Optional[dict]:
        """返回最近一次回测记录（供状态展示）。"""
        with self._lock:
            return dict(self._backtest_log[0]) if self._backtest_log else None

    # ------------------------------------------------------------------
    # 预测 → 回测中心（信号待验证）
    # ------------------------------------------------------------------
    def push_prediction(self, symbol: str, payload: dict) -> None:
        """预测操作板块产出研判时调用，推送待回测验证信号。"""
        rec = {"symbol": symbol}
        rec.update(payload or {})
        with self._lock:
            self._pending_predictions.insert(0, rec)
            self._pending_predictions = self._pending_predictions[:100]
        self.prediction_updated.emit(rec)

    def consume_pending_predictions(self) -> list:
        """回测中心消费待验证预测信号（返回并清空）。"""
        with self._lock:
            out = list(self._pending_predictions)
            self._pending_predictions.clear()
        return out

    def pending_count(self) -> int:
        """返回待回测验证的预测信号数量。"""
        with self._lock:
            return len(self._pending_predictions)


# 模块级单例：预测页与回测页 import 同一实例
BUS = LinkageBus()
