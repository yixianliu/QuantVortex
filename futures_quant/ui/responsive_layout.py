"""响应式布局模块 · 支持多分辨率自适应

本模块为期货量化分析系统提供屏幕分辨率自适应能力。
根据目标分辨率自动计算字体大小、间距、组件尺寸等布局参数，
确保在 2560*1440 和 1920*1080 等不同分辨率下均能良好显示。
"""
from __future__ import annotations

import sys
from typing import Optional, Tuple, Dict, Any

from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication, QWidget


# ============================================================================
# 目标分辨率标准定义
# ============================================================================
class ResolutionStandard:
    """分辨率标准配置类。

    定义不同分辨率下的布局参数基准值，包括：
    - 基础字体大小（pt）
    - 最小面板宽度（px）
    - 导航栏宽度（px）
    - 页面边距（px）
    - 行高（px）
    - 内边距系数
    """

    # 2560x1440 (2K) 作为基准分辨率
    STANDARD_WIDTH = 2560
    STANDARD_HEIGHT = 1440

    # 基础比例因子（基于基准分辨率）
    BASE_FONT_SIZE = 13
    BASE_NAV_WIDTH = 168
    BASE_PAGE_MARGIN = 10
    BASE_ROW_HEIGHT = 28
    BASE_PADDING_FACTOR = 1.0

    @classmethod
    def get_scale_factor(cls, width: int, height: int) -> float:
        """根据屏幕宽度计算缩放因子。

        参数:
            width: 屏幕宽度（px）
            height: 屏幕高度（px）

        返回:
            float: 缩放因子（1.0 为基准）
        """
        # 以宽度为主要参考，高度作为辅助
        width_ratio = width / cls.STANDARD_WIDTH
        height_ratio = height / cls.STANDARD_HEIGHT

        # 使用宽度比例作为主要缩放依据，限制在 0.85 ~ 1.5 范围内
        # M4-03：下限由 0.75 提升到 0.85，避免 1080p 下字号被过度压缩
        scale = max(0.85, min(1.5, width_ratio))
        return scale


