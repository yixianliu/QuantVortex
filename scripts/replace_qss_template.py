"""
一次性脚本：将 design_system.py 中的 _QSS_TEMPLATE 替换为已 token 化的版本。
运行：python scripts/replace_qss_template.py
"""
from __future__ import annotations

import re
from pathlib import Path

PATH = Path(r"D:\PythonProject\QuantVortex\futures_quant\ui\design_system.py")

NEW_TEMPLATE = r'''_QSS_TEMPLATE = """
/* ===== 基础 ===== */
QWidget { background:$BG$; color:$TEXT$; font-family:'SimHei','Noto Sans SC','Microsoft YaHei',sans-serif; }
QMainWindow { background:$BG$; }
QWidget#central { background:$BG$; }
QWidget#content-panel { background:$BG$; }
QFrame#toolbar { background:$PANEL$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; }
QFrame#hsep { background:$GRID$; border:none; }

/* ===== 侧边导航 ===== */
QListWidget#nav { background:$PANEL$; border:none; padding-top:$space_10$px; padding-bottom:$space_10$px; outline:0; }
QListWidget#nav::item { color:$SUB$; padding:$space_md$ $space_lg$; border-left:$space_3$px solid transparent; margin:$space_2$px $space_8$px; border-radius:$radius_md$px; }
QListWidget#nav::item:hover { background:$CARD$; color:$TEXT$; }
QListWidget#nav::item:selected { background:$CARD$; color:$TEXT$; border-left:$space_3$px solid $ACCENT$; }

/* ===== 内容区 ===== */
QStackedWidget { background:$BG$; }

/* ===== 文本 ===== */
QLabel { color:$TEXT$; background:transparent; }
QLabel#sub { color:$SUB$; }

/* ===== 按钮 ===== */
QPushButton { background:$ACCENT$; color:#fff; border:$space_1$px solid transparent; border-radius:$radius_md$px; padding:$space_8$px $space_18$px; font-size:$font_h3$px; font-weight:bold; }
QPushButton:hover { background:$ACCENT2$; border-color:$ACCENT$; }
QPushButton:pressed { background:$ACCENT2$; padding-top:$space_9$px; padding-bottom:$space_7$px; }
QPushButton:focus { border:$space_1$px solid $ACCENT2$; outline:none; }
QPushButton:disabled { background:$PANEL$; color:$SUB$; border-color:transparent; }
QPushButton#secondary { background:$CARD$; color:$TEXT$; border:$space_1$px solid $BORDER$; font-weight:500; }
QPushButton#secondary:hover { background:$PANEL$; border-color:$BORDER$; color:$TEXT$; }
QPushButton#secondary:pressed { background:$PANEL$; }
QPushButton#secondary:focus { border-color:$ACCENT2$; }
QPushButton#primary { background:$ACCENT$; }
QPushButton#primary:hover { background:$ACCENT2$; }
QPushButton#danger { background:#dc2626; }
QPushButton#danger:hover { background:#b91c1c; }
QPushButton#danger:pressed { background:#991b1b; }

/* ===== 输入控件 ===== */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background:$CARD$; border:$space_1$px solid $BORDER$; border-radius:$radius_md$px; padding:$space_6$px $space_10$px; color:$TEXT$; font-size:$font_h3$px; selection-background-color:$ACCENT$; selection-color:#fff; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover { border-color:$BORDER$; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus { border:$space_1$px solid $ACCENT2$; background:$CARD$; }
QComboBox::drop-down { border:none; width:$space_20$px; }
QComboBox QAbstractItemView { background:$CARD$; color:$TEXT$; selection-background-color:$ACCENT$; selection-color:#fff; border:$space_1$px solid $BORDER$; border-radius:$radius_md$px; outline:0; padding:$space_xs$px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width:$space_lg$px; border:none; background:transparent; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover { background:$PANEL$; }

/* ===== 表格 ===== */
QTableWidget { background:$CARD$; gridline-color:$GRID$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; outline=0; font-size:$font_body$px; }
QTableWidget::item { padding:$space_6$px $space_8$px; border:none; }
QTableWidget::item:selected { background:$ACCENT$; color:#fff; }
QHeaderView::section { background:$PANEL$; color:$SUB$; border:none; padding:$space_sm$px; font-weight:bold; font-size:$font_body$px; }
QHeaderView::section:hover { color:$TEXT$; }
QTableWidget::item:hover { background:$CARD$; }

/* ===== 标签页 ===== */
QTabWidget::pane { border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; top:-$space_1$px; }
QTabBar::tab { background:$PANEL$; color:$SUB$; padding:$space_9$px $space_16$px; margin-right:$space_2$px; border-top-left-radius:$radius_md$px; border-top-right-radius:$radius_md$px; }
QTabBar::tab:selected { background:$CARD$; color:$TEXT$; }
QTabBar::tab:hover { color:$TEXT$; }

/* ===== 滚动条 ===== */
QScrollBar:vertical { background:$BG$; width:$space_md$px; border-radius:$radius_sm$px; margin=0; }
QScrollBar::handle:vertical { background:$BORDER$; border-radius:$radius_sm$px; min-height:$space_32$px; margin:$space_1$px; }
QScrollBar::handle:vertical:hover { background:$SUB$; }
QScrollBar::handle:vertical:pressed { background:$ACCENT$; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height=0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:$BG$; height:$space_md$px; border-radius:$radius_sm$px; margin=0; }
QScrollBar::handle:horizontal { background:$BORDER$; border-radius:$radius_sm$px; min-width:$space_32$px; margin:$space_1$px; }
QScrollBar::handle:horizontal:hover { background:$SUB$; }
QScrollBar::handle:horizontal:pressed { background:$ACCENT$; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width=0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }

/* ===== 复选框 ===== */
QCheckBox { color:$TEXT$; spacing:$space_sm$px; background:transparent; }
QCheckBox::indicator { width:$space_lg$px; height:$space_lg$px; border-radius:$space_xs$px; border:$space_1$px solid $BORDER$; background:$CARD$; }
QCheckBox::indicator:hover { border-color:$ACCENT$; }
QCheckBox::indicator:checked { background:$ACCENT$; border-color:$ACCENT$; }
QCheckBox::indicator:checked:hover { background:$ACCENT2$; }

/* ===== 菜单栏 / 菜单 ===== */
QMenuBar { background:$PANEL$; color:$TEXT$; padding:$space_3$px $space_6$px; border-bottom:$space_1$px solid $BORDER$; spacing:$space_2$px; }
QMenuBar::item { background=transparent; padding:$space_6$px $space_14$px; border-radius:$radius_sm$px; }
QMenuBar::item:selected { background:$ACCENT$; color:#fff; }
QMenuBar::item:pressed { background:$ACCENT2$; }
QMenu { background:$CARD$; color:$TEXT$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; padding:$space_6$px; }
QMenu::item { padding:$space_8$px $space_26$px $space_8$px $space_14$px; border-radius:$radius_sm$px; }
QMenu::item:selected { background:$ACCENT$; color:#fff; }
QMenu::separator { height:$space_1$px; background:$BORDER$; margin:$space_5$px $space_md$px; }

/* ===== 状态栏 ===== */
QStatusBar { background:$PANEL$; color:$SUB$; border-top:$space_1$px solid $BORDER$; padding:$space_5$px $space_md$px; }
QStatusBar::item { border:none; }
#status-dot { color:$UP$; font-weight:bold; font-size:$font_h3$px; }
#status-ver { color:$ACCENT2$; font-weight:bold; font-size:$font_h3$px; padding=0 $space_sm$px; }
QFrame#chip { border-radius:$radius_pill$px; }

/* ===== 设计系统选择器（M4-04 单一事实来源） ===== */
QFrame#card { background:$CARD$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; }
QFrame#ai-group { background:$PANEL$; border:$space_1$px solid $BORDER$; border-radius:$radius_lg$px; }
QWidget#btn-bar, QFrame#btn-bar { background:transparent; spacing:$space_sm$px; }
QGroupBox#primary { border:$space_1$px solid $ACCENT$; border-radius:$radius_lg$px; }
QWidget#secondary { background:$PANEL$; }

QToolTip { background:$PANEL$; color:$TEXT$; border:$space_1$px solid $BORDER$; border-radius:$radius_sm$px; padding:$space_5$px $space_8$px; }

/* ===== 焦点可见样式（M4-14③：键盘导航可辨识） ===== */
QTableWidget:focus { border:$space_1$px solid $ACCENT2$; }
QListWidget:focus { border:$space_1$px solid $ACCENT2$; }
QListWidget#nav:focus { border:none; }
QListWidget#nav::item:focus { background:$CARD$; color:$TEXT$; border-left:$space_3$px solid $ACCENT2$; }
QTabBar::tab:focus { color:$TEXT$; border:$space_1$px solid $ACCENT2$; border-bottom:none; }
QTreeWidget:focus, QTreeView:focus, QListView:focus { border:$space_1$px solid $ACCENT2$; }
"""
'''

def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r'_QSS_TEMPLATE\s*=\s*"""\n.*?\n"""\s*\n',
        re.DOTALL,
    )
    matches = pattern.findall(text)
    if not matches:
        print("❌ 未找到 _QSS_TEMPLATE 块")
        return
    if len(matches) > 1:
        print(f"⚠️  发现 {len(matches)} 个匹配，将替换第一个")
    new_text = pattern.sub(lambda _: NEW_TEMPLATE, text, count=1)
    if new_text == text:
        print("⚠️  文本无变化")
        return
    PATH.write_text(new_text, encoding="utf-8")
    print("✅ _QSS_TEMPLATE 已替换")

if __name__ == "__main__":
    main()
