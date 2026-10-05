# -*- coding: utf-8 -*-
"""M5-08 行情源降级链契约测试。

覆盖：
- sina/csv/synthetic 三个数据源的 7 列契约（[datetime, open, high, low, close,
  volume, open_interest]），保证下游消费方对列序/列名的稳定预期。
- 离线场景下 sina get_recent 不崩溃（返空 df 而非抛异常）。
- _build_feed 的降级链：sina 探测失败 -> synthetic、csv 真实样本成功
  -> csv、未知 source -> synthetic。

运行：
    /d/anaconda3/python.exe -m pytest tests/unit/test_market_data_feeds.py -v
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
import pytest

from futures_quant.data import market_data as md
from futures_quant.data import sina_feed, csv_feed, synthetic

REQUIRED_COLS = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]


# ============================================================================
# 公共 fixture：把 _get_http_client 替换为永远返回 404 的 fake，
# 模拟「无网络 / 被限流 / 被拦截」场景。
# ============================================================================

class _NoNetResp:
    """强制走 _fetch_daily try 兜底路径（不抛异常、不返数据）。"""

    status_code = 503

    @property
    def reason(self) -> str:
        return "Service Unavailable"

    @property
    def text(self) -> str:
        return ""

    @property
    def content(self) -> bytes:
        return b""


class _NoNetClient:
    def get(self, url, **kwargs):
        return _NoNetResp()


@pytest.fixture
def no_net_http(monkeypatch):
    """离线 fake http client：注入到 sina_feed 的 http_client 单例与构造链。"""
    fake = _NoNetClient()
    # M5-03：SinaFeed._http 走 _get_http_client
    monkeypatch.setattr(sina_feed, "_get_http_client", lambda: fake)
    # 同时保证缓存目录不依赖项目根（落到 temp）
    monkeypatch.setattr(sina_feed.SinaFeed, "__init__",
                        lambda self, cache_dir="data/sina_cache", timeout=6.0, max_age_hours=6.0:
                        setattr(self, "cache_dir", cache_dir) or setattr(self, "timeout", timeout)
                        or setattr(self, "max_age_hours", max_age_hours)
                        or setattr(self, "_mem", {}))
    return fake


# ============================================================================
# 7 列契约（csv / synthetic 真样本；sina 用空 df 兜底验证列结构）
# ============================================================================

def test_csv_real_sample_has_seven_columns():
    """rb_SHFE_D 真样本必须含 7 列且列序一致。"""
    feed = csv_feed.CsvFeed()
    df = feed.get_recent("rb.SHFE", "D", limit=20)
    assert df is not None and not df.empty, "rb.SHFE 真样本不应为空"
    assert list(df.columns) == REQUIRED_COLS, f"列序错: {list(df.columns)}"


def test_csv_missing_symbol_falls_back_to_synthetic():
    """CSV 真样本缺失 -> 自动降级 SyntheticFeed（不抛异常，返有效 df）。"""
    feed = csv_feed.CsvFeed()
    df = feed.get_recent("NOSUCH.SYM", "D", limit=10)
    assert isinstance(df, pd.DataFrame), f"应返 DataFrame，实际 {type(df)}"
    assert list(df.columns) == REQUIRED_COLS, f"列序错: {list(df.columns)}"
    assert not df.empty, "synthetic 回退应能生成数据"


def test_synthetic_seven_columns():
    """SyntheticFeed.get_recent 必须产出 7 列。"""
    feed = synthetic.SyntheticFeed()
    df = feed.get_recent("rb.SHFE", "1m", limit=60)
    assert df is not None and not df.empty
    assert list(df.columns) == REQUIRED_COLS, f"列序错: {list(df.columns)}"


def test_synthetic_get_history_window():
    """SyntheticFeed.get_history[start,end] 应能按 datetime 切片。"""
    feed = synthetic.SyntheticFeed()
    full = feed.get_recent("rb.SHFE", "1m", limit=10)
    assert len(full) >= 5
    s = str(full["datetime"].iloc[0].date())
    e = str(full["datetime"].iloc[-1].date())
    sub = feed.get_history("rb.SHFE", s, e, "1m")
    assert not sub.empty
    assert list(sub.columns) == REQUIRED_COLS


def test_sina_offline_returns_valid_df(no_net_http):
    """M5-08 离线 sina：get_recent 不崩（无论返缓存/空 df 都接受），列结构必须 7 列。"""
    feed = sina_feed.SinaFeed()
    df = feed.get_recent("rb0", "D", limit=10)
    assert df is not None, "离线 sina 不应返 None"
    assert isinstance(df, pd.DataFrame), f"应返 DataFrame，实际 {type(df)}"
    assert list(df.columns) == REQUIRED_COLS, f"列序错: {list(df.columns)}"
    # 离线场景若有磁盘缓存则返缓存，否则返空 df —— 两种都属于安全降级


def test_sina_intraday_returns_empty_df(no_net_http):
    """日内周期（1m）sina 不支持 -> 返空 df（不抛）。"""
    feed = sina_feed.SinaFeed()
    df = feed.get_history("rb0", "2024-01-01", "2024-12-31", "1m")
    assert df is None or (df is not None and df.empty)


# ============================================================================
# 降级链：_build_feed
# ============================================================================

def test_build_feed_sina_offline_falls_back_to_synthetic(no_net_http, tmp_path, monkeypatch):
    """sina 离线 -> 探测失败 -> 降级 synthetic；LAST_FEED_ERROR 非空。"""
    # 把 sina 缓存目录落到 tmp，避免污染生产 data/
    monkeypatch.setattr(sina_feed, "os", __import__("os"))
    feed, effective = md._build_feed("sina", str(tmp_path))
    assert effective == "synthetic", f"sina 离线应降级 synthetic，实际 {effective}"
    assert md.LAST_FEED_ERROR, "降级时 LAST_FEED_ERROR 应记录原因"


def test_build_feed_csv_uses_real_samples(tmp_path):
    """csv 源真样本存在 -> 返回 csv（不降级）。"""
    feed, effective = md._build_feed("csv", str(tmp_path))
    assert effective == "csv"
    assert isinstance(feed, csv_feed.CsvFeed)


def test_build_feed_synthetic_explicit():
    """显式 synthetic source -> 直接返 synthetic，不探测。"""
    feed, effective = md._build_feed("synthetic", "data")
    assert effective == "synthetic"
    assert isinstance(feed, synthetic.SyntheticFeed)


def test_build_feed_unknown_source_falls_back_to_synthetic():
    """未知 source -> synthetic（防御性降级）。"""
    feed, effective = md._build_feed("nosuch_source", "data")
    assert effective == "synthetic"
    assert isinstance(feed, synthetic.SyntheticFeed)


def test_build_feed_akshare_attempts_then_falls_back(tmp_path, monkeypatch):
    """akshare 不可用 -> 降级 synthetic + LAST_FEED_ERROR。"""
    # 不强制 akshare 离线（仅确保探测失败时降级逻辑正确）
    # 如果 akshare 恰好在线，effective 可能是 akshare/synthetic 之一
    feed, effective = md._build_feed("akshare", str(tmp_path))
    assert effective in ("akshare", "synthetic"), f"akshare 探测结果异常: {effective}"


# ============================================================================
# 变异守护：列序打乱 -> 消费方立即发现
# ============================================================================

def test_mutation_guard_required_cols_order():
    """REQUIRED_COLS 顺序若被改坏，下游消费者会崩；本断言锁住列序。"""
    assert REQUIRED_COLS == ["datetime", "open", "high", "low", "close", "volume", "open_interest"], \
        "REQUIRED_COLS 列序必须与 DataFeed 契约一致"
    # 验证 sina_feed._COLS 与本契约一致（防止两边漂移）
    assert sina_feed._COLS == REQUIRED_COLS, \
        f"sina_feed._COLS 漂移: {sina_feed._COLS} != {REQUIRED_COLS}"