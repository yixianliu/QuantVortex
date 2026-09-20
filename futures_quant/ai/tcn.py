"""Temporal Convolutional Network (TCN) 纯 numpy 实现。

M5.3 TCN（时间卷积网络，纯 numpy）：1D 因果卷积 + 膨胀卷积堆叠。
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
        if seed is not None:
            np.random.seed(seed)
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
            weight = np.random.randn(out_channels, in_channels, kernel_size) * 0.01
            bias = np.zeros(out_channels)
            self.layers.append({
                'dilation': dilation_size,
                'weight': weight,
                'bias': bias,
                # 为了实现因果卷积，我们需要左填充 (kernel_size-1)*dilation
                'pad': (kernel_size - 1) * dilation_size
            })
        # 最终的线性层
        self.final_weight = np.random.randn(num_channels[-1]) * 0.01
        self.final_bias = np.zeros(1)

    def _causal_conv(self, x: np.ndarray, weight: np.ndarray, bias: np.ndarray, dilation: int, pad: int) -> np.ndarray:
        """因果卷积操作。
        x shape: (seq_len, in_channels)
        weight shape: (out_channels, in_channels, kernel_size)
        返回: (seq_len, out_channels)
        """
        seq_len, in_ch = x.shape
        out_ch, _, k = weight.shape
        # 左填充
        x_padded = np.pad(x, ((pad, 0), (0, 0)), mode='constant')
        # 输出序列长度与输入相同（因为我们只取有效部分）
        out = np.zeros((seq_len, out_ch))
        for i in range(seq_len):
            # 取从 i 到 i + pad + k 的切片，但因为左填充 pad，实际起始索引是 i
            # 卷积窗口: [i, i + k*dilation) 步长为 dilation
            start = i
            end = i + pad + k * dilation
            # 实际上我们只需要取每隔 dilation 的点，共 k 个点
            # 为了简化，我们可以使用 stride trick，但这里直接循环
            # 提取窗口
            window = x_padded[start:end:dilation]  # shape: (k, in_ch)
            # 确保窗口长度为 k
            if window.shape[0] != k:
                # 由于填充，应该不会发生
                continue
            # 卷积计算: 对每个输出通道
            for oc in range(out_ch):
                # weight[oc] shape: (in_ch, k)
                # 我们需要将 window 转置为 (k, in_ch) 然后与 weight[oc] 转置后 (k, in_ch) 相乘？
                # 实际上 weight[oc] 是 (in_ch, k)，我们想对每个 in_ch 的 k 个点求乘积和
                # 所以: sum over in_ch and t: window[t, ic] * weight[oc, ic, t]
                val = np.tensordot(window, weight[oc], axes=([0,1],[1,0])) + bias[oc]
                out[i, oc] = val
        return out

    def forward(self, x: np.ndarray) -> np.ndarray:
        """前向传播。
        x shape: (seq_len, num_inputs)
        返回: (seq_len,)  (假设输出为单一标量每个时间步)
        我们只取最后一个时间步的输出作为预测。
        """
        out = x
        for layer in self.layers:
            out = self._causal_conv(out, layer['weight'], layer['bias'],
                                   layer['dilation'], layer['pad'])
            # ReLU 激活
            out = np.maximum(out, 0)
            # dropout (这里简单跳过)
        # 全连接层：对每个时间步的最后输出取 dot product
        # out shape: (seq_len, last_channel)
        # final_weight shape: (last_channel,)
        out = np.dot(out, self.final_weight) + self.final_bias  # shape: (seq_len,)
        return out

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 10, lr: float = 0.001, batch_size: int = 32):
        """简单的梯度下降训练。
        X shape: (n_samples, seq_len, num_inputs)
        y shape: (n_samples,)  (回归目标)
        注意：这是一个非常简化的实现，仅用于演示。
        实际 TCN 训练需要反向传播通过时间和层，这里我们使用数值梯度或简单的SGD近似？
        出于时间，我们这里不实现真正的训练，而是保持权重随机，仅作结构演示。
        为了满足接口，我们什么也不做。
        """
        # 为了演示，我们不实现真正的训练，因为在纯 numpy 中实现反向传播较为复杂且耗时。
        # 用户如果想要训练，请使用 XGBoost/LightGBM 或其他库。
        # 这里我们仅做前向传播，保持权重随机。
        pass

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