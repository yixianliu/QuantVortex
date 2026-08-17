# -*- coding: utf-8 -*-
"""回测中心 ↔ KP预测 双向联动端到端验证（offscreen）。

验证 R3：
  A. 回测→预测：盈利策略库「🔮 预测」按钮跳转预测页并预载策略基因；
  B. 预测→回测：「🧪 回测此策略」按钮反向驱动回测中心手动回测（同基因）；
  C. 联动指标：backtest_linkage_for 暴露最优策略基因 best_gene；
  D. 基因透传：预测页将预载基因融合进策略信号（_merge_preloaded_strategy）；
  E. 历史缺陷修复：导航改用 stack.currentWidget()，symbol/gene 真正送达预测页。
"""
import os
import sys
import time
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

app = QApplication(sys.argv)

from futures_quant.data.market_data import MarketDataManager  # noqa: E402
from futures_quant.storage.analysis_store import AnalysisStore  # noqa: E402
from futures_quant.ui.backtest_page import BacktestCenterPage  # noqa: E402
from futures_quant.ui.predict_ops_page import PredictOpsPage  # noqa: E402
from futures_quant.core.metric_schema import backtest_linkage_for  # noqa: E402
from futures_quant.strategy.auto_evolve import (  # noqa: E402
    save_profitable, load_profitable, describe_gene, STORE_PATH,
)

fails = 0


def check(cond, msg):
    global fails
    status = "✅" if cond else "❌"
    print(f"{status} {msg}")
    if not cond:
        fails += 1


# ---- 构造主窗口桩（提供 _goto_page / stack.currentWidget）----
class _FakeSeries:
    def __init__(self, xs):
        self._x = xs

    def tolist(self):
        return self._x


class _FakeDF:
    def __init__(self, c, h, l):
        self._d = {"close": _FakeSeries(c), "high": _FakeSeries(h),
                   "low": _FakeSeries(l)}

    def __getitem__(self, k):
        return self._d[k]

    def __contains__(self, k):
        return k in self._d


class _FakeMW:
    def __init__(self, bt, pr):
        self._bt, self._pr = bt, pr
        self._target = None

    def _goto_page(self, key):
        self._target = self._pr if key == "predict" else self._bt

    @property
    def stack(self):
        return self

    def currentWidget(self):
        return self._target


# ---- 构造页面 ----
mdm = MarketDataManager(source="synthetic")
tmp_store = os.path.join(tempfile.gettempdir(), f"r3_analysis_{os.getpid()}.db")
store = AnalysisStore(tmp_store)
page_bt = BacktestCenterPage(mdm)
page_pr = PredictOpsPage(mdm, store)
mw = _FakeMW(page_bt, page_pr)
page_bt.window = lambda: mw
page_pr.window = lambda: mw
page_bt.show()
page_pr.show()
app.processEvents()

# ---- 准备一个合法策略基因（供双向联动透传）----
gene = page_bt._manual_gene("ma_cross")
gene_desc = describe_gene(gene)
sym = "rb.SHFE"
entry = {
    "symbol": sym, "symbol_name": "螺纹钢", "desc": gene_desc, "gene": gene,
    "metrics": {"total_return": 0.12, "annual_return": 0.18, "sharpe": 1.2,
                "max_drawdown": 0.08, "win_rate": 0.55},
    "found_at": "2026-07-28T00:00:00", "fitness": 9999.0,  # 主导，确保成为该品种最优
}

# =================== A. 回测 → 预测 ===================
print("\n[A] 回测中心「🔮 预测」→ KP预测 预载基因")
page_bt._fill_library([entry])
check(len(page_bt._lib_entries) == 1, "[A] 盈利策略库行已写入内存（_lib_entries）")
btn = page_bt.lib_tbl.cellWidget(0, 9)
check(btn is not None and isinstance(btn, QPushButton),
      "[A] 第 9 列「🔮 预测」按钮已渲染")
page_bt._lib_to_predict(0)
app.processEvents()
check(page_pr._preloaded_gene == gene, "[A] 预测页已预载该策略基因（_preloaded_gene）")
check(page_pr._preloaded_symbol == sym, "[A] 预测页记录预载品种（_preloaded_symbol）")
check(gene_desc in (page_pr.status_lbl.text() or ""),
      "[A] 状态栏展示「已载入回测策略基因」横幅")

# =================== C. 联动指标 best_gene ===================
print("\n[C] backtest_linkage_for 暴露最优策略基因")
# 备份 store 原文，待全部用例结束后「覆盖写回」（Windows 沙箱拦截 rename/delete）。
store_backup_bytes = None
if os.path.exists(STORE_PATH):
    with open(STORE_PATH, "rb") as f:
        store_backup_bytes = f.read()
