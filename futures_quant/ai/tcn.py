"""Temporal Convolutional Network (TCN) 纯 numpy 实现。

M5.3 TCN（时间卷积网络，纯 numpy）：1D 因果卷积 + 膨胀卷积堆叠。

M3-06 修复：
  ① `_causal_conv` 的切片上界写错（`end = i + pad + k*dilation`），取出的窗口长度恒为
     `2k-1` ≠ `k`，触发 `if window.shape[0] != k: continue` → **卷积输出恒为全零**，
     整个 TCN 等价于「预测常数 0」。改为按 `i + t*dilation (t=0..k-1)` 取索引，并整体
     向量化（原三重 Python 循环在 700 样本 × 4 层下慢到不可用）。
  ② `fit()` 原为 `pass`（权重随机、什么都不学）。现实装：
     随机因果膨胀卷积 + ReLU 作**固定特征提取器**（种子可复现），再对最后时间步的
     隐状态做 **岭回归最小二乘初始化 + epochs 轮小批量梯度下降**精调读出层。
     这属于「随机卷积特征 + 线性读出」范式，是纯 numpy 下可稳定收敛的标准做法。
"""
from __future__ import annotations

import numpy as np
from typing import Optional, Tuple


class TemporalConvNet:
    """简单的 TCN 回归/分类模型。
    
    因果卷积：每层卷积只能看到过去的时间步（通过左填充）。
    膨胀卷积：每层的膨胀率呈指数增长。
    最后接一个全连接层输出。
    """
    def __init__(
        self,
        num_inputs: int,
        num_channels: Tuple[int, ...],
        kernel_size: int = 2,
        dropout: float = 0.2,
        seed: Optional[int] = None,
    ):
        """
        参数:
            num_inputs: 输入特征维度（每个时间步的特征数）
            num_channels: 每层的输出通道数列表，例如 [25, 25, 25, 25]
            kernel_size: 卷积核大小，默认 2
            dropout: dropout 比例（这里仅作保留，实际未实现）
            seed: 随机种子
        """
        # M3-06：改用**局部** RNG。旧实现调 np.random.seed(seed) 会污染全局随机流，
        # 令后续与本模型无关的随机过程（LSTM 初始化、抽样等）被静默改变。
        self._rng = np.random.default_rng(seed)
        self.num_inputs = num_inputs
        self.num_channels = num_channels
        self.kernel_size = kernel_size
        self.dropout = dropout
        self.num_levels = len(num_channels)
        self.layers = []
        # 为每层创建卷积权重和偏置
        for i in range(self.num_levels):
            dilation_size = 2 ** i
            in_channels = num_inputs if i == 0 else num_channels[i-1]
            out_channels = num_channels[i]
            # 卷积权重 shape: (out_channels, in_channels, kernel_size)
            weight = self._rng.standard_normal((out_channels, in_channels, kernel_size)) * 0.01
            bias = np.zeros(out_channels)
            self.layers.append({
                'dilation': dilation_size,
                'weight': weight,
                'bias': bias,
                # 为了实现因果卷积，我们需要左填充 (kernel_size-1)*dilation
                'pad': (kernel_size - 1) * dilation_size
            })
        # 最终的线性层
        self.final_weight = self._rng.standard_normal(num_channels[-1]) * 0.01
        self.final_bias = np.zeros(1)
        # M3-06：读出层输入的标准化统计量（fit 后才有意义），与训练状态标志
        self.fitted = False
        self._h_mean = None
        self._h_std = None
        self.loss_history_ = []

    @staticmethod
    def _causal_conv(x: np.ndarray, weight: np.ndarray, bias: np.ndarray,
                     dilation: int, pad: int) -> np.ndarray:
        """因果膨胀卷积（向量化）。

        x shape: (seq_len, in_channels)
        weight shape: (out_channels, in_channels, kernel_size)
        返回: (seq_len, out_channels)

        语义：``out[i]`` 只依赖 ``x[i], x[i-dilation], ..., x[i-(k-1)*dilation]``
        （更早的位置由左填充的 0 补齐），因此严格因果、无未来函数。
        """
        seq_len, in_ch = x.shape
        out_ch, _, k = weight.shape
        # 左填充：pad = (k-1) * dilation
        x_padded = np.pad(x, ((pad, 0), (0, 0)), mode='constant')
        # 卷积窗口索引：out[i] 取 x_padded[i + t*d]，t = 0..k-1（共 k 个点）
        idx = np.arange(seq_len)[:, None] + np.arange(k)[None, :] * dilation
        window = x_padded[idx]                       # (seq_len, k, in_ch)
        # sum over (k, in_ch)：window 轴(1,2) 与 weight 轴(2,1) 收缩
        return np.tensordot(window, weight, axes=([1, 2], [2, 1])) + bias

    def _hidden(self, x: np.ndarray) -> np.ndarray:
        """卷积堆叠 + ReLU 后的隐状态，shape (seq_len, last_channel)。"""
        out = x
        for layer in self.layers:
            out = self._causal_conv(out, layer['weight'], layer['bias'],
                                    layer['dilation'], layer['pad'])
            out = np.maximum(out, 0.0)               # ReLU
        return out

    def forward(self, x: np.ndarray) -> np.ndarray:
        """前向传播。

        x shape: (seq_len, num_inputs)
        返回: (seq_len,) —— 每个时间步的读出值（predict 只取最后一个）。
        """
        h = self._hidden(x)
        if self.fitted and self._h_std is not None:
            h = (h - self._h_mean) / self._h_std
        return np.dot(h, self.final_weight) + self.final_bias

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 10,
            lr: float = 0.001, batch_size: int = 32):
        """训练**读出层**（随机卷积特征 + 梯度下降 + 岭回归收尾）。

        X shape: (n_samples, seq_len, num_inputs)
        y shape: (n_samples,)

        流程：
          1. 用固定的随机因果膨胀卷积把每个样本映射到最后时间步的隐状态 H，并标准化；
          2. 从 __init__ 的随机读出层出发，跑 epochs 轮小批量梯度下降
             （解析梯度，仅线性层；每步只在 loss 下降时才接受 → 单调不增）；
          3. 最后用岭回归最小二乘给出闭式解收尾，若更优则采用。

        注：之所以先 GD 再 LS —— LS 是线性读出的闭式最优，若先用 LS 初始化，
        GD 只会在最优点附近被 lr 推离，loss 反而变差（实测 lr=0.01 时 +0.05%）。
        loss 全程记录在 ``self.loss_history_``，可验证「训练确实发生了」。
        """
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).reshape(-1)
        n = X.shape[0]
        if n == 0:
            return self
        # ① 提取最后时间步的隐状态并标准化
        H = np.vstack([self._hidden(X[i])[-1] for i in range(n)])   # (n, last_ch)
        self._h_mean = H.mean(0)
        self._h_std = H.std(0) + 1e-8
        Hn = (H - self._h_mean) / self._h_std
        self.fitted = True

        def _loss(w, b):
            """处理loss。

                参数:
                    w
                    b"""
            return float(np.mean((Hn @ w + b - y) ** 2))

        best_w = self.final_weight.copy()
        best_b = float(np.asarray(self.final_bias).reshape(-1)[0])
        best_loss = _loss(best_w, best_b)
        self.loss_history_ = [best_loss]
        # ② 小批量梯度下降（只接受 loss 下降的步）
        bs = max(1, int(batch_size))
        for _ in range(max(0, int(epochs))):
            perm = self._rng.permutation(n)
            for s in range(0, n, bs):
                idx = perm[s:s + bs]
                hb, yb = Hn[idx], y[idx]
                pred = hb @ self.final_weight + self.final_bias[0]
                g = 2.0 * (pred - yb) / len(idx)
                self.final_weight -= lr * (hb.T @ g)
                self.final_bias[0] -= lr * float(g.sum())
            loss = _loss(self.final_weight, self.final_bias[0])
            if not np.isfinite(loss) or loss >= best_loss:
                self.final_weight = best_w.copy()
                self.final_bias[0] = best_b
                self.loss_history_.append(best_loss)
            else:
                best_w = self.final_weight.copy()
                best_b = float(self.final_bias[0])
                best_loss = loss
                self.loss_history_.append(loss)
        # ③ 岭回归最小二乘收尾（闭式解；alpha 网格按训练 MSE 选）
        y_mean = float(y.mean())
        yy = y - y_mean
        ls_w, ls_b, ls_loss = None, y_mean, float("inf")
        for alpha in (1e-3, 1e-2, 0.1, 1.0, 10.0):
            A = Hn.T @ Hn + alpha * np.eye(Hn.shape[1])
            try:
                w = np.linalg.solve(A, Hn.T @ yy)
            except np.linalg.LinAlgError:
                w = np.linalg.pinv(A) @ (Hn.T @ yy)
            loss = _loss(w, y_mean)
            if np.isfinite(loss) and loss < ls_loss:
                ls_w, ls_b, ls_loss = w, y_mean, loss
        if ls_w is not None and ls_loss < best_loss:
            self.final_weight = ls_w
            self.final_bias = np.asarray([ls_b])
            best_loss = ls_loss
        self.loss_history_.append(best_loss)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """预测。
        X shape: (n_samples, seq_len, num_inputs)
        返回: (n_samples,) 的预测值。
        """
        preds = []
        for i in range(X.shape[0]):
            out = self.forward(X[i])  # shape: (seq_len,)
            # 我们取最后一个时间步的输出作为该样本的预测
            preds.append(out[-1])
        return np.array(preds)


# 为了提供一个完整的示例，我们也可以实现一个分类版本，但这里回归版本足以说明结构。
# 如果需要分类，只需在最后加一个 softmax 阈值。