# ============================================================================
# 响应式布局管理器
# ============================================================================
class ResponsiveLayoutManager:
    """响应式布局管理器：根据当前屏幕分辨率动态计算布局参数。"""

    def __init__(self) -> None:
        """初始化布局管理器。"""
        self._screen: Optional[QScreen] = None
        self._scale: float = 1.0
        self._width: int = 0
        self._height: int = 0
        self._resolution_class: str = "standard"  # standard / compact / wide
        # M4-14④：用户字号缩放（0.9/1.0/1.1/1.25），与屏幕响应式缩放相乘
        self._user_font_scale: float = 1.0

    def initialize(self) -> None:
        """从应用主窗口初始化布局管理器。"""
        app = QApplication.instance()
        if app is None:
            return

        # 获取主屏幕
        primary_screen = app.primaryScreen()
        if primary_screen is None:
            return

        self._screen = primary_screen
        geometry = primary_screen.availableGeometry()
        self._width = geometry.width()
        self._height = geometry.height()
        self._scale = ResolutionStandard.get_scale_factor(
            self._width, self._height
        )

        # 确定分辨率级别
        self._determine_resolution_class()

    def _determine_resolution_class(self) -> None:
        """根据屏幕尺寸确定分辨率级别。"""
        w, h = self._width, self._height

        if w >= 2560 and h >= 1440:
            self._resolution_class = "wide"
        elif w >= 1920 and h >= 1080:
            self._resolution_class = "standard"
        elif w < 1366:
            self._resolution_class = "compact"
        else:
            self._resolution_class = "standard"

    @property
    def width(self) -> int:
        """返回屏幕宽度。"""
        return self._width

    @property
    def height(self) -> int:
        """返回屏幕高度。"""
        return self._height

    @property
    def scale(self) -> float:
        """返回缩放因子。"""
        return self._scale

    @property
    def resolution_class(self) -> str:
        """返回分辨率级别。"""
        return self._resolution_class

    # 字号下限（px）：M4-03 保证 1080p 下最小字号不低于 11px
    FONT_MIN = 11
    FONT_MAX = 18

    def font_size(self, base_size: int = 13) -> int:
        """根据缩放因子计算实际字体大小（三档钳制，保层级不丢失）。

        M4-03：对 ≤13 的字号，下限不得低于名义值（13/12/11），且整体不低于
        FONT_MIN=11px；上限 FONT_MAX=18px。这样 13/12/11 始终可区分。

        M4-14④：用户字号缩放**作用在响应式钳制结果之后**（先按屏幕缩放并
        钳制，再乘用户系数四舍五入）。不能乘在前面——compact 屏 scale=0.85
        会把 125% 抵消回原值；无障碍放大需要突破名义 floor。放大上限
        ``max(FONT_MAX, 名义值*1.5)`` 防布局溢出。

        参数:
            base_size: 基准字体大小（pt）

        返回:
            int: 实际字体大小
        """
        scaled = int(base_size * self._scale)
        if base_size <= 13:
            floor = max(self.FONT_MIN, base_size)
        else:
            floor = self.FONT_MIN
        resp = max(floor, min(self.FONT_MAX, scaled))
        if self._user_font_scale == 1.0:
            return resp
        if base_size <= 13:
            ceiling = max(self.FONT_MAX, int(base_size * 1.5))
        else:
            ceiling = self.FONT_MAX
        return max(self.FONT_MIN,
                   min(ceiling, round(resp * self._user_font_scale)))

    # ---- M4-14④：用户字号缩放 ----
    @property
    def user_font_scale(self) -> float:
        """用户字号缩放系数（1.0=100%）。"""
        return self._user_font_scale

    def set_user_font_scale(self, scale: float) -> None:
        """设置用户字号缩放（0.8~1.5 钳制；设置项为 90/100/110/125%）。"""
        try:
            self._user_font_scale = max(0.8, min(1.5, float(scale)))
        except (TypeError, ValueError):
            self._user_font_scale = 1.0

    def nav_width(self) -> int:
        """计算导航栏宽度。"""
        return max(120, int(ResolutionStandard.BASE_NAV_WIDTH * self._scale))

    def page_margin(self) -> int:
        """计算页面边距。"""
        return max(6, int(ResolutionStandard.BASE_PAGE_MARGIN * self._scale))

    def row_height(self) -> int:
        """计算表格行高。"""
        return max(24, int(ResolutionStandard.BASE_ROW_HEIGHT * self._scale))

    def padding_factor(self) -> float:
        """返回内边距系数。"""
        return self._scale

    def spacing(self, base_spacing: int = 8) -> int:
        """根据缩放因子计算间距。

        参数:
            base_spacing: 基准间距（px）

        返回:
            int: 实际间距
        """
        return max(4, int(base_spacing * self._scale))

    def component_size(
        self, base_size: int, min_size: int = 0, max_size: int = 9999
    ) -> int:
        """计算组件尺寸（带范围限制）。

        参数:
            base_size: 基准尺寸
            min_size: 最小尺寸
            max_size: 最大尺寸

        返回:
            int: 实际尺寸
        """
        return max(min_size, min(max_size, int(base_size * self._scale)))

    def get_min_window_size(self) -> Tuple[int, int]:
        """根据分辨率级别返回最小窗口尺寸。

        返回:
            Tuple[int, int]: (最小宽度, 最小高度)
        """
        if self._resolution_class == "compact":
            return (1024, 768)
        elif self._resolution_class == "wide":
            return (1366, 800)
        else:
            return (1100, 680)  # 原设计最小值

    def is_wide_screen(self) -> bool:
        """判断是否为宽屏（≥2560px）。"""
        return self._resolution_class in ("wide", "standard")

    def is_compact_screen(self) -> bool:
        """判断是否为紧凑屏（<1366px）。"""
        return self._resolution_class == "compact"


# ============================================================================
# 全局单例
# ============================================================================
_layout_manager: Optional[ResponsiveLayoutManager] = None


def get_layout_manager() -> ResponsiveLayoutManager:
    """获取全局布局管理器单例。

    返回:
        ResponsiveLayoutManager: 布局管理器实例
    """
    global _layout_manager
    if _layout_manager is None:
        _layout_manager = ResponsiveLayoutManager()
        _layout_manager.initialize()
    return _layout_manager


def refresh_layout() -> None:
    """重新初始化布局管理器（用于屏幕切换或分辨率变化时）。"""
    global _layout_manager
    _layout_manager = ResponsiveLayoutManager()
    _layout_manager.initialize()


def reset_layout() -> None:
    """重置布局管理器（用于测试或重置状态）。"""
    global _layout_manager
    _layout_manager = None
