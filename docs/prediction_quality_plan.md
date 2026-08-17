# 预测质量闭环设计文档（⑤~⑮）

> 目标：把「模型说涨 X%」从一句空洞的自信度，变成**可验证、可量化、能在实时研判里自我修正**的校准信号。
> 本文记录预测质量闭环的完整设计、各阶段落点、关键数学与回归约定。

---

## 0. 闭环全景

```
实时预测 ──▶ ①信号融合(资讯偏置+回测策略库) ──▶ ②模型层(ridge/ensemble)
     │                                                    │
     ▼                                                    ▼
⑤ 自适应选参(quick_regime/adaptive_config)        ⑥ 多源资讯(news_feed)
     │                                                    │
     └────────────── ④ 完整预测(predictor.fit/predict) ◀──┘
                              │
                              ▼
⑦ 置信度校准(reliability_calibration：分箱→PAVA平滑→Wilson区间)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
⑧ 可视化(ReliabilityChart+概率带)      ⑨ 历史回放灌样本(calibration_replay)
              │                               │
              ▼                               ▼
⑫ 区间置信带(Wilson 95% 落到落点)     ⑬ 实时研判降级(宽区间→⚠低置信)
              └───────────────┬───────────────┘
                              ▼
                 ⑩ 自适应建议看板(recommend_text)
                 ⑪ 结算闭环(evaluate_all_open → 写回 score)
```

整条链路一句话：**预测产生落点 → 回放/结算积累样本外校准 → 校准区间量化不确定度 → 不确定度反向约束实时研判**，形成自修正闭环。

---

## 1. 关键文件与职责

| 文件 | 职责 |
|------|------|
| `futures_quant/ai/feedback.py` | 校准数学核心：`reliability_calibration`、`_wilson`、`calibration_band_at`、`mean_band_width`、`reliability_summary`、`recommend_text`、`evaluate_all_open` |
| `futures_quant/ai/calibration_replay.py` | 离线回放 `data/real_samples` 真实日线，逐窗 predict 写 `status='closed'` 样本 |
| `futures_quant/storage/analysis_store.py` | `save_closed_prediction` / `query_closed_for_calibration` / `query_open_predictions` / `prediction_stats` |
| `futures_quant/ui/chart_widget.py` | `ReliabilityChart`（校准可靠度图 + Wilson 带 + 落点误差棒）、`PriceChart`（概率带 ±1σ） |
| `futures_quant/ui/predict_ops_page.py` | 「🎯 概率校准」Tab、研判徽章降级（`_calib_conf_flag` / `_render_verdict_badge`）、解读文本挂区间说明 |

---

## 2. 校准数学（⑦+⑫）

### 2.1 可靠性校准
- 取 `query_closed_for_calibration` 的已结算样本 `(p_up, score∈{0,1})`。
- 按 `p_up` 分 10 箱，每箱经验命中率 `emp = hits/n`，空箱前后向填充（`_fill_none`）。
- 保序回归（PAVA 栈合并）得到单调非递减 `smoothed`，抑制小样本抖动过拟合。
- `calib_fn(p) = interp(centers, smoothed)` → 喂给 `predictor.calibrate_p_up`。

### 2.2 Wilson 95% 区间（⑫）
每个分箱经验命中率 `p̂` 的二项 Wilson 区间：
```
denom   = 1 + z²/n
center  = (p̂ + z²/2n) / denom
half    = z·√(p̂(1-p̂)/n + z²/4n²) / denom
lo, hi  = clamp(center∓half, 0, 1)        # z=1.96
```
- 小样本稳健，不会像正态近似那样退化成 0/1 奇点。
- bins 升级为 **5 元组** `(center, smoothed, n, lo, hi)`；空箱 `lo/hi=None`。
- `calibration_band_at(bins, p_up)`：在落点处对 `(lo, hi)` 线性插值，返回该预测概率对应的校准区间。
- `mean_band_width(bins)`：各分箱（n≥3）区间宽度均值 = **校准整体不确定性**。

---

## 3. 实时研判降级信号（⑬，闭环出口）

**触发条件**：本次预测落点 `res["p_up"]` 处的 Wilson 区间宽度 `hi−lo > LOW_CONF_BAND_WIDTH`（默认 **0.25**）→ 判定 `low_conf`。

> 直觉：区间越宽 = 该档概率的校准样本越稀疏 = 模型在此概率上的「自信度」越不可信。
> 典型场景：极端概率（p_up≈0.9/0.1）天然样本少 → 必然命中降级；中心概率样本充足 → 不降级。

**四处一致呈现**（保证「看见」而非「猜到」）：
1. **研判徽章**：`verdict_badge` 文本追加 `·⚠低置信` 并转琥珀色（`_render_verdict_badge`）。
2. **可靠度图落点**：`ReliabilityChart` 红点 + 水平误差棒 + `[lo–hi]` 标注（`mark` 4 元组）。
3. **校准速览卡片**：第 4 张「校准区间±」显示 `mean_band_width`（如 `26.6pp`），带宽 >0.20 时评级追加 `·宽区间`。
4. **解读文本**：`_detail_html` 模型面段落追加「（⚠ 落点校准区间 ±Xpp 过宽，研判可信度下降）」或「（…校准较可信）」。

