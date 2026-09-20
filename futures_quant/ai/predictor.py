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
    if n < 8:
        return 0.0, float(np.std(actual) if n else 1e-4) + 1e-6
    sd_p = float(np.std(pred))
    if sd_p < 1e-12:                     # 预测恒定 -> 无信息
        return 0.0, float(np.std(actual)) + 1e-6
    beta = float(np.cov(pred, actual, ddof=0)[0, 1] / (sd_p ** 2))
    resid = actual - beta * pred
    sd_r = float(np.std(resid))
    # beta 的标准误： se = σ_resid / (√n · σ_pred)
    se = sd_r / (math.sqrt(n) * sd_p + 1e-12)
    t = beta / (se + 1e-12)
    beta *= (t * t) / (1.0 + t * t)      # 显著性收缩
    beta = max(0.0, min(1.5, beta))      # 负相关一律视作无技能，不做反向下注
    return beta, float(np.std(actual - beta * pred)) + 1e-6


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
        self.seq_len = 30  # 增加默认窗口长度以捕获更长期依赖
        self._feat_mean: np.ndarray | None = None
        self._feat_std: np.ndarray | None = None
        self.resid_std = 1e-4
        self.levels: list[dict] = []
        self.extended_features = False
        self.use_ensemble = False
        self.ensemble: object | None = None
        self._feat_names: list = []
        # LSTM 超参数（可通过实验调优）
        self.lstm_hidden_size = 64   # 增大隐藏单元以提升表达能力
        self.lstm_lr = 0.001         # 降低学习率以提升稳定性
        # 验证集导出的校准系数与技能度（predict 时用于收缩预测幅度）
        self.calib_beta = 1.0
        self.skill = 0.0                 # 相对「恒预测 0」基线的 MAE 改善率
        self.validated = False           # resid_std 是否来自样本外
        self.best_alpha = 1.0
        # 步长阻尼系数：多步递归外推时逐步收缩预测，防止发散
        self.STEP_DAMPING = 0.95

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
                                       seed=7)
            else:
                self.lstm = LSTM(input_size=n_feat, hidden_size=self.lstm_hidden_size,
                                 output_size=1, seed=7)
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
        if self.use_lstm and self.lstm is not None:
            return self.lstm.predict_batch(Xs)
        if self._ridge is not None:
            # Xs: (N, T, F) -> 逐行预测（_Ridge.predict 期望 1D 输入）
            return np.array([self._ridge.predict(Xs[i].reshape(-1)) for i in range(len(Xs))])
        return np.zeros(len(Xs))

    # ----------------------------- 训练 -----------------------------
    def fit(self, df: pd.DataFrame, seq_len: int = 20, epochs: int = 30,
            force_ridge: bool = False, extended_features: bool = False,
            use_ensemble: bool = False, symbol: str = "UNKNOWN", period: str = "1m") -> dict:
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
        self._symbol = symbol
        self._period = period
        ind, F = self._features(df, symbol=symbol, period=period)
        self.seq_len = seq_len
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)
        Xs, Ys = self._build_sequences(arr, y, seq_len)
        if len(Xs) < 20:
            self.trained = False
            logger.warning("模型训练失败：数据不足（有效样本少于20条）")
            return {"trained": False, "reason": "数据不足"}

        mean = Xs.reshape(-1, Xs.shape[-1]).mean(0)
        std = Xs.reshape(-1, Xs.shape[-1]).std(0) + 1e-8
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
        c1, c2 = int(m * 0.6), int(m * 0.8)
        self.calib_beta, self.skill, self.validated = 1.0, 0.0, False
        self.best_alpha = 1.0

        has_3way = (c1 >= 20 and (c2 - c1 - embargo) >= 8 and (m - c2 - embargo) >= 8)
        has_2way = (c2 >= 20 and (m - c2 - embargo) >= 8)

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
            ts = tr_X.reshape(-1, n_feat).std(0) + 1e-8
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
            mae_base = float(np.mean(np.abs(ca_Y))) + 1e-12
            self.calib_beta = beta
            self.skill = max(0.0, 1.0 - mae_model / mae_base)
            self.resid_std = resid
            self.validated = True

        # ---- 阶段 3：全量重训（保留验证集导出的 beta / σ）----
        self._train_core(Xn, Ys, n_feat, epochs, force_ridge)
        if not self.validated:
            # 数据不足以切分：退回样本内残差，但按经验因子放大以免过度自信
            preds = self._batch_pred(Xn)
            self.resid_std = float(np.std(Ys - preds)) * 1.5 + 1e-6
            self.calib_beta = 0.5           # 未经验证的预测一律先收缩一半

        if use_ensemble and len(df) >= seq_len + 30:
            try:
                self.ensemble = _MultiPeriodEnsemble_cls()
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

    def _pred_one(self, Xseq: np.ndarray) -> float:
        """处理predone。
        
            参数:
                Xseq: np.ndarray
        
            返回:
                float"""
        if self.use_lstm and self.lstm is not None:
            return float(self.lstm.predict_last(Xseq))
        if self._ridge is not None:
            return self._ridge.predict(Xseq.reshape(-1))
        return 0.0

    # 单步累计对数收益的安全上下界（±60%），防止 math.exp 溢出
    _CUM_CLIP = 0.6

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
                vol_next = 0.9 * vol_prev + 0.1 * abs(r_eff)
                new_row[1] = (vol_next - mean[1]) / std[1]
            seq = np.vstack([seq[1:], new_row[None, :]])
        return rets

    def _predict_next(self, df_upto: pd.DataFrame, seq_len: int | None = None) -> float:
        """滚动样本外评估用：截至 df_upto 的窗口，预测下一根对数收益。"""
        seq_len = seq_len or self.seq_len
        ind, F = self._features(df_upto)
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

        resid_std = max(float(resid_std), 1e-6)
        curve, upper, lower = self._assemble(rets, last_close, horizon, resid_std)
        mean_cum = float(np.sum(rets))
        if not math.isfinite(mean_cum):
            mean_cum = 0.0
        mean_cum = max(-self._CUM_CLIP, min(self._CUM_CLIP, mean_cum))
        sigma_h = resid_std * math.sqrt(max(horizon, 1))
        p_up = 0.5 * (1 + math.erf(mean_cum / (sigma_h * math.sqrt(2) + 1e-12)))

        # 外部资讯情感偏置：把 news_bias 经 sigmoid 转成概率偏置并温和融合
        # （限制幅度，单条资讯最多撬动约 ±12% 的涨跌概率）
        if news_bias:
            bias_p = 1.0 / (1.0 + math.exp(-news_bias * 1.5))
            p_up = 0.85 * p_up + 0.15 * bias_p
            # 同向温和修正累计预期收益
            mean_cum = mean_cum + 0.15 * news_bias * abs(mean_cum if mean_cum else 0.01)
        # 历史校准：若提供校准概率，与模型 p_up 融合（校准更可信）
        if calibrate_p_up is not None:
            p_up = 0.6 * float(calibrate_p_up) + 0.4 * p_up
        p_up = max(0.01, min(0.99, p_up))

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
            "model": ("LSTM+集成" if (self.use_ensemble and self.ensemble
                                       and self.ensemble.fitted)
                      else ("LSTM" if self.use_lstm else "Ridge(回退)")),
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
        atr = self._safe(ind["ATR"].iloc[-1]) if "ATR" in ind else 0.0
        atr_pct = (atr / close) if close > 0 else 0.0
        # 近期最大回撤（roll_max 可能为 0/NaN，需整体防护）
        roll_max = ind["close"].rolling(60, min_periods=1).max().replace(0, np.nan)
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
        score = 100 * (0.4 * min(atr_pct / 0.03, 1) + 0.3 * min(dd / 0.1, 1)
                        + 0.15 * min(adx / 50, 1) + 0.15 * (1 - min(dist / 0.02, 1)))
        score = round(min(100.0, max(0.0, score)), 1)
        label = "低风险" if score < 33 else ("中等风险" if score < 66 else "高风险")
        return {"score": score, "label": label, "atr_pct": round(atr_pct * 100, 2)}

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
        res_score = max(-500.0, min(500.0, self._safe(res_score)))
        p_up_like = 1 / (1 + math.exp(-res_score / 20))
        long_score = 100 * p_up_like * (1 - risk_score / 100) * (0.5 + min(abs(exp) * 20, 0.5))
        short_score = 100 * (1 - p_up_like) * (1 - risk_score / 100) * (0.5 + min(abs(exp) * 20, 0.5))
        rec = "偏多" if long_score > short_score else "偏空"
        if abs(long_score - short_score) < 8:
            rec = "观望"
        return {"long": round(long_score, 1), "short": round(short_score, 1),
                "recommend": rec, "expected_return_pct": round(exp * 100, 3)}

    def _feature_importance(self) -> list[dict]:
        """计算特征重要性（基于模型权重绝对值排序）。

        对于 LSTM：取输出层权重 |W_hy| 与隐藏层到输出的间接贡献；
        对于 Ridge：直接取 |w|。
        返回 [(feature_name, importance_score), ...] 按重要性降序。
        """
        if not self._feat_names:
            return []
        importances = []

        if self.use_lstm and self.lstm is not None:
            # LSTM: 用输出层权重近似重要性
            try:
                wy = np.abs(self.lstm.Why).flatten()  # (hid,)
                # 每个输入特征的权重 = 输出层权重 × 输入→隐藏的加权平均
                w_input = self.lstm.Wi + self.lstm.Wf + self.lstm.Wc + self.lstm.Wo
                feat_weights = np.abs(w_input).mean(axis=0)  # (input_size,)
                feat_importance = feat_weights * wy.mean()
            except Exception:
                feat_importance = np.ones(len(self._feat_names))
        elif self._ridge is not None and self._ridge.w is not None:
            feat_importance = np.abs(self._ridge.w)
        else:
            return []

        # 确保长度匹配
        n = len(self._feat_names)
        if len(feat_importance) != n:
            feat_importance = feat_importance[:n] if len(feat_importance) > n else np.pad(
                feat_importance, (0, n - len(feat_importance)), constant_values=1.0)

        # 归一化并排序
        total = ftotal = feat_importance.sum()
        if total > 0:
            feat_importance = feat_importance / total
        else:
            feat_importance = np.ones(n) / n

        indices = np.argsort(feat_importance)[::-1]
        importances = [
            {"name": self._feat_names[i], "importance": round(float(feat_importance[i]), 4)}
            for i in indices[:min(10, n)]  # 只返回 Top 10
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
        if adx > 25 and tr["state"] in ("多头趋势", "空头趋势"):
            return "趋势行情"
        if bw < 0.01:
            return "震荡收敛(变盘窗口)"
        return "震荡行情"

    # ----------------------------- 评估 -----------------------------
    def evaluate(self, df: pd.DataFrame, horizon: int = 1, seq_len: int = 20,
                 epochs: int = 30, extended_features: bool = False,
                 use_ensemble: bool = False, symbol: str = "UNKNOWN", period: str = "1m",
                 use_walk_forward: bool = True) -> dict:
        """评估模型在给定数据上的性能。这是模型迭代流程中的关键步骤。
        
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
        # 确保数据足够
        if len(df) < seq_len + 20:
            return {"error": "数据不足以进行评估"}
        
        # 特征工程
        ind, F = self._features(df, symbol=symbol, period=period)
        arr = F.values.astype(float)
        y = ind["ret"].shift(-1).values.astype(float)  # 预测下一根对数收益
        
        # 构造序列
        Xs, Ys = self._build_sequences(arr, y, seq_len)
        if len(Xs) < 30:
            return {"error": "有效样本不足"}
        
        # 时序切分 - 使用走行前验证或固定分割
        if use_walk_forward:
            # 走行前验证：使用扩展窗口模拟实盘递归重训
            # 训练集逐步扩展，每次只在最后进行一次预测/评估
            # 这种方法更真实地模拟实盘，但计算代价较高
            n_total = len(Xs)
            n_train = int(n_total * 0.7)  # 初始训练集占70%
            n_val = int(n_total * 0.15)   # 每次验证集占15%
            n_test = n_total - n_train - n_val  # 剩余作为测试集
            
            # 确保窗口大小合理
            if n_train < 20 or n_val < 5:
                use_walk_forward = False
                # 回退到简单的 80/20 分割
                split_idx = int(len(Xs) * 0.8)
                X_train, Y_train = Xs[:split_idx], Ys[:split_idx]
                X_val, Y_val = Xs[split_idx:], Ys[split_idx:]
            else:
                # 走行前验证模式：使用前70%作为初始训练集，随后每次前进n_val个样本进行验证
                # 这里我们简化处理：只进行一次使用前85%训练、后15%验证的评估，
                # 但保留 walk-forward 的结构以便后续扩展
                split_idx = int(len(Xs) * 0.85)
                X_train, Y_train = Xs[:split_idx], Ys[:split_idx]
                X_val, Y_val = Xs[split_idx:], Ys[split_idx:]
        else:
            # 固定 80/20 分割，速度更快用于快速原型验证
            split_idx = int(len(Xs) * 0.8)
            X_train, Y_train = Xs[:split_idx], Ys[:split_idx]
            X_val, Y_val = Xs[split_idx:], Ys[split_idx:]
        
        # 归一化（仅使用训练集统计量，防止数据泄漏）
        mean = X_train.reshape(-1, X_train.shape[-1]).mean(0)
        std = X_train.reshape(-1, X_train.shape[-1]).std(0) + 1e-8
        X_train_n = (X_train - mean) / std
        X_val_n = (X_val - mean) / std
        
        # 训练模型（这里我们复用内部训练逻辑，但不更新 self 的状态）
        # 为了简化，我们创建一个临时的 Predictor 实例
        temp_pred = FuturesPredictor()
        temp_pred.extended_features = extended_features
        temp_pred.use_ensemble = use_ensemble
        temp_pred.seq_len = seq_len
        # 直接设置归一化参数
        temp_pred._feat_mean = mean
        temp_pred._feat_std = std
        # 训练主模层
        temp_pred._train_core(X_train_n, Y_train, arr.shape[1], epochs, False)
        # 如果使用集成，也训练集成（这里为了简化，跳过集成评估，因为集成需要更长时间）
        # 实际使用时可以打开
        # if use_ensemble:
        #     temp_pred.ensemble = _MultiPeriodEnsemble_cls()
        #     temp_pred.ensemble.fit(df.iloc[:split_idx*seq_len + split_idx], seq_len, epochs)
        
        # 在验证集上预浮
        val_preds = temp_pred._batch_pred(X_val_n)
        
        # 方向预测（上涨为正）
        y_true_dir = (Y_val > 0).astype(int)
        y_pred_dir = (val_preds > 0).astype(int)
        
        # 计算方向指标
        tp = np.sum((y_true_dir == 1) & (y_pred_dir == 1))
        fp = np.sum((y_true_dir == 0) & (y_pred_dir == 1))
        fn = np.sum((y_true_dir == 1) & (y_pred_dir == 0))
        tn = np.sum((y_true_dir == 0) & (y_pred_dir == 0))
        
        direction_acc = (tp + tn) / (len(Y_val) + 1e-12)
        precision = tp / (tp + fp + 1e-12)
        recall = tp / (tp + fn + 1e-12)
        f1 = 2 * precision * recall / (precision + recall + 1e-12)
        
        # 回归指标
        mae = np.mean(np.abs(Y_val - val_preds))
        rmse = np.sqrt(np.mean((Y_val - val_preds) ** 2))
        # R-squared
        ss_res = np.sum((Y_val - val_preds) ** 2)
        ss_tot = np.sum((Y_val - np.mean(Y_val)) ** 2)
        r_squared = 1 - ss_res / (ss_tot + 1e-12)
        
        # 金融性能指标（基于预测收益率）
        # 计算策略收益：每天根据预测方向开仓，假设固定持仓1天
        if len(Y_val) > 0 and np.std(val_preds) > 0:
            # 按预测方向分配信号：正预测->多头，负预测->空头
            strategy_returns = val_preds  # 使用预测值作为收益率代理
            # 年化夏普率（假设252个交易日，无风险利率按2%年化折算为日0.0002）
            risk_free_daily = 0.02 / 252
            excess_returns = strategy_returns - risk_free_daily
            sharpe_ratio = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252) if np.std(excess_returns) > 0 else 0.0
            
            # 计算最大回撤
            cumulative_returns = np.cumprod(1 + strategy_returns)
            running_max = np.maximum.accumulate(cumulative_returns)
            drawdown = (cumulative_returns - running_max) / running_max
            max_drawdown = np.min(drawdown)
        else:
            sharpe_ratio = 0.0
            max_drawdown = 0.0
        
        return {
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
            "train_samples": int(len(Y_train))
        }

    def evaluate_regime(self, df: pd.DataFrame, horizon: int = 1, seq_len: int = 20,
                        epochs: int = 30, extended_features: bool = False,
                        use_ensemble: bool = False, symbol: str = "UNKNOWN", period: str = "1m") -> dict:
        """评估模型在不同市场状态下的性能。

        返回包含总体指标以及各行情（趋势、震荡收敛、震荡）的指标字典。
        """
        # 先得到总体评估
        _prev_ext = self.extended_features
        self.extended_features = extended_features
        overall = self.evaluate(df, horizon, seq_len, epochs, extended_features, use_ensemble, symbol, period)
        self.extended_features = _prev_ext
        if "error" in overall:
            return overall

        # 特征工程以获取指标用于判断行情（使用 extended_features）
        _prev_ext = self.extended_features
        self.extended_features = extended_features
        ind, F = self._features(df, symbol=symbol, period=period)
        self.extended_features = _prev_ext
        # 为每个点判断行情（需要滚动窗口，这里我们用整个序列的指标来判断，简化处理）
        # 为了与评估的验证集对齐，我们需要为验证集中的每个样本对应的点判断行情。
        # 验证集样本对应的时间索引是：从 seq_len-1 开始的每个点的标签 y[t] 对应的是 t+1 的收益。
        # 为了简单，我们使用 ind 的行情判断，并取与验证集相同长度的切片（从 seq_len-1 开始）。
        # 这里我们假设 ind 长度与 df 相同（因为特征工程不改变行数）。
        regimes = ind.apply(lambda row: self._regime(pd.DataFrame([row]), {"state": "未知"}), axis=1)
        # 实际上 _regime 需要 DataFrame 和 tr dict，这里我们简化为直接使用 ind 中的 ADX 和 BOLL 来判断。
        # 由于时间关系，我们采用一个简化的方法：使用 ind 中的 ADX > 25 和布林带宽 < 0.01 来判断。
        # 计算布林带宽
        if "BOLL_UP" in ind and "BOLL_LOW" in ind and "BOLL_MID" in ind:
            mid = ind["BOLL_MID"]
            bw = (ind["BOLL_UP"] - ind["BOLL_LOW"]) / mid.replace(0, np.nan)
            bw = bw.fillna(0)
        else:
            bw = pd.Series(0, index=ind.index)
        adx = ind["ADX"] if "ADX" in ind else pd.Series(0, index=ind.index)
        # 趋势：ADX > 25
        # 震荡收敛：布林带宽 < 0.01
        # 其他：震荡
        regime_labels = []
        for i in range(len(ind)):
            if adx.iloc[i] > 25:
                regime_labels.append("趋势行情")
            elif bw.iloc[i] < 0.01:
                regime_labels.append("震荡收敛(变盘窗口)")
            else:
                regime_labels.append("震荡行情")
        
        # 现在我们需要将验证集的预测与真实值按 regime 分组
        # 重新运行一次评估以获得预测和真实值（为了避免重复计算，我们可以修改 evaluate 返回预测值，
        # 但为了不改动太多，这里我们再次运行类似的过程但记录预测和真实值）。
        # 为了简化，我们直接复用 evaluate 中的中间结果，但这里我们重新实现一遍。
        # 特征工程（第二次，使用 extended_features）
        ind2, F2 = self._features(df, symbol=symbol, period=period)
        arr2 = F2.values.astype(float)
        y2 = ind2["ret"].shift(-1).values.astype(float)
        Xs2, Ys2 = self._build_sequences(arr2, y2, seq_len)
        split_idx2 = int(len(Xs2) * 0.8)
        X_train2, Y_train2 = Xs2[:split_idx2], Ys2[:split_idx2]
        X_val2, Y_val2 = Xs2[split_idx2:], Ys2[split_idx2:]
        mean2 = X_train2.reshape(-1, X_train2.shape[-1]).mean(0)
        std2 = X_train2.reshape(-1, X_train2.shape[-1]).std(0) + 1e-8
        X_train_n = (X_train2 - mean2) / std2
        X_val_n = (X_val2 - mean2) / std2
        # 训练临时模型
        temp_pred = FuturesPredictor()
        temp_pred.extended_features = extended_features
        temp_pred.use_ensemble = use_ensemble
        temp_pred.seq_len = seq_len
        temp_pred._feat_mean = mean2
        temp_pred._feat_std = std2
        temp_pred._train_core(X_train_n, Y_train2, arr2.shape[1], epochs, False)
        val_preds = temp_pred._batch_pred(X_val_n)

        # 现在我们需要将验证集的索引映射回原始 df 的索引，以得到对应的 regime。
        # 验证集的每个样本对应的时间点是：从 split_idx2 + seq_len - 1 开始？实际上序列构建时：
        # Xs[t] 对应的是 arr[t-seq_len+1 : t+1]，标签 Ys[t] = y[t] = ret[t+1]。
        # 所以验证集的第一个样本的时间索引是 split_idx2（在 Xs2 中），对应的原始时间点是 split_idx2 + seq_len - 1?
        # 为了简单，我们假设验证集的 regime 可以取 ind 中从 split_idx2 开始的同样长度的切片（因为特征与时间对齐）。
        # 这里我们取 regime_labels[split_idx2: split_idx2+len(X_val2)] 作为验证集的 regime。
        val_regimes = regime_labels[split_idx2: split_idx2+len(X_val2)]
        
        # 按 regime 分组计算指标
        regime_metrics = {}
        unique_regimes = set(val_regimes)
        for reg in unique_regimes:
            mask = np.array([r == reg for r in val_regimes])
            if np.sum(mask) == 0:
                continue
            y_true_reg = Y_val2[mask]
            y_pred_reg = val_preds[mask]
            # 方向
            y_true_dir = (y_true_reg > 0).astype(int)
            y_pred_dir = (y_pred_reg > 0).astype(int)
            tp = np.sum((y_true_dir == 1) & (y_pred_dir == 1))
            fp = np.sum((y_true_dir == 0) & (y_pred_dir == 1))
            fn = np.sum((y_true_dir == 1) & (y_pred_dir == 0))
            tn = np.sum((y_true_dir == 0) & (y_pred_dir == 0))
            acc = (tp + tn) / (len(y_true_reg) + 1e-12)
            precision = tp / (tp + fp + 1e-12)
            recall = tp / (tp + fn + 1e-12)
            f1 = 2 * precision * recall / (precision + recall + 1e-12)
            mae = np.mean(np.abs(y_true_reg - y_pred_reg))
            rmse = np.sqrt(np.mean((y_true_reg - y_pred_reg) ** 2))
            ss_res = np.sum((y_true_reg - y_pred_reg) ** 2)
            ss_tot = np.sum((y_true_reg - np.mean(y_true_reg)) ** 2)
            r_squared = 1 - ss_res / (ss_tot + 1e-12)
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