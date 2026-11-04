# -*- coding: utf-8 -*-
"""阶段 0（数据源可信化）回归测试。

覆盖：
1. 合成行情必须携带 is_synthetic=True / data_source=synthetic；
2. 真实源无数据时，MarketDataManager 不得静默回退：必须显式标注来源与原因；
3. 真实源数据经过 get_bars 切片后来源元数据不丢失；
4. 未标注的旧 DataFrame 读取来源时返回安全默认值（向后兼容）；
5. CTP 在历史 K 线仍为合成时，状态标签不得宣称「实盘已连接」。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
import pytest

from futures_quant.data.base import get_provenance, provenance_text
from futures_quant.data.synthetic import SyntheticFeed


def test_synthetic_frame_is_marked():
    """合成行情必须自带模拟标记，供 UI 常驻水印使用。"""
    df = SyntheticFeed().get_recent("rb.SHFE", "D", limit=20)
    prov = get_provenance(df)
    assert prov["data_source"] == "synthetic"
    assert prov["is_synthetic"] is True
    assert prov["is_stale"] is False
    assert prov["as_of"] is not None
    assert "合成" in prov["note"]


def test_unmarked_frame_defaults_are_backward_compatible():
    """未标注的老 DataFrame 读取时不抛异常，返回安全默认值。"""
    df = pd.DataFrame({"close": [1.0, 2.0]})
    prov = get_provenance(df)
    assert prov["data_source"] == "unknown"
    assert prov["is_synthetic"] is False
    assert prov["is_stale"] is False
    # 纯文本生成不得抛异常
    assert "来源未知" in provenance_text(prov["data_source"])


class _NullFeed:
    """真实源桩：对任何请求都返回空数据（模拟断网/周期不支持）。"""

    def get_history(self, symbol, start, end, period="D", limit=0):
        return None

    def get_recent(self, symbol, period="1m", limit=600):
        return None

    def connect(self):
        return False


def test_manager_marks_fallback_as_synthetic():
    """真实源无数据 → 回退合成必须显式标注，禁止静默。"""
    from futures_quant.data.market_data import MarketDataManager

    mdm = MarketDataManager(feed=_NullFeed())
    df = mdm.get_bars("rb.SHFE", "1m", limit=20)
    prov = mdm.last_provenance
    assert prov["is_synthetic"] is True
    assert prov["data_source"] == "synthetic"
    assert "回退合成" in prov["note"]
    assert get_provenance(df)["is_synthetic"] is True


class _RealFeed:
    """真实源桩：返回已标注来源的数据。"""

    def get_history(self, symbol, start, end, period="D", limit=0):
        n = 30
        out = pd.DataFrame({
            "datetime": pd.date_range("2024-01-02", periods=n, freq="D"),
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1000.0] * n,
            "open_interest": [5000.0] * n,
        })
        out.attrs.update({
            "data_source": "sina", "is_synthetic": False, "is_stale": False,
            "as_of": out["datetime"].iloc[-1], "note": "",
        })
        return out

    def get_recent(self, symbol, period="1m", limit=600):
        return self.get_history(symbol, None, None, period, limit)

    def connect(self):
        return True


def test_manager_preserves_real_provenance_after_slicing():
    """真实数据经 tail/reset_index 后 attrs 不能丢（否则 UI 会显示来源未知）。"""
    from futures_quant.data.market_data import MarketDataManager

    mdm = MarketDataManager(feed=_RealFeed())
    df = mdm.get_bars("rb.SHFE", "D", limit=10)
    prov = get_provenance(df)
    assert prov["data_source"] == "sina"
    assert prov["is_synthetic"] is False
    assert len(df) == 10


def test_ctp_label_does_not_claim_real_history():
    """CTP 历史 K 线为合成时，连接状态与数据来源必须分开表达。"""
    from futures_quant.data.ctp_gateway import CTPFeed

    feed = CTPFeed()
    feed.connected = True          # 模拟行情网关已连上
    label = feed.source_label
    assert "历史K线为合成" in label, f"CTP 标签不得掩盖合成历史: {label}"
    hist = feed.get_history("rb.SHFE", "2024-01-01", "2024-12-31", "D", limit=10)
    prov = get_provenance(hist)
    assert prov["is_synthetic"] is True
    assert prov["data_source"] == "ctp-fallback"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
