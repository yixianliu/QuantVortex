"""KP 预测核心（期货价格趋势 / 涨跌概率 / 压力支撑 / 风险度）。

流程：
    1. 特征工程：对数收益、滚动波动、RSI/MACD/KDJ/BOLL%/CCI 等；
    2. 训练：纯 numpy LSTM 预测「下一根对数收益」；若数值异常自动回退岭回归；
    3. 多步滚动：以最近窗口递归外推未来 N 根收盘价路径，并给出 ±1σ 预测带；
    4. 研判：涨跌概率（正态近似）、压力/支撑位、风险度、多空性价比、行情状态。

诚实声明：
    - 多步预测第 1 步为模型真实输出；第 2 步起的特征（指标类）采用「上一已知值
      外推 + 收益/波动滚动更新」的近似，属业界标准的点预测做法，非未来函数；
    - 模型在历史数据上拟合，预测为概率性研判，不构成任何交易建议。
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import logging
from ..analysis.support_resistance import compute_levels
from ..analysis.signals import resonance, trend_score
# M3-11：阈值集中化。所有魔法数字改为引用 .constants 中的运行期实例；
# 默认值与改造前的字面量逐一相等，故行为不变。
from .constants import PREDICTOR as _PC, EPS as _EPS
# 延迟导入：避免模块顶层加载 sklearn/PyQt6/LSTM 等重型依赖
# LSTM/ensemble/features 仅在 fit/predict 首次调用时导入
LSTM = None
_TorchLSTM = None
_ensure_torch_fn = None
_Ridge_cls = None
_MultiPeriodEnsemble_cls = None
_build_features_fn = None


def _lazy_import_ai():
    """懒加载 AI 子模块，首次调用时触发导入，后续复用全局变量。"""
    global LSTM, _TorchLSTM, _ensure_torch_fn, _Ridge_cls, _MultiPeriodEnsemble_cls, _build_features_fn
    if LSTM is None:
        from .lstm import LSTM as _L, TorchLSTM as _TL, _ensure_torch as _et
        from .features import build_features as _bf
        from .ensemble import MultiPeriodEnsemble as _ME, _Ridge as _R
        LSTM = _L
        _TorchLSTM = _TL
        _ensure_torch_fn = _et
        _Ridge_cls = _R
        _MultiPeriodEnsemble_cls = _ME
        _build_features_fn = _bf


logger = logging.getLogger(__name__)


def _walk_forward_plan(n: int, min_folds: int = None):
    """M3-05：为 `FuturesPredictor.evaluate` 生成因果滚动折叠方案。

    返回 `WalkForward.folds_plan(n)` 的结果；无法产出 ≥min_folds 折（样本太少）
    或 validation 模块不可用时返回 None，由调用方回退到固定 80/20 分割。

    窗口自适应：训练段取 50%，剩余部分均分为 (min_folds+1) 段，
    保证典型样本量下恰好产出 min_folds+1 折（≥3）。
    """
    # M3-11：缺省折数取自阈值中心（None 哨兵，避免默认值在 import 期被固化）
    if min_folds is None:
        min_folds = _PC.wf_min_folds
    try:
        from .validation import WalkForward
    except Exception as e:  # noqa: BLE001
        logger.warning("WalkForward 不可用（%s），回退固定 80/20 分割", e)
        return None
    if n < _PC.wf_min_samples:
        return None
    train_len = max(_PC.wf_min_train_len, int(n * _PC.wf_train_ratio))
    test_len = max(_PC.wf_min_test_len, (n - train_len) // (min_folds + 1))
    try:
        wf = WalkForward(train_len=train_len, test_len=test_len,
                         step=test_len, min_folds=min_folds)
        return wf.folds_plan(n)
    except ValueError as e:
        logger.warning("Walk-Forward 折叠生成失败，回退固定 80/20 分割：%s", e)
        return None


def _mincer_zarnowitz(pred: np.ndarray, actual: np.ndarray) -> tuple[float, float]:
    """Mincer-Zarnowitz 预测校准回归：actual = a + b * pred。

    返回 (beta, resid_std)。beta 是「预测值应被缩放多少」的最优系数：
      * beta ≈ 1  预测幅度恰当；
      * beta ≈ 0  预测与真实值无关（纯噪声）——此时应把预测收缩到 0；
      * beta < 0  预测方向系统性相反。

    这是治理「随机游走上也给出极端置信度」的关键：无技能的模型 beta 自动趋近 0，
    预测被收缩、残差变大，概率自然回归 0.5，而非靠人工阈值硬压。

    额外做**显著性收缩**：校准段通常只有几十个点，beta 本身估计噪声很大，
    纯噪声序列上也可能偶然算出 0.6+。按 t 统计量收缩
    ``beta ← beta · t²/(1+t²)``，使统计上不显著的 beta 自动塌向 0，
    显著时才接近原值。这等价于以 N(0, se²) 为先验的贝叶斯后验均值。
    """
    pred = np.asarray(pred, float)
    actual = np.asarray(actual, float)
    ok = np.isfinite(pred) & np.isfinite(actual)
    pred, actual = pred[ok], actual[ok]
    n = len(pred)
    if n < _PC.mz_min_samples:
        return 0.0, float(np.std(actual) if n else _EPS.default_resid_std) + _EPS.eps_resid
    sd_p = float(np.std(pred))
    if sd_p < _EPS.eps_div:              # 预测恒定 -> 无信息
        return 0.0, float(np.std(actual)) + _EPS.eps_resid
    beta = float(np.cov(pred, actual, ddof=0)[0, 1] / (sd_p ** 2))
    resid = actual - beta * pred
    sd_r = float(np.std(resid))
    # beta 的标准误： se = σ_resid / (√n · σ_pred)
    se = sd_r / (math.sqrt(n) * sd_p + _EPS.eps_div)
    t = beta / (se + _EPS.eps_div)
    beta *= (t * t) / (1.0 + t * t)      # 显著性收缩
    # 负相关一律视作无技能，不做反向下注（上限 mz_beta_max）
    beta = max(0.0, min(_PC.mz_beta_max, beta))
    return beta, float(np.std(actual - beta * pred)) + _EPS.eps_resid


class FuturesPredictor:
    """期货价格序列预测器。
    
    模型生命周期流程：
    1. 数据准备：收集历史价格、成交量等市场数据
    2. 特征工程：计算技术指标（收益率、波动率、RSI、MACD等）和扩展特征
    3. 模型训练：采用时序切分 -> 验证集校准 -> 全量重训三段式流程
    4. 模型评估：在验证集上评估方向准确率、精确率、召回率、F1、MAE、RMSE、R-squared等指标
    5. 模型预测：使用训练好的模型进行价格趋势、涨跌概率、预期收益等预测
    6. 模型迭代：定期使用新数据重新训练模型以适应市场变化（建议每月或每季度更新）
    
    训练细节：
    - 支持 LSTM（纯 numpy 实现）和 PyTorch 双向 LSTM（可选）两种模型架构
    - 自动回退到岭回归当 LLM 训练失败或不收敛时
    - 采用 Mincer-Zarnowitz 回归进行样本外校准，避免概率虚高问题
    - 支持集成学习（多周期集成）提高预测稳健性
    
    特征集：
    - 基础特征：ret, vol, RSI14, MACD, K, boll_pct, CCI14
    - 扩展特征：包含基础特征以及 20+ 个高级技术指标和量价关系特征
    """

    def __init__(self) -> None:
        """初始化相关对象。"""
        self.lstm: LSTM | None = None
        self._ridge: _Ridge_cls | None = None  # type: ignore[valid-type]
        self.use_lstm = True
        self.trained = False
        self.seq_len = _PC.default_seq_len  # 增加默认窗口长度以捕获更长期依赖
        self._feat_mean: np.ndarray | None = None
        self._feat_std: np.ndarray | None = None
        self.resid_std = _EPS.default_resid_std
        self.levels: list[dict] = []
        self.extended_features = False
        self.use_ensemble = False
        self.ensemble: object | None = None
        # M3-06 ④：可选的**外部主模型**（TCN / GBM / TS-Transformer 等）。
        # 只需实现 fit(X_3d, y) 与 predict(X_3d) -> (n,)；非空时 _train_core 优先用它，
        # 使「多模型对比」里 tcn / gbm 不再偷偷降级成 Ridge。
        self.external_model: object | None = None
        self._feat_names: list = []
        # LSTM 超参数（可通过实验调优；默认值来自 .constants.PREDICTOR）
        self.lstm_hidden_size = _PC.lstm_hidden_size   # 增大隐藏单元以提升表达能力
        self.lstm_lr = _PC.lstm_lr                     # 降低学习率以提升稳定性
        # 验证集导出的校准系数与技能度（predict 时用于收缩预测幅度）
        self.calib_beta = 1.0
        self.skill = 0.0                 # 相对「恒预测 0」基线的 MAE 改善率
        self.validated = False           # resid_std 是否来自样本外
        self.best_alpha = 1.0
        # 步长阻尼系数：多步递归外推时逐步收缩预测，防止发散
        self.STEP_DAMPING = _PC.step_damping

    # ----------------------------- 特征 -----------------------------
    def _features(self, df: pd.DataFrame, symbol: str = "UNKNOWN", period: str = "1m"):
        """处理特征。build_features 返回 (ind, F, feature_names)。"""
        _lazy_import_ai()  # 确保 build_features 已加载
        ind, F, names = _build_features_fn(df, self.extended_features, symbol=symbol, period=period)
        self._feat_names = names
        return ind, F

    # ------------------------------------------------------------------
    def _build_sequences(self, arr: np.ndarray, y: np.ndarray, seq_len: int):
        """构造 (窗口, 标签) 对。

        窗口取 arr[t-seq_len+1 : t+1]（**含第 t 根**），标签取 y[t]=ret[t+1]，
        即「用截至 t 的信息预测 t+1」，与推理时 arr[-seq_len:] -> ret[n] 完全同构。
        旧实现窗口为 arr[t-seq_len:t]（不含 t），训练实为 h=2 而推理 h=1，
        训练目标与实际用法错位一根，是模型精度的隐性损耗。
        """
        Xs, Ys = [], []
        for t in range(seq_len - 1, len(arr) - 1):
            Xs.append(arr[t - seq_len + 1:t + 1])
            Ys.append(y[t])
        if not Xs:
            return np.empty((0, seq_len, arr.shape[1])), np.empty(0)
        return np.array(Xs), np.nan_to_num(np.array(Ys), nan=0.0,
                                           posinf=0.0, neginf=0.0)

    def _train_core(self, Xs: np.ndarray, Ys: np.ndarray, n_feat: int,
                    epochs: int, force_ridge: bool) -> None:
        """在已归一化的 (Xs, Ys) 上训练主模型，LSTM 失败回退岭回归。"""
        _lazy_import_ai()  # 首次训练时触发 AI 子模块导入
        # M3-06 ④：外部模型优先（force_ridge 只应影响 ridge 分支，不再劫持 tcn/gbm）
        if self.external_model is not None:
            self.use_lstm = False
            self.lstm = None
            self._ridge = None
            try:
                self.external_model.fit(Xs, Ys)
                probe = np.asarray(self.external_model.predict(Xs[:1]),
                                   dtype=float).reshape(-1)
                if probe.size == 0 or not np.all(np.isfinite(probe)):
                    raise ValueError("外部模型输出非有限值")
            except Exception as e:  # noqa: BLE001
                logger.warning("外部模型训练失败，回退岭回归：%s", e)
                self.external_model = None
                self._ridge = _Ridge_cls(alpha=self.best_alpha)
                self._ridge.fit(Xs.reshape(len(Xs), -1), Ys)
            return
        if force_ridge:
            self.use_lstm = False
            self.lstm = None
            self._ridge = _Ridge_cls(alpha=self.best_alpha)
            self._ridge.fit(Xs.reshape(len(Xs), -1), Ys)
            return
        try:
            # 优先双向 LSTM + Attention（torch）；无 torch 则降级 numpy LSTM
            if _ensure_torch_fn():
                self.lstm = _TorchLSTM(input_size=n_feat, hidden_size=self.lstm_hidden_size,
                                       seed=_PC.random_seed)
            else:
                self.lstm = LSTM(input_size=n_feat, hidden_size=self.lstm_hidden_size,
                                 output_size=1, seed=_PC.random_seed)
            # TorchLSTM / numpy LSTM 共享 fit 签名（TorchLSTM 额外支持 val_split / patience）
            self.lstm.fit([Xs[i] for i in range(len(Xs))], Ys, epochs=epochs,
                          lr=self.lstm_lr)
            probe = self.lstm.predict_last(Xs[-1])
            if not math.isfinite(probe):
                raise ValueError("LSTM 输出非有限值")
            self.use_lstm = True
        except Exception:
            self.use_lstm = False
            self._ridge = _Ridge_cls(alpha=self.best_alpha)
            self._ridge.fit(Xs.reshape(len(Xs), -1), Ys)

    def _batch_pred(self, Xs: np.ndarray) -> np.ndarray:
        """批量预测（向量化），替代逐样本循环，速度提升 10x+。

        参数:
            Xs: np.ndarray，形状 (N, T, F)

        返回:
            np.ndarray，形状 (N,) 或 (N, out)
        """
        if self.external_model is not None:
            return np.asarray(self.external_model.predict(Xs), dtype=float).reshape(-1)
        if self.use_lstm and self.lstm is not None:
            return self.lstm.predict_batch(Xs)
        if self._ridge is not None:
            # Xs: (N, T, F) -> 逐行预测（_Ridge.predict 期望 1D 输入）
            return np.array([self._ridge.predict(Xs[i].reshape(-1)) for i in range(len(Xs))])
        return np.zeros(len(Xs))

    # ----------------------------- 训练 -----------------------------
    def fit(self, df: pd.DataFrame, seq_len: int = 20, epochs: int = 30,
            force_ridge: bool = False, extended_features: bool = False,
            use_ensemble: bool = False, symbol: str = "UNKNOWN", period: str = "1m",
            external_model: object | None = None) -> dict:
        """训练模型。采用「时序切分 -> 验证集校准 -> 全量重训」三段式：
        
        完整训练流程：
        1. 时序切分：将数据按时间顺序划分为训练集、验证集和校准集（带 embargo 隔离带防止数据泄漏）
        2. 超参数搜索：在训练集上使用交叉验证寻找最优正则化参数（alpha）
        3. 模型训练：在训练集上训练主模型（LSTM 或岭回归）
        4. 验证集校准：在验证集上执行 Mincer-Zarnowitz 回归，获得样本外预测缩放系数 beta
           及样本外残差标准差（避免旧实验中使用样本内残差导致的概率虚高问题）
        5. 全量重训：使用全部数据重新训练主模型，但保留步骤 4 得到的 beta 和 σ 作为不确定性度量
        6. 集成模型训练：（可选）训练多周期集成模型以提高预测稳健性
        
        模型迭代建议：
        - 定期重复此训练流程以适应市场变化（建议每月或每季度更新一次）
        - 每次迭代使用最新的历史数据，保持模型的时效性和适应性
        - 通过评估新旧模型在同一验证集上的表现来决定是否采用新模型
        
        参数说明见下方。
        """
        logger.info(f"开始训练模型，参数: seq_len={seq_len}, epochs={epochs}, force_ridge={force_ridge}, "
                   f"extended_features={extended_features}, use_ensemble={use_ensemble}, symbol={symbol}, period={period}")
        self.extended_features = extended_features
        self.use_ensemble = use_ensemble
        # M3-06 ④：外部主模型（非空时优先于 LSTM / Ridge）
        self.external_model = external_model
        self._symbol = symbol
        self._period = period
        ind, F = self._features(df, symbol=symbol, period=period)
        self.seq_len = seq_len
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)
        Xs, Ys = self._build_sequences(arr, y, seq_len)
        if len(Xs) < _PC.fit_min_samples:
            self.trained = False
            logger.warning("模型训练失败：数据不足（有效样本少于%d条）"
                           % _PC.fit_min_samples)
            return {"trained": False, "reason": "数据不足"}

        mean = Xs.reshape(-1, Xs.shape[-1]).mean(0)
        std = Xs.reshape(-1, Xs.shape[-1]).std(0) + _EPS.eps_std
        self._feat_mean, self._feat_std = mean, std
        Xn = (Xs - mean) / std
        n_feat = arr.shape[1]

        # ---- 阶段 1/2：三段时序切分（训练 / 选参 / 校准）----
        # 三段互不重叠且各带 embargo 隔离带。之所以必须把「选超参」与「估校准系数」
        # 分在两段不同数据上：若共用一段，alpha 是在该段上挑出来的最优值，
        # 再在同一段做 MZ 回归会产生选择偏差——实测纯随机游走上 beta 被抬到 0.80，
        # 等于把「碰巧拟合上的噪声」误判成技能。
        m = len(Xn)
        embargo = seq_len
        c1, c2 = int(m * _PC.train_split_ratio), int(m * _PC.calib_split_ratio)
        self.calib_beta, self.skill, self.validated = 1.0, 0.0, False
        self.best_alpha = 1.0

        has_3way = (c1 >= _PC.min_train_seg
                    and (c2 - c1 - embargo) >= _PC.min_val_seg
                    and (m - c2 - embargo) >= _PC.min_calib_seg)
        has_2way = (c2 >= _PC.min_train_seg
                    and (m - c2 - embargo) >= _PC.min_calib_seg)

        def _seg(a, b=None):
            """处理seg。
            
                参数:
                    a
                    b"""
            X = Xn[a:b] if b is not None else Xn[a:]
            Y = Ys[a:b] if b is not None else Ys[a:]
            return X, Y

        if has_3way or has_2way:
            if has_3way:
                tr_X, tr_Y = _seg(0, c1)
                va_X, va_Y = _seg(c1 + embargo, c2)
                ca_X, ca_Y = _seg(c2 + embargo)
            else:
                # 样本不足以三分：只做 训练/校准 两段，alpha 用稳健默认值不搜索，
                # 宁可略欠拟合，也不引入选择偏差。
                tr_X, tr_Y = _seg(0, c2)
                va_X, va_Y = None, None
                ca_X, ca_Y = _seg(c2 + embargo)

            # 归一化统计量只用训练段，避免统计泄漏
            tm = tr_X.reshape(-1, n_feat).mean(0)
            ts = tr_X.reshape(-1, n_feat).std(0) + _EPS.eps_std
            tr_n = (tr_X - tm) / ts
            ca_n = (ca_X - tm) / ts

            if va_X is not None:
                va_n = (va_X - tm) / ts
                picked = _Ridge_cls.fit_with_cv(tr_n.reshape(len(tr_n), -1), tr_Y,
                                            va_n.reshape(len(va_n), -1), va_Y)
                self.best_alpha = picked.alpha

            self._train_core(tr_n, tr_Y, n_feat, epochs, force_ridge)
            cp = self._batch_pred(ca_n)                # 完全未参与训练与选参
            beta, resid = _mincer_zarnowitz(cp, ca_Y)
            mae_model = float(np.mean(np.abs(ca_Y - beta * cp)))
            mae_base = float(np.mean(np.abs(ca_Y))) + _EPS.eps_div
            self.calib_beta = beta
            self.skill = max(0.0, 1.0 - mae_model / mae_base)
            self.resid_std = resid
            self.validated = True

        # ---- 阶段 3：全量重训（保留验证集导出的 beta / σ）----
        self._train_core(Xn, Ys, n_feat, epochs, force_ridge)
        if not self.validated:
            # 数据不足以切分：退回样本内残差，但按经验因子放大以免过度自信
            preds = self._batch_pred(Xn)
            self.resid_std = (float(np.std(Ys - preds)) * _PC.unvalidated_resid_inflate
                              + _EPS.eps_resid)
            self.calib_beta = _PC.unvalidated_beta  # 未经验证的预测一律先收缩一半

        if use_ensemble and len(df) >= seq_len + _PC.ensemble_min_extra_bars:
            try:
                # M3-04：必须透传 symbol —— 否则 ensemble 内 5 处 build_features
                # 全部落到默认 "UNKNOWN" 缓存键，不同品种互相覆盖（串味）。
                self.ensemble = _MultiPeriodEnsemble_cls(symbol=symbol)
                self.ensemble.fit(df, seq_len, epochs)
            except Exception:
                self.ensemble = None
        else:
            self.ensemble = None

        self.trained = True
        self.levels = compute_levels(df)
        logger.info(f"模型训练完成，结果: trained=True, use_lstm={self.use_lstm}, "
                   f"use_ensemble={self.ensemble is not None and self.ensemble.fitted}, "
                   f"resid_std={round(self.resid_std, 6)}, calib_beta={round(self.calib_beta, 4)}, "
                   f"skill={round(self.skill, 4)}, validated={self.validated}")
        return {"trained": True, "use_lstm": self.use_lstm,
                "use_ensemble": self.ensemble is not None and self.ensemble.fitted,
                "resid_std": round(self.resid_std, 6),
                "calib_beta": round(self.calib_beta, 4),
                "skill": round(self.skill, 4),
                "validated": self.validated}

    def _model_label(self) -> str:
        """当前生效主模型的可读名（供结果元信息与 UI 展示）。

        M3-06：外部模型（TCN / GBM / TS-Transformer）要如实显示，不能被标成
        「Ridge(回退)」—— 否则使用者无法察觉自己在看哪个模型的结果。
        """
        if self.external_model is not None:
            name = type(self.external_model).__name__
            if self.use_ensemble and self.ensemble and getattr(self.ensemble, "fitted", False):
                return f"{name}+集成"
            return name
        if self.use_ensemble and self.ensemble and getattr(self.ensemble, "fitted", False):
            return "LSTM+集成"
        return "LSTM" if self.use_lstm else "Ridge(回退)"

    def _pred_one(self, Xseq: np.ndarray) -> float:
        """处理predone。
        
            参数:
                Xseq: np.ndarray
        
            返回:
                float"""
        if self.external_model is not None:
            _out = np.asarray(self.external_model.predict(Xseq[None, ...]),
                              dtype=float).reshape(-1)
            return float(_out[0]) if _out.size else 0.0
        if self.use_lstm and self.lstm is not None:
            return float(self.lstm.predict_last(Xseq))
        if self._ridge is not None:
            return self._ridge.predict(Xseq.reshape(-1))
        return 0.0

    # 单步累计对数收益的安全上下界（±60%），防止 math.exp 溢出
    # M3-11：值取自阈值中心，运行期可覆盖（改它会同时影响路径/区间/预期收益三处）
    _CUM_CLIP = _PC.cum_clip

    def _assemble(self, rets, last_close, horizon, resid_std):
        """由每日收益序列构造价格路径与 ±1σ 区间。

        对累计对数收益做裁剪：模型发散时 math.exp 会抛 OverflowError，
        这里统一夹在 ±60%（对期货已属极端），保证 UI 永不因数值爆炸崩溃。
        """
        curve = [last_close]; upper = [last_close]; lower = [last_close]
        cum = 0.0
        for h, r in enumerate(rets, 1):
            cum += (r if math.isfinite(r) else 0.0)
            cum = max(-self._CUM_CLIP, min(self._CUM_CLIP, cum))
            sigma = min(resid_std * math.sqrt(h), self._CUM_CLIP)
            curve.append(last_close * math.exp(cum))
            upper.append(last_close * math.exp(min(cum + sigma, self._CUM_CLIP)))
            lower.append(last_close * math.exp(max(cum - sigma, -self._CUM_CLIP)))
        return np.array(curve), np.array(upper), np.array(lower)

    def _roll_forward(self, arr: np.ndarray, horizon: int) -> list[float]:
        """递归多步外推（已修正归一化口径）。

        关键修复：特征矩阵 seq 处于 **z-score 空间**，而模型输出 r 是**原始**对数收益。
        旧实现直接 `new_row[0] = r`，等于把 0.005 量级的原始收益塞进标准差为 1 的
        槽位——相当于每步都把收益特征强行置 0，递归迅速收敛到固定点并持续同向累加，
        这正是「随机游走上也能给出 ±10% 预期收益」的元凶。
        现改为先把 r 映射回 z 空间再写入，波动槽同理在原始空间更新后再归一化。
        """
        mean, std = self._feat_mean, self._feat_std
        seq = (arr[-self.seq_len:] - mean) / std
        base_scaled = (arr[-1] - mean) / std
        n_feat = arr.shape[1]
        rets: list[float] = []
        for step in range(horizon):
            r = self._pred_one(seq)
            if not math.isfinite(r):
                r = 0.0
            # 验证集校准 + 步长阻尼：越远的步预测越收缩
            r_eff = r * self.calib_beta * (self.STEP_DAMPING ** step)
            rets.append(float(r_eff))

            new_row = base_scaled.copy()
            # 槽位 0 = ret：原始 -> z 空间
            new_row[0] = (r_eff - mean[0]) / std[0]
            if n_feat > 1:
                # 槽位 1 = vol：先还原到原始空间做 EMA 更新，再归一化写回
                vol_prev = seq[-1, 1] * std[1] + mean[1]
                vol_next = (_PC.vol_ema_decay * vol_prev
                            + _PC.vol_ema_alpha * abs(r_eff))
                new_row[1] = (vol_next - mean[1]) / std[1]
            seq = np.vstack([seq[1:], new_row[None, :]])
        return rets

    def _predict_next(self, df_upto: pd.DataFrame, seq_len: int | None = None,
                      symbol: str | None = None, period: str | None = None) -> float:
        """滚动样本外评估用：截至 df_upto 的窗口，预测下一根对数收益。

        M3-04：symbol / period 缺省时回落到 fit() 期记录的值，再兜底 UNKNOWN/1m，
        保证任何路径都不会静默使用「未命名」缓存键。
        """
        seq_len = seq_len or self.seq_len
        sym = symbol if symbol is not None else getattr(self, "_symbol", "UNKNOWN")
        per = period if period is not None else getattr(self, "_period", "1m")
        ind, F = self._features(df_upto, symbol=sym, period=per)
        arr = F.values.astype(float)
        if self._feat_mean is None or len(arr) < seq_len + 1:
            return 0.0
        last = (arr[-seq_len:] - self._feat_mean) / self._feat_std
        return self._pred_one(last) * self.calib_beta

    # ----------------------------- 预测 -----------------------------
    def predict(self, df: pd.DataFrame, horizon: int = 10,
               news_bias: float = 0.0, news_samples: list | None = None,
               calibrate_p_up: float | None = None, symbol: str = "UNKNOWN", period: str = "1m") -> dict:
        """执行预测。"""
        _lazy_import_ai()  # 确保 AI 子模块已加载
        """执行预测。

        news_bias：外部资讯情感偏置，范围 [-1,1]，由 news_feed 计算得到；
            非零时作为「综合分析」的辅助维度，温和修正涨跌概率与预期收益方向，
            但不替代模型主体（限制幅度，避免单一资讯过度主导）。
        news_samples：命中的资讯标题列表，仅用于结果展示与落库。
        calibrate_p_up：若提供（来自历史命中率校准），其可信度高于纯模型 p_up，
            在两者间取加权融合，使「置信度」更贴合该行情状态的历史表现。
        """
        if not self.trained:
            logger.info("模型尚未训练，开始训练新模型")
            res = self.fit(df, symbol=symbol, period=period)
            if not res.get("trained"):
                # 数据不足以训练：返回结构完整的「中性」结果，而非继续执行导致
                # `arr - None` 崩溃（旧实现在 25 根数据下必抛 TypeError）
                logger.warning("模型训练失败：数据不足")
                return self._neutral_result(df, horizon, res.get("reason", "有效样本不足"))
            logger.info("模型训练完成")
        else:
            logger.debug("使用已训练好的模型进行预测")
        ind, F = self._features(df, symbol=symbol, period=period)
        arr = F.values.astype(float)
        if len(ind) == 0 or self._feat_mean is None or len(arr) < self.seq_len:
            return self._neutral_result(df, horizon, "有效样本不足")
        last_close = float(ind["close"].iloc[-1])
        if not math.isfinite(last_close) or last_close <= 0:
            return self._neutral_result(df, horizon, "收盘价异常")

        # 收益路径：集成模式直接用多周期集成的每日收益；否则递归外推
        if self.use_ensemble and self.ensemble and self.ensemble.fitted:
            rets = list(self.ensemble.predict_daily_returns(df, horizon))
            resid_std = self.ensemble.ensemble_resid
        else:
            rets = self._roll_forward(arr, horizon)
            resid_std = self.resid_std

        resid_std = max(float(resid_std), _EPS.eps_resid)
        curve, upper, lower = self._assemble(rets, last_close, horizon, resid_std)
        mean_cum = float(np.sum(rets))
        if not math.isfinite(mean_cum):
            mean_cum = 0.0
        mean_cum = max(-self._CUM_CLIP, min(self._CUM_CLIP, mean_cum))
        sigma_h = resid_std * math.sqrt(max(horizon, 1))
        p_up = 0.5 * (1 + math.erf(mean_cum / (sigma_h * math.sqrt(2) + _EPS.eps_div)))

        # 外部资讯情感偏置：把 news_bias 经 sigmoid 转成概率偏置并温和融合
        # （限制幅度，单条资讯最多撬动约 ±12% 的涨跌概率）
        if news_bias:
            bias_p = 1.0 / (1.0 + math.exp(-news_bias * _PC.news_bias_steepness))
            p_up = _PC.news_fusion_model_w * p_up + _PC.news_fusion_bias_w * bias_p
            # 同向温和修正累计预期收益
            mean_cum = mean_cum + _PC.news_return_adjust * news_bias * abs(
                mean_cum if mean_cum else _PC.news_return_floor)
        # 历史校准：若提供校准概率，与模型 p_up 融合（校准更可信）
        if calibrate_p_up is not None:
            p_up = (_PC.calib_fusion_calib_w * float(calibrate_p_up)
                    + _PC.calib_fusion_model_w * p_up)
        p_up = max(_PC.p_up_min, min(_PC.p_up_max, p_up))

        # 指标研判
        res = resonance(ind)
        tr = trend_score(ind)
        risk = self._risk_score(ind)
        ls = self._long_short(curve[-1], last_close, res["score"], risk["score"])

        return {
            "symbol": None,
            "last_close": round(last_close, 4),
            "horizon": horizon,
            "forecast": curve.tolist(),
            "upper": upper,
            "lower": lower,
            "rets": rets,
            "p_up": round(p_up, 4),
            "p_down": round(1 - p_up, 4),
            "expected_return_pct": round(mean_cum * 100, 3),
            "resonance": res,
            "trend": tr,
            "risk": risk,
            "long_short": ls,
            "levels": self.levels,
            "news_bias": round(float(news_bias), 3) if news_bias else 0.0,
            "news_samples": list(news_samples or []),
            "model": (self._model_label()),
            "regime": self._regime(ind, tr),
            # —— 模型可信度元信息（供 UI 透明展示，不参与计算）——
            "calib_beta": round(self.calib_beta, 4),
            "skill": round(self.skill, 4),
            "validated": self.validated,
            "resid_std": round(resid_std, 6),
            "degraded": False,
            "feature_importance": self._feature_importance(),
        }

    # ------------------------------------------------------------------
    def apply_p_up_calibration(self, result: dict, calibrated: float) -> dict:
        """M3-12 ①：把历史校准概率**就地**应用到已有预测结果，替代二次 predict()。

        背景：UI 侧拿到 `calibrated_confidence / reliability_calibration` 的校准概率后，
        旧实现是带着 `calibrate_p_up=conf` **再跑一遍完整 predict()**。而该重跑唯一
        真正生效的副作用只有 `p_up`（进而 `p_down`）的加权融合，其余
        `_features / _roll_forward / ensemble.predict_daily_returns / resonance /
        trend / _risk_score / _long_short / _feature_importance` 全部是重复计算
        （结果逐字相同，因为不含随机性）。此处只做那一步融合，语义等价：

            p_final = w_calib * calibrated + w_model * p_model   （见 predict 同名分支）

        【已注明假设】旧链路融合时用的是 predict 内部**未四舍五入**的 p_up，
        而这里只能拿到结果里 round(..., 4) 后的值，二者相差 ≤ 5e-5，
        对「方向判断 / 展示精度（4 位小数）」无影响，故按等价处理。

        参数:
            result: predict() 的返回字典（就地修改并返回）
            calibrated: 历史校准概率（来自可靠性校准 / regime 命中率）

        返回:
            同一个 result 字典（便于链式使用）
        """
        if not isinstance(result, dict):
            return result
        # 与旧行为保持一致：降级（数据不足/价格异常）结果不参与校准融合，
        # 因为旧实现二次 predict() 也会直接走 _neutral_result 分支忽略校准值。
        if result.get("degraded"):
            return result
        try:
            p_model = float(result.get("p_up", 0.5))
            p_cal = float(calibrated)
        except (TypeError, ValueError):
            return result
        if not (math.isfinite(p_model) and math.isfinite(p_cal)):
            return result
        fused = (_PC.calib_fusion_calib_w * p_cal
                 + _PC.calib_fusion_model_w * p_model)
        fused = max(_PC.p_up_min, min(_PC.p_up_max, fused))
        result["p_up"] = round(fused, 4)
        result["p_down"] = round(1.0 - fused, 4)
        return result

    # ------------------------------------------------------------------
    def _neutral_result(self, df: pd.DataFrame, horizon: int, reason: str) -> dict:
        """样本不足 / 数值异常时的安全兜底：结构与正常结果完全一致的中性研判。

        这样上层 UI、落库、校准链路都无需做 None 判断，也不会把「不知道」
        误呈现为「有把握的看多/看空」。
        """
        try:
            last_close = float(df["close"].iloc[-1])
            if not math.isfinite(last_close) or last_close <= 0:
                last_close = 0.0
        except Exception:
            last_close = 0.0
        flat = [last_close] * (horizon + 1)
        return {
            "symbol": None,
            "last_close": round(last_close, 4),
            "horizon": horizon,
            "forecast": list(flat),
            "upper": np.array(flat),
            "lower": np.array(flat),
            "rets": [0.0] * horizon,
            "p_up": 0.5, "p_down": 0.5,
            "expected_return_pct": 0.0,
            "resonance": {"score": 0.0, "label": "数据不足", "details": []},
            "trend": {"score": 0.0, "state": "未知"},
            "risk": {"score": 0.0, "label": "未知", "atr_pct": 0.0},
            "long_short": {"long": 0.0, "short": 0.0, "recommend": "观望",
                           "expected_return_pct": 0.0},
            "levels": [], "news_bias": 0.0, "news_samples": [],
            "model": "不可用", "regime": "未知",
            "calib_beta": 0.0, "skill": 0.0, "validated": False,
            "resid_std": 0.0, "feature_importance": [],
            "degraded": True, "degrade_reason": reason,
        }

    # ----------------------------- 辅助研判 -----------------------------
    @staticmethod
    def _safe(x, default: float = 0.0) -> float:
        """把可能为 NaN / inf / None 的标量安全转成有限 float。"""
        try:
            v = float(x)
        except (TypeError, ValueError):
            return default
        return v if math.isfinite(v) else default

    def _risk_score(self, ind: pd.DataFrame) -> dict:
        """处理风险评分。
        
            参数:
                ind: pd.DataFrame
        
            返回:
                dict"""
        last = ind.iloc[-1]
        close = self._safe(last["close"])
        # M3-01：tech.add_indicators 产出的列名是 ATR14（不是 "ATR"），
        # 原写法恒取不到 → atr=0 → 风险分中占比 40% 的 ATR 分量永远为 0。
        atr_col = "ATR14" if "ATR14" in ind.columns else ("ATR" if "ATR" in ind.columns else None)
        atr = self._safe(ind[atr_col].iloc[-1]) if atr_col else 0.0
        atr_pct = (atr / close) if (close > 0 and atr > 0) else 0.0
        # M3-07 ③：ATR 缺失/为 0 时的兜底。
        # 【与文档的差异·已标注】文档建议兜底用 `ret.std()*sqrt(252)`（**年化**波动率），
        # 但此处的 atr_pct 是**单根 K 线**的真实波幅占比（与阈值 0.03 即「单日 3%」
        # 同量纲）。代入年化值（典型 0.2~0.4）会让 min(atr_pct/0.03, 1) 恒等于 1，
        # 风险分被顶到上限、失去区分度。故改用**同量纲的单根波动率代理**：
        # 随机游走下 E[真实波幅] ≈ 1.6σ，于是 atr_pct ≈ 1.6 * ret.std()。
        atr_source = atr_col or "none"
        if atr_pct <= 0.0:
            try:
                sigma = float(pd.Series(ind["ret"]).replace([np.inf, -np.inf], np.nan)
                              .dropna().std())
            except Exception:  # noqa: BLE001
                sigma = 0.0
            if np.isfinite(sigma) and sigma > 0:
                atr_pct = _PC.atr_sigma_multiplier * sigma
                atr_source = "ret_std_fallback"
                logger.warning("ATR 缺失或为 0，风险评分改用收益标准差兜底："
                               "atr_pct≈%.4f", atr_pct)
        # 近期最大回撤（roll_max 可能为 0/NaN，需整体防护）
        roll_max = (ind["close"].rolling(_PC.drawdown_window, min_periods=1)
                    .max().replace(0, np.nan))
        dd_series = (ind["close"] - roll_max) / roll_max
        dd = self._safe(dd_series.replace([np.inf, -np.inf], np.nan).min())
        dd = abs(dd)
        adx = self._safe(last["ADX"]) if "ADX" in ind else 0.0
        # 距最近关键价位
        dist = 1.0
        if self.levels and close > 0:
            prices = [abs(self._safe(lv.get("price")) - close) / close
                      for lv in self.levels if lv.get("price") is not None]
            dist = min(prices) if prices else 1.0
        # M3-11：四个归一化基准（3% / 10% / ADX50 / 2%）彼此独立，勿合并
        score = 100 * (_PC.risk_w_atr * min(atr_pct / _PC.risk_atr_full, 1)
                       + _PC.risk_w_drawdown * min(dd / _PC.risk_dd_full, 1)
                       + _PC.risk_w_adx * min(adx / _PC.risk_adx_full, 1)
                       + _PC.risk_w_dist * (1 - min(dist / _PC.risk_dist_full, 1)))
        score = round(min(100.0, max(0.0, score)), 1)
        label = ("低风险" if score < _PC.risk_label_low_max
                 else ("中等风险" if score < _PC.risk_label_mid_max else "高风险"))
        return {"score": score, "label": label, "atr_pct": round(atr_pct * 100, 2),
                # M3-07：atr 来源可审计（ATR14 / ATR / ret_std_fallback / none）
                "atr_source": atr_source}

    def _long_short(self, forecast_price, last_close, res_score, risk_score) -> dict:
        """处理longshort。
        
            参数:
                forecast_price
                last_close
                res_score
                risk_score
        
            返回:
                dict"""
        last_close = self._safe(last_close)
        forecast_price = self._safe(forecast_price)
        exp = (forecast_price / last_close - 1) if last_close > 0 else 0.0
        exp = max(-self._CUM_CLIP, min(self._CUM_CLIP, exp))
        res_score = max(-_PC.resonance_clip, min(_PC.resonance_clip,
                                                 self._safe(res_score)))
        p_up_like = 1 / (1 + math.exp(-res_score / _PC.resonance_sigmoid_temp))
        gain = _PC.ls_base_weight + min(abs(exp) * _PC.ls_return_gain,
                                        _PC.ls_base_weight)
        long_score = 100 * p_up_like * (1 - risk_score / 100) * gain
        short_score = 100 * (1 - p_up_like) * (1 - risk_score / 100) * gain
        rec = "偏多" if long_score > short_score else "偏空"
        if abs(long_score - short_score) < _PC.ls_neutral_gap:
            rec = "观望"
        return {"long": round(long_score, 1), "short": round(short_score, 1),
                "recommend": rec, "expected_return_pct": round(exp * 100, 3)}

    def _feature_importance(self) -> list[dict]:
        """计算特征重要性（基于模型权重绝对值排序）。

        对于 LSTM：取门控权重**输入特征分块**（跳过隐状态列）后按隐单元平均，
                  再乘输出层 |W_hy| 的均值；
        对于 Ridge：把展平的 (seq_len × n_feat) 权重 reshape 回窗口后**按时间步平均**。
        返回 [{"name":..., "importance":...}, ...] 按重要性降序（最多 10 项）。

        M3-07：任何维度不符 / 无法解释的情况都 **logger.warning + 返回空**，
        不再截断或补 1 产出看似合理、实则无意义的排名。
        """
        if not self._feat_names:
            return []
        importances = []

        n = len(self._feat_names)

        if self.external_model is not None:
            # M3-07：外部模型（TCN / GBM）没有可直接解释的「每输入特征权重」，
            # 与其编造一个均匀分布充数，不如明确返回空并说明原因。
            logger.warning("特征重要性：外部模型 %s 不提供可解释的输入权重，返回空",
                           type(self.external_model).__name__)
            return []
        if self.use_lstm and self.lstm is not None:
            # LSTM: 用输出层权重近似重要性
            try:
                wy = np.abs(np.asarray(self.lstm.Why)).flatten()   # (hid,)
                # 每个输入特征的权重 = 输出层权重 × 输入→隐藏的加权平均
                w_input = (np.asarray(self.lstm.Wi) + np.asarray(self.lstm.Wf)
                           + np.asarray(self.lstm.Wc) + np.asarray(self.lstm.Wo))
                # M3-07 ①：门控权重形状是 (hidden, hidden + input)，列的前 hidden 列
                # 属于**上一时刻隐状态**（z = concat([h, x])），不属于输入特征。
                # 旧实现直接 mean(axis=0) 得到 (hidden+input,)，再被截断到前 n 个
                # —— 取到的其实是「隐状态 0..n-1」的权重，与真实特征毫无关系。
                hid = int(getattr(self.lstm, "hid", 0) or 0)
                if w_input.ndim == 2 and hid and w_input.shape[1] > hid:
                    w_input = w_input[:, hid:]          # 跳过隐状态部分 → (hidden, input)
                else:
                    w_input = w_input.T if w_input.ndim == 2 else w_input
                feat_weights = np.abs(w_input).mean(axis=0)          # (input_size,)
                feat_importance = feat_weights * float(wy.mean()) if wy.size else feat_weights
            except Exception as e:  # noqa: BLE001
                logger.warning("特征重要性：LSTM 权重解析失败（%s），返回空", e)
                return []
        elif self._ridge is not None and self._ridge.w is not None:
            # M3-07 ①（续）：岭回归的输入是**展平的时间窗口** (seq_len × n_feat)，
            # |w| 的长度是 seq_len*n_feat。旧实现直接拿它与 n 比长度后截断/补 1，
            # 得到的是「窗口前 n 个位置」的权重，同样不是特征重要性。
            # 正确做法：reshape 回 (seq_len, n_feat) 后**按时间步取平均**。
            w = np.asarray(self._ridge.w, dtype=float).reshape(-1)
            sl = int(getattr(self, "seq_len", 0) or 0)
            if w.size == n:
                feat_importance = np.abs(w)
            elif sl > 0 and w.size == sl * n:
                feat_importance = np.abs(w.reshape(sl, n)).mean(axis=0)
            else:
                logger.warning("特征重要性：岭回归权重维度 %d 与特征数 %d 不匹配"
                               "（seq_len=%d），返回空", w.size, n, sl)
                return []
        else:
            return []

        # M3-07 ②：维度不符时告警并返回空，**不再**截断/补 1 产出无意义排名
        if len(feat_importance) != n:
            logger.warning("特征重要性：权重维度 %d 与特征数 %d 不一致，返回空",
                           len(feat_importance), n)
            return []

        # 归一化并排序
        total = feat_importance.sum()
        if total > 0:
            feat_importance = feat_importance / total
        else:
            feat_importance = np.ones(n) / n

        indices = np.argsort(feat_importance)[::-1]
        importances = [
            {"name": self._feat_names[i], "importance": round(float(feat_importance[i]), 4)}
            for i in indices[:min(_PC.feature_importance_top_n, n)]  # 只返回 Top N
        ]
        return importances

    def _regime(self, ind: pd.DataFrame, tr: dict) -> str:
        """处理regime。
        
            参数:
                ind: pd.DataFrame
                tr: dict
        
            返回:
                str"""
        last = ind.iloc[-1]
        adx = self._safe(last["ADX"]) if "ADX" in ind else 0.0
        # 布林带宽（BOLL_MID 可能为 0，需防除零）
        bw = 0.0
        if "BOLL_UP" in ind and "BOLL_LOW" in ind and "BOLL_MID" in ind:
            mid = self._safe(ind["BOLL_MID"].iloc[-1])
            if mid:
                bw = self._safe((self._safe(ind["BOLL_UP"].iloc[-1])
                                 - self._safe(ind["BOLL_LOW"].iloc[-1])) / mid)
        # M3-11：阈值与 `evaluate_regime` 共用同一来源，杜绝两处各写一遍后脱钩
        if adx > _PC.adx_trend_threshold and tr["state"] in ("多头趋势", "空头趋势"):
            return "趋势行情"
        if bw < _PC.boll_band_squeeze:
            return "震荡收敛(变盘窗口)"
        return "震荡行情"

    # ----------------------------- 评估 -----------------------------
    def _evaluate_core(self, df: pd.DataFrame, horizon: int = 1, seq_len: int = 20,
                       epochs: int = 30, extended_features: bool = False,
                       use_ensemble: bool = False, symbol: str = "UNKNOWN",
                       period: str = "1m", use_walk_forward: bool = True) -> dict:
        """评估的**唯一实现**（M3-12）：跑一次，产出指标 + 逐样本中间结果。

        `evaluate` 与 `evaluate_regime` 都基于本方法，因此两者口径天然一致。
        改造前 `evaluate_regime` 自己又做了一遍「特征工程 + 建序列 + 训练 +
        预测」（且用的是固定 80/20，而 `evaluate` 默认走 Walk-Forward），
        既慢一倍，又让「总体指标」与「分行情指标」来自两套不同的评估。

        返回 dict：
            error: 数据不足时仅有此键；
            metrics: 公开指标字典（= `evaluate` 的返回值）；
            val_preds / Y_val: 验证段逐样本预测与真值（供分行情统计复用）；
            val_pos: 每个验证样本在 df 中的行号（供行情标签对齐）；
            regime_labels: 与 df 行对齐的行情标签（np.ndarray，向量化判定）。
        """
        # 确保数据足够
        if len(df) < seq_len + _PC.eval_min_extra_bars:
            return {"error": "数据不足以进行评估"}

        # 特征工程
        ind, F = self._features(df, symbol=symbol, period=period)
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)  # 预测下一根对数收益

        # 构造序列
        Xs, Ys = self._build_sequences(arr, y, seq_len)
        if len(Xs) < _PC.eval_min_samples:
            return {"error": "有效样本不足"}

        # 时序切分 —— M3-05：use_walk_forward=True 走**真·Walk-Forward**
        #
        # 【修复前】旧实现名义上叫 walk-forward，实际只做了一次「85% 训练 / 15% 验证」
        # 的单点切分（`split_idx = int(len(Xs) * 0.85)`），与 use_walk_forward=False 的
        # 80/20 没有本质区别 —— 名不副实，且只能看到单一时间段的样本外表现。
        # 【修复后】调用 ai/validation.py 的 WalkForward.folds_plan() 生成因果折叠，
        # 每折只用该折训练段训练 + 归一化，再预测该折测试段，最后拼接成完整 OOS。
        wf_used = False
        wf_folds: list = []
        wf_train_samples = 0
        conf = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        val_pos = np.empty(0, dtype=int)      # 验证样本在 df 中的行号

        if use_walk_forward:
            wf = _walk_forward_plan(len(Xs))
            if wf is not None:
                wf_used = True
                oos_pred, oos_true, oos_pos = [], [], []
                for p in wf:
                    x_tr = Xs[p["train_start"]:p["train_end"]]
                    y_tr = Ys[p["train_start"]:p["train_end"]]
                    x_te = Xs[p["test_start"]:p["test_end"]]
                    y_te = Ys[p["test_start"]:p["test_end"]]
                    # 归一化统计量**只来自本折训练段**（防泄漏）
                    m = x_tr.reshape(-1, x_tr.shape[-1]).mean(0)
                    s = x_tr.reshape(-1, x_tr.shape[-1]).std(0) + _EPS.eps_std
                    fold_pred = FuturesPredictor()
                    fold_pred.extended_features = extended_features
                    fold_pred.seq_len = seq_len
                    fold_pred._feat_mean, fold_pred._feat_std = m, s
                    fold_pred._train_core((x_tr - m) / s, y_tr, arr.shape[1], epochs, False)
                    pr = np.asarray(fold_pred._batch_pred((x_te - m) / s), dtype=float)
                    # 多空分界用**训练段收益中位数**（与 validation.WalkForward 同口径）
                    thr = float(np.median(y_tr)) if len(y_tr) else 0.0
                    yd = (np.asarray(y_te, dtype=float) > thr).astype(int)
                    pd_ = (pr > thr).astype(int)
                    conf["tp"] += int(np.sum((yd == 1) & (pd_ == 1)))
                    conf["fp"] += int(np.sum((yd == 0) & (pd_ == 1)))
                    conf["fn"] += int(np.sum((yd == 1) & (pd_ == 0)))
                    conf["tn"] += int(np.sum((yd == 0) & (pd_ == 0)))
                    oos_pred.append(pr)
                    oos_true.append(np.asarray(y_te, dtype=float))
                    oos_pos.append(np.arange(p["test_start"], p["test_end"]))
                    wf_folds.append({
                        "fold": int(p["fold"]),
                        "train": [int(p["train_start"]), int(p["train_end"])],
                        "test": [int(p["test_start"]), int(p["test_end"])],
                        "n_test": int(len(y_te)),
                        "threshold": thr,
                    })
                val_preds = np.concatenate(oos_pred)
                Y_val = np.concatenate(oos_true)
                val_pos = np.concatenate(oos_pos)
                wf_train_samples = int(wf[-1]["train_end"] - wf[-1]["train_start"])
                X_train = Xs[:wf[-1]["train_end"]]
                Y_train = Ys[:wf[-1]["train_end"]]
                tp, fp, fn, tn = conf["tp"], conf["fp"], conf["fn"], conf["tn"]

        if not wf_used:
            # 固定 80/20 分割（样本量不足跑不出 ≥3 折时的回退，保留原行为）
            split_idx = int(len(Xs) * _PC.eval_train_ratio)
            X_train, Y_train = Xs[:split_idx], Ys[:split_idx]
            X_val, Y_val = Xs[split_idx:], Ys[split_idx:]
            # 归一化（仅使用训练集统计量，防止数据泄漏）
            mean = X_train.reshape(-1, X_train.shape[-1]).mean(0)
            std = X_train.reshape(-1, X_train.shape[-1]).std(0) + _EPS.eps_std
            X_train_n = (X_train - mean) / std
            X_val_n = (X_val - mean) / std

            # 训练模型（复用内部训练逻辑，但不更新 self 的状态）
            temp_pred = FuturesPredictor()
            temp_pred.extended_features = extended_features
            temp_pred.use_ensemble = use_ensemble
            temp_pred.seq_len = seq_len
            temp_pred._feat_mean = mean
            temp_pred._feat_std = std
            temp_pred._train_core(X_train_n, Y_train, arr.shape[1], epochs, False)

            val_preds = temp_pred._batch_pred(X_val_n)
            val_pos = np.arange(split_idx, len(Xs))

            # 方向预测（对数收益以 0 为多空分界）
            y_true_dir = (Y_val > 0).astype(int)
            y_pred_dir = (val_preds > 0).astype(int)
            tp = int(np.sum((y_true_dir == 1) & (y_pred_dir == 1)))
            fp = int(np.sum((y_true_dir == 0) & (y_pred_dir == 1)))
            fn = int(np.sum((y_true_dir == 1) & (y_pred_dir == 0)))
            tn = int(np.sum((y_true_dir == 0) & (y_pred_dir == 0)))

        direction_acc = (tp + tn) / (len(Y_val) + _EPS.eps_div)
        precision = tp / (tp + fp + _EPS.eps_div)
        recall = tp / (tp + fn + _EPS.eps_div)
        f1 = 2 * precision * recall / (precision + recall + _EPS.eps_div)

        # 回归指标
        mae = np.mean(np.abs(Y_val - val_preds))
        rmse = np.sqrt(np.mean((Y_val - val_preds) ** 2))
        # R-squared
        ss_res = np.sum((Y_val - val_preds) ** 2)
        ss_tot = np.sum((Y_val - np.mean(Y_val)) ** 2)
        r_squared = 1 - ss_res / (ss_tot + _EPS.eps_div)

        # 金融性能指标（基于预测收益率）
        # 计算策略收益：每天根据预测方向开仓，假设固定持仓1天
        if len(Y_val) > 0 and np.std(val_preds) > 0:
            # 按预测方向分配信号：正预测->多头，负预测->空头
            strategy_returns = val_preds  # 使用预测值作为收益率代理
            # 年化夏普率（假设252个交易日，无风险利率按2%年化折算为日0.0002）
            risk_free_daily = _PC.risk_free_annual / _PC.annual_trading_days
            excess_returns = strategy_returns - risk_free_daily
            sharpe_ratio = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(_PC.annual_trading_days) if np.std(excess_returns) > 0 else 0.0

            # 计算最大回撤
            cumulative_returns = np.cumprod(1 + strategy_returns)
            running_max = np.maximum.accumulate(cumulative_returns)
            drawdown = (cumulative_returns - running_max) / running_max
            max_drawdown = np.min(drawdown)
        else:
            sharpe_ratio = 0.0
            max_drawdown = 0.0

        out = {
            "direction_acc": float(direction_acc),
            "direction_precision": float(precision),
            "direction_recall": float(recall),
            "direction_f1": float(f1),
            "mae": float(mae),
            "rmse": float(rmse),
            "r_squared": float(r_squared),
            "sharpe_ratio": float(sharpe_ratio),
            "max_drawdown": float(max_drawdown),
            "val_samples": int(len(Y_val)),
            "train_samples": int(wf_train_samples if wf_used else len(Y_train)),
        }
        # M3-05：Walk-Forward 结果透明化 —— 调用方可据此确认「真的滚起来了」
        out["walk_forward"] = bool(wf_used)
        out["n_folds"] = int(len(wf_folds)) if wf_used else 0
        out["folds"] = wf_folds

        return {
            "metrics": out,
            "val_preds": np.asarray(val_preds, dtype=float),
            "Y_val": np.asarray(Y_val, dtype=float),
            # Xs 第 k 个样本对应 df 的第 (seq_len-1+k) 行（见 _build_sequences）
            "val_pos": np.asarray(val_pos, dtype=int) + (seq_len - 1),
            "regime_labels": self._regime_labels(ind),
        }

    @staticmethod
    def _regime_labels(ind: pd.DataFrame) -> np.ndarray:
        """与 df 行对齐的行情标签（**向量化**，替换改造前的逐行 Python 循环）。

        判定口径与 `_regime` 保持同源（同一组阈值），但不要求 `trend_score` 的
        「多头/空头趋势」状态 —— 分行情统计只按 ADX / 布林带宽粗分三档。
        """
        adx = (ind["ADX"].to_numpy(dtype=float)
               if "ADX" in ind.columns else np.zeros(len(ind)))
        if all(c in ind.columns for c in ("BOLL_UP", "BOLL_LOW", "BOLL_MID")):
            mid = pd.to_numeric(ind["BOLL_MID"], errors="coerce").replace(0, np.nan)
            bw = ((pd.to_numeric(ind["BOLL_UP"], errors="coerce")
                   - pd.to_numeric(ind["BOLL_LOW"], errors="coerce")) / mid)
            bw = bw.fillna(0.0).to_numpy(dtype=float)
        else:
            bw = np.zeros(len(ind))
        return np.where(
            adx > _PC.adx_trend_threshold, "趋势行情",
            np.where(bw < _PC.boll_band_squeeze, "震荡收敛(变盘窗口)", "震荡行情"))

    def evaluate(self, df: pd.DataFrame, horizon: int = 1, seq_len: int = 20,
                 epochs: int = 30, extended_features: bool = False,
                 use_ensemble: bool = False, symbol: str = "UNKNOWN", period: str = "1m",
                 use_walk_forward: bool = True) -> dict:
        """评估模型在给定数据上的性能。这是模型迭代流程中的关键步骤。

        M3-12：本体已下沉到 `_evaluate_core`，本方法只取公开指标部分。
        
        评估流程：
        1. 数据准备：特征工程和序列构建（与训练过程保持一致）
        2. 时序切分：采用滚动窗口/走行前验证策略，确保模型在未见数据上的表现
        3. 模型训练：在训练集上使用与 fit 方法相同的配置训练临时模型
        4. 性能评估：在验证集上评估模型表现，返回多维度性能指标
        
        评估指标说明：
        - direction_acc: 上涨/下跌方向准确率，衡量模型预测方向的正确性
        - direction_precision: 精确率，预测为上涨中实际上涨的比例
        - direction_recall: 召回率，实际上涨中被正确预测的比例
        - direction_f1: F1 分数，精确率和召回率的调和平均数
        - mae: 平均绝对误差（对数收益），衡量预测值的平均绝对偏离程度
        - rmse: 均方根误差，对较大误差更敏感的误差度量
        - r_squared: 决定系数，模型解释目标变量变化的比例
        - sharpe_ratio: 夏普率（年化，假设252交易日）
        - max_drawdown: 最大回撤
        
        参数:
            use_walk_forward: 是否使用走行前验证（ expanding window），
                True: 使用扩展窗口验证，更真实模拟实盘情况
                False: 使用固定 80/20 分割，速度更快用于快速原型验证
        
        使用建议：
        - 定期评估模型性能以判断是否需要重新训练（性能显著下降时）
        - 在生产环境中建议使用 use_walk_forward=True 以获得更可靠的性能估计
        - 将评估结果作为模型迭代决策的重要依据
        - 对比不同特征集或模型参数的评估结果以选择最优配置
        
        返回包含以下指标的字典：
            - direction_acc: 上涨/下跌方向准确率
            - direction_precision, recall, f1: 二分类精准率、召回率、F1
            - mae: 平均绝对误差（对数收益）
            - rmse: 均方根误差
            - r_squared: 决定系数
            - sharpe_ratio: 夏普率（年化）
            - max_drawdown: 最大回撤
        """
        core = self._evaluate_core(df, horizon, seq_len, epochs,
                                   extended_features, use_ensemble,
                                   symbol, period, use_walk_forward)
        if "error" in core:
            return core
        return core["metrics"]

    def evaluate_regime(self, df: pd.DataFrame, horizon: int = 1, seq_len: int = 20,
                        epochs: int = 30, extended_features: bool = False,
                        use_ensemble: bool = False, symbol: str = "UNKNOWN",
                        period: str = "1m", use_walk_forward: bool = True) -> dict:
        """评估模型在不同市场状态下的性能。

        返回包含总体指标以及各行情（趋势、震荡收敛、震荡）的指标字典。

        M3-12：**不再重跑一遍评估**。改造前本方法先调 `evaluate()` 拿总体指标，
        然后又自己做了「特征工程 → 建序列 → 训练 → 预测」四步来拿逐样本预测，
        且用的是固定 80/20（而 `evaluate` 默认 Walk-Forward）——总体指标与分行情
        指标因此来自**两套不同口径**。现改为复用 `_evaluate_core` 的同一次运行：
            · 省掉 1 次特征工程 + 1 次建序列 + 1 次训练；
            · `overall` 与 `evaluate(...)` 完全相同（同一份 val_preds / Y_val）；
            · 删掉原先的逐行 `ind.apply(...)` 死代码（其结果 `regimes` 从未被使用）。

        【额外修正·已注明】行情标签与验证样本的对齐：序列 Xs[k] 覆盖
        `arr[seq_len-1+k]`，即对应 df 第 `seq_len-1+k` 行。旧代码直接用 Xs 下标
        去取 `regime_labels[...]`，**偏移了 seq_len-1**，分组实际错位。此处按
        `_build_sequences` 的真实下标映射修正（会改变分行情统计结果）。
        """
        _prev_ext = self.extended_features
        self.extended_features = extended_features
        try:
            core = self._evaluate_core(df, horizon, seq_len, epochs,
                                       extended_features, use_ensemble,
                                       symbol, period, use_walk_forward)
        finally:
            self.extended_features = _prev_ext
        if "error" in core:
            return core

        overall = core["metrics"]
        val_preds = core["val_preds"]
        Y_val = core["Y_val"]
        labels = core["regime_labels"]
        # val_pos 已是「df 行号」，直接按它取对应行的行情标签
        pos = np.clip(core["val_pos"], 0, max(len(labels) - 1, 0))
        val_regimes = labels[pos]

        # 按 regime 分组计算指标
        regime_metrics = {}
        for reg in sorted(set(val_regimes.tolist())):
            mask = val_regimes == reg
            if not np.any(mask):
                continue
            y_true_reg = Y_val[mask]
            y_pred_reg = val_preds[mask]
            # 方向
            y_true_dir = (y_true_reg > 0).astype(int)
            y_pred_dir = (y_pred_reg > 0).astype(int)
            tp = np.sum((y_true_dir == 1) & (y_pred_dir == 1))
            fp = np.sum((y_true_dir == 0) & (y_pred_dir == 1))
            fn = np.sum((y_true_dir == 1) & (y_pred_dir == 0))
            tn = np.sum((y_true_dir == 0) & (y_pred_dir == 0))
            acc = (tp + tn) / (len(y_true_reg) + _EPS.eps_div)
            precision = tp / (tp + fp + _EPS.eps_div)
            recall = tp / (tp + fn + _EPS.eps_div)
            f1 = 2 * precision * recall / (precision + recall + _EPS.eps_div)
            mae = np.mean(np.abs(y_true_reg - y_pred_reg))
            rmse = np.sqrt(np.mean((y_true_reg - y_pred_reg) ** 2))
            ss_res = np.sum((y_true_reg - y_pred_reg) ** 2)
            ss_tot = np.sum((y_true_reg - np.mean(y_true_reg)) ** 2)
            r_squared = 1 - ss_res / (ss_tot + _EPS.eps_div)
            regime_metrics[reg] = {
                "direction_acc": float(acc),
                "direction_precision": float(precision),
                "direction_recall": float(recall),
                "direction_f1": float(f1),
                "mae": float(mae),
                "rmse": float(rmse),
                "r_squared": float(r_squared),
                "samples": int(len(y_true_reg))
            }
        
        return {
            "overall": overall,
            "by_regime": regime_metrics
        }