"""分级日志系统。

记录：登录、行情接收、下单、撤单、报错、风控触发。
同时输出到控制台与本地文件，支持级别过滤。
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


def get_logger(
    name: str = "futures_quant",
    level: int = logging.INFO,
    log_dir: str | None = None,
    to_console: bool = True,
) -> logging.Logger:
    """构造一个分级 Logger。

    Args:
        name:       日志器名称。
        level:      最低记录级别（logging.INFO / DEBUG ...）。
        log_dir:    日志目录；为 None 时使用当前目录下的 logs/。
        to_console: 是否同时输出到控制台。
    """
    logger = logging.getLogger(name)
    if logger.handlers:  # 避免重复添加 handler
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_dir is None:
        log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, f"{name}.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        logger.addHandler(console_handler)

    return logger
