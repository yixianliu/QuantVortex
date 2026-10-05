"""M3-10 验证：模型卡片（Model Card）与状态透明化。

验收点（对应 UPGRADE_PLAN_V5 M3-10）：
  ① 定义 ModelCard{name, enabled, is_stub, train_range, n_samples, metrics,
     known_limits}（实现另加 backend / trained / display）；
  ② 为 7 个模型生成卡片：lstm_numpy / ridge / ensemble / tcn / transformer /
     garch / ppo；
  ③ 面板显示「TCN：占位实现（未训练）」，is_stub=True 的整行标灰并注明「占位实现」；
  ④ 装上/卸下 torch 时状态实时更新（probe_module 每次实时探测，不缓存）。
"""
import importlib.util
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'NG'}] {name}" + (f" — {detail}" if detail else ""))


from futures_quant.ai.model_card import (  # noqa: E402
    COLUMNS, ModelCard, cards_to_rows, collect_model_cards, format_cards_text,
    probe_module,
)

# 文档 M3-10 列 7 个；实现额外补了 gbm（M3-06 实装的外部主模型通道，
# 见 model_card.collect_model_cards 的「文档偏差」注释）。
EXPECTED = {"lstm_numpy", "ridge", "ensemble", "tcn", "transformer", "garch", "ppo"}
EXTRA = {"gbm"}


def _make_df(n=300, seed=7, base=3500.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.009, n)
    close = base * np.exp(np.cumsum(r))
    return pd.DataFrame(
        {
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close * (1 + np.abs(rng.normal(0, 0.004, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.004, n))),
            "close": close,
            "volume": rng.integers(1000, 9000, n).astype(float),
        },
        index=pd.date_range("2023-01-02", periods=n, freq="D"),
    )


# ---------------------------------------------------------------- ① 数据结构
print("\n测试 ①: ModelCard 数据结构字段完整")
flds = set(ModelCard.__dataclass_fields__.keys())
need = {"name", "enabled", "is_stub", "train_range", "n_samples",
        "metrics", "known_limits"}
check("文档要求的 7 个字段齐备", need <= flds, str(sorted(flds)))
check("扩展字段 backend/trained/display 存在",
      {"backend", "trained", "display"} <= flds)

c_empty = ModelCard(name="x")
check("默认 is_stub=False / enabled=False",
      (c_empty.is_stub, c_empty.enabled) == (False, False))
check("默认 n_samples=0 / train_range=None",
      c_empty.n_samples == 0 and c_empty.train_range is None)

# ---------------------------------------------------------------- ② 卡片集合
print("\n测试 ②: 7 个模型卡片全部生成")
cards = collect_model_cards()
names = [c.name for c in cards]
check("文档要求的 7 个模型全部有卡片", EXPECTED <= set(names), str(names))
check("额外补充 gbm（M3-06 外部主模型通道）", EXTRA <= set(names), str(names))
check("无重复卡片", len(names) == len(set(names)), str(names))
check("每个卡片都有非空中文显示名",
      all(c.label and c.label != c.name for c in cards),
      str([c.label for c in cards]))
check("每个卡片都写明已知局限（非空）",
      all(len(c.known_limits) >= 1 for c in cards),
      str({c.name: len(c.known_limits) for c in cards}))
check("每个卡片都有 backend", all(c.backend for c in cards),
      str([c.backend for c in cards]))

# ---------------------------------------------------------------- ③ 占位实现
print("\n测试 ③: 占位实现（is_stub）标注与「TCN：占位实现（未训练）」")
by = {c.name: c for c in cards}
tcn = by["tcn"]
check("TCN 被标为占位实现", tcn.is_stub is True)
check("TCN 状态文本 = 「占位实现（未训练）」",
      tcn.status_text() == "占位实现（未训练）", tcn.status_text())
txt = format_cards_text(cards)
check("渲染文本含「TCN（因果膨胀卷积）：占位实现（未训练）」",
      "TCN（因果膨胀卷积）：占位实现（未训练）" in txt,
      [l for l in txt.splitlines() if l.startswith("TCN")][:1])
check("TCN 未训练时训练区间/样本量为空",
      tcn.train_range is None and tcn.n_samples == 0)
check("TCN 局限注明「非端到端训练」",
      any("非端到端" in s for s in tcn.known_limits), str(tcn.known_limits))
check("LSTM / 岭回归 / 集成 不是占位实现",
      not by["lstm_numpy"].is_stub and not by["ridge"].is_stub
      and not by["ensemble"].is_stub)


# ------------------------------------------------- ④ 依赖装卸 → 状态实时更新
print("\n测试 ④: 装上/卸下 torch / arch 时状态实时更新")
_real_find_spec = importlib.util.find_spec


def _stub_find_spec(missing):
    def _f(name, *a, **k):
        if name in missing:
            return None
        return _real_find_spec(name, *a, **k)
    return _f


check("probe_module 对存在的模块返回 True", probe_module("json") is True)
check("probe_module 对不存在的模块返回 False",
      probe_module("__definitely_not_a_pkg_xyz__") is False)

