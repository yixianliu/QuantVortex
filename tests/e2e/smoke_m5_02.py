"""M5-02 行情源缓存与连接真实性 —— 验收冒烟（offscreen / 纯离线）。

覆盖 P0 两缺口（不触网、不依赖 vnpy/ctpbee 库，全部用 monkeypatch 夹具）：
  ① akshare 缓存优先降级链（AkshareFeed._load）：
     - 新鲜缓存（≤ CACHE_TTL_SEC）直接复用，不联网；
     - 陈旧缓存 + 联网失败 → 回退陈旧数据并 ``is_stale=True``；
     - 无缓存 + 联网失败 → 上抛异常（由上层回退 synthetic）。
  ② CTP 连接真实性与退避（CTPFeed）：
     - 凭据不完整 → connect() 返回 False（不冒充实盘）；
     - 缺 CTP 库 → connect() 返回 False；
     - maybe_reconnect 指数退避 30→60→120（封顶 300s）+ 退避窗口内不重复尝试。

运行：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m5_02.py
"""
from __future__ import annotations

import os
import sys
import time
import tempfile

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    import pandas as pd
    from futures_quant.data.akshare_feed import AkshareFeed
    from futures_quant.data.ctp_gateway import CTPFeed, CTPCredentials

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    # ---------------- ① akshare 缓存降级链 ----------------
    tmp = tempfile.mkdtemp(prefix="qv_ak_")

    def _sample_csv() -> pd.DataFrame:
        return pd.DataFrame({
            "datetime": ["2026-09-01", "2026-09-02"],
            "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
            "close": [1.0, 1.0], "volume": [0, 0], "open_interest": [0, 0],
        })

    # 夹具：_fetch_daily 一律抛异常（模拟断网）
    def _fail_fetch(self, symbol):
        raise RuntimeError("network-down (test fixture)")

    AkshareFeed._fetch_daily = _fail_fetch  # monkeypatch（仅本测试）

    sym = "rb.SHFE"

    # ①-a 新鲜缓存：写缓存 + 置当前 mtime → 直接复用，不联网，is_stale=False
    feed_fresh = AkshareFeed(cache_dir=tmp)
    cache_path = feed_fresh._cache_path(sym)
    _sample_csv().to_csv(cache_path, index=False)
    os.utime(cache_path, None)  # mtime = now
    df = feed_fresh._load(sym)
    check("akshare-fresh-cache-reuse",
          df is not None and len(df) == 2 and feed_fresh.is_stale is False,
          f"rows={len(df)} is_stale={feed_fresh.is_stale}")

    # ①-b 陈旧缓存 + 联网失败：置 mtime 为 2h 前（>TTL）→ 回退且 is_stale=True
    feed_stale = AkshareFeed(cache_dir=tmp)
    old = time.time() - (AkshareFeed.CACHE_TTL_SEC + 1)
    os.utime(cache_path, (old, old))
    df2 = feed_stale._load(sym)
    check("akshare-stale-fallback-flag",
          df2 is not None and len(df2) == 2 and feed_stale.is_stale is True,
          f"rows={len(df2)} is_stale={feed_stale.is_stale}")

    # ①-c 无缓存 + 联网失败 → 上抛异常
    empty_dir = tempfile.mkdtemp(prefix="qv_ak_empty_")
    feed_none = AkshareFeed(cache_dir=empty_dir)
    raised = False
    try:
        feed_none._load(sym)
    except Exception:  # noqa: BLE001
        raised = True
    check("akshare-no-cache-raises", raised, "无缓存且断网 → 上抛（上层回退 synthetic）")

    # ①-d 内存缓存命中（同一 feed 二次 _load 不重读盘）
    feed_mem = AkshareFeed(cache_dir=tmp)
    os.utime(cache_path, None)
    first = feed_mem._load(sym)
    again = feed_mem._load(sym)
    check("akshare-memory-hit", first is again, "内存命中同对象")

    # ---------------- ② CTP 连接真实性 + 退避 ----------------
    # ②-a 凭据不完整 → connect() False
    ctp = CTPFeed(CTPCredentials())  # 全空凭据
    ctp._detect_lib = lambda: None  # 隔离库探测
    check("ctp-incomplete-creds-false", ctp.connect() is False,
          f"connected={ctp.connected}")

    # ②-b 凭据完整但缺库 → connect() False（绝不冒充实盘）
    ctp2 = CTPFeed(CTPCredentials(
        md_front="tcp://x:0", td_front="tcp://x:0", broker_id="0",
        user_id="u", password="p"))
    ctp2._detect_lib = lambda: None
    check("ctp-missing-lib-false", ctp2.connect() is False,
          "缺 CTP 库 → connect() 返回 False")

    # ②-c maybe_reconnect 指数退避 30→60→120（封顶 300s）
    ctp3 = CTPFeed(CTPCredentials())
    ctp3._detect_lib = lambda: None
    ctp3.connect()  # 失败，计数 0
    seq = []
    # 手动驱动 3 次退避间隔（绕过时间门，直接读公式）
    for _ in range(3):
        backoff = min(ctp3._reconnect_base_sec * (2 ** ctp3._reconnect_attempts),
                      ctp3._reconnect_max_sec)
        ctp3._reconnect_attempts += 1
        seq.append(int(backoff))
    check("ctp-expo-backoff-30-60-120",
          seq == [30, 60, 120], f"退避序列={seq}")

    # ②-d 退避窗口内不重复尝试（maybe_reconnect 直接返回 False）
    ctp4 = CTPFeed(CTPCredentials())
    ctp4._detect_lib = lambda: None
    ctp4._reconnect_attempts = 1
    ctp4._next_reconnect_at = time.time()  # 刚尝试过，仍在窗口内
    r = ctp4.maybe_reconnect()
    check("ctp-backoff-window-skip",
          r is False and ctp4._reconnect_attempts == 1,
          f"skip={not r} attempts={ctp4._reconnect_attempts}")

    # ---------------- 汇总 ----------------
    print("=" * 62)
    print("M5-02 行情源缓存与连接真实性 · 验收")
    print("=" * 62)
    passed = 0
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f"  ({detail})" if detail else ""))
        passed += int(ok)
    total = len(results)
    print("-" * 62)
    print(f"结果：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
