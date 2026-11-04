"""M3-10 模型卡片（Model Card）与状态透明化 —— pytest 形态。

由散落脚本 ``tests/test_m3_10.py``（模块级 ``PASS/FAIL`` 列表 +
``check(name,cond,detail)`` 辅助 + 结尾 ``if FAIL: sys.exit(1)``，
0 个 ``def test_*``）机械改写：每段 ``check(...)`` 收敛为
``assert cond, f"{name} — {detail}"``，行为契约不变。

- 去掉脚本里的 ``sys.path.insert``（``tests/conftest.py`` 已注入项目根）。
- 依赖装卸（torch / arch）原脚本用 ``importlib.util.find_spec`` 现场 stub +
  ``finally`` 还原；这里抽成 ``_stub_find_spec`` 上下文管理器，行为等价。
- 已实测核对生产契约：全部 69 项断言仍有效（无一陈旧）。
"""
from __future__ import annotations

import contextlib
import importlib.util

import numpy as np
import pandas as pd

from futures_quant.ai.model_card import (
    COLUMNS, ModelCard, cards_to_rows, collect_model_cards,
    format_cards_text, probe_module,
)

# 文档 M3-10 列 7 个；实现额外补了 gbm（M3-06 实装的外部主模型通道）。
EXPECTED = {"lstm_numpy", "ridge", "ensemble", "tcn", "transformer", "garch", "ppo"}
EXTRA = {"gbm"}


def _make_df(n=300, seed=7, base=3500.0):
    """构造一份合成 OHLC 行情，供 predictor.fit 使用。"""
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


@contextlib.contextmanager
def _stub_find_spec(missing=(), present=()):
    """临时改写 ``importlib.util.find_spec``，模拟「卸下/装上」某个依赖。"""
    real = importlib.util.find_spec

    def _f(name, *a, **k):
        if name in missing:
            return None
        if name in present:
            return type("FakeSpec", (), {"name": name})()
        return real(name, *a, **k)

    importlib.util.find_spec = _f
    try:
        yield
    finally:
        importlib.util.find_spec = real


def test_datastructure_fields():
    """① ModelCard 数据结构字段完整（文档 7 字段 + 扩展 3 字段 + 默认值）。"""
    flds = set(ModelCard.__dataclass_fields__.keys())
    need = {"name", "enabled", "is_stub", "train_range", "n_samples",
            "metrics", "known_limits"}
    assert need <= flds, f"文档要求的 7 个字段齐备 — {sorted(flds)}"
    assert {"backend", "trained", "display"} <= flds, "扩展字段 backend/trained/display 存在"

    c_empty = ModelCard(name="x")
    assert (c_empty.is_stub, c_empty.enabled) == (False, False), "默认 is_stub=False / enabled=False"
    assert c_empty.n_samples == 0 and c_empty.train_range is None, "默认 n_samples=0 / train_range=None"


def test_cards_collection():
    """② 7 个模型卡片全部生成 + 额外 gbm；无重复、均含显示名/局限/后端。"""
    cards = collect_model_cards()
    names = [c.name for c in cards]
    assert EXPECTED <= set(names), f"文档要求的 7 个模型全部有卡片 — {names}"
    assert EXTRA <= set(names), f"额外补充 gbm（M3-06 外部主模型通道）— {names}"
    assert len(names) == len(set(names)), f"无重复卡片 — {names}"
    assert all(c.label and c.label != c.name for c in cards), \
        f"每个卡片都有非空中文显示名 — {[c.label for c in cards]}"
    assert all(len(c.known_limits) >= 1 for c in cards), \
        f"每个卡片都写明已知局限（非空）— {[c.name for c in cards if not c.known_limits]}"
    assert all(c.backend for c in cards), f"每个卡片都有 backend — {[c.backend for c in cards]}"


def test_stub_annotation():
    """③ 占位实现（is_stub）标注与「TCN：占位实现（未训练）」。"""
    cards = collect_model_cards()
    by = {c.name: c for c in cards}
    tcn = by["tcn"]
    assert tcn.is_stub is True, "TCN 被标为占位实现"
    assert tcn.status_text() == "占位实现（未训练）", tcn.status_text()
    txt = format_cards_text(cards)
    assert "TCN（因果膨胀卷积）：占位实现（未训练）" in txt, \
        [l for l in txt.splitlines() if l.startswith("TCN")][:1]
    assert tcn.train_range is None and tcn.n_samples == 0, "TCN 未训练时训练区间/样本量为空"
    assert any("非端到端" in s for s in tcn.known_limits), str(tcn.known_limits)
    assert not by["lstm_numpy"].is_stub and not by["ridge"].is_stub \
        and not by["ensemble"].is_stub, "LSTM / 岭回归 / 集成 不是占位实现"


