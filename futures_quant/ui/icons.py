"""矢量图标库（期货量化系统 UI）。

设计目标：
    - 全部图标为 24x24 viewBox 的 SVG 线/面图标，清晰、风格统一、可任意缩放；
    - 通过 QSvgRenderer 渲染，离线可跑（依赖 PyQt6.QtSvg，环境已具备）；
    - 主题感知：用 {color} 占位符替换描边/填充色，由调用方传入当前主题色；
    - 2x 超采样渲染后回设 devicePixelRatio，保证高分屏下依旧锐利；
    - 结果按 (name, color, size) 缓存，避免频繁重绘。

仅依赖 PyQt6（QtSvg）。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

# ----------------------------- 图标定义 -----------------------------------
# 每个条目：("stroke"|"fill", <svg 内部路径，24x24 viewBox>)
_ICONS: Dict[str, Tuple[str, str]] = {
    # ---- 导航 ----
    "market": ("stroke",
        "M3 4 v16 h18 M6 16 l3-4 l3 2 l4-6 l2 3 M6 16 v2 M9 12 v6 M12 14 v6 M16 8 v12"),
    "position": ("stroke",
        "M3 8 a2 2 0 0 1 2-2 h12 a2 2 0 0 1 2 2 v8 a2 2 0 0 1 -2 2 H5 a2 2 0 0 1 -2 -2 Z M15 12 h.01"),
    "strategy": ("stroke",
        "M12 3 a9 9 0 1 0 0.01 0 M12 7 a5 5 0 1 0 0.01 0 M12 11 a1 1 0 1 0 0.01 0 M12 2 v3 M12 19 v3 M2 12 h3 M19 12 h3"),
    "risk": ("stroke",
        "M12 3 l7 3 v5 c0 5 -3 8 -7 10 c-4 -2 -7 -5 -7 -10 V6 z M9 12 l2 2 l4 -4"),
    "log": ("stroke",
        "M8 6 h12 M8 12 h12 M8 18 h12 M4 6 h.01 M4 12 h.01 M4 18 h.01"),
    "backtest": ("stroke",
        "M4 20 V10 M10 20 V4 M16 20 V14 M20 11 a8 8 0 1 0 -2 6 M20 5 v6 h-6"),
    "predict": ("stroke",
        "M12 3 l2.2 5.8 l5.8 2.2 l-5.8 2.2 L12 21 l-2.2-5.8 L4 11 l5.8-2.2 z M18.5 3.5 l1 2.5 l2.5 1 l-2.5 1 l-1 2.5 l-1-2.5 l-2.5-1 l2.5-1 z"),

    # ---- 行为 / 工具 ----
    "play": ("fill", "M7 5 v14 l12 -7 z"),
    "pause": ("fill", "M8 5 h3 v14 h-3 z M14 5 h3 v14 h-3 z"),
    "stop": ("fill", "M6 6 h12 v12 H6 Z"),
    "lock": ("stroke", "M7 11 V8 a5 5 0 0 1 10 0 v3 M5 11 h14 v9 H5 Z"),
    "clear": ("stroke", "M5 7 h14 M9 7 V5 h6 v2 M7 7 l1 13 h8 l1 -13 M10 11 v6 M14 11 v6"),
    "send": ("stroke", "M21 3 L3 10 l7 3 l3 7 z M21 3 L10 13"),
    "refresh": ("stroke", "M20 11 a8 8 0 1 0 -2 6 M20 5 v6 h-6"),
    "sun": ("stroke", "M12 4 v2 M12 18 v2 M4 12 h2 M18 12 h2 M6 6 l1.5 1.5 M17 17 l1.5 1.5 M6 18 l1.5 -1.5 M17 7 l1.5 -1.5 M12 8 a4 4 0 1 0 0.01 0"),
    "moon": ("fill", "M20 14 a8 8 0 1 1 -9 -10 a6 6 0 0 0 9 10 z"),
    "filter": ("stroke", "M4 5 h16 l-6 7 v6 l-4 2 v-8 z"),
    "search": ("stroke", "M10 4 a6 6 0 1 0 0.01 0 M14 14 l5 5"),
    "star": ("stroke", "M12 4 l2.5 5 l5.5 .8 l-4 4 l1 5.5 l-5-2.8 l-5 2.8 l1 -5.5 l-4 -4 l5.5 -.8 z"),
    "warning": ("stroke", "M12 4 l9 16 H3 Z M12 10 v4 M12 17 h.01"),
    "check": ("stroke", "M5 12 l5 5 l9 -11"),
    "chevron": ("stroke", "M6 9 l6 6 l6 -6"),
    "bolt": ("fill", "M13 3 L4 14 h6 l-1 7 l9 -11 h-6 z"),
    "gear": ("stroke", "M12 9 a3 3 0 1 0 0.01 0 M19 12 a7 7 0 0 0 -.1 -1 l2 -1.5 l-2 -3.4 l-2.3 1 a7 7 0 0 0 -1.7 -1 l-.3 -2.5 h-4 l-.3 2.5 a7 7 0 0 0 -1.7 1 l-2.3 -1 l-2 3.4 l2 1.5 a7 7 0 0 0 0 2 l-2 1.5 l2 3.4 l2.3 -1 a7 7 0 0 0 1.7 1 l.3 2.5 h4 l.3 -2.5 a7 7 0 0 0 1.7 -1 l2.3 1 l2 -3.4 l-2 -1.5 a7 7 0 0 0 .1 -1 z"),
    "book": ("stroke", "M5 4 h11 a2 2 0 0 1 2 2 v14 H7 a2 2 0 0 0 -2 2 V4 z M5 18 a2 2 0 0 1 2 -2 h11"),
    # ---- 新增导航（分析预测系统） ----
    "indicator": ("stroke", "M4 19 V5 M4 15 l4-4 l3 2 l5-7 M9 11 v8 M16 4 v16 M4 15 h0"),
    "panorama": ("stroke", "M3 3 h8 v8 H3 Z M13 3 h8 v5 h-8 Z M3 13 h8 v8 H3 Z M13 11 h8 v10 h-8 Z"),
    "validate": ("stroke", "M4 6 h11 M4 12 h7 M4 18 h9 M18 5 l2 2 l4 -4"),
    # 数据管理（数据库圆柱体）
    "db": ("stroke",
        "M12 3 c-4.4 0 -8 1.3 -8 3 v12 c0 1.7 3.6 3 8 3 s8 -1.3 8 -3 V6 "
        "c0 -1.7 -3.6 -3 -8 -3 z M4 6 c0 1.7 3.6 3 8 3 s8 -1.3 8 -3 "
        "M4 12 c0 1.7 3.6 3 8 3 s8 -1.3 8 -3"),
}

# 导航顺序（与 main_window 的 nav_items 一一对应）
NAV_ICONS = ["market", "position", "strategy", "risk", "log", "backtest", "predict"]

_CACHE: Dict[Tuple[str, str, int], QIcon] = {}


def icon(name: str, theme: str = "dark", color_override: Optional[str] = None,
         size: int = 20) -> QIcon:
    """返回渲染好的 QIcon。

    :param name: 图标名（见 _ICONS）
    :param theme: "dark"/"light"，用于取默认描边色
    :param color_override: 显式指定颜色（十六进制），优先于主题默认
    :param size: 逻辑像素尺寸
    """
    if name not in _ICONS:
        name = "star"
    key = (name, color_override or theme, size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    kind, body = _ICONS[name]
    if color_override:
        col = color_override
    else:
        from .widgets import PALETTE
        col = PALETTE[theme]["text"]

    if kind == "fill":
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               f'fill="{col}" stroke="none">{body}</svg>')
    else:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               f'fill="none" stroke="{col}" stroke-width="2" '
               f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    dpr = 2
    px = QPixmap(size * dpr, size * dpr)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    px.setDevicePixelRatio(dpr)
    qi = QIcon(px)
    _CACHE[key] = qi
    return qi
