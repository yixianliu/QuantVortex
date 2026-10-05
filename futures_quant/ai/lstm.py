"""轻量 LSTM（纯 numpy 批量化实现，零外部依赖）。

相比逐样本循环版本，本实现在训练时对 mini-batch 做向量化前向 / BPTT，
时间复杂度从 O(N·T) 的 Python 循环降为少量向量化矩阵运算，速度提升数十倍，
且配合梯度裁剪数值稳定。

用途：期货价格序列的短期趋势预测（sequence-to-one 回归，预测下一根对数收益）。
预测器(predictor.py)在其输出异常（NaN/不收敛）时自动回退到岭回归。
"""
from __future__ import annotations

import numpy as np


def _sigmoid(x):
    """处理sigmoid。

    参数:
        x"""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


class LSTM:
    """批量化单隐层 LSTM（序列回归）。

    相比逐样本循环版本，本实现在训练时对 mini-batch 做向量化前向 / BPTT，
    时间复杂度从 O(N·T) 的 Python 循环降为少量向量化矩阵运算，速度提升数十倍，
    且配合梯度裁剪数值稳定。

    用途：期货价格序列的短期趋势预测（sequence-to-one 回归，预测下一根对数收益）。
    预测器(predictor.py)在其输出异常（NaN/不收敛）时自动回退到岭回归。
    """

    def __init__(self, input_size: int, hidden_size: int = 64, output_size: int = 1,
                 seed: int = 7) -> None:
        """初始化相关对象。

            参数:
                input_size: int
                hidden_size: int - 增加到64以提升表达能力
                output_size: int
                seed: int"""
        self.in_sz = input_size
        self.hid = hidden_size
        self.out_sz = output_size
        rng = np.random.default_rng(seed)
        # M3-11 附带修复：把 rng 挂到实例上，供 fit() 的批次打乱复用。
        # 原实现 fit() 用 `np.random.permutation`（**全局** RNG），导致同一 seed
        # 下多次训练结果各不相同 —— 回归测试无法复现（M3-11 验收要求指标差
        # <1e-9），也让「改了配置到底是变好还是变坏」无法判断。
        self._rng = rng
        s = 0.06  # 稍微减小权重标准差以稳定训练
        c = hidden_size + input_size
        self.Wf = rng.normal(0, s, (hidden_size, c))
        self.Wi = rng.normal(0, s, (hidden_size, c))
        self.Wc = rng.normal(0, s, (hidden_size, c))
        self.Wo = rng.normal(0, s, (hidden_size, c))
        self.bf = np.zeros(hidden_size)
        self.bi = np.zeros(hidden_size)
        self.bc = np.zeros(hidden_size)
        self.bo = np.zeros(hidden_size)
        self.Why = rng.normal(0, s, (output_size, hidden_size))
        self.by = np.zeros(output_size)
        self._m = {k: np.zeros_like(getattr(self, k)) for k in self._P}
        self._v = {k: np.zeros_like(getattr(self, k)) for k in self._P}

    _P = ("Wf", "Wi", "Wc", "Wo", "bf", "bi", "bc", "bo", "Why", "by")

    # ----------------------------- 批量化前向 -----------------------------
    def _forward(self, X):
        """X: (B, T, F)。返回 (Ys (B,T,out), cache)。"""
        B, T, _ = X.shape
        H = self.hid
        h = np.zeros((B, H))
        c = np.zeros((B, H))
        cache = dict(h=[], c=[], f=[], i=[], g=[], o=[], z=[], y=[])
        for t in range(T):
            xt = X[:, t, :]                       # (B,F)
            z = np.concatenate([h, xt], axis=1)  # (B, H+F)
            f = _sigmoid(z @ self.Wf.T + self.bf)
            i = _sigmoid(z @ self.Wi.T + self.bi)
            g = np.tanh(z @ self.Wc.T + self.bc)
            o = _sigmoid(z @ self.Wo.T + self.bo)
            c = f * c + i * g
            h = o * np.tanh(c)
            y = h @ self.Why.T + self.by         # (B,out)
            cache["h"].append(h.copy()); cache["c"].append(c.copy())
            cache["f"].append(f); cache["i"].append(i)
            cache["g"].append(g); cache["o"].append(o)
            cache["z"].append(z); cache["y"].append(y.copy())
        Ys = np.stack(cache["y"], axis=1)  # (B,T,out)
        return Ys, cache

    # ----------------------------- 批量化 BPTT -----------------------------
    def _backward(self, X, y_true, cache):
        """处理backward。

            参数:
                X
                y_true
                cache"""
        B, T, _ = X.shape
        H = self.hid
        grads = {k: np.zeros_like(getattr(self, k)) for k in self._P}
        y_pred = cache["y"][-1]                  # (B,out)
        dh_next = (y_pred - y_true) @ self.Why   # (B,H)
        dc_next = np.zeros((B, H))
        for t in reversed(range(T)):
            h = cache["h"][t]; c = cache["c"][t]
            f = cache["f"][t]; i = cache["i"][t]
            g = cache["g"][t]; o = cache["o"][t]; z = cache["z"][t]
            tanhc = np.tanh(c)
            dc = dc_next + (dh_next * o) * (1 - tanhc ** 2)
            dg = dc * i
            di = dc * g
            df = dc * c
            do = dh_next * tanhc
            dg_act = dg * (1 - g ** 2)
            di_act = di * i * (1 - i)
            df_act = df * f * (1 - f)
            do_act = do * o * (1 - o)
            # 累加批内梯度
            grads["Wc"] += dg_act.T @ z
            grads["Wi"] += di_act.T @ z
            grads["Wf"] += df_act.T @ z
            grads["Wo"] += do_act.T @ z
            grads["bc"] += dg_act.sum(0)
            grads["bi"] += di_act.sum(0)
            grads["bf"] += df_act.sum(0)
            grads["bo"] += do_act.sum(0)
            dz = df_act @ self.Wf + di_act @ self.Wi + dg_act @ self.Wc + do_act @ self.Wo
            dh_next = dz[:, :H]
            dc_next = dc * f
        # 输出层
        grads["Why"] += (y_pred - y_true).T @ cache["h"][-1]
        grads["by"] += (y_pred - y_true).sum(0)
        return grads

    def _adam(self, grads, lr=0.001, b1=0.9, b2=0.999, eps=1e-8, clip=5.0):
        """处理adam。

            参数:
                grads
                lr - 降低至0.001以提升稳定性
                b1
                b2
                eps
                clip"""
        for name in self._P:
            g = np.clip(grads[name], -clip, clip)
            self._m[name] = b1 * self._m[name] + (1 - b1) * g
            self._v[name] = b2 * self._v[name] + (1 - b2) * (g ** 2)
            mhat = self._m[name] / (1 - b1)
            vhat = self._v[name] / (1 - b2)
            p = getattr(self, name)
            setattr(self, name, p - lr * mhat / (np.sqrt(vhat) + eps))

    # ----------------------------- 训练 -----------------------------
    def fit(self, sequences, targets, epochs=30, lr=0.001, batch=32, verbose=False):
        """拟合相关对象。

            参数:
                sequences
                targets
                epochs - 减少至30轮以防止过拟合
                lr - 学习率0.001，提升稳定性
                batch
                verbose"""
        X3 = np.array(sequences, dtype=float)      # (N,T,F)
        Y = np.array(targets, dtype=float)         # (N,) or (N,out)
        if Y.ndim == 1:
            Y = Y[:, None]
        N = X3.shape[0]
        losses = []
        for ep in range(epochs):
            # 用实例 rng（而非全局 np.random）打乱批次 → 同 seed 可复现
            idx = self._rng.permutation(N)
            ep_loss = 0.0; cnt = 0
            for b in range(0, N, batch):
                bi = idx[b:b + batch]
                Xb = X3[bi]; Yb = Y[bi]
                if not np.isfinite(Xb).all() or not np.isfinite(Yb).all():
                    continue
                _, cache = self._forward(Xb)
                g = self._backward(Xb, Yb, cache)
                self._adam(g, lr=lr)
                yp = cache["y"][-1]
                ep_loss += float(((yp - Yb) ** 2).sum())
                cnt += len(bi)
            losses.append(ep_loss / max(cnt, 1))
            if verbose and (ep + 1) % 10 == 0:
                print(f"  epoch {ep+1:3d} mse={losses[-1]:.6f}")
        return losses

    # ----------------------------- 推理 -----------------------------
    def predict_batch(self, X: np.ndarray) -> np.ndarray:
        """批量推理：X 为 (B, T, F)，返回 (B, out) 的 ndarray。

        采用向量化前向传播，避免 Python 循环逐样本调用，速度提升 5-20x。
        """
        if X.ndim == 2:
            X = X[None, :, :]
        Ys, _ = self._forward(X)
        # Ys: (B, T, out) -> 取最后时刻
        out = Ys[:, -1]
        if self.out_sz == 1:
            return out.reshape(-1)
        return out

    def predict_last(self, X):
        """X: (T,F) 或 (1,T,F) -> 末步标量的 float（单输出）或向量。"""
        out = self.predict_batch(X)
        return float(out[0]) if self.out_sz == 1 else out