have_torch = _real_find_spec("torch") is not None
have_arch = _real_find_spec("arch") is not None
print(f"     （本机实际：torch={have_torch}, arch={have_arch}）")

# 模拟「卸下 torch」
importlib.util.find_spec = _stub_find_spec({"torch"})
try:
    c_off = {c.name: c for c in collect_model_cards()}
finally:
    importlib.util.find_spec = _real_find_spec
# 模拟「装上 torch」
class _FakeTorchSpec:      # 仅需一个非 None 对象即可
    name = "torch"
importlib.util.find_spec = lambda n, *a, **k: (
    _FakeTorchSpec() if n == "torch" else _real_find_spec(n, *a, **k))
try:
    c_on = {c.name: c for c in collect_model_cards()}
finally:
    importlib.util.find_spec = _real_find_spec

check("卸下 torch → Transformer is_stub=True（恒返回 0，不参与预测）",
      c_off["transformer"].is_stub is True)
check("装上 torch → Transformer is_stub=False",
      c_on["transformer"].is_stub is False,
      c_on["transformer"].status_text())
check("装上 torch → 后端文本变为 torch",
      c_on["transformer"].backend == "torch", c_on["transformer"].backend)
check("卸下 torch → 后端文本为 none", c_off["transformer"].backend == "none")
check("装上 torch → 局限文案随之切换（不再提示「不参与预测」）",
      not any("不参与任何预测" in s for s in c_on["transformer"].known_limits),
      str(c_on["transformer"].known_limits))
check("卸下 torch → PPO 退化为玩具实现（is_stub=True）",
      c_off["ppo"].is_stub is True)
check("装上 torch → PPO is_stub=False", c_on["ppo"].is_stub is False)
check("依赖装卸不影响 LSTM/岭回归的 is_stub",
      (c_off["lstm_numpy"].is_stub, c_on["lstm_numpy"].is_stub) == (False, False)
      and (c_off["ridge"].is_stub, c_on["ridge"].is_stub) == (False, False))

# arch 同理
importlib.util.find_spec = _stub_find_spec({"arch"})
try:
    g_off = {c.name: c for c in collect_model_cards()}["garch"]
finally:
    importlib.util.find_spec = _real_find_spec
importlib.util.find_spec = lambda n, *a, **k: (
    _FakeTorchSpec() if n == "arch" else _real_find_spec(n, *a, **k))
try:
    g_on = {c.name: c for c in collect_model_cards()}["garch"]
finally:
    importlib.util.find_spec = _real_find_spec
check("卸下 arch → GARCH is_stub=True（EWMA 近似）", g_off.is_stub is True)
check("装上 arch → GARCH is_stub=False", g_on.is_stub is False)
check("卸下 arch → 后端为 numpy(EWMA)", g_off.backend == "numpy(EWMA)", g_off.backend)
check("装上 arch → 后端为 arch", g_on.backend == "arch", g_on.backend)

# ---------------------------------------------------------------- ⑤ 状态文本
print("\n测试 ⑤: status_text 的四态语义")
check("已启用且已训练 → 「已训练」",
      ModelCard("a", enabled=True, trained=True).status_text() == "已训练")
check("未启用 → 「未启用」",
      ModelCard("a", enabled=False, trained=True).status_text() == "未启用")
check("未训练 → 「未训练」",
      ModelCard("a", enabled=True, trained=False).status_text() == "未训练")
check("占位 + 部分训练 → 「占位实现（部分已训练）」",
      ModelCard("a", is_stub=True, enabled=True, trained=True).status_text()
      == "占位实现（部分已训练）")
check("占位优先于「未启用」暴露（避免能力幻觉）",
      ModelCard("a", is_stub=True, enabled=False).status_text()
      == "占位实现（未训练）")
d = ModelCard("a", is_stub=True).to_dict()
check("to_dict 含 status / is_stub / backend",
      {"status", "is_stub", "backend"} <= set(d.keys()), str(d))

# ---------------------------------------------------------------- ⑥ 表格渲染
print("\n测试 ⑥: 表格行渲染（UI 面板消费）")
rows = cards_to_rows(cards)
check("行数 = 卡片数", len(rows) == len(cards), f"{len(rows)}")
check("每行列数 = COLUMNS 列数", all(len(r) == len(COLUMNS) for r in rows),
      f"{len(COLUMNS)}")
check("COLUMNS 含「状态」与「已知局限」",
      "状态" in COLUMNS and "已知局限" in COLUMNS, str(COLUMNS))
tcn_row = rows[names.index("tcn")]
check("TCN 行状态列 = 占位实现（未训练）", tcn_row[1] == "占位实现（未训练）",
      str(tcn_row[:2]))
check("未训练行的样本量显示为「—」", tcn_row[5] == "—", str(tcn_row))
check("未启用行的启用列显示「否」",
      all(rows[i][2] == "否" for i, c in enumerate(cards) if not c.enabled))
