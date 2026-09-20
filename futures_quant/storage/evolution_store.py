"""M7.3 进化档案：把每次进化 run（基因 + 逐代 metrics + 收敛曲线）落盘并支持回看。

设计：
- 一个 run 对应 ``data/evolution/<run_id>.json``（run_id 默认时间戳 + 短哈希，可外部指定）。
- 原子写（复用 ``storage.json_store.AtomicJSON``）：崩溃不留半截文件。
- 每次 run 记录：创建时间、参数（世代数/种群/轨道）、逐代最佳基因与 metrics、
  收敛曲线（best/mean fitness）、最终 best_genome。
- 回看 API：
  - ``list_runs()`` → 按时间倒序的 run 摘要列表；
  - ``load(run_id)`` → 完整档案 dict；
  - ``convergence(run_id)`` → 收敛曲线 list；
  - 体积守卫：单次 run JSON < 阈值（默认 10MB）时正常写；超限截断逐代基因（保留每代 top-K）。

防未来函数 / 安全：只写本地文件，不联网；run_id 仅允许 [A-Za-z0-9_-]（防路径注入）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

__all__ = [
    "EvolutionStore",
    "DEFAULT_DIR",
    "MAX_RUN_BYTES",
]

# 项目根目录（futures_quant/storage -> futures_quant -> root）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DIR: str = os.path.join(ROOT, "data", "evolution")

# 单次 run 档案字节上限（默认 10MB，与方案「100 次进化 <10MB」对齐）
MAX_RUN_BYTES: int = 10 * 1024 * 1024

_RUNID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _make_run_id(seed: Optional[str] = None) -> str:
    """生成 run_id：时间戳 + 短哈希（seed 提供则增强确定性）。"""
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    h = hashlib.sha1((seed or str(ts)).encode("utf-8")).hexdigest()[:6]
    return f"{ts}_{h}"


class EvolutionStore:
    """进化档案存储。

    参数:
        path: 档案目录，默认 ``data/evolution``。
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or DEFAULT_DIR
        os.makedirs(self.path, exist_ok=True)

    # ---------------- 内部工具 ----------------
    @staticmethod
    def _sanitize_run_id(run_id: str) -> str:
        if not _RUNID_RE.match(run_id):
            raise ValueError(f"非法 run_id：{run_id!r}（仅允许 A-Za-z0-9_-）")
        return run_id

    def _run_path(self, run_id: str) -> str:
        return os.path.join(self.path, f"{self._sanitize_run_id(run_id)}.json")

    def _shrink_if_needed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """若落盘体积超过 MAX_RUN_BYTES，截断逐代 population（保留每代 top-K）。

        截断依据的是**将要写入磁盘的 JSON 体积**（而非原始 payload 对象），
        与体积守卫语义一致。
        """
        def serialized(b: Dict[str, Any]) -> int:
            return len(json.dumps(b, ensure_ascii=False).encode("utf-8"))

        if serialized(payload) <= MAX_RUN_BYTES:
            return payload
        top_k = 10
        gens = payload.get("generations")
        while isinstance(gens, list) and serialized(payload) > MAX_RUN_BYTES and top_k > 0:
            for g in gens:
                if isinstance(g, dict) and isinstance(g.get("population"), list):
                    g["population"] = g["population"][:top_k]
            top_k -= 1
        payload["__truncated__"] = True
        return payload

    # ---------------- 写入 ----------------
    def save_run(
        self,
        run_id: Optional[str],
        params: Dict[str, Any],
        generations: List[Dict[str, Any]],
        best: Dict[str, Any],
    ) -> str:
        """保存一次进化 run，返回 run_id。

        参数:
            run_id: 可选；None 时自动生成。
            params: 进化参数（世代数/种群/轨道/seed 等）。
            generations: 逐代记录 ``[{generation, best_fitness, best_genome, population?}]``。
            best: 最终 best（genome + fitness + metrics）。
        """
        run_id = run_id or _make_run_id()
        self._sanitize_run_id(run_id)
        payload: Dict[str, Any] = {
            "run_id": run_id,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "params": params,
            "generations": generations,
            "best": best,
        }
        payload = self._shrink_if_needed(payload)
        path = self._run_path(run_id)
        # 原子写
        fd, tmp = tempfile.mkstemp(dir=self.path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            # 先备份旧的好文件，再替换
            if os.path.exists(path):
                os.replace(path, path + ".bak")
            os.replace(tmp, path)
            # 首次写入后也确保存在一份 .bak，便于后续崩溃回退
            if not os.path.exists(path + ".bak"):
                import shutil
                shutil.copyfile(path, path + ".bak")
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        return run_id

    # ---------------- 读取 / 回看 ----------------
    def load(self, run_id: str) -> Dict[str, Any]:
        path = self._run_path(run_id)
        if not os.path.exists(path):
            raise FileNotFoundError(f"进化档案不存在：{run_id}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_with_fallback(self, run_id: str) -> Optional[Dict[str, Any]]:
        """读失败时尝试 .bak，再不行返回 None（与 json_store 崩溃恢复一致）。"""
        path = self._run_path(run_id)
        for p in (path, path + ".bak"):
            try:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f)
            except Exception:
                continue
        return None

    def convergence(self, run_id: str) -> List[Dict[str, Any]]:
        data = self.load(run_id)
        return [
            {"generation": g.get("generation"), "best": g.get("best_fitness")}
            for g in data.get("generations", [])
        ]

    def list_runs(self) -> List[Dict[str, Any]]:
        """按 created_at 倒序列出所有 run 摘要。"""
        out: List[Dict[str, Any]] = []
        for fn in os.listdir(self.path):
            if not fn.endswith(".json") or fn.endswith(".bak"):
                continue
            rid = fn[:-5]
            try:
                data = self.load(rid)
            except Exception:
                continue
            out.append({
                "run_id": rid,
                "created_at": data.get("created_at"),
                "n_generations": len(data.get("generations", [])),
                "best_fitness": (data.get("best") or {}).get("fitness"),
            })
        out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return out

    def size_bytes(self, run_id: str) -> int:
        return os.path.getsize(self._run_path(run_id))
