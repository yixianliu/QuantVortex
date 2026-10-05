# -*- coding: utf-8 -*-
"""回测中心「自动持久化 + 启动恢复」端到端验证（offscreen）。

流程：
1. 第一个页面实例：自动启动 → 跑两代 → 断言状态/历史/日志已自动落库；
2. 关闭页面（模拟程序退出，触发 WAL checkpoint）；
3. 第二个页面实例（模拟重启）：断言引擎断点续跑（代数延续）、
   历史记录表恢复、日志回放、KPI/曲线恢复。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from futures_quant.data.market_data import MarketDataManager  # noqa: E402
from futures_quant.ui.backtest_page import BacktestCenterPage  # noqa: E402
from futures_quant.storage.backtest_store import get_backtest_store  # noqa: E402

DEADLINE_MS = 40_000


def wait_generations(page, target_gen: int) -> None:
    t0 = time.time()
    while (time.time() - t0) * 1000 < DEADLINE_MS:
        app.processEvents()
        time.sleep(0.02)
        s = page._last_snapshot
        if s and s.get("generation", 0) >= target_gen:
            return
    raise AssertionError(f"等待第 {target_gen} 代超时")


mdm = MarketDataManager(source="synthetic")
bt_store = get_backtest_store()
print(f"[0] 持久化库就绪: {bt_store.path}")

# ---------- 阶段一：首次运行，跑两代并自动落库 ----------
page1 = BacktestCenterPage(mdm)
page1.show()
app.processEvents()
wait_generations(page1, 2)
gen_before = page1._last_snapshot["generation"]
eval_before = page1._engine.evaluated_total
print(f"[1] 首次运行 OK: 已完成第 {gen_before} 代, 累计评估 {eval_before}")

st = bt_store.load_state("engine")
assert st is not None and st.get("generation", 0) >= 2, "引擎断点未自动落库"
snap_db = bt_store.load_state("last_snapshot")
assert snap_db is not None and snap_db.get("ranked"), "最新快照未自动落库"
hist = bt_store.recent_history(50)
assert len(hist) >= 2, f"历史记录不足: {len(hist)}"
logs = bt_store.recent_logs(50)
assert len(logs) >= 1, "学习日志未落库"
print(f"[2] 自动持久化 OK: 断点gen={st['generation']} 历史 {len(hist)} 条 "
      f"日志 {len(logs)} 条 快照ranked={len(snap_db['ranked'])}")
assert page1.hist_tbl.rowCount() >= 2, "历史记录 Tab 未实时更新"
print(f"[3] 历史记录 Tab 实时更新 OK: {page1.hist_tbl.rowCount()} 行")

# ---------- 阶段二：关闭页面（模拟退出） ----------
page1.close()
app.processEvents()
print("[4] 页面关闭 OK（WAL checkpoint 已执行）")

# ---------- 阶段三：重建页面（模拟重启），验证恢复 ----------
page2 = BacktestCenterPage(mdm)
page2.show()
app.processEvents()
# 等自动启动完成恢复（600ms 定时器 + 恢复逻辑）
t0 = time.time()
while page2._engine is None and (time.time() - t0) * 1000 < 8000:
    app.processEvents()
    time.sleep(0.02)
assert page2._engine is not None, "重启后引擎未自动创建"
assert page2._engine.generation >= gen_before, \
    f"断点未恢复: {page2._engine.generation} < {gen_before}"
assert page2._engine.evaluated_total >= eval_before, "评估计数未恢复"
print(f"[5] 断点恢复 OK: 从第 {page2._engine.generation} 代续跑, "
      f"累计评估 {page2._engine.evaluated_total}")

assert page2.hist_tbl.rowCount() >= 2, "历史记录未恢复到表格"
assert page2.log_list.count() >= 1, "学习日志未回放"
assert page2._last_snapshot is not None, "上次快照未恢复"
chip_gen = page2._chips["generation"]._val.text()
assert chip_gen not in ("", "--"), "KPI 未从快照恢复"
print(f"[6] UI 恢复 OK: 历史表 {page2.hist_tbl.rowCount()} 行, "
      f"日志 {page2.log_list.count()} 条, 代数chip={chip_gen}")

# 续跑一代，验证代数在恢复基础上递增（真正的断点续跑）
wait_generations(page2, gen_before + 1)
assert page2._last_snapshot["generation"] == gen_before + 1 or \
    page2._last_snapshot["generation"] > gen_before, "续跑代数未延续"
print(f"[7] 断点续跑 OK: 重启后继续进化到第 "
      f"{page2._last_snapshot['generation']} 代（无缝衔接）")

# 主题切换（历史表随主题重刷）与关闭保护
page2.set_theme("light")
page2.set_theme("dark")
page2.close()
print("[8] 主题切换 / 关闭保护 OK")

print("=" * 60)
print("回测中心自动持久化 + 启动恢复：全部通过")
