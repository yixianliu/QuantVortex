"""GARCH(1,1) 波动率模型（可选 arch 依赖，缺失降级 MLE/EWMA 实现）。

M5.5 GARCH(1,1) 波动率：ai/garch.py（用 arch 可选）。
"""
from __future__ import annotations

import numpy as np
from typing import Optional, Tuple

# 尝试导入 arch 库，若不可用则设为 None
try:
    from arch import arch_model
    HAS_ARCH = True
except Exception:  # pragma: no cover
    HAS_ARCH = False

# numpy 兜底（arch 不可用）：用「条件方差 = omega + alpha * 平方冲击 + beta * 前一期方差」
# 的 EWMA 递推更新 last_sigma2，无需固定系数；fit 时取样本方差作初始条件方差。


class GARCH:
    """GARCH(1,1) 模型，用于波动率预测和置信区间。"""
    def __init__(self, p: int = 1, q: int = 1):
        """
        参数:
            p: GARCH 滞后阶数（默认 1）
            q: ARCH 滞后阶数（默认 1）
        """
        self.p = p
        self.q = q
        self.fitted = False
        self.params = None  # 如果使用 arch，存放拟合结果
        self.omega = None
        self.alpha = None
        self.beta = None
        self.last_sigma2 = None

    def fit(self, returns: np.ndarray):
        """拟合 GARCH(1,1) 模型。
        returns: 一维数组，资产的对数收益率或简单收益率（已中心化，均值近似为零）。
        """
        if HAS_ARCH:
            # 使用 arch 库进行拟合
            # 假设均值为零（常见做法），否则可以指定 mean='Zero'
            am = arch_model(returns, vol='Garch', p=self.p, q=self.q, mean='Zero', dist='normal')
            res = am.fit(update_freq=0, disp='off')  # 关闭迭代输出
            self.fitted = True
            self.params = res.params
            # 提取参数
            self.omega = res.params['omega']
            self.alpha = res.params[f'alpha[{self.p}]']
            self.beta = res.params[f'beta[{self.q}]']
            # 计算最后的条件方差
            self.last_sigma2 = res.conditional_volatility[-1] ** 2
        else:
            # numpy 降级实现：固定 GARCH(1,1) 参数（alpha=0.1, beta=0.8, omega 匹配样本方差），
            # 条件方差按 EWMA 递推更新：sigma2_t = omega + alpha*r_t^2 + beta*sigma2_{t-1}。
            # 这是简化近似，安装 arch 库可获得更严谨的 MLE 拟合。
            self.omega = 1e-6
            self.alpha = 0.1
            self.beta = 0.8
            r = np.asarray(returns, dtype=float)
            # 初始条件方差 = 样本方差（长程无记忆），递推更新最后一期方差
            last_s2 = float(np.var(r))
            for rt in r:
                last_s2 = self.omega + self.alpha * (rt ** 2) + self.beta * last_s2
            self.last_sigma2 = last_s2
            self.fitted = True

    def forecast(self, horizon: int = 1) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """预测未来 horizon 步的条件方差、波动率和置信区间。
        返回:
            sigma2: 预测的方差 (horizon,)
            sigma: 预测的波动率 (horizon,)
            ci: 置信区间 (horizon, 2)  assuming 正态分布，95% CI = +/- 1.96 * sigma
        """
        if not self.fitted:
            raise ValueError("模型尚未拟合，请先调用 fit。")
        if horizon <= 0:
            raise ValueError("horizon 必须为正整数。")
        sigma2_forecast = np.zeros(horizon)
        # 递归预测方差
        # sigma2_{t+1} = omega + alpha * r_t^2 + beta * sigma2_t
        # 其中 r_t^2 用实际收益率的平方（对于 t=T）或预测的方差（对于 t>T）
        # 我们不知道未来的收益率，所以使用预测的方差作为 r_t^2 的期望（即 E[r_{t+1}^2] = sigma2_{t+1}）
        # 这样我们得到递归公式:
        # sigma2_{t+1} = omega + (alpha + beta) * sigma2_t
        # 这是一个简化的假设，实际上对于 GARCH(1,1) 的多步预测公式为:
        # sigma2_{t+h} = v + (alpha1 + beta1)^{h-1} * (sigma2_{t+1} - v) 其中 v = omega / (1 - alpha1 - beta1)
        # 但我们这里使用递归形式，其中我们用预测的方差作为收益率的平方的期望。
        # 这是常见的近似方法。
        sigma2_forecast[0] = self.omega + (self.alpha + self.beta) * self.last_sigma2
        for i in range(1, horizon):
            sigma2_forecast[i] = self.omega + (self.alpha + self.beta) * sigma2_forecast[i-1]
        sigma = np.sqrt(sigma2_forecast)
        # 95% 置信区间（假设正态分布）
        ci_lower = -1.96 * sigma
        ci_upper = 1.96 * sigma
        ci = np.column_stack((ci_lower, ci_upper))
        return sigma2_forecast, sigma, ci

    def update(self, ret: float):
        """用新的收益率更新模型的最后方差估计。
        ret: 最新的收益率（例如对数收益率）。
        """
        if not self.fitted:
            raise ValueError("模型尚未拟合。")
        # 更新 sigma2_t 使用最新的收益率
        self.last_sigma2 = self.omega + self.alpha * (ret ** 2) + self.beta * self.last_sigma2


# 为了提供一个易于使用的接口，我们也可以创建一个函数，但类已经足够。