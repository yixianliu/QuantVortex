# -*- coding: utf-8 -*-
"""第 8 期 GUI offscreen 冒烟：PAGES_OK 7/7 + 截图导出。

运行方式（单条命令）：
    python -m pytest tests/e2e/test_phase8_gui_smoke.py -s -q

输出：
    - 控制台打印 ``PAGES_OK 7/7`` 实跑结果；
    - ``outputs/phase8_ux/page_*.png`` 各页面截图（供文档引用）。
"""
from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication


def _stop_timers(widget) -> None:
    """停掉窗口内的定时器，避免离屏冒烟后仍持续刷新。"""
    for t in widget.findChildren(QTimer):
        try:
            if t.isActive():
                t.stop()
        except Exception:  # noqa: BLE001
            pass


def test_pages_ok_7_and_screenshots(qapp):
    """主窗口 + 7 个页面在 offscreen 下均可构建，并导出截图。"""
    from futures_quant.ui.main_window import MainWindow, NAV

    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    outdir = os.path.join(root, "outputs", "phase8_ux")
    os.makedirs(outdir, exist_ok=True)

    win = MainWindow()
    ok = 0
    failed = []
    try:
        win.resize(1600, 960)
        win.show()
        qapp.processEvents()
        for idx, entry in enumerate(NAV):
            title = entry[0]
            try:
                built = bool(win._show_page(idx))
            except Exception as exc:  # noqa: BLE001
                built = False
                failed.append((idx, title, f"{type(exc).__name__}: {exc}"))
            _stop_timers(win)
            qapp.processEvents()
            if built:
                ok += 1
                try:
                    path = os.path.join(outdir, f"page_{idx}_{_slug(title)}.png")
                    win.grab().save(path)
                except Exception:  # noqa: BLE001
                    pass
            else:
                failed.append((idx, title, "构建返回 False"))
        print(f"\nPAGES_OK {ok}/{len(NAV)}")
        if failed:
            print("FAILED:", failed)
    finally:
        try:
            win.close()
        except Exception:  # noqa: BLE001
            pass
        qapp.processEvents()

    assert ok == len(NAV), f"页面构建退化：{failed}"


def _slug(title: str) -> str:
    """把中文页面标题转成安全的文件名后缀。"""
    mapping = {
        "行情全景": "market", "预测操作": "predict", "回测中心": "backtest",
        "独立回测": "simple_backtest", "实盘监控": "ctp", "日志预警": "log",
        "数据管理": "data",
    }
    return mapping.get(title, str(abs(hash(title)))[:8])
