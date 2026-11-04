# -*- coding: utf-8 -*-
"""阶段 5：TqSdk / SimNow 数据源适配器单测（全部离线，不需真实账号）。

覆盖：
1. 正常取数（日线 / 分钟线）与 provenance（data_source=tqsdk、is_synthetic=False）；
2. 未安装 tqsdk → NotInstalledError；
3. 未配置账号 → MissingCredentialsError；
4. 连接/取数失败 → ConnectFailedError；
5. 区间无数据 → NoDataError；
6. 周期不支持 → UnsupportedPeriodError（且不触发任何连接）；
7. close() 幂等；
8. 合约代码规范化与注册表可见；
9. 管理器层 TqSdk 失败不得回退合成行情（绝不出现 is_synthetic=True）。
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from futures_quant.data.base import get_feed_factory, get_provenance, registered_feeds
from futures_quant.data.tqsdk_feed import (
    ConnectFailedError,
    InvalidSymbolError,
    MissingCredentialsError,
    NoDataError,
    NotInstalledError,
    TqSdkCredentials,
    TqSdkFeed,
    UnsupportedPeriodError,
    normalize_period,
    to_tq_symbol,
    tqsdk_diagnose,
)

_ENV_KEYS = ("TQ_USER", "TQ_PASSWORD", "TQSDK_USER", "TQSDK_PASSWORD",
             "QV_TQ_USER", "QV_TQ_PASSWORD")


@pytest.fixture(autouse=True)
def _clean_tq_env(monkeypatch):
    """清空环境中的 TqSdk 凭据，避免测试结果受本机环境影响。"""
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def _bj_ns(ts) -> int:
    """北京墙钟时间 → TqSdk 纳秒时间戳（其 epoch 以北京时间为基准）。"""
    return int((pd.Timestamp(ts) - pd.Timedelta(hours=8)).value)


def _bars(start="2024-01-02 09:00", n=5, step="5min", price0=3800.0) -> pd.DataFrame:
    """构造 TqSdk 风格的原始 K 线（datetime 为纳秒整数）。"""
    ts = pd.date_range(start, periods=n, freq=step)
    return pd.DataFrame({
        "datetime": [_bj_ns(t) for t in ts],
        "open": [price0 + i for i in range(n)],
        "high": [price0 + i + 5 for i in range(n)],
        "low": [price0 + i - 5 for i in range(n)],
        "close": [price0 + i + 1 for i in range(n)],
        "volume": [100 + i for i in range(n)],
        "open_interest": [10000 + i for i in range(n)],
        "symbol": ["SHFE.rb2405"] * n,
    })


class _FakeApi:
    """最小 TqApi 桩：实现 range / serial 两条取数路径 + 幂等 close。"""

    def __init__(self, df: pd.DataFrame | None = None, error: Exception | None = None):
        self.df = df
        self.error = error
        self.close_calls = 0
        self.range_calls: list[dict] = []
        self.serial_calls: list[dict] = []

    def get_kline_data_series(self, symbol, duration_seconds,
                              start_dt=None, end_dt=None):
        self.range_calls.append({"symbol": symbol, "duration": duration_seconds})
        if self.error:
            raise self.error
        return None if self.df is None else self.df.copy()

    def get_kline_serial(self, symbol, duration_seconds, data_length=200):
        self.serial_calls.append({"symbol": symbol, "duration": duration_seconds,
                                  "data_length": data_length})
        if self.error:
            raise self.error
        if self.df is None:
            return pd.DataFrame()
        return self.df.tail(int(data_length)).copy()

    def close(self):
        self.close_calls += 1


def test_normal_range_fetch_provenance():
    """正常取数：列结构、时间口径、provenance 字段全部正确。"""
    api = _FakeApi(_bars())
    feed = TqSdkFeed(api_factory=lambda: api)
    df = feed.get_history("rb.SHFE", "2024-01-01", "2024-01-31", period="5m")

    assert list(df.columns) == ["datetime", "open", "high", "low", "close",
                                "volume", "open_interest"]
    assert len(df) == 5
    assert df["datetime"].iloc[0] == pd.Timestamp("2024-01-02 09:00")
    assert df["datetime"].iloc[-1] == pd.Timestamp("2024-01-02 09:20")

    prov = get_provenance(df)
    assert prov["data_source"] == "tqsdk"
    assert prov["is_synthetic"] is False
    assert prov["is_stale"] is False
    assert prov["as_of"] == df["datetime"].iloc[-1]

    assert api.range_calls[0]["symbol"] == "KQ.m@SHFE.rb"
    assert api.range_calls[0]["duration"] == 300


def test_daily_fetch_and_settle_kept():
    """日线取数；若上游带 settle 列则保留，缺失的成交量/持仓量补 0。"""
    raw = _bars(step="1D", n=3)
    raw = raw.drop(columns=["volume", "open_interest"])
    raw["settle"] = [3801.0, 3802.0, 3803.0]
    feed = TqSdkFeed(api_factory=lambda: _FakeApi(raw))
    df = feed.get_history("rb2601", "2023-12-01", "2024-01-31", period="D")

    assert len(df) == 3
    assert "settle" in df.columns
    assert df["volume"].tolist() == [0.0, 0.0, 0.0]
    assert df["open_interest"].tolist() == [0.0, 0.0, 0.0]


def test_recent_uses_serial_and_limit():
    """get_recent 走 get_kline_serial，limit 生效且结果按时间升序。"""
    api = _FakeApi(_bars(n=10))
    feed = TqSdkFeed(api_factory=lambda: api)
    df = feed.get_recent("rb.SHFE", "5m", limit=3)

    assert len(df) == 3
    assert api.serial_calls[0]["data_length"] == 3
    assert df["datetime"].is_monotonic_increasing
    assert get_provenance(df)["is_synthetic"] is False


def test_missing_library(monkeypatch):
    """未安装 tqsdk：抛 NotInstalledError，绝不返回合成数据。"""
    monkeypatch.setitem(sys.modules, "tqsdk", None)
    feed = TqSdkFeed(user="u", password="p")
    with pytest.raises(NotInstalledError) as ei:
        feed.get_history("rb.SHFE", "2024-01-01", "2024-01-31", "5m")
    assert "pip install tqsdk" in ei.value.hint
    assert "tqsdk" in ei.value.user_message


def test_missing_credentials(monkeypatch, tmp_path):
    """tqsdk 已安装但无账号：抛 MissingCredentialsError（不应尝试 TqApi）。"""
    mod = types.ModuleType("tqsdk")
    mod.TqApi = lambda *a, **k: pytest.fail("凭据缺失时不应创建 TqApi")
    mod.TqAuth = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "tqsdk", mod)

    feed = TqSdkFeed(creds_path=str(tmp_path / "not_exists.json"))
    with pytest.raises(MissingCredentialsError) as ei:
        feed.get_history("rb.SHFE", "2024-01-01", "2024-01-31", "D")
    assert "TQ_USER" in ei.value.user_message
    assert "tqsdk_settings.json" in ei.value.user_message


def test_connect_failure():
    """连接/初始化失败 → ConnectFailedError，错误类型明确。"""
    def _boom():
        raise RuntimeError("network unreachable")

    feed = TqSdkFeed(api_factory=_boom)
    with pytest.raises(ConnectFailedError) as ei:
        feed.get_history("rb.SHFE", None, None, "D", limit=5)
    assert "network unreachable" in str(ei.value)
    assert ei.value.kind == "ConnectFailed"


def test_empty_data_raises_no_data():
    """上游返回空表 → NoDataError（不得生成任何合成 K 线）。"""
    feed = TqSdkFeed(api_factory=lambda: _FakeApi(pd.DataFrame()))
    with pytest.raises(NoDataError) as ei:
        feed.get_history("rb.SHFE", "2024-01-01", "2024-01-31", "15m")
    assert "SHFE.rb" in str(ei.value)


def test_unsupported_period_does_not_connect():
    """周期不支持时立即抛错，不初始化连接（懒加载契约）。"""
    called = {"n": 0}

    def _factory():
        called["n"] += 1
        return _FakeApi(_bars())

    feed = TqSdkFeed(api_factory=_factory)
    with pytest.raises(UnsupportedPeriodError):
        feed.get_history("rb.SHFE", "2024-01-01", "2024-01-31", "1h")
    assert called["n"] == 0
    assert normalize_period("30MIN")[1] == 1800


def test_close_idempotent():
    """close() 幂等：重复调用只关闭一次，之后可重新懒建连接。"""
    api = _FakeApi(_bars())
    feed = TqSdkFeed(api_factory=lambda: api)
    feed.get_recent("rb.SHFE", "D", 3)
    assert feed._api is api

    feed.close()
    feed.close()
    assert api.close_calls == 1
    assert feed._api is None

    # 再次取数会重新初始化（尚未 close 的同一桩对象仍可用）
    feed.get_recent("rb.SHFE", "D", 3)
    assert feed._api is api
    feed.close()
    assert api.close_calls == 2


@pytest.mark.parametrize("raw,expected", [
    ("rb0", "KQ.m@SHFE.rb"),
    ("rb", "KQ.m@SHFE.rb"),
    ("rb.SHFE", "KQ.m@SHFE.rb"),
    ("RB.SHFE", "KQ.m@SHFE.rb"),
    ("SHFE.rb2611", "SHFE.rb2611"),
    ("rb2611", "SHFE.rb2611"),
    ("rb2611.SHFE", "SHFE.rb2611"),
    ("MA609", "CZCE.MA609"),
    ("i2409", "DCE.i2409"),
    ("KQ.m@SHFE.rb", "KQ.m@SHFE.rb"),
])
def test_symbol_normalization(raw, expected):
    """常见项目写法都能规范成 TqSdk 代码。"""
    assert to_tq_symbol(raw) == expected


def test_invalid_symbol_raises():
    """无法识别的合约代码必须报错，不能猜测一个错误合约。"""
    with pytest.raises(InvalidSymbolError):
        to_tq_symbol("zzz999")
    with pytest.raises(InvalidSymbolError):
        to_tq_symbol("XX.rb2611")


def test_credentials_from_env_and_file(monkeypatch, tmp_path):
    """凭据读取：环境变量优先；否则读取本地未跟踪文件。"""
    monkeypatch.setenv("TQ_USER", "tester")
    monkeypatch.setenv("TQ_PASSWORD", "secret")
    creds = TqSdkCredentials.load()
    assert creds.complete and creds.origin == "env"

    monkeypatch.delenv("TQ_USER")
    monkeypatch.delenv("TQ_PASSWORD")
    fp = tmp_path / "tqsdk_settings.json"
    fp.write_text('{"user": "file_user", "password": "file_pwd"}', encoding="utf-8")
    creds2 = TqSdkCredentials.load(path=str(fp))
    assert creds2.complete and creds2.origin.startswith("file:")


def test_registry_and_diagnose(tmp_path):
    """注册表可见 tqsdk；诊断在未安装/无凭据时如实报告。"""
    import futures_quant.data  # noqa: F401  # 触发包级注册
    assert "tqsdk" in registered_feeds()
    assert get_feed_factory("tqsdk") is not None

    diag = tqsdk_diagnose(path=str(tmp_path / "none.json"))
    assert isinstance(diag["installed"], bool)
    assert diag["creds_complete"] is False


def test_manager_tqsdk_failure_never_returns_synthetic(monkeypatch):
    """管理器层：TqSdk 失败返回空表 + tqsdk provenance，绝不回退合成。"""
    from futures_quant.data.market_data import MarketDataManager

    mdm = MarketDataManager(source="tqsdk")
    def _boom():
        raise RuntimeError("simulated outage")
    mdm.feed = TqSdkFeed(api_factory=_boom)

    df = mdm.get_bars("rb.SHFE", "1m", limit=10)
    assert df.empty
    prov = mdm.last_provenance
    assert prov["data_source"] == "tqsdk"
    assert prov["is_synthetic"] is False
    assert "TqSdk 取数失败" in prov["note"]

    # 连接探测失败：状态文本必须明确「不可用」，且禁止模拟 tick
    mdm.connect()
    assert mdm.is_real is False
    assert mdm.allow_sim is False
    assert "TqSdk 不可用" in mdm.status
    assert "合成" not in mdm.status
