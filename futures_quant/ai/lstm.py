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
    """批量化单隐层 LSTM（序列回归）。"""

    def __init__(self, input_size: int, hidden_size: int = 16, output_size: int = 1,
                 seed: int = 7) -> None:
        """初始化相关对象。
        
            参数:
                input_size: int
                hidden_size: int
                output_size: int
                seed: int"""
        self.in_sz = input_size
        self.hid = hidden_size
        self.out_sz = output_size
        rng = np.random.default_rng(seed)
        s = 0.08
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

    def _adam(self, grads, lr=0.01, b1=0.9, b2=0.999, eps=1e-8, clip=5.0):
        """处理adam。
        
            参数:
                grads
                lr
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
    def fit(self, sequences, targets, epochs=50, lr=0.005, batch=32, verbose=False):
        """拟合相关对象。
        
            参数:
                sequences
                targets
                epochs
                lr
                batch
                verbose"""
        X3 = np.array(sequences, dtype=float)      # (N,T,F)
        Y = np.array(targets, dtype=float)         # (N,) or (N,out)
        if Y.ndim == 1:
            Y = Y[:, None]
        N = X3.shape[0]
        losses = []
        for ep in range(epochs):
            idx = np.random.permutation(N)
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
    def predict_last(self, X):
        """X: (T,F) 或 (1,T,F) -> 末步标量的 float（单输出）或向量。"""
        if X.ndim == 2:
            X = X[None, :, :]
        Ys, _ = self._forward(X)
        out = Ys[0, -1]
        return float(out[0]) if self.out_sz == 1 else out
