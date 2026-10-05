"""TS-Transformer（可选 torch）：多头自注意力 + 位置编码 + 时间戳嵌入。

M5.4 TS-Transformer（可选 torch）：多头自注意力 + 位置编码 + 时间戳嵌入。
"""
from __future__ import annotations

import logging

import numpy as np
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except Exception:  # pragma: no cover
    TORCH_AVAILABLE = False


class PositionalEncoding(nn.Module if TORCH_AVAILABLE else object):
    """位置编码。"""
    def __init__(self, d_model: int, max_len: int = 5000):
        if TORCH_AVAILABLE:
            super().__init__()
            pe = torch.zeros(max_len, d_model)
            position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
            pe[:, 0::2] = torch.sin(position * div_term)
            pe[:, 1::2] = torch.cos(position * div_term)
            pe = pe.unsqueeze(0)  # (1, max_len, d_model)
            self.register_buffer('pe', pe)
        else:
            self.d_model = d_model
            self.max_len = max_len
            self.pe = np.zeros((max_len, d_model))
            position = np.arange(0, max_len, dtype=np.float32).reshape(-1, 1)
            # M3-06：`arange(0, d_model, 2)` 的长度在 **d_model 为奇数**时是
            # ceil(d/2)，而 `pe[:, 1::2]` 只有 floor(d/2) 列 → 广播直接崩
            # （如 feature_size=5 时 TSWrapper 构造即 ValueError）。
            # 按偶/奇位各自的列数分别取用 div_term。
            k_even = (d_model + 1) // 2
            k_odd = d_model // 2
            div_term = np.exp(np.arange(0, k_even, dtype=np.float32)
                              * (-np.log(10000.0) / d_model))
            self.pe[:, 0::2] = np.sin(position * div_term[:k_even])
            self.pe[:, 1::2] = np.cos(position * div_term[:k_odd])
            self.pe = self.pe[np.newaxis, ...]  # (1, max_len, d_model)

    def forward(self, x):
        if TORCH_AVAILABLE:
            # x: (batch, seq_len, d_model)
            x = x + self.pe[:, :x.size(1)]
            return x
        else:
            # x: (batch, seq_len, d_model) as numpy
            seq_len = x.shape[1]
            return x + self.pe[:, :seq_len, :]


class TSTransformer(nn.Module if TORCH_AVAILABLE else object):
    """简单的 Transformer 编码器，用于时间序列特征提取。"""
    def __init__(
        self,
        feature_size: int,
        num_layers: int = 1,
        num_heads: int = 4,
        dim_feedforward: int = 128,
        dropout: float = 0.1,
        seq_len: int = 20,
    ):
        if TORCH_AVAILABLE:
            super().__init__()
            self.feature_size = feature_size
            self.seq_len = seq_len
            self.pos_encoder = PositionalEncoding(d_model=feature_size, max_len=seq_len)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=feature_size,
                nhead=num_heads,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
                activation='relu',
                batch_first=True,
            )
            self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
            self.decoder = nn.Linear(feature_size, 1)
        else:
            self.feature_size = feature_size
            self.seq_len = seq_len
            self.pos_encoder = PositionalEncoding(d_model=feature_size, max_len=seq_len)
            # We'll implement a very simple attention as placeholder
            self.num_layers = num_layers
            self.num_heads = num_heads
            self.dim_feedforward = dim_feedforward
            self.dropout = dropout

    def forward(self, src):
        if TORCH_AVAILABLE:
            # src: (batch, seq_len, feature_size)
            src = self.pos_encoder(src)
            output = self.transformer_encoder(src)  # (batch, seq_len, feature_size)
            # We take the output of the last time step
            output = output[:, -1, :]  # (batch, feature_size)
            output = self.decoder(output)  # (batch, 1)
            return output.squeeze(-1)
        else:
            # Fallback: return zeros
            batch_size = src.shape[0] if hasattr(src, 'shape') else len(src)
            return np.zeros(batch_size)


class TSWrapper:
    """包装 TSTransformer 以符合统一接口。"""
    def __init__(
        self,
        feature_size: int,
        num_layers: int = 1,
        num_heads: int = 4,
        dim_feedforward: int = 128,
        dropout: float = 0.1,
        seq_len: int = 20,
        lr: float = 0.001,
        epochs: int = 10,
        device: Optional[str] = None,
    ):
        self.feature_size = feature_size
        self.seq_len = seq_len
        # M3-06：原实现漏掉 `self.epochs` / `self.lr`，而 fit() 里直接用 self.epochs
        # → 装了 torch 反而必抛 AttributeError（无 torch 时因提前 return 从未暴露）。
        self.epochs = int(epochs)
        self.lr = float(lr)
        if TORCH_AVAILABLE:
            self.device = device if device is not None else ('cuda' if torch.cuda.is_available() else 'cpu')
            self.model = TSTransformer(
                feature_size=feature_size,
                num_layers=num_layers,
                num_heads=num_heads,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
                seq_len=seq_len,
            ).to(self.device)
            self.optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
            self.criterion = torch.nn.MSELoss()
        else:
            self.model = TSTransformer(
                feature_size=feature_size,
                num_layers=num_layers,
                num_heads=num_heads,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
                seq_len=seq_len,
            )
            self.optimizer = None
            self.criterion = None
            self.available = False

    def fit(self, X: np.ndarray, y: np.ndarray):
        """训练模型。
        X shape: (n_samples, seq_len, feature_size)
        y shape: (n_samples,)

        M3-06：无 torch 时**明确标不可用**（`available=False` + 日志），而不是
        静默「什么都不做」—— 旧行为会让下游拿到一个恒返回 0 的模型，
        在多模型对比里伪装成一个「MAE 看似正常」的成员。
        """
        if not TORCH_AVAILABLE:
            self.available = False
            logger.warning(
                "TS-Transformer 不可用：未安装 torch。该模型为占位实现，"
                "predict() 恒返回 0，不应参与模型对比。")
            return self
        self.available = True
        self.model.train()
        for epoch in range(self.epochs):
            perm = np.random.permutation(len(X))
            epoch_loss = 0.0
            for i in range(0, len(X), 32):  # batch size 32
                indices = perm[i:i+32]
                batch_x = torch.from_numpy(X[indices]).float().to(self.device)
                batch_y = torch.from_numpy(y[indices]).float().to(self.device)
                self.optimizer.zero_grad()
                outputs = self.model(batch_x)
                loss = self.criterion(outputs, batch_y)
                loss.backward()
                self.optimizer.step()
                epoch_loss += loss.item()
            # 可选：打印损失
            # print(f'Epoch {epoch+1}/{self.epochs}, Loss: {epoch_loss/len(X):.4f}')

    def predict(self, X: np.ndarray) -> np.ndarray:
        """预测。
        X shape: (n_samples, seq_len, feature_size)
        返回: (n_samples,) 的预测值。
        """
        if not TORCH_AVAILABLE:
            # 返回零数组
            return np.zeros(X.shape[0])
        self.model.eval()
        with torch.no_grad():
            batch_x = torch.from_numpy(X).float().to(self.device)
            outputs = self.model(batch_x)
            return outputs.cpu().numpy()


# 为了提供一个可用的接口，我们也可以创建一个简单的函数，但类已经足够。