save_profitable([entry])
link = backtest_linkage_for(sym)
check(link.get("has_backtest") is True, "[C] has_backtest=True")
check(link.get("best_gene") == gene, "[C] best_gene 与写入基因一致（预测→回测可反向取用）")
check(link.get("strategy_count") >= 1, "[C] strategy_count>=1")
expected_gene = gene  # 本节已把该基因设为该品种最优（fitness=9999）

# 冻结 store 写入：后台自动进化仍在跑，但不再持久化新策略，
# 保证 Section B 读取的 best_gene 与本节一致（稳定反向联动）。
import futures_quant.strategy.auto_evolve as _ae_mod  # noqa: E402
_ae_mod.save_profitable = lambda *a, **k: 0  # 覆盖写，避免并发改写最优基因

# =================== B. 预测 → 回测 ===================
print("\n[B] KP预测「🧪 回测此策略」→ 回测中心手动回测（同基因）")
# 等可能残留的自动代际结束，确保手动运行不被并发干扰
t0 = time.time()
while page_bt._gen_running and (time.time() - t0) * 1000 < 15000:
    app.processEvents()
    time.sleep(0.02)

page_pr.cur_symbol = sym
page_pr._goto_backtest_with_strategy()
app.processEvents()
check(page_bt._manual_mode is True, "[B] 跳转后回测中心切到「手动回测」模式")
check(page_bt._manual_sym_cb.currentData() == sym,
      "[B] 手动回测品种已定位到该品种")
check(page_bt._manual_gene_override == gene or page_bt._manual_gene_override is None,
      "[B] 基因已注入手动回测（override 或已被 __lib__ 消费）")
t0 = time.time()
while page_bt._manual_running and (time.time() - t0) * 1000 < 30000:
    app.processEvents()
    time.sleep(0.02)
check(not page_bt._manual_running, "[B] 反向驱动的手动回测后台完成")
check(page_bt._last_manual is not None, "[B] 回测结果已回传（_last_manual 非空）")
# 验证用的正是联动暴露的 best_gene：手动结果基因与联动最优基因一致
ran_gene = (page_bt._last_manual or {}).get("gene")
check(ran_gene == expected_gene, "[B] 手动回测实际运行的基因 == 联动最优基因(best_gene)")

# =================== D. 基因透传（预测融合） ===================
print("\n[D] 预测页将预载基因融合进策略信号")
page_pr._preloaded_gene = gene
page_pr._preloaded_symbol = sym
closes = [100.0] * 25 + [100.0 + i * 4 for i in range(5)]  # 末端抬升制造交叉
df = _FakeDF(closes, closes, closes)
sig = {"n": 0, "bias": 0.0, "long": 0, "short": 0, "detail": []}
out = page_pr._merge_preloaded_strategy(sym, df, sig)
check(out["n"] == 1, "[D] 策略计数 +1（预载策略已计入）")
check(len(out["detail"]) >= 1 and out["detail"][0].get("preloaded") is True,
      "[D] 策略明细首位为预载策略并标记 preloaded")
check(out.get("preloaded_dir") in (-1, 0, 1),
      "[D] 预载策略方向有效（preloaded_dir ∈ {-1,0,1}）")
check((out.get("long", 0) + out.get("short", 0)) == (1 if out.get("preloaded_dir") else 0),
      "[D] 多/空计数与方向一致")

# =================== E. 历史缺陷修复 ===================
print("\n[E] 导航不再受 PAGE_KEY 覆写影响（修复前 symbol 无法送达预测页）")
# 重新注入我们的策略库行（Section B 手动回测完成时 _fill_library 已用真实库重填）
page_bt._fill_library([entry])
app.processEvents()
# 直接验证：以 dict 形式确认 set_symbol 经当前页控件被调用
_reached = {"gene": None}
_orig = page_pr.set_symbol

def _wrap(s, p="D", gene=None):
    _reached["gene"] = gene
    return _orig(s, p, gene)
page_pr.set_symbol = _wrap
page_bt._lib_to_predict(0)
check(_reached["gene"] == gene, "[E] 经 stack.currentWidget 导航，基因确实送达预测页 set_symbol")

page_bt.close()
page_pr.close()
# 还原盈利策略库原文（覆盖写，不触发沙箱删除拦截）
if store_backup_bytes is not None and os.path.exists(STORE_PATH):
    with open(STORE_PATH, "wb") as f:
        f.write(store_backup_bytes)
print("=" * 60)
if fails == 0:
    print("回测↔预测 双向联动 端到端验证：全部通过")
else:
    print(f"回测↔预测 双向联动 端到端验证：{fails} 项失败")
    sys.exit(1)
