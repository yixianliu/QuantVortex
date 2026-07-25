"""存储层演示：展示可插拔 StorageBackend 在 SQLite 下的完整用法。

运行：python examples/storage_demo.py
演示内容：
    1) 行情 K 线写入与区间回查；
    2) 引擎 live 模式跑策略，委托/成交/资金曲线自动落库；
    3) 策略参数 KV 存取；
    4) 资金曲线复盘读取。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from futures_quant.config.settings import Config
from futures_quant.core.engine import TradingEngine
from futures_quant.core.types import Bar
from futures_quant.data.base import Contract
from futures_quant.data.synthetic import generate_bars
from futures_quant.strategy.trend_following import TrendFollowing
from futures_quant.storage import get_storage
from futures_quant.utils.logger import get_logger


def df_to_bars(symbol: str, df) -> list:
    """把合成 DataFrame 转成 Bar 对象列表（数据层产出 DataFrame，引擎/存储需要 Bar）。"""
    return [
        Bar(symbol, r["datetime"], r["open"], r["high"], r["low"], r["close"],
            r["volume"], r["open_interest"])
        for _, r in df.iterrows()
    ]


def main() -> None:
    tmp = os.path.join(tempfile.gettempdir(), "storage_demo.db")
    if os.path.exists(tmp):
        os.remove(tmp)

    cfg = Config.load("config/settings.json")
    cfg.storage.backend = "sqlite"
    cfg.storage.sqlite_path = tmp

    db = get_storage(cfg)
    log = get_logger("storage_demo")

    # 1) 行情落地 + 回查
    df = generate_bars(symbol="rb.SHFE", mode="trend", n=1500, seed=11)
    bars = df_to_bars("rb.SHFE", df)
    db.insert_bars(bars)
    back = db.query_bars("rb.SHFE", limit=5)
    print(f"[bars]   写入 {len(bars)} 根，回查前 5 根收盘价: {[b.close for b in back]}")

    # 2) 引擎 live 模式跑策略，成交/委托/资金曲线自动落库
    eng = TradingEngine(cfg, logger=log, mode="paper", db=db)
    eng.add_contract(Contract(
        symbol="rb.SHFE", exchange="SHFE", multiplier=10, min_price_tick=1.0,
        margin_rate=0.10, commission_per_lot=3.0, trading_hours=[]))
    eng.register_strategy(TrendFollowing("rb.SHFE", {}))
    eng.start()
    for b in bars:
        eng.process_bar(b)

    trades = db.query_trades("rb.SHFE")
    orders = db.query_orders("rb.SHFE")
    eq = db.query_equity()
    print(f"[trades] 成交 {len(trades)} 笔 | [orders] 委托 {len(orders)} 笔 | "
          f"[equity] 资金曲线 {len(eq)} 点")

    # 3) 策略参数 KV 存取
    db.save_param("trend_rb", "fast=10,slow=30")
    print(f"[param]  读取: {db.load_param('trend_rb')}")

    # 4) 资金曲线复盘
    last = eq[-1]
    print(f"[equity] 末点权益: {float(last['equity']):.2f} | 回撤: {float(last['drawdown']):.4f}")

    db.close()
    print("STORAGE_DEMO_OK")


if __name__ == "__main__":
    main()
