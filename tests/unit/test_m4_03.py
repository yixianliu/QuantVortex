# -*- coding: utf-8 -*-
"""M4-03 验收（pytest 版）：修复字号层级丢失（P0）。

对照原始散落脚本 tests/test_m4_03.py 改写：
  · main() + sys.exit(main()) → pytest 函数；
  · check(cond,msg) → assert；行为契约不变；
  · 纯字符串/数值计算，不创建任何 Qt widget（build_qss / scale_qss_fonts 为纯函数）。

验收点：
  1. 1080p(1920×1080) 下 QSS 三档字号经响应式钳制后下限不丢失：
     font_size(13)>=13、font_size(12)>=12、font_size(11)>=11；
  2. scale 下限已提到 0.85（get_scale_factor(1920,1080) >= 0.85）；
  3. 生成的 QSS 中最小 font-size >= 11px（序号层级不丢失）；
  4. scale_qss_fonts 单趟替换幂等、无串味（二次应用结果一致，13/12 档各自保持）。
"""
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_mgr(w, h):
    from futures_quant.ui.responsive_layout import (
        ResolutionStandard, ResponsiveLayoutManager,
    )
    m = ResponsiveLayoutManager()
    m._width = w
    m._height = h
    m._scale = ResolutionStandard.get_scale_factor(w, h)
    m._determine_resolution_class()
    return m


# ───────────────────────────────────────────────────── ② scale 下限 0.85
def test_scale_floor_1080p():
    from futures_quant.ui.responsive_layout import ResolutionStandard

    s = ResolutionStandard.get_scale_factor(1920, 1080)
    assert abs(s - 0.85) < 1e-9, f"get_scale_factor(1920,1080)==0.85（实测 {s}）"


def test_scale_floor_compact():
    from futures_quant.ui.responsive_layout import ResolutionStandard

    s = ResolutionStandard.get_scale_factor(1366, 768)
    assert s >= 0.85, f"紧凑屏(1366×768) scale 钳到 0.85 下限（实测 {s}）"


def test_scale_2k_is_one():
    from futures_quant.ui.responsive_layout import ResolutionStandard

    s = ResolutionStandard.get_scale_factor(2560, 1440)
    assert abs(s - 1.0) < 1e-9, f"2K(2560×1440) scale==1.0（实测 {s}）"


# ───────────────────────────────────────────────────── ① 三档字号下限（1080p）
def test_font_size_floor_1080p():
    mgr = _make_mgr(1920, 1080)
    fs13, fs12, fs11 = mgr.font_size(13), mgr.font_size(12), mgr.font_size(11)
    assert fs13 >= 13, f"font_size(13)>=13（实测 {fs13}）"
    assert fs12 >= 12, f"font_size(12)>=12（实测 {fs12}）"
    assert fs11 >= 11, f"font_size(11)>=11（实测 {fs11}）"
    assert fs13 > fs11, f"13 与 11 档可区分（{fs13} > {fs11}）"
    assert fs13 >= fs12 >= fs11, "字号三档单调（13>=12>=11）"


@pytest.mark.parametrize("wh,tag", [
    ((1366, 768), "紧凑"), ((1920, 1080), "1080p"),
    ((2560, 1440), "2K"), ((3840, 2160), "4K"),
])
def test_font_size_floor_all_resolutions(wh, tag):
    mgr = _make_mgr(*wh)
    lo = mgr.font_size(11)
    assert lo >= 11, f"{tag}{wh} font_size(11)>=11（实测 {lo}）"


# ───────────────────────────────────────────────────── ③ QSS 最小字号 >=11px
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_qss_min_font_size(theme):
    from futures_quant.ui.design_system import build_qss
    from futures_quant.ui.main_window import scale_qss_fonts

    mgr = _make_mgr(1920, 1080)
    qss = build_qss(theme)
    scaled = scale_qss_fonts(qss, mgr)
    sizes = [int(x) for x in re.findall(r"font-size:(\d+)px", scaled)]
    assert sizes, f"[{theme}] 未找到任何 font-size（异常）"
    assert min(sizes) >= 11, \
        f"[{theme}] 缩放后最小字号 >=11px（实测最小 {min(sizes)}px）"
    bad = re.findall(r"font-size:(?:10|9|8|7|6|5|4|3|2|1)px", scaled)
    assert not bad, f"[{theme}] 无 <11px 字号串（实测 {bad}）"


# ───────────────────────────────────────────────────── ④ 幂等 + 不串味
def test_scale_qss_fonts_idempotent():
    from futures_quant.ui.design_system import build_qss
    from futures_quant.ui.main_window import scale_qss_fonts

    mgr = _make_mgr(1920, 1080)
    once = scale_qss_fonts(build_qss("dark"), mgr)
    twice = scale_qss_fonts(once, mgr)
    assert once == twice, "scale_qss_fonts 幂等（二次应用结果一致）"
    assert "font-size:13px;" in once and "font-size:12px;" in once, \
        "13/12 档在 1080p 下保持各自字号（层级未压平）"


def test_scale_qss_fonts_high_scale_floor():
    from futures_quant.ui.design_system import build_qss
    from futures_quant.ui.main_window import scale_qss_fonts
    from futures_quant.ui.responsive_layout import ResolutionStandard, ResponsiveLayoutManager

    mgr = ResponsiveLayoutManager()
    mgr._width, mgr._height = 2560, 1440
    mgr._scale = 1.5
    mgr._determine_resolution_class()
    hi = scale_qss_fonts(build_qss("dark"), mgr)
    hi_sizes = [int(x) for x in re.findall(r"font-size:(\d+)px", hi)]
    assert min(hi_sizes) >= 11, f"scale=1.5 下最小字号仍 >=11px（实测 {min(hi_sizes)}）"