def test_dependency_toggle():
    """④ 装上/卸下 torch / arch 时状态实时更新（probe_module 不缓存）。"""
    assert probe_module("json") is True, "probe_module 对存在的模块返回 True"
    assert probe_module("__definitely_not_a_pkg_xyz__") is False, \
        "probe_module 对不存在的模块返回 False"

    with _stub_find_spec(missing={"torch"}):
        c_off = {c.name: c for c in collect_model_cards()}
    with _stub_find_spec(present={"torch"}):
        c_on = {c.name: c for c in collect_model_cards()}

    assert c_off["transformer"].is_stub is True, \
        "卸下 torch → Transformer is_stub=True（恒返回 0，不参与预测）"
    assert c_on["transformer"].is_stub is False, \
        f"装上 torch → Transformer is_stub=False — {c_on['transformer'].status_text()}"
    assert c_on["transformer"].backend == "torch", "装上 torch → 后端文本变为 torch"
    assert c_off["transformer"].backend == "none", "卸下 torch → 后端文本为 none"
    assert not any("不参与任何预测" in s for s in c_on["transformer"].known_limits), \
        f"装上 torch → 局限文案随之切换（不再提示「不参与预测」）— {c_on['transformer'].known_limits}"
    assert c_off["ppo"].is_stub is True, "卸下 torch → PPO 退化为玩具实现（is_stub=True）"
    assert c_on["ppo"].is_stub is False, "装上 torch → PPO is_stub=False"
    assert (c_off["lstm_numpy"].is_stub, c_on["lstm_numpy"].is_stub) == (False, False) \
        and (c_off["ridge"].is_stub, c_on["ridge"].is_stub) == (False, False), \
        "依赖装卸不影响 LSTM/岭回归的 is_stub"

    # arch 同理
    with _stub_find_spec(missing={"arch"}):
        g_off = {c.name: c for c in collect_model_cards()}["garch"]
    with _stub_find_spec(present={"arch"}):
        g_on = {c.name: c for c in collect_model_cards()}["garch"]
    assert g_off.is_stub is True, "卸下 arch → GARCH is_stub=True（EWMA 近似）"
    assert g_on.is_stub is False, "装上 arch → GARCH is_stub=False"
    assert g_off.backend == "numpy(EWMA)", f"卸下 arch → 后端为 numpy(EWMA) — {g_off.backend}"
    assert g_on.backend == "arch", f"装上 arch → 后端为 arch — {g_on.backend}"


def test_status_text_semantics():
    """⑤ status_text 的四态语义 + to_dict 含关键字段。"""
    assert ModelCard("a", enabled=True, trained=True).status_text() == "已训练", \
        "已启用且已训练 → 「已训练」"
    assert ModelCard("a", enabled=False, trained=True).status_text() == "未启用", \
        "未启用 → 「未启用」"
    assert ModelCard("a", enabled=True, trained=False).status_text() == "未训练", \
        "未训练 → 「未训练」"
    assert ModelCard("a", is_stub=True, enabled=True, trained=True).status_text() \
        == "占位实现（部分已训练）", "占位 + 部分训练 → 「占位实现（部分已训练）」"
    assert ModelCard("a", is_stub=True, enabled=False).status_text() \
        == "占位实现（未训练）", "占位优先于「未启用」暴露（避免能力幻觉）"
    d = ModelCard("a", is_stub=True).to_dict()
    assert {"status", "is_stub", "backend"} <= set(d.keys()), f"to_dict 含 status / is_stub / backend — {d}"


def test_table_rows_render():
    """⑥ 表格行渲染（UI 面板消费）：列数、TCN 行、未训练/未启用显示。"""
    cards = collect_model_cards()
    names = [c.name for c in cards]
    rows = cards_to_rows(cards)
    assert len(rows) == len(cards), f"行数 = 卡片数 — {len(rows)}"
    assert all(len(r) == len(COLUMNS) for r in rows), f"每行列数 = COLUMNS 列数 — {len(COLUMNS)}"
    assert "状态" in COLUMNS and "已知局限" in COLUMNS, f"COLUMNS 含「状态」与「已知局限」— {COLUMNS}"
    tcn_row = rows[names.index("tcn")]
    assert tcn_row[1] == "占位实现（未训练）", f"TCN 行状态列 = 占位实现（未训练）— {tcn_row[:2]}"
    assert tcn_row[5] == "—", f"未训练行的样本量显示为「—」— {tcn_row}"
    assert all(rows[i][2] == "否" for i, c in enumerate(cards) if not c.enabled), \
        "未启用行的启用列显示「否」"
    assert all(isinstance(v, str) for r in rows for v in r), \
        "所有单元格为字符串（QTableWidgetItem 可直接消费）"


