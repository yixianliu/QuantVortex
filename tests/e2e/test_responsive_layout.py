"""GUI 响应式布局测试脚本

本脚本用于验证 GUI 界面在不同分辨率下的自适应布局效果。
测试目标分辨率：
  - 2560x1440 (2K)
  - 1920x1080 (Full HD)
  - 1366x768 (低分辨率)

用法:
    python test_responsive_layout.py [分辨率]

示例:
    python test_responsive_layout.py 1920x1080
    python test_responsive_layout.py 2560x1440
    python test_responsive_layout.py all
"""
import sys
import argparse

# 设置 Qt 属性
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt6.QtGui import QFont


def setup_high_dpi():
    """配置高 DPI 支持。"""
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)


class LayoutTestWindow(QWidget):
    """布局测试窗口。"""

    def __init__(self, width: int, height: int):
        """初始化测试窗口。

        参数:
            width: 窗口宽度
            height: 窗口高度
        """
        super().__init__()
        self.test_width = width
        self.test_height = height
        self.setWindowTitle(f"响应式布局测试 - {width}x{height}")
        self.resize(width, height)

        # 导入响应式布局管理器
        from futures_quant.ui.responsive_layout import ResponsiveLayoutManager, ResolutionStandard

        # 模拟指定分辨率
        self.layout_mgr = ResponsiveLayoutManager()
        self.layout_mgr._width = width
        self.layout_mgr._height = height
        self.layout_mgr._scale = ResolutionStandard.get_scale_factor(width, height)
        self.layout_mgr._determine_resolution_class()

        self._build_ui()

    def _build_ui(self):
        """构建测试界面。"""
        root = QVBoxLayout(self)
        root.setSpacing(15)

        # 标题
        title = QLabel("<h2>期货智能分析预测系统 - 响应式布局测试</h2>")
        title.setStyleSheet("color: #e6e6e6;")
        root.addWidget(title)

        # 分辨率信息
        info = QLabel(f"""
<b>测试分辨率:</b> {self.test_width} x {self.test_height}<br>
<b>缩放因子:</b> {self.layout_mgr.scale:.2f}<br>
<b>分辨率级别:</b> {self.layout_mgr.resolution_class}<br>
<b>基础字体:</b> {self.layout_mgr.font_size(13)}px<br>
<b>导航栏宽度:</b> {self.layout_mgr.nav_width()}px<br>
<b>页面边距:</b> {self.layout_mgr.page_margin()}px<br>
<b>表格行高:</b> {self.layout_mgr.row_height()}px<br>
<b>最小窗口尺寸:</b> {self.layout_mgr.get_min_window_size()}
""")
        info.setStyleSheet("""
            color: #e6e6e6;
            background: #161a24;
            padding: 15px;
            border-radius: 8px;
            font-family: 'Microsoft YaHei', sans-serif;
        """)
        info.setWordWrap(True)
        root.addWidget(info)

        # 组件预览
        preview_title = QLabel("<h3>组件预览</h3>")
        preview_title.setStyleSheet("color: #e6e6e6;")
        root.addWidget(preview_title)

        # 创建测试组件
        from futures_quant.ui.widgets import PageHeader, StatCard, Badge, ConfidenceBar

        # 页面标题
        header = PageHeader("实时行情全景", "全市场合约行情 · 盘口快照 · 自选监控")
        root.addWidget(header)

        # 指标卡片行
        cards_layout = QVBoxLayout()
        cards_container = QWidget()
        hlayout = QVBoxLayout(cards_container)
        hlayout.setContentsMargins(0, 0, 0, 0)

        row1 = " ".join([
            f"<b>最新价:</b> {self.layout_mgr.font_size(16)}px, "
            f"<b>涨跌幅:</b> {self.layout_mgr.font_size(14)}px, "
            f"<b>成交量:</b> {self.layout_mgr.font_size(14)}px"
        ])
        self.info_label = QLabel(row1)
        self.info_label.setStyleSheet("color: #e6e6e6; padding: 10px; background: #161a24; border-radius: 8px;")
        hlayout.addWidget(self.info_label)
        root.addWidget(cards_container)

        # 徽章和进度条
        badge_row = QWidget()
        bhlayout = QVBoxLayout(badge_row)
        bhlayout.setContentsMargins(0, 0, 0, 0)

        badge = Badge("中性", bg="#1c2230", fg="#e6e6e6")
        progress = ConfidenceBar(0.65)
        progress.setMinimumHeight(self.layout_mgr.component_size(18, min_size=14))

        row_widget = QWidget()
        rhlayout = QVBoxLayout(row_widget)
        rhlayout.setContentsMargins(10, 10, 10, 10)
        rhlayout.addWidget(badge)
        rhlayout.addWidget(progress)

        hlayout.addWidget(row_widget)
        root.addWidget(cards_container)

        root.addStretch(1)

        # 底部状态
        status = QLabel(f"窗口尺寸: {width}x{height} | 状态: 响应式布局已激活")
        status.setStyleSheet("""
            color: #8b93a7;
            background: #0b0d12;
            padding: 10px;
            border-top: 1px solid #2a2e3a;
        """)
        root.addWidget(status)

    def resizeEvent(self, event):
        """处理窗口尺寸变化事件。"""
        super().resizeEvent(event)
        size_info = f"当前窗口尺寸: {event.size().width()}x{event.size().height()}"
        # 更新状态标签（如果存在）
        for widget in self.findChildren(QLabel):
            if "窗口尺寸" in widget.text():
                widget.setText(size_info)
                break


def run_test(width: int, height: int):
    """运行单个分辨率测试。

    参数:
        width: 测试宽度
        height: 测试高度

    返回:
        bool: 测试是否成功
    """
    setup_high_dpi()

    app = QApplication(sys.argv)

    # 设置基础字体
    from futures_quant.ui.responsive_layout import get_layout_manager
    mgr = get_layout_manager()
    base_size = mgr.font_size(10)
    app.setFont(QFont("Microsoft YaHei", base_size))

    win = LayoutTestWindow(width, height)
    win.show()

    print(f"\n{'='*60}")
    print(f"分辨率测试: {width}x{height}")
    print(f"{'='*60}")
    print(f"缩放因子: {mgr.scale:.2f}")
    print(f"分辨率级别: {mgr.resolution_class}")
    print(f"最小窗口尺寸: {mgr.get_min_window_size()}")
    print(f"基础字体: {base_size}px")
    print(f"导航栏宽度: {mgr.nav_width()}px")
    print(f"页面边距: {mgr.page_margin()}px")
    print(f"表格行高: {mgr.row_height()}px")
    print(f"{'='*60}\n")

    # 等待用户查看结果后退出
    # 在实际测试中，这里可以添加自动截图验证逻辑
    return win


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="GUI 响应式布局测试")
    parser.add_argument(
        "resolution",
        nargs="?",
        default="all",
        help="目标分辨率 (格式: 1920x1080 或 'all')"
    )
    args = parser.parse_args()

    resolutions = [
        (2560, 1440, "2K (2560x1440)"),
        (1920, 1080, "Full HD (1920x1080)"),
        (1366, 768, "低分辨率 (1366x768)"),
    ]

    if args.resolution.lower() == "all":
        test_resolutions = resolutions
    else:
        w, h = map(int, args.resolution.split("x"))
        test_resolutions = [(w, h, f"自定义 ({w}x{h})")]

    windows = []
    for width, height, label in test_resolutions:
        win = run_test(width, height)
        windows.append(win)

    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
