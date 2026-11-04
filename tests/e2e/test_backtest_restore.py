# -*- coding: utf-8 -*-
"""R7-7.3 / R7-7.2 端到端验证（offscreen）。

流程：
1. （7.3）自动进化跑两代产生历史记录 → 取一条自动记录 id → 调 _rerun_history(id)
   （一键复跑）→ 断言新增一条 MANUAL_GEN 历史行，且复跑基因的基因与源记录完全一致；
2. （7.2）复跑会把「品种+精确基因」写入 last_manual_config → 新建页面实例（模拟重启）
   → 切到手动模式 → 断言品种下拉与精确基因被自动预填。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from futures_quant.data.market_data import MarketDataManager  # noqa: E402
from futures_quant.ui.backtest_page import BacktestCenterPage, MANUAL_GEN  # noqa: E402
from futures_quant.storage.backtest_store import get_backtest_store  # noqa: E402

DEADLINE_MS = 45_000


def wait_generations(page, target):
    t0 = time.time()
    while (time.time() - t0) * 1000 < DEADLINE_MS:
        app.processEvents()
        time.sleep(0.02)
        s = page._last_snapshot
        if s and s.get("generation", 0) >= target:
            return
    raise AssertionError(f"等待第 {target} 代超时")


def wait_manual(page):
    t0 = time.time()
    while (time.time() - t0) * 1000 < DEADLINE_MS:
        app.processEvents()
        time.sleep(0.02)
        if page._last_manual is not None:
            return
    raise AssertionError("等待手动回测完成超时")


def manual_rows_after(before_id):
    return [h for h in bt_store.recent_history(300)
            if h.get("generation") == MANUAL_GEN and h.get("id")
            and h["id"] > before_id]


mdm = MarketDataManager(source="synthetic")
bt_store = get_backtest_store()
print(f"[0] 持久化库就绪: {bt_store.path}")

# ---------- 阶段一：自动进化跑两代，产生历史记录 ----------
page = BacktestCenterPage(mdm)
page.show()
app.processEvents()
wait_generations(page, 2)
print(f"[1] 自动进化 OK: 已完成第 {page._last_snapshot['generation']} 代")

# ---------- 阶段二：7.3 历史记录表「🔁复跑」 ----------
hist = bt_store.recent_history(50)
auto_rows = [h for h in hist
             if h.get("generation") != MANUAL_GEN and h.get("id")]
assert auto_rows, "无可用自动历史记录用于复跑"
src = auto_rows[0]
src_detail = bt_store.get_history_detail(src["id"])
assert src_detail and src_detail.get("gene") and src_detail.get("symbol"), \
    "源记录缺少基因/品种信息"
print(f"[2] 选定源记录 id={src['id']} symbol={src_detail['symbol']} "
      f"entry={src_detail['gene'].get('entry')}")

max_id_before = max([h["id"] for h in bt_store.recent_history(300)
                     if h.get("generation") == MANUAL_GEN and h.get("id")],
                    default=-1)
page._rerun_history(src["id"])
wait_manual(page)
new_rows = manual_rows_after(max_id_before)
assert new_rows, \
    f"一键复跑未新增基因匹配的 MANUAL_GEN 历史行 (before_id={max_id_before})"
# 验证最新新增 Manual 行的基因与源记录一致（恢复「完整配置」语义）
newest = new_rows[0]
nd = bt_store.get_history_detail(newest["id"])
assert nd.get("gene") == src_detail["gene"], \
    f"复跑基因与源记录不一致: {nd.get('gene')} != {src_detail['gene']}"
assert page._last_manual is not None, "复跑后 _last_manual 未设置"
print(f"[3] 7.3 一键复跑 OK: 新增 Manual 历史行 id={newest['id']}，"
      f"基因与源记录完全一致")

# 复跑同会把手动配置落盘，供 7.2 预填验证
cfg = bt_store.load_state("last_manual_config")
assert cfg and cfg.get("symbol") and cfg.get("gene"), "手动配置未持久化"
print(f"[4] 7.2 手动配置已持久化: symbol={cfg['symbol']}")

# ---------- 阶段三：模拟重启，验证手动模式预填 ----------
page.close()
app.processEvents()

page2 = BacktestCenterPage(mdm)
page2.show()
app.processEvents()
t0 = time.time()
while page2._engine is None and (time.time() - t0) * 1000 < 8000:
    app.processEvents()
    time.sleep(0.02)
assert page2._engine is not None, "重启后引擎未自动创建"

# 切到手动回测模式 → 应自动预填上次配置
page2._rb_manual.setChecked(True)
app.processEvents()
time.sleep(0.15)
app.processEvents()

assert page2._manual_sym_cb.currentData() == cfg["symbol"], \
    (f"手动模式未预填品种: {page2._manual_sym_cb.currentData()} "
     f"!= {cfg['symbol']}")
assert page2._manual_gene_override == cfg["gene"], \
    "手动模式未预填精确基因"
print(f"[5] 7.2 重启预填 OK: 手动模式自动预填品种 "
      f"{page2._manual_sym_cb.currentData()} + 精确基因")

page2.close()
print("=" * 60)
print("R7-7.3 一键复跑 / R7-7.2 手动配置预填：全部通过")