# ----------------------------------------------------------------------
# 双向 LSTM 增强版本（PyTorch）：在 numpy 失败 / 需要更高表达力时启用
# ----------------------------------------------------------------------
_torch_ref = [None]  # type: list[Any | None]


def _ensure_torch():
    """延迟导入 torch；若不存在返回 None。

    使用闭包持有引用，避免模块顶层直接引用未加载的 nn，从而防止
    `AttributeError: 'NoneType' object has no attribute 'Module'` 崩溃。
    """
    if _torch_ref[0] is not None:
        return _torch_ref[0]
    try:
        import torch as _torch_mod
        import torch.nn as _nn_mod
        _torch_ref[0] = (_torch_mod, _nn_mod)
        return _torch_ref[0]
    except Exception:  # noqa: BLE001
        return None


class BidirectionalLSTM:
    """动态代理类：在 torch 存在时作为 nn.Module 子类，否则作为占位。

    通过 ``hasattr`` 与延迟属性绑定，避免模块顶层引用尚未导入的 ``nn``。
    """

    def __init__(self, input_size: int, hidden_size: int = 64, output_size: int = 1,
                 num_layers: int = 2, dropout: float = 0.2, seed: int = 7) -> None:
        """初始化相关对象。

            参数:
                input_size: 输入特征维度
                hidden_size: LSTM 隐藏单元数
                output_size: 输出维度（默认 1，标量预测）
                num_layers: LSTM 层数
                dropout: 丢弃率
                seed: 随机种子"""
        ref = _ensure_torch()
        if ref is None:
            raise RuntimeError("torch 未安装，无法使用 BidirectionalLSTM；请 pip install torch")
        torch, nn = ref
        # 动态设置基类，让实例拥有 nn.Module 的完整特性（state_dict / to / train / eval / parameters）
        object.__setattr__(self, '__class__', type('BidirectionalLSTM', (nn.Module,), {}))
        nn.Module.__init__(self)
        torch.manual_seed(seed)
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers=num_layers,
                            batch_first=True, bidirectional=True,
                            dropout=dropout if num_layers > 1 else 0.0)
        attn_dim = hidden_size * 2  # 双向拼接
        self.attention = nn.Sequential(
            nn.Linear(attn_dim, attn_dim // 2),
            nn.Tanh(),
            nn.Linear(attn_dim // 2, 1),
        )
        self.head = nn.Sequential(
            nn.Linear(attn_dim, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, output_size),
        )
        # weight decay（L2 正则）
        self.weight_decay = 1e-4
        self._torch = torch
        self._nn = nn

    def forward(self, x):
        """前向传播。

        参数:
            x: Tensor (B, T, F)

        返回:
            预测输出 (B, output_size)"""
        torch = self._torch
        lstm_out, _ = self.lstm(x)                 # (B, T, 2*hid)
        # 时序注意力
        attn_weights = self.attention(lstm_out)    # (B, T, 1)
        attn_weights = torch.softmax(attn_weights, dim=1)
        context = (lstm_out * attn_weights).sum(dim=1)  # (B, 2*hid)
        return self.head(context)                  # (B, out)

    def parameter_richness(self) -> int:
        """返回可训练参数总数，便于日志打印。"""
        return sum(p.numel() for p in self.parameters())


class TorchLSTM:
    """基于 PyTorch 的双向 LSTM 训练/推理包装，与 numpy LSTM 接口兼容。

    在 `predictor.py` 中，LSTM 训练失败会自动降级到本类（需 torch）或岭回归。
    """

    def __init__(self, input_size: int, hidden_size: int = 64, output_size: int = 1,
                 num_layers: int = 2, dropout: float = 0.2, lr: float = 1e-3,
                 weight_decay: float = 1e-4, seed: int = 7) -> None:
        """初始化相关对象。

            参数:
                input_size: int
                hidden_size: int
                output_size: int
                num_layers: int
                dropout: float
                lr: float
                weight_decay: float
                seed: int"""
        ref = _ensure_torch()
        if ref is None:
            raise RuntimeError("torch 未安装，无法使用 BidirectionalLSTM")
        torch, nn = ref
        self.model = BidirectionalLSTM(input_size=input_size,
                                       hidden_size=hidden_size,
                                       output_size=output_size,
                                       num_layers=num_layers,
                                       dropout=dropout,
                                       seed=seed)
        self.lr = lr
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=lr,
                                          weight_decay=weight_decay)
        self.criterion = nn.MSELoss()
        self.device = torch.device("cpu")  # 桌面端默认 CPU；可切换 CUDA
        self.model.to(self.device)
        self._trainable = True

    @property
    def trained(self) -> bool:
        """是否已训练。"""
        return self._trainable

    def fit(self, sequences, targets, epochs: int = 30, batch: int = 64,
            val_split: float = 0.2, patience: int = 5, verbose: bool = False):
        """训练主循环（带早停）。

            参数:
                sequences: list[np.ndarray] 或 np.ndarray (N, T, F)
                targets: np.ndarray (N,) or (N, out)
                epochs: int
                batch: int
                val_split: float，末尾一段作为验证集
                patience: int，早停容忍轮数
                verbose: bool"""
        torch = self.model._torch
        X = torch.tensor(np.array(sequences, dtype=np.float32), device=self.device)
        Y = torch.tensor(np.array(targets, dtype=np.float32), device=self.device)
        N = X.size(0)
        val_n = int(N * val_split)
        train_X, val_X = X[:N - val_n], X[N - val_n:]
        train_Y, val_Y = Y[:N - val_n], Y[N - val_n:]
        best_val_loss = float("inf")
        no_improve = 0
        losses = []
        for ep in range(1, epochs + 1):
            self.model.train()
            ep_loss = 0.0
            order = torch.randperm(N - val_n, device=self.device)
            for start in range(0, len(order), batch):
                idx = order[start:start + batch]
                xb = train_X[idx]; yb = train_Y[idx]
                self.optimizer.zero_grad()
                pred = self.model(xb)
                loss = self.criterion(pred, yb)
                # L2 正则惩罚（显式加到 loss）
                l2_reg = torch.tensor(0., device=self.device)
                for p in self.model.parameters():
                    l2_reg = l2_reg + p.norm(2)
                loss = loss + self.lr * l2_reg
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                self.optimizer.step()
                ep_loss += loss.item() * len(idx)
            ep_loss /= max(N - val_n, 1)
            losses.append(ep_loss)
            # 验证
            with torch.no_grad():
                val_pred = self.model(val_X)
                val_loss = self.criterion(val_pred, val_Y).item()
            if verbose and ep % 5 == 0:
                print(f"  epoch {ep:3d} train_mse={ep_loss:.6f} val_mse={val_loss:.6f}")
            if val_loss < best_val_loss - 1e-6:
                best_val_loss = val_loss
                no_improve = 0
                self._best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
            else:
                no_improve += 1
            if no_improve >= patience:
                if verbose:
                    print(f"  early stop at epoch {ep}, best val_mse={best_val_loss:.6f}")
                break
        # 恢复最佳权重
        if hasattr(self, "_best_state"):
            self.model.load_state_dict(self._best_state)
        self._trainable = True
        return losses

    def predict_batch(self, X: np.ndarray) -> np.ndarray:
        """批量预测。

            参数:
                X: np.ndarray (B, T, F)

            返回:
                np.ndarray (B, out)"""
        torch = self.model._torch
        if X.ndim == 2:
            X = X[None, :, :]
        self.model.eval()
        with torch.no_grad():
            t = torch.tensor(X, dtype=torch.float32, device=self.device)
            out = self.model(t).cpu().numpy()
        return out

    def predict_last(self, X) -> float:
        """单条预测，返回标量。

            参数:
                X: np.ndarray (T, F)

            返回:
                float"""
        out = self.predict_batch(X)
        return float(out[0, 0])

    def evaluate(self, X: np.ndarray, Y: np.ndarray) -> dict:
        """评估性能，返回 dict。

            参数:
                X: np.ndarray (N, T, F)
                Y: np.ndarray (N,) 或 (N, 1)

            返回:
                dict: {mae, rmse, mape}"""
        preds = self.predict_batch(X)
        Y = np.asarray(Y, float).reshape(-1, 1)
        mae = float(np.mean(np.abs(Y - preds)))
        rmse = float(np.sqrt(np.mean((Y - preds) ** 2)))
        denom = np.where(np.abs(Y) > 1e-8, np.abs(Y), 1e-8)
        mape = float(np.mean(np.abs((Y - preds) / denom)))
        return {"mae": mae, "rmse": rmse, "mape": mape}