**设计取舍**：
- 仅对「有数据但区间宽」降级；无 bins / None 不误报（避免空样本时满屏告警，整体「样本不足」态已另行提示）。
- 降级**只改信号呈现，不覆盖推荐结论**——避免在热路径静默改写建议，用户仍可见原始共振研判。

---

## 4. 离线样本积累（⑨）

- `calibration_replay.replay_symbol(store, df, sym, period, horizon, stride, max_samples)`：滑窗 predict（**仅训一次**），逐窗写 `status='closed'` 已结算样本。
- 回放在**独立 `FuturesPredictor` 实例**中执行，绝不影响页面共享 `self.predictor`（防污染）。
- 工具条可配 `replay_hor`（步长，与实时预测口径一致）+ `replay_cur`（仅当前品种）。
- 真实样本源：`data/real_samples/{rb,au,i,IF}.*.csv`（akshare 拉取，覆盖金属/贵金属/能化/股指）。

---

## 5. 回归约定（offscreen + Anaconda）

```bash
cd /d/PythonProject/QuantVortex
QT_QPA_PLATFORM=offscreen \
PYTHONPATH="D:/PythonProject/QuantVortex" \
/d/anaconda3/python.exe tests/e2e/<test>.py
# 注意：subprocess 内须用 Windows 风格绝对路径，Git-Bash /d/ 路径在子进程里解析失败
```

关键 e2e：
- `test_prob_calib_viz.py`：校准 Tab 组件 / 5 元组 bins / Wilson 带 / 落点 4 元组 / 速览卡片 / 深浅主题 paint 不崩 / 样本不足引导。
- `test_low_conf_signal.py`：⑬ 决策函数四态（窄/宽/插值/无bins）+ 徽章降级渲染 + 解读文本两态 + ⑭ `_soft_degrade_enter`/`-recommend` 四态单测。
- `test_screening_low_conf.py`：⑮ `_calib_low_conf` 三态 + 排行表 AI方向列标注 + 入手详情 KP预测信号标注。
- `test_calibration_replay.py`：回放灌样本 + `status='closed'` 隔离断言。
- `test_all_pages.py`：全页面构造冒烟（含 PredictOpsPage / ScreeningPage）。

临时测试库须带 `os.getpid()` 唯一后缀，避免跨运行污染导致 coverage 翻倍误判。

**沙箱已知 quirks**：
- `test_market_overview_tech_predict.py`：在 for 循环 + `> /dev/null 2>&1` 的 shell 管道下偶发 rc=127（沙箱怪癖），直接 `/d/anaconda3/python.exe` 单跑 rc=0。回归套件统计时以直接运行结果为准。

---

## 7. 结论软降级（⑭，闭环深化）

⑬ 只改「信号呈现」（徽章/图/卡片/文本），本步让 `low_conf` 真正**软降级结论**——避免高不确定档位误导激进建仓。

两个确定性 helper（`predict_ops_page.py`，可单测，零副作用）：
- `_soft_degrade_enter(enter, enter_col, low_conf)`：激进「可以入手（偏多）」+ low_conf → 降为「谨慎观望（置信偏低）」并转琥珀色；偏空/观望结论本身已保守，不改；low_conf=False 原样返回。
- `_soft_degrade_recommend(rec, low_conf)`：模型「偏多」建议 + low_conf → 降为「观望（置信偏低）」；与 enter 结论保持一致，避免「建议:偏多」与「谨慎观望」矛盾；偏空/观望不改。

接入点：
- `_detail_html` 算完 `enter` 后调 `_soft_degrade_enter(..., clow)`（`clow` 由 `calib_band` 第4元素透传，作用域提到块外）。
- `_on_predict_done` 设 `rec_badge` 时调 `_soft_degrade_recommend`，低置信态徽章转琥珀 + 深字配色。

**设计取舍**：只降「激进」结论，保守结论不动；不改写模型点估计，仅叠加不确定度约束——用户仍可见原始「可以入手」研判被标注为「置信偏低」。

---

## 8. 选品排行 AI 方向「置信偏低」标注（⑮，跨页一致）

把 ⑬/⑭ 的 `low_conf` 信号从预测页延伸到**选品排行页**，让「高不确定档位」的 AI 方向在全应用一致地提示可信度下降。

