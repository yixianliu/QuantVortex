"""M4-10 主线程去阻塞 —— 验收冒烟（offscreen）。

M4-10 四个目标点代码已落地（含 `M4-10` 注释），本测试补齐 DoD 要求的可执行验收：
  ① 构造期不发网络请求：`MainWindow.__init__` 不直接调 `mdm.connect()`，
     而是 `QTimer` singleShot 延迟到首帧后 `_reconnect`。
  ② `mdm.connect()` 移入 Worker：`_reconnect` 经 `_run_worker` 执行，主线程不阻塞。
  ③ `market_overview._refresh_all` 的全景 `compute_panorama` 结果 5s 缓存：
     `_get_panorama` 命中（同 key ≤5s）/ 过期（>5s 返 None）行为级验证。
  ④ 真实源 get_recent 节流至 2s + 子线程：`LIVE_RECENT_INTERVAL_MS == 2000`，
     且真实源 `start_live` 走 `LiveDataWorker`（QThread），非合成 QTimer。

运行：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m4_10.py
"""
from __future__ import annotations

import os
import sys
import time

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


def main() -> int:
    app = None
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from futures_quant.data.market_data import MarketDataManager
    from futures_quant.storage.analysis_store import AnalysisStore
    from futures_quant.ui.market_overview_page import MarketOverviewPage
    from futures_quant.data import market_data as md_mod

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    # ---------------- ① 构造期不发网络请求（延迟连接） ----------------
    import inspect
    from futures_quant.ui.main_window import MainWindow
    src_init = inspect.getsource(MainWindow.__init__)
    check("init-no-direct-connect",
          "mdm.connect()" not in src_init,
          "MainWindow.__init__ 不直接调 connect()")
    check("init-deferred-connect",
          "_connect_deferred" in src_init or "QTimer" in src_init,
          "连接经 QTimer 延迟到首帧后")

    # ---------------- ② connect 移入 Worker ----------------
    src_rec = inspect.getsource(MainWindow._reconnect)
    check("connect-via-worker",
          "_run_worker" in src_rec and "mdm.connect()" in src_rec,
          "_reconnect 经 _run_worker 执行 connect()（主线程不阻塞）")
    check("connect-worker-timeout",
          "timeout_ms" in src_rec, "connect worker 带超时上限")

    # ---------------- ③ 全景 5s 缓存（行为级） ----------------
    mdm = MarketDataManager(source="synthetic")
    store = AnalysisStore(path="data/quant_analysis_test.db")
    ov = MarketOverviewPage(mdm, store, config=None, session=None)

    check("pano-cache-ttl-5s",
          ov._PANO_CACHE_TTL == 5.0, f"TTL={ov._PANO_CACHE_TTL}")

    # 命中：写入后立即读 → 返回同一 DataFrame
    import pandas as pd
    sample = pd.DataFrame({"x": [1, 2, 3]})
    ov._put_panorama(sample)
    got = ov._get_panorama()
    check("pano-cache-hit",
          got is sample, "5s 内同 key 命中缓存（同一对象）")

    # 过期：把时间戳回拨 > TTL → 返回 None（触发重算）
    key = (ov.cur_period, ov.cur_cat)
    ov._pano_cache_ts[key] = time.time() - (ov._PANO_CACHE_TTL + 1.0)
    check("pano-cache-expired",
          ov._get_panorama() is None, ">5s 后缓存过期返 None")

    # 顺序修复（M4-10③ 回归守护）：_refresh_all 内 _refresh_watch 先于
    # _refresh_pano，若 watch 只读缓存则首次必空；改用 _ensure_panorama
    # 统一「读缓存→缺失则计算回填」后，_refresh_all 应令 watch 有行。
    ov._pano_cache.clear()
    ov._pano_cache_ts.clear()
    ov._refresh_all()
    check("pano-order-refresh-populates-watch",
          ov.watch.rowCount() > 0, f"watch={ov.watch.rowCount()} 行")

    # ---------------- ④ 真实源 get_recent 节流 2s + 子线程 ----------------
    check("live-recent-interval-2s",
          md_mod.LIVE_RECENT_INTERVAL_MS == 2000,
          f"LIVE_RECENT_INTERVAL_MS={md_mod.LIVE_RECENT_INTERVAL_MS}")

    from PyQt6.QtCore import QThread
    check("live-worker-is-thread",
          issubclass(md_mod.LiveDataWorker, QThread),
          "LiveDataWorker 继承 QThread（子线程执行）")

    # 真实源 start_live 走 LiveDataWorker 而非合成 QTimer：源码级断言
    src_live = inspect.getsource(MarketDataManager.start_live)
    check("real-source-via-live-worker",
          "LiveDataWorker" in src_live and "_live_worker.start()" in src_live,
          "真实源实时刷新经 LiveDataWorker.start() 子线程")

    # ---------------- 汇总 ----------------
    print("=" * 62)
    print("M4-10 主线程去阻塞 · 验收")
    print("=" * 62)
    passed = 0
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f"  ({detail})" if detail else ""))
        passed += int(ok)
    total = len(results)
    print("-" * 62)
    print(f"结果：{passed}/{total} 通过")

    try:
        from PyQt6.QtGui import QCloseEvent
        ov.closeEvent(QCloseEvent())
    except Exception:  # noqa: BLE001
        pass

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