check("所有单元格为字符串（QTableWidgetItem 可直接消费）",
      all(isinstance(v, str) for r in rows for v in r))

# ---------------------------------------------------------------- ⑦ 真实训练
print("\n测试 ⑦: 真实 predictor 训练后卡片反映训练区间与样本量")
from futures_quant.ai.predictor import FuturesPredictor  # noqa: E402

df = _make_df(300, seed=7)
P = FuturesPredictor()
try:
    P.fit(df, seq_len=20, epochs=8)
except Exception as e:  # noqa: BLE001
    print(f"     （fit 异常：{e}）")
c2 = {c.name: c for c in collect_model_cards(predictor=P, df=df)}
check("训练后 lstm_numpy 标记为已训练", c2["lstm_numpy"].trained is True)
check("训练后 lstm_numpy 为启用状态", c2["lstm_numpy"].enabled is True)
check("训练区间来自 df 索引首尾",
      c2["lstm_numpy"].train_range == f"{df.index[0]} ~ {df.index[-1]}",
      str(c2["lstm_numpy"].train_range))
check("样本量 = len(df)", c2["lstm_numpy"].n_samples == len(df),
      str(c2["lstm_numpy"].n_samples))
check("启用后状态文本不再是「未训练」",
      c2["lstm_numpy"].status_text() == "已训练",
      c2["lstm_numpy"].status_text())
check("指标来自 predictor（resid_std / calib_beta / skill 中至少一个可用键）",
      isinstance(c2["lstm_numpy"].metrics, dict))
check("TCN 未作为外部模型接入 → 仍为占位实现（未训练）",
      c2["tcn"].status_text() == "占位实现（未训练）", c2["tcn"].status_text())

# ---------------------------------------------------------------- ⑧ 外部模型
print("\n测试 ⑧: 外部模型通道（TCN / GBM / Transformer 适配器）")


class _TCNEstimator:                     # 名字对齐 calibration_replay 内部适配器
    def __init__(self):
        class _Net:
            fitted = True
        self.net = _Net()


class _GBMEstimator:
    pass


ext = _TCNEstimator()
c3 = {c.name: c for c in collect_model_cards(predictor=P, df=df, external_model=ext)}
check("传入 TCN 适配器 → tcn 卡片启用", c3["tcn"].enabled is True)
check("传入 TCN 适配器 → tcn 卡片已训练（net.fitted=True）",
      c3["tcn"].trained is True)
check("TCN 已训练 → 状态为「占位实现（部分已训练）」",
      c3["tcn"].status_text() == "占位实现（部分已训练）", c3["tcn"].status_text())
check("TCN 已训练 → 训练区间与样本量有值",
      c3["tcn"].train_range is not None and c3["tcn"].n_samples == len(df),
      f"{c3['tcn'].train_range} / {c3['tcn'].n_samples}")
check("主模型让位：外部模型生效时 LSTM 不再标为启用",
      c3["lstm_numpy"].enabled is False)
check("TCN 即便已训练仍保持 is_stub=True（只训读出层）",
      c3["tcn"].is_stub is True)

c4 = {c.name: c for c in collect_model_cards(predictor=P, df=df,
                                             external_model=_GBMEstimator())}
check("传入 GBM 适配器 → gbm 卡片启用", c4["gbm"].enabled is True)
check("传入 GBM 适配器 → tcn 卡片回落到未启用", c4["tcn"].enabled is False)

# ---------------------------------------------------------------- ⑨ UI 面板
print("\n测试 ⑨: 预测页「🧩 模型状态」面板接线")
import inspect  # noqa: E402
from futures_quant.ui import predict_ops_page as POP  # noqa: E402

src = inspect.getsource(POP)
check("存在 _refresh_model_cards 方法", "_refresh_model_cards" in src)
check("存在「🧩 模型状态」Tab", "模型状态" in src)
check("刷新按钮已连接", "mc_refresh_btn.clicked.connect" in src)
check("表格使用 model_card.COLUMNS 作为表头", "_MC_COLUMNS" in src)
check("占位行按主题色标灰（muted/normal 双色）",
      "muted if card.is_stub else normal" in src)
check("主题切换后重刷（set_theme 调用刷新）",
      src.count("_refresh_model_cards") >= 3,
      f"出现 {src.count('_refresh_model_cards')} 次")
_done_src = inspect.getsource(POP.PredictOpsPage._on_predict_done)
check("预测完成回调 _on_predict_done 内自动刷新模型卡片",
      "_refresh_model_cards()" in _done_src)
check("切到模型状态页时惰性刷新一次",
      "_refresh_model_cards()" in inspect.getsource(
          POP.PredictOpsPage._on_left_tab_changed))
check("读取的是本页共享的 _predictor（非 self.predictor 旧称）",
      'getattr(self, "_predictor", None)' in src)
check("训练数据引用已留存（_last_train_df）",
      "self._last_train_df = df" in src)

print(f"\n{'=' * 60}")
print(f"M3-10 验证结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("test_m3_10.py 全绿")