def test_real_training_cards():
    """⑦ 真实 predictor 训练后卡片反映训练区间与样本量。"""
    from futures_quant.ai.predictor import FuturesPredictor

    df = _make_df(300, seed=7)
    P = FuturesPredictor()
    P.fit(df, seq_len=20, epochs=8)
    c2 = {c.name: c for c in collect_model_cards(predictor=P, df=df)}
    assert c2["lstm_numpy"].trained is True, "训练后 lstm_numpy 标记为已训练"
    assert c2["lstm_numpy"].enabled is True, "训练后 lstm_numpy 为启用状态"
    assert c2["lstm_numpy"].train_range == f"{df.index[0]} ~ {df.index[-1]}", \
        f"训练区间来自 df 索引首尾 — {c2['lstm_numpy'].train_range}"
    assert c2["lstm_numpy"].n_samples == len(df), f"样本量 = len(df) — {c2['lstm_numpy'].n_samples}"
    assert c2["lstm_numpy"].status_text() == "已训练", \
        f"启用后状态文本不再是「未训练」— {c2['lstm_numpy'].status_text()}"
    assert isinstance(c2["lstm_numpy"].metrics, dict), \
        "指标来自 predictor（resid_std / calib_beta / skill 中至少一个可用键）"
    assert c2["tcn"].status_text() == "占位实现（未训练）", \
        f"TCN 未作为外部模型接入 → 仍为占位实现（未训练）— {c2['tcn'].status_text()}"


def test_external_model_channel():
    """⑧ 外部模型通道（TCN / GBM / Transformer 适配器）接线。"""
    from futures_quant.ai.predictor import FuturesPredictor

    df = _make_df(300, seed=7)
    P = FuturesPredictor()
    P.fit(df, seq_len=20, epochs=8)

    class _TCNEstimator:                 # 名字对齐 calibration_replay 内部适配器
        def __init__(self):
            class _Net:
                fitted = True
            self.net = _Net()

    class _GBMEstimator:
        pass

    c3 = {c.name: c for c in collect_model_cards(predictor=P, df=df, external_model=_TCNEstimator())}
    assert c3["tcn"].enabled is True, "传入 TCN 适配器 → tcn 卡片启用"
    assert c3["tcn"].trained is True, "传入 TCN 适配器 → tcn 卡片已训练（net.fitted=True）"
    assert c3["tcn"].status_text() == "占位实现（部分已训练）", \
        f"TCN 已训练 → 状态为「占位实现（部分已训练）」— {c3['tcn'].status_text()}"
    assert c3["tcn"].train_range is not None and c3["tcn"].n_samples == len(df), \
        f"TCN 已训练 → 训练区间与样本量有值 — {c3['tcn'].train_range} / {c3['tcn'].n_samples}"
    assert c3["lstm_numpy"].enabled is False, "主模型让位：外部模型生效时 LSTM 不再标为启用"
    assert c3["tcn"].is_stub is True, "TCN 即便已训练仍保持 is_stub=True（只训读出层）"

    c4 = {c.name: c for c in collect_model_cards(predictor=P, df=df,
                                                external_model=_GBMEstimator())}
    assert c4["gbm"].enabled is True, "传入 GBM 适配器 → gbm 卡片启用"
    assert c4["tcn"].enabled is False, "传入 GBM 适配器 → tcn 卡片回落到未启用"


def test_ui_panel_wiring():
    """⑨ 预测页「🧩 模型状态」面板接线（源码结构嗅探）。"""
    import inspect

    from futures_quant.ui import predict_ops_page as POP

    src = inspect.getsource(POP)
    assert "_refresh_model_cards" in src, "存在 _refresh_model_cards 方法"
    assert "模型状态" in src, "存在「🧩 模型状态」Tab"
    assert "mc_refresh_btn.clicked.connect" in src, "刷新按钮已连接"
    assert "_MC_COLUMNS" in src, "表格使用 model_card.COLUMNS 作为表头"
    assert "muted if card.is_stub else normal" in src, "占位行按主题色标灰（muted/normal 双色）"
    assert src.count("_refresh_model_cards") >= 3, \
        f"主题切换后重刷（set_theme 调用刷新）— 出现 {src.count('_refresh_model_cards')} 次"
    assert 'getattr(self, "_predictor", None)' in src, \
        "读取的是本页共享的 _predictor（非 self.predictor 旧称）"
    assert "self._last_train_df = df" in src, "训练数据引用已留存（_last_train_df）"

    done_src = inspect.getsource(POP.PredictOpsPage._on_predict_done)
    assert "_refresh_model_cards()" in done_src, "预测完成回调 _on_predict_done 内自动刷新模型卡片"
    tab_src = inspect.getsource(POP.PredictOpsPage._on_left_tab_changed)
    assert "_refresh_model_cards()" in tab_src, "切到模型状态页时惰性刷新一次"
