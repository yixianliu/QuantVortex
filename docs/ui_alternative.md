# 替代 UI：Streamlit 版本

本框架默认提供 **PyQt6 桌面端**（`futures_quant/ui/main_window.py`），适合
本地精美桌面应用与 exe 打包。若你更偏好「网页式、零前端构建」的轻量界面，
可用 **Streamlit** 快速搭建一个等价面板。

## 一、安装

```bash
pip install streamlit
```

## 二、最小可运行示例（`ui_streamlit.py`）

```python
import streamlit as st
import pandas as pd
from futures_quant.backtest.backtester import Backtester
from futures_quant.config.settings import Config
from futures_quant.data.base import Contract
from futures_quant.data.synthetic import SyntheticFeed, generate_bars
from futures_quant.strategy.trend_following import TrendFollowing

st.title("期货策略回测（Streamlit）")
name = st.selectbox("策略", ["趋势跟踪"])
n = st.slider("K线数量", 1000, 20000, 5000)

if st.button("运行"):
    cfg = Config.load("config/settings.json")
    feed = SyntheticFeed()
    feed._cache[("SIM.SHFE", "1m")] = generate_bars(
        symbol="SIM.SHFE", mode="trend", n=n, seed=7)
    bt = Backtester(cfg, feed)
    bt.add_contract(Contract(symbol="SIM.SHFE", exchange="SHFE", multiplier=10,
                             min_price_tick=1.0, margin_rate=0.10,
                             commission_per_lot=3.0, trading_hours=[]))
    bt.add_strategy(TrendFollowing("SIM.SHFE", {}))
    out = bt.run("SIM.SHFE", "2024-01-01", "2024-12-31", period="1m", warmup=60)
    files = bt.export(outdir="output", prefix=name)
    m = out["metrics"]
    st.metric("总收益", f"{m['total_return']:.2%}")
    st.metric("夏普", m["sharpe"])
    st.metric("最大回撤", f"{m['max_drawdown']:.2%}")
    eq = pd.read_csv(files["equity"])
    st.line_chart(eq.set_index("datetime")["equity"])
    st.write("报告：", files["html"])
```

运行：`streamlit run ui_streamlit.py`

## 三、PyQt6 vs Streamlit 取舍

| 维度 | PyQt6（默认） | Streamlit |
|------|---------------|-----------|
| 部署 | 可打包 exe，本地桌面 | 需 `streamlit run`，浏览器访问 |
| 实时性 | 原生事件循环，毫秒级刷新 | 基于脚本重跑，适合交互式探索 |
| 学习成本 | 需懂 Qt 布局 | 纯 Python，上手快 |
| 打包 | PyInstaller 一键 | 不适用（需服务器） |

> 无论哪种 UI，核心回测/策略/风控逻辑完全复用，无需重写。