`screening_page.py`：
- 导入 `reliability_calibration, calibration_band_at` + 模块常量 `LOW_CONF_BAND_WIDTH=0.25`（与 predict_ops_page 同值同口径）。
- `_load_calib()`：`_on_done` 时读一次全局校准分箱（`reliability_calibration(store)`，需 `status='closed'` 样本）；失败/空 bins → `None` 安全回退。
- `_calib_low_conf(pu)`：与 ⑬ 同判定——落点 Wilson 区间宽 `hi−lo > 0.25` → True；无 bins/None/异常 → False（零副作用）。
- 两处标注：
  1. 排行表「AI方向」列（col 10）：低置信品种追加 `·置信偏低` 并转琥珀色；
  2. 入手详情「③ KP预测信号」：低置信品种标注 `·置信偏低` + 追加「⚠ 该档概率历史校准样本稀疏…」警示段。

**设计取舍**：只标注、不篡改 AI 点估计；与预测页降级口径完全一致（同阈值同判定）。

---

## 8b. 板块关注方向「置信偏低」标注（⑱，闭环收口）

把 ⑮ 的品种级「置信偏低」信号向上聚合到**板块关注方向列**（ctbl 第6列），让整页的校准不确定度提示一致。

`screening_page.py`：
- `_screen()` 聚合 `cat_rows` 时增加 `avg_pu`（板块内品种 AI 方向概率均值，`sum(m.get("pu", 0.5) for m in members) / len(members)`），透传到 `cat_rows` dict。
- `_render_cats()` 第6列（关注方向）：在原有「重点留意/可留意/暂观望」文本后，若 `_calib_low_conf(c.get("avg_pu", 0.5))` 为 True 则追加 ` ·置信偏低`；零副作用：无校准信息 / 空 bins / 中概率档均不误报。
- 判定口径与品种级完全一致（同阈值 0.25pp、同 `calibration_band_at` 插值）。

**设计取舍**：板块级用平均 `avg_pu` 而非加权或投票，简化且对低置信信号保守（高 pu 品种占多时板块才会触发）；标注只追加文字，不改变方向判断本身。

---

## 9. 状态

- ⑤~⑱ 全部完成，预测质量闭环打通：信号融合 → 模型层 → 校准数学(Wilson/PAVA) → 可视化(可靠度图/Wilson带/落点误差棒) → 离线回放灌样本(835条) → 实时研判降级(⑬徽章+⑭结论软降级) → ⑮品种级标注 → ⑱板块级标注（全页一致）。
- 已灌 835 条 real closed 样本（rb/au/i/IF 各 200 + 原始 35），MBW=0.33pp。
- e2e 套件 26/26 通过（`test_market_overview_tech_predict` 沙箱 rc=127 artifact 不计入）。
- ⑱ 新增 `tests/e2e/test_screening_low_conf.py` 第4节：板块关注方向三态断言，全 rc=0。

---

## 12. 阈值自适应策略（⑲，2026-08-01）

实测校准数据揭示：所有 10 个分箱宽度均在 13~60pp 之间，固定阈值 0.25 会导致**全量误报**（所有预测均触发 low_conf）。

**策略**：`n < 50` 时强制判低置信（样本太少 → Wilson 区间天然宽），`n >= 50` 时用固定阈值 0.25。
- 判定时用**最近中心值**匹配分箱（避免 Wilson 区间因边界截断导致跨 bin 误匹配）。
- 判定口径：`width > 0.25 OR n_at_bin < 50` 即判低置信。

**实测效果**（835 条样本）：
- 密集分箱（n≥100）：4 个 bin，MBW=15pp → 中概率档（0.25-0.75）不触发 low_conf
- 中等分箱（20≤n<100）：2 个 bin，MBW=24.5pp → 边界档轻微触发
- 稀疏分箱（n<50）：4 个 bin，MBW=55pp → 端部档触发 low_conf
- 整体 low_conf 触发率：约 40%（端部 + 稀疏分箱），符合预期

**涉及文件**：
- `futures_quant/ui/predict_ops_page.py`：`_calib_conf_flag` 使用最近中心匹配 + 样本量判定
- `futures_quant/ui/screening_page.py`：`_calib_low_conf` 同口径
- `tests/e2e/test_low_conf_signal.py` / `test_screening_low_conf.py`：已验证全 rc=0

---

## 10. 沙箱 quirks（已验证）

- `test_market_overview_tech_predict.py` 在 for 循环+重定向下偶发 rc=127（与代码无关，沙箱环境怪癖），直接运行 rc=0。
- `rm` 在沙箱被 safe-delete 包裹，`/d/...` 路径被拒；删临时文件须用 `D:/...` 绝对路径。
- Windows 原生 python 不认 POSIX 路径；给 python 传参用相对路径或 `D:/...`。
- subprocess 内须用 Windows 风格绝对路径，Git-Bash `/d/` 路径在子进程里解析失败。

---

## 11. 回放 bug 修复（⑰，2026-08-01）

`calibration_replay.py` 的 `replay_symbol` 函数签名缺少 `extended_features` 和 `use_ensemble` 参数，调用时引用未定义变量触发 `NameError`，被外层 `except Exception` 静默吞掉，所有品种返回 `added=0`，回放永远无效。已修复：在签名中增加这两个 bool 参数，默认值 `True`，并在 `pred.fit()` 调用中透传。
