"""截图脚本：在 offscreen 下渲染新六页 UI，输出深/浅两套 PNG。

用法：
    QT_QPA_PLATFORM=offscreen python examples/capture_ui.py
"""
from __future__ import annotations

import os
import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from futures_quant.ui.main_window import MainWindow

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUT, exist_ok=True)

NAMES = ["market", "indicator", "predict", "panorama", "validate", "log"]


def setup_fonts(app: QApplication) -> str:
    """显式注册 CJK 字体并应用到 app，避免 offscreen 下回退成 tofu。

    返回最终生效的字体族名（用于断言）。
    """
    chosen = ""
    for fp, fam in (
        ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
        ("C:/Windows/Fonts/NotoSansSC-VF.ttf", "Noto Sans SC"),
        ("C:/Windows/Fonts/msyh.ttc", "Microsoft YaHei"),
    ):
        if os.path.exists(fp):
            QFontDatabase.addApplicationFont(fp)
    families = QFontDatabase.families()
    for fam in ("SimHei", "Noto Sans SC", "Microsoft YaHei"):
        if fam in families:
            chosen = fam
            break
    if chosen:
        app.setFont(QFont(chosen, 10))
        print(f"[font] 已加载并应用字体族: {chosen}  (候选 {len(families)} 个)")
    else:
        print("[font] 警告：未找到任何 CJK 字体族，截图可能 tofu")
    return chosen


def wait(ms: int = 200) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)


def main() -> None:
    # 截图模式不污染用户真实的 session_state / user_settings
    os.environ["QUANTVORTEX_NO_PERSIST"] = "1"
    app = QApplication([])
    setup_fonts(app)

    win = MainWindow()
    win.show()
    wait(600)

    # 先触发一次 KP预测，让预测页有完整内容
    try:
        pred_page = win.pages[2]
        pred_page._run()
        # 等待 worker 完成（最多 30s）
        for _ in range(150):
            QApplication.processEvents()
            time.sleep(0.1)
            if pred_page.run_btn.isEnabled():
                break
    except Exception as e:
        print("predict run skipped:", e)

    for theme in ("dark", "light"):
        win.theme = theme
        win._apply_theme()
        wait(300)
        for i, name in enumerate(NAMES):
            win.nav.setCurrentRow(i)
            wait(400)
            path = os.path.join(OUT, f"ui_{name}_{theme}.png")
            pix = win.grab()
            pix.save(path)
            print("saved", path)

    print("DONE")


if __name__ == "__main__":
    main()
