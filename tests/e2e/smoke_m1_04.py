"""M1-04 存储层并发安全与备份修正 smoke 测试。

覆盖 DoD：
    1. AtomicJSON 并发 8 线程写 200 次后 JSON 可 json.load
    2. 首次写入存在 .bak
    3. 备份顺序：先 copy(主→bak) 再 os.replace(tmp→主)
    4. EvolutionStore.save_run 走 _SAVE_LOCK（monkeypatch 计数）
    5. _shrink_if_needed 最多 3 轮（避免 O(n²)）
    6. auto_evolve.save_profitable 走 _STRATEGY_STORE_LOCK
    7. 并发 8 线程调 save_profitable 后 JSON 仍可解析
    8. 并发 8 线程 save_run 后 JSON 仍可解析
    9. 三个锁都是 RLock 且可重入

运行:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m1_04.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from unittest.mock import patch

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from futures_quant.storage import json_store as js_mod  # noqa: E402
from futures_quant.storage.json_store import AtomicJSON  # noqa: E402
from futures_quant.storage import evolution_store as es_mod  # noqa: E402
from futures_quant.storage.evolution_store import EvolutionStore  # noqa: E402
from futures_quant.strategy import auto_evolve as ae_mod  # noqa: E402


# =============================================================
# 测试组 1: AtomicJSON 并发写与 .bak
# =============================================================
def test_01_concurrent_writes_produce_valid_json():
    """8 线程并发写 200 次后，最终文件必须能被 json.load 解析。"""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "store.json")
        store = AtomicJSON(path, default={"k": 0}, version=1)

        barrier = threading.Barrier(8)
        errors: list[Exception] = []

        def worker(tid: int):
            try:
                barrier.wait()
                for i in range(25):  # 8*25 = 200
                    store.set("counter", tid * 100 + i)
                    store.set("thread", tid)
                    store.save()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发写报错: {errors[:3]}"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "__version__" in data
        assert "counter" in data


def test_02_first_write_creates_bak():
    """首次 save 后必须存在 .bak 备份。"""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "first.json")
        assert not os.path.exists(path + ".bak")
        store = AtomicJSON(path, default={"a": 1}, version=1)
        store.set("b", 2)
        ok = store.save()
        assert ok is True
        assert os.path.exists(path), "主文件缺失"
        assert os.path.exists(path + ".bak"), "首次写入未生成 .bak"
        with open(path, encoding="utf-8") as f:
            main = json.load(f)
        with open(path + ".bak", encoding="utf-8") as f:
            bak = json.load(f)
        assert main == bak


def test_03_backup_order_copy_before_replace():
    """备份顺序必须是「先 copy 主→bak，再 os.replace tmp→主」。

    旧代码 os.replace(主→bak) 会让主文件在 replace 失败时消失。
    """
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "order.json")
        store = AtomicJSON(path, default={"x": 1}, version=1)
        store.save()  # 先建立主文件

        calls: list[str] = []
        orig_copy = js_mod.shutil.copyfile
        orig_replace = js_mod.os.replace

        def spy_copy(*a, **kw):
            calls.append("copy")
            return orig_copy(*a, **kw)

        def spy_replace(*a, **kw):
            calls.append("replace")
            return orig_replace(*a, **kw)

        with patch.object(js_mod.shutil, "copyfile", spy_copy), \
             patch.object(js_mod.os, "replace", spy_replace):
            store.set("x", 2)
            store.save()

        assert len(calls) >= 2, f"预期至少 copy+replace 两次调用，实际 {calls}"
        # 关键：第一次操作必须是 copy（备份旧主），最后一次才是 replace
        assert calls[0] == "copy", f"备份顺序错误：第一个操作应为 copy，实际 {calls}"
        assert calls[-1] == "replace", f"最后操作应为 replace，实际 {calls}"
        first_copy = calls.index("copy")
        last_replace = len(calls) - 1 - calls[::-1].index("replace")
        assert first_copy < last_replace, f"copy 未在 replace 前完成: {calls}"


def test_03b_evolution_store_backup_order():
    """EvolutionStore.save_run 备份顺序同样必须「先 copy 再 replace」。"""
    with tempfile.TemporaryDirectory() as td:
        store = EvolutionStore(path=td)
        store.save_run("r_order", {"n": 1}, [{"generation": 0, "best_fitness": 0.1, "population": [{"g": 1}]}],
                       {"genome": {"a": 1}, "fitness": 0.1})

        calls: list[str] = []
        orig_copy = es_mod.shutil.copyfile
        orig_replace = es_mod.os.replace

        def spy_copy(*a, **kw):
            calls.append("copy")
            return orig_copy(*a, **kw)

        def spy_replace(*a, **kw):
            calls.append("replace")
            return orig_replace(*a, **kw)

        with patch.object(es_mod.shutil, "copyfile", spy_copy), \
             patch.object(es_mod.os, "replace", spy_replace):
            store.save_run("r_order", {"n": 2},
                           [{"generation": 0, "best_fitness": 0.2, "population": [{"g": 1}]}],
                           {"genome": {"a": 1}, "fitness": 0.2})

        # 第二次写入时主文件已存在，所以有 copy
        assert calls, "第二次写入未触发 copy/replace 调用"
        assert calls[0] == "copy", f"备份顺序错误：第一个操作应为 copy，实际 {calls}"
        assert "replace" in calls, f"应包含 replace 调用，实际 {calls}"


# =============================================================
# 测试组 2: EvolutionStore.save_run 走锁
# =============================================================
def test_04_save_run_uses_save_lock():
    """EvolutionStore.save_run 必须走 _SAVE_LOCK。"""
    with tempfile.TemporaryDirectory() as td:
        store = EvolutionStore(path=td)
        lock_enter_count = 0

        class SpyRLock:
            def __enter__(self):
                nonlocal lock_enter_count
                lock_enter_count += 1
                return self

            def __exit__(self, *a):
                return False

        orig_lock = es_mod._SAVE_LOCK
        es_mod._SAVE_LOCK = SpyRLock()
        try:
            store.save_run("r_lock", {"n": 1},
                           [{"generation": 0, "best_fitness": 0.1, "population": [{"g": 1}]}],
                           {"genome": {"a": 1}, "fitness": 0.1})
        finally:
            es_mod._SAVE_LOCK = orig_lock

        assert lock_enter_count >= 1, f"save_run 未进入 _SAVE_LOCK，计数={lock_enter_count}"


def test_05_shrink_if_needed_max_three_rounds():
    """_shrink_if_needed 最多 3 轮（避免 O(n²) 序列化）。"""
    # 常量断言
    assert es_mod._SHRINK_MAX_ROUNDS == 3
    assert es_mod._SHRINK_TOP_K_STEP == 2

    # 用一个大 payload 触发 shrink，验证 population 被裁剪
    store = EvolutionStore(path=tempfile.mkdtemp())
    # 构造超过 10MB 的 payload：每代 500 个基因，基因字典较大
    _pad = "x" * 100
    big_population = [{"f": f"feature_{i}_{_pad}", "v": i} for i in range(500)]
    gens = [{"generation": i, "best_fitness": 0.1 * i, "population": list(big_population)}
            for i in range(200)]
    payload = {"run_id": "big", "generations": gens}

    shrunken = store._shrink_if_needed(payload)

    # shrink 后应标记 __truncated__
    assert shrunken.get("__truncated__") is True
    # 至少一代被裁剪
    any_trimmed = any(len(g["population"]) < 500 for g in shrunken["generations"])
    assert any_trimmed, "_shrink_if_needed 未裁剪任何 generation.population"

    # 验证：即使 top_k 变到 0，也不会死循环（3 轮上限生效）
    # 构造一个极端情况：即使裁剪到最小，体积仍超限
    store2 = EvolutionStore(path=tempfile.mkdtemp())
    extreme_gens = [{"generation": i, "best_fitness": 0.1, "population": list(big_population)}
                    for i in range(5000)]
    payload2 = {"run_id": "extreme", "generations": extreme_gens}
    start = time.time()
    shrunken2 = store2._shrink_if_needed(payload2)
    elapsed = time.time() - start
    assert shrunken2.get("__truncated__") is True
    # 关键：极端情况也不能跑很久（3 轮上限）
    assert elapsed < 30.0, f"shrink 耗时过长 {elapsed:.1f}s，可能未受 3 轮上限约束"


def test_06_save_profitable_uses_lock():
    """auto_evolve.save_profitable 必须走 _STRATEGY_STORE_LOCK。"""
    with tempfile.TemporaryDirectory() as td:
        orig_store = ae_mod.STORE_PATH
        orig_backup = ae_mod.BACKUP_PATH
        ae_mod.STORE_PATH = os.path.join(td, "profitable.json")
        ae_mod.BACKUP_PATH = ae_mod.STORE_PATH + ".backup"

        lock_enter_count = 0

        class SpyRLock:
            def __enter__(self):
                nonlocal lock_enter_count
                lock_enter_count += 1
                return self

            def __exit__(self, *a):
                return False

        orig_lock = ae_mod._STRATEGY_STORE_LOCK
        ae_mod._STRATEGY_STORE_LOCK = SpyRLock()
        try:
            ae_mod.save_profitable([{"gene": {"a": 1}, "fitness": 0.9}])
        finally:
            ae_mod._STRATEGY_STORE_LOCK = orig_lock
            ae_mod.STORE_PATH = orig_store
            ae_mod.BACKUP_PATH = orig_backup

        assert lock_enter_count >= 1, "save_profitable 未进入 _STRATEGY_STORE_LOCK"


def test_07_concurrent_save_profitable_valid_json():
    """8 线程并发 save_profitable 后 JSON 仍可解析。"""
    with tempfile.TemporaryDirectory() as td:
        orig_store = ae_mod.STORE_PATH
        orig_backup = ae_mod.BACKUP_PATH
        ae_mod.STORE_PATH = os.path.join(td, "profitable.json")
        ae_mod.BACKUP_PATH = ae_mod.STORE_PATH + ".backup"
        try:
            barrier = threading.Barrier(8)
            errors: list[Exception] = []

            def worker(tid: int):
                try:
                    barrier.wait()
                    for i in range(25):  # 8*25 = 200 次写入
                        ae_mod.save_profitable([
                            {"gene": {"t": tid, "i": i}, "fitness": tid * 100 + i}
                        ])
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"并发 save_profitable 报错: {errors[:3]}"
            with open(ae_mod.STORE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, (list, dict))
        finally:
            ae_mod.STORE_PATH = orig_store
            ae_mod.BACKUP_PATH = orig_backup


def test_08_concurrent_save_run_valid_json():
    """8 线程并发 save_run 后 JSON 仍可解析。"""
    with tempfile.TemporaryDirectory() as td:
        store = EvolutionStore(path=td)

        barrier = threading.Barrier(8)
        errors: list[Exception] = []

        def worker(tid: int):
            try:
                barrier.wait()
                for i in range(10):
                    run_id = f"r_{tid}_{i}"
                    store.save_run(
                        run_id,
                        {"n": 3, "tid": tid, "i": i},
                        [{"generation": 0, "best_fitness": 0.1 * (tid + i), "population": [{"g": tid}]}],
                        {"genome": {"t": tid}, "fitness": 0.5},
                    )
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发 save_run 报错: {errors[:3]}"
        files = list(Path(td).glob("r_*.json"))
        assert len(files) == 80, f"应写入 80 个 run，实际 {len(files)}"
        for f in files:
            with open(f, encoding="utf-8") as fh:
                json.load(fh)  # 必须可解析


def test_09_rlock_allows_reentrant_enter():
    """三个锁都必须是 RLock 且可重入。"""
    assert isinstance(js_mod._SAVE_LOCK, type(threading.RLock()))
    assert isinstance(es_mod._SAVE_LOCK, type(threading.RLock()))
    assert isinstance(ae_mod._STRATEGY_STORE_LOCK, type(threading.RLock()))

    with js_mod._SAVE_LOCK:
        with js_mod._SAVE_LOCK:
            pass
    with es_mod._SAVE_LOCK:
        with es_mod._SAVE_LOCK:
            pass
    with ae_mod._STRATEGY_STORE_LOCK:
        with ae_mod._STRATEGY_STORE_LOCK:
            pass


# =============================================================
# Runner
# =============================================================
def _run():
    tests = [
        ("1. AtomicJSON 8线程×200次写后 JSON 可解析", test_01_concurrent_writes_produce_valid_json),
        ("2. 首次写入存在 .bak", test_02_first_write_creates_bak),
        ("3a. AtomicJSON 备份顺序：先 copy 再 replace", test_03_backup_order_copy_before_replace),
        ("3b. EvolutionStore 备份顺序：先 copy 再 replace", test_03b_evolution_store_backup_order),
        ("4. EvolutionStore.save_run 走 _SAVE_LOCK", test_04_save_run_uses_save_lock),
        ("5. _shrink_if_needed 最多 3 轮", test_05_shrink_if_needed_max_three_rounds),
        ("6. save_profitable 走 _STRATEGY_STORE_LOCK", test_06_save_profitable_uses_lock),
        ("7. 并发 8 线程 save_profitable 后 JSON 可解析", test_07_concurrent_save_profitable_valid_json),
        ("8. 并发 8 线程 save_run 后 JSON 可解析", test_08_concurrent_save_run_valid_json),
        ("9. 三个锁都是 RLock 且可重入", test_09_rlock_allows_reentrant_enter),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except Exception:
            print(f"  ✗ {name}")
            traceback.print_exc()
    print(f"\nM1-04 smoke: {passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    ok = _run()
    sys.exit(0 if ok else 1)
