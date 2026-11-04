# -*- coding: utf-8 -*-
"""M4-03 验证：修复字号层级丢失（P0）。

验收点：
    1. 1080p(1920×1080) 下 QSS 三档字号经响应式钳制后：
       font_size(13)>=13、font_size(12)>=12、font_size(11)>=11（下限不丢失）；
    2. scale 下限已提到 0.85（get_scale_factor(1920,1080) >= 0.85）；
    3. 生成的 QSS 中最小 font-size >= 11px（序号层级不丢失）；
    4. scale_qss_fonts 单趟替换幂等、无串味（二次应用结果一致）。

运行（offscreen）：
    QT_QPA_PLATFORM=offscreen python test_m4_03.py
"""
from __future__ import annotations

import os
import re
import sys

# offscreen 平台 + 守卫重定向（避免 E:\Temp 极慢/锁超时）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR",
    "D:/PythonProject/QuantVortex/.pytest_tmp/sd-state",
)
os.environ.setdefault("QUANTVORTEX_NO_PERSIST", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from futures_quant.ui.responsive_layout import (
        ResponsiveLayoutManager, ResolutionStandard,
    )
    from futures_quant.ui import main_window as MW
    from futures_quant.ui.main_window import scale_qss_fonts
    from futures_quant.ui.design_system import build_qss

    def make_mgr(w: int, h: int) -> ResponsiveLayoutManager:
        m = ResponsiveLayoutManager()
        m._width = w
        m._height = h
        m._scale = ResolutionStandard.get_scale_factor(w, h)
        m._determine_resolution_class()
        return m

    print("=" * 70)
    print("M4-03 · 字号层级修复验证")
    print("=" * 70)

    # ---- 验收 2：scale 下限 0.85 ----
    s1080 = ResolutionStandard.get_scale_factor(1920, 1080)
    check(abs(s1080 - 0.85) < 1e-9, f"get_scale_factor(1920,1080)==0.85（实测 {s1080}）")
    s_compact = ResolutionStandard.get_scale_factor(1366, 768)
    check(s_compact >= 0.85,
          f"紧凑屏(1366×768) scale 钳到 0.85 下限（实测 {s_compact}）")
    s_wide = ResolutionStandard.get_scale_factor(2560, 1440)
    check(abs(s_wide - 1.0) < 1e-9, f"2K(2560×1440) scale==1.0（实测 {s_wide}）")

    # ---- 验收 1：三档下限（1080p）----
    mgr = make_mgr(1920, 1080)
    fs13, fs12, fs11 = mgr.font_size(13), mgr.font_size(12), mgr.font_size(11)
    print(f"  [info] 1080p: fs13={fs13} fs12={fs12} fs11={fs11} scale={mgr.scale}")
    check(fs13 >= 13, f"font_size(13)>=13（实测 {fs13}）")
    check(fs12 >= 12, f"font_size(12)>=12（实测 {fs12}）")
    check(fs11 >= 11, f"font_size(11)>=11（实测 {fs11}）")
    check(fs13 > fs11, f"13 与 11 档可区分（{fs13} > {fs11}）")
    check(fs13 >= fs12 >= fs11, "字号三档单调（13>=12>=11）")

    # 多分辨率鲁棒性：任何分辨率下最低档都不低于 11px
    for (w, h, tag) in [(1366, 768, "紧凑"), (1920, 1080, "1080p"),
                        (2560, 1440, "2K"), (3840, 2160, "4K")]:
        m = make_mgr(w, h)
        lo = m.font_size(11)
        check(lo >= 11, f"{tag}({w}×{h}) font_size(11)>=11（实测 {lo}）")

    # ---- 验收 3：生成 QSS 最小字号 >=11px（M4-04 后 QSS 来自 build_qss）----
    for qss_name, theme in (("DARK", "dark"), ("LIGHT", "light")):
        qss = build_qss(theme)
        scaled = scale_qss_fonts(qss, mgr)
        sizes = [int(x) for x in re.findall(r"font-size:(\d+)px", scaled)]
        if sizes:
            mn = min(sizes)
            check(mn >= 11,
                  f"{qss_name} 缩放后最小字号 >=11px（实测最小 {mn}px）")
        else:
            check(False, f"{qss_name} 未找到任何 font-size（异常）")
        # 1080p 下不得出现 <11 的字号串
        bad = re.findall(r"font-size:(?:10|9|8|7|6|5|4|3|2|1)px", scaled)
        check(not bad, f"{qss_name} 无 <11px 字号串（实测 {bad}）")

    # ---- 验收 4：单趟替换幂等、无串味 ----
    once = scale_qss_fonts(build_qss("dark"), mgr)
    twice = scale_qss_fonts(once, mgr)
    check(once == twice, "scale_qss_fonts 幂等（二次应用结果一致）")
    # 源串 13/12 不与目标值串味：13 档换算后仍是 13（1080p），12 档仍是 12
    check("font-size:13px;" in once and "font-size:12px;" in once,
          "13/12 档在 1080p 下保持各自字号（层级未压平）")

    # 高层级 scale 下也不串味：手动设 scale=1.5
    mgr_hi = make_mgr(2560, 1440)
    mgr_hi._scale = 1.5
    hi = scale_qss_fonts(build_qss("dark"), mgr_hi)
    hi_sizes = [int(x) for x in re.findall(r"font-size:(\d+)px", hi)]
    check(min(hi_sizes) >= 11, f"scale=1.5 下最小字号仍 >=11px（实测 {min(hi_sizes)}）")

    print("=" * 70)
    if FAILS:
        print(f"M4-03 验证失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("M4-03 全部验收通过 ✅")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
